"""OPTIONAL Phase 5 demo: the consortium votes a 5th validator in, then out again (QBFT validator voting).

    .\\.venv\\Scripts\\python.exe -m chain.besu.vote

A majority (3 of 4) of validators call qbft_proposeValidatorVote on their own RPC port; each proposer then
puts its vote into the blocks it proposes. The new address has no running node: with 5 validators the QBFT
quorum is 4, which the 4 live nodes still meet. Votes are discarded afterwards. TEST network only.
"""
from __future__ import annotations

import json
import sys
import time

from chain.besu.status import rpc, status
from core.hashing import keccak256

PORTS = [8545, 8546, 8547, 8548]


def candidate() -> str:
    from eth_account import Account
    return Account.from_key(keccak256(b"qicas-besu-candidate-validator")).address


def _vote(addr: str, add: bool, voters: int = 3) -> None:
    for p in PORTS[:voters]:
        assert rpc("qbft_proposeValidatorVote", [addr, add], url=f"http://127.0.0.1:{p}") is True


def _discard(addr: str) -> None:
    for p in PORTS:
        rpc("qbft_discardValidatorVote", [addr], url=f"http://127.0.0.1:{p}")


def _wait(pred, timeout_s: float) -> tuple[bool, float]:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        s = status()
        if s and pred([v.lower() for v in s["validators"]]):
            return True, time.time() - t0
        time.sleep(1)
    return False, time.time() - t0


def add_then_remove(timeout_s: float = 90) -> dict:
    addr = candidate()
    _vote(addr, True)
    added, t_add = _wait(lambda vs: addr.lower() in vs and len(vs) == 5, timeout_s)
    _discard(addr)
    blocks_with_5 = status()["block"]
    _vote(addr, False)
    removed, t_rm = _wait(lambda vs: addr.lower() not in vs and len(vs) == 4, timeout_s)
    _discard(addr)
    after = status()
    return {"candidate": addr, "added": added, "seconds_to_add": round(t_add, 1), "removed": removed,
            "seconds_to_remove": round(t_rm, 1), "block_when_added": blocks_with_5,
            "validators_after": len(after["validators"]), "block_after": after["block"]}


if __name__ == "__main__":
    r = add_then_remove()
    print(json.dumps(r, indent=2))
    sys.exit(0 if r["added"] and r["removed"] else 1)
