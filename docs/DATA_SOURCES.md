# Data sources, licences and provenance (Phase 1)

All raw files live under `data/raw/` and are **git-ignored** (`.gitignore`: `data/`). They are never
committed, even to the private `origin` repository. Only the few **derived snapshot inputs** the model needs
(one number per region, in `config/real_snapshot.yaml`) are committed, each with a citation.
`tests/test_repo_hygiene.py` fails if anything under `data/raw/` becomes tracked.

**Snapshot hour:** `2024-10-15T12:00:00Z`, i.e. the UTC hour `[12:00, 13:00)` (approved 2026-11-19).
**Download checklist:** `data/raw/DOWNLOAD_CHECKLIST.md` (exact file names and folders).

## Summary

| # | Dataset | Final path (git-ignored) | SHA-256 | Commit raw? |
|---|---|---|---|---|
| A | Alibaba cluster-trace-v2018 `batch_task` | `data/raw/alibaba/batch_task.tar.gz` | `7c4b32361bd1ec2083647a8f52a6854a03bc125ca5c202652316c499fbf978c6` | no (extract stays local too, see A) |
| B1 | Electricity Maps carbon intensity SE-SE3 | `data/raw/carbon/SE-SE3_2024_hourly.csv` | `c0e31cca51a9aa55412c381a75fa1903dcea776d797567b18dba1b87ccbbd928` | **never** |
| B2 | Electricity Maps carbon intensity IE | `data/raw/carbon/IE_2024_hourly.csv` | `3a6cbf671f123185491f4341be16e06e6c693bd1d547556d9b600dcc3fc17ecb` | **never** |
| B3 | Electricity Maps carbon intensity US-MIDA-PJM | `data/raw/carbon/US-MIDA-PJM_2024_hourly.csv` | `79b932595ccc6afcb2e0985af105f6d6602a46fc8e0ada63a31935c466751581` | **never** |
| B4 | Electricity Maps carbon intensity IN-WE | `data/raw/carbon/IN-WE_2024_hourly.csv` | `b9d7ec4715e33330a1e7bfbd53b974c14b305187b23d5c40b971f52ae065c306` | **never** |
| C1 | ENTSO-E day-ahead price SE3 | `data/raw/prices/entsoe_SE3_2024-10-15.csv` | `24244197521228deb583b1cc11ce1c0d6e4cdbd3598fd489fe8cc35d7c44cefb` | no |
| C2 | ENTSO-E day-ahead price IE(SEM) | `data/raw/prices/entsoe_IE-SEM_2024-10-15.csv` | `98e18c7815df467f9d661e33caf12f1ed423129c2c461c896a9e5a49b69fa53f` | no |
| C3 | Electricity Maps API day-ahead price US-MIDA-PJM | `data/raw/prices/em_price_US-MIDA-PJM_2024-10-15.json` | `f149b3d2bd53ae97c5c42fe885c170344988e53ebdf2e06d2fb7e2ebb4f4ebba` | **never** |
| C4 | IEX India DAM Market Snapshot | `data/raw/prices/iex_dam_2024-10-15.xlsx` | `6c7a045ae47bd82ac04a979b9ddc229798cd6d19dde4d17c7b5000a6d80928a3` | no |
| D | ECB euro reference rates | `data/raw/fx/ecb_2024-10-15.csv` | `062214684d73882866726ae781a161862a807e157d57dda43e612ab056caa63a` | no (the two rates are in the config) |

The loaders recompute these hashes and record them in the run outputs; a mismatch is reported.

---

## A — Alibaba cluster-trace-v2018, `batch_task`

- **Source:** Alibaba Cluster Trace Program, https://github.com/alibaba/clusterdata → `cluster-trace-v2018/`
  (download link from `fetchData.sh`; checksums in `trace_2018.md`).
- **Obtained:** downloaded by script 2026-11-19; 130,310,549 bytes; SHA-256 matched the official checksum.
  The archive holds one file, `batch_task.csv` (802,261,444 bytes, ~14 M rows, no header).
- **Columns:** `task_name, instance_num, job_name, task_type, status, start_time, end_time, plan_cpu, plan_mem`.
  Times in seconds from the trace start (relative, no calendar date); `plan_cpu` in 1/100 core.
- **Use:** DAG structure (dependencies encoded in task names, e.g. `R5_2_3` = task 5 depends on 2 and 3),
  cores and duration per task. The processed file stores one representative instance per task plus the per-task
  `instance_num` and `duration_s` in `meta`; since **decision D1 (2026-11-23)** `core/instance.py::build_instance`
  scales each task by `instance_num` when the config says `workload.task_size: instance_num` (see "Task size (D1)").
- **Licence:** no licence file in the repository (checked 2026-11-23: `LICENSE` returns 404). The README
  states: *"You may use trace however you want as long as it is for reseach or study purpose."* Nothing is
  said about redistributing derived data. **Decision (per the approved rule "commit only if the licence
  allows"):** the processed extract `data/processed/alibaba_dags_*.json` is **kept local**; it is
  regenerated deterministically by `scripts/load_alibaba_dags.py` from the raw archive (same SHA-256 + seed ⇒
  byte-identical output).
- **Citation:** "Alibaba Cluster Trace Program, cluster-trace-v2018. https://github.com/alibaba/clusterdata".
  The maintainers ask to be told about publications using the trace (alibaba-clusterdata@list.alibaba-inc.com).
  Commonly cited analysis: Guo et al., "Who Limits the Resource Efficiency of My Datacenter: An Analysis of
  Alibaba Datacenter Traces", IWQoS 2019.
- **Filter counts (full trace, pass 1):** 4,201,014 jobs; **906,932 eligible**; dropped: bad task name
  1,029,401; too few tasks (< 3) 1,469,223; too many tasks (> 7) 313,385; zero/negative duration 451,563;
  status ≠ Terminated 30,453; > 4 cores 55; no `plan_cpu` 2; missing parent / cycle / duplicate / non-contiguous 0.
- **Known issues:**
  - The trace has **no data-transfer sizes** — edge volumes are drawn from the config's seeded log-normal and
    flagged `volume_source: estimated`. Energy uses the illustrative `watts_per_core` (12 W).
  - **Tasks are tiny under "one representative instance per task":** in the seed-7 sample every task uses
    1 core and runs 1–174 s (median 8 s), so every task is **below 1 Wh** (exact total 2.38 Wh). The contract
    unit is integer Wh, so each task is raised to 1 Wh (total 38 Wh, ~16× the exact value). The processed file
    records `duration_s`, `exact_task_energy_wh` and `tasks_below_1wh`. Consequence: on real workloads the
    (illustrative) network terms are a large share of the score. **Resolved by decision D1** (below); this
    "1 Wh floor" (option (c)) is now only a sensitivity row.
  - **Task size (D1, approved 2026-11-23, option (a) "scale by `instance_num`"):** with
    `workload.task_size: instance_num` (set in `config/real_snapshot.yaml`; the processed files are unchanged):
    - task cores = `cpu × instance_num` (the instances run side by side);
    - task energy = `max(1, round_half_up(cpu × duration_s × watts_per_core × instance_num / 3600))` Wh (integer
      arithmetic; `watts_per_core` = 12 W, illustrative);
    - region capacity = `ceil(total cores × capacity_share) + largest task's cores`. The added headroom keeps
      every instance feasible: with Σ shares ≥ 1 the contract's round-robin baseline always places every task
      (if each region had less than one largest task left, the total left would be below m × max, but it is at
      least (Σ shares − 1) × total + m × max). Without it, 4 of the 10 samples are infeasible, because one task
      holds up to 92 % of a sample's cores.
    - Seed-7 sample: 1,084 cores, **222 Wh** task energy (option (c): 38 Wh; exact one-instance energy 2.38 Wh).
      Samples 0–9: 62 – 18,967 Wh and 159 – 31,442 cores (very skewed: `instance_num` reaches 24,895).
    - **Consequences:** (1) the instance sizes now come from the trace, so task energy is no longer swamped by the
      illustrative network model (winner network share of score 44 % vs 31 % before; baseline 83 % vs 97 %);
      (2) the headroom makes capacity loose, so the near-zero-carbon region (Stockholm, 1 g/kWh) can take most
      of the load, and carbon reductions are very large (seed 7: 96.5 %); they are model outputs under an
      illustrative capacity rule, not achievable cloud savings; (3) integer contract units and the parity rules are
      unchanged (the change is entirely in instance construction; the default demo does not use it);
      (4) option (c) stays reproducible with `task_size: representative` and is reported next to the main result
      (`experiments.real_snapshot` sensitivity row; E4 dataset `real, 1 Wh floor (D1 sensitivity, option (c))`).
    - Not chosen: a finer energy unit (mWh), which would change the contract units and need Solidity + parity work.

## B1–B4 — Electricity Maps carbon intensity, 2024 hourly

- **Source:** Electricity Maps data portal, dataset version **2026-02-10**, granularity hourly, year 2024.
  Original file names `B{1..4}__snapshots_2026-02-10_<ZONE>-2024-hourly.csv`.
- **Zones:** B1 `SE-SE3` (South Central Sweden → `eu-north-1 (Stockholm)`), B2 `IE` (Ireland →
  `eu-west-1 (Ireland)`), B3 `US-MIDA-PJM` (PJM → `us-east-1 (Virginia)`), B4 `IN-WE` (Western India →
  `ap-south-1 (Mumbai)`).
- **Format:** CSV, 8,784 rows each (2024 is a leap year), columns `Datetime (UTC)`, `Country`, `Zone name`,
  `Zone id`, `Carbon intensity gCO₂eq/kWh (direct)`, `Carbon intensity gCO₂eq/kWh (Life cycle)`, `CFE%`, `RE%`,
  `Data source`, `Data estimated`, `Data estimation method`.
- **Units / time zone:** gCO₂eq/kWh; timestamps are UTC hour starts (no offset suffix in the file).
- **Basis used:** `direct` (operational) by default, rounded half-up to whole g/kWh (contract integer unit);
  `--basis lca` is available. Recorded in the config `snapshot:` block.
- **Licence:** used under an **academic licence** (institutional account of a team member): non-commercial use
  only; **no redistribution** of the data; credentials are not shared; Electricity Maps must be cited in any
  shared or published work. ⇒ raw files and per-hour values are **never** committed; only the four snapshot
  numbers (one per zone, for one hour) appear in `config/real_snapshot.yaml`, with this citation.
- **Citation:** "Electricity Maps (2026). Carbon intensity data, 2024 hourly, zones SE-SE3, IE, US-MIDA-PJM,
  IN-WE, dataset version 2026-02-10. https://www.electricitymaps.com".
- **Known issues:**
  - **IE:** every 2024 row is flagged `Data estimated = true` (`ESTIMATED_MODE_BREAKDOWN`), including the
    snapshot hour.
  - **IN-WE:** 7,507 of 8,784 rows are estimated (`ESTIMATED_MODE_BREAKDOWN`), including the snapshot hour.
  - **SE-SE3:** the direct value is very small (~1 g/kWh); rounding to whole g/kWh is a large *relative*
    rounding error for this zone (documented, not changed: the contract unit is g/kWh).
  - SE-SE3 (2 rows) and US-MIDA-PJM (11 rows) contain a few estimated hours; the snapshot hour is measured.

## C1, C2 — ENTSO-E day-ahead prices, SE3 and IE(SEM)

- **Source:** ENTSO-E Transparency Platform (new GUI), Energy Prices [12.1.D], delivery day 2024-10-15,
  exported as CSV. Original names `C1__GUI_ENERGY_PRICES_202410150000-202410160000.csv` (C1) and
  `... (1).csv` (C2).
- **Format:** 24 hourly rows; columns `MTU (UTC)` (e.g. `15/10/2024 12:00:00 - 15/10/2024 13:00:00`), `Area`
  (`BZN|SE3`, `BZN|IE(SEM)`), `Sequence`, `Day-ahead Price (EUR/MWh)`, intraday columns (empty).
- **Units / time zone:** EUR/MWh; **UTC** (verified: the time column header inside the file is `MTU (UTC)`).
  Hourly MTU (before the 1 Oct 2025 switch to 15-minute MTUs). No negative prices that day.
- **Licence / redistribution:** ENTSO-E Transparency Platform terms of use (attribution required)
  **[VERIFY exact terms]**. Project rule: raw file stays git-ignored; only the derived snapshot price is
  committed, with citation.
- **Citation:** "ENTSO-E Transparency Platform, Energy Prices [12.1.D], SE3 and IE(SEM), 2024-10-15".
- **Known issues:** none.

## C3 — US-MIDA-PJM day-ahead price (Electricity Maps API)

- **Source:** Electricity Maps API v4, `price-day-ahead` past-range, zone `US-MIDA-PJM`, 2024-10-15, accessed
  2026-11-23. **Why not PJM:** PJM Data Miner 2 (`da_hrl_lmps`, zone DOM), the originally planned source, was
  down. Several rows cite `pjm.com` as their source; most have `source: null`.
- **Format:** JSON `{zone, data: [24 × {zone, datetime, createdAt, updatedAt, value, unit, source}],
  temporalGranularity: "hourly"}`.
- **Units / time zone:** USD/MWh; UTC (`...Z` timestamps).
- **Licence:** Electricity Maps academic licence (as B1–B4): no redistribution, cite. The API key is **never**
  written to any file, log, config, test or commit (it lives only in a session environment variable when
  needed; it is not needed to run anything in this repository).
- **Citation:** "Electricity Maps API, day-ahead price US-MIDA-PJM, accessed 2026-11-23".
- **Known issues:**
  - **Outlier at 23:00Z = 332.43 USD/MWh** (other hours ~17–39). Flagged, **not "fixed"**; it does not
    affect the 12:00Z snapshot.
  - A second spike at **11:00Z = 137.34 USD/MWh** (found during ingestion). Also left as is.
  - This is a zone-level PJM price as served by Electricity Maps, not the Dominion (DOM) zonal LMP originally
    planned.

## C4 — IEX India Day-Ahead Market, Market Snapshot

- **Source:** IEX India (iexindia.com) → Day-Ahead Market → **Market Snapshot** export, delivery date
  15-10-2024 (verified in the sheet header `Date: 15-10-2024`), hourly interval. Original name
  `C4__DAM_Market Snapshot (1).xlsx`.
- **Format:** one sheet; header row `Date, Hour, Purchase Bid (MWh), Sell Bid (MWh), MCV (MWh), Final
  Scheduled Volume (MWh), MCP (Rs/MWh) *, Weighted MCP (Rs/MWh)`; 24 rows `Hour = 1..24`; summary rows
  (Total/Max/Min/Avg) are ignored. Read with the Python standard library (`zipfile` + XML), no new dependency.
- **Units / time zone:** Rs/MWh (INR); **IST (UTC+5:30)**. `Hour = h` covers `[h−1:00, h:00)` IST.
- **Hour alignment:** the snapshot instant 12:00Z = 17:30 IST lies in **Hour 18 (17:00–18:00 IST)** — the
  approved rule. Note: the UTC hour `[12:00, 13:00)Z` = `[17:30, 18:30)` IST straddles Hours 18 and 19; the
  loader can also compute the overlap-weighted mean (`align: overlap`), reported as a sensitivity value only.
- **Regional vs all-India:** the Market Snapshot has **no regional (W1–W3) area-price columns**, so the
  **all-India MCP is used for IN-WE** (Mumbai). This is a documented approximation; under congestion the
  Western-region area price can differ from the all-India MCP.
- **Licence / redistribution:** IEX website terms **[VERIFY]**. Project rule: raw file stays git-ignored;
  only the derived snapshot price is committed, with citation.
- **Citation:** "IEX India, Day-Ahead Market snapshot, 2024-10-15".

## D — ECB euro foreign exchange reference rates, 2024-10-15

- **Source:** ECB Data Portal, series `EXR.D.USD.EUR.SP00.A` and `EXR.D.INR.EUR.SP00.A`, fetched 2026-11-19.
- **Values:** **USD 1.0903 per EUR**, **INR 91.622 per EUR**.
- **Use:** every price is converted to EUR/MWh (reported), then to the model unit µUSD/kWh with the same
  ECB EUR→USD rate (`1 USD/MWh = 1,000 µUSD/kWh`), using exact decimal arithmetic and one half-up rounding at
  the end. USD prices therefore pass through unchanged (35.2 USD/MWh → 35,200 µUSD/kWh).
- **Licence:** ECB statistics may be reused with the source cited.
- **Citation:** "ECB euro reference exchange rates, 2024-10-15".
