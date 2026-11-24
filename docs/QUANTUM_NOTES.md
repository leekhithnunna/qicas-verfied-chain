# Phase 2 — Quantum layer: method, results, honest claims

Plan: `plans/PHASE2_QUANTUM.md`. Code: `core/subproblem/`, `experiments/quantum_benchmark.py`,
`config/quantum_bench.yaml`. Tests: `tests/test_quantum.py`. Raw outputs: `results/quantum/` (git-ignored,
regenerate with `python -m experiments.quantum_benchmark`, about 17 min on 4 worker processes).

## 1. Labels (AGENTS.md rule 5)

| Method | Key | Label |
|---|---|---|
| brute force | `exact` | reference |
| random feasible sampling | `random` | sanity baseline |
| simulated annealing | `sa` | **classical** |
| simulated quantum annealing (path-integral Monte Carlo) | `sqa` | **quantum-inspired** (runs on a classical computer) |
| simulated bifurcation, ballistic / discrete | `sb_ballistic`, `sb_discrete` | **quantum-inspired** (runs on a classical computer) |
| QAOA, XY ring / complete mixer, shot-based angle tuning | `qaoa_ring`, `qaoa_complete` | **quantum algorithm, classically simulated** |
| same, angles from exact expectations | `qaoa_ring_ideal`, `qaoa_complete_ideal` | quantum algorithm, classically simulated — **optimistic upper bound**, reported separately |

No run used quantum hardware. Nothing here shows or claims quantum advantage.

## 2. Method

**Sub-problems.** These are the per-workflow priced problems of the dual-price market
(`core/market.py::_solve_workflow`): minimise Σᵢ(linᵢ(dᵢ) + λ_d·cpuᵢ) + Σ_edges pair(d_a, d_b). There is no
capacity constraint, so the only feasibility rule is one-hot. The set uses workflows of 3–5 tasks × 4 regions
(12–20 qubits, 64–1,024 feasible states), from synthetic instances (test seeds 0–19; tuning seeds 100–109)
with integer-rounded prices from market rounds 1, 13 and 25. After deduplication there are
**324 test sub-problems**. The set is frozen and hashed in `manifest.json`.

**Budget.** Budget B ∈ {16, 64, 256} counts **energy evaluations**. `SubProblem` enforces it with a hard
counter: a method that exceeds it raises an error. This is the counted unit for each method:

| Method | Counted against B |
|---|---|
| random | every sample |
| SA / SQA | the start state(s) and every evaluated proposed move (all replicas) |
| SB | every decoded readout (one per trajectory) |
| QAOA-shots | every shot, **including** the shots used to estimate ⟨E⟩ during SPSA angle tuning |
| QAOA-ideal | only the final readout shots. Angle optimisation uses exact expectations, which are not counted |

**Fairness.** Every method runs on every sub-problem with seeds 0–29 at all three budgets (262,440 test
runs). Parameters were tuned per method and budget on 30 tuning sub-problems × 5 seeds, using a grid of at
most 12 settings and the lowest mean normalised gap as the criterion. They were frozen in `tuning.json`
before the test run. The normalised gap is (E − E*)/(E_max − E*). Each CI is a 95 % percentile bootstrap over
sub-problems (seeds on one sub-problem are correlated).

**QAOA simulation.** XY mixers keep each task register one-hot, so the state is simulated **exactly inside
the m^t feasible subspace**. Mixer edges are split into groups of disjoint pairs, as hardware would apply
them: ring = 2 groups, complete = 3 groups for m = 4. A test shows this equals a full 2ⁿ statevector
simulation built from Pauli matrices, with leakage < 1e-12. Angle optimisation is numpy-only: Nelder–Mead
with INTERP for the ideal variant, SPSA for the shot-based one.

## 3. Results (test set, 324 sub-problems × 30 seeds; `summary.csv`)

P(optimum) is the share of runs that return an exact optimum. Gap is the mean normalised gap, with the 95 %
CI in brackets.

| B | random (baseline) | SA (classical) | SQA (q-inspired) | SB-ballistic (q-inspired) | SB-discrete (q-inspired) | QAOA-ring (q-sim.) | QAOA-complete (q-sim.) |
|---:|---|---|---|---|---|---|---|
| 16 | 0.109 · 0.218 | 0.222 · 0.186 | 0.118 · 0.221 | 0.862 · 0.010 | 0.721 · 0.025 | 0.082 · 0.248 | 0.099 · 0.231 |
| 64 | 0.348 · 0.102 | 0.574 · 0.065 | 0.562 · 0.059 | 0.962 · 0.002 | 0.957 · 0.002 | 0.262 · 0.132 | 0.312 · 0.113 |
| 256 | 0.619 · 0.041 | 0.811 · 0.019 | 0.912 · 0.007 | 0.988 · 0.001 | 0.994 · 0.000 | 0.624 · 0.046 | 0.724 · 0.030 |

Each cell shows *P(opt) · gap*. Full CIs are in `summary.csv`, results by sub-problem size in
`summary_by_size.csv`, and figures in `fig_popt.png` and `fig_gap.png`.

Ideal-angle QAOA is reported separately because its angles come from uncounted exact expectations:

| B | QAOA-ring-ideal | QAOA-complete-ideal |
|---:|---|---|
| 16 | 0.927 · 0.004 | 0.965 · 0.002 |
| 64 | 0.973 · 0.001 | 0.990 · 0.000 |
| 256 | 0.981 · 0.001 | 0.998 · 0.000 |

**Where the classical method matches or beats the others** (`classical_vs.csv`, share of sub-problems where
SA's mean gap ≤ the other method's):

| B | vs random | vs SQA | vs QAOA-ring | vs QAOA-complete | vs SB (either) |
|---:|---:|---:|---:|---:|---:|
| 16 | 79 % | 80 % | 96 % | 83 % | 0 % |
| 64 | 73 % | 49 % | 84 % | 74 % | 4 % |
| 256 | 77 % | 45 % | 77 % | 65 % | 33 % |

**Simulator/CPU time per run (not indicative of hardware):** SA 0.2–1.7 ms, SQA 0.3–2 ms,
SB 9–36 ms, QAOA-shots 3–53 ms.

### Reading the results honestly
1. **Shot-based QAOA, the honest budgeted quantum variant, is no better than random sampling.** At B = 16
   and 64 it is at or below random. At B = 256 the ring mixer equals random (0.624 vs 0.619) and the complete
   mixer is ahead (0.724). Classical SA matches or beats QAOA-shots on 65–96 % of sub-problems. Angle
   tuning from shots costs evaluations that random or SA spend directly on candidate answers.
2. **Ideal-angle QAOA looks excellent only because it is not charged for its angle search.** One
   optimisation at p = 2 uses about 340 exact expectation calls. Every call is a weighted sum over **all** m^t
   energies, which is far more information than brute force needs. It is an optimistic upper bound, not a
   practical method.
3. **SB's lead comes partly from the budget unit.** The protocol counts SB's readouts only. Its internal
   dynamics (50–200 steps of a coupling-matrix product per trajectory) use the problem coefficients without
   being counted, just as an Ising machine would. SA and SQA pay one evaluation per move. So "SB beats SA per
   evaluation" is a statement about this accounting, not about one algorithm being better. In simulator time
   SB is about 5–80× slower than SA here,
   depending on budget and variant. SB's raw readouts are rarely one-hot (23–36 % at B ≤ 64; ≈ 0 % for
   ballistic at B = 256, which tuning set to 50 steps). Its answers depend on argmax decoding.
4. **SQA vs SA (both counted per move):** SA is better at B = 16, they are roughly level at 64, and SQA is
   better at 256 (0.91 vs 0.81 P(opt)). SA is better on 5-task sub-problems at B = 64 (`summary_by_size.csv`).
5. **Tuning caveats:** a few chosen settings lie on the edge of their grid (SA t0 = 4 at B = 256,
   SB-discrete ξ = 1.0). For QAOA-ideal at B = 256 every depth already reached gap 0 on the tuning set, so
   the tie-break picked p = 1. Wider grids could shift the numbers somewhat but would not change the
   ordering in point 1.
6. At this size **brute force solves every sub-problem in milliseconds**. All of the above measures
   solution quality per unit of sampling budget. It says nothing about practical usefulness, and nothing
   about quantum advantage.

## 4. Design questions (60 test sub-problems; `design_*.csv`)

These use QAOA-ideal with exact probabilities, so no sampling noise.

**Q1 Ring vs complete mixer vs depth.** These are the exact probability of an optimum and the expected
normalised gap. A uniform start has P(opt) = 0.007.

| p | ring P(opt) / ⟨gap⟩ | complete P(opt) / ⟨gap⟩ | XY gates (ring / complete) | mixer depth (ring / complete) |
|---:|---|---|---|---|
| 1 | 0.052 / 0.383 | 0.087 / 0.321 | 15.8 / 23.7 | 2 / 3 |
| 2 | 0.147 / 0.266 | 0.223 / 0.204 | 31.6 / 47.4 | 4 / 6 |
| 3 | 0.233 / 0.195 | 0.324 / 0.140 | 47.4 / 71.1 | 6 / 9 |

The complete mixer is better at equal p, but it costs 1.5× the gates. Its p = 2 result (47.4 gates, depth
6) roughly equals the ring at p = 3 (47.4 gates, depth 6): **at equal gate count the two are about the
same.**

**Q2 Re-using angles across price rounds (p = 2, 38 consecutive round pairs per mixer).**
- Ring: re-using round k's angles unchanged gives P(opt) 0.104, against 0.121 for fresh optimisation
  (about 340 expectation calls). Starting Nelder–Mead from the re-used angles reaches 0.123 in about 166
  calls.
- Complete: re-used 0.149, fresh 0.162, refined 0.162.

**Re-use as a warm start halves the angle-search cost with no loss in quality. Re-use alone loses about 10 %
of P(opt).**

**Q3 Warm start from SQA (p = 2; SQA at B = 64 was sub-optimal on 31 of the 60).**
- Warm starts raise the mean P(opt): ring 0.147 → 0.396 at ε = 0.1, complete 0.223 → 0.455.
- That gain comes from cases where SQA was already right.
- **Where SQA was wrong, warm starts get stuck.** At ε = 0.1, all 31 of those cases put more probability on
  the SQA answer than on the optimum (ring P(opt) 0.063 vs 0.111 uniform). At ε = 0.3, 14 (complete) and
  20 (ring) of the 31 got stuck.
- Use ε ≥ 0.3, or do not warm-start, when the classical answer may be wrong.

## 5. QAOA inside the market (experiment only; `market.csv`)

QAOA-ring (shots, B = 256 per sub-problem) supplies only the **upper-bound** schedule. The **lower bound
stays exact**: `LOWER_BOUND_SOLVER = "exact"` is not configurable, and a test checks it. A sub-optimal
sub-problem answer would make the Lagrangian bound invalid. Results on seeds 0, 1 and 2:

- The lower bounds are identical to the exact market's.
- The best upper bounds are worse: certified gap 19.6 % vs 17.6 %, 24.4 % vs 24.3 %, and 20.8 % vs 16.1 %.
- QAOA used 51,200 counted evaluations per instance.

Replacing exact sub-problem solves with QAOA-shots **loosens** the certificate on these instances.

## 6. Honest claims (what may be written in reports)

- ✔ The QAOA-XY subspace simulator is exact. It is tested against a full statevector simulation and the
  mixer keeps the state feasible.
- ✔ Under an equal energy-evaluation budget, shot-based QAOA on 12–20-qubit sub-problems was at or near
  random sampling. Classical SA matched or beat it on most sub-problems.
- ✔ Quantum-inspired SB had the highest P(opt) per counted readout. This comes with the accounting caveat
  in §3.3.
- ✘ Do not claim quantum advantage, a speed-up, or hardware performance. No hardware was used, and the
  simulator's run time grows as m^t.
- ✘ Do not quote QAOA-ideal numbers as achievable QAOA performance.
