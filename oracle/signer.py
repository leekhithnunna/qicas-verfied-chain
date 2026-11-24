"""EIP-712 CarbonReport signers for CarbonOracle.sol (Phase 4). STATUS: IMPLEMENTED

Deterministic TEST keys: private key i = keccak256("qicas-signer-<i>"). Never use them on a real network.
The typed-data layout must match CarbonOracle.REPORT_TYPEHASH / domainSeparator exactly (parity-tested).
"""
from __future__ import annotations

from dataclasses import dataclass

from eth_account import Account
from eth_account.messages import _hash_eip191_message, encode_typed_data

from core.hashing import keccak256

DOMAIN_NAME = "QICAS Carbon Oracle"
DOMAIN_VERSION = "1"
REPORT_TYPE = [
    {"name": "requestId", "type": "uint256"},
    {"name": "zone", "type": "bytes32"},
    {"name": "hourStart", "type": "uint64"},
    {"name": "ciGPerKwh", "type": "uint32"},
    {"name": "sourceHash", "type": "bytes32"},
    {"name": "issuedAt", "type": "uint64"},
]
REPORT_TYPE_STRING = ("CarbonReport(uint256 requestId,bytes32 zone,uint64 hourStart,uint32 ciGPerKwh,"
                      "bytes32 sourceHash,uint64 issuedAt)")
SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


def zone_id(code: str) -> bytes:
    """bytes32 zone identifier = keccak256 of the zone code (e.g. 'SE-SE3')."""
    return keccak256(code.encode())


@dataclass(frozen=True)
class Report:
    request_id: int
    zone: bytes
    hour_start: int
    ci_g_per_kwh: int
    source_hash: bytes
    issued_at: int

    def as_tuple(self) -> tuple:
        return (self.request_id, self.zone, self.hour_start, self.ci_g_per_kwh, self.source_hash, self.issued_at)

    def message(self) -> dict:
        return {"requestId": self.request_id, "zone": self.zone, "hourStart": self.hour_start,
                "ciGPerKwh": self.ci_g_per_kwh, "sourceHash": self.source_hash, "issuedAt": self.issued_at}


def typed_data(report: Report, chain_id: int, contract: str) -> dict:
    return {
        "types": {
            "EIP712Domain": [{"name": "name", "type": "string"}, {"name": "version", "type": "string"},
                             {"name": "chainId", "type": "uint256"}, {"name": "verifyingContract", "type": "address"}],
            "CarbonReport": REPORT_TYPE,
        },
        "primaryType": "CarbonReport",
        "domain": {"name": DOMAIN_NAME, "version": DOMAIN_VERSION, "chainId": chain_id, "verifyingContract": contract},
        "message": report.message(),
    }


def digest(report: Report, chain_id: int, contract: str) -> bytes:
    return bytes(_hash_eip191_message(encode_typed_data(full_message=typed_data(report, chain_id, contract))))


def recover(report: Report, signature: bytes, chain_id: int, contract: str) -> str:
    return Account.recover_message(encode_typed_data(full_message=typed_data(report, chain_id, contract)),
                                   signature=signature)


def malleate(sig: bytes) -> bytes:
    """High-s twin of a valid signature (same signer under plain ecrecover; rejected by the contract)."""
    r, s, v = sig[:32], int.from_bytes(sig[32:64], "big"), sig[64]
    return r + (SECP256K1_N - s).to_bytes(32, "big") + bytes([55 - v])     # 27 <-> 28


class Signer:
    def __init__(self, index: int) -> None:
        self.index = index
        self.key = keccak256(f"qicas-signer-{index}".encode())
        self.account = Account.from_key(self.key)
        self.address = self.account.address

    def sign(self, report: Report, chain_id: int, contract: str) -> bytes:
        sm = encode_typed_data(full_message=typed_data(report, chain_id, contract))
        return bytes(self.account.sign_message(sm).signature)


def make_signers(n: int = 5) -> list[Signer]:
    return [Signer(i) for i in range(n)]
