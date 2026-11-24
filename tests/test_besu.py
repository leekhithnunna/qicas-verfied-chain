"""Phase 5 on the 4-validator Besu QBFT network (OPT-IN; default pytest stays offline).

    scripts\\besu_up.ps1
    $env:QICAS_BESU='1'; .\\.venv\\Scripts\\python.exe -m pytest -q -m besu            # items 1-4
    $env:QICAS_BESU_VOTE='1'                                                          # + optional item 5

Skips cleanly when QICAS_BESU is not set or nothing answers on 127.0.0.1:8545.
1. 4 validators, blocks produced, ~2 s block period.
2. V1 demo on Besu = in-memory: same accepted scores, attacker outcomes, winner, Merkle root (gas: reported, and
   here also equal because the genesis enables the same fork rules).
3. V3 flow: oracle -> tokens -> V3 -> finalize: ERC-20 credits + soulbound certificate, Python parity.
4. Bound claim on a real-time chain: finalizeBound before the 1-hour window reverts WindowOpen (plan decision A10).
5. Optional: validator add/remove vote (qbft_proposeValidatorVote on a majority of validators).
"""
import os
import time

import pytest
import yaml

from chain.besu import status as besu

pytestmark = [
    pytest.mark.besu,
    pytest.mark.skipif(os.environ.get("QICAS_BESU") != "1", reason="opt-in: set QICAS_BESU=1 (needs Docker + Besu)"),
    pytest.mark.skipif(os.environ.get("QICAS_BESU") == "1" and not besu.is_up(),
                       reason="Besu not running on 127.0.0.1:8545 (scripts/besu_up.ps1)"),
]
CFG = yaml.safe_load(open("config/demo.yaml"))


def test_network_four_validators_and_block_period():
    s = besu.status()
    assert s["chain_id"] == 1338 and len(s["validators"]) == 4 and s["peers"] >= 3
    b0 = s["block"]
    t0 = int(besu.rpc("eth_getBlockByNumber", [hex(b0), False])["timestamp"], 16)
    deadline = time.time() + 30
    while besu.status()["block"] < b0 + 5 and time.time() < deadline:
        time.sleep(1)
    b1 = besu.status()["block"]
    t1 = int(besu.rpc("eth_getBlockByNumber", [hex(b1), False])["timestamp"], 16)
    assert b1 >= b0 + 5
    assert 1.5 <= (t1 - t0) / (b1 - b0) <= 3.5          # block period 2 s (empty blocks keep the cadence)


def test_v1_demo_on_besu_equals_memory():
    from chain.client import Chain
    from demo.pipeline import run
    from experiments.eval_common import seeded_salts
    res = {}
    for mode in ("memory", "besu"):
        cfg = {**CFG, "chain": {**CFG["chain"], "mode": mode}}
        out = run(cfg, log=lambda *_: None, chain=Chain.start(mode, min_stake=int(cfg["chain"]["stake_wei"])),
                  salt_fn=seeded_salts(7))
        res[mode] = out
    m, b = res["memory"], res["besu"]
    key = lambda o: [(r["agent"], r["status"], r.get("score"), r.get("reason")) for r in o["reveals"]]   # noqa: E731
    assert key(b) == key(m)
    for k in ("winner", "best_score", "merkle_root", "credits_minted", "slashed_eth"):
        assert b["final"][k] == m["final"][k], k
    # Gas is REPORTED (plan §4), not asserted equal: the EVM rules match (berlin/london/shanghai at genesis), but
    # commit hashes bind the sender address and Besu's TEST accounts differ from eth-tester's, so calldata
    # zero-byte counts (4 vs 16 gas per byte) can differ by a few gas per commit.
    diffs = [(t1["action"], t2["gas"] - t1["gas"]) for t1, t2 in zip(m["transactions"], b["transactions"])
             if t1["gas"] != t2["gas"]]
    assert all(a == "commit" and abs(d) <= 12 * 32 for a, d in diffs), diffs
    assert abs(b["final"]["net_saving_g"] - m["final"]["net_saving_g"]) < 1e-3


@pytest.fixture(scope="module")
def v3_flow():
    from chain.client import Chain
    from demo.pipeline_v3 import run_v3
    from experiments.eval_common import seeded_salts
    return run_v3(CFG, Chain.start("besu"), salt_fn=seeded_salts(7), market_rounds=2, log=lambda *_: None)


def test_v3_tokens_on_besu(v3_flow):
    r = v3_flow
    assert all(r["parity"].values()), r["parity"]
    assert r["winner"] == "dual-market" and r["certificate_owner"] == r["winner_address"]
    assert r["credits"] == r["net_saving_ug"] // 10**6 > 0
    assert r["certified_gap_bps"] == 10_000            # no finalised bound on a real-time chain (window 1 h)
    tk = r["_stack"].tokens
    owner = r["_stack"].market.accounts[0]
    with pytest.raises(RuntimeError, match="AccessControlUnauthorizedAccount"):
        tk.mint_credit(owner, 1, owner)                 # admin renounced: the deployer cannot mint
    with pytest.raises(RuntimeError, match="Soulbound"):
        tk.cert._send("transferFrom", tk.cert.contract.functions.transferFrom(
            r["winner_address"], owner, r["epoch_id"]), r["winner_address"])


def test_bound_claim_window_enforced_in_real_time(v3_flow):
    mk = v3_flow["market"]
    assert mk["claim_gas"] > 0 and not mk["bound_finalised"]
    assert mk["early_finalize"] == "reverted: WindowOpen"


@pytest.mark.skipif(os.environ.get("QICAS_BESU_VOTE") != "1", reason="optional: set QICAS_BESU_VOTE=1")
def test_validator_add_remove_vote():
    """The consortium governs who validates: 3 of 4 validators vote a 5th address in, then out again."""
    from chain.besu.vote import add_then_remove
    r = add_then_remove()
    assert r["added"] and r["removed"], r
    assert len(besu.status()["validators"]) == 4
