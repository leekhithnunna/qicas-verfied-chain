"""On-chain market tab (Phase 3): reads results/onchain_market/ (python -m experiments.onchain_market).

Prices λ per region, the dual value and the best certified lower bound per round, and gas per round of
PriceMarket.sol (integer mirror: core/market_int.py). No chain runs here. Missing inputs -> "not available".
"""
from __future__ import annotations

import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = ROOT / "results" / "onchain_market"
BLUE, ORANGE, AQUA, GRAY = "#2a78d6", "#eb6834", "#1baf7a", "#898781"
REGION_COLORS = [BLUE, ORANGE, AQUA, "#7d55c7"]


def _lam_long(rounds: pd.DataFrame, regions: list[str]) -> pd.DataFrame:
    rows = []
    for _, r in rounds.iterrows():
        for d, v in enumerate(str(r["lam"]).split()):
            rows.append({"round": int(r["round"]), "region": regions[d] if d < len(regions) else f"region {d}",
                         "lambda": int(v)})
    return pd.DataFrame(rows)


def render(src: str | Path = DEFAULT_DIR) -> None:
    src = Path(src)
    if not (src / "rounds.csv").exists() or not (src / "summary.json").exists():
        st.info("On-chain market results not available — Phase 3: run "
                "`python -m experiments.onchain_market` (writes results/onchain_market/).")
        return
    s = json.loads((src / "summary.json").read_text(encoding="utf-8"))
    rounds = pd.read_csv(src / "rounds.csv")
    st.caption("Phase 3 · `PriceMarket.sol`: per-region prices λ are updated on chain each round from the submitted "
               "per-workflow minimisers; the dual value is a lower bound on the optimum. Lower bound certified "
               "**assuming each workflow's minimum was submitted by at least one honest party** (Phase 4 adds fraud "
               "proofs). Classical Lagrangian decomposition — not quantum.")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rounds", s["rounds"])
    c2.metric("Best lower bound (on chain)", f"{s['lower_bound_onchain_int']:,}", f"round {s['lower_bound_round']}",
              delta_color="off")
    c3.metric("Certified gap (on chain)", f"≤ {s['certified_gap_bps_onchain'] / 100:.2f} %")
    c4.metric("Market gas (all rounds)", f"{s['gas']['market_total']:,}")

    regions = [f"region {d}" for d in range(int(s.get("regions", 4)))]
    lam = _lam_long(rounds, regions)
    st.subheader("Prices λ per round")
    st.altair_chart(alt.Chart(lam).mark_line(point=True).encode(
        x=alt.X("round:Q", title="Round"), y=alt.Y("lambda:Q", title="λ (integer price units)"),
        color=alt.Color("region:N", scale=alt.Scale(domain=regions, range=REGION_COLORS[:len(regions)]),
                        legend=alt.Legend(orient="top", title=None)),
        tooltip=["round", "region", "lambda"]).properties(height=260), width="stretch")

    st.subheader("Lower bound per round")
    lb = rounds.melt(id_vars="round", value_vars=["dual_value", "best_lb_so_far"], var_name="series",
                     value_name="value")
    lb["series"] = lb["series"].map({"dual_value": "dual value this round", "best_lb_so_far": "best certified LB"})
    ub = pd.DataFrame({"value": [s["upper_bound_best_revealed"]], "label": ["best revealed schedule (upper bound)"]})
    base = alt.Chart(lb).mark_line(point=True).encode(
        x=alt.X("round:Q", title="Round"), y=alt.Y("value:Q", title="Score units"),
        color=alt.Color("series:N", scale=alt.Scale(domain=["dual value this round", "best certified LB"],
                                                    range=[GRAY, BLUE]), legend=alt.Legend(orient="top", title=None)),
        tooltip=["round", "series", alt.Tooltip("value:Q", format=",")])
    rule = alt.Chart(ub).mark_rule(color=ORANGE, strokeDash=[4, 3]).encode(y="value:Q", tooltip=["label", "value"])
    st.altair_chart((base + rule).properties(height=260), width="stretch")

    st.subheader("Gas per round")
    st.altair_chart(alt.Chart(rounds).mark_bar(color=BLUE).encode(
        x=alt.X("round:O", title="Round"), y=alt.Y("round_gas:Q", title="Gas (submitBatch + closeRound)"),
        tooltip=["round", alt.Tooltip("round_gas:Q", format=","), alt.Tooltip("cumulative_market_gas:Q", format=",")]
    ).properties(height=220), width="stretch")
    if (src / "gas.csv").exists():
        st.dataframe(pd.read_csv(src / "gas.csv"), hide_index=True, width="stretch")
    st.caption(f"Net saving incl. market overhead at the demo's sensitivity parameters "
               f"({s['overhead_model']['energy_wh_per_million_gas']} Wh/Mgas, "
               f"{s['overhead_model']['chain_ci_g_per_kwh']:.0f} g/kWh — [VERIFY], not measured): "
               f"{s['net_saving_g_incl_market']:.1f} g (case-study flow only: {s['net_saving_g_case_study']:.1f} g).")
