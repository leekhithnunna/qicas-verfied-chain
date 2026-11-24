"""Exact reference for a sub-problem: brute force over all m^t assignments. STATUS: IMPLEMENTED

Uses the uncounted diagonal (it is the reference, not a budgeted method). Cross-checked against
`core/market.py::_solve_workflow` in tests/test_quantum.py (test 4).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .model import SubProblem, SubResult


@dataclass(frozen=True)
class ExactInfo:
    x: tuple[int, ...]       # an optimal assignment (lowest flat index among ties)
    e_star: int              # optimum energy
    e_max: int               # worst energy (for the normalised gap)
    n_opt: int               # number of optimal assignments


def exact_info(sp: SubProblem) -> ExactInfo:
    D = sp.diagonal().ravel()
    k = int(np.argmin(D))
    e_star, e_max = int(D[k]), int(D.max())
    return ExactInfo(sp.assignment_of(k), e_star, e_max, int((D == e_star).sum()))


def solve(sp: SubProblem, seed: int = 0, **_) -> SubResult:
    """Reference only (does not use the budget)."""
    info = exact_info(sp)
    return SubResult(info.x, info.e_star, 0, {"e_max": info.e_max, "n_opt": info.n_opt})


def normalised_gap(e: int, ref: ExactInfo) -> float:
    """(E - E*) / (E_max - E*), in [0, 1]; 0 when every assignment is optimal."""
    span = ref.e_max - ref.e_star
    return 0.0 if span == 0 else (e - ref.e_star) / span
