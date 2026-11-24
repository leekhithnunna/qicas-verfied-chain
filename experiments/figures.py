"""Phase 6 report figures fig5-fig11 from results/eval/*.csv -> results/eval/figures/ (PNG 200 dpi + SVG).
fig1-4 (demo/make_figures.py) are unchanged.

    python -m experiments.figures [--in results/eval] [--out results/eval/figures]

fig5  E1 net saving as % of gross over the [VERIFY] overhead grid (median colour, min..max range in each cell)
fig6  E1 overhead as % of gross saving vs energy per Mgas, one line per chain intensity, band = min..max
fig7  E2 gas per function vs tasks, with the 30 M reference block limit and the demo client's 15 M tx cap
fig8  E4 certified gap to the lower bound per solver/budget, mean +- 95 % bootstrap CI, one panel per preset
fig9  E4 paired difference (classical - SQA) in gap, mean +- 95 % CI, with win counts
fig8r/fig9r  the same on the Phase 1 real instances (D1: tasks x instance_num), when present
fig10 E5 Phase 2 sub-problems: P(optimum) vs evaluation budget per method (QAOA classically simulated)
fig11 E6 gas + confirmation latency per function, in-memory vs Besu QBFT (needs Besu rows)
A figure whose input rows are missing returns "NOT RUN - ..." instead of a file list.

Colours: reference palette of the dataviz skill (categorical slots 1-3 only; diverging blue<->red with a gray
midpoint). Every coloured mark also has a text label, so identity is never colour-only.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

from experiments.eval_common import MARKET_TERM, ROOT, TRUST_TERM, primary_term, read_csv  # noqa: E402

SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"            # categorical slots 1-3 (fixed order)
RED, NEUTRAL = "#e34948", "#f0efec"                               # diverging pole + gray midpoint
CRITICAL = "#d03b3b"
LABEL_COLOR = {"classical": BLUE, "quantum-inspired": ORANGE, "decomposition (classical)": AQUA}
VERIFY = "[VERIFY] illustrative overhead grid, no sources"


def _style() -> None:
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "axes.titlecolor": INK, "text.color": INK,
        "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
        "axes.spines.top": False, "axes.spines.right": False, "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "DejaVu Sans", "Arial"], "font.size": 9, "axes.titlesize": 10,
        "legend.frameon": False, "lines.linewidth": 2})


def _save(fig, out: Path, name: str, tight: bool = True) -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    if tight:
        fig.tight_layout()
    fig.savefig(out / f"{name}.png", dpi=200)
    fig.savefig(out / f"{name}.svg")
    plt.close(fig)
    return [f"{name}.png", f"{name}.svg"]


def _ok(rows):
    return [r for r in rows if r.get("status") == "ok"]


def _sens(src: Path) -> tuple[list[dict], str]:
    """E1 rows of ONE overhead definition: the most complete one present (incl. Phase 3 market rounds)."""
    rows = _ok(read_csv(src / "sensitivity.csv"))
    term = primary_term(r.get("overhead_terms") for r in rows)
    note = {TRUST_TERM: "case-study flow + Phase 3 market rounds + Phase 4 oracle/bound gas (measured); "
                        "Phase 5 PoA node term separate (poa_node_term.csv)",
            MARKET_TERM: "case-study flow + Phase 3 on-chain market rounds (measured gas); Phase 4–5 terms not included",
            }.get(term, "case-study flow gas incl. deploy; Phase 3–5 terms not included")
    return [r for r in rows if r.get("overhead_terms", term) == term], note


# ------------------------------------------------------------------------------- E1
def fig5(src: Path, out: Path) -> list[str]:
    rows, term_note = _sens(src)
    es = sorted({float(r["energy_wh_per_million_gas"]) for r in rows})
    cis = sorted({float(r["chain_ci_g_per_kwh"]) for r in rows})
    cell = defaultdict(list)
    for r in rows:
        g = float(r["gross_saving_g"])
        if g > 0:
            cell[(float(r["energy_wh_per_million_gas"]), float(r["chain_ci_g_per_kwh"]))].append(
                100 * float(r["net_saving_g"]) / g)
    med = np.array([[np.median(cell[(e, c)]) for c in cis] for e in es])
    cmap = LinearSegmentedColormap.from_list("div", [RED, NEUTRAL, BLUE])
    fig, ax = plt.subplots(figsize=(5.6, 4.6))
    ax.grid(False)
    im = ax.imshow(np.clip(med, -100, 100), cmap=cmap, vmin=-100, vmax=100, aspect="auto", origin="lower")
    for i, e in enumerate(es):
        for j, c in enumerate(cis):
            v = cell[(e, c)]
            lo, hi = min(v), max(v)
            txt = f"{lo:.0f}%" if abs(hi - lo) < 0.5 else f"{lo:.0f} … {hi:.0f}%"
            ax.text(j, i, txt, ha="center", va="center", fontsize=7.5, color=INK)
    ax.set_xticks(range(len(cis)), [f"{c:g}" for c in cis])
    ax.set_yticks(range(len(es)), [f"{e:g}" for e in es])
    ax.set_xlabel("Chain carbon intensity (g CO₂e/kWh)")
    ax.set_ylabel("Energy per million gas (Wh)")
    ax.set_title("E1 · Net saving as % of gross saving (range over all instances)", loc="left")
    cb = fig.colorbar(im, ax=ax, shrink=0.85)
    cb.set_label("median net / gross (%), clipped at ±100", color=INK2)
    cb.outline.set_visible(False)
    fig.text(0.01, 0.005, VERIFY + "; " + term_note,
             fontsize=6.5, color=MUTED)
    return _save(fig, out, "fig5_net_saving_heatmap")


def fig6(src: Path, out: Path) -> list[str]:
    rows, _ = _sens(src)
    rows = [r for r in rows if r["overhead_pct_of_gross"] != ""]
    es = sorted({float(r["energy_wh_per_million_gas"]) for r in rows})
    cis = sorted({float(r["chain_ci_g_per_kwh"]) for r in rows})
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    nudge = {0: -6, 1: -4, 2: 6}
    for k, (color, c) in enumerate(zip((BLUE, ORANGE, AQUA), cis)):
        vals = [[float(r["overhead_pct_of_gross"]) for r in rows
                 if float(r["energy_wh_per_million_gas"]) == e and float(r["chain_ci_g_per_kwh"]) == c] for e in es]
        lo, md, hi = [min(v) for v in vals], [float(np.median(v)) for v in vals], [max(v) for v in vals]
        ax.fill_between(es, lo, hi, color=color, alpha=0.15, linewidth=0)
        ax.plot(es, md, color=color, marker="o", markersize=4, label=f"{c:g} g/kWh")
        ax.annotate(f"{c:g} g/kWh", (es[-1], md[-1]), xytext=(5, nudge.get(k, 0)), textcoords="offset points",
                    color=INK2, fontsize=7.5, va="center")
    ax.axhline(100, color=CRITICAL, linewidth=1, linestyle="--")
    ax.text(es[0], 130, "break-even: overhead = gross saving", color=INK2, fontsize=7.5)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Energy per million gas (Wh)  [VERIFY]")
    ax.set_ylabel("Chain overhead as % of gross saving")
    ax.set_title("E1 · Overhead share vs assumed energy per gas (line = median, band = min–max)", loc="left")
    ax.legend(title="Chain intensity", loc="upper left", bbox_to_anchor=(0, 0.92), fontsize=7.5, title_fontsize=7.5)
    ax.set_xlim(es[0] / 1.5, es[-1] * 6)
    return _save(fig, out, "fig6_overhead_share")


# ------------------------------------------------------------------------------- E2
def fig7(src: Path, out: Path, ref: float = 30e6, cap: float = 15e6) -> list[str]:
    rows = _ok(read_csv(src / "gas_scaling.csv"))
    fits = {(f["function"], f["model"]): f for f in read_csv(src / "gas_fit.csv") if f["model"] == "a+b*n"}
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    nmax = max(int(r["tasks"]) for r in rows)
    offs = {"publish": (-8, 8), "reveal (accepted)": (-60, 10), "finalize": (6, -3)}
    for color, fn in zip((BLUE, ORANGE, AQUA), ("publish", "reveal (accepted)", "finalize")):
        pts = [(int(r["tasks"]), float(r["gas_max"]) / 1e6) for r in rows if r["function"] == fn]
        if not pts:
            continue
        x, y = zip(*pts)
        ax.scatter(x, y, s=22, color=color, edgecolor=SURFACE, linewidth=1, zorder=3, label=fn)
        f = fits.get((fn, "a+b*n"))
        if f:
            xs = np.array([0, nmax * 1.05])
            ax.plot(xs, (float(f["a"]) + float(f["b"]) * xs) / 1e6, color=color, linewidth=1.2, alpha=0.8)
        ax.annotate(fn + (" (max per tx)" if fn.startswith("reveal") else ""), (x[-1], y[-1]), xytext=offs[fn],
                    textcoords="offset points", fontsize=7.5, color=INK2)
    for lim, lab in ((ref, "30 M reference block limit [VERIFY]"), (cap, "15 M per-tx cap of the demo client")):
        ax.axhline(lim / 1e6, color=MUTED, linewidth=1, linestyle="--")
        ax.text(2, lim / 1e6 + 0.4, lab, fontsize=7.5, color=INK2)
    ax.set_xlim(0, nmax * 1.15)
    ax.set_ylim(0, ref / 1e6 * 1.12)
    ax.set_xlabel("Tasks in the instance (n)")
    ax.set_ylabel("Gas per transaction (millions)")
    ax.set_title("E2 · Gas vs instance size (measured; lines = linear fit)", loc="left")
    ax.legend(loc="center left", bbox_to_anchor=(0, 0.62), fontsize=7.5)
    return _save(fig, out, "fig7_gas_scaling")


# ------------------------------------------------------------------------------- E4
VARIANT_ORDER = [("greedy", "n/a"), ("sa", "default"), ("sa", "move-matched"), ("sqa", "default"),
                 ("dual-market", "default (25 rounds)")]
SHORT = {("greedy", "n/a"): "greedy", ("sa", "default"): "SA\ndefault", ("sa", "move-matched"): "SA\nmove-matched",
         ("sqa", "default"): "SQA", ("dual-market", "default (25 rounds)"): "dual-\nmarket"}


def fig8(src: Path, out: Path, dataset: str = "synthetic", name: str = "fig8_solver_gap",
         title: str = "synthetic instances") -> list[str] | str:
    rows = [r for r in _ok(read_csv(src / "solvers_summary.csv")) if r.get("dataset", "synthetic") == dataset]
    if not rows:
        return f"NOT RUN - no '{dataset}' rows in solvers_summary.csv"
    presets = list(dict.fromkeys(r["preset"] for r in rows))
    fig, axes = plt.subplots(1, len(presets), figsize=(max(7.5, 3.4 * len(presets) + 0.6), 4.4), sharey=True,
                             squeeze=False)
    for ax, p in zip(axes[0], presets):
        by = {(r["solver"], r["budget"]): r for r in rows if r["preset"] == p}
        for i, v in enumerate(VARIANT_ORDER):
            r = by.get(v)
            if not r:
                continue
            m, lo, hi = float(r["gap_pct_mean"]), float(r["gap_pct_ci_lo"]), float(r["gap_pct_ci_hi"])
            c = LABEL_COLOR[r["label"]]
            ax.errorbar(i, m, yerr=[[m - lo], [hi - m]], fmt="o", color=c, markersize=6, capsize=3,
                        elinewidth=1.5, markeredgecolor=SURFACE)
            ax.annotate(f"{m:.1f}", (i, hi), xytext=(0, 5), textcoords="offset points", ha="center",
                        va="bottom", fontsize=7, color=INK2)
        ax.set_xticks(range(len(VARIANT_ORDER)), [SHORT[v] for v in VARIANT_ORDER], fontsize=7)
        ax.set_title(p, loc="left")
    top = max(float(r["gap_pct_ci_hi"]) for r in rows)
    axes[0][0].set_ylim(0, top * 1.12)           # after all panels: shared y must cover every preset
    axes[0][0].set_ylabel("Certified gap to lower bound (%)  — lower is better")
    handles = [plt.Line2D([], [], marker="o", linestyle="", color=c, label=k) for k, c in LABEL_COLOR.items()]
    fig.suptitle(f"E4 · Solver comparison, {title} (mean ± 95 % bootstrap CI over solver seeds)",
                 x=0.01, ha="left", fontsize=10, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.86))
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.005, 0.93), ncol=3, fontsize=7.5)
    return _save(fig, out, name, tight=False)


def fig9(src: Path, out: Path, dataset: str = "synthetic", name: str = "fig9_classical_vs_sqa",
         title: str = "") -> list[str] | str:
    rows = [r for r in _ok(read_csv(src / "classical_vs_qi.csv")) if r.get("dataset", "synthetic") == dataset]
    if not rows:
        return f"NOT RUN - no '{dataset}' rows in classical_vs_qi.csv"
    presets = list(dict.fromkeys(r["preset"] for r in rows))
    fig, axes = plt.subplots(1, len(presets), figsize=(max(7.5, 3.6 * len(presets) + 1.2), 3.9), sharey=True,
                             squeeze=False)
    for ax, p in zip(axes[0], presets):
        rs = [r for r in rows if r["preset"] == p]
        for i, r in enumerate(rs):
            m, lo, hi = float(r["diff_gap_pct_mean"]), float(r["diff_ci_lo"]), float(r["diff_ci_hi"])
            c = LABEL_COLOR[r["classical_label"]]
            ax.errorbar(m, i, xerr=[[m - lo], [hi - m]], fmt="o", color=c, markersize=6, capsize=3,
                        elinewidth=1.5, markeredgecolor=SURFACE)
            ax.annotate(f"wins {r['classical_wins']}/{r['ties']}/{r['qi_wins']}", (hi, i), xytext=(5, 0),
                        textcoords="offset points", va="center", fontsize=7, color=INK2)
        ax.axvline(0, color=AXIS, linewidth=1.2)
        ax.set_yticks(range(len(rs)), [SHORT[(r["classical"], r["classical_budget"])].replace("-\n", "-").replace("\n", " ")
                                       + " − SQA" for r in rs], fontsize=7.5)
        ax.set_title(p, loc="left")
        ax.margins(x=0.35)
        ax.grid(axis="y", visible=False)
    axes[0][0].invert_yaxis()
    for ax in axes[0]:
        ax.set_xlabel("Δ gap (pp); < 0 = classical better")
    fig.suptitle(f"E4 · Paired gap difference vs SQA (quantum-inspired){title}, mean ± 95 % CI\n"
                 "wins = runs where classical / tie / SQA had the lower score", x=0.01, ha="left", fontsize=9.5,
                 color=INK)
    handles = [plt.Line2D([], [], marker="o", linestyle="", color=LABEL_COLOR[k], label=k)
               for k in ("classical", "decomposition (classical)")]
    fig.tight_layout(rect=(0, 0, 1, 0.84))
    fig.legend(handles=handles, loc="upper right", bbox_to_anchor=(0.995, 0.89), ncol=2, fontsize=7.5)
    return _save(fig, out, name, tight=False)


REAL = "real (Alibaba trace, config/real_snapshot.yaml)"            # = experiments.e4_solvers.REAL_DATASET


def fig8r(src: Path, out: Path) -> list[str] | str:
    return fig8(src, out, REAL, "fig8r_solver_gap_real",
                "real Alibaba DAGs × 2024-10-15T12Z snapshot (D1: tasks × instance_num)")


def fig9r(src: Path, out: Path) -> list[str] | str:
    return fig9(src, out, REAL, "fig9r_classical_vs_sqa_real", " — real instances (D1)")


QAOA = "#7d55c7"           # 4th categorical slot: quantum algorithm, classically simulated
E5_STYLE = {  # method -> (legend name, colour, linestyle)
    "sa": ("SA (classical)", BLUE, "-"), "sqa": ("SQA (quantum-inspired)", ORANGE, "-"),
    "sb_ballistic": ("SB ballistic (quantum-inspired)", ORANGE, "--"),
    "sb_discrete": ("SB discrete (quantum-inspired)", ORANGE, ":"),
    "qaoa_ring": ("QAOA ring (quantum, simulated)", QAOA, "-"),
    "qaoa_complete": ("QAOA complete (quantum, simulated)", QAOA, "--"),
    "random": ("random (sanity baseline)", MUTED, ":"),
}


def fig10(src: Path, out: Path) -> list[str] | str:
    """E5: P(optimum) per sub-problem vs evaluation budget (Phase 2 results, not re-run)."""
    rows = _ok(read_csv(src / "quantum_summary.csv"))
    if not rows:
        return "NOT RUN - Phase 2 results missing in quantum_summary.csv"
    fig, ax = plt.subplots(figsize=(8.6, 4.8))
    budgets = sorted({int(r["budget"]) for r in rows})
    ends = []
    for method, (name, c, ls) in E5_STYLE.items():
        rs = sorted((r for r in rows if r["method"] == method), key=lambda r: int(r["budget"]))
        if not rs:
            continue
        x = [int(r["budget"]) for r in rs]
        y = [float(r["p_opt"]) for r in rs]
        lo = [float(r["p_opt_ci_lo"]) for r in rs]
        hi = [float(r["p_opt_ci_hi"]) for r in rs]
        ax.plot(x, y, color=c, linestyle=ls, marker="o", markersize=4, linewidth=1.8)
        ax.fill_between(x, lo, hi, color=c, alpha=0.12, linewidth=0)
        ends.append([y[-1], f"{name}  {y[-1]:.2f}", c, x[-1]])
    ends.sort()                                        # spread end labels so they never overlap
    for i in range(1, len(ends)):
        ends[i][0] = max(ends[i][0], ends[i - 1][0] + 0.055)
    for y, text, c, x in ends:
        ax.annotate(text, (x, y), xytext=(8, 0), textcoords="offset points", va="center", fontsize=7,
                    color=c if c != MUTED else INK2, annotation_clip=False)
    ideal = [r for r in rows if r["method"].endswith("_ideal") and int(r["budget"]) == budgets[0]]
    if ideal:
        top = max(float(r["p_opt"]) for r in ideal)
        ax.axhline(top, color=AXIS, linewidth=1, linestyle="--")
        ax.annotate("QAOA with ideal angles: optimistic upper bound, not a runnable method", (budgets[0], top),
                    xytext=(0, 4), textcoords="offset points", fontsize=7, color=MUTED)
    ax.set_xscale("log", base=2)
    ax.set_xticks(budgets, [str(b) for b in budgets])
    ax.set_xlim(budgets[0] * 0.85, budgets[-1] * 1.15)
    ax.set_ylim(0, 1.12)
    ax.set_xlabel("Evaluation budget per sub-problem (energy evaluations / shots)")
    ax.set_ylabel("P(optimum found)  — higher is better")
    n = rows[0].get("n_subproblems", "")
    ax.set_title(f"E5 · Phase 2 workflow sub-problems ({n} sub-problems; mean, band = 95 % CI)\n"
                 "QAOA = quantum algorithm, classically simulated; no quantum-advantage claim", loc="left",
                 fontsize=9)
    fig.tight_layout(rect=(0, 0, 0.78, 1))
    return _save(fig, out, "fig10_quantum_subproblems", tight=False)


def fig11(src: Path, out: Path) -> list[str] | str:
    """E6: gas (identical by construction) and confirmation latency per function, in-memory vs Besu QBFT."""
    rows = [r for r in _ok(read_csv(src / "besu_vs_memory.csv")) if r.get("flow", "v1") == "v1"]
    if "besu" not in {r["chain"] for r in rows}:
        return "NOT RUN - no Besu rows in besu_vs_memory.csv (needs QICAS_BESU=1 + network up)"
    funcs = [f for f in dict.fromkeys(r["function"] for r in rows)
             if all(any(r["function"] == f and r["chain"] == c for r in rows) for c in ("memory", "besu"))]
    by = {(r["function"], r["chain"]): r for r in rows}
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 4.4))
    w, col = 0.38, {"memory": BLUE, "besu": ORANGE}
    names = {"memory": "in-memory (eth-tester, automine)", "besu": "Besu QBFT (4 validators, 2 s blocks)"}
    for k, c in enumerate(("memory", "besu")):
        xs = [i + (k - 0.5) * w for i in range(len(funcs))]
        a1.bar(xs, [float(by[(f, c)]["gas_mean"]) / 1e3 for f in funcs], width=w, color=col[c], label=names[c])
        t = [float(by[(f, c)]["confirm_mean_s"]) if by[(f, c)]["confirm_mean_s"] not in ("", None) else np.nan
             for f in funcs]
        a2.bar(xs, t, width=w, color=col[c])
    for ax in (a1, a2):
        ax.set_xticks(range(len(funcs)), funcs, rotation=30, ha="right", fontsize=7.5)
        ax.grid(axis="x", visible=False)
    a1.set_yscale("log")
    a1.set_ylabel("Gas per call (thousands, log scale)")
    a1.set_title("Gas per call", loc="left")
    a2.set_ylabel("Mean confirmation time (s)")
    a2.set_title("Confirmation latency", loc="left")
    for i, f in enumerate(funcs):
        if by[(f, "besu")]["confirm_mean_s"] in ("", None):
            a2.annotate("not timed\n(deploy path)", (i, 0), xytext=(0, 4), textcoords="offset points",
                        ha="center", fontsize=7, color=MUTED)
    fig.suptitle("E6 · Besu QBFT vs in-memory chain, V1 demo flow (seed 7)", x=0.01, ha="left", fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.88))
    h, lab = a1.get_legend_handles_labels()
    fig.legend(h, lab, loc="upper left", bbox_to_anchor=(0.005, 0.95), ncol=2, fontsize=8)
    return _save(fig, out, "fig11_besu_vs_memory", tight=False)


FIGURES = {"fig5": fig5, "fig6": fig6, "fig7": fig7, "fig8": fig8, "fig9": fig9, "fig8r": fig8r, "fig9r": fig9r,
           "fig10": fig10, "fig11": fig11}
NEEDS = {"fig5": "sensitivity.csv", "fig6": "sensitivity.csv", "fig7": "gas_scaling.csv",
         "fig8": "solvers_summary.csv", "fig9": "classical_vs_qi.csv", "fig8r": "solvers_summary.csv",
         "fig9r": "classical_vs_qi.csv", "fig10": "quantum_summary.csv", "fig11": "besu_vs_memory.csv"}


def make_all(src: str | Path = ROOT / "results" / "eval", out: str | Path | None = None,
             log=print) -> dict[str, list[str] | str]:
    src = Path(src)
    out = Path(out) if out else src / "figures"
    _style()
    done: dict[str, list[str] | str] = {}
    for name, fn in FIGURES.items():
        if not (src / NEEDS[name]).exists():
            done[name] = f"NOT RUN - {NEEDS[name]} missing (run experiments.run_all first)"
            log(f"[{name}] {done[name]}")
            continue
        done[name] = fn(src, out)
        log(f"[{name}] " + (done[name] if isinstance(done[name], str) else f"-> {out / done[name][0]}"))
    plt.rcdefaults()
    return done


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="src", default=str(ROOT / "results" / "eval"))
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    make_all(a.src, a.out)


if __name__ == "__main__":
    main()
