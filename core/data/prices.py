"""Day-ahead prices for one UTC hour + ECB FX conversion (docs/DATA_SOURCES.md C1-C4, D).

Sources (each with explicit time-zone handling):
  entsoe   ENTSO-E Transparency CSV (new GUI): `MTU (UTC)` = "dd/mm/yyyy HH:MM:SS - dd/mm/yyyy HH:MM:SS",
           `Day-ahead Price (EUR/MWh)`. The MTU header must say UTC. Sub-hourly MTUs are time-weighted.
  em_json  Electricity Maps API price-day-ahead JSON: data[] with ISO UTC `datetime`, `value`, `unit`.
  iex_xlsx IEX India DAM "Market Snapshot" xlsx: `Hour` 1..24 in IST (UTC+5:30), `MCP (Rs/MWh)`.
           Hour h covers [h-1:00, h:00) IST. align="instant" (approved): the IST hour containing the snapshot
           instant; align="overlap": time-weighted mean over the UTC hour (sensitivity only).
Read with the standard library only (zipfile + xml for xlsx; AGENTS.md rule 9).

Units: prices are returned as exact Fractions in their native currency per MWh; `to_eur_per_mwh` converts with
ECB rates (currency per EUR) and `to_uusd_per_kwh` gives the contract unit µUSD/kWh (1 USD/MWh = 1000 µUSD/kWh),
rounded half-up once at the end. Negative or missing prices raise (the contract stores uint256).
"""
from __future__ import annotations

import csv
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

from .carbon import normalize_header, parse_utc

HOUR = timedelta(hours=1)
IST = timezone(timedelta(hours=5, minutes=30))


@dataclass(frozen=True)
class PriceReading:
    value: Fraction             # native currency per MWh, exact
    currency: str               # EUR, USD, INR
    source: str                 # entsoe | em_json | iex_xlsx
    detail: dict[str, Any] = field(default_factory=dict)


def _dec(s: str) -> Fraction:
    s = str(s).strip().replace(",", "")
    if not re.fullmatch(r"-?\d+(\.\d+)?", s):
        raise ValueError(f"not a number: {s!r}")
    return Fraction(s)


def _check(v: Fraction, where: str) -> Fraction:
    if v < 0:
        raise ValueError(f"{where}: negative price {float(v)} (contract stores uint256; refusing, not clamping)")
    return v


def _weighted(intervals: list[tuple[datetime, datetime, Fraction]], hour: datetime, where: str) -> tuple[Fraction, list]:
    """Time-weighted mean of the intervals overlapping [hour, hour+1h); the hour must be fully covered."""
    end = hour + HOUR
    parts, covered, total = [], 0, Fraction(0)
    for a, b, v in intervals:
        lo, hi = max(a, hour), min(b, end)
        sec = int((hi - lo).total_seconds())
        if sec > 0:
            parts.append((a.isoformat(), b.isoformat(), str(v), sec))
            covered += sec
            total += v * sec
    if covered != 3600:
        raise ValueError(f"{where}: rows cover {covered} s of the hour {hour.isoformat()}, need 3600")
    return total / 3600, parts


# ---------------------------------------------------------------------------------------------- ENTSO-E
def read_entsoe(path: str | Path, hour: datetime) -> PriceReading:
    p = Path(path)
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        heads = reader.fieldnames or []
        mtu = next((h for h in heads if normalize_header(h).startswith("mtu")), None)
        price = next((h for h in heads if normalize_header(h).startswith("dayaheadprice")), None)
        if mtu is None or price is None:
            raise ValueError(f"{p}: need 'MTU (...)' and 'Day-ahead Price (...)' columns; found {heads}")
        if "UTC" not in mtu:
            raise ValueError(f"{p}: MTU column {mtu!r} is not in UTC; export with time zone UTC")
        if "EUR/MWh" not in price:
            raise ValueError(f"{p}: price column {price!r} is not EUR/MWh")
        area_col = next((h for h in heads if normalize_header(h) == "area"), None)
        intervals, areas = [], set()
        for r in reader:
            if not r[price].strip():
                continue
            a_s, b_s = [s.strip() for s in r[mtu].split(" - ")]
            a = datetime.strptime(a_s, "%d/%m/%Y %H:%M:%S").replace(tzinfo=timezone.utc)
            b = datetime.strptime(b_s, "%d/%m/%Y %H:%M:%S").replace(tzinfo=timezone.utc)
            intervals.append((a, b, _dec(r[price])))
            if area_col:
                areas.add(r[area_col].strip())
    v, parts = _weighted(intervals, hour, str(p))
    return PriceReading(_check(v, str(p)), "EUR", "entsoe", {"area": sorted(areas), "intervals": parts})


# ---------------------------------------------------------------------------------------------- EM JSON
def read_em_price_json(path: str | Path, hour: datetime) -> PriceReading:
    p = Path(path)
    d = json.loads(p.read_text(encoding="utf-8"))
    rows = d["data"] if isinstance(d, dict) else d
    hits = [r for r in rows if parse_utc(r["datetime"]) == hour]
    if len(hits) != 1:
        raise ValueError(f"{p}: expected one row for {hour.isoformat()}, found {len(hits)}")
    r = hits[0]
    unit = str(r.get("unit", ""))
    m = re.fullmatch(r"([A-Z]{3})/MWh", unit)
    if not m:
        raise ValueError(f"{p}: unexpected unit {unit!r}")
    v = _dec(str(r["value"]))
    return PriceReading(_check(v, str(p)), m.group(1), "em_json",
                        {"zone": r.get("zone") or (d.get("zone") if isinstance(d, dict) else None),
                         "row_source": r.get("source")})


# ---------------------------------------------------------------------------------------------- IEX xlsx
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def xlsx_rows(path: str | Path) -> list[list[str]]:
    """All cell values (as strings) of the first worksheet, stdlib only."""
    with zipfile.ZipFile(path) as z:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", _NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))
        sheets = sorted(n for n in z.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
        if not sheets:
            raise ValueError(f"{path}: no worksheet")
        out = []
        for row in ET.fromstring(z.read(sheets[0])).iter(f"{{{_NS['m']}}}row"):
            vals = []
            for c in row.findall("m:c", _NS):
                v, t = c.find("m:v", _NS), c.get("t")
                if t == "s" and v is not None:
                    vals.append(shared[int(v.text)])
                elif t == "inlineStr":
                    vals.append("".join(x.text or "" for x in c.iter(f"{{{_NS['m']}}}t")))
                else:
                    vals.append(v.text if v is not None and v.text is not None else "")
            out.append(vals)
        return out


def read_iex_xlsx(path: str | Path, hour: datetime, align: str = "instant") -> PriceReading:
    p = Path(path)
    rows = xlsx_rows(p)
    hdr_i = next((i for i, r in enumerate(rows) if r and r[0].strip() == "Date" and len(r) > 1
                  and r[1].strip() == "Hour"), None)
    if hdr_i is None:
        raise ValueError(f"{p}: no 'Date, Hour, ...' header row (expected the hourly Market Snapshot)")
    hdr = rows[hdr_i]
    mcp = next((i for i, h in enumerate(hdr) if normalize_header(h).startswith("mcprsmwh")), None)
    if mcp is None:
        raise ValueError(f"{p}: no 'MCP (Rs/MWh)' column; found {hdr}")
    regional = [h for h in hdr if re.search(r"\bW[123]\b", h)]
    by_hour: dict[datetime, Fraction] = {}
    for r in rows[hdr_i + 1:]:
        if len(r) <= mcp or not re.fullmatch(r"\d{1,2}", r[1].strip() if len(r) > 1 else ""):
            if r and r[0].strip() == "Date":
                break                                  # summary block starts
            continue
        day = datetime.strptime(r[0].strip(), "%d-%m-%Y")
        h = int(r[1])
        start = datetime(day.year, day.month, day.day, tzinfo=IST) + timedelta(hours=h - 1)
        by_hour[start.astimezone(timezone.utc)] = _dec(r[mcp])
    if not by_hour:
        raise ValueError(f"{p}: no hourly rows")
    if align == "instant":
        hits = [(a, v) for a, v in by_hour.items() if a <= hour < a + HOUR]
        if len(hits) != 1:
            raise ValueError(f"{p}: no IST hour contains {hour.isoformat()}")
        a, v = hits[0]
        detail = {"ist_hour_start": a.astimezone(IST).isoformat(), "align": "instant"}
    elif align == "overlap":
        v, parts = _weighted([(a, a + HOUR, x) for a, x in sorted(by_hour.items())], hour, str(p))
        detail = {"align": "overlap", "intervals": parts}
    else:
        raise ValueError("align must be 'instant' or 'overlap'")
    detail["price_column"] = hdr[mcp]
    detail["regional_columns"] = regional
    detail["scope"] = "regional" if regional else "all-India MCP (no W1-W3 columns in file)"
    return PriceReading(_check(v, str(p)), "INR", "iex_xlsx", detail)


# ---------------------------------------------------------------------------------------------- FX
def to_eur_per_mwh(r: PriceReading, per_eur: dict[str, Fraction | str]) -> Fraction:
    """per_eur: ECB rates, units of currency per 1 EUR (e.g. {'USD': '1.0903', 'INR': '91.622'})."""
    if r.currency == "EUR":
        return r.value
    if r.currency not in per_eur:
        raise ValueError(f"no ECB rate for {r.currency}")
    return r.value / Fraction(str(per_eur[r.currency]))


def to_uusd_per_kwh(eur_per_mwh: Fraction, usd_per_eur: Fraction | str) -> int:
    """EUR/MWh -> µUSD/kWh (1 USD/MWh = 1000 µUSD/kWh), exact until one half-up rounding."""
    x = eur_per_mwh * Fraction(str(usd_per_eur)) * 1000
    return int((2 * x.numerator + x.denominator) // (2 * x.denominator))


def read_price(kind: str, path: str | Path, hour: datetime, **kw: Any) -> PriceReading:
    if kind == "entsoe":
        return read_entsoe(path, hour)
    if kind == "em_json":
        return read_em_price_json(path, hour)
    if kind == "iex_xlsx":
        return read_iex_xlsx(path, hour, kw.get("align", "instant"))
    raise ValueError(f"unknown price source kind {kind!r}")
