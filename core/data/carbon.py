"""Electricity Maps hourly CSV -> carbon intensity (gCO2eq/kWh) for one UTC hour.

Recent portal exports use headers with a subscript two, e.g. `Carbon intensity gCO₂eq/kWh (direct)` and
`... (Life cycle)`; the normaliser below keeps digits including subscript digits, so both old and new headers are
recognised. `basis` selects direct (operational, default) or lca (life-cycle). Timestamps are UTC hour starts.
Licence: Electricity Maps academic licence (no redistribution) — values are read locally, never committed raw.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

TIMESTAMP_COLUMNS = ("datetimeutc", "datetime", "timestamputc", "timestamp", "timeutc", "time")
INTENSITY_COLUMNS = {
    "direct": ("carbonintensitygco2eqkwhdirect", "carbonintensityavg", "carbonintensity",
               "carbonintensitygco2eqkwh", "carbonintensityproductionavg"),
    "lca": ("carbonintensitygco2eqkwhlifecycle", "carbonintensitygco2eqkwhlca", "carbonintensitylifecycle"),
}


def normalize_header(value: str) -> str:
    """Lower-case alphanumerics only; subscript digits (₂) are folded to ASCII digits (2) first."""
    folded = unicodedata.normalize("NFKC", value.lstrip("﻿"))
    return re.sub(r"[^a-z0-9]", "", folded.lower())


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_hour(value: str) -> datetime:
    """Strict snapshot hour: ISO-8601 with an explicit UTC offset, aligned to the hour."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("hour must be an ISO-8601 UTC timestamp with Z, e.g. 2024-10-15T12:00:00Z")
    if parsed.minute or parsed.second or parsed.microsecond:
        raise ValueError("hour must be aligned to the start of an hour")
    return parsed.astimezone(timezone.utc)


def find_column(headers: list[str], candidates: tuple[str, ...], what: str) -> str:
    norm = {normalize_header(h): h for h in headers}
    for c in candidates:
        if c in norm:
            return norm[c]
    raise ValueError(f"CSV is missing a recognised {what} column; found: {', '.join(headers)}")


@dataclass(frozen=True)
class CarbonReading:
    value: Decimal              # exact value from the file
    g_per_kwh: int              # rounded half-up (contract unit)
    basis: str
    estimated: bool | None      # Electricity Maps "Data estimated" flag, if present
    zone: str | None


def read_carbon(path: str | Path, hour: datetime, basis: str = "direct") -> CarbonReading:
    if basis not in INTENSITY_COLUMNS:
        raise ValueError(f"basis must be one of {sorted(INTENSITY_COLUMNS)}")
    p = Path(path)
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"{p}: CSV is empty or has no header")
        ts = find_column(reader.fieldnames, TIMESTAMP_COLUMNS, "UTC timestamp")
        col = find_column(reader.fieldnames, INTENSITY_COLUMNS[basis], f"{basis} carbon-intensity")
        matches = [r for r in reader if parse_utc(r[ts]) == hour]
    if not matches:
        raise ValueError(f"{p}: no row for {hour.isoformat()}")
    if len(matches) > 1:
        raise ValueError(f"{p}: multiple rows for {hour.isoformat()}")
    row = matches[0]
    try:
        v = Decimal(row[col].strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError(f"{p}: carbon intensity is not a number") from exc
    if not v.is_finite() or v < 0:
        raise ValueError(f"{p}: carbon intensity must be finite and non-negative")
    est_key = next((h for h in row if normalize_header(h) == "dataestimated"), None)
    zone_key = next((h for h in row if normalize_header(h) == "zoneid"), None)
    est = None if est_key is None else row[est_key].strip().lower() == "true"
    return CarbonReading(v, int(v.quantize(Decimal("1"), rounding=ROUND_HALF_UP)), basis, est,
                         row[zone_key].strip() if zone_key else None)
