"""CLI entry point:  python -m demo.run_demo [--config config/demo.yaml] [--mode memory|rpc] [--seed N]"""
from __future__ import annotations

import argparse
import sys

from demo.pipeline import load_config, run, save


def _utf8_console() -> None:
    """Windows consoles/pipes may default to a legacy code page that cannot print '≈'; switch to UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass


def main() -> None:
    _utf8_console()
    ap = argparse.ArgumentParser(description="QICAS case-study end-to-end demo")
    ap.add_argument("--config", default="config/demo.yaml")
    ap.add_argument("--mode", choices=["memory", "rpc", "besu"], help="override chain.mode (besu: Phase 5 QBFT)")
    ap.add_argument("--rpc-url", help="override chain.rpc_url")
    ap.add_argument("--seed", type=int, help="override seed")
    a = ap.parse_args()
    cfg = load_config(a.config)
    if a.mode:
        cfg["chain"]["mode"] = a.mode
    if a.rpc_url:
        cfg["chain"]["rpc_url"] = a.rpc_url
    if a.seed is not None:
        cfg["seed"] = a.seed
    print("=" * 100)
    print("QICAS case-study demo: quantum-inspired, verifiable, carbon-aware scheduling")
    print("=" * 100)
    out = run(cfg)
    save(out)
    print("=" * 100)
    print("Saved full results to results/demo_run.json")


if __name__ == "__main__":
    main()
