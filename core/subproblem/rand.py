"""Random feasible sampling — sanity baseline. STATUS: IMPLEMENTED
Draws `budget` uniform one-hot assignments and keeps the best. Every sample is one counted evaluation."""
from __future__ import annotations

import numpy as np

from .model import SubProblem, SubResult


def solve(sp: SubProblem, seed: int = 0, **_) -> SubResult:
    if sp.budget is None:
        raise ValueError("random sampling needs a budget (sp.set_budget(B))")
    rng = np.random.default_rng(seed)
    k = sp.remaining
    idx = rng.integers(0, sp.n_states, size=k)
    E = sp.energy_index(idx)
    j = int(np.argmin(E))
    return SubResult(sp.assignment_of(int(idx[j])), int(E[j]), sp.evals, {})
