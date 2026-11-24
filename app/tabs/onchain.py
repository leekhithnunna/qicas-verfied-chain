"""On-chain tab (case study, unchanged)."""
from __future__ import annotations

import pandas as pd
import streamlit as st


def render(out: dict) -> None:
    f = out["final"]
    st.dataframe(pd.DataFrame(out["reveals"]).drop(columns=["address"], errors="ignore"), width="stretch")
    st.write("Transactions and gas:")
    st.dataframe(pd.DataFrame(out["transactions"]), width="stretch")
    st.write(f"Total gas: {f['total_gas']:,} · Slashed from attackers: {f['slashed_eth']:g} ETH · "
             f"Merkle root `{f['merkle_root']}`")
