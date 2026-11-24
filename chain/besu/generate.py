"""Generate the Phase 5 Besu QBFT network files DETERMINISTICALLY (TEST ONLY — never use on a real network).

    .\\.venv\\Scripts\\python.exe -m chain.besu.generate          # (re)writes genesis.json, nodes/*/key, static.json
    .\\.venv\\Scripts\\python.exe -m chain.besu.generate --check  # verify the committed files (also a pytest test)

Keys are keccak256 of public labels, so anyone can re-derive them: they protect NOTHING.
  validator i (1..4): keccak256("qicas-besu-validator-<i>")   -> nodes/validator<i>/key  (node key = QBFT signer)
  account j  (0..9):  keccak256("qicas-besu-account-<j>")     -> funded in genesis alloc (stakes/bonds in ETH)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import rlp
from eth_account import Account
from eth_keys import keys

from core.hashing import keccak256

HERE = Path(__file__).resolve().parent
CHAIN_ID = 1338                          # TEST ONLY (plan §1; != Hardhat 31337, != eth-tester)
N_VALIDATORS = 4
N_ACCOUNTS = 10
BLOCK_PERIOD_S = 2
GAS_LIMIT = 30_000_000                   # = the evaluation's reference block gas limit
BALANCE_WEI = 10**24                     # 1,000,000 test ETH per account
IPS = [f"172.16.239.{10 + i}" for i in range(1, N_VALIDATORS + 1)]
QBFT_MIXHASH = "0x63746963616c2062797a616e74696e65206661756c7420746f6c6572616e6365"


def validator_key(i: int) -> bytes:
    return keccak256(f"qicas-besu-validator-{i}".encode())


def account_key(j: int) -> bytes:
    return keccak256(f"qicas-besu-account-{j}".encode())


def address_of(key: bytes) -> str:
    return Account.from_key(key).address


def enode(i: int) -> str:
    pub = keys.PrivateKey(validator_key(i)).public_key.to_hex()[2:]
    return f"enode://{pub}@{IPS[i - 1]}:30303"


def qbft_extra_data(validators: list[str]) -> str:
    """RLP([32-byte vanity, [validators], [] (no vote), round 0 (empty bytes), [] (no seals)])."""
    enc = rlp.encode([b"\0" * 32, [bytes.fromhex(v[2:]) for v in validators], [], b"", []])
    return "0x" + enc.hex()


def genesis() -> dict:
    validators = sorted(address_of(validator_key(i)) for i in range(1, N_VALIDATORS + 1))
    return {
        "_comment": "TEST ONLY - deterministic QICAS Phase 5 QBFT genesis (chain/besu/generate.py). Never use on a real network.",
        "config": {
            "chainId": CHAIN_ID, "berlinBlock": 0, "londonBlock": 0, "shanghaiTime": 0, "zeroBaseFee": True,
            "qbft": {"blockperiodseconds": BLOCK_PERIOD_S, "epochlength": 30000, "requesttimeoutseconds": 4},
        },
        "nonce": "0x0", "timestamp": "0x0", "gasLimit": hex(GAS_LIMIT), "difficulty": "0x1",
        "mixHash": QBFT_MIXHASH, "coinbase": "0x" + "00" * 20,
        "alloc": {address_of(account_key(j))[2:].lower(): {"balance": hex(BALANCE_WEI)} for j in range(N_ACCOUNTS)},
        "extraData": qbft_extra_data(validators),
    }


def files() -> dict[Path, str]:
    out = {HERE / "genesis.json": json.dumps(genesis(), indent=2) + "\n",
           HERE / "static.json": json.dumps({"bootnode": enode(1), "validators": {
               f"validator{i}": {"address": address_of(validator_key(i)), "ip": IPS[i - 1],
                                 "rpc": f"http://127.0.0.1:{8544 + i}"} for i in range(1, N_VALIDATORS + 1)},
               "accounts": [address_of(account_key(j)) for j in range(N_ACCOUNTS)]}, indent=2) + "\n"}
    for i in range(1, N_VALIDATORS + 1):
        out[HERE / "nodes" / f"validator{i}" / "key"] = "0x" + validator_key(i).hex()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    bad = 0
    for path, text in files().items():
        if a.check:
            ok = path.is_file() and path.read_text(encoding="utf-8").replace("\r\n", "\n") == text
            print(f"{path.relative_to(HERE)}: {'OK' if ok else 'DIFFERENT'}")
            bad += not ok
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
            print(f"wrote {path.relative_to(HERE)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
