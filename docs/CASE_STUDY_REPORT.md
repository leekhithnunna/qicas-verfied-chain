# Verifiable, Quantum-Inspired, Carbon-Aware Scheduling of Cloud Workflows on Blockchain

**Case Study Report — QICAS-Chain, Team 07 (draft)**

> Draft status: every number in this report comes from `results/demo_run.json` (seed 7, default
> `config/demo.yaml`, run of 2026-11-13 09:40:58) or from the code/config it cites. Citation details
> that could not be verified from the repository are marked **[VERIFY]**. Figures are in
> `results/figures/` (git-ignored; regenerate with `.\.venv\Scripts\python.exe -m demo.make_figures`).

---

## 1. Title

Verifiable, Quantum-Inspired, Carbon-Aware Scheduling of Cloud Workflows on Blockchain.

## 2. Abstract

Data-centre operators increasingly shift computation towards regions and hours with low-carbon
electricity, but the resulting savings are computed and reported by the same party that benefits from
them. This case study examines three lines of work: industrial carbon-aware computing (Radovanović et
al., *IEEE Transactions on Power Systems*, 2023), blockchain-assisted scheduling (*The Journal of
Supercomputing*, 2026) and quantum-inspired multi-objective scheduling (Hammouda et al., *Scientific
Reports*, 2026). We identify a common gap: none of them lets untrusted parties compete to produce a
schedule whose carbon saving is re-computed and certified by a neutral verifier. We built a working
demo in which four off-chain solvers (greedy and simulated annealing — classical; simulated quantum
annealing — quantum-inspired; a Lagrangian dual-price market) schedule 39 workflow tasks across four
regions, and a Solidity contract re-scores every revealed schedule on-chain. On the seed-7 instance the
winning schedule reduces carbon from 961.8 g to 531.8 g (44.7 %), with a certified optimality gap of at
most 9.92 % and a net saving of 428.0 g after an estimated 1.87 g blockchain overhead. Three attacks
(over-capacity, copycat, no-show) all fail.

## 3. Introduction

Cloud data centres consume electricity whose carbon intensity varies strongly by location and time.
In the demo's illustrative configuration, the four regions range from 40 g CO₂e/kWh (Stockholm) to
680 g CO₂e/kWh (Mumbai) — a factor of 17 (source: `config/demo.yaml`). Placing the same task in a
different region therefore changes its emissions far more than most hardware-efficiency improvements.

Three complications make this placement problem harder than "send everything to the cleanest region":

1. **Capacity.** Clean regions are finite. In the demo, Stockholm holds 23 of the 91 CPU cores
   demanded (capacity share 0.25), so most work must go elsewhere.
2. **Workflows, not independent jobs.** Real cloud jobs are directed acyclic graphs (DAGs) of tasks
   that pass data to each other. Splitting connected tasks across regions costs network energy (and so
   carbon) and egress fees.
3. **Trust.** A carbon saving is a claim relative to a counterfactual. If the operator who schedules the
   work also picks the baseline and computes the saving, the claim cannot be independently checked —
   the same problem that afflicts many voluntary carbon-offset markets.

This report studies how the three source papers address the first two points, shows that the third is
largely unaddressed, and presents a demo that combines carbon-aware placement, quantum-inspired
optimisation and on-chain verification. The aim of the case study is a correct, honest, reproducible
prototype — not a performance claim.

## 4. Background

**Carbon intensity.** The grams of CO₂-equivalent emitted per kWh of electricity drawn from a grid at a
given place and time. Public sources such as the Electricity Maps data portal publish hourly values.
The demo currently uses illustrative, rounded values (README §5, §11).

**DAG workflows.** A workflow is a set of tasks with precedence and data-transfer edges. The demo
generates 8 workflows of 3–6 tasks each; every non-root task receives 1–2 parents, and each edge carries
a log-normally distributed data volume (median ≈ 400 MB; `core/instance.py`, `config/demo.yaml`).

**QUBO / Ising and annealing.** Assignment problems can be written as a quadratic unconstrained binary
optimisation (QUBO), equivalently an Ising spin model, by encoding "task *j* in region *d*" as a binary
variable with a one-hot constraint per task. Simulated annealing (SA) explores such energy landscapes by
accepting uphill moves with probability exp(−ΔE/T). Quantum annealing adds a transverse field Γ that
allows tunnelling through barriers; *simulated* quantum annealing (SQA) emulates this on a classical
computer via the Suzuki–Trotter decomposition into P coupled replicas (Martoňák, Santoro and Tosatti,
*Phys. Rev. B* 66, 094203, 2002).

**Smart contracts, commit-reveal and Merkle trees.** A smart contract is code executed identically by
every node of a blockchain, so its outputs can be checked by anyone. *Commit-reveal* prevents copying:
participants first publish a hash of their answer and only later reveal it. *Staking and slashing* make
misbehaviour costly. A *Merkle tree* commits to many items with one 32-byte root; any single item can
later be proved against the root with a short proof.

## 5. Literature study

Each core paper is summarised using the reading template in `docs/CASE_STUDY_PAPERS.md`. Fields that
require reading the full paper (datasets, numeric results, authors' stated limitations) are marked
[VERIFY] and must be completed from the papers themselves before submission.

### 5.1 Paper 1 — Carbon-aware computing for datacenters

A. Radovanović et al., "Carbon-Aware Computing for Datacenters," *IEEE Transactions on Power Systems*,
vol. 38, no. 2, pp. 1270–1280, 2023 [VERIFY volume/issue/pages, DOI, quartile — expected Q1].

| Field | Notes |
|---|---|
| Problem addressed | Shifting flexible compute in time and across data centres according to grid carbon intensity. |
| System model / assumptions | Production system at Google; day-ahead carbon forecasts; per-cluster capacity limits; one trusted operator. |
| Method | Forecast-driven, capacity-limited carbon-weighted placement [VERIFY algorithmic details]. |
| Dataset / carbon data | Google production fleet and grid forecasts [VERIFY]. |
| Metrics and baselines | [VERIFY] |
| Key results | [VERIFY] |
| Limitations (authors) | [VERIFY] |
| Limitations (ours) | Centralised and trusted; jobs treated as independent; no third-party verification of savings. |
| What the demo adopts | Carbon-weighted, capacity-limited placement objective. |
| What the demo adds | DAG data-transfer carbon; baseline computed by a contract, not by the operator. |

A newer related paper in the same journal is S. Hall et al., "Carbon-aware computing for data centers
with probabilistic performance guarantees," *IEEE Transactions on Power Systems*, 2025 [VERIFY volume,
pages, DOI].

### 5.2 Paper 2 — Blockchain-assisted scheduling

"Blockchain-assisted smart grid scheduling using energy-efficient swarm and deep learning models,"
*The Journal of Supercomputing*, Springer, 2026, https://link.springer.com/article/10.1007/s11227-026-08743-8
[VERIFY full author list, volume, article number, quartile — expected Q2].

| Field | Notes |
|---|---|
| Problem addressed | Energy-efficient scheduling with transparent, tamper-proof execution. |
| System model / assumptions | One hybrid optimiser; blockchain + smart contracts validate and record schedules. |
| Method | Swarm optimisation plus deep-learning forecasting; smart-contract validation. |
| Dataset | [VERIFY] |
| Metrics and baselines | [VERIFY] |
| Key results | [VERIFY] |
| Limitations (authors) | [VERIFY] |
| Limitations (ours) | Single trusted optimiser; no competition among untrusted solvers; no on-chain re-computation of cost; no optimality certificate. |
| What the demo adopts | Optimiser produces a schedule; a blockchain validates it. |
| What the demo adds | Commit-reveal competition, on-chain re-scoring, slashing, Merkle proofs, net-carbon credits, certified gap. |

Closest older work: "Blockchain-based decentralized workload and energy management of geo-distributed
data centers," *Sustainable Computing: Informatics and Systems*, vol. 29, 2021 [VERIFY authors, article
number, DOI].

### 5.3 Paper 3 — Quantum-driven multi-objective scheduling

N. G. Hammouda et al., "A quantum-driven multi-objective scheduler for scalable task orchestration in
fog-based cyber-physical-social systems," *Scientific Reports*, vol. 16, art. 6874, 2026,
DOI 10.1038/s41598-025-33627-x [VERIFY volume/article number/DOI resolve; quartile — expected Q1].

| Field | Notes |
|---|---|
| Problem addressed | Scalable multi-objective task orchestration in fog-based systems, including energy efficiency. |
| System model / assumptions | Centralised fog scheduler. |
| Method | Quantum-inspired evolutionary multi-objective optimisation. |
| Dataset / workload | [VERIFY] |
| Metrics and baselines | [VERIFY] |
| Key results | [VERIFY] |
| Limitations (authors) | [VERIFY] |
| Limitations (ours) | Centralised; no regional carbon-intensity signal; no verifiability. |
| What the demo adopts | A quantum-inspired heuristic for energy-aware scheduling. |
| What the demo adds | SQA with one-hot registers, honestly compared against classical SA on the same instance. |

Critical companion for the discussion: F. A. Quinton et al., "Quantum annealing applications,
challenges and limitations for optimisation problems compared to classical solvers," *Scientific
Reports*, vol. 15, art. 12733, 2025 [VERIFY]. It supports our decision not to claim quantum advantage.

Supporting (department relevance): B. M. Beena et al., "A green cloud-based framework for
energy-efficient task scheduling using carbon intensity data for heterogeneous cloud servers," *IEEE
Access*, vol. 13, pp. 73916–73936, 2025, doi:10.1109/ACCESS.2025.3562882 [VERIFY quartile — expected Q1 in SJR].

## 6. Comparative analysis

| Aspect | Paper 1 | Paper 2 | Paper 3 | Our demo |
|---|---|---|---|---|
| Carbon-intensity aware | ✔ | partial (energy) | energy only | ✔ |
| DAG / data-transfer cost | ✗ | ? [VERIFY] | ? [VERIFY] | ✔ |
| Quantum-inspired optimiser | ✗ | ✗ | ✔ | ✔ (SQA) |
| Untrusted solvers compete | ✗ | ✗ | ✗ | ✔ (commit-reveal) |
| On-chain re-verification of cost | ✗ | validation | ✗ | ✔ |
| Certified optimality gap | ✗ | ✗ | ✗ | ✔ (Lagrangian bound) |
| Net carbon incl. blockchain overhead | ✗ | ✗ | ✗ | ✔ |

*Source: `docs/CASE_STUDY_PAPERS.md`; ✔/✗ for papers 1–3 must be confirmed against the full texts.*

**Identified gaps.**

1. **Verifiability.** Paper 1 is trusted by construction; Paper 2 records schedules on-chain but does
   not re-derive their cost, so a wrong cost model or a manipulated baseline would go undetected.
2. **Competition and incentives.** No paper lets several independent, possibly malicious, solvers
   compete under a rule that rewards the best verified answer and penalises cheating.
3. **Optimality evidence.** Heuristic results are reported against baselines, but none gives a
   *certificate* of how far the result can be from the true optimum.
4. **Workflow structure.** Data-transfer carbon between dependent tasks is rarely modelled together with
   regional carbon intensity.
5. **Net accounting.** Verification itself costs energy; no paper subtracts it from the claimed saving.

## 7. Proposed approach

### 7.1 Problem model

Assign each task *j* to a region *x_j* to

minimise Σ_j [w_c · carbon(j, x_j) + w_p · cost(j, x_j)] + Σ_(j,k)∈edges [transfer carbon + egress fee if x_j ≠ x_k]

subject to Σ_{j: x_j = d} cpu_j ≤ capacity_d for every region *d*.

This is a generalised quadratic assignment problem (NP-hard): edges make it quadratic and capacities
couple all tasks. All quantities are integers so that Python and Solidity compute identical results:

| Quantity | Unit | Default value |
|---|---|---|
| Task energy | Wh = cores × hours × W/core | 12 W per core |
| Carbon intensity | g CO₂e/kWh | 40 / 330 / 380 / 680 |
| Electricity price | µUSD/kWh | 60 000 / 120 000 / 55 000 / 50 000 |
| Network energy | mWh/MB | 30 |
| Egress fee | nUSD/MB | 20 000 |
| Score | w_c · carbon [µg] + w_p · cost [nUSD] | w_c = w_p = 1 |

*Source: `config/demo.yaml`, README §5. Region order: Stockholm, Ireland, Virginia, Mumbai. Values are illustrative.*

### 7.2 Solvers (off-chain)

- **Greedy (classical)** — `core/solvers/greedy.py`. Places tasks one by one in the cheapest region with
  free capacity, counting edges to already-placed neighbours. Also the starting point for SA and SQA.
- **Simulated annealing (classical)** — `core/solvers/sa.py`. Single-task moves, Metropolis acceptance,
  geometric cooling from T₀ = 2.0 to 0.01 over 400 sweeps; capacity overflow penalised; best feasible
  schedule kept.
- **Simulated quantum annealing (quantum-inspired)** — `core/solvers/sqa.py`. P = 12 Trotter replicas
  in a ring; each task is a one-hot spin register; inter-replica coupling
  J⊥ = −(P·T/2)·ln tanh(Γ/(P·T)) with T = 0.05 and Γ annealed from 3.0 to 0.01 over 150 sweeps.
  It runs on a classical CPU; it is *not* quantum hardware.
- **Dual-price market (Lagrangian decomposition)** — `core/market.py`. Each region gets a price λ_d per
  CPU core. With prices fixed, workflows decouple and each is solved exactly (hence the limit of ≤ 7
  tasks per workflow). The relaxed optimum is a **lower bound** (weak duality); prices follow a
  subgradient rule λ_d ← max(0, λ_d + step_k·(load_d − C_d)) with step_k ∝ 1/√(k+1) over 25 rounds;
  each round's assignment is repaired into a feasible schedule (**upper bound**).
  gap = (UB − LB)/UB is a certified distance from optimal.

All solvers take a `seed` and are deterministic.

### 7.3 On-chain protocol

`chain/contracts/CarbonScheduleMarket.sol` (Solidity 0.8.24, single file, no dependencies):

| Step | Function | Purpose |
|---|---|---|
| 1 | `publish` (owner) | Stores regions, tasks, edges, weights; **computes the round-robin baseline on-chain** |
| 2 | `commit` + stake | Stores keccak256(epoch, schedule, salt, sender) — the sender binding defeats copying |
| 3 | `openReveal` (owner) | Moves to the reveal phase |
| 4 | `reveal` | Checks the hash; malformed or over-capacity → `Rejected` + slash; else re-scores with `evaluate()` and keeps the best |
| 5 | `finalize(overheadUg)` | Slashes non-revealers; stores the winner's Merkle root; mints credits = net saving in grams |
| 6 | `verifyPlacement` (anyone) | Checks one task's placement against the stored root |
| — | `withdraw` | Pull-payment refund of honest stakes (reentrancy-guarded) |

*Source: README §7, `CarbonScheduleMarket.sol`.*

Python↔Solidity integer parity of `evaluate`, `baselineSchedule`, `merkleRootOf` and `commitHashOf` is
enforced by `tests/test_parity.py`.

## 8. Demo implementation

**Architecture.** `config/demo.yaml` → `core/instance.py` (instance generation) → solvers in
`core/solvers/` and `core/market.py` → `demo/pipeline.py` (the 7-step scenario) → `chain/client.py`
(web3.py) → contract on an in-memory Ethereum Virtual Machine (py-evm), or optionally a local Hardhat
node. The same pipeline drives the CLI (`demo/run_demo.py`) and the Streamlit dashboard
(`app/dashboard.py`). `core/` never imports blockchain or UI code (README §3).

**Technologies.** Python 3.12, web3.py with py-evm (in-memory chain), Solidity 0.8.24 (precompiled,
optimiser 200 runs, viaIR, EVM version paris), Streamlit, Matplotlib, pytest.

**Tests.** Eight pytest tests: solver feasibility and improvement over baseline, lower bound below every
feasible schedule, Merkle proofs, the four parity tests, and an end-to-end run. Result: **8 passed**.

**Dashboard.** Tabs: Instance, Solvers, Dual-price market, On-chain, Merkle proof.
*[Insert dashboard screenshots here — not available in the repository.]*

**Reproduce.**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m demo.run_demo
.\.venv\Scripts\python.exe -m demo.make_figures
```

## 9. Results

### 9.1 Instance

39 tasks in 8 DAG workflows, 36 data edges, 91 CPU cores demanded, 4 regions with capacities
23 / 37 / 41 / 41 cores (Stockholm / Ireland / Virginia / Mumbai). Instance hash
`0x8fd313741e4cc3d26c8a026421f47b0f560fe2fe0d56ae34f3b7b35a56e725e0`.

*Source: `results/demo_run.json` → `instance`, `market.capacities`.*

### 9.2 Solver comparison

| Approach | Label | Score | Carbon (g) | Cost (USD) | Carbon ↓ vs baseline | Score gap to LB | Feasible | Time (s) |
|---|---|---:|---:|---:|---:|---:|:---:|---:|
| Round-robin baseline | baseline | 1,458,546,200 | 961.75 | 0.4968 | — | 56.20 % | ✔ | 0.00 |
| Greedy | classical | 872,431,150 | 627.53 | 0.2449 | 34.75 % | 26.78 % | ✔ | 0.0004 |
| Simulated annealing | classical | 758,638,650 | 542.77 | 0.2159 | 43.56 % | 15.79 % | ✔ | 0.05 |
| SQA | quantum-inspired | 730,160,300 | 552.74 | 0.1774 | 42.53 % | 12.51 % | ✔ | 0.27 |
| Dual-price market | decomposition | 709,208,800 | 531.85 | 0.1774 | 44.70 % | 9.92 % | ✔ | 0.60 |

*Source: `results/demo_run.json` → `offchain`; lower bound LB = 638,827,640 from `market.best_lower`.
"Carbon ↓" = (baseline − solver)/baseline carbon; "Score gap to LB" = (score − LB)/score, i.e. the
certified maximum distance of that schedule from the optimum. Times are single-run wall-clock and vary
between machines.*

![Figure 1 — carbon and cost per approach](../results/figures/fig1_solver_comparison.png)

*Figure 1. Carbon (left) and energy + transfer cost (right) per approach (`fig1_solver_comparison.png`).*

**Observations.**

- All four solvers beat the contract's baseline substantially; the dual-price market gives the best
  score and the lowest carbon.
- SQA achieves a lower *score* than SA (730.2 M vs 758.6 M) but *higher* carbon (552.7 g vs 542.8 g):
  with equal weights (w_c = w_p = 1) it found a much cheaper schedule (USD 0.1774 vs 0.2159) at a small
  carbon cost. The ranking therefore depends on the objective weights, not only on the solver.
- This is **one seed on one instance**, and the two annealers were not given equal compute budgets
  (SA: 400 sweeps of one state; SQA: 150 sweeps × 12 replicas). No conclusion about SQA being better
  than SA in general can be drawn; a budget-matched multi-seed comparison is planned (§10, Phase 2).
- The SQA best-so-far score stays at the greedy start (872,431,150) for the first 11 sweeps and reaches
  its final 730,160,300 at sweep 141 of 150 (`results/demo_run.json` → `sqa_trace`).

### 9.3 Dual-price market and certified gap

| Quantity | Value |
|---|---:|
| Rounds | 25 |
| Best lower bound (round 21) | 638,827,640 |
| Best upper bound (round 14) | 709,208,800 |
| Certified gap (UB − LB)/UB | 9.92 % |
| Rounds with a negative (uninformative) lower bound | 1 (round 3) |

*Source: `results/demo_run.json` → `market.lower`, `market.upper`, `best_lower`, `best_upper`, `gap`;
round numbers are 1-based indices.*

![Figure 2 — market bounds](../results/figures/fig2_market_bounds.png)

*Figure 2. Upper (feasible) and lower (Lagrangian) bounds per round (`fig2_market_bounds.png`).*

![Figure 3 — regional prices](../results/figures/fig3_region_prices.png)

*Figure 3. Congestion prices λ per region per round (`fig3_region_prices.png`).*

The lower bound oscillates, which is typical of the plain subgradient step rule; the best bound over
all rounds is used. Better step rules (and warm-starting) are listed as open work. The gap means that
no schedule for this instance can score below 638,827,640, so the winning schedule is within 9.92 % of
the optimum — a guarantee that holds regardless of which heuristic produced it.

### 9.4 On-chain reveals and attacker outcomes

Seven agents committed with a 1 ETH test stake each (`config/demo.yaml` → `stake_wei`).

| Agent | Role | Outcome | On-chain score | Python score matches | Gas |
|---|---|---|---:|:---:|---:|
| greedy | honest | accepted | 872,431,150 | ✔ | 636,188 |
| sa | honest | accepted | 758,638,650 | ✔ | 542,929 |
| sqa | honest | accepted | 730,160,300 | ✔ | 522,790 |
| dual-market | honest | accepted (**winner**) | 709,208,800 | ✔ | 522,766 |
| attacker: over-capacity | malicious | **rejected** (capacity violated), slashed | — | — | 438,828 |
| attacker: copycat | malicious | **reverted** (`HashMismatch`), slashed at finalize as non-revealer | — | — | 0 (reverted) |
| attacker: no-show | malicious | **not revealed**, slashed at finalize | — | — | — |

*Source: `results/demo_run.json` → `reveals`, `transactions`; attacker behaviour from `demo/pipeline.py`.
Total slashed: 3 ETH (`final.slashed_eth`).*

How each attack is stopped:

- **Over-capacity** places all 39 tasks in Stockholm (91 cores into 23). The contract's capacity check
  rejects it and slashes the stake. The attacker still pays 438,828 gas for the failed reveal.
- **Copycat** copies SQA's commitment hash and SQA's salt, then tries to reveal SQA's schedule. Because
  the commitment includes `msg.sender`, the recomputed hash differs and the reveal reverts with
  `HashMismatch`. Having never revealed successfully, the copycat is slashed at finalisation.
- **No-show** commits and never reveals (e.g. to block or to keep options open); it is slashed at
  finalisation.

Every accepted reveal's on-chain score equalled the Python score, confirming parity on live data.

### 9.5 Gas and blockchain overhead

| Transaction(s) | Count | Gas |
|---|---:|---:|
| deploy | 1 | 2,042,126 |
| publish (39 tasks, 36 edges; computes baseline) | 1 | 3,903,934 |
| commit | 7 | 702,908 |
| openReveal | 1 | 27,808 |
| reveal (5 executed; copycat reverted) | 5 | 2,663,501 |
| finalize | 1 | 236,284 |
| **Total** | 16 (+1 reverted, 0 gas recorded) | **9,576,561** |

*Source: `results/demo_run.json` → `transactions` (sums computed from the per-transaction gas values;
total equals `final.total_gas`).*

The overhead model (`demo/pipeline.py`, lines 137–138) is

overhead = gas_before_finalize / 10⁶ × 0.5 Wh per million gas × 400 g CO₂e/kWh,

with both parameters taken from `config/demo.yaml` and documented there as **sensitivity parameters,
not measurements**. Gas before finalize = 9,576,561 − 236,284 = 9,340,277, giving 4.67 Wh and
**1.868 g CO₂e**. (The finalize transaction itself is not included, because its gas is not known when
the overhead value is passed into it.)

### 9.6 Final outcome

| Quantity | Value |
|---|---:|
| Winner | dual-market |
| Baseline carbon (contract-computed) | 961.75 g |
| Winner carbon | 531.85 g |
| Gross saving | 429.90 g (44.70 %) |
| Estimated chain overhead | 1.868 g |
| **Net saving** | **428.03 g** |
| Credits minted | 428 |
| Certified gap | ≤ 9.92 % |
| Slashed from attackers | 3 ETH |
| Merkle root | `0x6b5b7933…09bd3a20` |
| Merkle proof, task 0 in region 2 | valid (true) |
| Tampered claim, task 0 in region 3 | invalid (false) |

*Source: `results/demo_run.json` → `final`, `merkle_check`.*

![Figure 4 — net saving](../results/figures/fig4_net_saving.png)

*Figure 4. Baseline carbon, winner carbon and estimated chain overhead; the title states the net saving (`fig4_net_saving.png`).*

Under the stated assumptions the overhead is about 0.4 % of the gross saving. This ratio depends
linearly on the two sensitivity parameters and on the instance size, and should not be quoted as a
general result.

## 10. Discussion

### 10.1 Trade-offs

**Carbon vs cost.** With equal weights, carbon in µg and cost in nUSD contribute comparable magnitudes
to the score (for the winner: 531,848,800 µg carbon vs 177,360,000 nUSD cost). The SA–SQA comparison
shows that changing the weights can reorder solvers. The dashboard's carbon-priority / balanced /
cost-priority presets make this trade-off visible; the report should present results for more than one
weighting.

**Verification cost vs trust.** Re-scoring a 39-task schedule costs about 0.52–0.64 M gas per reveal,
and publishing the instance about 3.9 M gas. These grow with instance size; Phase 6 will measure the
largest instance that fits a block.

**Heuristics vs certificates.** The Lagrangian lower bound turns any heuristic result into a bounded
claim. Its weakness is that, in this demo, the bound is computed off-chain by one party.

### 10.2 Honest limitations

1. Region carbon and price values are illustrative until replaced by a cited, dated snapshot.
2. Workloads are synthetic (Alibaba-style DAG shapes); the full project uses the Alibaba
   cluster-trace-v2018.
3. The oracle problem: the contract verifies schedules **given** the published data; it cannot prove the
   data is true.
4. SQA is a classical simulation of quantum annealing: we claim *quantum-inspired*, not quantum
   advantage.
5. The blockchain overhead model is a parameterised estimate.
6. The market runs off-chain in the demo; the full project moves the price rounds on-chain.

*Source: README §11.*

Additional limitations observed while writing this report:

7. Results are from a single seed on a single 39-task instance; no variance is reported.
8. SA and SQA were not budget-matched.
9. The in-memory chain has no real block production, validators or network latency.

### 10.3 What the full project adds

See §11 and `docs/PROJECT_PLAN.md`.

## 11. Conclusion and future work

The case study confirms the gap: existing work either schedules for carbon under a trusted operator,
records schedules on a blockchain without re-deriving their value, or applies quantum-inspired search
without verifiability. The demo shows that the three pillars can be combined in a small, tested system
in which untrusted solvers compete, the contract fixes the baseline and re-scores every answer, cheating
fails visibly, the result is bounded against the optimum, and the claimed saving is net of the chain's
own estimated footprint. On the seed-7 instance this yields a 44.7 % carbon reduction, a certified gap of
at most 9.92 % and a net saving of 428.0 g.

**End-semester plan** (from `docs/PROJECT_PLAN.md`; the default demo and all tests stay green throughout):

| Phase | Goal | Key deliverables |
|---|---|---|
| 1 Real data | Replace illustrative inputs | Alibaba cluster-trace-v2018 DAGs; dated Electricity Maps hourly carbon per region; day-ahead prices (ENTSO-E, IEX India, PJM); public latency and egress tables |
| 2 Quantum layer | Feasibility-preserving quantum solver | QAOA with XY mixer on 12–20-qubit sub-problems via price decomposition; simulated bifurcation; budget-matched comparison with SA/SQA; claim "quantum-ready", never advantage |
| 3 On-chain market | Move price rounds on-chain | Contract runs Lagrangian rounds; untrusted solvers respond; lower bound recorded on-chain |
| 4 Trust layer | Remove trusted oracle and trusted bound | Multi-signer EIP-712 carbon oracle (median per region); optimistic fraud proofs for bound claims |
| 5 Consortium chain | Realistic deployment | Hyperledger Besu (QBFT) with providers as validators; ERC-20 credits and ERC-721 certificates (OpenZeppelin) |
| 6 Evaluation | Final evidence | Net carbon after overhead with sensitivity ranges, gas limits, full attack suite, live dashboard, report figures |
| Stretch | Research lab | Proof-of-Useful-Work: blocks carry QUBO solutions |

*Source: `docs/PROJECT_PLAN.md`.*

## 12. References

1. A. Radovanović et al., "Carbon-Aware Computing for Datacenters," *IEEE Transactions on Power
   Systems*, vol. 38, no. 2, pp. 1270–1280, 2023. [VERIFY DOI; quartile — expected Q1]
2. S. Hall et al., "Carbon-aware computing for data centers with probabilistic performance guarantees,"
   *IEEE Transactions on Power Systems*, 2025. [VERIFY volume, issue, pages, DOI; quartile]
3. [VERIFY authors], "Blockchain-assisted smart grid scheduling using energy-efficient swarm and deep
   learning models," *The Journal of Supercomputing*, 2026,
   https://link.springer.com/article/10.1007/s11227-026-08743-8. [VERIFY volume, article number; quartile — expected Q2]
4. [VERIFY authors], "Blockchain-based decentralized workload and energy management of geo-distributed
   data centers," *Sustainable Computing: Informatics and Systems*, vol. 29, 2021. [VERIFY article
   number, DOI; quartile]
5. N. G. Hammouda et al., "A quantum-driven multi-objective scheduler for scalable task orchestration in
   fog-based cyber-physical-social systems," *Scientific Reports*, vol. 16, art. 6874, 2026,
   doi:10.1038/s41598-025-33627-x. [VERIFY; quartile — expected Q1]
6. F. A. Quinton et al., "Quantum annealing applications, challenges and limitations for optimisation
   problems compared to classical solvers," *Scientific Reports*, vol. 15, art. 12733, 2025. [VERIFY DOI; quartile]
7. B. M. Beena et al., "A green cloud-based framework for energy-efficient task scheduling using carbon
   intensity data for heterogeneous cloud servers," *IEEE Access*, vol. 13, pp. 73916–73936, 2025,
   doi:10.1109/ACCESS.2025.3562882. [VERIFY quartile — expected Q1 in SJR]
8. R. Martoňák, G. E. Santoro, E. Tosatti, "Quantum annealing by the path-integral Monte Carlo method:
   The two-dimensional random Ising model," *Physical Review B*, vol. 66, 094203, 2002. [VERIFY title]
9. Electricity Maps, data portal, https://www.electricitymaps.com/data-portal (ODbL). [VERIFY licence
   terms and access date when the snapshot is taken]
