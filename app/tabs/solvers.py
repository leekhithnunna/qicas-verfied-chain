"""Solvers tab (case study, unchanged)."""
from __future__ import annotations

import pandas as pd
import streamlit as st


def render(out: dict) -> None:
    df = pd.DataFrame(out["offchain"]).T
    st.dataframe(df, width="stretch")
    st.bar_chart(df[["carbon_g"]].astype(float), height=280)
    if "sqa_trace" in out:
        st.caption("SQA best score per sweep (quantum-inspired annealing progress)")
        st.line_chart(pd.DataFrame({"SQA best score": out["sqa_trace"]}), height=220)
