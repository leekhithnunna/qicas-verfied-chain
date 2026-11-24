"""Dual-price market tab (case study, unchanged)."""
from __future__ import annotations

import pandas as pd
import streamlit as st


def render(out: dict) -> None:
    mk = out["market"]
    st.write("Upper bound (feasible repaired schedule) and lower bound (Lagrangian dual) per round. "
             "The gap between them is a **certified** distance from optimal.")
    st.line_chart(pd.DataFrame({"upper bound": mk["upper"], "lower bound": mk["lower"]}), height=280)
    names = [r["name"] for r in out["instance"]["regions"]]
    st.write("Region prices λ (per CPU core) — over-demanded regions become expensive:")
    st.line_chart(pd.DataFrame(mk["prices"], columns=names), height=240)
