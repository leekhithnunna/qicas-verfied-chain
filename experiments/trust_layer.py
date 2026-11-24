"""Phase 4 experiment: trust layer (EIP-712 carbon oracle + optimistic fraud proofs) with measured gas and the
Phase 4 attack table.

Flow (seed 7, in-memory chain): case-study pipeline (V1, unchanged) -> PriceMarket, 25 honest rounds (Phase 3)
-> CarbonOracle with N = 5 bonded signers: requestSnapshot, one submitReports with N x m signed reports,
finalizeSnapshot (lower median) -> bindOracle (market ci == snapshot) -> claimBound on the best round, window,
finalizeBound -> finalizedGapBps. Separately: a dishonest 1-round market whose false claim is challenged
(challenge gas by workflow size), and every Phase 4 attack executed (attacks.csv).

Outputs: results/trust/{gas.csv, attacks.csv, summary.json}. Honest claims: trust-minimised, not trustless
(honest signer majority; >= 1 honest, live watcher per challenge window); parameters are illustrative.

  python -m experiments.trust_layer
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

import yaml

from chain.client import Chain
from chain.oracle_client import OracleClient, advance_time, block_time
from chain.price_market import PriceMarketClient
from core.instance import Instance
from core.market_int import CHALLENGE_WINDOW, MarketState, exact_workflow_min, workflow_layout
from core.oracle_math import median_lower
from oracle.signer import Report, make_signers, zone_id

N_SIGNERS = 5
ZONE_CODES = ["SE-SE3", "IE", "US-MIDA-PJM", "IN-WE"]      # Phase 1 zones; one per region (m = 4)
DEFENDED = "defended"
ATTACK_COLUMNS = ["attack", "layer", "expected", "observed", "attacker_gas", "stake_slashed_eth", "status", "note"]
GAS_COLUMNS = ["function", "detail", "calls", "gas_mean", "gas_total", "note"]


def zone_codes(inst: Instance) -> list[str]:
    return ZONE_CODES[:inst.m] if inst.m <= len(ZONE_CODES) else [f"Z{d}" for d in range(inst.m)]


# ------------------------------------------------------------------------------- measurement building blocks
PINNED_TIME = 2_000_000_000     # 2033-05-18; signed reports contain timestamps, so pin them for reproducible gas


def pin_time(w3) -> None:
    """Move the in-memory chain to PINNED_TIME (if it is still earlier), so report timestamps, signatures and
    therefore calldata gas are identical across runs. No-op on rpc chains or once past that time."""
    if getattr(w3.provider, "ethereum_tester", None) is not None and block_time(w3) < PINNED_TIME:
        advance_time(w3, PINNED_TIME - block_time(w3))


def oracle_snapshot(chain: Chain, inst: Instance, n_signers: int = N_SIGNERS) -> dict[str, Any]:
    """Deploy + bond an oracle, then one honest snapshot of the instance's ci values (every signer reports the
    configured value). Gas per step from receipts."""
    pin_time(chain.w3)
    oc = OracleClient(chain, make_signers(n_signers))
    k0 = len(oc.txs)
    hour = block_time(chain.w3) // 3600 * 3600
    rid = oc.publish_snapshot({z: [r.ci_g_per_kwh] * n_signers for z, r in zip(zone_codes(inst), inst.regions)}, hour)
    g = {t.action: t.gas for t in oc.txs[k0:]}
    one_off = sum(t.gas for t in oc.txs[:k0])
    return {"oc": oc, "rid": rid, "zones": [zone_id(z) for z in zone_codes(inst)], "request": g["requestSnapshot"],
            "submit": g["submitReports"], "finalize": g["finalizeSnapshot"], "reports": n_signers * inst.m,
            "one_off_deploy_and_bonds": one_off,
            "per_epoch": g["requestSnapshot"] + g["submitReports"] + g["finalizeSnapshot"]}


def certify_bound(pm: PriceMarketClient, mid: int, k: int, claimant: str) -> dict[str, int]:
    """Honest claim on round k, wait out the window, finalise."""
    pm.claim_bound(mid, k, claimant)
    claim = pm.last_gas()
    advance_time(pm.contract.w3, CHALLENGE_WINDOW + 1)
    pm.finalize_bound(mid, k)
    return {"claim": claim, "finalize": pm.last_gas()}


def false_claim_challenge(pm: PriceMarketClient, epoch_id: int, inst: Instance, attacker: str,
                          challenger: str, workflows: list[int] | None = None) -> list[dict[str, Any]]:
    """1-round market with a dishonest (argmax) submitter; the attacker claims; the challenger corrects each
    listed workflow (re-claim before each). Returns gas + outcome per challenge."""
    lay = workflow_layout(inst)
    lam = [0] * inst.m
    mid = pm.open_market(epoch_id, inst, [1], lay)
    x = []
    for w in range(lay.workflows):
        x += exact_workflow_min(inst, lay, w, lam, worst=True)[0]
    pm.submit_batch(mid, x, attacker)
    pm.close_round(mid)
    out = []
    for w in (workflows if workflows is not None else range(lay.workflows)):
        pm.claim_bound(mid, 0, attacker)
        xw, _ = exact_workflow_min(inst, lay, w, lam)
        r = pm.challenge(mid, 0, w, xw, lam, challenger)
        out.append({"workflow": w, "tasks": len(xw), **r})
    return out


def _try(thunk) -> str:
    try:
        thunk()
    except RuntimeError as exc:
        return f"reverted: {exc}"
    return "ok"


def phase4_attacks(chain: Chain, epoch_id: int, inst: Instance, attacker: str, challenger: str) -> list[dict[str, Any]]:
    """Execute the Phase 4 rows of the E3 attack table. Status 'defended' only when observed == expected."""
    rows: list[dict[str, Any]] = []
    oc = OracleClient(chain, make_signers(N_SIGNERS))
    signers, w3 = oc.signers, chain.w3
    z = zone_id(zone_codes(inst)[0])

    def new_request():
        now = block_time(w3)
        hour = now // 3600 * 3600
        return oc.request([z], hour, now + 3600), hour

    def add(attack, expected, observed, gas=0, slashed=0.0, note=""):
        rows.append({"attack": attack, "layer": "Phase 4", "expected": expected, "observed": observed,
                     "attacker_gas": gas, "stake_slashed_eth": slashed,
                     "status": DEFENDED if observed == expected else "FAILED: expected != observed", "note": note})

    # lying minority: 2 of 5 signers report extreme values
    rid, hour = new_request()
    vals = [0, 300, 310, 320, 2**32 - 1]
    reps = [Report(rid, z, hour, v, b"\0" * 32, block_time(w3)) for v in vals]
    oc.submit(rid, reps, [oc.sign(s, r) for s, r in zip(signers, reps)])
    oc.finalize(rid)
    med = oc.value_of(rid, z)
    add("lying oracle signer (minority)", "median = honest median (310)",
        f"median = honest median ({med})" if med == median_lower([300, 310, 320]) else f"median = {med}",
        note="2 of 5 signers report 0 and 2^32-1; lower median of 5 reports")

    # stale report
    rid, hour = new_request()
    r = Report(rid, z, hour, 300, b"\0" * 32, block_time(w3) - oc.contract.functions.maxAge().call() - 60)
    add("stale oracle report", "reverted: Stale", _try(lambda: oc.submit(rid, [r], [oc.sign(signers[0], r)], attacker)),
        note="issuedAt older than maxAge (6 h); relayed by the attacker")

    # replayed signature
    r = Report(rid, z, hour, 300, b"\0" * 32, block_time(w3))
    sig = oc.sign(signers[1], r)
    oc.submit(rid, [r], [sig])
    add("replayed oracle signature", "reverted: DuplicateReport", _try(lambda: oc.submit(rid, [r], [sig], attacker)),
        note="the same signed report relayed a second time")

    # equivocation (extra row)
    r2 = Report(rid, z, hour, 999, b"\0" * 32, r.issued_at)
    sig2 = oc.sign(signers[1], r2)
    oc.prove_equivocation(r, sig, r2, sig2, challenger)
    slashed = oc.contract.functions.slashedPool().call()
    add("signer equivocation (two values, same zone)", "bond slashed; signer removed",
        "bond slashed; signer removed" if slashed == oc.min_bond and not oc.is_signer(signers[1].address)
        else f"slashed {slashed}", slashed=slashed / 1e18, note="proveEquivocation by anyone")

    # false lower-bound claim, challenged
    pm = PriceMarketClient(chain)
    bond = pm.contract.functions.CLAIM_BOND().call()
    k = len(pm.txs)
    res = false_claim_challenge(pm, epoch_id, inst, attacker, challenger, workflows=[0])
    att_gas = sum(t.gas for t in pm.txs[k:] if t.sender == attacker)
    ok = res[0]["cancelled"] and pm.withdrawable(challenger) == bond // 2 and pm.slashed_pool() == bond - bond // 2
    add("false lower-bound claim (challenged and slashed)", "claim cancelled; 50 % bond to challenger, 50 % slashed",
        "claim cancelled; 50 % bond to challenger, 50 % slashed" if ok else str(res), gas=att_gas,
        slashed=(bond - bond // 2) / 1e18, note="dishonest submitter + claim; one exact minimum as fraud proof")

    # griefing challenge against an honest round
    lay = workflow_layout(inst)
    mid = pm.open_market(epoch_id, inst, [1], lay)
    st = MarketState(inst, [1], lay)
    x = st.honest_assignment()
    pm.submit_batch(mid, x, challenger)
    pm.close_round(mid)
    pm.claim_bound(mid, 0, challenger)
    xw = exact_workflow_min(inst, lay, 0, [0] * inst.m, worst=True)[0]
    obs = _try(lambda: pm.challenge(mid, 0, 0, xw, [0] * inst.m, attacker))
    add("griefing challenge (bond lost)", "reverted: NotCheaper", obs,
        note="this design needs no challenger bond: an invalid challenge reverts and costs the griefer only gas; "
             "the honest claim stays active")
    return rows


# ------------------------------------------------------------------------------- experiment
def _write_csv(path: Path, rows: list[dict[str, Any]], cols: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        wr.writeheader()
        wr.writerows(rows)


def run(base_config: str = "config/demo.yaml", out_dir: str = "results/trust", rounds: int | None = None,
        log: Callable[[str], None] = print) -> dict[str, Any]:
    from demo.pipeline import run as run_pipeline
    from experiments.eval_common import seeded_salts
    from experiments.onchain_market import measure_market

    t0 = time.perf_counter()
    cfg = copy.deepcopy(yaml.safe_load(open(base_config, encoding="utf-8")))
    cfg["chain"]["mode"] = "memory"
    R = int(rounds if rounds is not None else cfg["market"]["rounds"])
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    chain = Chain.start("memory", min_stake=int(cfg["chain"]["stake_wei"]))
    flow = run_pipeline(cfg, log=lambda *_: None, chain=chain, salt_fn=seeded_salts(7))
    inst, eid = flow["_instance"], flow["final"]["epoch_id"]
    log(f"[trust] seed {cfg['seed']}: case-study flow done; PriceMarket {R} rounds ...")
    mk = measure_market(chain, eid, inst, R, float(cfg["market"]["step0"]))
    pm, mid = mk["pm"], mk["market_id"]

    snap = oracle_snapshot(chain, inst)
    pm.bind_oracle(mid, snap["oc"].address, snap["rid"], snap["zones"])
    bind_gas = pm.last_gas()
    cert = certify_bound(pm, mid, mk["best_lb_round"], chain.accounts[1])
    has, clb, _ = pm.certified_lower_bound(mid)
    fgap, cgap = pm.finalized_gap_bps(mid), pm.certified_gap_bps(mid)
    log(f"[trust] oracle: {snap['reports']} reports, submitReports {snap['submit']:,} gas; finalised LB {clb:,} "
        f"(round {mk['best_lb_round']}); finalizedGapBps {fgap} (certifiedGapBps {cgap})")

    ch = false_claim_challenge(pm, eid, inst, chain.accounts[5], chain.accounts[6])
    by_size: dict[int, list[int]] = {}
    for c in ch:
        by_size.setdefault(c["tasks"], []).append(c["gas"])

    attacks = phase4_attacks(chain, eid, inst, chain.accounts[7], chain.accounts[8])
    _write_csv(out / "attacks.csv", attacks, ATTACK_COLUMNS)

    trust_epoch = snap["per_epoch"] + cert["claim"] + cert["finalize"]
    gas_rows = [
        {"function": "deploy CarbonOracle + bond 5 signers", "calls": 1 + N_SIGNERS, "gas_total": snap["one_off_deploy_and_bonds"],
         "note": "one-off"},
        {"function": "requestSnapshot", "detail": f"{inst.m} zones", "calls": 1, "gas_mean": snap["request"],
         "gas_total": snap["request"]},
        {"function": "submitReports", "detail": f"{snap['reports']} reports ({N_SIGNERS} signers x {inst.m} zones)",
         "calls": 1, "gas_mean": snap["submit"], "gas_total": snap["submit"],
         "note": f"{snap['submit'] / snap['reports']:,.0f} gas per report"},
        {"function": "finalizeSnapshot", "detail": f"{inst.m} zones", "calls": 1, "gas_mean": snap["finalize"],
         "gas_total": snap["finalize"]},
        {"function": "bindOracle", "calls": 1, "gas_mean": bind_gas, "gas_total": bind_gas},
        {"function": "claimBound", "calls": 1, "gas_mean": cert["claim"], "gas_total": cert["claim"]},
        {"function": "finalizeBound", "calls": 1, "gas_mean": cert["finalize"], "gas_total": cert["finalize"]},
        *[{"function": "challenge", "detail": f"workflow of {k} tasks", "calls": len(g), "gas_mean": sum(g) / len(g),
           "gas_total": sum(g), "note": "successful fraud proof (cancels a claim)"} for k, g in sorted(by_size.items())],
        {"function": "trust layer per epoch (honest)", "calls": 5, "gas_total": trust_epoch,
         "note": "requestSnapshot + submitReports + finalizeSnapshot + claimBound + finalizeBound (no challenge)"},
    ]
    _write_csv(out / "gas.csv", gas_rows, GAS_COLUMNS)
    e_wh, ci = float(cfg["chain"]["energy_wh_per_million_gas"]), float(cfg["chain"]["chain_ci_g_per_kwh"])
    summary = {
        "seed": cfg["seed"], "tasks": inst.n, "regions": inst.m, "signers": N_SIGNERS, "quorum": 3,
        "rounds": R, "finalized_lower_bound": clb, "finalized_round": mk["best_lb_round"],
        "finalized_gap_bps": fgap, "certified_gap_bps_phase3": cgap,
        "gas": {"submit_reports": snap["submit"], "per_report": snap["submit"] / snap["reports"],
                "finalize_snapshot": snap["finalize"], "claim_bound": cert["claim"], "finalize_bound": cert["finalize"],
                "challenge_mean": sum(c["gas"] for c in ch) / len(ch), "trust_per_epoch": trust_epoch,
                "market_total_25_rounds": mk["market_gas_total"]},
        "trust_overhead_g": trust_epoch / 1e6 * e_wh * ci / 1000,
        "attacks": {"executed": len(attacks), "defended": sum(a["status"] == DEFENDED for a in attacks)},
        "honest_claims": "trust-minimised, not trustless: honest majority of signers, >= 1 honest live watcher per "
                         "challenge window; signer and claim bonds / window are illustrative parameters",
        "runtime_s": round(time.perf_counter() - t0, 2),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log(f"[trust] gas: trust layer per epoch {trust_epoch:,} (claimBound {cert['claim']:,}, finalizeBound "
        f"{cert['finalize']:,}); challenge mean {summary['gas']['challenge_mean']:,.0f}")
    log(f"[trust] attacks: {summary['attacks']['defended']}/{len(attacks)} defended; wrote {out} "
        f"({summary['runtime_s']} s)")
    return summary


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rounds", type=int, default=None)
    ap.add_argument("--out", default="results/trust")
    a = ap.parse_args(argv)
    run(out_dir=a.out, rounds=a.rounds)


if __name__ == "__main__":
    main()
