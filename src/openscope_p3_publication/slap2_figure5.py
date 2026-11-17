"""SLAP2 Figure 5: glutamate signal quality as median event amplitude, rendered offline.

Each source is summarized by one continuous metric, its median event amplitude in raw-noise SD,
instead of archive-wide k-means classes. Two layouts share panels A-D:

* the manuscript figure pools all sessions (`figure-05-unit-extraction-plan.svg`);
* a variant splits the cumulative distribution, DMD pools and session axis by processing cohort
  (`figure-05-unit-extraction-plan-by-cohort.svg`).

Inputs are the issue-59 refresh of the archive tables, the noise-only surrogate reference and the
pinned example snapshot. Figure 9 and the legacy class panels keep the earlier archive tables.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

import matplotlib as mpl
import numpy as np
import pandas as pd

mpl.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.axes import Axes  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

from openscope_p3_publication import slap2_glutamate_figure7_panels as panels  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
TABLE_DIR = REPO_ROOT / "figure_sources/data/slap2-glutamate-qc-v2"
NOISE_DIR = REPO_ROOT / "figure_sources/data/slap2-figure5-noise"
GENERATED = REPO_ROOT / "images/figures/generated"
POOLED_OUTPUT = GENERATED / "figure-05-unit-extraction-plan.svg"
BY_COHORT_OUTPUT = GENERATED / "figure-05-unit-extraction-plan-by-cohort.svg"

AMPLITUDE = "median_event_raw_sd"
AMPLITUDE_LABEL = "Median event amplitude (raw-noise SD)"
# Medium lightness and high chroma: readable on the black map background, the grey dendrites
# and the white plot background. Lightness rises monotonically from indigo to amber.
AMPLITUDE_CMAP = LinearSegmentedColormap.from_list(
    "slap2_amplitude", ["#3949ab", "#0288b0", "#26a269", "#9cb800", "#f0a000"],
)
AMPLITUDE_LIMITS = (2.0, 8.0)
# Same value as the raw-neural and segmentation extractors. NWB grid_spacing is empty, so this
# scale still needs confirmation for the example session.
UM_PER_PIXEL = 0.25
COHORT_COLORS = {False: "#0072B2", True: "#CC79A7"}
COHORT_NAMES = {False: "Glu only", True: "Glu + Ca"}
# NWB imaging-plane locations; recorded only for sub-794237, the example mouse.
COMPARTMENTS = {1: "proximal", 2: "apical"}
POOLED_LINE, SESSION_LINE = "#1a1a1a", "#a9a9a9"
FIGURE_WIDTH, LEFT_MARGIN, RIGHT_MARGIN, TOP_MARGIN = 7.2, 0.6, 0.1, 0.1


@dataclass(frozen=True)
class Inputs:
    """Validated archive table, example snapshot and noise-only reference."""

    session: dict
    metrics: pd.DataFrame
    example: pd.DataFrame
    noise_centers: np.ndarray
    noise_counts: np.ndarray
    trace_dmd: int
    trace_roi: int

    @property
    def usable(self) -> pd.DataFrame:
        """Sources with a measurable noise floor and at least one event."""
        return panels.usable(self.metrics)


@dataclass(frozen=True)
class Panel:
    draw: Callable[[Axes], None]
    weight: float
    gap: float = 0
    letter_offset: float = 0.42


@dataclass(frozen=True)
class Row:
    height: float
    above: float
    below: float
    panels: tuple[Panel, ...] = field(default_factory=tuple)
    left: float = LEFT_MARGIN


def _check_outputs(directory: Path) -> dict:
    provenance = json.loads((directory / "provenance.json").read_text(encoding="utf-8"))
    for name, digest in provenance["outputs"].items():
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"SLAP2 Figure 5 input changed: {directory.name}/{name}")
    return provenance


def load_inputs(table_dir: Path = TABLE_DIR, noise_dir: Path = NOISE_DIR) -> Inputs:
    """Load committed inputs after checking them against their recorded checksums."""
    _check_outputs(table_dir)
    _check_outputs(noise_dir)
    metrics = pd.read_csv(table_dir / "slap2_metrics_all_sessions.csv")
    session = panels.load_example_snapshot(panels.EXAMPLE_PATH)
    example = metrics.loc[metrics.session == session["session_id"]].reset_index(drop=True)
    histogram = pd.read_csv(noise_dir / "noise_only_amplitude_histogram.csv")
    return Inputs(
        session=session,
        metrics=metrics,
        example=example,
        noise_centers=0.5 * (histogram.bin_left_sd + histogram.bin_right_sd).to_numpy(),
        noise_counts=histogram.events.to_numpy(),
        trace_dmd=1,
        trace_roi=panels.example_synapse(example, dmd=1),
    )


def noise_median(inputs: Inputs) -> float:
    """Median of the binned noise-only amplitudes, interpolated within the 0.1 SD bin."""
    cumulative = np.cumsum(inputs.noise_counts) / inputs.noise_counts.sum()
    return float(np.interp(0.5, cumulative, inputs.noise_centers + 0.05))


def amplitude_norm(inputs: Inputs) -> mpl.colors.Normalize:
    return panels.gradient_norm(inputs.usable, AMPLITUDE)


def _scale_bar(ax: Axes, um: float, right: float, y: float) -> None:
    pixels = um / UM_PER_PIXEL
    ax.plot([right - pixels, right], [y, y], color=panels.INK, lw=1.4,
            solid_capstyle="butt", clip_on=False, zorder=8)
    ax.annotate(f"{um:g} µm", (right - pixels, y), xytext=(-3, 0), textcoords="offset points",
                ha="right", va="center", fontsize=6, color=panels.INK, zorder=8)


def _draw_trace(ax: Axes, inputs: Inputs) -> None:
    traces = inputs.session["traces"][inputs.trace_dmd]
    trace, times = panels.source_trace(traces, inputs.trace_roi), traces["ts"]
    events = panels.event_table(trace, times, traces["dt"])
    start = float(np.nanmin(times)) + 900.0
    window = (times >= start) & (times < start + 20)
    shown_times, shown = times[window] - start, trace[window]
    in_window = (events["t"] >= start) & (events["t"] < start + 20)
    peak_times = times[events["peak_idx"]] - start
    candidates = np.flatnonzero(
        in_window & np.isfinite(events["amp_raw"]) & (peak_times >= 0) & (peak_times < 20)
    )
    largest = int(candidates[np.argmax(events["amp_raw"][candidates])])
    peak = float(trace[events["peak_idx"][largest]])
    base = peak - events["amp_raw"][largest] * events["raw_sd"]
    peak_time = float(peak_times[largest])
    band_low = events["raw_med"] - 3 * events["raw_sd"]
    band_high = events["raw_med"] + 3 * events["raw_sd"]
    ax.axhspan(band_low, band_high, color=panels.NOISE_GREY, alpha=0.25, lw=0)
    ax.plot(shown_times, shown, lw=0.5, color=panels.INK_2)
    low, high = min(np.nanmin(shown), band_low), max(np.nanmax(shown), band_high)
    span = high - low
    marker_y = high + 0.12 * span
    event_times = events["t"][in_window] - start
    ax.scatter(event_times, np.full(in_window.sum(), marker_y), marker="v", s=8,
               color=panels.ORANGE, linewidths=0)
    label_x = float(event_times[np.argmin(np.abs(event_times - 10))])
    ax.annotate("detected event", (label_x, marker_y), xytext=(0, 7),
                textcoords="offset points", ha="center", va="bottom", color=panels.ORANGE,
                fontsize=6.5)
    arrow_x = peak_time + 0.3
    ax.annotate("", (arrow_x, peak), xytext=(arrow_x, base),
                arrowprops={"arrowstyle": "<->", "color": panels.INK, "linewidth": 0.7})
    for level in (base, peak):
        ax.plot([peak_time, arrow_x + 0.07], [level, level], color=panels.INK, lw=0.5)
    ax.annotate("Event\namplitude", (arrow_x, peak), xytext=(5, 2), textcoords="offset points",
                fontsize=6, va="top")
    ax.annotate("±3 raw-noise SD", (0.925, band_high), xycoords=ax.get_yaxis_transform(),
                xytext=(0, 7.5), textcoords="offset points", ha="right", va="bottom", fontsize=6,
                color=panels.INK_2)
    ax.set(xlim=(0, 20), ylim=(low - 0.08 * span, high + 0.5 * span))
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("ΔF/F")


def _draw_footprint(ax: Axes, inputs: Inputs) -> None:
    _, mean_image, outlines = inputs.session["planes"][inputs.trace_dmd]
    mask = outlines[inputs.trace_roi]
    ys, xs = np.argwhere(mask).T
    y0, y1 = max(0, ys.min() - 14), min(mean_image.shape[0], ys.max() + 15)
    x0, x1 = max(0, xs.min() - 14), min(mean_image.shape[1], xs.max() + 15)
    crop = mean_image[y0:y1, x0:x1]
    ax.imshow(crop, cmap="gray", vmin=np.nanpercentile(crop, 2),
              vmax=np.nanpercentile(crop, 99.5), interpolation="nearest")
    ax.contour(mask[y0:y1, x0:x1], levels=[0.5], colors=[panels.ORANGE], linewidths=0.9)
    panels.hide_frame(ax)
    height, width = crop.shape
    _scale_bar(ax, 2, width - 1, height + 3)
    ax.set_ylim(height + 6, -0.5)
    ax.set_xlim(-0.5, width - 0.5)
    ax.set_anchor("C")


def _map_size(inputs: Inputs, dmd: int) -> tuple[int, int]:
    y0, y1, x0, x1 = panels.coverage_bbox(inputs.session["planes"][dmd][2])
    return y1 - y0, x1 - x0


def _draw_map(ax: Axes, inputs: Inputs, dmd: int, norm) -> None:
    """Fill each source with its median amplitude, opaque to stay readable on the mean image."""
    _, mean_image, outlines = inputs.session["planes"][dmd]
    y0, y1, x0, x1 = panels.coverage_bbox(outlines)
    crop = mean_image[y0:y1, x0:x1]
    ax.set_gid(f"amplitude-footprints-DMD{dmd}")
    ax.imshow(crop, cmap="gray", vmin=np.nanpercentile(crop, 2),
              vmax=np.nanpercentile(crop, 99.5), interpolation="nearest")
    rgba = np.zeros((*crop.shape, 4))
    plane = panels.usable(inputs.example.loc[inputs.example.dmd == dmd])
    for row in plane.itertuples():
        color = AMPLITUDE_CMAP(norm(getattr(row, AMPLITUDE)))[:3]
        rgba[outlines[int(row.roi)][y0:y1, x0:x1]] = (*color, 0.95)
    ax.imshow(rgba, interpolation="nearest")
    if dmd == inputs.trace_dmd:
        y, x = np.argwhere(outlines[inputs.trace_roi]).mean(axis=0)
        panels.mark_example(ax, float(x - x0), float(y - y0), dmd, inputs.trace_roi, below=True)
    ax.set_title(panels.COMPARTMENT[dmd], loc="left", fontsize=7, pad=2)
    panels.hide_frame(ax)
    ax.set_anchor("NW")
    height, width = _map_size(inputs, dmd)
    _scale_bar(ax, 25, width - 1, height + 8)
    ax.set_ylim(height + 12, -0.5)
    ax.set_xlim(-0.5, width - 0.5)


def _add_amplitude_colorbar(ax: Axes, norm) -> None:
    fig, box = ax.figure, ax.get_position()
    height = fig.get_figheight()
    bar = fig.add_axes((box.x0 + 0.62 * box.width, box.y1 - 0.1 / height,
                        0.32 * box.width, 0.07 / height))
    colorbar = fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=AMPLITUDE_CMAP), cax=bar,
                            orientation="horizontal", extend="both")
    colorbar.outline.set_visible(False)
    colorbar.ax.tick_params(labelsize=5.6, color=panels.INK_2, labelcolor=panels.INK_2,
                            width=0.5, length=2)
    bar.set_title(AMPLITUDE_LABEL, fontsize=5.8, color=panels.INK, pad=2)


def _ecdf_line(ax: Axes, values: np.ndarray, color: str, lw: float, *, alpha: float = 1.0,
               label: str | None = None, zorder: int = 2) -> None:
    ordered = np.sort(values)
    ax.step(ordered, np.arange(1, ordered.size + 1) / ordered.size * 100, where="post",
            color=color, lw=lw, alpha=alpha, label=label, zorder=zorder)


def _draw_cumulative(ax: Axes, inputs: Inputs, by_cohort: bool) -> None:
    """Cumulative distribution per session, with a bold line for all sources (and cohorts)."""
    usable = inputs.usable
    for cohort in (False, True):
        group = usable.loc[usable.has_calcium.eq(cohort)]
        color = COHORT_COLORS[cohort] if by_cohort else SESSION_LINE
        for _, rows in group.groupby("session"):
            _ecdf_line(ax, rows[AMPLITUDE].to_numpy(float), color, 0.6,
                       alpha=0.3 if by_cohort else 0.5)
        if by_cohort:
            _ecdf_line(ax, group[AMPLITUDE].to_numpy(float), COHORT_COLORS[cohort], 1.4,
                       label=f"{COHORT_NAMES[cohort]} ({len(group):,} sources)", zorder=3)
    _ecdf_line(ax, usable[AMPLITUDE].to_numpy(float), POOLED_LINE, 1.6,
               label=f"All sources ({len(usable):,})", zorder=4)
    if not by_cohort:
        ax.plot([], [], color=SESSION_LINE, lw=0.8,
                label=f"Sessions ({usable.session.nunique()})")
    reference = noise_median(inputs)
    ax.axhline(50, color=panels.GRID, lw=0.6, zorder=0)
    ax.axvline(reference, color=panels.INK_2, lw=0.7, ls=(0, (3, 2)), zorder=1)
    ax.annotate(f"Noise-only median {reference:.1f} SD", (reference, 0.98),
                xycoords=ax.get_xaxis_transform(), xytext=(2, 0), textcoords="offset points",
                rotation=90, ha="left", va="top", fontsize=5.4, color=panels.INK_2)
    ax.set_xlim(2, 10)
    ax.set_ylim(0, 101)
    ax.set_xlabel(AMPLITUDE_LABEL)
    ax.set_ylabel("Synapses (cumulative %)")
    ax.legend(loc="lower right", bbox_to_anchor=(1.02, 0.0), fontsize=5.6, handlelength=1.2,
              frameon=False)


def _draw_sources(ax: Axes, x: float, values: np.ndarray, norm, rng) -> None:
    """Jittered sources clipped to the axis, with median and interquartile range."""
    ax.scatter(x + rng.uniform(-0.26, 0.26, values.size), np.clip(values, *AMPLITUDE_LIMITS),
               s=1.4, c=AMPLITUDE_CMAP(norm(values)), linewidths=0, alpha=0.75, rasterized=True,
               zorder=2)
    low, median, high = np.percentile(values, [25, 50, 75])
    ax.plot([x, x], [low, high], color=panels.INK, lw=1.2, zorder=4, solid_capstyle="butt")
    ax.plot([x - 0.32, x + 0.32], [median, median], color=panels.INK, lw=1.2, zorder=4,
            solid_capstyle="butt")


def _finish_amplitude_axis(ax: Axes, inputs: Inputs, right: float) -> None:
    reference = noise_median(inputs)
    ax.axhline(reference, color=panels.INK_2, lw=0.6, ls=(0, (3, 2)), zorder=1)
    ax.text(right, reference - 0.06, "Noise-only median", ha="right", va="top", fontsize=5.6,
            color=panels.INK_2)
    ax.set_ylim(*AMPLITUDE_LIMITS)
    ax.set_ylabel("Median event\namplitude (SD)")
    ax.grid(axis="y", alpha=0.7)
    ax.set_axisbelow(True)


def _draw_dmd_pools(ax: Axes, inputs: Inputs, norm, by_cohort: bool) -> None:
    usable, rng = inputs.usable, np.random.default_rng(0)
    if by_cohort:
        positions = {(False, 1): 0.0, (False, 2): 1.0, (True, 1): 2.6, (True, 2): 3.6}
        for (cohort, dmd), x in positions.items():
            rows = usable.loc[usable.has_calcium.eq(cohort) & usable.dmd.eq(dmd)]
            _draw_sources(ax, x, rows[AMPLITUDE].to_numpy(float), norm, rng)
        for cohort, x in ((False, 0.5), (True, 3.1)):
            count = int(usable.has_calcium.eq(cohort).sum())
            ax.text(x, 1.03, f"{COHORT_NAMES[cohort]}\n({count:,} sources)", ha="center",
                    va="bottom", transform=ax.get_xaxis_transform(), fontsize=6,
                    color=panels.INK, linespacing=1.15)
        ticks = list(positions.values())
        labels = [f"DMD{dmd}\n{COMPARTMENTS[dmd]}" for _, dmd in positions]
        right = 4.2
    else:
        for dmd, x in ((1, 0.0), (2, 1.0)):
            rows = usable.loc[usable.dmd.eq(dmd)]
            _draw_sources(ax, x, rows[AMPLITUDE].to_numpy(float), norm, rng)
        ticks = [0.0, 1.0]
        labels = [f"DMD{dmd} · {COMPARTMENTS[dmd]}\n({int(usable.dmd.eq(dmd).sum()):,} sources)"
                  for dmd in (1, 2)]
        right = 1.6
    _finish_amplitude_axis(ax, inputs, right)
    ax.set_xticks(ticks, labels, fontsize=6)
    ax.set_xlim(-0.6, right)


def _session_table(inputs: Inputs) -> pd.DataFrame:
    table = panels.class_composition_summary(inputs.metrics)
    return table.loc[table.group.eq("Session")].reset_index(drop=True)


def _session_positions(table: pd.DataFrame, by_cohort: bool) -> np.ndarray:
    positions = np.arange(len(table), dtype=float)
    if by_cohort:
        positions[table.has_calcium.to_numpy(bool)] += 1
    for index, (_, rows) in enumerate(table.groupby("subject", sort=False)):
        positions[rows.index] += 0.35 * index
    return positions


def _session_axis(ax: Axes, table: pd.DataFrame, positions: np.ndarray, by_cohort: bool) -> None:
    transform = ax.get_xaxis_transform()
    if by_cohort:
        for cohort, rows in table.groupby("has_calcium", sort=False):
            ax.text(float(positions[rows.index].mean()), 1.06,
                    f"{COHORT_NAMES[cohort]} sessions", transform=transform, ha="center",
                    va="bottom", fontsize=6, color=panels.INK)
    for subject, rows in table.groupby("subject", sort=False):
        x = positions[rows.index]
        ax.plot([x.min() - 0.4, x.min() - 0.4, x.max() + 0.4, x.max() + 0.4],
                [-0.47, -0.5, -0.5, -0.47], transform=transform, clip_on=False,
                color=panels.INK_2, lw=0.5)
        ax.text(float(x.mean()), -0.57, str(subject).removeprefix("sub-"), transform=transform,
                ha="center", va="top", fontsize=5.2, color=panels.INK_2)
    for text, y in (("Date", -0.24), ("Mouse ID", -0.6)):
        ax.text(positions[0] - 1.1, y, text, transform=transform, ha="right", va="center",
                fontsize=6, color=panels.INK)
    ax.set_xticks(positions, table.label, rotation=60, ha="right", fontsize=5.5)
    ax.set_xlim(positions[0] - 1.2, positions[-1] + 0.6)


def _draw_sessions(ax: Axes, inputs: Inputs, norm, by_cohort: bool) -> None:
    table, usable = _session_table(inputs), inputs.usable
    positions, rng = _session_positions(table, by_cohort), np.random.default_rng(0)
    for x, row in zip(positions, table.itertuples(), strict=True):
        values = usable.loc[usable.session == row.session, AMPLITUDE].to_numpy(float)
        _draw_sources(ax, x, values, norm, rng)
    _session_axis(ax, table, positions, by_cohort)
    _finish_amplitude_axis(ax, inputs, positions[-1] + 0.6)


def figure_rows(inputs: Inputs, by_cohort: bool) -> list[Row]:
    """Panels A-G: trace, footprint, two maps, cumulative distribution, DMD pools, sessions."""
    norm = amplitude_norm(inputs)

    def first_map(ax: Axes) -> None:
        _draw_map(ax, inputs, 1, norm)
        _add_amplitude_colorbar(ax, norm)

    return [
        Row(1.1, 0.3, 0.42, (
            Panel(lambda ax: _draw_trace(ax, inputs), 4.3),
            Panel(lambda ax: _draw_footprint(ax, inputs), 1, gap=0.3, letter_offset=0.25),
        )),
        Row(1.55, 0.28, 0.05, (
            Panel(first_map, _map_size(inputs, 1)[1], letter_offset=0.3),
            Panel(lambda ax: _draw_map(ax, inputs, 2, norm), _map_size(inputs, 2)[1],
                  gap=0.35, letter_offset=0.3),
        ), left=0.35),
        Row(1.45, 0.32, 0.3, (
            Panel(lambda ax: _draw_cumulative(ax, inputs, by_cohort), 1),
            Panel(lambda ax: _draw_dmd_pools(ax, inputs, norm, by_cohort),
                  0.9 if by_cohort else 0.55, gap=0.65),
        )),
        Row(1.15, 0.5 if by_cohort else 0.3, 1.0,
            (Panel(lambda ax: _draw_sessions(ax, inputs, norm, by_cohort), 1),)),
    ]


def _compose(rows: list[Row]) -> plt.Figure:
    """Lay out rows on a fixed-width figure, with automatic sequential panel letters."""
    height = TOP_MARGIN + sum(row.above + row.height + row.below for row in rows)
    fig = plt.figure(figsize=(FIGURE_WIDTH, height))
    y = height - TOP_MARGIN
    letter = ord("A")
    for row in rows:
        y -= row.above
        bottom = y - row.height
        gaps = sum(panel.gap for panel in row.panels)
        available = FIGURE_WIDTH - row.left - RIGHT_MARGIN - gaps
        total = sum(panel.weight for panel in row.panels)
        x = row.left
        for panel in row.panels:
            x += panel.gap
            width = available * panel.weight / total
            ax = fig.add_axes((x / FIGURE_WIDTH, bottom / height, width / FIGURE_WIDTH,
                               row.height / height))
            fig.text(max(0.05, x - panel.letter_offset) / FIGURE_WIDTH, (y + 0.08) / height,
                     chr(letter), fontsize=11, fontweight="bold", va="bottom", ha="left",
                     color=panels.INK, gid=f"panel-label-{chr(letter)}")
            letter += 1
            panel.draw(ax)
            x += width
        y = bottom - row.below
    return fig


def stable_svg_ids(svg: str, prefix: str) -> str:
    """Replace Matplotlib's hash-based clip, marker and image IDs by sequential names.

    Matplotlib hashes each clip box's floats into its ID, so last-bit float differences
    between Python builds or platforms change the IDs although every drawn number is equal.
    """
    hashed = r"(?:p|m|image)[0-9a-f]{10}"
    names = {
        old: f"{prefix}-{index}"
        for index, old in enumerate(dict.fromkeys(re.findall(rf'id="({hashed})"', svg)))
    }
    pattern = rf'(id="|url\(#|href="#)({hashed})(?=[")])'
    return re.sub(pattern, lambda match: match.group(1) + names.get(match.group(2),
                                                                      match.group(2)), svg)


def _write(rows: list[Row], output: Path, title: str, description: str, id_prefix: str) -> Path:
    fig = _compose(rows)
    panels.save_panel(fig, output.parent, output.stem, preview_png=False)
    svg = stable_svg_ids(output.read_text(encoding="utf-8"), id_prefix)
    opening = svg.index(">", svg.index("<svg")) + 1
    accessible = (
        f'<title id="title">{escape(title)}</title>'
        f'<desc id="description">{escape(description)}</desc>'
    )
    output.write_text(svg[:opening] + accessible + svg[opening:], encoding="utf-8", newline="\n")
    return output


def write_figure5(
    pooled: Path = POOLED_OUTPUT, by_cohort: Path = BY_COHORT_OUTPUT,
) -> tuple[Path, Path]:
    """Render the pooled manuscript figure and the by-cohort variant from committed inputs."""
    inputs = load_inputs()
    usable = inputs.usable
    shared = (
        "A shows one raw glutamate trace with detected events and one event-amplitude "
        "measurement; B the source footprint; C and D the DMD1 and DMD2 dendritic maps of the "
        "example session, with each source colored by its median event amplitude. "
        f"E shows the cumulative distribution of median event amplitude across "
        f"{len(usable):,} sources from {usable.session.nunique()} sessions, with a "
        "noise-only reference; F the DMD1 and DMD2 pools; G each session."
    )
    with mpl.rc_context():
        panels.set_style()
        written_pooled = _write(
            figure_rows(inputs, by_cohort=False), pooled,
            "SLAP2 glutamate signal quality: median event amplitude", shared,
            "slap2-figure5",
        )
        written_by_cohort = _write(
            figure_rows(inputs, by_cohort=True), by_cohort,
            "SLAP2 glutamate signal quality by processing cohort",
            shared + " E, F and G separate the glutamate-only and glutamate-plus-calcium cohorts.",
            "slap2-figure5-by-cohort",
        )
    return written_pooled, written_by_cohort
