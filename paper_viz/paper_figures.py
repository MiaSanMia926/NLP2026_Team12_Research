"""
Publication figures for Track C, organized by research question.

Each figure has one non-overlapping job (no redundant geometries):

  fig1_rc          Risk-coverage step curves, panel-specific AURC  -> H1 / core
  fig2_metadata     Risk & coverage across complete/missing/incorrect, with
                    cluster-bootstrap CI                        -> H2
  fig3_dumbbell     Original vs. same-source-replica conditions -> H1
  fig4_forest       Gate-minus-Vote paired effects + numeric CI -> main contrast
  fig5_retention    Independent-support retention and abstention errors -> H3

Uncertainty is never invented: single-slice intervals use the same base-question
cluster resampling as evaluation.bootstrap, and the forest reuses the reviewed
paired_bootstrap implementation.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from collections import defaultdict
from pathlib import Path

# Make the project root importable when run as a plain script.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from matplotlib.ticker import PercentFormatter  # noqa: E402
from matplotlib.transforms import offset_copy  # noqa: E402

from evaluation.metrics import SLICE_FIELDS, load_jsonl, risk_curve, summarize  # noqa: E402
from evaluation.bootstrap import paired_bootstrap, percentile, get_path  # noqa: E402
from evaluation.publication import alignment, overlap_groups  # noqa: E402
from acl_style import (DOUBLE_COL, apply_style, method_style as acl_method_style,  # noqa: E402
                       condition_style,
                       save_figure, METADATA_LABELS, RULE)

BOOT_REPLICATES = 2000
BOOT_SEED = 20261019
METRIC_PRINT = {"coverage": "Coverage", "selective_risk": "Selective risk",
                "em_all_rows": "Exact match", "aurc": "AURC"}
REPLICA_CONDITIONS = ("no_replica", "same_source_replica")
METHOD_MARKS = (("o", "--"), ("^", ":"), ("D", "-."), ("s", "-"), ("v", "--"), ("P", ":"))
INK = "#132A38"
MUTED = "#4F6573"
ACCENT = "#006C68"
PANEL_TINT = "#F5F8FA"
ACCENT_TINT = "#E7F4F2"
GRID = "#DAE3E9"
BASELINE_COLORS = {"SMOKE_vote": "#345C8C", "SMOKE_exact": "#AF561D", "SMOKE_source": "#78608F", "B5": "#345C8C"}


def method_style(method):
    label, color, emphasis = acl_method_style(method)
    return label, ACCENT if emphasis else BASELINE_COLORS.get(method, color), emphasis


# --------------------------------------------------------------------------- #
# Data helpers
# --------------------------------------------------------------------------- #
def slice_rows(rows, **where):
    out = rows
    for key, value in where.items():
        out = [r for r in out if str(r.get(key)) == str(value)]
    return out


def cluster_bootstrap_ci(rows, metric_path, replicates=BOOT_REPLICATES, seed=BOOT_SEED):
    """
    Cluster-bootstrap CI for a single homogeneous method/condition slice.
    Resampling unit is the base question, exactly as the project protocol
    requires. The statistic is read from summarize() via a dotted path.
    """
    by_q = defaultdict(list)
    for r in rows:
        by_q[r["base_question_id"]].append(r)
    qids = sorted(by_q)

    def statistic(sample_rows):
        return get_path(summarize(sample_rows), metric_path)

    observed = statistic(rows)
    if observed is None:
        return None, None, None
    rng = random.Random(seed)
    draws = []
    for _ in range(replicates):
        sample = []
        for qid in (rng.choice(qids) for _ in qids):
            sample.extend(by_q[qid])
        value = statistic(sample)
        if value is not None and math.isfinite(value):
            draws.append(value)
    if not draws:
        return observed, None, None
    return observed, percentile(draws, 0.025), percentile(draws, 0.975)


def _pct_axis(ax, x=True, limits=(0, 1)):
    ticks = [0, .25, .5, .75, 1.0]
    if x:
        ax.set_xticks(ticks)
        ax.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
        ax.set_xlim(*limits)
    else:
        ax.set_yticks(ticks)
        ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
        ax.set_ylim(*limits)


def _panel(ax, col, title):
    anchor = offset_copy(ax.transAxes, fig=ax.figure, x=-13, y=7, units="points")
    ax.text(0, 1, chr(97 + col), transform=anchor, va="bottom", fontsize=9, fontweight="bold", color=ACCENT)
    ax.set_title(title, loc="left", pad=7, fontweight="bold", color=INK)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, length=2)


def _scope(rows, evidence):
    sample = next(iter(rows), {})
    synthetic = str(sample.get("dataset_id", "")).startswith("SYNTHETIC_")
    parts = ["Synthetic demo"] if synthetic else []
    if sample:
        questions = len({row["base_question_id"] for row in rows})
        parts += [sample["split"], sample["length_policy"].replace("_", " "), f"{questions} base questions"]
    return "  |  ".join([*parts, evidence])


def _heading(fig, rows, title, evidence):
    height = fig.get_figheight()
    fig.add_artist(Rectangle((0, 1 - .73 / height), 1, .73 / height,
                             transform=fig.transFigure, facecolor=PANEL_TINT, edgecolor="none", zorder=-3))
    fig.add_artist(Rectangle((.043, 1 - .59 / height), .007, .43 / height,
                             transform=fig.transFigure, facecolor=ACCENT, edgecolor="none", zorder=-2))
    fig.text(.066, 1 - .165 / height, _scope(rows, evidence), va="top", color=MUTED, fontsize=7.5)
    fig.text(.066, 1 - .32 / height, title, va="top", color=INK, fontsize=13.5,
             fontfamily="DejaVu Serif", fontweight="bold")


def _note(fig, details):
    fig.text(.066, .13 / fig.get_figheight(), details, fontsize=6.5, color=MUTED, va="bottom")


def _row_tint(ax, center, color=PANEL_TINT, half_height=.5):
    ax.axhspan(center - half_height, center + half_height, color=color, linewidth=0, zorder=0)


def _grid(ax, axis):
    ax.set_axisbelow(True)
    ax.grid(axis=axis, color=GRID, linewidth=.55)


def _interval(ax, y, low, high, color):
    # Percentile intervals can lie entirely to one side of the observed value.
    if low is not None and high is not None:
        ax.plot([low, high], [y, y], color=color, linewidth=.85,
                marker="|", markersize=4, markeredgewidth=.8, zorder=3)


def _point(ax, y, estimate, color, marker="o", size=4.5, filled=True):
    ax.plot(estimate, y, marker=marker, markersize=size, linestyle="none",
            markerfacecolor=color if filled else "white", markeredgecolor=color,
            markeredgewidth=.8, zorder=4)


def _proportion_panel(ax, xlabel, labels, show_labels, *, limits=(-.04, 1.2)):
    ax.set_yticks(range(len(labels)), labels if show_labels else [""] * len(labels))
    ax.set(ylim=(len(labels) - .5, -.5), xlabel=xlabel)
    ax.tick_params(axis="y", length=0)
    _pct_axis(ax, limits=limits)
    _grid(ax, "x")


def _legend(fig, handles, y=.12, ncols=4):
    if handles:
        fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(.5, y),
                   ncols=ncols, handlelength=1.7, handletextpad=.45, columnspacing=1.2)


def _save(fig, out_dir, stem):
    prefix = Path(out_dir) / stem
    try:
        if os.environ.get("NATURE_FIGURE_QA_DIR"):
            prefix.parent.mkdir(parents=True, exist_ok=True)
            alignment(fig, [ax for ax in fig.axes if ax.axison], prefix)
        return save_figure(fig, prefix)
    finally:
        plt.close(fig)


# --------------------------------------------------------------------------- #
# Figure 1: risk-coverage step curves (core)
# --------------------------------------------------------------------------- #
def _aurc_table(ax, methods, marks, curves_by_condition):
    _panel(ax, 2, "AURC by method")
    ax.set_axis_off()
    ax.set(xlim=(0, 1), ylim=(max(len(methods), 1) - .5, -1.45))
    headers = ((.08, "Method", "left"), (.405, "Original", "right"),
               (.565, "Replicas", "right"), (.755, "← Lower     Higher →", "center"),
               (.98, "Δ AURC", "right"))
    for x, label, align in headers:
        ax.text(x, -.94, label, color=MUTED, ha=align, va="center", fontsize=7, fontweight="bold")
    ax.axhline(-.5, color=GRID, linewidth=.7)
    values = [[curves[method]["area"] for curves in curves_by_condition] for method in methods]
    changes = [right - left if left is not None and right is not None else None for left, right in values]
    limit = max(.1, max((abs(value) for value in changes if value is not None), default=0))
    for i, (method, (left, right), change) in enumerate(zip(methods, values, changes)):
        name, color, emphasis = method_style(method)
        if emphasis or i % 2 == 0:
            _row_tint(ax, i, ACCENT_TINT if emphasis else PANEL_TINT)
        ax.plot([.018, .062], [i, i], color=color, linestyle=marks[method][1],
                linewidth=1.8 if emphasis else 1.3)
        ax.text(.08, i, name, color=INK, va="center", fontsize=8, fontweight="bold" if emphasis else "normal")
        for x, value in ((.405, left), (.565, right)):
            ax.text(x, i, f"{value:.3f}" if value is not None else "NA", ha="right", va="center",
                    color=INK, fontsize=8)
        if change is not None:
            ax.plot([.755, .755 + .112 * change / limit], [i, i], color=color,
                    linewidth=4, solid_capstyle="round")
        ax.text(.98, i, _signed(change, 3), ha="right", va="center", color=color, fontsize=8, fontweight="bold")
    ax.vlines(.755, -.5, len(methods) - .5, colors=GRID, linewidth=.75, zorder=2.1)
    if not methods:
        ax.text(.08, 0, "No candidate predictions", va="center", color=MUTED, fontsize=8)


def _signed(value, decimals):
    if value is None:
        return "NA"
    if round(value, decimals) == 0:
        return f"{0:.{decimals}f}"
    return f"{value:+.{decimals}f}".replace("-", "−")


def fig1_risk_coverage(rows, out_dir):
    rows = [r for r in rows if r["replica_condition"] in REPLICA_CONDITIONS]
    methods = list(dict.fromkeys(r["method"] for r in rows))
    marks = {method: METHOD_MARKS[i % len(METHOD_MARKS)] for i, method in enumerate(methods)}
    curves_by_condition = [
        {method: risk_curve(slice_rows(rows, method=method, replica_condition=condition)) for method in methods}
        for condition in REPLICA_CONDITIONS
    ]
    panel_groups = [overlap_groups([({"method": method}, curve) for method, curve in curves.items()])
                    for curves in curves_by_condition]
    curve_height = 1.62
    table_height = .66 + .24 * max(len(methods), 1)
    panel_gap = .69 + .14 * max(map(len, panel_groups))
    height = 1.07 + curve_height + panel_gap + table_height + .49
    fig = plt.figure(figsize=(DOUBLE_COL, height))
    grid = fig.add_gridspec(2, 2, left=.125, right=.955, top=1 - 1.07 / height,
                           bottom=.49 / height, height_ratios=(curve_height, table_height),
                           hspace=2 * panel_gap / (curve_height + table_height), wspace=.23)
    axes = [fig.add_subplot(grid[0, 0]), fig.add_subplot(grid[0, 1])]
    table = fig.add_subplot(grid[1, :])
    for j, (condition, groups) in enumerate(zip(REPLICA_CONDITIONS, panel_groups)):
        ax = axes[j]
        _panel(ax, j, condition_style(condition)[3])
        for coincident in groups:
            representative, curve = max(coincident, key=lambda item: method_style(item[0]["method"])[2])
            method = representative["method"]
            _, color, emphasis = method_style(method)
            names = " / ".join(method_style(context["method"])[0] for context, _ in coincident)
            points = curve["points"][1:]
            # The risk at the right endpoint applies to each coverage interval.
            coverage = [0.] + [p["coverage"] for p in points]
            risk = [points[0]["risk"]] + [p["risk"] for p in points]
            ax.step(coverage, risk, where="pre", color=color, linestyle=marks[method][1],
                    linewidth=2.15 if emphasis else 1.45, zorder=4 if emphasis else 3, label=names)
        handles, _ = ax.get_legend_handles_labels()
        if handles:
            ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(0, -.28),
                      borderaxespad=0, handlelength=2.1, handletextpad=.45, labelspacing=.31,
                      fontsize=6.5, labelcolor=INK)
        else:
            ax.text(.5, .5, "No rankable candidates", transform=ax.transAxes, ha="center", color=MUTED)
        _pct_axis(ax, x=True, limits=(-.02, 1.02))
        _pct_axis(ax, x=False, limits=(-.025, 1.025))
        _grid(ax, "y")
    axes[0].set_ylabel("Candidate error risk", color=MUTED)
    axes[1].tick_params(axis="y", labelleft=False)
    axes[0].set_xlabel("Candidate coverage", color=MUTED)
    axes[1].set_xlabel("Candidate coverage", color=MUTED)
    _aurc_table(table, methods, marks, curves_by_condition)
    _heading(fig, rows, "Candidate ranking under evidence replication", "Complete metadata")
    _note(fig, "Δ = replicas − original. Lower AURC is better. Identical curves share a line.\n"
               "NA = ranking unavailable.")
    return _save(fig, out_dir, "fig1_risk_coverage")


# --------------------------------------------------------------------------- #
# Figure 2: metadata three-state comparison with cluster-bootstrap CI (H2)
# --------------------------------------------------------------------------- #
def fig2_metadata(rows, out_dir):
    states = ("complete", "missing", "incorrect")
    methods = list(dict.fromkeys(r["method"] for r in rows))
    marks = {method: METHOD_MARKS[i % len(METHOD_MARKS)][0] for i, method in enumerate(methods)}
    legend_extra = .15 * max(0, (len(methods) - 1) // 4)
    height = max(4.0, 2.5 + .49 * len(methods)) + legend_extra
    fig, axes = plt.subplots(1, 2, figsize=(DOUBLE_COL, height))
    fig.subplots_adjust(left=.15, right=.955, bottom=(.78 + legend_extra) / height,
                        top=1 - 1.09 / height, wspace=.19)
    handles = []
    for method in methods:
        label, color, emphasis = method_style(method)
        handles.append(Line2D([], [], color=color, marker=marks[method], linestyle="none",
                              markersize=5 if emphasis else 4.2, label=label))

    for col, metric in enumerate(("coverage", "selective_risk")):
        ax = axes[col]
        _panel(ax, col, METRIC_PRINT[metric])
        for index in (0, 2):
            _row_tint(ax, index)
        for state_index, state in enumerate(states):
            for k, method in enumerate(methods):
                _, color, emphasis = method_style(method)
                y = state_index + .77 * ((k + .5) / len(methods) - .5)
                sample = slice_rows(rows, method=method, metadata_state=state)
                estimate, low, high = cluster_bootstrap_ci(sample, metric)
                if emphasis:
                    _row_tint(ax, y, ACCENT_TINT, half_height=.39 / len(methods))
                ax.text(1.28, y, "NA" if estimate is None else f"{estimate:.1%}",
                        ha="right", va="center", fontsize=6.5, color=color,
                        fontweight="bold" if emphasis else "normal")
                if estimate is not None:
                    _interval(ax, y, low, high, color)
                    _point(ax, y, estimate, color, marks[method], 5 if emphasis else 4.2)
        _proportion_panel(ax, "", [METADATA_LABELS[s] for s in states], col == 0, limits=(-.04, 1.32))

    _legend(fig, handles, y=.32 / height, ncols=min(4, max(1, len(handles))))
    _heading(fig, rows, "Selective answering across metadata states", "Original evidence")
    _note(fig, "Whiskers show 95% base-question cluster bootstrap. NA = unavailable or undefined.")
    return _save(fig, out_dir, "fig2_metadata")


# --------------------------------------------------------------------------- #
# Figure 3: paired original -> replica dumbbell (H1)
# --------------------------------------------------------------------------- #
def fig3_dumbbell(rows, out_dir):
    methods = list(dict.fromkeys(r["method"] for r in rows))
    height = max(3.85, 2.38 + .38 * len(methods))
    fig, axes = plt.subplots(1, 2, figsize=(DOUBLE_COL, height))
    fig.subplots_adjust(left=.18, right=.955, bottom=.92 / height, top=1 - 1.18 / height, wspace=.20)

    for col, metric in enumerate(("coverage", "selective_risk")):
        ax = axes[col]
        _panel(ax, col, METRIC_PRINT[metric])
        ax.text(1.27, 1.02, "Δ pp", transform=ax.get_xaxis_transform(), ha="right", va="bottom",
                fontsize=7, color=MUTED, fontweight="bold")
        for i, method in enumerate(methods):
            _, color, emphasis = method_style(method)
            estimates = [cluster_bootstrap_ci(slice_rows(rows, method=method, replica_condition=condition),
                                              metric) for condition in REPLICA_CONDITIONS]
            positions = [i - .17, i + .17]
            if emphasis or i % 2 == 0:
                _row_tint(ax, i, ACCENT_TINT if emphasis else PANEL_TINT)
            original, replica = (estimate for estimate, _, _ in estimates)
            change = None
            if original is not None and replica is not None:
                change = (replica - original) * 100
                ax.plot([estimate for estimate, _, _ in estimates], positions,
                        color=color, alpha=.75, linewidth=1.1, zorder=2)
            ax.text(1.27, i, _signed(change, 1), ha="right", va="center",
                    fontsize=7, color=color, fontweight="bold" if emphasis else "normal")
            for condition, y, (estimate, low, high) in zip(REPLICA_CONDITIONS, positions, estimates):
                marker, _, filled, _ = condition_style(condition)
                if estimate is None:
                    continue
                _interval(ax, y, low, high, color)
                _point(ax, y, estimate, color, marker, 5 if emphasis else 4.3, filled)
        _proportion_panel(ax, "", [method_style(m)[0] for m in methods], col == 0, limits=(-.04, 1.31))

    handles = []
    for condition in REPLICA_CONDITIONS:
        marker, _, filled, name = condition_style(condition)
        handles.append(Line2D([], [], marker=marker, linestyle="none", markersize=5,
                              markerfacecolor=RULE if filled else "white", markeredgecolor=RULE, label=name))
    _legend(fig, handles, y=.46 / height, ncols=2)
    _heading(fig, rows, "Answering behavior under evidence replication", "Complete metadata")
    _note(fig, "Δ pp = replicas − original, in percentage points. NA = undefined or unavailable.\n"
               "Whiskers show 95% base-question cluster bootstrap for each condition.")
    return _save(fig, out_dir, "fig3_dumbbell")


# --------------------------------------------------------------------------- #
# Figure 4: paired-effect forest with numeric column (main contrast)
# --------------------------------------------------------------------------- #
def fig4_forest(rows, out_dir, method_a="SMOKE_gate", method_b="SMOKE_vote"):
    metrics = ("coverage", "selective_risk", "em_all_rows", "aurc")
    a_label, b_label = method_style(method_a)[0], method_style(method_b)[0]
    fig = plt.figure(figsize=(DOUBLE_COL, 3.45))
    grid = fig.add_gridspec(1, 2, width_ratios=(2.5, 1), left=.16, right=.965,
                           top=.69, bottom=.24, wspace=.14)
    ax = fig.add_subplot(grid[0])
    values = fig.add_subplot(grid[1], sharey=ax)
    values.set_axis_off()
    values.set_title("Estimate [95% CI]", loc="right", color=INK, fontweight="bold", pad=7)
    ax.set_title(f"{a_label} − {b_label}", loc="left", color=INK, fontweight="bold", pad=7)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.axvline(0, linestyle="--", color=MUTED, linewidth=.8, zorder=2)

    pair_available = {method_a, method_b} <= {r["method"] for r in rows}
    for i, metric in enumerate(metrics):
        if i % 2 == 0:
            _row_tint(ax, i)
            _row_tint(values, i)
        result = (paired_bootstrap(rows, method_a, method_b, metric, BOOT_REPLICATES, BOOT_SEED)
                  if pair_available else {"observed_difference": None, "ci_95": None})
        estimate, ci = result["observed_difference"], result["ci_95"]
        if estimate is None:
            value_text = "NA"
        else:
            _point(ax, i, estimate, ACCENT, marker="s", size=5)
            value_text = f"{estimate:+.3f}  [NA]"
            if ci is not None:
                _interval(ax, i, *ci, ACCENT)
                value_text = f"{estimate:+.3f}  [{ci[0]:+.3f}, {ci[1]:+.3f}]"
        values.text(1, i, value_text, transform=values.get_yaxis_transform(),
                    ha="right", va="center", fontsize=7.5, color=INK)

    ax.set_yticks(range(len(metrics)), [METRIC_PRINT[m] for m in metrics])
    ax.tick_params(axis="y", length=0)
    ax.set(ylim=(3.5, -.5), xlim=(-1.05, 1.05), xticks=[-1, -.5, 0, .5, 1],
           xlabel="Difference in metric")
    _heading(fig, rows, "Paired differences across evaluation metrics", "Original evidence, complete metadata")
    _note(fig, f"95% paired base-question percentile bootstrap ({BOOT_REPLICATES:,} draws).")
    return _save(fig, out_dir, "fig4_forest")


# --------------------------------------------------------------------------- #
# Figure 5: independent-support retention + abstention errors (H3)
# --------------------------------------------------------------------------- #
def fig5_retention(rows, out_dir):
    methods = list(dict.fromkeys(r["method"] for r in rows))
    height = max(4.15, 2.68 + .38 * len(methods))
    fig, axes = plt.subplots(1, 2, figsize=(DOUBLE_COL, height))
    fig.subplots_adjust(left=.18, right=.955, bottom=1.13 / height, top=1 - 1.16 / height, wspace=.19)
    labels = [method_style(m)[0] for m in methods]
    _panel(axes[0], 0, "Independent support")
    _panel(axes[1], 1, "Answering errors")
    for ax, label in zip(axes, ("Groups", "Eligible n")):
        ax.text(1.28, 1.02, label, transform=ax.get_xaxis_transform(), ha="right", va="bottom",
                color=MUTED, fontsize=6.5, fontweight="bold")
    error_metrics = (("Inappropriate answer", "inappropriate_answer_rate", "should_abstain_n", "o", "#AF561D"),
                     ("Inappropriate refusal", "inappropriate_refusal_rate", "should_answer_n", "s", "#345C8C"))

    for i, method in enumerate(methods):
        _, color, emphasis = method_style(method)
        if emphasis or i % 2 == 0:
            for ax in axes:
                _row_tint(ax, i, ACCENT_TINT if emphasis else PANEL_TINT)
        retained = slice_rows(rows, method=method, replica_condition="independent_support")
        estimate, low, high = cluster_bootstrap_ci(retained, "independent_support_retention.micro_rate")
        group_counts = summarize(retained)["independent_support_retention"]
        count_label = "NA" if estimate is None else f"{group_counts['retained_groups']}/{group_counts['gold_groups']}"
        axes[0].text(1.28, i, count_label, ha="right", va="center", fontsize=7, color=color)
        if estimate is not None:
            _interval(axes[0], i, low, high, color)
            _point(axes[0], i, estimate, color, size=5 if emphasis else 4.2)

        original = slice_rows(rows, method=method, replica_condition="no_replica")
        observed = summarize(original)
        for k, (_, path, count_key, marker, error_color) in enumerate(error_metrics):
            y = i + (k - .5) * .36
            estimate, low, high = cluster_bootstrap_ci(original, path)
            axes[1].text(1.28, y, str(observed[count_key]), ha="right", va="center", fontsize=6.5, color=error_color)
            if estimate is None:
                continue
            _interval(axes[1], y, low, high, error_color)
            _point(axes[1], y, estimate, error_color, marker=marker, filled=(k == 0))

    _proportion_panel(axes[0], "Retained / gold groups", labels, True, limits=(-.04, 1.32))
    _proportion_panel(axes[1], "Rate over eligible predictions", labels, False, limits=(-.04, 1.32))
    handles = [Line2D([], [], marker=marker, color=color, linestyle="none", markersize=4.5,
                      markerfacecolor=color if k == 0 else "white", label=label)
               for k, (label, _, _, marker, color) in enumerate(error_metrics)]
    _legend(fig, handles, y=.48 / height, ncols=2)
    _heading(fig, rows, "Evidence retention and abstention errors", "Errors measured on original evidence")
    _note(fig, "Whiskers show 95% base-question cluster bootstrap. NA = unavailable or undefined.\n"
               "Error denominators are predictions labelled to abstain (circle) or answer (square).")
    return _save(fig, out_dir, "fig5_retention")


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def build_all(input_path, out_dir, length_policy="natural_length", split=None):
    apply_style(serif=False)
    plt.rcParams.update({"text.color": INK, "axes.labelcolor": MUTED,
                         "xtick.labelsize": 7, "ytick.labelsize": 7.5,
                         "axes.titlesize": 8.7, "legend.fontsize": 7})
    all_rows = slice_rows(load_jsonl(input_path), length_policy=length_policy)
    if not all_rows:
        raise ValueError(f"No predictions for length policy {length_policy!r}")
    splits = list(dict.fromkeys(r["split"] for r in all_rows))
    if split is None:
        split = next((preferred for preferred in ("test", "dev") if preferred in splits), splits[0])
    selected = slice_rows(all_rows, split=split)
    rows = slice_rows(selected, status="ok")
    if not rows:
        raise ValueError(f"No successful predictions for split {split!r} and length policy {length_policy!r}")
    for field in (*SLICE_FIELDS, "position_seed"):
        if len({row.get(field) for row in selected}) > 1:
            raise ValueError(f"Mixed {field}; pass a JSONL with one comparable evaluation slice")
    configs = defaultdict(set)
    for row in selected:
        configs[row["method"]].add(row["config_hash"])
    if any(len(hashes) > 1 for hashes in configs.values()):
        raise ValueError("Multiple configurations for one method; pass a JSONL with one configuration per method")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    written = []
    # Figures 1, 3 use complete metadata; figure 2 spans all states.
    written += fig1_risk_coverage(slice_rows(rows, metadata_state="complete"), out_dir)
    written += fig2_metadata(slice_rows(rows, replica_condition="no_replica"), out_dir)
    written += fig3_dumbbell(slice_rows(rows, metadata_state="complete"), out_dir)
    # The paired bootstrap handles failed rows at the matched-question level.
    forest_rows = slice_rows(selected, metadata_state="complete", replica_condition="no_replica")
    method_a, method_b = ("B7", "B5") if {"B7", "B5"} <= configs.keys() else ("SMOKE_gate", "SMOKE_vote")
    written += fig4_forest(forest_rows, out_dir, method_a=method_a, method_b=method_b)
    written += fig5_retention(rows, out_dir)
    return written


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="scored predictions JSONL")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--length-policy", default="natural_length")
    parser.add_argument("--split", help="dataset split (default: test, then dev, then the first available split)")
    args = parser.parse_args()
    written = build_all(args.input, args.output_dir, args.length_policy, args.split)
    print(json.dumps({"figures_written": len(written),
                      "files": written}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
