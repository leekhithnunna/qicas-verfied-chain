"""web3.py wrapper for PriceMarket (Phase 3 on-chain price rounds). STATUS: IMPLEMENTED

Deployed next to an existing CarbonScheduleMarket on the same chain (chain/client.py, unchanged). Reuses
Chain._send for dry-run + revert decoding; every transaction is logged with its gas in `txs`.
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from web3.logs import DISCARD

from chain.client import Chain, TxLog
from core.instance import Instance
from core.market_int import Layout, workflow_layout

ARTIFACT = Path(__file__).parent / "build" / "PriceMarket.json"


def unpack(packed: int, k: int) -> list[int]:
    return [(packed >> (8 * i)) & 0xFF for i in range(k)]


class PriceMarketClient:
    def __init__(self, chain: Chain, deployer: str | None = None) -> None:
        art = json.loads(ARTIFACT.read_text())
        w3 = chain.w3
        deployer = deployer or chain.accounts[0]
        tx = w3.eth.contract(abi=art["abi"], bytecode=art["bytecode"]).constructor().transact(
            {"from": deployer, "gas": chain.tx_gas})
        rcpt = w3.eth.wait_for_transaction_receipt(tx)
        self.contract = w3.eth.contract(address=rcpt.contractAddress, abi=art["abi"])
        self.csm = chain
        self._c = Chain(w3, self.contract, chain.accounts, tx_gas=chain.tx_gas)   # _send / error decoding
        self._c.txs.append(TxLog("deployPriceMarket", deployer, rcpt.gasUsed, "ok", rcpt.contractAddress))
        self.owner = deployer

    @property
    def txs(self) -> list[TxLog]:
        return self._c.txs

    @property
    def accounts(self) -> list[str]:
        return self._c.accounts

    def last_gas(self) -> int:
        return self._c.txs[-1].gas

    def _send(self, action: str, fn, sender: str, detail: str = "", value: int = 0):
        return self._c._send(action, fn, sender, value=value, detail=detail)

    # ---------------------------------------------------------------- Phase 4: fraud proofs
    def claim_bound(self, market_id: int, k: int, sender: str, bond: int | None = None):
        b = int(self.contract.functions.CLAIM_BOND().call()) if bond is None else bond
        return self._send("claimBound", self.contract.functions.claimBound(market_id, k), sender, value=b,
                          detail=f"round {k}")

    def challenge(self, market_id: int, k: int, w: int, xw: Sequence[int], lam: Sequence[int], sender: str) -> dict:
        rcpt = self._send("challenge", self.contract.functions.challenge(
            market_id, k, w, [int(d) for d in xw], [int(v) for v in lam]), sender, detail=f"round {k} workflow {w}")
        a = self.contract.events.Challenged().process_receipt(rcpt, errors=DISCARD)[0]["args"]
        return {"old": int(a["oldValue"]), "new": int(a["newValue"]), "dual_value": int(a["newDualValue"]),
                "cancelled": bool(a["claimCancelled"]), "gas": rcpt.gasUsed}

    def finalize_bound(self, market_id: int, k: int, sender: str | None = None):
        return self._send("finalizeBound", self.contract.functions.finalizeBound(market_id, k),
                          sender or self.owner, detail=f"round {k}")

    def withdraw(self, sender: str):
        return self._send("withdraw", self.contract.functions.withdraw(), sender)

    def bind_oracle(self, market_id: int, oracle: str, request_id: int, zone_ids: Sequence[bytes]):
        return self._send("bindOracle", self.contract.functions.bindOracle(market_id, oracle, request_id,
                                                                           list(zone_ids)), self.owner)

    def finalized_gap_bps(self, market_id: int) -> int:
        return int(self.contract.functions.finalizedGapBps(market_id).call())

    def certified_lower_bound(self, market_id: int) -> tuple[bool, int, int]:
        h, lb, k = self.contract.functions.certifiedLowerBound(market_id).call()
        return bool(h), int(lb), int(k)

    def claim_info(self, market_id: int, k: int) -> dict[str, Any]:
        c, s, a, f, b = self.contract.functions.claimInfo(market_id, k).call()
        return {"claimant": c, "start": int(s), "active": bool(a), "finalized": bool(f), "bond": int(b)}

    def withdrawable(self, addr: str) -> int:
        return int(self.contract.functions.withdrawable(addr).call())

    def slashed_pool(self) -> int:
        return int(self.contract.functions.slashedPool().call())

    # ---------------------------------------------------------------- protocol
    def open_market_fn(self, epoch_id: int, inst: Instance, steps: Sequence[int], lay: Layout | None = None,
                       csm_address: str | None = None):
        lay = lay or workflow_layout(inst)
        region_data = ([r.ci_g_per_kwh for r in inst.regions] + [r.price_uusd_per_kwh for r in inst.regions]
                       + [r.capacity for r in inst.regions])
        task_data = [t.cpu for t in inst.tasks] + [t.energy_wh for t in inst.tasks]
        params = [inst.net_energy_mwh_per_mb, inst.egress_nusd_per_mb, inst.w_carbon, inst.w_cost]
        return self.contract.functions.openMarket(
            csm_address or self.csm.contract.address, epoch_id, inst.m, region_data, task_data,
            [e.j for e in inst.edges], [e.k for e in inst.edges], [e.volume_mb for e in inst.edges], params,
            list(lay.task_start), list(lay.edge_start), [int(s) for s in steps])

    def open_market(self, epoch_id: int, inst: Instance, steps: Sequence[int], lay: Layout | None = None) -> int:
        rcpt = self._send("openMarket", self.open_market_fn(epoch_id, inst, steps, lay), self.owner,
                          detail=f"{inst.n} tasks, {len(steps)} rounds")
        ev = self.contract.events.MarketOpened().process_receipt(rcpt, errors=DISCARD)[0]["args"]
        return int(ev["marketId"])

    def submit(self, market_id: int, w: int, xw: Sequence[int], sender: str) -> dict[str, Any]:
        rcpt = self._send("submit", self.contract.functions.submit(market_id, w, [int(d) for d in xw]), sender,
                          detail=f"workflow {w} ({len(xw)} tasks)")
        ev = self.contract.events.Submitted().process_receipt(rcpt, errors=DISCARD)[0]["args"]
        return {"value": int(ev["value"]), "improved": bool(ev["improved"]), "gas": rcpt.gasUsed}

    def submit_batch(self, market_id: int, x: Sequence[int], sender: str) -> dict[str, Any]:
        rcpt = self._send("submitBatch", self.contract.functions.submitBatch(market_id, [int(d) for d in x]),
                          sender, detail=f"{len(x)} tasks")
        evs = self.contract.events.Submitted().process_receipt(rcpt, errors=DISCARD)
        return {"values": [int(e["args"]["value"]) for e in evs],
                "improved": [bool(e["args"]["improved"]) for e in evs], "gas": rcpt.gasUsed}

    def close_round(self, market_id: int, sender: str | None = None) -> dict[str, Any]:
        rcpt = self._send("closeRound", self.contract.functions.closeRound(market_id), sender or self.owner)
        a = self.contract.events.RoundClosed().process_receipt(rcpt, errors=DISCARD)[0]["args"]
        return {"round": int(a["round"]), "complete": bool(a["complete"]), "dual_value": int(a["dualValue"]),
                "lam": [int(v) for v in a["lam"]], "loads": [int(v) for v in a["loads"]],
                "next_lam": [int(v) for v in a["nextLam"]], "gas": rcpt.gasUsed}

    # ---------------------------------------------------------------- views (parity surface)
    def workflow_value(self, market_id: int, w: int, xw: Sequence[int], lam: Sequence[int]) -> int:
        return int(self.contract.functions.workflowValue(market_id, w, [int(d) for d in xw],
                                                         [int(v) for v in lam]).call())

    def dual_value_of(self, market_id: int, x: Sequence[int], lam: Sequence[int]) -> int:
        return int(self.contract.functions.dualValueOf(market_id, [int(d) for d in x], [int(v) for v in lam]).call())

    def next_prices(self, lam, loads, cap, step: int, m: int) -> list[int]:
        return [int(v) for v in self.contract.functions.nextPrices(
            [int(v) for v in lam], [int(v) for v in loads], [int(v) for v in cap], int(step), int(m)).call()]

    def gap_bps(self, ub: int, lb: int) -> int:
        return int(self.contract.functions.gapBps(int(ub), int(lb)).call())

    def certified_gap_bps(self, market_id: int) -> int:
        return int(self.contract.functions.certifiedGapBps(market_id).call())

    def prices(self, market_id: int) -> list[int]:
        return [int(v) for v in self.contract.functions.prices(market_id).call()]

    def round_info(self, market_id: int, k: int) -> dict[str, Any]:
        c, comp, sub, g = self.contract.functions.roundInfo(market_id, k).call()
        return {"closed": bool(c), "complete": bool(comp), "submitted": int(sub), "dual_value": int(g)}

    def workflow_best(self, market_id: int, k: int, w: int, tasks: int) -> tuple[bool, int, list[int]]:
        s, v, p = self.contract.functions.workflowBest(market_id, k, w).call()
        return bool(s), int(v), unpack(int(p), tasks)

    def best_lower_bound(self, market_id: int) -> tuple[bool, int, int]:
        h, lb, k = self.contract.functions.bestLowerBound(market_id).call()
        return bool(h), int(lb), int(k)
