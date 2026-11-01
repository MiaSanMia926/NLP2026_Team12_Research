"""Publication-scale, overlap-aware empirical figures; never smooth or move data."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from .metrics import GROUP_FIELDS, load_jsonl, risk_curve, summarize

CONDITION_FIELDS = tuple(k for k in GROUP_FIELDS if k not in {"method", "config_hash", "condition_id", "replica_condition"})
METHOD_STYLE = {
    "SMOKE_vote": ("Vote", "#707782", "--"),
    "SMOKE_exact": ("Text dedup.", "#B08B55", ":"),
    "SMOKE_source": ("Source count", "#777AA5", "-."),
    "SMOKE_gate": ("Conservative gate", "#167D8D", "-"),
    "B5": ("B5", "#707782", "--"), "B7": ("B7", "#167D8D", "-"),
}
PANEL_NAMES = {"no_replica": "Original evidence", "same_source_replica": "Same-source replicas",
               "independent_support": "Independent support", "complementary_support": "Complementary support"}
PANEL_ORDER = list(PANEL_NAMES)
STYLE_PRESETS = {
    "journal": {"label": "Journal teal", "colors": ("#707782", "#B08B55", "#777AA5", "#167D8D"),
                "background": "white", "grid": True, "grid_color": "#E9EAEC", "line_scale": 1.0},
    "minimal": {"label": "Minimal blue", "colors": ("#89929B", "#86A0B8", "#586D83", "#234F78"),
                "background": "white", "grid": False, "grid_color": "#EDF0F3", "line_scale": .9},
    "warm": {"label": "Warm muted", "colors": ("#888078", "#B59569", "#968AAB", "#A35B65"),
             "background": "#FAF8F4", "grid": True, "grid_color": "#E7E1D9", "line_scale": 1.1},
    "monochrome": {"label": "Monochrome print", "colors": ("#707070", "#969696", "#494949", "#171717"),
                   "background": "white", "grid": False, "grid_color": "#ECECEC", "line_scale": 1.0},
}
_ACTIVE_STYLE = "journal"
METHOD_ROLES = {"SMOKE_vote": 0, "SMOKE_exact": 1, "SMOKE_source": 2, "SMOKE_gate": 3, "B5": 0, "B7": 3}


def style_for(method, style=None):
    preset = STYLE_PRESETS[_ACTIVE_STYLE if style is None else style]
    if method in METHOD_STYLE:
        name, _, line = METHOD_STYLE[method]
        return name, preset["colors"][METHOD_ROLES[method]], line
    colors = preset["colors"]
    index = int(hashlib.sha256(method.encode()).hexdigest()[:8], 16)
    return method, colors[index % len(colors)], ("-", "--", ":", "-.")[index % 4]


def curve_key(curve):
    # Canonical right-endpoint step geometry: redundant horizontal vertices do
    # not change the function. Keep the original threshold grid in source CSV.
    segments = []
    for point in curve["points"][1:]:
        if segments and segments[-1][1] == point["risk"]:
            segments[-1] = (point["coverage"], point["risk"])
        else:
            segments.append((point["coverage"], point["risk"]))
    return tuple(segments)


def overlap_groups(group):
    grouped = defaultdict(list)
    for context, curve in group:
        if curve["available"]:
            grouped[curve_key(curve)].append((context, curve))
    return list(grouped.values())


def configure(style="journal"):
    global _ACTIVE_STYLE
    if style not in STYLE_PRESETS:
        raise ValueError("unknown publication style")
    _ACTIVE_STYLE = style
    import matplotlib as mpl
    mpl.use("Agg")
    mpl.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
                         "font.size": 7, "axes.titlesize": 8, "axes.labelsize": 7,
                         "xtick.labelsize": 6.5, "ytick.labelsize": 6.5, "legend.fontsize": 6.5,
                         "axes.spines.right": False, "axes.spines.top": False, "axes.linewidth": .65,
                         "xtick.major.width": .6, "ytick.major.width": .6,
                         "xtick.major.size": 2.5, "ytick.major.size": 2.5,
                         "pdf.fonttype": 42, "svg.fonttype": "none", "savefig.facecolor": "white",
                         "axes.facecolor": STYLE_PRESETS[style]["background"], "figure.facecolor": "white"})


def grouped_panels(curves):
    bundles = defaultdict(lambda: defaultdict(list))
    for context, curve in curves:
        key = tuple(context[k] for k in CONDITION_FIELDS)
        bundles[key][context["replica_condition"]].append((context, curve))
    return bundles


def labels(ax, letter, title):
    ax.annotate(letter, (0, 1), xycoords="axes fraction", xytext=(-22, 12), textcoords="offset points",
                ha="left", va="bottom", fontsize=9, fontweight="bold", annotation_clip=False)
    ax.set_title(title, loc="left", pad=10)
    ax.set_axisbelow(True)


def alignment(fig, axes, prefix):
    fig.canvas.draw()
    qa_dir = os.environ.get("NATURE_FIGURE_QA_DIR")
    if qa_dir:
        spec = importlib.util.spec_from_file_location("figure_alignment_audit", Path(qa_dir)/"audit_panel_alignment.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        module.require_matplotlib_panel_alignment(fig, axes=axes, panel_ids=list("abcdefghijklmnopqrstuvwxyz"[:len(axes)]),
                                                  json_out=str(prefix)+".alignment.json", strict=True,
                                                  tolerance_pt=1.5, gutter_tolerance_pt=1.5,
                                                  require_panel_labels=True)
    else:
        # Self-contained regular-grid gate for machines without the optional figure skill.
        boxes = [[v*fig.get_size_inches()[j % 2]*72 for j, v in enumerate(ax.get_position().bounds)] for ax in axes]
        deviations = {"bottom": max(b[1] for b in boxes)-min(b[1] for b in boxes),
                      "width": max(b[2] for b in boxes)-min(b[2] for b in boxes),
                      "height": max(b[3] for b in boxes)-min(b[3] for b in boxes)}
        if any(value > 1.5 for value in deviations.values()):
            raise ValueError("rendered regular-grid panel misalignment")
        Path(str(prefix)+".alignment.json").write_text(json.dumps({"verdict": "PASS" if len(axes)>1 else "NOT APPLICABLE",
                                                                 "tolerance_pt": 1.5, "bbox_xywh_pt": boxes,
                                                                 "deviations_pt": deviations}, indent=2), encoding="utf-8")


def export(fig, axes, prefix):
    # Never use bbox_inches='tight': preserve the declared physical page size.
    alignment(fig, axes, prefix)
    for suffix in ("pdf", "svg", "png"):
        fig.savefig(str(prefix)+"."+suffix, dpi=600)
    qa_dir = os.environ.get("NATURE_FIGURE_QA_DIR")
    audit = {"collision": "not_run", "pdf_text": "not_run"}
    if qa_dir:
        commands = [
            ("pdf_text", [sys.executable, str(Path(qa_dir)/"audit_pdf_text.py"), str(prefix)+".pdf", "--min-pt", "5", "--json"]),
            ("collision", [sys.executable, str(Path(qa_dir)/"audit_figure_collisions.py"), str(prefix)+".pdf", "--json-out", str(prefix)+".collision-audit.json", "--overlay-pdf", str(prefix)+".collision-audit.pdf"]),
        ]
        for name, command in commands:
            run = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
            Path(str(prefix)+f".{name}.txt").write_text(run.stdout+run.stderr, encoding="utf-8")
            if run.returncode:
                raise ValueError(f"{name} QA failed for {prefix.name}; inspect saved diagnostic")
            audit[name] = "completed_review_report"
    return audit


def figure_note(fig, label, n, suffix):
    title = {"software-selfcheck": "Synthetic offline validation", "pilot": "Exploratory pilot", "frozen-test": "Frozen test"}.get(label, label)
    fig.text(.09, .035, f"{title}  |  n = {n} base questions  |  {suffix}", fontsize=6, color="#555B63")


def draw_rc(panels, prefix, label):
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter
    ordered = sorted(panels, key=lambda x: PANEL_ORDER.index(x) if x in PANEL_ORDER else 99)
    # Two panels per page maximizes final-size legibility; all panels are retained in further pages.
    page = {key: panels[key] for key in ordered}
    fig, axes = plt.subplots(1, len(page), figsize=(178/25.4, 89/25.4), squeeze=False)
    axes = list(axes[0])
    fig.subplots_adjust(left=.09, right=.975, bottom=.34, top=.83, wspace=.28)
    overlap_records, source = [], []
    n_values = set()
    for i, (panel, group) in enumerate(page.items()):
        ax = axes[i]
        labels(ax, chr(97+i), PANEL_NAMES.get(panel, panel))
        for equal_curves in overlap_groups(group):
            representative = next((r for r in equal_curves if r[0]["method"] in {"SMOKE_gate", "B7"}), equal_curves[0])
            context, curve = representative
            _, color, line = style_for(context["method"])
            names = [style_for(r[0]["method"])[0] for r in equal_curves]
            display = " / ".join(names)
            # Keep legends compact without omitting any equal-curve member.
            display = display.replace("Conservative gate", "Gate")
            points = curve["points"][1:]
            n_values.add(curve["denominator"])
            ax.step([0.0]+[p["coverage"] for p in points], [points[0]["risk"]]+[p["risk"] for p in points],
                    where="pre", color=color, linestyle=line,
                    linewidth=(1.6 if len(equal_curves)>1 else 1.2)*STYLE_PRESETS[_ACTIVE_STYLE]["line_scale"],
                    label=display, clip_on=False)
            overlap_records.append({"panel": panel, "methods": [r[0]["method"] for r in equal_curves],
                                    "equal_step_geometry": True, "threshold_vertices_preserved_in_source": True})
        unavailable = [style_for(c["method"])[0] for c, curve in group if not curve["available"]]
        if unavailable:
            ax.text(0, -.55, "No ranking: "+", ".join(unavailable), transform=ax.transAxes, fontsize=6, va="top")
        for context, curve in group:
            for point in curve["points"]:
                source.append(dict(context, **point))
        mode = group[0][1]["mode"]
        ax.set(xlim=(0, 1), ylim=(0, 1), xlabel="Candidate coverage" if mode == "candidate" else "Answered coverage",
               ylabel="Error risk" if i == 0 else "")
        ax.set_xticks([0, .25, .5, .75, 1])
        ax.set_yticks([0, .25, .5, .75, 1])
        ax.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
        ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
        if STYLE_PRESETS[_ACTIVE_STYLE]["grid"]:
            ax.grid(axis="y", color=STYLE_PRESETS[_ACTIVE_STYLE]["grid_color"], linewidth=.45)
        ax.legend(loc="upper left", bbox_to_anchor=(-.01, -.29), borderaxespad=0, frameon=False,
                  handlelength=2.6, labelspacing=.5)
    mode_note = "empirical steps" if mode == "candidate" else "partial empirical curves"
    figure_note(fig, label, "/".join(map(str, sorted(n_values))) or "unavailable", "Identical step functions labelled together; "+mode_note)
    audit = export(fig, axes, prefix)
    plt.close(fig)
    return source, overlap_records, audit


def draw_operating(panels, rows, prefix, label):
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.ticker import PercentFormatter
    wanted = {"no_replica", "same_source_replica"}
    selected = [r for r in rows if r["replica_condition"] in wanted]
    methods = list(dict.fromkeys(r["method"] for r in selected))
    if not selected or set(panels) & wanted != wanted:
        return None
    fig, axes = plt.subplots(1, 2, figsize=(178/25.4, 83/25.4))
    fig.subplots_adjust(left=.21, right=.975, bottom=.29, top=.83, wspace=.27)
    source = []
    n_values = set()
    for col, metric in enumerate(("coverage", "selective_risk")):
        ax = axes[col]
        labels(ax, chr(97+col), "Answering coverage" if col == 0 else "Selective error risk")
        for i, method in enumerate(methods):
            estimates = []
            for panel in ("no_replica", "same_source_replica"):
                sample = [r for r in selected if r["method"] == method and r["replica_condition"] == panel]
                stats = summarize(sample)
                n_values.add(len(sample))
                estimates.append(stats[metric])
                if col == 0:
                    source.append({"method": method, "panel": panel, "n": stats["n"], "answered_n": stats["answered_n"],
                                   "coverage": stats["coverage"], "selective_risk": stats["selective_risk"]})
            _, color, _ = style_for(method)
            if all(v is not None for v in estimates):
                ax.plot(estimates, [i, i], color=color, linewidth=.8, zorder=1)
            for j, value in enumerate(estimates):
                if value is None:
                    ax.text(.03, i, "Undefined", color=color, va="center", fontsize=6)
                else:
                    # Nested circle/square remain identifiable when estimates coincide.
                    ax.plot(value, i, marker="o" if j == 0 else "s", markersize=6 if j == 0 else 3.2,
                            markerfacecolor="white" if j == 0 else color, markeredgecolor=color,
                            markeredgewidth=.9, linestyle="none", clip_on=False, zorder=2+j)
        ax.set(xlim=(-.04, 1.04), ylim=(len(methods)-.5, -.5), xlabel="Proportion of successful predictions" if col == 0 else "Proportion of answered predictions")
        ax.set_yticks(range(len(methods)), [style_for(m)[0] for m in methods] if col == 0 else [""]*len(methods))
        ax.tick_params(axis="y", length=0)
        ax.set_xticks([0, .25, .5, .75, 1])
        ax.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
        if STYLE_PRESETS[_ACTIVE_STYLE]["grid"]:
            ax.grid(axis="x", color=STYLE_PRESETS[_ACTIVE_STYLE]["grid_color"], linewidth=.45)
    handles = [Line2D([], [], marker="o", markersize=6, markerfacecolor="white", color="#444A52", linestyle="none", label="Original evidence"),
               Line2D([], [], marker="s", markersize=3.2, color="#444A52", linestyle="none", label="Same-source replicas")]
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(.56, .105), ncol=2, frameon=False, handletextpad=.65, columnspacing=2)
    figure_note(fig, label, "/".join(map(str, sorted(n_values))), "Paired evidence conditions; empirical proportions")
    audit = export(fig, list(axes), prefix)
    plt.close(fig)
    return source, audit


def csv_file(path, rows):
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
        writer.writeheader()
        writer.writerows(rows)


def render_report_figures(output, curves, label, rows=None, style="journal"):
    configure(style)
    index = []
    for key, panels in grouped_panels(curves).items():
        context = dict(zip(CONDITION_FIELDS, key))
        name = "rc_"+hashlib.sha256(repr(key).encode()).hexdigest()[:12]
        ordered = sorted(panels, key=lambda p: PANEL_ORDER.index(p) if p in PANEL_ORDER else 99)
        for page_start in range(0, len(ordered), 2):
            page_panels = {p: panels[p] for p in ordered[page_start:page_start+2]}
            prefix = output/(name+(f"_{page_start//2+1}" if len(ordered)>2 else ""))
            source, overlaps, audit = draw_rc(page_panels, prefix, label)
            csv_file(Path(str(prefix)+".source.csv"), source)
            curve_mode = next(iter(page_panels.values()))[0][1]["mode"]
            index.append({"kind": curve_mode+"_risk_coverage", "slice": context, "panels": list(page_panels),
                          "pdf": prefix.name+".pdf", "svg": prefix.name+".svg", "png": prefix.name+".png",
                          "overlap_groups": overlaps, "style": style, "qa": audit})
        if rows is not None:
            subset = [r for r in rows if all(r.get(k) == v for k, v in context.items())]
            prefix = output/(name+"_operating")
            operating = draw_operating(panels, subset, prefix, label)
            if operating:
                source, audit = operating
                csv_file(Path(str(prefix)+".source.csv"), source)
                index.append({"kind": "operating_points", "slice": context,
                              "pdf": prefix.name+".pdf", "svg": prefix.name+".svg", "png": prefix.name+".png", "style": style, "qa": audit})
    (output/"figure_index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    return f"generated_{len(index)}_publication_figures"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--where", action="append", default=[])
    parser.add_argument("--label", choices=["software-selfcheck", "pilot", "frozen-test"], default="software-selfcheck")
    parser.add_argument("--style", choices=list(STYLE_PRESETS), default="journal")
    parser.add_argument("--all-styles", action="store_true", help="export each style to a separate subdirectory")
    args = parser.parse_args()
    rows = load_jsonl(args.input)
    before = len(rows)
    for expression in args.where:
        k, v = expression.split("=", 1)
        rows = [r for r in rows if str(r.get(k)) == v]
    if not rows or args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise ValueError("need selected data and a new/empty output directory")
    grouped = defaultdict(list)
    for row in rows:
        grouped[tuple(row[k] for k in GROUP_FIELDS)].append(row)
    curves = [(dict(zip(GROUP_FIELDS, key)), risk_curve(group)) for key, group in grouped.items()]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.all_styles:
        statuses = {}
        for style in STYLE_PRESETS:
            folder = args.output_dir/style
            folder.mkdir()
            statuses[style] = render_report_figures(folder, curves, args.label, rows, style=style)
        status = statuses
    else:
        status = render_report_figures(args.output_dir, curves, args.label, rows, style=args.style)
    record = {"input_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(), "rows_before": before,
              "rows_plotted": len(rows), "filters": args.where, "status": status,
              "styles": list(STYLE_PRESETS) if args.all_styles else [args.style],
              "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "data_transforms": "none; identical step functions grouped for display only; all threshold vertices retained in source; no smoothing/jitter",
              "uncertainty": "empirical sample curves/proportions, not model-seed means; paired bootstrap CI remains in comparisons table"}
    (args.output_dir/"plot_provenance.json").write_text(json.dumps(record, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(record))


if __name__ == "__main__":
    main()
