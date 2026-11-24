"""E3 attack suite: every executed attack's observed outcome must equal the expected one; rows for missing
phases must say NOT RUN and assumption rows must never claim to be defended."""
import pytest

from experiments.e3_attacks import (ATTACK_COLUMNS, DEFENDED, PHASE3_ATTACKS, VULNERABLE,
                                    reentrancy_attacker_initcode, run_e3)
from experiments.eval_common import ASSUMPTION, Context, load_base_config, load_eval_config, read_csv


@pytest.fixture(scope="module")
def attacks(tmp_path_factory):
    out = tmp_path_factory.mktemp("e3")
    ev = load_eval_config()
    ctx = Context("smoke", ev["profiles"]["smoke"], ev, load_base_config(ev), out, log=lambda *_: None)
    res = run_e3(ctx)
    return read_csv(out / "attacks.csv"), res


def test_executed_attacks_match_expected(attacks):
    rows, res = attacks
    executed = [r for r in rows if r["layer"] == "case study"]
    assert len(executed) >= 7
    for r in executed:
        assert r["observed"] == r["expected"], r
        assert r["status"] == DEFENDED, r
    names = {r["attack"] for r in executed}
    for required in ("over-capacity schedule", "copycat (copied commitment)", "no-show (commit, never reveal)",
                     "malformed schedule: wrong length", "malformed schedule: region index >= m",
                     "reveal in wrong phase (before openReveal)", "non-owner finalize", "withdraw reentrancy"):
        assert required in names, required
    assert res.summary["failed"] == 0


def test_slashing_amounts(attacks):
    rows, _ = attacks
    by = {r["attack"]: r for r in rows}
    for a in ("over-capacity schedule", "copycat (copied commitment)", "no-show (commit, never reveal)",
              "malformed schedule: wrong length", "malformed schedule: region index >= m"):
        assert float(by[a]["stake_slashed_eth"]) == 1.0, a
    assert float(by["withdraw reentrancy"]["stake_slashed_eth"]) == 0.0


def test_missing_phase_rows_never_claim_defended(attacks):
    rows, _ = attacks
    assert set(ATTACK_COLUMNS) <= set(rows[0])
    for r in rows:
        if r["layer"].startswith("Phase") and r["layer"] not in ("Phase 3", "Phase 4", "Phase 5"):
            phase = r["layer"].split()[1]
            assert r["status"] == f"NOT RUN - Phase {phase} missing", r
        if r["layer"] == "assumption":
            assert r["status"] == ASSUMPTION, r
        if r["layer"] not in ("case study", "Phase 3", "Phase 4", "Phase 5"):
            assert r["status"] != DEFENDED, r
    assert not any(r["status"].startswith("NOT RUN") for r in rows), "Phases 3-5 are built: every attack executes"
    assert {r["layer"] for r in rows} >= {"case study", "Phase 3", "Phase 4", "Phase 5", "assumption"}


def test_phase3_market_attacks_executed(attacks):
    """Phase 3 rows are executed against PriceMarket: observed == expected for every row; the lone dishonest
    submitter is a documented vulnerability, never 'defended'."""
    rows, res = attacks
    p3 = {r["attack"]: r for r in rows if r["layer"] == "Phase 3"}
    assert set(p3) == {a for a, *_ in PHASE3_ATTACKS}
    for attack, expected, _, status in PHASE3_ATTACKS:
        r = p3[attack]
        assert r["observed"] == r["expected"] == expected, r
        assert r["status"] == status, r
    assert p3["lone dishonest market submitter (no honest minimum)"]["status"] == VULNERABLE != DEFENDED
    assert int(p3["inflated market submission"]["attacker_gas"]) > 0
    assert res.summary["vulnerable"] == 1 and res.summary["failed"] == 0


def test_phase4_trust_attacks_executed(attacks):
    """Phase 4 rows (oracle + fraud proofs) are executed: observed == expected, all defended."""
    rows, _ = attacks
    p4 = {r["attack"]: r for r in rows if r["layer"] == "Phase 4"}
    assert set(p4) >= {"lying oracle signer (minority)", "stale oracle report", "replayed oracle signature",
                       "false lower-bound claim (challenged and slashed)", "griefing challenge (bond lost)",
                       "signer equivocation (two values, same zone)"}
    for r in p4.values():
        assert r["observed"] == r["expected"] and r["status"] == DEFENDED, r
    assert float(p4["false lower-bound claim (challenged and slashed)"]["stake_slashed_eth"]) == 0.5


def test_phase5_token_attacks_executed(attacks):
    """Phase 5 rows (tokens) are executed against V3 + QicasCredit + ScheduleCertificate: all defended."""
    from experiments.phase5_tokens import PHASE5_ATTACKS
    rows, _ = attacks
    p5 = {r["attack"]: r for r in rows if r["layer"] == "Phase 5"}
    assert set(p5) == {a for a, *_ in PHASE5_ATTACKS} >= {"unauthorised credit mint", "double schedule certificate",
                                                        "minting after admin renounced"}
    for attack, expected, _ in PHASE5_ATTACKS:
        assert p5[attack]["observed"] == p5[attack]["expected"] == expected, p5[attack]
        assert p5[attack]["status"] == DEFENDED


def test_reentrancy_attacker_bytecode_is_small_and_wellformed():
    code = reentrancy_attacker_initcode()
    assert code[:2] == bytes([0x60, len(code) - 11]) and code[-1] == 0x00   # PUSH1 len ... STOP
