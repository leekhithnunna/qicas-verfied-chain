"""Repository hygiene (Phase 1 data rules, docs/DATA_SOURCES.md): fast, no data needed.

* nothing under data/ (raw, inbox, processed) is tracked by git;
* no secret files (.env, *.key) are tracked;
* no obvious API-key assignment appears in tracked text files;
* no tracked file looks like an Electricity Maps per-hour export (academic licence: no redistribution).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Named key/token assignments with a long opaque value, e.g. auth-token: "abc...", EM_API_KEY = 'abc...'.
# Deliberately does not match hex constants such as the deterministic TEST signer keys in oracle/signer.py.
KEY_PATTERNS = [
    re.compile(r"""(?i)(auth[-_]?token|api[-_]?key|x-api-key|access[-_]?token|secret[-_]?key)["']?\s*[:=]\s*["'][A-Za-z0-9_\-]{16,}["']"""),
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
]
EM_HEADER = re.compile(r"Carbon intensity gCO.{1,3}eq/kWh", re.IGNORECASE)
EM_MAX_LINES = 30            # tiny synthetic fixtures are allowed; a real export has 8,784 rows
TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".json", ".csv", ".txt", ".toml", ".ini", ".cfg", ".ps1",
                 ".sh", ".js", ".sol", ".env", ""}


def _tracked() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return [p for p in out.stdout.decode("utf-8").split("\0") if p]


def test_nothing_under_data_is_tracked():
    bad = [p for p in _tracked() if p == "data" or p.startswith("data/")]
    assert bad == [], f"data/ must stay git-ignored; tracked: {bad[:10]}"


def test_no_secret_files_tracked():
    bad = [p for p in _tracked() if Path(p).name == ".env" or Path(p).name.startswith(".env.")
           or p.endswith(".key")]
    assert bad == [], bad


def test_no_api_key_patterns_in_tracked_files():
    hits = []
    for rel in _tracked():
        path = ROOT / rel
        if Path(rel).suffix.lower() not in TEXT_SUFFIXES or not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        if rel == "tests/test_repo_hygiene.py":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        hits += [f"{rel}: {pat.pattern[:40]}" for pat in KEY_PATTERNS if pat.search(text)]
    assert hits == [], hits


def test_key_patterns_fire_on_fake_samples():
    """Guards against a vacuous check: the patterns must match obviously fake keys (and not a hex test key)."""
    fake = ['auth-token: "FAKEFAKEFAKEFAKEFAKE1234"', "EM_API_KEY = 'abcdefghijklmnop1234'"]
    assert all(any(p.search(s) for p in KEY_PATTERNS) for s in fake)
    assert not any(p.search("key = 0x" + "11" * 32) for p in KEY_PATTERNS)


def test_no_electricity_maps_hourly_exports_tracked():
    bad = []
    for rel in _tracked():
        path = ROOT / rel
        if Path(rel).suffix.lower() not in {".csv", ".json", ".txt"} or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if EM_HEADER.search(text) and text.count("\n") > EM_MAX_LINES:
            bad.append(rel)
    assert bad == [], f"looks like an Electricity Maps export (no redistribution): {bad}"


def _ignored(path: str) -> bool:
    try:
        r = subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT)
    except OSError:
        pytest.skip("git not available")
    return r.returncode == 0


def test_gitignore_covers_data_but_not_core_data():
    """/data/ is anchored to the repo root: raw/inbox/processed ignored, the core/data/ loader package is not."""
    for p in ("data/raw/inbox/x.csv", "data/raw/carbon/x.csv", "data/processed/x.json", ".env", "x.key"):
        assert _ignored(p), p
    for p in ("core/data/alibaba.py", "tests/fixtures/em_tiny.csv"):
        assert not _ignored(p), p
