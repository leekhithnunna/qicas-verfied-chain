# QICAS-Chain — Project Plan (Team 07)

**Verifiable, quantum-inspired, carbon-aware scheduling of cloud workflows on blockchain.**

This plan takes the working case-study demo to the full project. It is the single source of truth for
*what phase we are in* (see "Current phase" below). Hard engineering rules live in `AGENTS.md`; the
system map lives in `README.md`.

## Current phase

> **Case study: DONE** (case-study report drafted in `docs/CASE_STUDY_REPORT.md`).
> **Phase 2 — Quantum layer: DONE** (acceptance tests pass; results in [QUANTUM_NOTES.md](QUANTUM_NOTES.md)).
> **Phase 6-lite — Evaluation on synthetic data: DONE** (45 tests pass; results in README §14 and
> "Phase 6-lite results" below).
> **Phase 3 — On-chain price market: DONE** (2026-11-19; 64 tests pass + 1 opt-in recompile test; results in
> README §15 and "Phase 3 results" below).
> **Phase 4 — Trust layer: DONE** (2026-11-19; 89 tests pass + 1 opt-in recompile test; results in README §16
> and "Phase 4 results" below; decisions assumed from the plan's recommendations, confirmed by the user 2026-11-19).
> **Phase 1 — Real data: DONE** (2026-11-23; 118 tests pass + 1 opt-in recompile test; snapshot
> 2024-10-15T12:00Z; results in README §17 and "Phase 1 results" below; sources/licences in
> [DATA_SOURCES.md](DATA_SOURCES.md)).
> **Phase 5 — Consortium chain + tokens: DONE** (2026-11-23; Besu QBFT 4 validators, ERC-20 credits, soulbound
> ERC-721 certificates, `CarbonScheduleMarketV3`; results in README §18 and "Phase 5 results" below; build
> decisions A1–A10 in [plans/PHASE5_BESU_TOKENS.md](plans/PHASE5_BESU_TOKENS.md), confirmed by the user 2026-11-23).
> **Full Phase 6 — Evaluation: DONE** (2026-11-23; E1–E6 run, 0 NOT RUN rows with Besu up; fig5–fig11;
> dashboard tabs On-chain market, Oracle & challenges, Tokens; [FINAL_REPORT.md](FINAL_REPORT.md); README §19;
> decisions D1 (Phase 1 task size = `instance_num`) and D2 (Phase 5 A1–A10 confirmed) applied).
> **Current phase: Complete** — all phases done. Update this pointer only if new work is planned.
> Update this pointer whenever a phase's acceptance tests pass.

## Build order (approved 2026-11-13, changed 2026-11-17)

1. **Phase 2** — Quantum layer (DONE)
2. **Phase 6-lite** — E1–E4 on synthetic data + dashboard Evaluation tab (DONE)
3. **Phase 3** — on-chain price market, on synthetic data (built now: Phase 1 waits for data downloads)
4. **Phase 1** — Real data, when the raw downloads are ready
5. **Phase 4** — trust layer, then **Phase 5** — Besu + tokens
6. **Full Phase 6** — full evaluation and the new `docs/FINAL_REPORT.md` (`docs/CASE_STUDY_REPORT.md` stays unchanged)

Change of 2026-11-17 (user request): Phase 3 moved before Phase 1 because Phase 1 is blocked on manual
downloads (`data/raw/DOWNLOAD_CHECKLIST.md`). Order is now 3 → 1 → 4 → 5 → full 6.

Approved design decisions so far (details in each plan's "Decisions (approved)" section):
- Phase 2 (DONE): numpy only (no SciPy/Qiskit/PennyLane); benchmark budget = energy evaluations/shots,
  wall-clock secondary; Phase 2 built before Phase 1.
- Phase 5: schedule certificates are **soulbound** (non-transferable ERC-721 attestations); credits stay a
  normal transferable ERC-20; the validator add/remove vote test is included and marked optional.
- Phase 6: no sources exist for gas-to-energy or node-power inputs → wide illustrative grid marked
  [VERIFY]; net-carbon results presented as ranges.

## Plans

Detailed implementation plans (each with prerequisites and open decisions). A phase is implemented only
after its plan is approved.

| Build # | Phase | Plan | Status |
|---|---|---|---|
| 1 | 2 Quantum layer | [plans/PHASE2_QUANTUM.md](plans/PHASE2_QUANTUM.md) | **DONE** (commits `554756d`..`f6c9633`, 21 tests pass); decisions 1–2 resolved: numpy only, budget = energy evaluations/shots |
| 2 | 6-lite Evaluation (E1–E4 synthetic + Evaluation tab) | [plans/PHASE6_EVALUATION.md](plans/PHASE6_EVALUATION.md) | **DONE** (commits `9de7efa`..step 6, 45 tests pass, `run_all --profile lite` completes) |
| 3 | 3 On-chain price market | [plans/PHASE3_PRICE_MARKET.md](plans/PHASE3_PRICE_MARKET.md) | **DONE** (commits `2040ae3`..step 4, 64 tests pass); decisions 1–2: separate `PriceMarket.sol`, step schedule fixed at `openMarket`; V1 artifact byte-identical |
| 4 | 1 Real data | [plans/PHASE1_REAL_DATA.md](plans/PHASE1_REAL_DATA.md) | **DONE** 2026-11-23 (commits `2a54757`..`3801189`+docs, 118 tests pass); decisions 1–3 applied (extract kept local: no licence grants redistribution) |
| 5 | 4 Trust layer | [plans/PHASE4_TRUST_LAYER.md](plans/PHASE4_TRUST_LAYER.md) | **DONE** (commits `a57afb0`..step 4, 89 tests pass); decisions 1 (a) V2 market and 2 (bonds + equivocation) assumed from the recommendations, confirmed by the user 2026-11-19 |
| 6 | 5 Consortium chain + tokens | [plans/PHASE5_BESU_TOKENS.md](plans/PHASE5_BESU_TOKENS.md) | **DONE** 2026-11-23 (commits `e14e2b8`..docs); soulbound certificates, optional vote test (passes); OZ 5.4.0 vendored; V3 market; build decisions A1–A10 confirmed by the user 2026-11-23 |
| 7 | 6 Full evaluation | [plans/PHASE6_EVALUATION.md](plans/PHASE6_EVALUATION.md) | decisions approved (new `FINAL_REPORT.md`, [VERIFY] grid, ranges); builds last |

## Invariants for every phase (non-negotiable)

1. **The case-study demo keeps working.** `config/demo.yaml` (default config, seed 7) must still produce
   the RUN_GUIDE.md numbers, and all existing tests must pass, at the end of every phase. New behaviour
   goes behind new config files / flags / modules, not by changing defaults.
2. **Off-chain solve, on-chain verify.** The chain never runs a search; it checks.
3. **Integer parity Python = Solidity**, enforced by `tests/test_parity.py` and extended for every new
   on-chain function. Never loosen a parity test (AGENTS.md rule 7).
4. **Honest labels.** Greedy and SA = *classical*; SQA and simulated bifurcation (SB) = *quantum-inspired*;
   QAOA = *quantum algorithm* (run on a simulator unless stated otherwise). No "quantum advantage" claim.
5. **Contract-fixed baselines.** Savings are always measured against a baseline the contract computes.
6. **Net, not gross, carbon.** Every saving reported subtracts estimated chain overhead.
7. **Reproducible.** Every run records seed, instance hash, config hash and data-snapshot hash; external
   data is frozen into dated, checksummed files in the repo (or a documented download script + checksum
   where the licence forbids redistribution).
8. **Definition of done (each phase):** `.\.venv\Scripts\python.exe -m pytest -q` passes AND
   `.\.venv\Scripts\python.exe -m demo.run_demo` completes with unchanged default output.

---

## Case study — DONE (baseline we build on)

Synthetic Alibaba-style DAGs; 4 illustrative regions; greedy / SA / SQA / dual-market solvers;
`CarbonScheduleMarket.sol` with contract-computed round-robin baseline, commit-reveal, staking/slashing,
on-chain re-scoring, Merkle proofs, net-carbon credits; Streamlit dashboard; 8 tests including
Python↔Solidity parity. Seed-7 reference output is in `RUN_GUIDE.md`.

**Honest-claims note:** region values are illustrative, the workload is synthetic, the oracle is
trusted, the overhead model is a parameterised estimate, the market runs off-chain.

---

## Phase 1 — Real data — DONE

**Status.** DONE 2026-11-23. See "Phase 1 results" at the end of this section. The deliverables below are
the original outline; what was built differs where noted in the results (C3/C4 sources, no network tables).


**Goal.** Replace synthetic/illustrative inputs with real, dated, citable data while keeping the
synthetic path as the default demo.

**Deliverables.**
- `data/README.md` — provenance table: source, licence, URL, retrieval date, SHA-256 per file.
- `data/alibaba/` + `core/data/alibaba.py` — loader for **Alibaba cluster-trace-v2018** `batch_task`
  (DAG dependencies are encoded in task names, e.g. `M1`, `R2_1`); sampling of N jobs by seed;
  conversion to integer `Task`/`Edge` (cores, duration → Wh; edge MB from a documented heuristic,
  since the trace has no transfer sizes).
- `data/carbon/` + extend `scripts/load_em_snapshot.py` — dated **Electricity Maps** hourly carbon
  intensity per region (ODbL — verify licence terms at download time and attribute accordingly).
- `data/prices/` + `core/data/prices.py` — day-ahead prices: **ENTSO-E** Transparency (SE3 Stockholm,
  IE-SEM Ireland), **IEX India** DAM (Mumbai — document the bid area used), **PJM** day-ahead LMP
  (US-East / Dominion zone). Currency conversion with a fixed, dated FX rate.
- `data/network/` — public inter-region latency table and published cloud egress prices (dated) →
  per-region-pair edge carbon and fee (`Instance` gains optional pairwise matrices).
- `config/real_2026.yaml` — real-data config; `config/demo.yaml` unchanged.
- `tests/test_data.py` — loaders, checksums, unit conversion.

**Acceptance tests.**
- Loaders reproduce frozen fixtures byte-for-byte (checksum test).
- An instance built from `config/real_2026.yaml` is fully integer, passes `evaluate` parity against the
  contract, and has a stable instance hash across runs.
- `demo.run_demo --config config/real_2026.yaml` completes; default run output unchanged.

**Dependencies.** Case study only.

**Risks.** Alibaba trace is large (tens of GB) → commit only a small sampled extract + script;
Electricity Maps free-tier/portal terms may change; IEX/PJM download formats are not stable APIs;
pairwise edge matrices change the scoring formula → **must be mirrored in Solidity and parity-tested**
(contract recompile per README §9.3).

**Honest-claims note.** "Real carbon/price snapshot for one dated hour" — not real-time, not a forecast.
Edge data sizes are *estimated* (trace lacks them). Latency/egress are published list values, not measured.

### Phase 1 results

DONE 2026-11-23 (commits `2a54757` docs/data rules, `6e5f896` ingestion, `3801189` loaders + config + wiring, then
docs). Built as `docs/plans/PHASE1_REAL_DATA.md` §2–3, with these differences from the outline above:
- **Config name** `config/real_snapshot.yaml` (not `real_2026.yaml`); snapshot hour 2024-10-15T12:00Z.
- **Sources changed:** C3 = Electricity Maps API day-ahead price for US-MIDA-PJM (PJM Data Miner 2 was down);
  C4 = IEX DAM *Market Snapshot* (hourly, all-India MCP — no W1–W3 columns). The IEX xlsx is read with the standard
  library (no openpyxl). PJM CSV loader not built (no PJM file).
- **Not committed:** raw files and the processed Alibaba extract (no licence grants redistribution); only 8 derived
  integers + citations + raw SHA-256s are in the config. `data/` is git-ignored (anchored `/data/`; the unanchored
  pattern also hid `core/data/`, caught before commit) and `tests/test_repo_hygiene.py` guards it.
- **Out of scope (Phase 1b):** per-pair latency/egress tables (would change `evaluate` on both sides).
- **Evaluation:** E4 real-data rows run on 10 Alibaba samples when `data/processed/` exists, else
  `NOT RUN - data missing`; the manifest records the data snapshot. Smoke NOT RUN rows: 7 → 6 (none for Phase 1).

Key numbers (seed 7; details README §17): snapshot carbon 1 / 179 / 320 / 642 g/kWh (Stockholm, Ireland, Virginia,
Mumbai; IE and IN-WE are Electricity Maps estimates), prices 28.13 / 88.50 / 32.28 / 43.27 EUR/MWh. Real workload:
38 tasks, 30 edges; with D1 (tasks scaled by `instance_num`, 2026-11-23): winner dual-market, carbon 187.0 → 6.5 g
(96.5 %), net 178.7 g, certified gap ≤ 36.4 % (pre-D1 1 Wh floor, kept as sensitivity: SQA 121.0 → 8.9 g, 92.6 %,
gap ≤ 56.7 %).
E4 lite on real data (10 samples × 30 seeds × 3 presets) with D1: the classical dual-market has the smallest
certified gap (23.0 / 20.0 / 19.5 %), SQA (quantum-inspired) second (27.5 / 25.2 / 20.5 %) and better than
move-matched SA (31.1 / 35.7 / 34.0 %); under the pre-D1 1 Wh floor (sensitivity) SQA was best (46 / 41 / 44 %).
On synthetic data move-matched SA beats SQA under carbon-priority. No quantum-advantage claim (SQA is a classical
simulation; SA not re-tuned).
**Main caveat (resolved by D1, 2026-11-23):** one instance of every real task is < 1 Wh (median 8 s, 1 core); the
1 Wh floor let the illustrative network model dominate. D1 = option (a): cores and energy × `instance_num`,
capacity = ⌈total × share⌉ + largest task (feasibility); the floor is now an E4/real_snapshot sensitivity row.
New caveat: the capacity headroom is loose, so Stockholm (1 g/kWh) absorbs most load (reductions ~96 %).

---

## Phase 2 — Quantum layer — DONE

**Status.** DONE (commits `554756d`..`f6c9633`; 21 tests pass; default demo unchanged). Implemented in
`core/subproblem/` (the file names below are the original plan; see `plans/PHASE2_QUANTUM.md` §4 for the
as-built layout). Results: [QUANTUM_NOTES.md](QUANTUM_NOTES.md) and "Phase 2 results" below.

**Goal.** Add a constraint-preserving QAOA solver for workflow sub-problems and compare it honestly with
SQA, simulated bifurcation and classical SA.

**Deliverables.**
- `core/solvers/qubo.py` — shared QUBO/Ising builder for a sub-problem (one-hot register per task,
  capacity via Lagrangian prices from `core/market.py`, so no capacity penalty inside the sub-problem).
- `core/solvers/qaoa_xy.py` — QAOA with **XY mixer** (Hamming-weight-preserving, stays in the one-hot
  feasible subspace) on **12–20 qubits** (= 3–5 tasks × 4 regions, or larger with candidate-region
  pruning). Statevector simulator; `seed` argument; optional hardware backend behind a flag.
- `core/solvers/sb.py` — simulated bifurcation (ballistic/discrete variant), quantum-inspired.
- `experiments/quantum_benchmark.py` + `results/quantum/` — same sub-problems, same time budgets,
  ≥ 30 seeds, report approximation ratio vs exact optimum (brute force is possible at this size),
  feasibility rate, wall time.
- Design-knot write-ups in `docs/QUANTUM_NOTES.md`: **ring vs complete XY mixer**; **parameter reuse
  across price rounds** (do angles from round k warm-start round k+1?); **warm start from SQA**
  (initial state biased to SQA solution vs uniform W-state).
- Tests: XY mixer preserves Hamming weight (statevector check); QUBO energy equals `evaluate` +
  price terms on random assignments; determinism by seed.

**Acceptance tests.**
- QUBO ↔ `core/scoring.py` energy agreement on 100 random assignments (exact integers).
- QAOA output is always one-hot feasible (probability mass outside feasible subspace < 1e-9).
- Benchmark script runs end-to-end and writes a table with all four methods + exact optimum.
- Default demo and existing 8 tests unchanged (QAOA not in default solver list).

**Dependencies.** Phase 1 optional (benchmarks can use synthetic instances); `core/market.py` prices.
Python packages: **numpy only** (option A of the plan; pinned `numpy==2.5.4` in `requirements.txt`, already
installed via pandas). Justification (AGENTS.md rule 9): the QAOA-XY simulator, simulated bifurcation and
the Nelder–Mead / SPSA optimisers need vectorised linear algebra; numpy covers all of it, so SciPy / Qiskit /
PennyLane are not added. numpy is imported only by `core/subproblem/` and `experiments/`, never on the
default demo path.

**Risks.** Simulation cost grows as 2^n — 20 qubits is the practical ceiling; workflows up to 7 tasks
× 4 regions = 28 qubits do not fit without decomposition/pruning; QAOA at low depth may lose to SA,
which is an acceptable, reportable result; new deps (Qiskit/PennyLane) must not be imported by the
default demo path.

**Honest-claims note.** Claim **"quantum-ready, feasibility-preserving"** only. QAOA results are from a
classical simulator. Never claim quantum advantage or speed-up; report where classical SA wins.

### Phase 2 results

Source: `results/quantum/summary.csv` and `results/quantum/classical_vs.csv` (committed as evidence;
full write-up in [QUANTUM_NOTES.md](QUANTUM_NOTES.md)). 324 test sub-problems (3–5 tasks × 4 regions,
12–20 qubits) × 30 seeds per method and budget B (energy evaluations / shots). P(opt) = share of runs that
found the exact (brute-force) optimum; 95 % bootstrap CIs are in the CSV.

| Method | Label | P(opt) B=16 | B=64 | B=256 |
|---|---|---:|---:|---:|
| random | sanity baseline | 0.109 | 0.348 | 0.619 |
| SA | classical | 0.222 | 0.574 | 0.811 |
| SQA | quantum-inspired | 0.118 | 0.562 | 0.912 |
| SB ballistic | quantum-inspired | 0.862 | 0.962 | 0.988 |
| SB discrete | quantum-inspired | 0.721 | 0.957 | 0.994 |
| XY-QAOA ring (shots) | quantum algorithm, classically simulated | 0.082 | 0.262 | 0.624 |
| XY-QAOA complete (shots) | quantum algorithm, classically simulated | 0.099 | 0.312 | 0.724 |
| *XY-QAOA ring, ideal angles* | *optimistic upper bound only* | *0.927* | *0.973* | *0.981* |
| *XY-QAOA complete, ideal angles* | *optimistic upper bound only* | *0.965* | *0.990* | *0.998* |

- **Classical SA beats shot-based XY-QAOA** at every budget: SA strictly beats QAOA-ring on 96 % / 84 % /
  69 % of sub-problems (B = 16 / 64 / 256) and QAOA-complete on 83 % / 74 % / 50 %. Shot-based QAOA is at or
  below random sampling at B = 16 and 64.
- SA also beats SQA at B = 16; SQA overtakes SA at B = 256. SB (quantum-inspired, penalty-based, raw
  feasibility rate reported in the CSV) has the highest P(opt) of the honest-budget methods.
- **The complete XY mixer beat the ring mixer** at every budget (shots and ideal), at the cost of 1.5× the
  XY gates per layer; at equal gate count the two are about the same (QUANTUM_NOTES.md, Q1).
- QAOA-ideal rows use angles from exact expectations whose cost is not charged to the budget; they are an
  **optimistic upper bound**, not a comparable result.
- All QAOA results come from a classical statevector simulator; no quantum hardware was used. **No
  quantum advantage or speed-up is claimed.** At this size brute force solves every sub-problem in
  milliseconds.

---

## Phase 6-lite — Evaluation on synthetic data — DONE

**Status.** DONE. `experiments/run_all.py --profile smoke|lite` (one manifest), E1–E4 modules,
`experiments/figures.py` (fig5–fig9), dashboard split into `app/tabs/` with a new **Evaluation** tab (the five
case-study tabs render identically — checked with Streamlit AppTest element-tree dumps). Default demo, contract
artifact and `config/demo.yaml` unchanged. New config: `config/eval.yaml`. No new dependency (numpy, pandas,
matplotlib, altair via streamlit were already installed). Backward-compatible hooks: `Chain.start(
block_gas_limit=…)`, `Chain.tx_gas` (default 15 M), `pipeline.run(salt_fn=…)`; `chain/client.py::_error_name`
now decodes every custom-error selector (it previously named only printable ones such as `HashMismatch`).

### Phase 6-lite results

Source: `results/eval/*.csv` + `manifest.json` from `run_all --profile lite` (git-ignored; regenerate with the
command). Full summary in README §14.

| Exp. | Finding (synthetic data, in-memory chain) | Label / caveat |
|---|---|---|
| E1 | Overhead = 0.001 %–80,000 % of gross saving over the grid; net > 0 for every instance up to 10 Wh/Mgas; none at ≥ 1,000 Wh/Mgas × ≥ 400 g/kWh; break-even ≈ 76 tasks at 100 Wh/Mgas × 400 g/kWh | **[VERIFY]** grid without sources; ranges only; Phase 3–5 terms NOT RUN |
| E2 | `publish` ≈ 0.75 M + 83 k·n gas; 298 tasks = 25.5 M (< 30 M reference); extrapolated ≈ 354 tasks at 30 M; demo client's 15 M tx cap exceeded from ≈ 172 tasks | measured n only are claims; 30 M is the plan's reference [VERIFY] |
| E3 | 15/15 executed case-study attacks defended (expected = observed) | 11 Phase 3–5 attacks NOT RUN; 4 documented assumptions |
| E4 | SQA (quantum-inspired) has the smallest gap in balanced and cost-priority; **move-matched SA (classical) beats SQA in carbon-priority** (Δ −0.85 pp [−1.13, −0.57]); default-budget SA (4.5× fewer moves) loses everywhere | 10 instances × 30 seeds; SA not re-tuned; no quantum-advantage claim |

NOT RUN (22 rows in `not_run.csv`): E1 overhead terms for market rounds (Ph. 3), oracle + challenges (Ph. 4),
PoA node power (Ph. 5) and the on-chain cost of market rounds; E2 `openMarket`, `submitBatch`, `closeRound`
(Ph. 3), `challenge` (Ph. 4); 11 E3 attacks (Ph. 3/4/5); E4 real data (Ph. 1); E5 (out of Phase 6-lite scope);
E6 (Ph. 5).

---

## Phase 3 — On-chain price market — DONE

**Status.** DONE 2026-11-19 (commits `2040ae3` toolchain, `7c06808` contract + mirror + parity tests,
`d5a9148` experiment, `ad143fc` evaluation-harness wiring, then docs). Built exactly as
[plans/PHASE3_PRICE_MARKET.md](plans/PHASE3_PRICE_MARKET.md) specifies; that plan supersedes the original
deliverable list below where they differ:
- the mirror is `core/market_int.py` (not `core/market_onchain.py`); parity tests are in
  `tests/test_price_market.py` (16 tests), not in `tests/test_parity.py` (unchanged);
- the web3 wrapper is `chain/price_market.py`; `chain/client.py` is unchanged;
- no dashboard tab and no change to `demo/pipeline.py` in this phase (plan §4); the on-chain rounds are shown
  in `experiments/onchain_market.py` and in the dashboard's Evaluation tab (E1–E3 rows).

New dev-only dependency: `chain/package.json` pins `solc` 0.8.24 (solc-js) for `node chain/compile.js`.
Justification: reproducible README §9.3 option B compile; never imported at runtime or on the demo path.

### Phase 3 results

Seed-7 instance (39 tasks, 8 workflows, 4 regions), 25 rounds, one honest exact submitter per round
(`python -m experiments.onchain_market`; in-memory chain; every round parity-checked against Python):

| Quantity | Value |
|---|---|
| Lower bound, on-chain integer (best of 25 complete rounds, round 20) | 638,827,725 |
| Lower bound, off-chain float (`core/market.py`, default demo) | 638,827,640 |
| Upper bound (best revealed score, linked `CarbonScheduleMarket` epoch) | 709,208,800 |
| `certifiedGapBps` (on-chain) | **992 bps** (= the demo's 9.92 %) |
| `openMarket` (once; 39 tasks, 36 edges, 25 steps) | 2,542,058 gas |
| `submitBatch` (39 tasks), mean [min, max] | 711,179 [562,609, 736,423] gas |
| `closeRound`, mean [min, max] | 245,837 [230,020, 305,669] gas |
| **Gas per market round** (submitBatch + closeRound), mean [max] | **957,016** [996,560] |
| `submit` (one workflow, first submission) by size 4 / 5 / 6 tasks | 130,517 / 142,329 / 140,678 gas (seed 7 has no 3-task workflow) |
| Total for 25 rounds incl. `openMarket` | 26,467,460 gas (one-off `PriceMarket` deploy: 2,271,879) |
| Largest single tx / per round vs 30 M reference block [VERIFY] | 8.5 % / 3.3 % |
| Market carbon overhead at 0.5 Wh/Mgas, 400 g/kWh (sensitivity, not measured) | 5.29 g vs 428.0 g net saving → 422.7 g incl. market |

Round 2's dual value is negative (−131,177,880), as the plan predicted; it never becomes the bound.
Honest claim: the bound is certified **assuming each workflow's minimum was submitted by at least one honest
party**; `tests/test_price_market.py` and E3 demonstrate that a lone dishonest submitter can push the "lower
bound" above a feasible score (Phase 4 fraud proofs fix this). Parity issues found: none after the first
compile (the only build issue was a Yul stack-too-deep error, fixed by splitting the scoring helper).

**Goal.** Move the Lagrangian price-update rounds into the contract; untrusted solvers respond to
posted prices; a lower bound is recorded on-chain.

**Deliverables.**
- `chain/contracts/PriceMarket.sol` (or an extension of `CarbonScheduleMarket.sol`) — per-epoch rounds:
  contract posts integer prices λ_d; solvers submit per-workflow relaxed assignments; contract computes
  per-region demand and applies an integer subgradient step; contract computes the dual value
  Σ_w L_w(λ) − Σ_d λ_d·cap_d from submitted assignments.
- `core/market_onchain.py` — Python mirror of the integer price update (parity).
- `chain/client.py` additions; dashboard tab showing on-chain rounds.
- `tests/test_parity.py` extended: price update and dual-value computation Python = Solidity.

**Acceptance tests.**
- Integer subgradient update identical in Python and Solidity for all rounds of the seed-7 instance.
- On-chain dual value equals Python `core/market.py` lower bound (after integer rounding is defined in
  both) for the submitted assignments.
- Gas per round measured and reported; full run within block gas limit for the default instance size.

**Dependencies.** Case study (contract, market); Phase 2 optional (QAOA solves sub-problems).

**Risks.** Gas: per-round cost scales with tasks — may require batching or Merkle-committed
submissions; the contract can **verify the value** of a submitted per-workflow answer but **cannot prove
it is the minimum** → the bound is only certified if a cheaper answer cannot be found by challengers
(addressed in Phase 4); integer step-size rounding must be specified identically on both sides.

**Honest-claims note.** Until Phase 4, the on-chain lower bound is "certified assuming solvers report
per-workflow minima honestly"; say so explicitly.

---

## Phase 4 — Trust layer — DONE

**Status.** DONE 2026-11-19 (commits `a57afb0` oracle + V2, `f4f0403` fraud proofs, `27e6fcb` experiment +
harness, then docs). Built as [plans/PHASE4_TRUST_LAYER.md](plans/PHASE4_TRUST_LAYER.md) specifies, with the
assumed decisions listed there (V2 market reads the oracle; signer bonds + equivocation slashing included;
`finalizedGapBps` added instead of changing `certifiedGapBps`; claimless corrections), confirmed by the user
2026-11-19. V1 artifact byte-identical; default demo unchanged.
No new Python dependency (`eth_account` was already installed with web3).

### Phase 4 results

Seed 7 (`python -m experiments.trust_layer`; 5 signers × 4 zones; in-memory chain):

| Function | Gas |
|---|---|
| `requestSnapshot` (4 zones) | 274,562 |
| `submitReports` (20 reports) | 908,709 (≈ 45,435 per report; re-measured 2026-11-23, deterministic; first recorded 908,485) |
| `finalizeSnapshot` (4 zones) | 92,183 |
| `claimBound` / `finalizeBound` | 74,895 / 122,484 |
| `challenge` (successful), 4 / 5 / 6-task workflow | 119,314 / 136,829 / 129,488 |
| `bindOracle` | 103,203 |
| **Trust layer per epoch** (snapshot + claim + finalise) | **1,472,845** ≈ 0.29 g at 0.5 Wh/Mgas, 400 g/kWh (first recorded 1,472,609) |
| One-off: oracle deploy + 5 signer bonds | 1,774,394 |
| `PriceMarket` round after Phase 4 (λ hash stored) | 980,133 (Phase 3: 957,016) |

Finalised LB 638,827,725 → `finalizedGapBps` 992 (honest run, nothing corrected). E3: 6/6 Phase 4 attacks
defended; smoke harness NOT RUN rows 14 → 7. Parity issues found: none in contract logic. Two harness issues
were fixed: report timestamps made gas run-dependent (pinned the in-memory chain time), and CSV floats with 10
significant digits lost precision at 10⁵ g (now exact repr).

## Phase 4 — Trust layer (original outline)

**Goal.** Remove the two trusted points: the carbon-data oracle and the honesty of lower-bound claims.

**Deliverables.**
- `chain/contracts/CarbonOracle.sol` — multi-signer oracle: N registered signers submit **EIP-712**
  typed signed reports (region, hour, gCO₂/kWh, source hash); contract takes the **median per region**
  once a quorum is reached; `publish` reads from the oracle instead of the owner.
- `oracle/signer.py` — reference signer (reads frozen Phase 1 snapshots, signs EIP-712).
- `chain/contracts/BoundChallenge.sol` (or module) — **optimistic fraud proofs** (rollup-style): a
  bound claim stands after a challenge window; a challenger posts a per-workflow assignment with lower
  Lagrangian value → claimant slashed, bound corrected.
- Attack tests: lying signer minority (median holds), lying majority (documented failure), stale report,
  replayed signature (domain separator / nonce), false bound claim (challenged and slashed),
  griefing challenge (challenger bond lost).

**Acceptance tests.**
- EIP-712 digest identical in Python (`eth_account`) and Solidity (parity test).
- Median with k < N/2 malicious signers equals honest median ± honest spread.
- False bound claim is overturned within the window; honest claim survives all challenges in the suite.

**Dependencies.** Phase 1 (real data to sign), Phase 3 (on-chain bound).

**Risks.** Signer collusion is not solvable on-chain — only bounded by quorum assumptions; challenge
window lengthens finality; median over few signers is coarse.

**Honest-claims note.** "Trust-minimised", not "trustless": we assume an honest majority of oracle
signers and at least one honest, live challenger during the window.

---

## Phase 5 — Consortium chain

**Goal.** Run the system on a permissioned network that matches the real deployment model, and issue
standard tokens.

**Deliverables.**
- `chain/besu/` — Hyperledger Besu **QBFT** network config (4 validators = simulated cloud providers),
  genesis, docker-compose, startup script; `--mode besu` in `demo.run_demo`.
- `chain/contracts/CarbonCredit.sol` (**ERC-20**) and `ScheduleCertificate.sol` (**ERC-721**, one per
  finalised epoch, metadata = Merkle root + instance hash) using **OpenZeppelin** (pinned version).
- Compilation pipeline update (README §9.3) for OpenZeppelin imports; precompiled artifacts committed.
- Measured gas and block times on Besu vs in-memory EVM.

**Acceptance tests.**
- Full demo flow completes on the Besu network (`--mode besu`), same scores as in-memory mode.
- ERC-20 balance after finalise = net-saving credits; ERC-721 minted with correct root.
- Default in-memory demo and parity tests unchanged (new contracts are additive).

**Dependencies.** Phases 3–4 contracts; Docker available on the evaluation machine.

**Risks.** Docker/Windows friction; EVM version compatibility (keep `paris` or confirm Besu fork
settings); replacing the built-in minimal token must not break existing tests → keep it until the
ERC-20 path is verified, then migrate behind a flag.

**Honest-claims note.** A 4-validator local QBFT network *models* a provider consortium; it is not a
production deployment and says nothing about real providers' willingness to participate.

### Phase 5 results

DONE 2026-11-23 (commits `e14e2b8` tokens + vendored OZ, `bce2349` V3 market, `3137f6d` Besu network + client mode +
opt-in tests, then evaluation wiring + docs). Built as [plans/PHASE5_BESU_TOKENS.md](plans/PHASE5_BESU_TOKENS.md) with
build decisions A1–A10 (confirmed by the user 2026-11-23): OpenZeppelin **5.4.0** vendored (5.5+ needs `mcopy`, not `paris`); tokens
as top-level contracts; **new `CarbonScheduleMarketV3`** instead of changing V2; Besu **26.10.2** pinned by digest;
RPC on all 4 validators (loopback); certificate gap from `PriceMarket.finalizedGapBps` (10000 = none); chainId 1338;
opt-in flags `QICAS_BESU` / `QICAS_BESU_VOTE`; the 1-hour challenge window stays a contract constant (bound
finalisation in-memory only). No new Python dependency (web3 8.0.0 middlewares, `rlp`, `eth_keys` already installed);
no new npm dependency (OZ is vendored, not installed).

| Acceptance test (outline above) | Result |
|---|---|
| Full demo flow on Besu, same scores as in-memory | **pass** — identical output except the contract address; gas identical except −12 on one commit (sender-dependent hash) |
| ERC-20 balance after finalise = net-saving credits; ERC-721 with correct root | **pass** — in-memory and on Besu; certificate JSON byte-identical to `core/certificate.py`; gap 992 bps with a finalised bound |
| Default in-memory demo and parity tests unchanged | **pass** — seed-7 output = RUN_GUIDE.md; V1/V2/PriceMarket/Oracle artifacts IDENTICAL |
| Measured gas and block times on Besu vs in-memory | V1 flow 9,576,561 vs 9,576,573 gas; 32.3 s / 16 blocks vs 7.9 s; ≈ 2 s per confirmation (block period) |
| Optional validator add/remove vote | **pass** — added in 9.5 s, removed in 11.5 s |

E3: 4 Phase 5 attack rows executed and defended (unauthorised mint, double certificate, mint after admin renounced,
soulbound transfer). E1: PoA node term in `poa_node_term.csv` ([VERIFY] grid). E6: real when Besu is opted in.
Smoke harness NOT RUN rows 6 → 2. Details: README §18.

---

## Phase 6 — Evaluation

**Goal.** Produce the final, defensible evidence.

**Deliverables.**
- `experiments/` — scripted experiment matrix (instance sizes × solvers × weights × seeds × data
  snapshots), all outputs in `results/eval/` with run manifests (seeds, hashes, git commit).
- **Net carbon after chain overhead** with sensitivity sweep over `energy_wh_per_million_gas` and chain
  carbon intensity (in-memory vs Besu PoA vs public-chain estimates); break-even workload size.
- **Gas limits**: largest instance that fits one block / one epoch; scaling plots.
- **Full attack suite**: over-capacity, copycat, no-show, malformed, lying oracle signer(s), false
  bound, griefing challenger, replay — table of outcome + slashed amount.
- Live dashboard (Streamlit) connected to the Besu network.
- Final report figures (`demo/make_figures.py` extended or `experiments/figures.py`).

**Acceptance tests.**
- One command regenerates every figure and table in the report from frozen data.
- Every attack in the suite has a passing test asserting its expected outcome.
- Report numbers are traceable to a manifest file.

**Dependencies.** Phases 1–5.

**Risks.** Overhead model parameters dominate the net result — present as a sensitivity range, not a
point estimate; time budget for large experiment matrices.

**Honest-claims note.** Report net savings as ranges with stated assumptions; report solver results
with variance across seeds; state every place classical methods match or beat quantum(-inspired) ones.

---

## Stretch — Proof-of-Useful-Work lab

**Goal.** Explore blocks that carry QUBO solutions (consensus work = scheduling work).

**Deliverables.** `lab/pouw/` — toy chain or Besu plugin prototype where block validity requires a
QUBO solution beating a threshold; analysis of difficulty adjustment and verification cost.

**Acceptance tests.** Toy chain produces and validates blocks; invalid/weak solutions rejected.

**Dependencies.** Phase 2 QUBO builder.

**Risks.** Security of PoUW is an open research problem (solution reuse, precomputation, non-uniform
hardness); easily scope-creeps.

**Honest-claims note.** Lab experiment only — no claim that it is a secure consensus mechanism.

---

## Methodology rules (summary)

| Rule | Enforced by |
|---|---|
| Off-chain solve / on-chain verify | Contract design review; no search loops in Solidity |
| Integer parity Python = Solidity | `tests/test_parity.py`, extended per phase |
| Honest labels (SA classical; SQA/SB quantum-inspired; QAOA quantum, simulated) | Solver `label` field; report review |
| Contract-fixed baselines | `baselineSchedule()` on-chain |
| Net not gross carbon | `finalize(overheadUg)`; Phase 6 sensitivity |
| Reproducibility | Seeds, instance hashes, frozen data snapshots with SHA-256, run manifests |

## Full Phase 6 results (2026-11-23)

Report: [FINAL_REPORT.md](FINAL_REPORT.md) (every number with its source file; `report_pack/key_numbers.json`).
`run_all --profile lite` with Besu up: 1,717.6 s, 0 NOT RUN rows (D3: the lite profile covers the planned grid; no
separate full profile). E1 net saving only as ranges ([VERIFY] grid): all 18 flows net-positive at 1 Wh/Mgas, none
at 100 Wh/Mgas × 400 g/kWh once the on-chain market is counted; PoA node term 0.008–13,440 g per epoch. E2 `publish`
≈ 748 k + 82.6 k·n gas (≈ 354 tasks at 30 M). E3 28/29 executed attacks defended (+ 4 documented assumptions). E4 see
Phase 1 results above (real, D1) and README §14 (synthetic). E5 (Phase 2 tables): P(opt) at 256 evaluations SB 0.99,
SQA 0.91, SA 0.81, simulated QAOA 0.62–0.72. E6 Besu: identical outcomes, ≈ 2 s confirmation per tx. Dashboard: 3 new
tabs (Live tab skipped, D3). Tests: 152 passed, 6 skipped (opt-in); Besu opt-in 4 passed.
