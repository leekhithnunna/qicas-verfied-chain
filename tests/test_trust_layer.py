"""Phase 4 trust layer: CarbonOracle (EIP-712 multi-signer, lower median) parity + attacks.
Plan: docs/plans/PHASE4_TRUST_LAYER.md section C (attacks 1-15 here; 16-22 = fraud proofs, further below)."""
import random

import pytest
from eth_account import Account

from chain.client import Chain
from chain.oracle_client import DEFAULT_MAX_AGE, OracleClient, advance_time, block_time
from core.hashing import keccak256
from core.oracle_math import median_lower
from oracle.signer import REPORT_TYPE_STRING, Report, Signer, digest, make_signers, malleate, recover, zone_id

Z1, Z2 = zone_id("SE-SE3"), zone_id("IE")
SRC = keccak256(b"raw file bytes")


@pytest.fixture(scope="module")
def env():
    chain = Chain.start("memory")
    signers = make_signers(5)
    oc = OracleClient(chain, signers)
    return {"chain": chain, "signers": signers, "oc": oc}


def _err(oc, thunk) -> str:
    """Name of the custom error a call/transaction reverts with."""
    try:
        thunk()
    except Exception as exc:     # noqa: BLE001 - we want the decoded name
        return oc._c._error_name(exc) if not isinstance(exc, RuntimeError) else str(exc)
    return "ok"


def _new_request(oc, zones=(Z1, Z2), deadline_s=3600):
    now = block_time(oc.w3)
    hour = now // 3600 * 3600
    return oc.request(list(zones), hour, now + deadline_s), hour


def _report(oc, rid, hour, zone=Z1, ci=40, issued=None):
    return Report(rid, zone, hour, ci, SRC, block_time(oc.w3) if issued is None else issued)


# ------------------------------------------------------------------ parity
def test_typehash_and_digest_parity(env):
    oc = env["oc"]
    assert bytes(oc.contract.functions.REPORT_TYPEHASH().call()) == keccak256(REPORT_TYPE_STRING.encode())
    rng = random.Random(21)
    for _ in range(20):
        r = Report(rng.randrange(2**64), keccak256(bytes([rng.randrange(256)])), rng.randrange(2**64),
                   rng.randrange(2**32), keccak256(bytes([rng.randrange(256)])), rng.randrange(2**64))
        assert oc.report_digest(r) == digest(r, oc.chain_id, oc.address)


def test_recover_signer_parity(env):
    oc, signers = env["oc"], env["signers"]
    rng = random.Random(22)
    for i in range(20):
        s = signers[i % 5]
        r = Report(rng.randrange(1000), Z1, 3600 * rng.randrange(10**6), rng.randrange(1000), SRC, rng.randrange(2**40))
        sig = oc.sign(s, r)
        d = digest(r, oc.chain_id, oc.address)
        assert oc.recover_signer(d, sig) == recover(r, sig, oc.chain_id, oc.address) == s.address
        assert Account._recover_hash(d, signature=sig) == s.address


def test_median_lower_parity_fuzz(env):
    oc = env["oc"]
    rng = random.Random(23)
    for _ in range(200):
        k = rng.randint(1, 9)
        vals = [rng.choice([rng.randrange(5), rng.randrange(2**32)]) for _ in range(k)]   # duplicates likely
        assert oc.median_lower(vals) == median_lower(vals)
    assert median_lower([5, 1, 3, 2]) == 2 and median_lower([7]) == 7


def test_honest_snapshot_flow(env):
    oc = env["oc"]
    rid, hour = _new_request(oc)
    vals = {Z1: [40, 42, 38, 41, 39], Z2: [330, 300, 350, 320, 340]}
    reports, sigs = [], []
    for z, vs in vals.items():
        for s, v in zip(env["signers"], vs):
            r = _report(oc, rid, hour, z, v)
            reports.append(r)
            sigs.append(oc.sign(s, r))
    assert _err(oc, lambda: oc.value_of(rid, Z1)) == "NotFinalized"
    oc.submit(rid, reports, sigs)
    oc.finalize(rid)
    assert oc.value_of(rid, Z1) == median_lower(vals[Z1]) == 40
    assert oc.zone_info(rid, Z2) == {"listed": True, "reports": 5, "median": 330, "spread": 50}
    assert _err(oc, lambda: oc.finalize(rid)) == "AlreadyFinalized"


# ------------------------------------------------------------------ attacks 1-7: wrong signatures
def test_wrong_signatures(env):
    oc, s0 = env["oc"], env["signers"][0]
    rid, hour = _new_request(oc)
    r = _report(oc, rid, hour)
    good = oc.sign(s0, r)
    outsider = Signer(99)
    assert _err(oc, lambda: oc.submit(rid, [r], [outsider.sign(r, oc.chain_id, oc.address)])) == "UnknownSigner"  # 1
    tampered = Report(r.request_id, r.zone, r.hour_start, r.ci_g_per_kwh + 1, r.source_hash, r.issued_at)
    assert _err(oc, lambda: oc.submit(rid, [tampered], [good])) == "UnknownSigner"                               # 2
    assert _err(oc, lambda: oc.submit(rid, [r], [s0.sign(r, oc.chain_id + 1, oc.address)])) == "UnknownSigner"   # 3
    assert _err(oc, lambda: oc.submit(rid, [r], [s0.sign(r, oc.chain_id, env["chain"].contract.address)])) \
        == "UnknownSigner"
    assert _err(oc, lambda: oc.submit(rid, [r], [good[:64]])) == "BadSignature"                                  # 4
    assert _err(oc, lambda: oc.submit(rid, [r], [good[:64] + bytes([29])])) == "BadSignature"
    hi = malleate(good)
    assert Account._recover_hash(digest(r, oc.chain_id, oc.address), vrs=(hi[64], int.from_bytes(hi[:32], "big"),
                                 int.from_bytes(hi[32:64], "big"))) == s0.address    # same signer under ecrecover...
    assert _err(oc, lambda: oc.submit(rid, [r], [hi])) == "BadSignature"                                         # 5
    oc.submit(rid, [r], [good])
    assert _err(oc, lambda: oc.submit(rid, [r], [good])) == "DuplicateReport"                                    # 6


def test_equivocation_slashes_bond():                                                                            # 7
    chain = Chain.start("memory")
    signers = make_signers(5)
    oc = OracleClient(chain, signers)
    rid, hour = _new_request(oc)
    s0 = signers[0]
    r1, r2 = _report(oc, rid, hour, ci=40), _report(oc, rid, hour, ci=999)
    sig1, sig2 = oc.sign(s0, r1), oc.sign(s0, r2)
    oc.submit(rid, [r1], [sig1])
    assert _err(oc, lambda: oc.submit(rid, [r2], [sig2])) == "DuplicateReport"
    assert _err(oc, lambda: oc.prove_equivocation(r1, sig1, r1, sig1, chain.accounts[7])) == "NotEquivocation"
    s1 = signers[1]
    assert _err(oc, lambda: oc.prove_equivocation(r1, sig1, r2, oc.sign(s1, r2), chain.accounts[7])) \
        == "NotEquivocation"
    oc.prove_equivocation(r1, sig1, r2, sig2, chain.accounts[7])
    assert oc.bond_of(s0.address) == 0 and not oc.is_signer(s0.address)
    assert oc.contract.functions.slashedPool().call() == oc.min_bond
    r3 = _report(oc, rid, hour, zone=Z2)
    assert _err(oc, lambda: oc.submit(rid, [r3], [oc.sign(s0, r3)])) == "UnknownSigner"


def test_unbonded_signer_rejected():
    chain = Chain.start("memory")
    signers = make_signers(3)
    oc = OracleClient(chain, signers, quorum=2, bond=False)
    rid, hour = _new_request(oc)
    r = _report(oc, rid, hour)
    assert _err(oc, lambda: oc.submit(rid, [r], [oc.sign(signers[0], r)])) == "NotBonded"


# ------------------------------------------------------------------ attacks 8-13: stale data
def test_stale_data(env):
    oc, s = env["oc"], env["signers"][1]
    rid, hour = _new_request(oc)
    r = _report(oc, rid, hour - 3600)
    assert _err(oc, lambda: oc.submit(rid, [r], [oc.sign(s, r)])) == "WrongHour"                                # 8
    old_rid, old_hour = _new_request(oc)
    r = _report(oc, old_rid, hour)
    assert _err(oc, lambda: oc.submit(rid, [r], [oc.sign(s, r)])) == "WrongRequest"                             # 9
    now = block_time(oc.w3)
    r = _report(oc, rid, hour, issued=now - DEFAULT_MAX_AGE - 60)
    assert _err(oc, lambda: oc.submit(rid, [r], [oc.sign(s, r)])) == "Stale"                                    # 10
    r = _report(oc, rid, hour, issued=now + 3600)
    assert _err(oc, lambda: oc.submit(rid, [r], [oc.sign(s, r)])) == "FutureReport"                             # 11
    r = _report(oc, rid, hour, zone=zone_id("XX"))
    assert _err(oc, lambda: oc.submit(rid, [r], [oc.sign(s, r)])) == "UnknownZone"


def test_late_report_and_quorum():
    chain = Chain.start("memory")
    signers = make_signers(5)
    oc = OracleClient(chain, signers)
    rid, hour = _new_request(oc, zones=[Z1], deadline_s=600)
    for s in signers[:2]:
        r = _report(oc, rid, hour)
        oc.submit(rid, [r], [oc.sign(s, r)])
    assert _err(oc, lambda: oc.finalize(rid)) == "NoQuorum"                                                      # 13
    assert _err(oc, lambda: oc.value_of(rid, Z1)) == "NotFinalized"
    advance_time(oc.w3, 1200)
    r = _report(oc, rid, hour)
    assert _err(oc, lambda: oc.submit(rid, [r], [oc.sign(signers[2], r)])) == "Late"                            # 12


# ------------------------------------------------------------------ attacks 14-15: median robustness
def _snapshot(oc, signers, values):
    rid, hour = _new_request(oc, zones=[Z1])
    reports = [_report(oc, rid, hour, ci=v) for v in values]
    oc.submit(rid, reports, [oc.sign(s, r) for s, r in zip(signers, reports)])
    oc.finalize(rid)
    return oc.value_of(rid, Z1)


def test_minority_liars_do_not_move_the_median(env):                                                            # 14
    honest = [300, 310, 320]
    assert _snapshot(env["oc"], env["signers"], [0, 300, 310, 320, 2**32 - 1]) == median_lower(honest) == 310


def test_majority_liars_move_the_median_documented(env):                                                        # 15
    """Documents the honest-majority assumption: 3 of 5 colluding signers set the value."""
    assert _snapshot(env["oc"], env["signers"], [0, 0, 0, 300, 310]) == 0
