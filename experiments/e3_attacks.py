"""E3 — attack suite (case-study, Phase 3 market, Phase 4 trust layer and Phase 5 token layers EXECUTED).

Phase 3 rows run against PriceMarket on the same chain; one of them is a DOCUMENTED VULNERABILITY (a lone
dishonest submitter inflates the lower bound), recorded as such, never as "defended".

Every case-study attack is actually executed against the unchanged precompiled CarbonScheduleMarket on the
in-memory chain; the observed outcome is recorded next to the expected one. tests/test_attack_suite.py asserts
expected == observed for every executed row and that no NOT RUN / assumption row claims "defended".

The withdraw-reentrancy attacker is a tiny hand-assembled EVM contract (no Solidity compiler is needed):
  * called with calldata = <20-byte target><payload>: forwards payload + msg.value to target (so the contract's
    msg.sender for commit / reveal / withdraw is the attacker contract);
  * receiving ETH with empty calldata (the withdraw payout): once, re-enters target.withdraw() and records
    the re-entry's success flag (slot 2) and the first 32 bytes of its revert data (slot 3).

Outputs: attacks.csv, attacks.md (report table).
"""
from __future__ import annotations

import copy
from collections import defaultdict
from typing import Any

from web3.logs import DISCARD

from chain.client import Chain, commit_hash
from core.hashing import keccak256
from core.instance import generate_instance
from core.merkle import proof as merkle_proof
from core.solvers import SOLVERS
from experiments.eval_common import ASSUMPTION, Context, ExpResult, not_run, phase_present, seeded_salts, write_csv

ATTACK_COLUMNS = ["attack", "layer", "expected", "observed", "attacker_gas", "stake_slashed_eth", "test_name",
                  "status", "note"]
DEFENDED = "defended"
TEST_NAME = "tests/test_attack_suite.py::test_executed_attacks_match_expected"

# Attacks that need phases not built yet (plan §E3); kept as explicit NOT RUN rows.
MISSING = [
    ("inflated market submission", 3), ("incomplete market round", 3), ("market validation reverts", 3),
    ("lying oracle signer (minority)", 4), ("stale oracle report", 4), ("replayed oracle signature", 4),
    ("false lower-bound claim (challenged and slashed)", 4), ("griefing challenge (bond lost)", 4),
    ("unauthorised credit mint", 5), ("double schedule certificate", 5), ("minting after admin renounced", 5),
]
ASSUMPTIONS = [
    ("owner publishes false carbon / price data (trusted oracle in the case study)",
     "the contract verifies schedules GIVEN the published data; it cannot prove the data is true"),
    ("majority oracle collusion", "Phase 4 plan assumes an honest majority of signers"),
    ("no live challenger during the challenge window", "Phase 4 plan assumes >= 1 honest, live challenger"),
    ("data source itself wrong", "no on-chain mechanism can detect a wrong upstream measurement"),
]


# ------------------------------------------------------------------------------- tiny EVM assembler
_OP = {"STOP": 0x00, "SUB": 0x03, "ISZERO": 0x15, "SHL": 0x1B, "SHR": 0x1C, "CALLVALUE": 0x34,
       "CALLDATALOAD": 0x35, "CALLDATASIZE": 0x36, "CALLDATACOPY": 0x37, "CODECOPY": 0x39,
       "RETURNDATASIZE": 0x3D, "RETURNDATACOPY": 0x3E, "MLOAD": 0x51, "MSTORE": 0x52, "SLOAD": 0x54,
       "SSTORE": 0x55, "JUMPI": 0x57, "GAS": 0x5A, "JUMPDEST": 0x5B, "DUP1": 0x80, "DUP6": 0x85,
       "CALL": 0xF1, "RETURN": 0xF3, "REVERT": 0xFD}


def _assemble(prog: list) -> bytes:
    """prog items: opcode name, ("PUSH", nbytes, int | label), or ("LABEL", name). Two passes for labels."""
    labels: dict[str, int] = {}
    for _ in range(2):
        code = bytearray()
        for it in prog:
            if isinstance(it, str):
                code.append(_OP[it])
            elif it[0] == "LABEL":
                labels[it[1]] = len(code)
                code.append(_OP["JUMPDEST"])
            else:
                _, nb, v = it
                v = labels.get(v, 0) if isinstance(v, str) else v
                code.append(0x5F + nb)
                code += int(v).to_bytes(nb, "big")
    return bytes(code)


def reentrancy_attacker_initcode() -> bytes:
    sel = int.from_bytes(keccak256(b"withdraw()")[:4], "big")
    P = lambda nb, v: ("PUSH", nb, v)                      # noqa: E731
    runtime = _assemble([
        "CALLDATASIZE", "ISZERO", P(2, "reenter"), "JUMPI",
        # forward mode: target = calldata[0:20] (kept in slot 0), payload = calldata[20:]
        P(1, 0), "CALLDATALOAD", P(1, 0x60), "SHR", "DUP1", P(1, 0), "SSTORE",
        P(1, 20), "CALLDATASIZE", "SUB", P(1, 20), P(1, 0), "CALLDATACOPY",
        P(1, 0), P(1, 0), P(1, 20), "CALLDATASIZE", "SUB", P(1, 0), "CALLVALUE", "DUP6", "GAS", "CALL",
        P(2, "ok"), "JUMPI",
        "RETURNDATASIZE", P(1, 0), P(1, 0), "RETURNDATACOPY", "RETURNDATASIZE", P(1, 0), "REVERT",
        ("LABEL", "ok"), "STOP",
        # receive mode (withdraw payout): re-enter target.withdraw() once, record the result
        ("LABEL", "reenter"),
        P(1, 1), "SLOAD", P(2, "done"), "JUMPI",
        P(1, 1), P(1, 1), "SSTORE",
        P(4, sel), P(1, 0xE0), "SHL", P(1, 0), "MSTORE",
        P(1, 0), P(1, 0), P(1, 4), P(1, 0), P(1, 0), P(1, 0), "SLOAD", "GAS", "CALL",
        P(1, 2), "SSTORE",
        P(1, 0), P(1, 0), "MSTORE",
        "RETURNDATASIZE", P(1, 0), P(1, 0), "RETURNDATACOPY",
        P(1, 0), "MLOAD", P(1, 3), "SSTORE",
        ("LABEL", "done"), "STOP",
    ])
    n = len(runtime)
    init = bytes([0x60, n, 0x80, 0x60, 11, 0x60, 0x00, 0x39, 0x60, 0x00, 0xF3])   # 11-byte constructor
    assert n < 256 and len(init) == 11
    return init + runtime


# ------------------------------------------------------------------------------- helpers
def _publish_fn(chain: Chain, inst):
    m = inst.m
    region_data = ([r.ci_g_per_kwh for r in inst.regions] + [r.price_uusd_per_kwh for r in inst.regions]
                   + [r.capacity for r in inst.regions])
    task_data = [t.cpu for t in inst.tasks] + [t.energy_wh for t in inst.tasks]
    params = [inst.net_energy_mwh_per_mb, inst.egress_nusd_per_mb, inst.w_carbon, inst.w_cost]
    return chain.contract.functions.publish(inst.instance_hash(), m, region_data, task_data,
                                            [e.j for e in inst.edges], [e.k for e in inst.edges],
                                            [e.volume_mb for e in inst.edges], params)


def _try(fn) -> str:
    """Run a protocol action; return 'ok' or 'reverted: <CustomError>'."""
    try:
        res = fn()
    except RuntimeError as exc:
        return f"reverted: {exc}"
    if isinstance(res, dict) and res.get("status") == "reverted":
        return f"reverted: {res['reason']}"
    return "ok"


# ------------------------------------------------------------------------------- Phase 3 market attacks
VULNERABLE = "documented vulnerability (Phase 4 adds fraud proofs)"
PHASE3_ATTACKS = [   # attack, expected outcome, note, status when observed == expected
    ("inflated market submission", "kept minimum unchanged (improved=False)",
     "honest exact minimum submitted first, attacker then submits the worst assignment of that workflow", DEFENDED),
    ("incomplete market round", "no lower bound; prices unchanged",
     "only workflow 0 submitted before closeRound; an incomplete round never counts toward the bound", DEFENDED),
    ("market validation reverts", "reverted: BadInput, BadInput, BadInput, NotOwner, MarketClosed",
     "region >= m; wrong workflow length; openMarket with an edge crossing a workflow; non-owner closeRound; "
     "closeRound after the last round", DEFENDED),
    ("lone dishonest market submitter (no honest minimum)", "lower bound > a feasible score (false certificate)",
     "nobody submits the true minima, so the kept values are not minima; certified ASSUMING >= 1 honest submitter "
     "per workflow", VULNERABLE),
]


def _market_attacks(chain: Chain, eid: int, inst, feasible_score: int, honest: str, attacker: str,
                    owner: str) -> tuple[dict[str, str], dict[str, int]]:
    """Execute the Phase 3 PriceMarket attacks on the same chain as the case-study epoch `eid`."""
    import itertools

    from chain.price_market import PriceMarketClient
    from core.market_int import Layout, exact_workflow_min, workflow_layout, workflow_value

    pm = PriceMarketClient(chain, deployer=owner)
    lay = workflow_layout(inst)
    zero = [0] * inst.m
    obs: dict[str, str] = {}
    spent: dict[str, int] = defaultdict(int)

    def gas_since(k: int) -> int:
        return sum(t.gas for t in pm.txs[k:] if t.sender == attacker)

    def worst(w: int) -> list[int]:
        return list(max(itertools.product(range(inst.m), repeat=len(lay.tasks(w))),
                        key=lambda c: workflow_value(inst, lay, w, c, zero)))

    a = "inflated market submission"
    mid = pm.open_market(eid, inst, [1], lay)
    xh, vh = exact_workflow_min(inst, lay, 0, zero)
    pm.submit(mid, 0, xh, honest)
    k = len(pm.txs)
    r = pm.submit(mid, 0, worst(0), attacker)
    spent[a] = gas_since(k)
    kept = pm.workflow_best(mid, 0, 0, len(xh))[1]
    obs[a] = ("kept minimum unchanged (improved=False)" if not r["improved"] and kept == vh
              else f"kept {kept} (improved={r['improved']})")

    a = "incomplete market round"
    mid = pm.open_market(eid, inst, [1, 1], lay)
    pm.submit(mid, 0, xh, honest)
    c = pm.close_round(mid)
    has = pm.best_lower_bound(mid)[0]
    obs[a] = ("no lower bound; prices unchanged" if not c["complete"] and not has and c["next_lam"] == c["lam"]
              else f"complete={c['complete']}, has_lower_bound={has}, prices {c['lam']} -> {c['next_lam']}")

    a = "market validation reverts"
    mid = pm.open_market(eid, inst, [1], lay)
    k0, k = len(lay.tasks(0)), len(pm.txs)
    crossing = Layout([0, 1] + lay.task_start[1:], [0, 0] + lay.edge_start[1:])
    names = [_try(t) for t in (
        lambda: pm.submit(mid, 0, [inst.m] + [0] * (k0 - 1), attacker),
        lambda: pm.submit(mid, 0, [0] * (k0 + 1), attacker),
        lambda: pm._send("openMarket", pm.open_market_fn(eid, inst, [1], crossing), owner),
        lambda: pm.close_round(mid, sender=attacker))]
    pm.close_round(mid)
    names.append(_try(lambda: pm.close_round(mid)))
    spent[a] = gas_since(k)
    obs[a] = "reverted: " + ", ".join(n.removeprefix("reverted: ") for n in names)

    a = "lone dishonest market submitter (no honest minimum)"
    mid = pm.open_market(eid, inst, [1], lay)
    k = len(pm.txs)
    for w in range(lay.workflows):
        pm.submit(mid, w, worst(w), attacker)
    spent[a] = gas_since(k)
    pm.close_round(mid)
    lb = pm.best_lower_bound(mid)[1]
    obs[a] = ("lower bound > a feasible score (false certificate)" if lb > feasible_score
              else f"lower bound {lb:,} <= feasible score {feasible_score:,}")
    return obs, spent


# ------------------------------------------------------------------------------- E3
def run_e3(ctx: Context) -> ExpResult:
    a = ctx.profile["attacks"]
    cfg = copy.deepcopy(ctx.base_cfg)
    cfg["workflows"], cfg["seed"] = int(a["workflows"]), int(a["seed"])
    inst = generate_instance(cfg, cfg["seed"])
    honest, _ = SOLVERS["greedy"](inst, seed=cfg["seed"])
    stake = int(cfg["chain"]["stake_wei"])
    chain = Chain.start("memory", min_stake=stake)
    w3, acc, c = chain.w3, chain.accounts, chain.contract
    salt = seeded_salts(cfg["seed"])
    owner, hon, overcap, copycat, noshow, badlen, badreg, reent_eoa, outsider = acc[:9]
    obs: dict[str, str] = {}
    spent: dict[str, int] = defaultdict(int)          # attacker gas per attack (mined transactions only)
    slashed: dict[str, int] = {}

    def track(attack: str, thunk):
        k = len(chain.txs)
        res = thunk()
        spent[attack] += sum(t.gas for t in chain.txs[k:])
        return res

    eid = chain.publish(inst)

    # --- commit phase --------------------------------------------------------------------------------------
    s_hon = salt()
    chain.commit(eid, hon, honest, s_hon, stake)
    for attack, thunk in (
            ("reveal in wrong phase (before openReveal)", lambda: chain.reveal(eid, hon, honest, s_hon)),
            ("stake below minimum", lambda: chain.commit(eid, outsider, honest, salt(), stake // 2)),
            ("double commit", lambda: chain.commit(eid, hon, honest, salt(), stake)),
            ("non-owner openReveal", lambda: chain._send("openReveal", c.functions.openReveal(eid), outsider)),
            ("non-owner publish", lambda: chain._send("publish", _publish_fn(chain, inst), outsider))):
        obs[attack] = track(attack, lambda t=thunk: _try(t))

    bad = {"over-capacity schedule": (overcap, [0] * inst.n),
           "no-show (commit, never reveal)": (noshow, list(honest)),
           "malformed schedule: wrong length": (badlen, list(honest[:-1])),
           "malformed schedule: region index >= m": (badreg, [inst.m] + list(honest[1:]))}
    salts = {label: salt() for label in bad}
    for label, (who, x) in bad.items():
        track(label, lambda w=who, x=x, s=salts[label]: chain.commit(eid, w, x, s, stake))
    track("copycat (copied commitment)", lambda: chain.commit(          # copies the honest commitment hash
        eid, copycat, honest, s_hon, stake, override_hash=commit_hash(eid, honest, s_hon, hon)))

    # reentrancy attacker contract: commits an honest schedule so it ends up with a refundable stake
    rc = w3.eth.wait_for_transaction_receipt(
        w3.eth.send_transaction({"from": reent_eoa, "data": reentrancy_attacker_initcode(), "gas": 1_000_000}))
    proxy = rc.contractAddress

    def via_proxy(fn_name: str, args: list, value: int = 0) -> int:
        data = bytes.fromhex(c.address[2:]) + bytes.fromhex(c.encode_abi(fn_name, args=args)[2:])
        r = w3.eth.wait_for_transaction_receipt(w3.eth.send_transaction(
            {"from": reent_eoa, "to": proxy, "data": data, "value": value, "gas": 5_000_000}))
        if r.status != 1:
            raise RuntimeError(f"attacker contract call {fn_name} failed")
        return int(r.gasUsed)
    s_proxy = salt()
    spent["withdraw reentrancy"] += via_proxy("commit", [eid, commit_hash(eid, honest, s_proxy, proxy)], stake)

    # --- reveal phase --------------------------------------------------------------------------------------
    chain.open_reveal(eid)
    r = chain.reveal(eid, hon, honest, s_hon, "honest")
    assert r["status"] == "accepted", r
    obs["double reveal"] = track("double reveal", lambda: _try(lambda: chain.reveal(eid, hon, honest, s_hon)))
    for label in ("over-capacity schedule", "malformed schedule: wrong length",
                  "malformed schedule: region index >= m"):
        who, x = bad[label]
        pool0 = c.functions.slashedPool().call()
        res = track(label, lambda w=who, x=x, s=salts[label], lb=label: chain.reveal(eid, w, x, s, lb))
        obs[label] = (f"rejected: {res['reason']}; slashed" if res["status"] == "rejected"
                      else f"{res['status']}: {res.get('reason', '')}")
        slashed[label] = c.functions.slashedPool().call() - pool0
    cc = track("copycat (copied commitment)", lambda: chain.reveal(eid, copycat, honest, s_hon, "copycat"))
    obs["copycat (copied commitment)"] = f"reverted: {cc.get('reason')}" if cc["status"] == "reverted" else cc["status"]
    spent["withdraw reentrancy"] += via_proxy("reveal", [eid, list(honest), s_proxy])
    obs["non-owner finalize"] = track("non-owner finalize", lambda: _try(
        lambda: chain._send("finalize", c.functions.finalize(eid, 0), outsider)))

    pool_before = c.functions.slashedPool().call()
    rcpt = chain._send("finalize", c.functions.finalize(eid, 0), owner)
    fin_slash = {ev["args"]["solver"]: int(ev["args"]["amount"])
                 for ev in c.events.Slashed().process_receipt(rcpt, errors=DISCARD)}
    assert c.functions.slashedPool().call() - pool_before == sum(fin_slash.values())
    slashed["copycat (copied commitment)"] = fin_slash.get(copycat, 0)
    slashed["no-show (commit, never reveal)"] = fin_slash.get(noshow, 0)
    obs["copycat (copied commitment)"] += "; slashed at finalize (did not reveal)" if copycat in fin_slash else ""
    obs["no-show (commit, never reveal)"] = ("slashed at finalize (did not reveal)" if noshow in fin_slash
                                            else "not slashed")
    nx = bad["no-show (commit, never reveal)"][1]
    obs["reveal in wrong phase (after finalize)"] = track("reveal in wrong phase (after finalize)", lambda: _try(
        lambda: chain.reveal(eid, noshow, nx, salts["no-show (commit, never reveal)"])))

    best = chain.best_schedule(eid)
    fake = (best[0] + 1) % inst.m
    ok = chain.verify_placement(eid, 0, fake, merkle_proof(best, 0))
    obs["tampered Merkle placement claim"] = f"verifyPlacement = {ok}"

    # --- withdraw reentrancy -------------------------------------------------------------------------------
    bal_c0, bal_p0 = w3.eth.get_balance(c.address), w3.eth.get_balance(proxy)
    spent["withdraw reentrancy"] += via_proxy("withdraw", [])
    attempted = int.from_bytes(w3.eth.get_storage_at(proxy, 1), "big") == 1
    reentry_ok = int.from_bytes(w3.eth.get_storage_at(proxy, 2), "big")
    reentry_err = bytes(w3.eth.get_storage_at(proxy, 3))[:4]
    errname = "Reentrancy" if reentry_err == keccak256(b"Reentrancy()")[:4] else ("0x" + reentry_err.hex())
    paid = w3.eth.get_balance(proxy) - bal_p0
    drained = bal_c0 - w3.eth.get_balance(c.address)
    obs["withdraw reentrancy"] = (
        f"re-entry {'succeeded' if reentry_ok else 'reverted: ' + errname}; "
        + ("paid once" if paid == stake and drained == stake else f"paid {paid / 1e18:g} ETH")
        + ("" if attempted else " (re-entry not attempted)"))

    executed = [   # attack, expected outcome, note
        ("over-capacity schedule", "rejected: capacity violated; slashed", ""),
        ("copycat (copied commitment)", "reverted: HashMismatch; slashed at finalize (did not reveal)",
         "commit hash binds msg.sender"),
        ("no-show (commit, never reveal)", "slashed at finalize (did not reveal)", ""),
        ("malformed schedule: wrong length", "rejected: malformed schedule; slashed", "new in Phase 6"),
        ("malformed schedule: region index >= m", "rejected: malformed schedule; slashed",
         "new in Phase 6; a region >= 256 cannot even be ABI-encoded (uint8)"),
        ("reveal in wrong phase (before openReveal)", "reverted: WrongPhase", ""),
        ("reveal in wrong phase (after finalize)", "reverted: WrongPhase", ""),
        ("non-owner finalize", "reverted: NotOwner", ""),
        ("non-owner openReveal", "reverted: NotOwner", "extra"),
        ("non-owner publish", "reverted: NotOwner", "extra"),
        ("withdraw reentrancy", "re-entry reverted: Reentrancy; paid once",
         "hand-assembled attacker contract; nonReentrant + effects-before-interaction"),
        ("stake below minimum", "reverted: StakeTooLow", "extra"),
        ("double commit", "reverted: AlreadyCommitted", "extra"),
        ("double reveal", "reverted: NoCommitment", "extra"),
        ("tampered Merkle placement claim", "verifyPlacement = False", "view call, no gas"),
    ]
    rows: list[dict[str, Any]] = []
    for attack, expected, note in executed:
        o = obs[attack]
        rows.append({"attack": attack, "layer": "case study", "expected": expected, "observed": o,
                     "attacker_gas": spent.get(attack, 0), "stake_slashed_eth": slashed.get(attack, 0) / 1e18,
                     "test_name": TEST_NAME, "status": DEFENDED if o == expected else "FAILED: expected != observed",
                     "note": (note + "; " if note else "") + "gas 0 = reverted in the dry-run call, nothing mined"
                     if spent.get(attack, 0) == 0 and o.startswith("reverted") else note})
    if phase_present(3):
        from core.scoring import evaluate
        m_obs, m_spent = _market_attacks(chain, eid, inst, evaluate(inst, honest).score, hon, outsider, owner)
        for attack, expected, note, ok_status in PHASE3_ATTACKS:
            o = m_obs[attack]
            rows.append({"attack": attack, "layer": "Phase 3", "expected": expected, "observed": o,
                         "attacker_gas": m_spent.get(attack, 0), "stake_slashed_eth": 0.0, "test_name": TEST_NAME,
                         "status": ok_status if o == expected else "FAILED: expected != observed",
                         "note": note + "; PriceMarket has no stake (nothing to slash)"})
    if phase_present(4):
        from experiments.trust_layer import phase4_attacks
        for r4 in phase4_attacks(chain, eid, inst, outsider, hon):
            rows.append({**r4, "test_name": TEST_NAME})
    if phase_present(5):
        from experiments.phase5_tokens import phase5_attacks
        for r5 in phase5_attacks(chain, inst, outsider, hon):
            rows.append({**r5, "test_name": TEST_NAME})
    nr = []
    for attack, phase in MISSING:
        if phase_present(phase):
            continue
        rows.append({"attack": attack, "layer": f"Phase {phase}", "expected": "", "observed": "",
                     "test_name": "", "status": not_run(phase), "note": "attack surface does not exist yet"})
        nr.append({"experiment": "E3", "item": attack, "status": not_run(phase), "note": "attacks.csv row"})
    for attack, note in ASSUMPTIONS:
        rows.append({"attack": attack, "layer": "assumption", "expected": "not defended (assumption)",
                     "observed": "not executed (assumption, not a defence)", "test_name": "",
                     "status": ASSUMPTION, "note": note})
    write_csv(ctx.out / "attacks.csv", rows, ATTACK_COLUMNS)
    _write_md(ctx, rows)
    summary = {"executed": len(executed), "defended": sum(r["status"] == DEFENDED for r in rows),
               "failed": sum(r["status"].startswith("FAILED") for r in rows),
               "vulnerable": sum(r["status"] == VULNERABLE for r in rows),
               "not_run": len(nr), "assumptions": len(ASSUMPTIONS)}
    return ExpResult(["attacks.csv"], nr, summary)


def _write_md(ctx: Context, rows: list[dict[str, Any]]) -> None:
    lines = ["| Attack | Layer | Expected | Observed | Attacker gas | Slashed (ETH) | Status |",
             "|---|---|---|---|---:|---:|---|"]
    for r in rows:
        lines.append(f"| {r['attack']} | {r['layer']} | {r['expected']} | {r['observed']} | "
                     f"{r.get('attacker_gas', '')} | {r.get('stake_slashed_eth', '')} | {r['status']} |")
    (ctx.out / "attacks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
