"""Simulated quantum annealing on a sub-problem — QUANTUM-INSPIRED (classical computer). STATUS: IMPLEMENTED

Same path-integral Monte Carlo as `core/solvers/sqa.py` (Martonak, Santoro, Tosatti 2002): P Trotter
replicas on a ring, J_perp = -(P T / 2) ln tanh(Gamma / (P T)), Gamma annealed geometrically per sweep,
problem energy divided by P, one-hot structural (region indices).
Differences (budget protocol): random replica starts instead of perturbed greedy, no capacity penalty, and
the run stops when the budget is spent: P evaluations for the starts + 1 per proposed move (all replicas).
The best of all evaluated assignments is returned. If P > budget, P is reduced to the budget.
"""
from __future__ import annotations

import math
import random

from ..solvers.sqa import j_perp
from .model import SubProblem, SubResult


def solve(sp: SubProblem, seed: int = 0, replicas: int = 4, T: float = 0.05, gamma0: float = 3.0,
          gamma_end: float = 0.01, **_) -> SubResult:
    if sp.budget is None:
        raise ValueError("SQA needs a budget (sp.set_budget(B))")
    rng = random.Random(seed)
    t, m = sp.t, sp.m
    scale = sp.move_scale()
    P = max(1, min(replicas, sp.remaining))
    X = [[rng.randrange(m) for _ in range(t)] for _ in range(P)]
    cur = [sp.energy(x) for x in X]
    k = min(range(P), key=lambda r: cur[r])
    best, best_e = tuple(X[k]), cur[k]
    moves = sp.remaining
    sweeps = max(1, math.ceil(moves / (P * t)))
    done = 0
    for sweep in range(sweeps):
        frac = sweep / max(1, sweeps - 1)
        gamma = gamma0 * (gamma_end / gamma0) ** frac
        Jp = j_perp(P, T, gamma)
        for rho in range(P):
            x = X[rho]
            up, down = X[(rho + 1) % P], X[(rho - 1) % P]
            for _ in range(t):
                if done >= moves:
                    break
                i = rng.randrange(t)
                a = x[i]
                b = rng.randrange(m - 1)
                b = b if b < a else b + 1
                dE_prob = sp.delta(x, i, b)
                done += 1
                if cur[rho] + dE_prob < best_e:
                    best_e = cur[rho] + dE_prob
                    best = tuple(x[:i] + [b] + x[i + 1:])
                agree_before = (up[i] == a) + (down[i] == a)
                agree_after = (up[i] == b) + (down[i] == b)
                dE = dE_prob / scale / P - 4.0 * Jp * (agree_after - agree_before) / P
                if dE <= 0 or rng.random() < math.exp(-dE / T):
                    x[i] = b
                    cur[rho] += dE_prob
    return SubResult(best, best_e, sp.evals, {"replicas": P})
