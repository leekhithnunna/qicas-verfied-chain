r"""Build the university-report pack: report_pack/ + report_pack.zip (both git-ignored).

    .\.venv\Scripts\python.exe scripts\make_report_pack.py [--screenshots]

Run after: pytest, demo.run_demo, demo.make_figures, experiments.run_all --profile lite (+ E6 on Besu),
experiments.figures, experiments.onchain_market, experiments.trust_layer, experiments.real_snapshot.

Contents (docs/FINAL_REPORT.md §"Report pack"):
  docs/        FINAL_REPORT, README, RUN_GUIDE, PROJECT_PLAN, DATA_SOURCES, QUANTUM_NOTES, CASE_STUDY_PAPERS, plans/*
  figures/     every evaluation / phase figure as PNG       diagrams/  7 architecture + flow diagrams (PNG)
  tables/      summary tables as CSV (+ the run manifests)   key_numbers.json  headline numbers (value, unit, source)
  repo_overview.md  file tree, tests, requirements, hardware, reproduce commands
  screenshots/ dashboard screenshots (only with --screenshots; headless Chrome/Edge)
Never copied: data/ (raw or processed), per-hour Electricity Maps values, API keys, private keys.
"""
from __future__ import annotations

import argparse
import csv
import json
import platform

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "report_pack"
ZIP = ROOT / "report_pack.zip"
PY = sys.executable

DOCS = ["docs/FINAL_REPORT.md", "README.md", "RUN_GUIDE.md", "docs/PROJECT_PLAN.md", "docs/DATA_SOURCES.md",
        "docs/QUANTUM_NOTES.md", "docs/CASE_STUDY_PAPERS.md", "docs/CASE_STUDY_REPORT.md"]
FIGURE_DIRS = {"results/eval/figures": "eval", "results/figures": "case_study", "results/quantum": "phase2_quantum"}
TABLES = {  # pack name -> source (relative to the repo root)
    "E1_sensitivity.csv": "results/eval/sensitivity.csv", "E1_breakeven.csv": "results/eval/breakeven.csv",
    "E1_tradeoff_market_rounds.csv": "results/eval/tradeoff.csv",
    "E1_poa_node_term.csv": "results/eval/poa_node_term.csv",
    "E2_gas_scaling.csv": "results/eval/gas_scaling.csv", "E2_gas_fit.csv": "results/eval/gas_fit.csv",
    "E3_attacks.csv": "results/eval/attacks.csv",
    "E4_solvers_summary.csv": "results/eval/solvers_summary.csv",
    "E4_classical_vs_qi.csv": "results/eval/classical_vs_qi.csv", "E4_solvers_raw.csv": "results/eval/solvers.csv",
    "E5_quantum_summary.csv": "results/eval/quantum_summary.csv",
    "E5_quantum_classical_vs.csv": "results/eval/quantum_classical_vs.csv",
    "E5_quantum_market.csv": "results/eval/quantum_market.csv",
    "E6_besu_vs_memory.csv": "results/eval/besu_vs_memory.csv",
    "E6_besu_vs_memory_summary.csv": "results/eval/besu_vs_memory_summary.csv",
    "not_run.csv": "results/eval/not_run.csv",
    "phase3_market_rounds.csv": "results/onchain_market/rounds.csv",
    "phase3_market_gas.csv": "results/onchain_market/gas.csv",
    "phase4_trust_gas.csv": "results/trust/gas.csv", "phase4_trust_attacks.csv": "results/trust/attacks.csv",
    "phase1_real_attribution.csv": "results/real_snapshot/attribution.csv",
    "phase2_quantum_summary_by_size.csv": "results/quantum/summary_by_size.csv",
    "manifest_eval.json": "results/eval/manifest.json", "manifest_quantum.json": "results/quantum/manifest.json",
    "summary_onchain_market.json": "results/onchain_market/summary.json",
    "summary_trust.json": "results/trust/summary.json", "summary_real_snapshot.json": "results/real_snapshot/summary.json",
}
sys.path.insert(0, str(ROOT))
from tests.test_repo_hygiene import KEY_PATTERNS as SECRET_PATTERNS  # noqa: E402  same rules as the repo scan


def known_test_keys() -> list[str]:
    """The deterministic TEST private keys of this repo (Besu validators/accounts, oracle signers): none may appear
    in the pack (hashes and Merkle roots look the same, so the check is by value, not by shape)."""
    sys.path.insert(0, str(ROOT))
    from chain.besu.generate import account_key, validator_key
    from oracle.signer import make_signers
    keys = [validator_key(i) for i in range(1, 5)] + [account_key(j) for j in range(10)]
    keys += [s.key for s in make_signers(5)]
    return [bytes(k).hex().lower() for k in keys]


def rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def read_csv(p: Path) -> list[dict[str, str]]:
    with p.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def sh(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=120).stdout.strip()
    except Exception as exc:                                     # pragma: no cover - environment-specific
        return f"n/a ({exc.__class__.__name__})"


# ------------------------------------------------------------------------------------------- key numbers
def key_numbers() -> dict[str, Any]:
    k: dict[str, Any] = {}

    def put(name, value, unit, source, note=""):
        k[name] = {"value": value, "unit": unit, "source": source, **({"note": note} if note else {})}

    demo = json.loads((ROOT / "results/demo_run.json").read_text(encoding="utf-8"))["final"]
    src = "results/demo_run.json (python -m demo.run_demo, seed 7)"
    put("demo_baseline_carbon", round(demo["baseline_carbon_g"], 1), "g CO2e", src)
    put("demo_winner_carbon", round(demo["best_carbon_g"], 1), "g CO2e", src, f"winner {demo['winner']}")
    put("demo_carbon_reduction", round(demo["reduction_pct"], 1), "%", src)
    put("demo_chain_overhead", round(demo["overhead_g"], 4), "g CO2e", src,
        "at 0.5 Wh/Mgas x 400 g/kWh [VERIFY] sensitivity parameters, not measured")
    put("demo_net_saving", round(demo["net_saving_g"], 1), "g CO2e", src)
    put("demo_credits_minted", demo["credits_minted"], "credits (1 = 1 g net)", src)
    put("demo_certified_gap", round(demo["certified_gap_pct"], 2), "% (upper bound)", src)

    rs = ROOT / "results/real_snapshot/summary.json"
    if rs.exists():
        r = json.loads(rs.read_text(encoding="utf-8"))
        s = "results/real_snapshot/summary.json (python -m experiments.real_snapshot)"
        p = r["pipeline"]
        put("real_baseline_carbon", round(p["baseline_carbon_g"], 1), "g CO2e", s, "D1: tasks x instance_num")
        put("real_winner_carbon", round(p["best_carbon_g"], 1), "g CO2e", s, f"winner {p['winner']}")
        put("real_carbon_reduction", round(p["reduction_pct"], 1), "%", s,
            "model output under an illustrative capacity rule, not an achievable cloud saving")
        put("real_certified_gap", round(p["certified_gap_pct"], 2), "% (upper bound)", s)
        put("real_credits_minted", p["credits_minted"], "credits", s)
        put("real_task_energy_D1", r["workload"]["total_task_energy_wh"], "Wh", s, "seed-7 sample, 38 tasks")
        put("real_task_energy_1wh_floor", r["workload_1wh_floor"]["total_task_energy_wh"], "Wh", s,
            "D1 option (c) sensitivity")
        floor = [c for c in r["sensitivity"] if "1 Wh floor" in str(c.get("regions", ""))]
        if floor:
            put("real_carbon_reduction_1wh_floor", round(floor[0]["carbon_reduction_pct"], 1), "%", s,
                f"winner {floor[0]['winner']}")
        put("snapshot_carbon_intensity", {x["name"]: x["ci_g_per_kwh"] for x in r["regions"]}, "g CO2e/kWh",
            "config/real_snapshot.yaml", "Electricity Maps (academic licence), direct basis, 2024-10-15T12:00Z")
        put("snapshot_price", {x["name"]: x["price_eur_per_mwh"] for x in r["regions"]}, "EUR/MWh",
            "config/real_snapshot.yaml", "ENTSO-E, Electricity Maps API (PJM), IEX India; ECB FX 2024-10-15")

    ev = ROOT / "results/eval"
    if (ev / "sensitivity.csv").exists():
        rows = [x for x in read_csv(ev / "sensitivity.csv") if x["status"] == "ok"]
        net = [float(x["net_saving_g"]) for x in rows]
        pct = [float(x["overhead_pct_of_gross"]) for x in rows if x.get("overhead_pct_of_gross")]
        put("E1_net_saving_range", [round(min(net), 1), round(max(net), 1)], "g CO2e per epoch",
            "results/eval/sensitivity.csv", "range over the [VERIFY] grid x instance sizes x overhead terms")
        if pct:
            put("E1_overhead_share_range", [round(min(pct), 4), round(max(pct), 1)], "% of gross saving",
                "results/eval/sensitivity.csv", "[VERIFY] grid")
    if (ev / "poa_node_term.csv").exists():
        rows = [x for x in read_csv(ev / "poa_node_term.csv") if x["status"] == "ok"]
        node = [float(x["node_term_g"]) for x in rows]
        put("E1_poa_node_term_range", [round(min(node), 3), round(max(node), 1)], "g CO2e per epoch",
            "results/eval/poa_node_term.csv", "4 validators x 5-200 W x 0.01-24 h x 40-700 g/kWh [VERIFY]")
    if (ev / "gas_fit.csv").exists():
        put("E2_gas_fit", {f"{x.get('function')} [{x.get('model')}]": {
            c: x.get(c) for c in ("a", "b", "c", "r2", "max_measured_tasks", "largest_measured_tasks_under_demo_cap",
                                  "extrapolated_tasks_at_reference") if x.get(c) not in (None, "")}
                           for x in read_csv(ev / "gas_fit.csv") if x.get("status") == "ok"}, "gas",
            "results/eval/gas_fit.csv", "gas ~ a + b*n + c*edges (numpy polyfit), in-memory chain")
    if (ev / "attacks.csv").exists():
        rows = read_csv(ev / "attacks.csv")
        st: dict[str, int] = {}
        for x in rows:
            st[x["status"]] = st.get(x["status"], 0) + 1
        put("E3_attack_rows_by_status", st, "rows", "results/eval/attacks.csv")
    if (ev / "solvers_summary.csv").exists():
        rows = [x for x in read_csv(ev / "solvers_summary.csv") if x["status"] == "ok"]
        out: dict[str, dict] = {}
        for x in rows:
            out.setdefault(x["dataset"], {}).setdefault(x["preset"], {})[f"{x['solver']} ({x['budget']})"] = {
                "label": x["label"], "gap_pct_mean": round(float(x["gap_pct_mean"]), 2),
                "ci95": [round(float(x["gap_pct_ci_lo"]), 2), round(float(x["gap_pct_ci_hi"]), 2)]}
        put("E4_certified_gap", out, "% (mean, 95 % bootstrap CI)", "results/eval/solvers_summary.csv")
    if (ev / "classical_vs_qi.csv").exists():
        rows = [x for x in read_csv(ev / "classical_vs_qi.csv") if x["status"] == "ok"]
        put("E4_classical_matches_or_beats_sqa", {
            "count": sum(x["classical_matches_or_beats"] == "True" for x in rows), "of": len(rows)},
            "comparisons", "results/eval/classical_vs_qi.csv", "CI of (classical - SQA) gap includes or is below 0")
    if (ev / "quantum_summary.csv").exists():
        rows = [x for x in read_csv(ev / "quantum_summary.csv") if x["status"] == "ok"]
        put("E5_p_opt", {f"{x['method']} @ {x['budget']}": {"label": x["label"], "p_opt": round(float(x["p_opt"]), 3)}
                         for x in rows}, "probability", "results/eval/quantum_summary.csv (from results/quantum/)",
            "QAOA classically simulated; *_ideal = optimistic upper bound")
    if (ev / "besu_vs_memory.csv").exists():
        rows = [x for x in read_csv(ev / "besu_vs_memory.csv") if x["status"] == "ok"]
        if rows:
            put("E6_rows", len(rows), "function x chain rows", "results/eval/besu_vs_memory.csv")
    bs = ROOT / "results/eval/besu_vs_memory_summary.csv"
    if bs.exists():
        put("E6_flows", {f"{x['flow']}/{x['chain']}": {"gas_total": int(x["gas_total"]),
                                                      "wall_s": round(float(x["wall_s"]), 1),
                                                      "block_period_s": round(float(x["block_period_s"]), 2)}
                         for x in read_csv(bs) if x["status"] == "ok"}, "gas / s",
            "results/eval/besu_vs_memory_summary.csv")
    for name, f in (("phase3_market", "results/onchain_market/summary.json"), ("phase4_trust", "results/trust/summary.json")):
        p = ROOT / f
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            put(f"{name}_gas", d["gas"], "gas", f)
    if (ev / "not_run.csv").exists():
        put("not_run_rows", [f"{x['experiment']}: {x['status']}" for x in read_csv(ev / "not_run.csv")], "rows",
            "results/eval/not_run.csv")
    return k


# ------------------------------------------------------------------------------------------- repo overview
DESCRIPTIONS = {
    "core/instance.py": "instance model; synthetic generator; real-workload builder (D1 instance_num scaling)",
    "core/scoring.py": "evaluate() score/carbon/cost/feasibility (== contract evaluate); round-robin baseline",
    "core/merkle.py": "Merkle root + proofs of the winning schedule (== merkleRootOf)",
    "core/market.py": "Lagrangian dual-price market (float), lower bound",
    "core/market_int.py": "integer mirror of PriceMarket.sol (Phase 3/4 parity)",
    "core/oracle_math.py": "lower-median / quorum rules of CarbonOracle (Phase 4 parity)",
    "core/certificate.py": "certificate metadata JSON + tokenURI (== ScheduleCertificate)",
    "core/solvers/": "greedy, SA (classical); SQA (quantum-inspired)",
    "core/subproblem/": "Phase 2: exact, SA, SQA, SB (quantum-inspired), QAOA-XY (simulated), QUBO",
    "core/data/": "Phase 1 loaders: Alibaba trace, carbon, prices, snapshot checks (stdlib only)",
    "chain/contracts/CarbonScheduleMarket.sol": "V1: commit-reveal, on-chain re-scoring, slashing, Merkle root, credits",
    "chain/contracts/CarbonScheduleMarketV2.sol": "V2: V1 + region carbon read from CarbonOracle",
    "chain/contracts/CarbonScheduleMarketV3.sol": "V3: V2 + ERC-20 credit + soulbound certificate minting",
    "chain/contracts/PriceMarket.sol": "on-chain dual-price rounds, certified lower bound, fraud proofs",
    "chain/contracts/CarbonOracle.sol": "EIP-712 signed carbon reports, bonds, quorum, lower median, equivocation slash",
    "chain/contracts/QicasCredit.sol": "ERC-20 credits (decimals 0), MINTER_ROLE, retire",
    "chain/contracts/ScheduleCertificate.sol": "soulbound ERC-721 certificate with on-chain tokenURI",
    "chain/client.py": "web3 client (memory | rpc | besu), commit hash, gas log",
    "chain/besu/": "Besu QBFT genesis, TEST-ONLY keys, docker-compose, status/vote tools",
    "oracle/signer.py": "EIP-712 CarbonReport signing (deterministic TEST keys)",
    "demo/pipeline.py": "7-step case-study scenario", "demo/pipeline_v3.py": "Phase 5 token flow",
    "experiments/run_all.py": "evaluation harness E1-E6 + manifest", "experiments/figures.py": "fig5-fig11",
    "experiments/quantum_benchmark.py": "Phase 2 fair sub-problem benchmark",
    "app/dashboard.py": "Streamlit dashboard (tabs in app/tabs/)",
}


def tree() -> str:
    files = sh(["git", "ls-files"]).splitlines()
    dirs: dict[str, int] = {}
    for f in files:
        top = "/".join(f.split("/")[:2]) if "/" in f else f
        dirs[top] = dirs.get(top, 0) + 1
    lines = [f"{d:<52} {n:>4} file(s)" for d, n in sorted(dirs.items())]
    return "\n".join(lines)


def tests_table() -> tuple[str, int]:
    out = sh([PY, "-m", "pytest", "--collect-only", "-q"])
    per: dict[str, int] = {}
    for ln in out.splitlines():
        if "::" in ln:
            f = ln.split("::")[0]
            per[f] = per.get(f, 0) + 1
    total = sum(per.values())
    rows = "\n".join(f"| `{f}` | {n} |" for f, n in sorted(per.items()))
    return f"| Test file | Tests collected |\n|---|---|\n{rows}\n| **total** | **{total}** |", total


def hardware() -> dict[str, str]:
    ps = lambda c: sh(["powershell", "-NoProfile", "-Command", c])  # noqa: E731
    return {"os": platform.platform(),
            "cpu": ps("(Get-CimInstance Win32_Processor | Select-Object -First 1).Name"),
            "cores_logical": ps("(Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors"),
            "ram_gb": ps("[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB,1)")}


def repo_overview() -> str:
    man = json.loads((ROOT / "results/eval/manifest.json").read_text(encoding="utf-8"))
    env = man.get("environment", {})
    hw = hardware()
    tt, total = tests_table()
    desc = "\n".join(f"| `{k}` | {v} |" for k, v in DESCRIPTIONS.items())
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    cmds = claude.split("## Commands (PowerShell, repo root)")[1].split("## Hard rules")[0].strip()
    return f"""# QICAS-Chain — repository overview (Team 07)

Generated by `scripts/make_report_pack.py` at commit `{sh(['git', 'rev-parse', '--short', 'HEAD'])}`.

## Main modules and contracts

| Path | What it does |
|---|---|
{desc}

## File tree (tracked files per folder)

```
{tree()}
```

## Tests

{tt}

Default `pytest -q` is offline and deterministic; 6 tests are opt-in skips (`QICAS_RECOMPILE=1` recompile check;
`QICAS_BESU=1` Besu tests, `QICAS_BESU_VOTE=1` validator vote test).

## Software

| Component | Version |
|---|---|
| Python | {env.get('python', platform.python_version())} |
| numpy / pandas / pyyaml | {env.get('numpy')} / {env.get('pandas')} / {env.get('pyyaml')} |
| web3 / eth-tester / py-evm | {env.get('web3')} / {env.get('eth-tester')} / {env.get('py-evm')} |
| matplotlib / streamlit | {env.get('matplotlib')} / {env.get('streamlit')} |
| Node.js | {sh(['node', '--version'])} |
| solc (solc-js) | 0.8.24 (`chain/package.json`; evm `paris`, viaIR, 200 runs) |
| OpenZeppelin Contracts | 5.4.0 (vendored, `chain/vendor/openzeppelin`) |
| Docker | {sh(['docker', 'version', '--format', '{{.Server.Version}}'])} |
| Hyperledger Besu | 26.10.2 (`hyperledger/besu@sha256:bc599f5e…a2c7`) |
| Full list | `requirements.txt` |

## Hardware used for the reported runs

| Item | Value |
|---|---|
| OS | {hw['os']} |
| CPU | {hw['cpu']} ({hw['cores_logical']} logical cores) |
| RAM | {hw['ram_gb']} GB |

## Reproduce everything (PowerShell, repo root; `$env:PYTHONIOENCODING='utf-8'`)

{cmds}

Report pack: `.\\.venv\\Scripts\\python.exe scripts\\make_report_pack.py --screenshots` (after the runs above).
"""


def real_snapshot_inputs() -> list[dict[str, Any]]:
    import yaml
    cfg = yaml.safe_load((ROOT / "config/real_snapshot.yaml").read_text(encoding="utf-8"))
    usd = float(cfg["snapshot"]["fx"]["usd_per_eur"])
    zones = {"eu-north-1 (Stockholm)": ("SE-SE3", "ENTSO-E SE3"), "eu-west-1 (Ireland)": ("IE", "ENTSO-E IE(SEM)"),
             "us-east-1 (Virginia)": ("US-MIDA-PJM", "Electricity Maps API (PJM day-ahead)"),
             "ap-south-1 (Mumbai)": ("IN-WE", "IEX India DAM (all-India MCP)")}
    return [{"region": r["name"], "carbon_zone": zones[r["name"]][0], "ci_g_per_kwh": r["ci_g_per_kwh"],
             "carbon_source": "Electricity Maps (2026), 2024 hourly, direct basis, academic licence",
             "price_uusd_per_kwh": r["price_uusd_per_kwh"],
             "price_eur_per_mwh": round(r["price_uusd_per_kwh"] / 1000 / usd, 2), "price_source": zones[r["name"]][1],
             "capacity_share": r["capacity_share"], "hour_utc": cfg["snapshot"]["hour"]} for r in cfg["regions"]]


# ------------------------------------------------------------------------------------------- screenshots
def _cdp_capture(browser: str, url: str, png: Path, width: int, height: int, wait_s: float) -> bool:
    """Open `url` in headless Chrome/Edge via the DevTools protocol, wait in real time until Streamlit has finished
    running the script (no 'stale'/'running' status widget), then capture the full page as PNG."""
    import asyncio
    import base64
    import time
    import urllib.request

    import websockets

    port = 9333
    prof = PACK / ".chrome-profile"
    proc = subprocess.Popen([browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                             f"--remote-debugging-port={port}", "--remote-allow-origins=*",
                             f"--user-data-dir={prof}", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws_url = None
        for _ in range(60):
            try:
                tabs = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2).read())
                ws_url = next(t["webSocketDebuggerUrl"] for t in tabs if t.get("type") == "page")
                break
            except Exception:
                time.sleep(0.5)
        if not ws_url:
            return False

        async def run() -> bytes:
            async with websockets.connect(ws_url, max_size=None) as ws:
                n = 0

                async def call(method, **params):
                    nonlocal n
                    n += 1
                    await ws.send(json.dumps({"id": n, "method": method, "params": params}))
                    while True:
                        msg = json.loads(await ws.recv())
                        if msg.get("id") == n:
                            return msg.get("result", {})

                await call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1,
                           mobile=False)
                await call("Page.navigate", url=url)
                t0 = time.time()
                await asyncio.sleep(4)
                js = ("!!document.querySelector('[data-testid=\"stApp\"]') && "
                      "!document.querySelector('[data-testid=\"stStatusWidget\"]') && "
                      "!document.querySelector('[data-testid=\"stSpinner\"]') && "
                      "!document.querySelector('[data-stale=\"true\"]')")
                quiet = 0
                while time.time() - t0 < wait_s:
                    r = await call("Runtime.evaluate", expression=js, returnByValue=True)
                    quiet = quiet + 1 if r.get("result", {}).get("value") else 0
                    if quiet >= 3:                         # idle for ~3 s
                        break
                    await asyncio.sleep(1)
                await asyncio.sleep(2)                     # charts finish their transitions
                shot = await call("Page.captureScreenshot", format="png", captureBeyondViewport=False)
                return base64.b64decode(shot["data"])

        png.write_bytes(asyncio.run(run()))
        return png.stat().st_size > 20000
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        shutil.rmtree(prof, ignore_errors=True)


def screenshots(out: Path) -> list[str]:
    import time
    import urllib.request
    browser = next((b for b in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe") if Path(b).exists()), None)
    if not browser:
        return ["skipped: no Chrome/Edge found"]
    out.mkdir(parents=True, exist_ok=True)
    port = 8599
    proc = subprocess.Popen([PY, "-m", "streamlit", "run", str(ROOT / "scripts" / "screenshot_app.py"),
                             "--server.headless", "true", "--server.port", str(port), "--browser.gatherUsageStats",
                             "false", "--theme.base", "light"], cwd=ROOT, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    done = []
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=2)
                break
            except Exception:
                time.sleep(1)
        for view, h in (("overview", 1500), ("evaluation", 2000), ("market", 1900), ("oracle", 1700),
                        ("tokens", 2200)):
            png = out / f"dashboard_{view}.png"
            ok = _cdp_capture(browser, f"http://127.0.0.1:{port}/?view={view}", png, 1400, h, wait_s=120)
            done.append(png.name if ok else f"{view}: failed")
    finally:
        proc.terminate()
    return done


# ------------------------------------------------------------------------------------------- build
def build(with_screens: bool) -> Path:
    if PACK.exists():
        shutil.rmtree(PACK)
    (PACK / "docs" / "plans").mkdir(parents=True)
    for d in DOCS:
        if (ROOT / d).exists():
            shutil.copy2(ROOT / d, PACK / "docs" / Path(d).name)
    for p in sorted((ROOT / "docs" / "plans").glob("*.md")):
        shutil.copy2(p, PACK / "docs" / "plans" / p.name)
    for src, name in FIGURE_DIRS.items():
        for p in sorted((ROOT / src).glob("*.png")):
            (PACK / "figures" / name).mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, PACK / "figures" / name / p.name)
    sys.path.insert(0, str(ROOT / "scripts"))
    import report_diagrams
    report_diagrams.make_all(PACK / "diagrams")
    (PACK / "tables").mkdir()
    missing = []
    for name, src in TABLES.items():
        if (ROOT / src).exists():
            shutil.copy2(ROOT / src, PACK / "tables" / name)
        else:
            missing.append(src)
    rows = real_snapshot_inputs()
    with (PACK / "tables" / "phase1_real_snapshot_inputs.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    kn = key_numbers()
    (PACK / "key_numbers.json").write_text(json.dumps(kn, indent=2), encoding="utf-8")
    (PACK / "repo_overview.md").write_text(repo_overview(), encoding="utf-8")
    shots = screenshots(PACK / "screenshots") if with_screens else ["skipped (run with --screenshots)"]
    # safety: nothing from data/, no secrets
    bad, test_keys = [], known_test_keys()
    for p in PACK.rglob("*"):
        if p.is_file() and p.suffix in (".md", ".csv", ".json", ".txt"):
            t = p.read_text(encoding="utf-8", errors="ignore")
            bad += [f"{rel(p)}: {pat.pattern}" for pat in SECRET_PATTERNS if pat.search(t)]
            bad += [f"{rel(p)}: TEST private key" for k in test_keys if k in t.lower()]
    (PACK / "PACK_INFO.txt").write_text(
        "QICAS-Chain report pack (Team 07). Generated by scripts/make_report_pack.py at commit "
        f"{sh(['git', 'rev-parse', '--short', 'HEAD'])}.\nNo raw data, no per-hour Electricity Maps values, "
        "no API keys, no private keys. Electricity Maps data used under an academic licence: cite "
        "'Electricity Maps (2026), https://www.electricitymaps.com'.\n"
        f"Missing optional inputs: {missing or 'none'}\nScreenshots: {shots}\nSecret scan hits: {bad or 'none'}\n",
        encoding="utf-8")
    if bad:
        raise SystemExit(f"secret-like strings found, pack NOT zipped: {bad}")
    if ZIP.exists():
        ZIP.unlink()
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(PACK.rglob("*")):
            if p.is_file():
                z.write(p, Path("report_pack") / p.relative_to(PACK))
    print(f"missing optional inputs: {missing or 'none'}")
    print(f"screenshots: {shots}")
    print(f"files: {sum(1 for p in PACK.rglob('*') if p.is_file())}")
    print(f"{ZIP}  {ZIP.stat().st_size:,} bytes")
    return ZIP


def main(argv=None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--screenshots", action="store_true", help="capture dashboard PNGs with headless Chrome/Edge")
    build(ap.parse_args(argv).screenshots)


if __name__ == "__main__":
    main()
