"""web3.py wrappers for the Phase 5 OpenZeppelin tokens. STATUS: IMPLEMENTED

QicasCredit (ERC-20, transferable, decimals 0, MINTER_ROLE, retire) and ScheduleCertificate (SOULBOUND ERC-721,
tokenId = epochId, on-chain JSON metadata). Each token gets its own chain.client.Chain view so reverts are
decoded against that token's ABI (OpenZeppelin custom errors such as AccessControlUnauthorizedAccount, Soulbound).
Works on every chain mode (memory, rpc, besu); deployed from the precompiled artifacts in chain/build/.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from web3.logs import DISCARD

from chain.client import Chain, TxLog
from core.certificate import CertData
from core.hashing import keccak256

BUILD = Path(__file__).parent / "build"
ART_CREDIT = BUILD / "QicasCredit.json"
ART_CERT = BUILD / "ScheduleCertificate.json"
MINTER_ROLE = keccak256(b"MINTER_ROLE")
DEFAULT_ADMIN_ROLE = b"\0" * 32

IFACE = {"ERC165": "0x01ffc9a7", "ERC721": "0x80ac58cd", "ERC721Metadata": "0x5b5e139f",
         "AccessControl": "0x7965db0b", "ERC5192": "0xb45a3c0e"}


def deploy_artifact(chain: Chain, artifact: Path, args: list, deployer: str, label: str) -> Chain:
    """Deploy a precompiled artifact on `chain`'s network; returns a Chain view bound to the new contract."""
    art = json.loads(artifact.read_text())
    w3 = chain.w3
    tx = w3.eth.contract(abi=art["abi"], bytecode=art["bytecode"]).constructor(*args).transact(
        {"from": deployer, "gas": chain.tx_gas})
    rcpt = w3.eth.wait_for_transaction_receipt(tx)
    if rcpt.status != 1:
        raise RuntimeError(f"deploy {label} reverted")
    view = Chain(w3, w3.eth.contract(address=rcpt.contractAddress, abi=art["abi"]), chain.accounts, tx_gas=chain.tx_gas)
    view.txs.append(TxLog(label, deployer, rcpt.gasUsed, "ok", rcpt.contractAddress))
    return view


@dataclass
class Tokens:
    credit: Chain
    cert: Chain
    admin: str

    @classmethod
    def deploy(cls, chain: Chain, admin: str | None = None) -> "Tokens":
        admin = admin or chain.accounts[0]
        return cls(deploy_artifact(chain, ART_CREDIT, [admin], admin, "deployCredit"),
                   deploy_artifact(chain, ART_CERT, [admin], admin, "deployCertificate"), admin)

    @property
    def txs(self) -> list[TxLog]:
        return self.credit.txs + self.cert.txs

    # ---------------------------------------------------------------- roles
    def grant_minter(self, minter: str, sender: str | None = None) -> None:
        for t, name in ((self.credit, "credit"), (self.cert, "certificate")):
            t._send(f"grantMinter({name})", t.contract.functions.grantRole(MINTER_ROLE, minter), sender or self.admin)

    def renounce_admin(self, sender: str | None = None) -> None:
        who = sender or self.admin
        for t, name in ((self.credit, "credit"), (self.cert, "certificate")):
            t._send(f"renounceAdmin({name})", t.contract.functions.renounceRole(DEFAULT_ADMIN_ROLE, who), who)

    def is_minter(self, addr: str) -> tuple[bool, bool]:
        return (bool(self.credit.contract.functions.hasRole(MINTER_ROLE, addr).call()),
                bool(self.cert.contract.functions.hasRole(MINTER_ROLE, addr).call()))

    def is_admin(self, addr: str) -> tuple[bool, bool]:
        return (bool(self.credit.contract.functions.hasRole(DEFAULT_ADMIN_ROLE, addr).call()),
                bool(self.cert.contract.functions.hasRole(DEFAULT_ADMIN_ROLE, addr).call()))

    # ---------------------------------------------------------------- ERC-20 credits
    def mint_credit(self, to: str, amount: int, sender: str) -> Any:
        return self.credit._send("mintCredit", self.credit.contract.functions.mint(to, amount), sender)

    def balance(self, addr: str) -> int:
        return int(self.credit.contract.functions.balanceOf(addr).call())

    def total_supply(self) -> int:
        return int(self.credit.contract.functions.totalSupply().call())

    def transfer(self, sender: str, to: str, amount: int) -> Any:
        return self.credit._send("transfer", self.credit.contract.functions.transfer(to, amount), sender)

    def approve_credit(self, sender: str, spender: str, amount: int) -> Any:
        return self.credit._send("approve", self.credit.contract.functions.approve(spender, amount), sender)

    def transfer_from(self, spender: str, owner: str, to: str, amount: int) -> Any:
        return self.credit._send("transferFrom", self.credit.contract.functions.transferFrom(owner, to, amount), spender)

    def retire(self, sender: str, amount: int, beneficiary: str, reason: str) -> dict:
        rcpt = self.credit._send("retire", self.credit.contract.functions.retire(amount, beneficiary, reason), sender)
        ev = self.credit.contract.events.Retired().process_receipt(rcpt, errors=DISCARD)[0]["args"]
        return {"holder": ev["holder"], "beneficiary": ev["beneficiary"], "amount": int(ev["amount"]),
                "reason": ev["reason"], "gas": rcpt.gasUsed}

    # ---------------------------------------------------------------- ERC-721 certificates (soulbound)
    def mint_cert(self, to: str, token_id: int, data: CertData, sender: str) -> Any:
        return self.cert._send("mintCertificate", self.cert.contract.functions.mint(to, token_id, data.as_tuple()), sender)

    def owner_of(self, token_id: int) -> str:
        return self.cert.contract.functions.ownerOf(token_id).call()

    def cert_balance(self, addr: str) -> int:
        return int(self.cert.contract.functions.balanceOf(addr).call())

    def cert_data(self, token_id: int) -> CertData:
        return CertData.from_tuple(self.cert.contract.functions.certData(token_id).call())

    def token_uri(self, token_id: int) -> str:
        return self.cert.contract.functions.tokenURI(token_id).call()

    def metadata_json(self, token_id: int) -> str:
        return self.cert.contract.functions.metadataJson(token_id).call()

    def locked(self, token_id: int) -> bool:
        return bool(self.cert.contract.functions.locked(token_id).call())

    def supports(self, iface: str) -> bool:
        return bool(self.cert.contract.functions.supportsInterface(bytes.fromhex(IFACE.get(iface, iface)[2:])).call())
