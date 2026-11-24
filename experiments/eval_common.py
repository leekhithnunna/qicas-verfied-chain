"""Shared helpers for the Phase 6-lite evaluation harness (experiments/run_all.py).

Conventions used by every experiment CSV in results/eval/:
  * every row has a `status` column: "ok", "NOT RUN - Phase X missing", "documented assumption", ...
  * columns ending in "_s" are timing columns (CPU / wall seconds); they are the ONLY columns allowed to
    differ between two runs of the same profile (tests/test_eval_smoke.py checks this).
  * anything that needs a phase that is not built yet gets an explicit NOT RUN row; nothing is skipped
    silently.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
STATUS_OK = "ok"
ASSUMPTION = "documented assumption"

# Which phases exist in this build: all of 1-5. Phase 1 rows additionally need the git-ignored data files:
# without them they are "NOT RUN - data missing" (real_workloads below). E6 (Besu vs in-memory) additionally needs
# the opt-in Besu network: without it its rows are "NOT RUN - Besu not running".
PHASES_PRESENT = {"case-study": True, 1: True, 2: True, 3: True, 4: True, 5: True}
DATA_MISSING = "NOT RUN - data missing"
BESU_MISSING = "NOT RUN - Besu not running"


# E1 overhead definitions (sensitivity.csv column overhead_terms)
FLOW_TERM = "case-study flow gas (deploy..finalize)"
MARKET_TERM = "case-study flow + on-chain market (openMarket + R x (submitBatch + closeRound))"
TRUST_TERM = ("case-study flow + on-chain market + trust layer (oracle snapshot + bound claim/finalize)")


def primary_term(terms) -> str:
    """The most complete overhead definition present (trust layer > market > case-study flow only)."""
    t = set(terms)
    return TRUST_TERM if TRUST_TERM in t else MARKET_TERM if MARKET_TERM in t else FLOW_TERM


def not_run(phase: int | str) -> str:
    return f"NOT RUN - Phase {phase} missing"


def phase_present(phase: int | str) -> bool:
    return bool(PHASES_PRESENT.get(phase, False))


def real_workloads(real_cfg: dict[str, Any], seeds: Iterable[int]) -> tuple[dict[int, Path], list[str]]:
    """Phase 1 processed workload files for the given sample seeds -> (present {seed: path}, missing paths)."""
    from core.instance import workload_path
    present, missing = {}, []
    for s in seeds:
        p = workload_path(real_cfg, int(s))
        if p.is_file():
            present[int(s)] = p
        else:
            missing.append(str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p))
    return present, missing


def load_real_config(eval_cfg: dict[str, Any]) -> dict[str, Any] | None:
    rc = eval_cfg.get("real_config")
    if not rc:
        return None
    return yaml.safe_load((ROOT / rc).read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------- context
@dataclass
class Context:
    profile_name: str
    profile: dict[str, Any]
    eval_cfg: dict[str, Any]
    base_cfg: dict[str, Any]
    out: Path
    log: Callable[[str], None] = print
    cache: dict[str, Any] = field(default_factory=dict)      # shared between experiments (E1/E2 flows)


@dataclass
class ExpResult:
    files: list[str] = field(default_factory=list)
    not_run: list[dict[str, str]] = field(default_factory=list)   # {experiment, item, status, note}
    summary: dict[str, Any] = field(default_factory=dict)


def load_eval_config(path: str | Path = "config/eval.yaml") -> dict[str, Any]:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def load_base_config(eval_cfg: dict[str, Any]) -> dict[str, Any]:
    return yaml.safe_load((ROOT / eval_cfg["base_config"]).read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------- CSV
def write_csv(path: Path, rows: Iterable[dict[str, Any]], columns: list[str]) -> None:
    """Write rows with an explicit column order (missing keys -> empty cell). Floats are written with
    repr-stable formatting so two identical runs give byte-identical files (time columns aside)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="raise")
        w.writeheader()
        for r in rows:
            w.writerow({c: _fmt(r.get(c, "")) for c in columns})


def _fmt(v: Any) -> Any:
    if isinstance(v, (bool, np.bool_)):
        return str(bool(v))
    if isinstance(v, (float, np.floating)):
        v = float(v)
        if v != v:                          # NaN
            return ""
        return repr(v)                      # shortest exact round-trip (10 sig. digits lost precision at 1e5 g)
    if isinstance(v, np.integer):
        return int(v)
    return v


def read_csv(path: Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def is_time_column(name: str) -> bool:
    return name.endswith("_s")


def csv_hash_without_time(path: Path) -> str:
    """SHA-256 of a CSV with its timing columns (names ending in _s) removed."""
    rows = read_csv(path)
    with Path(path).open(newline="", encoding="utf-8") as fh:
        header = next(csv.reader(fh), [])
    keep = [c for c in header if not is_time_column(c)]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(keep)
    for r in rows:
        w.writerow([r[c] for c in keep])
    return hashlib.sha256(buf.getvalue().encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ------------------------------------------------------------------------------- determinism
def seeded_salts(seed: int) -> Callable[[], bytes]:
    """Deterministic 32-byte commit salts (gas depends on calldata zero bytes, so random salts would make
    gas numbers irreproducible by a few units)."""
    counter = [0]

    def nxt() -> bytes:
        counter[0] += 1
        return hashlib.sha256(f"qicas-eval-salt/{seed}/{counter[0]}".encode()).digest()
    return nxt


# ------------------------------------------------------------------------------- statistics
def bootstrap_mean_ci(values: Iterable[float], n_boot: int = 2000, seed: int = 0,
                      alpha: float = 0.05) -> tuple[float, float, float]:
    """Mean and percentile-bootstrap (1 - alpha) CI. numpy only (no SciPy)."""
    a = np.asarray(list(values), dtype=float)
    if a.size == 0:
        return float("nan"), float("nan"), float("nan")
    mean = float(a.mean())
    if a.size == 1 or np.all(a == a[0]):
        return mean, mean, mean
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, a.size, size=(n_boot, a.size))
    boots = a[idx].mean(axis=1)
    lo, hi = np.quantile(boots, [alpha / 2, 1 - alpha / 2])
    return mean, float(lo), float(hi)


# ------------------------------------------------------------------------------- environment
def git_info() -> dict[str, Any]:
    def run(*args: str) -> str:
        try:
            return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                                  timeout=20).stdout.strip()
        except Exception:                   # git missing: record that, do not fail the run
            return ""
    commit = run("rev-parse", "HEAD")
    dirty = run("status", "--porcelain", "--untracked-files=no")
    return {"commit": commit or "unknown", "dirty": bool(dirty)}


def package_versions() -> dict[str, str]:
    from importlib import metadata
    out = {"python": sys.version.split()[0], "platform": platform.platform()}
    for pkg in ("numpy", "pandas", "pyyaml", "web3", "eth-tester", "py-evm", "matplotlib", "streamlit"):
        try:
            out[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            out[pkg] = "not installed"
    return out


def dump_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
