"""
Side-by-side comparison of four candidate palettes on the same radar chart,
so the preferred color scheme can be picked visually before re-rendering.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _p in (str(_HERE), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from evaluation.metrics import load_jsonl, summarize  # noqa: E402
from evaluation.bootstrap import get_path  # noqa: E402
from modern_style import apply_style  # noqa: E402
from acl_style import DOUBLE_COL, save_figure  # noqa: E402
from paper_figures import slice_rows  # noqa: E402

AXES_DEF = [
    ("Coverage", "coverage", False),
    ("1 - Risk", "selective_risk", True),
    ("Exact match", "em_all_rows", False),
    ("Retention", "independent_support_retention.micro_rate", False),
    ("1 - AURC", "aurc", True),
]

# Four deliberately different, print-ready schemes.
PALETTES = {
    "A Morandi (muted)": ["#7A8CA5", "#C08497", "#8BA888", "#B57169"],
    "B Nature (crisp)":  ["#3B4992", "#EE0000", "#0099B5", "#F39B7F"],
    "C Cool tech":       ["#2E5EAA", "#17A2B8", "#0F9488", "#6F58A6"],
    "D Warm earth":      ["#B23A48", "#DB7C26", "#6B8E23", "#8C624A"],
}


def profile(rows, method):
    stats = summarize(slice_rows(rows, method=method))
    vals = []
    for _, path, invert in AXES_DEF:
        value = get_path(stats, path)
        value = 0 if value is None else value
        vals.append(1 - value if invert else value)
    return vals


def main():
    input_path = Path(r"C:\Users\czh99\Desktop\NLP\artifacts\selfcheck"
                      r"\ab_to_c_20261031\scored_predictions.jsonl")
    out_dir = _HERE / "figures"
    apply_style()
    all_rows = slice_rows(load_jsonl(str(input_path)),
                          length_policy="natural_length", status="ok",
                          metadata_state="complete")
    methods = list(dict.fromkeys(r["method"] for r in all_rows))
    profiles = {m: profile(all_rows, m) for m in methods}

    n = len(AXES_DEF)
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False).tolist()
    angles += angles[:1]

    fig = plt.figure(figsize=(DOUBLE_COL, 5.2))
    fig.subplots_adjust(left=.03, right=.97, bottom=.08, top=.93,
                        hspace=.35, wspace=.25)
    for k, (name, colors) in enumerate(PALETTES.items()):
        ax = fig.add_subplot(2, 2, k + 1, polar=True)
        ax.set_title(name, fontsize=9, pad=8)
        for method, color in zip(methods, colors):
            vals = profiles[method] + profiles[method][:1]
            ax.plot(angles, vals, color=color, linewidth=1.3, marker="o",
                    markersize=3.5)
            ax.fill(angles, vals, color=color, alpha=.15)
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels([a[0] for a in AXES_DEF], fontsize=6)
        ax.set_ylim(0, 1)
        ax.set_yticks([.5, 1])
        ax.set_yticklabels([".5", "1"], fontsize=5.5, color="#999999")
        ax.grid(color="#E4E8EC", linewidth=.5)

    save_figure(fig, out_dir / "palette_compare")
    print("written", out_dir / "palette_compare.png")


if __name__ == "__main__":
    main()
