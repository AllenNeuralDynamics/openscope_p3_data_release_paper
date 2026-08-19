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
import shutil
import urllib.request
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
except ImportError as exc:  # pragma: no cover - optional extraction environment
    raise SystemExit(
        "Run with: uv run --with h5py --with iblatlas --with numpy "
        "--with rastermap==1.0 --with remfile "
        "python scripts/extract_neuropixels_event_responses.py"
    ) from exc

from openscope_p3_publication.neural_responses import (
    BIN_SECONDS,
    NEURAL_SESSIONS,
    QC_THRESHOLDS,
    RASTERMAP_PARAMETERS,
    RASTERMAP_VERSION,
    SMOOTHING_SIGMA_SECONDS,
    WINDOW_END_SECONDS,
    WINDOW_START_SECONDS,
    context_event_definitions,
    event_indices,
    gaussian_kernel,
    neural_baseline_windows,
    neural_response_windows,
    qc_passes,
    relative_bin_centers,
    relative_bin_edges,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "figure_sources" / "data"
DEFAULT_OUTPUT = DATA_DIR / "neuropixels-event-responses.json"
DEFAULT_PROVENANCE_OUTPUT = DEFAULT_OUTPUT.with_suffix(".provenance.json")
DEFAULT_MEDIA_DIR = REPO_ROOT / "figure_sources" / "media" / "neuropixels-event-responses"
MEDIA_ASSET_ROOT = "media/neuropixels-event-responses"
DANDI_API = "https://api.dandiarchive.org/api"
DANDISET_ID = "001637"
DANDI_VERSION = "draft"
VERSION = 3
CONDITION_ORDER = ("context", "control")
PROBE_ORDER = tuple(f"Probe{letter}" for letter in "ABCDEF")
FRONTAL_PREFIXES = ("ACA", "ILA", "PL", "ORB", "MOp", "MOs")
MOTOR_PREFIXES = ("MOp", "MOs")
VISUAL_THALAMUS_PREFIXES = ("LGd", "LGv", "LP")


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


def area_classification(acronyms: list[str]) -> dict[str, dict]:
    regions = BrainRegions()
    classifications = {}
    for acronym in sorted(set(acronyms)):
        ids = np.atleast_1d(regions.acronym2id(acronym))
        ancestors = (
            list(regions.ancestors(int(ids[0])).acronym)
            if len(ids) and int(ids[0]) != 0
            else []
        )
        major_parent = next(
            (
                parent
                for parent in reversed(ancestors)
                if parent in {"Isocortex", "TH", "HPF"}
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
        classifications[acronym] = {
            "groups": groups,
            "majorParent": major_parent,
        }
    return classifications


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
    context_arrays = table_arrays(nwb[f"intervals/{config.context_table}"])
    control_arrays = table_arrays(nwb[f"intervals/{config.control_table}"])
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
        for condition, arrays in (
            ("context", context_arrays),
            ("control", control_arrays),
        ):
            baseline_windows[condition] = [
                window
                for window in neural_baseline_windows(
                    arrays["start"],
                    arrays["stop"],
                    condition_indices[condition],
                    config.context,
                    arrays["block_number"],
                )
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
                "condition_onsets": condition_onsets,
                "response_windows": response_windows,
            }
        )
    return records, extraction


def histogram_trial_moments(
    spikes: np.ndarray,
    onsets: np.ndarray,
    relative_edges: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    counts = np.zeros(len(relative_edges) - 1, dtype=np.uint32)
    squared_counts = np.zeros(len(relative_edges) - 1, dtype=np.uint32)
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
        squared_counts += trial_counts * trial_counts
    maximum = np.iinfo(np.uint16).max
    if (
        np.max(counts, initial=0) > maximum
        or np.max(squared_counts, initial=0) > maximum
    ):
        raise RuntimeError("Aggregated PSTH moments exceed uint16 capacity.")
    return counts.astype(np.uint16), squared_counts.astype(np.uint16)


def baseline_rate_stats(
    spikes: np.ndarray,
    windows: list[tuple[float, float]],
) -> tuple[float, float]:
    count = 0
    total = 0.0
    total_squared = 0.0
    for start, stop in windows:
        bin_count = math.floor((stop - start) / BIN_SECONDS)
        if bin_count < 1:
            continue
        edges = start + np.arange(bin_count + 1, dtype=float) * BIN_SECONDS
        first = int(np.searchsorted(spikes, edges[0], side="left"))
        last = int(np.searchsorted(spikes, edges[-1], side="left"))
        rates = np.histogram(spikes[first:last], bins=edges)[0] / BIN_SECONDS
        count += len(rates)
        total += float(np.sum(rates))
        total_squared += float(np.sum(rates * rates))
    if count < 2:
        return math.nan, math.nan
    mean = total / count
    variance = max(0.0, (total_squared - total * total / count) / (count - 1))
    return mean, math.sqrt(variance)


def mean_rate_in_windows(
    spikes: np.ndarray,
    windows: list[tuple[float, float]],
) -> float:
    rates = []
    for start, stop in windows:
        first = int(np.searchsorted(spikes, start, side="left"))
        last = int(np.searchsorted(spikes, stop, side="right"))
        rates.append((last - first) / (stop - start))
    return float(np.mean(rates))


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
        "moduleSha256": file_sha256(
            REPO_ROOT / "src" / "openscope_p3_publication" / "neural_responses.py"
        ),
        "probes": selected_probes,
        "qcThresholds": QC_THRESHOLDS,
        "rastermapParameters": RASTERMAP_PARAMETERS,
        "rastermapVersion": RASTERMAP_VERSION,
        "scriptSha256": file_sha256(Path(__file__)),
        "smoothingSigmaSeconds": SMOOTHING_SIGMA_SECONDS,
        "window": [WINDOW_START_SECONDS, WINDOW_END_SECONDS],
    }
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def rastermap_ranks(
    counts: np.ndarray,
    baseline_mean: np.ndarray,
    baseline_std: np.ndarray,
    events: list[dict],
    decoder_labels: np.ndarray,
    unit_ids: np.ndarray,
    context: str,
) -> np.ndarray:
    bin_centers = np.asarray(relative_bin_centers(), dtype=float)
    display_start = -1.5 if context == "duration" else -1.0
    visible = bin_centers >= display_start
    kernel = np.asarray(gaussian_kernel(), dtype=float)
    edge_weights = np.convolve(np.ones(counts.shape[-1]), kernel, mode="same")
    ranks = np.empty((len(events), counts.shape[2]), dtype=np.uint16)
    label_eligible = np.isin(decoder_labels, ("mua", "sua"))

    for event_index, event in enumerate(events):
        rates = (
            counts[event_index, 0].astype(np.float32)
            / event["contextTrialCount"]
            / BIN_SECONDS
        )
        smoothed = np.vstack(
            [np.convolve(row, kernel, mode="same") / edge_weights for row in rates]
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
                f"{context} event {event['id']} has too few Rastermap-eligible units."
            )
        model = Rastermap(
            **RASTERMAP_PARAMETERS,
            keep_norm_X=False,
            verbose=False,
        ).fit(matrix[eligible_indices], compute_X_embedding=False)
        ordered = eligible_indices[np.asarray(model.isort, dtype=int)]
        if len(ordered) != len(eligible_indices) or len(np.unique(ordered)) != len(ordered):
            raise RuntimeError(f"{context} event {event['id']} Rastermap order is invalid.")
        remaining = np.setdiff1d(np.arange(counts.shape[2]), ordered, assume_unique=True)
        remaining = remaining[np.argsort(unit_ids[remaining], kind="stable")]
        full_order = np.concatenate((ordered, remaining))
        ranks[event_index, full_order] = np.arange(counts.shape[2], dtype=np.uint16)
    return ranks


def extract_session(config, media_dir: Path, selected_probes: tuple[str, ...]) -> dict:
    asset = source_asset(config)
    relative_edges = np.asarray(relative_bin_edges(), dtype=float)
    with closing(remfile.File(asset["downloadUrl"])) as remote, h5py.File(
        remote, "r"
    ) as nwb:
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
            "presence_ratio",
            "spike_times",
            "spike_times_index",
        }
        missing = sorted(required - set(units))
        if missing:
            raise RuntimeError(f"{config.session_id} unit columns missing: {missing}")
        events, extraction = event_records(nwb, config)
        device_names = np.asarray(units["device_name"][:]).astype("U")
        selected_rows = np.flatnonzero(np.isin(device_names, selected_probes))
        if not len(selected_rows):
            raise RuntimeError(f"{config.session_id} has no selected probes.")
        unit_count = len(selected_rows)
        bin_count = len(relative_edges) - 1
        event_count = len(events)
        counts = np.zeros(
            (event_count, len(CONDITION_ORDER), unit_count, bin_count),
            dtype=np.uint16,
        )
        squared_counts = np.zeros_like(counts)
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
        ids = np.asarray(units["id"][:], dtype=int)
        ks_ids = np.asarray(units["ks_unit_id"][:], dtype=int)
        decoder_labels = np.asarray(units["decoder_label"][:]).astype("U")
        depths = np.asarray(units["depth"][:], dtype=float)
        firing_rates = np.asarray(units["firing_rate"][:], dtype=float)
        isi = np.asarray(units["isi_violations_ratio"][:], dtype=float)
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

            for event_index, event_extract in enumerate(extraction):
                for condition_index, condition in enumerate(CONDITION_ORDER):
                    onsets = event_extract["condition_onsets"][condition]
                    count_sum, count_square_sum = histogram_trial_moments(
                        spikes,
                        onsets,
                        relative_edges,
                    )
                    counts[event_index, condition_index, output_row] = count_sum
                    squared_counts[
                        event_index,
                        condition_index,
                        output_row,
                    ] = count_square_sum
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
                    "spikeCount": spike_stop - spike_start,
                }
            )
            if (output_row + 1) % 250 == 0 or output_row + 1 == unit_count:
                print(
                    f"{config.context}: {output_row + 1}/{unit_count} units",
                    flush=True,
                )

        classifications = area_classification(
            [unit["location"] for unit in unit_records]
        )
        for unit in unit_records:
            classification = classifications[unit["location"]]
            unit["areaGroups"] = classification["groups"]
            unit["majorParent"] = classification["majorParent"]
        ranks = rastermap_ranks(
            counts,
            baseline_mean,
            baseline_std,
            events,
            decoder_labels[selected_rows],
            ids[selected_rows],
            config.context,
        )

    session_prefix = config.context.replace("sensorimotor", "motor")
    counts_path = media_dir / f"{session_prefix}-counts.u16.gz"
    squared_counts_path = media_dir / f"{session_prefix}-count-squares.u16.gz"
    count_asset = write_gzip(counts_path, counts.astype("<u2").tobytes())
    squared_count_asset = write_gzip(
        squared_counts_path,
        squared_counts.astype("<u2").tobytes(),
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
        "countAtlas": {
            **count_asset,
            "dtype": "uint16 little-endian",
            "shape": list(counts.shape),
        },
        "countSquareAtlas": {
            **squared_count_asset,
            "dtype": "uint16 little-endian",
            "shape": list(squared_counts.shape),
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
        "sessionId": config.session_id,
        "subject": "830846",
        "unitCount": unit_count,
        "units": unit_records,
    }


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
    metadata_path = session_cache / "session.json"
    if metadata_path.is_file():
        cached = json.loads(metadata_path.read_text(encoding="utf-8"))
        valid = True
        for key in ("countAtlas", "countSquareAtlas"):
            source = session_cache / Path(cached[key]["path"]).name
            valid &= source.is_file() and file_sha256(source) == cached[key]["sha256"]
        if valid:
            media_dir.mkdir(parents=True, exist_ok=True)
            for key in ("countAtlas", "countSquareAtlas"):
                source = session_cache / Path(cached[key]["path"]).name
                shutil.copy2(source, media_dir / source.name)
            return cached
    session_cache.mkdir(parents=True, exist_ok=True)
    cached_media = session_cache / "media"
    record = extract_session(config, cached_media, selected_probes)
    media_dir.mkdir(parents=True, exist_ok=True)
    for key in ("countAtlas", "countSquareAtlas"):
        source = cached_media / Path(record[key]["path"]).name
        target = session_cache / source.name
        shutil.copy2(source, target)
        shutil.copy2(source, media_dir / source.name)
    metadata_path.write_text(
        json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return record


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
                "sequence": "previous row start_time through event start_time",
                "standard": "previous row stop_time through event start_time",
            },
            "binSeconds": BIN_SECONDS,
            "heatmapModes": [
                "mismatch spikes/s",
                "control spikes/s",
                "mismatch-minus-control spikes/s",
                "mismatch baseline z score",
                "control baseline z score",
            ],
            "firingRateSource": "NWB Units firing_rate",
            "qcThresholds": QC_THRESHOLDS,
            "rastermap": {
                "input": (
                    "smoothed mismatch baseline z score over the displayed "
                    "peri-event window"
                ),
                "packageVersion": RASTERMAP_VERSION,
                "parameters": RASTERMAP_PARAMETERS,
            },
            "responseWindow": "selected row NWB start_time through stop_time",
            "smoothingSigmaSeconds": SMOOTHING_SIGMA_SECONDS,
            "timeBinCentersSeconds": relative_bin_centers(),
            "unitDefault": {
                "decoderLabels": ["mua", "sua"],
                "minimumFiringRateHz": 1.0,
                "numericalQc": "manuscript QC passing",
            },
            "windowSeconds": [WINDOW_START_SECONDS, WINDOW_END_SECONDS],
        },
        "sessionOrder": [record["context"] for record in records],
        "sessions": records,
        "subject": "830846",
        "version": VERSION,
    }
    write_json(args.output, payload)
    referenced_media = {
        Path(record[key]["path"]).name
        for record in records
        for key in ("countAtlas", "countSquareAtlas")
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
        "module": {
            "path": "src/openscope_p3_publication/neural_responses.py",
            "sha256": file_sha256(
                REPO_ROOT / "src" / "openscope_p3_publication" / "neural_responses.py"
            ),
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
