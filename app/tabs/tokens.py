"""Tokens tab (Phase 5): ERC-20 credits (QicasCredit) + soulbound ERC-721 certificate (ScheduleCertificate).

Shows the stored E6 rows (results/besu/, python -m experiments.besu_vs_memory) and, on request, runs the V3 token
flow on a fresh IN-MEMORY chain (demo/pipeline_v3.py, ~15 s): credit balances, a retirement (burn + Retired event)
and the decoded certificate tokenURI JSON. Credits = floor(NET saving in g); 1 QCC = 1 g CO2e. Never on Besu here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = ROOT / "results" / "besu"
RETIRE = 10


def run_token_flow() -> dict[str, Any]:
    """V3 flow on the in-memory chain, then the winner retires RETIRE credits. Returns plain data only."""
    from chain.client import Chain
    from demo.pipeline import load_config
    from demo.pipeline_v3 import run_v3
    from experiments.eval_common import seeded_salts
    cfg = load_config(ROOT / "config" / "demo.yaml")
    base = Chain.start("memory", min_stake=int(cfg["chain"]["stake_wei"]))
    out = run_v3(cfg, base, salt_fn=seeded_salts(7), market_rounds=0, log=lambda *_: None)
    tk = out["_stack"].tokens
    winner = out["winner_address"]
    minted = tk.balance(winner)
    ret = tk.retire(winner, min(RETIRE, minted), winner, "QICAS demo retirement") if minted else None
    names = ["deployer", "greedy", "sa", "sqa", "dual-market", "attacker: over-capacity", "attacker: copycat",
             "attacker: no-show"]
    balances = [{"account": n, "address": a, "QCC credits": tk.balance(a), "certificates": tk.cert_balance(a)}
                for n, a in zip(names, base.accounts)]
    return {"winner": out["winner"], "winner_address": winner, "minted": minted, "retired": ret,
            "total_supply": tk.total_supply(), "balances": balances, "token_uri_json": out["token_uri_json"],
            "certificate_owner": out["certificate_owner"], "locked": tk.locked(out["epoch_id"]),
            "parity": out["parity"], "net_saving_g": out["net_saving_ug"] / 1e6,
            "certified_gap_bps": out["certified_gap_bps"], "epoch_id": out["epoch_id"]}


def render(src: str | Path = DEFAULT_DIR) -> None:
    src = Path(src)
    st.caption("Phase 5 · **QicasCredit** (ERC-20, transferable, decimals 0, only the market's MINTER_ROLE mints; "
               "`retire` burns) and **ScheduleCertificate** (ERC-721, soulbound: transfers and approvals revert). "
               "After the admin renounces, the minter set is frozen; the market keeps its minter role.")
    if (src / "summary.csv").exists():
        st.subheader("E6 · token flow (V3) on Besu vs in-memory")
        st.dataframe(pd.read_csv(src / "summary.csv"), hide_index=True, width="stretch")
    else:
        st.info("E6 results not available — Phase 5: start Besu (`scripts/besu_up.ps1`) and run "
                "`python -m experiments.besu_vs_memory` (writes results/besu/).")

    st.subheader("Run the token flow (in-memory)")
    if st.button("Run V3 token flow (~15 s)", key="tokens_run"):
        with st.spinner("Deploying oracle, tokens and V3; 7 agents commit and reveal; finalize mints…"):
            st.session_state["token_flow"] = run_token_flow()
    tf = st.session_state.get("token_flow")
    if not tf:
        st.info("Press the button to deploy the Phase 5 contracts on a fresh in-memory chain.")
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Winner", tf["winner"])
    c2.metric("Credits minted (QCC)", tf["minted"], f"NET {tf['net_saving_g']:.1f} g", delta_color="off")
    c3.metric("Retired", tf["retired"]["amount"] if tf["retired"] else 0)
    c4.metric("Total supply after retirement", tf["total_supply"])
    st.dataframe(pd.DataFrame(tf["balances"]), hide_index=True, width="stretch")
    if tf["retired"]:
        st.caption(f"`Retired` event: holder {tf['retired']['holder']} → beneficiary {tf['retired']['beneficiary']}, "
                   f"{tf['retired']['amount']} QCC, reason “{tf['retired']['reason']}”, gas {tf['retired']['gas']:,}.")
    st.subheader(f"Certificate #{tf['epoch_id']} — decoded tokenURI")
    st.write(f"Owner {tf['certificate_owner']} · soulbound (`locked`) = **{tf['locked']}** · gap field "
             f"{tf['certified_gap_bps']} bps (10000 = no fraud-proof bound linked in this run)")
    st.json(tf["token_uri_json"])
    st.write("Python ↔ Solidity parity: " + ", ".join(f"{k} {'✓' if v else '✗'}" for k, v in tf["parity"].items()))
