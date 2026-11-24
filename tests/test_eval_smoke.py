"""Phase 6-lite harness (experiments/run_all.py), smoke profile only: offline, a few seconds."""
import json
import time

import pytest

from experiments import e1_e2_overhead_gas as e12
from experiments import e3_attacks as e3
from experiments import e4_solvers as e4
from experiments import e5_quantum as e5
from experiments.besu_vs_memory import E6_COLUMNS, besu_available
from experiments.eval_common import BESU_MISSING, read_csv
from experiments.run_all import NOT_RUN_COLUMNS, run

# file -> required columns (every experiment CSV also carries `status`)
EXPECTED_COLUMNS = {
    "not_run.csv": NOT_RUN_COLUMNS,
    "sensitivity.csv": e12.SENSITIVITY_COLUMNS,
    "breakeven.csv": e12.BREAKEVEN_COLUMNS,
    "tradeoff.csv": e12.TRADEOFF_COLUMNS,
    "gas_scaling.csv": e12.GAS_COLUMNS,
    "gas_fit.csv": e12.FIT_COLUMNS,
    "attacks.csv": e3.ATTACK_COLUMNS,
    "solvers.csv": e4.RAW_COLUMNS,
    "solvers_summary.csv": e4.SUMMARY_COLUMNS,
    "classical_vs_qi.csv": e4.VS_COLUMNS,
    "poa_node_term.csv": e12.POA_COLUMNS,          # Phase 5
    "besu_vs_memory.csv": E6_COLUMNS,              # Phase 5 (E6)
    **e5.COLUMNS,                                  # Phase 2 tables (E5, copied, not re-run)
}


def test_e5_copies_phase2_tables_or_says_not_run(tmp_path):
    """E5 never re-runs Phase 2: it copies the tables with their source, or writes one explicit NOT RUN row."""
    from experiments.eval_common import Context
    cfg = {"e5": {"source": str(tmp_path / "nope")}}
    ctx = Context("smoke", {}, cfg, {}, tmp_path / "out", lambda *_: None)
    res = e5.run_e5(ctx)
    assert res.not_run and res.not_run[0]["status"] == e5.E5_MISSING
    for f in e5.COLUMNS:
        assert [r["status"] for r in read_csv(tmp_path / "out" / f)] == [e5.E5_MISSING]
    src = tmp_path / "q"
    src.mkdir()
    (src / "summary.csv").write_text("method,label,budget,n_subproblems,p_opt\nsa,classical,16,3,0.5\n"
                                     "sqa,quantum-inspired,16,3,0.25\n", encoding="utf-8")
    (src / "classical_vs.csv").write_text("budget,method,label\n16,sqa,quantum-inspired\n", encoding="utf-8")
    (src / "market.csv").write_text("inst_seed,ub_solver,label\n0,sqa,quantum-inspired\n", encoding="utf-8")
    ctx = Context("smoke", {}, {"e5": {"source": str(src)}}, {}, tmp_path / "out2", lambda *_: None)
    res = e5.run_e5(ctx)
    assert not res.not_run
    rows = read_csv(tmp_path / "out2" / "quantum_summary.csv")
    assert [(r["method"], r["label"], r["status"]) for r in rows] == [("sa", "classical", "ok"),
                                                                      ("sqa", "quantum-inspired", "ok")]
    assert res.summary["highest_p_opt_per_budget (runnable methods)"]["16"]["method"] == "sa"


@pytest.fixture(scope="module")
def smoke(tmp_path_factory):
    out = tmp_path_factory.mktemp("eval_smoke")
    t0 = time.perf_counter()
    manifest = run("smoke", out_dir=out, log=lambda *_: None)
    return out, manifest, time.perf_counter() - t0


def test_smoke_runs_fast_and_writes_manifest(smoke):
    out, manifest, dt = smoke
    assert dt < 60, f"smoke profile took {dt:.1f} s"
    on_disk = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    for key in ("git", "configs_sha256", "contract_artifact_sha256", "data_snapshots", "environment",
                "chain_mode", "profile_settings", "experiments", "not_run", "outputs", "runtime_s"):
        assert key in on_disk, key
    assert on_disk["profile"] == "smoke"
    assert set(on_disk["experiments"]) == {"E1", "E2", "E3", "E4", "E5", "E6"}
    # Phase 5 present: E6 runs; without the opt-in Besu network it records an explicit NOT RUN row
    assert on_disk["experiments"]["E6"]["status"] == "run"
    e6 = read_csv(out / "besu_vs_memory.csv")
    if not besu_available():
        assert [r["status"] for r in e6] == [BESU_MISSING]
        assert any(r["experiment"] == "E6" and r["status"] == BESU_MISSING for r in read_csv(out / "not_run.csv"))
    else:
        assert {r["chain"] for r in e6} == {"memory", "besu"} and all(r["status"] == "ok" for r in e6)


def test_every_csv_has_expected_columns(smoke):
    out, manifest, _ = smoke
    for name, cols in EXPECTED_COLUMNS.items():
        rows = read_csv(out / name)
        header = list(rows[0].keys()) if rows else []
        assert header, f"{name} is empty"
        assert set(cols) <= set(header), (name, set(cols) - set(header))
        if name != "not_run.csv":
            assert "status" in header, name


def test_not_run_rows_are_explicit(smoke):
    out, manifest, _ = smoke
    rows = read_csv(out / "not_run.csv")
    assert rows, "phases 1/3/4/5 are missing, so there must be NOT RUN rows"
    for r in rows:
        assert r["status"].startswith("NOT RUN"), r
        assert r["status"] != "defended"
    # every experiment either ran or is accounted for as NOT RUN
    accounted = {r["experiment"] for r in rows if r["note"] in ("whole experiment", "") or "scope" in r["status"]}
    for eid, e in manifest["experiments"].items():
        assert e["status"] == "run" or eid in accounted, (eid, e)


def test_e1_overhead_formula_and_labels(smoke):
    out, _, _ = smoke
    rows = read_csv(out / "sensitivity.csv")
    ok = [r for r in rows if r["status"] == "ok"]
    assert ok
    for r in ok:
        assert r["label"].startswith("[VERIFY]")
        expect = int(r["gas_total"]) / 1e6 * float(r["energy_wh_per_million_gas"]) * float(r["chain_ci_g_per_kwh"]) / 1000
        assert abs(float(r["overhead_g"]) - expect) <= 1e-9 * max(1.0, expect)
        assert abs(float(r["net_saving_g"]) - (float(r["gross_saving_g"]) - float(r["overhead_g"]))) < 1e-6
    statuses = {r["status"] for r in rows}
    assert statuses == {"ok"}, "Phases 3-5 are built: no NOT RUN overhead term is left"
    # Phase 5 PoA node term: validators x W x h on top of the trust-layer gas term, same chain ci
    poa = read_csv(out / "poa_node_term.csv")
    assert poa and all(r["status"] == "ok" and r["label"].startswith("[VERIFY]") for r in poa)
    for r in poa:
        node = int(r["validators"]) * float(r["node_power_w"]) * float(r["hours_per_epoch"]) * float(r["chain_ci_g_per_kwh"]) / 1000
        assert float(r["node_term_g"]) == pytest.approx(node)
        assert float(r["overhead_g"]) == pytest.approx(float(r["gas_overhead_g"]) + node)
        assert float(r["net_saving_g"]) == pytest.approx(float(r["gross_saving_g"]) - float(r["overhead_g"]))
        assert r["overhead_terms"] == e12.TRUST_TERM + " + PoA node term"
    # Phase 4: trust-layer term on top of the market term, for every flow
    trust = {(r["workflows"], r["inst_seed"]): int(r["gas_total"]) for r in ok if r["overhead_terms"] == e12.TRUST_TERM}
    # Phase 3: every flow also has a row incl. the measured on-chain market gas, strictly larger than flow-only
    flow = {(r["workflows"], r["inst_seed"]): int(r["gas_total"]) for r in ok if r["overhead_terms"] == e12.FLOW_TERM}
    mkt = {(r["workflows"], r["inst_seed"]): int(r["gas_total"]) for r in ok if r["overhead_terms"] == e12.MARKET_TERM}
    assert flow and set(mkt) == set(flow) and all(mkt[k] > flow[k] for k in flow)
    assert set(trust) == set(flow) and all(trust[k] > mkt[k] for k in flow)
    be = read_csv(out / "breakeven.csv")
    assert {r["overhead_terms"] for r in be} == {e12.FLOW_TERM, e12.MARKET_TERM, e12.TRUST_TERM}
    tr = read_csv(out / "tradeoff.csv")
    by = {}
    for r in tr:
        by.setdefault((r["workflows"], r["inst_seed"]), []).append((int(r["market_rounds"]), int(r["onchain_round_overhead"])))
    for pts in by.values():                 # measured gas grows with the number of on-chain rounds
        pts.sort()
        assert all(g1 < g2 for (_, g1), (_, g2) in zip(pts, pts[1:]))


def test_e1_default_point_matches_demo_formula(smoke):
    """At the demo's own parameters (0.5 Wh/Mgas, 400 g/kWh) the overhead is the pipeline's step-6 formula."""
    assert e12.overhead_g(9_340_000, 0.5, 400) == pytest.approx(1.868)


def test_e2_gas_rows(smoke):
    out, _, _ = smoke
    rows = read_csv(out / "gas_scaling.csv")
    fns = {r["function"] for r in rows if r["status"] == "ok"}
    assert {"deploy", "publish", "commit", "openReveal", "reveal (accepted)", "finalize"} <= fns
    assert {"openMarket", "submitBatch", "closeRound", "market round (submitBatch + closeRound)"} <= fns   # Phase 3
    for r in rows:
        if r["function"] in ("openMarket", "submitBatch", "closeRound") and r["status"] == "ok":
            assert int(r["gas_max"]) > 0 and r["fits_reference_block"] == "True"
    assert {"requestSnapshot", "submitReports", "finalizeSnapshot", "claimBound", "finalizeBound",
            "challenge"} <= fns                                                                          # Phase 4
    nr = {r["function"]: r["status"] for r in rows if r["status"] != "ok"}
    assert nr == {}
    pub = sorted((int(r["tasks"]), int(r["gas_max"])) for r in rows if r["function"] == "publish")
    assert all(g1 < g2 for (_, g1), (_, g2) in zip(pub, pub[1:])), "publish gas must grow with n"


def test_e4_labels_budgets_and_real_data_rows(smoke):
    out, _, _ = smoke
    rows = read_csv(out / "solvers.csv")
    ok = [r for r in rows if r["status"] == "ok"]
    assert {r["label"] for r in ok if r["solver"] in ("greedy", "sa")} == {"classical"}
    assert {r["label"] for r in ok if r["solver"] == "sqa"} == {"quantum-inspired"}
    sa_mm = {int(r["moves"]) for r in ok if r["solver"] == "sa" and r["budget"] == "move-matched"}
    sqa = {int(r["moves"]) for r in ok if r["solver"] == "sqa"}
    assert sa_mm == sqa, "move-matched SA must use exactly the SQA move count"
    for r in ok:
        assert float(r["gap_pct"]) >= -1e-9, "no schedule may beat the certified lower bound"
    real = [r for r in rows if r["dataset"].startswith("real")]
    from core.instance import workload_path
    from experiments.eval_common import load_eval_config, load_real_config
    real_cfg = load_real_config(load_eval_config())
    have_data = all(workload_path(real_cfg, s).is_file()
                    for s in load_eval_config()["profiles"]["smoke"]["solvers"]["real_inst_seeds"])
    if have_data:        # Phase 1 data present: every real row ran, with the same honest labels and LB check
        assert real and all(r["status"] == "ok" for r in real)
        assert {r["label"] for r in real if r["solver"] == "sqa"} == {"quantum-inspired"}
        summary = read_csv(out / "solvers_summary.csv")
        from experiments.e4_solvers import REAL_DATASET, REAL_FLOOR_DATASET
        assert {r["dataset"] for r in summary} == {"synthetic", REAL_DATASET, REAL_FLOOR_DATASET}
        # D1: the main real rows scale tasks by instance_num; the 1 Wh floor is the sensitivity (option (c)) only
        t_main = {r["inst_seed"]: int(r["tasks"]) for r in real if r["dataset"] == REAL_DATASET}
        t_floor = {r["inst_seed"]: int(r["tasks"]) for r in real if r["dataset"] == REAL_FLOOR_DATASET}
        assert t_main and t_main == t_floor
    else:                # machine without data/: explicit NOT RUN rows, nothing silently skipped
        assert real and all(r["status"] == "NOT RUN - data missing" for r in real)
        assert any(r["status"] == "NOT RUN - data missing" for r in read_csv(out / "not_run.csv"))


def test_figures_render_from_smoke_csvs(smoke, tmp_path):
    """fig5-fig9 render headless (Agg) from the smoke CSVs; PNG + SVG per figure."""
    from experiments.figures import FIGURES, make_all
    out, _, _ = smoke
    done = make_all(out, tmp_path / "figs", log=lambda *_: None)
    assert set(done) == set(FIGURES)
    for name, files in done.items():
        if isinstance(files, str):     # input rows absent in this environment (no Besu / no data / no Phase 2 run)
            assert name in ("fig8r", "fig9r", "fig10", "fig11") and files.startswith("NOT RUN"), (name, files)
            continue
        for f in files:
            assert (tmp_path / "figs" / f).stat().st_size > 1000, f


def test_figures_report_missing_inputs(tmp_path):
    from experiments.figures import make_all
    done = make_all(tmp_path, tmp_path / "figs", log=lambda *_: None)
    assert all(v.startswith("NOT RUN") for v in done.values())


def _render_eval(eval_dir):
    from app.tabs import evaluation
    evaluation.render(eval_dir)


def test_evaluation_tab_renders_on_smoke_csvs(smoke):
    from streamlit.testing.v1 import AppTest
    out, _, _ = smoke
    at = AppTest.from_function(_render_eval, kwargs={"eval_dir": str(out)}, default_timeout=60).run()
    assert not at.exception
    assert [t.label for t in at.tabs] == ["E1 Net carbon", "E2 Gas", "E3 Attacks", "E4 Solvers", "NOT RUN"]
    # live sliders: move to a high-overhead corner and the net-saving range must follow the stored gas
    at.select_slider[0].set_value(10000)
    at.slider[0].set_value(700)
    at.run()
    assert not at.exception
    rows = [r for r in read_csv(out / "sensitivity.csv") if r["status"] == "ok"
            and float(r["energy_wh_per_million_gas"]) == 10000 and float(r["chain_ci_g_per_kwh"]) == 700]
    lo = min(float(r["net_saving_g"]) for r in rows)
    assert at.metric[0].value.startswith(f"{lo:,.1f}")


def test_evaluation_tab_without_results(tmp_path):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_function(_render_eval, kwargs={"eval_dir": str(tmp_path)}, default_timeout=60).run()
    assert not at.exception
    assert "not available" in at.info[0].value


def test_smoke_is_reproducible(smoke, tmp_path):
    out, manifest, _ = smoke
    again = run("smoke", out_dir=tmp_path, log=lambda *_: None)
    assert again["configs_sha256"] == manifest["configs_sha256"]
    assert again["contract_artifact_sha256"] == manifest["contract_artifact_sha256"]
    assert set(again["outputs"]) == set(manifest["outputs"])
    for f, h in manifest["outputs"].items():
        assert again["outputs"][f]["sha256_without_time_columns"] == h["sha256_without_time_columns"], f
