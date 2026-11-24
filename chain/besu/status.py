"""Besu QBFT network status (stdlib JSON-RPC, no web3 needed).

    .\\.venv\\Scripts\\python.exe -m chain.besu.status            # one-shot status
    .\\.venv\\Scripts\\python.exe -m chain.besu.status --wait 180  # wait until blocks are produced by 4 validators
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

RPC = "http://127.0.0.1:8545"


def rpc(method: str, params: list | None = None, url: str = RPC, timeout: float = 3.0):
    body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params or [], "id": 1}).encode()
    req = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read())
    if "error" in out:
        raise RuntimeError(out["error"])
    return out["result"]


def status(url: str = RPC) -> dict | None:
    """None if nothing answers; else block number, chain id, validators, peers."""
    try:
        block = int(rpc("eth_blockNumber", url=url), 16)
        return {"block": block, "chain_id": int(rpc("eth_chainId", url=url), 16),
                "validators": rpc("qbft_getValidatorsByBlockNumber", ["latest"], url=url),
                "peers": int(rpc("net_peerCount", url=url), 16)}
    except Exception:
        return None


def is_up(url: str = RPC) -> bool:
    s = status(url)
    return bool(s and s["block"] > 0 and len(s["validators"]) >= 4)


def wait(timeout_s: float = 180, url: str = RPC) -> dict | None:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        s = status(url)
        if s and s["block"] > 1 and len(s["validators"]) >= 4:
            return s
        time.sleep(2)
    return status(url)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=float, default=0)
    ap.add_argument("--url", default=RPC)
    a = ap.parse_args(argv)
    s = wait(a.wait, a.url) if a.wait else status(a.url)
    print(json.dumps(s, indent=2) if s else f"nothing answers on {a.url}")
    return 0 if s and s["block"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
