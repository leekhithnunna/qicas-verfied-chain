// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC721} from "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {Base64} from "@openzeppelin/contracts/utils/Base64.sol";
import {Strings} from "@openzeppelin/contracts/utils/Strings.sol";

/// @title ScheduleCertificate — SOULBOUND ERC-721 schedule certificate (QICAS Phase 5)
/// @notice One certificate per finalised epoch (tokenId = epochId), minted to the winning solver by the market
///         contract (MINTER_ROLE). It is an ATTESTATION bound to the winner's address, not a tradeable asset:
///         every transfer and approval path reverts with `Soulbound()` (ERC-5192 `locked` = true).
///         The certified data is stored on-chain and `tokenURI` returns it as data:application/json;base64
///         (no IPFS). Python mirror of the JSON: core/certificate.py (tests/test_tokens.py checks parity).
/// @dev OpenZeppelin 5.4.0, vendored in chain/vendor/openzeppelin. After the admin renounces
///      DEFAULT_ADMIN_ROLE, no new minter can ever be added.
contract ScheduleCertificate is ERC721, AccessControl {
    using Strings for uint256;
    using Strings for address;

    bytes32 public constant MINTER_ROLE = keccak256("MINTER_ROLE");

    struct CertData {
        bytes32 merkleRoot;        // Merkle root of the winning schedule (core/merkle.py)
        bytes32 instanceHash;      // core/instance.py::Instance.instance_hash
        uint256 baselineCarbonUg;  // contract-computed round-robin baseline carbon
        uint256 winnerCarbonUg;    // winning schedule's carbon
        uint256 netSavingUg;       // baseline - winner - chain overhead (floored at 0)
        uint256 certifiedGapBps;   // PriceMarket.finalizedGapBps (fraud-proof bound); 10000 = no certified bound
        uint256 oracleRequestId;   // CarbonOracle snapshot the carbon intensities came from
        address market;            // the market contract that verified the schedule
    }

    mapping(uint256 => CertData) private _data;

    error Soulbound();
    error CertificateExists(uint256 tokenId);

    /// @dev ERC-5192 (minimal soulbound interface).
    event Locked(uint256 tokenId);

    constructor(address admin) ERC721("QICAS Schedule Certificate", "QSC") {
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
    }

    function mint(address to, uint256 epochId, CertData calldata d) external onlyRole(MINTER_ROLE) {
        if (_ownerOf(epochId) != address(0)) revert CertificateExists(epochId);
        _data[epochId] = d;
        _mint(to, epochId);
        emit Locked(epochId);
    }

    function certData(uint256 tokenId) external view returns (CertData memory) {
        _requireOwned(tokenId);
        return _data[tokenId];
    }

    /// @notice ERC-5192: every certificate is permanently locked to its owner.
    function locked(uint256 tokenId) external view returns (bool) {
        _requireOwned(tokenId);
        return true;
    }

    // ------------------------------------------------------------------ soulbound: no transfers, no approvals
    function approve(address, uint256) public pure override {
        revert Soulbound();
    }

    function setApprovalForAll(address, bool) public pure override {
        revert Soulbound();
    }

    /// @dev Every transfer path (transferFrom, safeTransferFrom) goes through _update; only minting
    ///      (from == address(0)) is allowed. There is no burn function.
    function _update(address to, uint256 tokenId, address auth) internal override returns (address) {
        if (_ownerOf(tokenId) != address(0)) revert Soulbound();
        return super._update(to, tokenId, auth);
    }

    // ------------------------------------------------------------------ metadata (mirror: core/certificate.py)
    function tokenURI(uint256 tokenId) public view override returns (string memory) {
        _requireOwned(tokenId);
        return string.concat("data:application/json;base64,", Base64.encode(bytes(metadataJson(tokenId))));
    }

    function metadataJson(uint256 tokenId) public view returns (string memory) {
        _requireOwned(tokenId);
        CertData storage d = _data[tokenId];
        string memory head = string.concat(
            '{"name":"QICAS Schedule Certificate #', tokenId.toString(),
            '","description":"Soulbound attestation of a verified carbon-aware schedule (QICAS Phase 5)",',
            '"epochId":', tokenId.toString(),
            ',"market":"', d.market.toHexString(),
            '","merkleRoot":"', uint256(d.merkleRoot).toHexString(32),
            '","instanceHash":"', uint256(d.instanceHash).toHexString(32), '",');
        string memory tail = string.concat(
            '"baselineCarbonUg":', d.baselineCarbonUg.toString(),
            ',"winnerCarbonUg":', d.winnerCarbonUg.toString(),
            ',"netSavingUg":', d.netSavingUg.toString(),
            ',"certifiedGapBps":', d.certifiedGapBps.toString(),
            ',"oracleRequestId":', d.oracleRequestId.toString(), "}");
        return string.concat(head, tail);
    }

    function supportsInterface(bytes4 interfaceId) public view override(ERC721, AccessControl) returns (bool) {
        return interfaceId == 0xb45a3c0e || super.supportsInterface(interfaceId);   // ERC-5192
    }
}
