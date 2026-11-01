"""Offline, single-session standard-oddball diagnostics from Figure 9 inputs."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from xml.etree import ElementTree as ET

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np

from .figure_typography import (
    PDF_FIGURE_HEIGHT_MM,
    PDF_FIGURE_WIDTH_MM,
    SVG_NS,
    normalize_figure_svg,
)
from .image_encoding import canonical_svg_images
from .neural_response_figure import (
    DATA_PATH,
    PROVENANCE_PATH,
    REPO_ROOT,
    SOURCE_MEDIA_DIR,
    STATIC_EXAMPLE_GROUPS,
    float32_values,
    load_neuropixels_event_responses,
    uint16_values,
)

EVENTS = ("orientation_45", "orientation_90", "halt", "omission")
LABELS = ("45 deg", "90 deg", "Halt", "Omission")
SESSION_ID = "ecephys_830794_2026-01-27_11-25-31"
MIN_AREA_UNITS = 10
MODES = ("hz", "zscore")
Mode = Literal["hz", "zscore"]
OUTPUT_DIR = REPO_ROOT / "images" / "figures" / "generated"
AUDIT_DIR = REPO_ROOT / "figure_sources" / "derived" / "neuropixels-standard-oddball"
STAT_FIELDS = (
    "q1_p", "q1_q", "q1_modulation", "q1_trials",
    "q2_delta_p", "q2_delta_q", "q2_delta_modulation", "q2_trials", "q2_control_trials",
)
CONTEXT_COLOR = "#148f82"
CONTROL_COLOR = "#635aa5"


@dataclass
class Diagnostic:
    """Validated eligible units and decoded data in one shared anatomical order."""

    session: dict
    indices: list[int]
    areas: list[str]
    rates: np.ndarray
    baseline_mean: np.ndarray
    baseline_sd: np.ndarray
    statistics: dict[str, np.ndarray]

    @property
    def units(self) -> list[dict]:
        return [self.session["units"][index] for index in self.indices]


def qc_sua_unit(unit: dict) -> bool:
    """Require QC-passing SUA firing strictly above 1 Hz, regardless of anatomy."""
    return (
        unit["qcPass"]
        and unit["decoderLabel"] == "sua"
        and math.isfinite(unit["firingRateHz"])
        and unit["firingRateHz"] > 1.0
    )


def eligible_unit(unit: dict) -> bool:
    """Require Figure 9 visual membership, QC, SUA, and strictly more than 1 Hz."""
    return qc_sua_unit(unit) and any(
        groups <= set(unit["areaGroups"]) for _, groups in STATIC_EXAMPLE_GROUPS
    )


def _decode_statistic(session: dict, key: str) -> np.ndarray:
    descriptor = session["responsiveness"][key]
    shape = (4, session["unitCount"])
    values = np.asarray(float32_values(descriptor["base64"]), dtype=float)
    if descriptor.get("shape") != list(shape) or values.size != math.prod(shape):
        raise ValueError(f"Invalid standard-oddball statistic shape: {key}")
    values = values.reshape(shape)
    finite = values[np.isfinite(values)]
    if np.any(np.isinf(values)):
        raise ValueError(f"Infinite standard-oddball statistic: {key}")
    if key.endswith(("_p", "_q")) and np.any((finite < 0) | (finite > 1)):
        raise ValueError(f"Invalid standard-oddball probability: {key}")
    if key.endswith("trials") and (
        not np.all(np.isfinite(values)) or np.any(values < 0) or np.any(values % 1)
    ):
        raise ValueError(f"Invalid standard-oddball trial counts: {key}")
    return values


def analyze_session(
    session: dict, atlas: np.ndarray, *, visual_only: bool = True,
) -> Diagnostic:
    """Validate a standard session and retain eligible units without retesting."""
    if session["context"] != "standard" or tuple(e["id"] for e in session["events"]) != EVENTS:
        raise ValueError("Expected the four standard-oddball events in their original order.")
    units = session["units"]
    count = session["unitCount"]
    if len(units) != count or len({unit["id"] for unit in units}) != count:
        raise ValueError("Standard-oddball unit inventory is inconsistent.")
    if session["conditionOrder"] != ["context", "control"]:
        raise ValueError("Unexpected standard-oddball condition order.")
    time = np.asarray(session["timeBinCentersSeconds"])
    expected_shape = (4, 2, count, time.size)
    if (
        atlas.shape != expected_shape
        or session["sdfMeanAtlas"]["shape"] != list(expected_shape)
        or not np.all(np.isfinite(atlas))
        or np.any(atlas < 0)
        or time.size < 2
        or not np.all(np.diff(time) > 0)
    ):
        raise ValueError("Standard-oddball SDF atlas or time grid is invalid.")
    for event in session["events"]:
        if (
            event["cleanTrialCount"] + event["excludedAdjacentTrialCount"]
            != event["contextTrialCount"]
        ):
            raise ValueError("Standard-oddball trial counts are inconsistent.")
        for condition in ("context", "control"):
            windows = event["timing"][condition]["presentationWindows"]
            if not {-1, 0} <= {w["rowOffset"] for w in windows}:
                raise ValueError("Missing standard-oddball presentation windows.")
    indices = sorted(
        (i for i, unit in enumerate(units)
         if (eligible_unit(unit) if visual_only else qc_sua_unit(unit))),
        key=lambda i: (
            visual_group(units[i]) if visual_only else 0,
            units[i]["parentAreaGraphOrder"], units[i]["parentArea"],
            units[i]["depthUm"], units[i]["id"],
        ),
    )
    if not indices:
        raise ValueError("No QC-passing SUA firing strictly above 1 Hz.")
    area_orders: dict[str, int] = {}
    for i in indices:
        unit = units[i]
        area = unit["parentArea"]
        order = unit["parentAreaGraphOrder"]
        if not area or not math.isfinite(unit["depthUm"]):
            raise ValueError("Invalid eligible-unit anatomy.")
        if area in area_orders and area_orders[area] != order:
            raise ValueError(f"Inconsistent parent-area ontology order: {area}")
        area_orders[area] = order
    baselines = []
    for key in ("baselineMeanHzBase64", "baselineStdHzBase64"):
        values = np.asarray(float32_values(session[key]), dtype=float)
        if values.size != 8 * count:
            raise ValueError(f"Invalid standard-oddball baseline shape: {key}")
        baselines.append(values.reshape(4, 2, count)[:, :, indices])
    return Diagnostic(
        session, indices, list(area_orders),
        atlas[:, :, indices].astype(float) / session["sdfMeanAtlas"]["quantizationScalePerHz"],
        *baselines,
        {key: _decode_statistic(session, key)[:, indices] for key in STAT_FIELDS},
    )


def load_diagnostic(*, visual_only: bool = True) -> Diagnostic:
    """Load checksummed Figure 9 inputs without network access."""
    payload = load_neuropixels_event_responses()
    sessions = [s for s in payload["sessions"] if s["context"] == "standard"]
    if len(sessions) != 1 or sessions[0]["sessionId"] != SESSION_ID:
        raise ValueError("Expected the existing mouse 830794 standard session.")
    session = sessions[0]
    atlas = np.asarray(
        uint16_values(SOURCE_MEDIA_DIR / Path(session["sdfMeanAtlas"]["path"]).name)
    ).reshape(session["sdfMeanAtlas"]["shape"])
    return analyze_session(session, atlas, visual_only=visual_only)


def normalized_heatmaps(data: Diagnostic, mode: Mode) -> np.ndarray:
    """Normalize each condition independently, preserving unavailable rows."""
    delta = data.rates - data.baseline_mean[..., None]
    if mode == "hz":
        return np.where(np.isfinite(delta), delta, np.nan)
    if mode != "zscore":
        raise ValueError(f"Unknown normalization: {mode}")
    valid = np.isfinite(data.baseline_sd) & (data.baseline_sd > 0)
    result = np.full_like(delta, np.nan)
    np.divide(delta, data.baseline_sd[..., None], out=result, where=valid[..., None])
    result[~np.isfinite(result)] = np.nan
    return result


def population_means(data: Diagnostic) -> np.ndarray:
    """Average baseline-subtracted unit means equally within each visual group."""
    values = normalized_heatmaps(data, "hz")
    if not np.all(np.isfinite(values)):
        raise ValueError("Population mean requires finite per-unit baseline-subtracted SDFs.")
    groups = np.array([visual_group(unit) for unit in data.units])
    if any(not np.any(groups == group) for group in range(2)):
        raise ValueError("Both Figure 9 visual populations must be present.")
    return np.stack([values[:, :, groups == group].mean(axis=2) for group in range(2)])


def response_masks(
    p: np.ndarray, q: np.ndarray, modulation: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return testability, exploratory response, and stored-BH response masks."""
    if not (p.shape == q.shape == modulation.shape):
        raise ValueError("Response statistic shapes must agree.")
    tested = np.isfinite(p) & np.isfinite(modulation)
    effect = np.abs(modulation) > 0.1
    return tested, tested & (p < 0.05) & effect, tested & np.isfinite(q) & (q < 0.05) & effect


def test_masks(data: Diagnostic, test: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Apply the existing Q1 or baseline-subtracted Q2 screen."""
    if test not in ("q1", "q2_delta"):
        raise ValueError(f"Unknown response test: {test}")
    return response_masks(*(data.statistics[f"{test}_{key}"] for key in ("p", "q", "modulation")))


def visual_group(unit: dict) -> int:
    """Return Figure 9's cortical/thalamic group index; reject other areas."""
    for i, (_, groups) in enumerate(STATIC_EXAMPLE_GROUPS):
        if groups <= set(unit["areaGroups"]):
            return i
    raise ValueError(f"Unit {unit['id']} is outside Figure 9's visual groups.")


def joint_example_mask(data: Diagnostic) -> np.ndarray:
    """Require exploratory Q1 and baseline-subtracted Q2 for the same event."""
    return test_masks(data, "q1")[1] & test_masks(data, "q2_delta")[1]


def example_selections(data: Diagnostic) -> list[dict]:
    """Choose fixed layer/LGd examples passing Q1 and Q2 for the same event."""
    responsive = joint_example_mask(data)
    selections = []
    for label, number in (("VISp2/3", 1), ("VISp4", 1), ("VISp5", 1), ("LGd", 3)):
        candidates = []
        for i, unit in enumerate(data.units):
            if (unit["parentArea"] if label == "LGd" else unit["location"]) != label:
                continue
            events = np.flatnonzero(responsive[:, i])
            if events.size:
                event = min(events, key=lambda e: (-abs(data.statistics["q1_modulation"][e, i]), e))
                candidates.append((i, int(event)))
        candidates.sort(
            key=lambda item: (
                -abs(data.statistics["q1_modulation"][item[1], item[0]]),
                data.units[item[0]]["id"],
            )
        )
        if len(candidates) < number:
            raise ValueError(
                f"{label}: need {number} joint Q1/Q2 exploratory SUA, found {len(candidates)}."
            )
        for i, event in candidates[:number]:
            selections.append({
                "unit_id": data.units[i]["id"], "index": i, "label": label,
                "recorded_area": data.units[i]["location"], "event_id": EVENTS[event],
                "p": float(data.statistics["q1_p"][event, i]),
                "q": float(data.statistics["q1_q"][event, i]),
                "modulation": float(data.statistics["q1_modulation"][event, i]),
                "q2_p": float(data.statistics["q2_delta_p"][event, i]),
                "q2_q": float(data.statistics["q2_delta_q"][event, i]),
                "q2_modulation": float(data.statistics["q2_delta_modulation"][event, i]),
            })
    return selections


def example_indices(data: Diagnostic) -> list[int]:
    """Return the fixed six-example indices in layer/pooled-LGd order."""
    return [record["index"] for record in example_selections(data)]


def area_summaries(data: Diagnostic) -> list[dict]:
    """Count eligible and testable units by canonical parent, event, and test."""
    rows = []
    for test in ("q1", "q2_delta"):
        tested, exploratory, corrected = test_masks(data, test)
        for event, event_id in enumerate(EVENTS):
            for area in data.areas:
                members = np.array([unit["parentArea"] == area for unit in data.units])
                n = int(np.sum(tested[event] & members))
                row = {
                    "session_id": data.session["sessionId"], "event_id": event_id,
                    "test": test, "parent_area": area,
                    "eligible_units": int(members.sum()), "tested_units": n,
                    "non_testable_units": int(members.sum()) - n,
                    "p_responsive": int(np.sum(exploratory[event] & members)),
                    "bh_responsive": int(np.sum(corrected[event] & members)),
                    "displayable": n >= MIN_AREA_UNITS,
                }
                for screen in ("p", "bh"):
                    row[f"{screen}_fraction"] = row[f"{screen}_responsive"] / n if n else None
                rows.append(row)
    return rows


def _heatmap_display(values: np.ndarray, mode: Mode) -> dict:
    finite = np.abs(values[np.isfinite(values)])
    if not finite.size:
        raise ValueError(f"No finite heatmap samples for {mode}.")
    limit = 3.0 if mode == "zscore" else max(1.0, math.ceil(np.percentile(finite, 99)))
    return {
        "limit": limit,
        "limit_rule": "fixed +/-3" if mode == "zscore" else "ceil(pooled absolute 99th percentile)",
        "clipped_samples": int(np.sum(finite > limit)),
        "finite_samples": int(finite.size),
        "unavailable_samples": int(values.size - finite.size),
        "unavailable_rows_by_event_condition": np.all(~np.isfinite(values), axis=-1).sum(-1)
        .tolist(),
    }


def _shade_windows(ax: plt.Axes, event: dict, condition: str) -> None:
    windows = event["timing"][condition]["presentationWindows"]
    for window in windows:
        offset = window["rowOffset"]
        if offset in (-1, 0):
            ax.axvspan(
                window["startSeconds"], window["stopSeconds"],
                color="#e7c797" if offset == -1 else "#aaaaaa",
                alpha=0.25, linewidth=0,
            )
    ax.axvline(0, color="#555555", linewidth=0.6, linestyle="--")


def _render_svg(
    data: Diagnostic, mode: Mode, output: Path,
) -> dict:
    values = normalized_heatmaps(data, mode)
    display = _heatmap_display(values, mode)
    time = data.session["timeBinCentersSeconds"]
    counts = {area: sum(u["parentArea"] == area for u in data.units) for area in data.areas}
    starts = np.cumsum([0] + list(counts.values()))
    groups = np.array([visual_group(unit) for unit in data.units])
    rc = {
        "font.family": "DejaVu Sans", "font.size": 11,
        "svg.fonttype": "none", "svg.hashsalt": "standard-oddball-neuropixels",
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.linewidth": 0.5, "xtick.labelsize": 10, "ytick.labelsize": 10,
    }
    with mpl.rc_context(rc):
        fig = plt.figure(figsize=(12, 12), facecolor="white")
        grid = fig.add_gridspec(
            4, 4, left=0.14, right=0.91, top=0.885, bottom=0.145,
            height_ratios=[2.5, 2.5, 1.4, 1.4], hspace=0.6, wspace=0.35,
        )
        units_label = "baseline-subtracted Hz" if mode == "hz" else "baseline z-score"
        fig.suptitle("Standard oddball | visual populations | mouse 830794", y=0.982, fontsize=16)
        fig.text(
            0.14, 0.956, f"QC-passing SUA, firing >1 Hz | n={len(data.indices)} | {units_label}",
            fontsize=12,
        )
        cmap = mpl.colormaps["RdBu_r"].with_extremes(bad="#b9b9b9")
        for condition, condition_name in enumerate(("Context", "Matched control")):
            for event_index, event in enumerate(data.session["events"]):
                ax = fig.add_subplot(grid[condition, event_index])
                ax.set_gid(f"heatmap-{mode}-{condition}-{EVENTS[event_index]}")
                image = ax.imshow(
                    values[event_index, condition], aspect="auto", interpolation="none",
                    cmap=cmap, vmin=-display["limit"], vmax=display["limit"],
                    extent=(*data.session["windowSeconds"], len(data.indices), 0),
                )
                for boundary in starts[1:-1]:
                    ax.axhline(boundary, color="#333333", linewidth=0.35)
                ax.axhline(int(np.sum(groups == 0)), color="black", linewidth=1.5)
                ax.axvline(0, color="#333333", linewidth=0.6, linestyle="--")
                for window in event["timing"][("context", "control")[condition]][
                    "presentationWindows"
                ]:
                    if window["rowOffset"] in (-1, 0):
                        ax.plot(
                            [window["startSeconds"], window["stopSeconds"]], [-8, -8],
                            color="#a57330" if window["rowOffset"] == -1 else "#333333",
                            linewidth=2, clip_on=False,
                        )
                ax.set_xlim(data.session["windowSeconds"])
                ax.set_xticks([-0.5, 0, 0.5])
                ax.set_xlabel("Time from event (s)")
                large = [i for i, area in enumerate(data.areas) if counts[area] >= 10]
                ax.set_yticks(
                    [(starts[i] + starts[i + 1]) / 2 for i in large],
                    [f"{data.areas[i]} ({counts[data.areas[i]]})" for i in large]
                    if event_index == 0 else [],
                )
                ax.tick_params(axis="y", length=0, labelsize=9)
                if event_index == 0:
                    ax.set_ylabel(condition_name, labelpad=5)
                if condition == 0:
                    ax.set_title(
                        f"{LABELS[event_index]}\n"
                        f"{event['contextTrialCount']} context / "
                        f"{event['controlTrialCount']} control",
                        pad=15, fontsize=10,
                    )
        cax = fig.add_axes((0.93, 0.64, 0.014, 0.18))
        fig.colorbar(image, cax=cax, label=units_label, extend="both")
        fig.text(
            0.075, 0.91,
            "A", fontweight="bold", gid="panel-label-A",
        )
        means = population_means(data)
        for group, (name, _) in enumerate(STATIC_EXAMPLE_GROUPS):
            for event_index, event in enumerate(data.session["events"]):
                ax = fig.add_subplot(grid[2 + group, event_index])
                ax.set_gid(f"population-mean-{group}-{EVENTS[event_index]}")
                _shade_windows(ax, event, "context")
                for condition, color in enumerate((CONTEXT_COLOR, CONTROL_COLOR)):
                    ax.plot(
                        time, means[group, event_index, condition], color=color,
                        linewidth=1.2, label=("Context", "Control")[condition],
                    )
                ax.axhline(0, color="#555555", linewidth=0.4)
                ax.set_xlim(data.session["windowSeconds"])
                ax.set_xticks([-0.5, 0, 0.5])
                ax.set_xlabel("Time from event (s)")
                ax.set_ylim(
                    min(0, float(means[group].min())) - 0.3,
                    max(0, float(means[group].max())) + 0.3,
                )
                if event_index == 0:
                    ax.set_ylabel("Delta firing rate (Hz)")
                    ax.set_title(f"{name}, n={np.sum(groups == group)}", fontsize=10)
                    fig.text(
                        0.075, ax.get_position().y1 + 0.015, ("B", "C")[group],
                        fontweight="bold", gid=f"panel-label-{('B', 'C')[group]}",
                    )
                    if group == 0:
                        fig.legend(
                            *ax.get_legend_handles_labels(), loc="upper right",
                            bbox_to_anchor=(0.97, 0.95), fontsize=10, ncol=2, frameon=False,
                        )
        clipped = display["clipped_samples"] / display["finite_samples"]
        footer = [
            "A: all eligible visual SUA, same rows throughout; cortex above thick line, "
            "visual thalamus below. LGv: n=3.",
            f"Heatmaps clipped at +/-{display['limit']:g} "
            f"({'Hz' if mode == 'hz' else 'z'}); {clipped:.2%} of finite samples clipped. "
            "Gray = unavailable baseline.",
            "B/C: visual cortex / visual thalamus; equal-unit means of baseline-subtracted "
            "trial-mean SDFs (Hz), not trial SEM.",
            "Tan = preceding presentation; gray = event window. "
            "All-trial population traces; example gallery uses clean context trials.",
            "No responsiveness filter for populations; Q1/Q2 area panels intentionally omitted.",
        ]
        for i, line in enumerate(footer):
            fig.text(0.06, 0.075 - i * 0.0105, line, fontsize=9)
    description = (
        f"Mouse 830794, {len(data.indices)} QC-passing SUA firing strictly above 1 Hz. "
        "Four events: 45 degree orientation, 90 degree orientation, halt, omission. "
        "A: anatomically ordered context and control heatmaps. "
        "B: visual-cortex population mean. C: visual-thalamus population mean. "
        "All eligible units weighted equally. These are unit heatmaps, not trial rasters. "
        "Stored population traces average all trials; the separate example gallery uses clean "
        "context trials. No area-responsiveness panels."
    )
    save_diagnostic_svg(
        fig, output, f"Neuropixels visual standard oddball: {units_label}", description,
        {"data-normalization": mode, "data-unit-order": ",".join(str(u["id"]) for u in data.units)},
    )
    return display


def save_diagnostic_svg(
    fig: plt.Figure, output: Path, title: str, description: str, attributes: dict[str, str],
    *, target_width_mm: float = PDF_FIGURE_WIDTH_MM,
    target_height_mm: float = PDF_FIGURE_HEIGHT_MM,
) -> None:
    """Write deterministic, accessible SVGs with shared editable typography."""
    buffer = io.StringIO()
    with mpl.rc_context({"svg.fonttype": "none", "svg.hashsalt": "standard-oddball-neuropixels"}):
        fig.savefig(buffer, format="svg", metadata={"Date": None, "Creator": "OpenScope P3"})
    plt.close(fig)
    root = ET.fromstring(normalize_figure_svg(
        canonical_svg_images(buffer.getvalue()), target_width_mm=target_width_mm,
        target_height_mm=target_height_mm,
    ))
    root.set("role", "img")
    root.set("aria-labelledby", "oddball-title oddball-description")
    root.attrib.update(attributes)
    for tag, text in (("title", title), ("desc", description)):
        element = ET.Element(
            f"{{{SVG_NS}}}{tag}", id=f"oddball-{'title' if tag == 'title' else 'description'}",
        )
        element.text = text
        root.insert(0, element)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(ET.tostring(root, encoding="unicode") + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f"Refusing to write an empty audit table: {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_standard_oddball_diagnostic(
    output_dir: Path = OUTPUT_DIR, audit_dir: Path = AUDIT_DIR,
) -> list[Path]:
    """Write both deterministic static variants, audit tables, and provenance."""
    data = load_diagnostic()
    from .standard_oddball_examples import load_example_spikes, render_example_gallery

    example_payload = load_example_spikes(data)
    summary = area_summaries(data)
    examples = example_indices(data)
    audit_dir.mkdir(parents=True, exist_ok=True)
    units_path = audit_dir / "unit-statistics.csv"
    areas_path = audit_dir / "area-responsiveness.csv"
    unit_rows = []
    masks = {test: test_masks(data, test) for test in ("q1", "q2_delta")}
    for event_index, event in enumerate(EVENTS):
        for i, unit in enumerate(data.units):
            row = {
                "session_id": data.session["sessionId"], "event_id": event,
                "unit_id": unit["id"], "parent_area": unit["parentArea"],
                "recorded_area": unit["location"], "probe": unit["probe"],
                "qc_pass": unit["qcPass"], "decoder_label": unit["decoderLabel"],
                "firing_rate_hz": unit["firingRateHz"], "heatmap_row": i,
                "selected_example": i in examples,
            }
            for key, values in data.statistics.items():
                value = float(values[event_index, i])
                row[key] = value if math.isfinite(value) else None
            for test, values in masks.items():
                for name, mask in zip(
                    ("testable", "p_responsive", "bh_responsive"), values, strict=True,
                ):
                    row[f"{test}_{name}"] = bool(mask[event_index, i])
            unit_rows.append(row)
    _write_csv(units_path, unit_rows)
    _write_csv(areas_path, summary)
    paths = []
    displays = {}
    for mode in MODES:
        path = output_dir / (
            "neuropixels-standard-oddball-baseline-"
            f"{'hz' if mode == 'hz' else 'zscore'}.svg"
        )
        displays[mode] = _render_svg(data, mode, path)
        paths.append(path)
    gallery_paths = render_example_gallery(
        data, example_payload, output_dir / "neuropixels-standard-oddball-examples",
    )
    comparison_paths = []
    for tau_ms in (20, 25):
        comparison_paths.extend(render_example_gallery(
            data, example_payload,
            output_dir / "neuropixels-standard-oddball-examples" / "smoothing-comparison",
            bin_seconds=0.005, tau_seconds=tau_ms / 1000,
            filename_suffix=f"-5ms-tau{tau_ms}ms",
        ))
    sources = [
        DATA_PATH, PROVENANCE_PATH,
        SOURCE_MEDIA_DIR / Path(data.session["sdfMeanAtlas"]["path"]).name,
        Path(__file__), Path(__file__).with_name("neural_response_figure.py"),
        Path(__file__).with_name("figure_typography.py"),
        Path(__file__).with_name("image_encoding.py"),
        Path(__file__).with_name("standard_oddball_examples.py"),
        REPO_ROOT / "figure_sources/data/neuropixels-standard-oddball-examples.json",
        REPO_ROOT / "figure_sources/data/neuropixels-standard-oddball-examples.provenance.json",
    ]
    provenance = {
        "version": 2, "session_id": data.session["sessionId"],
        "subject": data.session["subject"], "asset": data.session["asset"],
        "sources": [
            {"path": str(path.relative_to(REPO_ROOT)), "sha256": _sha256(path)}
            for path in sources
        ],
        "unit_filter": (
            "Figure 9 visual groups; qcPass and decoderLabel == sua and firingRateHz > 1"
        ),
        "eligible_units": len(data.indices), "total_recorded_units": data.session["unitCount"],
        "parent_areas": data.areas,
        "tests": {
            "q1": "paired Wilcoxon; raw-rate MI; deviant vs preceding standard",
            "q2_delta": "two-sided Mann-Whitney U; baseline-subtracted responses and MI",
            "thresholds": "p < 0.05 or stored BH q < 0.05, and abs(MI) > 0.1",
            "bh_family": "original all-recorded-unit per-event per-test; not recomputed",
            "denominator": "eligible units with finite p and MI, separately per event/test",
            "area_panel": "omitted; area audit table retained",
        },
        "trial_sets": [
            {key: event[key] for key in (
                "id", "contextTrialCount", "controlTrialCount", "cleanTrialCount",
                "excludedAdjacentTrialCount",
            )}
            for event in data.session["events"]
        ],
        "trace_caveat": (
            "population: all trials; example raster and mean: identical clean trials"
        ),
        "baseline_sd": "across 20 ms baseline rate bins, not trial uncertainty",
        "normalization": {
            "hz": "SDF minus condition-specific baseline mean",
            "zscore": "(SDF minus condition-specific baseline mean) / condition-specific SD",
            "invalid_baseline": "unavailable rows retained and drawn gray, never set to zero",
        },
        "display": displays,
        "example_selection": example_selections(data),
        "example_smoothing": {
            "default": {"bin_seconds": 0.0025, "tau_seconds": 0.01},
            "comparisons": [
                {"bin_seconds": 0.005, "tau_seconds": tau / 1000} for tau in (20, 25)
            ],
            "kernel_support": "ten time constants; normalized causal exponential",
            "statistics": "display only; trial selection and Q1/Q2 tests unchanged",
        },
        "example_unit_ids": [
            data.units[i]["id"] for i in examples
        ],
        "outputs": [
            {"name": path.name, "sha256": _sha256(path)}
            for path in [*paths, *gallery_paths, *comparison_paths, units_path, areas_path]
        ],
        "software": {"numpy": np.__version__, "matplotlib": mpl.__version__},
    }
    provenance_path = audit_dir / "provenance.json"
    provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    return [*gallery_paths, *paths, units_path, areas_path, *comparison_paths, provenance_path]


if __name__ == "__main__":
    for output in build_standard_oddball_diagnostic():
        print(f"Wrote {output}")
