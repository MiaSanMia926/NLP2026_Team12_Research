"""
Modern full-color visual system for Track C.

This is a stylistic counterpart to acl_style: it keeps the same ACL page
geometry, serif body type and real-bootstrap discipline, but uses the Nature
(NPG) palette chosen from the comparison sheet -- crisp blue, red, cyan and
orange, with the proposed method emphasized in the strongest red.

Nothing here invents uncertainty: every band or interval is still supplied by
the reviewed bootstrap helpers on real predictions.
"""
from __future__ import annotations

import hashlib

import matplotlib as mpl
from matplotlib.colors import LinearSegmentedColormap

# Reuse the fixed ACL geometry and generic render/annotation utilities.
from acl_style import (SINGLE_COL, DOUBLE_COL, MM, GOLDEN,  # noqa: F401
                       save_figure, panel_label, footnote, light_grid)

# --------------------------------------------------------------------------- #
# 1. Nature / NPG method palette. The proposed method uses the strongest red.
# --------------------------------------------------------------------------- #
BLUE = "#3B4992"
RED = "#EE0000"
CYAN = "#0099B5"
ORANGE = "#F39B7F"
# NPG has no separate green; cyan acts as the positive channel. The remaining
# names are kept so the figure module can still label neutral/extra series.
GREEN = "#0099B5"
TEAL = "#A9C2D9"
PURPLE = "#7E6AAB"
GRID = "#E4E8EC"
RULE = "#9AA3AB"

# Soft, lighter variants for fills / secondary series.
SOFT = {
    BLUE: "#9AA3D0", RED: "#F5A0A0", CYAN: "#8FCBD6",
    ORANGE: "#F9C9B6", GREEN: "#8FCBD6", TEAL: "#D4E0EC",
    PURPLE: "#C2B6DA",
}

METHOD_STYLE = {
    "SMOKE_vote":  ("Vote", BLUE, False),
    "SMOKE_exact": ("Text dedup.", ORANGE, False),
    "SMOKE_source": ("Source count", CYAN, False),
    "SMOKE_gate":  ("Gate", RED, True),
    "B5": ("B5", BLUE, False),
    "B7": ("B7", RED, True),
}
_FALLBACK = (BLUE, ORANGE, CYAN, PURPLE, TEAL)

# Condition -> marker + line style (grayscale channel), same vocabulary as the
# core style so the two systems stay interpretable.
CONDITION_STYLE = {
    "no_replica":              ("o", "-",  "Original evidence"),
    "same_source_replica":     ("s", "--", "Same-source replicas"),
    "independent_support":     ("^", ":",  "Independent support"),
    "complementary_support":   ("D", "-.", "Complementary support"),
}
_FALLBACK_MARKERS = ("o", "s", "^", "D", "v")
_FALLBACK_LINES = ("-", "--", ":", "-.")

METADATA_LABELS = {"complete": "Complete", "missing": "Missing",
                   "incorrect": "Incorrect"}

# Fill transparency used throughout: strong enough to read, soft enough to layer.
FILL_ALPHA = .18
BAND_ALPHA = .22


def _stable_index(token: str) -> int:
    return int(hashlib.sha256(token.encode("utf-8")).hexdigest()[:8], 16)


def method_style(method: str):
    if method in METHOD_STYLE:
        return METHOD_STYLE[method]
    idx = _stable_index(method)
    return method, _FALLBACK[idx % len(_FALLBACK)], False


def condition_style(condition: str):
    if condition in CONDITION_STYLE:
        marker, line, label = CONDITION_STYLE[condition]
        return marker, line, True, label
    idx = _stable_index(condition)
    return (_FALLBACK_MARKERS[idx % len(_FALLBACK_MARKERS)],
            _FALLBACK_LINES[idx % len(_FALLBACK_LINES)], True, condition)


# --------------------------------------------------------------------------- #
# 2. Heat-map colormaps built from the NPG red/cyan.
# --------------------------------------------------------------------------- #
def diverging_cmap():
    # Red at the low end, cyan at the high end; the figure reverses it for risk
    # so low risk reads cyan and high risk reads red.
    return LinearSegmentedColormap.from_list(
        "npg_div", ["#EE0000", "#F7C9C0", "#F4F1EC", "#9FD0D8", "#0099B5"])


def sequential_cmap():
    # Soft single-hue blue ramp for one-directional quantities.
    return LinearSegmentedColormap.from_list(
        "npg_blue", ["#F2F4FA", "#9AA3D0", "#3B4992"])


# --------------------------------------------------------------------------- #
# 3. Global rcParams: modern, slightly fuller, still print-ready.
# --------------------------------------------------------------------------- #
def apply_style(serif: bool = True) -> None:
    mpl.use("Agg")
    family = "serif" if serif else "sans-serif"
    serif_fonts = ["Times New Roman", "STIXGeneral", "DejaVu Serif"]
    sans_fonts = ["Arial", "Helvetica", "DejaVu Sans"]
    mpl.rcParams.update({
        "font.family": family,
        "font.serif": serif_fonts,
        "font.sans-serif": sans_fonts,
        "mathtext.fontset": "stix" if serif else "dejavusans",
        "font.size": 8.5,
        "axes.titlesize": 9.5,
        "axes.labelsize": 8.5,
        "xtick.labelsize": 7.8,
        "ytick.labelsize": 7.8,
        "legend.fontsize": 7.8,
        "axes.facecolor": "white",
        "figure.facecolor": "white",
        "axes.linewidth": .8,
        "axes.spines.top": True,
        "axes.spines.right": True,
        "xtick.major.width": .7,
        "ytick.major.width": .7,
        "xtick.major.size": 3.2,
        "ytick.major.size": 3.2,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "svg.fonttype": "none",
        "savefig.facecolor": "white",
        "savefig.dpi": 600,
        "figure.dpi": 150,
        "lines.linewidth": 1.6,
        "lines.markersize": 6,
        "legend.frameon": True,
        "legend.framealpha": .9,
        "legend.edgecolor": "#D0D5DA",
    })
