"""QAOA with XY mixers (Quantum Alternating Operator Ansatz) — QUANTUM ALGORITHM, CLASSICALLY SIMULATED.
STATUS: IMPLEMENTED

Hadfield et al., Algorithms 12, 34 (2019); Wang, Rubin, Dominy, Rieffel, PRA 101, 012320 (2020);
INTERP angle initialisation: Zhou et al., PRX 10, 021067 (2020).

Encoding: task i has a register of m qubits, one-hot "task i is in region d" (n = t*m qubits).
The XY mixer (X_d X_e + Y_d Y_e)/2 on qubits d, e of one register preserves the register's Hamming
weight, so starting from one-hot states the circuit never leaves the FEASIBLE SUBSPACE of size m^t.
This module simulates exactly inside that subspace (state tensor of shape (m,)*t):
  - cost layer:  diagonal phase exp(-i gamma E~(x)), E~ = (E - lower_offset) / energy_scale
    (coefficient-level normalisation, no knowledge of the optimum);
  - mixer layer: the register's XY edges (ring = cycle graph, complete = complete graph) are split
    into groups of disjoint pairs, applied as on hardware (Trotterised, one group after another).
    Within a group the pairs commute; in the subspace each pair acts as the 2x2 rotation
    [[cos b, -i sin b], [-i sin b, cos b]] on the amplitudes "task in d" / "task in e".
tests/test_quantum.py proves this equals a full 2^n statevector simulation built from Pauli matrices.

Two budgeted solvers (fair-comparison protocol, docs/plans/PHASE2_QUANTUM.md §3):
  - `solve_shots` (QAOA-shots): angles tuned by SPSA on SHOT estimates; every shot, including the
    estimation shots, is a counted evaluation. The honest budgeted variant.
  - `solve_ideal` (QAOA-ideal): angles tuned (Nelder-Mead + INTERP, p = 1..p) on EXACT expectations,
    which are NOT counted; only the final readout shots are counted. Optimistic upper bound, reported
    separately and labelled "ideal".
This is a classical simulation: run time grows as m^t and says nothing about quantum hardware.
"""
from __future__ import annotations

import math

import numpy as np

from .model import SubProblem, SubResult
from .optim import nelder_mead, spsa

MIXERS = ("ring", "complete")


# ------------------------------------------------------------------------------- mixer structure
def mixer_edges(m: int, kind: str) -> list[tuple[int, int]]:
    if kind == "ring":
        if m < 2:
            return []
        if m == 2:
            return [(0, 1)]
        return [(d, (d + 1) % m) for d in range(m)]
    if kind == "complete":
        return [(d, e) for d in range(m) for e in range(d + 1, m)]
    raise ValueError(f"unknown mixer {kind!r}")


def mixer_groups(m: int, kind: str) -> list[list[tuple[int, int]]]:
    """Partition the register's XY edges into groups of disjoint pairs (one circuit layer each).
    ring: even edges, odd edges (+ the wrap edge alone when m is odd)  -> 2 groups for even m.
    complete: round-robin perfect matchings                            -> m-1 groups for even m."""
    if kind == "ring":
        edges = mixer_edges(m, "ring")
        if m <= 2:
            return [edges] if edges else []
        if m % 2 == 0:
            return [edges[0::2], edges[1::2]]
        return [edges[0:m - 1:2], edges[1:m - 1:2], [edges[m - 1]]]
    if kind == "complete":
        players = list(range(m)) + ([None] if m % 2 else [])
        k = len(players)
        groups = []
        for _ in range(k - 1):
            g = []
            for i in range(k // 2):
                a, b = players[i], players[k - 1 - i]
                if a is not None and b is not None:
                    g.append((min(a, b), max(a, b)))
            groups.append(sorted(g))
            players = [players[0]] + [players[-1]] + players[1:-1]
        return groups
    raise ValueError(f"unknown mixer {kind!r}")


def gate_count(t: int, m: int, kind: str) -> dict[str, int]:
    """Per QAOA layer: two-qubit XY gates and mixer depth (groups of disjoint pairs)."""
    return {"xy_gates_per_layer": t * len(mixer_edges(m, kind)), "mixer_depth": len(mixer_groups(m, kind))}


# ------------------------------------------------------------------------------- simulator
class SubspaceQAOA:
    def __init__(self, sp: SubProblem, mixer: str = "ring"):
        self.sp, self.t, self.m, self.mixer = sp, sp.t, sp.m, mixer
        self.groups = mixer_groups(sp.m, mixer)
        self.E = (sp.diagonal().astype(float) - sp.lower_offset()) / sp.energy_scale()   # uncounted cost layer

    def initial(self, warm: tuple[int, ...] | None = None, eps: float = 0.3) -> np.ndarray:
        """Uniform superposition of one-hot states (product of W states), or a warm start that puts
        weight 1-eps on region warm[i] of each register and eps/(m-1) on each other region."""
        t, m = self.t, self.m
        psi = np.ones((1,), dtype=complex)
        for i in range(t):
            if warm is None:
                r = np.full(m, 1.0 / math.sqrt(m), dtype=complex)
            else:
                r = np.full(m, math.sqrt(eps / (m - 1)), dtype=complex)
                r[warm[i]] = math.sqrt(1.0 - eps)
            psi = np.multiply.outer(psi, r)
        return psi.reshape((m,) * t)

    def apply_cost(self, psi: np.ndarray, gamma: float) -> np.ndarray:
        return psi * np.exp(-1j * gamma * self.E)

    def register_unitary(self, beta: float) -> np.ndarray:
        """m x m one-register mixer: product of the group exponentials (group 0 applied first).
        Each group is a direct sum of exact 2x2 rotations on disjoint pairs."""
        c, s = math.cos(beta), math.sin(beta)
        U = np.eye(self.m, dtype=complex)
        for group in self.groups:
            G = np.eye(self.m, dtype=complex)
            for d, e in group:
                G[d, d] = G[e, e] = c
                G[d, e] = G[e, d] = -1j * s
            U = G @ U
        return U

    def apply_mixer(self, psi: np.ndarray, beta: float) -> np.ndarray:
        U = self.register_unitary(beta)
        for i in range(self.t):
            psi = np.moveaxis(np.tensordot(U, psi, axes=([1], [i])), 0, i)
        return psi

    def state(self, gammas, betas, init: np.ndarray | None = None) -> np.ndarray:
        psi = self.initial() if init is None else init
        for g, b in zip(gammas, betas):
            psi = self.apply_mixer(self.apply_cost(psi, g), b)
        return psi

    def probs(self, gammas, betas, init: np.ndarray | None = None) -> np.ndarray:
        p = np.abs(self.state(gammas, betas, init).ravel()) ** 2
        return p / p.sum()

    def expectation(self, gammas, betas, init: np.ndarray | None = None) -> float:
        return float(self.probs(gammas, betas, init) @ self.E.ravel())


# ------------------------------------------------------------------------------- angle schedules
def interp(gammas: np.ndarray, betas: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """INTERP: optimal depth-p angles -> initial depth-(p+1) angles (Zhou et al. 2020)."""
    p = len(gammas)

    def up(v):
        v = np.concatenate([[0.0], v, [0.0]])
        return np.array([(i / p) * v[i] + ((p - i) / p) * v[i + 1] for i in range(p + 1)])
    return up(np.asarray(gammas, float)), up(np.asarray(betas, float))


def linear_ramp(p: int, gamma_max: float, beta_max: float) -> tuple[np.ndarray, np.ndarray]:
    """Annealing-like start: gamma ramps up, beta ramps down."""
    f = (np.arange(p) + 0.5) / p
    return gamma_max * f, beta_max * (1.0 - f)


_IDEAL_CACHE: dict[tuple, tuple[np.ndarray, np.ndarray, float]] = {}


def optimise_ideal(sim: SubspaceQAOA, p: int, init: np.ndarray | None = None, init_key=None,
                   max_evals: int = 300, use_cache: bool = True) -> tuple[np.ndarray, np.ndarray, float]:
    """Exact-expectation angle optimisation: coarse grid at p=1, Nelder-Mead, INTERP up to p.
    Deterministic (no seed needed); cached per (sub-problem, mixer, p, start)."""
    key = (sim.sp.sp_hash(), sim.mixer, p, init_key)
    if use_cache and key in _IDEAL_CACHE:
        return _IDEAL_CACHE[key]

    def f(v, q):
        return sim.expectation(v[:q], v[q:], init)
    best = None
    for g in np.linspace(0.5, 4.0 * math.pi, 9):
        for b in np.linspace(0.1, 0.9 * math.pi, 7):
            val = f(np.array([g, b]), 1)
            if best is None or val < best[0]:
                best = (val, g, b)
    v, val, _ = nelder_mead(lambda v: f(v, 1), [best[1], best[2]], step=[0.5, 0.2], max_evals=max_evals)
    gs, bs = v[:1], v[1:]
    for q in range(2, p + 1):
        g0, b0 = interp(gs, bs)
        v, val, _ = nelder_mead(lambda v, q=q: f(v, q), np.concatenate([g0, b0]), step=0.2, max_evals=max_evals)
        gs, bs = v[:q], v[q:]
    out = (gs, bs, float(val))
    if use_cache:
        _IDEAL_CACHE[key] = out
    return out


# ------------------------------------------------------------------------------- budgeted solvers
def _readout(sp: SubProblem, probs: np.ndarray, shots: int, rng: np.random.Generator):
    idx = rng.choice(probs.size, size=shots, p=probs)
    return idx, sp.energy_index(idx)


def solve_ideal(sp: SubProblem, seed: int = 0, mixer: str = "ring", p: int = 3,
                warm: tuple[int, ...] | None = None, eps: float = 0.3, **_) -> SubResult:
    """QAOA-ideal: exact-expectation angles (uncounted), then sp.remaining counted readout shots."""
    if sp.budget is None:
        raise ValueError("QAOA needs a budget (sp.set_budget(B))")
    sim = SubspaceQAOA(sp, mixer)
    init = None if warm is None else sim.initial(warm, eps)
    gs, bs, exp_e = optimise_ideal(sim, p, init, None if warm is None else (tuple(warm), eps))
    rng = np.random.default_rng(seed)
    probs = sim.probs(gs, bs, init)
    idx, E = _readout(sp, probs, sp.remaining, rng)
    j = int(np.argmin(E))
    return SubResult(sp.assignment_of(int(idx[j])), int(E[j]), sp.evals,
                     {"mixer": mixer, "p": p, "mode": "ideal", "expect_norm": exp_e,
                      "gammas": [float(g) for g in gs], "betas": [float(b) for b in bs]})


def solve_shots(sp: SubProblem, seed: int = 0, mixer: str = "ring", p: int = 1, shots: int = 4,
                opt_frac: float = 0.5, gamma_max: float = 3.0, beta_max: float = 0.8,
                spsa_a: float = 0.3, spsa_c: float = 0.2, **_) -> SubResult:
    """QAOA-shots: linear-ramp start, SPSA on shot estimates of <E>, final readout. All shots counted;
    the best sample seen anywhere (estimation or readout) is returned."""
    if sp.budget is None:
        raise ValueError("QAOA needs a budget (sp.set_budget(B))")
    sim = SubspaceQAOA(sp, mixer)
    rng = np.random.default_rng(seed)
    best = [None, None]

    def sample(v, k):
        idx, E = _readout(sp, sim.probs(v[:p], v[p:]), k, rng)
        j = int(np.argmin(E))
        if best[1] is None or E[j] < best[1]:
            best[0], best[1] = int(idx[j]), int(E[j])
        return E

    g0, b0 = linear_ramp(p, gamma_max, beta_max)
    v = np.concatenate([g0, b0])
    iters = int(opt_frac * sp.remaining) // (2 * shots)
    if iters > 0:
        scale = sp.energy_scale()
        v = spsa(lambda u: float(sample(u, shots).mean()) / scale, v, iters, rng, a=spsa_a, c=spsa_c)
    if sp.remaining > 0:
        sample(v, sp.remaining)
    return SubResult(sp.assignment_of(best[0]), best[1], sp.evals,
                     {"mixer": mixer, "p": p, "mode": "shots", "spsa_iters": iters,
                      "gammas": [float(g) for g in v[:p]], "betas": [float(b) for b in v[p:]]})


def _bind(fn, **fixed):
    def solver(sp: SubProblem, seed: int = 0, **params) -> SubResult:
        return fn(sp, seed, **{**params, **fixed})
    solver.__name__ = fn.__name__ + "_" + "_".join(f"{k}" for k in fixed.values())
    return solver


qaoa_ring = _bind(solve_shots, mixer="ring")
qaoa_complete = _bind(solve_shots, mixer="complete")
qaoa_ring_ideal = _bind(solve_ideal, mixer="ring")
qaoa_complete_ideal = _bind(solve_ideal, mixer="complete")
