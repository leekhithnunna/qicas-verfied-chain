"""Python mirror of the Phase 5 token rules (stdlib only; parity: tests/test_tokens.py).

* credits_for(net_saving_ug)  == CarbonScheduleMarketV3.finalize credit amount (1 credit = 1 g = 10^6 ug, floored;
                                 identical to V1's built-in token)
* metadata_json(...)          == ScheduleCertificate.metadataJson(tokenId), byte-for-byte
* token_uri(...)              == ScheduleCertificate.tokenURI(tokenId)
* NO_CERTIFIED_BOUND_BPS      == the gap V3 stores when no fraud-proof bound was finalised for the epoch
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass

UG_PER_CREDIT = 1_000_000
NO_CERTIFIED_BOUND_BPS = 10_000
DESCRIPTION = "Soulbound attestation of a verified carbon-aware schedule (QICAS Phase 5)"


def credits_for(net_saving_ug: int) -> int:
    return int(net_saving_ug) // UG_PER_CREDIT


@dataclass(frozen=True)
class CertData:
    """Field order = ScheduleCertificate.CertData (also the ABI tuple order)."""
    merkle_root: bytes
    instance_hash: bytes
    baseline_carbon_ug: int
    winner_carbon_ug: int
    net_saving_ug: int
    certified_gap_bps: int
    oracle_request_id: int
    market: str

    def as_tuple(self) -> tuple:
        return (self.merkle_root, self.instance_hash, self.baseline_carbon_ug, self.winner_carbon_ug,
                self.net_saving_ug, self.certified_gap_bps, self.oracle_request_id, self.market)

    @classmethod
    def from_tuple(cls, t) -> "CertData":
        return cls(bytes(t[0]), bytes(t[1]), int(t[2]), int(t[3]), int(t[4]), int(t[5]), int(t[6]), str(t[7]))


def _hex32(b: bytes) -> str:
    return "0x" + bytes(b).rjust(32, b"\0").hex()


def metadata_json(token_id: int, d: CertData) -> str:
    """Exactly the string ScheduleCertificate.metadataJson builds (address and hashes lower-case hex)."""
    return (
        '{"name":"QICAS Schedule Certificate #%d","description":"%s",'
        '"epochId":%d,"market":"%s","merkleRoot":"%s","instanceHash":"%s",'
        '"baselineCarbonUg":%d,"winnerCarbonUg":%d,"netSavingUg":%d,"certifiedGapBps":%d,"oracleRequestId":%d}'
        % (token_id, DESCRIPTION, token_id, d.market.lower(), _hex32(d.merkle_root), _hex32(d.instance_hash),
           d.baseline_carbon_ug, d.winner_carbon_ug, d.net_saving_ug, d.certified_gap_bps, d.oracle_request_id))


def token_uri(token_id: int, d: CertData) -> str:
    return "data:application/json;base64," + base64.b64encode(metadata_json(token_id, d).encode()).decode()


def decode_token_uri(uri: str) -> dict:
    prefix = "data:application/json;base64,"
    if not uri.startswith(prefix):
        raise ValueError("not an on-chain JSON token URI")
    return json.loads(base64.b64decode(uri[len(prefix):]))
