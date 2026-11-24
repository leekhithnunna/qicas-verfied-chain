"""Phase 5 Besu network files, checked OFFLINE (default pytest; no Docker needed)."""
import json
import re
from pathlib import Path

import rlp

from chain.besu import generate
from chain.besu import status as besu

ROOT = Path(__file__).resolve().parents[1]


def test_committed_network_files_are_the_deterministic_ones():
    assert generate.main(["--check"]) == 0


def test_genesis_qbft_settings():
    g = json.loads((ROOT / "chain/besu/genesis.json").read_text())
    assert g["config"]["chainId"] == 1338 and g["config"]["zeroBaseFee"] is True
    assert g["config"]["qbft"]["blockperiodseconds"] == 2
    assert "TEST ONLY" in g["_comment"]
    vanity, validators, vote, rnd, seals = rlp.decode(bytes.fromhex(g["extraData"][2:]))
    assert vanity == b"\0" * 32 and len(validators) == 4 and vote == [] and rnd == b"" and seals == []
    assert len(g["alloc"]) == 10


def test_compose_pins_exact_image_and_loopback_rpc():
    text = (ROOT / "chain/besu/docker-compose.yml").read_text()
    images = set(re.findall(r"image:\s*(\S+)", text))
    assert images == {"hyperledger/besu:26.10.2@sha256:bc599f5ef95a3d5d03f966cd2c1f7dfd7353834c84bc5651ffb4af884860a2c7"}
    assert ":latest" not in text
    ports = re.findall(r'"([\d.]+):(\d+):8545"', text)
    assert sorted(p for _, p in ports) == ["8545", "8546", "8547", "8548"] and {h for h, _ in ports} == {"127.0.0.1"}
    assert generate.enode(1) in text                       # bootnode matches validator1's key


def test_test_keys_are_labelled():
    assert "NEVER USE ON A REAL NETWORK" in (ROOT / "chain/besu/README.md").read_text(encoding="utf-8")


def test_besu_tests_skip_cleanly_when_not_running():
    """Nothing answering on an unused port -> status() is None (test_besu.py then skips, never fails)."""
    assert besu.status("http://127.0.0.1:9") is None
    assert besu.is_up("http://127.0.0.1:9") is False
