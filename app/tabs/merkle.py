"""Merkle proof tab (case study, unchanged): calls verifyPlacement on-chain live."""
from __future__ import annotations

import streamlit as st

from core import merkle


def render(out: dict) -> None:
    f = out["final"]
    chain, inst, best = out["_chain"], out["_instance"], out["_best"]
    j = st.number_input("Task index", 0, inst.n - 1, 0)
    claimed = st.selectbox("Claimed region", list(range(inst.m)),
                           format_func=lambda d: inst.regions[d].name, index=best[j])
    ok = chain.verify_placement(f["epoch_id"], int(j), int(claimed), merkle.proof(best, int(j)))
    (st.success if ok else st.error)(
        f"On-chain verifyPlacement(task {j} → {inst.regions[claimed].name}) = {ok}")
