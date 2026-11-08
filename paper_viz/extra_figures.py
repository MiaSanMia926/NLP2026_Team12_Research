"""
Extended figure gallery for Track C.

Six additional, genuinely different chart geometries that complement the five
core figures, all sharing the same ACL page geometry and Okabe-Ito encoding:

  fig6_heatmap     Method x condition selective-risk matrix with color bar
  fig7_grouped_bar Grouped vertical bars across metadata states, with CI
  fig8_boxplot     Distribution of per-question selection scores
  fig9_stacked     Mutually exclusive outcome composition (100% columns)
  fig10_bubble     Coverage x risk scatter, bubble area = output-token cost
  fig11_radar      Multi-metric polar profile (all axes "larger is better")

Everything reuses acl_style and the reviewed bootstrap helpers in
paper_figures; no uncertainty is invented and no existing file is modified.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _p in (str(_HERE), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import PercentFormatter  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

from evaluation.metrics import load_jsonl, summarize  # noqa: E402
from evaluation.bootstrap import get_path  # noqa: E402
from acl_style import (SINGLE_COL, DOUBLE_COL, apply_style, method_style,  # noqa: E402
                       condition_style, panel_label, footnote, light_grid,
                       save_figure, METADATA_LABELS, GRID)
from paper_figures import slice_rows, cluster_bootstrap_ci  # noqa: E402

CONDITIONS = ["no_replica", "same_source_replica",
              "independent_support", "complementary_support"]
STATES = ["complete", "missing", "incorrect"]


# --------------------------------------------------------------------------- #
# Figure 6: method x condition selective-risk heatmap
# --------------------------------------------------------------------------- #
def fig6_heatmap(rows, out_dir):
    methods = list(dict.fromkeys(r["method"] for r in rows))
    matrix = np.full((len(methods), len(CONDITIONS)), np.nan)
    for i, method in enumerate(methods):
        for j, cond in enumerate(CONDITIONS):
            sub = slice_rows(rows, method=method, replica_condition=cond)
            est, _, _ = cluster_bootstrap_ci(sub, "selective_risk")
            matrix[i, j] = est if est is not None else np.nan

    fig, ax = plt.subplots(figsize=(SINGLE_COL, 2.6))
    fig.subplots_adjust(left=.27, right=.90, bottom=.22, top=.90)
    cmap = LinearSegmentedColormap.from_list(
        "risk_cmap", ["#F1F5F8", "#8FB3CC", "#0072B2"])
    im = ax.imshow(matrix, cmap=cmap, vmin=0, vmax=1, aspect="auto")

    ax.set_xticks(range(len(CONDITIONS)))
    ax.set_xticklabels([condition_style(c)[3] for c in CONDITIONS],
                       rotation=22, ha="right", fontsize=6.6)
    ax.set_yticks(range(len(methods)))
    ax.set_yticklabels([method_style(m)[0] for m in methods])
    ax.tick_params(length=0)

    for i in range(len(methods)):
        for j in range(len(CONDITIONS)):
            value = matrix[i, j]
            if np.isfinite(value):
                ax.text(j, i, f"{value:.2f}", ha="center", va="center",
                        fontsize=6.3, color="white" if value > .55 else "#1A1A1A")

    cbar = fig.colorbar(im, ax=ax, fraction=.05, pad=.04)
    cbar.set_label("Selective risk", fontsize=7)
    cbar.ax.tick_params(labelsize=6.5, length=2)

    panel_label(ax, "a")
    footnote(fig, "Point estimates; shared 0-1 risk scale.", y=.01)
    return save_figure(fig, Path(out_dir) / "fig6_heatmap")


# --------------------------------------------------------------------------- #
# Figure 7: grouped vertical bars across metadata states, with CI
# --------------------------------------------------------------------------- #
def fig7_grouped_bar(rows, out_dir):
    methods = list(dict.fromkeys(r["method"] for r in rows))
    fig, ax = plt.subplots(figsize=(DOUBLE_COL, 2.95))
    fig.subplots_adjust(left=.10, right=.985, bottom=.25, top=.84)

    width = .8 / len(methods)
    x = np.arange(len(STATES))
    for k, method in enumerate(methods):
        label, color, _ = method_style(method)
        vals, lower, upper = [], [], []
        for state in STATES:
            sub = slice_rows(rows, method=method, metadata_state=state)
            est, lo, hi = cluster_bootstrap_ci(sub, "selective_risk")
            vals.append(est if est is not None else np.nan)
            lower.append((est - lo) if lo is not None else 0)
            upper.append((hi - est) if hi is not None else 0)
        offset = (k - (len(methods) - 1) / 2) * width
        ax.bar(x + offset, vals, width=width, color=color, edgecolor="white",
               linewidth=.5, label=label, zorder=3)
        ax.errorbar(x + offset, vals, yerr=[lower, upper], fmt="none",
                    ecolor="#333333", elinewidth=.6, capsize=2,
                    capthick=.6, zorder=4)

    ax.set_xticks(x)
    ax.set_xticklabels([METADATA_LABELS[s] for s in STATES])
    ax.set_xlabel("Source-metadata state")
    ax.set_ylabel("Selective risk")
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    light_grid(ax, "y")

    fig.legend(loc="lower center", bbox_to_anchor=(.5, .05), ncol=4,
               handlelength=1.4, columnspacing=1.2)
    footnote(fig, "Original evidence, natural-length; whiskers are 95% "
                  "base-question cluster-bootstrap CI.", y=.004)
    panel_label(ax, "a")
    return save_figure(fig, Path(out_dir) / "fig7_grouped_bar")


# --------------------------------------------------------------------------- #
# Figure 8: boxplot of per-question selection scores
# --------------------------------------------------------------------------- #
def fig8_boxplot(rows, out_dir):
    methods = list(dict.fromkeys(r["method"] for r in rows))
    data = []
    for method in methods:
        sub = slice_rows(rows, method=method)
        data.append([r["selection_score"] for r in sub
                     if r.get("selection_score") is not None])

    fig, ax = plt.subplots(figsize=(SINGLE_COL, 2.7))
    fig.subplots_adjust(left=.17, right=.97, bottom=.22, top=.88)
    bp = ax.boxplot(
        data, positions=range(len(methods)), widths=.58, patch_artist=True,
        showfliers=True,
        medianprops=dict(color="white", linewidth=1),
        flierprops=dict(marker=".", markersize=3.5, markerfacecolor="#555555",
                        markeredgecolor="#555555", alpha=.6),
        whiskerprops=dict(linewidth=.7, color="#333333"),
        capprops=dict(linewidth=.7, color="#333333"),
        boxprops=dict(linewidth=.7))
    for patch, method in zip(bp["boxes"], methods):
        _, color, _ = method_style(method)
        patch.set_facecolor(color)
        patch.set_alpha(.85)
        patch.set_edgecolor("#333333")

    ax.set_xticks(range(len(methods)))
    ax.set_xticklabels([method_style(m)[0] for m in methods],
                       rotation=15, ha="right", fontsize=7)
    ax.set_ylabel("Selection score")
    ax.set_ylim(-.05, 1.06)
    light_grid(ax, "y")
    panel_label(ax, "a")
    footnote(fig, "Box = IQR; line = median; dots = outliers.", y=.01)
    return save_figure(fig, Path(out_dir) / "fig8_boxplot")


# --------------------------------------------------------------------------- #
# Figure 9: 100% stacked outcome composition
# --------------------------------------------------------------------------- #
def fig9_stacked(rows, out_dir):
    methods = list(dict.fromkeys(r["method"] for r in rows))
    cats = [
        ("correct_answer", "Correct answer", "#1A1A1A"),
        ("wrong_answer", "Wrong answer", "#D55E00"),
        ("wrong_abstain", "Wrong refusal", "#CC79A7"),
        ("correct_abstain", "Correct abstain", "#9AA2A9"),
    ]

    def classify(r):
        if r["answered"]:
            return "correct_answer" if r["correct"] else "wrong_answer"
        return "correct_abstain" if not r["should_answer"] else "wrong_abstain"

    fig, ax = plt.subplots(figsize=(DOUBLE_COL, 2.95))
    fig.subplots_adjust(left=.10, right=.985, bottom=.25, top=.84)
    x = np.arange(len(methods))
    totals = np.array([len(slice_rows(rows, method=m)) for m in methods],
                      dtype=float)
    bottoms = np.zeros(len(methods))
    for key, label, color in cats:
        vals = np.array([
            sum(1 for r in slice_rows(rows, method=m) if classify(r) == key)
            for m in methods], dtype=float) / totals
        ax.bar(x, vals, .62, bottom=bottoms, color=color, edgecolor="white",
               linewidth=.5, label=label, zorder=3)
        for i, v in enumerate(vals):
            if v > .045:
                ax.text(i, bottoms[i] + v / 2, f"{v:.0%}", ha="center",
                        va="center", fontsize=6.3, color="white")
        bottoms += vals

    ax.set_xticks(x)
    ax.set_xticklabels([method_style(m)[0] for m in methods])
    ax.set_ylabel("Share of questions")
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))

    fig.legend(loc="lower center", bbox_to_anchor=(.5, .05), ncol=4,
               handlelength=1.3, columnspacing=1)
    footnote(fig, "Natural-length, original evidence; each column sums to "
                  "100% over mutually exclusive outcomes.", y=.004)
    panel_label(ax, "a")
    return save_figure(fig, Path(out_dir) / "fig9_stacked")


# --------------------------------------------------------------------------- #
# Figure 10: coverage x risk bubble scatter, size = output-token cost
# --------------------------------------------------------------------------- #
def fig10_bubble(rows, out_dir):
    methods = list(dict.fromkeys(r["method"] for r in rows))
    fig, ax = plt.subplots(figsize=(SINGLE_COL, 2.8))
    fig.subplots_adjust(left=.18, right=.97, bottom=.18, top=.88)

    for method in methods:
        sub = slice_rows(rows, method=method)
        stats = summarize(sub)
        coverage, risk = stats["coverage"], stats["selective_risk"]
        if coverage is None or risk is None:
            continue
        tokens = [r["output_tokens"] for r in sub
                  if r.get("output_tokens") is not None]
        avg_tokens = sum(tokens) / len(tokens) if tokens else 0
        label, color, _ = method_style(method)
        size = 42 + max(avg_tokens - 50, 0) * 5
        ax.scatter(coverage, risk, s=size, color=color, alpha=.8,
                   edgecolor="white", linewidth=.7, zorder=3)
        # Labels pinned to the right at each point's own y, so vertically
        # adjacent points never share a label.
        ax.annotate(label, (coverage, risk), xytext=(10, 0),
                    textcoords="offset points", ha="left", va="center",
                    fontsize=6.6)

    ax.set_xlabel("Coverage")
    ax.set_ylabel("Selective risk")
    ax.set_xlim(0, 1.05)
    ax.set_ylim(0, 1.0)
    ax.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    light_grid(ax, "both")
    panel_label(ax, "a")
    footnote(fig, "Bubble area encodes mean output tokens (cost); the "
                  "lower-right region is preferred.", y=.01)
    return save_figure(fig, Path(out_dir) / "fig10_bubble")


# --------------------------------------------------------------------------- #
# Figure 11: polar radar profile, every axis oriented "larger is better"
# --------------------------------------------------------------------------- #
def fig11_radar(rows, out_dir):
    methods = list(dict.fromkeys(r["method"] for r in rows))
    axes_def = [
        ("Coverage", "coverage", False),
        ("1 - Risk", "selective_risk", True),
        ("Exact match", "em_all_rows", False),
        ("Retention", "independent_support_retention.micro_rate", False),
        ("1 - AURC", "aurc", True),
    ]
    n = len(axes_def)
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False).tolist()
    angles += angles[:1]

    fig = plt.figure(figsize=(SINGLE_COL, 3.3))
    ax = fig.add_subplot(111, polar=True)
    fig.subplots_adjust(left=.08, right=.92, bottom=.18, top=.90)

    for method in methods:
        sub = slice_rows(rows, method=method)
        stats = summarize(sub)
        vals = []
        for _, path, invert in axes_def:
            value = get_path(stats, path)
            value = 0 if value is None else value
            vals.append(1 - value if invert else value)
        vals += vals[:1]
        label, color, emphasis = method_style(method)
        ax.plot(angles, vals, color=color,
                linewidth=1.4 if emphasis else .9, label=label)
        ax.fill(angles, vals, color=color, alpha=.13 if emphasis else .06)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels([a[0] for a in axes_def], fontsize=6.8)
    ax.set_ylim(0, 1)
    ax.set_yticks([.25, .5, .75, 1])
    ax.set_yticklabels(["", ".5", "", "1"], fontsize=6, color="#888888")
    ax.grid(color=GRID, linewidth=.5)
    ax.set_axisbelow(True)
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(.5, .075),
               ncol=4, handlelength=1.4, columnspacing=.8)
    fig.text(.5, .015, "All axes normalized so larger is better; risk and "
                       "AURC inverted.", ha="center", fontsize=6.0,
             color="#5A6168")
    return save_figure(fig, Path(out_dir) / "fig11_radar")


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def build_extras(input_path, out_dir, length_policy="natural_length"):
    apply_style(serif=True)
    all_rows = load_jsonl(input_path)
    rows = slice_rows(all_rows, length_policy=length_policy, status="ok")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    written = []
    written += fig6_heatmap(slice_rows(rows, metadata_state="complete"), out_dir)
    written += fig7_grouped_bar(slice_rows(rows, replica_condition="no_replica"),
                                out_dir)
    written += fig8_boxplot(rows, out_dir)
    written += fig9_stacked(slice_rows(rows, replica_condition="no_replica"),
                            out_dir)
    written += fig10_bubble(slice_rows(rows, replica_condition="no_replica"),
                            out_dir)
    written += fig11_radar(slice_rows(rows, metadata_state="complete"), out_dir)
    return written


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="scored predictions JSONL")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--length-policy", default="natural_length")
    args = parser.parse_args()
    written = build_extras(args.input, args.output_dir, args.length_policy)
    print(json.dumps({"figures_written": len(written),
                      "files": written}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
