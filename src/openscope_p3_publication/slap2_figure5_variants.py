"""Two candidate layouts for SLAP2 Figure 5, rendered offline from committed inputs.

Both candidates place the maps directly after the footprint, add scale bars and merge the three
single-source histograms into one overlay. They differ in how they present source quality:

* Variant A uses one continuous metric, median event amplitude, with no k-means classes.
* Variant B keeps the archive-wide k-means classes.

The manuscript still uses `figure-07-unit-extraction-plan.svg`. These files are for review.
"""

from __future__ import annotations

import hashlib
import json
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
from matplotlib.lines import Line2D  # noqa: E402

from openscope_p3_publication import slap2_glutamate_figure7_panels as panels  # noqa: E402
from openscope_p3_publication.slap2_glutamate_qc_events import SD_LARGE  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "figure_sources/data/slap2-figure5-variants"
GENERATED = REPO_ROOT / "images/figures/generated"
VARIANT_A_OUTPUT = GENERATED / "figure-07-unit-extraction-plan-variant-a.svg"
VARIANT_B_OUTPUT = GENERATED / "figure-07-unit-extraction-plan-variant-b.svg"

AMPLITUDE = "median_event_raw_sd"
AMPLITUDE_LABEL = "Median event amplitude (raw-noise SD)"
AMPLITUDE_BINS = np.arange(2.0, 10.01, 0.125)
# Same value as the raw-neural and segmentation extractors. NWB grid_spacing is empty, so this
# scale still needs confirmation for the example session.
UM_PER_PIXEL = 0.25
COHORT_COLORS = {False: "#0072B2", True: "#CC79A7"}
COHORT_NAMES = {False: "Glu only", True: "Glu + Ca"}
TRACE_ROLE = "Trace example"
# Separated viridis positions: the three example medians sit too close on the map scale.
PERCENTILE_COLOR_STOPS = {90: 0.62, 50: 0.35, 10: 0.08}
FIGURE_WIDTH, LEFT_MARGIN, RIGHT_MARGIN, TOP_MARGIN = 7.2, 0.6, 0.1, 0.1


@dataclass(frozen=True)
class Inputs:
    """Validated publication tables, example snapshot and candidate-figure inputs."""

    session: dict
    metrics: pd.DataFrame
    example: pd.DataFrame
    noise_centers: np.ndarray
    noise_counts: np.ndarray
    amplitudes: pd.DataFrame
    trace_dmd: int
    trace_roi: int


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


def load_inputs(directory: Path = DATA_DIR) -> Inputs:
    """Load committed inputs after checking them against their recorded checksums."""
    provenance = json.loads((directory / "provenance.json").read_text(encoding="utf-8"))
    for name, digest in provenance["outputs"].items():
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"SLAP2 Figure 5 variant input changed: {name}")
    metrics, _, _ = panels.publication_tables()
    session = panels.load_example_snapshot(panels.EXAMPLE_PATH)
    example = metrics.loc[metrics.session == session["session_id"]].reset_index(drop=True)
    histogram = pd.read_csv(directory / "noise_only_amplitude_histogram.csv")
    return Inputs(
        session=session,
        metrics=metrics,
        example=example,
        noise_centers=0.5 * (histogram.bin_left_sd + histogram.bin_right_sd).to_numpy(),
        noise_counts=histogram.events.to_numpy(),
        amplitudes=pd.read_csv(directory / "example_source_amplitudes.csv"),
        trace_dmd=1,
        trace_roi=panels.example_synapse(example, dmd=1),
    )


def noise_median(inputs: Inputs) -> float:
    """Median of the binned noise-only amplitudes, interpolated within the 0.1 SD bin."""
    cumulative = np.cumsum(inputs.noise_counts) / inputs.noise_counts.sum()
    return float(np.interp(0.5, cumulative, inputs.noise_centers + 0.05))


def percentile_examples(inputs: Inputs) -> dict[int, tuple[int, int]]:
    """Return {percentile: (dmd, roi)} for the sources with committed event amplitudes."""
    sources = inputs.amplitudes[["percentile", "dmd", "roi"]].drop_duplicates()
    return {int(r.percentile): (int(r.dmd), int(r.roi)) for r in sources.itertuples()}


def _smooth_density(
    samples: np.ndarray, grid: np.ndarray, weights: np.ndarray | None = None, width: float = 0.3,
) -> np.ndarray:
    weights = np.ones(samples.size) if weights is None else weights
    z = (grid[:, None] - samples[None, :]) / width
    return (weights * np.exp(-0.5 * z**2)).sum(1) / (weights.sum() * width * np.sqrt(2 * np.pi))


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
    ax.set_xlabel("Time (s, from 900 s into the session)")
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


def _draw_amplitude_footprints(
    ax: Axes, inputs: Inputs, dmd: int, examples: dict, norm,
) -> None:
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
        color = panels.GRADIENT_CMAP(norm(getattr(row, AMPLITUDE)))[:3]
        rgba[outlines[int(row.roi)][y0:y1, x0:x1]] = (*color, 0.95)
    ax.imshow(rgba, interpolation="nearest")
    for role, (plane_id, roi) in examples.items():
        if plane_id == dmd:
            y, x = np.argwhere(outlines[roi]).mean(axis=0)
            panels.mark_example(ax, float(x - x0), float(y - y0), dmd, roi,
                                below=role in {TRACE_ROLE, 10, 50})
    ax.set_title(panels.COMPARTMENT[dmd], loc="left", fontsize=7, pad=2)
    panels.hide_frame(ax)


def _draw_map(ax: Axes, inputs: Inputs, dmd: int, examples: dict, norm=None) -> None:
    marked = {**examples, TRACE_ROLE: (inputs.trace_dmd, inputs.trace_roi)}
    if norm is None:
        panels.draw_class_footprints(ax, inputs.session, inputs.example, dmd, marked)
        ax.set_title(panels.COMPARTMENT[dmd], loc="left", fontsize=7, pad=2)
    else:
        _draw_amplitude_footprints(ax, inputs, dmd, marked, norm)
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
    colorbar = fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=panels.GRADIENT_CMAP), cax=bar,
                            orientation="horizontal", extend="both")
    colorbar.outline.set_visible(False)
    colorbar.ax.tick_params(labelsize=5.6, color=panels.INK_2, labelcolor=panels.INK_2,
                            width=0.5, length=2)
    bar.set_title(AMPLITUDE_LABEL, fontsize=5.8, color=panels.INK, pad=2)


def _draw_percentile_overlay(ax: Axes, inputs: Inputs) -> None:
    """Three sources named by median amplitude, with the noise-only curve."""
    grid = np.linspace(-2.0, 14.0, 500)
    handles = []
    for percentile, stop in PERCENTILE_COLOR_STOPS.items():
        rows = inputs.amplitudes.loc[inputs.amplitudes.percentile == percentile]
        amplitudes = rows.amplitude_sd.to_numpy()
        median = float(np.median(amplitudes))
        color = panels.GRADIENT_CMAP(stop)
        density = _smooth_density(amplitudes, grid)
        ax.plot(grid, density, color=color, lw=1.2)
        ax.plot(median, float(np.interp(median, grid, density)), "o", ms=3.5, color=color,
                mec="white", mew=0.6, zorder=5)
        handles.append(Line2D([], [], color=color, lw=1.2, label=(
            f"Source {int(rows.roi.iloc[0])}: {median:.1f} SD ({percentile}th percentile)"
        )))
    dash = (0, (3, 2))
    ax.plot(grid, _smooth_density(inputs.noise_centers, grid, inputs.noise_counts),
            color=panels.INK, lw=1, ls=dash)
    handles.append(Line2D([], [], color=panels.INK, lw=1, ls=dash,
                          label=f"Noise only: {noise_median(inputs):.1f} SD"))
    ax.set_xlim(grid[0], grid[-1])
    ax.set_xticks([0, 2, 4, 8, 12])
    ax.set_xlabel("Event amplitude (raw-noise SD)")
    ax.set_ylim(bottom=0)
    ax.set_ylabel("Event density")
    ax.set_yticks([])
    ax.legend(handles=handles, loc="upper right", fontsize=5.6, handlelength=1.3,
              labelspacing=0.25, borderaxespad=0.1, title="Median event amplitude",
              title_fontsize=5.6, alignment="left")


def _draw_class_overlay(ax: Axes, inputs: Inputs, examples: dict[str, tuple[int, int]]) -> None:
    """Three class examples on one axis, with the two amplitude bins shaded."""
    grid = np.linspace(-2.0, 14.0, 500)
    ax.axvspan(grid[0], 2, color=panels.BIN_GREYS["lt2"], alpha=0.35, lw=0)
    ax.axvspan(SD_LARGE, grid[-1], color=panels.BIN_GREYS["gt4"], alpha=0.12, lw=0)
    handles = []
    for name in reversed(panels.CLASS_ORDER):
        dmd, roi = examples[name]
        traces = inputs.session["traces"][dmd]
        events = panels.event_table(panels.source_trace(traces, roi), traces["ts"], traces["dt"])
        amplitudes = events["amp_raw"][np.isfinite(events["amp_raw"])]
        color = panels.CLASS_COLORS[name]
        ax.plot(grid, _smooth_density(amplitudes, grid), color=color, lw=1.2)
        handles.append(Line2D([], [], color=color, lw=1.2, label=(
            f"{name.replace(' SNR', '')} ({roi}): {100 * (amplitudes < 2).mean():.0f}%, "
            f"{100 * (amplitudes >= SD_LARGE).mean():.0f}%"
        )))
    ax.set_xlim(grid[0], grid[-1])
    ax.set_xticks([0, 2, 4, 8, 12])
    ax.set_xlabel("Event amplitude (raw-noise SD)")
    ax.set_ylim(bottom=0)
    ax.set_ylabel("Event density")
    ax.set_yticks([])
    ax.legend(handles=handles, loc="upper right", fontsize=5.6, handlelength=1.3,
              labelspacing=0.25, borderaxespad=0.1, title="Source: % < 2 SD, % ≥ 4 SD",
              title_fontsize=5.6, alignment="left")


def _draw_class_scatter(ax: Axes, inputs: Inputs, examples: dict[str, tuple[int, int]]) -> None:
    keys = set(examples.values())
    example = inputs.example
    rings = example[[key in keys for key in zip(example.dmd, example.roi, strict=True)]]
    usable = panels.usable(inputs.metrics)
    xlim = (0, np.ceil(100 * usable.frac_events_lt2sd.max() / 5) * 5)
    ylim = (np.floor(100 * usable.frac_events_gt4sd.min() / 10) * 10, 100)
    ax.set_gid("scatter")
    panels._draw_feature_space(ax, usable, "", rings, xlim, ylim)
    ax.set_ylabel("Synapse's events ≥ 4 SD (%)")
    ax.set_xlabel("Synapse's events < 2 SD (%)")


def _draw_amplitude_histogram(ax: Axes, inputs: Inputs) -> None:
    """Distribution of median event amplitude, split only by processing cohort."""
    usable = panels.usable(inputs.metrics)
    edges = AMPLITUDE_BINS
    for cohort in (False, True):
        values = usable.loc[usable.has_calcium.eq(cohort), AMPLITUDE].dropna().to_numpy(float)
        clipped = np.clip(values, edges[0], edges[-1])
        color = COHORT_COLORS[cohort]
        ax.hist(clipped, bins=edges, histtype="stepfilled", color=color, alpha=0.25, lw=0)
        ax.hist(clipped, bins=edges, histtype="step", color=color, lw=1,
                label=f"{COHORT_NAMES[cohort]} (n = {values.size:,})")
    median = noise_median(inputs)
    ax.axvline(median, color=panels.INK_2, lw=0.7, ls=(0, (3, 2)))
    ax.annotate(f"Noise-only\nmedian\n{median:.1f} SD", (median, 1.0),
                xycoords=ax.get_xaxis_transform(), xytext=(2, 0), textcoords="offset points",
                ha="left", va="top", fontsize=5.6, color=panels.INK_2)
    for dmd, roi in percentile_examples(inputs).values():
        rows = inputs.example.loc[(inputs.example.dmd == dmd) & (inputs.example.roi == roi)]
        value = float(rows[AMPLITUDE].iloc[0])
        ax.plot(value, 1.03, "v", ms=4, color=panels.INK, transform=ax.get_xaxis_transform(),
                clip_on=False)
        ax.annotate(str(roi), (value, 1.03), xycoords=ax.get_xaxis_transform(), xytext=(0, 3),
                    textcoords="offset points", ha="center", va="bottom", fontsize=5.6,
                    color=panels.INK)
    ax.set_xlim(edges[0], edges[-1])
    ax.set_xlabel(AMPLITUDE_LABEL)
    ax.set_ylabel("Synapses")
    ax.legend(loc="center right", fontsize=6, handlelength=1.2)


def _session_positions(table: pd.DataFrame) -> tuple[np.ndarray, pd.Series]:
    positions = np.arange(len(table), dtype=float)
    sessions = table.group.eq("Session")
    positions[sessions] += 1.5
    positions[sessions & table.has_calcium] += 1
    for index, (_, rows) in enumerate(table.loc[sessions].groupby("subject", sort=False)):
        positions[rows.index] += 0.35 * index
    return positions, sessions


def _session_axis(
    ax: Axes, table: pd.DataFrame, positions: np.ndarray, sessions: pd.Series,
) -> None:
    transform = ax.get_xaxis_transform()
    for (group, cohort), rows in table.groupby(["group", "has_calcium"], sort=False):
        kind = "DMDs" if group == "Compartment" else "sessions"
        ax.text(float(positions[rows.index].mean()), 1.14, f"{COHORT_NAMES[cohort]}\n{kind}",
                transform=transform, ha="center", va="bottom", fontsize=6, color=panels.INK,
                linespacing=1.2)
    for subject, rows in table.loc[sessions].groupby("subject", sort=False):
        x = positions[rows.index]
        ax.plot([x.min() - 0.4, x.min() - 0.4, x.max() + 0.4, x.max() + 0.4],
                [-0.47, -0.5, -0.5, -0.47], transform=transform, clip_on=False,
                color=panels.INK_2, lw=0.5)
        ax.text(float(x.mean()), -0.57, str(subject).removeprefix("sub-"), transform=transform,
                ha="center", va="top", fontsize=5.2, color=panels.INK_2)
    label_x = positions[sessions][0] - 1.6
    for text, y in (("Date", -0.24), ("Mouse ID", -0.6)):
        ax.text(label_x, y, text, transform=transform, ha="right", va="center", fontsize=6,
                color=panels.INK)
    ax.set_xticks(positions, table.label, rotation=60, ha="right", fontsize=5.5)
    ax.set_xlim(-0.6, positions[-1] + 0.6)


def _draw_session_amplitudes(ax: Axes, inputs: Inputs, norm) -> None:
    """Per-session sources with median and interquartile range, on the composition positions."""
    table = panels.class_composition_summary(inputs.metrics)
    usable = panels.usable(inputs.metrics)
    positions, sessions = _session_positions(table)
    rng = np.random.default_rng(0)
    limits = (2, 10)
    for position, row in zip(positions, table.itertuples(), strict=True):
        if row.group == "Compartment":
            subset = usable.loc[
                usable.has_calcium.eq(row.has_calcium) & usable.dmd.eq(int(row.label[-1]))
            ]
        else:
            subset = usable.loc[usable.session == row.session]
        values = subset[AMPLITUDE].dropna().to_numpy(float)
        ax.scatter(position + rng.uniform(-0.26, 0.26, size=values.size), np.clip(values, *limits),
                   s=1.2, c=panels.GRADIENT_CMAP(norm(values)), linewidths=0, alpha=0.65,
                   rasterized=True, zorder=2)
        low, median, high = np.percentile(values, [25, 50, 75])
        ax.plot([position, position], [low, high], color=panels.INK, lw=1.2, zorder=4,
                solid_capstyle="butt")
        ax.plot([position - 0.32, position + 0.32], [median, median], color=panels.INK, lw=1.2,
                zorder=4, solid_capstyle="butt")
    reference = noise_median(inputs)
    ax.axhline(reference, color=panels.INK_2, lw=0.6, ls=(0, (3, 2)), zorder=1)
    ax.text(positions[-1] + 0.6, reference, "Noise-only median", ha="right", va="bottom",
            fontsize=5.6, color=panels.INK_2)
    _session_axis(ax, table, positions, sessions)
    ax.set_ylim(*limits)
    ax.set_ylabel("Median event\namplitude (SD)")
    ax.grid(axis="y", alpha=0.7)
    ax.set_axisbelow(True)


def _draw_class_composition(ax: Axes, inputs: Inputs) -> None:
    table = panels.class_composition_summary(inputs.metrics)
    positions, sessions = _session_positions(table)
    base = np.zeros(len(table))
    for name in panels.CLASS_ORDER:
        values = table[name].to_numpy(dtype=float)
        ax.bar(positions, values, bottom=base, width=0.72, color=panels.CLASS_COLORS[name],
               edgecolor="white", linewidth=0.3)
        base += values
    _session_axis(ax, table, positions, sessions)
    ax.set_ylim(0, 100)
    ax.set_ylabel("Synapses (%)")
    ax.grid(axis="y", alpha=0.7)
    ax.set_axisbelow(True)


def _shared_rows(inputs: Inputs, examples: dict, norm=None) -> list[Row]:
    def first_map(ax: Axes) -> None:
        _draw_map(ax, inputs, 1, examples, norm)
        if norm is not None:
            _add_amplitude_colorbar(ax, norm)

    return [
        Row(1.1, 0.3, 0.42, (
            Panel(lambda ax: _draw_trace(ax, inputs), 4.3),
            Panel(lambda ax: _draw_footprint(ax, inputs), 1, gap=0.3, letter_offset=0.25),
        )),
        Row(1.55, 0.28, 0.05, (
            Panel(first_map, _map_size(inputs, 1)[1], letter_offset=0.3),
            Panel(lambda ax: _draw_map(ax, inputs, 2, examples, norm), _map_size(inputs, 2)[1],
                  gap=0.35, letter_offset=0.3),
        ), left=0.35),
    ]


def _variant_a_rows(inputs: Inputs) -> list[Row]:
    norm = panels.gradient_norm(panels.usable(inputs.metrics), AMPLITUDE)
    return [
        *_shared_rows(inputs, percentile_examples(inputs), norm),
        Row(1.45, 0.32, 0.42, (
            Panel(lambda ax: _draw_percentile_overlay(ax, inputs), 1),
            Panel(lambda ax: _draw_amplitude_histogram(ax, inputs), 1.15, gap=0.55),
        )),
        Row(1.15, 0.5, 1.0, (Panel(lambda ax: _draw_session_amplitudes(ax, inputs, norm), 1),)),
    ]


def _variant_b_rows(inputs: Inputs) -> list[Row]:
    examples = panels.class_examples(inputs.example)
    return [
        *_shared_rows(inputs, examples),
        Row(1.75, 0.3, 0.42, (
            Panel(lambda ax: _draw_class_overlay(ax, inputs, examples), 1),
            Panel(lambda ax: _draw_class_scatter(ax, inputs, examples), 1.1, gap=0.55),
        )),
        Row(1.05, 0.5, 1.0, (Panel(lambda ax: _draw_class_composition(ax, inputs), 1),)),
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


def _write_variant(rows: list[Row], output: Path, title: str, description: str) -> Path:
    fig = _compose(rows)
    panels.save_panel(fig, output.parent, output.stem, preview_png=False)
    svg = output.read_text(encoding="utf-8")
    opening = svg.index(">", svg.index("<svg")) + 1
    accessible = (
        f'<title id="title">{escape(title)}</title>'
        f'<desc id="description">{escape(description)}</desc>'
    )
    output.write_text(svg[:opening] + accessible + svg[opening:], encoding="utf-8", newline="\n")
    return output


def write_figure5_variants(
    variant_a: Path = VARIANT_A_OUTPUT, variant_b: Path = VARIANT_B_OUTPUT,
    *, directory: Path = DATA_DIR,
) -> tuple[Path, Path]:
    """Render both candidate layouts from committed inputs."""
    inputs = load_inputs(directory)
    shared = (
        "A shows one raw trace with detected events and an amplitude measurement; B its "
        "footprint; C and D the DMD1 and DMD2 dendritic maps of the example session, with scale "
        "bars. "
    )
    with mpl.rc_context():
        panels.set_style()
        written_a = _write_variant(
            _variant_a_rows(inputs), variant_a,
            "SLAP2 glutamate signal quality, candidate A: median event amplitude",
            shared + "Sources are colored by median event amplitude in raw-noise SD. E shows the "
            "event amplitudes of the sources at the 10th, 50th and 90th percentiles of that "
            "session, with a spectrum-matched noise-only curve; F the distribution across 2,521 "
            "sources in two processing cohorts; G the per-pool and per-session distributions.",
        )
        written_b = _write_variant(
            _variant_b_rows(inputs), variant_b,
            "SLAP2 glutamate signal quality, candidate B: k-means classes",
            shared + "Sources are colored by archive-wide k-means class. E overlays one example "
            "source from each class; F shows the archive in the below-2 versus at-least-4-SD "
            "event-fraction plane; G the class composition of pools and sessions.",
        )
    return written_a, written_b
