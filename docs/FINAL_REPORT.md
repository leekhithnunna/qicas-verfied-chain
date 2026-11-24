# QICAS-Chain — Final Report

**Verifiable, Quantum-Inspired, Carbon-Aware Scheduling of Cloud Workflows on Blockchain**

Team 07 · 23CSE335 Blockchain and its Applications · Semester VII · Amrita School of Computing, Bengaluru ·
Faculty: Dr. Beena B M
Members: Leekhith Nunna (BL.EN.U4AIE23060), K. S. G. Yeseswini (BL.EN.U4AIE23013), Mukkheshh V (BL.EN.U4AIE23036)

Status: all phases done (case study, Phases 1–5, full Phase 6), 2026-11-23. The case-study report
(`docs/CASE_STUDY_REPORT.md`) is unchanged; this document covers the full project. **Every number below comes from a
file under `results/` and is listed with its source in `report_pack/key_numbers.json`** (`scripts/make_report_pack.py`);
the evaluation run is described by `results/eval/manifest.json` (git commit, config + data SHA-256s, seeds, package
versions, output hashes).

## Results at a glance

| Question | Answer (with its assumptions) | Source |
|---|---|---|
| Does on-chain verification work end to end? | Yes. Seed-7 demo: 4 honest reveals accepted, the over-capacity, copycat and no-show attackers rejected / reverted / slashed; carbon **961.8 → 531.8 g (−44.7 %)** vs the contract's own baseline; **428 credits**; certified gap **≤ 9.92 %**. Identical outcome on Besu QBFT. | `results/demo_run.json`, `results/eval/besu_vs_memory*.csv` |
| Is the net saving positive after the chain's own footprint? | **Only as a range.** Over the [VERIFY] grid the overhead is 0.0005 %–80,000 % of the gross saving for the case-study flow alone. At 1 Wh/Mgas every measured instance is net-positive (any intensity, any overhead definition); at 100 Wh/Mgas × 400 g/kWh none is once the on-chain market is included. | `results/eval/sensitivity.csv`, `breakeven.csv` |
| What dominates the overhead on a PoA chain? | The always-on validators, not gas: 4 × 50 W × 1 h at 400 g/kWh = 80 g per epoch vs ≈ 1.9 g of gas term for the demo flow at the demo parameters. | `results/eval/poa_node_term.csv` |
| How large can an instance be? | `publish` is the bottleneck: ≈ 0.75 M + 82.6 k·n gas (R² 0.9998); 298 tasks measured at 25.5 M (< 30 M [VERIFY]), fit reaches the 30 M limit at ≈ 354 tasks; the demo client's 15 M per-tx cap at ≈ 172 tasks. | `results/eval/gas_fit.csv` |
| Are the attacks stopped? | **28 of 29 executed attacks defended** (15 case-study, 3 + 1 Phase 3, 6 Phase 4, 4 Phase 5); the 1 Phase 3 vulnerability (lone dishonest submitter) is closed by Phase 4 fraud proofs; 4 rows are documented **assumptions**, not defences. | `results/eval/attacks.csv` |
| Which solver is best? | Depends on the data: synthetic — quantum-inspired SQA smallest gap in 2 of 3 presets, classical move-matched SA better under carbon-priority; real Alibaba (D1) — the **classical dual-market** smallest gap (19.5–23.0 %), SQA second, better than SA. **No quantum-advantage claim.** | `results/eval/solvers_summary.csv`, `classical_vs_qi.csv` |
| Quantum layer (Phase 2) | On 324 sub-problems, quantum-inspired SB reaches P(opt) 0.86–0.99; simulated QAOA (ring/complete) 0.08–0.72, at or below classical SA (0.22–0.81) at every budget. | `results/eval/quantum_summary.csv` |
| Real data (Phase 1 + D1) | Seed-7 real pipeline: carbon 187.0 → 6.5 g (−96.5 %), gap ≤ 36.4 %, 178 credits — a model output under an illustrative capacity rule. The 1 Wh floor sensitivity gives 121.0 → 8.9 g (−92.6 %), gap ≤ 56.7 %. | `results/real_snapshot/summary.json` |

---

## 1. Problem and contribution

Cloud workflows (DAGs of dependent tasks) can be placed in regions whose grid carbon intensity and electricity price
differ by orders of magnitude. Carbon-aware schedulers exist (e.g. Radovanović et al. 2023), but they are run and
reported by one trusted operator: nobody else can check that a claimed saving is real or that the schedule is good.
QICAS-Chain separates **who optimises** from **who verifies**:

1. Untrusted solvers (classical, quantum-inspired, a Lagrangian dual market) propose schedules off-chain.
2. A smart contract stores the instance, **re-scores every schedule on chain** with exactly the same integer
   function as the Python model, rejects infeasible ones, slashes cheaters, and certifies the winner's carbon
   saving net of the chain's own overhead.
3. An **on-chain price market** produces a Lagrangian **lower bound**, so the certificate also states how far the
   winner can be from optimal (certified gap); **fraud proofs** make that bound trust-minimised.
4. A **multi-signer carbon oracle** (EIP-712) feeds region carbon intensities; savings are minted as **ERC-20
   credits** and a **soulbound ERC-721 certificate**, on a permissioned **Besu QBFT** network.

Honest labels used throughout (AGENTS.md rule 5): greedy and SA are *classical*; SQA and SB are
*quantum-inspired* (classical simulations); QAOA is a *quantum algorithm, classically simulated*; the dual market is a
*classical Lagrangian decomposition*. **No quantum-advantage claim is made anywhere.**

## 2. System overview

Diagrams (PNG) are in `report_pack/diagrams/`: d1 system architecture, d2 commit–reveal + scoring, d3 price-market
rounds, d4 oracle + fraud proofs, d5 Besu + tokens, d6 data pipeline, d7 evaluation harness.

| Layer | Implementation | Phase |
|---|---|---|
| Instance + scoring (integers) | `core/instance.py`, `core/scoring.py` (`evaluate` ≡ `CarbonScheduleMarket.evaluate`) | case study |
| Solvers | `core/solvers/` greedy, SA (classical), SQA (quantum-inspired); `core/market.py` dual market | case study |
| Commit–reveal market | `CarbonScheduleMarket.sol` (V1, default demo): commit hash + stake, reveal, re-score, slash, Merkle root, credits | case study |
| Quantum layer | `core/subproblem/` exact, SA, SQA, SB, QAOA-XY (simulated, one-hot subspace), QUBO | 2 |
| On-chain price market | `PriceMarket.sol` ≡ `core/market_int.py` | 3 |
| Trust layer | `CarbonOracle.sol` (5 bonded EIP-712 signers, lower median, equivocation slashing), fraud proofs in `PriceMarket.sol`, `CarbonScheduleMarketV2.sol` | 4 |
| Real data | `core/data/`, `config/real_snapshot.yaml` (2024-10-15T12:00Z), Alibaba trace DAGs | 1 |
| Consortium chain + tokens | Besu 26.10.2 QBFT (4 validators), `QicasCredit` (ERC-20), `ScheduleCertificate` (soulbound ERC-721), `CarbonScheduleMarketV3.sol`; OpenZeppelin 5.4.0 vendored | 5 |
| Evaluation | `experiments/run_all.py` E1–E6, `experiments/figures.py` fig5–fig11, dashboard (`app/`) | 6 |

**Invariants that held in every phase.** Python ↔ Solidity parity for scoring, baseline, Merkle root, commit hash,
price-market rounds, oracle digest/median, certificate JSON (parity tests; never loosened); integers only across the
boundary; V1 artifact byte-identical (`tests/test_artifacts.py`; `node chain/compile.js --check` → IDENTICAL for all 7
contracts); default demo output unchanged; `core/` uses stdlib + numpy only; tests offline and deterministic (Besu and
recompile opt-in).

## 3. Methods

### 3.1 Scoring model (all integers)
For schedule x (task j → region d): carbon (µg) = Σ_j E_j·ci_d·1000 + network terms for DAG edges that cross regions
(estimated volume × energy per MB × ci); cost (nUSD) = Σ_j E_j·price_d + egress; score = w_c·carbon + w_$·cost;
feasible iff every region's core load ≤ capacity. The contract recomputes the same integers; the baseline is the
contract's round-robin first-fit schedule. Units: README §5.

### 3.2 Verification protocol
`publish` → `commit(keccak(epoch, x, salt, sender))` + stake → `reveal(x, salt)` (hash check, capacity check, on-chain
score) → `finalize`: best feasible score wins, non-revealers are slashed, the winner's Merkle root is stored
(`verifyPlacement` proves single placements), credits = ⌊(baseline carbon − winner carbon − chain overhead) / 1 g⌋.
Chain overhead = gas × energy per gas × chain intensity — a **sensitivity parameter, not a measurement** (§6).

### 3.3 Certified gap
Lagrangian relaxation of the capacity constraints gives a lower bound LB = Σ_w min_x V_w(x, λ) − Σ_d λ_d·cap_d for any
prices λ ≥ 0; each workflow has ≤ 7 tasks, so min V_w is solved exactly. Certified gap = (UB − LB)/UB with UB = best
revealed score. Phase 3 computes the rounds on chain (fixed step schedule; the owner cannot steer prices); Phase 4
lets anyone **challenge** a claimed bound inside a 1 h window with a cheaper workflow assignment (fraud proof).

### 3.4 Quantum layer (Phase 2)
Per-workflow priced sub-problems (3–5 tasks × 4 regions = 12–20 qubits) solved by random sampling, SA, SQA, SB
(ballistic/discrete) and QAOA with XY ring/complete mixers, simulated exactly in the one-hot subspace (proved equal to a
full statevector in `tests/test_quantum.py`). Fair comparison: same 324 sub-problems, seeds 0–29, budgets 16/64/256
energy evaluations (every move/readout/shot counted), parameters tuned on separate instances and frozen. Details:
`docs/QUANTUM_NOTES.md`.

### 3.5 Real data (Phase 1) and decision D1
One snapshot hour, **2024-10-15T12:00Z**: carbon intensity (direct) from Electricity Maps for SE-SE3, IE, US-MIDA-PJM,
IN-WE (1 / 179 / 320 / 642 g CO₂e/kWh; IE and IN-WE are Electricity Maps estimates); day-ahead prices from ENTSO-E (SE3,
IE(SEM)), the Electricity Maps API (PJM) and IEX India (all-India MCP), converted with ECB rates of 2024-10-15
(28.13 / 88.50 / 32.28 / 43.27 EUR/MWh). Workloads: 10 seeded samples of 8 Alibaba cluster-trace-v2018 DAG jobs
(3–7 tasks each; 906,932 eligible jobs). Only the 8 derived integers and their citations are committed
(`config/real_snapshot.yaml`); raw files and the extract stay local (`docs/DATA_SOURCES.md`).

**D1 (approved 2026-11-23): tasks are scaled by `instance_num`.** One instance of a trace task is 1 core for
1–174 s (median 8 s), i.e. below 1 Wh; the pre-D1 rule floored each task to 1 Wh (seed 7: 38 Wh vs an exact 2.38 Wh),
which let the illustrative network model dominate. With D1 a task is all its instances: cores = cpu × instance_num,
energy = max(1, round(cpu × s × 12 W × instance_num / 3600)) Wh, and each region's capacity = ⌈total cores × share⌉ +
the largest task's cores (keeps the contract's round-robin baseline feasible — provably, when the shares sum to ≥ 1;
without it 4 of 10 samples are infeasible because one task can hold 92 % of a sample's cores). Seed 7: 1,084 cores,
222 Wh. Option (c) "1 Wh floor" is reported next to every real-data result as a sensitivity row. D1 only changes
instance construction for the real-snapshot config; contract units, parity and the default demo are untouched.

### 3.6 Evaluation harness (Phase 6)
`python -m experiments.run_all --profile lite` (with `QICAS_BESU=1` and Besu up for E6) writes every table to
`results/eval/` and `manifest.json`; anything that cannot run is an explicit `NOT RUN - …` row (`not_run.csv`).
**Time budget (D3):** the planned grid is covered by the `lite` profile — E2 up to 64 workflows (≈ 300 tasks), E4 10
instances × 30 solver seeds × 3 weight presets on synthetic data and on the 10 real samples (plus the D1 sensitivity
dataset) — so no separate "full" profile was run. Measured runtime of the reported run: **1,717.6 s** (E1 953.7 s, E2 0.1 s, E3 20.5 s, E4 605.7 s, E5 0.1 s, E6 137.4 s; 8 E4 workers), git commit `5e333e7` plus the Phase 6 working-tree changes committed right after (the manifest records `dirty: true`); **0 NOT RUN rows** (Besu was up). Without Besu, E6 records `NOT RUN - Besu not running` and the smoke profile has 1 NOT RUN row.
Statistics: mean ± 95 % bootstrap CI (2,000 resamples, solver seeds resampled within instances); paired bootstrap for
classical − SQA; numpy only.

## 4. Results

All numbers: lite profile, 2026-11-23, in-memory chain unless stated, synthetic instances = `config/demo.yaml`
generator, real instances = 10 Alibaba samples × `config/real_snapshot.yaml`. Figures: `results/eval/figures/`
(also `report_pack/figures/`).

### 4.1 Case-study demo (seed 7) and Phases 3–5 on the same instance

| Quantity | Value | Source |
|---|---|---|
| Instance | 39 tasks, 8 workflows, 36 edges, 4 regions | `results/demo_run.json` |
| Baseline (contract round-robin) → winner (dual-market) | 961.8 → 531.8 g (−44.7 %), cost $0.4968 → $0.1774 | same |
| Solvers (score) | greedy 872,431,150 · SA 758,638,650 · SQA 730,160,300 · dual-market 709,208,800 | same |
| Lagrangian LB / certified gap | 638,827,640 / ≤ 9.92 % | same |
| Chain overhead (0.5 Wh/Mgas × 400 g/kWh, [VERIFY]) / net / credits | 1.868 g / 428.0 g / 428 | same |
| On-chain market (Phase 3): LB on chain, gap | 638,827,725 (round 20), 992 bps | `results/onchain_market/summary.json` |
| Market gas: openMarket / per round / 25 rounds | 2,542,189 / 980,133 / 27,045,516 | same |
| Trust layer (Phase 4): finalised LB, fraud-proof gap | 638,827,725, 992 bps | `results/trust/summary.json` |
| Trust gas per epoch (snapshot + claim + finalise) | 1,472,845 (submitReports 908,709 for 20 reports) | same |
| V3 token flow (Phase 5) | 427 QCC credits + soulbound certificate #1; V3 `finalize` 502,580 gas | `results/eval/besu_vs_memory_summary.csv` |

### 4.2 E1 — net carbon vs overhead (fig5, fig6; `sensitivity.csv`, `breakeven.csv`, `tradeoff.csv`, `poa_node_term.csv`)

18 flows (2–64 workflows = 7–298 tasks × 3 seeds); gross saving 47–3,386 g per epoch. Three overhead definitions
(flow only; + 25 on-chain market rounds; + trust layer), each over the [VERIFY] grid.

| Energy per Mgas × 400 g/kWh | Flow only: instances net-positive | + market | + market + trust |
|---|---|---|---|
| 1 Wh | 18/18 (net 44.5–3,369 g) | 18/18 | 18/18 (38.9–3,307 g) |
| 10 Wh | 18/18 | 17/18, break-even ≈ 19 tasks | 17/18, break-even ≈ 19 tasks |
| 100 Wh | 11/18, break-even ≈ 76 tasks | **0/18** | **0/18** (−4,609 … −619 g) |

Full range over the grid (flow + market + trust): net −1,395,634 … +3,386 g; overhead 0.002 %–286,927 % of the gross
saving. The 25 market rounds cost ≈ 2.2–3.6× the flow's gas (e.g. 154.9 M vs 43.5 M gas at 298 tasks).
**PoA node term** (4 validators, [VERIFY]): 0.008 g (5 W, 0.01 h, 40 g/kWh) … 13,440 g (200 W, 24 h, 700 g/kWh) per
epoch; at 400 g/kWh, 50 W × 1 h = 80 g and 200 W × 24 h = 7,680 g, at which no measured instance stays net-positive.
**Trade-off (median certified gap over 18 flows):** 57.0 % after 5 rounds, 32.8 % after 10, 13.3 % after 25.

### 4.3 E2 — gas vs instance size (fig7; `gas_scaling.csv`, `gas_fit.csv`)

| Function | Fit (gas, n = tasks) | R² |
|---|---|---|
| `publish` | 748 k + 82.6 k·n (≈ 740 k + 50.2 k·n + 33.2 k·edges) | 0.99985 |
| `reveal` (accepted) | 251 k + 9.4 k·n | 0.99986 |
| `finalize` | 187 k + 1.26 k·n | 0.99995 |
| `openMarket` / `submitBatch` / `closeRound` | 1.41 M + 29.8 k·n / 97 k + 17.0 k·n / 233 k + 2.5 k·n | ≥ 0.9996 |

Largest measured instance 298 tasks (`publish` 25.5 M, under the 30 M reference limit [VERIFY]); the fit extrapolates
to ≈ 354 tasks at 30 M; the demo client's 15 M per-tx cap is exceeded from ≈ 172 tasks (150 fits, 282 does not).
Structural limits: m ≤ 255 regions (`uint8`), ≤ 7 tasks per workflow for exact sub-problems.

### 4.4 E3 — attack suite (`attacks.csv`; asserted row by row in `tests/test_attack_suite.py`)

| Layer | Executed | Defended | Notes |
|---|---|---|---|
| Case study | 15 | 15 | over-capacity, copycat, no-show, malformed schedules, wrong phase, non-owner finalize, withdraw reentrancy … |
| Phase 3 market | 4 | 3 | inflated submission, incomplete round, validation reverts defended; **lone dishonest submitter = documented vulnerability**, fixed by Phase 4 fraud proofs |
| Phase 4 trust layer | 6 | 6 | minority liars, stale report, replayed signature, equivocation, false bound claim, griefing challenge |
| Phase 5 tokens | 4 | 4 | unauthorised mint, double certificate, mint after admin renounced (minter set frozen; market keeps its role), soulbound transfer |
| Assumptions | 4 | — | majority oracle collusion, no live challenger, wrong data source … **documented, not defended** |

### 4.5 E4 — solver comparison (fig8, fig9, fig8r, fig9r; `solvers_summary.csv`, `classical_vs_qi.csv`)

10 instances × 30 solver seeds × 3 weight presets per dataset; certified gap to the Lagrangian LB, mean [95 % CI];
every run feasible. SA "move-matched" gets exactly SQA's move count (sweeps × replicas).

| Dataset · preset | greedy (cl.) | SA default (cl.) | SA move-matched (cl.) | SQA (q-inspired) | dual-market (cl. decomp.) |
|---|---|---|---|---|---|
| synthetic · carbon-priority | 24.4 | 17.0 [16.8, 17.3] | **15.2** [14.9, 15.4] | 16.0 [15.8, 16.2] | 17.2 |
| synthetic · balanced | 27.6 | 13.0 [12.6, 13.3] | 10.8 [10.5, 11.1] | **9.2** [9.0, 9.4] | 16.0 |
| synthetic · cost-priority | 35.5 | 14.1 [13.6, 14.5] | 12.4 [12.0, 12.8] | **9.5** [9.3, 9.6] | 23.6 |
| real (D1) · carbon-priority | 60.6 | 32.2 [31.4, 33.0] | 31.1 [30.2, 32.0] | 27.5 [27.2, 27.9] | **23.0** |
| real (D1) · balanced | 59.0 | 36.3 [34.6, 38.1] | 35.7 [34.0, 37.4] | 25.2 [24.3, 26.1] | **20.0** |
| real (D1) · cost-priority | 59.9 | 36.2 [34.8, 37.6] | 34.0 [32.5, 35.4] | 20.5 [19.2, 21.9] | **19.5** |
| real, 1 Wh floor (D1 sensitivity) · carbon / balanced / cost | 72.6 / 83.0 / 92.5 | 57.5 / 65.7 / 70.7 | 55.6 / 65.2 / 69.7 | **46.3 / 40.9 / 44.2** | 86.7 / 91.1 / 94.3 |

**Where classical matches or beats quantum-inspired** (paired Δ = classical − SQA gap, 95 % CI; 4 of 36 comparisons):
synthetic carbon-priority, move-matched SA −0.84 pp [−1.13, −0.57]; real (D1) dual-market −4.53 pp [−4.88, −4.15]
(carbon-priority) and −5.20 pp [−6.10, −4.36] (balanced); real (D1) cost-priority dual-market −1.02 pp [−2.38, 0.33]
(no significant difference). In all other comparisons SQA has the smaller gap (e.g. real D1 vs move-matched SA:
+3.5 / +10.6 / +13.4 pp). CPU time ≈ 0.45–0.55 s per SA-move-matched / SQA run, ≈ 1.4–2.8 s per dual-market run
(simulator time on a laptop).

**D1 effect.** Scaling by `instance_num` gives the task energy real weight. All solvers then reach much smaller
gaps (SQA 20.5–27.5 % vs 40.9–46.3 % under the 1 Wh floor), and the dual market goes from worst (86.7–94.3 %) to best.
Under the floor its schedules were dominated by the illustrative network terms, which the Lagrangian relaxation
handles badly.

### 4.6 E5 — quantum sub-problems (Phase 2, not re-run; fig10; `quantum_summary.csv`)

P(optimum found) per sub-problem (324 sub-problems × 30 seeds), budget 16 / 64 / 256 evaluations:

| Method (label) | 16 | 64 | 256 |
|---|---|---|---|
| random (sanity baseline) | 0.11 | 0.35 | 0.62 |
| SA (classical) | 0.22 | 0.57 | 0.81 |
| SQA (quantum-inspired) | 0.12 | 0.56 | 0.91 |
| SB ballistic / discrete (quantum-inspired) | 0.86 / 0.72 | 0.96 / 0.96 | 0.99 / 0.99 |
| QAOA ring / complete (quantum, classically simulated) | 0.08 / 0.10 | 0.26 / 0.31 | 0.62 / 0.72 |
| QAOA with ideal angles (optimistic upper bound, not runnable) | 0.93 / 0.96 | 0.97 / 0.99 | 0.98 / 1.00 |

At this size brute force solves every sub-problem in milliseconds; the benchmark measures quality per sampling budget
on a classical simulator. Classical SA matches or beats simulated QAOA on 65–96 % of sub-problems
(`quantum_classical_vs.csv`).

### 4.7 E6 — Besu QBFT vs in-memory (fig11; `besu_vs_memory.csv`, `besu_vs_memory_summary.csv`)

| Seed-7 flow | in-memory (py-evm, automine) | Besu QBFT (4 validators, 2 s blocks) |
|---|---|---|
| V1: outcome (scores, attackers, winner, Merkle root, 428 credits) | reference | **identical** |
| V1: gas (16 txs) | 9,576,573 | 9,576,561 (−12: one commit hash binds a different sender address → calldata zero bytes) |
| V1: wall-clock, blocks | 8.6 s, 15 | 33.4 s, 17 (≈ 1.96 s per block) |
| Confirmation per tx | 0.1–1.4 s | ≈ 1.9–3.0 s (≈ one block period) |
| V3 token flow (31 txs + 2 market rounds) | 19,811,982 gas, 13.6 s | 19,811,866 gas, 76.3 s, 38 blocks; 427 credits, certificate #1, parity ✓ |

Opt-in Besu tests: `QICAS_BESU=1 pytest -m besu` → 4 passed (vote test opt-in via `QICAS_BESU_VOTE=1`; passed in
Phase 5). On Besu the 1 h challenge window runs in real time, so the certificate's gap field is 10000 (no certified
bound); with time travel (in-memory) it carries 992 bps.

## 5. Discussion — what the results do and do not show

- **Verification is cheap per decision but not free per epoch.** Re-scoring a 39-task schedule costs ≈ 0.5 M gas
  per reveal, and the whole demo flow ≈ 9.6 M gas. Whether that is "green" depends on parameters we could not source:
  at ≤ 1 Wh/Mgas every measured case is net-positive; at 100 Wh/Mgas the market and trust layer cancel the
  saving. On a PoA consortium the node term dominates, so the useful question is how many epochs share an always-on
  network, not how much gas one epoch uses. We therefore never quote a single net-saving number.
- **The certificate's value is the bound.** 25 rounds bring the median certified gap from 57 % (5 rounds) to 13 %,
  for ≈ 1 M gas per round at the demo size. The fraud-proof window turns "trust the submitter" into "trust that one
  watcher is live".
- **Solver ranking is data-dependent.** On synthetic instances quantum-inspired SQA leads in 2 of 3 presets, but a
  classical SA with the same move budget beats it under carbon-priority. On real (D1) instances the classical
  Lagrangian dual market is best, and SQA beats SA by a wide margin. SA was not re-tuned for the real instances' smaller
  score scale, so part of that margin may be tuning. SQA and SB are classical simulations; nothing here is evidence of
  quantum advantage, and simulated QAOA is the weakest runnable method at these budgets.
- **D1 changed the conclusions on real data, as an approved modelling decision should be visible.** Under the 1 Wh
  floor SQA looked dominant and the dual market looked useless; with tasks scaled by `instance_num`, the dual market
  wins. Both are reported.
- **Besu changes latency, not results.** Same scores, same attacker outcomes, same Merkle root and credits; gas
  differs by ≤ 116 per flow (calldata zero bytes); confirmation follows the 2 s block period.

## 6. Limitations and threats to validity

**Construct validity.**
- *Overhead is not measured.* Energy per gas and the PoA node power have **no sources** ([VERIFY], decision 2 of the
  Phase 6 plan). Net carbon is therefore reported only as **ranges** over a wide illustrative grid (0.01–10,000 Wh/Mgas
  × 40/400/700 g/kWh; 4 validators × 5–200 W × 0.01–24 h per epoch). Gas is not energy: on a PoA network the
  always-on validators dominate.
- *Illustrative model parts.* Power per core (12 W), capacity shares, network energy and egress price per MB are
  illustrative; Alibaba edge volumes are **estimated** (the trace has none). Under D1 the capacity headroom is loose,
  so real-data carbon reductions (~96 %) mostly show that a near-zero-carbon region (Stockholm, 1 g/kWh) can absorb the
  load in this model — not an achievable cloud saving.
- *The certified gap includes the looseness of the bound itself* (the Lagrangian relaxation ignores cross-region edge
  coupling), so a large gap does not mean a bad schedule.

**Internal validity.**
- *Simulated chain.* E1–E5 run on an in-memory EVM (eth-tester/py-evm, block gas limit raised to measure large
  instances; every result is compared with a 30 M reference limit [VERIFY]). Besu (E6) runs 4 validators on **one
  laptop**: it shows identical outcomes and ~2 s confirmation, not inter-data-centre latency.
- *Solver tuning.* SA and SQA keep the demo's settings; SA was not re-tuned for the longer move-matched budget or for
  the ~30× smaller score scale of the real instances. CPU times are simulator times on a laptop.
- *Quantum results are simulator-only* (Phase 2); "ideal angles" QAOA rows are an optimistic upper bound.

**External validity.**
- *One snapshot hour, one day* (2024-10-15T12:00Z): not real time, not a forecast. IE and IN-WE intensities are
  Electricity Maps estimates; IN-WE uses the all-India IEX price.
- *Trace sampling:* 10 samples × 8 jobs of 3–7 tasks (structural limit: the market solves each workflow exactly);
  synthetic E4 instances are all the demo size (~35–40 tasks).
- *Trust assumptions, not defences:* honest majority of oracle signers; ≥ 1 honest live watcher per challenge window;
  the upstream data source itself is correct. Bonds, quorum and window are illustrative, not tuned for economic
  security. Keys, genesis and zero gas price are TEST ONLY.
- *Design limits:* `publish` gas grows ≈ linearly with tasks (§4 E2); m ≤ 255 regions (`uint8` schedules).

## 7. Conclusion

QICAS-Chain shows that a blockchain can **verify** carbon-aware workflow schedules produced by untrusted solvers.
It re-scores them with an integer model identical to the off-chain one, stops 28 of 29 executed attacks (the
29th is closed by the Phase 4 fraud proofs), and certifies both the saving and a provable optimality gap, on an
in-memory EVM and on a 4-validator Besu QBFT network with ERC-20 credits and soulbound certificates. The open question
is the overhead. Gas-to-energy and node power have no sources, so net carbon is a range: clearly positive at low energy
per gas, negative once the market and an always-on PoA network are charged to a single small epoch. The
quantum-inspired solvers are competitive heuristics, not a quantum advantage, and on real instances a classical
decomposition was best. Next steps: sourced overhead parameters, many epochs per network, more snapshot hours and
regions with forecasts, per-pair network tables (Phase 1b), and hardware runs of the quantum sub-problems.

## 8. Reproducibility

Exact commands: `CLAUDE.md` ("Commands") and `RUN_GUIDE.md`; software/hardware: `report_pack/repo_overview.md`.
Run order for this report: `pytest -q` → `demo.run_demo` → `demo.make_figures` → `experiments.onchain_market` →
`experiments.trust_layer` → `experiments.real_snapshot` → `scripts\besu_up.ps1` → `$env:QICAS_BESU='1'`
`experiments.run_all --profile lite` → `experiments.figures` → `scripts\besu_down.ps1` →
`scripts\make_report_pack.py --screenshots`. Phase 2 tables come from `experiments.quantum_benchmark` (committed
summaries in `results/quantum/`).

## 9. References

1. A. Radovanović et al., "Carbon-Aware Computing for Datacenters," *IEEE Transactions on Power Systems*, vol. 38,
   no. 2, pp. 1270–1280, 2023.
2. "Blockchain-assisted smart grid scheduling using energy-efficient swarm and deep learning models," *The Journal of
   Supercomputing*, 2026. https://link.springer.com/article/10.1007/s11227-026-08743-8 [VERIFY author list]
3. N. G. Hammouda et al., "A quantum-driven multi-objective scheduler for scalable task orchestration in fog-based
   cyber-physical-social systems," *Scientific Reports*, vol. 16, art. 6874, 2026. doi:10.1038/s41598-025-33627-x
4. F. A. Quinton et al., "Quantum annealing applications, challenges and limitations for optimisation problems
   compared to classical solvers," *Scientific Reports*, vol. 15, art. 12733, 2025.
5. B. M. Beena et al., "A green cloud-based framework for energy-efficient task scheduling using carbon intensity data
   for heterogeneous cloud servers," *IEEE Access*, vol. 13, pp. 73916–73936, 2025. doi:10.1109/ACCESS.2025.3562882
6. **Electricity Maps (2026).** Carbon intensity data, 2024 hourly, zones SE-SE3, IE, US-MIDA-PJM, IN-WE, dataset
   version 2026-02-10; day-ahead price US-MIDA-PJM via the Electricity Maps API (accessed 2026-11-23).
   https://www.electricitymaps.com — *used under an academic licence: non-commercial use, no redistribution; only one
   derived value per region is reproduced in this report.*
7. ENTSO-E Transparency Platform, Energy Prices [12.1.D], bidding zones SE3 and IE(SEM), 2024-10-15.
8. IEX India, Day-Ahead Market snapshot, 2024-10-15.
9. European Central Bank, euro foreign exchange reference rates, 2024-10-15.
10. Alibaba Cluster Trace Program, cluster-trace-v2018. https://github.com/alibaba/clusterdata; analysis: J. Guo et al.,
    "Who Limits the Resource Efficiency of My Datacenter: An Analysis of Alibaba Datacenter Traces," IWQoS 2019.
11. OpenZeppelin Contracts 5.4.0 (MIT). Hyperledger Besu 26.10.2 (Apache-2.0), QBFT consensus.
12. Quartiles and full author lists: verify on SCImago/JCR before submission (`docs/CASE_STUDY_PAPERS.md`).
