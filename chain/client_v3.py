"""web3.py client for CarbonScheduleMarketV3 (Phase 5: V2 + ERC-20 credits + soulbound ERC-721 certificate).
STATUS: IMPLEMENTED

Same protocol and views as ChainV2 (oracle-fed publish); differences: deployment needs the two token addresses,
`finalize` takes an optional linked PriceMarket (for the certificate's fraud-proof gap) and mints credits +
certificate in the token contracts, `credits()` reads QicasCredit.

deploy_stack() = plan §3 deploy order: (oracle on the caller's side) -> credit + certificate -> V3 -> grant
MINTER_ROLE on both tokens to V3 -> optionally renounce the deployer's admin role (no further minters).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from web3.logs import DISCARD

from chain.client import Chain, TxLog
from chain.client_v2 import ChainV2
from chain.tokens import Tokens
from core.certificate import NO_CERTIFIED_BOUND_BPS, CertData

ARTIFACT_V3 = Path(__file__).parent / "build" / "CarbonScheduleMarketV3.json"


class ChainV3(ChainV2):
    tokens: Tokens | None = None

    @classmethod
    def deploy(cls, base: Chain, tokens: Tokens, min_stake: int = 10**18,   # type: ignore[override]
               deployer: str | None = None) -> "ChainV3":
        art = json.loads(ARTIFACT_V3.read_text())
        w3 = base.w3
        deployer = deployer or base.accounts[0]
        tx = w3.eth.contract(abi=art["abi"], bytecode=art["bytecode"]).constructor(
            min_stake, tokens.credit.contract.address, tokens.cert.contract.address).transact(
            {"from": deployer, "gas": base.tx_gas})
        rcpt = w3.eth.wait_for_transaction_receipt(tx)
        c = cls(w3, w3.eth.contract(address=rcpt.contractAddress, abi=art["abi"]), base.accounts, tx_gas=base.tx_gas)
        c.tokens = tokens
        c.extra_error_abi = tokens.credit.contract.abi + tokens.cert.contract.abi
        c.txs.append(TxLog("deployV3", deployer, rcpt.gasUsed, "ok", rcpt.contractAddress))
        return c

    def finalize(self, epoch_id: int, overhead_ug: int, price_market: str | None = None,  # type: ignore[override]
                 market_id: int = 0, sender: str | None = None) -> dict:
        pm = price_market or "0x" + "00" * 20
        rcpt = self._send("finalize", self.contract.functions.finalize(epoch_id, overhead_ug, pm, market_id),
                          sender or self.accounts[0])
        out = self.summary(epoch_id)
        ev = self.contract.events.CertificateIssued().process_receipt(rcpt, errors=DISCARD)
        out["credits_minted"] = int(ev[0]["args"]["credits"]) if ev else 0
        out["certified_gap_bps"] = int(ev[0]["args"]["certifiedGapBps"]) if ev else None
        out["finalize_gas"] = rcpt.gasUsed
        return out

    def credits(self, addr: str) -> int:
        assert self.tokens is not None
        return self.tokens.balance(addr)

    def certificate(self, epoch_id: int) -> CertData:
        assert self.tokens is not None
        return self.tokens.cert_data(epoch_id)


@dataclass
class V3Stack:
    tokens: Tokens
    market: ChainV3
    deploy_gas: dict[str, int]

    @property
    def txs(self) -> list[TxLog]:
        return self.tokens.txs + self.market.txs


def deploy_stack(base: Chain, min_stake: int = 10**18, renounce_admin: bool = False,
                 deployer: str | None = None) -> V3Stack:
    """credit + certificate -> V3 -> MINTER_ROLE to V3 on both -> (flag) renounce the deployer's admin role."""
    deployer = deployer or base.accounts[0]
    tokens = Tokens.deploy(base, deployer)
    market = ChainV3.deploy(base, tokens, min_stake, deployer)
    tokens.grant_minter(market.contract.address)
    if renounce_admin:
        tokens.renounce_admin()
    gas: dict[str, Any] = {t.action: t.gas for t in tokens.txs + market.txs}
    return V3Stack(tokens, market, gas)


__all__ = ["ChainV3", "V3Stack", "deploy_stack", "NO_CERTIFIED_BOUND_BPS"]
