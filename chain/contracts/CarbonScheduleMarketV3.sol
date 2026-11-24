// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice The one view of CarbonOracle.sol that V3 reads (finalised lower-median carbon intensity per zone).
interface ICarbonOracle {
    function valueOf(uint256 requestId, bytes32 zone) external view returns (uint256);
}

/// @notice QicasCredit.sol (ERC-20): V3 holds MINTER_ROLE.
interface IQicasCredit {
    function mint(address to, uint256 amount) external;
}

/// @notice ScheduleCertificate.sol (soulbound ERC-721): V3 holds MINTER_ROLE. Struct layout = ABI tuple there.
interface IScheduleCertificate {
    struct CertData {
        bytes32 merkleRoot;
        bytes32 instanceHash;
        uint256 baselineCarbonUg;
        uint256 winnerCarbonUg;
        uint256 netSavingUg;
        uint256 certifiedGapBps;
        uint256 oracleRequestId;
        address market;
    }
    function mint(address to, uint256 epochId, CertData calldata d) external;
}

/// @notice The two PriceMarket.sol views V3 reads for the certificate's gap (Phase 4 fraud-proof bound).
interface IPriceMarketGap {
    function marketInfo(uint256 marketId) external view returns (
        address csm, uint256 epochId, uint8 m, uint256 n, uint256 workflows, uint256 totalRounds, uint256 round);
    function finalizedGapBps(uint256 marketId) external view returns (uint256);
}

/// @title CarbonScheduleMarketV3 — V2 with OpenZeppelin tokens: ERC-20 credits + soulbound certificate (Phase 5)
/// @notice IDENTICAL to CarbonScheduleMarketV2.sol (oracle-fed `publish`, scoring, baseline, commit hash, Merkle
///         root) except: (1) the built-in minimal token is removed; (2) `finalize` mints the NET saving (floored
///         grams, same rule as V1/V2) as QicasCredit to the winner and a soulbound ScheduleCertificate
///         (tokenId = epochId) carrying the Merkle root, instance hash, baseline/winner carbon, net saving,
///         oracle requestId and the certified gap (PriceMarket.finalizedGapBps of a market linked to this epoch,
///         10000 = no certified bound). Token addresses are fixed in the constructor.
///         tests/test_market_v3.py runs the V1 parity tests against V3 and checks the minted tokens.
/// @dev Generated from V2 by exact substitutions; keep V1, V2 and V3 in sync. V1 + V2 artifacts stay unchanged.
/// @notice Flow per epoch: publish instance (contract computes its own baseline) -> solvers commit
///         hash(schedule, salt, sender) with a stake -> owner opens reveal -> solvers reveal ->
///         contract verifies capacity and recomputes carbon/cost/score (mirrors core/scoring.py)
///         -> finalize: best schedule wins, Merkle root stored, NET carbon saving minted as credits +
///         certificate.
contract CarbonScheduleMarketV3 {
    // ------------------------------------------------------------------ types
    enum Phase { None, Commit, Reveal, Finalized }

    struct Epoch {
        Phase phase;
        bytes32 instanceHash;
        uint8 m;
        uint256[] ci;          // g/kWh per region
        uint256[] price;       // µUSD/kWh per region
        uint256[] capacity;    // cores per region
        uint256[] cpu;         // cores per task
        uint256[] energy;      // Wh per task
        uint32[] edgeJ;
        uint32[] edgeK;
        uint256[] edgeVol;     // MB
        uint256 netEnergy;     // mWh per MB
        uint256 egress;        // nUSD per MB
        address oracle;        // V2: carbon source
        uint256 oracleRequestId;
        uint256 wCarbon;
        uint256 wCost;
        uint256 baselineScore;
        uint256 baselineCarbon;
        address bestSolver;
        uint256 bestScore;
        uint256 bestCarbon;
        uint256 bestCost;
        uint8[] bestSchedule;
        bytes32 merkleRoot;
        uint256 netSavingUg;
        address[] committers;
        mapping(address => bytes32) commitment;
        mapping(address => uint256) stake;
        mapping(address => bool) revealed;
    }

    // ------------------------------------------------------------------ storage
    uint256 public constant NO_CERTIFIED_BOUND_BPS = 10_000;
    address public immutable owner;
    uint256 public immutable minStake;
    IQicasCredit public immutable credit;          // V3: ERC-20, 1 unit = 1 gram CO2e of NET certified saving
    IScheduleCertificate public immutable certificate;   // V3: soulbound ERC-721, tokenId = epochId
    uint256 public epochCount;
    mapping(uint256 => Epoch) internal epochs;
    mapping(address => uint256) public withdrawable;   // pull payments (refunds)
    uint256 public slashedPool;
    bool private locked;

    // ------------------------------------------------------------------ events
    event Published(uint256 indexed epochId, bytes32 instanceHash, uint256 baselineScore, uint256 baselineCarbon);
    event Committed(uint256 indexed epochId, address indexed solver);
    event RevealOpened(uint256 indexed epochId);
    event Revealed(uint256 indexed epochId, address indexed solver, uint256 score, uint256 carbonUg, uint256 costNusd, bool isBest);
    event Rejected(uint256 indexed epochId, address indexed solver, string reason);
    event Slashed(uint256 indexed epochId, address indexed solver, uint256 amount, string reason);
    event Finalized(uint256 indexed epochId, address indexed winner, uint256 bestScore, uint256 bestCarbon, uint256 netSavingUg, bytes32 merkleRoot);
    event CertificateIssued(uint256 indexed epochId, address indexed winner, uint256 credits, uint256 certifiedGapBps);

    // ------------------------------------------------------------------ errors
    error NotOwner();
    error WrongPhase();
    error BadInput();
    error StakeTooLow();
    error AlreadyCommitted();
    error NoCommitment();
    error HashMismatch();
    error Reentrancy();
    error InfeasibleBaseline();

    modifier onlyOwner() { if (msg.sender != owner) revert NotOwner(); _; }
    modifier nonReentrant() { if (locked) revert Reentrancy(); locked = true; _; locked = false; }

    constructor(uint256 minStake_, address credit_, address certificate_) {
        if (credit_ == address(0) || certificate_ == address(0)) revert BadInput();
        owner = msg.sender;
        minStake = minStake_;
        credit = IQicasCredit(credit_);
        certificate = IScheduleCertificate(certificate_);
    }

    // ------------------------------------------------------------------ publish
    /// @notice Publish an instance. V2: ci[d] = oracle.valueOf(requestId, zoneIds[d]) (finalised snapshot);
    ///         priceCap = [price..., capacity...] (2*m values).
    ///         taskData = [cpu..., energy...] (2*n values). params = [netEnergy, egress, wCarbon, wCost].
    function publish(
        bytes32 instanceHash,
        uint8 m,
        address oracle,
        uint256 requestId,
        bytes32[] calldata zoneIds,
        uint256[] calldata priceCap,
        uint256[] calldata taskData,
        uint32[] calldata edgeJ,
        uint32[] calldata edgeK,
        uint256[] calldata edgeVol,
        uint256[4] calldata params
    ) external onlyOwner returns (uint256 epochId) {
        if (m == 0 || zoneIds.length != m || priceCap.length != 2 * uint256(m) || taskData.length % 2 != 0)
            revert BadInput();
        if (edgeJ.length != edgeK.length || edgeJ.length != edgeVol.length) revert BadInput();
        uint256 n = taskData.length / 2;
        epochId = ++epochCount;
        Epoch storage e = epochs[epochId];
        e.instanceHash = instanceHash;
        e.m = m;
        e.oracle = oracle;
        e.oracleRequestId = requestId;
        for (uint256 d = 0; d < m; d++) {
            e.ci.push(ICarbonOracle(oracle).valueOf(requestId, zoneIds[d]));   // reverts unless finalised
            e.price.push(priceCap[d]);
            e.capacity.push(priceCap[uint256(m) + d]);
        }
        for (uint256 j = 0; j < n; j++) {
            e.cpu.push(taskData[j]);
            e.energy.push(taskData[n + j]);
        }
        for (uint256 i = 0; i < edgeJ.length; i++) {
            if (edgeJ[i] >= n || edgeK[i] >= n) revert BadInput();
            e.edgeJ.push(edgeJ[i]);
            e.edgeK.push(edgeK[i]);
            e.edgeVol.push(edgeVol[i]);
        }
        e.netEnergy = params[0];
        e.egress = params[1];
        e.wCarbon = params[2];
        e.wCost = params[3];
        e.bestScore = type(uint256).max;

        uint8[] memory base = baselineSchedule(epochId);
        (uint256 s, uint256 c, , bool ok) = evaluate(epochId, base);
        if (!ok) revert InfeasibleBaseline();
        e.baselineScore = s;
        e.baselineCarbon = c;
        e.phase = Phase.Commit;
        emit Published(epochId, instanceHash, s, c);
    }

    // ------------------------------------------------------------------ scoring (mirror of core/scoring.py)
    /// @notice Recompute score, carbon (µg), cost (nUSD) and capacity feasibility of a schedule.
    function evaluate(uint256 epochId, uint8[] memory x)
        public view returns (uint256 score, uint256 carbonUg, uint256 costNusd, bool feasible)
    {
        Epoch storage e = epochs[epochId];
        uint256 n = e.cpu.length;
        uint8 m = e.m;
        if (x.length != n) revert BadInput();
        uint256[] memory loads = new uint256[](m);
        for (uint256 j = 0; j < n; j++) {
            uint8 d = x[j];
            if (d >= m) revert BadInput();
            carbonUg += e.energy[j] * e.ci[d] * 1000;
            costNusd += e.energy[j] * e.price[d];
            loads[d] += e.cpu[j];
        }
        for (uint256 i = 0; i < e.edgeJ.length; i++) {
            uint8 a = x[e.edgeJ[i]];
            uint8 b = x[e.edgeK[i]];
            if (a != b) {
                carbonUg += (e.edgeVol[i] * e.netEnergy) * (e.ci[a] + e.ci[b]) / 2;
                costNusd += e.edgeVol[i] * e.egress;
            }
        }
        feasible = true;
        for (uint256 d = 0; d < m; d++) {
            if (loads[d] > e.capacity[d]) { feasible = false; break; }
        }
        score = e.wCarbon * carbonUg + e.wCost * costNusd;
    }

    /// @notice Round-robin baseline (mirror of core/scoring.py::round_robin_baseline).
    function baselineSchedule(uint256 epochId) public view returns (uint8[] memory x) {
        Epoch storage e = epochs[epochId];
        uint256 n = e.cpu.length;
        uint8 m = e.m;
        uint256[] memory remaining = new uint256[](m);
        for (uint256 d = 0; d < m; d++) remaining[d] = e.capacity[d];
        x = new uint8[](n);
        for (uint256 j = 0; j < n; j++) {
            bool placed = false;
            for (uint256 step = 0; step < m; step++) {
                uint256 d = (j + step) % m;
                if (remaining[d] >= e.cpu[j]) {
                    remaining[d] -= e.cpu[j];
                    x[j] = uint8(d);
                    placed = true;
                    break;
                }
            }
            if (!placed) revert InfeasibleBaseline();
        }
    }

    // ------------------------------------------------------------------ commit / reveal
    /// @notice Must equal demo/chain_client.py::commit_hash byte-for-byte.
    function commitHashOf(uint256 epochId, uint8[] memory x, bytes32 salt, address solver) public pure returns (bytes32) {
        return keccak256(abi.encodePacked(epochId, x, salt, solver));
    }

    function commit(uint256 epochId, bytes32 commitment) external payable {
        Epoch storage e = epochs[epochId];
        if (e.phase != Phase.Commit) revert WrongPhase();
        if (msg.value < minStake) revert StakeTooLow();
        if (e.commitment[msg.sender] != bytes32(0)) revert AlreadyCommitted();
        e.commitment[msg.sender] = commitment;
        e.stake[msg.sender] = msg.value;
        e.committers.push(msg.sender);
        emit Committed(epochId, msg.sender);
    }

    function openReveal(uint256 epochId) external onlyOwner {
        Epoch storage e = epochs[epochId];
        if (e.phase != Phase.Commit) revert WrongPhase();
        e.phase = Phase.Reveal;
        emit RevealOpened(epochId);
    }

    /// @notice Reveal a committed schedule. Hash mismatch reverts (protects against copying, since the
    ///         hash binds msg.sender). Structurally valid but infeasible schedules are rejected and slashed.
    function reveal(uint256 epochId, uint8[] calldata x, bytes32 salt) external {
        Epoch storage e = epochs[epochId];
        if (e.phase != Phase.Reveal) revert WrongPhase();
        bytes32 c = e.commitment[msg.sender];
        if (c == bytes32(0) || e.revealed[msg.sender]) revert NoCommitment();
        if (c != commitHashOf(epochId, x, salt, msg.sender)) revert HashMismatch();
        e.revealed[msg.sender] = true;
        uint256 st = e.stake[msg.sender];
        e.stake[msg.sender] = 0;

        if (x.length != e.cpu.length || !_regionsValid(x, e.m)) {
            _slash(epochId, msg.sender, st, "malformed schedule");
            return;
        }
        (uint256 s, uint256 carbon, uint256 cost, bool ok) = evaluate(epochId, x);
        if (!ok) {
            _slash(epochId, msg.sender, st, "capacity violated");
            return;
        }
        withdrawable[msg.sender] += st;     // honest reveal -> stake refundable
        bool isBest = s < e.bestScore;
        if (isBest) {
            e.bestScore = s;
            e.bestCarbon = carbon;
            e.bestCost = cost;
            e.bestSolver = msg.sender;
            e.bestSchedule = x;
        }
        emit Revealed(epochId, msg.sender, s, carbon, cost, isBest);
    }

    // ------------------------------------------------------------------ finalize
    /// @param overheadUg estimated carbon of this epoch's transactions (computed off-chain from gas used).
    /// @param priceMarket PriceMarket holding a lower bound for THIS epoch (address(0) = none).
    /// @param marketId that market's id; it must be linked to (this contract, epochId).
    function finalize(uint256 epochId, uint256 overheadUg, address priceMarket, uint256 marketId) external onlyOwner {
        Epoch storage e = epochs[epochId];
        if (e.phase != Phase.Reveal) revert WrongPhase();
        e.phase = Phase.Finalized;
        for (uint256 i = 0; i < e.committers.length; i++) {      // slash non-revealers
            address a = e.committers[i];
            if (!e.revealed[a] && e.stake[a] > 0) {
                uint256 st = e.stake[a];
                e.stake[a] = 0;
                _slash(epochId, a, st, "did not reveal");
            }
        }
        if (e.bestSolver != address(0)) {
            e.merkleRoot = merkleRootOf(e.bestSchedule);
            uint256 spent = e.bestCarbon + overheadUg;
            e.netSavingUg = e.baselineCarbon > spent ? e.baselineCarbon - spent : 0;
            uint256 credits = e.netSavingUg / 1_000_000;           // µg -> g
            uint256 gap = _certifiedGap(epochId, priceMarket, marketId);
            if (credits > 0) credit.mint(e.bestSolver, credits);
            certificate.mint(e.bestSolver, epochId, IScheduleCertificate.CertData({
                merkleRoot: e.merkleRoot, instanceHash: e.instanceHash, baselineCarbonUg: e.baselineCarbon,
                winnerCarbonUg: e.bestCarbon, netSavingUg: e.netSavingUg, certifiedGapBps: gap,
                oracleRequestId: e.oracleRequestId, market: address(this)}));
            emit CertificateIssued(epochId, e.bestSolver, credits, gap);
        }
        emit Finalized(epochId, e.bestSolver, e.bestScore, e.bestCarbon, e.netSavingUg, e.merkleRoot);
    }

    /// @dev Fraud-proof-certified gap of a PriceMarket linked to this epoch; 10000 bps when there is none.
    function _certifiedGap(uint256 epochId, address priceMarket, uint256 marketId) internal view returns (uint256) {
        if (priceMarket == address(0)) return NO_CERTIFIED_BOUND_BPS;
        (address csm, uint256 eid, , , , , ) = IPriceMarketGap(priceMarket).marketInfo(marketId);
        if (csm != address(this) || eid != epochId) revert BadInput();
        try IPriceMarketGap(priceMarket).finalizedGapBps(marketId) returns (uint256 g) {
            return g;
        } catch {
            return NO_CERTIFIED_BOUND_BPS;                         // no finalised bound (yet)
        }
    }

    function withdraw() external nonReentrant {
        uint256 amt = withdrawable[msg.sender];
        withdrawable[msg.sender] = 0;                              // effects before interaction
        (bool ok, ) = payable(msg.sender).call{value: amt}("");
        require(ok, "transfer failed");
    }

    // ------------------------------------------------------------------ Merkle (mirror of core/merkle.py)
    function leaf(uint256 j, uint8 d) public pure returns (bytes32) {
        return keccak256(abi.encodePacked(j, d));
    }

    function _pair(bytes32 a, bytes32 b) internal pure returns (bytes32) {
        return a < b ? keccak256(abi.encodePacked(a, b)) : keccak256(abi.encodePacked(b, a));
    }

    function merkleRootOf(uint8[] memory x) public pure returns (bytes32) {
        uint256 len = x.length;
        bytes32[] memory level = new bytes32[](len);
        for (uint256 j = 0; j < len; j++) level[j] = leaf(j, x[j]);
        while (len > 1) {
            uint256 next = (len + 1) / 2;
            for (uint256 i = 0; i < len / 2; i++) level[i] = _pair(level[2 * i], level[2 * i + 1]);
            if (len % 2 == 1) level[next - 1] = level[len - 1];
            len = next;
        }
        return level[0];
    }

    /// @notice Anyone can check one task's placement against the stored root.
    function verifyPlacement(uint256 epochId, uint256 j, uint8 d, bytes32[] calldata proof) external view returns (bool) {
        bytes32 h = leaf(j, d);
        for (uint256 i = 0; i < proof.length; i++) h = _pair(h, proof[i]);
        return h == epochs[epochId].merkleRoot;
    }

    // ------------------------------------------------------------------ views
    function summary(uint256 epochId) external view returns (
        uint8 phase, uint256 baselineScore, uint256 baselineCarbon, address bestSolver,
        uint256 bestScore, uint256 bestCarbon, uint256 bestCost, uint256 netSavingUg, bytes32 merkleRoot, uint256 committers
    ) {
        Epoch storage e = epochs[epochId];
        return (uint8(e.phase), e.baselineScore, e.baselineCarbon, e.bestSolver, e.bestScore, e.bestCarbon,
                e.bestCost, e.netSavingUg, e.merkleRoot, e.committers.length);
    }

    function bestSchedule(uint256 epochId) external view returns (uint8[] memory) {
        return epochs[epochId].bestSchedule;
    }

    /// @notice V2/V3: where this epoch's carbon intensities came from, and the values stored.
    function carbonSource(uint256 epochId) external view returns (address oracle, uint256 requestId, uint256[] memory ci) {
        Epoch storage e = epochs[epochId];
        return (e.oracle, e.oracleRequestId, e.ci);
    }

    // ------------------------------------------------------------------ internal
    function _regionsValid(uint8[] calldata x, uint8 m) internal pure returns (bool) {
        for (uint256 j = 0; j < x.length; j++) if (x[j] >= m) return false;
        return true;
    }

    function _slash(uint256 epochId, address solver, uint256 amount, string memory reason) internal {
        slashedPool += amount;
        emit Rejected(epochId, solver, reason);
        emit Slashed(epochId, solver, amount, reason);
    }
}
