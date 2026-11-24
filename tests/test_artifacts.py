"""Artifact guard: the precompiled V1 contract must never change (the default demo's seed-7 overhead line
includes its deploy gas), and every committed artifact must be reproducible from source with the pinned
toolchain (README section 9.3, option B: `node chain/compile.js --check`).

The recompile test needs Node.js + `npm install` in chain/ and takes ~1 min (solc-js, viaIR), so it is
opt-in: set QICAS_RECOMPILE=1 (RUN_GUIDE.md). The SHA-256 pin and the compiler check always run."""
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "chain" / "build"
V1_SHA256 = "06311ec83c92baf21e5b18ada4c7faf35e76863e129c897d26635ac999bac02f"   # unchanged since e960f39
COMPILER = "0.8.24+commit.e11b9ed9.Emscripten.clang"


def test_v1_artifact_is_byte_identical():
    assert hashlib.sha256((BUILD / "CarbonScheduleMarket.json").read_bytes()).hexdigest() == V1_SHA256


def test_artifacts_record_the_pinned_compiler():
    for p in sorted(BUILD.glob("*.json")):
        art = json.loads(p.read_text())
        assert art["compiler"] == COMPILER, p.name
        assert art["contractName"] == p.stem
        assert art["bytecode"].startswith("0x") and art["abi"]


def _toolchain():
    node = shutil.which("node")
    if node is None or not (ROOT / "chain" / "node_modules" / "solc").is_dir():
        return None
    return node


@pytest.mark.skipif(os.environ.get("QICAS_RECOMPILE") != "1", reason="opt-in: set QICAS_RECOMPILE=1 (~1 min)")
@pytest.mark.skipif(_toolchain() is None, reason="Node.js or chain/node_modules/solc missing (npm install in chain/)")
def test_recompile_reproduces_every_artifact():
    r = subprocess.run([_toolchain(), str(ROOT / "chain" / "compile.js"), "--check"], cwd=ROOT,
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    for p in sorted(BUILD.glob("*.json")):
        assert f"{p.stem}: IDENTICAL" in r.stdout, r.stdout
