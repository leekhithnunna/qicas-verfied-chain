"""web3.py wrapper for CarbonOracle (Phase 4). STATUS: IMPLEMENTED

Deployed on an existing Chain (chain/client.py, unchanged); reuses Chain._send for dry-run + revert decoding.
Also: block time helpers for challenge windows / freshness (in-memory: eth-tester time_travel; rpc:
evm_increaseTime + evm_mine).
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from web3.logs import DISCARD

from chain.client import Chain, TxLog
from oracle.signer import Report, Signer, zone_id

ARTIFACT = Path(__file__).parent / "build" / "CarbonOracle.json"

DEFAULT_QUORUM = 3
DEFAULT_MAX_AGE = 6 * 3600
DEFAULT_BOND = 10**18


def block_time(w3) -> int:
    return int(w3.eth.get_block("latest")["timestamp"])


def advance_time(w3, seconds: int) -> int:
    """Move chain time forward by `seconds` and mine a block; returns the new latest timestamp."""
    target = block_time(w3) + int(seconds)
    tester = getattr(w3.provider, "ethereum_tester", None)
    if tester is not None:
        tester.time_travel(target)
    else:
        w3.provider.make_request("evm_increaseTime", [int(seconds)])
        w3.provider.make_request("evm_mine", [])
    return block_time(w3)


def _deploy(chain: Chain, artifact: Path, args: list, deployer: str):
    art = json.loads(artifact.read_text())
    w3 = chain.w3
    tx = w3.eth.contract(abi=art["abi"], bytecode=art["bytecode"]).constructor(*args).transact(
        {"from": deployer, "gas": chain.tx_gas})
    rcpt = w3.eth.wait_for_transaction_receipt(tx)
    return w3.eth.contract(address=rcpt.contractAddress, abi=art["abi"]), rcpt.gasUsed


class OracleClient:
    def __init__(self, chain: Chain, signers: Sequence[Signer], quorum: int = DEFAULT_QUORUM,
                 max_age: int = DEFAULT_MAX_AGE, min_bond: int = DEFAULT_BOND, deployer: str | None = None,
                 bond: bool = True) -> None:
        self.w3 = chain.w3
        self.owner = deployer or chain.accounts[0]
        self.signers = list(signers)
        self.contract, gas = _deploy(chain, ARTIFACT, [[s.address for s in signers], quorum, max_age, min_bond],
                                     self.owner)
        self._c = Chain(chain.w3, self.contract, chain.accounts, tx_gas=chain.tx_gas)
        self._c.txs.append(TxLog("deployOracle", self.owner, gas, "ok", self.contract.address))
        self.chain_id = int(self.w3.eth.chain_id)
        self.min_bond = min_bond
        if bond and min_bond > 0:
            for s in self.signers:
                self.deposit_bond(s.address, min_bond)

    @property
    def address(self) -> str:
        return self.contract.address

    @property
    def txs(self) -> list[TxLog]:
        return self._c.txs

    def _send(self, action: str, fn, sender: str, value: int = 0, detail: str = ""):
        return self._c._send(action, fn, sender, value=value, detail=detail)

    # ---------------------------------------------------------------- protocol
    def deposit_bond(self, signer: str, amount: int, sender: str | None = None) -> None:
        self._send("depositBond", self.contract.functions.depositBond(signer), sender or self.owner, value=amount)

    def request(self, zones: Sequence[bytes], hour_start: int, deadline: int, sender: str | None = None) -> int:
        rcpt = self._send("requestSnapshot", self.contract.functions.requestSnapshot(list(zones), hour_start, deadline),
                          sender or self.owner)
        return int(self.contract.events.SnapshotRequested().process_receipt(rcpt, errors=DISCARD)[0]["args"]["requestId"])

    def sign(self, signer: Signer, report: Report) -> bytes:
        return signer.sign(report, self.chain_id, self.address)

    def submit_fn(self, request_id: int, reports: Sequence[Report], sigs: Sequence[bytes]):
        return self.contract.functions.submitReports(request_id, [r.as_tuple() for r in reports], list(sigs))

    def submit(self, request_id: int, reports: Sequence[Report], sigs: Sequence[bytes], sender: str | None = None):
        return self._send("submitReports", self.submit_fn(request_id, reports, sigs), sender or self.owner,
                          detail=f"{len(reports)} reports")

    def finalize(self, request_id: int, sender: str | None = None):
        return self._send("finalizeSnapshot", self.contract.functions.finalizeSnapshot(request_id),
                          sender or self.owner)

    def prove_equivocation(self, r1: Report, s1: bytes, r2: Report, s2: bytes, sender: str):
        return self._send("proveEquivocation", self.contract.functions.proveEquivocation(
            r1.as_tuple(), s1, r2.as_tuple(), s2), sender)

    def publish_snapshot(self, values: dict[str, Sequence[int]], hour_start: int, source_hash: bytes = b"\0" * 32,
                         deadline_s: int = 3600) -> int:
        """Convenience honest flow: request, every signer i reports values[zone][i], finalize. Returns requestId."""
        now = block_time(self.w3)
        zones = [zone_id(z) for z in values]
        rid = self.request(zones, hour_start, now + deadline_s)
        reports, sigs = [], []
        issued = block_time(self.w3)
        for code, vals in values.items():
            for s, v in zip(self.signers, vals):
                r = Report(rid, zone_id(code), hour_start, int(v), source_hash, issued)
                reports.append(r)
                sigs.append(self.sign(s, r))
        self.submit(rid, reports, sigs)
        self.finalize(rid)
        return rid

    # ---------------------------------------------------------------- views / parity surface
    def value_of(self, request_id: int, zone: bytes) -> int:
        return int(self.contract.functions.valueOf(request_id, zone).call())

    def zone_info(self, request_id: int, zone: bytes) -> dict[str, Any]:
        listed, k, med, spr = self.contract.functions.zoneInfo(request_id, zone).call()
        return {"listed": bool(listed), "reports": int(k), "median": int(med), "spread": int(spr)}

    def report_digest(self, report: Report) -> bytes:
        return bytes(self.contract.functions.reportDigest(report.as_tuple()).call())

    def recover_signer(self, digest: bytes, sig: bytes) -> str:
        return self.contract.functions.recoverSigner(digest, sig).call()

    def median_lower(self, values: Sequence[int]) -> int:
        return int(self.contract.functions.medianLower([int(v) for v in values]).call())

    def bond_of(self, signer: str) -> int:
        return int(self.contract.functions.bondOf(signer).call())

    def is_signer(self, signer: str) -> bool:
        return bool(self.contract.functions.isSigner(signer).call())
