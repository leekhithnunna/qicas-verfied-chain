"""Phase 2 fair-comparison benchmark (docs/plans/PHASE2_QUANTUM.md §3). NOT on the default demo path.

Same sub-problems, same seeds (0..run_seeds-1), same budgets B (energy evaluations, enforced by
SubProblem's counter) for every method. Parameters are tuned on TUNING instances only (grid <= 12
settings per method and budget) and frozen in tuning.json before the test run.

Outputs (config `output_dir`, default results/quantum/):
  manifest.json          frozen sub-problem set (hashes), tuned parameters, environment
  tuning.csv             every tuning run (tuning instances only)
  raw.csv                one row per (sub-problem, method, budget, seed) on TEST instances
  summary.csv            per (method, budget): P(opt), normalised gap (mean, median, 95% bootstrap CI over
                         sub-problems), SB raw feasibility, wall-clock (simulator/CPU time, NOT hardware)
  summary_by_size.csv    same, split by number of tasks
  classical_vs.csv       per budget: share of sub-problems where classical SA matches or beats each method
  design_*.csv           design questions Q1-Q3; market.csv: QAOA as market upper-bound solver
  fig_gap.png, fig_popt.png

Labels (AGENTS.md rule 5): SA classical; SQA, SB quantum-inspired; QAOA = quantum algorithm, classically
simulated; QAOA-ideal = optimistic upper bound (angles from exact, uncounted expectations), reported
separately. Nothing here measures or claims quantum advantage.

Usage:  python -m experiments.quantum_benchmark [--config config/quantum_bench.yaml] [--smoke] [--out DIR]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")      # one BLAS thread per worker process (inherited by spawned workers)

import numpy as np  # noqa: E402
import yaml  # noqa: E402

from core.instance import generate_instance  # noqa: E402
from core.market import _solve_workflow, run_market  # noqa: E402
from core.scoring import FastEvaluator  # noqa: E402
from core.solvers.common import repair  # noqa: E402
from core.subproblem import LABEL, SUBSOLVERS, SubProblem  # noqa: E402
from core.subproblem.exact import exact_info, normalised_gap  # noqa: E402
from core.subproblem.optim import nelder_mead  # noqa: E402
from core.subproblem.qaoa_xy import SubspaceQAOA, gate_count, optimise_ideal  # noqa: E402

RAW_COLUMNS = ["sp_id", "sp_hash", "inst_seed", "workflow", "round", "tasks", "qubits", "method", "label",
               "budget", "seed", "energy", "e_star", "e_max", "gap", "is_opt", "evals", "feasible_rate",
               "wall_s"]
SUMMARY_COLUMNS = ["method", "label", "budget", "n_subproblems", "n_runs", "p_opt", "p_opt_ci_lo",
                   "p_opt_ci_hi", "gap_mean", "gap_ci_lo", "gap_ci_hi", "gap_median", "feasible_rate",
                   "wall_s_mean"]
SMOKE = {"run_seeds": 2, "budgets": [16], "max_test": 2, "tuning": False, "design": False, "market": False}


# ------------------------------------------------------------------------------- sub-problem set
def build_subproblems(cfg: dict, base_cfg: dict, seeds: list[int], limit: int | None = None) -> list[SubProblem]:
    """Workflows with tasks_min..tasks_max tasks, priced with integer-rounded market prices of the given
    rounds. Deduplicated by sub-problem hash; order = (seed, round, workflow)."""
    sc = cfg["subproblems"]
    out, seen = [], set()
    for s in seeds:
        inst = generate_instance(base_cfg, s)
        ev = FastEvaluator(inst)
        mk = run_market(inst, rounds=sc["market_rounds"])
        for r in sc["price_rounds"]:
            lam = [int(round(v)) for v in mk.prices[r - 1]]
            for w, tasks in sorted(inst.workflows().items()):
                if not sc["tasks_min"] <= len(tasks) <= sc["tasks_max"]:
                    continue
                sp = SubProblem.from_workflow(inst, tasks, lam, ev,
                                              meta={"inst_seed": s, "workflow": w, "round": r})
                h = sp.sp_hash()
                if h in seen:
                    continue
                seen.add(h)
                sp.meta["sp_id"] = f"s{s}-w{w}-r{r}"
                out.append(sp)
                if limit is not None and len(out) >= limit:
                    return out
    return out


def manifest_hash(sps: list[SubProblem]) -> str:
    return "0x" + hashlib.sha256("".join(sp.sp_hash() for sp in sps).encode()).hexdigest()


# ------------------------------------------------------------------------------- running
def _run_jobs(job) -> list[dict]:
    """Worker: one sub-problem, a list of (method, tag, params), budgets, seeds -> raw rows."""
    sp, specs, budgets, seeds = job
    ref = exact_info(sp)
    rows = []
    for method, tag, params in specs:
        fn = SUBSOLVERS[method]
        for B in budgets:
            prm = params[B] if isinstance(params, dict) and B in params else params
            for seed in seeds:
                sp.set_budget(B)
                t0 = time.perf_counter()
                r = fn(sp, seed=seed, **prm)
                wall = time.perf_counter() - t0
                if r.evals > B or r.energy != sp._energy(r.x):
                    raise RuntimeError(f"{method} violated the protocol on {sp.meta['sp_id']}")
                rows.append({
                    "sp_id": sp.meta["sp_id"], "sp_hash": sp.sp_hash(), "inst_seed": sp.meta["inst_seed"],
                    "workflow": sp.meta["workflow"], "round": sp.meta["round"], "tasks": sp.t,
                    "qubits": sp.n_qubits, "method": method if tag is None else f"{method}#{tag}",
                    "label": LABEL[method], "budget": B, "seed": seed, "energy": r.energy,
                    "e_star": ref.e_star, "e_max": ref.e_max, "gap": normalised_gap(r.energy, ref),
                    "is_opt": int(r.energy == ref.e_star), "evals": r.evals,
                    "feasible_rate": r.info.get("feasible_rate", ""), "wall_s": round(wall, 6)})
    return rows


def run_all(jobs: list, workers: int) -> list[dict]:
    if workers <= 1 or len(jobs) <= 1:
        res = [_run_jobs(j) for j in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            res = list(ex.map(_run_jobs, jobs, chunksize=1))      # order preserved => deterministic
    return [row for rows in res for row in rows]


# ------------------------------------------------------------------------------- statistics
def bootstrap_ci(per_sp: np.ndarray, n_boot: int = 2000, seed: int = 0) -> tuple[float, float]:
    """95% percentile bootstrap CI of the mean, resampling SUB-PROBLEMS (runs on one sub-problem are
    correlated). numpy only."""
    if per_sp.size == 0:
        return math.nan, math.nan
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, per_sp.size, size=(n_boot, per_sp.size))
    means = per_sp[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def _group(rows, keys):
    out: dict[tuple, list[dict]] = {}
    for r in rows:
        out.setdefault(tuple(r[k] for k in keys), []).append(r)
    return out


def summarise(rows: list[dict], extra_keys: tuple[str, ...] = ()) -> list[dict]:
    out = []
    for key, rs in _group(rows, ("method", "budget") + extra_keys).items():
        by_sp = _group(rs, ("sp_id",))
        gap_sp = np.array([np.mean([r["gap"] for r in v]) for v in by_sp.values()])
        opt_sp = np.array([np.mean([r["is_opt"] for r in v]) for v in by_sp.values()])
        g_lo, g_hi = bootstrap_ci(gap_sp)
        o_lo, o_hi = bootstrap_ci(opt_sp)
        fr = [float(r["feasible_rate"]) for r in rs if r["feasible_rate"] != ""]
        row = {"method": key[0], "label": rs[0]["label"], "budget": key[1], "n_subproblems": len(by_sp),
               "n_runs": len(rs), "p_opt": float(opt_sp.mean()), "p_opt_ci_lo": o_lo, "p_opt_ci_hi": o_hi,
               "gap_mean": float(gap_sp.mean()), "gap_ci_lo": g_lo, "gap_ci_hi": g_hi,
               "gap_median": float(np.median([r["gap"] for r in rs])),
               "feasible_rate": float(np.mean(fr)) if fr else "",
               "wall_s_mean": float(np.mean([r["wall_s"] for r in rs]))}
        for i, k in enumerate(extra_keys):
            row[k] = key[2 + i]
        out.append(row)
    return out


def classical_vs(rows: list[dict], ref: str = "sa") -> list[dict]:
    """Per budget and method: share of sub-problems where classical SA's mean gap is <= the method's
    (match or beat), and where it is strictly lower (beat)."""
    mean_gap = {k: np.mean([r["gap"] for r in v]) for k, v in _group(rows, ("method", "budget", "sp_id")).items()}
    out = []
    methods = sorted({r["method"] for r in rows if r["method"] != ref})
    for B in sorted({r["budget"] for r in rows}):
        sps = sorted({k[2] for k in mean_gap if k[1] == B})
        for meth in methods:
            pairs = [(mean_gap[(ref, B, s)], mean_gap[(meth, B, s)]) for s in sps
                     if (ref, B, s) in mean_gap and (meth, B, s) in mean_gap]
            if not pairs:
                continue
            out.append({"budget": B, "method": meth, "label": LABEL[meth], "n_subproblems": len(pairs),
                        "sa_matches_or_beats": float(np.mean([a <= b for a, b in pairs])),
                        "sa_strictly_beats": float(np.mean([a < b for a, b in pairs]))})
    return out


def write_csv(path: Path, rows: list[dict], columns: list[str] | None = None) -> None:
    columns = columns or (list(rows[0].keys()) if rows else [])
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (f"{v:.6g}" if isinstance(v, float) else v) for k, v in r.items()})


# ------------------------------------------------------------------------------- tuning
def tune(cfg: dict, sps: list[SubProblem], workers: int) -> tuple[dict, list[dict]]:
    """Grid search per method and budget on tuning sub-problems. Returns ({method: {B: params}}, rows)."""
    tc = cfg["tuning"]
    seeds = list(range(tc["seeds"]))
    specs = [(m, i, p) for m, mc in cfg["methods"].items() for i, p in enumerate(mc["grid"])]
    rows = run_all([(sp, specs, cfg["budgets"], seeds) for sp in sps], workers)
    stats = {}
    for (meth, B), rs in _group(rows, ("method", "budget")).items():
        stats[(meth, B)] = (np.mean([r["gap"] for r in rs]), -np.mean([r["is_opt"] for r in rs]))
    chosen = {}
    for m, mc in cfg["methods"].items():
        chosen[m] = {}
        for B in cfg["budgets"]:
            best = min(range(len(mc["grid"])), key=lambda i: (*stats[(f"{m}#{i}", B)], i))
            chosen[m][B] = dict(mc["grid"][best])
    return chosen, rows


# ------------------------------------------------------------------------------- design questions
def design_ring_vs_complete(sps, depths) -> list[dict]:
    """Q1: exact probability of the optimum and normalised <E> for QAOA-ideal, ring vs complete, per p."""
    out = []
    for sp in sps:
        ref = exact_info(sp)
        D = sp.diagonal().ravel()
        opt = D == ref.e_star
        for mixer in ("ring", "complete"):
            sim = SubspaceQAOA(sp, mixer)
            gc = gate_count(sp.t, sp.m, mixer)
            for p in depths:
                gs, bs, _ = optimise_ideal(sim, p)
                pr = sim.probs(gs, bs)
                exp_e = float(pr @ D)
                out.append({"sp_id": sp.meta["sp_id"], "tasks": sp.t, "mixer": mixer, "p": p,
                            "p_opt": float(pr[opt].sum()), "uniform_p_opt": float(opt.mean()),
                            "exp_gap": (exp_e - ref.e_star) / max(1, ref.e_max - ref.e_star),
                            "xy_gates": p * gc["xy_gates_per_layer"], "mixer_depth": p * gc["mixer_depth"]})
    return out


def design_param_reuse(sps, p: int = 2) -> list[dict]:
    """Q2: reuse round k's ideal angles at the next price round vs fresh optimisation."""
    by_wf = _group([{"sp": sp, "inst_seed": sp.meta["inst_seed"], "workflow": sp.meta["workflow"]} for sp in sps],
                   ("inst_seed", "workflow"))
    out = []
    for (s, w), items in by_wf.items():
        seq = sorted((it["sp"] for it in items), key=lambda sp: sp.meta["round"])
        for prev, cur in zip(seq, seq[1:]):
            for mixer in ("ring", "complete"):
                sim_prev, sim_cur = SubspaceQAOA(prev, mixer), SubspaceQAOA(cur, mixer)
                g_prev, b_prev, _ = optimise_ideal(sim_prev, p)
                g_new, b_new, _ = optimise_ideal(sim_cur, p)
                D = cur.diagonal().ravel()
                opt = D == D.min()
                v, _, n_eval = nelder_mead(lambda u, sim=sim_cur: sim.expectation(u[:p], u[p:]),
                                           np.concatenate([g_prev, b_prev]), step=0.2, max_evals=300)
                out.append({"inst_seed": s, "workflow": w, "from_round": prev.meta["round"],
                            "to_round": cur.meta["round"], "mixer": mixer, "p": p,
                            "p_opt_fresh": float(sim_cur.probs(g_new, b_new)[opt].sum()),
                            "p_opt_reuse": float(sim_cur.probs(g_prev, b_prev)[opt].sum()),
                            "p_opt_reuse_refined": float(sim_cur.probs(v[:p], v[p:])[opt].sum()),
                            "refine_expectation_calls": n_eval,
                            "fresh_expectation_calls": _fresh_calls(sim_cur, p)})
    return out


def _fresh_calls(sim, p) -> int:
    """Number of exact-expectation calls a fresh (uncached) ideal optimisation needs."""
    calls = [0]
    orig = sim.expectation

    def counting(*a, **k):
        calls[0] += 1
        return orig(*a, **k)
    sim.expectation = counting
    try:
        optimise_ideal(sim, p, use_cache=False)
    finally:
        sim.expectation = orig
    return calls[0]


def design_warm_start(sps, eps_list, p, sqa_budget, sqa_params) -> list[dict]:
    """Q3: warm start from an SQA answer vs uniform start (QAOA-ideal, exact probabilities)."""
    out = []
    for sp in sps:
        ref = exact_info(sp)
        D = sp.diagonal().ravel()
        opt = D == ref.e_star
        sp.set_budget(sqa_budget)
        sq = SUBSOLVERS["sqa"](sp, seed=0, **sqa_params)
        sq_idx = sp.index_of(sq.x)
        sqa_opt = sq.energy == ref.e_star
        for mixer in ("ring", "complete"):
            sim = SubspaceQAOA(sp, mixer)
            starts = [("uniform", None)] + [(f"warm_eps{e}", e) for e in eps_list]
            for name, eps in starts:
                init = None if eps is None else sim.initial(sq.x, eps)
                key = None if eps is None else (tuple(sq.x), eps)
                gs, bs, _ = optimise_ideal(sim, p, init, key)
                pr = sim.probs(gs, bs, init)
                out.append({"sp_id": sp.meta["sp_id"], "tasks": sp.t, "mixer": mixer, "p": p, "start": name,
                            "sqa_found_opt": int(sqa_opt), "p_opt": float(pr[opt].sum()),
                            "p_sqa_answer": float(pr[sq_idx]),
                            "stuck_on_sqa": int((not sqa_opt) and pr[sq_idx] > pr[opt].sum())})
    return out


# ------------------------------------------------------------------------------- market (UB only)
LOWER_BOUND_SOLVER = "exact"     # NOT configurable: an inexact sub-problem answer invalidates the bound


def market_with_ub_solver(inst, rounds: int, solver: str, budget: int, params: dict, seed: int) -> dict:
    """Copy of core.market.run_market's loop (the market itself is untouched) where the UPPER-bound
    schedule's workflow placements come from `solver`; the LOWER bound always uses exact
    `_solve_workflow`. Returns the exact market's and this market's best bounds."""
    assert LOWER_BOUND_SOLVER == "exact"
    ref = run_market(inst, rounds=rounds)
    ev = FastEvaluator(inst)
    m, wfs = inst.m, inst.workflows()
    best_lower, best_upper, evals = -math.inf, None, 0
    for k, lam in enumerate(ref.prices):           # same price path as the exact market
        x_lb, x_ub = [0] * inst.n, [0] * inst.n
        g = 0.0
        lam_i = [int(round(v)) for v in lam]
        for w, tasks in sorted(wfs.items()):
            sub, v = _solve_workflow(ev, tasks, lam, m)            # exact -> lower bound
            g += v
            sp = SubProblem.from_workflow(inst, tasks, lam_i, ev)
            sp.set_budget(budget)
            r = SUBSOLVERS[solver](sp, seed=seed * 1000 + k * 37 + w, **params)
            evals += r.evals
            for i, t in enumerate(tasks):
                x_lb[t], x_ub[t] = sub[i], r.x[i]
        g -= sum(lam[d] * ev.cap[d] for d in range(m))
        best_lower = max(best_lower, g)
        ub = ev.score(repair(ev, x_ub))
        best_upper = ub if best_upper is None else min(best_upper, ub)
    return {"exact_lower": ref.best_lower, "exact_upper": ref.best_upper, "exact_gap": ref.gap,
            "lower": best_lower, "upper": best_upper, "gap": (best_upper - best_lower) / best_upper,
            "ub_solver_evals": evals}


# ------------------------------------------------------------------------------- figures
GROUPS = [("classical", ["sa"]), ("quantum-inspired", ["sqa", "sb_ballistic", "sb_discrete"]),
          ("quantum algorithm, classically simulated", ["qaoa_ring", "qaoa_complete"]),
          ("ideal-angle QAOA (optimistic upper bound)", ["qaoa_ring_ideal", "qaoa_complete_ideal"])]
SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]     # default categorical slots 1-4, fixed order
MARKERS = ["o", "s", "^", "D"]


def make_figures(summary: list[dict], out: Path) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    files = []
    S = {(r["method"], r["budget"]): r for r in summary}
    budgets = sorted({r["budget"] for r in summary})
    for metric, lo, hi, ylabel, fname in [
            ("gap_mean", "gap_ci_lo", "gap_ci_hi", "mean normalised gap (lower is better)", "fig_gap.png"),
            ("p_opt", "p_opt_ci_lo", "p_opt_ci_hi", "P(optimum) (higher is better)", "fig_popt.png")]:
        fig, axes = plt.subplots(1, 4, figsize=(15, 3.8), sharey=True)
        fig.patch.set_facecolor("#fcfcfb")
        for ax, (title, methods) in zip(axes, GROUPS):
            ax.set_facecolor("#fcfcfb")
            if all(("random", B) in S for B in budgets):
                ax.plot(budgets, [S[("random", B)][metric] for B in budgets], color="#8a8985", lw=1.5,
                        ls="--", label="random (sanity baseline)")
            for i, meth in enumerate(methods):
                if not all((meth, B) in S for B in budgets):
                    continue
                y = [S[(meth, B)][metric] for B in budgets]
                ax.fill_between(budgets, [S[(meth, B)][lo] for B in budgets], [S[(meth, B)][hi] for B in budgets],
                                color=SERIES_COLORS[i], alpha=0.15, lw=0)
                ax.plot(budgets, y, color=SERIES_COLORS[i], lw=2, marker=MARKERS[i], ms=6, label=meth,
                        markeredgecolor="#fcfcfb", markeredgewidth=1.5)
            ax.set_xscale("log", base=2)
            ax.set_xticks(budgets, [str(b) for b in budgets])
            ax.set_title(title, fontsize=9, color="#0b0b0b")
            ax.set_xlabel("budget B (energy evaluations)", fontsize=8, color="#52514e")
            ax.grid(True, color="#e6e5e0", lw=0.6)
            ax.tick_params(colors="#52514e", labelsize=8)
            for s in ("top", "right"):
                ax.spines[s].set_visible(False)
            for s in ("left", "bottom"):
                ax.spines[s].set_color("#c3c2b7")
            ax.legend(fontsize=7, frameon=False, labelcolor="#0b0b0b")
        axes[0].set_ylabel(ylabel, fontsize=8, color="#52514e")
        fig.suptitle("Phase 2 sub-problems, test set: " + ylabel.split(" (")[0] +
                     " vs budget, mean over sub-problems, 95% bootstrap CI (classical simulation; no hardware)",
                     fontsize=9, color="#0b0b0b")
        fig.tight_layout()
        fig.savefig(out / fname, dpi=150)
        plt.close(fig)
        files.append(fname)
    return files


# ------------------------------------------------------------------------------- main
def run(config_path: str = "config/quantum_bench.yaml", smoke: bool = False, out_dir: str | None = None,
        workers: int | None = None, log=print) -> dict:
    cfg = yaml.safe_load(open(config_path, encoding="utf-8"))
    base_cfg = yaml.safe_load(open(cfg["base_config"], encoding="utf-8"))
    out = Path(out_dir or cfg["output_dir"])
    out.mkdir(parents=True, exist_ok=True)
    if workers is None:
        workers = cfg.get("workers", 0) or min(4, os.cpu_count() or 1)
    t_start = time.perf_counter()
    budgets = SMOKE["budgets"] if smoke else cfg["budgets"]
    n_seeds = SMOKE["run_seeds"] if smoke else cfg["run_seeds"]
    cfg = dict(cfg, budgets=budgets)

    # 1. frozen sub-problem sets
    test_sps = build_subproblems(cfg, base_cfg, cfg["subproblems"]["test_seeds"],
                                 SMOKE["max_test"] if smoke else None)
    log(f"[1] test sub-problems: {len(test_sps)} (manifest {manifest_hash(test_sps)[:18]}...)")

    # 2. tuning on tuning instances only, frozen before the test run
    if smoke:
        tuned = {m: {B: dict(mc["grid"][0]) for B in budgets} for m, mc in cfg["methods"].items()}
        tuning_rows, tune_sps = [], []
    else:
        tune_sps = build_subproblems(cfg, base_cfg, cfg["subproblems"]["tuning_seeds"],
                                     cfg["tuning"]["max_subproblems"])
        log(f"[2] tuning on {len(tune_sps)} tuning sub-problems ...")
        tuned, tuning_rows = tune(cfg, tune_sps, workers)
        write_csv(out / "tuning.csv", tuning_rows, RAW_COLUMNS)
    (out / "tuning.json").write_text(json.dumps({m: {str(B): p for B, p in v.items()} for m, v in tuned.items()},
                                                indent=2), encoding="utf-8")
    log(f"[2] tuned parameters frozen -> {out / 'tuning.json'}")

    manifest = {
        "plan": "docs/plans/PHASE2_QUANTUM.md §3", "config": config_path, "smoke": smoke,
        "budget_unit": "energy evaluations (SubProblem counter); wall-clock is secondary",
        "budgets": budgets, "run_seeds": list(range(n_seeds)),
        "test_manifest_hash": manifest_hash(test_sps),
        "tuning_manifest_hash": manifest_hash(tune_sps) if tune_sps else None,
        "test_subproblems": [{"sp_id": sp.meta["sp_id"], "hash": sp.sp_hash(), "tasks": sp.t,
                              "qubits": sp.n_qubits, "states": sp.n_states, "lam": sp.lam} for sp in test_sps],
        "tuning_subproblems": [{"sp_id": sp.meta["sp_id"], "hash": sp.sp_hash()} for sp in tune_sps],
        "tuned_params": {m: {str(B): p for B, p in v.items()} for m, v in tuned.items()},
        "labels": {m: LABEL[m] for m in cfg["methods"]},
        "environment": {"python": sys.version.split()[0], "numpy": np.__version__,
                        "platform": platform.platform(), "workers": workers},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # 3. test run: every method x every sub-problem x every budget x every seed
    specs = [(m, None, tuned[m]) for m in cfg["methods"]]
    log(f"[3] test run: {len(specs)} methods x {len(test_sps)} sub-problems x {len(budgets)} budgets "
        f"x {n_seeds} seeds ...")
    rows = run_all([(sp, specs, budgets, list(range(n_seeds))) for sp in test_sps], workers)
    write_csv(out / "raw.csv", rows, RAW_COLUMNS)
    summary = sorted(summarise(rows), key=lambda r: (r["budget"], list(cfg["methods"]).index(r["method"])))
    write_csv(out / "summary.csv", summary, SUMMARY_COLUMNS)
    by_size = sorted(summarise(rows, ("tasks",)), key=lambda r: (r["tasks"], r["budget"], r["method"]))
    write_csv(out / "summary_by_size.csv", by_size, ["tasks"] + SUMMARY_COLUMNS)
    cvs = classical_vs(rows) if "sa" in cfg["methods"] else []
    if cvs:
        write_csv(out / "classical_vs.csv", cvs)
    result = {"out": str(out), "n_test": len(test_sps), "n_rows": len(rows), "summary": summary,
              "classical_vs": cvs}

    # 4. design questions
    if not smoke and cfg.get("design", {}).get("enabled"):
        dc = cfg["design"]
        dsp = test_sps[:dc["max_subproblems"]]
        log(f"[4] design questions on {len(dsp)} sub-problems ...")
        write_csv(out / "design_ring_vs_complete.csv", design_ring_vs_complete(dsp, dc["depths"]))
        write_csv(out / "design_param_reuse.csv", design_param_reuse(dsp))
        sqa_params = tuned["sqa"].get(dc["warm_sqa_budget"], {})
        write_csv(out / "design_warm_start.csv",
                  design_warm_start(dsp, dc["warm_eps"], dc["warm_p"], dc["warm_sqa_budget"], sqa_params))

    # 5. QAOA as the market's upper-bound solver (lower bound stays exact)
    if not smoke and cfg.get("market", {}).get("enabled"):
        mc = cfg["market"]
        log(f"[5] market with {mc['solver']} as upper-bound solver, seeds {mc['seeds']} ...")
        mrows = []
        for s in mc["seeds"]:
            inst = generate_instance(base_cfg, s)
            params = tuned[mc["solver"]].get(mc["budget"], {})
            r = market_with_ub_solver(inst, mc["rounds"], mc["solver"], mc["budget"], params, s)
            mrows.append({"inst_seed": s, "ub_solver": mc["solver"], "label": LABEL[mc["solver"]],
                          "lower_bound_solver": LOWER_BOUND_SOLVER, "budget_per_subproblem": mc["budget"], **r})
        write_csv(out / "market.csv", mrows)
        result["market"] = mrows

    if not smoke:
        result["figures"] = make_figures(summary, out)
    result["elapsed_s"] = time.perf_counter() - t_start
    log(f"[done] {len(rows)} test runs in {result['elapsed_s']:.1f}s -> {out}")
    return result


def print_summary(summary: list[dict]) -> None:
    print(f"{'budget':>6}  {'method':22s} {'label':58s} {'P(opt)':>7} {'gap':>7}  95% CI gap")
    for r in summary:
        print(f"{r['budget']:>6}  {r['method']:22s} {r['label']:58s} {r['p_opt']:7.3f} {r['gap_mean']:7.4f}"
              f"  [{r['gap_ci_lo']:.4f}, {r['gap_ci_hi']:.4f}]")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", default="config/quantum_bench.yaml")
    ap.add_argument("--smoke", action="store_true", help="2 sub-problems x 2 seeds x B=16, no tuning")
    ap.add_argument("--out", default=None)
    ap.add_argument("--workers", type=int, default=None)
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    res = run(a.config, a.smoke, a.out, a.workers)
    print_summary(res["summary"])


if __name__ == "__main__":
    main()
