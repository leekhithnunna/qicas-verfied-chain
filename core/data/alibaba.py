"""Alibaba cluster-trace-v2018 `batch_task` -> small integer DAG workload (docs/plans/PHASE1_REAL_DATA.md §2.1).

Input rows (no header): task_name, instance_num, job_name, task_type, status, start_time, end_time, plan_cpu,
plan_mem. Dependencies are encoded in task names: `R5_2_3` = task 5 depends on tasks 2 and 3; `M1` = task 1, no
parents. Names such as `task_xyz` or `MergeTask` carry no dependency information -> the whole job is dropped.

Streaming: rows of one job are contiguous in the trace, so jobs are validated one at a time and the ~14 M rows
never sit in memory. A job that re-appears after another job started is dropped ("non_contiguous").

Pass 1 (`scan_eligible`) returns the sorted eligible job names + drop counts; sampling is
`random.Random(seed).sample(sorted_names, n)`; pass 2 (`collect_jobs`) re-reads only the sampled jobs.
Same raw file + seed => byte-identical processed JSON.
"""
from __future__ import annotations

import csv
import io
import math
import random
import re
import tarfile
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable, Iterator

TASK_NAME_RE = re.compile(r"^([A-Za-z]+)(\d+)((?:_\d+)*)$")
DROP_REASONS = ("bad_task_name", "status", "time", "too_few_tasks", "too_many_tasks", "duplicate_task",
                "missing_parent", "cycle", "no_plan_cpu", "too_many_cores", "non_contiguous")


def parse_task_name(name: str) -> tuple[int, list[int]] | None:
    """`M1` -> (1, []); `R5_2_3` -> (5, [2, 3]); `task_xyz` -> None."""
    m = TASK_NAME_RE.match(name.strip())
    if not m:
        return None
    parents = [int(p) for p in m.group(3).split("_") if p]
    return int(m.group(2)), parents


@dataclass(frozen=True)
class RawTask:
    name: str
    tid: int
    parents: tuple[int, ...]
    instance_num: int
    start: int
    end: int
    cpu: int            # whole cores = ceil(plan_cpu / 100)


@dataclass(frozen=True)
class Limits:
    min_tasks: int = 3
    max_tasks: int = 7          # market solves each workflow exactly (<= 7 tasks)
    max_cpu: int = 4


# ------------------------------------------------------------------------------------------- reading
def open_rows(path: str | Path) -> Iterator[list[str]]:
    """Yield CSV rows from a plain .csv or a .tar.gz containing batch_task.csv (streamed)."""
    p = Path(path)
    if p.name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(p, "r:gz") as tar:
            member = next((m for m in tar.getmembers() if m.isfile() and m.name.endswith(".csv")), None)
            if member is None:
                raise ValueError(f"{p}: no .csv member in archive")
            f = tar.extractfile(member)
            assert f is not None
            yield from csv.reader(io.TextIOWrapper(f, encoding="utf-8", newline=""))
    else:
        with p.open("r", encoding="utf-8", newline="") as f:
            yield from csv.reader(f)


def iter_jobs(rows: Iterable[list[str]], counts: Counter,
              bad: set[str] | None = None) -> Iterator[tuple[str, list[list[str]]]]:
    """Group contiguous rows by job_name. A job that re-appears later is added to `bad`; its first chunk may
    already have been yielded, so callers must discard every name in `bad` after the full pass."""
    seen: set[str] = set()
    bad = set() if bad is None else bad
    cur: str | None = None
    buf: list[list[str]] = []
    for row in rows:
        if len(row) < 9:
            counts["malformed_rows"] += 1
            continue
        job = row[2]
        if job != cur:
            if cur is not None and cur not in bad:
                yield cur, buf
            if job in seen:
                bad.add(job)
            seen.add(job)
            cur, buf = job, []
        buf.append(row)
    if cur is not None and cur not in bad:
        yield cur, buf


def _cores(plan_cpu: str) -> int | None:
    try:
        v = Decimal(plan_cpu.strip())
    except (InvalidOperation, AttributeError):
        return None
    if not v.is_finite() or v <= 0:
        return None
    return int(math.ceil(v / 100))


def validate_job(rows: list[list[str]], lim: Limits) -> tuple[list[RawTask] | None, str]:
    """Return (tasks, "ok") or (None, drop_reason)."""
    tasks: list[RawTask] = []
    for r in rows:
        parsed = parse_task_name(r[0])
        if parsed is None:
            return None, "bad_task_name"
        if r[4].strip() != "Terminated":
            return None, "status"
        try:
            start, end, inst = int(r[5]), int(r[6]), int(r[1])
        except ValueError:
            return None, "time"
        if start <= 0 or end <= start:
            return None, "time"
        cpu = _cores(r[7])
        if cpu is None:
            return None, "no_plan_cpu"
        tasks.append(RawTask(r[0].strip(), parsed[0], tuple(parsed[1]), inst, start, end, cpu))
    if len(tasks) < lim.min_tasks:
        return None, "too_few_tasks"
    if len(tasks) > lim.max_tasks:
        return None, "too_many_tasks"
    ids = [t.tid for t in tasks]
    if len(set(ids)) != len(ids):
        return None, "duplicate_task"
    idset = set(ids)
    if any(p not in idset for t in tasks for p in t.parents):
        return None, "missing_parent"
    if topo_order(tasks) is None:
        return None, "cycle"
    if any(t.cpu > lim.max_cpu for t in tasks):
        return None, "too_many_cores"
    return tasks, "ok"


def topo_order(tasks: list[RawTask]) -> list[RawTask] | None:
    """Kahn's algorithm, ties broken by task id (deterministic). None if cyclic."""
    by = {t.tid: t for t in tasks}
    indeg = {t.tid: len(set(t.parents)) for t in tasks}
    children: dict[int, list[int]] = {t.tid: [] for t in tasks}
    for t in tasks:
        for p in set(t.parents):
            children[p].append(t.tid)
    ready = sorted(i for i, d in indeg.items() if d == 0)
    out: list[RawTask] = []
    while ready:
        i = ready.pop(0)
        out.append(by[i])
        for c in children[i]:
            indeg[c] -= 1
            if indeg[c] == 0:
                ready.append(c)
        ready.sort()
    return out if len(out) == len(tasks) else None


# ------------------------------------------------------------------------------------------- passes
def scan_eligible(path: str | Path, lim: Limits = Limits()) -> tuple[list[str], dict[str, int]]:
    """Pass 1: sorted eligible job names + counts (jobs_total, kept, one count per drop reason)."""
    counts: Counter = Counter()
    eligible: list[str] = []
    bad: set[str] = set()
    for job, rows in iter_jobs(open_rows(path), counts, bad):
        counts["jobs_seen"] += 1
        tasks, why = validate_job(rows, lim)
        if tasks is None:
            counts[why] += 1
        else:
            eligible.append(job)
    counts["non_contiguous"] = len(bad)
    eligible = sorted(set(eligible) - bad)
    counts["eligible"] = len(eligible)
    return eligible, {k: int(counts.get(k, 0)) for k in ("jobs_seen", "eligible", *DROP_REASONS, "malformed_rows")}


def collect_jobs(path: str | Path, names: Iterable[str], lim: Limits = Limits()) -> dict[str, list[RawTask]]:
    """Pass 2: validated tasks of the requested jobs only."""
    want = set(names)
    out: dict[str, list[RawTask]] = {}
    for job, rows in iter_jobs(open_rows(path), Counter()):
        if job in want:
            tasks, why = validate_job(rows, lim)
            if tasks is None:
                raise ValueError(f"job {job} became ineligible in pass 2 ({why}); raw file changed?")
            out[job] = tasks
    missing = want - out.keys()
    if missing:
        raise ValueError(f"{len(missing)} sampled jobs not found in pass 2, e.g. {sorted(missing)[:3]}")
    return out


def sample_names(eligible: list[str], n: int, seed: int) -> list[str]:
    """Deterministic sample (sorted input), returned in name order."""
    if n > len(eligible):
        raise ValueError(f"asked for {n} workflows but only {len(eligible)} eligible jobs")
    return sorted(random.Random(seed).sample(sorted(eligible), n))


# ------------------------------------------------------------------------------------------- conversion
def energy_wh(cpu: int, seconds: int, watts_per_core: int) -> int:
    """max(1, round_half_up(cpu * seconds / 3600 * W)) with integer arithmetic."""
    num = cpu * seconds * watts_per_core
    return max(1, (2 * num + 3600) // 7200)


def to_workload(jobs: dict[str, list[RawTask]], seed: int, watts_per_core: int,
                volume_mb_lognormal: tuple[float, float], meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Convert validated jobs (ordered by name) to the processed JSON dict: tasks, edges, meta.
    Edge volumes are ESTIMATED (the trace has none): seeded log-normal, like the synthetic generator."""
    mu, sigma = volume_mb_lognormal
    rng = random.Random(seed)
    tasks: list[dict[str, Any]] = []
    edges: list[dict[str, int]] = []
    inst_nums: list[int] = []
    durations: list[int] = []
    for w, job in enumerate(sorted(jobs)):
        order = topo_order(jobs[job])
        assert order is not None
        index = {t.tid: len(tasks) + i for i, t in enumerate(order)}
        for t in order:
            tasks.append({"name": f"{job}/{t.name}", "workflow": w, "cpu": int(t.cpu),
                          "energy_wh": int(energy_wh(t.cpu, t.end - t.start, int(watts_per_core)))})
            inst_nums.append(int(t.instance_num))
            durations.append(int(t.end - t.start))
        for t in order:
            for p in sorted(set(t.parents)):
                vol = max(1, int(math.exp(rng.gauss(mu, sigma))))
                edges.append({"j": index[p], "k": index[t.tid], "volume_mb": vol})
    m = dict(meta or {})
    exact_wh = sum(Fraction(t["cpu"] * d * int(watts_per_core), 3600) for t, d in zip(tasks, durations))
    m.update({"seed": seed, "jobs": sorted(jobs), "instance_num": inst_nums, "duration_s": durations,
              "exact_task_energy_wh": float(exact_wh), "tasks_below_1wh": sum(
                  t["cpu"] * d * int(watts_per_core) < 3600 for t, d in zip(tasks, durations)),
              "energy_floor_note": "energy_wh is an integer >= 1 (contract unit); tasks below 1 Wh are raised to 1",
              "volume_source": "estimated",
              "task_size": "one representative instance per task", "watts_per_core": int(watts_per_core)})
    return {"tasks": tasks, "edges": edges, "meta": m}
