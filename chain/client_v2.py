"""web3.py client for CarbonScheduleMarketV2 (Phase 4: region carbon read from CarbonOracle). STATUS: IMPLEMENTED

Same protocol and views as chain/client.py::Chain (inherited unchanged); only deployment and `publish` differ.
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from web3.logs import DISCARD

from chain.client import Chain, TxLog
from core.instance import Instance

ARTIFACT_V2 = Path(__file__).parent / "build" / "CarbonScheduleMarketV2.json"


class ChainV2(Chain):
    @classmethod
    def deploy(cls, base: Chain, min_stake: int = 10**18, deployer: str | None = None) -> "ChainV2":
        """Deploy V2 on the same chain (w3, accounts) as an existing client."""
        art = json.loads(ARTIFACT_V2.read_text())
        w3 = base.w3
        deployer = deployer or base.accounts[0]
        tx = w3.eth.contract(abi=art["abi"], bytecode=art["bytecode"]).constructor(min_stake).transact(
            {"from": deployer, "gas": base.tx_gas})
        rcpt = w3.eth.wait_for_transaction_receipt(tx)
        c = cls(w3, w3.eth.contract(address=rcpt.contractAddress, abi=art["abi"]), base.accounts, tx_gas=base.tx_gas)
        c.txs.append(TxLog("deployV2", deployer, rcpt.gasUsed, "ok", rcpt.contractAddress))
        return c

    def publish_fn(self, inst: Instance, oracle: str, request_id: int, zone_ids: Sequence[bytes]):
        price_cap = [r.price_uusd_per_kwh for r in inst.regions] + [r.capacity for r in inst.regions]
        task_data = [t.cpu for t in inst.tasks] + [t.energy_wh for t in inst.tasks]
        params = [inst.net_energy_mwh_per_mb, inst.egress_nusd_per_mb, inst.w_carbon, inst.w_cost]
        return self.contract.functions.publish(
            inst.instance_hash(), inst.m, oracle, request_id, list(zone_ids), price_cap, task_data,
            [e.j for e in inst.edges], [e.k for e in inst.edges], [e.volume_mb for e in inst.edges], params)

    def publish_from_oracle(self, inst: Instance, oracle: str, request_id: int, zone_ids: Sequence[bytes]) -> int:
        rcpt = self._send("publish", self.publish_fn(inst, oracle, request_id, zone_ids), self.accounts[0],
                          detail=f"{inst.n} tasks, oracle request {request_id}")
        return int(self.contract.events.Published().process_receipt(rcpt, errors=DISCARD)[0]["args"]["epochId"])

    def publish(self, inst: Instance) -> int:          # V1 signature is not available on V2
        raise NotImplementedError("V2 reads carbon from CarbonOracle: use publish_from_oracle")

    def carbon_source(self, epoch_id: int) -> tuple[str, int, list[int]]:
        o, rid, ci = self.contract.functions.carbonSource(epoch_id).call()
        return o, int(rid), [int(v) for v in ci]
