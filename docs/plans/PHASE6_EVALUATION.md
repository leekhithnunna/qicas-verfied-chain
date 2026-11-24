# Phase 6 — Evaluation (plan)

- **Status:** **Full Phase 6 DONE 2026-11-23** (E1–E6 incl. E4 real data with D1 + 1 Wh floor sensitivity, E5 from
  Phase 2, E6 on Besu; fig5–fig11 + fig8r/fig9r; tabs On-chain market, Oracle & challenges, Tokens — Live skipped per
  D3; `docs/FINAL_REPORT.md`; README §19). Lite profile used for the full run (D3; it covers the planned grid).
  Decisions approved 2026-11-13. **Phase 6-lite DONE 2026-11-17** (harness, E1–E4 on synthetic
  data, fig5–fig9, dashboard refactor + Evaluation tab; results in README §14 and PROJECT_PLAN.md). Full Phase 6
  (real data, Phases 3–5 rows, E5–E6, other new tabs, `FINAL_REPORT.md`) is built last.
  As built: profiles are `smoke | lite` (`config/eval.yaml`); the sidebar config selector waits for Phases 1/5.
- **Planned:** 2026-11-13
- **Parent:** `docs/PROJECT_PLAN.md` → Phase 6
- **Invariant:** existing fig1–4 (`demo/make_figures.py`), the 5 existing dashboard tabs, the default
  config + in-memory chain, and the 8 existing tests are unchanged.

## Prerequisites

| # | Prerequisite | Needed for | Status |
|---|---|---|---|
| P1 | Case study | Phase 6-lite (E1–E4 on synthetic data) | done |
| P2 | Phase 1 (real data) | E4 on real data | pending approval + user downloads |
| P3 | Phase 2 (quantum) | E5 | pending approval |
| P4 | Phases 3–4 (market, oracle, fraud proofs) | full E1, E2, E3 | pending approval + Node.js |
| P5 | Phase 5 (Besu, tokens) | E6, PoA node term in E1, Live tab | **done 2026-11-23** (E6 opt-in: `QICAS_BESU=1` + network up; E1 `poa_node_term.csv`; E3 Phase 5 rows executed) |
| P6 | Sources for overhead parameter ranges | E1 | pending (open decision 2) |

Each experiment declares the phase it needs; if missing, it writes an explicit `NOT RUN — Phase X missing`
row and never skips silently.

## Open decisions

All three are resolved — see "Decisions (approved)" below.

1. Final report as a **new `docs/FINAL_REPORT.md`** (recommended) or overwrite `CASE_STUDY_REPORT.md`?
2. **Overhead parameter ranges:** sources for energy per gas (or per tx) and PoA node power? If none, use a
   wide illustrative grid labelled [VERIFY] and present results as sensitivity ranges only.
3. **What first:**
   - **(a) Phase 6-lite now (recommended):** E1–E4 on case-study code + synthetic data, plus the dashboard
     Evaluation tab; no Node, Docker or downloads needed; results fill in as phases land.
   - **(b)** Implement Phases 1–5 first, then full Phase 6 (needs: plan approvals for Phases 1–5,
     `nvm use 20`, Docker Desktop running, Phase 1 downloads).

## Decisions (approved)

Recorded 2026-11-13.

1. **Final report:** create a **new `docs/FINAL_REPORT.md` later** (at full Phase 6).
   **`docs/CASE_STUDY_REPORT.md` stays unchanged.**
2. **Overhead inputs:** there are **no sources** for gas-to-energy or node-power inputs. E1 uses a **wide
   illustrative grid marked [VERIFY]**, and all net-carbon results are presented as **ranges**, never as a
   single headline number.
3. **Phase 6 is split in two (option (a) adopted, sequenced):**
   - **Phase 6-lite** = E1–E4 on synthetic data plus the dashboard **Evaluation** tab. Built **second**,
     right after Phase 2.
   - **Full Phase 6** (real data, Phases 3–5 rows, E5–E6, other new tabs, `FINAL_REPORT.md`) is built
     **last**.
   - Full order: Phase 2 → Phase 6-lite → Phase 1 → Phases 3, 4, 5 → full Phase 6.

---

## 1. Experiments (`experiments/`, one runner, one manifest)

`experiments/run_all.py --profile full|smoke` → `results/eval/`, plus `manifest.json` with git commit,
config SHA-256s, data-snapshot SHA-256s, seeds, package versions, chain mode, experiments run/skipped (why).

| ID | Experiment | Needs | Output |
|---|---|---|---|
| **E1** | Net carbon vs overhead sensitivity | case study (lite); Phases 3–5 for full | `sensitivity.csv`, fig5, fig6 |
| **E2** | Gas vs instance size | case study (lite); Phases 3–5 for full | `gas_scaling.csv`, fig7 |
| **E3** | Attack suite | case study (lite); Phases 3–5 for full | `attacks.csv`, report table |
| **E4** | Solver comparison | Phase 1 for real data; synthetic now | `solvers.csv`, `solvers_summary.csv`, fig8, fig9 |
| E5 | Quantum sub-problem results (from Phase 2, not re-run) | Phase 2 | fig10 |
| E6 | Besu vs in-memory (from Phase 5) | Phase 5 | fig11 |

### E1. Net carbon vs overhead
- **Gas inputs:** case-study flow; market rounds (Phase 3); oracle + challenges (Phase 4); plus a
  **PoA node term** N validators × assumed W/node × hours/epoch (Phase 5).
- **Grid:** `energy_wh_per_million_gas` × `chain_ci_g_per_kwh` (40 / 400 / 700) × node power; values need
  sources **[VERIFY]** (open decision 2).
- **Outputs:** net-saving heatmap; **break-even workload size** (tasks for net saving > 0) per setting;
  overhead as % of gross saving.
- **Trade-off curve:** market rounds (5 / 10 / 25) vs certified gap and added overhead ("is a tighter bound
  worth its carbon?").
- **Per-task normalisation** of saving and overhead.

### E2. Gas vs instance size
- n ≈ 10, 20, 39, 80, 160, 320 tasks (2–64 workflows), 3 instance seeds each.
- Functions: `publish`, each `reveal`, `finalize`; Phase 3 `openMarket`, `submitBatch`, `closeRound`;
  Phase 4 `challenge`.
- Fit gas ≈ a + b·n + c·edges (numpy `polyfit`).
- **Largest n under the 30 M block gas limit** per tx (expect `publish` first: ~3.9 M at 39 tasks ⇒ roughly
  300 tasks; only measured numbers reported). Structural limits noted (m ≤ 255, `uint8` schedules).
- In-memory; one size spot-checked on Besu if up.

### E3. Attack suite
One script **executes** each attack and records the observed outcome; `tests/test_attack_suite.py` asserts
expected = observed per row.

| Layer | Attacks |
|---|---|
| Case study (now) | over-capacity, copycat, no-show, **malformed schedule** (new: bad length or region ≥ m), reveal in wrong phase, non-owner finalize, withdraw reentrancy |
| Phase 3 | inflated submission, incomplete round, validation reverts |
| Phase 4 | the oracle and bound attacks from the Phase 4 plan |
| Phase 5 | unauthorised mint, double certificate, minting after admin renounced |
| **Assumptions, not defences** | majority oracle collusion, no live challenger during the window, data source itself wrong |

Columns: attack, layer, expected, observed, attacker gas, stake/bond slashed, test name, status (defended /
documented assumption / NOT RUN). Assumption rows kept on purpose so the table doesn't overclaim.

### E4. Solver comparison
- **Real data:** `config/real_snapshot.yaml`, 10 Alibaba DAG samples × seeds 0–29.
- **Synthetic (runs now):** instance seeds 0–9 × solver seeds 0–29.
- Solvers: greedy, SA, SQA, dual-market.
- **SA vs SQA budgets:** **move-matched** (SA sweeps·n = SQA sweeps·P·n — fixes the case-study weakness)
  and default settings, reported separately.
- Weight presets: carbon-priority, balanced, cost-priority.
- Metrics: score, carbon, cost, certified gap to LB, feasibility, CPU time.
- Statistics: mean ± 95 % bootstrap CI; **paired** bootstrap of SA−SQA per instance (numpy, no SciPy);
  win counts.
- Report rule: table of "where classical matches or beats quantum-inspired".

## 2. Dashboard (`app/`)

First split `app/dashboard.py` (147 lines) into `app/tabs/*.py`; **existing 5 tabs behave identically**;
`config/demo.yaml` + in-memory stays default. Sidebar gets a **config selector** (demo / real_snapshot /
besu); chain mode adds `besu`.

| Tab | Contents |
|---|---|
| **Evaluation** | E1 heatmap with **live sliders** for the two overhead parameters (recomputed from stored gas, no chain), E2 gas-vs-size with block-limit line, E3 attack table with layer/status filters, E4 comparison with CIs and weight preset |
| On-chain market (Phase 3) | λ per round, LB per round, gas per round |
| Oracle & challenges (Phase 4) | reports per zone, median + spread, claim → challenge → finalise timeline |
| Tokens (Phase 5) | ERC-20 balances, retirements, decoded certificate `tokenURI` JSON |
| Live (Phase 5, optional) | polls Besu RPC for blocks/events; shows validators |

Missing inputs show "not available — Phase X". Built following the Streamlit and dataviz skills: one
palette, readable in light and dark themes, same look as the report figures.

## 3. Report figures

`experiments/figures.py` → **fig5–fig11** from `results/eval/*.csv`, PNG (200 dpi) + SVG. fig1–4 unchanged.

## 4. Report and README

- **`docs/FINAL_REPORT.md` (new, recommended);** `CASE_STUDY_REPORT.md` stays as the case-study record.
  Methods of Phases 1–5 and E1–E6; **threats-to-validity** (simulated chain, assumed overhead parameters,
  trace sampling, single snapshot hour, simulator-only quantum results); every number with a source note
  (CSV/manifest); unverified citations stay [VERIFY].
- **README:** §11 updated — **resolved:** 1 real data, 2 Alibaba workload, 6 on-chain market; **mitigated:**
  3 oracle (trust-minimised, honest majority); **remaining:** 4 SQA not quantum hardware, 5 overhead model
  an estimate. New §14 "Evaluation" (commands + results summary).
- **RUN_GUIDE.md:** evaluation commands. **PROJECT_PLAN.md:** status per phase. **CLAUDE.md:** `run_all`.

## 5. Tests (default pytest stays offline and fast)

1. `test_eval_smoke.py`: `run_all --profile smoke` < 60 s, every CSV with expected columns.
2. Reproducibility: smoke profile twice ⇒ identical CSVs except time columns; same manifest hashes.
3. `test_attack_suite.py`: every row expected = observed; missing-phase rows must say `NOT RUN`, never
   `defended`.
4. Figures render from fixture CSVs (headless matplotlib).
5. Dashboard import smoke test: every tab module imports and renders on fixture data.
6. Existing 8 tests unchanged; `demo.run_demo` matches RUN_GUIDE.md.

Full profile (est. 30–90 min, mostly E4 seeds and E2 large instances) runs separately, not in pytest;
runtime recorded in the manifest.

## 6. Honest-claims rules for the final report

- Net saving as **ranges**, never a headline number without its assumptions.
- Every solver claim with a CI and a fixed compute budget; say plainly where classical wins.
- Gas is not energy: PoA energy is dominated by always-on nodes, not gas.
- E2 size limits stated as limits of the current design.
- QAOA results from classical simulation; no advantage claim.

## 7. After approval

1. Harness + experiments that can run with the phases present. 2. Dashboard refactor + extension.
3. Figures. 4. pytest, `demo.run_demo`, `run_all --profile full`.
5. `FINAL_REPORT.md`; update README, RUN_GUIDE, PROJECT_PLAN, CLAUDE.md. 6. Commit, without pushing.
