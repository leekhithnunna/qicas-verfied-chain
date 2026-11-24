"""Streamlit dashboard for the live demo.   Run:  streamlit run app/dashboard.py
STATUS: IMPLEMENTED
Tabs live in app/tabs/ (one module each): the five case-study tabs, unchanged, plus the Phase 6 tabs
Evaluation (results/eval/), On-chain market (Phase 3, results/onchain_market/), Oracle & challenges (Phase 4,
results/trust/) and Tokens (Phase 5, results/besu/ + an in-memory V3 token flow)."""
from __future__ import annotations

import copy
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # allow `streamlit run app/dashboard.py`

import pandas as pd
import streamlit as st

from app.tabs import evaluation, instance, market, onchain, onchain_market, oracle, solvers, tokens  # noqa: E402
from app.tabs import merkle as merkle_tab  # noqa: E402
from demo.pipeline import load_config, run, save  # noqa: E402

st.set_page_config(page_title="QICAS case-study demo", layout="wide")
st.title("QICAS — quantum-inspired, verifiable, carbon-aware scheduling")
st.caption("Case-study demo: DAG workflows placed across 4 cloud regions; solvers compete; a smart contract "
           "verifies every schedule and certifies net carbon savings.")

with st.expander("About / Papers"):
    st.markdown(textwrap.dedent("""
                - **Carbon-aware scheduling:** Radovanović et al., *Carbon-Aware Computing for Datacenters* (2023).
                    The demo models carbon-weighted placement in `core/scoring.py`, with region data in `config/demo.yaml`
                    "and an on-chain baseline in `CarbonScheduleMarket.sol`.
                - **Blockchain-verified scheduling:** *Blockchain-assisted smart grid scheduling using energy-efficient
                    swarm and deep learning models* (2026). The commit-reveal competition, on-chain re-scoring, slashing,
                    "and Merkle proofs are implemented in `chain/contracts/CarbonScheduleMarket.sol` and `chain/client.py`.
                - **Quantum-inspired scheduling:** Hammouda et al., *A quantum-driven multi-objective scheduler for
                    scalable task orchestration in fog-based cyber-physical-social systems* (2026). This demo implements
                    simulated quantum annealing in `core/solvers/sqa.py`; it is a classical simulation, compared with
                    "classical greedy and simulated annealing in `demo/pipeline.py`.
                """))

PHASE_TABS = ["Evaluation", "On-chain market", "Oracle & challenges", "Tokens"]
cfg = load_config(Path(__file__).resolve().parents[1] / "config" / "demo.yaml")
with st.sidebar:
    st.header("Settings")
    cfg["seed"] = st.number_input("Seed", 0, 10_000, int(cfg["seed"]))
    cfg["workflows"] = st.slider("Workflows", 3, 14, int(cfg["workflows"]))
    preset = st.radio("Objective weights", ["Carbon priority (1:1)", "Balanced (1:5)", "Cost priority (1:20)"])
    cfg["weights"] = {"Carbon priority (1:1)": {"carbon": 1, "cost": 1},
                      "Balanced (1:5)": {"carbon": 1, "cost": 5},
                      "Cost priority (1:20)": {"carbon": 1, "cost": 20}}[preset]
    cfg["chain"]["mode"] = st.selectbox("Chain", ["memory", "rpc"], help="rpc = a running Hardhat node")
    if cfg["chain"]["mode"] == "rpc":
        cfg["chain"]["rpc_url"] = st.text_input("RPC URL", cfg["chain"]["rpc_url"])
    go = st.button("▶ Run full demo", type="primary", width="stretch")
    compare_weights = st.button("Compare weights", width="stretch")

if go:
    logs: list[str] = []
    with st.status("Running pipeline…", expanded=True) as status:
        def log(msg: str) -> None:
            logs.append(msg)
            st.write(msg)
        try:
            st.session_state["out"] = run(cfg, log=log)
            save(st.session_state["out"])
            status.update(label="Demo finished", state="complete")
        except Exception as exc:  # show the error instead of a blank page
            status.update(label=f"Failed: {exc}", state="error")
            raise

if compare_weights:
    presets = [
        ("Carbon priority (1:1)", {"carbon": 1, "cost": 1}),
        ("Balanced (1:5)", {"carbon": 1, "cost": 5}),
        ("Cost priority (1:20)", {"carbon": 1, "cost": 20}),
    ]
    rows = []
    with st.spinner("Running three fresh in-memory demos…"):
        for label, weights in presets:
            compare_cfg = copy.deepcopy(cfg)
            compare_cfg["chain"]["mode"] = "memory"
            compare_cfg["weights"] = weights
            result = run(compare_cfg, log=lambda _: None)
            winner = result["final"]["winner"]
            winner_result = result["offchain"][winner]
            rows.append({
                "preset": label,
                "winner": winner,
                "carbon_g": result["final"]["best_carbon_g"],
                "cost_usd": winner_result["cost_usd"],
            })
    st.session_state["weight_comparison"] = rows

comparison = st.session_state.get("weight_comparison")
if comparison:
    st.subheader("Weight comparison")
    st.dataframe(pd.DataFrame(comparison), hide_index=True, width="stretch")

out = st.session_state.get("out")
if not out:
    st.info("Press **Run full demo** in the sidebar.")
    t_eval, t_mkt, t_orc, t_tok = st.tabs(PHASE_TABS)   # Phase 3-6 results are viewable without a demo run
    with t_eval:
        evaluation.render()
    with t_mkt:
        onchain_market.render()
    with t_orc:
        oracle.render()
    with t_tok:
        tokens.render()
    st.stop()

f = out["final"]
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Carbon reduction vs contract baseline", f"{f['reduction_pct']:.1f}%")
c2.metric("Net saving (after chain overhead)", f"{f['net_saving_g']:.1f} g")
c3.metric("Certified optimality gap", f"≤ {f['certified_gap_pct']:.2f}%")
c4.metric("Winner", f["winner"])
c5.metric("Credits minted", f["credits_minted"])

tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9 = st.tabs(["Instance", "Solvers", "Dual-price market",
                                                                "On-chain", "Merkle proof", *PHASE_TABS])

with tab1:
    instance.render(out)

with tab2:
    solvers.render(out)

with tab3:
    market.render(out)

with tab4:
    onchain.render(out)

with tab5:
    merkle_tab.render(out)

with tab6:
    evaluation.render()

with tab7:
    onchain_market.render()

with tab8:
    oracle.render()

with tab9:
    tokens.render()
