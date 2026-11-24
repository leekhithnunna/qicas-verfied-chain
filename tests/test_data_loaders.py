"""Phase 1 data loaders (docs/plans/PHASE1_REAL_DATA.md §3). Synthetic fixtures only: these tests pass on a
machine without data/. Tests that read the real raw files are skipped when data/ is absent."""
from __future__ import annotations

import json
import random
import zipfile
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

import pytest
import yaml

from core.data import alibaba, carbon, prices, snapshot
from core.data.alibaba import Limits
from core.instance import Instance, build_instance, generate_instance
from core.scoring import evaluate

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
TINY = FIX / "alibaba_batch_task_tiny.csv"
FIXTURE_JSON = FIX / "alibaba_dags_fixture.json"
HOUR = datetime(2030, 1, 2, 12, tzinfo=timezone.utc)
REAL_CFG = ROOT / "config" / "real_snapshot.yaml"


def load(p):
    return yaml.safe_load(Path(p).read_text(encoding="utf-8"))


def make_fixture_workload(seed: int = 7, n: int = 3) -> str:
    """Processed JSON text from the tiny trace (same code path and serialisation as the CLI script)."""
    eligible, counts = alibaba.scan_eligible(TINY)
    names = alibaba.sample_names(eligible, n, seed)
    jobs = alibaba.collect_jobs(TINY, names)
    wl = alibaba.to_workload(jobs, seed, 12, (6.0, 1.0), {"filter_counts": counts, "source": "synthetic fixture"})
    return json.dumps(wl, indent=1, sort_keys=True) + "\n"


# ------------------------------------------------------------------------------------------- Alibaba
def test_task_name_parsing():
    assert alibaba.parse_task_name("M1") == (1, [])
    assert alibaba.parse_task_name("R5_2_3") == (5, [2, 3])
    assert alibaba.parse_task_name("J12_10") == (12, [10])
    for bad in ("task_xyz", "MergeTask", "M", "5_1", ""):
        assert alibaba.parse_task_name(bad) is None


def test_every_filter_counts():
    eligible, counts = alibaba.scan_eligible(TINY)
    assert eligible == ["j_10", "j_11", "j_20"]
    expected = {"jobs_seen": 11, "eligible": 3, "bad_task_name": 1, "status": 1, "time": 1, "too_few_tasks": 1,
                "too_many_tasks": 1, "duplicate_task": 0, "missing_parent": 1, "cycle": 1, "no_plan_cpu": 0,
                "too_many_cores": 1, "non_contiguous": 0, "malformed_rows": 0}
    assert counts == expected


def test_non_contiguous_job_is_dropped(tmp_path):
    rows = TINY.read_text(encoding="utf-8").splitlines()
    p = tmp_path / "t.csv"
    p.write_text("\n".join(rows + ["M9,1,j_10,1,Terminated,10,20,100,0.2"]) + "\n", encoding="utf-8")
    eligible, counts = alibaba.scan_eligible(p)
    assert "j_10" not in eligible and counts["non_contiguous"] == 1


def test_unit_conversion_hand_computed():
    jobs = alibaba.collect_jobs(TINY, ["j_10", "j_11"])
    wl = alibaba.to_workload(jobs, 0, 12, (6.0, 1.0))
    got = [(t["name"], t["workflow"], t["cpu"], t["energy_wh"]) for t in wl["tasks"]]
    # cpu = ceil(plan_cpu/100); energy = max(1, round_half_up(cpu * seconds / 3600 * 12)); topological order
    assert got == [("j_10/M1", 0, 1, 12), ("j_10/M2", 0, 2, 12), ("j_10/R3_1_2", 0, 1, 12), ("j_10/J4_3", 0, 4, 5),
                   ("j_11/M1", 1, 1, 6), ("j_11/R2_1", 1, 3, 6), ("j_11/R3_2", 1, 2, 1)]
    assert [(e["j"], e["k"]) for e in wl["edges"]] == [(0, 2), (1, 2), (2, 3), (4, 5), (5, 6)]
    for t in wl["tasks"]:
        assert all(isinstance(t[k], int) for k in ("workflow", "cpu", "energy_wh"))
    assert all(isinstance(e["volume_mb"], int) and e["volume_mb"] >= 1 for e in wl["edges"])
    assert wl["meta"]["instance_num"] == [2, 3, 5, 1, 1, 1, 1] and wl["meta"]["volume_source"] == "estimated"
    assert wl["meta"]["duration_s"] == [3600, 1800, 3600, 360, 1800, 600, 150]
    assert wl["meta"]["exact_task_energy_wh"] == 53.8 and wl["meta"]["tasks_below_1wh"] == 0
    assert alibaba.energy_wh(1, 1, 12) == 1 and alibaba.energy_wh(4, 450, 12) == 6   # 6.0 exactly; 0.0033 -> 1


def test_limits_are_parameters():
    eligible, _ = alibaba.scan_eligible(TINY, Limits(min_tasks=3, max_tasks=7, max_cpu=6))
    assert "j_17" in eligible


def test_determinism_and_sampling():
    assert make_fixture_workload() == make_fixture_workload()
    eligible, _ = alibaba.scan_eligible(TINY)
    samples = {tuple(alibaba.sample_names(eligible, 2, s)) for s in range(10)}
    assert len(samples) > 1, "different seeds must give different samples when eligible > sample"
    with pytest.raises(ValueError):
        alibaba.sample_names(eligible, 4, 0)


def test_frozen_fixture_reproduced_byte_for_byte():
    assert FIXTURE_JSON.read_text(encoding="utf-8").replace("\r\n", "\n") == make_fixture_workload(), \
        "regenerate with: python -c \"from tests.test_data_loaders import write_fixture; write_fixture()\""


def write_fixture() -> None:                      # helper, not a test
    FIXTURE_JSON.write_text(make_fixture_workload(), encoding="utf-8", newline="\n")


# ------------------------------------------------------------------------------------------- build_instance
def test_build_instance_default_path_unchanged():
    cfg = load(ROOT / "config" / "demo.yaml")
    for s in (3, 7):
        assert build_instance(cfg, s).instance_hash() == generate_instance(cfg, s).instance_hash()


def test_build_instance_from_file_is_valid_and_market_ready():
    cfg = load(FIX / "fixture_snapshot.yaml")
    inst = build_instance(cfg, 7)
    assert isinstance(inst, Instance) and inst.n == 10 and inst.m == 4
    assert all(len(ix) <= 7 for ix in inst.workflows().values())
    total = sum(t.cpu for t in inst.tasks)
    assert [r.capacity for r in inst.regions] == [max(1, -(-total * s // 100)) for s in (25, 40, 45, 45)]
    for e in inst.edges:
        assert e.j < e.k and inst.tasks[e.j].workflow == inst.tasks[e.k].workflow
    assert build_instance(cfg, 7).instance_hash() == inst.instance_hash()
    from core.market import run_market
    mk = run_market(inst, rounds=5, step0=1.0)
    assert evaluate(inst, mk.best_schedule).feasible


def test_build_instance_task_size_instance_num():
    """D1 option (a): cores and energy scale by instance_num; capacity = ceil(total x share) + largest task;
    the round-robin baseline (contract rule) stays feasible; option (c) (default key) is unchanged."""
    from core.scoring import round_robin_baseline
    cfg = load(FIX / "fixture_snapshot.yaml")
    rep = build_instance(cfg, 7)
    cfg["workload"]["task_size"] = "instance_num"
    inst = build_instance(cfg, 7)
    d = json.loads(FIXTURE_JSON.read_text(encoding="utf-8"))["meta"]
    k, s, w = d["instance_num"], d["duration_s"], d["watts_per_core"]
    assert [t.cpu for t in inst.tasks] == [r.cpu * ki for r, ki in zip(rep.tasks, k)]
    assert [t.energy_wh for t in inst.tasks] == [
        max(1, (2 * r.cpu * si * w * ki + 3600) // 7200) for r, si, ki in zip(rep.tasks, s, k)]
    total, big = sum(t.cpu for t in inst.tasks), max(t.cpu for t in inst.tasks)
    assert [r.capacity for r in inst.regions] == [max(1, -(-total * p // 100)) + big for p in (25, 40, 45, 45)]
    assert evaluate(inst, round_robin_baseline(inst)).feasible
    assert inst.meta["task_size"] == "instance_num" and rep.meta["task_size"] == "representative"
    cfg["workload"]["task_size"] = "bogus"
    with pytest.raises(ValueError, match="task_size"):
        build_instance(cfg, 7)


def test_build_instance_missing_file_says_data_missing(tmp_path):
    cfg = load(FIX / "fixture_snapshot.yaml")
    cfg["workload"]["path"] = str(tmp_path / "nope.json")
    with pytest.raises(FileNotFoundError, match="data missing"):
        build_instance(cfg, 7)


def test_parity_on_real_shaped_instance():
    """Fixture (trace-shaped) instance scores identically in Python and the contract."""
    from chain.client import Chain
    from core.scoring import round_robin_baseline
    inst = build_instance(load(FIX / "fixture_snapshot.yaml"), 7)
    chain = Chain.start("memory")
    eid = chain.publish(inst)
    assert chain.baseline_schedule(eid) == round_robin_baseline(inst)
    rng = random.Random(5)
    for _ in range(15):
        x = [rng.randrange(inst.m) for _ in range(inst.n)]
        e = evaluate(inst, x)
        assert chain.evaluate(eid, x) == (e.score, e.carbon_ug, e.cost_nusd, e.feasible)


# ------------------------------------------------------------------------------------------- carbon
def test_em_subscript_header_and_basis():
    d = carbon.read_carbon(FIX / "em_tiny.csv", HOUR)
    assert (d.value, d.g_per_kwh, d.basis, d.estimated, d.zone) == (carbon.Decimal("222.50"), 223, "direct", True,
                                                                    "XX-TEST")
    lca = carbon.read_carbon(FIX / "em_tiny.csv", HOUR, "lca")
    assert lca.g_per_kwh == 260                     # 260.49 rounds down
    with pytest.raises(ValueError, match="no row"):
        carbon.read_carbon(FIX / "em_tiny.csv", datetime(2030, 1, 3, 12, tzinfo=timezone.utc))
    assert carbon.normalize_header("Carbon intensity gCO₂eq/kWh (direct)") == "carbonintensitygco2eqkwhdirect"


def test_hour_must_be_utc_and_aligned():
    assert carbon.parse_hour("2024-10-15T12:00:00Z") == datetime(2024, 10, 15, 12, tzinfo=timezone.utc)
    for bad in ("2024-10-15T12:00:00", "2024-10-15T12:30:00Z", "2024-10-15T12:00:00+05:30"):
        with pytest.raises(ValueError):
            carbon.parse_hour(bad)


def test_legacy_script_recognises_subscript_header():
    import scripts.load_em_snapshot as legacy
    assert legacy.read_intensity(FIX / "em_tiny.csv", HOUR) == 223


# ------------------------------------------------------------------------------------------- prices
def test_entsoe_hourly_15min_negative_and_timezone():
    r = prices.read_entsoe(FIX / "entsoe_tiny.csv", HOUR)
    assert (r.value, r.currency, r.detail["area"]) == (Fraction("50.25"), "EUR", ["BZN|XX"])
    assert prices.read_entsoe(FIX / "entsoe_15min_tiny.csv", HOUR).value == 55     # time-weighted mean
    with pytest.raises(ValueError, match="negative"):
        prices.read_entsoe(FIX / "entsoe_negative_tiny.csv", HOUR)
    with pytest.raises(ValueError, match="not in UTC"):
        prices.read_entsoe(FIX / "entsoe_cet_tiny.csv", HOUR)


def test_em_price_json():
    r = prices.read_em_price_json(FIX / "em_price_tiny.json", HOUR)
    assert (r.value, r.currency, r.detail["row_source"]) == (Fraction("21.8"), "USD", "synthetic")


def write_iex_xlsx(path: Path, mcp: dict[int, str], extra_cols: tuple[str, ...] = ()) -> None:
    """Minimal hourly IEX 'Market Snapshot' workbook (inline strings), stdlib only."""
    def cell(ref, v):
        if isinstance(v, str) and not v.replace(".", "").isdigit():
            return f'<c r="{ref}" t="inlineStr"><is><t>{v}</t></is></c>'
        return f'<c r="{ref}"><v>{v}</v></c>'
    head = ["Date", "Hour", "Purchase Bid (MWh)", "MCP (Rs/MWh) *", *extra_cols]
    rows = [[f"Market Snapshot"], ["Date: 02-01-2030"], head]
    rows += [["02-01-2030", str(h), "100.00", mcp.get(h, "3000.00")] for h in range(1, 25)]
    rows += [["Date", "Summary", "Purchase Bid (MWh)", "MCP (Rs/MWh) *"], ["02-01-2030", "Avg", "100.00", "9999"]]
    cols = "ABCDEFG"
    xml_rows = "".join(f'<row r="{i + 1}">' + "".join(cell(f"{cols[j]}{i + 1}", v) for j, v in enumerate(r))
                       + "</row>" for i, r in enumerate(rows))
    sheet = ('<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/'
             f'spreadsheetml/2006/main"><sheetData>{xml_rows}</sheetData></worksheet>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", sheet)


def test_iex_ist_to_utc(tmp_path):
    p = tmp_path / "iex.xlsx"
    write_iex_xlsx(p, {18: "4000.00", 19: "5000.00"})
    r = prices.read_iex_xlsx(p, HOUR)        # 12:00Z = 17:30 IST -> Hour 18 = [17:00, 18:00) IST
    assert (r.value, r.currency, r.detail["ist_hour_start"]) == (Fraction(4000), "INR", "2030-01-02T17:00:00+05:30")
    assert r.detail["scope"].startswith("all-India")
    assert prices.read_iex_xlsx(p, HOUR, "overlap").value == 4500   # [17:30, 18:30) IST: half of 18, half of 19
    p2 = tmp_path / "iex_w.xlsx"
    write_iex_xlsx(p2, {}, ("W1", "W2"))
    assert prices.read_iex_xlsx(p2, HOUR).detail["scope"] == "regional"


def test_fx_conversion_exact():
    eur = prices.to_eur_per_mwh(prices.PriceReading(Fraction("35.2"), "USD", "x"), {"USD": "1.0903"})
    assert prices.to_uusd_per_kwh(eur, "1.0903") == 35200          # USD passes through unchanged
    assert prices.to_uusd_per_kwh(Fraction("50.25"), "1.0903") == 54788      # 54787.575 -> half-up
    assert prices.to_uusd_per_kwh(Fraction("88.5"), "1.0903") == 96492       # 96491.55 -> half-up
    inr = prices.to_eur_per_mwh(prices.PriceReading(Fraction("91.622"), "INR", "x"), {"INR": "91.622"})
    assert inr == 1 and prices.to_uusd_per_kwh(inr, "1.0903") == 1090
    with pytest.raises(ValueError):
        prices.to_eur_per_mwh(prices.PriceReading(Fraction(1), "GBP", "x"), {"USD": "1"})


def test_snapshot_compute_on_fixtures():
    cfg = load(FIX / "fixture_snapshot.yaml")
    rows = snapshot.compute(cfg["snapshot"], ROOT)
    assert [(r.name, r.ci_g_per_kwh, r.price_uusd_per_kwh) for r in rows] == [("r0", 223, 54788), ("r1", 223, 21800)]
    assert snapshot.check_regions(cfg["regions"][:2], rows) == []
    bad = [dict(cfg["regions"][0], ci_g_per_kwh=1)]
    assert snapshot.check_regions(bad, rows) == ["r0: ci_g_per_kwh committed 1 != recomputed 223"]


# ------------------------------------------------------------------------------------------- real config
def test_real_config_shape_without_data():
    """Committed config: integers only, four regions, citations/hashes for every source, demo untouched."""
    cfg = load(REAL_CFG)
    assert [r["name"] for r in cfg["regions"]] == [r["name"] for r in load(ROOT / "config/demo.yaml")["regions"]]
    for r in cfg["regions"]:
        assert isinstance(r["ci_g_per_kwh"], int) and isinstance(r["price_uusd_per_kwh"], int)
        assert r["price_uusd_per_kwh"] > 0
    assert set(cfg["snapshot"]["sources"]) == {r["name"] for r in cfg["regions"]}
    assert all(len(v) == 64 for v in snapshot.raw_files(cfg["snapshot"]).values())
    assert cfg["snapshot"]["hour"] == "2024-10-15T12:00:00Z"
    assert "workload" not in load(ROOT / "config/demo.yaml")


real_data = pytest.mark.skipif(not snapshot.data_present(load(REAL_CFG)["snapshot"], ROOT),
                               reason="data missing (data/raw/ is git-ignored; see docs/DATA_SOURCES.md)")


@real_data
def test_real_snapshot_matches_raw_files():
    cfg = load(REAL_CFG)
    assert all(h["match"] for h in snapshot.verify_hashes(cfg["snapshot"], ROOT).values())
    assert snapshot.check_regions(cfg["regions"], snapshot.compute(cfg["snapshot"], ROOT)) == []


@pytest.mark.skipif(not (ROOT / load(REAL_CFG)["workload"]["path"]).is_file(),
                    reason="data missing (run scripts/load_alibaba_dags.py)")
def test_real_instance_valid_and_under_gas_cap():
    cfg = load(REAL_CFG)
    inst = build_instance(cfg, 7)
    assert 0 < inst.n <= 56 and len(inst.workflows()) == 8          # far below the ~172-task publish gas cap
    assert all(len(ix) <= 7 for ix in inst.workflows().values())
    assert inst.meta["workload_meta"]["raw_sha256"] == \
        "7c4b32361bd1ec2083647a8f52a6854a03bc125ca5c202652316c499fbf978c6"


def test_real_snapshot_experiment_without_data(tmp_path, monkeypatch):
    import experiments.real_snapshot as rs
    monkeypatch.setattr(rs, "workload_path", lambda cfg, seed=None: tmp_path / "missing.json")
    lines = []
    assert rs.run(tmp_path / "out", log=lines.append) == {"status": "NOT RUN - data missing"}
    assert "NOT RUN - data missing" in lines[0] and not (tmp_path / "out").exists()
