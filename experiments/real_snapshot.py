"""Phase 1 real-snapshot experiment (docs/plans/PHASE1_REAL_DATA.md).

    python -m experiments.real_snapshot              # -> results/real_snapshot/

1. Full 7-step pipeline (in-memory chain) on config/real_snapshot.yaml: real Alibaba DAGs (sample seed 7) over the
   2024-10-15T12:00Z carbon/price snapshot.
2. 2 x 2 attribution, off-chain (same solvers/settings as the demo): workload {synthetic, real Alibaba} x region
   inputs {illustrative (demo.yaml), real snapshot} -> which change moves the results.
3. Score decomposition of the baseline and the winner: task energy terms vs network (edge) terms.
4. Sensitivity (only with the raw files present): carbon basis LCA instead of direct; IEX overlap-weighted price.

Honest labels: greedy/SA classical, SQA quantum-inspired, dual-market = Lagrangian decomposition (classical).
Region values: Electricity Maps (academic licence, cite; docs/DATA_SOURCES.md), ENTSO-E, EM API, IEX, ECB.
capacity_share, watts_per_core and the network model remain ILLUSTRATIVE; edge volumes are ESTIMATED.
Without data/processed/ the experiment prints "NOT RUN - data missing" and exits 0.
"""
from __future__ import annotations

import argparse
import copy
import csv
import dataclasses
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

import yaml

from core.data.snapshot import compute, data_present
from core.instance import Instance, build_instance, workload_path
from core.market import run_market
from core.scoring import evaluate, round_robin_baseline
from core.solvers import KIND, SOLVERS

ROOT = Path(__file__).resolve().parents[1]
DATA_MISSING = "NOT RUN - data missing"


def load(p: str | Path) -> dict[str, Any]:
    return yaml.safe_load((ROOT / p).read_text(encoding="utf-8"))


def solve_all(inst: Instance, cfg: dict[str, Any]) -> dict[str, Any]:
    """Off-chain: baseline + every solver + dual market (as demo/pipeline.py step 2)."""
    rows: dict[str, Any] = {}
    x0 = round_robin_baseline(inst)
    rows["baseline"] = (x0, evaluate(inst, x0), "baseline")
    for name, fn in SOLVERS.items():
        x, _ = fn(inst, seed=cfg["seed"], **cfg["solvers"].get(name, {}))
        rows[name] = (x, evaluate(inst, x), KIND[name])
    mk = run_market(inst, **cfg["market"])
    rows["dual-market"] = (mk.best_schedule, evaluate(inst, mk.best_schedule), "decomposition")
    best = min((k for k in rows if k != "baseline"), key=lambda k: rows[k][1].score)
    return {"rows": rows, "lb": mk.best_lower, "best": best}


def decompose(inst: Instance, x: list[int]) -> dict[str, float]:
    """Score split: task terms (edges removed) vs network terms (the rest)."""
    task_only = evaluate(dataclasses.replace(inst, edges=[]), x)
    full = evaluate(inst, x)
    return {"task_score_share": task_only.score / full.score if full.score else 0.0,
            "network_score_share": 1 - task_only.score / full.score if full.score else 0.0,
            "task_carbon_g": task_only.carbon_ug / 1e6, "network_carbon_g": (full.carbon_ug - task_only.carbon_ug) / 1e6}


def workload_stats(inst: Instance, file_meta: dict[str, Any] | None = None) -> dict[str, Any]:
    e = sorted(t.energy_wh for t in inst.tasks)
    extra = {}
    if file_meta:                        # real trace: exact energy before the 1 Wh integer floor
        d = sorted(file_meta["duration_s"])
        extra = {"exact_task_energy_wh": file_meta["exact_task_energy_wh"],
                 "tasks_below_1wh": file_meta["tasks_below_1wh"], "median_duration_s": d[len(d) // 2],
                 "max_duration_s": d[-1], "energy_floor_note": file_meta["energy_floor_note"]}
    return {**extra, "tasks": inst.n, "workflows": len(inst.workflows()), "edges": len(inst.edges),
            "total_cpu": sum(t.cpu for t in inst.tasks), "total_task_energy_wh": sum(e),
            "median_task_energy_wh": e[len(e) // 2], "max_task_energy_wh": e[-1],
            "total_edge_volume_mb": sum(ed.volume_mb for ed in inst.edges)}


def cell(inst: Instance, cfg: dict[str, Any], workload: str, regions: str) -> dict[str, Any]:
    r = solve_all(inst, cfg)
    base, best = r["rows"]["baseline"][1], r["rows"][r["best"]][1]
    out = {"workload": workload, "regions": regions, "tasks": inst.n, "baseline_carbon_g": base.carbon_ug / 1e6,
           "baseline_cost_usd": base.cost_nusd / 1e9, "winner": r["best"], "winner_kind": r["rows"][r["best"]][2],
           "winner_carbon_g": best.carbon_ug / 1e6, "winner_cost_usd": best.cost_nusd / 1e9,
           "carbon_reduction_pct": 100 * (base.carbon_ug - best.carbon_ug) / base.carbon_ug,
           "certified_gap_pct": 100 * (best.score - r["lb"]) / best.score,
           "baseline_network_score_share": decompose(inst, r["rows"]["baseline"][0])["network_score_share"],
           "winner_network_score_share": decompose(inst, r["rows"][r["best"]][0])["network_score_share"]}
    for k, (_, ev, _) in r["rows"].items():
        out[f"score_{k}"] = ev.score
    return out


def run(out_dir: Path, log=print) -> dict[str, Any]:
    t0 = time.perf_counter()
    demo_cfg, real_cfg = load("config/demo.yaml"), load("config/real_snapshot.yaml")
    wl = workload_path(real_cfg)
    if not wl.is_file():
        log(f"[real] {DATA_MISSING}: {wl} (run scripts/load_alibaba_dags.py)")
        return {"status": DATA_MISSING}
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1 full pipeline on the real config (seeded salts -> reproducible gas)
    from demo.pipeline import run as run_pipeline
    rng = random.Random(0)
    lines: list[str] = []
    res = run_pipeline(copy.deepcopy(real_cfg), log=lines.append, salt_fn=lambda: rng.randbytes(32))
    for ln in lines:
        log("  " + ln)
    fin = res["final"]

    # 2 attribution 2 x 2 (off-chain)
    real_inst = build_instance(real_cfg, real_cfg["seed"])
    synth_cfg_real_regions = copy.deepcopy(demo_cfg)
    synth_cfg_real_regions["regions"] = real_cfg["regions"]
    real_wl_demo_regions = copy.deepcopy(real_cfg)
    real_wl_demo_regions["regions"] = demo_cfg["regions"]
    cells = [
        cell(build_instance(demo_cfg, 7), demo_cfg, "synthetic", "illustrative"),
        cell(build_instance(synth_cfg_real_regions, 7), synth_cfg_real_regions, "synthetic", "real snapshot"),
        cell(build_instance(real_wl_demo_regions, 7), real_wl_demo_regions, "real Alibaba", "illustrative"),
        cell(real_inst, real_cfg, "real Alibaba", "real snapshot"),
    ]
    cols = list(cells[0])
    with (out_dir / "attribution.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(cells)

    # 3 regions table (derived snapshot inputs only) + 4 sensitivity
    regions = [{"name": r["name"], "ci_g_per_kwh": r["ci_g_per_kwh"], "price_uusd_per_kwh": r["price_uusd_per_kwh"],
                "price_eur_per_mwh": round(r["price_uusd_per_kwh"] / 1000 / float(real_cfg["snapshot"]["fx"]["usd_per_eur"]), 2)}
               for r in real_cfg["regions"]]
    sensitivity: list[dict[str, Any]] = []
    if data_present(real_cfg["snapshot"], ROOT):
        for label, kw in (("carbon basis LCA", {"basis": "lca"}), ("IEX overlap-weighted price", {"iex_align": "overlap"})):
            snap = compute(real_cfg["snapshot"], ROOT, **kw)
            c2 = copy.deepcopy(real_cfg)
            by = {s.name: s for s in snap}
            for r in c2["regions"]:
                r["ci_g_per_kwh"], r["price_uusd_per_kwh"] = by[r["name"]].ci_g_per_kwh, by[r["name"]].price_uusd_per_kwh
            row = cell(build_instance(c2, 7), c2, "real Alibaba", label)
            row["region_values"] = {s.name: [s.ci_g_per_kwh, s.price_uusd_per_kwh] for s in snap}
            sensitivity.append(row)
    else:
        sensitivity.append({"status": DATA_MISSING, "note": "raw snapshot files absent; committed values used"})
    # D1 sensitivity: option (c) "1 Wh floor" (one representative instance per task) vs the approved instance_num
    floor_cfg = copy.deepcopy(real_cfg)
    floor_cfg["workload"]["task_size"] = "representative"
    floor_inst = build_instance(floor_cfg, 7)
    sensitivity.append(cell(floor_inst, floor_cfg, "real Alibaba", "1 Wh floor (D1 option (c))"))

    summary = {
        "experiment": "Phase 1 real snapshot", "snapshot_hour": real_cfg["snapshot"]["hour"],
        "carbon_basis": real_cfg["snapshot"]["carbon_basis"], "fx": real_cfg["snapshot"]["fx"],
        "workload_file": wl.name, "task_size": real_inst.meta.get("task_size"),
        "workload": workload_stats(real_inst, json.loads(wl.read_text(encoding="utf-8"))["meta"]),
        "workload_1wh_floor": workload_stats(floor_inst),
        "synthetic_workload": workload_stats(build_instance(demo_cfg, 7)),
        "regions": regions, "instance_hash": res["instance"]["instance_hash"],
        "pipeline": {k: fin[k] for k in ("winner", "baseline_carbon_g", "best_carbon_g", "reduction_pct", "overhead_g",
                                         "net_saving_g", "credits_minted", "certified_gap_pct", "total_gas")},
        "reveals": [{"agent": r["agent"], "status": r["status"], "score": r.get("score")} for r in res["reveals"]],
        "decomposition_winner": decompose(real_inst, res["_best"]),
        "attribution": cells, "sensitivity": sensitivity,
        "labels": {"greedy": "classical", "sa": "classical", "sqa": "quantum-inspired",
                   "dual-market": "decomposition (classical)"},
        "illustrative_inputs": ["capacity_share", "watts_per_core", "network.energy_mwh_per_mb",
                                "network.egress_nusd_per_mb", "edge volumes (estimated)"],
        "runtime_s": round(time.perf_counter() - t0, 1),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    log(f"[real] snapshot {summary['snapshot_hour']}: " + ", ".join(
        f"{r['name'].split(' ')[0]} {r['ci_g_per_kwh']} g/kWh {r['price_eur_per_mwh']} EUR/MWh" for r in regions))
    log(f"[real] workload: {summary['workload']['tasks']} tasks / {summary['workload']['edges']} edges, "
        f"{summary['workload']['total_cpu']} cores, {summary['workload']['total_task_energy_wh']} Wh task energy "
        f"(task_size {summary['task_size']}: cores and energy x instance_num; D1). Option (c) 1 Wh floor: "
        f"{summary['workload_1wh_floor']['total_task_energy_wh']} Wh (exact one-instance energy "
        f"{summary['workload']['exact_task_energy_wh']:.2f} Wh; {summary['workload']['tasks_below_1wh']} of "
        f"{summary['workload']['tasks']} tasks below 1 Wh; median duration {summary['workload']['median_duration_s']} s) "
        f"(synthetic demo: "
        f"{summary['synthetic_workload']['total_task_energy_wh']} Wh)")
    for c in cells:
        log(f"[real] {c['workload']:13s} x {c['regions']:13s}: winner {c['winner']:11s} carbon "
            f"{c['baseline_carbon_g']:7.1f} -> {c['winner_carbon_g']:6.1f} g ({c['carbon_reduction_pct']:4.1f}% lower), "
            f"gap <= {c['certified_gap_pct']:4.1f}%, network share of winner score {100 * c['winner_network_score_share']:4.1f}%")
    for s in sensitivity:
        if "winner" in s:
            log(f"[real] sensitivity {s['regions']}: winner {s['winner']} carbon {s['baseline_carbon_g']:.1f} -> "
                f"{s['winner_carbon_g']:.1f} g ({s['carbon_reduction_pct']:.1f}% lower)")
    log(f"[real] wrote {out_dir} ({summary['runtime_s']} s)")
    return summary


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "results" / "real_snapshot"))
    run(Path(ap.parse_args(argv).out))


if __name__ == "__main__":
    main()
