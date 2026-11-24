"""Phase 1 real-data loaders (pure Python: stdlib only, no web3/streamlit — AGENTS.md rules 4 and 9).

alibaba   Alibaba cluster-trace-v2018 batch_task -> integer Task/Edge DAG workloads
carbon    Electricity Maps hourly CSV -> carbon intensity for one UTC hour
prices    ENTSO-E CSV, Electricity Maps price JSON, IEX xlsx -> price for one UTC hour; ECB FX conversion
snapshot  config `snapshot:` block -> integer region inputs (ci_g_per_kwh, price_uusd_per_kwh) + provenance

Licences and citations: docs/DATA_SOURCES.md. Raw files live in data/raw/ (git-ignored).
"""
from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
