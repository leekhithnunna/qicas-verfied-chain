# Phase 2 — Quantum layer (plan)

- **Status:** **DONE** (commits `554756d`..`f6c9633`; 21 tests pass; default demo unchanged; results in
  `docs/QUANTUM_NOTES.md` and "Phase 2 results" below). All decisions resolved — see "Decisions (approved)".
- **Planned:** 2026-11-13
- **Parent:** `docs/PROJECT_PLAN.md` → Phase 2
- **Invariant:** `core/solvers/__init__.py`, the market, the contract and `config/demo.yaml` are not
  changed; the default demo output stays identical.

## Prerequisites

| # | Prerequisite | Owner | Status |
|---|---|---|---|
| P1 | Case study complete | — | done |
| P2 | numpy available | — | done (numpy 2.5.4 in `.venv`, via pandas) |
| P3 | Answers to the open decisions below | user | done (all resolved) |
| P4 | Phase 1 | — | **not required**: benchmarks run on synthetic instances; Alibaba DAGs plug in later |

Note: the "no heavy dependencies" rule is **not** in AGENTS.md; it is in `VSCODE_AGENT_PROMPT.md:43`.
AGENTS.md has only rules 1–8. This phase adds a proper dependency rule to AGENTS.md (§1.3).

## Decisions (approved) — all DONE

Recorded 2026-11-13; implemented and closed out with Phase 2.

1. **Dependencies — DONE: numpy only (option A)**, with our own Nelder–Mead and SPSA in
   `core/subproblem/optim.py`. No SciPy, Qiskit or PennyLane.
2. **Budget unit — DONE: energy evaluations / shots**, wall-clock as a secondary column labelled
   "simulator/CPU time, not indicative of hardware".
3. **Order — DONE: Phase 2 built before Phase 1.** Full order: Phase 2 → Phase 6-lite → Phase 1 →
   Phases 3, 4, 5 → full Phase 6. Phase 6-lite is now the current phase in `docs/PROJECT_PLAN.md`.

## Phase 2 results

From `results/quantum/summary.csv` and `results/quantum/classical_vs.csv` (both committed as evidence;
full analysis in `docs/QUANTUM_NOTES.md`). 324 test sub-problems × 30 seeds, budgets B ∈ {16, 64, 256}
energy evaluations / shots. P(opt) = share of runs that hit the brute-force optimum.

| Method | Label | P(opt) B=16 | B=64 | B=256 |
|---|---|---:|---:|---:|
| random | sanity baseline | 0.109 | 0.348 | 0.619 |
| SA | classical | 0.222 | 0.574 | 0.811 |
| SQA | quantum-inspired | 0.118 | 0.562 | 0.912 |
| SB ballistic / discrete | quantum-inspired | 0.862 / 0.721 | 0.962 / 0.957 | 0.988 / 0.994 |
| XY-QAOA ring / complete (shots) | quantum algorithm, classically simulated | 0.082 / 0.099 | 0.262 / 0.312 | 0.624 / 0.724 |
| *XY-QAOA ring / complete, ideal angles* | *optimistic upper bound only* | *0.927 / 0.965* | *0.973 / 0.990* | *0.981 / 0.998* |

- Classical SA strictly beats shot-based XY-QAOA on most sub-problems at every budget (ring: 96 / 84 / 69 %;
  complete: 83 / 74 / 50 %); shot-based QAOA is at or below random at B = 16 and 64.
- SB (quantum-inspired) has the highest P(opt) among budget-honest methods; SQA overtakes SA only at B = 256.
- **The complete XY mixer beat the ring mixer** at every budget (shots and ideal); it uses 1.5× the XY
  gates per layer, and at equal gate count the two are about the same.
- QAOA-ideal is reported only as an **optimistic upper bound** (angle-finding cost not charged).
- QAOA ran on a classical simulator; no hardware. **No quantum advantage or speed-up is claimed.**

---

## 1. Dependency choice

### 1.1 Installed
`numpy 2.5.4` (via pandas). SciPy, Qiskit, PennyLane not installed.

### 1.2 Recommendation: numpy only, no new packages
- Each task gets a register of m qubits that is one-hot ("task j is in region d").
- The XY mixer, (XᵢXⱼ + YᵢYⱼ)/2 within each register, preserves the number of 1s in the register.
- Starting from a one-hot state, the circuit stays inside the **feasible subspace** of size mᵗ.

For 3–5 tasks × 4 regions (12–20 qubits) that subspace has 64–1,024 states, against 2¹²–2²⁰ for the full
statevector. Simulating inside the subspace is **exact**:
- **Cost layer:** diagonal phase e^(−iγE(x)) on each of the mᵗ feasible states.
- **Mixer layer:** in the subspace each register's XY mixer is an m×m hopping matrix: cycle graph for the
  **ring** mixer, complete graph for the **complete** mixer. Applied as hardware would: edges split into
  groups of disjoint pairs (ring, m=4: {01, 23} then {12, 30}; complete: 3 perfect matchings). Pairs in a
  group commute, so each group's exponential is an exact 2×2 rotation, applied per task by reshaping the
  state into a t-dimensional tensor.
- **Angle optimisation (no SciPy):** Nelder–Mead (~60 lines numpy) for exact expectations, SPSA (~30
  lines) for shot-noise estimates; depth grown with INTERP for p = 1…3.

| Option | Size / dependencies | Gives | Verdict |
|---|---|---|---|
| **A. numpy (present)** | 0 new packages | exact subspace simulation; own optimisers | **Recommended** |
| B. A + SciPy | ~40 MB, one wheel | tested COBYLA / Nelder–Mead | fallback |
| C. Qiskit / Aer | ~200 MB+, many deps, API churn | hardware path, noise | not now; later behind a flag in `experiments/` only |
| D. PennyLane | autograd, autoray, … | gradient angle training | not justified |

The subspace trick works only because the mixer preserves feasibility, so a test must prove it matches a
full 2ⁿ simulation (test 1, §5).

### 1.3 AGENTS.md change (proposed rule 9)
> *Dependencies:* `core/` may use the standard library and numpy only. Any new runtime dependency needs a
> justification in `docs/PROJECT_PLAN.md` and must not be imported on the default demo path. Quantum SDKs
> (Qiskit, PennyLane) are allowed only in `experiments/`, behind a flag.

Rule 5 extended: greedy/SA classical; SQA/SB quantum-inspired; QAOA **quantum algorithm, classically
simulated**. Add `numpy>=1.26` to `requirements.txt` explicitly.

## 2. Sub-problem and sizes

The market's priced per-workflow problems (`core/market.py::_solve_workflow`). Minimise
Σᵢ (lin[i][d] + λ_d·cpuᵢ) + Σ_edges pair[i,k][dᵢ][d_k].
No capacity constraint (prices stand in for it), so feasibility = one-hot per task, preserved by the XY
mixer by construction.

| Sub-problem | Qubits | Feasible states | Exact optimum |
|---|---:|---:|---|
| 3 tasks × 4 regions | 12 | 64 | brute force |
| 4 tasks × 4 regions | 16 | 256 | brute force |
| 5 tasks × 4 regions | 20 | 1,024 | brute force |
| optional: 6 tasks × top-3 regions (pruned) | 18 | 729 | brute force (+ check whether pruning removed the optimum) |

Instances: workflows of 3–5 tasks from the synthetic generator (tuning seeds 100–109, test seeds 0–19);
prices λ from market rounds 1, 13 and 25. Sub-problem set frozen and hashed into a manifest; Phase 1
Alibaba DAGs plug in as a second set later.

**Honest framing:** at this size brute force solves every sub-problem in milliseconds. The benchmark
measures **solution quality per unit of sampling budget**, not practical usefulness, and not quantum
advantage.

## 3. Fair comparison protocol

| Method | Label | Feasibility |
|---|---|---|
| exact (brute force) | reference | — |
| random feasible sampling | sanity baseline | structural |
| SA | classical | structural (one-hot moves) |
| SQA | quantum-inspired | structural |
| SB (ballistic + discrete) | quantum-inspired | **penalty-based**; raw feasibility rate reported before argmax decoding |
| QAOA-XY, ring and complete | quantum algorithm, classically simulated | structural (proved by test) |

**Same instances and seeds:** every method on every sub-problem, seeds 0–29, own
`numpy.random.Generator(seed)` / `random.Random(seed)`.

**Same budget — primary unit is energy evaluations, not wall-clock** (Python loops vs numpy vs an
exponential-cost simulator are not comparable, and simulator time says nothing about hardware). Budgets
B ∈ {16, 64, 256}, enforced by a counter in `SubProblem`; exceeding it fails the run.

| Method | Counts against B |
|---|---|
| SA / SQA | every evaluated proposed move (all replicas) |
| SB | every evaluated decoded readout |
| random | every sample |
| **QAOA-shots** | every shot, **including** expectation-estimation shots during angle optimisation |
| **QAOA-ideal** | only final readout shots; angles from exact expectations — optimistic upper bound labelled "ideal", reported separately, never in the same column |

Secondary: wall-clock, labelled "simulator/CPU time, not indicative of hardware".

**Tuning:** same small grid (≤ 12 settings) per method, on tuning instances only; frozen before test.

**Metrics:** P(optimum); normalised gap (E − E*)/(E_max − E*); feasibility rate (SB); mean/median over
seeds with 95 % bootstrap CIs (numpy); table of where classical methods match or beat the others.

**Open design questions** (sub-experiments, written up in `docs/QUANTUM_NOTES.md`):
1. Ring vs complete mixer: quality vs p, plus gate count (2 vs 3 pair groups per register).
2. Parameter reuse across price rounds: reuse round k's angles at k+1 vs fresh; evaluations saved vs
   quality lost.
3. Warm start from SQA: each register starts as √(1−ε)|SQA⟩ + √(ε/(m−1))·Σ(other regions), ε ∈ {0.1, 0.3},
   vs uniform. Report if it gets stuck on the SQA answer.

**Use inside the market (experiment only):** QAOA may supply only the **upper bound** (answer repaired to
feasible). The **lower bound stays exact** — a sub-optimal sub-problem answer invalidates the Lagrangian
bound. Enforced in code (`lower_bound_solver="exact"` not configurable) and in the notes.

## 4. Files

| File | Contents |
|---|---|
| `core/subproblem/model.py` | `SubProblem` from (Instance, workflow, λ): integer-scaled linear/pairwise terms, `energy()`, evaluation counter |
| `core/subproblem/exact.py` | brute force (cross-checked vs `market._solve_workflow`) |
| `core/subproblem/qubo.py` | QUBO / Ising with one-hot penalty (for SB and docs) |
| `core/subproblem/sa.py`, `sqa.py` | sub-problem kernels, same move rules/schedules as `core/solvers/` (existing files untouched) |
| `core/subproblem/sb.py` | ballistic and discrete simulated bifurcation |
| `core/subproblem/qaoa_xy.py` | subspace simulator, ring/complete mixers, INTERP, sampling, warm start |
| `core/subproblem/optim.py` | Nelder–Mead and SPSA (numpy) |
| `core/subproblem/__init__.py` | `SUBSOLVERS` and `LABEL` |
| `experiments/quantum_benchmark.py` + `config/quantum_bench.yaml` | runner → `results/quantum/{raw.csv, summary.csv, manifest.json, fig_*.png}` |
| `docs/QUANTUM_NOTES.md` | method, protocol, design-question results, honest-claims section |
| `tests/test_quantum.py` | §5 |
| `AGENTS.md`, `CLAUDE.md`, `requirements.txt`, `docs/PROJECT_PLAN.md` | rule 9 + labels, numpy pin, status |

## 5. Tests (`tests/test_quantum.py`, deterministic)

1. **Subspace = full statevector:** test-only numpy full-2ⁿ simulator applying XX+YY gates locally. On
   (2 tasks × 3 regions = 6 qubits) and (3 × 4 = 12 qubits), random angles, p = 2, both mixers: one-hot
   probabilities match (tol 1e-10); leakage outside the feasible subspace < 1e-12.
2. Mixer unitary; pairs within a group commute; β = γ = 0 ⇒ uniform over feasible states.
3. **Energy = scoring:** single-workflow instance, λ = 0: `SubProblem.energy(x) == evaluate(inst, x).score`
   on all mᵗ assignments (exact ints). With integer λ equals `market._solve_workflow`'s value.
4. Brute-force optimum = `market._solve_workflow` optimum on sub-problems from seeds 0–4.
5. QUBO energy = `SubProblem.energy` on every one-hot vector; penalty > 0 on non-one-hot.
6. **Budget enforced:** each sub-solver uses ≤ B evaluations; exceeding raises.
7. Determinism by seed for every sub-solver.
8. QAOA-ideal p = 3: P(opt) ≥ uniform-random P(opt) on a fixed 12-qubit case (sanity floor, not a claim).
9. Benchmark smoke run (2 sub-problems × 2 seeds × B = 16) < 15 s, expected CSV columns.
10. Existing 8 tests unchanged → 18 total.

## 6. After approval — DONE

1. Implement. 2. pytest (21 passed), `demo.run_demo` (matches RUN_GUIDE.md), full benchmark.
3. Update docs and PROJECT_PLAN status. 4. Commit, without pushing. All four steps are complete.
