# Phase 1 — Real data (plan)

- **Status:** DONE 2026-11-23 (results: README §17, PROJECT_PLAN "Phase 1 results"; data: `docs/DATA_SOURCES.md`).
- **Planned:** 2026-11-13
- **Parent:** `docs/PROJECT_PLAN.md` → Phase 1
- **Invariant:** `config/demo.yaml` and the synthetic generator keep exactly their current code path, so
  the default seed-7 output cannot change. Real data enters only through a new optional `workload:` key in
  a new config. No Solidity change is needed: the contract already accepts any integer regions, tasks and
  edges.

## Prerequisites

| # | Prerequisite | Owner | Status |
|---|---|---|---|
| P1 | Raw files downloaded into `data/raw/` (table in §1) | user | done (2026-11-23): all of A, B1–B4, C1–C4, D ingested; SHA-256s in `docs/DATA_SOURCES.md` |
| P2 | Answers to the open decisions below | user | done (2026-11-19) |
| P3 | Case study complete (pytest 8 passed, demo matches RUN_GUIDE.md) | — | done |

## Open decisions

1. **Commit the small processed Alibaba extract** (`data/processed/*.json`, a few KB) so others can run
   without the 14 M-row download? Recommended: yes, if the trace licence allows redistributing derived
   data **[VERIFY on the clusterdata page]**.
2. **Snapshot hour:** is `2024-10-15T12:00:00Z` OK, or is there a preferred date?
3. **Task size:** one representative instance per task (recommended; magnitudes comparable to the current
   demo), or scale energy by `instance_num` (more realistic totals, but cores then need scaling too or
   capacity repair fails)?

## Decisions (approved)

Recorded 2026-11-13.

- **Build order:** Phase 1 is built **after Phase 2 and Phase 6-lite**, when the raw downloads (§1) are
  ready. Full order: Phase 2 → Phase 6-lite → Phase 1 → Phases 3, 4, 5 → full Phase 6.
- Open decisions 1–3 answered by the user on 2026-11-19 (all as recommended):
  1. **Commit the processed extract: yes, if the licence allows** redistributing derived data. Check the
     clusterdata licence when implementing; if it does not allow it, keep `data/processed/` local.
  2. **Snapshot hour: `2024-10-15T12:00:00Z`.** ECB reference rates for that date (fetched from the ECB data
     API, saved as `data/raw/fx/ecb_2024-10-15.csv`): **USD 1.0903 per EUR, INR 91.622 per EUR**.
  3. **Task size: one representative instance per task**; `instance_num` kept in `meta` only.
     **Superseded by D1 (below).**
- **D1 — energy unit / task size (approved by the user 2026-11-23): option (a) "scale by `instance_num`".**
  The 1-instance rule floored every real task to 1 Wh (all 38 seed-7 tasks are below 1 Wh; 38 Wh vs an exact
  2.38 Wh), so the illustrative network model dominated. Now, behind the real-snapshot config only
  (`workload.task_size: instance_num` in `config/real_snapshot.yaml`; `config/demo.yaml` and the default demo are
  unchanged): task energy = per-instance energy × `instance_num`, rounded to integer Wh (minimum 1); task cores =
  `cpu × instance_num`; region capacity = `ceil(total cores × capacity_share) + largest task` so every instance stays
  feasible (the round-robin baseline provably fits; details and consequences in `docs/DATA_SOURCES.md`).
  Option (c) "1 Wh floor" (`task_size: representative`) is reported as a sensitivity/ablation row in
  `experiments.real_snapshot` and in E4. Implementation: `core/instance.py::scale_by_instance_num`; tests:
  `tests/test_data_loaders.py::test_build_instance_task_size_instance_num`, `tests/test_eval_smoke.py`.
  Seed 7: winner dual-market, 187.0 → 6.5 g (96.5 %), certified gap ≤ 36.4 % (option (c): SQA, 121.0 → 8.9 g,
  92.6 %, gap ≤ 56.7 %).

---

## 1. Files the user downloads (into `data/raw/`, git-ignored)

**First pick one UTC hour**, e.g. `HOUR = 2024-10-15T12:00:00Z`, and use it for every source.
A past year (2024) is recommended because:
- Electricity Maps lets you download full past years for free.
- Before 1 Oct 2025, European day-ahead prices were hourly. After that date the European day-ahead market
  switched to 15-minute periods.

Pick a weekday hour with no negative prices. The contract stores prices as `uint256`, so the loader will
refuse negative prices rather than clamp them.

| # | Region | File to save | Source and steps |
|---|---|---|---|
| A | (workload) | `data/raw/alibaba/batch_task.csv` (or the `.tar.gz`) | github.com/alibaba/clusterdata → `cluster-trace-v2018/`. Download links and checksums are in `fetchData.sh` / `trace_2018.md`. Download **batch_task only** (about 14 M rows). Check the licence and whether a survey is required **[VERIFY]**. |
| B1 | Stockholm | `data/raw/carbon/SE-SE3_2024_hourly.csv` | electricitymaps.com/data-portal: zone **Sweden SE3** (`SE-SE3`), 2024, hourly, CSV. |
| B2 | Ireland | `data/raw/carbon/IE_2024_hourly.csv` | Same portal, zone **Ireland** (`IE`). |
| B3 | Virginia | `data/raw/carbon/US-MIDA-PJM_2024_hourly.csv` | Same portal, zone **PJM** (`US-MIDA-PJM`). |
| B4 | Mumbai | `data/raw/carbon/IN-WE_2024_hourly.csv` | Same portal, zone **Western India** (`IN-WE`). |
| C1 | Stockholm | `data/raw/prices/entsoe_SE3_2024-10-15.csv` | transparency.entsoe.eu (free account) → Market → Day-ahead Prices → bidding zone **SE3** → that day → time zone **UTC** → Export CSV. |
| C2 | Ireland | `data/raw/prices/entsoe_IE-SEM_2024-10-15.csv` | Same, bidding zone **IE(SEM)**. |
| C3 | Virginia | `data/raw/prices/em_price_US-MIDA-PJM_2024-10-15.json` — **used instead:** Electricity Maps API v4 day-ahead price, zone US-MIDA-PJM, USD/MWh, UTC (PJM Data Miner 2 was down). Originally planned: `pjm_da_DOM_2024-10-15.csv` | dataminer2.pjm.com → **Day-Ahead Hourly LMPs** (`da_hrl_lmps`) → pnode type ZONE, **DOM** → that day → export CSV. Use `total_lmp_da` and its UTC timestamp. |
| C4 | Mumbai | `data/raw/prices/iex_dam_2024-10-15.xlsx` — **used instead:** IEX DAM *Market Snapshot* (hourly, IST, all-India MCP; no W1–W3 columns, so all-India MCP stands in for IN-WE). Originally planned: `iex_dam_2024-10-15.csv` | iexindia.com → Market Data → Day-Ahead Market → Area Prices → that day → export. 15-minute blocks in IST (UTC+5:30); the loader averages the 4 blocks covering the UTC hour. Use the Western-region bid area covering Maharashtra **[VERIFY W1/W2/W3]**. |
| D | (FX) | none; two numbers in the config | ECB euro reference rates for that date: USD per EUR and INR per EUR (to derive USD per INR). |

Add `data/raw/` to `.gitignore`. `data/README.md` holds a provenance table (source, licence, URL,
retrieval date, SHA-256 per raw file); the loaders compute the hashes automatically.

## 2. Design

### 2.1 `scripts/load_alibaba_dags.py` (raw trace → small processed JSON)

- **Input:** `batch_task`, no header, columns `task_name, instance_num, job_name, task_type, status,
  start_time, end_time, plan_cpu, plan_mem`. Read row by row (plain `.csv` or straight from `.tar.gz`), so
  the 14 M rows never sit in memory.
- **Parsing dependencies:** `R5_2_3` means "task 5, depends on tasks 2 and 3". Leading letter(s) = task
  type, first number = task id, remaining numbers = parents. A job is kept only if **every** task matches
  `^[A-Za-z]+(\d+)(?:_(\d+))*$`. Jobs with names like `task_xyz` or `MergeTask` carry no dependency
  information and are dropped.
- **Job filters (each counted and reported):** status `Terminated`; end time after start time; 3–7 tasks
  (`--min-tasks 3 --max-tasks 7`; 7 is the market's limit); every parent exists inside the same job; graph
  acyclic; `plan_cpu` present.
- **Converting tasks:**
  - `cpu = ceil(plan_cpu/100)` (`plan_cpu` is in 1/100 core). Jobs where any task exceeds `--max-cpu 4` are
    dropped, not clamped.
  - `energy_wh = max(1, round(cpu × (end−start)/3600 × watts_per_core))`.
  - Each task is treated as one representative instance; `instance_num` kept in `meta` (open decision 3).
- **Edges:** the trace has **no data sizes**. Each edge gets a volume drawn from the config's log-normal,
  seeded, flagged `"volume_source": "estimated"`.
- **Deterministic sampling:** collect eligible job names → sort → `random.Random(seed).sample(eligible,
  n_workflows)` → topological task order within each job, jobs ordered by name. Same raw file + seed ⇒
  byte-identical output.
- **Output:** `data/processed/alibaba_dags_seed7_n8.json` = `{"tasks": [...], "edges": [...], "meta":
  {source sha256, filter counts, seed, sampled job names}}`, only the `Task`/`Edge` fields from
  `core/instance.py`. Regions and network come from the config.
- **Code split:** pure parsing/conversion in `core/data/alibaba.py` (no web3/streamlit, AGENTS rule 4);
  the script is a thin CLI wrapper, so tests call the functions directly.

### 2.2 Extending `scripts/load_em_snapshot.py`, plus new `scripts/load_prices.py`

- **Header fix (likely needed):** recent Electricity Maps exports appear to use headers like
  `Carbon Intensity gCO₂eq/kWh (direct)` with a subscript ₂. The loader's normaliser deletes that
  character, giving `carbonintensitygcoeqkwhdirect`, which is not in the candidate list. Add the subscript
  variants and check against the real file; existing names keep working.
- **`--basis direct|lca`:** choose the column explicitly; default `direct`; recorded.
- **`--config config/real_snapshot.yaml`:** already supported; document it in README §5.
- **`--out FILE`:** optionally write the region block plus a `snapshot:` metadata section (hour, basis, CSV
  hashes). Without the flag it prints exactly as now.
- **New `scripts/load_prices.py`:** one `--region NAME=SOURCE:CSV` per region (SOURCE ∈ `entsoe`, `pjm`,
  `iex`), plus `--hour`, `--eur-usd`, `--inr-usd`. Converts to integer µUSD/kWh:
  **1 USD/MWh = 1,000 µUSD/kWh**, rounded half-up. Fails on negative or missing prices; explicit time-zone
  handling per source. Parsing code in `core/data/prices.py`.

### 2.3 Pipeline wiring (the only change to existing code)

- **`core/instance.py`:** add `build_instance(cfg, seed)`:
  - no `workload` key → returns `generate_instance(cfg, seed)` (default path byte-for-byte identical);
  - `workload.source == "file"` → load the processed JSON, add regions (capacity =
    `ceil(total_cpu × capacity_share)`, same rule as now), network and weights; snapshot provenance in
    `meta`.
- **`demo/pipeline.py:47`:** `generate_instance(...)` → `build_instance(...)`. Dashboard keeps `demo.yaml`.
- **New `config/real_snapshot.yaml`:** copy of `demo.yaml` with real `ci_g_per_kwh` and
  `price_uusd_per_kwh`, plus:
  ```yaml
  workload: {source: file, path: data/processed/alibaba_dags_seed7_n8.json}
  snapshot: {hour: 2024-10-15T12:00:00Z, carbon_basis: direct, fx: {eur_usd: …, inr_usd: …, date: …}, sources: {...sha256...}}
  ```
  `capacity_share`, `network`, `watts_per_core` keep demo values and stay labelled illustrative.
- **Out of scope (→ Phase 1b):** latency, egress and per-pair network tables. They need per-pair edge costs,
  i.e. changing `evaluate` in Python and Solidity, recompiling, and extending parity tests.

## 3. Tests: `tests/test_data_loaders.py` + `tests/fixtures/`

Fixtures (tiny, hand-written, committed):
- `alibaba_batch_task_tiny.csv` (~25 rows): a valid 4-task DAG; a valid 3-task chain; `task_xyz` job
  (dropped); missing parent (dropped); cycle (dropped); 8-task job (dropped); status `Failed` (dropped);
  a task needing 6 cores (dropped).
- `em_tiny.csv`: 3 hours, subscript-₂ headers, both direct and LCA columns.
- `entsoe_tiny.csv`, `pjm_tiny.csv`, `iex_tiny.csv`: a few rows each, including one negative price.
- `fixture_snapshot.yaml`: config whose `workload` points at a fixture-derived processed JSON.

Tests:
1. Task-name parsing (`M1` → (1, []), `R5_2_3` → (5, [2, 3]), `task_xyz` → None).
2. Every filter: only the 2 valid jobs survive; drop counts as expected.
3. Unit conversion: cpu and energy match hand-computed integers; every field is `int`.
4. Determinism: same seed ⇒ byte-identical JSON; different seed ⇒ different sample when eligible > sample.
5. Processed JSON → `build_instance` → valid `Instance`; market accepts every workflow (≤ 7 tasks).
6. Electricity Maps: subscript header detected; `--basis lca` picks LCA; missing hour raises.
7. Prices: one test per source for units and timestamps (incl. IEX 15-min averaging across the IST offset);
   negative price raises.
8. Parity on real-shaped data: fixture instance scores identically in Python and the contract.
9. `build_instance(demo cfg)` gives the same instance hash as `generate_instance` (guards the default path).

## 4. After approval

1. Implement everything above.
2. Run pytest and `demo.run_demo` with `config/demo.yaml` (must match RUN_GUIDE.md) and with
   `config/real_snapshot.yaml`. If raw files are not yet downloaded, run the second config against
   `fixture_snapshot.yaml`; `real_snapshot.yaml` then ships with clearly marked `TODO` values.
3. Update README §5 and PROJECT_PLAN.md status.
4. Commit, without pushing.
