"""Recorded trial spikes and raster galleries for selected standard-oddball SUA."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np

from .mismatch_responsiveness import clean_trial_mask
from .neural_responses import (
    SDF_SOURCE_BIN_SECONDS,
    SDF_TAU_SECONDS,
    context_event_definitions,
    event_indices,
    neural_baseline_windows,
    sdf_kernel,
)
from .standard_oddball_neuropixels import (
    CONTEXT_COLOR,
    CONTROL_COLOR,
    DATA_PATH,
    EVENTS,
    LABELS,
    REPO_ROOT,
    Diagnostic,
    example_selections,
    joint_example_mask,
    save_diagnostic_svg,
)

EXAMPLES_PATH = DATA_PATH.with_name("neuropixels-standard-oddball-examples.json")
EXAMPLES_PROVENANCE = EXAMPLES_PATH.with_suffix(".provenance.json")
# Retain enough native-bin history for the optional 25 ms smoothing comparison.
PADDING_BINS = len(sdf_kernel(tau_seconds=0.025)) - 1
WINDOW = (-0.75, 0.75)
SOURCE_START = WINDOW[0] - PADDING_BINS * SDF_SOURCE_BIN_SECONDS
SELECTION_RULE = (
    "one per VISp2/3, VISp4, VISp5; three pooled LGd; largest abs(Q1 MI) among "
    "events passing BOTH Q1 and baseline-subtracted Q2, each with p < 0.05 and abs(MI) > 0.1 "
    "for the SAME event; ties by unit ID; exploratory, not BH-selected"
)


def example_trial_records(
    tables: dict[str, dict[str, np.ndarray]], *, event_ids: tuple[str, ...] = EVENTS,
) -> list[dict]:
    """Align trial IDs/windows using existing standard-oddball inclusion rules."""
    events = []
    if not event_ids or len(set(event_ids)) != len(event_ids) or not set(event_ids) <= set(EVENTS):
        raise ValueError("Expected distinct standard-oddball event IDs.")
    for definition in context_event_definitions("standard"):
        if definition.id not in event_ids:
            continue
        conditions = {}
        for condition, table in tables.items():
            indices = event_indices(
                table["trial_type"], table["orientation"], table["delay"], definition,
                control=condition == "control",
            )
            clean = (
                clean_trial_mask(table["trial_type"], indices, "standard", table["block_number"])
                if condition == "context" else [True] * len(indices)
            )
            baselines = neural_baseline_windows(
                table["start"], table["stop"], indices, "standard", table["block_number"],
            )
            trials = []
            excluded = []
            for index, keep, baseline in zip(indices, clean, baselines, strict=True):
                if not keep:
                    excluded.append(int(index))
                    continue
                onset = float(table["start"][index])
                previous = None
                if index > 0 and table["block_number"][index - 1] == table["block_number"][index]:
                    previous = [
                        float(table[key][index - 1] - onset) for key in ("start", "stop")
                    ]
                trials.append({
                    "row_index": int(index), "onset_seconds": onset,
                    "previous_window": previous,
                    "event_window": [0.0, float(table["stop"][index] - onset)],
                    "baseline_window": (
                        [float(t - onset) for t in baseline] if baseline is not None else None
                    ),
                })
            conditions[condition] = {
                "trials": trials, "excluded_rows": excluded, "total_trials": len(indices),
            }
        events.append({"id": definition.id, "conditions": conditions})
    return events


def aligned_trial_spikes(spikes: np.ndarray, trials: list[dict]) -> list[list[float]]:
    """Preserve native spike offsets in padded half-open trial windows."""
    spikes = np.asarray(spikes, dtype=float)
    if not np.all(np.isfinite(spikes)) or np.any(np.diff(spikes) < 0):
        raise ValueError("Selected unit spike timestamps are nonfinite or unsorted.")
    result = []
    for trial in trials:
        onset = trial["onset_seconds"]
        first, last = np.searchsorted(
            spikes, [onset + SOURCE_START, onset + WINDOW[1]], side="left",
        )
        result.append((spikes[first:last] - onset).tolist())
    return result


def trial_mean_sdf(
    spike_trials: list[list[float]], *,
    bin_seconds: float = SDF_SOURCE_BIN_SECONDS,
    tau_seconds: float = SDF_TAU_SECONDS,
) -> np.ndarray:
    """Rebin and causally smooth the exact displayed trials, retaining empty trials."""
    if not spike_trials:
        raise ValueError("Cannot compute an example mean without trials.")
    if not np.all(np.isfinite([bin_seconds, tau_seconds])) or min(bin_seconds, tau_seconds) <= 0:
        raise ValueError("SDF bin width and time constant must be finite and positive.")
    display_count = round((WINDOW[1] - WINDOW[0]) / bin_seconds)
    if not np.isclose(display_count * bin_seconds, WINDOW[1] - WINDOW[0], atol=1e-12, rtol=0):
        raise ValueError("SDF bin width must divide the display window.")
    kernel = sdf_kernel(bin_seconds=bin_seconds, tau_seconds=tau_seconds)
    padding = len(kernel) - 1
    start = WINDOW[0] - padding * bin_seconds
    if start < SOURCE_START - 1e-10:
        raise ValueError("Insufficient extracted spike history for this SDF kernel.")
    count = display_count + padding
    edges = start + np.arange(count + 1) * bin_seconds
    counts = np.zeros(count)
    for spikes in spike_trials:
        values = np.asarray(spikes, dtype=float)
        if (
            not np.all(np.isfinite(values)) or np.any(np.diff(values) < 0)
            or np.any(values < SOURCE_START - 1e-10) or np.any(values >= WINDOW[1])
        ):
            raise ValueError("Example spike offsets are outside their padded window or unsorted.")
        counts += np.histogram(values, bins=edges)[0]
    rate = counts / len(spike_trials) / bin_seconds
    return np.convolve(rate, kernel, mode="full")[padding:count]


def validate_example_spikes(
    payload: dict, data: Diagnostic, *, selection: list[dict] | None = None,
    selection_rule: str = SELECTION_RULE, event_ids: tuple[str, ...] = EVENTS,
) -> None:
    """Reject changed selection, misaligned trials, missing rows, or invalid spikes."""
    if (
        payload.get("version") != 1
        or payload.get("session_id") != data.session["sessionId"]
        or payload.get("asset") != data.session["asset"]
        or payload.get("selection") != (
            example_selections(data) if selection is None else selection
        )
        or payload.get("source_window_seconds") != [SOURCE_START, WINDOW[1]]
        or payload.get("display_window_seconds") != list(WINDOW)
        or payload.get("selection_rule") != selection_rule
        or payload.get("padding_bins") != PADDING_BINS
        or payload.get("bin_seconds") != SDF_SOURCE_BIN_SECONDS
    ):
        raise ValueError("Example snapshot identity, selection, or extraction window changed.")
    events = payload.get("events", [])
    if [event["id"] for event in events] != list(event_ids):
        raise ValueError("Example snapshot event coverage changed.")
    for event in events:
        original = data.session["events"][EVENTS.index(event["id"])]
        for condition in ("context", "control"):
            record = event["conditions"][condition]
            trials = record["trials"]
            n = original["cleanTrialCount" if condition == "context" else "controlTrialCount"]
            excluded = record["excluded_rows"]
            expected_total = original[f"{condition}TrialCount"]
            rows = [t["row_index"] for t in trials]
            if (
                len(trials) != n or len(set(rows)) != n or rows != sorted(rows)
                or set(rows) & set(excluded) or len(set(excluded)) != len(excluded)
                or len(trials) + len(excluded) != expected_total
                or record["total_trials"] != expected_total
            ):
                raise ValueError(f"{event['id']} {condition}: trial IDs/counts are inconsistent.")
            onsets = np.array([t["onset_seconds"] for t in trials])
            if not np.all(np.isfinite(onsets)) or np.any(np.diff(onsets) <= 0):
                raise ValueError("Example trial onset ordering is invalid.")
            for trial in trials:
                for field in ("previous_window", "event_window", "baseline_window"):
                    window = trial[field]
                    if window is None:
                        if field == "event_window" or condition == "context":
                            raise ValueError(f"Missing example {field}.")
                    elif (
                        len(window) != 2 or not np.all(np.isfinite(window))
                        or window[1] <= window[0]
                    ):
                        raise ValueError(f"Invalid example {field}.")
    units = payload.get("units", [])
    if [u["id"] for u in units] != [s["unit_id"] for s in payload["selection"]]:
        raise ValueError("Example spike/unit alignment is inconsistent.")
    for unit in units:
        if set(unit["spikes"]) != set(event_ids):
            raise ValueError("Missing selected-unit event spikes.")
        for event in events:
            for condition in ("context", "control"):
                spikes = unit["spikes"][event["id"]][condition]
                if len(spikes) != len(event["conditions"][condition]["trials"]):
                    raise ValueError("Example spike trial count is inconsistent.")
                trial_mean_sdf(spikes)


def load_example_spikes(
    data: Diagnostic, path: Path = EXAMPLES_PATH, provenance_path: Path = EXAMPLES_PROVENANCE,
    *, selection: list[dict] | None = None, selection_rule: str = SELECTION_RULE,
    event_ids: tuple[str, ...] = EVENTS,
) -> dict:
    """Load the small committed spike snapshot, checking data/source hashes."""
    provenance = json.loads(provenance_path.read_text())
    if hashlib.sha256(path.read_bytes()).hexdigest() != provenance["output_sha256"]:
        raise ValueError("Example spike snapshot checksum mismatch.")
    for source in provenance["sources"]:
        actual = hashlib.sha256((REPO_ROOT / source["path"]).read_bytes()).hexdigest()
        if actual != source["sha256"]:
            raise ValueError(f"Example extraction source changed: {source['path']}")
    payload = json.loads(path.read_text())
    validate_example_spikes(
        payload, data, selection=selection, selection_rule=selection_rule, event_ids=event_ids,
    )
    return payload


def _trial_windows(ax: plt.Axes, trials: list[dict], raster: bool) -> None:
    for field, color in (("previous_window", "#e7c797"), ("event_window", "#aaaaaa")):
        if raster:
            for row, trial in enumerate(trials):
                window = trial[field]
                if window is not None:
                    ax.fill_betweenx(
                        [row + 0.5, row + 1.5], window[0], window[1],
                        color=color, alpha=0.25, linewidth=0,
                    )
        else:
            windows = [trial[field] for trial in trials if trial[field] is not None]
            if windows:
                start, stop = np.mean(windows, axis=0)
                ax.axvspan(start, stop, color=color, alpha=0.25, linewidth=0)
    ax.axvline(0, color="#555555", linewidth=0.6, linestyle="--")


def render_example_gallery(
    data: Diagnostic, payload: dict, output_dir: Path, *,
    bin_seconds: float = SDF_SOURCE_BIN_SECONDS,
    tau_seconds: float = SDF_TAU_SECONDS,
    filename_suffix: str = "",
) -> list[Path]:
    """Render one raster/mean SVG per selected unit for the snapshot's events."""
    paths = []
    responsive = joint_example_mask(data)
    rc = {
        "font.family": "DejaVu Sans", "font.size": 10, "svg.fonttype": "none",
        "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": 0.5,
    }
    for selection, unit in zip(payload["selection"], payload["units"], strict=True):
        with mpl.rc_context(rc):
            fig = plt.figure(figsize=(12, 8))
            grid = fig.add_gridspec(
                3, len(payload["events"]), left=0.08, right=0.97, top=0.86, bottom=0.17,
                height_ratios=[1.4, 2, 1.25], hspace=0.3, wspace=0.35,
            )
            fig.suptitle(
                f"Standard oddball | {selection['label']} | unit {unit['id']} | mouse 830794",
                y=0.98, fontsize=15,
            )
            fig.text(
                0.08, 0.935,
                "SUA, QC, >1 Hz | Q1 AND Q2, same event: each p < 0.05 and |MI| > 0.1",
                fontsize=10,
            )
            for column, event in enumerate(payload["events"]):
                event_index = EVENTS.index(event["id"])
                means = []
                for condition_index, condition in enumerate(("context", "control")):
                    trials = event["conditions"][condition]["trials"]
                    spikes = unit["spikes"][event["id"]][condition]
                    ax = fig.add_subplot(grid[condition_index, column])
                    ax.set_gid(f"raster-{condition}-{event['id']}")
                    _trial_windows(ax, trials, raster=True)
                    for row, trial_spikes in enumerate(spikes):
                        visible = [s for s in trial_spikes if WINDOW[0] <= s < WINDOW[1]]
                        ax.vlines(visible, row + 0.65, row + 1.35, color="black", linewidth=0.5)
                    ax.set_ylim(len(trials) + 0.5, 0.5)
                    ax.set_yticks([1, len(trials)])
                    if column == 0:
                        ax.set_ylabel(
                            f"{'Clean context' if condition_index == 0 else 'Control'} trial"
                        )
                    ax.set_xlim(WINDOW)
                    ax.set_xticks([-0.5, 0, 0.5], [])
                    if condition_index == 0:
                        i = selection["index"]
                        p = data.statistics["q1_p"][event_index, i]
                        mi = data.statistics["q1_modulation"][event_index, i]
                        p2 = data.statistics["q2_delta_p"][event_index, i]
                        mi2 = data.statistics["q2_delta_modulation"][event_index, i]
                        status = (
                            "not testable" if not np.all(np.isfinite([p, mi, p2, mi2])) else
                            "passes both" if responsive[event_index, i] else "does not pass both"
                        )
                        ax.set_title(
                            f"{LABELS[event_index]} | {status}\n"
                            f"Q1 p={p:.2g}, MI={mi:.2f}\nQ2 p={p2:.2g}, MI={mi2:.2f}",
                            fontsize=9,
                        )
                    means.append(trial_mean_sdf(
                        spikes, bin_seconds=bin_seconds, tau_seconds=tau_seconds,
                    ))
                ax = fig.add_subplot(grid[2, column])
                ax.set_gid(f"trial-mean-{event['id']}")
                _trial_windows(ax, event["conditions"]["context"]["trials"], raster=False)
                for condition_index, color in enumerate((CONTEXT_COLOR, CONTROL_COLOR)):
                    times = (
                        data.session["timeBinCentersSeconds"]
                        if bin_seconds == SDF_SOURCE_BIN_SECONDS else
                        WINDOW[0] + (np.arange(len(means[condition_index])) + 0.5) * bin_seconds
                    )
                    ax.plot(
                        times, means[condition_index], color=color,
                        linewidth=1.1, label=("Context", "Control")[condition_index],
                    )
                ax.set_xlim(WINDOW)
                ax.set_ylim(bottom=0)
                ax.set_xticks([-0.5, 0, 0.5])
                ax.set_xlabel("Time from event (s)")
                if column == 0:
                    ax.set_ylabel("Firing rate (Hz)")
                    fig.legend(
                        *ax.get_legend_handles_labels(), loc="upper right",
                        bbox_to_anchor=(0.97, 0.955), fontsize=10, ncol=2, frameon=False,
                    )
            for row, letter in enumerate("ABC"):
                pos = grid[row, 0].get_position(fig)
                fig.text(
                    0.025, pos.y1, letter, fontweight="bold", gid=f"panel-label-{letter}",
                )
            for i, text in enumerate((
                "A/B: real spike times, one chronological trial per row; empty trials retained. "
                "Clean context / all matched controls.",
                f"C: causal {tau_seconds * 1000:g} ms exponential SDF from exactly these trials, "
                f"{bin_seconds * 1000:g} ms bins; "
                "no trial SEM. Hidden pre-padding is not plotted.",
                "Tan: preceding presentation; gray: event window. Raster windows are per-trial; "
                "mean-plot windows average clean-context timings.",
                "Exploratory Q1 AND Q2 selection (uncorrected), same deviant; not representative. "
                "Other displayed events need not pass.",
            )):
                fig.text(0.08, 0.075 - i * 0.018, text, fontsize=9)
            path = output_dir / f"unit-{unit['id']}{filename_suffix}.svg"
            save_diagnostic_svg(
                fig, path,
                f"{selection['label']} unit {unit['id']}: trial rasters and firing rates",
                f"{'Four' if len(payload['events']) == 4 else len(payload['events'])} "
                "standard-oddball events. "
                "A: clean-context trial raster. B: matched-control "
                "trial raster. C: mean firing rates from exactly the raster trials, "
                f"{bin_seconds * 1000:g} ms bins, causal exponential kernel with "
                f"{tau_seconds * 1000:g} ms time constant and ten time constants of support. "
                "Rows retain "
                "chronological order and empty trials. Exploratory Q1 AND Q2 p/MI selection "
                "for the same deviant, using baseline-subtracted Q2; "
                "not every displayed event is significant.",
                {
                    "data-unit-id": str(unit["id"]), "data-example-label": selection["label"],
                    "data-selection-rule": "q1-and-q2-same-event",
                    "data-sdf-bin-seconds": str(bin_seconds),
                    "data-sdf-tau-seconds": str(tau_seconds),
                    "data-context-trial-counts": ",".join(
                        str(len(e["conditions"]["context"]["trials"])) for e in payload["events"]
                    ),
                    "data-control-trial-counts": ",".join(
                        str(len(e["conditions"]["control"]["trials"])) for e in payload["events"]
                    ),
                },
            )
            paths.append(path)
    return paths
