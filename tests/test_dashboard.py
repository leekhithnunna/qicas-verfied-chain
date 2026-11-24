"""Dashboard import + render smoke tests (Streamlit AppTest, headless, in-memory chain)."""
import importlib
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from demo.pipeline import load_config, run

APP = str(Path(__file__).resolve().parents[1] / "app" / "dashboard.py")
CASE_STUDY_TABS = ["Instance", "Solvers", "Dual-price market", "On-chain", "Merkle proof"]
PHASE_TABS = ["Evaluation", "On-chain market", "Oracle & challenges", "Tokens"]


@pytest.mark.parametrize("mod", ["instance", "solvers", "market", "onchain", "merkle", "evaluation",
                                 "onchain_market", "oracle", "tokens"])
def test_every_tab_module_imports(mod):
    m = importlib.import_module(f"app.tabs.{mod}")
    assert callable(m.render)


def test_prerun_screen_shows_info_and_evaluation_tab():
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert at.info[0].value == "Press **Run full demo** in the sidebar."
    labels = [t.label for t in at.tabs]           # includes the Evaluation tab's nested sub-tabs
    assert labels[0] == "Evaluation" and [x for x in labels if x in PHASE_TABS] == PHASE_TABS


def test_case_study_tabs_unchanged_after_run():
    cfg = load_config()
    cfg["workflows"] = 5
    out = run(cfg, log=lambda *_: None)
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["out"] = out
    at.run()
    assert not at.exception
    labels = [t.label for t in at.tabs]           # includes the Evaluation tab's nested sub-tabs
    assert labels[:6] == CASE_STUDY_TABS + ["Evaluation"]
    assert [x for x in labels if x in CASE_STUDY_TABS + PHASE_TABS] == CASE_STUDY_TABS + PHASE_TABS
    assert [m.label for m in at.metric][:5] == ["Carbon reduction vs contract baseline",
                                                "Net saving (after chain overhead)", "Certified optimality gap",
                                                "Winner", "Credits minted"]
    assert at.success and "= True" in at.success[0].value          # live verifyPlacement in the Merkle tab


def _render_phase_tab(mod, src):
    import importlib
    importlib.import_module(f"app.tabs.{mod}").render(src)


@pytest.mark.parametrize("mod", ["onchain_market", "oracle", "tokens"])
def test_phase_tabs_say_not_available_without_results(mod, tmp_path):
    at = AppTest.from_function(_render_phase_tab, kwargs={"mod": mod, "src": str(tmp_path)}, default_timeout=60).run()
    assert not at.exception
    assert any("not available" in i.value for i in at.info)


def _fixture_market(d):
    import json
    d.mkdir()
    (d / "summary.json").write_text(json.dumps({
        "rounds": 2, "regions": 2, "lower_bound_onchain_int": 90, "lower_bound_round": 1,
        "certified_gap_bps_onchain": 1000, "upper_bound_best_revealed": 100, "gas": {"market_total": 5},
        "overhead_model": {"energy_wh_per_million_gas": 0.5, "chain_ci_g_per_kwh": 400},
        "net_saving_g_incl_market": 1.0, "net_saving_g_case_study": 2.0}), encoding="utf-8")
    (d / "rounds.csv").write_text("round,lam,dual_value,best_lb_so_far,round_gas,cumulative_market_gas\n"
                                  "0,0 0,80,80,3,3\n1,5 0,90,90,2,5\n", encoding="utf-8")


def test_onchain_market_tab_renders_fixture(tmp_path):
    _fixture_market(tmp_path / "m")
    at = AppTest.from_function(_render_phase_tab, kwargs={"mod": "onchain_market", "src": str(tmp_path / "m")},
                               default_timeout=60).run()
    assert not at.exception
    assert [m.label for m in at.metric][:3] == ["Rounds", "Best lower bound (on chain)", "Certified gap (on chain)"]
