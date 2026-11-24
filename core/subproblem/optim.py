"""Derivative-free optimisers for QAOA angles (numpy only, no SciPy). STATUS: IMPLEMENTED

- `nelder_mead`: deterministic simplex method, used with EXACT expectations (QAOA-ideal).
- `spsa`: simultaneous-perturbation stochastic approximation (Spall 1998), used with SHOT-NOISE
  estimates (QAOA-shots); every function call there is paid for with counted shots.
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np


def nelder_mead(f: Callable[[np.ndarray], float], x0, step: float | np.ndarray = 0.3, max_evals: int = 300,
                tol: float = 1e-9) -> tuple[np.ndarray, float, int]:
    """Minimise f from x0. Returns (x_best, f_best, n_evals). Standard coefficients (1, 2, 0.5, 0.5)."""
    x0 = np.asarray(x0, dtype=float)
    n = x0.size
    steps = np.broadcast_to(np.asarray(step, dtype=float), (n,))
    simplex = [x0.copy()]
    for k in range(n):
        v = x0.copy()
        v[k] += steps[k]
        simplex.append(v)
    fs = [f(v) for v in simplex]
    evals = n + 1
    while evals < max_evals:
        order = np.argsort(fs, kind="stable")
        simplex = [simplex[i] for i in order]
        fs = [fs[i] for i in order]
        if abs(fs[-1] - fs[0]) <= tol:
            break
        centroid = np.mean(simplex[:-1], axis=0)
        xr = centroid + (centroid - simplex[-1])
        fr = f(xr)
        evals += 1
        if fs[0] <= fr < fs[-2]:
            simplex[-1], fs[-1] = xr, fr
            continue
        if fr < fs[0]:
            xe = centroid + 2.0 * (xr - centroid)
            fe = f(xe)
            evals += 1
            if fe < fr:
                simplex[-1], fs[-1] = xe, fe
            else:
                simplex[-1], fs[-1] = xr, fr
            continue
        if fr < fs[-1]:                                   # outside contraction
            xc = centroid + 0.5 * (xr - centroid)
        else:                                             # inside contraction
            xc = centroid + 0.5 * (simplex[-1] - centroid)
        fc = f(xc)
        evals += 1
        if fc < min(fr, fs[-1]):
            simplex[-1], fs[-1] = xc, fc
            continue
        for k in range(1, n + 1):                         # shrink towards the best vertex
            simplex[k] = simplex[0] + 0.5 * (simplex[k] - simplex[0])
            fs[k] = f(simplex[k])
            evals += 1
    k = int(np.argmin(fs))
    return simplex[k], float(fs[k]), evals


def spsa(f: Callable[[np.ndarray], float], x0, iters: int, rng: np.random.Generator, a: float = 0.2,
         c: float = 0.15, alpha: float = 0.602, gamma: float = 0.101) -> np.ndarray:
    """Plain SPSA: 2 function calls per iteration. Returns the final parameters."""
    x = np.asarray(x0, dtype=float).copy()
    A = 0.1 * max(1, iters)
    for k in range(iters):
        ak = a / (k + 1 + A) ** alpha
        ck = c / (k + 1) ** gamma
        delta = rng.choice([-1.0, 1.0], size=x.size)
        g = (f(x + ck * delta) - f(x - ck * delta)) / (2.0 * ck) * delta
        x = x - ak * g
    return x
