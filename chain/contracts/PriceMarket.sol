// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice The one view of the case-study contract that PriceMarket reads (upper bound = best revealed score).
interface ICarbonScheduleMarket {
    function summary(uint256 epochId) external view returns (
        uint8 phase, uint256 baselineScore, uint256 baselineCarbon, address bestSolver, uint256 bestScore,
        uint256 bestCarbon, uint256 bestCost, uint256 netSavingUg, bytes32 merkleRoot, uint256 committers);
}

/// @title PriceMarket — on-chain Lagrangian price rounds for a CarbonScheduleMarket epoch (QICAS Phase 3)
/// @notice Capacity constraints are relaxed with a price lambda_d per CPU core in region d. Per round, anyone
///         submits workflow assignments; the contract scores each at the current prices and keeps the MINIMUM
///         value per workflow. closeRound computes the dual value
///             g(lambda) = sum_w min V_w - sum_d lambda_d * cap_d
///         (weak duality: g <= OPT if every minimum is a true minimum), the per-region loads of the kept
///         assignments and the integer subgradient price update. The best g over COMPLETE rounds is the lower
///         bound; the upper bound is the best revealed score of the linked CarbonScheduleMarket epoch.
/// @dev Mirror: core/market_int.py (tests/test_price_market.py enforces parity). The contract never solves.
///      certifiedGapBps is certified ASSUMING each workflow's minimum was submitted by at least one honest party.
///      Phase 4 adds optimistic fraud proofs: claimBound (bonded) -> challenge window in which anyone can post a
///      cheaper assignment for one workflow (claim cancelled, bond split) -> finalizeBound; finalizedGapBps uses
///      only finalised bounds (one honest, live watcher per window suffices). Workflows are contiguous blocks of
///      tasks and edges. Integers only (README section 5).
interface ICarbonOracleView {
    function valueOf(uint256 requestId, bytes32 zone) external view returns (uint256);
}

contract PriceMarket {
    uint256 public constant MAX_WF_TASKS = 32;      // packed assignment: 8 bits per task in one uint256
    uint256 public constant BPS = 10_000;
    uint256 public constant CLAIM_BOND = 1 ether;   // illustrative parameter, not tuned for economic security
    uint256 public constant CHALLENGE_WINDOW = 1 hours;

    struct Market {
        address csm;
        uint256 epochId;
        uint8 m;
        uint256[] ci;           // g/kWh per region
        uint256[] price;        // µUSD/kWh per region
        uint256[] cap;          // cores per region
        uint64[] cpu;           // cores per task
        uint64[] energy;        // Wh per task
        uint32[] edgeJ;
        uint32[] edgeK;
        uint64[] edgeVol;       // MB
        uint256 netEnergy;      // mWh per MB
        uint256 egress;         // nUSD per MB
        uint256 wCarbon;
        uint256 wCost;
        uint32[] wfTaskStart;   // W + 1 entries: tasks of workflow w are [wfTaskStart[w], wfTaskStart[w+1])
        uint32[] wfEdgeStart;   // W + 1 entries: edges of workflow w are [wfEdgeStart[w], wfEdgeStart[w+1])
        uint256[] steps;        // step size per round, fixed at openMarket (one round per entry)
        uint256[] lam;          // current prices (score units per core)
        uint256 round;          // index of the open round; == steps.length when the market is finished
        bool hasLB;
        int256 bestLB;
        uint256 bestLBRound;
        bool hasCertLB;         // Phase 4: best FINALISED (unchallenged) bound
        int256 certLB;
        uint256 certLBRound;
        address oracle;         // Phase 4: optional binding of ci to a CarbonOracle snapshot
        uint256 oracleRequestId;
    }

    struct Round {
        uint256 submitted;      // number of workflows with at least one submission
        bool closed;
        bool complete;          // every workflow submitted at least once
        int256 g;               // dual value (only if complete); lowered by successful challenges
        bytes32 lamHash;        // keccak256(abi.encode(lambda_k)) (complete rounds), for challenges
    }

    struct Claim {
        address claimant;
        uint64 start;
        bool active;
        bool finalized;
        uint256 bond;
    }

    struct WfBest {
        uint256 valuePlus1;     // 0 = nothing submitted yet
        uint256 packedX;        // region of local task i in bits [8i, 8i+8)
    }

    address public immutable owner;
    uint256 public marketCount;
    mapping(uint256 => Market) internal markets;
    mapping(uint256 => mapping(uint256 => Round)) internal rounds;                        // market => k
    mapping(uint256 => mapping(uint256 => mapping(uint256 => WfBest))) internal best;     // market => k => w
    mapping(uint256 => mapping(uint256 => Claim)) internal claims;                        // market => k
    mapping(address => uint256) public withdrawable;
    uint256 public slashedPool;
    bool private locked;

    event BoundClaimed(uint256 indexed marketId, uint256 indexed round, address claimant, int256 dualValue);
    event Challenged(uint256 indexed marketId, uint256 indexed round, uint256 indexed workflow, address challenger,
                     uint256 oldValue, uint256 newValue, int256 newDualValue, bool claimCancelled);
    event BoundFinalized(uint256 indexed marketId, uint256 indexed round, int256 dualValue);
    event OracleBound(uint256 indexed marketId, address oracle, uint256 requestId);

    event MarketOpened(uint256 indexed marketId, address csm, uint256 epochId, uint256 workflows, uint256 rounds);
    event Submitted(uint256 indexed marketId, uint256 indexed round, uint256 indexed workflow, address solver,
                    uint256 value, bool improved);
    event RoundClosed(uint256 indexed marketId, uint256 indexed round, bool complete, int256 dualValue,
                      uint256[] lam, uint256[] loads, uint256[] nextLam);

    error NotOwner();
    error BadInput();
    error UnknownMarket();
    error UnknownEpoch();
    error MarketClosed();
    error NoLowerBound();
    error NoUpperBound();
    error Overflow();
    error RoundNotClaimable();
    error AlreadyClaimed();
    error BadBond();
    error NoClaim();
    error WindowOpen();
    error WindowClosed();
    error NotCheaper();
    error RoundFinalized();
    error OracleMismatch();
    error Reentrancy();

    modifier onlyOwner() { if (msg.sender != owner) revert NotOwner(); _; }
    modifier nonReentrant() { if (locked) revert Reentrancy(); locked = true; _; locked = false; }

    constructor() {
        owner = msg.sender;
    }

    // ------------------------------------------------------------------ open
    /// @notice regionData = [ci..., price..., cap...] (3m), taskData = [cpu..., energy...] (2n),
    ///         params = [netEnergy, egress, wCarbon, wCost] — same layout as CarbonScheduleMarket.publish.
    function openMarket(
        address csm,
        uint256 epochId,
        uint8 m,
        uint256[] calldata regionData,
        uint256[] calldata taskData,
        uint32[] calldata edgeJ,
        uint32[] calldata edgeK,
        uint256[] calldata edgeVol,
        uint256[4] calldata params,
        uint32[] calldata wfTaskStart,
        uint32[] calldata wfEdgeStart,
        uint256[] calldata steps
    ) external onlyOwner returns (uint256 marketId) {
        if (m == 0 || regionData.length != 3 * uint256(m) || taskData.length == 0 || taskData.length % 2 != 0)
            revert BadInput();
        if (edgeJ.length != edgeK.length || edgeJ.length != edgeVol.length || steps.length == 0) revert BadInput();
        (uint8 phase, , , , , , , , , ) = ICarbonScheduleMarket(csm).summary(epochId);
        if (phase == 0) revert UnknownEpoch();
        _checkLayout(taskData.length / 2, edgeJ, edgeK, wfTaskStart, wfEdgeStart);

        marketId = ++marketCount;
        Market storage mk = markets[marketId];
        mk.csm = csm;
        mk.epochId = epochId;
        mk.m = m;
        _storeRegions(mk, m, regionData);
        _storeTasks(mk, taskData);
        _storeEdges(mk, edgeJ, edgeK, edgeVol);
        mk.netEnergy = params[0];
        mk.egress = params[1];
        mk.wCarbon = params[2];
        mk.wCost = params[3];
        mk.wfTaskStart = wfTaskStart;
        mk.wfEdgeStart = wfEdgeStart;
        mk.steps = steps;
        emit MarketOpened(marketId, csm, epochId, wfTaskStart.length - 1, steps.length);
    }

    function _checkLayout(uint256 n, uint32[] calldata edgeJ, uint32[] calldata edgeK,
                          uint32[] calldata ts, uint32[] calldata es) internal pure {
        if (ts.length < 2 || es.length != ts.length || ts[0] != 0 || es[0] != 0) revert BadInput();
        if (ts[ts.length - 1] != n || es[es.length - 1] != edgeJ.length) revert BadInput();
        for (uint256 w = 0; w + 1 < ts.length; w++) {
            uint256 a = ts[w];
            uint256 b = ts[w + 1];
            if (b <= a || b - a > MAX_WF_TASKS || es[w + 1] < es[w]) revert BadInput();
            for (uint256 i = es[w]; i < es[w + 1]; i++) {
                if (edgeJ[i] < a || edgeJ[i] >= b || edgeK[i] < a || edgeK[i] >= b) revert BadInput();
            }
        }
    }

    function _storeRegions(Market storage mk, uint8 m, uint256[] calldata regionData) internal {
        for (uint256 d = 0; d < m; d++) {
            mk.ci.push(regionData[d]);
            mk.price.push(regionData[m + d]);
            mk.cap.push(regionData[2 * uint256(m) + d]);
            mk.lam.push(0);
        }
    }

    function _storeTasks(Market storage mk, uint256[] calldata taskData) internal {
        uint256 n = taskData.length / 2;
        for (uint256 j = 0; j < n; j++) {
            mk.cpu.push(_u64(taskData[j]));
            mk.energy.push(_u64(taskData[n + j]));
        }
    }

    function _storeEdges(Market storage mk, uint32[] calldata edgeJ, uint32[] calldata edgeK,
                         uint256[] calldata edgeVol) internal {
        for (uint256 i = 0; i < edgeJ.length; i++) {
            mk.edgeJ.push(edgeJ[i]);
            mk.edgeK.push(edgeK[i]);
            mk.edgeVol.push(_u64(edgeVol[i]));
        }
    }

    // ------------------------------------------------------------------ submit
    /// @notice Offer an assignment for workflow w in the open round; the minimum value per workflow is kept.
    function submit(uint256 marketId, uint256 w, uint8[] calldata xw) external {
        Market storage mk = _open(marketId);
        if (w + 1 >= mk.wfTaskStart.length) revert BadInput();
        uint256 a = mk.wfTaskStart[w];
        if (xw.length != mk.wfTaskStart[w + 1] - a) revert BadInput();
        uint256[] memory lam = mk.lam;
        (uint256 v, uint256 packed) = _value(mk, w, xw, 0, lam);
        _offer(marketId, mk.round, w, v, packed);
    }

    /// @notice Offer a whole relaxed assignment (all workflows) in one transaction.
    function submitBatch(uint256 marketId, uint8[] calldata x) external {
        Market storage mk = _open(marketId);
        if (x.length != mk.cpu.length) revert BadInput();
        uint256[] memory lam = mk.lam;
        uint256 k = mk.round;
        uint256 nw = mk.wfTaskStart.length - 1;
        for (uint256 w = 0; w < nw; w++) {
            (uint256 v, uint256 packed) = _value(mk, w, x, mk.wfTaskStart[w], lam);
            _offer(marketId, k, w, v, packed);
        }
    }

    function _offer(uint256 marketId, uint256 k, uint256 w, uint256 v, uint256 packed) internal {
        WfBest storage b = best[marketId][k][w];
        bool improved = b.valuePlus1 == 0 || v + 1 < b.valuePlus1;
        if (b.valuePlus1 == 0) rounds[marketId][k].submitted += 1;
        if (improved) {
            b.valuePlus1 = v + 1;
            b.packedX = packed;
        }
        emit Submitted(marketId, k, w, msg.sender, v, improved);
    }

    // ------------------------------------------------------------------ close
    /// @notice Close the open round: dual value (complete rounds only), loads, price update, best lower bound.
    ///         An incomplete round gives no bound and leaves the prices unchanged.
    function closeRound(uint256 marketId) external onlyOwner {
        Market storage mk = _open(marketId);
        uint256 k = mk.round;
        Round storage r = rounds[marketId][k];
        uint256 nw = mk.wfTaskStart.length - 1;
        uint256[] memory loads = new uint256[](mk.m);
        uint256 sumV = 0;
        for (uint256 w = 0; w < nw; w++) {
            WfBest storage b = best[marketId][k][w];
            if (b.valuePlus1 == 0) continue;
            sumV += b.valuePlus1 - 1;
            uint256 packed = b.packedX;
            uint256 a = mk.wfTaskStart[w];
            uint256 e = mk.wfTaskStart[w + 1];
            for (uint256 j = a; j < e; j++) {
                loads[(packed >> (8 * (j - a))) & 0xff] += mk.cpu[j];
            }
        }
        uint256[] memory lam = mk.lam;
        uint256[] memory cap = mk.cap;
        bool complete = r.submitted == nw;
        int256 g = 0;
        uint256[] memory next = lam;
        if (complete) {
            uint256 priced = 0;
            for (uint256 d = 0; d < lam.length; d++) priced += lam[d] * cap[d];
            g = _i(sumV) - _i(priced);
            r.g = g;
            r.lamHash = keccak256(abi.encode(lam));
            if (!mk.hasLB || g > mk.bestLB) {
                mk.hasLB = true;
                mk.bestLB = g;
                mk.bestLBRound = k;
            }
            next = nextPrices(lam, loads, cap, mk.steps[k], mk.m);
            mk.lam = next;
        }
        r.closed = true;
        r.complete = complete;
        mk.round = k + 1;
        emit RoundClosed(marketId, k, complete, g, lam, loads, next);
    }

    // ------------------------------------------------------------------ Phase 4: optimistic fraud proofs
    /// @notice Claim that round k's dual value is a valid lower bound; bonded; opens the challenge window.
    function claimBound(uint256 marketId, uint256 k) external payable {
        _market(marketId);
        Round storage r = rounds[marketId][k];
        if (!r.closed || !r.complete) revert RoundNotClaimable();
        Claim storage c = claims[marketId][k];
        if (c.active || c.finalized) revert AlreadyClaimed();
        if (msg.value != CLAIM_BOND) revert BadBond();
        c.claimant = msg.sender;
        c.start = uint64(block.timestamp);
        c.active = true;
        c.bond = msg.value;
        emit BoundClaimed(marketId, k, msg.sender, r.g);
    }

    /// @notice Fraud proof: an assignment of workflow w cheaper (at lambda_k) than round k's recorded minimum.
    ///         Lowers the recorded minimum and g_k; an active claim is cancelled and its bond split 50 % to the
    ///         challenger, 50 % to the slashed pool. Without a claim it is a plain correction (no reward).
    ///         A challenge that is not strictly cheaper reverts (griefers lose only gas; no challenger bond).
    function challenge(uint256 marketId, uint256 k, uint256 w, uint8[] calldata xw, uint256[] calldata lam)
        external
    {
        Market storage mk = _market(marketId);
        Round storage r = rounds[marketId][k];
        if (!r.closed || !r.complete) revert RoundNotClaimable();
        if (keccak256(abi.encode(lam)) != r.lamHash || w + 1 >= mk.wfTaskStart.length) revert BadInput();
        if (xw.length != mk.wfTaskStart[w + 1] - mk.wfTaskStart[w]) revert BadInput();
        Claim storage c = claims[marketId][k];
        if (c.finalized) revert RoundFinalized();
        if (c.active && block.timestamp >= c.start + CHALLENGE_WINDOW) revert WindowClosed();
        (uint256 v, uint256 packed) = _value(mk, w, xw, 0, lam);
        WfBest storage b = best[marketId][k][w];
        uint256 old = b.valuePlus1 - 1;
        if (v >= old) revert NotCheaper();
        b.valuePlus1 = v + 1;
        b.packedX = packed;
        r.g -= _i(old - v);
        bool cancelled = c.active;
        if (cancelled) {
            uint256 half = c.bond / 2;
            withdrawable[msg.sender] += half;
            slashedPool += c.bond - half;
            c.active = false;
            c.bond = 0;
        }
        emit Challenged(marketId, k, w, msg.sender, old, v, r.g, cancelled);
    }

    /// @notice After an unchallenged window: the claimed g_k becomes a certified (finalised) lower bound.
    function finalizeBound(uint256 marketId, uint256 k) external {
        Market storage mk = _market(marketId);
        Claim storage c = claims[marketId][k];
        if (!c.active) revert NoClaim();
        if (block.timestamp < c.start + CHALLENGE_WINDOW) revert WindowOpen();
        int256 g = rounds[marketId][k].g;
        c.active = false;
        c.finalized = true;
        withdrawable[c.claimant] += c.bond;
        c.bond = 0;
        if (!mk.hasCertLB || g > mk.certLB) {
            mk.hasCertLB = true;
            mk.certLB = g;
            mk.certLBRound = k;
        }
        emit BoundFinalized(marketId, k, g);
    }

    /// @notice Pull payment of refunded bonds and challenge rewards (reentrancy-guarded).
    function withdraw() external nonReentrant {
        uint256 amt = withdrawable[msg.sender];
        withdrawable[msg.sender] = 0;
        (bool ok, ) = payable(msg.sender).call{value: amt}("");
        require(ok, "transfer failed");
    }

    /// @notice (UB - certified LB) / UB in bps using FINALISED bounds only.
    function finalizedGapBps(uint256 marketId) external view returns (uint256) {
        Market storage mk = _market(marketId);
        if (!mk.hasCertLB) revert NoLowerBound();
        (, , , , uint256 ub, , , , , ) = ICarbonScheduleMarket(mk.csm).summary(mk.epochId);
        if (ub == 0 || ub == type(uint256).max) revert NoUpperBound();
        return gapBps(ub, mk.certLB);
    }

    /// @notice Bind the market's region carbon intensities to a finalised CarbonOracle snapshot (checks equality).
    function bindOracle(uint256 marketId, address oracle, uint256 requestId, bytes32[] calldata zoneIds)
        external onlyOwner
    {
        Market storage mk = _market(marketId);
        if (zoneIds.length != mk.m) revert BadInput();
        for (uint256 d = 0; d < zoneIds.length; d++) {
            if (ICarbonOracleView(oracle).valueOf(requestId, zoneIds[d]) != mk.ci[d]) revert OracleMismatch();
        }
        mk.oracle = oracle;
        mk.oracleRequestId = requestId;
        emit OracleBound(marketId, oracle, requestId);
    }

    function certifiedLowerBound(uint256 marketId) external view returns (bool has, int256 lb, uint256 round) {
        Market storage mk = _market(marketId);
        return (mk.hasCertLB, mk.certLB, mk.certLBRound);
    }

    function claimInfo(uint256 marketId, uint256 k)
        external view returns (address claimant, uint64 start, bool active, bool finalized, uint256 bond)
    {
        Claim storage c = claims[marketId][k];
        return (c.claimant, c.start, c.active, c.finalized, c.bond);
    }

    function oracleBinding(uint256 marketId) external view returns (address oracle, uint256 requestId) {
        Market storage mk = _market(marketId);
        return (mk.oracle, mk.oracleRequestId);
    }

    // ------------------------------------------------------------------ parity surface (mirror core/market_int.py)
    /// @notice V_w(x_w, lambda): weighted carbon + cost of workflow w's tasks and internal edges + priced cores.
    function workflowValue(uint256 marketId, uint256 w, uint8[] calldata xw, uint256[] calldata lam)
        external view returns (uint256 v)
    {
        Market storage mk = _market(marketId);
        if (w + 1 >= mk.wfTaskStart.length || lam.length != mk.m) revert BadInput();
        if (xw.length != mk.wfTaskStart[w + 1] - mk.wfTaskStart[w]) revert BadInput();
        (v, ) = _value(mk, w, xw, 0, lam);
    }

    /// @notice Lagrangian value of a whole assignment x: sum_w V_w(x_w, lambda) - sum_d lambda_d * cap_d.
    function dualValueOf(uint256 marketId, uint8[] calldata x, uint256[] calldata lam)
        external view returns (int256)
    {
        Market storage mk = _market(marketId);
        if (x.length != mk.cpu.length || lam.length != mk.m) revert BadInput();
        uint256 s = 0;
        uint256 nw = mk.wfTaskStart.length - 1;
        for (uint256 w = 0; w < nw; w++) {
            (uint256 v, ) = _value(mk, w, x, mk.wfTaskStart[w], lam);
            s += v;
        }
        uint256 priced = 0;
        for (uint256 d = 0; d < lam.length; d++) priced += lam[d] * mk.cap[d];
        return _i(s) - _i(priced);
    }

    /// @notice lambda_d <- max(0, lambda_d + tdiv(step * (load_d - cap_d) * m, sum(cap))).
    ///         Solidity signed division truncates toward zero (Python mirror uses an explicit tdiv).
    function nextPrices(uint256[] memory lam, uint256[] memory loads, uint256[] memory cap, uint256 step,
                        uint256 m) public pure returns (uint256[] memory out)
    {
        if (lam.length != loads.length || lam.length != cap.length) revert BadInput();
        uint256 sumCap = 0;
        for (uint256 d = 0; d < cap.length; d++) sumCap += cap[d];
        if (sumCap == 0) revert BadInput();
        out = new uint256[](lam.length);
        for (uint256 d = 0; d < lam.length; d++) {
            int256 delta = _i(step) * (_i(loads[d]) - _i(cap[d])) * _i(m) / _i(sumCap);
            int256 nl = _i(lam[d]) + delta;
            out[d] = nl > 0 ? uint256(nl) : 0;
        }
    }

    /// @notice Gap in basis points: 10000 if lb <= 0, 0 if lb >= ub, else floor((ub - lb) * 10000 / ub).
    function gapBps(uint256 ub, int256 lb) public pure returns (uint256) {
        if (lb <= 0) return BPS;
        if (uint256(lb) >= ub) return 0;
        return (ub - uint256(lb)) * BPS / ub;
    }

    /// @notice (UB - LB) / UB in bps; UB = best revealed score of the linked epoch, LB = best complete-round g.
    function certifiedGapBps(uint256 marketId) external view returns (uint256) {
        Market storage mk = _market(marketId);
        if (!mk.hasLB) revert NoLowerBound();
        (, , , , uint256 ub, , , , , ) = ICarbonScheduleMarket(mk.csm).summary(mk.epochId);
        if (ub == 0 || ub == type(uint256).max) revert NoUpperBound();
        return gapBps(ub, mk.bestLB);
    }

    // ------------------------------------------------------------------ views
    function prices(uint256 marketId) external view returns (uint256[] memory) {
        return _market(marketId).lam;
    }

    function roundInfo(uint256 marketId, uint256 k)
        external view returns (bool closed, bool complete, uint256 submitted, int256 dualValue)
    {
        _market(marketId);
        Round storage r = rounds[marketId][k];
        return (r.closed, r.complete, r.submitted, r.g);
    }

    function workflowBest(uint256 marketId, uint256 k, uint256 w)
        external view returns (bool submitted, uint256 value, uint256 packedX)
    {
        _market(marketId);
        WfBest storage b = best[marketId][k][w];
        if (b.valuePlus1 == 0) return (false, 0, 0);
        return (true, b.valuePlus1 - 1, b.packedX);
    }

    function bestLowerBound(uint256 marketId) external view returns (bool has, int256 lb, uint256 round) {
        Market storage mk = _market(marketId);
        return (mk.hasLB, mk.bestLB, mk.bestLBRound);
    }

    function marketInfo(uint256 marketId) external view returns (
        address csm, uint256 epochId, uint8 m, uint256 n, uint256 workflows, uint256 totalRounds, uint256 round
    ) {
        Market storage mk = _market(marketId);
        return (mk.csm, mk.epochId, mk.m, mk.cpu.length, mk.wfTaskStart.length - 1, mk.steps.length, mk.round);
    }

    // ------------------------------------------------------------------ internal
    /// @dev Value of workflow w with local task i placed at x[off + i]; also returns the packed assignment.
    function _value(Market storage mk, uint256 w, uint8[] calldata x, uint256 off, uint256[] memory lam)
        internal view returns (uint256 v, uint256 packed)
    {
        uint256 a = mk.wfTaskStart[w];
        (v, packed) = _taskTerms(mk, a, mk.wfTaskStart[w + 1], x, off, lam);
        v += _edgeTerms(mk, w, a, x, off);
    }

    function _taskTerms(Market storage mk, uint256 a, uint256 b, uint8[] calldata x, uint256 off,
                        uint256[] memory lam) internal view returns (uint256 v, uint256 packed)
    {
        uint8 m = mk.m;
        for (uint256 j = a; j < b; j++) {
            uint8 d = x[off + j - a];
            if (d >= m) revert BadInput();
            uint256 en = mk.energy[j];
            v += mk.wCarbon * en * mk.ci[d] * 1000 + mk.wCost * en * mk.price[d] + lam[d] * mk.cpu[j];
            packed |= uint256(d) << (8 * (j - a));
        }
    }

    function _edgeTerms(Market storage mk, uint256 w, uint256 a, uint8[] calldata x, uint256 off)
        internal view returns (uint256 v)
    {
        uint256 eEnd = mk.wfEdgeStart[w + 1];
        for (uint256 i = mk.wfEdgeStart[w]; i < eEnd; i++) {
            uint8 p = x[off + mk.edgeJ[i] - a];
            uint8 q = x[off + mk.edgeK[i] - a];
            if (p != q) {
                uint256 vol = mk.edgeVol[i];
                v += mk.wCarbon * ((vol * mk.netEnergy) * (mk.ci[p] + mk.ci[q]) / 2) + mk.wCost * vol * mk.egress;
            }
        }
    }

    function _market(uint256 marketId) internal view returns (Market storage mk) {
        mk = markets[marketId];
        if (mk.m == 0) revert UnknownMarket();
    }

    function _open(uint256 marketId) internal view returns (Market storage mk) {
        mk = _market(marketId);
        if (mk.round >= mk.steps.length) revert MarketClosed();
    }

    function _i(uint256 a) internal pure returns (int256) {
        if (a > uint256(type(int256).max)) revert Overflow();
        return int256(a);
    }

    function _u64(uint256 a) internal pure returns (uint64) {
        if (a > type(uint64).max) revert BadInput();
        return uint64(a);
    }
}
