"""Phase 2 quantum layer tests (docs/plans/PHASE2_QUANTUM.md §5). All deterministic."""
import itertools

import numpy as np
import pytest
import yaml

from core.instance import generate_instance
from core.market import _solve_workflow, run_market
from core.scoring import FastEvaluator, evaluate
from core.subproblem import SUBSOLVERS, BudgetExceeded, SubProblem
from core.subproblem.exact import exact_info
from core.subproblem.model import workflow_instance
from core.subproblem.qubo import build_qubo, onehot_vector

cfg = yaml.safe_load(open("config/demo.yaml"))


def _subproblems(seeds, rounds=(0, 12), max_tasks=5):
    """Priced sub-problems: workflows with 3..max_tasks tasks, integer-rounded market prices."""
    out = []
    for s in seeds:
        inst = generate_instance(cfg, s)
        ev = FastEvaluator(inst)
        mk = run_market(inst, rounds=max(rounds) + 1)
        for r in rounds:
            lam = [int(round(v)) for v in mk.prices[r]]
            for w, tasks in inst.workflows().items():
                if 3 <= len(tasks) <= max_tasks:
                    out.append((inst, ev, tasks, lam, SubProblem.from_workflow(inst, tasks, lam, ev)))
    return out


# 3 --------------------------------------------------------------------------------------------
def test_energy_equals_scoring_and_market():
    inst = generate_instance(cfg, 3)
    for w, tasks in inst.workflows().items():
        if len(tasks) > 5:
            continue
        sub_inst = workflow_instance(inst, w)
        sp = SubProblem.from_workflow(sub_inst, list(range(len(tasks))), [0] * inst.m)
        D = sp.diagonal()
        for x in itertools.product(range(inst.m), repeat=len(tasks)):
            e = sp.energy(x)
            assert e == evaluate(sub_inst, x).score
            assert e == int(D[x])
    # integer prices: optimum value equals market._solve_workflow's value exactly
    for inst_, ev, tasks, lam, sp in _subproblems([3], rounds=(12,)):
        _, v = _solve_workflow(ev, tasks, [float(l) for l in lam], inst_.m)
        assert exact_info(sp).e_star == v


# 4 --------------------------------------------------------------------------------------------
def test_bruteforce_matches_market_solver():
    n = 0
    for inst, ev, tasks, lam, sp in _subproblems(range(5)):
        xm, vm = _solve_workflow(ev, tasks, [float(l) for l in lam], inst.m)
        ref = exact_info(sp)
        assert ref.e_star == vm
        assert sp._energy(xm) == ref.e_star
        n += 1
    assert n >= 20


# 5 --------------------------------------------------------------------------------------------
def test_qubo_energy_matches_and_penalises():
    rng = np.random.default_rng(0)
    for _, _, _, _, sp in _subproblems([1], rounds=(12,))[:3]:
        qb = build_qubo(sp)
        for x in itertools.product(range(sp.m), repeat=sp.t):
            assert qb.energy(onehot_vector(x, sp.m)) == sp._energy(x)
        for _ in range(200):
            b = rng.integers(0, 2, size=qb.n)
            if qb.decode_onehot(b) is not None:
                continue
            k = b.reshape(sp.t, sp.m).sum(axis=1)
            pen = qb.penalty * int(((k - 1) ** 2).sum())
            assert pen > 0
            # QUBO - penalty = objective part, which is >= the coefficient lower offset
            assert qb.energy(b) - pen >= sp.lower_offset()
        # Ising form agrees with the QUBO on random spin vectors
        J, h, c = qb.ising()
        for _ in range(20):
            b = rng.integers(0, 2, size=qb.n)
            s = 2 * b - 1
            assert abs(s @ J @ s / 2 + h @ s + c - qb.energy(b)) < 1e-6 * max(1, abs(qb.energy(b)))


# 6 --------------------------------------------------------------------------------------------
BUDGETED = [k for k in SUBSOLVERS if k != "exact"]


def test_budget_enforced():
    sp = _subproblems([2], rounds=(12,))[0][-1]
    for name in BUDGETED:
        for B in (16, 64):
            sp.set_budget(B)
            res = SUBSOLVERS[name](sp, seed=0)
            assert 0 < sp.evals <= B and res.evals == sp.evals, name
            assert res.energy == sp._energy(res.x), name
    sp.set_budget(2)
    sp.energy((0,) * sp.t)
    sp.energy((1,) * sp.t)
    with pytest.raises(BudgetExceeded):
        sp.energy((2,) * sp.t)


# 7 --------------------------------------------------------------------------------------------
def test_subsolver_deterministic():
    sp = _subproblems([4], rounds=(12,))[0][-1]
    for name in BUDGETED:
        outs = []
        for _ in range(2):
            sp.set_budget(64)
            r = SUBSOLVERS[name](sp, seed=5)
            outs.append((r.x, r.energy, r.evals, sorted(r.info.items()).__repr__()))
        assert outs[0] == outs[1], name


# ------------------------------------------------------------------------------------------------
# Step 2: sub-problem solvers (SA, SQA, SB, QAOA-XY)
from core.subproblem import LABEL  # noqa: E402
from core.subproblem.qaoa_xy import (SubspaceQAOA, mixer_edges, mixer_groups,  # noqa: E402
                                     solve_ideal)

_X = np.array([[0, 1], [1, 0]], dtype=complex)
_Y = np.array([[0, -1j], [1j, 0]], dtype=complex)


def _xy_gate(beta):
    """exp(-i beta (XX + YY)/2), built from Pauli matrices (independent of qaoa_xy.py)."""
    G = (np.kron(_X, _X) + np.kron(_Y, _Y)) / 2
    w, V = np.linalg.eigh(G)
    return (V * np.exp(-1j * beta * w)) @ V.conj().T


def _full_qaoa(sp, mixer, gammas, betas):
    """Test-only full 2^n statevector: one-hot embedding, diagonal cost phase, local XX+YY gates."""
    t, m = sp.t, sp.m
    n = t * m
    E_sub = SubspaceQAOA(sp, mixer).E
    onehot_idx = {}
    for x in itertools.product(range(m), repeat=t):
        bits = [0] * n
        for i, d in enumerate(x):
            bits[i * m + d] = 1
        onehot_idx[x] = int("".join(map(str, bits)), 2)
    Efull = np.zeros(2 ** n)
    psi = np.zeros(2 ** n, dtype=complex)
    for x, k in onehot_idx.items():
        Efull[k] = E_sub[x]
        psi[k] = 1.0 / np.sqrt(m ** t)
    for g, b in zip(gammas, betas):
        psi = psi * np.exp(-1j * g * Efull)
        U = _xy_gate(b).reshape(2, 2, 2, 2)
        T = psi.reshape((2,) * n)
        for group in mixer_groups(m, mixer):
            for i in range(t):
                for d, e in group:
                    q, r = i * m + d, i * m + e
                    T = np.moveaxis(np.tensordot(U, T, axes=([2, 3], [q, r])), (0, 1), (q, r))
        psi = T.ravel()
    p = np.abs(psi) ** 2
    sub = np.array([p[onehot_idx[x]] for x in itertools.product(range(m), repeat=t)])
    return sub, 1.0 - sub.sum()


# 1 --------------------------------------------------------------------------------------------
def test_subspace_equals_full_statevector():
    rng = np.random.default_rng(11)
    small = SubProblem(m=3, lin=[[5, 1, 7], [2, 9, 4]], edges=[(0, 1, [[0, 3, 6], [3, 0, 2], [6, 2, 0]])])
    sp12 = _subproblems([0], rounds=(12,), max_tasks=3)[0][-1]
    assert (small.n_qubits, sp12.n_qubits) == (6, 12)
    for sp in (small, sp12):
        for mixer in ("ring", "complete"):
            gs, bs = rng.uniform(0, 3, 2), rng.uniform(0, 3, 2)          # p = 2, random angles
            full, leak = _full_qaoa(sp, mixer, gs, bs)
            sub = SubspaceQAOA(sp, mixer).probs(gs, bs)
            assert np.max(np.abs(full - sub)) < 1e-10, (sp.n_qubits, mixer)
            assert leak < 1e-12


# 2 --------------------------------------------------------------------------------------------
def test_mixer_structure_unitary_and_uniform_start():
    for m in (2, 3, 4, 5):
        for mixer in ("ring", "complete"):
            groups = mixer_groups(m, mixer)
            flat = [e for g in groups for e in g]
            assert sorted(tuple(sorted(e)) for e in flat) == sorted(tuple(sorted(e)) for e in mixer_edges(m, mixer))
            for g in groups:                                   # disjoint pairs => commuting
                qs = [q for e in g for q in e]
                assert len(qs) == len(set(qs))
    assert len(mixer_groups(4, "ring")) == 2 and len(mixer_groups(4, "complete")) == 3
    sp = _subproblems([0], rounds=(12,))[0][-1]
    for mixer in ("ring", "complete"):
        sim = SubspaceQAOA(sp, mixer)
        U = sim.register_unitary(0.7)
        assert np.allclose(U.conj().T @ U, np.eye(sp.m), atol=1e-12)
        # pair rotations within a group commute
        c, s = np.cos(0.7), np.sin(0.7)
        for g in sim.groups:
            mats = []
            for d, e in g:
                R = np.eye(sp.m, dtype=complex)
                R[d, d] = R[e, e] = c
                R[d, e] = R[e, d] = -1j * s
                mats.append(R)
            for A in mats:
                for B in mats:
                    assert np.allclose(A @ B, B @ A)
        p0 = sim.probs([0.0, 0.0], [0.0, 0.0])
        assert np.allclose(p0, 1.0 / sp.n_states, atol=1e-14)
        assert abs(np.linalg.norm(sim.state([1.3, 0.4], [0.2, 0.9])) - 1.0) < 1e-12


# 8 --------------------------------------------------------------------------------------------
def test_qaoa_ideal_beats_uniform_floor():
    """Sanity floor only (NOT an advantage claim): optimised p = 3 puts more weight on the optimum
    than the uniform superposition on a fixed 12-qubit case."""
    sp = _subproblems([0], rounds=(12,), max_tasks=3)[0][-1]
    D = sp.diagonal().ravel()
    opt = D == D.min()
    uniform = opt.sum() / sp.n_states
    for mixer in ("ring", "complete"):
        sp.set_budget(16)
        r = solve_ideal(sp, seed=0, mixer=mixer, p=3)
        p = SubspaceQAOA(sp, mixer).probs(r.info["gammas"], r.info["betas"])
        assert p[opt].sum() >= uniform


def test_labels_are_honest():
    assert LABEL["sa"] == "classical"
    for k in ("sqa", "sb_ballistic", "sb_discrete"):
        assert LABEL[k] == "quantum-inspired"
    for k in SUBSOLVERS:
        if k.startswith("qaoa"):
            assert LABEL[k].startswith("quantum algorithm, classically simulated")
    assert not any("advantage" in v for v in LABEL.values())


def test_subsolvers_feasible_and_agree_with_exact_on_small():
    """Every budgeted sub-solver returns a valid one-hot assignment whose energy is >= E*, and with a
    generous budget (B = 256 on 64-state 3-task sub-problems) the best of 5 seeds hits the exact optimum."""
    sps = [x[-1] for x in _subproblems([0, 1], rounds=(0, 12), max_tasks=3)][:4]
    assert len(sps) == 4
    for sp in sps:
        ref = exact_info(sp)
        for name in BUDGETED:
            best = None
            for seed in range(5):
                sp.set_budget(256)
                r = SUBSOLVERS[name](sp, seed=seed)
                assert len(r.x) == sp.t and all(0 <= d < sp.m for d in r.x), name
                assert r.energy == sp._energy(r.x) >= ref.e_star, name
                best = r.energy if best is None else min(best, r.energy)
            assert best == ref.e_star, name


def test_sb_reports_raw_feasibility():
    sp = _subproblems([2], rounds=(12,))[0][-1]
    for name in ("sb_ballistic", "sb_discrete"):
        sp.set_budget(32)
        r = SUBSOLVERS[name](sp, seed=1)
        assert 0.0 <= r.info["feasible_rate"] <= 1.0 and r.info["trajectories"] == 32


# 9 --------------------------------------------------------------------------------------------
def _no_wall(rows):
    return [{k: v for k, v in r.items() if k != "wall_s_mean"} for r in rows]


def test_benchmark_smoke(tmp_path):
    """Fair-comparison runner, smoke mode: 2 sub-problems x 2 seeds x B = 16, < 15 s, expected files."""
    import csv
    import time

    from experiments.quantum_benchmark import RAW_COLUMNS, SUMMARY_COLUMNS, run
    t0 = time.perf_counter()
    res = run(smoke=True, out_dir=str(tmp_path), workers=1, log=lambda *_: None)
    assert time.perf_counter() - t0 < 15
    for f in ("raw.csv", "summary.csv", "summary_by_size.csv", "classical_vs.csv", "manifest.json", "tuning.json"):
        assert (tmp_path / f).exists(), f
    with open(tmp_path / "raw.csv", encoding="utf-8") as fh:
        raw = list(csv.DictReader(fh))
    assert list(raw[0].keys()) == RAW_COLUMNS
    methods = {r["method"] for r in raw}
    assert methods == set(SUBSOLVERS) - {"exact"}
    assert len(raw) == 2 * 2 * len(methods) == res["n_rows"]
    assert all(int(r["evals"]) <= int(r["budget"]) == 16 for r in raw)
    with open(tmp_path / "summary.csv", encoding="utf-8") as fh:
        assert next(csv.reader(fh)) == SUMMARY_COLUMNS
    # deterministic apart from wall-clock
    res2 = run(smoke=True, out_dir=str(tmp_path / "again"), workers=1, log=lambda *_: None)
    assert _no_wall(res["summary"]) == _no_wall(res2["summary"])


def test_market_lower_bound_stays_exact():
    """QAOA may only supply the market's UPPER bound; the lower bound equals the exact market's."""
    from experiments.quantum_benchmark import LOWER_BOUND_SOLVER, market_with_ub_solver
    assert LOWER_BOUND_SOLVER == "exact"
    inst = generate_instance(cfg, 0)
    r = market_with_ub_solver(inst, rounds=3, solver="qaoa_ring", budget=16, params={}, seed=0)
    ref = run_market(inst, rounds=3)
    assert r["lower"] == ref.best_lower == r["exact_lower"]
    assert r["upper"] >= r["lower"]
