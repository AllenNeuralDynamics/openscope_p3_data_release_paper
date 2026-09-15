#!/usr/bin/env python3
"""Extract compact per-unit Neuropixels mismatch-response atlases from public NWBs."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import gzip
import hashlib
import json
import math
import re
import shutil
import urllib.request
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path

try:
    import h5py
    import numpy as np
    import remfile
    from iblatlas.regions import BrainRegions
    from rastermap import Rastermap

    from openscope_p3_publication.optotagging import (
        CONDITIONS as OPTOTAGGING_CONDITIONS,
    )
    from openscope_p3_publication.optotagging import (
        compute_response_metrics,
        expand_pulse_times,
    )
except ImportError as exc:  # pragma: no cover - optional extraction environment
    raise SystemExit(
        "Run with: uv run --with h5py --with iblatlas --with numpy --with pandas "
        "--with rastermap==1.0 --with remfile --with scipy "
        "python scripts/extract_neuropixels_event_responses.py"
    ) from exc

from openscope_p3_publication.mismatch_adjacency import (
    SENSORIMOTOR_MIN_INTERVAL_SECONDS,
)
from openscope_p3_publication.mismatch_responsiveness import (
    DEFAULT_MODULATION_MINIMUM,
    DEFAULT_Q_MAX,
    SENSORIMOTOR_BASELINE_SECONDS,
    benjamini_hochberg,
    classify_responsive,
    clean_trial_mask,
    comparison_windows,
    paired_p_values,
    unpaired_p_values,
)
from openscope_p3_publication.mismatch_responsiveness import (
    modulation_index as trialwise_modulation_index,
)
from openscope_p3_publication.neural_responses import (
    BASELINE_BIN_SECONDS,
    BIN_SECONDS,
    CONTEXT_WINDOWS_SECONDS,
    NEURAL_SESSIONS,
    NEURAL_SUBJECT,
    QC_THRESHOLDS,
    RASTERMAP_PARAMETERS,
    RASTERMAP_VERSION,
    SDF_KERNEL_DURATION_TAU,
    SDF_QUANTIZATION_SCALE,
    SDF_SOURCE_BIN_SECONDS,
    SDF_TAU_SECONDS,
    SEQUENCE_CONTROL_BASELINE_TABLE,
    adjacent_blank_windows,
    classify_neuron_type,
    context_event_definitions,
    context_window_seconds,
    event_indices,
    neural_baseline_windows,
    neural_response_windows,
    qc_passes,
    relative_bin_centers,
    sample_windows_evenly,
    sdf_kernel,
)
from openscope_p3_publication.sensorimotor_running import (
    DEFAULT_RUNNING_THRESHOLD_CM_S,
    forward_speed,
    sensorimotor_trial_masks,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "figure_sources" / "data"
DEFAULT_OUTPUT = DATA_DIR / "neuropixels-event-responses.json"
DEFAULT_PROVENANCE_OUTPUT = DEFAULT_OUTPUT.with_suffix(".provenance.json")
DEFAULT_RESPONSIVENESS_OUTPUT = DATA_DIR / "neuropixels-mismatch-responsiveness.csv"
DEFAULT_MEDIA_DIR = REPO_ROOT / "figure_sources" / "media" / "neuropixels-event-responses"
MEDIA_ASSET_ROOT = "media/neuropixels-event-responses"
DANDI_API = "https://api.dandiarchive.org/api"
DANDISET_ID = "001637"
DANDI_VERSION = "draft"
VERSION = 11
CONDITION_ORDER = ("context", "control")
PROBE_ORDER = tuple(f"Probe{letter}" for letter in "ABCDEF")
COMPATIBLE_METADATA_SIGNATURES = (
    "ffdafa7a1121a37592dcd233749734e9f0fa0939c8b5bdbb5aa4655a57e8ea5d",
)
FRONTAL_PREFIXES = ("ACA", "ILA", "PL", "ORB", "MOp", "MOs")
MOTOR_PREFIXES = ("MOp", "MOs")
VISUAL_THALAMUS_PREFIXES = ("LGd", "LGv", "LP")
SST_OPTOTAGGING_CONDITION = next(
    condition
    for condition in OPTOTAGGING_CONDITIONS
    if condition.table_name == "5 hz pulse train_presentations"
)
RUNNING_SERIES = "processing/running/running_speed"
SST_P_VALUE_MAX = 0.05
SST_MODULATION_INDEX_MIN = 0.1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--provenance-output",
        type=Path,
        default=DEFAULT_PROVENANCE_OUTPUT,
    )
    parser.add_argument("--media-dir", type=Path, default=DEFAULT_MEDIA_DIR)
    parser.add_argument(
        "--responsiveness-output",
        type=Path,
        default=DEFAULT_RESPONSIVENESS_OUTPUT,
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="Optional directory for resumable per-session extracted artifacts.",
    )
    parser.add_argument(
        "--session-id",
        action="append",
        help="Extract only this configured session; may be repeated.",
    )
    parser.add_argument(
        "--probe",
        action="append",
        choices=PROBE_ORDER,
        help="Extract only this probe; may be repeated.",
    )
    parser.add_argument("--max-workers", type=int, default=2)
    parser.add_argument("--retrieved-date", default=dt.date.today().isoformat())
    return parser.parse_args()


def decode(value):
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, np.generic):
        return value.item()
    return value


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def region_index(regions: BrainRegions, acronym: str) -> int:
    indices = np.flatnonzero(
        (regions.acronym == acronym) & (regions.id >= 0)
    )
    if len(indices) != 1:
        raise RuntimeError(
            f"Allen ontology acronym {acronym!r} matched {len(indices)} regions."
        )
    return int(indices[0])


def canonical_parent_area_index(regions: BrainRegions, index: int) -> int:
    current = index
    while True:
        parent_id = regions.parent[current]
        if not math.isfinite(parent_id):
            return current
        parent_indices = np.flatnonzero(regions.id == int(parent_id))
        if len(parent_indices) != 1:
            raise RuntimeError(
                f"Allen ontology parent {parent_id!r} matched {len(parent_indices)} regions."
            )
        parent = int(parent_indices[0])
        acronym = str(regions.acronym[current])
        parent_acronym = str(regions.acronym[parent])
        name = str(regions.name[current]).lower()
        ancestors = set(
            regions.ancestors(int(regions.id[current])).acronym
        )
        cortical_layer = (
            "Isocortex" in ancestors
            and re.search(r"(?:1|2|2/3|3|4|5|6|6a|6b)$", acronym)
            is not None
        )
        collapsible = (
            "layer" in name
            or acronym.startswith(f"{parent_acronym}-")
            or cortical_layer
        )
        if not collapsible:
            return current
        current = parent


def ontology_record(regions: BrainRegions, index: int) -> dict[str, int | str]:
    return {
        "acronym": str(regions.acronym[index]),
        "graphOrder": int(regions.order[index]),
        "id": int(regions.id[index]),
        "level": int(regions.level[index]),
    }


def area_classification(acronyms: list[str]) -> dict[str, dict]:
    regions = BrainRegions()
    classifications = {}
    for acronym in sorted(set(acronyms)):
        index = region_index(regions, acronym)
        region_id = int(regions.id[index])
        ancestors = (
            list(regions.ancestors(region_id).acronym)
            if region_id != 0
            else []
        )
        major_parent = next(
            (
                parent
                for parent in reversed(ancestors)
                if parent in {"Isocortex", "TH", "HPF", "STR"}
            ),
            "Other",
        )
        groups = []
        if major_parent == "Isocortex":
            groups.append("cortical")
        if major_parent == "TH":
            groups.append("thalamic")
        if major_parent == "HPF":
            groups.append("hippocampal")
        if acronym.startswith("VIS") or acronym.startswith(
            VISUAL_THALAMUS_PREFIXES
        ):
            groups.append("visual")
        if acronym.startswith(FRONTAL_PREFIXES):
            groups.append("frontal")
        if acronym.startswith(MOTOR_PREFIXES):
            groups.append("motor")
        area = ontology_record(regions, index)
        parent_area = ontology_record(
            regions,
            canonical_parent_area_index(regions, index),
        )
        classifications[acronym] = {
            "areaGraphOrder": area["graphOrder"],
            "groups": groups,
            "majorParent": major_parent,
            "areaId": area["id"],
            "areaLevel": area["level"],
            "parentArea": parent_area["acronym"],
            "parentAreaGraphOrder": parent_area["graphOrder"],
            "parentAreaId": parent_area["id"],
            "parentAreaLevel": parent_area["level"],
        }
    return classifications


def annotate_unit_areas(unit_records: list[dict]) -> None:
    classifications = area_classification(
        [unit["location"] for unit in unit_records]
    )
    for unit in unit_records:
        classification = classifications[unit["location"]]
        unit["areaGraphOrder"] = classification["areaGraphOrder"]
        unit["areaGroups"] = classification["groups"]
        unit["areaId"] = classification["areaId"]
        unit["areaLevel"] = classification["areaLevel"]
        unit["majorParent"] = classification["majorParent"]
        unit["parentArea"] = classification["parentArea"]
        unit["parentAreaGraphOrder"] = classification[
            "parentAreaGraphOrder"
        ]
        unit["parentAreaId"] = classification["parentAreaId"]
        unit["parentAreaLevel"] = classification["parentAreaLevel"]


def encode_float32(values: np.ndarray) -> str:
    array = np.ascontiguousarray(values, dtype="<f4")
    return base64.b64encode(array.tobytes()).decode("ascii")


def encode_uint16(values: np.ndarray) -> str:
    array = np.ascontiguousarray(values, dtype="<u2")
    return base64.b64encode(array.tobytes()).decode("ascii")


def write_gzip(path: Path, content: bytes) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    compressed = gzip.compress(content, compresslevel=9, mtime=0)
    path.write_bytes(compressed)
    return {
        "path": f"{MEDIA_ASSET_ROOT}/{path.name}",
        "sha256": hashlib.sha256(compressed).hexdigest(),
        "size": len(compressed),
        "uncompressedSize": len(content),
    }


def table_arrays(table: h5py.Group) -> dict[str, np.ndarray]:
    return {
        "block_number": np.asarray(table["BlockNumber"][:], dtype=float),
        "delay": np.asarray(table["Delay"][:], dtype=float),
        "orientation": np.asarray(table["Orientation"][:], dtype=float),
        "start": np.asarray(table["start_time"][:], dtype=float),
        "stop": np.asarray(table["stop_time"][:], dtype=float),
        "trial_type": np.asarray(table["TrialType"][:]).astype("U"),
    }


def event_records(nwb: h5py.File, config) -> tuple[list[dict], list[dict]]:
    window_start, window_stop = context_window_seconds(config.context)
    context_arrays = table_arrays(nwb[f"intervals/{config.context_table}"])
    control_arrays = table_arrays(nwb[f"intervals/{config.control_table}"])
    sequence_baseline_arrays = (
        table_arrays(nwb[f"intervals/{SEQUENCE_CONTROL_BASELINE_TABLE}"])
        if config.context == "sequence"
        else None
    )
    records = []
    extraction = []
    for definition in context_event_definitions(config.context):
        condition_indices = {}
        condition_onsets = {}
        for condition, arrays, control in (
            ("context", context_arrays, False),
            ("control", control_arrays, True),
        ):
            indices = np.asarray(
                event_indices(
                    arrays["trial_type"],
                    arrays["orientation"],
                    arrays["delay"],
                    definition,
                    control=control,
                ),
                dtype=int,
            )
            if not len(indices):
                raise RuntimeError(
                    f"{config.context} {definition.id} has no {condition} trials."
                )
            condition_indices[condition] = indices
            condition_onsets[condition] = arrays["start"][indices]
        baseline_windows = {}
        response_windows = {}
        trial_baseline_windows = {}
        for condition, arrays in (
            ("context", context_arrays),
            ("control", control_arrays),
        ):
            # Per-trial baselines keep their trial alignment, including the
            # unavailable ones, so responsiveness can subtract a trial's own
            # baseline. The pooled list below drops them because
            # baseline_rate_stats accumulates 20 ms bins across all baselines.
            trial_baseline_windows[condition] = neural_baseline_windows(
                arrays["start"],
                arrays["stop"],
                condition_indices[condition],
                config.context,
                arrays["block_number"],
            )
            baseline_windows[condition] = [
                window
                for window in trial_baseline_windows[condition]
                if window is not None
            ]
            if not baseline_windows[condition]:
                raise RuntimeError(
                    f"{config.context} {definition.id} has no {condition} baselines."
                )
            response_windows[condition] = neural_response_windows(
                arrays["start"],
                arrays["stop"],
                condition_indices[condition],
            )

        if config.context == "sequence":
            # Control block 2 has no blank period anywhere in its 298 s: its
            # rows are contiguous, so the sequence rule's row offset lands on
            # an arbitrary grating rather than a baseline. Borrow the blank
            # inter-stimulus intervals of the control block 1 repeat that ends
            # where control block 2 begins -- genuine no-stimulus windows
            # within a minute of the trials they baseline.
            borrowed = adjacent_blank_windows(
                sequence_baseline_arrays["start"],
                sequence_baseline_arrays["stop"],
                sequence_baseline_arrays["block_number"],
                float(control_arrays["start"].min()),
            )
            trials = len(condition_indices["control"])
            trial_baseline_windows["control"] = sample_windows_evenly(
                borrowed, trials
            )
            baseline_windows["control"] = list(trial_baseline_windows["control"])

        # Duration only: the epoch the manipulation actually changes. The
        # violated delay runs from row i-1 stop to row i start; the standard
        # delay it is compared against runs from row i-2 stop to row i-1 start,
        # which is the same interval the duration baseline uses.
        delay_windows: list[tuple[float, float] | None] = []
        standard_delay_windows: list[tuple[float, float] | None] = []
        if config.context == "duration":
            starts = context_arrays["start"]
            stops = context_arrays["stop"]
            blocks = context_arrays["block_number"]
            for row in condition_indices["context"]:
                if row < 2 or (
                    blocks[row - 2] != blocks[row] or blocks[row - 1] != blocks[row]
                ):
                    delay_windows.append(None)
                    standard_delay_windows.append(None)
                    continue
                violated = (float(stops[row - 1]), float(starts[row]))
                standard = (float(stops[row - 2]), float(starts[row - 1]))
                delay_windows.append(violated if violated[0] < violated[1] else None)
                standard_delay_windows.append(
                    standard if standard[0] < standard[1] else None
                )

        # Q1 compares each mismatch against the most recent expected instance in
        # the same block, so it needs windows only for the context condition.
        comparison = comparison_windows(
            context_arrays["start"],
            context_arrays["stop"],
            condition_indices["context"],
            config.context,
            context_arrays["block_number"],
        )
        clean_mask = clean_trial_mask(
            context_arrays["trial_type"],
            condition_indices["context"],
            config.context,
            context_arrays["block_number"],
        )
        timing = {}
        for condition, arrays in (
            ("context", context_arrays),
            ("control", control_arrays),
        ):
            indices = condition_indices[condition]
            timing[condition] = {
                "presentationStartSeconds": 0.0,
                "presentationStopSeconds": round(
                    float(np.mean(arrays["stop"][indices] - arrays["start"][indices])),
                    6,
                ),
            }
            offsets = (0,) if config.context == "sensorimotor" else range(-64, 65)
            presentation_windows = []
            for row_offset in offsets:
                shifted = indices + row_offset
                valid_mask = (shifted >= 0) & (shifted < len(arrays["start"]))
                shifted = shifted[valid_mask]
                reference = indices[valid_mask]
                same_block = (
                    arrays["block_number"][shifted]
                    == arrays["block_number"][reference]
                )
                shifted = shifted[same_block]
                reference = reference[same_block]
                if not len(shifted):
                    continue
                start_seconds = float(
                    np.mean(
                        arrays["start"][shifted]
                        - arrays["start"][reference]
                    )
                )
                stop_seconds = float(
                    np.mean(
                        arrays["stop"][shifted]
                        - arrays["start"][reference]
                    )
                )
                if (
                    stop_seconds < window_start
                    or start_seconds > window_stop
                ):
                    continue
                presentation_windows.append(
                    {
                        "rowOffset": row_offset,
                        "startSeconds": round(start_seconds, 6),
                        "stopSeconds": round(stop_seconds, 6),
                    }
                )
            timing[condition]["presentationWindows"] = presentation_windows
            if config.context == "duration":
                valid = indices[
                    (indices > 0)
                    & (
                        arrays["block_number"][indices - 1]
                        == arrays["block_number"][indices]
                    )
                ]
                timing[condition].update(
                    previousPresentationStartSeconds=round(
                        float(
                            np.mean(
                                arrays["start"][valid - 1] - arrays["start"][valid]
                            )
                        ),
                        6,
                    ),
                    previousPresentationStopSeconds=round(
                        float(
                            np.mean(
                                arrays["stop"][valid - 1] - arrays["start"][valid]
                            )
                        ),
                        6,
                    ),
                )
        records.append(
            {
                "contextTrialCount": len(condition_indices["context"]),
                "controlTrialCount": len(condition_indices["control"]),
                "id": definition.id,
                "label": definition.label,
                "responseWindowLabel": "NWB start_time–stop_time",
                "staticGroup": definition.static_group or definition.id,
                "timing": timing,
            }
        )
        extraction.append(
            {
                "baseline_windows": baseline_windows,
                "clean_mask": clean_mask,
                "comparison_windows": comparison,
                "condition_onsets": condition_onsets,
                "delay_windows": delay_windows,
                "standard_delay_windows": standard_delay_windows,
                "response_windows": response_windows,
                "trial_baseline_windows": trial_baseline_windows,
            }
        )
    return records, extraction


def histogram_trial_counts(
    spikes: np.ndarray,
    onsets: np.ndarray,
    relative_edges: np.ndarray,
) -> np.ndarray:
    counts = np.zeros(len(relative_edges) - 1, dtype=np.uint32)
    for onset in onsets:
        first = int(np.searchsorted(spikes, onset + relative_edges[0], side="left"))
        last = int(np.searchsorted(spikes, onset + relative_edges[-1], side="left"))
        if last <= first:
            continue
        trial_counts = np.histogram(
            spikes[first:last] - onset,
            bins=relative_edges,
        )[0].astype(np.uint32)
        counts += trial_counts
    maximum = np.iinfo(np.uint16).max
    if np.max(counts, initial=0) > maximum:
        raise RuntimeError("Aggregated PSTH counts exceed uint16 capacity.")
    return counts.astype(np.uint16)


def sdf_trial_mean(
    count_sum: np.ndarray,
    trial_count: int,
    output_start_index: int,
    output_count: int,
) -> np.ndarray:
    if trial_count < 1:
        raise ValueError("SDF calculation requires at least one trial.")
    source_mean_hz = (
        count_sum.astype(np.float64)
        / trial_count
        / SDF_SOURCE_BIN_SECONDS
    )
    padded_mean_hz = np.convolve(
        source_mean_hz,
        np.asarray(sdf_kernel(), dtype=float),
        mode="full",
    )[: len(source_mean_hz)]
    output_stop_index = output_start_index + output_count
    if output_start_index < 0 or output_stop_index > len(padded_mean_hz):
        raise ValueError("SDF output slice is outside the padded source window.")
    return padded_mean_hz[output_start_index:output_stop_index].astype(
        np.float32
    )


def quantize_sdf(values: np.ndarray) -> np.ndarray:
    maximum = np.iinfo(np.uint16).max / SDF_QUANTIZATION_SCALE
    if np.any(~np.isfinite(values)) or np.min(values, initial=0) < 0:
        raise RuntimeError("SDF values must be finite and nonnegative.")
    if np.max(values, initial=0) > maximum:
        raise RuntimeError(
            f"SDF value exceeds the quantized maximum of {maximum:g} spikes/s."
        )
    return np.rint(values * SDF_QUANTIZATION_SCALE).astype(np.uint16)


def baseline_rate_stats(
    spikes: np.ndarray,
    windows: list[tuple[float, float]],
) -> tuple[float, float]:
    count = 0
    total = 0.0
    total_squared = 0.0
    for start, stop in windows:
        bin_count = math.floor((stop - start) / BASELINE_BIN_SECONDS)
        if bin_count < 1:
            continue
        edges = (
            start
            + np.arange(bin_count + 1, dtype=float) * BASELINE_BIN_SECONDS
        )
        first = int(np.searchsorted(spikes, edges[0], side="left"))
        last = int(np.searchsorted(spikes, edges[-1], side="left"))
        rates = (
            np.histogram(spikes[first:last], bins=edges)[0]
            / BASELINE_BIN_SECONDS
        )
        count += len(rates)
        total += float(np.sum(rates))
        total_squared += float(np.sum(rates * rates))
    if count < 2:
        return math.nan, math.nan
    mean = total / count
    variance = max(0.0, (total_squared - total * total / count) / (count - 1))
    return mean, math.sqrt(variance)


def rates_in_windows(
    spikes: np.ndarray,
    windows: list[tuple[float, float] | None],
) -> np.ndarray:
    """Spike rate in each window, NaN where the window is unavailable.

    Windows are per trial, so this is the per-trial vector the responsiveness
    tests consume. ``None`` marks a trial whose comparison window falls outside
    the table or crosses a block boundary.
    """
    rates = np.full(len(windows), np.nan, dtype=float)
    for index, window in enumerate(windows):
        if window is None:
            continue
        start, stop = window
        first = int(np.searchsorted(spikes, start, side="left"))
        last = int(np.searchsorted(spikes, stop, side="right"))
        rates[index] = (last - first) / (stop - start)
    return rates


def mean_rate_in_windows(
    spikes: np.ndarray,
    windows: list[tuple[float, float]],
) -> float:
    return float(np.mean(rates_in_windows(spikes, windows)))


def responsiveness_statistics(
    collected: dict[str, np.ndarray],
    clean_mask: Sequence[bool],
) -> dict[str, np.ndarray]:
    """Q1 and Q2 statistics for every unit at one event.

    Q1 is the within-block comparison against the most recent expected
    instance, paired within trial. Its p-value is invariant to subtracting a
    common per-trial baseline, because the paired difference cancels it, so one
    p-value is reported with modulation indices for both variants.

    Q2 compares the mismatch response against the matched control block. The
    blocks are recorded at different times with unequal trial counts, so the
    test is unpaired and the baseline-subtracted variant is a genuinely
    different comparison rather than a rescaling.
    """
    clean = np.asarray(list(clean_mask), dtype=bool)
    test = collected["context_test"][:, clean]
    comparison = collected["context_comparison"][:, clean]
    context_baseline = collected["context_baseline"][:, clean]
    control_test = collected["control_test"]
    control_baseline = collected["control_baseline"]
    unit_count = test.shape[0]

    q1_p = paired_p_values(test, comparison)
    q1_trials = np.sum(np.isfinite(test) & np.isfinite(comparison), axis=1)

    q1_modulation = np.array(
        [trialwise_modulation_index(test[row], comparison[row]) for row in range(unit_count)]
    )
    q1_modulation_baseline = np.array(
        [
            trialwise_modulation_index(
                test[row] - context_baseline[row],
                comparison[row] - context_baseline[row],
            )
            for row in range(unit_count)
        ]
    )

    q2_p = unpaired_p_values(test, control_test)
    q2_modulation = np.array(
        [
            trialwise_modulation_index(
                np.full(1, np.nanmean(test[row])),
                np.full(1, np.nanmean(control_test[row])),
            )
            for row in range(unit_count)
        ]
    )
    mismatch_delta = test - context_baseline
    control_delta = control_test - control_baseline
    q2_delta_p = unpaired_p_values(mismatch_delta, control_delta)
    q2_delta_modulation = np.array(
        [
            trialwise_modulation_index(
                np.full(1, np.nanmean(mismatch_delta[row])),
                np.full(1, np.nanmean(control_delta[row])),
            )
            for row in range(unit_count)
        ]
    )
    q2_trials = np.sum(np.isfinite(test), axis=1)
    q2_control_trials = np.sum(np.isfinite(control_test), axis=1)

    # Duration only: firing during the violated delay against firing during a
    # standard delay in the same trial. This is the epoch the manipulation
    # changes, which the post-delay comparison above does not test.
    nan_row = np.full(unit_count, np.nan)
    delay_p = nan_row
    delay_modulation = nan_row
    delay_trials = np.zeros(unit_count, dtype=np.int32)
    if "delay" in collected and np.any(np.isfinite(collected["delay"])):
        delay = collected["delay"][:, clean]
        standard_delay = collected["standard_delay"][:, clean]
        delay_p = paired_p_values(delay, standard_delay)
        delay_modulation = np.array(
            [
                trialwise_modulation_index(delay[row], standard_delay[row])
                for row in range(unit_count)
            ]
        )
        delay_trials = np.sum(
            np.isfinite(delay) & np.isfinite(standard_delay), axis=1
        ).astype(np.int32)

    return {
        "q1_p": q1_p,
        "q1_q": benjamini_hochberg(q1_p),
        "q1_modulation": q1_modulation,
        "q1_modulation_baseline_subtracted": q1_modulation_baseline,
        "q1_trials": q1_trials.astype(np.int32),
        "q2_p": q2_p,
        "q2_q": benjamini_hochberg(q2_p),
        "q2_modulation": q2_modulation,
        "q2_delta_p": q2_delta_p,
        "q2_delta_q": benjamini_hochberg(q2_delta_p),
        "q2_delta_modulation": q2_delta_modulation,
        "q2_trials": q2_trials.astype(np.int32),
        "q2_control_trials": q2_control_trials.astype(np.int32),
        "delay_p": delay_p,
        "delay_q": benjamini_hochberg(delay_p),
        "delay_modulation": delay_modulation,
        "delay_trials": delay_trials,
    }


def optotagging_pulse_times(nwb) -> np.ndarray:
    table_name = SST_OPTOTAGGING_CONDITION.table_name
    if table_name not in nwb["intervals"]:
        raise RuntimeError(f"Missing SST optotagging table: {table_name}")
    table = nwb["intervals"][table_name]
    return expand_pulse_times(
        np.asarray(table["start_time"][:], dtype=float),
        np.asarray(table["duration"][:], dtype=float),
        SST_OPTOTAGGING_CONDITION.pulse_frequency_hz,
    )


def sst_optotagging_result(
    spikes: np.ndarray,
    pulse_times: np.ndarray,
) -> tuple[bool, float, float]:
    metrics = compute_response_metrics(
        spikes,
        pulse_times,
        SST_OPTOTAGGING_CONDITION,
    )
    p_value = float(metrics["p_value"])
    modulation_index = float(metrics["modulation_index"])
    return (
        math.isfinite(p_value)
        and math.isfinite(modulation_index)
        and p_value < SST_P_VALUE_MAX
        and modulation_index > SST_MODULATION_INDEX_MIN,
        p_value,
        modulation_index,
    )


def source_asset(config) -> dict:
    detail = fetch_json(f"{DANDI_API}/assets/{config.asset_id}/")
    if detail["path"] != config.asset_path:
        raise RuntimeError(f"DANDI asset path changed for {config.session_id}.")
    digest = detail.get("digest", {})
    if "dandi:sha2-256" not in digest:
        raise RuntimeError(f"DANDI asset lacks SHA-256: {config.asset_id}")
    return {
        "assetId": config.asset_id,
        "dandisetId": DANDISET_ID,
        "digest": digest,
        "downloadUrl": f"{DANDI_API}/assets/{config.asset_id}/download/",
        "modified": detail["dateModified"],
        "path": config.asset_path,
        "size": int(detail["contentSize"]),
        "version": DANDI_VERSION,
    }


def analysis_signature(selected_probes: tuple[str, ...]) -> str:
    content = {
        "binSeconds": BIN_SECONDS,
        "baselineBinSeconds": BASELINE_BIN_SECONDS,
        "moduleSha256": file_sha256(
            REPO_ROOT / "src" / "openscope_p3_publication" / "neural_responses.py"
        ),
        "ontologyPackageVersion": version("iblatlas"),
        "probes": selected_probes,
        "qcThresholds": QC_THRESHOLDS,
        "rastermapParameters": RASTERMAP_PARAMETERS,
        "rastermapVersion": RASTERMAP_VERSION,
        "scriptSha256": file_sha256(Path(__file__)),
        "sdfKernelDurationTau": SDF_KERNEL_DURATION_TAU,
        "sdfQuantizationScale": SDF_QUANTIZATION_SCALE,
        "sdfSourceBinSeconds": SDF_SOURCE_BIN_SECONDS,
        "sdfTauSeconds": SDF_TAU_SECONDS,
        "contextWindowsSeconds": CONTEXT_WINDOWS_SECONDS,
    }
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def rastermap_ranks(
    sdf_mean: np.ndarray,
    baseline_mean: np.ndarray,
    baseline_std: np.ndarray,
    events: list[dict],
    decoder_labels: np.ndarray,
    unit_ids: np.ndarray,
    context: str,
) -> np.ndarray:
    bin_centers = np.asarray(relative_bin_centers(context), dtype=float)
    window_start, _ = context_window_seconds(context)
    visible = bin_centers >= window_start
    ranks = np.empty((len(events), sdf_mean.shape[2]), dtype=np.uint16)
    label_eligible = np.isin(decoder_labels, ("mua", "sua"))

    for event_index in range(len(events)):
        smoothed = (
            sdf_mean[event_index, 0].astype(np.float32)
            / SDF_QUANTIZATION_SCALE
        )
        mean = baseline_mean[event_index, 0, :, np.newaxis]
        std = baseline_std[event_index, 0, :, np.newaxis]
        with np.errstate(divide="ignore", invalid="ignore"):
            z_scores = (smoothed - mean) / std
        matrix = z_scores[:, visible].astype(np.float32)
        centered_std = (matrix - matrix.mean(axis=1, keepdims=True)).std(axis=1)
        eligible = (
            label_eligible
            & np.isfinite(std[:, 0])
            & (std[:, 0] > 0)
            & np.all(np.isfinite(matrix), axis=1)
            & (centered_std > 0)
        )
        eligible_indices = np.flatnonzero(eligible)
        if len(eligible_indices) < 2:
            raise RuntimeError(
                f"{context} event {events[event_index]['id']} has too few "
                "Rastermap-eligible units."
            )
        model = Rastermap(
            **RASTERMAP_PARAMETERS,
            keep_norm_X=False,
            verbose=False,
        ).fit(matrix[eligible_indices], compute_X_embedding=False)
        ordered = eligible_indices[np.asarray(model.isort, dtype=int)]
        if len(ordered) != len(eligible_indices) or len(np.unique(ordered)) != len(ordered):
            raise RuntimeError(
                f"{context} event {events[event_index]['id']} Rastermap order is invalid."
            )
        remaining = np.setdiff1d(
            np.arange(sdf_mean.shape[2]),
            ordered,
            assume_unique=True,
        )
        remaining = remaining[np.argsort(unit_ids[remaining], kind="stable")]
        full_order = np.concatenate((ordered, remaining))
        ranks[event_index, full_order] = np.arange(
            sdf_mean.shape[2],
            dtype=np.uint16,
        )
    return ranks


def extract_session(config, media_dir: Path, selected_probes: tuple[str, ...]) -> dict:
    asset = source_asset(config)
    window_start, window_stop = context_window_seconds(config.context)
    output_bin_count = round(
        (window_stop - window_start)
        / SDF_SOURCE_BIN_SECONDS
    )
    causal_padding_bins = len(sdf_kernel()) - 1
    source_bin_count = output_bin_count + causal_padding_bins
    source_start = (
        window_start
        - causal_padding_bins * SDF_SOURCE_BIN_SECONDS
    )
    source_edges = (
        source_start
        + np.arange(source_bin_count + 1, dtype=float)
        * SDF_SOURCE_BIN_SECONDS
    )
    with closing(remfile.File(asset["downloadUrl"])) as remote, h5py.File(
        remote, "r"
    ) as nwb:
        # Sensorimotor mismatches only exist as a stimulus while the animal is
        # running, because the decoupled optic flow is self-generated. Read the
        # processed running series so those trials can be gated.
        running_times = running_forward = None
        if config.context == "sensorimotor":
            if RUNNING_SERIES not in nwb:
                raise RuntimeError(
                    f"{config.session_id} has no {RUNNING_SERIES}; the sensorimotor "
                    "running gate cannot be applied."
                )
            series = nwb[RUNNING_SERIES]
            velocity = np.asarray(series["data"][:], dtype=float)
            stamps = np.asarray(series["timestamps"][:], dtype=float)
            unit_attr = series["data"].attrs.get("unit", series.attrs.get("unit", b""))
            unit_attr = decode(unit_attr)
            if str(unit_attr).lower().replace(" ", "") not in {"cm/s", "cmps"}:
                raise RuntimeError(
                    f"{config.session_id} running unit {unit_attr!r} is not cm/s."
                )
            finite = np.isfinite(stamps) & np.isfinite(velocity)
            stamps, velocity = stamps[finite], velocity[finite]
            order = np.argsort(stamps, kind="stable")
            running_times = stamps[order]
            running_forward = forward_speed(velocity[order])
        units = nwb["units"]
        required = {
            "amplitude_cutoff",
            "decoder_label",
            "depth",
            "device_name",
            "electrodes",
            "electrodes_index",
            "extremum_channel_index",
            "firing_rate",
            "id",
            "isi_violations_ratio",
            "ks_unit_id",
            "peak_to_valley",
            "presence_ratio",
            "spike_times",
            "spike_times_index",
        }
        missing = sorted(required - set(units))
        if missing:
            raise RuntimeError(f"{config.session_id} unit columns missing: {missing}")
        events, extraction = event_records(nwb, config)
        sst_pulse_times = optotagging_pulse_times(nwb)
        device_names = np.asarray(units["device_name"][:]).astype("U")
        selected_rows = np.flatnonzero(np.isin(device_names, selected_probes))
        if not len(selected_rows):
            raise RuntimeError(f"{config.session_id} has no selected probes.")
        unit_count = len(selected_rows)
        bin_count = len(relative_bin_centers(config.context))
        if bin_count != output_bin_count:
            raise RuntimeError("SDF source and output bin counts are inconsistent.")
        event_count = len(events)
        sdf_mean = np.zeros(
            (event_count, len(CONDITION_ORDER), unit_count, bin_count),
            dtype=np.uint16,
        )
        baseline_mean = np.full(
            (event_count, len(CONDITION_ORDER), unit_count),
            np.nan,
            dtype=np.float32,
        )
        baseline_std = np.full_like(baseline_mean, np.nan)
        response_rates = np.full(
            (event_count, len(CONDITION_ORDER), unit_count),
            np.nan,
            dtype=np.float32,
        )
        # Per-trial rates, held in memory only. They feed the rank tests and are
        # then discarded: storing them would cost about 40 MB across the four
        # sessions and, with the statistical test fixed at extraction time, buy
        # nothing the stored p, q, and modulation indices do not already give.
        trial_rates: list[dict[str, np.ndarray]] = []
        for event_extract in extraction:
            context_trials = len(event_extract["condition_onsets"]["context"])
            control_trials = len(event_extract["condition_onsets"]["control"])
            trial_rates.append(
                {
                    "context_test": np.full(
                        (unit_count, context_trials), np.nan, dtype=np.float64
                    ),
                    "context_comparison": np.full(
                        (unit_count, context_trials), np.nan, dtype=np.float64
                    ),
                    "context_baseline": np.full(
                        (unit_count, context_trials), np.nan, dtype=np.float64
                    ),
                    "control_test": np.full(
                        (unit_count, control_trials), np.nan, dtype=np.float64
                    ),
                    "control_baseline": np.full(
                        (unit_count, control_trials), np.nan, dtype=np.float64
                    ),
                    "delay": np.full(
                        (unit_count, context_trials), np.nan, dtype=np.float64
                    ),
                    "standard_delay": np.full(
                        (unit_count, context_trials), np.nan, dtype=np.float64
                    ),
                }
            )
        ids = np.asarray(units["id"][:], dtype=int)
        ks_ids = np.asarray(units["ks_unit_id"][:], dtype=int)
        decoder_labels = np.asarray(units["decoder_label"][:]).astype("U")
        depths = np.asarray(units["depth"][:], dtype=float)
        firing_rates = np.asarray(units["firing_rate"][:], dtype=float)
        isi = np.asarray(units["isi_violations_ratio"][:], dtype=float)
        peak_to_valley_ms = (
            np.asarray(units["peak_to_valley"][:], dtype=float) * 1_000
        )
        presence = np.asarray(units["presence_ratio"][:], dtype=float)
        amplitude = np.asarray(units["amplitude_cutoff"][:], dtype=float)
        spreads = (
            np.asarray(units["spread"][:], dtype=float)
            if "spread" in units
            else np.full(len(ids), np.nan)
        )
        if np.any(~np.isfinite(firing_rates[selected_rows])) or np.any(
            firing_rates[selected_rows] < 0
        ):
            raise RuntimeError(f"{config.session_id} has invalid unit firing rates.")
        if np.any(~np.isfinite(peak_to_valley_ms[selected_rows])) or np.any(
            peak_to_valley_ms[selected_rows] < 0
        ):
            raise RuntimeError(
                f"{config.session_id} has invalid peak-to-valley durations."
            )
        spike_ends = np.asarray(units["spike_times_index"][:], dtype=int)
        electrode_ends = np.asarray(units["electrodes_index"][:], dtype=int)
        electrode_refs = np.asarray(units["electrodes"][:], dtype=int)
        electrode_table = nwb["general/extracellular_ephys/electrodes"]
        unit_records = []

        for output_row, row in enumerate(selected_rows):
            electrode_start = 0 if row == 0 else int(electrode_ends[row - 1])
            electrode_stop = int(electrode_ends[row])
            unit_electrodes = electrode_refs[electrode_start:electrode_stop]
            peak_channel = int(units["extremum_channel_index"][row])
            if not 0 <= peak_channel < len(unit_electrodes):
                raise RuntimeError(f"{config.session_id} unit {row} peak channel is invalid.")
            electrode = int(unit_electrodes[peak_channel])
            location = str(decode(electrode_table["location"][electrode]))
            spike_start = 0 if row == 0 else int(spike_ends[row - 1])
            spike_stop = int(spike_ends[row])
            spikes = np.asarray(
                units["spike_times"][spike_start:spike_stop],
                dtype=float,
            )
            if len(spikes) and np.any(np.diff(spikes) < 0):
                raise RuntimeError(f"{config.session_id} unit {row} spikes are unsorted.")
            sst_optotagged, sst_p_value, sst_modulation_index = (
                sst_optotagging_result(spikes, sst_pulse_times)
            )

            for event_index, event_extract in enumerate(extraction):
                for condition_index, condition in enumerate(CONDITION_ORDER):
                    onsets = event_extract["condition_onsets"][condition]
                    count_sum = histogram_trial_counts(
                        spikes,
                        onsets,
                        source_edges,
                    )
                    mean_hz = sdf_trial_mean(
                        count_sum,
                        len(onsets),
                        causal_padding_bins,
                        bin_count,
                    )
                    sdf_mean[
                        event_index,
                        condition_index,
                        output_row,
                    ] = quantize_sdf(mean_hz)
                    response_rates[event_index, condition_index, output_row] = (
                        mean_rate_in_windows(
                            spikes,
                            event_extract["response_windows"][condition],
                        )
                    )
                    mean, std = baseline_rate_stats(
                        spikes,
                        event_extract["baseline_windows"][condition],
                    )
                    baseline_mean[event_index, condition_index, output_row] = mean
                    baseline_std[event_index, condition_index, output_row] = std

                    # Per-trial rates for the responsiveness tests.
                    collected = trial_rates[event_index]
                    collected[f"{condition}_test"][output_row] = rates_in_windows(
                        spikes,
                        event_extract["response_windows"][condition],
                    )
                    collected[f"{condition}_baseline"][output_row] = rates_in_windows(
                        spikes,
                        event_extract["trial_baseline_windows"][condition],
                    )
                    if condition == "context":
                        collected["context_comparison"][output_row] = (
                            rates_in_windows(
                                spikes,
                                event_extract["comparison_windows"],
                            )
                        )
                        if event_extract["delay_windows"]:
                            collected["delay"][output_row] = rates_in_windows(
                                spikes, event_extract["delay_windows"]
                            )
                            collected["standard_delay"][output_row] = (
                                rates_in_windows(
                                    spikes,
                                    event_extract["standard_delay_windows"],
                                )
                            )

            unit_records.append(
                {
                    "amplitudeCutoff": round(float(amplitude[row]), 6),
                    "decoderLabel": str(decoder_labels[row]),
                    "depthUm": round(float(depths[row]), 3),
                    "firingRateHz": round(float(firing_rates[row]), 6),
                    "id": int(ids[row]),
                    "isiViolationsRatio": round(float(isi[row]), 6),
                    "ksUnitId": int(ks_ids[row]),
                    "location": location,
                    "peakToValleyMs": round(float(peak_to_valley_ms[row]), 6),
                    "peakChannel": peak_channel,
                    "presenceRatio": round(float(presence[row]), 6),
                    "probe": str(device_names[row]),
                    "qcPass": qc_passes(
                        isi_violations_ratio=float(isi[row]),
                        presence_ratio=float(presence[row]),
                        amplitude_cutoff=float(amplitude[row]),
                    ),
                    "spreadUm": (
                        round(float(spreads[row]), 3)
                        if math.isfinite(spreads[row])
                        else None
                    ),
                    "sstOptotagged": sst_optotagged,
                    "sstOptotaggingModulationIndex": round(
                        sst_modulation_index,
                        12,
                    ),
                    "sstOptotaggingPValue": round(sst_p_value, 12),
                    "spikeCount": spike_stop - spike_start,
                }
            )
            if (output_row + 1) % 250 == 0 or output_row + 1 == unit_count:
                print(
                    f"{config.context}: {output_row + 1}/{unit_count} units",
                    flush=True,
                )

        annotate_unit_areas(unit_records)
        for unit in unit_records:
            unit["neuronType"] = classify_neuron_type(
                peak_to_valley_ms=unit["peakToValleyMs"],
                major_parent=unit["majorParent"],
                sst_optotagged=unit["sstOptotagged"],
            )
        ranks = rastermap_ranks(
            sdf_mean,
            baseline_mean,
            baseline_std,
            events,
            decoder_labels[selected_rows],
            ids[selected_rows],
            config.context,
        )

        # The effective trial mask combines the context-specific adjacency
        # hygiene with, for sensorimotor only, the running gate and the 2 s
        # minimum-interval rule the released data does not honour.
        gates: list[np.ndarray] | None = None
        gate_summaries: list[dict] | None = None
        if config.context == "sensorimotor":
            gates, gate_summaries = sensorimotor_trial_masks(
                [
                    extraction[index]["condition_onsets"]["context"]
                    for index in range(event_count)
                ],
                [
                    np.asarray(
                        [
                            stop
                            for _start, stop in extraction[index]["response_windows"][
                                "context"
                            ]
                        ],
                        dtype=float,
                    )
                    for index in range(event_count)
                ],
                running_times,
                running_forward,
            )

        effective_masks = []
        for event_index, event in enumerate(events):
            mask = np.asarray(extraction[event_index]["clean_mask"], dtype=bool)
            event["excludedAdjacentTrialCount"] = int((~mask).sum())
            if gates is not None:
                mask = mask & gates[event_index]
                event["runningGate"] = gate_summaries[event_index]
            event["cleanTrialCount"] = int(mask.sum())
            effective_masks.append(mask)

        responsiveness = [
            responsiveness_statistics(
                trial_rates[event_index],
                effective_masks[event_index],
            )
            for event_index in range(event_count)
        ]

        # A reader asking "responsive to any event in this context" runs one test
        # per event per unit, so that filter needs the wider family. Stored
        # alongside the per-event q, which stays the primary value because it
        # matches the per-event claim.
        for key in ("q1_p", "q2_p", "q2_delta_p", "delay_p"):
            stacked = np.stack([record[key] for record in responsiveness])
            wide = benjamini_hochberg(stacked.ravel()).reshape(stacked.shape)
            for event_index, record in enumerate(responsiveness):
                record[f"{key[:-2]}_q_across_events"] = wide[event_index]


    session_prefix = config.context.replace("sensorimotor", "motor")
    sdf_mean_path = media_dir / f"{session_prefix}-sdf-mean.u16.gz"
    sdf_mean_asset = write_gzip(
        sdf_mean_path,
        sdf_mean.astype("<u2").tobytes(),
    )
    response_delta = response_rates[:, 0] - response_rates[:, 1]
    return {
        "asset": asset,
        "baselineMeanHzBase64": encode_float32(baseline_mean),
        "baselineStdHzBase64": encode_float32(baseline_std),
        "conditionOrder": list(CONDITION_ORDER),
        "context": config.context,
        "contextTable": config.context_table,
        "controlTable": config.control_table,
        "sdfMeanAtlas": {
            **sdf_mean_asset,
            "dtype": "uint16 little-endian",
            "quantizationScalePerHz": SDF_QUANTIZATION_SCALE,
            "shape": list(sdf_mean.shape),
        },
        "events": events,
        "responseContextHzBase64": encode_float32(response_rates[:, 0]),
        "responseControlHzBase64": encode_float32(response_rates[:, 1]),
        "responseDeltaHzBase64": encode_float32(response_delta),
        "rastermapRank": {
            "base64": encode_uint16(ranks),
            "dtype": "uint16 little-endian",
            "shape": list(ranks.shape),
        },
        "responsiveness": {
            key: {
                "base64": encode_float32(
                    np.stack([record[key] for record in responsiveness])
                ),
                "dtype": "float32 little-endian",
                "shape": [event_count, unit_count],
            }
            for key in (
                "q1_p",
                "q1_q",
                "q1_modulation",
                "q1_modulation_baseline_subtracted",
                "q1_trials",
                "q2_p",
                "q2_q",
                "q2_modulation",
                "q2_delta_p",
                "q2_delta_q",
                "q2_delta_modulation",
                "q2_trials",
                "q2_control_trials",
                "delay_p",
                "delay_q",
                "delay_modulation",
                "delay_trials",
                "q1_q_across_events",
                "q2_q_across_events",
                "q2_delta_q_across_events",
                "delay_q_across_events",
            )
        },
        "sessionId": config.session_id,
        "subject": NEURAL_SUBJECT,
        "timeBinCentersSeconds": relative_bin_centers(config.context),
        "unitCount": unit_count,
        "units": unit_records,
        "windowSeconds": [window_start, window_stop],
    }


def load_cached_session(session_cache: Path) -> dict | None:
    metadata_path = session_cache / "session.json"
    if metadata_path.is_file():
        cached = json.loads(metadata_path.read_text(encoding="utf-8"))
        valid = True
        for key in ("sdfMeanAtlas",):
            source = session_cache / Path(cached[key]["path"]).name
            valid &= source.is_file() and file_sha256(source) == cached[key]["sha256"]
        if valid:
            return cached
    return None


def install_cached_session(
    cached: dict,
    source_cache: Path,
    target_cache: Path,
    media_dir: Path,
) -> dict:
    target_cache.mkdir(parents=True, exist_ok=True)
    media_dir.mkdir(parents=True, exist_ok=True)
    for key in ("sdfMeanAtlas",):
        source = source_cache / Path(cached[key]["path"]).name
        shutil.copy2(source, target_cache / source.name)
        shutil.copy2(source, media_dir / source.name)
    (target_cache / "session.json").write_text(
        json.dumps(cached, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return cached


def cached_session(
    config,
    media_dir: Path,
    selected_probes: tuple[str, ...],
    cache_dir: Path | None,
    signature: str,
) -> dict:
    if cache_dir is None:
        return extract_session(config, media_dir, selected_probes)
    session_cache = cache_dir / f"{config.asset_id}-{signature[:16]}"
    cached = load_cached_session(session_cache)
    if cached is not None:
        media_dir.mkdir(parents=True, exist_ok=True)
        for key in ("sdfMeanAtlas",):
            source = session_cache / Path(cached[key]["path"]).name
            shutil.copy2(source, media_dir / source.name)
        return cached
    if selected_probes == PROBE_ORDER:
        for compatible_signature in COMPATIBLE_METADATA_SIGNATURES:
            compatible_cache = (
                cache_dir / f"{config.asset_id}-{compatible_signature[:16]}"
            )
            cached = load_cached_session(compatible_cache)
            if cached is None:
                continue
            annotate_unit_areas(cached["units"])
            return install_cached_session(
                cached,
                compatible_cache,
                session_cache,
                media_dir,
            )
    session_cache.mkdir(parents=True, exist_ok=True)
    cached_media = session_cache / "media"
    record = extract_session(config, cached_media, selected_probes)
    return install_cached_session(
        record,
        cached_media,
        session_cache,
        media_dir,
    )


RESPONSIVENESS_COLUMNS = (
    "session_id",
    "context",
    "event_id",
    "unit_id",
    "probe",
    "location",
    "parent_area",
    "major_parent",
    "neuron_type",
    "qc_pass",
    "firing_rate_hz",
    "q1_n_trials",
    "q1_p",
    "q1_q",
    "q1_modulation_index",
    "q1_modulation_index_baseline_subtracted",
    "q1_responsive",
    "q2_n_mismatch",
    "q2_n_control",
    "q2_p",
    "q2_q",
    "q2_modulation_index",
    "q2_delta_p",
    "q2_delta_q",
    "q2_delta_modulation_index",
    "q2_selective",
    "q1_q_across_events",
    "q2_delta_q_across_events",
    "delay_n_trials",
    "delay_p",
    "delay_q",
    "delay_modulation_index",
)


def _csv_number(value) -> str:
    """Six significant figures, empty for non-finite, to keep the table compact."""
    number = float(value)
    if not math.isfinite(number):
        return ""
    return f"{number:.6g}"


def write_responsiveness_csv(path: Path, records: list[dict]) -> dict:
    """Write one row per unit per event: the reviewable responsiveness snapshot."""
    rows = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(",".join(RESPONSIVENESS_COLUMNS) + "\n")
        for record in records:
            responsiveness = record["responsiveness"]
            decoded = {
                key: np.frombuffer(
                    base64.b64decode(responsiveness[key]["base64"]), dtype="<f4"
                ).reshape(responsiveness[key]["shape"])
                for key in responsiveness
            }
            q1_flag = classify_responsive(
                q_values=decoded["q1_q"].ravel(),
                modulation_indices=decoded["q1_modulation"].ravel(),
            ).reshape(decoded["q1_q"].shape)
            q2_flag = classify_responsive(
                q_values=decoded["q2_delta_q"].ravel(),
                modulation_indices=decoded["q2_delta_modulation"].ravel(),
            ).reshape(decoded["q2_delta_q"].shape)

            for event_index, event in enumerate(record["events"]):
                for unit_index, unit in enumerate(record["units"]):
                    cells = [
                        record["sessionId"],
                        record["context"],
                        event["id"],
                        str(unit["id"]),
                        unit["probe"],
                        unit["location"],
                        unit["parentArea"],
                        unit["majorParent"],
                        unit["neuronType"],
                        "1" if unit["qcPass"] else "0",
                        _csv_number(unit["firingRateHz"]),
                        _csv_number(decoded["q1_trials"][event_index, unit_index]),
                        _csv_number(decoded["q1_p"][event_index, unit_index]),
                        _csv_number(decoded["q1_q"][event_index, unit_index]),
                        _csv_number(decoded["q1_modulation"][event_index, unit_index]),
                        _csv_number(
                            decoded["q1_modulation_baseline_subtracted"][
                                event_index, unit_index
                            ]
                        ),
                        "1" if q1_flag[event_index, unit_index] else "0",
                        _csv_number(decoded["q2_trials"][event_index, unit_index]),
                        _csv_number(
                            decoded["q2_control_trials"][event_index, unit_index]
                        ),
                        _csv_number(decoded["q2_p"][event_index, unit_index]),
                        _csv_number(decoded["q2_q"][event_index, unit_index]),
                        _csv_number(decoded["q2_modulation"][event_index, unit_index]),
                        _csv_number(decoded["q2_delta_p"][event_index, unit_index]),
                        _csv_number(decoded["q2_delta_q"][event_index, unit_index]),
                        _csv_number(
                            decoded["q2_delta_modulation"][event_index, unit_index]
                        ),
                        "1" if q2_flag[event_index, unit_index] else "0",
                        _csv_number(
                            decoded["q1_q_across_events"][event_index, unit_index]
                        ),
                        _csv_number(
                            decoded["q2_delta_q_across_events"][event_index, unit_index]
                        ),
                        _csv_number(decoded["delay_trials"][event_index, unit_index]),
                        _csv_number(decoded["delay_p"][event_index, unit_index]),
                        _csv_number(decoded["delay_q"][event_index, unit_index]),
                        _csv_number(
                            decoded["delay_modulation"][event_index, unit_index]
                        ),
                    ]
                    handle.write(",".join(cells) + "\n")
                    rows += 1
    return {
        "path": display_path(path),
        "rows": rows,
        "sha256": file_sha256(path),
        "size": path.stat().st_size,
    }


def write_json(path: Path, payload: dict) -> None:
    def json_safe(value):
        if isinstance(value, dict):
            return {key: json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [json_safe(item) for item in value]
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            json_safe(payload),
            allow_nan=False,
            indent=2,
            ensure_ascii=True,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    args = parse_args()
    if args.max_workers < 1:
        raise SystemExit("--max-workers must be at least one.")
    dt.date.fromisoformat(args.retrieved_date)
    installed_rastermap_version = version("rastermap")
    if installed_rastermap_version != RASTERMAP_VERSION:
        raise SystemExit(
            f"Rastermap {RASTERMAP_VERSION} is required; found "
            f"{installed_rastermap_version}."
        )
    selected_sessions = set(args.session_id or ())
    configs = [
        config
        for config in NEURAL_SESSIONS
        if not selected_sessions or config.session_id in selected_sessions
    ]
    if not configs:
        raise SystemExit("No configured sessions matched --session-id.")
    selected_probes = tuple(args.probe or PROBE_ORDER)
    signature = analysis_signature(selected_probes)
    args.media_dir.mkdir(parents=True, exist_ok=True)
    records = []
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {
            executor.submit(
                cached_session,
                config,
                args.media_dir,
                selected_probes,
                args.cache_dir,
                signature,
            ): config
            for config in configs
        }
        for future in as_completed(futures):
            config = futures[future]
            records.append(future.result())
            print(f"extracted {config.session_id}", flush=True)
    order = {
        context: index
        for index, context in enumerate(
            ("standard", "sensorimotor", "sequence", "duration")
        )
    }
    records.sort(key=lambda record: order[record["context"]])
    payload = {
        "analysisParameters": {
            "baselineRules": {
                "duration": "row i-2 stop_time through row i-1 start_time",
                "sensorimotor": "343 ms immediately preceding event start_time",
                "sequence": (
                    "context: grey inter-sequence interval at row i-3, the full row "
                    "from its start_time through its stop_time. control: control "
                    "block 2 is contiguous and contains no grey, so baselines are "
                    "the blank inter-stimulus intervals of the control block 1 "
                    "repeat that ends where control block 2 begins, sampled evenly "
                    "across that repeat, one per trial"
                ),
                "standard": "previous row stop_time through event start_time",
            },
            "baselineBinSeconds": BASELINE_BIN_SECONDS,
            "binSeconds": BIN_SECONDS,
            "contextWindowsSeconds": {
                context: list(window)
                for context, window in CONTEXT_WINDOWS_SECONDS.items()
            },
            "cellTypeClassification": {
                "defaultFastSpikingMaximumMs": 0.4,
                "striatum": "RS",
                "sst": {
                    "condition": SST_OPTOTAGGING_CONDITION.table_name,
                    "modulationIndexMinimum": SST_MODULATION_INDEX_MIN,
                    "pValueMaximum": SST_P_VALUE_MAX,
                },
                "sstOverridesWaveformClass": True,
                "thalamicFastSpikingMaximumMs": 0.28,
            },
            "responsiveness": {
                "comparisonRules": {
                    "duration": (
                        "pre-delay stimulus at row i-1, against the post-delay "
                        "stimulus at row i"
                    ),
                    "sensorimotor": (
                        f"{SENSORIMOTOR_BASELINE_SECONDS * 1000:.0f} ms immediately "
                        "preceding event start_time, because closed-loop flow is "
                        "continuous and has no preceding trial"
                    ),
                    "sequence": (
                        "element three of the previous sequence at row i-5, the same "
                        "physical sequence position"
                    ),
                    "standard": (
                        "previous presentation at row i-1, the expected standard "
                        "stimulus"
                    ),
                },
                "sensorimotorGate": {
                    "minimumIntervalSeconds": SENSORIMOTOR_MIN_INTERVAL_SECONDS,
                    "rationale": (
                        "closed-loop optic flow is self-generated, so a stationary "
                        "animal has no flow to decouple and the mismatch is not a "
                        "stimulus; the protocol's 2 s minimum separation is also not "
                        "honoured in the released data"
                    ),
                    "runningThresholdCmS": DEFAULT_RUNNING_THRESHOLD_CM_S,
                    "runningWindows": (
                        "mean forward speed must reach the threshold in both the "
                        "pre-event baseline window and the mismatch window"
                    ),
                },
                "hygiene": (
                    "a mismatch preceded by another mismatch is excluded from Q1, "
                    "because its comparison is not an expected stimulus; for sequence "
                    "the whole previous sequence must be free of substitutions"
                ),
                "modulationIndex": (
                    "trial-wise mean of (test - comparison) / (test + comparison), "
                    "matching the SST optotagging convention"
                ),
                "multipleComparisons": {
                    "family": (
                        "all units recorded in one context block, tested at one event, "
                        "for one test. Sessions and contexts are one to one and units "
                        "are distinct acute insertions never shared between sessions, "
                        "so there is no cross-session multiplicity to correct"
                    ),
                    "familyAcrossEvents": (
                        "a second Benjamini-Hochberg value is stored over units by "
                        "events, for the 'responsive to any event' selection, which "
                        "implicitly runs one test per event per unit"
                    ),
                    "familyIncludesFilteredUnits": (
                        "the family deliberately spans every unit rather than only the "
                        "analysable set, so the stored q stays valid whatever unit "
                        "filters a reader applies"
                    ),
                    "method": "Benjamini-Hochberg",
                    "note": (
                        "non-finite p values are excluded from the family rather than "
                        "treated as non-significant"
                    ),
                    "reporting": (
                        "the figure reports the uncorrected p with the chance "
                        "expectation shown alongside every count, because the observed "
                        "signal runs 7 to 12 times chance for most events so the "
                        "uncorrected false-discovery proportion is about 8 to 13 "
                        "percent; corrected q values remain available as a stricter "
                        "option and are used for example-neuron selection"
                    ),
                },
                "q1": {
                    "question": (
                        "is the unit driven differently by the mismatch than by the "
                        "most recent expected instance in the same block"
                    ),
                    "test": "paired Wilcoxon signed-rank across trials, zero_method zsplit",
                    "baselineInvariance": (
                        "both windows are presentations in the same trial, so "
                        "subtracting that trial's baseline leaves the paired difference "
                        "unchanged; the p value is identical with and without baseline "
                        "subtraction and only the modulation index differs"
                    ),
                },
                "delayEpoch": {
                    "contexts": ["duration"],
                    "question": (
                        "does firing during the violated delay differ from firing "
                        "during a standard delay in the same trial"
                    ),
                    "test": "paired Wilcoxon signed-rank across trials, zero_method zsplit",
                    "windows": (
                        "violated delay from row i-1 stop_time to row i start_time, "
                        "against the standard delay from row i-2 stop_time to row i-1 "
                        "start_time"
                    ),
                    "rationale": (
                        "the duration manipulation changes the delay itself, which the "
                        "post-delay comparison does not test; deviant delays of 150, "
                        "500 and 1000 ms give windows of unequal length, so rates "
                        "rather than counts are compared and the 150 ms window is the "
                        "noisiest"
                    ),
                },
                "q2": {
                    "question": (
                        "is the unit's mismatch response different from the same "
                        "physical event in the matched control block"
                    ),
                    "test": "Mann-Whitney U, two-sided",
                    "unpaired": (
                        "trial counts differ between blocks and the blocks are recorded "
                        "at different times, so the comparison cannot be paired"
                    ),
                    "variants": (
                        "raw response windows and baseline-subtracted responses are both "
                        "reported; subtraction matters here because each block has its "
                        "own baseline"
                    ),
                },
                "thresholds": {
                    "modulationIndexMinimum": DEFAULT_MODULATION_MINIMUM,
                    "qValueMaximum": DEFAULT_Q_MAX,
                    "twoSided": True,
                    "twoSidedNote": (
                        "suppression counts as responsive, unlike the one-sided SST "
                        "optotagging rule, because a mismatch can reduce firing"
                    ),
                },
            },
            "heatmapModes": [
                "mismatch SDF spikes/s",
                "control SDF spikes/s",
                "mismatch-minus-control SDF spikes/s",
                "mismatch baseline z score",
                "control baseline z score",
            ],
            "ontology": {
                "areaSource": (
                    "Allen CCF location of each unit's extremum-channel electrode"
                ),
                "graphOrderSource": (
                    "Allen structure-tree graph_order via iblatlas BrainRegions.order"
                ),
                "packageVersion": version("iblatlas"),
                "parentAreaRule": (
                    "collapse Allen layer nodes and hyphenated subdivisions to the "
                    "nearest non-collapsible ancestor; retain an already canonical area"
                ),
            },
            "firingRateSource": "NWB Units firing_rate",
            "qcThresholds": QC_THRESHOLDS,
            "rastermap": {
                "input": (
                    "native 1 ms causal-exponential SDF mismatch baseline z score "
                    "over the displayed peri-event window"
                ),
                "packageVersion": RASTERMAP_VERSION,
                "parameters": RASTERMAP_PARAMETERS,
            },
            "responseWindow": "selected row NWB start_time through stop_time",
            "sdf": {
                "causalPrepaddingSeconds": (
                    (len(sdf_kernel()) - 1)
                    * SDF_SOURCE_BIN_SECONDS
                ),
                "displayBinSeconds": BIN_SECONDS,
                "kernel": "causal exponential",
                "kernelDurationTau": SDF_KERNEL_DURATION_TAU,
                "kernelSamples": len(sdf_kernel()),
                "quantizationScalePerHz": SDF_QUANTIZATION_SCALE,
                "sourceBinSeconds": SDF_SOURCE_BIN_SECONDS,
                "tauSeconds": SDF_TAU_SECONDS,
            },
            "unitDefault": {
                "decoderLabels": ["mua", "sua"],
                "minimumFiringRateHz": 1.0,
                "neuronTypes": ["RS", "FS", "SST"],
                "numericalQc": "manuscript QC passing",
            },
        },
        "sessionOrder": [record["context"] for record in records],
        "sessions": records,
        "subject": NEURAL_SUBJECT,
        "version": VERSION,
    }
    write_json(args.output, payload)
    responsiveness_asset = write_responsiveness_csv(
        args.responsiveness_output, records
    )
    referenced_media = {
        Path(record[key]["path"]).name
        for record in records
        for key in ("sdfMeanAtlas",)
    }
    for path in args.media_dir.glob("*.gz"):
        if path.name not in referenced_media:
            path.unlink()
    media = sorted(
        [
            {
                "path": display_path(path),
                "sha256": file_sha256(path),
                "size": path.stat().st_size,
            }
            for path in args.media_dir.glob("*.gz")
        ],
        key=lambda record: record["path"],
    )
    provenance = {
        "analysisSignature": signature,
        "configuredSessions": [asdict(config) for config in configs],
        "media": media,
        "responsivenessTable": responsiveness_asset,
        "responsivenessModule": {
            "path": "src/openscope_p3_publication/mismatch_responsiveness.py",
            "sha256": file_sha256(
                REPO_ROOT
                / "src"
                / "openscope_p3_publication"
                / "mismatch_responsiveness.py"
            ),
        },
        "module": {
            "path": "src/openscope_p3_publication/neural_responses.py",
            "sha256": file_sha256(
                REPO_ROOT / "src" / "openscope_p3_publication" / "neural_responses.py"
            ),
        },
        "ontology": {
            "graphOrderField": "BrainRegions.order",
            "packageVersion": version("iblatlas"),
            "sourceField": "Allen structure-tree graph_order",
        },
        "outputPath": display_path(args.output),
        "outputSha256": file_sha256(args.output),
        "rastermap": {
            "packageVersion": RASTERMAP_VERSION,
            "parameters": RASTERMAP_PARAMETERS,
        },
        "retrievedDate": args.retrieved_date,
        "script": {
            "path": "scripts/extract_neuropixels_event_responses.py",
            "sha256": file_sha256(Path(__file__)),
        },
        "sessionCount": len(records),
        "totalQcUnits": sum(
            sum(unit["qcPass"] for unit in record["units"]) for record in records
        ),
        "totalUnits": sum(record["unitCount"] for record in records),
        "version": VERSION,
    }
    write_json(args.provenance_output, provenance)
    print(f"Wrote {args.output}")
    print(f"Wrote {args.provenance_output}")


if __name__ == "__main__":
    main()
