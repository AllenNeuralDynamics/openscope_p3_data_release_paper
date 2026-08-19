from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .pupil_responses import EVENT_DEFINITIONS, EventDefinition, event_matches

WINDOW_START_SECONDS = -1.5
WINDOW_END_SECONDS = 2.0
BIN_SECONDS = 0.02
SMOOTHING_SIGMA_SECONDS = 0.04
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


NEURAL_SESSIONS = (
    NeuralSession(
        context="sequence",
        session_id="ecephys_830846_2026-03-09_10-32-54",
        asset_id="03973a42-cf55-476f-80d7-85bc402fa57b",
        asset_path=(
            "sub-830846/"
            "sub-830846_ses-ecephys-830846-2026-03-09-10-32-54_ecephys.nwb"
        ),
        context_table="Sequence mismatch block_presentations",
        control_table="Control block 2_presentations",
    ),
    NeuralSession(
        context="duration",
        session_id="ecephys_830846_2026-03-10_10-17-25",
        asset_id="77123ffa-5029-4485-a2e5-2eacac954f74",
        asset_path=(
            "sub-830846/"
            "sub-830846_ses-ecephys-830846-2026-03-10-10-17-25_ecephys.nwb"
        ),
        context_table="Duration mismatch block_presentations",
        control_table="Control block 3_presentations",
    ),
    NeuralSession(
        context="standard",
        session_id="ecephys_830846_2026-03-11_10-19-32",
        asset_id="680d1c0c-e338-4d0b-ba29-4329436d2ae2",
        asset_path=(
            "sub-830846/"
            "sub-830846_ses-ecephys-830846-2026-03-11-10-19-32_ecephys.nwb"
        ),
        context_table="Standard mismatch block_presentations",
        control_table="Control block 1_presentations",
    ),
    NeuralSession(
        context="sensorimotor",
        session_id="ecephys_830846_2026-03-12_11-09-13",
        asset_id="7b0e4734-f3e6-4733-8318-223a28687ec1",
        asset_path=(
            "sub-830846/"
            "sub-830846_ses-ecephys-830846-2026-03-12-11-09-13_ecephys.nwb"
        ),
        context_table="Sensory-motor mismatch block_presentations",
        control_table="Control block 4_presentations",
    ),
)


def relative_bin_edges() -> list[float]:
    count = round((WINDOW_END_SECONDS - WINDOW_START_SECONDS) / BIN_SECONDS)
    return [WINDOW_START_SECONDS + index * BIN_SECONDS for index in range(count + 1)]


def relative_bin_centers() -> list[float]:
    edges = relative_bin_edges()
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
            if index == 0 or (
                block_numbers is not None
                and block_numbers[index - 1] != block_numbers[index]
            ):
                windows.append(None)
                continue
            start = float(start_times[index - 1])
            stop = event_start
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


def gaussian_kernel(
    *,
    bin_seconds: float = BIN_SECONDS,
    sigma_seconds: float = SMOOTHING_SIGMA_SECONDS,
    radius_sigma: float = 3,
) -> list[float]:
    if bin_seconds <= 0 or sigma_seconds <= 0 or radius_sigma <= 0:
        raise ValueError("Gaussian-kernel parameters must be positive.")
    sigma_bins = sigma_seconds / bin_seconds
    radius = max(1, math.ceil(radius_sigma * sigma_bins))
    weights = [
        math.exp(-0.5 * (offset / sigma_bins) ** 2)
        for offset in range(-radius, radius + 1)
    ]
    total = sum(weights)
    return [weight / total for weight in weights]


def smooth_trace(
    values: Sequence[float],
    kernel: Sequence[float] | None = None,
) -> list[float]:
    kernel = gaussian_kernel() if kernel is None else list(kernel)
    if not kernel or len(kernel) % 2 != 1:
        raise ValueError("Smoothing kernel must have positive odd length.")
    radius = len(kernel) // 2
    smoothed = []
    for index in range(len(values)):
        weighted = 0.0
        weight_sum = 0.0
        for kernel_index, weight in enumerate(kernel):
            source_index = index + kernel_index - radius
            if 0 <= source_index < len(values):
                weighted += float(values[source_index]) * weight
                weight_sum += weight
        smoothed.append(weighted / weight_sum)
    return smoothed


def context_event_definitions(context: str) -> tuple[EventDefinition, ...]:
    try:
        return EVENT_DEFINITIONS[context]
    except KeyError as exc:
        raise ValueError(f"Unknown neural-response context: {context}") from exc
