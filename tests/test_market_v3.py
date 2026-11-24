"""Phase 5: CarbonScheduleMarketV3 (V2 + QicasCredit + soulbound ScheduleCertificate) on the in-memory chain.

* the four V1 parity tests (scoring, baseline, commit hash, Merkle) run against V3 (as test_parity_v2 does for V2);
* the seed-7 case-study scenario on V3 (demo/pipeline_v3.py) with 25 linked PriceMarket rounds and a finalised
  fraud-proof bound: credits = floor(net saving g), certificate data + tokenURI = Python (core/certificate.py),
  certificate gap = PriceMarket.finalizedGapBps (992 bps, the demo's 9.92 %);
* minting is only possible through V3; finalize is all-or-nothing; no second certificate per epoch.
"""
import random

import pytest
import yaml

from chain.client import Chain, commit_hash, new_salt
from chain.client_v3 import ChainV3, deploy_stack
from chain.oracle_client import OracleClient, block_time
from chain.tokens import Tokens
from core import merkle
from core.certificate import NO_CERTIFIED_BOUND_BPS, credits_for
from core.instance import generate_instance
from core.scoring import evaluate, round_robin_baseline
from demo.pipeline_v3 import run_v3
from experiments.eval_common import seeded_salts
from oracle.signer import make_signers, zone_id

ZONES = ["SE-SE3", "IE", "US-MIDA-PJM", "IN-WE"]
CFG = yaml.safe_load(open("config/demo.yaml"))


def _err(thunk) -> str:
    with pytest.raises(RuntimeError) as ei:
        thunk()
    return str(ei.value)


def _small_epoch(grant: bool = True):
    """Instance seed 3 published on a fresh V3 stack (oracle snapshot = config ci)."""
    inst = generate_instance(CFG, 3)
    base = Chain.start("memory")
    oc = OracleClient(base, make_signers(5))
    rid = oc.publish_snapshot({z: [r.ci_g_per_kwh] * 5 for z, r in zip(ZONES, inst.regions)},
                              block_time(base.w3) // 3600 * 3600)
    if grant:
        st = deploy_stack(base)
        v3, tk = st.market, st.tokens
    else:                                   # V3 deployed but never given MINTER_ROLE
        tk = Tokens.deploy(base)
        v3 = ChainV3.deploy(base, tk)
    eid = v3.publish_from_oracle(inst, oc.address, rid, [zone_id(z) for z in ZONES])
    return inst, base, v3, tk, eid


@pytest.fixture(scope="module")
def small():
    return _small_epoch()


def test_v1_parity_checks_on_v3(small):
    inst, _, v3, _, eid = small
    rng = random.Random(1)
    for _ in range(30):
        x = [rng.randrange(inst.m) for _ in range(inst.n)]
        e = evaluate(inst, x)
        assert v3.evaluate(eid, x) == (e.score, e.carbon_ug, e.cost_nusd, e.feasible)
    assert v3.baseline_schedule(eid) == round_robin_baseline(inst)
    x, s, a = round_robin_baseline(inst), new_salt(), v3.accounts[2]
    assert v3.commit_hash_onchain(eid, x, s, a) == commit_hash(eid, x, s, a)
    for n in (1, 2, 5, 16, 39):
        y = [rng.randrange(4) for _ in range(n)]
        assert v3.merkle_root_of(y) == merkle.root(y)
    assert v3.carbon_source(eid)[2] == [r.ci_g_per_kwh for r in inst.regions]


@pytest.fixture(scope="module")
def flow():
    base = Chain.start("memory")
    return run_v3(CFG, base, salt_fn=seeded_salts(7), market_rounds=25, log=lambda *_: None)


def test_v3_flow_same_outcome_as_case_study(flow):
    """Same 4 accepted scores, same 3 attacker outcomes and the same winner as the default demo (RUN_GUIDE.md)."""
    r = flow["reveals"]
    assert {k: v.get("score") for k, v in r.items() if v["status"] == "accepted"} == {
        "greedy": 872_431_150, "sa": 758_638_650, "sqa": 730_160_300, "dual-market": 709_208_800}
    assert r["attacker: over-capacity"] == {**r["attacker: over-capacity"], "status": "rejected",
                                            "reason": "capacity violated"}
    assert (r["attacker: copycat"]["status"], r["attacker: copycat"]["reason"]) == ("reverted", "HashMismatch")
    assert r["attacker: no-show"]["status"] == "not revealed"
    assert flow["winner"] == "dual-market" and flow["slashed_eth"] == 3
    assert all(flow["parity"].values()), flow["parity"]


def test_v3_credits_and_certificate(flow):                                               # plan §4 tests 2 + 3
    net = flow["baseline_carbon_ug"] - flow["best_carbon_ug"] - flow["overhead_ug"]
    assert flow["net_saving_ug"] == net and flow["credits"] == credits_for(net) == flow["credits_event"]
    assert 425 <= flow["credits"] <= 430          # V1 demo: 428 credits (overhead differs only by V3's own gas)
    assert flow["certificate_owner"] == flow["winner_address"]
    assert flow["market"]["bound_finalised"]
    assert flow["certified_gap_bps"] == 992      # = PriceMarket.finalizedGapBps = the demo's certified 9.92 %
    pm_gap = flow["_stack"].market.w3.eth.contract(
        address=flow["addresses"]["price_market"],
        abi=[{"type": "function", "name": "finalizedGapBps", "stateMutability": "view",
              "inputs": [{"name": "m", "type": "uint256"}], "outputs": [{"name": "", "type": "uint256"}]}]
    ).functions.finalizedGapBps(1).call()
    assert pm_gap == 992
    meta = flow["token_uri_json"]
    assert (meta["epochId"], meta["merkleRoot"], meta["netSavingUg"], meta["oracleRequestId"]) == (
        flow["epoch_id"], flow["merkle_root"], flow["net_saving_ug"], flow["oracle_request_id"])


def test_v3_no_second_certificate_and_soulbound(flow):                                   # plan §4 tests 5 + 6
    st = flow["_stack"]
    v3, tk, eid = st.market, st.tokens, flow["epoch_id"]
    assert _err(lambda: v3.finalize(eid, 0)) == "WrongPhase"
    winner = flow["winner_address"]
    assert _err(lambda: tk.cert._send("transferFrom", tk.cert.contract.functions.transferFrom(
        winner, v3.accounts[9], eid), winner)) == "Soulbound"
    tk.transfer(winner, v3.accounts[9], 1)                            # credits stay a normal ERC-20
    assert tk.balance(v3.accounts[9]) == 1


def test_only_v3_mints_after_admin_renounced(flow):                                     # E3 Phase 5 rows
    st = flow["_stack"]
    tk, owner = st.tokens, st.market.accounts[0]
    assert tk.is_admin(owner) == (False, False) and tk.is_minter(st.market.contract.address) == (True, True)
    for who in (owner, st.market.accounts[8]):
        assert _err(lambda w=who: tk.mint_credit(w, 1, w)) == "AccessControlUnauthorizedAccount"
        assert _err(lambda w=who: tk.grant_minter(w, sender=w)) == "AccessControlUnauthorizedAccount"


def test_finalize_is_atomic_without_minter_role():
    """If V3 lacks MINTER_ROLE, finalize reverts (token error decoded) and the epoch stays open."""
    inst, base, v3, tk, eid = _small_epoch(grant=False)
    x, salt = round_robin_baseline(inst), new_salt()
    v3.commit(eid, base.accounts[1], x, salt, 10**18)
    v3.open_reveal(eid)
    assert v3.reveal(eid, base.accounts[1], x, salt)["status"] == "accepted"
    assert _err(lambda: v3.finalize(eid, 0)) == "AccessControlUnauthorizedAccount"
    assert v3.summary(eid)["phase"] == 2 and tk.total_supply() == 0      # still Reveal; nothing minted


def test_no_price_market_means_no_certified_bound(small):
    inst, base, v3, tk, eid = small
    x, salt = round_robin_baseline(inst), new_salt()
    v3.commit(eid, base.accounts[1], x, salt, 10**18)
    v3.open_reveal(eid)
    v3.reveal(eid, base.accounts[1], x, salt)
    fin = v3.finalize(eid, 0)
    assert fin["certified_gap_bps"] == NO_CERTIFIED_BOUND_BPS
    assert tk.owner_of(eid) == base.accounts[1] and fin["credits_minted"] == 0     # baseline schedule: no saving
    assert tk.cert_data(eid).certified_gap_bps == NO_CERTIFIED_BOUND_BPS
