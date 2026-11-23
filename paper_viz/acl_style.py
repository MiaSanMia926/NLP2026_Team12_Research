"""
ACL / CCF-style visual system for the Track-C selective-answering project.

Design goals
------------
1. One physical page geometry: figures are sized to the ACL A4 column *before*
   rendering, so every glyph is already at its final printed size.
2. Two orthogonal visual channels, never mixed:
      method    -> color          (the proposed method is emphasized in black)
      condition -> marker + line style (so the plot survives grayscale print)
3. Serif type that matches the paper body (Times New Roman), editable text in
   the vector PDF (TrueType, fonttype 42), plus a 600-dpi raster preview.
4. Color-blind-safe Okabe-Ito colors and zero chart junk (no 3D, shadows,
   backgrounds or invented smoothing).

Nothing here invents uncertainty: confidence intervals are always supplied by
evaluation.bootstrap on real predictions.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import matplotlib as mpl

# --------------------------------------------------------------------------- #
# 1. Physical page geometry (ACL A4 layout).
#    Column width 7.7 cm, column gap 0.6 cm. 1 inch = 25.4 mm.
# --------------------------------------------------------------------------- #
MM = 1 / 25.4
SINGLE_COL = 77 * MM                       # 3.03 in, one ACL column
DOUBLE_COL = (77 * 2 + 6) * MM             # 6.30 in, full text width
GOLDEN = 1.618                             # pleasant default aspect ratio

# --------------------------------------------------------------------------- #
# 2. Color-blind-safe palette (Okabe-Ito). The proposed method is black so it
#    dominates in both color and grayscale; baselines get distinct hues whose
#    gray levels also differ.
# --------------------------------------------------------------------------- #
BLACK = "#1A1A1A"
BLUE = "#0072B2"
VERMILLION = "#D55E00"
GREEN = "#009E73"
SKY = "#56B4E9"
PURPLE = "#CC79A7"
GRID = "#D9DDE1"
RULE = "#8A9299"

# Method -> (display name, color, emphasis). Unknown methods fall back safely.
METHOD_STYLE = {
    "SMOKE_vote":  ("Vote",        BLUE,      False),
    "SMOKE_exact": ("Text dedup.", VERMILLION, False),
    "SMOKE_source": ("Source count", GREEN,   False),
    "SMOKE_gate":  ("Gate",        BLACK,     True),
    # Forward-compatible with the planned B5/B7 identifiers.
    "B5": ("B5", BLUE, False),
    "B7": ("B7", BLACK, True),
}
_FALLBACK_COLORS = (BLUE, VERMILLION, GREEN, PURPLE, SKY)

# Condition -> (marker, line style, filled marker?) -- the grayscale channel.
CONDITION_STYLE = {
    "no_replica":              ("o", "-",  True,  "Original evidence"),
    "same_source_replica":     ("s", "--", False, "Same-source replicas"),
    "independent_support":     ("^", ":",  True,  "Independent support"),
    "complementary_support":   ("D", "-.", False, "Complementary support"),
}
_FALLBACK_MARKERS = ("o", "s", "^", "D", "v")
_FALLBACK_LINES = ("-", "--", ":", "-.")

# Human-readable metadata labels (H2).
METADATA_LABELS = {
    "complete": "Complete",
    "missing": "Missing",
    "incorrect": "Incorrect",
}


def _stable_index(token: str) -> int:
    return int(hashlib.sha256(token.encode("utf-8")).hexdigest()[:8], 16)


def method_style(method: str):
    """Return (label, color, emphasized) for a method, with safe fallback."""
    if method in METHOD_STYLE:
        return METHOD_STYLE[method]
    idx = _stable_index(method)
    return method, _FALLBACK_COLORS[idx % len(_FALLBACK_COLORS)], False


def condition_style(condition: str):
    """Return (marker, linestyle, filled, label) for an evidence condition."""
    if condition in CONDITION_STYLE:
        return CONDITION_STYLE[condition]
    idx = _stable_index(condition)
    return (_FALLBACK_MARKERS[idx % len(_FALLBACK_MARKERS)],
            _FALLBACK_LINES[idx % len(_FALLBACK_LINES)],
            True, condition)


# --------------------------------------------------------------------------- #
# 3. Global rcParams. Call once at the start of a rendering run.
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
        # Final-size point sizes; nothing is smaller than ~7 pt when printed.
        "font.size": 8,
        "axes.titlesize": 8.5,
        "axes.labelsize": 8,
        "xtick.labelsize": 7.5,
        "ytick.labelsize": 7.5,
        "legend.fontsize": 7.5,
        # Classic, thin full frame -- the conventional look of CCF/ACL papers.
        "axes.facecolor": "white",
        "figure.facecolor": "white",
        "axes.linewidth": 0.6,
        "axes.spines.top": True,
        "axes.spines.right": True,
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
        "xtick.minor.width": 0.5,
        "ytick.minor.width": 0.5,
        "xtick.major.size": 3.0,
        "ytick.major.size": 3.0,
        "xtick.direction": "out",
        "ytick.direction": "out",
        # Editable text inside vectors, white background, fixed physical size.
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "svg.fonttype": "none",
        "savefig.facecolor": "white",
        "savefig.dpi": 600,
        "figure.dpi": 150,
        "lines.linewidth": 1.1,
        "lines.markersize": 5,
        "legend.frameon": False,
    })


# --------------------------------------------------------------------------- #
# 4. Shared annotations.
# --------------------------------------------------------------------------- #
def panel_label(ax, letter: str) -> None:
    """Bold (a), (b), ... label at the top-left, outside the axes box."""
    ax.annotate(f"({letter})", xy=(0.0, 1.0), xycoords="axes fraction",
                xytext=(-14, 8), textcoords="offset points",
                ha="left", va="bottom", fontsize=9, fontweight="bold",
                annotation_clip=False)


def footnote(fig, text: str, x: float = 0.012, y: float = 0.015) -> None:
    """Small, self-contained provenance line under the figure."""
    fig.text(x, y, text, fontsize=6.5, color="#5A6168", ha="left", va="bottom")


def light_grid(ax, axis: str = "y") -> None:
    """Subtle, behind-the-data grid; keeps the full frame but removes clutter."""
    ax.set_axisbelow(True)
    ax.grid(axis=axis, color=GRID, linewidth=0.5, linestyle="-", alpha=0.9)
    ax.set_axisbelow(True)


def save_figure(fig, path_stem: str, formats=("pdf", "png")) -> list[str]:
    """
    Write a fixed-size vector (PDF) and a 600-dpi preview (PNG).
    Never use bbox_inches='tight': the declared physical geometry is preserved.
    """
    out = Path(path_stem)
    out.parent.mkdir(parents=True, exist_ok=True)
    written = []
    for suffix in formats:
        target = out.with_suffix("." + suffix)
        fig.savefig(target, dpi=600)
        written.append(str(target))
    return written
