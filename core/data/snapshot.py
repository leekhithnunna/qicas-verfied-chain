"""Config `snapshot:` block -> integer region inputs + provenance (config/real_snapshot.yaml).

The committed config holds only the derived integers (one carbon intensity and one price per region, for one
hour) plus citations. This module recomputes them from the git-ignored raw files, checks SHA-256s, and compares
them with the committed values (`check_regions`). Without data/ the committed values are used as they are.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from . import sha256_file
from .carbon import parse_hour, read_carbon
from .prices import read_price, to_eur_per_mwh, to_uusd_per_kwh


@dataclass
class RegionSnapshot:
    name: str
    zone: str
    ci_exact: str
    ci_g_per_kwh: int
    ci_estimated: bool | None
    price_native: str
    currency: str
    price_eur_per_mwh: float
    price_uusd_per_kwh: int
    price_source: str
    price_detail: dict[str, Any] = field(default_factory=dict)


def resolve(root: Path, p: str) -> Path:
    q = Path(p)
    return q if q.is_absolute() else root / q


def raw_files(snap: dict[str, Any]) -> dict[str, str]:
    """Every raw file referenced by the snapshot block -> expected SHA-256 (may be empty string)."""
    out = {}
    for src in snap["sources"].values():
        for k in ("carbon", "price"):
            out[src[k]["path"]] = src[k].get("sha256", "")
    if snap.get("fx", {}).get("path"):
        out[snap["fx"]["path"]] = snap["fx"].get("sha256", "")
    return out


def data_present(snap: dict[str, Any], root: Path) -> bool:
    return all(resolve(root, p).is_file() for p in raw_files(snap))


def verify_hashes(snap: dict[str, Any], root: Path) -> dict[str, dict[str, Any]]:
    res = {}
    for p, want in raw_files(snap).items():
        got = sha256_file(resolve(root, p))
        res[p] = {"sha256": got, "expected": want, "match": (not want) or got == want}
    return res


def compute(snap: dict[str, Any], root: Path, basis: str | None = None,
            iex_align: str | None = None) -> list[RegionSnapshot]:
    hour = parse_hour(str(snap["hour"]))
    basis = basis or snap.get("carbon_basis", "direct")
    fx = snap["fx"]
    per_eur = {"USD": Fraction(str(fx["usd_per_eur"])), "INR": Fraction(str(fx["inr_per_eur"]))}
    out = []
    for name, src in snap["sources"].items():
        c = read_carbon(resolve(root, src["carbon"]["path"]), hour, basis)
        if c.zone and c.zone != src["carbon"]["zone"]:
            raise ValueError(f"{name}: carbon file zone {c.zone!r} != configured {src['carbon']['zone']!r}")
        pk = src["price"]
        align = iex_align or pk.get("align", "instant")
        pr = read_price(pk["kind"], resolve(root, pk["path"]), hour, align=align)
        eur = to_eur_per_mwh(pr, per_eur)
        out.append(RegionSnapshot(
            name=name, zone=src["carbon"]["zone"], ci_exact=str(c.value), ci_g_per_kwh=c.g_per_kwh,
            ci_estimated=c.estimated, price_native=f"{float(pr.value):.6g}", currency=pr.currency,
            price_eur_per_mwh=round(float(eur), 4), price_uusd_per_kwh=to_uusd_per_kwh(eur, per_eur["USD"]),
            price_source=pr.source, price_detail=pr.detail))
    return out


def check_regions(cfg_regions: list[dict[str, Any]], computed: list[RegionSnapshot]) -> list[str]:
    """Differences between the committed config region values and values recomputed from raw data."""
    by = {r.name: r for r in computed}
    diffs = []
    for r in cfg_regions:
        c = by.get(r["name"])
        if c is None:
            diffs.append(f"{r['name']}: no snapshot source")
            continue
        for key in ("ci_g_per_kwh", "price_uusd_per_kwh"):
            if not isinstance(r.get(key), int) or r[key] != getattr(c, key):
                diffs.append(f"{r['name']}: {key} committed {r[key]} != recomputed {getattr(c, key)}")
    return diffs
