"""Phase 5 tokens on the in-memory chain: QicasCredit (ERC-20) and the SOULBOUND ScheduleCertificate (ERC-721).

Standalone token behaviour + Python<->Solidity parity of the certificate metadata (core/certificate.py). The
market integration (CarbonScheduleMarketV3 mints both) is tested in tests/test_market_v3.py."""
import random

import pytest

from chain.client import Chain
from chain.tokens import Tokens
from core import certificate as cert_py
from core.certificate import CertData
from core.hashing import keccak256


@pytest.fixture()
def env():
    chain = Chain.start("memory")
    admin, minter, alice, bob, outsider = chain.accounts[0], chain.accounts[1], *chain.accounts[2:5]
    tk = Tokens.deploy(chain, admin)
    tk.grant_minter(minter)
    return tk, admin, minter, alice, bob, outsider


def _err(thunk) -> str:
    with pytest.raises(RuntimeError) as ei:
        thunk()
    return str(ei.value)


def _data(rng: random.Random, market: str) -> CertData:
    return CertData(keccak256(rng.randbytes(8)), keccak256(rng.randbytes(8)), rng.randrange(1, 10**15),
                    rng.randrange(10**12), rng.randrange(10**14), rng.randrange(10_001), rng.randrange(1, 50), market)


def test_metadata_and_decimals(env):
    tk, *_ = env
    c = tk.credit.contract.functions
    assert (c.name().call(), c.symbol().call(), c.decimals().call()) == ("QICAS Carbon Credit", "QCC", 0)
    n = tk.cert.contract.functions
    assert (n.name().call(), n.symbol().call()) == ("QICAS Schedule Certificate", "QSC")


def test_only_minter_can_mint(env):                                                       # plan §4 test 1
    tk, admin, minter, alice, _, outsider = env
    for who in (outsider, admin):           # the admin can GRANT minting but does not hold MINTER_ROLE itself
        assert _err(lambda: tk.mint_credit(alice, 5, who)) == "AccessControlUnauthorizedAccount"
        assert _err(lambda: tk.mint_cert(alice, 1, _data(random.Random(0), minter), who)) == \
            "AccessControlUnauthorizedAccount"
    assert _err(lambda: tk.grant_minter(outsider, sender=outsider)) == "AccessControlUnauthorizedAccount"
    tk.mint_credit(alice, 5, minter)
    assert tk.balance(alice) == 5 and tk.total_supply() == 5


def test_erc20_transfer_approve_and_retire(env):                                         # plan §4 tests 4 + 6
    tk, _, minter, alice, bob, outsider = env
    tk.mint_credit(alice, 100, minter)
    tk.transfer(alice, bob, 30)
    tk.approve_credit(bob, outsider, 10)
    tk.transfer_from(outsider, bob, outsider, 10)
    assert (tk.balance(alice), tk.balance(bob), tk.balance(outsider)) == (70, 20, 10)
    assert _err(lambda: tk.transfer_from(outsider, bob, outsider, 1)) == "ERC20InsufficientAllowance"
    r = tk.retire(alice, 25, bob, "offset 2026-11 batch")
    assert (r["holder"], r["beneficiary"], r["amount"], r["reason"]) == (alice, bob, 25, "offset 2026-11 batch")
    assert tk.balance(alice) == 45 and tk.total_supply() == 75      # retirement burns: supply goes down
    assert _err(lambda: tk.retire(outsider, 11, outsider, "x")) == "ERC20InsufficientBalance"


def test_certificate_mint_data_and_token_uri_parity(env):                                # plan §4 tests 3 + 4
    tk, _, minter, alice, *_ = env
    rng = random.Random(7)
    for token_id in (1, 2, 17, 2**40):
        d = _data(rng, tk.cert.contract.address)
        tk.mint_cert(alice, token_id, d, minter)
        assert tk.owner_of(token_id) == alice and tk.locked(token_id)
        assert tk.cert_data(token_id) == d
        assert tk.metadata_json(token_id) == cert_py.metadata_json(token_id, d)     # byte-for-byte parity
        uri = tk.token_uri(token_id)
        assert uri == cert_py.token_uri(token_id, d)
        meta = cert_py.decode_token_uri(uri)
        assert meta["epochId"] == token_id and meta["merkleRoot"] == "0x" + d.merkle_root.hex()
        assert (meta["baselineCarbonUg"], meta["netSavingUg"], meta["certifiedGapBps"]) == \
            (d.baseline_carbon_ug, d.net_saving_ug, d.certified_gap_bps)
        assert meta["market"] == d.market.lower()
    assert tk.cert_balance(alice) == 4


def test_no_second_certificate_for_the_same_epoch(env):                                  # plan §4 test 5
    tk, _, minter, alice, bob, _ = env
    d = _data(random.Random(1), minter)
    tk.mint_cert(alice, 3, d, minter)
    assert _err(lambda: tk.mint_cert(bob, 3, d, minter)) == "CertificateExists"
    assert tk.owner_of(3) == alice


def test_certificate_is_soulbound(env):                                                  # plan §4 test 6 (decision 1)
    tk, _, minter, alice, bob, _ = env
    tk.mint_cert(alice, 9, _data(random.Random(2), minter), minter)
    f = tk.cert.contract.functions
    for name, fn in (("transferFrom", f.transferFrom(alice, bob, 9)),
                     ("safeTransferFrom", f.safeTransferFrom(alice, bob, 9)),
                     ("safeTransferFrom+data", f.safeTransferFrom(alice, bob, 9, b"x")),
                     ("approve", f.approve(bob, 9)),
                     ("setApprovalForAll", f.setApprovalForAll(bob, True))):
        assert _err(lambda fn=fn, n=name: tk.cert._send(n, fn, alice)) == "Soulbound", name
    assert tk.owner_of(9) == alice and tk.cert_balance(bob) == 0
    for iface in ("ERC165", "ERC721", "ERC721Metadata", "AccessControl", "ERC5192"):
        assert tk.supports(iface), iface
    assert not tk.supports("0xffffffff")


def test_unknown_token_views_revert(env):
    tk, *_ = env
    for fn in (tk.token_uri, tk.cert_data, tk.locked, tk.owner_of):
        with pytest.raises(Exception, match="ERC721NonexistentToken|revert"):
            fn(404)


def test_admin_renounced_no_further_minters(env):                                        # E3 Phase 5 row
    """After the admin renounces DEFAULT_ADMIN_ROLE nobody can grant MINTER_ROLE again (the deployer can no longer
    mint or add minters); the existing minter (the market contract in V3) keeps its protocol role."""
    tk, admin, minter, alice, _, outsider = env
    tk.renounce_admin()
    assert tk.is_admin(admin) == (False, False)
    for who in (admin, outsider):
        assert _err(lambda w=who: tk.grant_minter(w, sender=w)) == "AccessControlUnauthorizedAccount"
        assert _err(lambda w=who: tk.mint_credit(w, 1, w)) == "AccessControlUnauthorizedAccount"
    assert tk.is_minter(admin) == (False, False) and tk.is_minter(minter) == (True, True)
    tk.mint_credit(alice, 2, minter)
    assert tk.balance(alice) == 2


def test_credits_rule_matches_v1():
    """1 credit per whole gram of NET saving, floored (identical to V1's built-in token)."""
    assert [cert_py.credits_for(u) for u in (0, 999_999, 1_000_000, 427_999_999_999, 428_000_000_000)] == \
        [0, 0, 1, 427_999, 428_000]
