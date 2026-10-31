# Author: Marcel C. Raabe
# Contributors: Lucas Rudelt
# Date: 2026-10-29
"""Receptive fields mapped with local Gabor patches and the Zebra noise movie.

Draws the static receptive-field figure from the committed intermediate
``figure_sources/data/receptive-fields/receptive-fields.h5``. Reading that file
needs no network, so ``build-publication-figures`` reproduces the SVG
byte-for-byte from a fresh clone. The intermediate is written by
``scripts/extract_receptive_fields.py`` from the reduced pipeline results; the
selection, significance tests, Gaussian fits and statistics all happen there,
and this module only draws them.

Columns are the modalities (Neuropixels, mesoscope, SLAP2 glutamate):

* A: one example unit per selection (only Zebra, only Gabor, both tests
  significant), Gabor map above Zebra map, with the Gaussian fit of a significant map.
* B: units of the two compared structures by which test they pass.
* C: Gaussian centre, one-sigma area and peak strength of the significant maps,
  Gabor above Zebra, with the median, its bootstrap 95% CI and a permutation test.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import h5py
import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Ellipse, Patch

from .figure_typography import normalize_figure_svg
from .figures import load_platform_logos
from .image_encoding import canonical_svg_images

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "figure_sources" / "data" / "receptive-fields"
DATA_PATH = DATA_DIR / "receptive-fields.h5"
PROVENANCE_PATH = DATA_DIR / "receptive-fields.provenance.json"
OUTPUT_PATH = REPO_ROOT / "images" / "figures" / "generated" / "receptive-fields.svg"

MODALITIES = (
    ("ecephys", "Neuropixels"),
    ("mesoscope", "Mesoscope"),
    ("slap2", "SLAP2 glutamate"),
)
SELECTIONS = ("both", "gabor-only", "zebra-only")
EXAMPLE_ORDER = ("zebra-only", "gabor-only", "both")
SELECTION_TITLES = {
    "both": "Both\nsignificant",
    "gabor-only": "Only Gabor\nsignificant",
    "zebra-only": "Only Zebra\nsignificant",
}
PIE_ORDER = ("neither", "Zebra only", "Gabor only", "both")
PIE_COLORS = {
    "neither": "#c8c8c8",
    "Zebra only": "#4C78A8",
    "Gabor only": "#E45756",
    "both": "#54A24B",
}
SELECTION_COLORS = {
    "both": PIE_COLORS["both"],
    "gabor-only": PIE_COLORS["Gabor only"],
    "zebra-only": PIE_COLORS["Zebra only"],
}
STRUCTURE_ORDER = ("V1", "LM", "DMD1\n(apical)", "DMD2\n(basal)")
STRUCTURE_COLORS = {
    "V1": "#2166ac",
    "LM": "#b2182b",
    "DMD1\n(apical)": "#2166ac",
    "DMD2\n(basal)": "#b2182b",
}
# Fixed top of the RF-area axis, deg²; larger areas lie outside the frame.
AREA_YMAX = 2000.0

# Layout, inches. A degree has the same length on every map and scatter.
INCH_PER_DEG = 0.0088
FIG_W = 15.0
STIM_W = 1.25
MARGIN_L = 0.35
MODULE_X = 1.95
MODULE_W = (FIG_W - MODULE_X - 0.55) / len(MODALITIES)

TICK = 10.0
LABEL = 11.0
TITLE = 11.0
MODALITY_TITLE = 16.0
LETTER = 18.0

RC_PARAMS = {
    "font.family": "DejaVu Sans",
    "font.size": LABEL,
    "axes.linewidth": 0.45,
    "xtick.labelsize": TICK,
    "ytick.labelsize": TICK,
    "xtick.major.width": 0.45,
    "ytick.major.width": 0.45,
    "xtick.major.size": 2.5,
    "ytick.major.size": 2.5,
    "legend.frameon": False,
    "svg.fonttype": "none",
    "svg.hashsalt": "openscope-p3-receptive-fields",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strings(dataset: h5py.Dataset) -> list[str]:
    return list(dataset.asstr()[:])


def _table(group: h5py.Group) -> dict[str, np.ndarray]:
    return {
        name: np.asarray(_strings(ds)) if ds.dtype.kind == "O" else ds[:]
        for name, ds in group.items()
    }


def load_receptive_fields(path: Path = DATA_PATH, provenance: Path = PROVENANCE_PATH) -> dict:
    """The committed intermediate, after checking it against its provenance checksum."""
    expected = json.loads(provenance.read_text(encoding="utf-8"))["output"]["sha256"]
    if sha256(path) != expected:
        raise ValueError(f"{path.name} does not match the SHA-256 in {provenance.name}")
    data: dict = {}
    with h5py.File(path, "r") as hf:
        data["attrs"] = dict(hf.attrs)
        data["zebra_frame"] = hf["stimulus/zebra_frame"][:]
        data["gabor_patch"] = {
            key.removeprefix("gabor_"): value for key, value in hf["stimulus"].attrs.items()
        }
        for modality, _ in MODALITIES:
            group = hf[modality]
            examples = group["examples"]
            data[modality] = {
                "attrs": dict(group.attrs),
                "examples": {
                    **_table(examples),
                    "attrs": dict(examples.attrs),
                },
                "units": _table(group["units"]),
            }
            for kind in ("gabor", "zebra"):
                data[modality][f"{kind}_fits"] = _table(group[f"{kind}_fits"])
                data[modality][f"{kind}_window"] = group[f"{kind}_fits"].attrs["window_deg"]
                data[modality][f"{kind}_summary"] = _table(group[f"{kind}_summary"])
                data[modality][f"{kind}_tests"] = _table(group[f"{kind}_tests"])
    return data


# ---------------------------------------------------------------------------
# Stimuli
# ---------------------------------------------------------------------------


def gabor_frame(shape: tuple[int, int], coverage, patch: dict) -> np.ndarray:
    """One Gabor patch on mean grey, over the whole screen at ``shape`` pixels."""
    x0, x1, y0, y1 = coverage
    az, el = np.meshgrid(np.linspace(x0, x1, shape[1]), np.linspace(y0, y1, shape[0]))
    dx, dy = az - patch["x_deg"], el - patch["y_deg"]
    theta = patch["orientation_rad"]
    along = dx * np.cos(theta) + dy * np.sin(theta)
    grating = patch["contrast"] * np.cos(2 * np.pi * patch["spatial_frequency_cpd"] * along)
    inside = np.hypot(dx, dy) <= patch["diameter_deg"] / 2
    return 0.5 + 0.5 * np.where(inside, grating, 0.0)


def _draw_stimulus(ax, image: np.ndarray, title: str) -> None:
    ax.imshow(image, cmap="gray", vmin=0, vmax=1, aspect="auto", interpolation="lanczos")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title(title, fontsize=LABEL, pad=3)


# ---------------------------------------------------------------------------
# Row A: example maps
# ---------------------------------------------------------------------------


def _span(extent) -> tuple[float, float]:
    x0, x1, y0, y1 = (float(v) for v in extent)
    return abs(x1 - x0), abs(y1 - y0)


def _row_scale(maps: np.ndarray, present: np.ndarray) -> float:
    peaks = [np.nanmax(np.abs(m)) for m, keep in zip(maps, present, strict=True) if keep]
    peaks = [p for p in peaks if np.isfinite(p) and p > 0]
    return float(max(peaks)) if peaks else 1.0


def _clipped_ticks(ticks: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return ticks[(ticks >= min(lo, hi)) & (ticks <= max(lo, hi))]


def _draw_map(ax, image, extent, origin, norm, faint_zero=False):
    im = ax.imshow(
        image.T, cmap="coolwarm", norm=norm, extent=extent,
        origin=origin, aspect="equal", interpolation="nearest",
    )
    zero = ".75" if faint_zero else ".4"
    ax.axhline(0, color=zero, lw=0.35, zorder=1)
    ax.axvline(0, color=zero, lw=0.35, zorder=1)
    x0, x1, y0, y1 = extent
    ax.set_xticks(_clipped_ticks(np.arange(-40, 80, 40), x0, x1))
    ax.set_yticks(_clipped_ticks(np.arange(-40, 60, 20), y0, y1))
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    return im


def _draw_empty(ax, extent, text: str | None) -> None:
    ax.set_xlim(*extent[:2])
    ax.set_ylim(*extent[2:])
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    if text:
        ax.text(0.5, 0.5, text, transform=ax.transAxes, ha="center", va="center",
                fontsize=TICK)


def _frame(ax, color: str) -> None:
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_edgecolor(color)
        spine.set_linewidth(0.8)


def _mark_q(ax, passed: bool, q_level: float) -> None:
    ax.text(
        0.96, 0.95, f"q < {q_level:g}" if passed else "n.s.",
        transform=ax.transAxes, ha="right", va="top", fontsize=TICK - 1, zorder=5,
        bbox={"boxstyle": "round,pad=0.15", "facecolor": "white", "edgecolor": "none",
              "alpha": 0.8},
    )


def _draw_gaussian(ax, fit: np.ndarray) -> None:
    """Centre and one-sigma ellipse; ``fit`` is (x0, y0, sigma_x, sigma_y, theta, r2)."""
    x0, y0, sx, sy, theta, _ = (float(v) for v in fit)
    if not np.isfinite([x0, y0, sx, sy, theta]).all():
        return
    # sigma_x lies along angle theta, as in gaussian_envelope.gaussian2d.
    kw = dict(xy=(x0, y0), width=2 * sx, height=2 * sy, angle=np.degrees(theta),
              fill=False, zorder=3)
    ax.add_patch(Ellipse(edgecolor="black", linewidth=1.0, **kw))
    ax.add_patch(Ellipse(edgecolor="white", linewidth=0.4, **kw))
    ax.plot(x0, y0, marker="o", ms=2.5, mfc="white", mec="black", mew=0.4,
            linestyle="none", zorder=4)


def draw_examples(place, data: dict, modality: str, x: float, y: float,
                  norms: dict[str, mpl.colors.Normalize]) -> tuple[float, float]:
    """Row A of one modality, top-left at (x, y). Returns the y of the two map rows' centres."""
    ex = data[modality]["examples"]
    q_level = float(data["attrs"]["q_level"])
    gabor_extent = tuple(float(v) for v in ex["attrs"]["gabor_extent_deg"])
    zebra_extent = tuple(float(v) for v in data["attrs"]["zebra_extent_deg"])
    gabor_w, gabor_h = (s * INCH_PER_DEG for s in _span(gabor_extent))
    zebra_w, zebra_h = (s * INCH_PER_DEG for s in _span(zebra_extent))
    gap, row_gap, title_h = 0.10, 0.40, 0.42
    left = (MODULE_W - 3 * zebra_w - 2 * gap) / 2
    gabor_y = y + title_h
    zebra_y = gabor_y + gabor_h + row_gap
    present = ex["present"]
    indices = {selection: index for index, selection in enumerate(ex["selection"])}
    for col, selection in enumerate(EXAMPLE_ORDER):
        index = indices[selection]
        zx = x + left + col * (zebra_w + gap)
        gabor_ax = place(zx + (zebra_w - gabor_w) / 2, gabor_y, gabor_w, gabor_h)
        zebra_ax = place(zx, zebra_y, zebra_w, zebra_h)
        gabor_ax.set_gid(f"example-{modality}-gabor-{selection}")
        zebra_ax.set_gid(f"example-{modality}-zebra-{selection}")
        gabor_ax.set_title(SELECTION_TITLES[selection], fontsize=LABEL, pad=4)
        if not present[index]:
            note = "No significant result"
            _draw_empty(gabor_ax, gabor_extent, note if selection != "zebra-only" else None)
            _draw_empty(zebra_ax, zebra_extent, note if selection != "gabor-only" else None)
            continue
        _draw_map(gabor_ax, ex["gabor_map"][index], gabor_extent, "lower", norms["gabor"])
        _draw_map(zebra_ax, ex["zebra_map"][index], zebra_extent, "upper",
                  norms["zebra"], faint_zero=True)
        gabor_ax.tick_params(labelbottom=False)
        for ax, kind in ((gabor_ax, "gabor"), (zebra_ax, "zebra")):
            ax.tick_params(labelsize=TICK, pad=1.5)
            _frame(ax, SELECTION_COLORS[selection])
            passed = bool(ex[f"pass_{kind}"][index])
            _mark_q(ax, passed, q_level)
            if passed:
                _draw_gaussian(ax, ex[f"{kind}_fit"][index])
        if col > 0 or modality != MODALITIES[0][0]:
            gabor_ax.tick_params(labelleft=False)
            zebra_ax.tick_params(labelleft=False)
    return gabor_y + gabor_h / 2, zebra_y + zebra_h / 2


# ---------------------------------------------------------------------------
# Row B: significance overlap
# ---------------------------------------------------------------------------


def _ordered(structures) -> list[str]:
    present = set(structures)
    return [name for name in STRUCTURE_ORDER if name in present]


def overlap_counts(units: dict, structure: str) -> dict[str, int]:
    keep = units["structure"] == structure
    zebra, gabor = units["pass_zebra"][keep], units["pass_gabor"][keep]
    return {
        "neither": int((~zebra & ~gabor).sum()),
        "Zebra only": int((zebra & ~gabor).sum()),
        "Gabor only": int((gabor & ~zebra).sum()),
        "both": int((zebra & gabor).sum()),
    }


def draw_pie(ax, title: str, counts: dict[str, int]) -> None:
    present = [name for name in PIE_ORDER if counts[name] > 0]
    _, _, autotexts = ax.pie(
        [counts[name] for name in present], colors=[PIE_COLORS[name] for name in present],
        startangle=90, autopct=lambda pct: f"{pct:.0f}%" if pct >= 6 else "",
        pctdistance=0.62, wedgeprops={"linewidth": 0.35, "edgecolor": "white"},
    )
    for text in autotexts:
        text.set_fontsize(TICK)
    ax.set_title(title, fontsize=LABEL, pad=4)


def draw_overlap(place, data: dict, modality: str, x: float, y: float) -> None:
    units = data[modality]["units"]
    diameter, slot = 1.65, MODULE_W / 2
    for i, structure in enumerate(_ordered(units["structure"])):
        n = int((units["structure"] == structure).sum())
        # one-line titles get an empty first line, so the pies line up with the DMD pies
        title = structure if "\n" in structure else f"\n{structure}"
        ax = place(x + i * slot + (slot - diameter) / 2, y + 0.42, diameter, diameter)
        ax.set_gid(f"overlap-{modality}-{i}")
        draw_pie(ax, f"{title} ({n})", overlap_counts(units, structure))


# ---------------------------------------------------------------------------
# Row C: RF summaries
# ---------------------------------------------------------------------------


def _star_label(p_value: float) -> str:
    if p_value > 0.05:
        return "n.s."
    if p_value < 0.001:
        return "***"
    if p_value < 0.01:
        return "**"
    return "*"


def _draw_position(ax, fits: dict, extent) -> None:
    for structure in _ordered(fits["structure"]):
        keep = fits["structure"] == structure
        ax.scatter(fits["x0"][keep], fits["y0"][keep], s=5, alpha=0.55, linewidths=0,
                   color=STRUCTURE_COLORS[structure], zorder=2)
    x0, x1, y0, y1 = (float(v) for v in extent)
    ax.axhline(0, color=".75", lw=0.35, zorder=1)
    ax.axvline(0, color=".75", lw=0.35, zorder=1)
    ax.set_xticks(_clipped_ticks(np.arange(-40, 80, 40), x0, x1))
    ax.set_yticks(_clipped_ticks(np.arange(-40, 60, 20), y0, y1))
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.tick_params(labelsize=TICK, pad=1.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    handles = [
        Line2D([0], [0], linestyle="none", marker="o", markersize=4,
               markerfacecolor=STRUCTURE_COLORS[s], markeredgecolor="none",
               label=f"{s.split(chr(10), 1)[0]} (n={int((fits['structure'] == s).sum())})")
        for s in _ordered(fits["structure"])
    ]
    if handles:
        ax.legend(handles=handles, fontsize=TICK, loc="lower left", bbox_to_anchor=(0, 1.0),
                  borderaxespad=0.1, handlelength=0.6, handletextpad=0.3, labelspacing=0.15,
                  ncols=1)


def _draw_comparison(ax, fits: dict, summary: dict, tests: dict, column: str, ylabel: str,
                     ymax: float | None = None) -> None:
    """Box plot per structure, with the median's bootstrap CI and the permutation test."""
    structures = _ordered(fits["structure"])
    grouped = []
    for structure in structures:
        values = np.asarray(fits[column][fits["structure"] == structure], dtype=float)
        grouped.append(values[np.isfinite(values)])
    boxed = [(i, values) for i, values in enumerate(grouped) if len(values) >= 2]
    if boxed:
        bp = ax.boxplot(
            [values for _, values in boxed], positions=[i for i, _ in boxed], widths=0.55,
            patch_artist=True, whis=1.5, showfliers=True,
            medianprops={"color": "k", "linewidth": 0.6},
            whiskerprops={"color": "k", "linewidth": 0.45},
            capprops={"color": "k", "linewidth": 0.45},
            flierprops={"marker": "o", "markersize": 1.6, "markerfacecolor": "0.35",
                        "markeredgecolor": "none", "alpha": 0.55},
        )
        for patch, (i, _) in zip(bp["boxes"], boxed, strict=True):
            patch.set_facecolor(STRUCTURE_COLORS[structures[i]])
            patch.set_edgecolor("k")
            patch.set_alpha(0.45)
            patch.set_linewidth(0.45)
    for i, (structure, values) in enumerate(zip(structures, grouped, strict=True)):
        if len(values) == 1:
            ax.scatter(i, values[0], s=10, color=STRUCTURE_COLORS[structure],
                       edgecolors="k", linewidths=0.4, zorder=4)
        row = (summary["column"] == column) & (summary["structure"] == structure)
        if len(values) and row.any():
            center = float(summary["median"][row][0])
            lo, hi = float(summary["ci_low"][row][0]), float(summary["ci_high"][row][0])
            ax.errorbar(i, center, yerr=[[max(center - lo, 0.0)], [max(hi - center, 0.0)]],
                        fmt="none", ecolor="k", elinewidth=0.5, capsize=1.8, capthick=0.5,
                        zorder=6)
    test = tests["column"] == column
    if len(grouped) == 2 and all(len(values) for values in grouped) and test.any():
        p_value = float(tests["p_value"][test][0])
        pooled = np.concatenate(grouped)
        if ymax is None:
            y_top = float(np.nanmax(pooled))
            y_span = y_top - float(np.nanmin(pooled))
            if y_span <= 0:
                y_span = abs(y_top) if y_top else 1.0
            bracket = y_top + 0.08 * y_span
            rise = 0.035 * y_span
            y_lo = float(np.nanmin(pooled)) - 0.05 * y_span
            y_hi = bracket + 0.28 * y_span
            annotation_y = bracket + 0.045 * y_span
            annotation_transform = ax.transData
        else:
            y_lo, y_hi = 0.0, float(ymax)
            bracket, rise, annotation_y = 1.02, 0.03, 1.065
            annotation_transform = ax.get_xaxis_transform()
        ax.plot([0, 0, 1, 1], [bracket, bracket + rise, bracket + rise, bracket],
                color="k", lw=0.4, transform=annotation_transform, clip_on=False)
        ax.text(0.5, annotation_y, _star_label(p_value), ha="center", va="bottom",
                fontsize=TICK, transform=annotation_transform, clip_on=False)
        ax.set_ylim(y_lo, y_hi)
        if ymax is not None:
            ax.set_yticks(np.arange(0, ymax + 1, 1000))
    ax.set_xlim(-0.4, 1.4)
    ax.set_xticks(range(len(structures)))
    ax.set_xticklabels([structure.split("\n", 1)[0] for structure in structures], fontsize=TICK)
    ax.set_ylabel(ylabel, fontsize=LABEL, labelpad=1)
    ax.tick_params(axis="y", labelsize=TICK, pad=1.5)
    ax.tick_params(axis="x", length=0, pad=2)
    for side in ("top", "right", "bottom"):
        ax.spines[side].set_visible(False)


def draw_summary(place, data: dict, modality: str, x: float, y: float) -> tuple[float, float]:
    """Row C of one modality, top-left at (x, y). Returns the y of the two rows' centres."""
    packed = data[modality]
    gabor_window = tuple(float(v) for v in packed["gabor_window"])
    zebra_window = tuple(float(v) for v in packed["zebra_window"])
    # both scatters share the wider elevation range, so no fitted centre is clipped
    y_lo, y_hi = min(gabor_window[2], zebra_window[2]), max(gabor_window[3], zebra_window[3])
    gabor_window = (*gabor_window[:2], y_lo, y_hi)
    zebra_window = (*zebra_window[:2], y_lo, y_hi)
    gabor_w, height = (s * INCH_PER_DEG for s in _span(gabor_window))
    zebra_w = _span(zebra_window)[0] * INCH_PER_DEG
    legend_h, row_gap = 0.28, 0.72
    box_w, box_gap = 0.80, 0.64
    left = (MODULE_W - zebra_w - 2 * (box_w + box_gap)) / 2
    centres = []
    for row, (kind, window, width, strength_label) in enumerate((
        ("gabor", gabor_window, gabor_w, "Peak |z|"),
        ("zebra", zebra_window, zebra_w, "Peak |r|"),
    )):
        top = y + legend_h + row * (height + row_gap + legend_h)
        # same azimuth above the same azimuth
        sx = x + left + (window[0] - zebra_window[0]) * INCH_PER_DEG
        fits = packed[f"{kind}_fits"]
        position = place(sx, top, width, height)
        position.set_gid(f"summary-{modality}-{kind}-position")
        _draw_position(position, fits, window)
        position.set_xlabel("Azimuth (deg)", fontsize=LABEL, labelpad=1)
        if modality == MODALITIES[0][0]:
            position.set_ylabel("Elevation (deg)", fontsize=LABEL, labelpad=1)
        else:
            position.tick_params(labelleft=False)
        area_x = x + left + zebra_w + box_gap
        summary, tests = packed[f"{kind}_summary"], packed[f"{kind}_tests"]
        area = place(area_x, top, box_w, height)
        strength = place(area_x + box_w + box_gap, top, box_w, height)
        area.set_gid(f"summary-{modality}-{kind}-area")
        strength.set_gid(f"summary-{modality}-{kind}-strength")
        _draw_comparison(area, fits, summary, tests, "area", "Area (deg²)", ymax=AREA_YMAX)
        _draw_comparison(strength, fits, summary, tests, "strength", strength_label)
        centres.append(top + height / 2)
    return centres[0], centres[1]


# ---------------------------------------------------------------------------
# Figure
# ---------------------------------------------------------------------------


def build_figure(data: dict) -> plt.Figure:
    row_a_h, row_b_h, row_c_h = 3.03, 2.87, 3.95
    top_margin, gap = 0.98, 0.20
    fig_h = top_margin + row_a_h + gap + row_b_h + gap + row_c_h + 0.1
    fig = plt.figure(figsize=(FIG_W, fig_h))

    def place(x: float, y: float, w: float, h: float):
        """Axes at (x, y) inches from the top-left corner, w x h inches."""
        return fig.add_axes((x / FIG_W, 1 - (y + h) / fig_h, w / FIG_W, h / fig_h))

    row_a_y = top_margin
    row_b_y = row_a_y + row_a_h + gap
    row_c_y = row_b_y + row_b_h + gap
    for letter, top in (("A", row_a_y - 0.2), ("B", row_b_y), ("C", row_c_y)):
        fig.text(0.08 / FIG_W, 1 - top / fig_h, letter, fontsize=LETTER, fontweight="bold",
                 ha="left", va="top", gid=f"panel-label-{letter}")

    a_centres = c_centres = None
    norms = {}
    for kind in ("gabor", "zebra"):
        vmax = max(
            _row_scale(data[modality]["examples"][f"{kind}_map"],
                       data[modality]["examples"]["present"])
            for modality, _ in MODALITIES
        )
        norms[kind] = mpl.colors.Normalize(vmin=-vmax, vmax=vmax)
    logos = load_platform_logos()
    for i, (modality, title) in enumerate(MODALITIES):
        x = MODULE_X + i * MODULE_W
        centre = x + MODULE_W / 2
        logo_side, logo_gap, logo_top = 0.72, 0.09, 0.06
        heading = fig.text(
            centre / FIG_W, 1 - (logo_top + logo_side / 2) / fig_h, title,
            fontsize=MODALITY_TITLE, fontweight="bold", ha="center", va="center",
        )
        heading.set_gid(f"modality-heading-{modality}")
        title_width = heading.get_window_extent().width / fig.dpi
        logo_left = centre - title_width / 2 - logo_gap - logo_side
        logo_modality = "neuropixels" if modality == "ecephys" else modality
        logo = place(logo_left, logo_top, logo_side, logo_side)
        logo.set_gid(f"platform-logo-{logo_modality}")
        logo.imshow(plt.imread(logos[logo_modality]), interpolation="nearest")
        logo.set_axis_off()
        a = draw_examples(place, data, modality, x, row_a_y, norms)
        draw_overlap(place, data, modality, x, row_b_y)
        c = draw_summary(place, data, modality, x, row_c_y)
        if i == 0:
            a_centres, c_centres = a, c

    for kind, centre, label in zip(
        ("gabor", "zebra"), a_centres, ("z score", "Correlation"), strict=True,
    ):
        cbar = fig.colorbar(
            mpl.cm.ScalarMappable(norm=norms[kind], cmap="coolwarm"),
            cax=place(14.20, centre - 0.42, 0.12, 0.84),
            ticks=(-norms[kind].vmax, 0, norms[kind].vmax),
            format="%.2g",
        )
        cbar.ax.set_gid(f"shared-colorbar-{kind}")
        cbar.solids.set_rasterized(False)
        cbar.ax.tick_params(labelsize=TICK, pad=1.5)
        cbar.set_label(label, fontsize=LABEL, labelpad=3)

    legend = fig.legend(
        handles=[Patch(facecolor=PIE_COLORS[name], edgecolor="none", label=name)
                 for name in PIE_ORDER],
        loc="center", bbox_to_anchor=((MODULE_X + 3 * MODULE_W / 2) / FIG_W,
                                     1 - (row_b_y + 2.40) / fig_h),
        fontsize=TICK, ncols=4, handlelength=1.0, handleheight=0.8, handletextpad=0.4,
        columnspacing=1.5,
    )
    legend.set_gid("overlap-shared-legend")

    bottom = fig_h * (1 - min(
        axis.get_position().y0 for axis in fig.axes
        if axis.get_gid() and axis.get_gid().startswith("example-")
    ))
    elevation = fig.text(
        1.60 / FIG_W, 1 - np.mean(a_centres) / fig_h, "elevation (deg)",
        fontsize=LABEL, rotation=90, ha="center", va="center",
    )
    elevation.set_gid("examples-shared-elevation")
    azimuth = fig.text(
        (MODULE_X + 3 * MODULE_W / 2) / FIG_W,
        1 - (bottom + 0.38) / fig_h, "azimuth (deg)",
        fontsize=LABEL, ha="center", va="top",
    )
    azimuth.set_gid("examples-shared-azimuth")

    zebra = data["zebra_frame"] / 255.0
    gabor = gabor_frame(zebra.shape, data["attrs"]["visual_coverage_deg"], data["gabor_patch"])
    zebra_w, zebra_h = (s * INCH_PER_DEG for s in _span(data["attrs"]["zebra_extent_deg"]))
    stim_x = MARGIN_L + STIM_W - zebra_w - 0.31
    for centres in (a_centres, c_centres):
        for image, title, centre in (
            (gabor, "Gabor patch", centres[0]), (zebra, "Zebra noise", centres[1]),
        ):
            _draw_stimulus(place(stim_x, centre - zebra_h / 2, zebra_w, zebra_h), image, title)
    return fig


def write_receptive_fields_svg(output: Path = OUTPUT_PATH, data_path: Path = DATA_PATH) -> Path:
    """Render the static receptive-field figure from the committed intermediate."""
    data = load_receptive_fields(data_path)
    with mpl.rc_context(RC_PARAMS):
        fig = build_figure(data)
        buffer = io.StringIO()
        fig.savefig(buffer, format="svg", dpi=200, metadata={"Date": None, "Creator": None})
        plt.close(fig)
    svg = canonical_svg_images(buffer.getvalue())
    svg = normalize_figure_svg(svg)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(svg, encoding="utf-8", newline="\n")
    return output
