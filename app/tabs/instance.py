"""Instance tab (case study, unchanged)."""
from __future__ import annotations

import pandas as pd
import streamlit as st


def render(out: dict) -> None:
    st.subheader("Regions (illustrative values — replace with Electricity Maps snapshot)")
    st.dataframe(pd.DataFrame(out["instance"]["regions"]), width="stretch")
    i = out["instance"]
    st.write(f"{i['tasks']} tasks · {i['workflows']} DAG workflows · {i['edges']} data edges · "
             f"{i['total_cpu']} CPU cores · instance hash `{i['instance_hash']}`")
