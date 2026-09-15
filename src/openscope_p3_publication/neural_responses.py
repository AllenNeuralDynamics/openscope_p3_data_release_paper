from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .pupil_responses import EVENT_DEFINITIONS, EventDefinition, event_matches

CONTEXT_WINDOWS_SECONDS = {
    "standard": (-0.75, 0.75),
    "sensorimotor": (-0.75, 0.75),
    # Wide enough for the previous sequence to be both computable and visible.
    # Rows are a measured 266.9 ms, so element three of the previous sequence
    # sits at -1.3345 s and that sequence begins at -1.868 s.
    "sequence": (-2.0, 1.0),
    "duration": (-1.5, 1.5),
}
SEQUENCE_BASELINE_OFFSET = -3
"""Row offset of the grey inter-sequence interval from a substituted element."""
BIN_SECONDS = 0.0025
BASELINE_BIN_SECONDS = 0.02
SDF_SOURCE_BIN_SECONDS = 0.0025
SDF_TAU_SECONDS = 0.01
SDF_KERNEL_DURATION_TAU = 10
SDF_QUANTIZATION_SCALE = 20
QC_THRESHOLDS = {
    "amplitude_cutoff_max": 0.1,
    "isi_violations_ratio_max": 0.5,
    "presence_ratio_min": 0.8,
}
RASTERMAP_VERSION = "1.0"
RASTERMAP_PARAMETERS = {
    "grid_upsample": 10,
    "locality": 0.0,
    "mean_time": True,
    "n_PCs": 200,
    "n_clusters": 100,
    "n_splits": 0,
    "normalize": True,
    "random_state": 0,
    "run_scaled_kmeans": True,
    "time_bin": 0,
    "time_lag_window": 0,
}


@dataclass(frozen=True)
class NeuralSession:
    context: str
    session_id: str
    asset_id: str
    asset_path: str
    context_table: str
    control_table: str


# Mouse 830794. Its predecessor, 830846, averaged 1.12 cm/s in the sensorimotor
# block with a median of 0.00 and retained 2 to 4 trials per mismatch type after
# running gating, which cannot support a closed-loop analysis. 830794 runs in
# every context and has the highest QC-passing unit count in the release.
#
# These asset IDs pin the August 2026 revisions of the draft. Dandiset 001637 is
# mutable and 48 of its 60 assets were replaced that month; the earlier June
# revisions labelled one visual area with an acronym absent from the Allen
# ontology, which the August revisions fixed. See
# docs/neuropixels-area-label-provenance.md.
NEURAL_SUBJECT = "830794"
NEURAL_SESSIONS = (
    NeuralSession(
        context="sensorimotor",
        session_id="ecephys_830794_2026-01-26_12-02-05",
        asset_id="0766996b-2afa-4c6f-a381-134c9e380edc",
        asset_path=(
            "sub-830794/"
            "sub-830794_ses-ecephys-830794-2026-01-26-12-02-05_ecephys.nwb"
        ),
        context_table="Sensory-motor mismatch block_presentations",
        control_table="Control block 4_presentations",
    ),
    NeuralSession(
        context="standard",
        session_id="ecephys_830794_2026-01-27_11-25-31",
        asset_id="50a50f11-dbf8-482f-bc8f-6629e91c2f06",
        asset_path=(
            "sub-830794/"
            "sub-830794_ses-ecephys-830794-2026-01-27-11-25-31_ecephys.nwb"
        ),
        context_table="Standard mismatch block_presentations",
        control_table="Control block 1_presentations",
    ),
    NeuralSession(
        context="sequence",
        session_id="ecephys_830794_2026-01-28_11-01-44",
        asset_id="f30a96cf-3d66-4975-8d43-65138633fb93",
        asset_path=(
            "sub-830794/"
            "sub-830794_ses-ecephys-830794-2026-01-28-11-01-44_ecephys.nwb"
        ),
        context_table="Sequence mismatch block_presentations",
        control_table="Control block 2_presentations",
    ),
    NeuralSession(
        context="duration",
        session_id="ecephys_830794_2026-01-29_11-12-57",
        asset_id="d8a2fb8e-d542-4c9b-9c71-38942b2049f0",
        asset_path=(
            "sub-830794/"
            "sub-830794_ses-ecephys-830794-2026-01-29-11-12-57_ecephys.nwb"
        ),
        context_table="Duration mismatch block_presentations",
        control_table="Control block 3_presentations",
    ),
)


def context_window_seconds(context: str) -> tuple[float, float]:
    try:
        return CONTEXT_WINDOWS_SECONDS[context]
    except KeyError as exc:
        raise ValueError(f"Unknown neural-response context: {context}") from exc


def relative_bin_edges(context: str) -> list[float]:
    start, stop = context_window_seconds(context)
    count = round((stop - start) / BIN_SECONDS)
    return [start + index * BIN_SECONDS for index in range(count + 1)]


def relative_bin_centers(context: str) -> list[float]:
    edges = relative_bin_edges(context)
    return [(left + right) / 2 for left, right in zip(edges[:-1], edges[1:], strict=True)]


def event_indices(
    trial_types: Sequence[str],
    orientations: Sequence[float],
    delays: Sequence[float],
    definition: EventDefinition,
    *,
    control: bool,
) -> list[int]:
    if not (len(trial_types) == len(orientations) == len(delays)):
        raise ValueError("Stimulus-table arrays must have the same length.")
    return [
        index
        for index, (trial_type, orientation, delay) in enumerate(
            zip(trial_types, orientations, delays, strict=True)
        )
        if event_matches(
            definition,
            str(trial_type),
            control=control,
            orientation=float(orientation),
            delay=float(delay),
        )
    ]


def neural_baseline_windows(
    start_times: Sequence[float],
    stop_times: Sequence[float],
    indices: Sequence[int],
    context: str,
    block_numbers: Sequence[float] | None = None,
) -> list[tuple[float, float] | None]:
    """Return neural baseline windows without using a duration mismatch delay."""
    if len(start_times) != len(stop_times):
        raise ValueError("start_times and stop_times must have the same length.")
    if block_numbers is not None and len(block_numbers) != len(start_times):
        raise ValueError("block_numbers must match the stimulus-table length.")
    if context not in EVENT_DEFINITIONS:
        raise ValueError(f"Unknown neural-response context: {context}")

    windows = []
    for index in indices:
        event_start = float(start_times[index])
        if context == "duration":
            if index < 2 or (
                block_numbers is not None
                and (
                    block_numbers[index - 2] != block_numbers[index]
                    or block_numbers[index - 1] != block_numbers[index]
                )
            ):
                windows.append(None)
                continue
            start = float(stop_times[index - 2])
            stop = float(start_times[index - 1])
        elif context == "standard":
            if index == 0 or (
                block_numbers is not None
                and block_numbers[index - 1] != block_numbers[index]
            ):
                windows.append(None)
                continue
            start = float(stop_times[index - 1])
            stop = event_start
        elif context == "sequence":
            # The grey inter-sequence interval, not the preceding grating
            # element. Sequences are five rows (four gratings then grey) with
            # the substitution at element three, so the grey sits three rows
            # back. Verified in 140/140 mismatch trials.
            reference = index + SEQUENCE_BASELINE_OFFSET
            if reference < 0 or (
                block_numbers is not None
                and block_numbers[reference] != block_numbers[index]
            ):
                windows.append(None)
                continue
            start = float(start_times[reference])
            stop = float(stop_times[reference])
        else:
            start = event_start - 0.343
            stop = event_start
        if start >= stop:
            raise ValueError(
                f"{context} event has a nonpositive neural baseline: {start}, {stop}"
            )
        windows.append((start, stop))
    return windows


def neural_response_windows(
    start_times: Sequence[float],
    stop_times: Sequence[float],
    indices: Sequence[int],
) -> list[tuple[float, float]]:
    if len(start_times) != len(stop_times):
        raise ValueError("start_times and stop_times must have the same length.")
    windows = []
    for index in indices:
        start = float(start_times[index])
        stop = float(stop_times[index])
        if start >= stop:
            raise ValueError(f"Neural response window is nonpositive: {start}, {stop}")
        windows.append((start, stop))
    return windows


def qc_passes(
    *,
    isi_violations_ratio: float,
    presence_ratio: float,
    amplitude_cutoff: float,
) -> bool:
    return (
        math.isfinite(isi_violations_ratio)
        and math.isfinite(presence_ratio)
        and math.isfinite(amplitude_cutoff)
        and isi_violations_ratio < QC_THRESHOLDS["isi_violations_ratio_max"]
        and presence_ratio > QC_THRESHOLDS["presence_ratio_min"]
        and amplitude_cutoff < QC_THRESHOLDS["amplitude_cutoff_max"]
    )


def classify_neuron_type(
    *,
    peak_to_valley_ms: float,
    major_parent: str,
    sst_optotagged: bool,
) -> str:
    if sst_optotagged:
        return "SST"
    if not math.isfinite(peak_to_valley_ms) or peak_to_valley_ms < 0:
        raise ValueError("Peak-to-valley duration must be finite and nonnegative.")
    if major_parent == "STR":
        return "RS"
    fast_spiking_limit_ms = 0.28 if major_parent == "TH" else 0.4
    return "FS" if peak_to_valley_ms <= fast_spiking_limit_ms else "RS"


def sdf_kernel(
    *,
    bin_seconds: float = SDF_SOURCE_BIN_SECONDS,
    tau_seconds: float = SDF_TAU_SECONDS,
    duration_tau: int = SDF_KERNEL_DURATION_TAU,
) -> list[float]:
    if bin_seconds <= 0 or tau_seconds <= 0 or duration_tau < 1:
        raise ValueError("Spike-density kernel parameters must be positive.")
    sample_count = max(1, int(duration_tau * tau_seconds / bin_seconds))
    weights = [
        math.exp(-(index * bin_seconds) / tau_seconds)
        for index in range(sample_count)
    ]
    total = sum(weights)
    return [weight / total for weight in weights]


def smooth_trace(
    values: Sequence[float],
    kernel: Sequence[float] | None = None,
) -> list[float]:
    kernel = sdf_kernel() if kernel is None else list(kernel)
    if not kernel:
        raise ValueError("Smoothing kernel must not be empty.")
    smoothed = []
    for index in range(len(values)):
        weighted = 0.0
        for lag, weight in enumerate(kernel):
            source_index = index - lag
            if source_index >= 0:
                weighted += float(values[source_index]) * weight
        smoothed.append(weighted)
    return smoothed


def context_event_definitions(context: str) -> tuple[EventDefinition, ...]:
    try:
        return EVENT_DEFINITIONS[context]
    except KeyError as exc:
        raise ValueError(f"Unknown neural-response context: {context}") from exc
