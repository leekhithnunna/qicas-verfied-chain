"""Phase 5 attack rows for E3 (executed, in-memory): unauthorised mint, double certificate, minting after the
admin renounced, certificate transfer (soulbound). Runs a small V3 epoch on the caller's chain:
oracle snapshot -> credit + certificate + V3 (MINTER_ROLE to V3) -> publish -> one honest commit/reveal -> finalize.
"""
from __future__ import annotations

from typing import Any

from chain.client import Chain
from chain.client_v3 import deploy_stack
from core.instance import Instance
from core.scoring import round_robin_baseline

DEFENDED = "defended"
UNAUTH = "AccessControlUnauthorizedAccount"

PHASE5_ATTACKS = [   # attack, expected, note
    ("unauthorised credit mint", f"reverted: {UNAUTH}, {UNAUTH}",
     "outsider calls QicasCredit.mint and ScheduleCertificate.mint directly; only V3 holds MINTER_ROLE"),
    ("double schedule certificate", "reverted: WrongPhase, CertificateExists",
     "owner re-finalizes the finalised epoch; then a second minter (granted by the admin for the test) mints the "
     "same tokenId = epochId"),
    ("minting after admin renounced", f"reverted: {UNAUTH}, {UNAUTH}",
     "after renounceRole(DEFAULT_ADMIN_ROLE) the ex-admin tries to grant itself MINTER_ROLE, then to mint; V3 keeps "
     "its role (protocol minting continues)"),
    ("certificate transfer / approval (soulbound)", "reverted: Soulbound, Soulbound",
     "winner tries transferFrom and approve on its certificate"),
]


def _try(thunk) -> str:
    try:
        thunk()
    except RuntimeError as exc:
        return f"reverted: {exc}"
    return "ok"


def phase5_attacks(chain: Chain, inst: Instance, outsider: str, honest: str) -> list[dict[str, Any]]:
    from experiments.trust_layer import oracle_snapshot
    snap = oracle_snapshot(chain, inst)
    stack = deploy_stack(chain, int(1e18))
    v3, tk = stack.market, stack.tokens
    admin = chain.accounts[0]
    eid = v3.publish_from_oracle(inst, snap["oc"].address, snap["rid"], snap["zones"])
    x = round_robin_baseline(inst)
    salt = b"\x05" * 32
    v3.commit(eid, honest, x, salt, int(1e18))
    v3.open_reveal(eid)
    v3.reveal(eid, honest, x, salt, "honest")
    v3.finalize(eid, 0)
    obs: dict[str, str] = {}

    def joined(*names: str) -> str:
        return "reverted: " + ", ".join(n.removeprefix("reverted: ") for n in names)

    obs["unauthorised credit mint"] = joined(
        _try(lambda: tk.mint_credit(outsider, 10**6, outsider)),
        _try(lambda: tk.mint_cert(outsider, eid + 1, v3.certificate(eid), outsider)))

    refin = _try(lambda: v3.finalize(eid, 0))
    tk.cert._send("grantRole", tk.cert.contract.functions.grantRole(
        tk.cert.contract.functions.MINTER_ROLE().call(), admin), admin)
    again = _try(lambda: tk.mint_cert(outsider, eid, v3.certificate(eid), admin))
    tk.cert._send("revokeRole", tk.cert.contract.functions.revokeRole(
        tk.cert.contract.functions.MINTER_ROLE().call(), admin), admin)
    obs["double schedule certificate"] = joined(refin, again)

    tk.renounce_admin()
    obs["minting after admin renounced"] = joined(
        _try(lambda: tk.grant_minter(admin, sender=admin)), _try(lambda: tk.mint_credit(admin, 1, admin)))

    f = tk.cert.contract.functions
    obs["certificate transfer / approval (soulbound)"] = joined(
        _try(lambda: tk.cert._send("transferFrom", f.transferFrom(honest, outsider, eid), honest)),
        _try(lambda: tk.cert._send("approve", f.approve(outsider, eid), honest)))

    rows = []
    for attack, expected, note in PHASE5_ATTACKS:
        o = obs[attack]
        rows.append({"attack": attack, "layer": "Phase 5", "expected": expected, "observed": o, "attacker_gas": 0,
                     "stake_slashed_eth": 0.0, "status": DEFENDED if o == expected else "FAILED: expected != observed",
                     "note": note + "; gas 0 = reverted in the dry-run call, nothing mined; tokens have no stake"})
    return rows
