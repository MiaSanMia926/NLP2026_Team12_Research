"""
Publication figures for Track C, organized by research question.

Each figure has one non-overlapping job (no redundant geometries):

  fig1_rc          Risk-coverage step curves, AURC in legend  -> H1 / core
  fig2_metadata     Risk & coverage across complete/missing/incorrect, with
                    cluster-bootstrap CI                        -> H2
  fig3_dumbbell     Paired original -> same-source-replica shift -> H1
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
import random
import sys
from collections import defaultdict
from pathlib import Path

# Make the project root importable when run as a plain script.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import PercentFormatter  # noqa: E402

from evaluation.metrics import load_jsonl, risk_curve, summarize  # noqa: E402
from evaluation.bootstrap import paired_bootstrap, percentile, get_path  # noqa: E402
from acl_style import (SINGLE_COL, DOUBLE_COL, apply_style, method_style,  # noqa: E402
                       condition_style, panel_label, footnote, light_grid,
                       save_figure, METADATA_LABELS, RULE)

BOOT_REPLICATES = 2000
BOOT_SEED = 20261019
METRIC_PRINT = {"coverage": "Coverage", "selective_risk": "Selective risk",
                "em_all_rows": "Exact match", "aurc": "AURC"}


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
    rng = random.Random(seed)
    draws = []
    for _ in range(replicates):
        sample = []
        for qid in (rng.choice(qids) for _ in qids):
            sample.extend(by_q[qid])
        value = statistic(sample)
        if value is not None and math.isfinite(value):
            draws.append(value)
    if observed is None or not draws:
        return observed, None, None
    return observed, percentile(draws, 0.025), percentile(draws, 0.975)


def _pct_axis(ax, x=True, limit=1.0):
    ticks = [0, .25, .5, .75, 1.0]
    if x:
        ax.set_xticks(ticks)
        ax.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
        ax.set_xlim(0, limit)
    else:
        ax.set_yticks(ticks)
        ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
        ax.set_ylim(0, limit)


# --------------------------------------------------------------------------- #
# Figure 1: risk-coverage step curves (core)
# --------------------------------------------------------------------------- #
def fig1_risk_coverage(rows, out_dir):
    conditions = ["no_replica", "same_source_replica"]
    methods = list(dict.fromkeys(r["method"] for r in rows))
    fig, axes = plt.subplots(1, 2, figsize=(DOUBLE_COL, 3.0))
    fig.subplots_adjust(left=.10, right=.985, bottom=.27, top=.83, wspace=.20)
    legend_items = []

    for j, condition in enumerate(conditions):
        ax = axes[j]
        panel_label(ax, chr(97 + j))
        _, linestyle, _, cond_label = condition_style(condition)
        ax.set_title(cond_label, fontsize=8.5)
        for method in methods:
            label, color, emphasis = method_style(method)
            marker, _, filled, _ = condition_style(condition)
            sub = slice_rows(rows, method=method, replica_condition=condition)
            curve = risk_curve(sub)
            if not curve["available"]:
                continue
            pts = curve["points"]
            cov = [p["coverage"] for p in pts]
            risk = [0.0 if p["risk"] is None else p["risk"] for p in pts]
            line, = ax.step(cov, risk, where="post", color=color,
                            linestyle=linestyle, linewidth=1.8 if emphasis else 1.1,
                            marker=marker, markersize=3.6 if emphasis else 3,
                            markerfacecolor=color if filled else "white",
                            markeredgecolor=color, markeredgewidth=.8, zorder=3)
            # One method-level legend entry, using the original-panel AURC.
            if j == 0:
                legend_items.append((line, f"{label} (AURC {curve['area']:.3f})"))
        ax.set_xlabel("Candidate coverage")
        if j == 0:
            ax.set_ylabel("Error risk")
        _pct_axis(ax, x=True)
        _pct_axis(ax, x=False)
        light_grid(ax, "y")
    # Single figure-level legend on its own row; footnote sits strictly below.
    fig.legend([h for h, _ in legend_items], [t for _, t in legend_items],
               loc="lower center", bbox_to_anchor=(.5, .055), ncol=4,
               handlelength=2.2, columnspacing=1.3)
    footnote(fig, "Complete metadata, natural-length context; step curves from "
                  "empirical candidate ranks; AURC = area under the curve.", y=.004)
    return save_figure(fig, Path(out_dir) / "fig1_risk_coverage")


# --------------------------------------------------------------------------- #
# Figure 2: metadata three-state comparison with cluster-bootstrap CI (H2)
# --------------------------------------------------------------------------- #
def fig2_metadata(rows, out_dir):
    states = ["complete", "missing", "incorrect"]
    methods = list(dict.fromkeys(r["method"] for r in rows))
    fig, axes = plt.subplots(1, 2, figsize=(DOUBLE_COL, 2.6))
    fig.subplots_adjust(left=.10, right=.985, bottom=.23, top=.83, wspace=.24)
    x = range(len(states))

    for col, metric in enumerate(("coverage", "selective_risk")):
        ax = axes[col]
        panel_label(ax, chr(97 + col))
        ax.set_title(METRIC_PRINT[metric], fontsize=8.5)
        for method in methods:
            label, color, emphasis = method_style(method)
            ys, lows, highs = [], [], []
            for state in states:
                sub = slice_rows(rows, method=method, metadata_state=state)
                est, lo, hi = cluster_bootstrap_ci(sub, metric)
                ys.append(float("nan") if est is None else est)
                lows.append(float("nan") if lo is None else est - lo)
                highs.append(float("nan") if hi is None else hi - est)
            ax.errorbar(list(x), ys, yerr=[lows, highs], color=color,
                        marker="o", markersize=4.5 if emphasis else 4,
                        linewidth=1.5 if emphasis else 1.0,
                        capsize=2.5, capthick=.7, elinewidth=.7,
                        label=label, zorder=3)
        ax.set_xticks(list(x))
        ax.set_xticklabels([METADATA_LABELS[s] for s in states])
        ax.set_ylim(0, 1.0)
        ax.set_yticks([0, .25, .5, .75, 1])
        ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
        ax.set_xlabel("Source-metadata state")
        light_grid(ax, "y")
        if col == 0:
            ax.set_ylabel("Proportion")
        if col == 1:
            ax.legend(loc="upper left", bbox_to_anchor=(.02, 1.02))
    footnote(fig, "Original evidence, natural-length context; points are sample "
                  "proportions, bars are 95% base-question cluster-bootstrap CI.")
    return save_figure(fig, Path(out_dir) / "fig2_metadata")


# --------------------------------------------------------------------------- #
# Figure 3: paired original -> replica dumbbell (H1)
# --------------------------------------------------------------------------- #
def fig3_dumbbell(rows, out_dir):
    methods = list(dict.fromkeys(r["method"] for r in rows))
    metrics = ("coverage", "selective_risk")
    fig, axes = plt.subplots(1, 2, figsize=(DOUBLE_COL, 3.05))
    fig.subplots_adjust(left=.16, right=.985, bottom=.28, top=.82, wspace=.26)

    for col, metric in enumerate(metrics):
        ax = axes[col]
        panel_label(ax, chr(97 + col))
        ax.set_title(METRIC_PRINT[metric], fontsize=8.5)
        for i, method in enumerate(methods):
            label, color, emphasis = method_style(method)
            estimates = []
            for condition in ("no_replica", "same_source_replica"):
                sub = slice_rows(rows, method=method, replica_condition=condition)
                est, lo, hi = cluster_bootstrap_ci(sub, metric)
                estimates.append((condition, est, lo, hi))
            (_, v0, lo0, hi0), (_, v1, lo1, hi1) = estimates
            # Connecting segment.
            ax.plot([v0, v1], [i, i], color=color, linewidth=1.0, zorder=2)
            for condition, value, lo, hi in estimates:
                marker, _, filled, _ = condition_style(condition)
                ax.errorbar(value, i,
                            xerr=[[value - lo], [hi - value]] if lo is not None else None,
                            marker=marker, markersize=6 if emphasis else 5,
                            markerfacecolor=color if filled else "white",
                            markeredgecolor=color, markeredgewidth=.9,
                            ecolor=color, elinewidth=.6, capsize=2,
                            color=color, linestyle="none", zorder=3)
        ax.set_yticks(range(len(methods)))
        # Only the left panel carries method names to avoid gutter collisions.
        ax.set_yticklabels([method_style(m)[0] for m in methods] if col == 0
                           else [""] * len(methods))
        ax.set_ylim(-.6, len(methods) - .4)
        ax.set_xlim(0, 1.0)
        ax.set_xticks([0, .25, .5, .75, 1])
        ax.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
        ax.set_xlabel("Proportion")
        light_grid(ax, "x")
    # Shared condition legend.
    from matplotlib.lines import Line2D
    handles = []
    for condition in ("no_replica", "same_source_replica"):
        marker, _, filled, name = condition_style(condition)
        handles.append(Line2D([], [], marker=marker, linestyle="none",
                              markerfacecolor=RULE if filled else "white",
                              markeredgecolor=RULE, markersize=7, label=name))
    fig.legend(handles=handles, loc="lower center", ncol=2,
               bbox_to_anchor=(.5, .045), handletextpad=.5, columnspacing=2)
    footnote(fig, "Complete metadata, natural-length context; paired segments "
                  "link the same base questions; 95% cluster-bootstrap CI.", y=.002)
    return save_figure(fig, Path(out_dir) / "fig3_dumbbell")


# --------------------------------------------------------------------------- #
# Figure 4: paired-effect forest with numeric column (main contrast)
# --------------------------------------------------------------------------- #
def fig4_forest(rows, out_dir, method_a="SMOKE_gate", method_b="SMOKE_vote"):
    metrics = ("coverage", "selective_risk", "em_all_rows", "aurc")
    fig, ax = plt.subplots(figsize=(SINGLE_COL, 2.95))
    fig.subplots_adjust(left=.33, right=.97, bottom=.17, top=.90)
    ax.axvline(0, linestyle="--", color=RULE, linewidth=.7, zorder=1)

    for i, metric in enumerate(metrics):
        result = paired_bootstrap(rows, method_a, method_b, metric,
                                  BOOT_REPLICATES, BOOT_SEED)
        est, ci = result["observed_difference"], result["ci_95"]
        if est is None or ci is None:
            ax.text(-.95, i, "NA", fontsize=7, va="center")
            continue
        lo, hi = ci
        ax.plot([lo, hi], [i, i], color="#1A1A1A", linewidth=1.1, zorder=2)
        ax.plot([lo, lo], [i - .12, i + .12], color="#1A1A1A", linewidth=.7)
        ax.plot([hi, hi], [i - .12, i + .12], color="#1A1A1A", linewidth=.7)
        ax.plot(est, i, marker="s", color="#1A1A1A", markersize=4.5,
                linestyle="none", zorder=3)
        # Numeric column pinned inside the right edge: x in axes fraction,
        # y in data coordinates (blended transform), so it never leaves page.
        ax.text(.985, i, f"{est:+.2f} [{lo:+.2f}, {hi:+.2f}]",
                transform=ax.get_yaxis_transform(),
                ha="right", va="center", fontsize=5.4)

    a_label = method_style(method_a)[0]
    b_label = method_style(method_b)[0]
    ax.set_yticks(range(len(metrics)))
    ax.set_yticklabels([METRIC_PRINT[m] for m in metrics])
    ax.set_ylim(3.5, -.5)
    ax.set_xlim(-1.0, 1.0)
    ax.set_xticks([-1, -.5, 0, .5, 1])
    ax.set_xlabel(f"{a_label} minus {b_label}")
    panel_label(ax, "a")
    footnote(fig, "95% paired percentile bootstrap (2,000 draws); negative "
                  "risk/AURC favors " + a_label + ".", y=.002)
    return save_figure(fig, Path(out_dir) / "fig4_forest")


# --------------------------------------------------------------------------- #
# Figure 5: independent-support retention + abstention errors (H3)
# --------------------------------------------------------------------------- #
def fig5_retention(rows, out_dir):
    methods = list(dict.fromkeys(r["method"] for r in rows))
    fig, axes = plt.subplots(1, 2, figsize=(DOUBLE_COL, 2.65))
    fig.subplots_adjust(left=.13, right=.99, bottom=.22, top=.84, wspace=.22)

    # Panel a: independent-support micro retention.
    ax = axes[0]
    panel_label(ax, "a")
    ax.set_title("Independent-support retention", fontsize=8.5)
    path = "independent_support_retention.micro_rate"
    for i, method in enumerate(methods):
        label, color, emphasis = method_style(method)
        sub = slice_rows(rows, method=method, replica_condition="independent_support")
        est, lo, hi = cluster_bootstrap_ci(sub, path)
        xerr = [[est - lo], [hi - est]] if lo is not None else None
        ax.errorbar(est, i, xerr=xerr, color=color,
                    marker="o", markersize=5 if emphasis else 4.5,
                    capsize=2.5, elinewidth=.7, capthick=.7, label=label, zorder=3)
    ax.set_yticks(range(len(methods)))
    ax.set_yticklabels([method_style(m)[0] for m in methods])
    ax.set_ylim(-.5, len(methods) - .5)
    ax.set_xlim(0, 1.05)
    ax.set_xticks([0, .25, .5, .75, 1])
    ax.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.set_xlabel("Retained / gold independent groups")
    light_grid(ax, "x")

    # Panel b: abstention error rates.
    ax = axes[1]
    panel_label(ax, "b")
    ax.set_title("Selective-answer errors", fontsize=8.5)
    rate_paths = {
        "Inappropriate answer": "inappropriate_answer_rate",
        "Inappropriate refusal": "inappropriate_refusal_rate",
    }
    width = .32
    for k, (name, path) in enumerate(rate_paths.items()):
        for i, method in enumerate(methods):
            sub = slice_rows(rows, method=method, replica_condition="no_replica")
            est, lo, hi = cluster_bootstrap_ci(sub, path)
            offset = (k - .5) * width
            ax.barh(i + offset, est, height=width,
                    color="#1A1A1A" if k == 0 else "#9AA2A9",
                    edgecolor="white", linewidth=.5, zorder=3)
            # Skip zero-length labels so they do not pile up on the axis.
            if est is not None and est > .001:
                ax.text(est + .02, i + offset, f"{est:.0%}",
                        va="center", fontsize=6.3)
        ax.plot([], [], color="#1A1A1A" if k == 0 else "#9AA2A9", label=name)
    ax.set_yticks(range(len(methods)))
    # Method names are carried by panel a only.
    ax.set_yticklabels([""] * len(methods))
    ax.set_ylim(-.5, len(methods) - .5)
    ax.set_xlim(0, 1.0)
    ax.set_xticks([0, .25, .5, .75, 1])
    ax.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.set_xlabel("Rate over labelled questions")
    ax.legend(loc="upper right")
    light_grid(ax, "x")
    footnote(fig, "Natural-length context; retention uses reliable lineage panels; "
                  "95% cluster-bootstrap CI where applicable.")
    return save_figure(fig, Path(out_dir) / "fig5_retention")


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def build_all(input_path, out_dir, length_policy="natural_length"):
    apply_style(serif=True)
    all_rows = load_jsonl(input_path)
    rows = slice_rows(all_rows, length_policy=length_policy, status="ok")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    written = []
    # Figures 1, 3 use complete metadata; figure 2 spans all states.
    written += fig1_risk_coverage(slice_rows(rows, metadata_state="complete"), out_dir)
    written += fig2_metadata(slice_rows(rows, replica_condition="no_replica"), out_dir)
    written += fig3_dumbbell(slice_rows(rows, metadata_state="complete"), out_dir)
    forest_rows = slice_rows(rows, metadata_state="complete",
                             replica_condition="no_replica")
    # paired_bootstrap needs one comparable slice; converge to a single split.
    splits = list(dict.fromkeys(r["split"] for r in forest_rows))
    chosen_split = "test" if "test" in splits else splits[0]
    forest_rows = slice_rows(forest_rows, split=chosen_split)
    written += fig4_forest(forest_rows, out_dir)
    written += fig5_retention(rows, out_dir)
    return written


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="scored predictions JSONL")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--length-policy", default="natural_length")
    args = parser.parse_args()
    written = build_all(args.input, args.output_dir, args.length_policy)
    print(json.dumps({"figures_written": len(written),
                      "files": written}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
