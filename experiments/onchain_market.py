"""Phase 3 experiment: on-chain price rounds for the seed-7 case-study epoch, with measured gas.

Flow: the unchanged case-study pipeline (demo/pipeline.py; publish / commit / reveal / finalize, seeded salts)
-> PriceMarket deployed on the same in-memory chain and linked to that epoch -> R rounds, each with one honest
exact submitter (submitBatch of the per-workflow exact minimisers, core/market_int.py) and closeRound -> on-chain
certifiedGapBps (UB = best revealed score). Every round is checked against the Python twin (MarketState);
any mismatch aborts the run. A separate 1-round market measures `submit` gas by workflow size.

Outputs (results/onchain_market/): rounds.csv, gas.csv, summary.json.
Honest claim: the bound is certified ASSUMING each workflow's minimum was submitted by an honest party.

  python -m experiments.onchain_market                # seed 7, 25 rounds (config/demo.yaml market.rounds)
  python -m experiments.onchain_market --rounds 3     # quick run
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np
import yaml

from chain.client import Chain
from chain.price_market import PriceMarketClient
from core.instance import Instance
from core.market_int import MarketState, default_steps, exact_workflow_min, gap_bps, workflow_layout

ROUND_COLUMNS = ["round", "complete", "lam", "loads", "dual_value", "best_lb_so_far", "float_market_lower",
                 "submit_gas", "close_gas", "round_gas", "cumulative_market_gas"]
GAS_COLUMNS = ["function", "workflow_tasks", "calls", "gas_mean", "gas_min", "gas_max", "gas_total", "note"]


class ParityError(AssertionError):
    pass


def measure_market(chain: Chain, epoch_id: int, inst: Instance, rounds: int, step0: float = 1.0,
                   submit_mode: str = "batch", solver: str | None = None,
                   log: Callable[[str], None] = lambda s: None) -> dict[str, Any]:
    """Deploy PriceMarket on `chain`, run `rounds` honest rounds for `epoch_id`, check parity every round."""
    pm = PriceMarketClient(chain)
    lay = workflow_layout(inst)
    steps = default_steps(inst, rounds, step0)
    st = MarketState(inst, steps, lay)
    solver = solver or chain.accounts[1]
    deploy_gas = pm.last_gas()
    mid = pm.open_market(epoch_id, inst, steps, lay)
    open_gas = pm.last_gas()
    recs = []
    cum = open_gas
    while not st.finished:
        if pm.prices(mid) != st.lam:
            raise ParityError(f"round {st.round}: prices differ")
        x = st.honest_assignment()
        if submit_mode == "batch":
            sub_gas = pm.submit_batch(mid, x, solver)["gas"]
        elif submit_mode == "single":
            sub_gas = 0
            for w in range(lay.workflows):
                sub_gas += pm.submit(mid, w, x[lay.task_start[w]:lay.task_start[w + 1]], solver)["gas"]
        else:
            raise ValueError("submit_mode must be 'batch' or 'single'")
        st.submit_batch(x)
        c, p = pm.close_round(mid), st.close_round()
        if (c["complete"], c["lam"], c["loads"], c["dual_value"], c["next_lam"]) != (
                p.complete, p.lam, p.loads, p.dual_value, p.next_lam):
            raise ParityError(f"round {p.k}: on-chain {c} != python {p}")
        cum += sub_gas + c["gas"]
        recs.append({"round": p.k, "complete": p.complete, "lam": p.lam, "loads": p.loads, "dual_value": p.dual_value,
                     "best_lb_so_far": st.best_lb, "submit_gas": sub_gas, "close_gas": c["gas"],
                     "round_gas": sub_gas + c["gas"], "cumulative_market_gas": cum})
        log(f"    round {p.k:2d}: g={p.dual_value:,} submit {sub_gas:,} + close {c['gas']:,} gas")
    has, lb, lb_round = pm.best_lower_bound(mid)
    if (has, lb, lb_round) != (True, st.best_lb, st.best_lb_round):
        raise ParityError("best lower bound differs")
    return {"pm": pm, "market_id": mid, "steps": steps, "rounds": recs, "best_lb": lb, "best_lb_round": lb_round,
            "deploy_gas": deploy_gas, "open_gas": open_gas, "layout": lay,
            "market_gas_total": cum, "round_gas": [r["round_gas"] for r in recs]}


def submit_gas_by_size(chain: Chain, epoch_id: int, inst: Instance, pm: PriceMarketClient) -> list[dict[str, Any]]:
    """1-round market: one first (improving) `submit` per workflow; gas grouped by workflow size."""
    lay = workflow_layout(inst)
    mid = pm.open_market(epoch_id, inst, [1], lay)
    by: dict[int, list[int]] = {}
    for w in range(lay.workflows):
        xw, _ = exact_workflow_min(inst, lay, w, [0] * inst.m)
        by.setdefault(len(xw), []).append(pm.submit(mid, w, xw, chain.accounts[2])["gas"])
    return [{"function": "submit", "workflow_tasks": k, "calls": len(g), "gas_mean": float(np.mean(g)),
             "gas_min": min(g), "gas_max": max(g), "gas_total": sum(g),
             "note": "first (improving) submission of one workflow"} for k, g in sorted(by.items())]


def overhead_g(gas: int, wh_per_mgas: float, ci: float) -> float:
    """Same formula as demo/pipeline.py step 6 (sensitivity parameters, not measured)."""
    return gas / 1e6 * wh_per_mgas * ci / 1000.0


def _write_csv(path: Path, rows: list[dict[str, Any]], cols: list[str]) -> None:
    import csv
    with path.open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        wr.writeheader()
        for r in rows:
            wr.writerow({k: (" ".join(map(str, v)) if isinstance(v, list) else v) for k, v in r.items()})


def run(config: str = "config/onchain_market.yaml", rounds: int | None = None, out_dir: str | None = None,
        log: Callable[[str], None] = print) -> dict[str, Any]:
    from demo.pipeline import run as run_pipeline
    from experiments.eval_common import seeded_salts

    ecfg = yaml.safe_load(open(config, encoding="utf-8"))
    cfg = copy.deepcopy(yaml.safe_load(open(ecfg["base_config"], encoding="utf-8")))
    cfg["chain"]["mode"] = "memory"
    R = int(rounds if rounds is not None else cfg["market"]["rounds"])
    step0 = float(cfg["market"]["step0"])
    out = Path(out_dir or ecfg["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()

    log(f"[onchain-market] case-study flow, seed {cfg['seed']} ...")
    chain = Chain.start("memory", min_stake=int(cfg["chain"]["stake_wei"]))
    flow = run_pipeline(cfg, log=lambda *_: None, chain=chain, salt_fn=seeded_salts(int(ecfg["salt_seed"])))
    inst, eid, fin = flow["_instance"], flow["final"]["epoch_id"], flow["final"]
    flow_gas = chain.total_gas()
    log(f"[onchain-market] epoch {eid}: best revealed score {fin['best_score']:,}, flow gas {flow_gas:,}")

    log(f"[onchain-market] PriceMarket: {R} rounds, submit mode {ecfg['submit_mode']} ...")
    res = measure_market(chain, eid, inst, R, step0, ecfg["submit_mode"], log=log)
    pm, mid = res["pm"], res["market_id"]
    ub = int(chain.summary(eid)["best_score"])
    gap_onchain = pm.certified_gap_bps(mid)
    if gap_onchain != gap_bps(ub, res["best_lb"]):
        raise ParityError("certifiedGapBps differs from gap_bps")
    sizes = submit_gas_by_size(chain, eid, inst, pm)

    flt = flow["market"]["lower"]
    for r in res["rounds"]:
        r["float_market_lower"] = flt[r["round"]] if r["round"] < len(flt) else ""
    _write_csv(out / "rounds.csv", res["rounds"], ROUND_COLUMNS)

    rg = res["round_gas"]
    sub = [r["submit_gas"] for r in res["rounds"]]
    clo = [r["close_gas"] for r in res["rounds"]]
    fn_name = "submitBatch" if ecfg["submit_mode"] == "batch" else "submit (all workflows)"
    gas_rows = [
        {"function": "deploy PriceMarket", "calls": 1, "gas_mean": res["deploy_gas"], "gas_min": res["deploy_gas"],
         "gas_max": res["deploy_gas"], "gas_total": res["deploy_gas"], "note": "one-off"},
        {"function": "openMarket", "calls": 1, "gas_mean": res["open_gas"], "gas_min": res["open_gas"],
         "gas_max": res["open_gas"], "gas_total": res["open_gas"], "note": f"{inst.n} tasks, {len(inst.edges)} edges, {R} steps"},
        {"function": fn_name, "workflow_tasks": inst.n, "calls": len(sub), "gas_mean": float(np.mean(sub)),
         "gas_min": min(sub), "gas_max": max(sub), "gas_total": sum(sub), "note": "honest exact minimisers, every round"},
        {"function": "closeRound", "calls": len(clo), "gas_mean": float(np.mean(clo)), "gas_min": min(clo),
         "gas_max": max(clo), "gas_total": sum(clo), "note": "complete rounds"},
        *sizes,
        {"function": "per round (submit + closeRound)", "calls": len(rg), "gas_mean": float(np.mean(rg)),
         "gas_min": min(rg), "gas_max": max(rg), "gas_total": sum(rg), "note": ""},
        {"function": f"market total ({R} rounds incl. openMarket)", "calls": 1 + 2 * R,
         "gas_mean": "", "gas_min": "", "gas_max": "", "gas_total": res["market_gas_total"],
         "note": "excludes the one-off PriceMarket deployment"},
    ]
    _write_csv(out / "gas.csv", gas_rows, GAS_COLUMNS)

    e_wh, ci = float(cfg["chain"]["energy_wh_per_million_gas"]), float(cfg["chain"]["chain_ci_g_per_kwh"])
    ref = int(ecfg["reference_block_gas_limit"])
    mkt_g = overhead_g(res["market_gas_total"], e_wh, ci)
    summary = {
        "seed": cfg["seed"], "instance_hash": "0x" + inst.instance_hash().hex(), "tasks": inst.n,
        "edges": len(inst.edges), "workflows": res["layout"].workflows, "regions": inst.m, "rounds": R,
        "submit_mode": ecfg["submit_mode"], "steps": res["steps"],
        "parity": "every round: prices, loads, dual value, next prices, best LB, certifiedGapBps == Python",
        "lower_bound_onchain_int": res["best_lb"], "lower_bound_round": res["best_lb_round"],
        "lower_bound_float_offchain": flow["market"]["best_lower"],
        "upper_bound_best_revealed": ub,
        "certified_gap_bps_onchain": gap_onchain, "certified_gap_pct_offchain_float": fin["certified_gap_pct"],
        "gas": {"deploy_price_market": res["deploy_gas"], "open_market": res["open_gas"],
                "submit_mean": float(np.mean(sub)), "close_round_mean": float(np.mean(clo)),
                "per_round_mean": float(np.mean(rg)), "per_round_max": max(rg),
                "market_total": res["market_gas_total"], "case_study_flow_total": flow_gas,
                "max_single_tx": max([res["open_gas"], *sub, *clo]),
                "max_single_tx_share_of_reference_block": max([res["open_gas"], *sub, *clo]) / ref,
                "per_round_share_of_reference_block": max(rg) / ref,
                "reference_block_gas_limit": ref},
        "overhead_model": {"energy_wh_per_million_gas": e_wh, "chain_ci_g_per_kwh": ci,
                           "label": "sensitivity parameters from config/demo.yaml, NOT measured"},
        "market_overhead_g": mkt_g, "case_study_overhead_g": fin["overhead_g"],
        "net_saving_g_case_study": fin["net_saving_g"], "net_saving_g_incl_market": fin["net_saving_g"] - mkt_g,
        "honest_claim": "lower bound certified assuming each workflow's minimum was submitted by >= 1 honest party "
                        "(Phase 4 adds fraud proofs); integer bound may differ slightly from the float bound",
        "runtime_s": round(time.perf_counter() - t0, 2),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log(f"[onchain-market] LB (on-chain, int) {res['best_lb']:,} vs float {flow['market']['best_lower']:,.0f}; "
        f"UB {ub:,}; certified gap {gap_onchain} bps")
    log(f"[onchain-market] gas: openMarket {res['open_gas']:,}; per round {np.mean(rg):,.0f} "
        f"(submit {np.mean(sub):,.0f} + close {np.mean(clo):,.0f}); {R} rounds total {res['market_gas_total']:,}")
    log(f"[onchain-market] market overhead {mkt_g:.4f} g (at {e_wh} Wh/Mgas, {ci:g} g/kWh) vs case-study net saving "
        f"{fin['net_saving_g']:.1f} g -> {summary['net_saving_g_incl_market']:.1f} g incl. market")
    log(f"[onchain-market] wrote {out / 'rounds.csv'}, gas.csv, summary.json ({summary['runtime_s']} s)")
    return summary


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", default="config/onchain_market.yaml")
    ap.add_argument("--rounds", type=int, default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    run(a.config, a.rounds, a.out)


if __name__ == "__main__":
    main()
