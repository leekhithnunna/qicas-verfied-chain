r"""Alibaba cluster-trace-v2018 batch_task -> processed DAG workloads (local only; never committed).

    .\.venv\Scripts\python.exe scripts\load_alibaba_dags.py                      # seeds 0-9 (E4) + 7 (config)
    .\.venv\Scripts\python.exe scripts\load_alibaba_dags.py --seeds 7 --n-workflows 8

Writes data/processed/alibaba_dags_seed{S}_n{N}.json for every seed: {"tasks", "edges", "meta"} with only the
core.instance Task/Edge fields; meta records the raw SHA-256, filter counts, limits, sampled job names.
Two streaming passes over the ~14 M-row trace (~70 s each). Licence: research/study use; no redistribution
clause -> the output stays in git-ignored data/processed/ (docs/DATA_SOURCES.md, A).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from core.data import sha256_file  # noqa: E402
from core.data.alibaba import Limits, collect_jobs, sample_names, scan_eligible, to_workload  # noqa: E402

OFFICIAL_SHA256 = "7c4b32361bd1ec2083647a8f52a6854a03bc125ca5c202652316c499fbf978c6"


def parse_seeds(s: str) -> list[int]:
    out: list[int] = []
    for part in s.split(","):
        a, _, b = part.strip().partition("-")
        out += list(range(int(a), int(b) + 1)) if b else [int(a)]
    return sorted(set(out))


def build(raw: Path, seeds: list[int], n: int, cfg: dict, lim: Limits, out_dir: Path, log=print) -> list[Path]:
    digest = sha256_file(raw)
    log(f"[alibaba] raw {raw} sha256 {digest}" + ("" if digest == OFFICIAL_SHA256 or raw.suffix == ".csv"
                                                   else "  (WARNING: differs from the official checksum)"))
    t0 = time.perf_counter()
    eligible, counts = scan_eligible(raw, lim)
    log(f"[alibaba] pass 1: {counts['jobs_seen']:,} jobs, {counts['eligible']:,} eligible "
        f"({time.perf_counter() - t0:.0f} s); drops: "
        + ", ".join(f"{k}={v:,}" for k, v in counts.items() if k not in ("jobs_seen", "eligible") and v))
    samples = {s: sample_names(eligible, n, s) for s in seeds}
    t0 = time.perf_counter()
    jobs = collect_jobs(raw, {j for names in samples.values() for j in names}, lim)
    log(f"[alibaba] pass 2: collected {len(jobs)} jobs ({time.perf_counter() - t0:.0f} s)")
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for s, names in samples.items():
        meta = {"source": "Alibaba Cluster Trace Program, cluster-trace-v2018, batch_task",
                "raw_file": raw.name, "raw_sha256": digest, "filter_counts": counts,
                "limits": {"min_tasks": lim.min_tasks, "max_tasks": lim.max_tasks, "max_cpu": lim.max_cpu},
                "n_workflows": n, "licence_note": "research/study use only; not redistributed (local file)"}
        wl = to_workload({j: jobs[j] for j in names}, s, int(cfg["watts_per_core"]),
                         tuple(cfg["volume_mb_lognormal"]), meta)
        p = out_dir / f"alibaba_dags_seed{s}_n{n}.json"
        p.write_text(json.dumps(wl, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        log(f"[alibaba] seed {s}: {len(wl['tasks'])} tasks, {len(wl['edges'])} edges, "
            f"{sum(t['cpu'] for t in wl['tasks'])} cores -> {p.relative_to(ROOT) if p.is_relative_to(ROOT) else p}")
        written.append(p)
    return written


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", default=str(ROOT / "data/raw/alibaba/batch_task.tar.gz"))
    ap.add_argument("--seeds", default="0-9", help="sample seeds, e.g. 0-9 or 7 or 0,3,7 (7 is always added)")
    ap.add_argument("--n-workflows", type=int, default=8)
    ap.add_argument("--config", default=str(ROOT / "config/real_snapshot.yaml"),
                    help="source of watts_per_core and volume_mb_lognormal")
    ap.add_argument("--min-tasks", type=int, default=3)
    ap.add_argument("--max-tasks", type=int, default=7)
    ap.add_argument("--max-cpu", type=int, default=4)
    ap.add_argument("--out-dir", default=str(ROOT / "data/processed"))
    a = ap.parse_args(argv)
    raw = Path(a.raw)
    if not raw.is_file():
        print(f"raw trace not found: {raw} (see data/raw/DOWNLOAD_CHECKLIST.md)", file=sys.stderr)
        return 2
    if a.max_tasks > 7:
        ap.error("--max-tasks must be <= 7 (the market solves each workflow exactly)")
    cfg = yaml.safe_load(Path(a.config).read_text(encoding="utf-8"))
    seeds = sorted(set(parse_seeds(a.seeds)) | {int(cfg.get("seed", 7))})
    build(raw, seeds, a.n_workflows, cfg, Limits(a.min_tasks, a.max_tasks, a.max_cpu), Path(a.out_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
