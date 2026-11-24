"""Simulated bifurcation (ballistic bSB and discrete dSB) — QUANTUM-INSPIRED (classical computer).
STATUS: IMPLEMENTED

Goto, Tatsumura, Dixon, Sci. Adv. 5, eaav2372 (2019); Goto et al., Sci. Adv. 7, eabe7953 (2021).
Classical Hamiltonian dynamics inspired by a network of Kerr-nonlinear parametric oscillators.
Works on the Ising form of the one-hot-penalised QUBO (`qubo.build_qubo`):
    E(s) = s^T J s / 2 + h . s + const,  s in {-1,+1}^n,  n = tasks * regions
Each trajectory evolves positions x and momenta y (symplectic Euler, inelastic walls at |x| = 1):
    y += dt * ( -(a0 - a(t)) x  -  c0 (J z + h) ),   z = x (ballistic) or sign(x) (discrete)
    x += dt * a0 * y
with a(t) ramped linearly 0 -> a0. Feasibility is PENALTY-BASED (not structural): the raw readout
sign(x) may violate one-hot; the raw feasibility rate is reported in `info["feasible_rate"]` before
the per-register argmax decoding that turns every readout into a one-hot assignment.

Budget protocol: every decoded readout is one counted evaluation, so the solver runs exactly
`sp.remaining` independent trajectories (vectorised) and reads each out once at the end.
The internal dynamics use the coefficients (J, h) only, as a hardware Ising machine would.
"""
from __future__ import annotations

import numpy as np

from .model import SubProblem, SubResult
from .qubo import build_qubo


def solve(sp: SubProblem, seed: int = 0, variant: str = "ballistic", steps: int = 100, dt: float = 0.5,
          xi: float = 0.5, a0: float = 1.0, **_) -> SubResult:
    if sp.budget is None:
        raise ValueError("SB needs a budget (sp.set_budget(B))")
    if variant not in ("ballistic", "discrete"):
        raise ValueError(f"unknown SB variant {variant!r}")
    rng = np.random.default_rng(seed)
    qb = build_qubo(sp)
    J, h, _ = qb.ising()
    n, t, m = qb.n, sp.t, sp.m
    c0 = xi / float(max(1e-12, np.max(np.abs(J).sum(axis=1) + np.abs(h))))
    R = sp.remaining
    X = rng.uniform(-0.1, 0.1, size=(R, n))
    Y = rng.uniform(-0.1, 0.1, size=(R, n))
    for k in range(steps):
        a = a0 * k / max(1, steps - 1)
        Z = X if variant == "ballistic" else np.sign(X)
        Y += dt * (-(a0 - a) * X - c0 * (Z @ J + h))
        X += dt * a0 * Y
        wall = np.abs(X) > 1.0
        X[wall] = np.sign(X[wall])
        Y[wall] = 0.0
    B = (X > 0).reshape(R, t, m)
    feasible = B.sum(axis=2) == 1                       # (R, t) one bit per register
    raw_ok = feasible.all(axis=1)
    # argmax decoding (always one-hot); on a feasible register it equals the raw readout bit
    A = X.reshape(R, t, m).argmax(axis=2)
    idx = np.ravel_multi_index(tuple(A.T), (m,) * t)
    E = sp.energy_index(idx)
    j = int(np.argmin(E))
    return SubResult(sp.assignment_of(int(idx[j])), int(E[j]), sp.evals,
                     {"variant": variant, "trajectories": R, "feasible_rate": float(raw_ok.mean())})


def solve_discrete(sp: SubProblem, seed: int = 0, **params) -> SubResult:
    params["variant"] = "discrete"
    return solve(sp, seed, **params)
