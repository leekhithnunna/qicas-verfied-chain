# Run Guide

## Setup and Commands

Run these from the repository root in PowerShell. The verified environment is Python 3.12.15.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m demo.run_demo
.\.venv\Scripts\python.exe -m demo.make_figures
explorer results\figures
.\.venv\Scripts\python.exe -m streamlit run app/dashboard.py
```

Expected test result (2026-11-24, all phases done): `152 passed, 6 skipped` in ~3–4 min (per-file counts: `report_pack/repo_overview.md`). The 6 skips are opt-in: the recompile check (`$env:QICAS_RECOMPILE='1'`, needs Node.js 20 and `npm install` in `chain/`) and 5 Besu tests (`$env:QICAS_BESU='1'` with the network up → 4 pass; `$env:QICAS_BESU_VOTE='1'` adds the vote test). On a machine without the git-ignored `data/` folder, the Phase 1 tests that read the real files are skipped as well and the E4 real-data rows are `NOT RUN - data missing`; everything else, including the Phase 1 loaders on synthetic fixtures, still runs. `tests/test_eval_smoke.py` asserts the smoke profile runs in < 60 s (≈ 27 s on an idle laptop; do not run heavy jobs in parallel). The verified seed-7 CLI run printed these key lines (runtime and transaction address can vary):

```text
[5] reveal greedy                   -> accepted score=872,431,150
[5] reveal sa                       -> accepted score=758,638,650
[5] reveal sqa                      -> accepted score=730,160,300
[5] reveal dual-market              -> accepted score=709,208,800
[5] reveal attacker: over-capacity  -> rejected (capacity violated)
[5] reveal attacker: copycat        -> reverted (HashMismatch)
[5] reveal attacker: no-show        -> not revealed
[6] Winner: dual-market. Carbon 961.8 g -> 531.8 g (44.7% lower). Chain overhead ≈ 1.8681 g. NET saving 428.0 g; 428 credits minted. Certified gap ≤ 9.92%. Slashed from attackers: 3 ETH
[7] Merkle proof task 0 in region 2: True; tampered claim region 3: False
```

Optional local RPC mode (requires Node.js 18+; this path was not exercised during verification):

```powershell
Set-Location chain/hardhat
npm install
npx hardhat node
```

In a second terminal at the repository root:

```powershell
.\.venv\Scripts\python.exe -m demo.run_demo --mode rpc --rpc-url http://127.0.0.1:8545
```

For the dashboard's RPC option, choose `rpc` in the sidebar and enter `http://127.0.0.1:8545`.

Phase 2 quantum-layer benchmark (optional; not part of the demo, demo output above is unchanged):

```powershell
.\.venv\Scripts\python.exe -m experiments.quantum_benchmark --smoke   # ~2 s sanity run
.\.venv\Scripts\python.exe -m experiments.quantum_benchmark           # full fair comparison -> results\quantum\
```

The full run uses 4 worker processes by default (`workers:` in `config/quantum_bench.yaml`; lower it on a
low-memory machine — results do not depend on it). Method, results and honest claims: `docs/QUANTUM_NOTES.md`.

Phase 6 evaluation (optional; in-memory chain, E4 also on real data when `data/processed/` exists; E6 on Besu
with `$env:QICAS_BESU='1'` and the network up; demo output above is unchanged):

```powershell
.\.venv\Scripts\python.exe -m experiments.run_all --profile smoke   # ~15 s sanity run (also inside pytest)
.\.venv\Scripts\python.exe -m experiments.run_all --profile lite    # E1-E4 -> results\eval\ (see README §14 for runtime)
.\.venv\Scripts\python.exe -m experiments.figures                   # fig5-fig11 (+ fig8r/fig9r) -> results\eval\figures\
.\.venv\Scripts\python.exe scripts\make_report_pack.py --screenshots   # report_pack\ + report_pack.zip (git-ignored)
explorer results\eval
```

`--only E1,E3` runs a subset; `--out DIR` writes elsewhere. E4 uses up to 8 worker processes (results do not
depend on it). `results\eval\manifest.json` lists what ran, what is `NOT RUN - Phase X missing` and why, and the
output hashes; `results\eval\not_run.csv` lists every missing row. In the dashboard, open the **Evaluation** tab
(available before a demo run too). Method and results: README §14.

Phase 5 — Besu QBFT network + tokens (optional; needs Docker Desktop running; demo output above is unchanged):

```powershell
docker info --format '{{.ServerVersion}}'                            # engine must answer
docker pull hyperledger/besu:26.10.2                                 # once, ~320 MB (pinned; digest in chain/besu/README.md)
powershell -ExecutionPolicy Bypass -File scripts\besu_up.ps1         # 4 validators; waits for blocks (~20 s)
.\.venv\Scripts\python.exe -m demo.run_demo --mode besu              # same seed-7 output as above (~40 s; only the address differs)
$env:QICAS_BESU='1'; .\.venv\Scripts\python.exe -m pytest -q -m besu # opt-in Besu tests (add $env:QICAS_BESU_VOTE='1' for the vote test)
.\.venv\Scripts\python.exe -m experiments.besu_vs_memory             # E6: gas, confirmation time, blocks -> results\besu\
.\.venv\Scripts\python.exe -m chain.besu.vote                        # optional: vote a 5th validator in and out
powershell -ExecutionPolicy Bypass -File scripts\besu_down.ps1       # stop (-Reset also wipes chain data)
```

On Besu the `[3]` line shows a different contract address (deterministic TEST accounts); every other line equals
the seed-7 output above. Token flow (ERC-20 credits + soulbound certificate, `CarbonScheduleMarketV3`) and E3
Phase 5 attacks run in the default pytest on the in-memory chain. `node chain/compile.js --check` must print
IDENTICAL for all 7 contracts. Details: README §18, `chain/besu/README.md`.

## Five-Minute Presentation

1. **0:00–0:40 — Start the story.** Click **Run full demo**. Explain that the demo places connected workflow tasks across four regions with different illustrative carbon, price, and capacity values.
2. **0:40–1:30 — Compare solvers.** Open **Solvers**. Point out that greedy and simulated annealing are classical, while SQA is quantum-inspired and runs on a classical computer. Use **Compare weights** to show winner carbon and cost under carbon-priority, balanced, and cost-priority settings.
3. **1:30–2:10 — Show the market.** Open **Dual-price market**. Describe the feasible upper bound, Lagrangian lower bound, and how regional prices rise with demand.
4. **2:10–3:15 — Show verification.** Open **On-chain**. Walk through honest reveals and the rejected over-capacity, reverted copycat, and unrevealed no-show cases; point out the slashed stake and transaction gas.
5. **3:15–4:00 — Verify a placement.** Open **Merkle proof**. Show that the selected task placement verifies, then change the claimed region and show the claim fails.
6. **4:00–5:00 — Close with evidence and limits.** Return to the summary metrics and mention the net carbon saving and certified gap. State that the region inputs and workload are illustrative/synthetic, the carbon-data oracle is trusted, overhead is estimated, SQA is not quantum hardware or quantum advantage, and the market is off-chain in this demo.
Phase 3 on-chain price market (optional; separate `PriceMarket` contract, demo output above is unchanged):

```powershell
.\.venv\Scripts\python.exe -m experiments.onchain_market               # seed 7, 25 rounds -> results\onchain_market\ (~16 s)
.\.venv\Scripts\python.exe -m experiments.onchain_market --rounds 3    # quick run
```

Expected key lines (seed 7):

```text
[onchain-market] LB (on-chain, int) 638,827,725 vs float 638,827,640; UB 709,208,800; certified gap 992 bps
[onchain-market] gas: openMarket 2,542,189; per round 980,133 (submit 711,435 + close 268,698); 25 rounds total 27,045,516
```

Recompiling contracts (only after editing a `.sol` file; Node.js 20, README §9.3 option B):

```powershell
Set-Location chain; npm install; Set-Location ..
node chain/compile.js --check     # must print IDENTICAL for every contract
```

(The gas line above is with Phase 4's `PriceMarket`, whose `closeRound` also stores a λ hash; Phase 3 measured
957,016 per round.)

Phase 4 trust layer (optional; oracle + fraud proofs, demo output above is unchanged):

```powershell
.\.venv\Scripts\python.exe -m experiments.trust_layer     # seed 7 -> results\trust\ (~20 s)
```

Expected key lines (seed 7):

```text
[trust] oracle: 20 reports, submitReports 908,709 gas; finalised LB 638,827,725 (round 20); finalizedGapBps 992 (certifiedGapBps 992)
[trust] gas: trust layer per epoch 1,472,845 (claimBound 74,895, finalizeBound 122,484); challenge mean 128,426
[trust] attacks: 6/6 defended; wrote results\trust (...)
```

Phase 1 real data (optional; snapshot 2024-10-15T12:00Z; demo output above is unchanged). Raw files live in the
git-ignored `data/raw/` (names, licences and SHA-256s: `docs/DATA_SOURCES.md`; Electricity Maps data is used under an
academic licence and is never committed):

```powershell
.\.venv\Scripts\python.exe scripts\load_alibaba_dags.py                         # local Alibaba extract -> data\processed\ (~3 min)
.\.venv\Scripts\python.exe scripts\build_real_snapshot.py                       # recompute snapshot inputs, check config
.\.venv\Scripts\python.exe -m demo.run_demo --config config/real_snapshot.yaml  # 7-step demo on real data
.\.venv\Scripts\python.exe -m experiments.real_snapshot                         # -> results\real_snapshot\ (~10 s)
```

Expected key lines:

```text
committed config region values match the raw data
[1] Instance: 38 tasks in 8 DAG workflows, 30 data edges, 4 regions; hash 0x9851299643aba5c4…
[6] Winner: dual-market. Carbon 187.0 g -> 6.5 g (96.5% lower). Chain overhead ≈ 1.7778 g. NET saving 178.7 g; 178 credits minted. Certified gap ≤ 36.42%. Slashed from attackers: 3 ETH
[real] snapshot 2024-10-15T12:00:00Z: eu-north-1 1 g/kWh 28.13 EUR/MWh, eu-west-1 179 g/kWh 88.5 EUR/MWh, us-east-1 320 g/kWh 32.28 EUR/MWh, ap-south-1 642 g/kWh 43.27 EUR/MWh
```

Without `data/processed/`, `experiments.real_snapshot` prints `NOT RUN - data missing` and the E4 real-data rows of
`experiments.run_all` are `NOT RUN - data missing`. Read the results with README §17. Since decision D1
(2026-11-23) a real task is all its instances (`workload.task_size: instance_num` in `config/real_snapshot.yaml`:
cores and energy × `instance_num`); the earlier "1 Wh floor" (option (c)) is kept as a sensitivity row in
`experiments.real_snapshot` and as the E4 dataset `real, 1 Wh floor (D1 sensitivity, option (c))`.
