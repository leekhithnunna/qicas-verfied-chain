# CLAUDE.md — QICAS-Chain (Team 07)

**Purpose:** verifiable, quantum-inspired, carbon-aware scheduling of cloud workflows on blockchain.
Off-chain solvers place DAG workflow tasks across regions; a smart contract re-scores, verifies and
certifies the schedule. Follow `AGENTS.md` strictly. `README.md` is the system map.

## Commands (PowerShell, repo root)
```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q                 # expect: 152 passed, 6 skipped (opt-in recompile + 5 opt-in Besu)
.\.venv\Scripts\python.exe -m demo.run_demo             # seed-7 output must match RUN_GUIDE.md
.\.venv\Scripts\python.exe -m demo.make_figures         # -> results/figures/
.\.venv\Scripts\python.exe -m streamlit run app/dashboard.py
.\.venv\Scripts\python.exe -m experiments.run_all --profile lite   # Phase 6 E1-E6 -> results/eval/ (E6: QICAS_BESU=1 + Besu up)
.\.venv\Scripts\python.exe -m experiments.figures                  # fig5-fig11 (+ fig8r/fig9r real) -> results/eval/figures/
.\.venv\Scripts\python.exe -m experiments.onchain_market           # Phase 3 on-chain rounds -> results/onchain_market/
.\.venv\Scripts\python.exe -m experiments.trust_layer              # Phase 4 oracle + fraud proofs -> results/trust/
.\.venv\Scripts\python.exe scripts\load_alibaba_dags.py   # Phase 1: local Alibaba extract -> data/processed/ (~3 min)
.\.venv\Scripts\python.exe scripts\build_real_snapshot.py # Phase 1: recompute + check config/real_snapshot.yaml
.\.venv\Scripts\python.exe -m experiments.real_snapshot           # Phase 1 real snapshot -> results/real_snapshot/
node chain/compile.js --check                                      # Node 20; recompile check (README §9.3 B), 7 contracts
powershell -ExecutionPolicy Bypass -File scripts\besu_up.ps1       # Phase 5: Besu QBFT (Docker); besu_down.ps1 [-Reset]
.\.venv\Scripts\python.exe -m demo.run_demo --mode besu            # Phase 5: demo on Besu (same output, other address)
$env:QICAS_BESU='1'; .\.venv\Scripts\python.exe -m pytest -q -m besu   # Phase 5 opt-in tests (QICAS_BESU_VOTE=1: vote test)
.\.venv\Scripts\python.exe -m experiments.besu_vs_memory           # Phase 5 E6 -> results/besu/
.\.venv\Scripts\python.exe scripts\make_snapshot.py     # ZIP snapshot -> _snapshot/ (git-ignored)
.\.venv\Scripts\python.exe scripts\make_report_pack.py --screenshots  # report_pack/ + report_pack.zip (git-ignored)
```

## Hard rules (from AGENTS.md — never break)
1. Scoring parity: `core/scoring.py::evaluate` = `CarbonScheduleMarket.sol::evaluate` (also baseline,
   Merkle root, commit hash). `tests/test_parity.py` enforces it. Change both sides or neither.
2. `chain/build/CarbonScheduleMarket.json` is precompiled. Edit `.sol` → recompile (README §9.3) → pytest.
   Never hand-edit the JSON.
3. Integers only across the Python ↔ Solidity boundary (units: README §5).
4. `core/` never imports web3 or streamlit. Chain code in `chain/`, UI in `app/`.
5. Honest labels: greedy/SA classical; SQA/SB quantum-inspired; QAOA quantum (simulated). No
   "quantum advantage" claims.
6. Determinism: every solver takes `seed`; tests stay deterministic.
7. Never loosen a failing parity test — find the real mismatch.
8. Keep the default demo (`config/demo.yaml`) and all existing tests working in every phase; new
   features go behind new configs/flags/modules.
9. Dependencies: `core/` uses stdlib + numpy only; quantum SDKs only in `experiments/` behind a flag.

## Data rules (details: `docs/DATA_SOURCES.md`)
- `data/` is git-ignored and never committed (raw files, inbox, processed extracts). `tests/test_repo_hygiene.py`
  enforces it.
- Electricity Maps data (carbon B1–B4, PJM price C3) is used under an ACADEMIC licence: non-commercial, NO
  redistribution, always cite Electricity Maps. Never commit raw files or per-hour values.
- Never write an API key (Electricity Maps or any other) to a file, log, config, test or commit. If the API is
  needed, ask the user to set it in an environment variable for that session.
- Only derived snapshot inputs (one value per region, e.g. in `config/real_snapshot.yaml`) may be committed,
  each with its citation. The Alibaba extract stays local (no licence grants redistribution).
- Git: push only to `origin` (qicas-chain). Never push to `casestudy`. No force-push, no history rewrite.

## Folder map
```
config/      demo.yaml — all tunable parameters (default config: do not change behaviour)
             real_snapshot.yaml (Phase 1: 2024-10-15T12:00Z derived inputs + citations)
core/        pure Python: instance, scoring, merkle, market, solvers/ (greedy, sa, sqa)
             subproblem/ (Phase 2: exact, sa, sqa, sb, qaoa_xy, optim, qubo; not on demo path)
             market_int.py (Phase 3/4: integer mirror of PriceMarket.sol), oracle_math.py (Phase 4)
             data/ (Phase 1: alibaba, carbon, prices, snapshot loaders; stdlib only)
chain/       contracts/*.sol, build/*.json (precompiled), client.py (web3), hardhat/ (optional rpc)
             PriceMarket.sol + price_market.py (Phase 3/4), CarbonOracle.sol + oracle_client.py,
             CarbonScheduleMarketV2.sol + client_v2.py (Phase 4), compile.js + package.json (solc-js 0.8.24)
             Phase 5: QicasCredit.sol (ERC-20) + ScheduleCertificate.sol (soulbound ERC-721) + tokens.py,
             CarbonScheduleMarketV3.sol + client_v3.py, vendor/openzeppelin (OZ 5.4.0, offline compile),
             besu/ (QBFT genesis + TEST keys via generate.py, docker-compose, status.py, vote.py)
oracle/      signer.py (Phase 4: EIP-712 CarbonReport signing, deterministic TEST keys)
demo/        pipeline.py (7-step scenario), run_demo.py (CLI, --mode memory|rpc|besu), make_figures.py,
             pipeline_v3.py (Phase 5 token flow); config/besu.yaml = demo.yaml with chain.mode besu
app/         dashboard.py (Streamlit) + tabs/ (one module per tab; evaluation.py, onchain_market.py, oracle.py,
             tokens.py = Phase 6 tabs)
tests/       test_core, test_parity (Python=Solidity), test_demo (end-to-end), test_quantum (Phase 2),
             test_price_market (Phase 3 parity), test_artifacts (V1 artifact SHA-256 pin),
             test_trust_layer + test_parity_v2 + test_fraud_proofs (Phase 4),
             test_tokens + test_market_v3 + test_besu_config (Phase 5, offline), test_besu (opt-in QICAS_BESU=1)
experiments/ quantum_benchmark.py (Phase 2 fair comparison; config/quantum_bench.yaml -> results/quantum/)
             run_all.py + e1_e2_overhead_gas, e3_attacks, e4_solvers, figures (Phase 6; config/eval.yaml
             -> results/eval/); missing phases -> explicit "NOT RUN - Phase X missing" rows
             e5_quantum.py (E5: copies Phase 2 tables, not re-run)
             onchain_market.py (Phase 3; config/onchain_market.yaml -> results/onchain_market/)
             trust_layer.py (Phase 4 -> results/trust/), phase5_tokens.py (E3 rows), besu_vs_memory.py (E6)
scripts/     setup/run helpers, load_em_snapshot.py, make_snapshot.py, make_report_pack.py + report_diagrams.py +
             screenshot_app.py (report pack)
docs/        FINAL_REPORT.md (full project), PROJECT_PLAN.md, QUANTUM_NOTES.md, plans/, CASE_STUDY_PAPERS.md,
             CASE_STUDY_REPORT.md (unchanged), CASE_STUDY_REPORT_TEMPLATE.md
results/     generated outputs (git-ignored)   _snapshot/  snapshot ZIPs   report_pack/ + .zip (all git-ignored)
```

## Current phase
See **`docs/PROJECT_PLAN.md` → "Current phase"**. Case study, Phase 2 (quantum layer), Phase 6-lite
(evaluation on synthetic data), Phase 3 (on-chain price market), Phase 4 (trust layer), Phase 1 (real data,
snapshot 2024-10-15T12:00Z; D1: real tasks scaled by instance_num), Phase 5 (Besu QBFT + ERC-20 credits + soulbound
ERC-721) and full Phase 6 (E1-E6, docs/FINAL_REPORT.md; 2026-11-23) are DONE. Current phase: **Complete**.
Update that pointer if new work is planned.

## Definition of done
Work is done only when BOTH hold:
1. `.\.venv\Scripts\python.exe -m pytest -q` passes (all tests, no loosened assertions), AND
2. `.\.venv\Scripts\python.exe -m demo.run_demo` completes (default seed-7 output unchanged unless the
   change is intended and RUN_GUIDE.md is updated).
Commit only when asked; never push without explicit permission.
