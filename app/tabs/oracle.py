"""Oracle & challenges tab (Phase 4): reads results/trust/ (python -m experiments.trust_layer).

Carbon reports per zone (5 bonded EIP-712 signers, lower median of the reports), the claim -> challenge window ->
finalise timeline of the certified lower bound (fraud proofs), gas per step and the executed attack table.
No chain runs here. Missing inputs -> "not available".
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = ROOT / "results" / "trust"
ZONES = ["SE-SE3", "IE", "US-MIDA-PJM", "IN-WE"]

TIMELINE = [  # (step, gas.csv function, what happens)
    ("1 request", "requestSnapshot", "owner asks for one carbon value per zone for one hour"),
    ("2 report", "submitReports", "5 bonded signers send EIP-712 signed reports (one per zone)"),
    ("3 finalise snapshot", "finalizeSnapshot", "quorum 3 reached: value = lower median of the reports"),
    ("4 bind", "bindOracle", "the market epoch reads its region carbon intensities from the snapshot"),
    ("5 claim bound", "claimBound", "a claimer posts the best lower-bound round with a bond"),
    ("6 challenge window", "challenge", "1 h: anyone can submit a better workflow minimiser (fraud proof) and "
                                        "cancel a false claim; the bond goes to the challenger"),
    ("7 finalise bound", "finalizeBound", "after the window: the bound becomes the certificate's gap"),
]


def render(src: str | Path = DEFAULT_DIR) -> None:
    src = Path(src)
    if not (src / "summary.json").exists():
        st.info("Oracle & challenge results not available — Phase 4: run `python -m experiments.trust_layer` "
                "(writes results/trust/).")
        return
    s = json.loads((src / "summary.json").read_text(encoding="utf-8"))
    st.caption("Phase 4 · `CarbonOracle.sol` + fraud proofs in `PriceMarket.sol`. **Trust-minimised, not "
               "trustless:** " + s.get("honest_claims", ""))
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Signers / quorum", f"{s['signers']} / {s['quorum']}")
    c2.metric("Finalised lower bound", f"{s['finalized_lower_bound']:,}", f"round {s['finalized_round']}",
              delta_color="off")
    c3.metric("Fraud-proof gap", f"≤ {s['finalized_gap_bps'] / 100:.2f} %")
    c4.metric("Trust-layer gas per epoch", f"{s['gas']['trust_per_epoch']:,}")

    st.subheader("Reports per zone (honest case)")
    demo = yaml.safe_load((ROOT / "config" / "demo.yaml").read_text(encoding="utf-8"))
    rows = []
    for z, r in zip(ZONES, demo["regions"]):
        v = int(r["ci_g_per_kwh"])
        rows.append({"zone": z, "region": r["name"], "reports (g/kWh)": ", ".join([str(v)] * int(s["signers"])),
                     "median (on chain)": v, "spread": 0})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("In the honest run every signer reports the configured value, so the spread is 0. The attack table "
               "below shows a lying minority (2 of 5 report 0 and 2³²−1): the lower median stays the honest value.")

    st.subheader("Claim → challenge → finalise")
    gas = pd.read_csv(src / "gas.csv") if (src / "gas.csv").exists() else pd.DataFrame()
    tl = []
    for step, fn, what in TIMELINE:
        g = gas[gas["function"] == fn] if not gas.empty else gas
        mean = g["gas_mean"].dropna().mean() if not g.empty else None
        tl.append({"step": step, "function": fn, "what happens": what,
                   "gas (mean)": f"{mean:,.0f}" if mean is not None and mean == mean else "—"})
    st.dataframe(pd.DataFrame(tl), hide_index=True, width="stretch")

    if (src / "attacks.csv").exists():
        st.subheader("Attacks executed (E3, Phase 4 rows)")
        st.dataframe(pd.read_csv(src / "attacks.csv"), hide_index=True, width="stretch")
    if not gas.empty:
        with st.expander("Gas per function"):
            st.dataframe(gas, hide_index=True, width="stretch")
