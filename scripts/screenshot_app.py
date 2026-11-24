"""Report screenshots only (scripts/make_report_pack.py --screenshots): renders ONE dashboard view per URL,
    ?view=overview | evaluation | market | oracle | tokens
using the same tab modules as app/dashboard.py (headless browsers cannot click tabs). In-memory chain only."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from app.tabs import evaluation, onchain_market, oracle, solvers, tokens  # noqa: E402

st.set_page_config(page_title="QICAS dashboard", layout="wide")
view = st.query_params.get("view", "overview")
st.title("QICAS — quantum-inspired, verifiable, carbon-aware scheduling")


@st.cache_resource(show_spinner=False)
def demo_out():
    from demo.pipeline import load_config, run
    return run(load_config(), log=lambda *_: None)


if view == "overview":
    out = demo_out()
    f = out["final"]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Carbon reduction vs contract baseline", f"{f['reduction_pct']:.1f}%")
    c2.metric("Net saving (after chain overhead)", f"{f['net_saving_g']:.1f} g")
    c3.metric("Certified optimality gap", f"≤ {f['certified_gap_pct']:.2f}%")
    c4.metric("Winner", f["winner"])
    c5.metric("Credits minted", f["credits_minted"])
    st.subheader("Solvers (seed-7 demo)")
    solvers.render(out)
elif view == "evaluation":
    st.subheader("Evaluation")
    evaluation.render()
elif view == "market":
    st.subheader("On-chain market (Phase 3)")
    onchain_market.render()
elif view == "oracle":
    st.subheader("Oracle & challenges (Phase 4)")
    oracle.render()
elif view == "tokens":
    st.subheader("Tokens (Phase 5)")
    if "token_flow" not in st.session_state:
        st.session_state["token_flow"] = st.cache_resource(show_spinner=False)(tokens.run_token_flow)()
    tokens.render()
