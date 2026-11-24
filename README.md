# QICAS Case-Study Demo
### Verifiable, quantum-inspired, carbon-aware scheduling of cloud workflows on a blockchain

> **What this repository is:** a complete, working, tested demo for the *case-study* stage of the
> QICAS project. It is small enough to understand in a day and run in one command, but it exercises
> all three pillars studied in the case study: **green cloud scheduling**, **quantum-inspired
> optimisation**, and **blockchain verification**.

## QICAS-Chain — project status

| Phase | What | Status |
|---|---|---|
| Case study | Off-chain solvers + `CarbonScheduleMarket` contract, 7-step demo, dashboard | **DONE** |
| Phase 2 | Quantum layer: SA / SQA / SB / XY-QAOA (simulated) sub-problem benchmark (§11b) | **DONE** |
| Phase 6-lite | Evaluation harness E1–E4 on synthetic data + dashboard Evaluation tab (§14) | **DONE** |
| Phase 3 | On-chain price market: `PriceMarket.sol` price rounds + on-chain lower bound (§15) | **DONE** |
| Phase 4 | Trust layer: EIP-712 multi-signer carbon oracle, V2 market reading it, fraud proofs for bounds (§16) | **DONE** |
| Phase 1 | Real data: Alibaba trace DAGs + 2024-10-15T12:00Z carbon/price snapshot (§17; `docs/DATA_SOURCES.md`) | **DONE** |
| Phase 5 | Besu QBFT network (4 validators) + ERC-20 credits + soulbound ERC-721 certificates, V3 market (§18) | **DONE** |
| Full Phase 6 | E1–E6 (real data, Phases 3–5 rows, E5, E6 on Besu), fig5–fig11, 3 new tabs, `docs/FINAL_REPORT.md` (§19) | **DONE** |

Details and build order: `docs/PROJECT_PLAN.md`. Main commands (PowerShell, repo root):
```powershell
.\.venv\Scripts\python.exe -m pytest -q                              # offline test suite
.\.venv\Scripts\python.exe -m demo.run_demo                          # 7-step demo (seed 7, see RUN_GUIDE.md)
.\.venv\Scripts\python.exe -m experiments.run_all --profile smoke    # or --profile lite -> results\eval\
.\.venv\Scripts\python.exe -m experiments.onchain_market             # Phase 3: on-chain price rounds, seed 7
.\.venv\Scripts\python.exe -m experiments.trust_layer                # Phase 4: oracle + fraud proofs, seed 7
.\.venv\Scripts\python.exe -m experiments.real_snapshot              # Phase 1: real snapshot (needs local data/)
powershell -ExecutionPolicy Bypass -File scripts\besu_up.ps1         # Phase 5: Besu QBFT network (Docker)
.\.venv\Scripts\python.exe -m demo.run_demo --mode besu              # Phase 5: same demo on Besu
.\.venv\Scripts\python.exe -m experiments.besu_vs_memory             # Phase 5: E6 -> results\besu\
.\.venv\Scripts\python.exe -m streamlit run app/dashboard.py         # dashboard
```

---

## 0. Quick start (copy-paste)

**Windows (PowerShell)**
```powershell
cd qicas-casestudy-demo
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt
python -m pytest -q                   # expect: 45 passed
python -m demo.run_demo               # full end-to-end demo in the terminal (~10 s)
python -m demo.make_figures           # report figures -> results/figures/
streamlit run app/dashboard.py        # interactive dashboard in the browser
```

**macOS / Linux**
```bash
cd qicas-casestudy-demo
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q && python -m demo.run_demo && python -m demo.make_figures
streamlit run app/dashboard.py
```

No Node.js, no Solidity compiler, no API keys are needed for the default mode: the blockchain runs
**in memory** (a real Ethereum Virtual Machine, py-evm) and the contract is precompiled.
An optional mode uses a real local Hardhat node (§9.2).

---

## 1. What the demo shows (the story for your presentation)

1. A batch of **cloud workflows** (DAGs of tasks that pass data to each other) must be placed across
   **4 regions** that differ in **carbon intensity**, **electricity price** and **capacity**.
   Splitting connected tasks across regions costs network energy (carbon) and transfer fees.
2. Four **off-chain solvers** compute schedules:
   `greedy` (classical), `sa` (simulated annealing, classical), `sqa` (**simulated quantum annealing,
   quantum-inspired**), and `dual-market` (Lagrangian price decomposition, which also yields a
   **certified lower bound** on the best possible score).
3. A **smart contract** receives the instance and computes its **own baseline** (so nobody can pick a
   convenient baseline).
4. Solvers **commit** a hash of their schedule plus a stake, then **reveal**. The contract
   **re-computes carbon, cost and capacity on-chain** and keeps the best schedule.
5. Three **attackers** try to cheat and fail on camera:
   - *over-capacity* schedule → **rejected** and stake slashed;
   - *copycat* copies another solver's commitment → **reverted** (`HashMismatch`), because the hash binds the sender;
   - *no-show* commits but never reveals → **slashed** at finalisation.
6. **Finalisation:** winner selected, **Merkle root** of the schedule stored, **net** carbon saving
   (gross saving minus estimated blockchain overhead) minted as credits.
7. Anyone can **verify one task's placement** against the on-chain Merkle root; a tampered claim fails.

Example output (seed 7, default config):
```
[2] baseline (round-robin)   carbon=961.8 g   cost=$0.4968
[2] greedy                   carbon=627.5 g   cost=$0.2449   (classical)
[2] sa                       carbon=542.8 g   cost=$0.2159   (classical)
[2] sqa                      carbon=552.7 g   cost=$0.1774   (quantum-inspired)
[2] dual-market              carbon=531.8 g   cost=$0.1774   (decomposition)
[2] Lagrangian lower bound -> every schedule above is at most 9.9% from optimal
[5] attacker: over-capacity -> rejected (capacity violated)
[5] attacker: copycat       -> reverted (HashMismatch)
[6] Winner: dual-market. Carbon 961.8 g -> 531.8 g (44.7% lower). NET saving 428.0 g; 428 credits minted.
    Certified gap <= 9.92%. Slashed from attackers: 3 ETH
[7] Merkle proof task 0: True; tampered claim: False
```
(Exact numbers depend on seed and config. Region values are illustrative, see §5.)

---

## 2. How the demo maps to the three case-study papers
Full details and the reading template: `docs/CASE_STUDY_PAPERS.md`.

| Pillar | Core paper (expected quartile — verify) | What we take | What the demo adds | Where in code |
|---|---|---|---|---|
| Green cloud | Radovanović et al., *IEEE Trans. Power Systems* 2023 (Q1) | Carbon-weighted, capacity-limited placement | DAG data-transfer carbon; contract-computed baseline | `core/scoring.py`, `baselineSchedule()` |
| Blockchain | *J. Supercomputing* 2026, blockchain-assisted scheduling (Q2) | Optimiser + on-chain validation | Untrusted competing solvers, on-chain re-scoring, slashing, Merkle proofs, net-carbon credits | `chain/contracts/CarbonScheduleMarket.sol` |
| Quantum-inspired | Hammouda et al., *Scientific Reports* 2026 (Q1) | Quantum-inspired heuristic for energy-aware scheduling | Simulated quantum annealing with one-hot registers; honest comparison vs classical SA | `core/solvers/sqa.py` |

---

## 3. Architecture

```
                     config/demo.yaml
                            │
                ┌───────────▼───────────┐
                │ core/instance.py      │  synthetic Alibaba-style DAG workflows + 4 regions
                └───────────┬───────────┘
                            │ Instance (all integers)
        ┌───────────────────┼─────────────────────────────┐
        ▼                   ▼                             ▼
 core/solvers/        core/market.py               core/scoring.py  ◄── parity ──► CarbonScheduleMarket.sol
 greedy, sa, sqa      Lagrangian prices,           (reference cost)                 evaluate()
        │             lower bound, repair                                                ▲
        └──────────┬────────┘                                                            │
                   ▼                                                                     │
          demo/pipeline.py  ── chain/client.py (web3.py) ── publish / commit / reveal / finalize ─┘
                   │                    ▲
       ┌───────────┴──────────┐         └─ in-memory EVM (py-evm)  or  Hardhat node (rpc)
       ▼                      ▼
 demo/run_demo.py      app/dashboard.py (Streamlit)        demo/make_figures.py → results/figures/*.png
```

---

## 4. Folder and file guide

```
qicas-casestudy-demo/
├── README.md                      ← this file (system map + how to run)
├── VSCODE_AGENT_PROMPT.md         ← prompt to paste into your VS Code AI assistant
├── AGENTS.md, CLAUDE.md, .github/copilot-instructions.md   ← rules AI assistants read automatically
├── requirements.txt
├── config/demo.yaml               ← ALL tunable parameters (regions, workload, solvers, chain)
├── core/                          ← pure Python, no blockchain imports
│   ├── hashing.py                 keccak256 (Ethereum hash) + canonical JSON
│   ├── instance.py                Region/Task/Edge/Instance dataclasses; generate_instance()
│   ├── scoring.py                 evaluate(), round_robin_baseline(), FastEvaluator (move deltas)
│   ├── merkle.py                  Merkle tree identical to the contract's
│   ├── market.py                  Lagrangian dual-price market → lower bound + feasible upper bound
│   └── solvers/
│       ├── common.py              capacity repair, penalty weight, cost scale
│       ├── greedy.py              classical constructive baseline
│       ├── sa.py                  simulated annealing (classical)
│       └── sqa.py                 simulated quantum annealing (quantum-inspired, path-integral MC)
├── chain/
│   ├── contracts/CarbonScheduleMarket.sol   the smart contract (single file, no dependencies)
│   ├── build/CarbonScheduleMarket.json      precompiled ABI + bytecode (solc 0.8.24, viaIR, paris)
│   ├── client.py                  web3.py client: deploy, publish, commit, reveal, finalize, views
│   └── hardhat/                   optional local Ethereum node for rpc mode
├── demo/
│   ├── pipeline.py                the 7-step end-to-end scenario (shared by CLI and dashboard)
│   ├── run_demo.py                CLI entry point
│   └── make_figures.py            report figures from results/demo_run.json
├── app/dashboard.py               Streamlit UI (tabs: Instance, Solvers, Market, On-chain, Merkle proof, Evaluation)
├── app/tabs/                      one module per dashboard tab (evaluation, onchain_market, oracle, tokens = Phase 6)
├── config/eval.yaml               Phase 6 evaluation profiles (smoke | lite) + [VERIFY] overhead grid
├── experiments/                   Phase 2 benchmark; Phase 6 run_all.py, e1_e2/e3/e4/e5 modules, figures.py
├── docs/
│   ├── CASE_STUDY_PAPERS.md       3 core papers + mapping + reading template + comparison table
│   └── CASE_STUDY_REPORT_TEMPLATE.md
├── scripts/                       setup/run helpers for PowerShell and bash
├── tests/                         pytest: core logic, Python↔Solidity parity, end-to-end
└── results/                       generated: demo_run.json, figures/ (git-ignored)
```

---

## 5. Data model and units (why everything is an integer)

Solidity has no floating-point numbers, so every value crossing to the chain is an integer.
The units are chosen so that products need **no rounding**:

| Quantity | Unit | Example |
|---|---|---|
| Task energy | Wh | 2 cores × 1.5 h × 12 W = 36 Wh |
| Carbon intensity | g CO₂e / kWh | Stockholm 40, Mumbai 680 |
| Price | µUSD / kWh | 60 000 = $0.06/kWh |
| Task carbon | Wh × g/kWh = **mg** → ×1000 = **µg** | |
| Task cost | Wh × µUSD/kWh = **nUSD** | |
| Edge network energy | MB × mWh/MB = mWh; × g/kWh = **µg** | |
| Score | `w_carbon · carbon_µg + w_cost · cost_nUSD` | lower is better |

⚠️ **Region values in `config/demo.yaml` are illustrative** (typical order of magnitude) and stay that way: the
default demo is unchanged. **Phase 1** adds `config/real_snapshot.yaml` with a cited snapshot for
2024-10-15T12:00Z (Electricity Maps carbon intensity under an academic licence — no redistribution; ENTSO-E,
Electricity Maps API, IEX and ECB for prices/FX) and real Alibaba DAGs; see §17 and `docs/DATA_SOURCES.md`.
Prices are converted native → EUR/MWh (ECB rates, per EUR) → µUSD/kWh (× 1.0903 USD/EUR × 1000), exactly, with one
half-up rounding. `scripts/build_real_snapshot.py` recomputes those values from the raw files and checks the config.

To prepare a pasteable `regions:` block from one Electricity Maps CSV per region, run this from the repository
root, replacing the sample paths with your downloaded CSVs:

```powershell
python scripts/load_em_snapshot.py --hour 2026-10-14T12:00:00Z `
   --region "eu-north-1 (Stockholm)=data/stockholm.csv" `
   --region "eu-west-1 (Ireland)=data/ireland.csv" `
   --region "us-east-1 (Virginia)=data/virginia.csv" `
   --region "ap-south-1 (Mumbai)=data/mumbai.csv"
```

The loader matches the exact UTC hour, recognizes common portal timestamp and carbon-intensity headers, rounds
intensity to the nearest whole g CO₂e/kWh, and preserves each region's configured price and capacity. Replace
the existing `regions:` block with its output; the default config is not changed automatically.

---

## 6. Algorithms (what each solver does)

### 6.1 Problem
Assign each task `j` to a region `x_j`:
```
minimise   Σ_j [w_c·carbon(j, x_j) + w_p·cost(j, x_j)] + Σ_(j,k)∈edges [transfer carbon + fee if x_j ≠ x_k]
subject to Σ_{j: x_j = d} cpu_j ≤ capacity_d   for every region d
```
This is a **Generalised Quadratic Assignment Problem** (NP-hard): the edge terms make it quadratic,
and capacities couple all tasks.

### 6.2 Greedy (classical) — `core/solvers/greedy.py`
Places tasks one by one in the cheapest region with free capacity, counting edges to already-placed
neighbours. Fast, used as the starting point for SA and SQA.

### 6.3 Simulated annealing (classical) — `core/solvers/sa.py`
Random single-task moves; accept worse moves with probability `exp(−ΔE/T)`; temperature cools
geometrically. Capacity overflow is penalised; the best feasible schedule is kept.

### 6.4 Simulated quantum annealing (quantum-inspired) — `core/solvers/sqa.py`
Quantum annealing lets a system *tunnel* through barriers using a transverse field Γ. SQA simulates
this on a classical computer with the **Suzuki–Trotter** trick: `P` replicas of the schedule are
coupled in a ring. Each task is a one-hot "spin register" (one spin per region). Coupling strength
```
J⊥ = −(P·T/2) · ln tanh(Γ / (P·T))
```
grows as Γ is annealed to ~0, forcing replicas to agree on the final answer. Moving task `j` from
region `a` to `b` in replica ρ changes energy by
`Δcost/P  −  4·J⊥·(agreements_after − agreements_before)/P`.
Reference: Martoňák, Santoro, Tosatti, *Phys. Rev. B* 66, 094203 (2002).

### 6.5 Lagrangian dual-price market — `core/market.py`
Each region gets a **price λ_d per CPU core**. With prices, workflows become independent small problems
(solved exactly). The relaxed optimum gives a **lower bound** on the true optimum (weak duality). Prices
rise in over-demanded regions (subgradient rule), the combined answer is repaired into a feasible
schedule (**upper bound**), and `gap = (UB − LB)/UB` is a *certified* distance from optimal. This is the
preview of the full project's on-chain price market.

---

## 7. Blockchain protocol — `chain/contracts/CarbonScheduleMarket.sol`

| Function | Who | What it does |
|---|---|---|
| `publish(...)` | owner | Stores regions, tasks, edges, weights; **computes the round-robin baseline on-chain** |
| `commit(epoch, hash)` + stake | solver | Stores `keccak256(epoch, schedule, salt, sender)`; hides the schedule |
| `openReveal(epoch)` | owner | Moves to reveal phase |
| `reveal(epoch, schedule, salt)` | solver | Checks the hash (binds `msg.sender` → copy attack fails); malformed or over-capacity → `Rejected` + slash; else re-scores with `evaluate()` and keeps the best |
| `finalize(epoch, overheadUg)` | owner | Slashes non-revealers; stores Merkle root of the winner; mints credits = net saving in grams |
| `verifyPlacement(epoch, task, region, proof)` | anyone | Checks one task's placement against the root |
| `evaluate`, `baselineSchedule`, `merkleRootOf`, `commitHashOf`, `summary` | anyone (views) | Used by tests to prove Python ↔ Solidity parity |
| `withdraw()` | solver | Pull-payment refund of honest stakes (reentrancy-guarded) |

**Blockchain concepts exercised:** keccak hashing, commit-reveal, staking and slashing (incentives),
on-chain verification, Merkle trees and proofs, events, a minimal token, pull payments and reentrancy
protection, custom errors, gas measurement.

**Net carbon:** `overhead = total_gas / 1e6 × energy_wh_per_million_gas × chain_ci` (both parameters are
in `config/demo.yaml` and are **sensitivity parameters, not measurements**; state this in the report).

**Phase 3:** a second contract, `chain/contracts/PriceMarket.sol`, runs the Lagrangian price rounds on-chain and
reads the upper bound from this contract's `summary(epoch).bestScore`. This contract and its artifact are
unchanged (byte-identical), so the default demo output is unchanged. See §15.

---

## 8. The dashboard (`streamlit run app/dashboard.py`)
Sidebar: seed, number of workflows, objective weights (carbon-priority, balanced, cost-priority), chain mode.
Press **Run full demo**. Tabs:
- **Instance:** region table, workload size, instance hash.
- **Solvers:** score, carbon, cost, feasibility, runtime per approach + SQA progress curve.
- **Dual-price market:** upper and lower bound per round; region prices λ.
- **On-chain:** every reveal with outcome (accepted / rejected / reverted), every transaction with gas.
- **Merkle proof:** pick any task and claimed region → calls `verifyPlacement` on-chain live.
- **Evaluation:** reads `results/eval/` (see §14, §19); visible even before a demo run.
- **On-chain market / Oracle & challenges / Tokens (Phase 6):** read `results/onchain_market/`, `results/trust/`,
  `results/besu/`; the Tokens tab can run the V3 token flow in memory (credits, a retirement, certificate JSON).

Tip for the live presentation: run once with "Carbon priority", then "Cost priority", and show how the
winning schedule's carbon and cost trade off.

---

## 9. Running options

### 9.1 Default: in-memory chain
`python -m demo.run_demo` (or `--seed 12`, `--config other.yaml`). Results go to `results/demo_run.json`.

### 9.2 Real local node (Hardhat) — optional, needs Node.js 18+
```bash
cd chain/hardhat && npm install && npx hardhat node      # keep this terminal open
# new terminal, project root, venv active:
python -m demo.run_demo --mode rpc --rpc-url http://127.0.0.1:8545
```
In the dashboard choose `rpc` in the sidebar. The Python client deploys the precompiled contract to the node.

### 9.3 Recompiling the contract (only if you edit the .sol file)
Option A (Hardhat): copy `chain/contracts/CarbonScheduleMarket.sol` to `chain/hardhat/contracts/`,
run `npx hardhat compile`, then copy `abi` and `bytecode` from
`chain/hardhat/artifacts/contracts/CarbonScheduleMarket.sol/CarbonScheduleMarket.json` into
`chain/build/CarbonScheduleMarket.json` (keep the same keys). Compiler settings must stay:
solc 0.8.24, optimizer 200 runs, `viaIR: true`, `evmVersion: "paris"`.
Option B (solc-js, used since Phase 3; needs Node.js 20, e.g. `nvm install 20`, `nvm use 20`):
```powershell
Set-Location chain; npm install; Set-Location ..     # installs solc 0.8.24 (chain/package.json)
node chain/compile.js            # compiles every chain/contracts/<Name>.sol -> chain/build/<Name>.json
node chain/compile.js --check    # recompiles and compares with the committed artifacts; writes nothing
```
`compile.js` uses exactly the settings above and **refuses to overwrite** `CarbonScheduleMarket.json` if its
bytecode or ABI would change (the demo's seed-7 overhead line includes its deploy gas; `tests/test_artifacts.py`
pins its SHA-256). Then **always** run `python -m pytest -q` (parity tests); `$env:QICAS_RECOMPILE='1'` also runs
the ~1 min recompile check inside pytest.

---

## 10. Troubleshooting
| Symptom | Fix |
|---|---|
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `pip install` fails building a package on Windows | Use Python 3.11 or 3.12 (wheels available); upgrade pip; or use rpc mode with Hardhat |
| `ModuleNotFoundError: core` | Run commands from the project root, with `python -m ...` |
| Dashboard shows nothing | Press **Run full demo** in the sidebar |
| rpc mode: `cannot connect` | Start `npx hardhat node` first; check the URL/port |
| `repair failed` | Capacities too small: increase `capacity_share` values in `config/demo.yaml` |
| `workflows too large for exact sub-problem` | Keep `tasks_per_workflow` max ≤ 7 |

---

## 11. Honest limitations (put these in the report)
1. Region carbon/price values are illustrative in the default demo. Phase 1 (§17) adds one cited, dated snapshot
   hour (2024-10-15T12:00Z) — one hour, not real time and not a forecast; IE and IN-WE values are Electricity Maps
   estimates; IN-WE uses the all-India IEX price.
2. Workloads are synthetic in the default demo. Phase 1 uses real Alibaba 2018 DAGs, but edge data sizes are
   estimated, power per core is illustrative, and real task sizes depend on the `instance_num` scaling rule (D1, §17).
3. The oracle problem: the contract verifies schedules **given** the published data; it cannot prove the data is true.
   Phase 4 (§16) replaces the single owner with 5 bonded EIP-712 signers and a lower median (honest-majority
   assumption); the upstream data source itself is still trusted. The default demo still uses owner data (V1).
4. SQA is a classical simulation of quantum annealing: we claim *quantum-inspired*, not quantum advantage.
5. The blockchain overhead model is a parameterised estimate.
6. The market runs off-chain in the default demo. Phase 3 (§15) adds on-chain price rounds; their lower bound
   is certified only **assuming each workflow's minimum was submitted by at least one honest party** (Phase 4
   adds fraud proofs).

## 11b. Phase 2 — Quantum layer (experiment; not on the default demo path)

Plan: `docs/plans/PHASE2_QUANTUM.md`. Method, results and honest claims: `docs/QUANTUM_NOTES.md`.
Nothing here changes the demo, the market, the contract or `config/demo.yaml`.

**What it is.** The dual-price market (§6.5) splits the schedule into small per-workflow priced
sub-problems (3–5 tasks × 4 regions = 12–20 qubits, 64–1,024 feasible assignments). Phase 2 solves those
sub-problems with several methods under the **same evaluation budget** and compares them fairly against
the exact brute-force optimum.

| Code (`core/subproblem/`) | Method | Honest label |
|---|---|---|
| `exact.py` | brute force | reference |
| `rand.py` | random feasible sampling | sanity baseline |
| `sa.py` | simulated annealing | classical |
| `sqa.py` | simulated quantum annealing (path-integral MC) | quantum-inspired |
| `sb.py` | simulated bifurcation, ballistic + discrete | quantum-inspired |
| `qaoa_xy.py` | QAOA with XY ring / complete mixers (`qaoa_ring`, `qaoa_complete`) | quantum algorithm, classically simulated |
| `qaoa_xy.py` | same, angles from exact expectations (`*_ideal`) | quantum algorithm, classically simulated — optimistic upper bound, reported separately |

Supporting files: `model.py` (integer `SubProblem` with a hard evaluation counter), `qubo.py` (one-hot
penalised QUBO/Ising, used by SB), `optim.py` (numpy Nelder–Mead and SPSA). Dependencies: stdlib + numpy
only (AGENTS.md rule 9). QAOA is simulated **exactly inside the one-hot subspace** (the XY mixer never
leaves it); `tests/test_quantum.py` proves this equals a full 2ⁿ statevector simulation.

**Fair comparison** (`experiments/quantum_benchmark.py`, `config/quantum_bench.yaml`): same sub-problems,
seeds 0–29, budgets B ∈ {16, 64, 256} counted in energy evaluations (every SA/SQA move, SB readout, QAOA
shot — including estimation shots); parameters tuned on separate tuning instances (≤ 12 settings) and
frozen before the test run; P(optimum), normalised gap with 95 % bootstrap CIs; wall-clock reported only
as "simulator/CPU time, not indicative of hardware". Outputs go to `results/quantum/`.

```powershell
.\.venv\Scripts\python.exe -m experiments.quantum_benchmark --smoke   # seconds; also run inside pytest
.\.venv\Scripts\python.exe -m experiments.quantum_benchmark           # full run (tens of minutes)
```

**Honest framing.** At this size brute force solves every sub-problem in milliseconds. The benchmark
measures solution quality per unit of sampling budget on a classical simulator. It is not a claim of
practical usefulness and not a claim of quantum advantage.

## 12. From case study to full project
QAOA with constraint-preserving XY mixers on workflow sub-problems; on-chain price rounds; optimistic
lower-bound certification; multi-signer carbon oracle (EIP-712); ERC-20/ERC-721 via OpenZeppelin;
Hyperledger Besu permissioned network; real Electricity Maps and Alibaba data.

## 13. Glossary
**DAG** directed acyclic graph of tasks · **Carbon intensity** grams CO₂e per kWh of grid electricity ·
**SA / SQA** simulated (quantum) annealing · **Lagrangian relaxation** replacing a constraint with a price ·
**Lower bound** a value no schedule can beat · **Commit-reveal** publish a hash first, the value later ·
**Slashing** confiscating a misbehaving participant's stake · **Merkle root** one hash committing to many
items, enabling short proofs · **Gas** the unit of computation cost on Ethereum.

## 14. Evaluation — Phase 6-lite (synthetic data; not on the default demo path; full Phase 6: §19)

Plan: `docs/plans/PHASE6_EVALUATION.md`. One runner, one manifest; nothing here changes the demo, the
contract or `config/demo.yaml`. Profiles and the overhead grid are in `config/eval.yaml`.

```powershell
.\.venv\Scripts\python.exe -m experiments.run_all --profile smoke   # ~10 s; also run inside pytest
.\.venv\Scripts\python.exe -m experiments.run_all --profile lite    # ~4 min (8 cores) -> results\eval\
.\.venv\Scripts\python.exe -m experiments.figures                   # fig5-fig11 -> results\eval\figures\
```

`results/eval/manifest.json` records git commit, config + contract-artifact SHA-256s, seeds, package versions,
chain mode, every experiment run / NOT RUN (with reason) and output hashes. Anything that needs Phases 1, 3, 4
or 5 is an explicit `NOT RUN - Phase X missing` row (`not_run.csv`, 22 rows in the lite run); nothing is skipped
silently.

| ID | What runs now | Outputs | Needs later |
|---|---|---|---|
| E1 | Net carbon vs overhead on the unchanged 7-agent case-study flow, 2–64 workflows (7–298 tasks) × 3 seeds, **[VERIFY]** grid 0.01–10,000 Wh/Mgas × 40/400/700 g/kWh | `sensitivity.csv`, `breakeven.csv`, `tradeoff.csv`, fig5, fig6 | market-round, oracle/challenge gas (Ph. 3/4), PoA node term (Ph. 5) |
| E2 | Gas per function vs n (same runs), linear fits, block-limit check | `gas_scaling.csv`, `gas_fit.csv`, fig7 | `openMarket`/`submitBatch`/`closeRound` (Ph. 3), `challenge` (Ph. 4) |
| E3 | 15 case-study attacks **executed** (incl. malformed schedules and withdraw reentrancy via a hand-assembled attacker contract) | `attacks.csv`, `attacks.md` | 11 Phase 3/4/5 attacks; 4 assumption rows kept |
| E4 | greedy, SA (classical), SQA (quantum-inspired), dual-market (decomposition) on 10 synthetic instances × 30 solver seeds × 3 weight presets; SA at default **and move-matched** budget | `solvers.csv`, `solvers_summary.csv`, `classical_vs_qi.csv`, fig8, fig9 | real-data rows (Ph. 1) |

**Results of the lite run** (in-memory chain; synthetic instances; illustrative regions):

- **E1 — net carbon is a range, not a number.** Gross saving 47–3,386 g per epoch. Over the [VERIFY] grid the
  chain overhead is 0.001 %–80,000 % of the gross saving. Up to 10 Wh/Mgas (any intensity) every measured
  instance has a positive net saving; at ≥ 1,000 Wh/Mgas with ≥ 400 g/kWh, and at 10,000 Wh/Mgas with any
  intensity, none does. At 100 Wh/Mgas × 400 g/kWh
  the break-even is ≈ 76 tasks (fixed costs — deploy ≈ 2.0 M gas, 7 commits — dominate small instances).
  Gas is not energy: a PoA chain's energy is dominated by always-on nodes (Phase 5 term, NOT RUN).
- **Trade-off (off-chain only):** certified gap (median) 57 % after 5 market rounds, 33 % after 10, 13 % after
  25; the on-chain cost of those rounds needs Phase 3.
- **E2 — `publish` is the bottleneck.** ≈ 0.75 M + 83 k·n gas (R² 0.9998). Largest measured instance, 298
  tasks, publishes in 25.5 M gas (< 30 M reference block limit [VERIFY]); the linear fit extrapolates to ≈ 354
  tasks at 30 M. **The demo client's 15 M per-tx cap is exceeded from ≈ 172 tasks** (measured: 150 fits, 282
  does not). Reveal ≈ 0.25 M + 9.4 k·n, finalize ≈ 0.19 M + 1.3 k·n. Structural: m ≤ 255 regions (`uint8`).
- **E3 — 15/15 executed attacks defended** (observed = expected, asserted by `tests/test_attack_suite.py`);
  slashed stake 1 ETH each for over-capacity, copycat, no-show and both malformed schedules; the reentrant
  `withdraw` is stopped by `nonReentrant` and pays out once. 11 Phase 3–5 rows NOT RUN, 4 assumption rows.
- **E4 — quantum-inspired SQA has the smallest gap in 2 of 3 presets; classical matches or beats it in 1.**
  Gap to the Lagrangian lower bound, mean [95 % CI]: carbon-priority SA move-matched 15.2 [14.9, 15.4] vs SQA
  16.0 [15.8, 16.2] → **classical better** (paired Δ −0.85 pp [−1.13, −0.57]); balanced SQA 9.2 [9.0, 9.4] vs
  SA move-matched 10.8 [10.5, 11.1]; cost-priority SQA 9.5 [9.3, 9.6] vs 12.4 [12.0, 12.8]. At the old default
  budget SA got 4.5× fewer moves than SQA and lost in every preset — the move-matched comparison is the fair
  one. Dual-market (deterministic) 16–24 %, greedy 24–35 %. All schedules feasible. CPU time ≈ 0.45–0.5 s per
  SA-move-matched / SQA run (simulator time on a laptop, not indicative of hardware). No quantum advantage is
  claimed: SQA is a classical simulation, and SA parameters were not re-tuned for the longer budget.

**Phase 3 additions (lite run, 2026-11-19).** Every flow above also runs the on-chain market (25 rounds,
one honest batch submitter; Phase 3 `PriceMarket`) on the same chain; the 8 `NOT RUN - Phase 3 missing` rows
are now measured (14 NOT RUN rows remain):
- **Gas per market round** (submitBatch + closeRound) ≈ 0.21 M + 19.5 k·n: 0.41 M at 9 tasks, 0.92 M at 35,
  2.99 M at 147, 5.76 M at 298 (all < 30 M [VERIFY]). Fits: `openMarket` ≈ 1.41 M + 29.8 k·n (≈ 959 tasks at
  30 M), `submitBatch` ≈ 0.10 M + 17.0 k·n (≈ 1,764), `closeRound` ≈ 0.21 M + 2.5 k·n. `publish` stays the
  bottleneck.
- **E1 with the market term:** 25 on-chain rounds cost ≈ 2.2–3.5× the case-study flow's gas (e.g. 154 M vs
  44 M gas at 298 tasks). At 100 Wh/Mgas × 400 g/kWh the flow-only break-even is ≈ 76 tasks; including the
  market, **no measured size has a positive net saving** (net −4,527 … −537 g). Including the market, every
  measured instance stays net-positive only up to 1 Wh/Mgas (any intensity) or 10 Wh/Mgas at 40 g/kWh; at
  10 Wh/Mgas with 400–700 g/kWh the break-even falls inside the measured range. Fewer rounds or cheaper submissions are the levers (`tradeoff.csv` gives the
  measured gas of openMarket + k rounds).
- **E3:** 4 market attacks executed: 3 defended (inflated submission, incomplete round, validation reverts);
  the lone dishonest submitter is recorded as a **documented vulnerability** (Phase 4).

Threats to validity: simulated chain; overhead parameters without sources ([VERIFY]); synthetic workloads
and illustrative regions; 10 instances of one size in E4; the certified gap includes the looseness of the
lower bound itself.

## 15. Phase 3 — On-chain price market (`PriceMarket.sol`; not on the default demo path)

Plan: `docs/plans/PHASE3_PRICE_MARKET.md`. A **separate** contract, so `CarbonScheduleMarket.sol` and its
artifact stay byte-identical and the default demo output is unchanged.

| Piece | File |
|---|---|
| Contract (one file, no dependencies) | `chain/contracts/PriceMarket.sol` → `chain/build/PriceMarket.json` (`node chain/compile.js`, §9.3) |
| Integer Python mirror (no web3) | `core/market_int.py` |
| web3 wrapper | `chain/price_market.py` (`chain/client.py` unchanged) |
| Experiment | `experiments/onchain_market.py`, `config/onchain_market.yaml` → `results/onchain_market/{rounds.csv, gas.csv, summary.json}` |
| Tests | `tests/test_price_market.py` (16), `tests/test_artifacts.py` (V1 SHA-256 pin, opt-in recompile) |

How it works (integers only, mirrored exactly in Python):

- `openMarket` (owner) stores the instance, the workflow layout (contiguous tasks/edges per workflow; an edge
  crossing a workflow reverts) and a **step schedule fixed in advance**, `round(S₀·scale/√(k+1))`, so the owner
  cannot steer prices. It is linked to a `CarbonScheduleMarket` epoch.
- Each round, anyone calls `submit(w, x_w)` or `submitBatch(x)`. The contract scores
  V_w = Σ_j (w_c·E·ci·1000 + w_p·E·price + λ·cpu) + internal edge terms at the current prices λ and keeps the
  **minimum per workflow**.
- `closeRound` (owner): if every workflow was submitted, dual value g = Σ_w min V_w − Σ_d λ_d·cap_d, per-region
  loads, price update λ_d ← max(0, λ_d + tdiv(step·(load_d − cap_d)·m, Σcap)) (Solidity truncates toward zero;
  Python uses an explicit `tdiv`), best lower bound. An incomplete round gives no bound and keeps the prices.
- `certifiedGapBps` = (UB − LB)·10000/UB with UB = best revealed score of the linked epoch.

```powershell
.\.venv\Scripts\python.exe -m experiments.onchain_market               # seed 7, 25 rounds, ~16 s
.\.venv\Scripts\python.exe -m experiments.onchain_market --rounds 3    # quick run
```

**Seed-7 results** (25 rounds, one honest exact submitter per round; every round parity-checked):

| | |
|---|---|
| Lower bound on-chain (integer) / off-chain float | 638,827,725 / 638,827,640 (both valid bounds) |
| Upper bound (best revealed) · `certifiedGapBps` | 709,208,800 · **992 bps** (= 9.92 %) |
| `openMarket` (once) | 2.54 M gas |
| **Per round**: `submitBatch` (39 tasks) + `closeRound` | 0.71 M + 0.25 M = **0.96 M gas** (max 1.0 M; 3.3 % of a 30 M block [VERIFY]) |
| 25 rounds incl. `openMarket` | 26.5 M gas → 5.3 g CO₂e at 0.5 Wh/Mgas, 400 g/kWh (sensitivity parameters) vs 428 g net saving |
| `submit` of one workflow (4 / 5 / 6 tasks) | 131 k / 142 k / 141 k gas |

Parity tests (`tests/test_price_market.py`): `workflowValue` (50 random cases), `dualValueOf` incl. negative
values, `nextPrices` (200 fuzzed cases, negative imbalances), `gapBps`, Σ_w V_w at λ = 0 =
`CarbonScheduleMarket.evaluate`, a 25-round full run = `run_market_int`, weak duality (LB ≤ revealed scores;
on a 6-task instance LB ≤ brute-force optimum), min-keeping, incomplete rounds, and every validation revert.

**Honest claims.** The contract scores and updates prices; it never solves or repairs. The lower bound is
certified **assuming each workflow's minimum was submitted by at least one honest party**: a test and an E3 row
show that a lone dishonest submitter can push the "lower bound" above a feasible score. Phase 4 adds fraud
proofs. The instance data is supplied to both contracts by the owner and checked to agree only off-chain (Σ V_w
at λ = 0 equals `evaluate`); on-chain enforcement is Phase 4.

In the Phase 6 harness (§14), every E1/E2 flow now also runs the on-chain market on the same chain, and E3
executes four market attacks. That turned the 8 `NOT RUN - Phase 3 missing` rows into measured rows.
(Phase 4 later added fraud proofs to `PriceMarket`: `closeRound` now also stores a hash of λ_k, so the seed-7
round costs 0.98 M gas instead of 0.96 M; bounds and gap are unchanged. Numbers above are as measured in Phase 3.)

## 16. Phase 4 — Trust layer (oracle + fraud proofs; not on the default demo path)

Plan: `docs/plans/PHASE4_TRUST_LAYER.md` (decisions assumed from the plan's recommendations and confirmed by
the user on 2026-11-19 — see its "Decisions" section). V1 `CarbonScheduleMarket.sol` stays byte-identical; the default demo is
unchanged.

| Piece | File |
|---|---|
| Multi-signer EIP-712 carbon oracle | `chain/contracts/CarbonOracle.sol`; Python: `oracle/signer.py`, `core/oracle_math.py`, `chain/oracle_client.py` |
| V2 market: region carbon read from a finalised snapshot | `chain/contracts/CarbonScheduleMarketV2.sol` (V1 copy, only `publish` differs), `chain/client_v2.py` |
| Fraud proofs for lower-bound claims | added to `chain/contracts/PriceMarket.sol`; mirror in `core/market_int.py` (`MarketState.claim_bound / challenge / finalize_bound`) |
| Experiment | `experiments/trust_layer.py` → `results/trust/{gas.csv, attacks.csv, summary.json}` |
| Tests | `tests/test_trust_layer.py` (11), `tests/test_parity_v2.py` (5), `tests/test_fraud_proofs.py` (8) |

**Oracle.** `requestSnapshot(zones, hour, deadline)` → signers sign
`CarbonReport(requestId, zone, hourStart, ciGPerKwh, sourceHash, issuedAt)` (EIP-712 domain
"QICAS Carbon Oracle", version 1, chainId, contract) → anyone relays `submitReports`. Each report is checked
for signature format (65 bytes, v ∈ {27, 28}, **low-s**), a registered and bonded signer, the matching
request/hour/zone, freshness (`maxAge` 6 h, not in the future), the deadline, and one report per signer and zone.
`finalizeSnapshot` stores the **lower median** per zone (quorum 3 of 5). Anyone can slash a signer that signed
two different reports for one zone (`proveEquivocation`). Defaults are 5 signers, quorum 3, 1 ETH test bonds;
they are illustrative.

**Fraud proofs.** `claimBound(market, k)` + 1 ETH bond opens a 1 h window. Inside it, `challenge(market, k, w, x_w,
λ_k)` accepts any assignment of workflow w that is strictly cheaper at round k's prices. It lowers the kept
minimum and g_k, cancels the claim and pays the bond 50 % to the challenger and 50 % to the slashed pool. A
challenge that is not cheaper reverts, so a griefer loses only gas. `finalizeBound` after an unchallenged window
certifies g_k. `finalizedGapBps` uses finalised bounds only, while `certifiedGapBps` keeps its Phase 3 meaning.
This fixes the Phase 3 weakness: a lone dishonest submitter's inflated bound is corrected to ≤ the brute-force
optimum (test 16). `bindOracle` checks the market's carbon values against the oracle snapshot.

```powershell
.\.venv\Scripts\python.exe -m experiments.trust_layer      # seed 7, ~20 s -> results\trust\
```

**Seed-7 results** (in-memory chain; 5 signers × 4 zones):

| | gas |
|---|---|
| `requestSnapshot` / `submitReports` (20 reports, ≈ 45 k each) / `finalizeSnapshot` | 274,562 / 908,709 / 92,183 |
| `claimBound` / `finalizeBound` / `bindOracle` | 74,895 / 122,484 / 103,203 |
| `challenge` (successful fraud proof), 4 / 5 / 6-task workflow | 119 k / 137 k / 129 k |
| **Trust layer per epoch** (snapshot + claim + finalise, honest) | **1,472,845** (≈ 0.29 g at 0.5 Wh/Mgas, 400 g/kWh) |
| One-off: oracle deployment + 5 bonds | 1,774,394 |

Finalised lower bound 638,827,725 (round 20) → `finalizedGapBps` = 992, the same as Phase 3's
`certifiedGapBps`, because nothing in the honest run needed correcting. Attacks: 6 of 6 executed Phase 4 rows
defended (minority liars, stale report, replayed signature, equivocation, false bound claim, griefing challenge).
The tests cover all 22 attacks of the plan's §C table, plus parity for the EIP-712 digest, signer recovery, `medianLower` (200
fuzzed arrays), the four V1 parity checks against V2, and bound bookkeeping (on-chain = `MarketState`).

In the Phase 6 harness, E1 gains a third overhead definition (flow + market + trust layer), E2 gains the oracle
and fraud-proof functions, and E3 executes the Phase 4 rows. 7 NOT RUN rows remain: Phase 5 (4), Phase 1 (1),
E5 out of scope (1), E6 Besu (1).

**Honest claims.** The trust layer is trust-minimised, not trustless. It assumes an honest majority of signers
(test 15 shows 3 colluding signers set the value) and at least one honest, live watcher per challenge window.
With ≤ 7-task workflows, such a watcher can always find the exact minimum. Same-source risk remains: signers
reading the same wrong source agree. Bonds, quorum and window are not tuned for real economic security. Signer
bonds cannot be withdrawn yet (Phase 5).

## 17. Phase 1 — Real data (snapshot 2024-10-15T12:00Z; not on the default demo path)

**What changed.** `config/real_snapshot.yaml` replaces the illustrative region values with one cited snapshot hour
and the synthetic workload with real **Alibaba cluster-trace-v2018** DAGs; `config/demo.yaml` and the seed-7 demo are
unchanged (`build_instance` falls back to the synthetic generator when a config has no `workload:` key). No Solidity
change: the contract already accepts any integer regions/tasks/edges, and a trace-shaped fixture instance is
parity-tested (`tests/test_data_loaders.py`). Sources, licences, SHA-256s and known issues: `docs/DATA_SOURCES.md`.

| Region (zone) | Carbon intensity, direct (g CO₂e/kWh) | Day-ahead price | EUR/MWh (ECB 2024-10-15) | Model µUSD/kWh |
|---|---|---|---|---|
| Stockholm (SE-SE3) | 1.2 → **1** | 28.13 EUR/MWh (ENTSO-E SE3) | 28.13 | 30,670 |
| Ireland (IE) | 178.94 → **179** (EM estimate) | 88.50 EUR/MWh (ENTSO-E IE(SEM)) | 88.50 | 96,492 |
| Virginia (US-MIDA-PJM) | 320.46 → **320** | 35.20 USD/MWh (Electricity Maps API) | 32.28 | 35,200 |
| Mumbai (IN-WE) | 641.72 → **642** (EM estimate) | 3,964.56 Rs/MWh (IEX all-India MCP, 17:00–18:00 IST) | 43.27 | 47,178 |

Carbon: Electricity Maps (2026), 2024 hourly, dataset version 2026-02-10 (academic licence; cite; no redistribution).
Prices: ENTSO-E Transparency Platform [12.1.D]; Electricity Maps API (PJM Data Miner 2 was down); IEX India DAM
Market Snapshot (no W1–W3 regional columns, so the all-India MCP stands in for IN-WE). FX: ECB, USD 1.0903 and
INR 91.622 per EUR. Compared with the illustrative values (40 / 330 / 380 / 680 g/kWh), Stockholm is far cleaner
and Ireland cleaner; prices are lower everywhere except Ireland.

**Workload.** Of 4.2 M trace jobs, 906,932 pass the filters (3–7 tasks, parseable DAG names, Terminated, positive
durations, ≤ 4 cores). Seed 7 samples 8 jobs → 38 tasks, 30 edges (samples 0–9: 30–42 tasks; far below the ~172-task
publish gas cap). The extract stays local (`scripts/load_alibaba_dags.py`), because the trace's terms allow research
use but say nothing about redistribution.

**Results (seed 7, `python -m experiments.real_snapshot`).** Full 7-step pipeline: every honest reveal accepted,
the three attackers rejected/reverted/not revealed, contract baseline = Python baseline. 2 × 2 attribution
(off-chain, same solver settings):

| Workload × regions | Winner | Carbon baseline → winner | Reduction | Certified gap | Network share of winner score |
|---|---|---|---|---|---|
| synthetic × illustrative (= demo) | dual-market | 961.8 → 531.8 g | 44.7 % | ≤ 9.9 % | 4.2 % |
| synthetic × real snapshot | dual-market | 773.9 → 355.6 g | 54.1 % | ≤ 15.0 % | 2.6 % |
| real Alibaba × illustrative | dual-market | 238.3 → 21.5 g | 91.0 % | ≤ 24.6 % | 28.8 % |
| **real Alibaba × real snapshot** | **dual-market** | **187.0 → 6.5 g** | **96.5 %** (net 178.7 g after 1.78 g chain overhead) | **≤ 36.4 %** | 44.3 % |

Real-workload rows use **decision D1** (2026-11-23): a task is all its instances (`workload.task_size: instance_num`:
cores and energy × `instance_num`; capacity = ⌈total × share⌉ + largest task; method in `docs/DATA_SOURCES.md`).
Seed 7: 1,084 cores, 222 Wh task energy. Sensitivity: life-cycle carbon basis 222.8 → 11.7 g (94.7 %); IEX
overlap-weighted price (mean of 17–18 h and 18–19 h IST) 187.0 → 6.5 g (96.5 %); **D1 option (c) "1 Wh floor"**
(one representative instance per task, the pre-D1 method) SQA 121.0 → 8.9 g (92.6 %), gap ≤ 56.7 %.

**E4 on real data** (`run_all --profile lite`: 10 Alibaba samples × 30 solver seeds × 3 presets, same regions;
D1 `instance_num` scaling, full Phase 6 run 2026-11-23). Mean certified gap (95 % CI); every run feasible:

| Preset | greedy | SA default | SA move-matched | SQA (quantum-inspired) | dual-market |
|---|---|---|---|---|---|
| carbon-priority | 60.6 % | 32.2 % (31.4–33.0) | 31.1 % (30.2–32.0) | 27.5 % (27.2–27.9) | **23.0 %** |
| balanced | 59.0 % | 36.3 % (34.6–38.1) | 35.7 % (34.0–37.4) | 25.2 % (24.3–26.1) | **20.0 %** |
| cost-priority | 59.9 % | 36.2 % (34.8–37.6) | 34.0 % (32.5–35.4) | 20.5 % (19.2–21.9) | **19.5 %** |

With D1 the classical dual market has the smallest gap (CI of dual-market − SQA below 0 in carbon-priority and
balanced; includes 0 in cost-priority); SQA beats every SA variant (vs move-matched SA: +3.5 / +10.6 / +13.4 gap
points). **D1 sensitivity (1 Wh floor, the pre-D1 method):** SQA 46.3 / 40.9 / 44.2 %, SA move-matched 55.6 / 65.2 /
69.7 %, dual-market 86.7 / 91.1 / 94.3 % — under the floor SQA beat every classical variant. On synthetic instances
move-matched SA beats SQA under carbon-priority. Gaps are larger than on synthetic data because the bound is weak
here (see below).

**How to read this (honest claims).**
- Real snapshot regions alone (synthetic workload) raise the achievable reduction from 44.7 % to 54.1 %, mainly
  because Stockholm's real intensity (~1 g/kWh) is far below the illustrative 40.
- The real workload changes the picture more. One instance of a sampled task is 1 core for 1–174 s (median 8 s),
  i.e. **below 1 Wh**; the pre-D1 rule floored each task to 1 Wh (38 Wh vs an exact 2.38 Wh), so the
  **illustrative** network model dominated (97 % of the baseline score). D1 scales each task by its `instance_num`
  (seed 7: 222 Wh, 1,084 cores; network share of the baseline score 83 %). The capacity headroom that keeps the
  skewed samples feasible (one task can hold 92 % of a sample's cores) also makes capacity loose, so near-zero-carbon
  Stockholm absorbs most of the load: the ~96 % reduction is a model output under an illustrative capacity rule,
  not an achievable cloud saving. Treat the absolute grams as model outputs, not measurements.
- The certified gap is wide (≤ 36 % with D1, ≤ 57 % with the 1 Wh floor) because the Lagrangian bound relaxes the
  cross-region edge coupling, which is large here; under the 1 Wh floor, 25 rounds of the dual market also produce
  the worst schedule of the four solvers on the seed-7 instance (with D1 it wins).
  SQA's lead over SA on real instances is a comparison of two *classical* heuristics (SQA is quantum-inspired,
  simulated on a CPU) at the demo's settings; the SA temperature schedule was not re-tuned for the real
  instances' ~30× smaller score scale (a possible cause, not verified). No quantum-advantage claim.
- One hour, one day: not real time, not a forecast. IE and IN-WE intensities are Electricity Maps estimates; C3 has
  outliers at 11:00Z (137.34) and 23:00Z (332.43 USD/MWh), kept as is and not affecting 12:00Z.
- Decided (D1, 2026-11-23): scale by `instance_num` (option (a)); the 1 Wh floor stays as a sensitivity row. Not
  chosen: a finer energy unit (mWh — changes contract units, needs Solidity + parity work). Per-pair
  latency/egress tables are Phase 1b.

## 18. Phase 5 — Consortium chain (Besu QBFT) + OpenZeppelin tokens (not on the default demo path)

**What changed.** Three new contracts and a local 4-validator **Hyperledger Besu QBFT** network; V1
(`CarbonScheduleMarket`, still the default demo) and V2 are byte-identical (`node chain/compile.js --check`: 7 × IDENTICAL).

| Piece | File | What it does |
|---|---|---|
| ERC-20 credits | `chain/contracts/QicasCredit.sol` | OpenZeppelin `ERC20` + `ERC20Burnable` + `AccessControl`; `decimals = 0` (1 QCC = 1 g CO₂e NET saving); only `MINTER_ROLE` mints; `retire(amount, beneficiary, reason)` burns + emits `Retired`; transferable |
| Certificates | `chain/contracts/ScheduleCertificate.sol` | **soulbound** ERC-721 (tokenId = epochId): `transferFrom`, `safeTransferFrom`, `approve`, `setApprovalForAll` revert `Soulbound()`; ERC-5192 `locked`; on-chain `CertData` (Merkle root, instance hash, baseline/winner carbon, net saving, certified gap, oracle requestId, market) and `tokenURI` = `data:application/json;base64,…` |
| Market | `chain/contracts/CarbonScheduleMarketV3.sol` | V2 (oracle-fed `publish`, same scoring) + `finalize(epoch, overhead, priceMarket, marketId)` mints ⌊net g⌋ credits and the certificate to the winner; gap = `PriceMarket.finalizedGapBps` of a linked market (Phase 4 fraud-proof bound), 10000 = none |
| OpenZeppelin | `chain/vendor/openzeppelin/` | 5.4.0, 21 files + LICENSE + `VERSION.md`, resolved offline by `compile.js` (5.5+ needs the Cancun opcode `mcopy`; we compile for `paris`) |
| Network | `chain/besu/` | `hyperledger/besu:26.10.2@sha256:bc599f5e…` (pinned), 4 validators (tolerates 1 faulty), 2 s blocks, chainId 1338, zero gas price, deterministic **TEST-ONLY** keys/genesis (`generate.py`), RPC 127.0.0.1:8545–8548 |
| Python | `chain/tokens.py`, `chain/client_v3.py`, `demo/pipeline_v3.py`, `Chain.start("besu")` | local signing with the TEST keys; `run_demo --mode besu`; `core/certificate.py` = Python mirror of credits rule and certificate JSON |

**Tests.** Default (offline): `test_tokens.py` (9), `test_market_v3.py` (7), `test_besu_config.py` (5), Phase 5 rows in
`test_attack_suite.py` / `test_eval_smoke.py`. Opt-in: `$env:QICAS_BESU='1'; pytest -m besu` (4 tests;
`QICAS_BESU_VOTE=1` adds the validator vote test); they skip cleanly when nothing answers on 127.0.0.1:8545.

**Results (seed 7; `python -m experiments.besu_vs_memory` -> `results/besu/`, 2026-11-23).**

| | in-memory (py-evm) | Besu QBFT (4 validators) |
|---|---|---|
| V1 demo: scores, attacker outcomes, winner, Merkle root, credits | 4 accepted / rejected / HashMismatch / not revealed; dual-market; `0x6b5b7933…`; 428 | **identical** |
| V1 flow gas (16 txs) | 9,576,573 | 9,576,561 (−12: one commit hash binds a different sender address → calldata zero bytes) |
| V1 deploy / publish / finalize gas | 2,042,126 / 3,903,934 / 236,284 | identical |
| V1 flow wall-clock, blocks | 7.9 s, 15 blocks (automine) | 32.3 s, 16 blocks |
| Send → confirmation per tx (dry-run + send + receipt) | 0.1–1.5 s | **≈ 1.8–2.3 s** (= the 2 s block period) |
| V3 token flow (oracle, tokens, V3, 2 market rounds + claim; 31 txs + market) | 19,811,982 gas, 14.7 s | 19,811,650 gas, 78.2 s, 39 blocks |
| V3 `finalize` (incl. credit mint + certificate mint) | 502,580 (V1: 236,284) | 502,580 |
| One-off: credit / certificate / V3 deploy | 853,500 / 1,592,542 / 2,284,572 | same (±24) |
| Credits / certificate (V3 flow) | 427 QCC (net 427.97 g; V3's own gas → overhead 1.93 g) + soulbound certificate #1 | same |
| Optional vote test | – | 5th validator voted in after 9.5 s, out after 11.5 s; blocks continued |

With 25 market rounds and the 1-hour challenge window waited out by time travel (in-memory only), the certificate
carries **`certifiedGapBps` = 992** (= the demo's 9.92 %). On Besu the window runs in real time, so the test checks
that an early `finalizeBound` reverts `WindowOpen` and the certificate says 10000 (no certified bound).

**E3 Phase 5 rows (executed, all defended):** unauthorised credit/certificate mint → `AccessControlUnauthorizedAccount`
×2; double certificate → `WrongPhase` (re-finalize) and `CertificateExists` (second minter, same epoch); minting
after the admin renounced → `AccessControlUnauthorizedAccount` ×2 (no new minters; V3 keeps its role); certificate
transfer/approval → `Soulbound` ×2. **E1** gets the PoA node term (`poa_node_term.csv`: 4 validators × {5, 50, 200}
W × {0.01, 1, 24} h per epoch, **[VERIFY]**, ranges only). **E6** is real when `QICAS_BESU=1` and the network is up,
else `NOT RUN - Besu not running`. Smoke harness NOT RUN rows: 6 → 2 (E5 out of scope; E6 opt-in).

**How to read this (honest claims).**
- One laptop running 4 validators *models* a provider consortium; it says nothing about real providers'
  willingness, latency between data centres, or production security. Keys and zero gas price are TEST ONLY.
- Gas is not energy: on a PoA network the always-on validators dominate (E1 PoA term: e.g. 4 × 50 W × 1 h =
  200 Wh = 80 g at 400 g/kWh, far above the ≈ 1.9 g gas term of one demo epoch). The node parameters have no source.
- A certificate attests that this ledger verified a schedule against oracle data; it is only as good as the oracle
  majority and a live challenger (Phase 4 assumptions). Retirement prevents double counting **within this ledger only**.
- The V3 flow mints 427 credits vs V1's 428 only because V3's own transactions are counted in the overhead.

## 19. Full Phase 6 — Evaluation E1–E6, dashboard, final report (DONE 2026-11-23)

Plan: `docs/plans/PHASE6_EVALUATION.md`. **Report: `docs/FINAL_REPORT.md`** (methods, results with ranges and honest
labels, limitations, threats to validity, citations); `docs/CASE_STUDY_REPORT.md` is unchanged.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\besu_up.ps1                         # only for E6
$env:QICAS_BESU='1'; .\.venv\Scripts\python.exe -m experiments.run_all --profile lite   # E1-E6, ~29 min (8 cores)
.\.venv\Scripts\python.exe -m experiments.figures                                   # fig5-fig11 + fig8r/fig9r
powershell -ExecutionPolicy Bypass -File scripts\besu_down.ps1
.\.venv\Scripts\python.exe scripts\make_report_pack.py --screenshots                # report_pack/ + report_pack.zip
```

- **Time budget (decision D3):** the `lite` profile already covers the planned grid (E2 to ≈ 300 tasks; E4 10
  instances × 30 seeds × 3 presets on synthetic + real data), so no separate full profile was run. Runtime 1,717.6 s;
  **0 NOT RUN rows** with Besu up (smoke without Besu: 1 row, E6).
- **New:** E5 (`experiments/e5_quantum.py`, copies the Phase 2 tables with their source, never re-runs); E4 real-data
  rows use D1 (`task_size: instance_num`) plus the **1 Wh floor sensitivity dataset**; figures fig10 (E5), fig11 (E6),
  fig8r/fig9r (E4 real); dashboard tabs **On-chain market**, **Oracle & challenges**, **Tokens** (in-memory V3 token flow
  with a retirement and the decoded certificate JSON); the optional "Live" tab was skipped (D3). Report pack:
  `scripts/make_report_pack.py`, `scripts/report_diagrams.py` (7 diagrams), `scripts/screenshot_app.py`.

| Exp. | Key result (details and sources: FINAL_REPORT §4) |
|---|---|
| E1 | Net saving only as a range: at 1 Wh/Mgas all 18 flows net-positive under every overhead definition; at 100 Wh/Mgas × 400 g/kWh none once the 25-round market is included. PoA node term 0.008–13,440 g per epoch ([VERIFY]) dominates gas. Median certified gap 57 / 33 / 13 % after 5 / 10 / 25 rounds. |
| E2 | `publish` ≈ 748 k + 82.6 k·n gas; 298 tasks measured < 30 M; fit hits 30 M at ≈ 354 tasks; demo 15 M tx cap at ≈ 172. |
| E3 | 28 of 29 executed attacks defended; 1 Phase 3 vulnerability closed by Phase 4; 4 documented assumptions. |
| E4 | Synthetic: SQA (quantum-inspired) smallest gap in 2/3 presets, move-matched SA (classical) better under carbon-priority. Real (D1): classical dual-market smallest gap (19.5–23.0 %), SQA second (20.5–27.5 %), SA 31–36 %. 1 Wh floor sensitivity: SQA 41–46 %, dual-market 87–94 %. |
| E5 | P(opt) at 256 evaluations: SB 0.99, SQA 0.91, SA 0.81, simulated QAOA 0.62–0.72, random 0.62. |
| E6 | Besu: identical outcomes; gas −12 (V1) / −116 (V3); confirmation ≈ 2 s per tx; V1 flow 33.4 s vs 8.6 s. |
