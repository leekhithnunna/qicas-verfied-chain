"""QUBO / Ising form of a sub-problem with a one-hot penalty. STATUS: IMPLEMENTED

Binary variable b[q], q = i*m + d  (1 = task i placed in region d).

    QUBO(b) = offset + sum_q Q[q,q] b_q + sum_{q<r} Q[q,r] b_q b_r          (integers)
            = sum_i lin'_i . b_i + sum_edges b_a^T pair b_b + A * sum_i (sum_d b_{i,d} - 1)^2 + sum_i min_d lin_i

lin'_i = lin_i - min_d lin_i (shifted to >= 0). With
    A = 1 + max_i ( max_d lin'_i[d] + sum_{edges at i} max(pair) )
every single-bit-flip local minimum is one-hot (an empty register is always improved by adding a bit,
a register with >= 2 bits by removing one). On one-hot vectors QUBO(b) == SubProblem energy exactly
(tests/test_quantum.py, test 5). Used by simulated bifurcation (penalty-based feasibility) and the docs;
QAOA-XY does NOT need the penalty (its mixer keeps the state one-hot).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .model import SubProblem


@dataclass
class Qubo:
    Q: np.ndarray       # (n, n) int64, upper-triangular incl. diagonal
    offset: int
    penalty: int
    t: int
    m: int

    @property
    def n(self) -> int:
        return self.Q.shape[0]

    def energy(self, b) -> int:
        b = np.asarray(b, dtype=np.int64)
        return int(b @ self.Q @ b) + self.offset

    def ising(self) -> tuple[np.ndarray, np.ndarray, float]:
        """Return (J, h, const) as floats with E = s^T J s / 2 + h . s + const, s in {-1,+1}^n,
        J symmetric with zero diagonal."""
        Q = self.Q.astype(float)
        diag = np.diag(Q).copy()
        U = np.triu(Q, 1)
        # b = (1+s)/2:  U b_q b_r = U (1 + s_q + s_r + s_q s_r)/4,  D b_q = D (1 + s_q)/2
        J = (U + U.T) / 4.0                       # sum_{q<r} U/4 s_q s_r = s^T J s / 2
        h = diag / 2.0 + J.sum(axis=1)
        const = diag.sum() / 2.0 + U.sum() / 4.0 + self.offset
        return J, h, const

    def decode_onehot(self, b) -> tuple[int, ...] | None:
        B = np.asarray(b).reshape(self.t, self.m)
        if not np.all(B.sum(axis=1) == 1):
            return None
        return tuple(int(v) for v in B.argmax(axis=1))


def build_qubo(sp: SubProblem) -> Qubo:
    t, m = sp.t, sp.m
    n = t * m
    Q = np.zeros((n, n), dtype=np.int64)
    offset = 0
    lin_shift = []
    for i in range(t):
        lo = min(sp.lin[i])
        offset += lo
        lin_shift.append([v - lo for v in sp.lin[i]])
    incident = [0] * t
    for a, b, mat in sp.edges:
        mx = max(max(r) for r in mat)
        incident[a] += mx
        incident[b] += mx
    A = 1 + max(max(lin_shift[i]) + incident[i] for i in range(t))
    for i in range(t):
        for d in range(m):
            q = i * m + d
            Q[q, q] += lin_shift[i][d] - A                 # A*(b^2 - 2b) = -A*b on the diagonal
            for e in range(d + 1, m):
                Q[q, i * m + e] += 2 * A
    offset += A * t
    for a, b, mat in sp.edges:
        for d in range(m):
            for e in range(m):
                q, r = a * m + d, b * m + e
                lo_, hi_ = (q, r) if q < r else (r, q)
                Q[lo_, hi_] += mat[d][e]
    return Qubo(Q=Q, offset=offset, penalty=A, t=t, m=m)


def onehot_vector(x, m: int) -> np.ndarray:
    b = np.zeros(len(x) * m, dtype=np.int64)
    for i, d in enumerate(x):
        b[i * m + d] = 1
    return b
