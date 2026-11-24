"""E4 — solver comparison on SYNTHETIC instances and (Phase 1) REAL instances.

Real instances: Alibaba cluster-trace-v2018 DAG samples (data/processed/alibaba_dags_seed{S}_n8.json, local only)
over the config/real_snapshot.yaml regions (Electricity Maps carbon + day-ahead prices, 2024-10-15T12:00Z). Without
those files the real rows are "NOT RUN - data missing".

Solvers and honest labels: greedy (classical), SA (classical), SQA (quantum-inspired), dual-market
(Lagrangian decomposition, classical; deterministic). Weight presets: carbon-priority, balanced, cost-priority.

SA vs SQA budgets (fixes the case-study weakness), reported separately:
  * default       : config/demo.yaml settings (SA 400 sweeps; SQA 150 sweeps x 12 replicas)
  * move-matched  : SA sweeps * n = SQA sweeps * P * n  -> SA gets 150 * 12 = 1800 sweeps
Metric: certified gap to the Lagrangian lower bound, gap% = 100 * (score - LB) / score (LB from the market with
the demo's 25 rounds, per instance and preset); also carbon, cost, feasibility, CPU time.

Statistics (numpy only): mean and 95 % bootstrap CI, resampling solver seeds WITHIN each instance (the instance
set is fixed); paired SA-SQA difference per (instance, seed) with the same stratified bootstrap; win counts.

Outputs: solvers.csv (raw), solvers_summary.csv, classical_vs_qi.csv ("where classical matches or beats
quantum-inspired").
"""
from __future__ import annotations

import copy
import os
import time
from concurrent.futures import ProcessPoolExecutor
from typing import Any

import numpy as np

from core.instance import build_instance, generate_instance
from core.market import run_market
from core.scoring import evaluate
from core.solvers import SOLVERS
from experiments.eval_common import (DATA_MISSING, STATUS_OK, Context, ExpResult, load_real_config, real_workloads,
                                     write_csv)

REAL_DATASET = "real (Alibaba trace, config/real_snapshot.yaml)"
# D1 sensitivity (option (c)): same samples, seeds and presets, but one representative instance per task with the
# 1 Wh integer floor instead of the approved instance_num scaling (option (a)).
REAL_FLOOR_DATASET = "real, 1 Wh floor (D1 sensitivity, option (c))"

LABEL = {"greedy": "classical", "sa": "classical", "sqa": "quantum-inspired",
         "dual-market": "decomposition (classical)"}
RAW_COLUMNS = ["dataset", "preset", "inst_seed", "tasks", "solver", "label", "budget", "moves", "seed", "score",
               "carbon_g", "cost_usd", "lower_bound", "gap_pct", "feasible", "cpu_time_s", "status", "note"]
SUMMARY_COLUMNS = ["dataset", "preset", "solver", "label", "budget", "moves_per_run_mean", "n_instances", "n_runs",
                   "gap_pct_mean", "gap_pct_ci_lo", "gap_pct_ci_hi", "carbon_g_mean", "carbon_g_ci_lo",
                   "carbon_g_ci_hi", "cost_usd_mean", "feasible_rate", "cpu_time_mean_s", "status"]
VS_COLUMNS = ["dataset", "preset", "classical", "classical_label", "classical_budget", "quantum_inspired",
              "qi_budget", "n_pairs", "diff_gap_pct_mean", "diff_ci_lo", "diff_ci_hi", "classical_wins", "ties",
              "qi_wins", "verdict", "classical_matches_or_beats", "status"]

# (solver, budget) variants that take a solver seed
SEEDED = [("sa", "default"), ("sa", "move-matched"), ("sqa", "default")]


def _variant_params(base_cfg: dict, solver: str, budget: str) -> dict:
    p = dict(base_cfg["solvers"].get(solver, {}))
    if solver == "sa" and budget == "move-matched":
        q = base_cfg["solvers"]["sqa"]
        p["sweeps"] = int(q["sweeps"]) * int(q["replicas"])
    return p


def _moves(solver: str, params: dict, n: int) -> int | str:
    if solver == "sa":
        return int(params["sweeps"]) * n
    if solver == "sqa":
        return int(params["sweeps"]) * int(params["replicas"]) * n
    return ""


def _one_instance(job: tuple) -> list[dict[str, Any]]:
    """All solver runs for one (preset, instance seed). Top-level so it can run in a worker process."""
    base_cfg, preset, weights, inst_seed, workflows, solver_seeds, dataset = job
    cfg = copy.deepcopy(base_cfg)
    cfg["workflows"], cfg["seed"], cfg["weights"] = int(workflows), int(inst_seed), dict(weights)
    if dataset == "synthetic":
        inst = generate_instance(cfg, int(inst_seed))
    else:                                   # Phase 1: processed Alibaba sample `inst_seed`, real snapshot regions
        inst = build_instance(cfg, int(inst_seed), workload_seed=int(inst_seed))
    rows = []
    t0 = time.process_time()
    mk = run_market(inst, **cfg["market"])
    t_mk = time.process_time() - t0
    lb = float(mk.best_lower)

    def row(solver, budget, seed, x, cpu, moves):
        ev = evaluate(inst, x)
        return {"dataset": dataset, "preset": preset, "inst_seed": inst_seed, "tasks": inst.n,
                "solver": solver, "label": LABEL[solver], "budget": budget, "moves": moves, "seed": seed,
                "score": ev.score, "carbon_g": ev.carbon_ug / 1e6, "cost_usd": ev.cost_nusd / 1e9,
                "lower_bound": lb, "gap_pct": 100 * (ev.score - lb) / ev.score, "feasible": ev.feasible,
                "cpu_time_s": cpu, "status": STATUS_OK, "note": ""}
    rows.append(row("dual-market", "default (25 rounds)", "", mk.best_schedule, t_mk, ""))
    t0 = time.process_time()
    xg, _ = SOLVERS["greedy"](inst, seed=0)
    rows.append(row("greedy", "n/a", "", xg, time.process_time() - t0, ""))
    for s in solver_seeds:
        for solver, budget in SEEDED:
            p = _variant_params(cfg, solver, budget)
            t0 = time.process_time()
            x, _ = SOLVERS[solver](inst, seed=int(s), **p)
            rows.append(row(solver, budget, int(s), x, time.process_time() - t0, _moves(solver, p, inst.n)))
    return rows


def _strat_boot(mat: np.ndarray, n_boot: int, seed: int) -> tuple[float, float, float]:
    """mat: (instances, seeds). Mean and 95 % CI resampling seeds within each instance."""
    mean = float(mat.mean())
    if mat.shape[1] == 1 or np.all(mat == mat.flat[0]):
        return mean, mean, mean
    rng = np.random.default_rng(seed)
    I, S = mat.shape
    idx = rng.integers(0, S, size=(n_boot, I, S))
    boots = mat[np.arange(I)[None, :, None], idx].mean(axis=(1, 2))
    lo, hi = np.quantile(boots, [0.025, 0.975])
    return mean, float(lo), float(hi)


def _matrix(rows: list[dict], key: str, insts: list[int]) -> np.ndarray:
    """(instances, runs) matrix of `key`, rows ordered by (instance, seed)."""
    by = {}
    for r in rows:
        by.setdefault(r["inst_seed"], []).append(r)
    return np.array([[float(r[key]) for r in sorted(by[i], key=lambda r: (r["seed"] == "", r["seed"]))]
                     for i in insts])


def run_e4(ctx: Context) -> ExpResult:
    sp = ctx.profile["solvers"]
    presets = {p: ctx.eval_cfg["weight_presets"][p] for p in sp["presets"]}
    seeds = [int(s) for s in sp["solver_seeds"]]
    jobs = [(ctx.base_cfg, p, w, int(i), int(sp["workflows"]), seeds, "synthetic")
            for p, w in presets.items() for i in sp["inst_seeds"]]
    real_cfg = load_real_config(ctx.eval_cfg)
    real_seeds = [int(s) for s in sp.get("real_inst_seeds", [])]
    present, missing = real_workloads(real_cfg, real_seeds) if real_cfg else ({}, ["no real_config"])
    real_ok = bool(real_seeds) and not missing
    if real_ok:
        jobs += [(real_cfg, p, w, s, 8, seeds, REAL_DATASET) for p, w in presets.items() for s in real_seeds]
        floor_cfg = copy.deepcopy(real_cfg)
        floor_cfg["workload"]["task_size"] = "representative"
        jobs += [(floor_cfg, p, w, s, 8, seeds, REAL_FLOOR_DATASET) for p, w in presets.items() for s in real_seeds]
    workers = max(1, min(int(sp.get("workers", 0)) or (os.cpu_count() or 1), len(jobs), 8))
    if ctx.profile_name == "smoke":
        workers = 1                                      # pytest: no process pool
    ctx.log(f"    E4: {len(jobs)} (preset, instance) jobs x {len(sp['solver_seeds'])} solver seeds, {workers} workers")
    if workers == 1:
        results = [_one_instance(j) for j in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(_one_instance, jobs))
    raw = [r for rs in results for r in rs]

    nr = []
    if not real_ok:
        note = f"missing: {', '.join(missing[:3])}{' ...' if len(missing) > 3 else ''}; run scripts/load_alibaba_dags.py"
        for solver in ("greedy", "sa", "sqa", "dual-market"):
            raw.append({"dataset": REAL_DATASET, "solver": solver, "label": LABEL[solver], "status": DATA_MISSING,
                        "note": note})
        nr.append({"experiment": "E4", "item": "solver comparison on real data (Alibaba trace + Electricity Maps)",
                   "status": DATA_MISSING, "note": note})
    ctx.log(f"    E4 real data: {'ok, samples ' + str(real_seeds) if real_ok else DATA_MISSING}")
    write_csv(ctx.out / "solvers.csv", raw, RAW_COLUMNS)

    nb, bs = int(ctx.eval_cfg["bootstrap"]["n_boot"]), int(ctx.eval_cfg["bootstrap"]["seed"])
    ok = [r for r in raw if r["status"] == STATUS_OK]
    summary_rows, vs_rows = [], []
    variants = [("dual-market", "default (25 rounds)"), ("greedy", "n/a"), *SEEDED]
    datasets = ["synthetic"] + ([REAL_DATASET, REAL_FLOOR_DATASET] if real_ok else [])
    for dataset, preset in [(d, p) for d in datasets for p in presets]:
        dok = [r for r in ok if r["dataset"] == dataset]
        insts = sorted({r["inst_seed"] for r in dok})
        grp = {v: [r for r in dok if r["preset"] == preset and (r["solver"], r["budget"]) == v] for v in variants}
        for (solver, budget), rs in grp.items():
            gm, glo, ghi = _strat_boot(_matrix(rs, "gap_pct", insts), nb, bs)
            cm, clo, chi = _strat_boot(_matrix(rs, "carbon_g", insts), nb, bs)
            mv = [r["moves"] for r in rs if r["moves"] != ""]
            summary_rows.append({
                "dataset": dataset, "preset": preset, "solver": solver, "label": LABEL[solver], "budget": budget,
                "moves_per_run_mean": float(np.mean(mv)) if mv else "", "n_instances": len(insts), "n_runs": len(rs),
                "gap_pct_mean": gm, "gap_pct_ci_lo": glo, "gap_pct_ci_hi": ghi, "carbon_g_mean": cm,
                "carbon_g_ci_lo": clo, "carbon_g_ci_hi": chi, "cost_usd_mean": float(np.mean([r["cost_usd"] for r in rs])),
                "feasible_rate": float(np.mean([bool(r["feasible"]) for r in rs])),
                "cpu_time_mean_s": float(np.mean([r["cpu_time_s"] for r in rs])), "status": STATUS_OK})
        q = _matrix(grp[("sqa", "default")], "gap_pct", insts)
        qs = _matrix(grp[("sqa", "default")], "score", insts)
        for solver, budget in [("greedy", "n/a"), ("sa", "default"), ("sa", "move-matched"),
                               ("dual-market", "default (25 rounds)")]:
            cg, cs = _matrix(grp[(solver, budget)], "gap_pct", insts), _matrix(grp[(solver, budget)], "score", insts)
            if cg.shape[1] == 1:                       # deterministic solver: compare against every SQA seed
                cg, cs = np.repeat(cg, q.shape[1], axis=1), np.repeat(cs, q.shape[1], axis=1)
            d = cg - q                                 # < 0  => classical has the smaller gap (better)
            m, lo, hi = _strat_boot(d, nb, bs)
            wins, ties, losses = int((cs < qs).sum()), int((cs == qs).sum()), int((cs > qs).sum())
            if hi < 0:
                verdict = "classical better (CI below 0)"
            elif lo > 0:
                verdict = "quantum-inspired better (CI above 0)"
            else:
                verdict = "no significant difference (CI includes 0)"
            vs_rows.append({"dataset": dataset, "preset": preset, "classical": solver,
                            "classical_label": LABEL[solver], "classical_budget": budget, "quantum_inspired": "sqa",
                            "qi_budget": "default", "n_pairs": int(d.size), "diff_gap_pct_mean": m, "diff_ci_lo": lo,
                            "diff_ci_hi": hi, "classical_wins": wins, "ties": ties, "qi_wins": losses,
                            "verdict": verdict, "classical_matches_or_beats": lo <= 0, "status": STATUS_OK})
    write_csv(ctx.out / "solvers_summary.csv", summary_rows, SUMMARY_COLUMNS)
    write_csv(ctx.out / "classical_vs_qi.csv", vs_rows, VS_COLUMNS)
    summary = {"instances": len({r["inst_seed"] for r in ok if r["dataset"] == "synthetic"}),
               "real_instances": len(real_seeds) if real_ok else DATA_MISSING, "solver_seeds": len(sp["solver_seeds"]), "presets": list(presets),
               "classical_matches_or_beats_sqa": sum(bool(r["classical_matches_or_beats"]) for r in vs_rows),
               "comparisons": len(vs_rows)}
    return ExpResult(["solvers.csv", "solvers_summary.csv", "classical_vs_qi.csv"], nr, summary)
