"""Phase 3: PriceMarket.sol <-> core/market_int.py parity, weak duality, min-keeping, attacks, validation.

Plan: docs/plans/PHASE3_PRICE_MARKET.md section 6. The artifact guard (item 12) is tests/test_artifacts.py."""
import copy
import itertools
import random

import pytest
import yaml

from chain.client import Chain, new_salt
from chain.price_market import PriceMarketClient
from core.instance import generate_instance
from core.market_int import (Layout, MarketState, dual_value, exact_workflow_min, gap_bps, next_prices, tdiv,
                             default_steps, run_market_int, workflow_layout, workflow_value)
from core.scoring import evaluate
from core.solvers import SOLVERS

ROUNDS = 25


@pytest.fixture(scope="module")
def env():
    cfg = yaml.safe_load(open("config/demo.yaml"))
    inst = generate_instance(cfg, 3)
    chain = Chain.start("memory")
    eid = chain.publish(inst)
    pm = PriceMarketClient(chain)
    lay = workflow_layout(inst)
    steps = default_steps(inst, ROUNDS)
    mid = pm.open_market(eid, inst, steps)
    return {"cfg": cfg, "inst": inst, "chain": chain, "eid": eid, "pm": pm, "lay": lay, "steps": steps, "mid": mid}


def _rand_lam(rng, m):
    return [rng.choice([0, rng.randrange(10**6), rng.randrange(10**9), rng.randrange(10**12)]) for _ in range(m)]


# 0. Python helpers ---------------------------------------------------------------------------------------
def test_tdiv_truncates_toward_zero():
    assert tdiv(7, 2) == 3 and tdiv(-7, 2) == -3 and tdiv(7, -2) == -3 and tdiv(-7, -2) == 3
    assert (-7) // 2 == -4          # the hazard tdiv avoids


def test_layout_is_contiguous(env):
    inst, lay = env["inst"], env["lay"]
    assert lay.task_start[0] == 0 and lay.task_start[-1] == inst.n and lay.edge_start[-1] == len(inst.edges)
    for w in range(lay.workflows):
        assert {inst.tasks[j].workflow for j in lay.tasks(w)} == {w}


# 1. workflowValue parity ---------------------------------------------------------------------------------
def test_workflow_value_parity(env):
    inst, lay, pm, mid = env["inst"], env["lay"], env["pm"], env["mid"]
    rng = random.Random(11)
    for _ in range(50):
        w = rng.randrange(lay.workflows)
        xw = [rng.randrange(inst.m) for _ in lay.tasks(w)]
        lam = _rand_lam(rng, inst.m)
        assert pm.workflow_value(mid, w, xw, lam) == workflow_value(inst, lay, w, xw, lam)


# 2. dualValueOf parity incl. negative --------------------------------------------------------------------
def test_dual_value_parity_including_negative(env):
    inst, lay, pm, mid = env["inst"], env["lay"], env["pm"], env["mid"]
    rng = random.Random(12)
    seen_negative = False
    for i in range(30):
        x = [rng.randrange(inst.m) for _ in range(inst.n)]
        lam = [10**12 + rng.randrange(10**12) for _ in range(inst.m)] if i % 3 == 0 else _rand_lam(rng, inst.m)
        g = dual_value(inst, lay, x, lam)
        seen_negative |= g < 0
        assert pm.dual_value_of(mid, x, lam) == g
    assert seen_negative


# 3. nextPrices parity, fuzzed, both signs ------------------------------------------------------------------
def test_next_prices_parity_fuzz(env):
    pm = env["pm"]
    rng = random.Random(13)
    neg = 0
    for _ in range(200):
        m = rng.randint(1, 6)
        cap = [rng.randint(0, 50) for _ in range(m)]
        if sum(cap) == 0:
            cap[0] = 1
        loads = [rng.randint(0, 100) for _ in range(m)]
        lam = [rng.choice([0, rng.randrange(1000), rng.randrange(10**15)]) for _ in range(m)]
        step = rng.choice([1, rng.randrange(10**3), rng.randrange(10**12)])
        neg += sum(1 for l, c in zip(loads, cap) if l < c and (step * (c - l) * m) % sum(cap))
        assert pm.next_prices(lam, loads, cap, step, m) == next_prices(lam, loads, cap, step, m)
    assert neg > 50          # many negative imbalances with a non-zero remainder: floor != trunc there


# 4. gapBps parity ----------------------------------------------------------------------------------------
def test_gap_bps_parity(env):
    pm = env["pm"]
    rng = random.Random(14)
    cases = [(100, 0), (100, -5), (100, 100), (100, 150), (100, 99), (1, 1), (10**9, 638_827_640)]
    cases += [(rng.randint(1, 10**12), rng.randint(-10**12, 10**12)) for _ in range(40)]
    for ub, lb in cases:
        assert pm.gap_bps(ub, lb) == gap_bps(ub, lb)
    assert gap_bps(100, 0) == 10_000 and gap_bps(100, 100) == 0 and gap_bps(100, 99) == 100


# 5. cross-contract: sum V_w at lambda = 0 == CarbonScheduleMarket.evaluate ---------------------------------
def test_sum_of_workflow_values_at_zero_prices_equals_case_study_score(env):
    inst, lay, pm, mid, chain, eid = env["inst"], env["lay"], env["pm"], env["mid"], env["chain"], env["eid"]
    rng = random.Random(15)
    zero = [0] * inst.m
    for _ in range(10):
        x = [rng.randrange(inst.m) for _ in range(inst.n)]
        onchain = sum(pm.workflow_value(mid, w, x[lay.task_start[w]:lay.task_start[w + 1]], zero)
                      for w in range(lay.workflows))
        assert onchain == chain.evaluate(eid, x)[0] == evaluate(inst, x).score
        assert pm.dual_value_of(mid, x, zero) == evaluate(inst, x).score


# 6. full-run parity: 25 on-chain rounds == run_market_int ------------------------------------------------
@pytest.fixture(scope="module")
def full_run(env):
    inst, pm, mid, steps = env["inst"], env["pm"], env["mid"], env["steps"]
    py = run_market_int(inst, steps)
    solver = pm.accounts[1]
    chain_rounds = []
    for rec in py.history:
        assert pm.prices(mid) == rec.lam
        x = [d for d in rec.x]
        pm.submit_batch(mid, x, solver)
        chain_rounds.append(pm.close_round(mid))
    return py, chain_rounds


def test_full_run_parity(env, full_run):
    pm, mid = env["pm"], env["mid"]
    py, ch = full_run
    assert len(ch) == ROUNDS
    for rec, c in zip(py.history, ch):
        assert c["complete"] and rec.complete
        assert (c["lam"], c["dual_value"], c["loads"], c["next_lam"]) == (rec.lam, rec.dual_value, rec.loads,
                                                                         rec.next_lam)
        info = pm.round_info(mid, rec.k)
        assert info == {"closed": True, "complete": True, "submitted": env["lay"].workflows,
                        "dual_value": rec.dual_value}
    assert pm.best_lower_bound(mid) == (True, py.best_lb, py.best_lb_round)
    assert pm.prices(mid) == py.lam
    assert any(r.dual_value < 0 for r in py.history) or py.best_lb > 0
    # after the last round the market is finished
    with pytest.raises(RuntimeError, match="MarketClosed"):
        pm.close_round(mid)


# 7. weak duality -------------------------------------------------------------------------------------------
def test_weak_duality_vs_revealed_scores_and_certified_gap(env, full_run):
    inst, chain, eid, pm, mid = env["inst"], env["chain"], env["eid"], env["pm"], env["mid"]
    py, _ = full_run
    with pytest.raises(Exception):
        pm.certified_gap_bps(mid)                          # no reveal yet -> no upper bound
    scores = []
    for i, name in enumerate(["greedy", "sa"]):
        x, _ = SOLVERS[name](inst, seed=0)
        a, s = chain.accounts[3 + i], new_salt()
        chain.commit(eid, a, x, s, 10**18)
        scores.append(evaluate(inst, x).score)
        env.setdefault("reveals", []).append((a, x, s))
    chain.open_reveal(eid)
    for a, x, s in env["reveals"]:
        assert chain.reveal(eid, a, x, s)["status"] == "accepted"
    _, lb, _ = pm.best_lower_bound(mid)
    assert lb <= min(scores)
    ub = chain.summary(eid)["best_score"]
    assert ub == min(scores)
    assert pm.certified_gap_bps(mid) == gap_bps(ub, lb)


def _tiny(seed=5):
    cfg = yaml.safe_load(open("config/demo.yaml"))
    cfg = copy.deepcopy(cfg)
    cfg["workflows"], cfg["tasks_per_workflow"] = 2, [3, 3]
    return generate_instance(cfg, seed)


def _brute_opt(inst):
    best = None
    for x in itertools.product(range(inst.m), repeat=inst.n):
        e = evaluate(inst, x)
        if e.feasible and (best is None or e.score < best):
            best = e.score
    return best


@pytest.fixture(scope="module")
def tiny():
    inst = _tiny()
    chain = Chain.start("memory")
    eid = chain.publish(inst)
    pm = PriceMarketClient(chain)
    return {"inst": inst, "chain": chain, "eid": eid, "pm": pm, "opt": _brute_opt(inst),
            "steps": default_steps(inst, 10)}


def test_weak_duality_tiny_instance_brute_force(tiny):
    inst, pm, steps = tiny["inst"], tiny["pm"], tiny["steps"]
    mid = pm.open_market(tiny["eid"], inst, steps)
    py = run_market_int(inst, steps)
    for rec in py.history:
        pm.submit_batch(mid, rec.x, pm.accounts[1])
        pm.close_round(mid)
    has, lb, _ = pm.best_lower_bound(mid)
    assert has and lb == py.best_lb
    assert lb <= tiny["opt"]
    # every complete round's g is itself a valid bound
    assert all(r.dual_value <= tiny["opt"] for r in py.history)


# 8. min-keeping ------------------------------------------------------------------------------------------
def test_inflated_submission_does_not_raise_kept_minimum(tiny):
    inst, pm = tiny["inst"], tiny["pm"]
    mid = pm.open_market(tiny["eid"], inst, [1])
    lay = workflow_layout(inst)
    honest, attacker = pm.accounts[1], pm.accounts[2]
    lam = [0] * inst.m
    xh, vh = exact_workflow_min(inst, lay, 0, lam)
    xa = max(itertools.product(range(inst.m), repeat=len(xh)), key=lambda c: workflow_value(inst, lay, 0, c, lam))
    r1 = pm.submit(mid, 0, xh, honest)
    r2 = pm.submit(mid, 0, list(xa), attacker)
    assert r1["improved"] and not r2["improved"] and r2["value"] > r1["value"] == vh
    assert pm.workflow_best(mid, 0, 0, len(xh)) == (True, vh, xh)
    # the other order: the honest minimum replaces an earlier inflated one
    r3 = pm.submit(mid, 1, list(exact_workflow_min(inst, lay, 1, lam)[0]), honest)
    assert r3["improved"]
    st = MarketState(inst, [1])
    st.submit(0, xh)
    assert st.submit(0, list(xa)) == (r2["value"], False)


# 9. documented vulnerability ----------------------------------------------------------------------------
def test_lone_dishonest_submitter_can_inflate_lower_bound_above_optimum(tiny):
    """Why Phase 4 fraud proofs are needed: with no honest submitter for a workflow, the kept 'minimum' is not
    a minimum, and the 'certified' lower bound exceeds the true optimum."""
    inst, pm = tiny["inst"], tiny["pm"]
    lay = workflow_layout(inst)
    mid = pm.open_market(tiny["eid"], inst, [1])
    lam = [0] * inst.m
    for w in range(lay.workflows):
        k = len(lay.tasks(w))
        worst = max(itertools.product(range(inst.m), repeat=k), key=lambda c: workflow_value(inst, lay, w, c, lam))
        pm.submit(mid, w, list(worst), pm.accounts[2])
    pm.close_round(mid)
    _, lb, _ = pm.best_lower_bound(mid)
    assert lb > tiny["opt"]


# 10. incomplete round ------------------------------------------------------------------------------------
def test_incomplete_round_gives_no_bound_and_keeps_prices(tiny):
    inst, pm = tiny["inst"], tiny["pm"]
    lay = workflow_layout(inst)
    steps = tiny["steps"][:3]
    mid = pm.open_market(tiny["eid"], inst, steps)
    st = MarketState(inst, steps)
    xw, _ = exact_workflow_min(inst, lay, 0, [0] * inst.m)
    pm.submit(mid, 0, xw, pm.accounts[1])
    st.submit(0, xw)
    c, p = pm.close_round(mid), st.close_round()
    assert not c["complete"] and not p.complete
    assert c["dual_value"] == p.dual_value == 0 and c["next_lam"] == c["lam"] == p.next_lam
    assert c["loads"] == p.loads
    assert pm.best_lower_bound(mid) == (False, 0, 0) and st.best_lb is None
    with pytest.raises(Exception):
        pm.certified_gap_bps(mid)                                   # NoLowerBound
    # a later complete round does count
    x = st.honest_assignment()
    pm.submit_batch(mid, x, pm.accounts[1])
    st.submit_batch(x)
    assert pm.close_round(mid)["dual_value"] == st.close_round().dual_value
    assert pm.best_lower_bound(mid) == (True, st.best_lb, 1)


# 11. validation reverts ----------------------------------------------------------------------------------
def test_validation_reverts(tiny):
    inst, pm, eid = tiny["inst"], tiny["pm"], tiny["eid"]
    lay = workflow_layout(inst)
    owner, other = pm.owner, pm.accounts[5]
    send = pm._send

    # non-contiguous workflows: split the first workflow so an edge crosses the boundary
    bad = Layout([0, 1] + lay.task_start[1:], [0, 0] + lay.edge_start[1:])
    with pytest.raises(RuntimeError, match="BadInput"):
        send("openMarket", pm.open_market_fn(eid, inst, [1], bad), owner)
    # wrong lengths: layout end != n
    bad2 = Layout(lay.task_start[:-1] + [inst.n - 1], lay.edge_start)
    with pytest.raises(RuntimeError, match="BadInput"):
        send("openMarket", pm.open_market_fn(eid, inst, [1], bad2), owner)
    # no rounds
    with pytest.raises(RuntimeError, match="BadInput"):
        send("openMarket", pm.open_market_fn(eid, inst, []), owner)
    # unknown epoch of the linked contract
    with pytest.raises(RuntimeError, match="UnknownEpoch"):
        send("openMarket", pm.open_market_fn(eid + 99, inst, [1]), owner)
    # non-owner open
    with pytest.raises(RuntimeError, match="NotOwner"):
        send("openMarket", pm.open_market_fn(eid, inst, [1]), other)

    mid = pm.open_market(eid, inst, [1])
    k0 = len(lay.tasks(0))
    with pytest.raises(RuntimeError, match="BadInput"):             # region >= m
        pm.submit(mid, 0, [inst.m] + [0] * (k0 - 1), other)
    with pytest.raises(RuntimeError, match="BadInput"):             # wrong workflow length
        pm.submit(mid, 0, [0] * (k0 + 1), other)
    with pytest.raises(RuntimeError, match="BadInput"):             # workflow out of range
        pm.submit(mid, lay.workflows, [0] * k0, other)
    with pytest.raises(RuntimeError, match="BadInput"):             # batch of wrong length
        pm.submit_batch(mid, [0] * (inst.n - 1), other)
    with pytest.raises(RuntimeError, match="NotOwner"):             # non-owner close
        pm.close_round(mid, sender=other)
    with pytest.raises(RuntimeError, match="UnknownMarket"):
        pm.submit(mid + 99, 0, [0] * k0, other)
    pm.close_round(mid)
    with pytest.raises(RuntimeError, match="MarketClosed"):         # out-of-order: close after the end
        pm.close_round(mid)
    with pytest.raises(RuntimeError, match="MarketClosed"):
        pm.submit(mid, 0, [0] * k0, other)


def test_layout_rejects_crossing_edges_in_python():
    inst = _tiny()
    from dataclasses import replace
    e0 = inst.edges[0]
    crossing = replace(e0, k=inst.n - 1)                          # child in the last workflow
    inst.edges[0] = crossing
    with pytest.raises(ValueError):
        workflow_layout(inst)


# experiment smoke (Phase 3 section 4/5): seed-7 flow + 2 on-chain rounds, parity checked inside the run
def test_onchain_market_experiment_smoke(tmp_path):
    from experiments.onchain_market import run
    s = run(rounds=2, out_dir=str(tmp_path), log=lambda *_: None)
    assert {p.name for p in tmp_path.iterdir()} == {"rounds.csv", "gas.csv", "summary.json"}
    assert s["rounds"] == 2 and s["upper_bound_best_revealed"] == 709_208_800
    assert s["lower_bound_onchain_int"] <= s["upper_bound_best_revealed"]
    g = s["gas"]
    assert g["open_market"] > 0 and g["per_round_mean"] > 0 and g["max_single_tx_share_of_reference_block"] < 1
