"""Problem instance: regions, workflow tasks (DAGs), data-transfer edges.

STATUS: IMPLEMENTED
All numbers are INTEGERS so Python and Solidity compute identical results.
Unit trick (no rounding needed):
  energy [Wh] x carbon intensity [g/kWh]  = carbon [mg]   -> x1000 = [µg]
  energy [Wh] x price [µUSD/kWh]          = cost [nUSD]
  network energy [mWh] x intensity [g/kWh] = carbon [µg]
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .hashing import hash_json


@dataclass(frozen=True)
class Region:
    name: str
    ci_g_per_kwh: int          # carbon intensity
    price_uusd_per_kwh: int    # electricity price, micro-USD per kWh
    capacity: int              # CPU cores available for this batch


@dataclass(frozen=True)
class Task:
    name: str
    workflow: int
    cpu: int                   # cores
    energy_wh: int             # energy if run anywhere (PUE ignored in the case-study model)


@dataclass(frozen=True)
class Edge:
    j: int                     # parent task index
    k: int                     # child task index
    volume_mb: int             # data passed from j to k


@dataclass
class Instance:
    regions: list[Region]
    tasks: list[Task]
    edges: list[Edge]
    net_energy_mwh_per_mb: int     # network energy intensity
    egress_nusd_per_mb: int        # inter-region transfer price
    w_carbon: int = 1              # objective weights (integers)
    w_cost: int = 1
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def n(self) -> int:
        return len(self.tasks)

    @property
    def m(self) -> int:
        return len(self.regions)

    def workflows(self) -> dict[int, list[int]]:
        out: dict[int, list[int]] = {}
        for i, t in enumerate(self.tasks):
            out.setdefault(t.workflow, []).append(i)
        return out

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    def instance_hash(self) -> bytes:
        d = self.to_dict()
        d.pop("meta")
        return hash_json(d)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Instance":
        return cls(
            regions=[Region(**r) for r in d["regions"]],
            tasks=[Task(**t) for t in d["tasks"]],
            edges=[Edge(**e) for e in d["edges"]],
            net_energy_mwh_per_mb=d["net_energy_mwh_per_mb"],
            egress_nusd_per_mb=d["egress_nusd_per_mb"],
            w_carbon=d.get("w_carbon", 1),
            w_cost=d.get("w_cost", 1),
            meta=d.get("meta", {}),
        )


ROOT = Path(__file__).resolve().parents[1]

# Phase 1 task-size rule for file workloads (`workload.task_size`; decision D1, 2026-11-23).
#   representative: one representative instance per task, energy raised to >= 1 Wh (the "1 Wh floor", option (c)).
#   instance_num:   a task is all its instances (option (a)): cores x instance_num, energy x instance_num.
TASK_SIZE_REPRESENTATIVE = "representative"
TASK_SIZE_INSTANCE_NUM = "instance_num"


def scale_by_instance_num(d: dict[str, Any]) -> list[Task]:
    """Option (a): task cores = cpu x instance_num (instances run side by side); task energy =
    max(1, round_half_up(cpu x duration_s x W x instance_num / 3600)) Wh, integer arithmetic, from the per-task
    `instance_num` / `duration_s` and `watts_per_core` recorded in the processed file's meta."""
    m = d.get("meta", {})
    if "instance_num" not in m or "duration_s" not in m or "watts_per_core" not in m:
        raise ValueError("task_size instance_num needs meta.instance_num, meta.duration_s and meta.watts_per_core "
                         "(regenerate with scripts/load_alibaba_dags.py)")
    w = int(m["watts_per_core"])
    out = []
    for t, k, s in zip(d["tasks"], m["instance_num"], m["duration_s"]):
        k = max(1, int(k))
        num = int(t["cpu"]) * int(s) * w * k
        out.append(Task(name=str(t["name"]), workflow=int(t["workflow"]), cpu=int(t["cpu"]) * k,
                        energy_wh=max(1, (2 * num + 3600) // 7200)))
    return out


def workload_path(cfg: dict[str, Any], seed: int | None = None) -> Path:
    """Processed workload file of a `workload: {source: file}` config. With `seed` and a `pattern`, the
    per-seed sample (E4 real-data instances); otherwise `path`. Relative paths are relative to the repo root."""
    wl = cfg["workload"]
    p = Path(wl["pattern"].format(seed=seed)) if seed is not None and wl.get("pattern") else Path(wl["path"])
    return p if p.is_absolute() else ROOT / p


def build_instance(cfg: dict[str, Any], seed: int, workload_seed: int | None = None) -> Instance:
    """Instance from a config. No `workload` key -> `generate_instance(cfg, seed)` (the default demo path,
    byte-for-byte unchanged). `workload.source == "file"` -> Phase 1 real workload: tasks/edges from the
    processed Alibaba JSON (scripts/load_alibaba_dags.py), regions/network/weights from the config, capacity
    with the same rule as the synthetic generator (ceil(total_cpu * capacity_share))."""
    wl = cfg.get("workload")
    if not wl:
        return generate_instance(cfg, seed)
    if wl.get("source") != "file":
        raise ValueError(f"unknown workload source {wl.get('source')!r}")
    path = workload_path(cfg, workload_seed)
    if not path.is_file():
        raise FileNotFoundError(f"workload file {path} not found (data missing): run "
                                "scripts/load_alibaba_dags.py (needs data/raw/alibaba/batch_task.tar.gz)")
    d = json.loads(path.read_text(encoding="utf-8"))
    task_size = wl.get("task_size", TASK_SIZE_REPRESENTATIVE)
    if task_size == TASK_SIZE_REPRESENTATIVE:
        tasks = [Task(name=str(t["name"]), workflow=int(t["workflow"]), cpu=int(t["cpu"]),
                      energy_wh=int(t["energy_wh"])) for t in d["tasks"]]
    elif task_size == TASK_SIZE_INSTANCE_NUM:
        tasks = scale_by_instance_num(d)
    else:
        raise ValueError(f"unknown workload.task_size {task_size!r}")
    edges = [Edge(j=int(e["j"]), k=int(e["k"]), volume_mb=int(e["volume_mb"])) for e in d["edges"]]
    total_cpu = sum(t.cpu for t in tasks)
    # D1 (instance_num): one task may hold most of the cores, so each region gets the headroom of one largest task:
    # capacity = ceil(total x share) + max task cpu. With sum(share) >= 1 the round-robin baseline always fits (if
    # every region had < max left, the total left would be < m x max, but it is >= (sum(share)-1) x total + m x max).
    headroom = max(t.cpu for t in tasks) if task_size == TASK_SIZE_INSTANCE_NUM else 0
    regions = [
        Region(name=r["name"], ci_g_per_kwh=int(r["ci_g_per_kwh"]),
               price_uusd_per_kwh=int(r["price_uusd_per_kwh"]),
               capacity=max(1, int(math.ceil(total_cpu * r["capacity_share"]))) + headroom)
        for r in cfg["regions"]
    ]
    meta = {"seed": seed, "generator": "alibaba-cluster-trace-v2018 (file)", "workload_file": path.name,
            "task_size": task_size,
            "workload_meta": {k: v for k, v in d.get("meta", {}).items() if k not in ("instance_num", "duration_s")}}
    if cfg.get("snapshot"):
        meta["snapshot"] = {"hour": cfg["snapshot"].get("hour"), "carbon_basis": cfg["snapshot"].get("carbon_basis")}
    return Instance(
        regions=regions, tasks=tasks, edges=edges,
        net_energy_mwh_per_mb=int(cfg["network"]["energy_mwh_per_mb"]),
        egress_nusd_per_mb=int(cfg["network"]["egress_nusd_per_mb"]),
        w_carbon=int(cfg["weights"]["carbon"]), w_cost=int(cfg["weights"]["cost"]), meta=meta,
    )


def generate_instance(cfg: dict[str, Any], seed: int) -> Instance:
    """Synthetic Alibaba-style workflow batch (DAGs) over the configured regions.

    cfg keys (see config/demo.yaml): regions, workflows, tasks_per_workflow [lo, hi],
    cpu_range, duration_h_range, watts_per_core, volume_mb_lognormal [mu, sigma],
    capacity_share (per region, fraction of total CPU demand), network, weights.
    """
    rng = random.Random(seed)
    tasks: list[Task] = []
    edges: list[Edge] = []
    lo, hi = cfg["tasks_per_workflow"]
    for w in range(cfg["workflows"]):
        start = len(tasks)
        k = rng.randint(lo, hi)
        for i in range(k):
            cpu = rng.randint(*cfg["cpu_range"])
            dur = rng.uniform(*cfg["duration_h_range"])
            energy = max(1, int(round(cpu * dur * cfg["watts_per_core"])))
            tasks.append(Task(name=f"wf{w}/t{i}", workflow=w, cpu=cpu, energy_wh=energy))
        mu, sigma = cfg["volume_mb_lognormal"]
        for i in range(1, k):                      # each non-root task gets 1-2 parents (DAG)
            parents = rng.sample(range(i), k=min(i, rng.choice([1, 1, 2])))
            for p in parents:
                vol = max(1, int(math.exp(rng.gauss(mu, sigma))))
                edges.append(Edge(j=start + p, k=start + i, volume_mb=vol))
    total_cpu = sum(t.cpu for t in tasks)
    regions = [
        Region(
            name=r["name"],
            ci_g_per_kwh=int(r["ci_g_per_kwh"]),
            price_uusd_per_kwh=int(r["price_uusd_per_kwh"]),
            capacity=max(1, int(math.ceil(total_cpu * r["capacity_share"]))),
        )
        for r in cfg["regions"]
    ]
    inst = Instance(
        regions=regions, tasks=tasks, edges=edges,
        net_energy_mwh_per_mb=int(cfg["network"]["energy_mwh_per_mb"]),
        egress_nusd_per_mb=int(cfg["network"]["egress_nusd_per_mb"]),
        w_carbon=int(cfg["weights"]["carbon"]), w_cost=int(cfg["weights"]["cost"]),
        meta={"seed": seed, "generator": "synthetic-alibaba-style"},
    )
    return inst
