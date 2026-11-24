// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title CarbonOracle — multi-signer EIP-712 carbon-intensity snapshots, lower median per zone (QICAS Phase 4)
/// @notice Flow: owner requests a snapshot (zones, hour, deadline) -> registered, bonded signers sign
///         CarbonReport structs off-chain (EIP-712) -> anyone relays them with submitReports -> finalizeSnapshot
///         takes the LOWER MEDIAN per zone (needs >= quorum reports) -> consumers read valueOf(requestId, zone).
///         A signer who signs two different reports for the same (request, zone) can be slashed by anyone
///         (proveEquivocation). Trust-minimised, not trustless: assumes an honest majority of signers and does
///         not remove trust in the upstream data source.
/// @dev Single file, no dependencies. Python mirror: oracle/signer.py (EIP-712 digest, signatures) and
///      core/oracle_math.py (median); parity enforced by tests/test_trust_layer.py.
contract CarbonOracle {
    struct CarbonReport {
        uint256 requestId;
        bytes32 zone;           // keccak256 of the zone code, e.g. keccak256("SE-SE3")
        uint64 hourStart;       // unix seconds, UTC hour the value refers to
        uint32 ciGPerKwh;       // carbon intensity, g CO2e / kWh
        bytes32 sourceHash;     // SHA-256 of the raw file the signer read
        uint64 issuedAt;        // unix seconds when signed
    }

    struct Request {
        uint64 hourStart;
        uint64 deadline;
        bool finalized;
        bytes32[] zones;
    }

    struct Zone {
        bool listed;
        uint32 median;
        uint32 spread;
        uint32[] values;
        mapping(address => bool) reported;
    }

    bytes32 public constant DOMAIN_TYPEHASH =
        keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)");
    bytes32 public constant REPORT_TYPEHASH = keccak256(
        "CarbonReport(uint256 requestId,bytes32 zone,uint64 hourStart,uint32 ciGPerKwh,bytes32 sourceHash,uint64 issuedAt)");
    uint256 internal constant HALF_N = 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0;

    address public immutable owner;
    uint256 public immutable quorum;
    uint256 public immutable maxAge;
    uint256 public immutable minBond;
    bytes32 public immutable domainSeparator;

    mapping(address => bool) public isSigner;
    mapping(address => uint256) public bondOf;
    uint256 public signerCount;
    uint256 public slashedPool;
    uint256 public requestCount;
    mapping(uint256 => Request) internal requests;
    mapping(uint256 => mapping(bytes32 => Zone)) internal zones;

    event SnapshotRequested(uint256 indexed requestId, uint64 hourStart, uint64 deadline, bytes32[] zones);
    event ReportAccepted(uint256 indexed requestId, bytes32 indexed zone, address indexed signer, uint32 ciGPerKwh);
    event SnapshotFinalized(uint256 indexed requestId);
    event BondDeposited(address indexed signer, uint256 amount);
    event Equivocation(address indexed signer, uint256 slashed);

    error NotOwner();
    error BadInput();
    error BadSignature();
    error UnknownSigner();
    error NotBonded();
    error WrongRequest();
    error WrongHour();
    error UnknownZone();
    error Stale();
    error FutureReport();
    error Late();
    error DuplicateReport();
    error NoQuorum();
    error NotFinalized();
    error AlreadyFinalized();
    error NotEquivocation();

    modifier onlyOwner() { if (msg.sender != owner) revert NotOwner(); _; }

    constructor(address[] memory signers, uint256 quorum_, uint256 maxAge_, uint256 minBond_) {
        if (quorum_ == 0 || quorum_ > signers.length) revert BadInput();
        owner = msg.sender;
        quorum = quorum_;
        maxAge = maxAge_;
        minBond = minBond_;
        for (uint256 i = 0; i < signers.length; i++) {
            if (signers[i] == address(0) || isSigner[signers[i]]) revert BadInput();
            isSigner[signers[i]] = true;
        }
        signerCount = signers.length;
        domainSeparator = keccak256(abi.encode(DOMAIN_TYPEHASH, keccak256(bytes("QICAS Carbon Oracle")),
                                               keccak256(bytes("1")), block.chainid, address(this)));
    }

    // ------------------------------------------------------------------ bonds
    /// @notice Anyone may bond a registered signer (e.g. the operator funds it); the bond is slashable.
    function depositBond(address signer) external payable {
        if (!isSigner[signer] || msg.value == 0) revert BadInput();
        bondOf[signer] += msg.value;
        emit BondDeposited(signer, msg.value);
    }

    // ------------------------------------------------------------------ request / report / finalize
    function requestSnapshot(bytes32[] calldata zoneIds, uint64 hourStart, uint64 deadline)
        external onlyOwner returns (uint256 requestId)
    {
        if (zoneIds.length == 0 || deadline < block.timestamp) revert BadInput();
        requestId = ++requestCount;
        Request storage q = requests[requestId];
        q.hourStart = hourStart;
        q.deadline = deadline;
        for (uint256 i = 0; i < zoneIds.length; i++) {
            Zone storage z = zones[requestId][zoneIds[i]];
            if (z.listed) revert BadInput();
            z.listed = true;
            q.zones.push(zoneIds[i]);
        }
        emit SnapshotRequested(requestId, hourStart, deadline, zoneIds);
    }

    /// @notice Relay signed reports for `requestId`. Checks, in order: signature format and recovery,
    ///         registered and bonded signer, request / hour / zone match, freshness, deadline, one report per
    ///         (signer, request, zone).
    function submitReports(uint256 requestId, CarbonReport[] calldata reports, bytes[] calldata sigs) external {
        if (reports.length != sigs.length || reports.length == 0) revert BadInput();
        Request storage q = requests[requestId];
        if (q.deadline == 0) revert WrongRequest();
        for (uint256 i = 0; i < reports.length; i++) {
            CarbonReport calldata r = reports[i];
            address signer = recoverSigner(reportDigest(r), sigs[i]);
            if (!isSigner[signer]) revert UnknownSigner();
            if (bondOf[signer] < minBond) revert NotBonded();
            if (r.requestId != requestId) revert WrongRequest();
            if (r.hourStart != q.hourStart) revert WrongHour();
            Zone storage z = zones[requestId][r.zone];
            if (!z.listed) revert UnknownZone();
            if (r.issuedAt > block.timestamp) revert FutureReport();
            if (block.timestamp - r.issuedAt > maxAge) revert Stale();
            if (block.timestamp > q.deadline || q.finalized) revert Late();
            if (z.reported[signer]) revert DuplicateReport();
            z.reported[signer] = true;
            z.values.push(r.ciGPerKwh);
            emit ReportAccepted(requestId, r.zone, signer, r.ciGPerKwh);
        }
    }

    /// @notice Anyone; every zone needs >= quorum reports. Stores the lower median and the spread per zone.
    function finalizeSnapshot(uint256 requestId) external {
        Request storage q = requests[requestId];
        if (q.deadline == 0) revert WrongRequest();
        if (q.finalized) revert AlreadyFinalized();
        for (uint256 i = 0; i < q.zones.length; i++) {
            Zone storage z = zones[requestId][q.zones[i]];
            if (z.values.length < quorum) revert NoQuorum();
            uint32[] memory s = _sorted(z.values);
            z.median = s[(s.length - 1) / 2];
            z.spread = s[s.length - 1] - s[0];
        }
        q.finalized = true;
        emit SnapshotFinalized(requestId);
    }

    /// @notice Two different signed reports by the same signer for the same (request, zone): bond slashed,
    ///         signer removed. The reports need not have been submitted.
    function proveEquivocation(CarbonReport calldata r1, bytes calldata sig1, CarbonReport calldata r2,
                               bytes calldata sig2) external {
        bytes32 d1 = reportDigest(r1);
        bytes32 d2 = reportDigest(r2);
        address s1 = recoverSigner(d1, sig1);
        if (d1 == d2 || s1 != recoverSigner(d2, sig2) || !isSigner[s1]) revert NotEquivocation();
        if (r1.requestId != r2.requestId || r1.zone != r2.zone) revert NotEquivocation();
        uint256 b = bondOf[s1];
        bondOf[s1] = 0;
        isSigner[s1] = false;
        signerCount -= 1;
        slashedPool += b;
        emit Equivocation(s1, b);
    }

    // ------------------------------------------------------------------ consumer views
    function valueOf(uint256 requestId, bytes32 zone) external view returns (uint256) {
        Request storage q = requests[requestId];
        if (!q.finalized) revert NotFinalized();
        Zone storage z = zones[requestId][zone];
        if (!z.listed) revert UnknownZone();
        return z.median;
    }

    function zoneInfo(uint256 requestId, bytes32 zone)
        external view returns (bool listed, uint256 reports, uint256 median, uint256 spread)
    {
        Zone storage z = zones[requestId][zone];
        return (z.listed, z.values.length, z.median, z.spread);
    }

    function requestInfo(uint256 requestId)
        external view returns (uint64 hourStart, uint64 deadline, bool finalized, bytes32[] memory zoneIds)
    {
        Request storage q = requests[requestId];
        return (q.hourStart, q.deadline, q.finalized, q.zones);
    }

    // ------------------------------------------------------------------ parity surface
    function reportDigest(CarbonReport calldata r) public view returns (bytes32) {
        bytes32 structHash = keccak256(abi.encode(REPORT_TYPEHASH, r.requestId, r.zone, r.hourStart, r.ciGPerKwh,
                                                  r.sourceHash, r.issuedAt));
        return keccak256(abi.encodePacked("\x19\x01", domainSeparator, structHash));
    }

    /// @notice 65-byte (r, s, v) signature, v in {27, 28}, low-s only (no malleable copies), non-zero signer.
    function recoverSigner(bytes32 digest, bytes calldata sig) public pure returns (address signer) {
        if (sig.length != 65) revert BadSignature();
        bytes32 r = bytes32(sig[0:32]);
        bytes32 s = bytes32(sig[32:64]);
        uint8 v = uint8(sig[64]);
        if ((v != 27 && v != 28) || uint256(s) > HALF_N) revert BadSignature();
        signer = ecrecover(digest, v, r, s);
        if (signer == address(0)) revert BadSignature();
    }

    /// @notice Lower median sorted[(k - 1) / 2] (k >= 1).
    function medianLower(uint32[] memory values) public pure returns (uint32) {
        if (values.length == 0) revert BadInput();
        uint32[] memory s = _sorted(values);
        return s[(s.length - 1) / 2];
    }

    function _sorted(uint32[] memory a) internal pure returns (uint32[] memory s) {
        s = new uint32[](a.length);
        for (uint256 i = 0; i < a.length; i++) {
            uint32 v = a[i];
            uint256 j = i;
            while (j > 0 && s[j - 1] > v) {
                s[j] = s[j - 1];
                j--;
            }
            s[j] = v;
        }
    }
}
