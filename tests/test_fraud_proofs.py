"""Phase 4 optimistic fraud proofs on PriceMarket (plan PHASE4_TRUST_LAYER.md section C, attacks 16-22) and the
bound-bookkeeping parity against core/market_int.MarketState, plus PriceMarket.bindOracle."""
import copy
import itertools

import pytest
import yaml

from chain.client import Chain, new_salt
from chain.oracle_client import OracleClient, advance_time, block_time
from chain.price_market import PriceMarketClient
from core.hashing import keccak256
from core.instance import generate_instance
from core.market_int import (CHALLENGE_WINDOW, MarketError, MarketState, default_steps, exact_workflow_min,
                             workflow_layout, workflow_value)
from core.scoring import evaluate
from oracle.signer import make_signers, zone_id


def _tiny():
    cfg = copy.deepcopy(yaml.safe_load(open("config/demo.yaml")))
    cfg["workflows"], cfg["tasks_per_workflow"] = 2, [3, 3]
    return generate_instance(cfg, 5)


def _brute_best(inst):
    feas = [x for x in itertools.product(range(inst.m), repeat=inst.n) if evaluate(inst, x).feasible]
    x = min(feas, key=lambda x: evaluate(inst, x).score)
    return list(x), evaluate(inst, x).score


@pytest.fixture()
def fp():
    """Fresh chain per test: tiny instance (2 workflows x 3 tasks) published on V1, PriceMarket deployed."""
    inst = _tiny()
    chain = Chain.start("memory")
    eid = chain.publish(inst)
    x_opt, opt = _brute_best(inst)
    return {"inst": inst, "chain": chain, "eid": eid, "pm": PriceMarketClient(chain), "lay": workflow_layout(inst),
            "w3": chain.w3, "honest": chain.accounts[1], "attacker": chain.accounts[2],
            "challenger": chain.accounts[3], "opt": opt, "x_opt": x_opt}


def _worst(inst, lay, w, lam):
    return list(max(itertools.product(range(inst.m), repeat=len(lay.tasks(w))),
                    key=lambda c: workflow_value(inst, lay, w, c, lam)))


def _err(thunk) -> str:
    try:
        thunk()
    except RuntimeError as exc:
        return str(exc)
    return "ok"


def _honest_round(fp, rounds=2):
    inst, pm, lay = fp["inst"], fp["pm"], fp["lay"]
    steps = default_steps(inst, rounds)
    mid = pm.open_market(fp["eid"], inst, steps, lay)
    st = MarketState(inst, steps, lay)
    x = st.honest_assignment()
    pm.submit_batch(mid, x, fp["honest"])
    st.submit_batch(x)
    pm.close_round(mid)
    st.close_round()
    return mid, st


def test_false_bound_claim_is_challenged_and_corrected(fp):                                       # 16 + 22
    inst, pm, lay, w3 = fp["inst"], fp["pm"], fp["lay"], fp["w3"]
    att, ch, hon = fp["attacker"], fp["challenger"], fp["honest"]
    mid = pm.open_market(fp["eid"], inst, [1], lay)
    st = MarketState(inst, [1], lay)
    lam = [0] * inst.m
    for w in range(lay.workflows):                    # lone dishonest submitter: inflated "minima"
        xw = _worst(inst, lay, w, lam)
        pm.submit(mid, w, xw, att)
        st.submit(w, xw)
    pm.close_round(mid)
    st.close_round()
    assert pm.round_info(mid, 0)["dual_value"] == st.history[0].dual_value > fp["opt"]     # Phase 3 weakness
    bond = pm.contract.functions.CLAIM_BOND().call()
    for w in range(lay.workflows):                    # attacker (re)claims; a watcher posts the exact minimum
        pm.claim_bound(mid, 0, att)
        st.claim_bound(0, att, block_time(w3))
        xw, _ = exact_workflow_min(inst, lay, w, lam)
        r = pm.challenge(mid, 0, w, xw, lam, ch)
        assert r["cancelled"] and st.challenge(0, w, xw, ch, block_time(w3))
        assert r["dual_value"] == st.history[0].dual_value
    assert pm.withdrawable(ch) == st.withdrawable[ch] == lay.workflows * (bond // 2)
    assert pm.slashed_pool() == st.slashed_pool == lay.workflows * (bond - bond // 2)
    corrected = pm.round_info(mid, 0)["dual_value"]
    assert corrected <= fp["opt"]                     # corrected g_0 is a valid bound again
    pm.claim_bound(mid, 0, hon)
    st.claim_bound(0, hon, block_time(w3))
    advance_time(w3, CHALLENGE_WINDOW + 1)
    pm.finalize_bound(mid, 0)
    st.finalize_bound(0, block_time(w3))
    assert pm.certified_lower_bound(mid) == (True, st.cert_lb, st.cert_lb_round) == (True, corrected, 0)
    assert pm.withdrawable(hon) == st.withdrawable[hon] == bond
    # 22: weak duality vs the revealed optimum (UB) and the brute-force optimum
    chain, eid, s = fp["chain"], fp["eid"], new_salt()
    chain.commit(eid, hon, fp["x_opt"], s, 10**18)
    chain.open_reveal(eid)
    assert chain.reveal(eid, hon, fp["x_opt"], s)["status"] == "accepted"
    assert corrected <= fp["opt"] == chain.summary(eid)["best_score"]
    assert pm.finalized_gap_bps(mid) == pm.gap_bps(fp["opt"], corrected)


def test_challenge_not_cheaper_reverts(fp):                                                          # 17
    pm, inst, lay = fp["pm"], fp["inst"], fp["lay"]
    mid, st = _honest_round(fp)
    pm.claim_bound(mid, 0, fp["honest"])
    lam, xw = st.history[0].lam, st.history[0].kept[0][1]
    assert _err(lambda: pm.challenge(mid, 0, 0, xw, lam, fp["attacker"])) == "NotCheaper"      # equal != cheaper
    assert _err(lambda: pm.challenge(mid, 0, 0, _worst(inst, lay, 0, lam), lam, fp["attacker"])) == "NotCheaper"
    with pytest.raises(MarketError, match="NotCheaper"):
        st.challenge(0, 0, xw, fp["attacker"], block_time(fp["w3"]))
    assert _err(lambda: pm.challenge(mid, 0, 0, xw, [v + 1 for v in lam], fp["attacker"])) == "BadInput"
    assert pm.claim_info(mid, 0)["active"]


def test_window_rules(fp):                                                                           # 18
    pm = fp["pm"]
    mid, st = _honest_round(fp)
    pm.claim_bound(mid, 0, fp["honest"])
    assert _err(lambda: pm.finalize_bound(mid, 0)) == "WindowOpen"
    advance_time(fp["w3"], CHALLENGE_WINDOW + 1)
    xw, lam = st.history[0].kept[0][1], st.history[0].lam
    assert _err(lambda: pm.challenge(mid, 0, 0, xw, lam, fp["attacker"])) == "WindowClosed"
    pm.finalize_bound(mid, 0)
    assert _err(lambda: pm.challenge(mid, 0, 0, xw, lam, fp["attacker"])) == "RoundFinalized"


def test_honest_claim_survives_every_challenge_and_bond_is_refunded(fp):                             # 19
    pm, inst, lay, w3 = fp["pm"], fp["inst"], fp["lay"], fp["w3"]
    mid, st = _honest_round(fp)
    pm.claim_bound(mid, 0, fp["honest"])
    lam = st.history[0].lam
    for w in range(lay.workflows):
        for cand in itertools.product(range(inst.m), repeat=len(lay.tasks(w))):
            assert workflow_value(inst, lay, w, cand, lam) >= st.history[0].kept[w][0]   # nothing is cheaper
        assert _err(lambda w=w: pm.challenge(mid, 0, w, _worst(inst, lay, w, lam), lam, fp["attacker"])) \
            == "NotCheaper"
    advance_time(w3, CHALLENGE_WINDOW + 1)
    pm.finalize_bound(mid, 0)
    assert pm.certified_lower_bound(mid) == (True, st.history[0].dual_value, 0)
    assert st.history[0].dual_value <= fp["opt"]
    bal0 = w3.eth.get_balance(fp["honest"])
    pm.withdraw(fp["honest"])
    assert pm.withdrawable(fp["honest"]) == 0 and w3.eth.get_balance(fp["honest"]) > bal0


def test_claim_preconditions(fp):                                                                    # 20
    pm, inst, lay = fp["pm"], fp["inst"], fp["lay"]
    mid = pm.open_market(fp["eid"], inst, [1, 1], lay)
    assert _err(lambda: pm.claim_bound(mid, 0, fp["honest"])) == "RoundNotClaimable"            # not closed
    xw, _ = exact_workflow_min(inst, lay, 0, [0] * inst.m)
    pm.submit(mid, 0, xw, fp["honest"])
    pm.close_round(mid)
    assert _err(lambda: pm.claim_bound(mid, 0, fp["honest"])) == "RoundNotClaimable"            # incomplete
    mid2, _ = _honest_round(fp)
    assert _err(lambda: pm.claim_bound(mid2, 0, fp["honest"], bond=10**17)) == "BadBond"
    pm.claim_bound(mid2, 0, fp["honest"])
    assert _err(lambda: pm.claim_bound(mid2, 0, fp["attacker"])) == "AlreadyClaimed"            # double claim
    assert _err(lambda: pm.finalize_bound(mid2, 1)) == "NoClaim"


def test_bond_withdrawal_reentrancy_blocked(fp):                                                    # 21
    from experiments.e3_attacks import reentrancy_attacker_initcode
    pm, w3, eoa = fp["pm"], fp["w3"], fp["attacker"]
    mid, _ = _honest_round(fp)
    rc = w3.eth.wait_for_transaction_receipt(w3.eth.send_transaction(
        {"from": eoa, "data": reentrancy_attacker_initcode(), "gas": 1_000_000}))
    proxy, c = rc.contractAddress, pm.contract

    def via_proxy(fn, args, value=0):
        data = bytes.fromhex(c.address[2:]) + bytes.fromhex(c.encode_abi(fn, args=args)[2:])
        r = w3.eth.wait_for_transaction_receipt(w3.eth.send_transaction(
            {"from": eoa, "to": proxy, "data": data, "value": value, "gas": 5_000_000}))
        assert r.status == 1, fn
    bond = c.functions.CLAIM_BOND().call()
    via_proxy("claimBound", [mid, 0], bond)
    advance_time(w3, CHALLENGE_WINDOW + 1)
    pm.finalize_bound(mid, 0)
    held = w3.eth.get_balance(c.address)
    via_proxy("withdraw", [])
    assert int.from_bytes(w3.eth.get_storage_at(proxy, 1), "big") == 1         # re-entry attempted ...
    assert int.from_bytes(w3.eth.get_storage_at(proxy, 2), "big") == 0         # ... and failed
    assert bytes(w3.eth.get_storage_at(proxy, 3))[:4] == keccak256(b"Reentrancy()")[:4]
    assert held - w3.eth.get_balance(c.address) == bond                         # paid exactly once


def test_bind_oracle(fp):
    pm, inst = fp["pm"], fp["inst"]
    oc = OracleClient(fp["chain"], make_signers(5))
    codes = ["SE-SE3", "IE", "US-MIDA-PJM", "IN-WE"]
    hour = block_time(fp["w3"]) // 3600 * 3600
    good = oc.publish_snapshot({z: [r.ci_g_per_kwh] * 5 for z, r in zip(codes, inst.regions)}, hour)
    bad = oc.publish_snapshot({z: [r.ci_g_per_kwh + 1] * 5 for z, r in zip(codes, inst.regions)}, hour)
    mid = pm.open_market(fp["eid"], inst, [1], fp["lay"])
    zones = [zone_id(z) for z in codes]
    assert _err(lambda: pm.bind_oracle(mid, oc.address, bad, zones)) == "OracleMismatch"
    pm.bind_oracle(mid, oc.address, good, zones)
    assert tuple(pm.contract.functions.oracleBinding(mid).call()) == (oc.address, good)


def test_trust_layer_experiment_smoke(tmp_path):
    """experiments/trust_layer.py: seed-7 flow, 2 rounds, oracle snapshot, finalised bound, challenges, attacks."""
    from experiments.trust_layer import run
    s = run(out_dir=str(tmp_path), rounds=2, log=lambda *_: None)
    assert {p.name for p in tmp_path.iterdir()} == {"gas.csv", "attacks.csv", "summary.json"}
    assert s["attacks"]["defended"] == s["attacks"]["executed"] == 6
    assert s["finalized_gap_bps"] == s["certified_gap_bps_phase3"]          # honest run: nothing was corrected
    assert s["gas"]["trust_per_epoch"] > 0 and s["gas"]["challenge_mean"] > 0
