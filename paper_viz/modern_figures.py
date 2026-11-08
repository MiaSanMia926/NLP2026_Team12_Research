"""
Modern full-color figures for Track C, modeled on the reference screenshots.

  m1_radar      Filled polar profile with colored axis labels
  m2_heatmap    Red-yellow-green method x condition matrix, white cell grid
  m3_line_band  Multi-color lines with real bootstrap confidence bands
  m4_soft_bar   Soft grouped vertical bars with CI (main method hatched)
  m5_area       Stacked-area outcome composition across evidence conditions

All confidence bands/intervals come from the same reviewed bootstrap helpers;
no uncertainty is invented and no earlier file is modified.
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

from evaluation.metrics import load_jsonl, summarize  # noqa: E402
from evaluation.bootstrap import get_path  # noqa: E402
from modern_style import (SINGLE_COL, DOUBLE_COL, apply_style, method_style,  # noqa: E402
                          condition_style, panel_label, footnote, save_figure,
                          diverging_cmap, sequential_cmap, FILL_ALPHA,
                          BAND_ALPHA, GRID, METADATA_LABELS,
                          BLUE, ORANGE, GREEN, RED, PURPLE, TEAL)
from paper_figures import slice_rows, cluster_bootstrap_ci  # noqa: E402

CONDITIONS = ["no_replica", "same_source_replica",
              "independent_support", "complementary_support"]
STATES = ["complete", "missing", "incorrect"]
AXIS_COLORS = [BLUE, ORANGE, GREEN, PURPLE, TEAL]


# --------------------------------------------------------------------------- #
# M1: filled radar with colored axis labels
# --------------------------------------------------------------------------- #
def m1_radar(rows, out_dir):
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

    fig = plt.figure(figsize=(SINGLE_COL, 3.4))
    ax = fig.add_subplot(111, polar=True)
    fig.subplots_adjust(left=.08, right=.92, bottom=.18, top=.88)

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
        ax.plot(angles, vals, color=color, linewidth=1.8 if emphasis else 1.3,
                marker="o", markersize=5, label=label)
        ax.fill(angles, vals, color=color, alpha=.22 if emphasis else .12)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels([a[0] for a in axes_def], fontsize=7)
    # Color each axis label like the reference radar.
    for tick, color in zip(ax.get_xticklabels(), AXIS_COLORS):
        tick.set_color(color)
        tick.set_fontweight("bold")
    ax.set_ylim(0, 1)
    ax.set_yticks([.25, .5, .75, 1])
    ax.set_yticklabels(["", ".5", "", "1"], fontsize=6, color="#999999")
    ax.grid(color=GRID, linewidth=.6)
    ax.set_axisbelow(True)

    handles, labels = ax.get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(.5, .05),
               ncol=4, handlelength=1.4, columnspacing=.8)
    fig.text(.5, .005, "All axes normalized so larger is better; risk and "
                       "AURC inverted.", ha="center", fontsize=6,
             color="#5A6168")
    return save_figure(fig, Path(out_dir) / "m1_radar")


# --------------------------------------------------------------------------- #
# M2: red-yellow-green heatmap with white cell grid
# --------------------------------------------------------------------------- #
def m2_heatmap(rows, out_dir):
    methods = list(dict.fromkeys(r["method"] for r in rows))
    matrix = np.full((len(methods), len(CONDITIONS)), np.nan)
    for i, method in enumerate(methods):
        for j, cond in enumerate(CONDITIONS):
            sub = slice_rows(rows, method=method, replica_condition=cond)
            est, _, _ = cluster_bootstrap_ci(sub, "selective_risk")
            matrix[i, j] = est if est is not None else np.nan

    fig, ax = plt.subplots(figsize=(SINGLE_COL, 2.7))
    fig.subplots_adjust(left=.27, right=.91, bottom=.24, top=.90)
    # High risk should read red, so reverse the green-good diverging map.
    cmap = diverging_cmap().reversed()
    im = ax.imshow(matrix, cmap=cmap, vmin=0, vmax=1, aspect="auto")

    ax.set_xticks(np.arange(-.5, len(CONDITIONS), 1), minor=True)
    ax.set_yticks(np.arange(-.5, len(methods), 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=1.2)
    ax.tick_params(which="minor", length=0)

    ax.set_xticks(range(len(CONDITIONS)))
    ax.set_xticklabels([condition_style(c)[3] for c in CONDITIONS],
                       rotation=22, ha="right", fontsize=6.6)
    ax.set_yticks(range(len(methods)))
    ax.set_yticklabels([method_style(m)[0] for m in methods])
    ax.tick_params(which="major", length=0)

    for i in range(len(methods)):
        for j in range(len(CONDITIONS)):
            value = matrix[i, j]
            if np.isfinite(value):
                ax.text(j, i, f"{value:.2f}", ha="center", va="center",
                        fontsize=6.3,
                        color="white" if .32 < value < .72 else "#1A1A1A")

    cbar = fig.colorbar(im, ax=ax, fraction=.05, pad=.04)
    cbar.set_label("Selective risk", fontsize=7)
    cbar.ax.tick_params(labelsize=6.5, length=2)
    panel_label(ax, "a")
    footnote(fig, "Point estimates; red = high risk, cyan = low risk.",
             y=.01)
    return save_figure(fig, Path(out_dir) / "m2_heatmap")


# --------------------------------------------------------------------------- #
# M3: multi-color lines with bootstrap confidence bands
# --------------------------------------------------------------------------- #
def m3_line_band(rows, out_dir):
    methods = list(dict.fromkeys(r["method"] for r in rows))
    fig, ax = plt.subplots(figsize=(DOUBLE_COL, 3.1))
    fig.subplots_adjust(left=.10, right=.98, bottom=.26, top=.84)
    x = np.arange(len(STATES))

    for method in methods:
        label, color, emphasis = method_style(method)
        vals, los, his = [], [], []
        for state in STATES:
            sub = slice_rows(rows, method=method, metadata_state=state)
            est, lo, hi = cluster_bootstrap_ci(sub, "selective_risk")
            vals.append(est if est is not None else np.nan)
            los.append(lo if lo is not None else np.nan)
            his.append(hi if hi is not None else np.nan)
        vals, los, his = map(np.array, (vals, los, his))
        # Keep the line dominant; bands stay very light so overlapping CIs
        # never build up into a muddy block.
        ax.plot(x, vals, color=color, marker="o", markersize=7,
                linewidth=2.1 if emphasis else 1.6, label=label, zorder=5)
        ax.fill_between(x, los, his, color=color, alpha=.10, zorder=2,
                        linewidth=0)

    ax.set_xticks(x)
    ax.set_xticklabels([METADATA_LABELS[s] for s in STATES])
    ax.set_xlabel("Source-metadata state")
    ax.set_ylabel("Selective risk")
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.grid(color=GRID, linewidth=.6)
    ax.set_axisbelow(True)

    fig.legend(loc="lower center", bbox_to_anchor=(.5, .05), ncol=4,
               handlelength=1.6, columnspacing=1)
    footnote(fig, "Original evidence, natural-length; shaded bands are 95% "
                  "cluster-bootstrap CI.", y=.003)
    panel_label(ax, "a")
    return save_figure(fig, Path(out_dir) / "m3_line_band")


# --------------------------------------------------------------------------- #
# M4: soft grouped vertical bars with CI, main method hatched
# --------------------------------------------------------------------------- #
def m4_soft_bar(rows, out_dir):
    methods = list(dict.fromkeys(r["method"] for r in rows))
    fig, ax = plt.subplots(figsize=(DOUBLE_COL, 3.1))
    fig.subplots_adjust(left=.10, right=.98, bottom=.26, top=.84)
    width = .8 / len(methods)
    x = np.arange(len(STATES))

    for k, method in enumerate(methods):
        label, color, emphasis = method_style(method)
        vals, lower, upper = [], [], []
        for state in STATES:
            sub = slice_rows(rows, method=method, metadata_state=state)
            est, lo, hi = cluster_bootstrap_ci(sub, "selective_risk")
            vals.append(est if est is not None else np.nan)
            lower.append((est - lo) if lo is not None else 0)
            upper.append((hi - est) if hi is not None else 0)
        offset = (k - (len(methods) - 1) / 2) * width
        ax.bar(x + offset, vals, width=width, color=color,
               edgecolor="white", linewidth=.8, label=label, zorder=3,
               hatch="//" if emphasis else None)
        ax.errorbar(x + offset, vals, yerr=[lower, upper], fmt="none",
                    ecolor="#3A3A3A", elinewidth=.7, capsize=2.2,
                    capthick=.7, zorder=4)

    ax.set_xticks(x)
    ax.set_xticklabels([METADATA_LABELS[s] for s in STATES])
    ax.set_xlabel("Source-metadata state")
    ax.set_ylabel("Selective risk")
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.grid(color=GRID, linewidth=.6, axis="y")
    ax.set_axisbelow(True)

    fig.legend(loc="lower center", bbox_to_anchor=(.5, .05), ncol=4,
               handlelength=1.4, columnspacing=1)
    footnote(fig, "Original evidence, natural-length; whiskers are 95% "
                  "cluster-bootstrap CI.", y=.003)
    panel_label(ax, "a")
    return save_figure(fig, Path(out_dir) / "m4_soft_bar")


# --------------------------------------------------------------------------- #
# M5: stacked-area outcome composition across evidence conditions
# --------------------------------------------------------------------------- #
def m5_area(rows, out_dir):
    methods = list(dict.fromkeys(r["method"] for r in rows))
    cats = [
        ("correct_answer", "Correct answer", GREEN),
        ("wrong_answer", "Wrong answer", ORANGE),
        ("wrong_abstain", "Wrong refusal", RED),
        ("correct_abstain", "Correct abstain", TEAL),
    ]

    def classify(r):
        if r["answered"]:
            return "correct_answer" if r["correct"] else "wrong_answer"
        return "correct_abstain" if not r["should_answer"] else "wrong_abstain"

    # Use the main method across all four conditions for a coherent composition.
    main_method = methods[-1]
    x = np.arange(len(CONDITIONS))
    series = {key: [] for key, _, _ in cats}
    for cond in CONDITIONS:
        sub = slice_rows(rows, method=main_method, replica_condition=cond)
        total = len(sub) or 1
        for key, _, _ in cats:
            series[key].append(
                sum(1 for r in sub if classify(r) == key) / total)

    fig, ax = plt.subplots(figsize=(DOUBLE_COL, 3.4))
    fig.subplots_adjust(left=.10, right=.98, bottom=.31, top=.85)
    ax.stackplot(x, [series[key] for key, _, _ in cats],
                 labels=[label for _, label, _ in cats],
                 colors=[color for _, _, color in cats], alpha=.88,
                 edgecolor="white", linewidth=.8)

    ax.set_xticks(x)
    ax.set_xticklabels([condition_style(c)[3] for c in CONDITIONS],
                       rotation=15, ha="right", fontsize=7)
    ax.set_xlabel("Evidence condition")
    ax.set_ylabel("Share of questions")
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))

    fig.legend(loc="lower center", bbox_to_anchor=(.5, .035), ncol=4,
               handlelength=1.4, columnspacing=1)
    label, _, _ = method_style(main_method)
    footnote(fig, f"Outcome composition for {label}; each vertical slice "
                  "sums to 100%.", y=.003)
    panel_label(ax, "a")
    return save_figure(fig, Path(out_dir) / "m5_area")


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def build_modern(input_path, out_dir, length_policy="natural_length"):
    apply_style(serif=True)
    all_rows = load_jsonl(input_path)
    rows = slice_rows(all_rows, length_policy=length_policy, status="ok")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    written = []
    written += m1_radar(slice_rows(rows, metadata_state="complete"), out_dir)
    written += m2_heatmap(slice_rows(rows, metadata_state="complete"), out_dir)
    written += m3_line_band(slice_rows(rows, replica_condition="no_replica"),
                            out_dir)
    written += m4_soft_bar(slice_rows(rows, replica_condition="no_replica"),
                           out_dir)
    written += m5_area(rows, out_dir)
    return written


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="scored predictions JSONL")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--length-policy", default="natural_length")
    args = parser.parse_args()
    written = build_modern(args.input, args.output_dir, args.length_policy)
    print(json.dumps({"figures_written": len(written),
                      "files": written}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
