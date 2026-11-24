r"""Recompute the Phase 1 snapshot inputs from the raw files and compare with config/real_snapshot.yaml.

    .\.venv\Scripts\python.exe scripts\build_real_snapshot.py            # table + check (exit 1 on mismatch)
    .\.venv\Scripts\python.exe scripts\build_real_snapshot.py --basis lca --iex-align overlap   # sensitivity

Prints only the snapshot-hour values (one per region) — never per-hour series (Electricity Maps licence).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from core.data.snapshot import check_regions, compute, data_present, raw_files, verify_hashes  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(ROOT / "config/real_snapshot.yaml"))
    ap.add_argument("--basis", choices=["direct", "lca"], default=None)
    ap.add_argument("--iex-align", choices=["instant", "overlap"], default=None)
    a = ap.parse_args(argv)
    cfg = yaml.safe_load(Path(a.config).read_text(encoding="utf-8"))
    snap = cfg["snapshot"]
    if not data_present(snap, ROOT):
        missing = [p for p in raw_files(snap) if not (ROOT / p).is_file()]
        print(f"NOT RUN - data missing: {missing}")
        return 2
    hashes = verify_hashes(snap, ROOT)
    for p, h in hashes.items():
        print(f"  {'OK ' if h['match'] else 'BAD'} {h['sha256'][:16]}…  {p}")
    rows = compute(snap, ROOT, a.basis, a.iex_align)
    print(f"\nsnapshot {snap['hour']}  basis={a.basis or snap.get('carbon_basis')}  "
          f"FX {snap['fx']['date']}: USD {snap['fx']['usd_per_eur']}/EUR, INR {snap['fx']['inr_per_eur']}/EUR")
    print(f"{'region':26} {'zone':12} {'CI g/kWh':>10} {'int':>4} {'est':>5}  {'price native':>18} "
          f"{'EUR/MWh':>9} {'µUSD/kWh':>9}  source")
    for r in rows:
        print(f"{r.name:26} {r.zone:12} {r.ci_exact:>10} {r.ci_g_per_kwh:>4} {str(r.ci_estimated):>5}  "
              f"{r.price_native + ' ' + r.currency + '/MWh':>18} {r.price_eur_per_mwh:>9.4f} "
              f"{r.price_uusd_per_kwh:>9}  {r.price_source} {r.price_detail.get('scope', '')}"
              f"{r.price_detail.get('ist_hour_start', '')}")
    bad = [p for p, h in hashes.items() if not h["match"]]
    diffs = check_regions(cfg["regions"], rows) if a.basis is None and a.iex_align is None else []
    for d in diffs:
        print("MISMATCH", d)
    if not diffs and a.basis is None and a.iex_align is None:
        print("\ncommitted config region values match the raw data")
    return 1 if bad or diffs else 0


if __name__ == "__main__":
    raise SystemExit(main())
