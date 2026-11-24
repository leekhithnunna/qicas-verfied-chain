"""E1 (net carbon vs overhead sensitivity) and E2 (gas vs instance size) — Phase 6-lite.

Both use the SAME runs: the unchanged case-study pipeline (demo/pipeline.py: 4 honest solvers + 3 attackers,
publish / commit / reveal / finalize) on synthetic instances of increasing size, on the in-memory chain with a
raised block gas limit (so large instances can be measured), with seeded commit salts (reproducible gas).

E1 outputs
  sensitivity.csv  per (instance, energy_wh_per_million_gas, chain_ci): gross saving, overhead, NET saving,
                   overhead % of gross, per-task values. Overhead grid is [VERIFY] (no sources): read the
                   results as RANGES. Two overhead definitions (column overhead_terms): FLOW_TERM = the
                   case-study flow only; MARKET_TERM = flow + Phase 3 on-chain market (openMarket + R rounds of
                   submitBatch + closeRound, measured on the same chain). Phase 4/5 terms are NOT RUN rows.
  breakeven.csv    per overhead term and grid point: smallest measured workload with net saving > 0
  tradeoff.csv     market rounds (5/10/25) vs certified gap; onchain_round_overhead = measured gas of
                   openMarket + the first k on-chain rounds (Phase 3).
E2 outputs
  gas_scaling.csv  gas per function per instance, incl. Phase 3 openMarket / submitBatch / closeRound
                   (+ NOT RUN rows for Phase 4 functions)
  gas_fit.csv      gas ~ a + b*n (+ c*edges) per function (numpy lstsq), largest MEASURED n under the 30 M
                   reference block limit and under the demo client's 15 M per-tx cap; extrapolations labelled.
"""
from __future__ import annotations

import copy
import time
from collections import defaultdict
from typing import Any

import numpy as np

from chain.client import Chain
from demo.pipeline import run as run_pipeline
from experiments.eval_common import (FLOW_TERM, MARKET_TERM, TRUST_TERM, STATUS_OK, Context, ExpResult, not_run,
                                     phase_present, primary_term,
                                     seeded_salts, write_csv)

VERIFY = "[VERIFY] illustrative overhead parameters (no sources)"

SENSITIVITY_COLUMNS = [
    "workflows", "inst_seed", "tasks", "edges", "overhead_terms", "energy_wh_per_million_gas",
    "chain_ci_g_per_kwh", "gas_total", "gas_epoch", "baseline_carbon_g", "best_carbon_g", "gross_saving_g",
    "overhead_g", "net_saving_g", "overhead_pct_of_gross", "overhead_epoch_g", "net_saving_epoch_g",
    "gross_saving_per_task_g", "overhead_per_task_g", "net_saving_per_task_g", "label", "status", "note"]
BREAKEVEN_COLUMNS = [
    "overhead_terms", "energy_wh_per_million_gas", "chain_ci_g_per_kwh", "break_even_tasks", "break_even_workflows",
    "break_even_tasks_epoch", "result", "net_saving_g_min", "net_saving_g_max", "overhead_pct_min",
    "overhead_pct_max", "label", "status"]
TRADEOFF_COLUMNS = [
    "workflows", "inst_seed", "tasks", "market_rounds", "lower_bound", "market_upper_bound",
    "market_gap_pct", "best_revealed_score", "certified_gap_pct", "onchain_round_overhead", "status"]
GAS_COLUMNS = [
    "workflows", "inst_seed", "tasks", "edges", "function", "calls", "gas_mean", "gas_max", "gas_total",
    "fits_reference_block", "fits_demo_tx_cap", "status", "note"]
FIT_COLUMNS = [
    "function", "model", "a", "b", "c", "r2", "max_measured_tasks", "largest_measured_tasks_under_reference",
    "largest_measured_tasks_under_demo_cap", "extrapolated_tasks_at_reference", "extrapolated_tasks_at_demo_cap",
    "status", "note"]

POA_COLUMNS = [
    "workflows", "inst_seed", "tasks", "overhead_terms", "validators", "node_power_w", "hours_per_epoch",
    "energy_wh_per_million_gas", "chain_ci_g_per_kwh", "gas_overhead_g", "node_energy_wh", "node_term_g",
    "overhead_g", "gross_saving_g", "net_saving_g", "node_share_of_overhead_pct", "label", "status", "note"]

FIT_FUNCTIONS = ["publish", "reveal (accepted)", "reveal (rejected: capacity)", "finalize",
                 "openMarket", "submitBatch", "closeRound"]

# overhead terms / functions that need phases not yet built (each becomes an explicit NOT RUN row)
E1_MISSING_TERMS = [
    ("on-chain market rounds gas (openMarket / submitBatch / closeRound)", 3),
    ("oracle reports + bound challenges gas", 4),
    ("PoA node term: N validators x W/node x hours/epoch", 5),
]
E2_MISSING_FUNCTIONS = [("openMarket", 3), ("submitBatch", 3), ("closeRound", 3), ("challenge", 4)]


def _missing(items: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """Entries whose phase is not built yet (built phases produce real rows instead)."""
    return [(a, ph) for a, ph in items if not phase_present(ph)]


# ------------------------------------------------------------------------------- shared flow runs
def flow_runs(ctx: Context) -> list[dict[str, Any]]:
    """One full case-study pipeline run per (workflows, instance seed); cached for E1 and E2."""
    if "flows" in ctx.cache:
        return ctx.cache["flows"]
    fl = ctx.profile["flows"]
    limit = int(ctx.eval_cfg["chain"]["measurement_block_gas_limit"])
    runs = []
    for wf in fl["workflows"]:
        for s in fl["inst_seeds"]:
            cfg = copy.deepcopy(ctx.base_cfg)
            cfg["workflows"], cfg["seed"] = int(wf), int(s)
            cfg["chain"]["mode"] = "memory"
            t0 = time.perf_counter()
            chain = Chain.start("memory", min_stake=int(cfg["chain"]["stake_wei"]), block_gas_limit=limit)
            out = run_pipeline(cfg, log=lambda *_: None, chain=chain, salt_fn=seeded_salts(1000 * int(wf) + int(s)))
            outcome = {r["agent"]: r for r in out["reveals"]}
            txs = []
            for t in out["transactions"]:
                fn = t["action"]
                if fn == "reveal":
                    r = outcome.get(t["detail"], {})
                    if t["status"] != "ok":
                        fn = "reveal (reverted pre-flight)"
                    elif r.get("status") == "accepted":
                        fn = "reveal (accepted)"
                    else:
                        fn = f"reveal (rejected: {r.get('reason', '?')})"
                txs.append({"function": fn, "gas": int(t["gas"]), "ok": t["status"] == "ok"})
            f = out["final"]
            market = None
            if phase_present(3):          # Phase 3: on-chain price rounds on the same chain, linked to this epoch
                from experiments.onchain_market import measure_market
                R = max(int(k) for k in ctx.profile["market_rounds"])
                mk = measure_market(chain, int(f["epoch_id"]), out["_instance"], R, float(cfg["market"]["step0"]))
                market = {"rounds": R, "open_gas": mk["open_gas"], "best_lb": mk["best_lb"],
                          "submit_gas": [r["submit_gas"] for r in mk["rounds"]],
                          "close_gas": [r["close_gas"] for r in mk["rounds"]],
                          "cumulative_gas": [r["cumulative_market_gas"] for r in mk["rounds"]],
                          "total_gas": mk["market_gas_total"]}
                if phase_present(4):      # Phase 4: oracle snapshot + honest bound claim/finalize + one fraud proof
                    from experiments.trust_layer import certify_bound, false_claim_challenge, oracle_snapshot
                    inst_ = out["_instance"]
                    snap = oracle_snapshot(chain, inst_)
                    cert = certify_bound(mk["pm"], mk["market_id"], mk["best_lb_round"], chain.accounts[1])
                    lay = mk["layout"]
                    big = max(range(lay.workflows), key=lambda w: len(lay.tasks(w)))
                    ch = false_claim_challenge(mk["pm"], int(f["epoch_id"]), inst_, chain.accounts[5],
                                               chain.accounts[6], workflows=[big])[0]
                    market["trust"] = {"submitReports": snap["submit"], "requestSnapshot": snap["request"],
                                       "finalizeSnapshot": snap["finalize"], "claimBound": cert["claim"],
                                       "finalizeBound": cert["finalize"], "challenge": ch["gas"],
                                       "challenge_tasks": ch["tasks"],
                                       "per_epoch": snap["per_epoch"] + cert["claim"] + cert["finalize"]}
            runs.append({
                "workflows": int(wf), "inst_seed": int(s), "tasks": out["instance"]["tasks"],
                "edges": out["instance"]["edges"], "txs": txs, "gas_total": int(f["total_gas"]),
                "gas_deploy": sum(t["gas"] for t in txs if t["function"] == "deploy"),
                "baseline_carbon_g": f["baseline_carbon_g"], "best_carbon_g": f["best_carbon_g"],
                "best_score": int(f["best_score"]), "market_lower": out["market"]["lower"],
                "market_upper": out["market"]["upper"], "onchain_market": market,
                "wall_s": time.perf_counter() - t0,
            })
            ctx.log(f"    flow workflows={wf} seed={s}: {runs[-1]['tasks']} tasks, gas {f['total_gas']:,}"
                    + (f"; on-chain market {market['rounds']} rounds, gas {market['total_gas']:,}" if market else ""))
    ctx.cache["flows"] = runs
    return runs


# ------------------------------------------------------------------------------- E1
def overhead_g(gas: int, e_wh_per_mgas: float, ci: float) -> float:
    """gas / 1e6 x Wh per Mgas x g/kWh / 1000 = g CO2e (same formula as demo/pipeline.py step 6)."""
    return gas / 1e6 * e_wh_per_mgas * ci / 1000.0


def run_e1(ctx: Context) -> ExpResult:
    runs = flow_runs(ctx)
    grid = ctx.eval_cfg["overhead_grid"]
    rows: list[dict[str, Any]] = []
    for r in runs:
        gross = r["baseline_carbon_g"] - r["best_carbon_g"]
        terms = [(FLOW_TERM, r["gas_total"], r["gas_total"] - r["gas_deploy"],
                  "gas_epoch excludes the one-off contract deployment")]
        mk = r.get("onchain_market")
        if mk:
            terms.append((MARKET_TERM, r["gas_total"] + mk["total_gas"], r["gas_total"] - r["gas_deploy"] + mk["total_gas"],
                          f"Phase 3 market: openMarket + {mk['rounds']} measured rounds; gas_total excludes the one-off "
                          "PriceMarket deployment, gas_epoch also the case-study deployment"))
            tr = mk.get("trust")
            if tr:
                extra = mk["total_gas"] + tr["per_epoch"]
                terms.append((TRUST_TERM, r["gas_total"] + extra, r["gas_total"] - r["gas_deploy"] + extra,
                              "Phase 4: + requestSnapshot, submitReports (5 signers x m zones), finalizeSnapshot, "
                              "claimBound, finalizeBound (honest, unchallenged); oracle deploy/bonds excluded"))
        for term, gas_total, gas_epoch, note in terms:
            for e in grid["energy_wh_per_million_gas"]:
                for ci in grid["chain_ci_g_per_kwh"]:
                    ov, ov_ep = overhead_g(gas_total, e, ci), overhead_g(gas_epoch, e, ci)
                    rows.append({
                        "workflows": r["workflows"], "inst_seed": r["inst_seed"], "tasks": r["tasks"],
                        "edges": r["edges"], "overhead_terms": term,
                        "energy_wh_per_million_gas": e, "chain_ci_g_per_kwh": ci, "gas_total": gas_total,
                        "gas_epoch": gas_epoch, "baseline_carbon_g": r["baseline_carbon_g"],
                        "best_carbon_g": r["best_carbon_g"], "gross_saving_g": gross, "overhead_g": ov,
                        "net_saving_g": gross - ov,
                        "overhead_pct_of_gross": 100 * ov / gross if gross > 0 else float("nan"),
                        "overhead_epoch_g": ov_ep, "net_saving_epoch_g": gross - ov_ep,
                        "gross_saving_per_task_g": gross / r["tasks"], "overhead_per_task_g": ov / r["tasks"],
                        "net_saving_per_task_g": (gross - ov) / r["tasks"], "label": VERIFY, "status": STATUS_OK,
                        "note": note})
    nr = []
    for term, phase in _missing(E1_MISSING_TERMS):
        rows.append({"overhead_terms": term, "label": VERIFY, "status": not_run(phase),
                     "note": "term not included in overhead_g above"})
        nr.append({"experiment": "E1", "item": f"overhead term: {term}", "status": not_run(phase),
                   "note": "sensitivity.csv row"})
    write_csv(ctx.out / "sensitivity.csv", rows, SENSITIVITY_COLUMNS)
    files = ["sensitivity.csv", "breakeven.csv", "tradeoff.csv"]
    if phase_present(5):
        write_csv(ctx.out / "poa_node_term.csv", poa_rows(runs, rows, ctx.eval_cfg), POA_COLUMNS)
        files.append("poa_node_term.csv")

    ok_rows = [r for r in rows if r["status"] == STATUS_OK]
    be_rows = []
    for term in (FLOW_TERM, MARKET_TERM, TRUST_TERM):
        sel = [r for r in ok_rows if r["overhead_terms"] == term]
        if sel:
            be_rows += [{"overhead_terms": term, **b} for b in breakeven(sel, grid)]
    write_csv(ctx.out / "breakeven.csv", be_rows, BREAKEVEN_COLUMNS)

    trade = []
    for r in runs:
        mk = r.get("onchain_market")
        for k in ctx.profile["market_rounds"]:
            k = min(int(k), len(r["market_lower"]))
            lb, ub = max(r["market_lower"][:k]), min(r["market_upper"][:k])
            trade.append({"workflows": r["workflows"], "inst_seed": r["inst_seed"], "tasks": r["tasks"],
                          "market_rounds": k, "lower_bound": lb, "market_upper_bound": ub,
                          "market_gap_pct": 100 * (ub - lb) / ub,
                          "best_revealed_score": r["best_score"],
                          "certified_gap_pct": 100 * (r["best_score"] - lb) / r["best_score"],
                          "onchain_round_overhead": mk["cumulative_gas"][k - 1] if mk else not_run(3),
                          "status": STATUS_OK})
    if not phase_present(3):
        nr.append({"experiment": "E1", "item": "trade-off: on-chain overhead of market rounds",
                   "status": not_run(3), "note": "tradeoff.csv column onchain_round_overhead"})
    write_csv(ctx.out / "tradeoff.csv", trade, TRADEOFF_COLUMNS)

    main_term = primary_term(r["overhead_terms"] for r in ok_rows)
    sel = [r for r in ok_rows if r["overhead_terms"] == main_term]
    nets = [r["net_saving_g"] for r in sel]
    pcts = [r["overhead_pct_of_gross"] for r in sel if r["overhead_pct_of_gross"] == r["overhead_pct_of_gross"]]
    summary = {"overhead_terms": main_term,
               "net_saving_g_range": [min(nets), max(nets)], "overhead_pct_of_gross_range": [min(pcts), max(pcts)],
               "grid_points": len(grid["energy_wh_per_million_gas"]) * len(grid["chain_ci_g_per_kwh"]),
               "label": VERIFY}
    if phase_present(5):
        poa = read_poa(ctx.out / "poa_node_term.csv")
        summary["poa_net_saving_g_range"] = [min(poa), max(poa)]
        summary["poa_label"] = VERIFY + "; PoA node term: validators x W/node x hours/epoch"
    return ExpResult(files, nr, summary)


def read_poa(path) -> list[float]:
    from experiments.eval_common import read_csv
    return [float(r["net_saving_g"]) for r in read_csv(path) if r["status"] == STATUS_OK]


def poa_rows(runs: list[dict[str, Any]], sens_rows: list[dict[str, Any]], eval_cfg: dict[str, Any]) -> list[dict]:
    """Phase 5 PoA node term on top of the most complete gas overhead (sensitivity.csv rows of that term):
    node energy = validators x node power x hours per epoch (Wh), at the same chain ci as the gas term.
    'Gas is not energy': on a PoA network the always-on nodes, not gas, dominate. [VERIFY] grid, ranges only."""
    p = eval_cfg["poa_node_term"]
    n_val = int(p["validators"])
    ok = [r for r in sens_rows if r["status"] == STATUS_OK]
    term = primary_term(r["overhead_terms"] for r in ok)
    out = []
    for r in (r for r in ok if r["overhead_terms"] == term):
        for w in p["node_power_w"]:
            for h in p["hours_per_epoch"]:
                wh = n_val * float(w) * float(h)
                node_g = wh * float(r["chain_ci_g_per_kwh"]) / 1000.0
                ov = r["overhead_g"] + node_g
                out.append({
                    "workflows": r["workflows"], "inst_seed": r["inst_seed"], "tasks": r["tasks"],
                    "overhead_terms": term + " + PoA node term", "validators": n_val, "node_power_w": w,
                    "hours_per_epoch": h, "energy_wh_per_million_gas": r["energy_wh_per_million_gas"],
                    "chain_ci_g_per_kwh": r["chain_ci_g_per_kwh"], "gas_overhead_g": r["overhead_g"],
                    "node_energy_wh": wh, "node_term_g": node_g, "overhead_g": ov,
                    "gross_saving_g": r["gross_saving_g"], "net_saving_g": r["gross_saving_g"] - ov,
                    "node_share_of_overhead_pct": 100 * node_g / ov if ov > 0 else float("nan"),
                    "label": VERIFY, "status": STATUS_OK,
                    "note": f"Phase 5: {n_val}-validator QBFT network (chain/besu); node power and hours/epoch are "
                            "illustrative parameters, not measurements"})
    return out


def breakeven(rows: list[dict[str, Any]], grid: dict[str, list]) -> list[dict[str, Any]]:
    """Smallest measured workload size (workflows) such that net saving > 0 for every seed at that size and at
    every larger measured size. Reported only within the measured range."""
    out = []
    for e in grid["energy_wh_per_million_gas"]:
        for ci in grid["chain_ci_g_per_kwh"]:
            pts = [r for r in rows if r["energy_wh_per_million_gas"] == e and r["chain_ci_g_per_kwh"] == ci]
            by_wf: dict[int, list[dict]] = defaultdict(list)
            for r in pts:
                by_wf[r["workflows"]].append(r)
            sizes = sorted(by_wf)

            def first_positive(key: str) -> int | None:
                be = None
                for wf in reversed(sizes):
                    if all(r[key] > 0 for r in by_wf[wf]):
                        be = wf
                    else:
                        break
                return be
            be, be_ep = first_positive("net_saving_g"), first_positive("net_saving_epoch_g")
            mean_tasks = {wf: float(np.mean([r["tasks"] for r in by_wf[wf]])) for wf in sizes}
            if be is None:
                result = "no net saving at any measured size (or not at the largest)"
            elif be == sizes[0]:
                result = "net saving > 0 at every measured size (break-even below measured range)"
            else:
                result = "break-even inside measured range"
            pct = [r["overhead_pct_of_gross"] for r in pts if r["overhead_pct_of_gross"] == r["overhead_pct_of_gross"]]
            out.append({
                "energy_wh_per_million_gas": e, "chain_ci_g_per_kwh": ci,
                "break_even_tasks": mean_tasks[be] if be is not None else "",
                "break_even_workflows": be if be is not None else "",
                "break_even_tasks_epoch": mean_tasks[be_ep] if be_ep is not None else "",
                "result": result, "net_saving_g_min": min(r["net_saving_g"] for r in pts),
                "net_saving_g_max": max(r["net_saving_g"] for r in pts),
                "overhead_pct_min": min(pct) if pct else "", "overhead_pct_max": max(pct) if pct else "",
                "label": VERIFY, "status": STATUS_OK})
    return out


# ------------------------------------------------------------------------------- E2
def run_e2(ctx: Context) -> ExpResult:
    runs = flow_runs(ctx)
    ref = int(ctx.eval_cfg["chain"]["reference_block_gas_limit"])
    cap = int(ctx.eval_cfg["chain"]["demo_client_tx_gas_cap"])
    rows = []
    for r in runs:
        groups: dict[str, list[int]] = defaultdict(list)
        for t in r["txs"]:
            groups[t["function"]].append(t["gas"])
        mk = r.get("onchain_market")
        if mk:                              # Phase 3 functions, measured on the same chain
            groups["openMarket"].append(mk["open_gas"])
            groups["submitBatch"] += mk["submit_gas"]
            groups["closeRound"] += mk["close_gas"]
            for fn in ("requestSnapshot", "submitReports", "finalizeSnapshot", "claimBound", "finalizeBound",
                       "challenge"):
                if mk.get("trust"):       # Phase 4 functions, measured on the same chain
                    groups[fn].append(mk["trust"][fn])
        for fn, gs in groups.items():
            pre = fn == "reveal (reverted pre-flight)"
            rows.append({
                "workflows": r["workflows"], "inst_seed": r["inst_seed"], "tasks": r["tasks"], "edges": r["edges"],
                "function": fn, "calls": len(gs), "gas_mean": float(np.mean(gs)), "gas_max": max(gs),
                "gas_total": sum(gs), "fits_reference_block": "" if pre else max(gs) <= ref,
                "fits_demo_tx_cap": "" if pre else max(gs) <= cap,
                "status": STATUS_OK,
                "note": "copycat reveal reverts in the dry-run call; no transaction is mined (gas 0)" if pre else ""})
        rows.append({"workflows": r["workflows"], "inst_seed": r["inst_seed"], "tasks": r["tasks"],
                     "edges": r["edges"], "function": "flow total", "calls": len(r["txs"]),
                     "gas_mean": float(np.mean([t["gas"] for t in r["txs"]])), "gas_max": max(t["gas"] for t in r["txs"]),
                     "gas_total": r["gas_total"], "fits_reference_block": "", "fits_demo_tx_cap": "",
                     "status": STATUS_OK, "note": "sum over all transactions of the epoch incl. deploy"})
        if mk:
            rows.append({"workflows": r["workflows"], "inst_seed": r["inst_seed"], "tasks": r["tasks"],
                         "edges": r["edges"], "function": "market round (submitBatch + closeRound)",
                         "calls": mk["rounds"],
                         "gas_mean": float(np.mean([a + b for a, b in zip(mk["submit_gas"], mk["close_gas"])])),
                         "gas_max": max(a + b for a, b in zip(mk["submit_gas"], mk["close_gas"])),
                         "gas_total": sum(mk["submit_gas"]) + sum(mk["close_gas"]), "fits_reference_block": "",
                         "fits_demo_tx_cap": "", "status": STATUS_OK,
                         "note": "Phase 3: one honest batch submitter per round; two transactions per round"})
    nr = []
    for fn, phase in _missing(E2_MISSING_FUNCTIONS):
        rows.append({"function": fn, "status": not_run(phase), "note": "function does not exist yet"})
        nr.append({"experiment": "E2", "item": f"gas of {fn}", "status": not_run(phase), "note": "gas_scaling.csv row"})
    write_csv(ctx.out / "gas_scaling.csv", rows, GAS_COLUMNS)

    fits = gas_fits([r for r in rows if r["status"] == STATUS_OK], ref, cap)
    fits.append({"function": "schedule entries / regions", "model": "structural", "status": STATUS_OK,
                 "note": "m <= 255 regions (uint8 m and uint8[] schedules); edge indices uint32"})
    write_csv(ctx.out / "gas_fit.csv", fits, FIT_COLUMNS)
    measured = [f for f in fits if f.get("model") == "a+b*n" and f.get("extrapolated_tasks_at_reference") != ""]
    bottleneck = min(measured, key=lambda f: f["extrapolated_tasks_at_reference"]) if measured else None
    summary = {"reference_block_gas_limit": ref, "demo_client_tx_gas_cap": cap,
               "max_measured_tasks": max(r["tasks"] for r in runs),
               "bottleneck_function": bottleneck["function"] if bottleneck else None,
               "bottleneck_largest_measured_tasks_under_reference":
                   bottleneck["largest_measured_tasks_under_reference"] if bottleneck else None,
               "bottleneck_extrapolated_tasks_at_reference":
                   bottleneck["extrapolated_tasks_at_reference"] if bottleneck else None}
    return ExpResult(["gas_scaling.csv", "gas_fit.csv"], nr, summary)


def gas_fits(rows: list[dict[str, Any]], ref: int, cap: int) -> list[dict[str, Any]]:
    out = []
    for fn in FIT_FUNCTIONS:
        pts = [r for r in rows if r["function"] == fn]
        if len(pts) < 2:
            continue
        n = np.array([r["tasks"] for r in pts], dtype=float)
        ed = np.array([r["edges"] for r in pts], dtype=float)
        y = np.array([r["gas_max"] for r in pts], dtype=float)
        under_ref = [r["tasks"] for r in pts if r["gas_max"] <= ref]
        under_cap = [r["tasks"] for r in pts if r["gas_max"] <= cap]
        base = {"function": fn, "max_measured_tasks": int(n.max()),
                "largest_measured_tasks_under_reference": max(under_ref) if under_ref else "",
                "largest_measured_tasks_under_demo_cap": max(under_cap) if under_cap else ""}
        edges_per_task = float(ed.sum() / n.sum())
        for model, X in (("a+b*n", np.column_stack([np.ones_like(n), n])),
                         ("a+b*n+c*edges", np.column_stack([np.ones_like(n), n, ed]))):
            if len(set(n.tolist())) < X.shape[1]:
                continue
            coef, *_ = np.linalg.lstsq(X, y, rcond=None)
            pred = X @ coef
            ss = float(((y - y.mean()) ** 2).sum())
            r2 = 1 - float(((y - pred) ** 2).sum()) / ss if ss > 0 else 1.0
            a, b = float(coef[0]), float(coef[1])
            c = float(coef[2]) if len(coef) > 2 else 0.0
            slope = b + c * edges_per_task
            ex_ref = int((ref - a) / slope) if slope > 0 else ""
            ex_cap = int((cap - a) / slope) if slope > 0 else ""
            note = ("extrapolation from the fit (assumes edges/task = %.2f); only measured n are claims"
                    % edges_per_task)
            if model == "a+b*n+c*edges":
                note += "; n and edges are strongly collinear, so b and c individually are not identifiable"
            out.append({**base, "model": model, "a": a, "b": b, "c": c if len(coef) > 2 else "", "r2": r2,
                        "extrapolated_tasks_at_reference": ex_ref, "extrapolated_tasks_at_demo_cap": ex_cap,
                        "status": STATUS_OK, "note": note})
    return out
