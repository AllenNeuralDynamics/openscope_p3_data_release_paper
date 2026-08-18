from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class EventDefinition:
    id: str
    label: str
    context_trial_type: str
    control_trial_type: str
    parameter: str | None = None
    value: float | None = None
    static_group: str | None = None


EVENT_DEFINITIONS = {
    "standard": (
        EventDefinition(
            "orientation_45",
            "45 degree orientation",
            "orientation_45",
            "single",
            "orientation",
            math.pi / 4,
            "orientation",
        ),
        EventDefinition(
            "orientation_90",
            "90 degree orientation",
            "orientation_90",
            "single",
            "orientation",
            math.pi / 2,
            "orientation",
        ),
        EventDefinition("halt", "Halt", "halt", "halt"),
        EventDefinition("omission", "Omission", "omission", "omission"),
    ),
    "sensorimotor": (
        EventDefinition(
            "motor_orientation_45",
            "45 degree motor orientation",
            "motor_orientation_45",
            "motor_orientation_45",
            static_group="motor_orientation",
        ),
        EventDefinition(
            "motor_orientation_90",
            "90 degree motor orientation",
            "motor_orientation_90",
            "motor_orientation_90",
            static_group="motor_orientation",
        ),
        EventDefinition("motor_halt", "Motor halt", "motor_halt", "motor_halt"),
        EventDefinition(
            "motor_omission",
            "Motor omission",
            "motor_omission",
            "motor_omission",
        ),
    ),
    "sequence": (
        EventDefinition(
            "orientation_45",
            "45 degree substitution",
            "orientation_45",
            "single",
            "orientation",
            math.pi / 4,
            "orientation",
        ),
        EventDefinition(
            "orientation_90",
            "90 degree substitution",
            "orientation_90",
            "single",
            "orientation",
            math.pi / 2,
            "orientation",
        ),
        EventDefinition("halt", "Halt", "halt", "halt"),
        EventDefinition("omission", "Omission", "omission", "omission"),
    ),
    "duration": (
        EventDefinition(
            "delay_150",
            "150 ms delay",
            "jitter",
            "single",
            "delay",
            0.15,
        ),
        EventDefinition(
            "delay_500",
            "500 ms delay",
            "jitter",
            "single",
            "delay",
            0.5,
        ),
        EventDefinition(
            "delay_1000",
            "1000 ms delay",
            "jitter",
            "single",
            "delay",
            1.0,
        ),
        EventDefinition("omission", "Omission", "omission", "omission"),
    ),
}

SENSORIMOTOR_BASELINE_SECONDS = 0.343
DURATION_STIMULUS_COMMAND_SECONDS = 0.343


def event_start_times(
    start_times: Sequence[float],
    indices: Sequence[int],
) -> list[float]:
    """Return display-synchronized NWB start times for selected event rows."""
    return [float(start_times[index]) for index in indices]


def event_baseline_windows(
    start_times: Sequence[float],
    stop_times: Sequence[float],
    indices: Sequence[int],
    context: str,
    block_numbers: Sequence[float] | None = None,
) -> list[tuple[float, float] | None]:
    """Return the context-specific pre-event pupil baseline for each selected row."""
    if len(start_times) != len(stop_times):
        raise ValueError("start_times and stop_times must have the same length.")
    if block_numbers is not None and len(block_numbers) != len(start_times):
        raise ValueError("block_numbers must match the stimulus-table length.")
    if context not in EVENT_DEFINITIONS:
        raise ValueError(f"Unknown pupil-response context: {context}")

    windows = []
    for index in indices:
        end = float(start_times[index])
        if context in {"standard", "duration"}:
            if index == 0 or (
                block_numbers is not None
                and block_numbers[index - 1] != block_numbers[index]
            ):
                windows.append(None)
                continue
            start = float(stop_times[index - 1])
        elif context == "sequence":
            if index == 0 or (
                block_numbers is not None
                and block_numbers[index - 1] != block_numbers[index]
            ):
                windows.append(None)
                continue
            start = float(start_times[index - 1])
        else:
            start = end - SENSORIMOTOR_BASELINE_SECONDS
        if start >= end:
            raise ValueError(
                f"{context} event has a nonpositive baseline interval: {start}, {end}"
            )
        windows.append((start, end))
    return windows


def event_response_windows(
    start_times: Sequence[float],
    stop_times: Sequence[float],
    delays: Sequence[float],
    indices: Sequence[int],
    context: str,
) -> list[tuple[float, float]]:
    """Return the absolute pupil-response interval for each selected event row."""
    if not (len(start_times) == len(stop_times) == len(delays)):
        raise ValueError("Stimulus timing arrays must have the same length.")
    if context not in EVENT_DEFINITIONS:
        raise ValueError(f"Unknown pupil-response context: {context}")

    windows = []
    for index in indices:
        if context == "duration":
            start = float(start_times[index]) + DURATION_STIMULUS_COMMAND_SECONDS
            end = start + float(delays[index])
        else:
            start = float(start_times[index])
            end = float(stop_times[index])
        if start >= end:
            raise ValueError(
                f"{context} event has a nonpositive response interval: {start}, {end}"
            )
        windows.append((start, end))
    return windows


def pupil_response_window_label(
    context: str,
    event_id: str,
) -> str:
    if context not in EVENT_DEFINITIONS:
        raise ValueError(f"Unknown pupil-response context: {context}")
    if context != "duration":
        return "NWB start_time–stop_time"
    definition = next(
        (event for event in EVENT_DEFINITIONS[context] if event.id == event_id),
        None,
    )
    if definition is None:
        raise ValueError(f"Unknown {context} pupil-response event: {event_id}")
    delay = (
        definition.value
        if definition.parameter == "delay"
        else DURATION_STIMULUS_COMMAND_SECONDS
    )
    end = DURATION_STIMULUS_COMMAND_SECONDS + float(delay)
    return f"{DURATION_STIMULUS_COMMAND_SECONDS:g}–{end:g} s"


def event_matches(
    definition: EventDefinition,
    trial_type: str,
    *,
    control: bool,
    orientation: float | None = None,
    delay: float | None = None,
) -> bool:
    expected_type = (
        definition.control_trial_type if control else definition.context_trial_type
    )
    if trial_type != expected_type:
        return False
    if definition.parameter == "orientation":
        return orientation is not None and math.isclose(
            orientation,
            definition.value or 0,
            rel_tol=0,
            abs_tol=1e-6,
        )
    if definition.parameter == "delay":
        return delay is not None and math.isclose(
            delay,
            definition.value or 0,
            rel_tol=0,
            abs_tol=1e-6,
        )
    return True


def remove_isolated_outliers_with_interpolation(
    trace: Sequence[float],
    sample_rate_hz: float,
    *,
    window_seconds: float = 3.0,
    zscore_threshold: float = 3.0,
    max_isolated_length: int = 3,
) -> tuple[list[float], list[int]]:
    if sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be positive.")
    if window_seconds <= 0:
        raise ValueError("window_seconds must be positive.")
    if zscore_threshold <= 0:
        raise ValueError("zscore_threshold must be positive.")
    if max_isolated_length < 1:
        raise ValueError("max_isolated_length must be at least one.")

    values = [float(value) for value in trace]
    window = max(3, round(window_seconds * sample_rate_hz))
    if window > len(values):
        return values, []

    prefix_counts = [0]
    prefix_sums = [0.0]
    prefix_squares = [0.0]
    for value in values:
        finite = math.isfinite(value)
        prefix_counts.append(prefix_counts[-1] + int(finite))
        prefix_sums.append(prefix_sums[-1] + (value if finite else 0.0))
        prefix_squares.append(
            prefix_squares[-1] + (value * value if finite else 0.0)
        )

    half_window = window // 2
    outliers = [False] * len(values)
    for index, value in enumerate(values):
        start = index - half_window
        end = start + window
        if start < 0 or end > len(values) or not math.isfinite(value):
            continue
        count = prefix_counts[end] - prefix_counts[start]
        if count != window:
            continue
        total = prefix_sums[end] - prefix_sums[start]
        total_squared = prefix_squares[end] - prefix_squares[start]
        mean = total / count
        variance = max(
            0.0,
            (total_squared - total * total / count) / (count - 1),
        )
        standard_deviation = math.sqrt(variance)
        if (
            standard_deviation > 0
            and abs(value - mean) / standard_deviation > zscore_threshold
        ):
            outliers[index] = True

    isolated_indices = []
    start = 0
    while start < len(outliers):
        if not outliers[start]:
            start += 1
            continue
        end = start + 1
        while end < len(outliers) and outliers[end]:
            end += 1
        if end - start <= max_isolated_length:
            isolated_indices.extend(range(start, end))
        start = end

    cleaned = values.copy()
    isolated = set(isolated_indices)
    for index in isolated_indices:
        left = index - 1
        while left >= 0 and (left in isolated or not math.isfinite(cleaned[left])):
            left -= 1
        right = index + 1
        while right < len(cleaned) and (
            right in isolated or not math.isfinite(cleaned[right])
        ):
            right += 1
        if left < 0 or right >= len(cleaned):
            continue
        fraction = (index - left) / (right - left)
        cleaned[index] = cleaned[left] + fraction * (cleaned[right] - cleaned[left])
    return cleaned, isolated_indices


def mean_trace(traces: Sequence[Sequence[float | None]]) -> list[float | None]:
    if not traces:
        return []
    width = len(traces[0])
    if any(len(trace) != width for trace in traces):
        raise ValueError("All traces must have the same length.")
    result = []
    for column in zip(*traces, strict=True):
        finite = [
            float(value)
            for value in column
            if value is not None and math.isfinite(value)
        ]
        result.append(sum(finite) / len(finite) if finite else None)
    return result


def combine_mean_and_std_traces(
    mean_traces: Sequence[Sequence[float | None]],
    std_traces: Sequence[Sequence[float | None]],
) -> tuple[list[float | None], list[float | None]]:
    """Combine within-session SD and between-session mean variation equally by session."""
    if len(mean_traces) != len(std_traces):
        raise ValueError("Mean and standard-deviation trace counts do not match.")
    if not mean_traces:
        return [], []
    width = len(mean_traces[0])
    if any(len(trace) != width for trace in (*mean_traces, *std_traces)):
        raise ValueError("All traces must have the same length.")

    combined_means = []
    combined_stds = []
    for means, stds in zip(
        zip(*mean_traces, strict=True),
        zip(*std_traces, strict=True),
        strict=True,
    ):
        pairs = [
            (float(mean), float(std))
            for mean, std in zip(means, stds, strict=True)
            if mean is not None
            and std is not None
            and math.isfinite(mean)
            and math.isfinite(std)
        ]
        if not pairs:
            combined_means.append(None)
            combined_stds.append(None)
            continue
        combined_mean = sum(mean for mean, _ in pairs) / len(pairs)
        combined_variance = sum(
            std * std + (mean - combined_mean) ** 2
            for mean, std in pairs
        ) / len(pairs)
        combined_means.append(combined_mean)
        combined_stds.append(math.sqrt(combined_variance))
    return combined_means, combined_stds


def subtract_traces(
    minuend: Sequence[float | None],
    subtrahend: Sequence[float | None],
) -> list[float | None]:
    if len(minuend) != len(subtrahend):
        raise ValueError("Trace lengths do not match.")
    return [
        None
        if left is None or right is None
        else float(left) - float(right)
        for left, right in zip(minuend, subtrahend, strict=True)
    ]
