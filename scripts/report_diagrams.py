r"""Architecture / flow diagrams for the report (PNG, white background, 200 dpi) — matplotlib only.

    .\.venv\Scripts\python.exe scripts\report_diagrams.py [--out report_pack\diagrams]

d1_system_architecture   d2_commit_reveal_scoring   d3_price_market_rounds   d4_oracle_fraud_proofs
d5_besu_qbft_tokens      d6_data_pipeline           d7_evaluation_harness
Every box names the real module / contract that implements it.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
INK, MUTED = "#1d1d1b", "#5b5a56"
FILL = {"core": "#e8f1fb", "chain": "#fdeee6", "data": "#e6f6ef", "ui": "#f1ecfa", "ext": "#f3f3f1",
        "attack": "#fbe6e6"}
EDGE = {"core": "#2a78d6", "chain": "#eb6834", "data": "#1baf7a", "ui": "#7d55c7", "ext": "#898781",
        "attack": "#d03b3b"}


def _fig(w=13, h=7.2, title=""):
    fig, ax = plt.subplots(figsize=(w, h))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    if title:
        ax.text(0.5, 98.5, title, fontsize=15, fontweight="bold", color=INK, va="top")
    return fig, ax


def box(ax, x, y, w, h, title, body="", kind="core", fs=9.5):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.4,rounding_size=1.2", linewidth=1.6,
                                edgecolor=EDGE[kind], facecolor=FILL[kind]))
    ax.text(x + w / 2, y + h - 2.2, title, ha="center", va="top", fontsize=fs + 1, fontweight="bold", color=INK)
    if body:
        ax.text(x + w / 2, y + h - 6.3, body, ha="center", va="top", fontsize=fs - 0.5, color=MUTED,
                linespacing=1.35)
    return (x, y, w, h)


def arrow(ax, p, q, label="", color=INK, style="-|>", ls="-", fs=8.5, off=(0, 1.4), rad=0.0):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle=style, mutation_scale=14, linewidth=1.4, color=color,
                                 linestyle=ls, connectionstyle=f"arc3,rad={rad}"))
    if label:
        ax.text((p[0] + q[0]) / 2 + off[0], (p[1] + q[1]) / 2 + off[1], label, ha="center", va="bottom",
                fontsize=fs, color=color, bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.9))


def legend(ax, items, y=3):
    x = 2
    for kind, text in items:
        ax.add_patch(FancyBboxPatch((x, y), 2.2, 2.2, boxstyle="round,pad=0.1", fc=FILL[kind], ec=EDGE[kind]))
        ax.text(x + 3, y + 1.1, text, va="center", fontsize=8.5, color=MUTED)
        x += 3.5 + len(text) * 0.62


def _save(fig, out: Path, name: str) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"{name}.png"
    fig.savefig(p, dpi=200, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return p


# ------------------------------------------------------------------------------------------------ diagrams
def d1(out):
    fig, ax = _fig(14, 8, "QICAS-Chain — system architecture")
    box(ax, 2, 70, 20, 22, "Inputs", "config/demo.yaml (synthetic)\nconfig/real_snapshot.yaml\n(Alibaba DAGs +\n"
        "Electricity Maps carbon +\nday-ahead prices)", "data")
    box(ax, 27, 64, 30, 28, "Off-chain solvers  (core/)", "instance.py · scoring.py (evaluate)\n"
        "greedy, SA  — classical\nSQA, SB  — quantum-inspired\nQAOA  — quantum, classically simulated\n"
        "market.py  — Lagrangian dual market\nmerkle.py · market_int.py · oracle_math.py", "core")
    box(ax, 63, 58, 35, 34, "Smart contracts  (chain/contracts/)", "CarbonScheduleMarket (V1, default demo)\n"
        "  commit-reveal · re-score · slash · Merkle root\nV2 (oracle-fed) · V3 (mints tokens)\n"
        "PriceMarket — on-chain dual rounds + fraud proofs\nCarbonOracle — EIP-712 signed carbon reports\n"
        "QicasCredit (ERC-20) · ScheduleCertificate\n(soulbound ERC-721) — OpenZeppelin 5.4.0", "chain")
    box(ax, 63, 22, 35, 26, "Chains", "in-memory: eth-tester + py-evm (default, tests)\nrpc: Hardhat node (optional)\n"
        "Besu QBFT: 4 validators, 2 s blocks,\nchainId 1338 (Docker, opt-in)\nclients: chain/client*.py, tokens.py",
        "chain")
    box(ax, 27, 22, 30, 30, "Demo + evaluation", "demo/pipeline.py — 7-step scenario\n"
        "demo/pipeline_v3.py — token flow\nexperiments/run_all.py — E1–E6\nexperiments/figures.py — fig5–fig11\n"
        "oracle/signer.py — TEST signers", "core")
    box(ax, 2, 22, 20, 36, "Dashboard  (app/)", "Streamlit, one module per tab:\nInstance · Solvers\n"
        "Dual-price market · On-chain\nMerkle proof · Evaluation\nOn-chain market · Oracle &\nchallenges · Tokens",
        "ui")
    arrow(ax, (22, 81), (27, 81), "instance")
    arrow(ax, (57, 80), (63, 80), "commit / reveal\nschedules")
    arrow(ax, (80.5, 58), (80.5, 48), "transactions")
    arrow(ax, (42, 64), (42, 52), "")
    arrow(ax, (57, 37), (63, 37), "web3")
    arrow(ax, (27, 37), (22, 37), "results/")
    ax.text(50, 12, "Integers only across Python ↔ Solidity · core/scoring.evaluate ≡ contract evaluate (parity tests) · "
            "core/ = stdlib + numpy", ha="center", fontsize=9.5, color=MUTED)
    legend(ax, [("data", "data / config"), ("core", "Python (off-chain)"), ("chain", "Solidity / chains"),
                ("ui", "dashboard")])
    return _save(fig, out, "d1_system_architecture")


def d2(out):
    fig, ax = _fig(14, 7.6, "Commit–reveal competition and on-chain scoring (CarbonScheduleMarket)")
    xs = [2, 21, 40, 59, 78]
    steps = [("1 publish", "owner publishes the instance\n(regions, tasks, edges)\ncontract stores it +\n"
                           "computes round-robin baseline"),
             ("2 commit", "each solver sends\nkeccak(epoch, x, salt, addr)\n+ 1 ETH stake\n(schedule hidden)"),
             ("3 reveal", "solver reveals (x, salt);\ncontract re-checks hash,\ncapacity, re-scores with\n"
                          "evaluate() = Python"),
             ("4 finalize", "best feasible score wins;\nnon-revealers slashed;\nMerkle root of winner stored"),
             ("5 credits", "credits = ⌊gross saving −\nchain overhead⌋ grams\n(V3: ERC-20 + soulbound\ncertificate)")]
    for x, (t, b) in zip(xs, steps):
        box(ax, x, 50, 18, 34, t, b, "chain")
    for i in range(4):
        arrow(ax, (xs[i] + 18, 67), (xs[i + 1], 67))
    box(ax, 2, 14, 30, 24, "Off-chain (core/)", "greedy · SA (classical)\nSQA (quantum-inspired)\n"
        "dual market (decomposition)\nscore = w_c·carbon + w_$·cost", "core")
    arrow(ax, (25, 38), (30, 50), "commit hashes", rad=-0.1)
    box(ax, 38, 14, 28, 24, "Attackers (executed)", "over-capacity → rejected\ncopycat → HashMismatch\n"
        "no-show → slashed\nmalformed / wrong phase → revert", "attack")
    arrow(ax, (52, 38), (49, 50), "", color=EDGE["attack"])
    box(ax, 72, 14, 26, 24, "Verification", "verifyPlacement(task, region,\nMerkle proof) → true / false\n"
        "certified gap ≤ (UB − LB)/UB", "chain")
    arrow(ax, (87, 50), (85, 38), "")
    ax.text(50, 6, "Seed-7 demo: 4 honest reveals accepted, 3 attackers stopped; carbon 961.8 → 531.8 g (44.7 %), "
            "428 credits, gap ≤ 9.92 %", ha="center", fontsize=9.5, color=MUTED)
    return _save(fig, out, "d2_commit_reveal_scoring")


def d3(out):
    fig, ax = _fig(14, 7.2, "On-chain dual-price market rounds (PriceMarket.sol ≡ core/market_int.py)")
    box(ax, 2, 55, 22, 30, "openMarket", "instance + step sizes\nλ_d = 0 for every region d", "chain")
    box(ax, 30, 55, 26, 30, "submitBatch (each round)", "for each workflow w:\nsubmitter sends its minimiser\n"
        "of V_w(λ) = score_w + Σ λ_d·load_d\n(≤ 7 tasks → exact)", "core")
    box(ax, 62, 55, 36, 30, "closeRound", "dual value g = Σ_w min V_w − Σ_d λ_d·cap_d\nbest LB = max(LB, g)\n"
        "λ_d ← max(0, λ_d + step·(load_d − cap_d))\ncertifiedGapBps = (UB − LB)/UB", "chain")
    arrow(ax, (24, 70), (30, 70), "")
    arrow(ax, (56, 70), (62, 70), "")
    arrow(ax, (80, 55), (43, 55), "next round, new λ", rad=0.35, off=(0, -9))
    box(ax, 2, 10, 44, 24, "Honest claim", "LB is certified assuming each workflow's minimum was\n"
        "submitted by ≥ 1 honest party; Phase 4 fraud proofs\nremove this assumption for the claimed round", "ext")
    box(ax, 54, 10, 44, 24, "Seed-7 result (25 rounds)", "on-chain integer LB 638,827,725 (round 20)\n"
        "gap ≤ 9.92 % (992 bps) · market gas 27.0 M\nevery round: λ, loads, g, LB == Python (parity)", "core")
    return _save(fig, out, "d3_price_market_rounds")


def d4(out):
    fig, ax = _fig(14, 7.6, "Trust layer: carbon oracle + fraud-proof bound (Phase 4)")
    box(ax, 2, 58, 20, 28, "5 bonded signers", "oracle/signer.py\nEIP-712 CarbonReport\n(zone, hour, g/kWh)\n"
        "TEST keys only", "ext")
    box(ax, 27, 58, 22, 28, "CarbonOracle", "requestSnapshot\nsubmitReports\nfinalizeSnapshot:\nquorum 3 → lower median\n"
        "equivocation → slash", "chain")
    box(ax, 54, 58, 20, 28, "V2 / V3 market", "publish reads region\ncarbon from the\nfinalised snapshot", "chain")
    box(ax, 79, 58, 19, 28, "PriceMarket", "rounds as in Phase 3\nclaimBound(round)\n+ claimer bond", "chain")
    arrow(ax, (22, 72), (27, 72), "signed\nreports")
    arrow(ax, (49, 72), (54, 72), "medians")
    arrow(ax, (74, 72), (79, 72), "epoch")
    box(ax, 20, 14, 26, 28, "Challenge window (1 h)", "anyone submits a workflow\nminimiser better than the\n"
        "claimed one → fraud proof\ncancels the claim, bond to\nchallenger", "attack")
    box(ax, 54, 14, 26, 28, "finalizeBound", "after the window:\nfinalizedGapBps → certificate\n(V3) gap field",
        "chain")
    arrow(ax, (88, 58), (40, 42), "claimed bound", rad=-0.15)
    arrow(ax, (46, 28), (54, 28), "no valid challenge")
    ax.text(50, 5, "Assumptions (documented, not defended): honest signer majority · ≥ 1 live watcher per window · "
            "data source itself correct", ha="center", fontsize=9.5, color=EDGE["attack"])
    return _save(fig, out, "d4_oracle_fraud_proofs")


def d5(out):
    fig, ax = _fig(14, 7.6, "Besu QBFT consortium network + token minting (Phase 5)")
    cx = [(4, 62), (24, 62), (4, 34), (24, 34)]
    for i, (x, y) in enumerate(cx, 1):
        box(ax, x, y, 17, 20, f"validator{i}", f"Besu 26.10.2\nRPC 127.0.0.1:{8544 + i}", "ext", fs=9)
    ax.text(23, 90, "QBFT: 4 validators, 2 s blocks, chainId 1338\n(tolerates 1 faulty validator)", ha="center",
            fontsize=9.5, color=MUTED)
    for a, b in [((21, 72), (24, 72)), ((12.5, 62), (12.5, 54)), ((32.5, 62), (32.5, 54)), ((21, 44), (24, 44))]:
        arrow(ax, a, b, style="<|-|>")
    box(ax, 50, 62, 22, 24, "CarbonScheduleMarketV3", "V2 flow (oracle-fed)\nfinalize(epoch, overhead,\npriceMarket, id)",
        "chain")
    box(ax, 77, 70, 21, 18, "QicasCredit (ERC-20)", "mint ⌊net g⌋ QCC\nretire = burn + event", "chain")
    box(ax, 77, 44, 21, 20, "ScheduleCertificate", "soulbound ERC-721\ntokenURI = on-chain JSON\n(root, gap, carbon)",
        "chain")
    arrow(ax, (72, 78), (77, 78), "MINTER_ROLE")
    arrow(ax, (72, 68), (77, 56), "mint #epoch")
    arrow(ax, (41, 58), (50, 70), "txs (web3)", off=(-2, 1))
    box(ax, 50, 12, 48, 22, "Admin renounced (A4)", "minter set frozen: no new minters can be granted;\n"
        "the market contract keeps its minter role.\nE3: unauthorised mint, double certificate, mint after renounce "
        "→ revert", "attack")
    box(ax, 4, 10, 37, 18, "Run", "scripts/besu_up.ps1 · run_demo --mode besu\nexperiments.besu_vs_memory (E6) · "
        "besu_down.ps1", "core", fs=9)
    return _save(fig, out, "d5_besu_qbft_tokens")


def d6(out):
    fig, ax = _fig(14, 7.6, "Data pipeline: raw sources → snapshot inputs (Phase 1)")
    srcs = [("A  Alibaba trace v2018", "batch_task.csv (14 M rows)\nresearch use; no redistribution"),
            ("B1–B4  Electricity Maps", "carbon intensity 2024 hourly\nACADEMIC licence, cite, no redistribution"),
            ("C1–C4  day-ahead prices", "ENTSO-E SE3, IE(SEM) · EM API PJM\nIEX India DAM"),
            ("D  ECB FX 2024-10-15", "USD 1.0903 / EUR · INR 91.622 / EUR")]
    for i, (t, b) in enumerate(srcs):
        box(ax, 2, 72 - i * 19, 28, 15, t, b, "data", fs=8.5)
    ax.text(16, 90, "data/raw/  (git-ignored, SHA-256 pinned)", ha="center", fontsize=9.5, color=MUTED)
    box(ax, 37, 60, 26, 26, "scripts/load_alibaba_dags.py", "filter: 3–7 tasks, DAG names,\nTerminated, ≤ 4 cores\n"
        "906,932 eligible jobs\nseeded sample: 8 jobs/instance\n→ data/processed/ (local)", "core", fs=8.5)
    box(ax, 37, 18, 26, 30, "core/data/ + build_real_snapshot", "carbon: direct, hour 2024-10-15\n12:00Z, rounded g/kWh\n"
        "price → EUR/MWh → µUSD/kWh\n(integers, contract units)\nchecks config == raw", "core", fs=8.5)
    arrow(ax, (30, 79), (37, 73))
    for i in range(1, 4):
        arrow(ax, (30, 79 - i * 19), (37, 33))
    box(ax, 70, 52, 28, 34, "Instance (core/instance.py)", "workload.task_size: instance_num (D1)\n"
        "cores = cpu × instance_num\nenergy = round(cpu·s·12 W·k/3600) Wh, ≥ 1\ncapacity = ⌈total·share⌉ + largest\n"
        "edges: estimated volumes", "core", fs=8.5)
    box(ax, 70, 14, 28, 30, "config/real_snapshot.yaml", "COMMITTED: 8 derived integers\n(1 ci + 1 price per region)\n"
        "+ citations + raw SHA-256s\nStockholm 1 · Ireland 179\nVirginia 320 · Mumbai 642 g/kWh", "data", fs=8.5)
    arrow(ax, (63, 73), (70, 70), "DAGs")
    arrow(ax, (63, 33), (70, 30), "8 values")
    arrow(ax, (84, 44), (84, 52), "regions")
    return _save(fig, out, "d6_data_pipeline")


def d7(out):
    fig, ax = _fig(14, 7.4, "Evaluation harness (experiments/run_all.py → results/eval/ + manifest.json)")
    box(ax, 2, 62, 22, 26, "config/eval.yaml", "profiles: smoke · lite\n[VERIFY] overhead grid\nPoA node term\n"
        "weight presets · bootstrap", "data")
    exps = [("E1", "net carbon vs\noverhead (ranges)"), ("E2", "gas vs size\n+ block limits"),
            ("E3", "attack suite\n(executed)"), ("E4", "solvers: synthetic\n+ real (+ D1 row)"),
            ("E5", "Phase 2 quantum\ntables (copied)"), ("E6", "Besu vs in-memory\n(opt-in)")]
    for i, (t, b) in enumerate(exps):
        x = 30 + (i % 3) * 23
        y = 64 if i < 3 else 36
        box(ax, x, y, 20, 22, t, b, "core" if t != "E6" else "chain", fs=9)
    arrow(ax, (24, 75), (30, 75))
    box(ax, 2, 22, 22, 30, "Outputs", "CSV per experiment\nnot_run.csv (explicit)\nmanifest.json: git, config\n"
        "+ data SHA-256s, seeds,\npackages, output hashes", "data")
    arrow(ax, (30, 47), (24, 40), "")
    box(ax, 30, 6, 32, 22, "experiments/figures.py", "fig5–fig9, fig8r/9r (real),\nfig10 (E5), fig11 (E6)\n"
        "PNG 200 dpi + SVG", "core")
    box(ax, 68, 6, 30, 22, "Consumers", "docs/FINAL_REPORT.md\ndashboard Evaluation tab\nreport_pack/", "ui")
    arrow(ax, (62, 17), (68, 17))
    arrow(ax, (13, 22), (30, 17), "", rad=0.2)
    return _save(fig, out, "d7_evaluation_harness")


DIAGRAMS = [d1, d2, d3, d4, d5, d6, d7]


def make_all(out: Path) -> list[Path]:
    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["DejaVu Sans", "Arial"]})  # has ⌊⌋⌈⌉
    return [d(out) for d in DIAGRAMS]


def main(argv=None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "report_pack" / "diagrams"))
    for p in make_all(Path(ap.parse_args(argv).out)):
        print(p)


if __name__ == "__main__":
    main()
