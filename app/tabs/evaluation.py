"""Evaluation tab (Phase 6-lite): reads results/eval/*.csv written by `python -m experiments.run_all`.

No chain and no solver runs here: E1 is recomputed live from the STORED gas and gross savings when the two
overhead sliders move. Missing inputs show "not available"; NOT RUN rows are listed, never hidden.
Colours follow the report figures (experiments/figures.py): categorical slots 1-3 only.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from experiments.eval_common import FLOW_TERM, MARKET_TERM, TRUST_TERM, primary_term

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = ROOT / "results" / "eval"
BLUE, ORANGE, AQUA, GRAY = "#2a78d6", "#eb6834", "#1baf7a", "#898781"
LABEL_COLORS = {"classical": BLUE, "quantum-inspired": ORANGE, "decomposition (classical)": AQUA}
# wide log grid for the live slider; includes every value of the [VERIFY] grid in config/eval.yaml
ENERGY_STEPS = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000]
VERIFY = ("**[VERIFY]** There are no sources for energy per gas or chain intensity: these are illustrative "
          "sensitivity parameters. Read every net-carbon number as a **range**, not a headline value.")


@st.cache_data(show_spinner=False)
def _csv(path: str, mtime: float) -> pd.DataFrame:      # mtime: cache key, refreshes after a new run
    return pd.read_csv(path)


def load(eval_dir: Path, name: str) -> pd.DataFrame | None:
    p = Path(eval_dir) / name
    return _csv(str(p), p.stat().st_mtime) if p.exists() else None


def recompute_e1(flows: pd.DataFrame, energy_wh_per_mgas: float, chain_ci: float) -> pd.DataFrame:
    """Per stored flow: overhead = gas / 1e6 x Wh/Mgas x g/kWh / 1000 g; net = gross - overhead."""
    d = flows.copy()
    d["overhead_g"] = d["gas_total"] / 1e6 * energy_wh_per_mgas * chain_ci / 1000.0
    d["net_saving_g"] = d["gross_saving_g"] - d["overhead_g"]
    d["overhead_pct_of_gross"] = 100 * d["overhead_g"] / d["gross_saving_g"]
    d["net_saving_per_task_g"] = d["net_saving_g"] / d["tasks"]
    return d


def break_even(d: pd.DataFrame) -> str:
    """Smallest measured size with net > 0 for every seed there and at every larger size."""
    sizes = sorted(d["workflows"].unique())
    be = None
    for wf in reversed(sizes):
        if (d.loc[d["workflows"] == wf, "net_saving_g"] > 0).all():
            be = wf
        else:
            break
    if be is None:
        return "none in measured range"
    tasks = d.loc[d["workflows"] == be, "tasks"].mean()
    return f"≤ {tasks:.0f} tasks (below measured range)" if be == sizes[0] else f"≈ {tasks:.0f} tasks"


def _not_available(what: str, how: str = "run `python -m experiments.run_all --profile lite`") -> None:
    st.info(f"{what}: not available — {how}.")


# ------------------------------------------------------------------------------- sections
def _e1(eval_dir: Path) -> None:
    sens = load(eval_dir, "sensitivity.csv")
    if sens is None:
        return _not_available("E1 sensitivity")
    st.markdown(VERIFY)
    ok = sens[sens["status"] == "ok"]
    term = primary_term(ok["overhead_terms"]) if "overhead_terms" in ok else FLOW_TERM
    if "overhead_terms" in ok:
        ok = ok[ok["overhead_terms"] == term]
    flows = ok.drop_duplicates(["workflows", "inst_seed"])[["workflows", "inst_seed", "tasks", "gas_total",
                                                             "gross_saving_g"]]
    c1, c2 = st.columns(2)
    e = c1.select_slider("Energy per million gas (Wh) [VERIFY]", options=ENERGY_STEPS, value=0.5,
                         help="Demo default 0.5. Log steps from 0.01 to 10,000.")
    ci = c2.slider("Chain carbon intensity (g CO₂e/kWh) [VERIFY]", 0, 1000, 400, step=10,
                   help="Demo default 400. Report grid: 40 / 400 / 700.")
    d = recompute_e1(flows, float(e), float(ci))
    m1, m2, m3 = st.columns(3)
    m1.metric("Net saving, range over instances", f"{d['net_saving_g'].min():,.1f} … {d['net_saving_g'].max():,.1f} g")
    m2.metric("Overhead as % of gross, range",
              f"{d['overhead_pct_of_gross'].min():.3g} … {d['overhead_pct_of_gross'].max():.3g} %")
    m3.metric("Break-even workload", break_even(d))
    chart = alt.Chart(d).mark_circle(size=70, color=BLUE).encode(
        x=alt.X("tasks:Q", title="Tasks in the instance"),
        y=alt.Y("net_saving_g:Q", title="Net saving (g CO₂e)"),
        tooltip=["workflows", "inst_seed", "tasks", alt.Tooltip("gross_saving_g", format=",.1f"),
                 alt.Tooltip("overhead_g", format=",.3f"), alt.Tooltip("net_saving_g", format=",.1f")])
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=GRAY, strokeDash=[4, 3]).encode(y="y:Q")
    st.altair_chart(chart + zero, width="stretch")
    if term == TRUST_TERM:
        st.caption("Overhead = case-study flow gas + measured Phase 3 on-chain market gas + Phase 4 trust layer "
                   "(oracle snapshot of 5 signers, bound claim + finalise). The Phase 5 PoA node term (validators × W/node × "
                   "hours/epoch, [VERIFY]) is in poa_node_term.csv; gas is not energy on a PoA network.")
    elif term == MARKET_TERM:
        st.caption("Overhead = case-study flow gas (deploy … finalize, 7 agents) + measured Phase 3 on-chain market "
                   "gas (openMarket + rounds of submitBatch + closeRound). Phase 4–5 overhead terms (oracle and "
                   "challenges, PoA node power) are NOT RUN.")
    else:
        st.caption("Overhead uses the case-study flow gas only (deploy … finalize, 7 agents). "
                   "Phase 3–5 overhead terms (market rounds, oracle and challenges, PoA node power) are NOT RUN.")
    tr = load(eval_dir, "tradeoff.csv")
    if tr is not None:
        with st.expander("Trade-off: market rounds vs certified gap"):
            g = tr.groupby("market_rounds")[["market_gap_pct", "certified_gap_pct"]].agg(["min", "median", "max"])
            st.dataframe(g.round(2), width="stretch")
            ov = pd.to_numeric(tr["onchain_round_overhead"], errors="coerce")
            if ov.notna().all():
                gk = ov.groupby(tr["market_rounds"]).agg(["min", "max"])
                st.caption("Measured on-chain gas of openMarket + k rounds (Phase 3): " + "; ".join(
                    f"k={k}: {r['min']:,.0f} … {r['max']:,.0f}" for k, r in gk.iterrows()) + ".")
            else:
                st.caption(f"On-chain overhead of the rounds: {tr['onchain_round_overhead'].iloc[0]}.")


def _e2(eval_dir: Path) -> None:
    gas, fit = load(eval_dir, "gas_scaling.csv"), load(eval_dir, "gas_fit.csv")
    if gas is None:
        return _not_available("E2 gas scaling")
    ok = gas[(gas["status"] == "ok") & gas["function"].isin(["publish", "reveal (accepted)", "finalize"])].copy()
    ok["gas_millions"] = ok["gas_max"] / 1e6
    pts = alt.Chart(ok).mark_circle(size=60).encode(
        x=alt.X("tasks:Q", title="Tasks in the instance (n)"),
        y=alt.Y("gas_millions:Q", title="Gas per transaction (millions)", scale=alt.Scale(domain=[0, 33])),
        color=alt.Color("function:N", scale=alt.Scale(domain=["publish", "reveal (accepted)", "finalize"],
                                                       range=[BLUE, ORANGE, AQUA]), title="Function"),
        tooltip=["function", "tasks", "edges", alt.Tooltip("gas_max", format=",")])
    lim = pd.DataFrame({"y": [30, 15], "label": ["30 M reference block limit [VERIFY]", "15 M demo client tx cap"]})
    rules = alt.Chart(lim).mark_rule(color=GRAY, strokeDash=[4, 3]).encode(y="y:Q", tooltip=["label"])
    text = alt.Chart(lim).mark_text(align="left", dx=4, dy=-6, color=GRAY).encode(x=alt.value(0), y="y:Q",
                                                                                   text="label")
    st.altair_chart(pts + rules + text, width="stretch")
    if fit is not None:
        st.dataframe(fit[fit["model"] == "a+b*n"][[
            "function", "a", "b", "r2", "max_measured_tasks", "largest_measured_tasks_under_reference",
            "largest_measured_tasks_under_demo_cap", "extrapolated_tasks_at_reference", "note"]],
            hide_index=True, width="stretch")
        st.caption("Only measured n are claims; `extrapolated_*` columns come from the linear fit.")
    nr = gas[gas["status"] != "ok"][["function", "status"]]
    if len(nr):
        st.caption("Not measured: " + "; ".join(f"{r.function} ({r.status})" for r in nr.itertuples()))


def _e3(eval_dir: Path) -> None:
    att = load(eval_dir, "attacks.csv")
    if att is None:
        return _not_available("E3 attack suite")
    c1, c2 = st.columns(2)
    layers = c1.multiselect("Layer", sorted(att["layer"].unique()), default=sorted(att["layer"].unique()))
    statuses = c2.multiselect("Status", sorted(att["status"].unique()), default=sorted(att["status"].unique()))
    view = att[att["layer"].isin(layers) & att["status"].isin(statuses)]
    st.dataframe(view.drop(columns=["test_name"]), hide_index=True, width="stretch")
    n = att["status"].value_counts()
    st.caption(" · ".join(f"{k}: {v}" for k, v in n.items()) + ". Assumption rows are kept on purpose so the "
               "table does not overclaim.")


def _e4(eval_dir: Path) -> None:
    summ, vs = load(eval_dir, "solvers_summary.csv"), load(eval_dir, "classical_vs_qi.csv")
    if summ is None:
        return _not_available("E4 solver comparison")
    datasets = list(dict.fromkeys(summ["dataset"])) if "dataset" in summ else ["synthetic"]
    dataset = st.selectbox("Dataset", datasets, key="eval_e4_dataset") if len(datasets) > 1 else datasets[0]
    if "dataset" in summ:
        summ = summ[summ["dataset"] == dataset]
        if vs is not None and "dataset" in vs:
            vs = vs[vs["dataset"] == dataset]
    presets = list(dict.fromkeys(summ["preset"]))
    preset = st.selectbox("Weight preset", presets, key="eval_e4_preset")
    s = summ[summ["preset"] == preset].copy()
    s["variant"] = s["solver"] + " · " + s["budget"].fillna("n/a").astype(str)   # pandas reads "n/a" as NaN
    base = alt.Chart(s).encode(x=alt.X("variant:N", sort=None, title=None, axis=alt.Axis(labelAngle=0,
                                                                                         labelLimit=140)))
    bars = base.mark_rule(strokeWidth=2).encode(
        y=alt.Y("gap_pct_ci_lo:Q", title="Certified gap to lower bound (%) — lower is better"),
        y2="gap_pct_ci_hi:Q", color=alt.Color("label:N", scale=alt.Scale(domain=list(LABEL_COLORS),
                                                                          range=list(LABEL_COLORS.values()))))
    dots = base.mark_circle(size=90).encode(
        y="gap_pct_mean:Q", color=alt.Color("label:N", title="Label"),
        tooltip=["solver", "label", "budget", "n_runs", alt.Tooltip("gap_pct_mean", format=".2f"),
                 alt.Tooltip("gap_pct_ci_lo", format=".2f"), alt.Tooltip("gap_pct_ci_hi", format=".2f"),
                 alt.Tooltip("moves_per_run_mean", format=",.0f")])
    st.altair_chart(bars + dots, width="stretch")
    st.caption("Mean ± 95 % bootstrap CI over solver seeds (instances fixed). SA move-matched = same number of "
               "moves as SQA (sweeps × replicas × n). Synthetic instances, plus Phase 1 real instances (Alibaba trace + 2024-10-15T12:00Z snapshot) when the local data files are present; otherwise those rows are NOT RUN - data missing.")
    if vs is not None:
        st.markdown("**Where classical matches or beats quantum-inspired (SQA)**")
        st.dataframe(vs[vs["preset"] == preset][[
            "classical", "classical_budget", "diff_gap_pct_mean", "diff_ci_lo", "diff_ci_hi", "classical_wins",
            "ties", "qi_wins", "verdict", "classical_matches_or_beats"]], hide_index=True, width="stretch")


def _manifest(eval_dir: Path) -> dict[str, Any] | None:
    p = Path(eval_dir) / "manifest.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def render(eval_dir: str | Path | None = None) -> None:
    eval_dir = Path(eval_dir) if eval_dir else DEFAULT_DIR
    man = _manifest(eval_dir)
    if man is None:
        _not_available("Evaluation results")
        return
    st.caption(f"Profile **{man['profile']}** · commit `{man['git']['commit'][:10]}` · runtime "
               f"{man['runtime_s']:.0f} s · synthetic data only · in-memory chain. Labels: greedy, SA = classical; "
               "SQA = quantum-inspired; dual-market = decomposition (classical). No quantum-advantage claim.")
    t1, t2, t3, t4, t5 = st.tabs(["E1 Net carbon", "E2 Gas", "E3 Attacks", "E4 Solvers", "NOT RUN"])
    with t1:
        _e1(eval_dir)
    with t2:
        _e2(eval_dir)
    with t3:
        _e3(eval_dir)
    with t4:
        _e4(eval_dir)
    with t5:
        nr = load(eval_dir, "not_run.csv")
        if nr is None:
            _not_available("NOT RUN list")
        else:
            st.dataframe(nr, hide_index=True, width="stretch")
            st.caption("Everything that needs Phases 1, 3, 4 or 5 is listed here; nothing is skipped silently.")
