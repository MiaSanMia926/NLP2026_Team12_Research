"""Alternative scientific chart geometries from saved, comparable C outputs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .metrics import load_jsonl, summarize
from .publication import CONDITION_FIELDS, PANEL_NAMES, configure, csv_file, export, figure_note, labels, style_for
from .publication import alignment as require_matplotlib_panel_alignment

PANELS = ("no_replica", "same_source_replica")
METRICS = ("coverage", "selective_risk", "em_all_rows", "aurc")
METRIC_NAMES = {"coverage": "Coverage", "selective_risk": "Selective risk", "em_all_rows": "Exact match", "aurc": "AURC"}


def save_chart(fig, axes, prefix):
    # Explicit gate for each standalone chart; the common exporter rechecks
    # final geometry before writing editable vectors and the 600-dpi preview.
    require_matplotlib_panel_alignment(fig, axes, prefix)
    return export(fig, axes, prefix)


def comparable_summary(rows):
    if not rows:
        raise ValueError("no selected records")
    for field in CONDITION_FIELDS:
        if len({r.get(field) for r in rows}) != 1:
            raise ValueError(f"mixed {field}; use --where to choose one comparable slice")
    if {r["replica_condition"] for r in rows} != set(PANELS):
        raise ValueError("select both original and same-source-replica conditions")
    methods = list(dict.fromkeys(r["method"] for r in rows))
    samples, stats, source = {}, {}, []
    expected_ids = None
    for method in methods:
        if len({r["config_hash"] for r in rows if r["method"] == method}) != 1:
            raise ValueError("multiple method configurations cannot be pooled")
        for panel in PANELS:
            sample = [r for r in rows if r["method"] == method and r["replica_condition"] == panel]
            ids = {r["base_question_id"] for r in sample}
            if len(ids) != len(sample) or expected_ids is not None and ids != expected_ids:
                raise ValueError("missing, duplicated or unmatched base questions")
            expected_ids = ids
            samples[method, panel] = sample
            m = summarize(sample)
            stats[method, panel] = m
            source.append({"method": method, "condition": panel, "planned_n": len(sample), "successful_n": m["n"],
                           "failed_n": m["failed_n"], "answered_n": m["answered_n"], "wrong_answered_n": m["wrong_answered_n"],
                           **{metric: m[metric] for metric in METRICS}})
    return methods, stats, source, len(expected_ids)


def method_label(method):
    return style_for(method)[0].replace("Conservative gate", "Gate")


def condition_legend(fig):
    from matplotlib.patches import Patch
    fig.legend(handles=[Patch(facecolor="white", edgecolor="#79838C", label="Original evidence"),
                        Patch(facecolor="#358697", edgecolor="#236C7A", label="Same-source replicas")],
               loc="lower center", bbox_to_anchor=(.53, .105), ncol=2, frameon=False, handlelength=1.6, columnspacing=2)


def grouped_bars(methods, stats, n, prefix, label):
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter
    fig, axes = plt.subplots(1, 2, figsize=(178/25.4, 90/25.4))
    fig.subplots_adjust(left=.09, right=.975, bottom=.32, top=.83, wspace=.29)
    for col, metric in enumerate(("coverage", "selective_risk")):
        ax = axes[col]
        labels(ax, chr(97+col), "Answer coverage" if col == 0 else "Selective error risk")
        for j, panel in enumerate(PANELS):
            for i, method in enumerate(methods):
                value = stats[method, panel][metric]
                xpos = i+(-.18 if j == 0 else .18)
                if value is None:
                    ax.text(xpos, .05, "NA", ha="center", fontsize=6)
                    continue
                ax.bar(xpos, value, width=.31, color="white" if j == 0 else "#358697",
                       edgecolor="#79838C" if j == 0 else "#236C7A", linewidth=.65, zorder=3)
                ax.annotate(f"{100*value:.0f}%", (xpos, value), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=6)
        ax.set(ylim=(0, 1.12), ylabel="Proportion" if col == 0 else "")
        names = [method_label(m).replace("Text dedup.", "Text\ndedup.").replace("Source count", "Source\ncount") for m in methods]
        ax.set_xticks(range(len(methods)), names)
        ax.set_yticks([0, .25, .5, .75, 1])
        ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
        ax.grid(axis="y", linewidth=.4, color="#E8EBED")
    condition_legend(fig)
    figure_note(fig, label, n, "Empirical proportions; zero bars explicitly labelled")
    audit = save_chart(fig, list(axes), prefix)
    plt.close(fig)
    return audit


def heatmaps(methods, stats, n, prefix, label):
    import matplotlib.pyplot as plt
    import numpy as np
    fig, axes = plt.subplots(1, 2, figsize=(178/25.4, 88/25.4))
    fig.subplots_adjust(left=.19, right=.975, bottom=.28, top=.83, wspace=.28)
    for col, metric in enumerate(("coverage", "selective_risk")):
        ax = axes[col]
        labels(ax, chr(97+col), "Answer coverage" if col == 0 else "Selective error risk")
        values = np.array([[stats[m, p][metric] if stats[m, p][metric] is not None else np.nan for p in PANELS] for m in methods])
        image = ax.imshow(np.ma.masked_invalid(values), cmap="Blues", vmin=0, vmax=1, aspect="auto", interpolation="nearest")
        for row in range(len(methods)):
            for c in range(2):
                value = values[row, c]
                ax.text(c, row, "NA" if np.isnan(value) else f"{100*value:.1f}%", ha="center", va="center",
                        color="white" if not np.isnan(value) and value >= .65 else "#233C50", fontsize=7)
        ax.set_xticks([0, 1], ["Original", "Replicas"])
        ax.set_yticks(range(len(methods)), [method_label(m) for m in methods] if col == 0 else [""]*len(methods))
        ax.set_xticks([-.5, .5, 1.5], minor=True)
        ax.set_yticks([i-.5 for i in range(len(methods)+1)], minor=True)
        ax.grid(which="minor", color="white", linewidth=1.5)
        ax.tick_params(which="both", length=0)
        for spine in ax.spines.values():
            spine.set_visible(False)
    figure_note(fig, label, n, "Darker = larger value; larger coverage and lower risk are preferable")
    audit = save_chart(fig, list(axes), prefix)
    plt.close(fig)
    return audit


def tradeoff_scatter(methods, stats, n, prefix, label):
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter
    fig, axes = plt.subplots(1, 2, figsize=(178/25.4, 86/25.4))
    fig.subplots_adjust(left=.09, right=.975, bottom=.26, top=.83, wspace=.28)
    for j, panel in enumerate(PANELS):
        ax = axes[j]
        labels(ax, chr(97+j), PANEL_NAMES[panel])
        coincident = {}
        undefined = []
        for method in methods:
            m = stats[method, panel]
            if m["coverage"] is None or m["selective_risk"] is None:
                undefined.append(method_label(method))
            else:
                coincident.setdefault((m["coverage"], m["selective_risk"]), []).append(method)
        for (coverage, risk), group in coincident.items():
            representative = next((m for m in group if m in {"SMOKE_gate", "B7"}), group[0])
            _, color, _ = style_for(representative)
            ax.scatter([coverage], [risk], s=30, color=color, marker="s" if representative in {"SMOKE_gate", "B7"} else "o", zorder=3, clip_on=False)
            ax.annotate("\n".join(method_label(m) for m in group), (coverage, risk), xytext=(7, 3), textcoords="offset points",
                        ha="left", va="bottom", fontsize=6.5, color=color, annotation_clip=False)
        if undefined:
            ax.text(0, -.24, "Undefined risk: "+", ".join(undefined), transform=ax.transAxes, fontsize=6)
        ax.set(xlim=(0, 1.14), ylim=(-.05, 1.05), xlabel="Answer coverage", ylabel="Selective error risk" if j == 0 else "")
        ax.set_xticks([0, .25, .5, .75, 1])
        ax.set_yticks([0, .25, .5, .75, 1])
        ax.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
        ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
        # Direct labels are the key to this sparse plot; omit crossing grid lines.
        ax.grid(False)
    figure_note(fig, label, n, "Each point is an actual decision policy; coincident points named together")
    audit = save_chart(fig, list(axes), prefix)
    plt.close(fig)
    return audit


def comparison_data(comparisons, rows):
    context = {k: rows[0][k] for k in CONDITION_FIELDS}
    selected = [c for c in comparisons if c.get("panel") == "condition" and c.get("status") == "ok"
                and all(c.get("slice", {}).get(k) == v for k, v in context.items())]
    identities = {(c["method_a"], c["method_b"]) for c in selected}
    if len(identities) != 1:
        raise ValueError("need exactly one saved paired method contrast for this slice")
    a, b = next(iter(identities))
    source = []
    for panel in PANELS:
        records = [c for c in selected if c["slice"]["replica_condition"] == panel]
        if len(records) != 1:
            raise ValueError("missing or duplicate saved comparison panel")
        for metric in METRICS:
            stats = [s for s in records[0]["statistics"] if s["metric"] == metric]
            if len(stats) != 1:
                raise ValueError("saved comparison lacks required statistic")
            s = stats[0]
            method_values = [summarize([r for r in rows if r["method"] == m and r["replica_condition"] == panel])[metric] for m in (a, b)]
            if s["observed_difference"] is not None and all(v is not None for v in method_values):
                if abs(s["observed_difference"]-(method_values[0]-method_values[1])) > 1e-12:
                    raise ValueError("saved CI belongs to different predictions")
            source.append({"condition": panel, "method_a": a, "method_b": b, "metric": metric,
                           "difference": s["observed_difference"], "ci_low": s["ci_95"][0] if s["ci_95"] else None,
                           "ci_high": s["ci_95"][1] if s["ci_95"] else None,
                           "paired_n": s["paired_base_questions"], "replicates": s["requested_replicates"],
                           "defined_replicates": s["defined_replicates"], "interval_warning": s["interval_warning"]})
    return a, b, source


def forest(comparison_rows, n, prefix, label):
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(178/25.4, 87/25.4))
    fig.subplots_adjust(left=.18, right=.975, bottom=.30, top=.83, wspace=.29)
    a, b = comparison_rows[0]["method_a"], comparison_rows[0]["method_b"]
    for j, panel in enumerate(PANELS):
        ax = axes[j]
        labels(ax, chr(97+j), PANEL_NAMES[panel])
        ax.axvline(0, linestyle="--", color="#BFC6CC", linewidth=.7, zorder=1)
        for i, metric in enumerate(METRICS):
            record = next(r for r in comparison_rows if r["condition"] == panel and r["metric"] == metric)
            estimate, low, high = record["difference"], record["ci_low"], record["ci_high"]
            if estimate is None or low is None or high is None:
                ax.text(-.95, i, "Unavailable", fontsize=6, va="center")
            else:
                ax.plot([low, high], [i, i], color="#358697", linewidth=1.3, zorder=2)
                ax.plot([low, low], [i-.07, i+.07], color="#358697", linewidth=.8)
                ax.plot([high, high], [i-.07, i+.07], color="#358697", linewidth=.8)
                ax.plot(estimate, i, marker="s", color="#1D5967", markersize=4, linestyle="none", zorder=3)
        ax.set(xlim=(-1.05, 1.05), ylim=(3.5, -.5), xlabel=method_label(a)+" minus "+method_label(b))
        ax.set_yticks(range(4), [METRIC_NAMES[m] for m in METRICS] if j == 0 else [""]*4)
        ax.set_xticks([-1, -.5, 0, .5, 1])
        ax.tick_params(axis="y", length=0)
    figure_note(fig, label, n, "95% paired bootstrap CI; risk/AURC: negative favours first method")
    audit = save_chart(fig, list(axes), prefix)
    plt.close(fig)
    return audit


def make_charts(predictions, output, comparisons=None, kind="all", label="software-selfcheck", filters=None):
    configure("journal")
    import matplotlib as mpl
    mpl.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
                         "svg.fonttype": "none", "pdf.fonttype": 42, "savefig.dpi": 600})
    rows = load_jsonl(predictions)
    before = len(rows)
    for expression in filters or []:
        key, value = expression.split("=", 1)
        rows = [r for r in rows if str(r.get(key)) == value]
    methods, stats, source, n = comparable_summary(rows)
    kinds = ["bars", "heatmap", "scatter", "forest"] if kind == "all" else [kind]
    if output.exists() and any(output.iterdir()):
        raise ValueError("output directory must be new or empty")
    paired = None
    if "forest" in kinds:
        if comparisons is None:
            raise ValueError("forest/all needs saved --comparisons; intervals are not invented")
        _, _, paired = comparison_data(json.loads(comparisons.read_text(encoding="utf-8")), rows)
    output.mkdir(parents=True, exist_ok=True)
    index = []
    renderers = {"bars": grouped_bars, "heatmap": heatmaps, "scatter": tradeoff_scatter}
    for chart in kinds:
        prefix = output/chart
        if chart == "forest":
            audit = forest(paired, n, prefix, label)
            csv_file(output/"forest.source.csv", paired)
        else:
            audit = renderers[chart](methods, stats, n, prefix, label)
            csv_file(output/(chart+".source.csv"), source)
        index.append({"kind": chart, "pdf": chart+".pdf", "svg": chart+".svg", "png": chart+".png", "qa": audit})
    provenance = {"input_sha256": hashlib.sha256(predictions.read_bytes()).hexdigest(), "rows_before": before, "rows_plotted": len(rows),
                  "filters": filters or [], "label": label, "charts": index,
                  "comparisons_sha256": hashlib.sha256(comparisons.read_bytes()).hexdigest() if comparisons else None,
                  "drawing_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  "transformations": "C metrics reused without rescaling; no sampling, smoothing or jitter; saved CI reused only after estimate check"}
    (output/"chart_index.json").write_text(json.dumps(provenance, indent=2)+"\n", encoding="utf-8")
    return provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--comparisons", type=Path)
    parser.add_argument("--kind", choices=["all", "bars", "heatmap", "scatter", "forest"], default="all")
    parser.add_argument("--where", action="append", default=[])
    parser.add_argument("--label", choices=["software-selfcheck", "pilot", "frozen-test"], default="software-selfcheck")
    args = parser.parse_args()
    result = make_charts(args.input, args.output_dir, args.comparisons, args.kind, args.label, args.where)
    print(json.dumps({"chart_count": len(result["charts"]), "rows": result["rows_plotted"], "output": str(args.output_dir)}))


if __name__ == "__main__":
    main()
