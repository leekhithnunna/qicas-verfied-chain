"""Phase 5 token flow (not on the default demo path): the case-study scenario on CarbonScheduleMarketV3.

oracle snapshot (5 bonded EIP-712 signers, Phase 4) -> credit + certificate + V3 (MINTER_ROLE to V3, optional
admin renounce) -> publish from the oracle -> the same 7 agents as demo/pipeline.py (4 honest solvers, 3
attackers) commit / reveal -> optional PriceMarket rounds linked to the V3 epoch + bound claim (+ window + finalise
on the in-memory chain only) -> finalize: NET-saving credits (ERC-20) + soulbound certificate (ERC-721).

Works on any Chain (memory, rpc, besu). Used by tests/test_market_v3.py, tests/test_besu.py and
experiments/besu_vs_memory.py. Python parity is checked inline (scores, baseline, Merkle root, credits, metadata).
"""
from __future__ import annotations

import copy
import time
from typing import Any, Callable

from chain.client import Chain, commit_hash, new_salt
from chain.client_v3 import deploy_stack
from chain.oracle_client import OracleClient, advance_time, block_time
from core import certificate as cert_py
from core import merkle
from core.instance import build_instance
from core.market import run_market
from core.scoring import evaluate, round_robin_baseline
from core.solvers import SOLVERS
from oracle.signer import make_signers, zone_id

ZONE_CODES = ["SE-SE3", "IE", "US-MIDA-PJM", "IN-WE"]
N_SIGNERS = 5


def is_memory(chain: Chain) -> bool:
    return getattr(chain.w3.provider, "ethereum_tester", None) is not None


def run_v3(cfg: dict[str, Any], base: Chain, salt_fn: Callable[[], bytes] = new_salt, market_rounds: int = 0,
           finalize_bound: bool | None = None, renounce_admin: bool = True,
           log: Callable[[str], None] = print) -> dict[str, Any]:
    """market_rounds > 0: run that many honest PriceMarket rounds linked to the V3 epoch and claim the best round.
    finalize_bound (default: only on the in-memory chain) waits out the 1-hour challenge window with time travel
    and finalises, so the certificate carries the fraud-proof gap; otherwise the gap is 10000 (no certified
    bound). Returns a dict with the outcome, Python-parity flags and gas per transaction."""
    cfg = copy.deepcopy(cfg)
    t_start = time.perf_counter()
    finalize_bound = is_memory(base) if finalize_bound is None else finalize_bound
    inst = build_instance(cfg, cfg["seed"])
    stake = int(cfg["chain"]["stake_wei"])
    acc = base.accounts
    out: dict[str, Any] = {"instance": {"tasks": inst.n, "edges": len(inst.edges), "m": inst.m,
                                        "hash": "0x" + inst.instance_hash().hex()}}

    # off-chain solvers (same calls as demo/pipeline.py)
    sched: dict[str, list[int]] = {}
    for name, fn in SOLVERS.items():
        sched[name], _ = fn(inst, seed=cfg["seed"], **cfg["solvers"].get(name, {}))
    mk = run_market(inst, **cfg["market"])
    sched["dual-market"] = mk.best_schedule

    # oracle snapshot of the configured ci values (every signer reports the same value -> median = config)
    if is_memory(base):
        from experiments.trust_layer import pin_time        # reproducible report timestamps / gas
        pin_time(base.w3)
    zones = ZONE_CODES[:inst.m] if inst.m <= len(ZONE_CODES) else [f"Z{d}" for d in range(inst.m)]
    oc = OracleClient(base, make_signers(N_SIGNERS))
    rid = oc.publish_snapshot({z: [r.ci_g_per_kwh] * N_SIGNERS for z, r in zip(zones, inst.regions)},
                              block_time(base.w3) // 3600 * 3600)
    log(f"[v3] oracle {oc.address}: snapshot {rid} finalised ({N_SIGNERS} signers x {inst.m} zones)")

    stack = deploy_stack(base, stake, renounce_admin=renounce_admin)
    v3, tk = stack.market, stack.tokens
    log(f"[v3] credit {tk.credit.contract.address}, certificate {tk.cert.contract.address}, "
        f"V3 {v3.contract.address}; admin renounced = {renounce_admin}")
    eid = v3.publish_from_oracle(inst, oc.address, rid, [zone_id(z) for z in zones])
    base_py = evaluate(inst, round_robin_baseline(inst))
    s0 = v3.summary(eid)
    out["baseline_parity"] = s0["baseline_score"] == base_py.score

    agents = [("greedy", acc[1], sched["greedy"]), ("sa", acc[2], sched["sa"]), ("sqa", acc[3], sched["sqa"]),
              ("dual-market", acc[4], sched["dual-market"]), ("attacker: over-capacity", acc[5], [0] * inst.n),
              ("attacker: copycat", acc[6], sched["sqa"]), ("attacker: no-show", acc[7], sched["greedy"])]
    salts = {a[0]: salt_fn() for a in agents}
    salts["attacker: copycat"] = salts["sqa"]
    for label, addr, x in agents:
        override = commit_hash(eid, sched["sqa"], salts["sqa"], acc[3]) if label == "attacker: copycat" else None
        v3.commit(eid, addr, x, salts[label], stake, override_hash=override)
    v3.open_reveal(eid)
    reveals = {}
    for label, addr, x in agents:
        if label == "attacker: no-show":
            reveals[label] = {"status": "not revealed"}
            continue
        r = v3.reveal(eid, addr, x, salts[label], label)
        if r["status"] == "accepted":
            r["python_score_matches"] = evaluate(inst, x).score == r["score"]
        reveals[label] = r
    out["reveals"] = reveals
    log("[v3] reveals: " + ", ".join(f"{k} {v['status']}" for k, v in reveals.items()))

    pm_addr, mid, market = None, 0, None
    if market_rounds > 0:
        from experiments.onchain_market import measure_market
        m = measure_market(v3, eid, inst, int(market_rounds), float(cfg["market"]["step0"]))
        pm, mid, pm_addr = m["pm"], m["market_id"], m["pm"].contract.address
        pm.claim_bound(mid, m["best_lb_round"], acc[1])
        market = {"rounds": int(market_rounds), "best_lb": m["best_lb"], "best_lb_round": m["best_lb_round"],
                  "market_gas_total": m["market_gas_total"], "claim_gas": pm.last_gas(), "bound_finalised": False}
        if finalize_bound:
            from core.market_int import CHALLENGE_WINDOW
            advance_time(base.w3, CHALLENGE_WINDOW + 1)
            pm.finalize_bound(mid, m["best_lb_round"])
            market.update(bound_finalised=True, finalize_bound_gas=pm.last_gas())
        else:
            try:                                            # real-time chain: the window is enforced
                pm.finalize_bound(mid, m["best_lb_round"])
                market["early_finalize"] = "ok (UNEXPECTED)"
            except RuntimeError as exc:
                market["early_finalize"] = f"reverted: {exc}"
        log(f"[v3] PriceMarket {pm_addr}: {market_rounds} rounds, LB {m['best_lb']:,}, bound finalised = "
            f"{market['bound_finalised']}" + (f" (early finalize {market['early_finalize']})"
                                              if "early_finalize" in market else ""))
    out["market"] = market

    ccfg = cfg["chain"]
    gas_so_far = v3.total_gas()
    overhead_ug = int(gas_so_far / 1e6 * ccfg["energy_wh_per_million_gas"] * ccfg["chain_ci_g_per_kwh"] * 1000)
    fin = v3.finalize(eid, overhead_ug, pm_addr, mid)
    winner = next((lbl for lbl, a, _ in agents if a == fin["best_solver"]), "?")
    best = v3.best_schedule(eid)
    cd = v3.certificate(eid)
    expected = cert_py.CertData(bytes.fromhex(fin["merkle_root"][2:]), inst.instance_hash(),
                                fin["baseline_carbon_ug"], fin["best_carbon_ug"], fin["net_saving_ug"],
                                fin["certified_gap_bps"], rid, v3.contract.address)
    uri = tk.token_uri(eid)
    out.update({
        "epoch_id": eid, "winner": winner, "winner_address": fin["best_solver"], "best_score": fin["best_score"],
        "baseline_carbon_ug": fin["baseline_carbon_ug"], "best_carbon_ug": fin["best_carbon_ug"],
        "overhead_ug": overhead_ug, "net_saving_ug": fin["net_saving_ug"], "merkle_root": fin["merkle_root"],
        "credits": tk.balance(fin["best_solver"]), "credits_event": fin["credits_minted"],
        "certified_gap_bps": fin["certified_gap_bps"], "certificate_owner": tk.owner_of(eid),
        "token_uri_json": cert_py.decode_token_uri(uri),
        "parity": {
            "merkle_root": bytes.fromhex(fin["merkle_root"][2:]) == merkle.root(best),
            "credits": tk.balance(fin["best_solver"]) == cert_py.credits_for(fin["net_saving_ug"]),
            "cert_data": cd == expected,
            "token_uri": uri == cert_py.token_uri(eid, expected),
            "baseline": out["baseline_parity"],
            "scores": all(r.get("python_score_matches", True) for r in reveals.values()),
        },
        "slashed_eth": v3.contract.functions.slashedPool().call() / 1e18,
        "oracle_request_id": rid,
        "addresses": {"oracle": oc.address, "credit": tk.credit.contract.address,
                      "certificate": tk.cert.contract.address, "market": v3.contract.address, "price_market": pm_addr},
        "transactions": [t.__dict__ for t in oc.txs + stack.txs],
        "wall_s": time.perf_counter() - t_start,
    })
    log(f"[v3] winner {winner}: net {out['net_saving_ug'] / 1e6:.1f} g -> {out['credits']} QCC credits; "
        f"certificate #{eid} (soulbound) to {fin['best_solver']}; gap {fin['certified_gap_bps']} bps; "
        f"parity {all(out['parity'].values())}")
    out["_stack"], out["_oracle"], out["_instance"] = stack, oc, inst
    return out
