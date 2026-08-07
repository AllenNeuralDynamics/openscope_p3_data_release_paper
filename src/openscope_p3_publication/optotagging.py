"""Optotagging analysis for the public OpenScope P3 Neuropixels NWBs."""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


DANDISET_ID = "001637"
DANDISET_VERSION = "draft"
DEFAULT_SESSION_PATH = (
    "sub-834687/"
    "sub-834687_ses-ecephys-834687-2026-03-18-15-50-10_ecephys.nwb"
)
DEFAULT_OUTPUT_DIR = Path.home() / "Data" / "openscope_p3_data_release_paper"
PSTH_WINDOW = (-0.5, 1.2)
PSTH_BIN_SECONDS = 0.001
PRE_WINDOW_GAP_SECONDS = 0.001
HEATMAP_CACHE_VERSION = "pulse-rate-v3"
ATLAS_DISPLAY_BINS = 256
ATLAS_ZSCORE_LIMIT = 8.0
ATLAS_QUANTIZATION_SCALE = 127 / ATLAS_ZSCORE_LIMIT
ATLAS_NAN_SENTINEL = -128
ALLEN_MAJOR_DIVISIONS = (
    "Isocortex",
    "OLF",
    "HPF",
    "CTXsp",
    "STR",
    "PAL",
    "TH",
    "HY",
    "MB",
    "P",
    "MY",
    "CB",
)


@dataclass(frozen=True)
class ConditionConfig:
    """Analysis parameters for one optotagging stimulus."""

    table_name: str
    pulse_frequency_hz: float
    pulse_width_seconds: float
    count_window_seconds: float
    post_delay_seconds: float


CONDITIONS = (
    ConditionConfig(
        table_name="raised_cosine_presentations",
        pulse_frequency_hz=1.0,
        pulse_width_seconds=1.0,
        count_window_seconds=0.5,
        post_delay_seconds=0.25,
    ),
    ConditionConfig(
        table_name="5 hz pulse train_presentations",
        pulse_frequency_hz=5.0,
        pulse_width_seconds=0.010,
        count_window_seconds=0.010,
        post_delay_seconds=0.002,
    ),
    ConditionConfig(
        table_name="40 hz pulse train_presentations",
        pulse_frequency_hz=40.0,
        pulse_width_seconds=0.006,
        # Preserve the reference notebook's 10 ms response window even though
        # heatmap ordering uses only the exact 6 ms laser pulse.
        count_window_seconds=0.010,
        post_delay_seconds=0.002,
    ),
)
CONDITION_NAMES = tuple(condition.table_name for condition in CONDITIONS)
METRIC_NAMES = ("pre_mean", "post_mean", "modulation_index", "p_value")
CONDITION_DISPLAY_NAMES = {
    "raised_cosine_presentations": "Raised cosine",
    "5 hz pulse train_presentations": "5 Hz pulse train",
    "40 hz pulse train_presentations": "40 Hz pulse train",
}


class SessionSkipped(RuntimeError):
    """Raised when a session cannot support the requested optotagging analysis."""


@dataclass
class SessionAnalysis:
    """Per-unit statistics and PSTHs for one NWB session."""

    session_id: str
    asset_id: str
    asset_path: str
    metrics: pd.DataFrame
    psths: dict[str, np.ndarray]
    pulse_firing_rates: dict[str, np.ndarray]
    time_seconds: np.ndarray
    trial_counts: dict[str, int]
    pulse_counts: dict[str, int]
    unit_count: int
    major_parent_acronyms: np.ndarray | None = None


def decode_text(value: Any) -> str:
    """Decode scalar NWB text values consistently."""

    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def discover_session_assets(
    dandiset_id: str = DANDISET_ID,
    version: str = DANDISET_VERSION,
) -> list[dict[str, Any]]:
    """Return deterministic metadata for session-level NWB assets."""

    from dandi.dandiapi import DandiAPIClient

    records = []
    with DandiAPIClient() as client:
        dandiset = client.get_dandiset(dandiset_id, version_id=version)
        for asset in dandiset.get_assets():
            if not asset.path.endswith(".nwb") or "probe" in asset.path.lower():
                continue
            digest = asset.get_raw_metadata().get("digest", {})
            records.append(
                {
                    "asset_id": str(asset.identifier),
                    "asset_path": asset.path,
                    "content_url": asset.get_content_url(
                        follow_redirects=1,
                        strip_query=True,
                    ),
                    "modified": (
                        asset.modified.isoformat()
                        if getattr(asset, "modified", None) is not None
                        else None
                    ),
                    "size": getattr(asset, "size", None),
                    "digest": {
                        key: digest[key]
                        for key in sorted(digest)
                        if key in {"dandi:dandi-etag", "dandi:sha2-256"}
                    },
                }
            )
    return sorted(records, key=lambda record: record["asset_path"])


def validate_nwb(nwb: Mapping[str, Any]) -> None:
    """Validate the NWB groups and columns required by the analysis."""

    if "intervals" not in nwb:
        raise SessionSkipped("missing intervals group")
    missing_conditions = [
        name for name in CONDITION_NAMES if name not in nwb["intervals"]
    ]
    if missing_conditions:
        raise SessionSkipped(
            "missing optotagging tables: " + ", ".join(missing_conditions)
        )
    if "units" not in nwb:
        raise SessionSkipped("missing units table")
    required_unit_columns = {
        "decoder_label",
        "id",
        "spike_times",
        "spike_times_index",
    }
    missing_unit_columns = sorted(required_unit_columns - set(nwb["units"]))
    if missing_unit_columns:
        raise SessionSkipped(
            "missing unit columns: " + ", ".join(missing_unit_columns)
        )


def expand_pulse_times(
    start_times: np.ndarray,
    durations: np.ndarray,
    frequency_hz: float,
) -> np.ndarray:
    """Expand presentation starts into pulse starts at a fixed frequency."""

    pulse_times = []
    for start_time, duration in zip(start_times, durations, strict=True):
        pulse_count = max(1, int(np.floor(float(duration) * frequency_hz + 1e-9)))
        pulse_offsets = np.arange(pulse_count, dtype=float) / frequency_hz
        pulse_times.append(float(start_time) + pulse_offsets)
    if not pulse_times:
        return np.array([], dtype=float)
    return np.concatenate(pulse_times)


def count_spikes_in_windows(
    spike_times: np.ndarray,
    starts: np.ndarray,
    ends: np.ndarray,
) -> np.ndarray:
    """Count sorted spike times in half-open time windows."""

    left = np.searchsorted(spike_times, starts, side="left")
    right = np.searchsorted(spike_times, ends, side="left")
    return right - left


def compute_psth(
    spike_times: np.ndarray,
    event_times: np.ndarray,
    *,
    window: tuple[float, float] = PSTH_WINDOW,
    bin_seconds: float = PSTH_BIN_SECONDS,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute an event-averaged firing-rate PSTH for one unit."""

    edges = np.arange(window[0], window[1] + bin_seconds / 2, bin_seconds)
    counts = np.zeros(len(edges) - 1, dtype=float)
    relative_spike_chunks = []
    for event_time in event_times:
        start = np.searchsorted(spike_times, event_time + window[0], side="left")
        stop = np.searchsorted(spike_times, event_time + window[1], side="left")
        relative_spike_chunks.append(spike_times[start:stop] - event_time)
    if relative_spike_chunks:
        relative_spikes = np.concatenate(relative_spike_chunks)
        bin_indices = np.floor(
            (relative_spikes - window[0]) / bin_seconds + 1e-9
        ).astype(int)
        valid_indices = bin_indices[
            (bin_indices >= 0) & (bin_indices < len(counts))
        ]
        counts = np.bincount(valid_indices, minlength=len(counts)).astype(float)
    if len(event_times):
        counts /= len(event_times) * bin_seconds
    centers = edges[:-1] + bin_seconds / 2
    return centers, counts


def compute_response_metrics(
    spike_times: np.ndarray,
    event_times: np.ndarray,
    condition: ConditionConfig,
    *,
    compute_p_value: bool = True,
) -> dict[str, float]:
    """Compute the reference notebook's paired pre/post response metrics."""

    window = condition.count_window_seconds
    pre_ends = event_times - PRE_WINDOW_GAP_SECONDS
    pre_starts = pre_ends - window
    post_starts = event_times + condition.post_delay_seconds
    post_ends = post_starts + window

    pre_rates = count_spikes_in_windows(spike_times, pre_starts, pre_ends) / window
    post_rates = count_spikes_in_windows(spike_times, post_starts, post_ends) / window
    denominator = post_rates + pre_rates
    modulation = np.divide(
        post_rates - pre_rates,
        denominator,
        out=np.full_like(post_rates, np.nan, dtype=float),
        where=denominator != 0,
    )

    if not compute_p_value or not len(event_times):
        p_value = np.nan
    else:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            result = wilcoxon(
                pre_rates,
                post_rates,
                zero_method="zsplit",
                correction=False,
            )
        p_value = float(result.pvalue)

    return {
        "pre_mean": float(np.mean(pre_rates)) if len(pre_rates) else np.nan,
        "post_mean": float(np.mean(post_rates)) if len(post_rates) else np.nan,
        "modulation_index": (
            float(np.nanmean(modulation))
            if np.any(np.isfinite(modulation))
            else np.nan
        ),
        "p_value": p_value,
    }


def baseline_zscore(
    psths: np.ndarray,
    time_seconds: np.ndarray,
) -> np.ndarray:
    """Z-score each unit against its pre-stimulus PSTH bins."""

    baseline = psths[:, time_seconds < 0]
    baseline_mean = np.mean(baseline, axis=1, keepdims=True)
    baseline_std = np.std(baseline, axis=1, keepdims=True)
    return np.divide(
        psths - baseline_mean,
        baseline_std,
        out=np.full_like(psths, np.nan, dtype=float),
        where=baseline_std != 0,
    )


def order_heatmap_rows(
    response_scores: np.ndarray,
) -> np.ndarray:
    """Order units from unscored/weakest to strongest response."""

    scores = np.nan_to_num(
        np.asarray(response_scores, dtype=float),
        nan=-np.inf,
    )
    return np.argsort(scores, kind="stable")


def mean_firing_rate_during_pulses(
    spike_times: np.ndarray,
    pulse_times: np.ndarray,
    pulse_width_seconds: float,
) -> float:
    """Average firing rate inside the exact duration of every laser pulse."""

    if not len(pulse_times):
        return np.nan
    pulse_counts = count_spikes_in_windows(
        spike_times,
        pulse_times,
        pulse_times + pulse_width_seconds,
    )
    return float(np.mean(pulse_counts / pulse_width_seconds))


def heatmap_response_scores(
    analysis: SessionAnalysis,
    condition: ConditionConfig,
) -> tuple[np.ndarray, str]:
    """Return the validated condition-specific score used to order heatmap rows."""

    pulse_width_ms = condition.pulse_width_seconds * 1_000
    return (
        analysis.pulse_firing_rates[condition.table_name],
        f"mean firing during {pulse_width_ms:g} ms pulses",
    )


def strongest_first_indices(response_scores: np.ndarray) -> np.ndarray:
    """Return a stable strongest-first order with unscored units last."""

    scores = np.asarray(response_scores, dtype=float)
    sortable = np.where(np.isfinite(scores), -scores, np.inf)
    return np.argsort(sortable, kind="stable")


def allen_major_parent_acronyms(
    acronyms: Iterable[str],
    *,
    brain_regions: Any | None = None,
) -> np.ndarray:
    """Map Allen structure acronyms to canonical major divisions via iblatlas."""

    if brain_regions is None:
        from iblatlas.regions import BrainRegions

        brain_regions = BrainRegions()
    major_divisions = set(ALLEN_MAJOR_DIVISIONS)
    parents = []
    for acronym in acronyms:
        ids = np.atleast_1d(brain_regions.acronym2id(str(acronym)))
        if not len(ids) or int(ids[0]) == 0:
            parents.append("Other")
            continue
        ancestors = brain_regions.ancestors(int(ids[0])).acronym
        parent = next(
            (candidate for candidate in reversed(ancestors) if candidate in major_divisions),
            "Other",
        )
        parents.append(parent)
    return np.asarray(parents, dtype=str)


def downsample_zscored_psths(
    psths: np.ndarray,
    time_seconds: np.ndarray,
    *,
    display_bins: int = ATLAS_DISPLAY_BINS,
) -> tuple[np.ndarray, np.ndarray]:
    """Baseline-zscore then deterministically average contiguous display bins."""

    zscored = baseline_zscore(np.asarray(psths, dtype=float), time_seconds)
    bin_count = min(display_bins, zscored.shape[1])
    edges = np.linspace(0, zscored.shape[1], bin_count + 1, dtype=int)
    downsampled = np.empty((zscored.shape[0], bin_count), dtype=float)
    display_times = np.empty(bin_count, dtype=float)
    for index, (start, stop) in enumerate(zip(edges[:-1], edges[1:], strict=True)):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            downsampled[:, index] = np.nanmean(zscored[:, start:stop], axis=1)
        display_times[index] = float(np.mean(time_seconds[start:stop]))
    return display_times, downsampled


def quantize_zscores(values: np.ndarray) -> np.ndarray:
    """Quantize the documented display range exactly, reserving an NaN sentinel."""

    values = np.asarray(values, dtype=float)
    clipped = np.clip(values, -ATLAS_ZSCORE_LIMIT, ATLAS_ZSCORE_LIMIT)
    finite_values = np.where(np.isfinite(clipped), clipped, 0)
    quantized = np.rint(finite_values * ATLAS_QUANTIZATION_SCALE).astype(np.int8)
    quantized[~np.isfinite(values)] = ATLAS_NAN_SENTINEL
    return quantized


def encode_numeric_atlas_png(condition_values: list[np.ndarray]) -> bytes:
    """Pack signed 8-bit scalar matrices into a lossless grayscale PNG."""

    from PIL import Image

    stacked = np.concatenate(condition_values, axis=0).astype(np.int8, copy=False)
    pixels = stacked.view(np.uint8)
    output = io.BytesIO()
    Image.fromarray(pixels, mode="L").save(
        output,
        format="PNG",
        optimize=True,
        compress_level=9,
    )
    return output.getvalue()


def build_session_numeric_atlas(analysis: SessionAnalysis) -> tuple[dict[str, Any], bytes]:
    """Build compact atlas metadata and numeric PNG in original unit order."""

    if analysis.major_parent_acronyms is None:
        raise ValueError("Session analysis does not contain Allen parent areas.")
    parent_areas = sorted(set(analysis.major_parent_acronyms))
    parent_lookup = {area: index for index, area in enumerate(parent_areas)}
    parent_codes = [parent_lookup[area] for area in analysis.major_parent_acronyms]
    quantized_conditions = []
    orders = {}
    display_times = None
    for condition in CONDITIONS:
        display_times, downsampled = downsample_zscored_psths(
            analysis.psths[condition.table_name],
            analysis.time_seconds,
        )
        quantized_conditions.append(quantize_zscores(downsampled))
        scores, _ = heatmap_response_scores(analysis, condition)
        orders[condition.table_name] = strongest_first_indices(scores).tolist()
    assert display_times is not None
    metadata = {
        "version": 2,
        "unit_count": analysis.unit_count,
        "time_bin_count": len(display_times),
        "time_seconds": [float(display_times[0]), float(display_times[-1])],
        "parent_areas": parent_areas,
        "parent_codes": parent_codes,
        "strongest_first_unit_indices": orders,
        "condition_row_offsets": {
            condition.table_name: index * analysis.unit_count
            for index, condition in enumerate(CONDITIONS)
        },
        "quantization": {
            "dtype": "int8",
            "scale": ATLAS_QUANTIZATION_SCALE,
            "range": [-ATLAS_ZSCORE_LIMIT, ATLAS_ZSCORE_LIMIT],
            "nan_sentinel": ATLAS_NAN_SENTINEL,
            "png_channels": "single-channel uint8 viewed as signed int8",
        },
    }
    return metadata, encode_numeric_atlas_png(quantized_conditions)


def _read_condition_events(
    nwb: Mapping[str, Any],
    condition: ConditionConfig,
) -> tuple[np.ndarray, np.ndarray]:
    table = nwb["intervals"][condition.table_name]
    start_times = np.asarray(table["start_time"], dtype=float)
    durations = np.asarray(table["duration"][:], dtype=float)
    pulse_times = expand_pulse_times(
        start_times,
        durations,
        condition.pulse_frequency_hz,
    )
    return start_times, pulse_times


def _unit_anatomy_acronyms(nwb: Mapping[str, Any]) -> np.ndarray:
    """Resolve each unit's extremum contact to its electrode-table location."""

    units = nwb["units"]
    unit_count = len(units["id"])
    no_anatomy = np.full(unit_count, "Other", dtype=object)
    try:
        electrodes = nwb["general/extracellular_ephys/electrodes"]
    except (KeyError, TypeError):
        return no_anatomy
    if "location" not in electrodes or "extremum_channel_index" not in units:
        return no_anatomy

    locations = np.asarray(
        [decode_text(value) for value in electrodes["location"][:]],
        dtype=object,
    )
    extrema = np.asarray(units["extremum_channel_index"], dtype=np.int64)
    resolved = no_anatomy.copy()
    if "electrodes" in units and "electrodes_index" in units:
        references = np.asarray(units["electrodes"], dtype=np.int64)
        ends = np.asarray(units["electrodes_index"], dtype=np.int64)
        starts = np.concatenate(([0], ends[:-1]))
        for unit_index, (start, end, extremum) in enumerate(
            zip(starts, ends, extrema, strict=True)
        ):
            unit_electrodes = references[start:end]
            if 0 <= extremum < len(unit_electrodes):
                electrode_index = int(unit_electrodes[extremum])
                if 0 <= electrode_index < len(locations):
                    resolved[unit_index] = locations[electrode_index]
        return resolved

    if "device_name" not in units or "group_name" not in electrodes:
        return resolved
    devices = np.asarray(
        [decode_text(value) for value in units["device_name"][:]],
        dtype=object,
    )
    groups = np.asarray(
        [decode_text(value) for value in electrodes["group_name"][:]],
        dtype=object,
    )
    rows_by_probe = {
        probe: np.flatnonzero(groups == probe) for probe in np.unique(devices)
    }
    for unit_index, (device, extremum) in enumerate(
        zip(devices, extrema, strict=True)
    ):
        probe_rows = rows_by_probe.get(device, np.array([], dtype=np.int64))
        if 0 <= extremum < len(probe_rows):
            resolved[unit_index] = locations[probe_rows[extremum]]
    return resolved


def _selected_units(
    nwb: Mapping[str, Any],
) -> list[tuple[int, str, int, int, str]]:
    units = nwb["units"]
    labels = [decode_text(value) for value in units["decoder_label"][:]]
    unit_ids = np.asarray(units["id"])
    if "unit_name" in units:
        unit_names = [decode_text(value) for value in units["unit_name"][:]]
    else:
        unit_names = [str(value) for value in unit_ids]
    spike_ends = np.asarray(units["spike_times_index"], dtype=np.int64)
    spike_starts = np.concatenate(([0], spike_ends[:-1]))
    anatomy_acronyms = _unit_anatomy_acronyms(nwb)
    major_parents = np.full(len(anatomy_acronyms), "Other", dtype=object)
    has_anatomy = anatomy_acronyms != "Other"
    if np.any(has_anatomy):
        major_parents[has_anatomy] = allen_major_parent_acronyms(
            anatomy_acronyms[has_anatomy]
        )
    return [
        (
            index,
            unit_names[index],
            int(spike_starts[index]),
            int(spike_ends[index]),
            major_parents[index],
        )
        for index, label in enumerate(labels)
        if label != "noise"
    ]


def analyze_nwb(
    nwb: Mapping[str, Any],
    *,
    asset_id: str,
    asset_path: str,
    max_units: int | None = None,
    compute_p_values: bool = True,
) -> SessionAnalysis:
    """Analyze one open NWB file and return metrics plus plotting data."""

    validate_nwb(nwb)
    session_id = decode_text(nwb["general/session_id"][()])
    condition_events = {
        condition.table_name: _read_condition_events(nwb, condition)
        for condition in CONDITIONS
    }
    selected_units = _selected_units(nwb)
    if max_units is not None:
        selected_units = selected_units[:max_units]
    if not selected_units:
        raise SessionSkipped("no non-noise units")

    metric_rows = []
    psth_rows = {name: [] for name in CONDITION_NAMES}
    pulse_rate_rows = {name: [] for name in CONDITION_NAMES}
    time_seconds = None
    spike_times_all_units = np.asarray(nwb["units"]["spike_times"], dtype=float)

    for _, unit_id, spike_start, spike_end, _ in selected_units:
        spike_times = spike_times_all_units[spike_start:spike_end]
        metric_row: dict[str, Any] = {
            "asset_id": asset_id,
            "asset_path": asset_path,
            "session_id": session_id,
            "unit_id": unit_id,
        }
        for condition in CONDITIONS:
            trial_starts, pulse_times = condition_events[condition.table_name]
            time_seconds, psth = compute_psth(spike_times, trial_starts)
            psth_rows[condition.table_name].append(psth)
            pulse_rate_rows[condition.table_name].append(
                mean_firing_rate_during_pulses(
                    spike_times,
                    pulse_times,
                    condition.pulse_width_seconds,
                )
            )
            metrics = compute_response_metrics(
                spike_times,
                pulse_times,
                condition,
                compute_p_value=compute_p_values,
            )
            for metric_name, value in metrics.items():
                metric_row[f"{condition.table_name}__{metric_name}"] = value
        metric_rows.append(metric_row)

    assert time_seconds is not None
    return SessionAnalysis(
        session_id=session_id,
        asset_id=asset_id,
        asset_path=asset_path,
        metrics=pd.DataFrame(metric_rows),
        psths={
            name: np.asarray(rows, dtype=float)
            for name, rows in psth_rows.items()
        },
        pulse_firing_rates={
            name: np.asarray(rows, dtype=float)
            for name, rows in pulse_rate_rows.items()
        },
        time_seconds=time_seconds,
        trial_counts={
            name: len(events[0]) for name, events in condition_events.items()
        },
        pulse_counts={
            name: len(events[1]) for name, events in condition_events.items()
        },
        unit_count=len(selected_units),
        major_parent_acronyms=np.asarray(
            [major_parent for *_, major_parent in selected_units],
            dtype=str,
        ),
    )


def analyze_asset(
    asset: Mapping[str, Any],
    *,
    max_units: int | None = None,
    compute_p_values: bool = True,
) -> SessionAnalysis:
    """Stream and analyze one DANDI NWB asset."""

    import h5py
    import remfile

    remote_file = remfile.File(asset["content_url"])
    try:
        with h5py.File(remote_file, mode="r") as nwb:
            return analyze_nwb(
                nwb,
                asset_id=str(asset["asset_id"]),
                asset_path=str(asset["asset_path"]),
                max_units=max_units,
                compute_p_values=compute_p_values,
            )
    finally:
        remote_file.close()


def render_session_heatmaps(
    analysis: SessionAnalysis,
    *,
    dpi: int = 100,
) -> bytes:
    """Render all condition PSTH heatmaps for one session as PNG bytes."""

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(
        1,
        len(CONDITIONS),
        figsize=(15, 5),
        sharex=True,
        sharey=True,
        constrained_layout=True,
    )
    image = None
    for axis, condition in zip(axes, CONDITIONS, strict=True):
        condition_psths = analysis.psths[condition.table_name]
        zscored = baseline_zscore(
            condition_psths,
            analysis.time_seconds,
        )
        response_scores, ordering_label = heatmap_response_scores(analysis, condition)
        order = order_heatmap_rows(response_scores)
        image = axis.imshow(
            zscored[order],
            aspect="auto",
            interpolation="nearest",
            cmap="coolwarm",
            vmin=-3,
            vmax=3,
            extent=(
                analysis.time_seconds[0],
                analysis.time_seconds[-1],
                0,
                analysis.unit_count,
            ),
            origin="lower",
            rasterized=True,
        )
        axis.axvline(0, color="black", linewidth=0.8, linestyle="--")
        condition_label = CONDITION_DISPLAY_NAMES[condition.table_name]
        axis.set_title(f"{condition_label}\nordered by {ordering_label}")
        axis.set_xlabel("Time from laser onset (s)")
    axes[0].set_ylabel(
        "Units ordered by condition-specific laser response\n(strongest at top)"
    )
    figure.suptitle(
        f"{analysis.session_id}: laser-aligned PSTHs "
        f"({analysis.unit_count:,} non-noise units)"
    )
    if image is not None:
        figure.colorbar(image, ax=axes, label="Baseline z-scored firing rate")

    output = io.BytesIO()
    figure.savefig(
        output,
        format="png",
        dpi=dpi,
        metadata={
            "Software": "openscope-p3-publication",
            "Title": f"{analysis.session_id} optotagging heatmaps",
        },
    )
    plt.close(figure)
    return output.getvalue()


def render_session_summary(analysis: SessionAnalysis) -> bytes:
    """Render mean PSTHs and pre/post firing-rate comparisons."""

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(
        2,
        len(CONDITIONS),
        figsize=(15, 8),
        constrained_layout=True,
    )
    for column, condition in enumerate(CONDITIONS):
        condition_name = condition.table_name
        mean_psth = np.nanmean(analysis.psths[condition_name], axis=0)
        trace_axis = axes[0, column]
        trace_axis.plot(analysis.time_seconds, mean_psth, color="#245f73")
        trace_axis.axvline(0, color="black", linewidth=0.8, linestyle="--")
        trace_axis.set_title(CONDITION_DISPLAY_NAMES[condition_name])
        trace_axis.set_xlabel("Time from laser onset (s)")
        if column == 0:
            trace_axis.set_ylabel("Mean firing rate (spikes/s)")

        pre_column = f"{condition_name}__pre_mean"
        post_column = f"{condition_name}__post_mean"
        pre_rates = analysis.metrics[pre_column]
        post_rates = analysis.metrics[post_column]
        scatter_axis = axes[1, column]
        scatter_axis.scatter(
            pre_rates,
            post_rates,
            s=7,
            alpha=0.35,
            color="#245f73",
            edgecolors="none",
        )
        finite_values = np.concatenate(
            [
                pre_rates[np.isfinite(pre_rates)].to_numpy(),
                post_rates[np.isfinite(post_rates)].to_numpy(),
            ]
        )
        maximum = float(np.max(finite_values)) if len(finite_values) else 1.0
        scatter_axis.plot([0, maximum], [0, maximum], color="black", linestyle="--")
        scatter_axis.set_xlabel("Pre-stimulus firing rate (spikes/s)")
        if column == 0:
            scatter_axis.set_ylabel("Post-stimulus firing rate (spikes/s)")
    figure.suptitle(f"{analysis.session_id}: optotagging response summaries")

    output = io.BytesIO()
    figure.savefig(output, format="png", dpi=120)
    plt.close(figure)
    return output.getvalue()


def write_results(
    metrics: pd.DataFrame,
    *,
    assets: Iterable[Mapping[str, Any]],
    skipped: list[dict[str, str]],
    failed: list[dict[str, str]],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> tuple[Path, Path]:
    """Write deterministic Parquet results and adjacent provenance."""

    output_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = output_dir / "optotagging-results.parquet"
    provenance_path = output_dir / "optotagging-results.provenance.json"

    ordered_metrics = metrics.sort_values(
        ["session_id", "unit_id"],
        kind="stable",
    ).reset_index(drop=True)
    ordered_metrics.to_parquet(parquet_path, index=False)
    asset_manifest = [
        {
            key: asset.get(key)
            for key in ("asset_id", "asset_path", "modified", "size", "digest")
        }
        for asset in assets
    ]
    provenance = {
        "version": 1,
        "dandiset_id": DANDISET_ID,
        "dandiset_version": DANDISET_VERSION,
        "source_url": (
            f"https://dandiarchive.org/dandiset/{DANDISET_ID}/"
            f"{DANDISET_VERSION}/files"
        ),
        "retrieved_date": dt.date.today().isoformat(),
        "output_path": str(parquet_path),
        "output_sha256": hashlib.sha256(parquet_path.read_bytes()).hexdigest(),
        "rows": len(ordered_metrics),
        "sessions": int(ordered_metrics["session_id"].nunique()),
        "conditions": [
            {
                "table_name": condition.table_name,
                "pulse_frequency_hz": condition.pulse_frequency_hz,
                "count_window_seconds": condition.count_window_seconds,
                "post_delay_seconds": condition.post_delay_seconds,
            }
            for condition in CONDITIONS
        ],
        "psth": {
            "window_seconds": list(PSTH_WINDOW),
            "bin_seconds": PSTH_BIN_SECONDS,
            "alignment": "interval start_time (laser onset)",
            "stored_in_parquet": False,
        },
        "unit_filter": "decoder_label != 'noise'",
        "asset_manifest": asset_manifest,
        "skipped_sessions": skipped,
        "failed_sessions": failed,
    }
    provenance_path.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return parquet_path, provenance_path
