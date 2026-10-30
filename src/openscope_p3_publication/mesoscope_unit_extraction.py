"""Editable mesoscope quality figure from the unchanged, committed QC cohort."""

from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import patheffects
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Patch

from openscope_p3_publication.figure_typography import SVG_NS, normalize_figure_svg
from openscope_p3_publication.image_encoding import canonical_svg_images

ROOT = Path(__file__).resolve().parents[2]
PROVENANCE = ROOT / "figure_sources" / "data" / "mesoscope-unit-extraction.provenance.json"
SESSION = "839909_2026-02-26"
PLANE = "VISp_1"
TRACE_ROI = 84
CLASS_ORDER = ["Low SNR", "Intermediate", "High SNR"]
CLASS_COLORS = {"Low SNR": "#E69F00", "Intermediate": "#56B4E9", "High SNR": "#009E73"}
FRACTIONS = ["frac_events_lt2sd", "frac_events_2_4sd", "frac_events_gt4sd"]
DEPTH_ORDER = ["\u2264150", "151\u2013250", "251\u2013350", ">350"]
INK, MUTED, ORANGE = "#242424", "#52514e", "#eb6834"


def decode_plane(plane: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """Decode the saved quantized excerpts without smoothing or interpolation."""
    shape = (plane["nRois"], plane["excerptFrames"])
    dff = np.frombuffer(base64.b64decode(plane["dffBase64"]), dtype="<i2")
    events = np.frombuffer(base64.b64decode(plane["eventsBase64"]), dtype="<i2")
    return (
        (dff.astype(np.float32) * plane["dffScale"]).reshape(shape),
        (events.astype(np.float32) * plane["eventsScale"]).reshape(shape),
    )


def build_planes(
    payload: dict[str, Any], cls_lookup: dict[tuple[str, int], str],
) -> list[dict[str, Any]]:
    """Join saved ROI masks to archived cohort classes, never refitting them."""
    planes = []
    for plane in payload["planes"]:
        runs = np.frombuffer(base64.b64decode(plane["maskRunsBase64"]), dtype="<u2")
        offsets = plane["maskRunOffsets"]
        labels = np.full((plane["imageHeight"], plane["imageWidth"]), -1, dtype=np.int32)
        classes = {}
        for index, roi in enumerate(plane["rois"]):
            for k in range(offsets[index], offsets[index + 1], 3):
                row, col, length = (int(value) for value in runs[k:k + 3])
                labels[row, col:col + length] = index
            classes[index] = cls_lookup.get((plane["plane"], roi["roi_index"]))
        planes.append({
            "plane": plane["plane"], "depth": plane["depthUm"], "n": plane["nRois"],
            "projection": mpl.image.imread(io.BytesIO(base64.b64decode(plane["projectionPng"]))),
            "labels": labels, "roi_class": classes, "raw": plane,
        })
    return planes


def onsets(events: np.ndarray) -> np.ndarray:
    """Locate positive runs in the saved OASIS series, not new detections."""
    result = np.zeros(events.shape, dtype=bool)
    result[1:] = (events[1:] > 0) & (events[:-1] <= 0)
    result[0] = events[0] > 0
    return result


def pick_example(planes: list[dict[str, Any]]) -> tuple:
    """Retain the original brightest-firing, mid-sized High SNR trace selection."""
    best = None
    for plane in planes:
        dff, events = decode_plane(plane["raw"])
        for index, roi in enumerate(plane["raw"]["rois"]):
            if plane["roi_class"][index] != "High SNR":
                continue
            count = int((events[index] > 0).sum())
            if 150 <= roi["roi_area_pix"] <= 450 and (best is None or count > best[0]):
                best = (count, plane, index, roi, dff[index], events[index])
    if best is None:
        raise ValueError("No mid-sized High SNR ROI is available for the example trace.")
    return best


def load_cohort(path: Path) -> pd.DataFrame:
    """Read the archived classifications with their original grouping dtypes."""
    cohort = pd.read_csv(path, dtype={"session": str, "subject_id": str, "acq_date": str})
    cohort["depth_bin"] = pd.Categorical(
        cohort["depth_bin"], categories=DEPTH_ORDER, ordered=True,
    )
    return cohort


def shares(frame: pd.DataFrame, key: str) -> pd.DataFrame:
    """Return original ROI-weighted class percentages and denominators."""
    table = (
        frame.groupby(key, observed=True)["amp_threshold_quality_class"]
        .value_counts(normalize=True).unstack().reindex(columns=CLASS_ORDER).fillna(0) * 100
    )
    table["n"] = frame.groupby(key, observed=True).size()
    return table


def panel_inputs(cohort: pd.DataFrame) -> dict[str, Any]:
    """Preserve the area, depth, session, and mouse summaries of the original figure."""
    metadata = cohort.groupby("session").agg(
        subject=("subject_id", "first"), date=("acq_date", "first"),
    )
    sessions = shares(cohort, "session").join(metadata).sort_values(
        ["subject", "date"],
    ).reset_index()
    mice = shares(cohort, "subject_id")
    mice["n_sessions"] = cohort.groupby("subject_id")["session"].nunique()
    return {
        "by_area": shares(cohort, "structure").reindex(["VISp", "VISl"]),
        "by_depth": shares(cohort, "depth_bin"),
        "by_session": sessions, "by_mouse": mice,
        "counts": {
            "sessions": cohort["session"].nunique(), "mice": cohort["subject_id"].nunique(),
            "rois": len(cohort),
            "per_class": cohort["amp_threshold_quality_class"].value_counts().to_dict(),
        },
    }


def load_publication_inputs(
    provenance_path: Path = PROVENANCE,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Verify both committed data snapshots before rendering offline."""
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    paths = {}
    for name in ("source_table", "example_payload"):
        record = provenance[name]
        path = ROOT / record["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError(f"Mesoscope {name} does not match its provenance checksum.")
        paths[name] = path
    cohort = load_cohort(paths["source_table"])
    counts = panel_inputs(cohort)["counts"]
    expected = provenance["cohort"]
    if any(counts[key] != expected[key] for key in ("rois", "sessions", "mice")):
        raise ValueError("Mesoscope cohort counts do not match the recorded cohort.")
    if counts["per_class"] != expected["classes"]:
        raise ValueError("Mesoscope archived class counts do not match provenance.")
    return cohort, json.loads(paths["example_payload"].read_bytes())


def class_examples(cohort: pd.DataFrame) -> dict[str, pd.Series]:
    """Choose one example per class in the displayed FOV, near the cohort centroid."""
    plane = cohort.loc[cohort.session.eq(SESSION) & cohort.plane.eq(PLANE)]
    examples = {}
    for cls in CLASS_ORDER:
        candidates = plane.loc[plane.amp_threshold_quality_class.eq(cls)]
        if candidates.empty:
            raise ValueError(f"The displayed mesoscope FOV has no {cls} example.")
        centroid = cohort.loc[cohort.amp_threshold_quality_class.eq(cls), FRACTIONS].mean()
        distance = np.linalg.norm(candidates[FRACTIONS].values - centroid.values, axis=1)
        examples[cls] = candidates.iloc[int(distance.argmin())]
    return examples


def _bare(axis: Axes) -> None:
    axis.spines[["top", "right"]].set_visible(False)
    axis.grid(False)
    axis.tick_params(colors=MUTED)


def _letter(figure: Figure, axis: Axes, letter: str) -> None:
    bounds = axis.get_position()
    figure.text(max(0.015, bounds.x0 - 0.075), bounds.y1 + 0.008, letter,
                fontsize=10, fontweight="bold", va="bottom", color=INK,
                gid=f"panel-label-{letter}")


def _mark_example(axis: Axes, x: float, y: float, roi: int) -> None:
    identifier = f"{axis.get_gid()}-example-{roi}"
    axis.plot(x, y, "o", ms=7, mfc="none", mec="white", mew=0.9, zorder=6,
              gid=identifier,
              path_effects=[patheffects.Stroke(linewidth=2, foreground=INK),
                            patheffects.Normal()])
    axis.annotate(str(roi), (x, y), xytext=(6, 6), textcoords="offset points",
                  fontsize=6.5, color="white", zorder=7, gid=f"{identifier}-label",
                  bbox={"facecolor": INK, "alpha": 0.8, "edgecolor": "none", "pad": 1})


def make_mesoscope_figure(cohort: pd.DataFrame, payload: dict[str, Any]) -> Figure:
    """Build the compact A-I layout without changing any input values or class fits."""
    selected = [plane for plane in payload["planes"] if plane["plane"] == PLANE]
    if len(selected) != 1:
        raise ValueError(f"Expected one saved {PLANE} FOV.")
    session = cohort.loc[cohort.session.eq(SESSION)]
    lookup = {(row.plane, int(row.roi_index)): row.amp_threshold_quality_class
              for row in session.itertuples()}
    plane, = build_planes({"planes": selected}, lookup)
    if any(cls not in CLASS_ORDER for cls in plane["roi_class"].values()):
        raise ValueError("A displayed mesoscope ROI has no archived cohort class.")
    trace_index = next((i for i, roi in enumerate(plane["raw"]["rois"])
                        if roi["roi_index"] == TRACE_ROI), None)
    if trace_index is None:
        raise ValueError(f"The displayed mesoscope FOV has no trace ROI {TRACE_ROI}.")
    trace_roi = plane["raw"]["rois"][trace_index]
    dff, saved_events = decode_plane(plane["raw"])
    trace, events = dff[trace_index], saved_events[trace_index]
    examples = class_examples(cohort)
    inputs = panel_inputs(cohort)
    figure = plt.figure(figsize=(7.2, 8.2))
    outer = figure.add_gridspec(
        5, 1, height_ratios=[1, 0.65, 1.65, 1.3, 1.05],
        hspace=0.65, left=0.10, right=0.975, top=0.945, bottom=0.075,
    )

    top = outer[0].subgridspec(1, 2, width_ratios=[4.2, 1.1], wspace=0.23)
    axis = figure.add_subplot(top[0])
    axis.set_gid("mesoscope-example-trace")
    times = np.arange(plane["raw"]["excerptFrames"]) * plane["raw"]["dtSeconds"]
    noise = trace_roi["baseline_noise_sd"]
    axis.axhspan(-3 * noise, 3 * noise, color="#b6b5b0", alpha=0.25, lw=0,
                 gid="mesoscope-noise-reference")
    axis.plot(times, trace, lw=0.5, color=MUTED)
    height = float(np.nanmax(trace))
    detected = onsets(events)
    marker_y = height * 1.13
    axis.scatter(times[detected], np.full(detected.sum(), marker_y),
                 marker="v", s=6, color=ORANGE, lw=0)
    if not detected.any():
        raise ValueError("The saved mesoscope trace contains no OASIS onset.")
    example_time = times[detected][np.argmin(np.abs(times[detected] - times[-1] / 2))]
    axis.annotate("detected event", (example_time, marker_y), xytext=(0, 5),
                  textcoords="offset points", color=ORANGE, fontsize=6.5,
                  ha="center", va="bottom")
    axis.text(0.99, -2 * noise, "\u00b13 baseline-noise SD",
              transform=axis.get_yaxis_transform(), ha="right", va="center",
              fontsize=6.5, color=MUTED)
    axis.set(xlim=(times[0], times[-1]), ylim=(-3 * noise - 0.15 * height, height * 1.5),
             xlabel="Time (s, from excerpt start)", ylabel="\u0394F/F")
    _bare(axis)
    _letter(figure, axis, "A")

    footprint = figure.add_subplot(top[1])
    _letter(figure, footprint, "B")
    slot = top[1].get_position(figure)
    right = axis.get_position().x1
    footprint.set_position([right, slot.y0, outer.right - right, slot.height])
    footprint.set_gid("mesoscope-single-roi-footprint")
    ys, xs = np.nonzero(plane["labels"] == trace_index)
    crop = (slice(max(0, ys.min() - 30), min(plane["labels"].shape[0], ys.max() + 30)),
            slice(max(0, xs.min() - 30), min(plane["labels"].shape[1], xs.max() + 30)))
    footprint.imshow(plane["projection"][crop], cmap="gray", interpolation="nearest")
    footprint.set_aspect("equal", adjustable="datalim")
    footprint.contour((plane["labels"] == trace_index)[crop], levels=[0.5],
                      colors=[ORANGE], linewidths=0.65)
    footprint.set_axis_off()

    class_row = outer[1].subgridspec(1, 3, wspace=0.35)
    for index, cls in enumerate(reversed(CLASS_ORDER)):
        axis = figure.add_subplot(class_row[index])
        axis.set_gid(f"mesoscope-fractions-{cls.lower().replace(' ', '-')}")
        row = examples[cls]
        values = row[FRACTIONS].to_numpy(dtype=float)[[0, 2]] * 100
        axis.bar(np.arange(2), values, color=CLASS_COLORS[cls], width=0.62, lw=0)
        for x, value in enumerate(values):
            axis.text(x, value + 3, f"{value:.0f}%", ha="center", va="bottom", fontsize=6.5)
        axis.set(ylim=(0, 100), xticks=[0, 1], xticklabels=["<2", ">4"],
                 yticks=[0, 50, 100])
        axis.set_title(f"{cls} - ROI {int(row.roi_index)}", loc="left", fontsize=7, pad=4)
        if index == 0:
            axis.set_ylabel("Events (%)")
        else:
            axis.tick_params(labelleft=False)
        _bare(axis)
        _letter(figure, axis, "CDE"[index])
    bounds = outer[1].get_position(figure)
    figure.text((bounds.x0 + bounds.x1) / 2, bounds.y0 - 0.035,
                "OASIS event amplitude (baseline-noise SD)", ha="center", fontsize=7)

    middle = outer[2].subgridspec(1, 2, width_ratios=[1, 2], wspace=0.5)
    field = figure.add_subplot(middle[0])
    field.set_gid("mesoscope-single-fov")
    _letter(figure, field, "F")
    field.imshow(plane["projection"], cmap="gray", interpolation="nearest")
    for cls in CLASS_ORDER:
        members = [index for index, value in plane["roi_class"].items() if value == cls]
        mask = np.isin(plane["labels"], members)
        rgba = np.zeros((*mask.shape, 4))
        rgba[mask] = mpl.colors.to_rgba(CLASS_COLORS[cls], 0.5)
        field.imshow(rgba, interpolation="nearest", gid=f"mesoscope-filled-{cls}")
        field.contour(mask, levels=[0.5], colors=[CLASS_COLORS[cls]], linewidths=0.35)
    for row in examples.values():
        index = next(i for i, roi in enumerate(plane["raw"]["rois"])
                     if roi["roi_index"] == int(row.roi_index))
        y, x = np.argwhere(plane["labels"] == index).mean(axis=0)
        _mark_example(field, float(x), float(y), int(row.roi_index))
    field.set_title(f"{plane['raw']['structure']} - {plane['depth']:.0f} \u00b5m",
                    loc="left", fontsize=7, pad=5)
    field.set(xlim=(-32, plane["labels"].shape[1] + 32),
              ylim=(plane["labels"].shape[0] + 32, -32))
    field.set_anchor("N")
    field.set_axis_off()

    scatter = figure.add_subplot(middle[1])
    scatter.set_gid("mesoscope-cohort-feature-space")
    for cls in CLASS_ORDER:
        rows = cohort.loc[cohort.amp_threshold_quality_class.eq(cls)]
        scatter.scatter(rows.frac_events_lt2sd * 100, rows.frac_events_gt4sd * 100,
                        s=1, lw=0, alpha=0.45, color=CLASS_COLORS[cls], rasterized=True)
    for row in examples.values():
        _mark_example(scatter, float(row.frac_events_lt2sd * 100),
                      float(row.frac_events_gt4sd * 100), int(row.roi_index))
    scatter.set(xlim=(0, 100), ylim=(0, 100),
                xlabel="Events <2 SD (%)", ylabel="Events >4 SD (%)")
    scatter.legend(handles=[Patch(facecolor=CLASS_COLORS[cls], label=cls)
                            for cls in CLASS_ORDER],
                   loc="upper right", frameon=False, fontsize=6.5, handlelength=1)
    _bare(scatter)
    _letter(figure, scatter, "G")

    composition = figure.add_subplot(outer[3])
    composition.set_gid("mesoscope-shared-composition")
    groups = [
        ("Cortical area", inputs["by_area"]),
        ("Depth (\u00b5m)", inputs["by_depth"]),
        ("Mouse ID", inputs["by_mouse"]),
    ]
    position = 0
    ticks, labels = [], []
    for title, table in groups:
        x = np.arange(len(table)) + position
        bottom = np.zeros(len(table))
        for cls in CLASS_ORDER:
            composition.bar(x, table[cls], bottom=bottom, color=CLASS_COLORS[cls],
                            width=0.76, edgecolor="white", linewidth=0.25)
            bottom += table[cls].to_numpy()
        composition.text(float(x.mean()), 1.12, title,
                         transform=composition.get_xaxis_transform(),
                         ha="center", va="bottom", fontsize=7)
        ticks.extend(x)
        labels.extend(str(label) for label in table.index)
        position += len(table) + 1
    composition.set(ylim=(0, 100), ylabel="ROIs (%)", xticks=ticks, xticklabels=labels,
                    xlim=(-0.7, ticks[-1] + 0.7), yticks=[0, 50, 100])
    composition.tick_params(axis="x", labelrotation=60, labelsize=6.5)
    _bare(composition)
    _letter(figure, composition, "H")

    spread = figure.add_subplot(outer[4])
    spread.set_gid("mesoscope-session-spread")
    rng = np.random.default_rng(0)
    mice = inputs["by_mouse"].index
    for index, mouse in enumerate(mice):
        rows = inputs["by_session"].loc[inputs["by_session"].subject.eq(mouse)]
        values = rows["High SNR"].to_numpy()
        spread.scatter(index + rng.uniform(-0.17, 0.17, len(values)), values,
                       s=8, lw=0, color="black")
        spread.plot([index - 0.28, index + 0.28], [np.median(values)] * 2,
                    color=INK, lw=0.7, solid_capstyle="butt")
    spread.set(xlim=(-0.6, len(mice) - 0.4), ylim=(0, 50), ylabel="High SNR ROIs\nper session (%)",
               xticks=np.arange(len(mice)), xticklabels=list(mice), xlabel="Mouse ID",
               yticks=[0, 25, 50])
    spread.tick_params(axis="x", labelsize=6.5)
    _bare(spread)
    _letter(figure, spread, "I")
    return figure


def write_mesoscope_unit_extraction_svg(output: Path) -> Path:
    """Render the canonical editable figure offline with final-size publication typography."""
    cohort, payload = load_publication_inputs()
    style = {
        "font.family": "DejaVu Sans", "font.size": 7.5, "axes.labelsize": 7.5,
        "axes.linewidth": 0.5, "axes.edgecolor": MUTED, "text.color": INK,
        "xtick.labelsize": 6.5, "ytick.labelsize": 6.5,
        "xtick.major.width": 0.5, "ytick.major.width": 0.5,
        "xtick.major.size": 2.5, "ytick.major.size": 2.5,
        "svg.fonttype": "none", "svg.hashsalt": "openscope-mesoscope-quality",
        "savefig.bbox": None,
    }
    with mpl.rc_context(style):
        figure = make_mesoscope_figure(cohort, payload)
        try:
            buffer = io.StringIO()
            figure.savefig(buffer, format="svg", dpi=250, metadata={"Date": None})
            root = ET.fromstring(canonical_svg_images(buffer.getvalue()))
            root.set("role", "img")
            root.set("aria-labelledby", "mesoscope-title mesoscope-description")
            title = ET.Element(f"{{{SVG_NS}}}title", id="mesoscope-title")
            title.text = "Mesoscope event-amplitude signal quality"
            description = ET.Element(f"{{{SVG_NS}}}desc", id="mesoscope-description")
            description.text = (
                "A raw trace and B individual footprint; C-E archived event fractions; "
                f"F one VISp field of view; G all {len(cohort):,} cohort ROIs; "
                "H shared area, depth, and mouse compositions; "
                f"I all {cohort.session.nunique()} sessions from "
                f"{cohort.subject_id.nunique()} mice, with mouse medians. "
                "Three archived quality classes are retained without refitting."
            )
            root.insert(0, title)
            root.insert(1, description)
            svg = normalize_figure_svg(ET.tostring(root, encoding="unicode"))
        finally:
            plt.close(figure)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(svg, encoding="utf-8", newline="\n")
    return output
