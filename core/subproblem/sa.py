"""Simulated annealing on a sub-problem — CLASSICAL. STATUS: IMPLEMENTED

Same move rule and schedule as `core/solvers/sa.py`: relocate one task to a different region,
Metropolis acceptance, geometric cooling t0 -> t_end, temperatures in units of the typical move size.
Differences (budget protocol): random start instead of greedy (greedy would spend evaluations), no
capacity penalty (prices replace it), and the number of steps is set by the budget:
1 evaluation for the start + 1 per proposed move. The best of all evaluated assignments is returned.
"""
from __future__ import annotations

import math
import random

from .model import SubProblem, SubResult


def solve(sp: SubProblem, seed: int = 0, t0: float = 2.0, t_end: float = 0.01, **_) -> SubResult:
    if sp.budget is None:
        raise ValueError("SA needs a budget (sp.set_budget(B))")
    rng = random.Random(seed)
    t, m = sp.t, sp.m
    scale = sp.move_scale()
    x = [rng.randrange(m) for _ in range(t)]
    cur = sp.energy(x)
    best, best_e = tuple(x), cur
    steps = sp.remaining
    for s in range(steps):
        T = t0 * (t_end / t0) ** (s / max(1, steps - 1))
        i = rng.randrange(t)
        d = rng.randrange(m - 1)
        d = d if d < x[i] else d + 1
        dE = sp.delta(x, i, d)
        if cur + dE < best_e:
            best_e = cur + dE
            best = tuple(x[:i] + [d] + x[i + 1:])
        if dE <= 0 or rng.random() < math.exp(-dE / scale / T):
            x[i] = d
            cur += dE
    return SubResult(best, best_e, sp.evals, {})
