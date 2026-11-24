"""Phase 4: the four V1 parity tests (tests/test_parity.py, unchanged) run against CarbonScheduleMarketV2, whose
region carbon intensities come from a finalised CarbonOracle snapshot instead of the owner."""
import random

import yaml

from chain.client import Chain, commit_hash, new_salt
from chain.client_v2 import ChainV2
from chain.oracle_client import OracleClient, block_time
from core import merkle
from core.instance import generate_instance
from core.scoring import evaluate, round_robin_baseline
from oracle.signer import make_signers, zone_id

ZONES = ["SE-SE3", "IE", "US-MIDA-PJM", "IN-WE"]


def setup_module():
    global inst, chain, eid, oc, rid
    cfg = yaml.safe_load(open("config/demo.yaml"))
    inst = generate_instance(cfg, 3)
    base = Chain.start("memory")
    oc = OracleClient(base, make_signers(5))
    hour = block_time(base.w3) // 3600 * 3600
    # every signer reports the configured value -> median = config value (so Python scoring applies unchanged)
    rid = oc.publish_snapshot({z: [r.ci_g_per_kwh] * 5 for z, r in zip(ZONES, inst.regions)}, hour)
    chain = ChainV2.deploy(base)
    eid = chain.publish_from_oracle(inst, oc.address, rid, [zone_id(z) for z in ZONES])


def test_v2_reads_carbon_from_oracle():
    o, r, ci = chain.carbon_source(eid)
    assert (o, r, ci) == (oc.address, rid, [x.ci_g_per_kwh for x in inst.regions])


def test_scoring_parity_v2():
    rng = random.Random(1)
    for _ in range(30):
        x = [rng.randrange(inst.m) for _ in range(inst.n)]
        e = evaluate(inst, x)
        assert chain.evaluate(eid, x) == (e.score, e.carbon_ug, e.cost_nusd, e.feasible)


def test_baseline_parity_v2():
    assert chain.baseline_schedule(eid) == round_robin_baseline(inst)


def test_commit_hash_parity_v2():
    x, s, a = round_robin_baseline(inst), new_salt(), chain.accounts[2]
    assert chain.commit_hash_onchain(eid, x, s, a) == commit_hash(eid, x, s, a)


def test_merkle_parity_v2():
    rng = random.Random(2)
    for n in (1, 2, 5, 16, 39):
        x = [rng.randrange(4) for _ in range(n)]
        assert chain.merkle_root_of(x) == merkle.root(x)
