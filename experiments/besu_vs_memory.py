"""E6 / Phase 5 measurements: the same flows on the in-memory chain (eth-tester + py-evm) and on the 4-validator
Besu QBFT network (chain/besu).

    scripts\\besu_up.ps1; .\\.venv\\Scripts\\python.exe -m experiments.besu_vs_memory     # -> results/besu/
    (inside experiments.run_all, E6 runs only with QICAS_BESU=1 and a running network; else an explicit
     "NOT RUN - Besu not running" row)

Flows (seed-7 instance, seeded salts): (1) V1 case-study pipeline (demo/pipeline.py); (2) Phase 5 V3 token flow
(demo/pipeline_v3.py: oracle snapshot, tokens, V3, 2 PriceMarket rounds + bound claim, finalize -> credits +
soulbound certificate; no bound finalisation on either chain, so both run the same transactions).
Per chain: gas per function, send-to-confirmation time per function (dry-run call + send + receipt, *_s columns
are timing columns), flow wall-clock, blocks produced, carbon overhead at the demo's sensitivity parameters.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from experiments.eval_common import BESU_MISSING, ROOT, STATUS_OK, Context, ExpResult, seeded_salts, write_csv

E6_COLUMNS = ["flow", "chain", "function", "calls", "gas_mean", "gas_total", "confirm_mean_s", "confirm_max_s",
              "status", "note"]
E6_SUMMARY_COLUMNS = ["flow", "chain", "transactions", "gas_total", "wall_s", "blocks_produced", "block_period_s",
                      "overhead_g_at_demo_params", "outcome", "status", "note"]


def besu_available() -> bool:
    from chain.besu.status import is_up
    return os.environ.get("QICAS_BESU") == "1" and is_up()


def _timed(chain) -> list[tuple[str, float]]:
    """Wrap chain._send to record (action, seconds from dry-run to receipt) for every mined transaction."""
    rec: list[tuple[str, float]] = []
    orig = chain._send

    def timed(action, fn, sender, *a, **k):
        t0 = time.perf_counter()
        r = orig(action, fn, sender, *a, **k)
        rec.append((action, time.perf_counter() - t0))
        return r
    chain._send = timed
    return rec


def _block(chain) -> int:
    return int(chain.w3.eth.block_number)


def measure(mode: str, cfg: dict[str, Any], log=print) -> dict[str, Any]:
    from chain.client import Chain
    from demo.pipeline import run as run_v1
    from demo.pipeline_v3 import run_v3
    stake = int(cfg["chain"]["stake_wei"])
    res: dict[str, Any] = {}

    # V1 case-study flow
    chain = Chain.start(mode, min_stake=stake)
    times = _timed(chain)
    b0, t0 = _block(chain), time.perf_counter()
    out = run_v1(cfg, log=lambda *_: None, chain=chain, salt_fn=seeded_salts(7))
    wall, b1 = time.perf_counter() - t0, _block(chain)
    f = out["final"]
    res["v1"] = {"txs": [(t["action"], t["gas"]) for t in out["transactions"] if t["status"] == "ok"],
                 "times": times, "wall_s": wall, "blocks": b1 - b0, "gas_total": f["total_gas"],
                 "overhead_g": f["overhead_g"],
                 "outcome": f"winner {f['winner']}, scores " + ",".join(
                     str(r.get("score", r["status"])) for r in out["reveals"]) + f", root {f['merkle_root'][:10]}, "
                     f"{f['credits_minted']} credits"}
    log(f"    [{mode}] V1 flow: {len(res['v1']['txs'])} txs, gas {f['total_gas']:,}, {wall:.1f} s, {b1 - b0} blocks")

    # V3 token flow (oracle + tokens + V3 + 2 market rounds + claim)
    base = Chain.start(mode, min_stake=stake)
    b0, t0 = _block(base), time.perf_counter()
    import chain.client as cc
    rec: list[tuple[str, float]] = []
    orig = cc.Chain._send

    def timed(self, action, fn, sender, *a, **k):          # every Chain view (oracle, tokens, V3, PriceMarket)
        t = time.perf_counter()
        r = orig(self, action, fn, sender, *a, **k)
        rec.append((action, time.perf_counter() - t))
        return r
    cc.Chain._send = timed
    try:
        v3 = run_v3(cfg, base, salt_fn=seeded_salts(7), market_rounds=2, finalize_bound=False, log=lambda *_: None)
    finally:
        cc.Chain._send = orig
    wall, b1 = time.perf_counter() - t0, _block(base)
    pm_txs = v3["_stack"].market.txs                     # V3 txs; PriceMarket txs are in its own client
    txs = [(t["action"], t["gas"]) for t in v3["transactions"] if t["status"] == "ok"]
    res["v3"] = {"txs": txs, "times": rec, "wall_s": wall, "blocks": b1 - b0,
                 "gas_total": sum(g for _, g in txs) + v3["market"]["market_gas_total"] + v3["market"]["claim_gas"],
                 "overhead_g": v3["overhead_ug"] / 1e6,
                 "outcome": f"winner {v3['winner']}, {v3['credits']} credits, certificate #{v3['epoch_id']} "
                            f"(gap {v3['certified_gap_bps']} bps), parity {all(v3['parity'].values())}, "
                            f"early finalizeBound {v3['market'].get('early_finalize')}",
                 "market_gas_total": v3["market"]["market_gas_total"], "v3_txs": len(pm_txs)}
    log(f"    [{mode}] V3 flow: {len(txs)} txs (+ market), {wall:.1f} s, {b1 - b0} blocks; {res['v3']['outcome']}")
    return res


def rows_from(results: dict[str, dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    rows, summ = [], []
    for mode, res in results.items():
        for flow, r in res.items():
            gas: dict[str, list[int]] = defaultdict(list)
            for a, g in r["txs"]:
                gas[a].append(int(g))
            tm: dict[str, list[float]] = defaultdict(list)
            for a, s in r["times"]:
                tm[a].append(s)
            for fn in sorted(set(gas) | set(tm)):
                gs, ts = gas.get(fn, []), tm.get(fn, [])
                rows.append({"flow": flow, "chain": mode, "function": fn, "calls": len(gs) or len(ts),
                             "gas_mean": float(np.mean(gs)) if gs else "", "gas_total": sum(gs) if gs else "",
                             "confirm_mean_s": float(np.mean(ts)) if ts else "", "confirm_max_s": max(ts) if ts else "",
                             "status": STATUS_OK,
                             "note": "confirm = dry-run call + send + receipt" if ts else "no timing (deploy path)"})
            summ.append({"flow": flow, "chain": mode, "transactions": len(r["txs"]), "gas_total": r["gas_total"],
                         "wall_s": r["wall_s"], "blocks_produced": r["blocks"],
                         "block_period_s": r["wall_s"] / r["blocks"] if r["blocks"] else "",
                         "overhead_g_at_demo_params": r["overhead_g"], "outcome": r["outcome"], "status": STATUS_OK,
                         "note": "memory: one block per transaction (automine)" if mode == "memory"
                         else "Besu QBFT: 4 validators, 2 s block period"})
    return rows, summ


def run_e6(ctx: Context) -> ExpResult:
    if not besu_available():
        write_csv(ctx.out / "besu_vs_memory.csv", [{"flow": "all", "chain": "besu", "status": BESU_MISSING,
                                                    "note": "opt-in: QICAS_BESU=1 + scripts/besu_up.ps1"}], E6_COLUMNS)
        return ExpResult(["besu_vs_memory.csv"],
                         [{"experiment": "E6", "item": "Besu vs in-memory measurements", "status": BESU_MISSING,
                           "note": "whole experiment (opt-in: QICAS_BESU=1 + scripts/besu_up.ps1)"}],
                         {"status": BESU_MISSING})
    results = {m: measure(m, ctx.base_cfg, ctx.log) for m in ("memory", "besu")}
    rows, summ = rows_from(results)
    write_csv(ctx.out / "besu_vs_memory.csv", rows, E6_COLUMNS)
    write_csv(ctx.out / "besu_vs_memory_summary.csv", summ, E6_SUMMARY_COLUMNS)
    return ExpResult(["besu_vs_memory.csv", "besu_vs_memory_summary.csv"], [],
                     {"flows": {f"{s['flow']}/{s['chain']}": {k: s[k] for k in ("gas_total", "blocks_produced",
                                                                                "outcome")} for s in summ}})


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config/demo.yaml")
    ap.add_argument("--out", default=str(ROOT / "results" / "besu"))
    a = ap.parse_args(argv)
    from chain.besu.status import is_up
    if not is_up():
        print(f"{BESU_MISSING}: start it with scripts\\besu_up.ps1")
        return 1
    cfg = yaml.safe_load((ROOT / a.config).read_text(encoding="utf-8"))
    results = {m: measure(m, cfg) for m in ("memory", "besu")}
    rows, summ = rows_from(results)
    out = Path(a.out)
    write_csv(out / "gas_and_latency.csv", rows, E6_COLUMNS)
    write_csv(out / "summary.csv", summ, E6_SUMMARY_COLUMNS)
    (out / "summary.json").write_text(json.dumps(summ, indent=2, default=str), encoding="utf-8")
    for s in summ:
        print(f"{s['flow']:3s} {s['chain']:7s} txs={s['transactions']:3d} gas={s['gas_total']:>11,} "
              f"wall={s['wall_s']:6.1f} s blocks={s['blocks_produced']:4d} overhead={s['overhead_g_at_demo_params']:.4f} g"
              f" | {s['outcome']}")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
