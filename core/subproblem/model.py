"""Per-workflow priced sub-problem (Phase 2 quantum layer). STATUS: IMPLEMENTED

The Lagrangian market (`core/market.py::_solve_workflow`) splits the schedule into independent
per-workflow problems. For workflow tasks t_0..t_{T-1} and integer prices lambda_d:

    E(x) = sum_i ( lin[t_i][x_i] + lambda[x_i] * cpu[t_i] )  +  sum_{edges (a,b)} pair[x_a][x_b]

There is no capacity constraint (the prices stand in for it), so the only feasibility rule is
"each task is in exactly one region" (one-hot per task register).

All coefficients are Python integers, so E(x) is exact. Prices from the market are floats; callers
round them to integers (`int(round(lam))`); with lambda = 0 the energy equals `scoring.evaluate`'s
score on a single-workflow instance (tests/test_quantum.py, test 3).

Budget accounting (fair-comparison protocol, docs/plans/PHASE2_QUANTUM.md §3): every counted call
(`energy`, `energy_index`, `delta`) adds to `evals`; exceeding `budget` raises `BudgetExceeded`.
Uncounted accessors (`diagonal`, coefficients) exist for the exact reference, for metrics and for
building the QAOA cost layer / QUBO from coefficients; solvers must not use them to look up answers.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..instance import Instance
from ..scoring import FastEvaluator


class BudgetExceeded(RuntimeError):
    """Raised when a sub-solver evaluates more assignments than its budget allows."""


@dataclass
class SubProblem:
    m: int                                        # regions
    lin: list[list[int]]                          # lin[i][d] incl. lambda_d * cpu_i  (integers)
    edges: list[tuple[int, int, list[list[int]]]]  # (parent pos, child pos, pair[d_parent][d_child])
    task_ids: list[int] = field(default_factory=list)
    lam: list[int] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    budget: int | None = None
    evals: int = 0

    def __post_init__(self) -> None:
        self.adj: list[list[tuple[int, list[list[int]], bool]]] = [[] for _ in range(self.t)]
        for a, b, mat in self.edges:
            self.adj[a].append((b, mat, True))
            self.adj[b].append((a, mat, False))
        self._diag: np.ndarray | None = None

    # ------------------------------------------------------------------ construction
    @classmethod
    def from_workflow(cls, inst: Instance, tasks: Sequence[int], lam: Sequence[int],
                      ev: FastEvaluator | None = None, meta: dict[str, Any] | None = None) -> "SubProblem":
        """Same construction as `market._solve_workflow` (edge orientation parent -> child)."""
        ev = ev or FastEvaluator(inst)
        lam_i = [int(v) for v in lam]
        if any(v != l for v, l in zip(lam_i, lam)):
            raise ValueError("prices must be integers (round market prices first)")
        m = inst.m
        pos = {t: i for i, t in enumerate(tasks)}
        lin = [[ev.lin[t][d] + lam_i[d] * ev.cpu[t] for d in range(m)] for t in tasks]
        edges = []
        for t in tasks:
            for k, mat, parent in ev.adj[t]:
                if parent and k in pos:
                    edges.append((pos[t], pos[k], [list(r) for r in mat]))
        return cls(m=m, lin=lin, edges=edges, task_ids=list(tasks), lam=lam_i, meta=dict(meta or {}))

    # ------------------------------------------------------------------ basic properties
    @property
    def t(self) -> int:
        return len(self.lin)

    @property
    def n_states(self) -> int:
        return self.m ** self.t

    @property
    def n_qubits(self) -> int:
        return self.t * self.m

    def sp_hash(self) -> str:
        blob = json.dumps({"m": self.m, "lin": self.lin, "edges": self.edges}, sort_keys=True)
        return "0x" + hashlib.sha256(blob.encode()).hexdigest()

    # ------------------------------------------------------------------ budget
    def set_budget(self, budget: int | None) -> None:
        self.budget, self.evals = budget, 0

    @property
    def remaining(self) -> int:
        return (1 << 62) if self.budget is None else self.budget - self.evals

    def _count(self, k: int) -> None:
        self.evals += k
        if self.budget is not None and self.evals > self.budget:
            raise BudgetExceeded(f"{self.evals} evaluations > budget {self.budget}")

    # ------------------------------------------------------------------ uncounted reference
    def _energy(self, x: Sequence[int]) -> int:
        e = sum(self.lin[i][d] for i, d in enumerate(x))
        for a, b, mat in self.edges:
            e += mat[x[a]][x[b]]
        return e

    def _local(self, x: Sequence[int], i: int, d: int) -> int:
        c = self.lin[i][d]
        for k, mat, i_parent in self.adj[i]:
            c += mat[d][x[k]] if i_parent else mat[x[k]][d]
        return c

    def diagonal(self) -> np.ndarray:
        """E for all m^t assignments, shape (m,)*t, C-order index = assignment (int64, exact).
        Built from coefficients by broadcasting (the cost Hamiltonian's diagonal). UNCOUNTED."""
        if self._diag is None:
            t, m = self.t, self.m
            E = np.zeros((m,) * t, dtype=np.int64)
            for i in range(t):
                shape = [1] * t
                shape[i] = m
                E = E + np.asarray(self.lin[i], dtype=np.int64).reshape(shape)
            for a, b, mat in self.edges:
                shape = [1] * t
                shape[a], shape[b] = m, m
                M = np.asarray(mat, dtype=np.int64)
                E = E + (M if a < b else M.T).reshape(shape)
            self._diag = E
        return self._diag

    def index_of(self, x: Sequence[int]) -> int:
        return int(np.ravel_multi_index(tuple(x), (self.m,) * self.t))

    def assignment_of(self, idx: int) -> tuple[int, ...]:
        return tuple(int(v) for v in np.unravel_index(int(idx), (self.m,) * self.t))

    def lower_offset(self) -> int:
        """sum_i min_d lin[i][d]: coefficient-level lower bound (pair terms are >= 0)."""
        return sum(min(r) for r in self.lin)

    def energy_scale(self) -> float:
        """Coefficient-level bound on the energy spread; used to normalise the QAOA cost layer."""
        s = sum(max(r) - min(r) for r in self.lin) + sum(max(max(r) for r in mat) for _, _, mat in self.edges)
        return float(max(1, s))

    def move_scale(self) -> float:
        """Typical single-move energy change (same role as `solvers.common.cost_scale`)."""
        s = [max(r) - min(r) for r in self.lin]
        return max(1.0, sum(s) / len(s))

    # ------------------------------------------------------------------ counted oracle
    def energy(self, x: Sequence[int]) -> int:
        """Energy of one assignment. COUNTED (1 evaluation)."""
        if len(x) != self.t or any(not (0 <= d < self.m) for d in x):
            raise ValueError("invalid assignment")
        self._count(1)
        return self._energy(x)

    def energy_index(self, idx: np.ndarray) -> np.ndarray:
        """Energies of sampled flat indices (e.g. QAOA shots). COUNTED (len(idx) evaluations)."""
        idx = np.asarray(idx, dtype=np.int64).ravel()
        self._count(int(idx.size))
        return self.diagonal().ravel()[idx]

    def delta(self, x: Sequence[int], i: int, d: int) -> int:
        """E(x with x_i := d) - E(x): evaluates the proposed assignment. COUNTED (1 evaluation)."""
        self._count(1)
        return self._local(x, i, d) - self._local(x, i, x[i])


@dataclass
class SubResult:
    x: tuple[int, ...]           # best assignment found (always one-hot feasible: one region per task)
    energy: int                  # its energy (exact int)
    evals: int                   # counted evaluations used
    info: dict[str, Any] = field(default_factory=dict)


def workflow_instance(inst: Instance, w: int) -> Instance:
    """Single-workflow Instance (tasks of workflow w, re-indexed), for scoring cross-checks."""
    tasks = inst.workflows()[w]
    pos = {t: i for i, t in enumerate(tasks)}
    edges = [type(e)(j=pos[e.j], k=pos[e.k], volume_mb=e.volume_mb)
             for e in inst.edges if e.j in pos and e.k in pos]
    return Instance(regions=list(inst.regions), tasks=[inst.tasks[t] for t in tasks], edges=edges,
                    net_energy_mwh_per_mb=inst.net_energy_mwh_per_mb,
                    egress_nusd_per_mb=inst.egress_nusd_per_mb,
                    w_carbon=inst.w_carbon, w_cost=inst.w_cost, meta=dict(inst.meta, workflow=w))
