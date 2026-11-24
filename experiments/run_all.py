"""Phase 6 evaluation harness (Phase 6-lite profiles + full Phase 6 experiments E1-E6): one runner, one manifest (docs/plans/PHASE6_EVALUATION.md §1).

    python -m experiments.run_all --profile smoke     # seconds; also run inside pytest
    python -m experiments.run_all --profile lite      # Phase 6 results (several minutes; the full-Phase-6 run used it)

Outputs go to results/eval/ (or --out DIR):
  manifest.json   git commit, config + artifact SHA-256s, data snapshots (none: synthetic), seeds, package
                  versions, chain mode, experiments run / not run (with reason), output hashes, runtime
  not_run.csv     every experiment or row that could not run in this build, with the missing phase
  <experiment CSVs>  see each experiment module (E1-E6; E5 copies Phase 2 tables, E6 needs QICAS_BESU=1 + Besu)

Honest labels (AGENTS.md rule 5): greedy + SA classical; SQA quantum-inspired; dual-market = Lagrangian
decomposition (classical). Overhead parameters are a [VERIFY] illustrative grid; net carbon only as ranges.
"""
from __future__ import annotations

import argparse
import sys
import time
from importlib import import_module
from pathlib import Path
from typing import Any, Callable

from experiments.eval_common import (DATA_MISSING, PHASES_PRESENT, ROOT, Context, ExpResult, csv_hash_without_time,
                                     dump_json, git_info, load_base_config, load_eval_config, load_real_config,
                                     not_run, package_versions, phase_present, real_workloads, sha256_file,
                                     write_csv)

NOT_RUN_COLUMNS = ["experiment", "item", "status", "note"]

# id -> (title, implementation "module:function" or None, phases needed for the experiment to run at all)
EXPERIMENTS: dict[str, dict[str, Any]] = {
    "E1": {"title": "Net carbon vs overhead sensitivity (synthetic; case-study flow + Phase 3 market + Phase 4 trust "
                    "layer gas; Phase 5 PoA node term)",
           "impl": "experiments.e1_e2_overhead_gas:run_e1", "needs": []},
    "E2": {"title": "Gas vs instance size (case-study + Phase 3/4 functions)",
           "impl": "experiments.e1_e2_overhead_gas:run_e2", "needs": []},
    "E3": {"title": "Attack suite (case-study + Phase 3/4/5 layers executed)", "impl": "experiments.e3_attacks:run_e3",
           "needs": []},
    "E4": {"title": "Solver comparison (synthetic instances + Phase 1 real instances when data is present)", "impl": "experiments.e4_solvers:run_e4",
           "needs": []},
    "E5": {"title": "Quantum sub-problem results (from Phase 2 results/quantum/, not re-run)",
           "impl": "experiments.e5_quantum:run_e5", "needs": [2]},
    "E6": {"title": "Besu vs in-memory chain (Phase 5; opt-in: QICAS_BESU=1 + running network)",
           "impl": "experiments.besu_vs_memory:run_e6", "needs": [5]},
}


def _data_snapshots(eval_cfg: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """Phase 1 provenance: snapshot hour, committed raw-file SHA-256s, processed workload hashes (or data missing)."""
    real_cfg = load_real_config(eval_cfg)
    if real_cfg is None:
        return {"status": "synthetic only", "note": "no real_config in config/eval.yaml"}
    seeds = profile.get("solvers", {}).get("real_inst_seeds", [])
    present, missing = real_workloads(real_cfg, seeds)
    snap = real_cfg.get("snapshot", {})
    out = {"synthetic": "core/instance.py::generate_instance (config/demo.yaml)",
           "real_config": eval_cfg["real_config"], "snapshot_hour": snap.get("hour"),
           "carbon_basis": snap.get("carbon_basis"), "fx": snap.get("fx"),
           "raw_files_sha256_expected": {p: h for s in snap.get("sources", {}).values()
                                         for p, h in ((s[k]["path"], s[k].get("sha256")) for k in ("carbon", "price"))},
           "licence_note": "raw files git-ignored; Electricity Maps academic licence (no redistribution); "
                           "see docs/DATA_SOURCES.md"}
    if missing or not seeds:
        out.update({"status": DATA_MISSING, "missing": missing})
    else:
        out.update({"status": "ok", "workloads_sha256": {p.name: sha256_file(p) for p in present.values()}})
    return out


def _resolve(impl: str) -> Callable[[Context], ExpResult]:
    mod, fn = impl.split(":")
    return getattr(import_module(mod), fn)


def run(profile: str = "smoke", out_dir: str | Path | None = None, config: str = "config/eval.yaml",
        only: list[str] | None = None, log: Callable[[str], None] = print) -> dict[str, Any]:
    t_start = time.perf_counter()
    eval_cfg = load_eval_config(config)
    if profile not in eval_cfg["profiles"]:
        raise SystemExit(f"unknown profile {profile!r}; choose from {sorted(eval_cfg['profiles'])}")
    out = Path(out_dir) if out_dir else ROOT / "results" / "eval"
    out.mkdir(parents=True, exist_ok=True)
    ctx = Context(profile, eval_cfg["profiles"][profile], eval_cfg, load_base_config(eval_cfg), out, log)
    log(f"[eval] profile={profile} -> {out}")

    experiments: dict[str, Any] = {}
    not_run_rows: list[dict[str, str]] = []
    files: list[str] = []
    for eid, spec in EXPERIMENTS.items():
        if only and eid not in only:
            experiments[eid] = {"title": spec["title"], "status": "not selected (--only)"}
            continue
        missing = [p for p in spec["needs"] if not phase_present(p)]
        if missing:
            status = not_run(missing[0])
            not_run_rows.append({"experiment": eid, "item": spec["title"], "status": status,
                                 "note": "whole experiment"})
            experiments[eid] = {"title": spec["title"], "status": status}
            log(f"[{eid}] {status}")
            continue
        if spec.get("scope"):
            not_run_rows.append({"experiment": eid, "item": spec["title"], "status": "NOT RUN - out of scope",
                                 "note": spec["scope"]})
            experiments[eid] = {"title": spec["title"], "status": "NOT RUN - out of scope", "note": spec["scope"]}
            log(f"[{eid}] NOT RUN - out of scope: {spec['scope']}")
            continue
        if spec["impl"] is None:
            status = "NOT RUN - not implemented in this build"
            not_run_rows.append({"experiment": eid, "item": spec["title"], "status": status, "note": ""})
            experiments[eid] = {"title": spec["title"], "status": status}
            log(f"[{eid}] {status}")
            continue
        t0 = time.perf_counter()
        log(f"[{eid}] {spec['title']} ...")
        res = _resolve(spec["impl"])(ctx)
        dt = time.perf_counter() - t0
        files += res.files
        not_run_rows += res.not_run
        experiments[eid] = {"title": spec["title"], "status": "run", "files": res.files,
                            "rows_not_run": len(res.not_run), "summary": res.summary, "runtime_s": round(dt, 2)}
        log(f"[{eid}] done in {dt:.1f} s -> {', '.join(res.files)}")

    write_csv(out / "not_run.csv", not_run_rows, NOT_RUN_COLUMNS)
    files.append("not_run.csv")
    runtime = time.perf_counter() - t_start
    manifest = {
        "harness": "experiments/run_all.py (Phase 6)",
        "profile": profile,
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "runtime_s": round(runtime, 2),
        "git": git_info(),
        "environment": package_versions(),
        "configs_sha256": {c: sha256_file(ROOT / c) for c in (config, eval_cfg["base_config"])},
        "contract_artifact_sha256": sha256_file(ROOT / "chain" / "build" / "CarbonScheduleMarket.json"),
        "data_snapshots": _data_snapshots(eval_cfg, ctx.profile),
        "chain_mode": {"mode": "memory (eth-tester + py-evm); E6 also Besu QBFT when opted in",
                       "besu_image": "hyperledger/besu:26.10.2@sha256:bc599f5ef95a3d5d03f966cd2c1f7dfd7353834c84bc5651ffb4af884860a2c7",
                       "measurement_block_gas_limit": eval_cfg["chain"]["measurement_block_gas_limit"],
                       "reference_block_gas_limit": eval_cfg["chain"]["reference_block_gas_limit"],
                       "note": "block limit raised only so large instances can be measured; every result "
                               "is compared against the reference limit afterwards"},
        "profile_settings": ctx.profile,
        "overhead_grid": {**eval_cfg["overhead_grid"],
                          "label": "[VERIFY] illustrative grid, no sources; net carbon reported as ranges"},
        "poa_node_term": {**eval_cfg.get("poa_node_term", {}),
                          "label": "[VERIFY] illustrative node power / hours per epoch (Phase 5); ranges only"},
        "phases_present": {str(k): v for k, v in PHASES_PRESENT.items()},
        "honest_labels": {"greedy": "classical", "sa": "classical", "sqa": "quantum-inspired",
                          "dual-market": "decomposition (classical Lagrangian)"},
        "experiments": experiments,
        "not_run": not_run_rows,
        "outputs": {f: {"sha256": sha256_file(out / f),
                        "sha256_without_time_columns": csv_hash_without_time(out / f)}
                    for f in sorted(set(files)) if f.endswith(".csv")},
    }
    dump_json(out / "manifest.json", manifest)
    log(f"[eval] finished in {runtime:.1f} s; {len(not_run_rows)} NOT RUN rows; manifest.json written")
    return manifest


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", choices=["smoke", "lite"], default="smoke")
    ap.add_argument("--out", default=None, help="output directory (default results/eval/)")
    ap.add_argument("--config", default="config/eval.yaml")
    ap.add_argument("--only", default="", help="comma-separated subset, e.g. E1,E2")
    a = ap.parse_args(argv)
    run(a.profile, a.out, a.config, [s.strip() for s in a.only.split(",") if s.strip()] or None)


if __name__ == "__main__":
    main()
