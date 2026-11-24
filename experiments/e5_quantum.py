"""E5 — quantum sub-problem results, taken from Phase 2 (NOT re-run; docs/plans/PHASE6_EVALUATION.md §1).

Reads the outputs of `python -m experiments.quantum_benchmark` (default results/quantum/; `e5.source` in
config/eval.yaml) and writes three tables into the evaluation folder, each row with its source file:

  quantum_summary.csv       per method x budget: P(optimum) and mean gap with 95 % bootstrap CIs (324 sub-problems)
  quantum_classical_vs.csv  share of sub-problems where classical SA matches / strictly beats each method
  quantum_market.csv        dual market with a quantum(-inspired) upper-bound solver vs exact sub-problem solves

Honest labels (AGENTS.md rule 5): SA classical; SQA and SB quantum-inspired; QAOA = quantum algorithm, classically
simulated ("ideal angles" rows are an optimistic upper bound, not a runnable method). No quantum-advantage claim.
Without the Phase 2 results every table is a single "NOT RUN - Phase 2 results missing" row.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from experiments.eval_common import ROOT, STATUS_OK, Context, ExpResult, read_csv, sha256_file, write_csv

E5_MISSING = "NOT RUN - Phase 2 results missing"
SOURCES = {"quantum_summary.csv": "summary.csv", "quantum_classical_vs.csv": "classical_vs.csv",
           "quantum_market.csv": "market.csv"}
SUMMARY_COLUMNS = ["method", "label", "budget", "n_subproblems", "n_runs", "p_opt", "p_opt_ci_lo", "p_opt_ci_hi",
                   "gap_mean", "gap_ci_lo", "gap_ci_hi", "gap_median", "feasible_rate", "wall_s_mean", "source",
                   "status"]
VS_COLUMNS = ["budget", "method", "label", "n_subproblems", "sa_matches_or_beats", "sa_strictly_beats", "source",
              "status"]
MARKET_COLUMNS = ["inst_seed", "ub_solver", "label", "lower_bound_solver", "budget_per_subproblem", "exact_lower",
                  "exact_upper", "exact_gap", "lower", "upper", "gap", "ub_solver_evals", "source", "status"]
COLUMNS = {"quantum_summary.csv": SUMMARY_COLUMNS, "quantum_classical_vs.csv": VS_COLUMNS,
           "quantum_market.csv": MARKET_COLUMNS}


def source_dir(ctx: Context) -> Path:
    p = Path(ctx.eval_cfg.get("e5", {}).get("source", "results/quantum"))
    return p if p.is_absolute() else ROOT / p


def run_e5(ctx: Context) -> ExpResult:
    src = source_dir(ctx)
    missing = [f for f in SOURCES.values() if not (src / f).is_file()]
    files = list(SOURCES)
    if missing:
        note = f"missing {', '.join(missing)} in {src}; run python -m experiments.quantum_benchmark"
        for out, cols in COLUMNS.items():
            write_csv(ctx.out / out, [{"status": E5_MISSING, "source": str(src)}], cols)
        return ExpResult(files, [{"experiment": "E5", "item": "quantum sub-problem results (Phase 2)",
                                  "status": E5_MISSING, "note": note}], {"status": E5_MISSING})
    for out, name in SOURCES.items():
        rel = (src / name).relative_to(ROOT).as_posix() if src.is_relative_to(ROOT) else str(src / name)
        rows = [{**r, "source": rel, "status": STATUS_OK} for r in read_csv(src / name)]
        write_csv(ctx.out / out, rows, COLUMNS[out])
    summ = read_csv(src / "summary.csv")
    best: dict[str, Any] = {}
    for r in summ:
        b = int(r["budget"])
        if "ideal" in r["method"] or r["method"] == "random":
            continue
        if b not in best or float(r["p_opt"]) > best[b]["p_opt"]:
            best[b] = {"method": r["method"], "label": r["label"], "p_opt": float(r["p_opt"])}
    manifest = src / "manifest.json"
    return ExpResult(files, [], {
        "source": str(src), "source_manifest_sha256": sha256_file(manifest) if manifest.is_file() else None,
        "budgets": sorted({int(r["budget"]) for r in summ}), "methods": sorted({r["method"] for r in summ}),
        "n_subproblems": int(summ[0]["n_subproblems"]) if summ else 0,
        "highest_p_opt_per_budget (runnable methods)": {str(k): v for k, v in sorted(best.items())},
        "note": "Phase 2 results, not re-run; QAOA classically simulated; no quantum-advantage claim"})
