"""Integer Lagrangian price market — exact mirror of chain/contracts/PriceMarket.sol (Phase 3).

STATUS: IMPLEMENTED. Pure integers, no web3 (AGENTS.md rule 4). The float market in core/market.py is unchanged.

  V_w(x_w, lam) = sum_{j in w} [wC*E_j*ci[x_j]*1000 + wP*E_j*price[x_j] + lam[x_j]*cpu_j]
                + sum_{edges in w, x_a != x_b} [wC*floor(vol*net*(ci_a+ci_b)/2) + wP*vol*egress]
  g(lam)        = sum_w min V_w - sum_d lam_d*cap_d                     (int; may be negative)
  next lam_d    = max(0, lam_d + tdiv(step_k*(load_d - cap_d)*m, sum(cap)))   (tdiv truncates toward zero,
                                                                              like Solidity signed division)
  gap_bps       = 10000 if lb <= 0; 0 if lb >= ub; else (ub - lb)*10000 // ub

At lam = 0, sum_w V_w(x) == core.scoring.evaluate(x).score (edges never cross workflows).
Round rules (same as the contract): the minimum value per workflow is kept (strictly smaller replaces, so the
first submitter of a tie stays); a round is COMPLETE when every workflow has a submission; only complete rounds
give a dual value / lower bound and update the prices; an incomplete round leaves the prices unchanged.
"""
from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

from .instance import Instance
from .scoring import FastEvaluator, edge_carbon, edge_cost, task_carbon, task_cost
from .solvers.common import cost_scale

BPS = 10_000
MAX_WF_TASKS = 32          # contract limit (packed assignment, 8 bits per task)
MAX_EXACT_TASKS = 7        # brute-force limit of exact_workflow_min (m^k candidates)


def tdiv(a: int, b: int) -> int:
    """Integer division truncating toward zero (Solidity int256 '/'). Python '//' floors instead."""
    if b == 0:
        raise ZeroDivisionError("tdiv by zero")
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


@dataclass(frozen=True)
class Layout:
    task_start: list[int]      # W + 1 entries
    edge_start: list[int]      # W + 1 entries

    @property
    def workflows(self) -> int:
        return len(self.task_start) - 1

    def tasks(self, w: int) -> range:
        return range(self.task_start[w], self.task_start[w + 1])

    def edges(self, w: int) -> range:
        return range(self.edge_start[w], self.edge_start[w + 1])


def workflow_layout(inst: Instance) -> Layout:
    """Contiguous task / edge blocks per workflow, checked exactly like PriceMarket.openMarket."""
    ts, es = [0], [0]
    wf_of = [t.workflow for t in inst.tasks]
    order = []
    for j, w in enumerate(wf_of):
        if not order or order[-1] != w:
            if w in order:
                raise ValueError("tasks of a workflow are not contiguous")
            order.append(w)
            if j:
                ts.append(j)
    ts.append(inst.n)
    e = 0
    for wi in range(len(order)):
        a, b = ts[wi], ts[wi + 1]
        while e < len(inst.edges) and a <= inst.edges[e].j < b:
            ed = inst.edges[e]
            if not (a <= ed.k < b):
                raise ValueError(f"edge {e} crosses a workflow boundary")
            e += 1
        es.append(e)
    if e != len(inst.edges):
        raise ValueError("edges are not grouped by workflow in task order")
    for wi in range(len(order)):
        if ts[wi + 1] - ts[wi] > MAX_WF_TASKS:
            raise ValueError(f"workflow {wi} has more than {MAX_WF_TASKS} tasks")
    return Layout(ts, es)


# ------------------------------------------------------------------------------- parity surface
def workflow_value(inst: Instance, lay: Layout, w: int, xw: Sequence[int], lam: Sequence[int]) -> int:
    a = lay.task_start[w]
    if len(xw) != lay.task_start[w + 1] - a or len(lam) != inst.m:
        raise ValueError("bad input")
    v = 0
    for i, d in enumerate(xw):
        if not 0 <= d < inst.m:
            raise ValueError("region out of range")
        j = a + i
        v += (inst.w_carbon * task_carbon(inst, j, d) + inst.w_cost * task_cost(inst, j, d)
              + lam[d] * inst.tasks[j].cpu)
    for e in lay.edges(w):
        ed = inst.edges[e]
        p, q = xw[ed.j - a], xw[ed.k - a]
        v += inst.w_carbon * edge_carbon(inst, ed.volume_mb, p, q) + inst.w_cost * edge_cost(inst, ed.volume_mb, p, q)
    return v


def priced_capacity(inst: Instance, lam: Sequence[int]) -> int:
    return sum(l * r.capacity for l, r in zip(lam, inst.regions))


def dual_value(inst: Instance, lay: Layout, x: Sequence[int], lam: Sequence[int]) -> int:
    if len(x) != inst.n:
        raise ValueError("bad input")
    s = sum(workflow_value(inst, lay, w, x[lay.task_start[w]:lay.task_start[w + 1]], lam)
            for w in range(lay.workflows))
    return s - priced_capacity(inst, lam)


def next_prices(lam: Sequence[int], loads: Sequence[int], cap: Sequence[int], step: int, m: int) -> list[int]:
    if not (len(lam) == len(loads) == len(cap)) or sum(cap) == 0:
        raise ValueError("bad input")
    sc = sum(cap)
    return [max(0, l + tdiv(step * (ld - c) * m, sc)) for l, ld, c in zip(lam, loads, cap)]


def gap_bps(ub: int, lb: int) -> int:
    if lb <= 0:
        return BPS
    if lb >= ub:
        return 0
    return (ub - lb) * BPS // ub


def default_steps(inst: Instance, rounds: int, step0: float = 1.0) -> list[int]:
    """Integer step schedule fixed at openMarket: round(step0 * scale / sqrt(k + 1)), with the same price scale
    as core/market.py (typical move cost per average core). Computed off-chain once; the chain only stores it."""
    ev = FastEvaluator(inst)
    scale = cost_scale(ev) / (sum(ev.cpu) / len(ev.cpu))
    return [max(1, int(round(step0 * scale / math.sqrt(k + 1)))) for k in range(rounds)]


# ------------------------------------------------------------------------------- honest exact submitter
@lru_cache(maxsize=None)
def _grid(m: int, k: int) -> np.ndarray:
    """All m^k assignments in itertools.product (lexicographic) order."""
    return np.array(list(itertools.product(range(m), repeat=k)), dtype=np.int64).reshape(-1, k)


def exact_workflow_min(inst: Instance, lay: Layout, w: int, lam: Sequence[int],
                       worst: bool = False) -> tuple[list[int], int]:
    """argmin_{x_w} V_w(x_w, lam) by brute force; ties -> lexicographically first assignment.
    worst=True returns the argmax instead (used to model a dishonest submitter in experiments/tests).
    Uses int64 numpy when every value provably fits, otherwise exact Python ints."""
    tasks = list(lay.tasks(w))
    k, m = len(tasks), inst.m
    if k > MAX_EXACT_TASKS:
        raise ValueError(f"workflow {w} too large for exact solving ({k} > {MAX_EXACT_TASKS} tasks)")
    a = tasks[0]
    lin = [[inst.w_carbon * task_carbon(inst, j, d) + inst.w_cost * task_cost(inst, j, d) + lam[d] * inst.tasks[j].cpu
            for d in range(m)] for j in tasks]
    emats = []
    for e in lay.edges(w):
        ed = inst.edges[e]
        mat = [[inst.w_carbon * edge_carbon(inst, ed.volume_mb, p, q) + inst.w_cost * edge_cost(inst, ed.volume_mb, p, q)
                for q in range(m)] for p in range(m)]
        emats.append((ed.j - a, ed.k - a, mat))
    bound = sum(max(r) for r in lin) + sum(max(max(r) for r in mat) for _, _, mat in emats)
    if bound < 2 ** 62:
        g = _grid(m, k)
        v = np.zeros(len(g), dtype=np.int64)
        for i in range(k):
            v += np.asarray(lin[i], dtype=np.int64)[g[:, i]]
        for p, q, mat in emats:
            v += np.asarray(mat, dtype=np.int64)[g[:, p], g[:, q]]
        i = int(np.argmax(v) if worst else np.argmin(v))       # first extremum = lexicographic tie rule
        xw = [int(d) for d in g[i]]
    else:                                                      # exact fallback for huge integers
        best, xw = None, None
        sign = -1 if worst else 1
        for cand in itertools.product(range(m), repeat=k):
            val = sign * (sum(lin[i][cand[i]] for i in range(k)) + sum(mat[cand[p]][cand[q]] for p, q, mat in emats))
            if best is None or val < best:
                best, xw = val, list(cand)
    return xw, workflow_value(inst, lay, w, xw, lam)


# ------------------------------------------------------------------------------- round state machine
@dataclass
class RoundRecord:
    k: int
    lam: list[int]
    complete: bool
    dual_value: int            # 0 when incomplete (as on chain)
    loads: list[int]
    next_lam: list[int]
    x: list[int | None]        # kept assignment per task (None = workflow not submitted)
    submitted: int
    kept: dict[int, tuple[int, list[int]]] = field(default_factory=dict)   # w -> (min value, x_w)


# Phase 4 fraud-proof parameters (PriceMarket.CLAIM_BOND / CHALLENGE_WINDOW)
CLAIM_BOND = 10**18
CHALLENGE_WINDOW = 3600


class MarketError(ValueError):
    """Raised with the contract's custom-error name (e.g. 'NotCheaper')."""


@dataclass
class Claim:
    claimant: str
    start: int
    active: bool = True
    finalized: bool = False
    bond: int = CLAIM_BOND


@dataclass
class MarketState:
    """Python twin of one PriceMarket market (submit / close semantics identical to the contract)."""
    inst: Instance
    steps: list[int]
    lay: Layout = None  # type: ignore[assignment]
    lam: list[int] = field(default_factory=list)
    round: int = 0
    best_lb: int | None = None
    best_lb_round: int | None = None
    history: list[RoundRecord] = field(default_factory=list)
    _cur: dict[int, tuple[int, list[int]]] = field(default_factory=dict)
    # Phase 4 bookkeeping (mirror of claimBound / challenge / finalizeBound / withdraw)
    claims: dict[int, Claim] = field(default_factory=dict)
    withdrawable: dict[str, int] = field(default_factory=dict)
    slashed_pool: int = 0
    cert_lb: int | None = None
    cert_lb_round: int | None = None

    def __post_init__(self) -> None:
        if self.lay is None:
            self.lay = workflow_layout(self.inst)
        if not self.steps:
            raise ValueError("need at least one round")
        self.lam = [0] * self.inst.m

    @property
    def finished(self) -> bool:
        return self.round >= len(self.steps)

    def submit(self, w: int, xw: Sequence[int]) -> tuple[int, bool]:
        if self.finished:
            raise ValueError("MarketClosed")
        v = workflow_value(self.inst, self.lay, w, list(xw), self.lam)
        improved = w not in self._cur or v < self._cur[w][0]
        if improved:
            self._cur[w] = (v, list(xw))
        return v, improved

    def submit_batch(self, x: Sequence[int]) -> None:
        if len(x) != self.inst.n:
            raise ValueError("bad input")
        for w in range(self.lay.workflows):
            self.submit(w, x[self.lay.task_start[w]:self.lay.task_start[w + 1]])

    def close_round(self) -> RoundRecord:
        if self.finished:
            raise ValueError("MarketClosed")
        inst, lay, k = self.inst, self.lay, self.round
        loads = [0] * inst.m
        x: list[int | None] = [None] * inst.n
        sum_v = 0
        for w, (v, xw) in self._cur.items():
            sum_v += v
            for i, d in enumerate(xw):
                j = lay.task_start[w] + i
                loads[d] += inst.tasks[j].cpu
                x[j] = d
        complete = len(self._cur) == lay.workflows
        cap = [r.capacity for r in inst.regions]
        g, nxt = 0, list(self.lam)
        if complete:
            g = sum_v - priced_capacity(inst, self.lam)
            if self.best_lb is None or g > self.best_lb:
                self.best_lb, self.best_lb_round = g, k
            nxt = next_prices(self.lam, loads, cap, self.steps[k], inst.m)
        rec = RoundRecord(k, list(self.lam), complete, g, loads, nxt, x, len(self._cur), dict(self._cur))
        self.history.append(rec)
        self.lam = nxt
        self.round += 1
        self._cur = {}
        return rec

    # ---------------------------------------------------------------- Phase 4: optimistic fraud proofs
    def _claimable(self, k: int) -> RoundRecord:
        if k >= len(self.history) or not self.history[k].complete:
            raise MarketError("RoundNotClaimable")
        return self.history[k]

    def claim_bound(self, k: int, claimant: str, now: int, bond: int = CLAIM_BOND) -> None:
        self._claimable(k)
        c = self.claims.get(k)
        if c is not None and (c.active or c.finalized):
            raise MarketError("AlreadyClaimed")
        if bond != CLAIM_BOND:
            raise MarketError("BadBond")
        self.claims[k] = Claim(claimant, now, bond=bond)

    def challenge(self, k: int, w: int, xw: Sequence[int], challenger: str, now: int) -> bool:
        """Returns True if an active claim was cancelled."""
        rec = self._claimable(k)
        c = self.claims.get(k)
        if c is not None and c.finalized:
            raise MarketError("RoundFinalized")
        if c is not None and c.active and now >= c.start + CHALLENGE_WINDOW:
            raise MarketError("WindowClosed")
        v = workflow_value(self.inst, self.lay, w, list(xw), rec.lam)
        old = rec.kept[w][0]
        if v >= old:
            raise MarketError("NotCheaper")
        rec.kept[w] = (v, list(xw))
        rec.dual_value -= old - v
        if c is not None and c.active:
            half = c.bond // 2
            self.withdrawable[challenger] = self.withdrawable.get(challenger, 0) + half
            self.slashed_pool += c.bond - half
            c.active, c.bond = False, 0
            return True
        return False

    def finalize_bound(self, k: int, now: int) -> None:
        c = self.claims.get(k)
        if c is None or not c.active:
            raise MarketError("NoClaim")
        if now < c.start + CHALLENGE_WINDOW:
            raise MarketError("WindowOpen")
        g = self.history[k].dual_value
        c.active, c.finalized = False, True
        self.withdrawable[c.claimant] = self.withdrawable.get(c.claimant, 0) + c.bond
        c.bond = 0
        if self.cert_lb is None or g > self.cert_lb:
            self.cert_lb, self.cert_lb_round = g, k

    def honest_assignment(self) -> list[int]:
        """Combined exact per-workflow minimisers at the current prices (what an honest submitter sends)."""
        x: list[int] = []
        for w in range(self.lay.workflows):
            xw, _ = exact_workflow_min(self.inst, self.lay, w, self.lam)
            x += xw
        return x


def run_market_int(inst: Instance, steps: Sequence[int]) -> MarketState:
    """All rounds with one honest exact submitter per round (submitBatch of the exact minimisers)."""
    st = MarketState(inst, list(steps))
    while not st.finished:
        st.submit_batch(st.honest_assignment())
        st.close_round()
    return st
