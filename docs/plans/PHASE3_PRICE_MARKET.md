# Phase 3 — On-chain price market (plan)

- **Status:** DONE (2026-11-19) — approved by the user's "build Phase 3 now, exactly as planned". As-built
  results, gas table and commits: `docs/PROJECT_PLAN.md` → "Phase 3 results"; README §15.
- **Planned:** 2026-11-13
- **Parent:** `docs/PROJECT_PLAN.md` → Phase 3
- **Invariant:** `CarbonScheduleMarket.sol` and `chain/build/CarbonScheduleMarket.json` stay byte-identical,
  so the default demo (whose overhead line includes deploy gas) is unchanged.

## Prerequisites

| # | Prerequisite | Owner | Status |
|---|---|---|---|
| P1 | **Working Node.js** for solc-js (README §9.3 option B). `node` currently resolves to `C:\nvm4w\nodejs\node.ps1` and prints no version. Fix: `nvm install 20`, `nvm use 20`, check `node --version`. | user | done (Node v20.20.2 via nvm-windows) |
| P2 | Toolchain check: recompile the **unchanged** `CarbonScheduleMarket.sol` with `chain/compile.js` and require byte-identical bytecode + ABI vs the committed artifact (`0.8.24+commit.e11b9ed9.Emscripten.clang`). Stop and report if different. | Claude | done: IDENTICAL |
| P3 | Case study complete | — | done |
| P4 | Answers to the open decisions below | user | done (2026-11-17, recommendations) |
| P5 | Phase 2 | — | optional (QAOA could solve sub-problems; not needed) |

No alternative compiler (e.g. py-solc-x / native solc) will be used, because §9.3 is required exactly.

## Open decisions

1. Separate **`PriceMarket.sol`** with the existing contract byte-identical (recommended), or extend
   `CarbonScheduleMarket.sol` (changes the default demo's overhead line; RUN_GUIDE.md must be updated)?
2. Step schedule **fixed at `openMarket`** (recommended) or on-chain `isqrt`?
3. ~~Order of phases relative to Phases 1, 2~~ — resolved, see below.

## Decisions (approved)

Recorded 2026-11-13.

- **Open decision 3 — resolved (build order):** Phase 3 is built after Phase 2, Phase 6-lite and Phase 1,
  and before Phases 4 and 5. Full order: Phase 2 → Phase 6-lite → Phase 1 → Phases 3, 4, 5 → full Phase 6.
- Open decisions 1 (separate `PriceMarket.sol` vs extending) and 2 (fixed step schedule vs on-chain
  `isqrt`) are **still open**. Prerequisite P1 (working Node.js) is unchanged.

Recorded 2026-11-17 (user asked to build Phase 3 now, "exactly as planned").

- **Build order changed:** Phase 3 is built now, before Phase 1 (which waits for data downloads).
  Order: Phase 2 → Phase 6-lite → **Phase 3** → Phase 1 → Phase 4 → Phase 5 → full Phase 6.
- **Decision 1:** separate `PriceMarket.sol`; `CarbonScheduleMarket.sol` and its artifact stay byte-identical
  (the plan's recommendation).
- **Decision 2:** step schedule fixed at `openMarket` (the plan's recommendation; no on-chain `isqrt`).
- **P1 done:** Node v20.20.2 via nvm-windows. **P2 done:** `node chain/compile.js --check` (solc-js
  `0.8.24+commit.e11b9ed9.Emscripten.clang`, optimizer 200 runs, viaIR, paris) reproduces
  `CarbonScheduleMarket.json` bytecode and ABI exactly.

---

## 1. Key design: separate `PriceMarket.sol`, `CarbonScheduleMarket.sol` untouched

- Any change to `CarbonScheduleMarket.sol` changes its deploy gas, which is counted in the chain overhead
  (`demo/pipeline.py:137`), so `Chain overhead ≈ 1.8681 g` would change.
- New `chain/contracts/PriceMarket.sol`, linked to a `CarbonScheduleMarket` address and epoch; reads the
  upper bound from the existing external view `summary(epochId).bestScore`.
- Existing artifact, ABI, tests and seed-7 output stay byte-identical. PROJECT_PLAN.md already allows this.

| On-chain (new) | Off-chain |
|---|---|
| Store per-round prices λ | Solving each workflow's priced sub-problem (exact, SQA, QAOA…) |
| Score each submitted workflow assignment at current λ | Repair into a feasible schedule (UB still from existing commit-reveal) |
| Keep the **minimum** value per workflow per round | |
| Close round: dual value g(λ), per-region loads, integer price update | |
| Track best LB over **complete** rounds (every workflow submitted ≥ once) | |
| `certifiedGapBps` = (UB − LB)·10 000 / UB, UB from linked contract | |

## 2. Integer arithmetic (defined once, mirrored exactly)

Python mirror `core/market_int.py` (pure integer, no web3). Existing `core/market.py` (float) unchanged.

- **`workflowValue`:**
  V_w(x, λ) = Σ_{j∈w} [w_c·E_j·ci[x_j]·1000 + w_p·E_j·price[x_j] + λ[x_j]·cpu_j]
            + Σ_{edges in w, x_a≠x_b} [w_c·⌊vol·net·(ci_a+ci_b)/2⌋ + w_p·vol·egress]   (`uint256`).
  At λ = 0, Σ_w V_w = `CarbonScheduleMarket.evaluate(x).score` exactly (tested across contracts).
- **`dualValue`:** g = Σ_w min V_w − Σ_d λ_d·cap_d (`int256`; can be negative — round 3 of seed 7 was).
- **`nextPrices`** (public pure): λ_d ← max(0, λ_d + tdiv(step_k · (load_d − cap_d) · m, Σcap)).
  **Parity hazard:** Solidity signed division truncates toward zero, Python `//` floors toward −∞. Python
  uses explicit `tdiv`; dedicated fuzz test with negative imbalances.
- **Step schedule:** `uint256[] steps` fixed and stored at `openMarket`; default computed off-chain as
  round(S₀·scale/√(k+1)). Committed before any round (owner can't steer prices), no on-chain sqrt, no extra
  parity surface. Alternative: on-chain `isqrt` with `math.isqrt` mirror (open decision 2).
- **Units:** λ in score units per core (integer). Overflow bounds documented (products < 2¹²⁸).

## 3. Contract interface (single file, no dependencies)

```solidity
openMarket(csm, epochId, m, ci[], price[], cap[], cpu[], energy[], edgeJ[], edgeK[], edgeVol[], params[4],
           wfTaskStart[], wfEdgeStart[], steps[])            // owner; validates contiguity + bounds
submit(marketId, w, uint8[] xw)                              // anyone; keeps min V_w for current round
submitBatch(marketId, uint8[] x)                             // anyone; whole relaxed assignment, saves 21k/tx
closeRound(marketId)                                         // owner; dual value, loads, price update, event
workflowValue(marketId, w, xw, lam[]) view                   // parity surface
dualValueOf(marketId, x, lam[]) view                         // parity surface
nextPrices(lam[], loads[], cap[], step, m) pure              // parity surface
certifiedGapBps(marketId) view / gapBps(ub, lb) pure         // parity surface
prices(marketId) / roundInfo(marketId, k) / bestLowerBound(marketId) views
```

- **Instance data duplicated:** the existing contract has no getters for cpu/capacity/energy; adding them
  changes its bytecode. Owner supplies the data again; a cross-contract test checks agreement (Σ V_w at
  λ = 0 = `evaluate`). On-chain enforcement belongs to Phase 4.
- **Workflow layout:** tasks and edges contiguous per workflow (generator already does this; Phase 1 loader
  will too). `openMarket` reverts on any edge crossing a workflow boundary.

## 4. Python side

| File | Contents |
|---|---|
| `core/market_int.py` | `workflow_value`, `dual_value`, `next_prices`, `tdiv`, `gap_bps`, `default_steps`, `exact_workflow_min`, `run_market_int` |
| `chain/price_market.py` | web3 wrapper: deploy, open, submit, submitBatch, closeRound, views; gas per tx. `chain/client.py` untouched apart from at most a shared deploy helper. |
| `experiments/onchain_market.py` + `config/onchain_market.yaml` | seed 7: CSM flow → PriceMarket 25 rounds with honest exact submitters → gap. Writes `results/onchain_market/{rounds.csv, gas.csv, summary.json}` |
| `chain/compile.js` | reproducible §9.3-B compile of both contracts |
| `chain/build/PriceMarket.json` | new artifact; `CarbonScheduleMarket.json` unchanged (tested) |

Default `demo/pipeline.py` and dashboard not wired up in this phase.

## 5. Gas measurement

From receipts on the in-memory EVM, reported in `gas.csv` and PROJECT_PLAN.md: `openMarket` (once);
`submit` by workflow size (3, 4, 5, 6 tasks); `submitBatch` (39 tasks); `closeRound`; **total per round**;
**total for 25 rounds**; share of the 30 M block gas limit; **market carbon overhead** at the existing
sensitivity parameters (0.5 Wh/Mgas, 400 g/kWh) vs the 428 g net saving. Only measured numbers reported;
if overhead is large, fewer rounds or batching are the levers.

## 6. Tests: `tests/test_price_market.py`

1. `workflowValue` parity: 50 random (w, x_w, λ), exact integers.
2. `dualValueOf` parity incl. negative results.
3. `nextPrices` parity: 200 fuzzed cases, positive/negative imbalances (tdiv).
4. `gapBps` parity incl. LB ≤ 0 and LB = UB.
5. Cross-contract: at λ = 0, Σ_w V_w = `CarbonScheduleMarket.evaluate(x).score`.
6. **Full-run parity:** 25 on-chain rounds = `run_market_int` (λ path, g per round, loads, best LB).
7. **Weak duality:** on-chain best LB ≤ every revealed feasible score; tiny instance (2 workflows × 3
   tasks): ≤ brute-force optimum.
8. Min-keeping: inflated submission doesn't raise V_w when an honest minimum exists.
9. **Documented vulnerability:** a lone dishonest submitter for a workflow can inflate the LB above the
   true optimum — shows why Phase 4 fraud proofs are needed.
10. Incomplete round not counted toward best LB.
11. Validation reverts: non-contiguous workflow, wrong lengths, region ≥ m, out-of-order close, non-owner
    `closeRound`.
12. Artifact guard: `CarbonScheduleMarket.json` unchanged; recompile of unchanged source reproduces it.
13. Existing 8 tests unchanged (~20 total, plus Phase 2's if it lands first).

## 7. Honest claims

- "On-chain price rounds with an on-chain-computed Lagrangian bound, **certified assuming each workflow's
  minimum was submitted by at least one honest party**" — until Phase 4 adds fraud proofs.
- The contract doesn't solve or repair; it scores and updates prices.
- Integer bound may differ slightly from the float bound; both valid; report both.

## 8. After approval (and Node works)

1. Toolchain check (P2). 2. Implement. 3. Recompile (§9.3-B), commit `PriceMarket.json`.
4. pytest, `demo.run_demo` (must match RUN_GUIDE.md), experiment.
5. Update README §7 and §9.3 (compile script), PROJECT_PLAN.md status and gas table.
6. Commit, without pushing.
