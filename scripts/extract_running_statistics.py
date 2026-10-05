#!/usr/bin/env python3
"""Extract comparable running summaries from public OpenScope sessions."""

from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import json
import math
import re
import tempfile
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

try:
    import h5py
    import harp
    import numpy as np
    import remfile
except ImportError as exc:  # pragma: no cover - optional extraction environment
    raise SystemExit(
        "Run with: uv run --with h5py --with harp-python --with numpy --with remfile "
        "python scripts/extract_running_statistics.py"
    ) from exc


REPO_ROOT = Path(__file__).resolve().parents[1]
SESSION_RECORDS_PATH = REPO_ROOT / "figure_sources" / "data" / "experimental-sessions.csv"
SESSION_PROVENANCE_PATH = SESSION_RECORDS_PATH.with_suffix(".provenance.json")
DEFAULT_OUTPUT = REPO_ROOT / "figure_sources" / "data" / "running-statistics.json"
DANDI_API = "https://api.dandiarchive.org/api"
S3_ROOT = "https://aind-open-data.s3.us-west-2.amazonaws.com"
SAMPLE_RATE_HZ = 20
PROFILE_BIN_SECONDS = 5
RUNNING_THRESHOLD_CM_S = 1.0
SLAP2_COUNTS_PER_REVOLUTION = 8192
SLAP2_WHEEL_RADIUS_CM = 8.255
SLAP2_SUBJECT_POSITION = 2 / 3
SLAP2_COUNTER_BITS = 16
SLAP2_CALIBRATION_URL = (
    "https://github.com/AllenNeuralDynamics/slap2_packaging_nwb/blob/"
    "37ce6471824c5f76b18820e429c7d8fd69352f0a/code/slap2_running_packaging.py"
)
CONTEXTS = (
    ("SENSORYMOTOR", "sensorimotor", "Sensorimotor"),
    ("STANDARD", "standard", "Standard"),
    ("SEQUENCE", "sequence", "Sequence"),
    ("DURATION", "duration", "Duration"),
)
DANDISETS = {
    "neuropixels": {"id": "001637", "session_prefix": "ecephys"},
    "mesoscope": {"id": "001768", "session_prefix": "multiplane-ophys"},
}
PROFILE_SESSION_IDS = {
    "neuropixels": "ecephys_820459_2025-11-10_15-07-13",
    "mesoscope": "multiplane-ophys_832700_2026-01-29_11-18-09",
    "slap2": "828408_2025-11-13_10-30-53",
}
SESSION_CACHE_VERSION = 2
BLOCK_DEFINITIONS = (
    ("standard", "Standard", "control"),
    ("context", "Context", "context"),
    ("standard_repeat", "Standard repeat", "control"),
    ("sequence", "Sequence", "control"),
    ("jitter", "Jitter", "control"),
    ("open_loop", "Open loop", "control"),
    ("movie", "Natural movie", "other"),
    ("rf", "RF mapping", "other"),
)
CONTEXT_TABLE_NAMES = {
    "sensorimotor": "Sensory-motor mismatch block_presentations",
    "standard": "Standard mismatch block_presentations",
    "sequence": "Sequence mismatch block_presentations",
    "duration": "Duration mismatch block_presentations",
}


class RunningDataUnavailableError(RuntimeError):
    """Raised when a matched public session has no processed running series."""


class ProtocolDataUnavailableError(RunningDataUnavailableError):
    """Raised when a public session lacks a complete protocol block table."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="Optional directory for verified SLAP2 downloads and session summaries.",
    )
    return parser.parse_args()


def context_record(stimulus: str) -> tuple[str, str] | None:
    upper = stimulus.upper()
    for token, context_id, label in CONTEXTS:
        if token in upper:
            return context_id, label
    return None


def load_session_records() -> list[dict[str, str]]:
    with SESSION_RECORDS_PATH.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=180) as response:
        return json.load(response)


def dandi_assets(dandiset_id: str) -> list[dict]:
    url = f"{DANDI_API}/dandisets/{dandiset_id}/versions/draft/assets/?page_size=100"
    assets = []
    while url:
        page = fetch_json(url)
        assets.extend(page["results"])
        url = page["next"]
    return assets


def source_session_id(path: str, prefix: str) -> str | None:
    match = re.search(
        rf"_ses-{re.escape(prefix)}-(\d+)-(\d{{4}}-\d{{2}}-\d{{2}})-"
        rf"(\d{{2}}-\d{{2}}-\d{{2}})(?:_|\.nwb)",
        path,
    )
    if not match:
        return None
    return f"{prefix}_{match.group(1)}_{match.group(2)}_{match.group(3)}"


def decode_attribute(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def binned_velocity_from_velocity(
    timestamps: np.ndarray, velocity: np.ndarray
) -> np.ndarray:
    _, binned_velocity = binned_running_from_velocity(timestamps, velocity)
    return binned_velocity


def increasing_samples(
    timestamps: np.ndarray, values: np.ndarray
) -> tuple[np.ndarray, np.ndarray, int]:
    timestamps = np.asarray(timestamps, dtype=float)
    values = np.asarray(values)
    finite = np.isfinite(timestamps)
    if np.issubdtype(values.dtype, np.floating):
        finite &= np.isfinite(values)
    timestamps = timestamps[finite]
    values = values[finite]
    if len(timestamps) < 2:
        raise RuntimeError("Running data has fewer than two finite timestamps.")
    keep = np.zeros(len(timestamps), dtype=bool)
    latest = -np.inf
    for index, timestamp in enumerate(timestamps):
        if timestamp > latest:
            keep[index] = True
            latest = timestamp
    discarded = int(np.count_nonzero(~keep))
    if discarded > max(3, round(len(timestamps) * 0.001)):
        raise RunningDataUnavailableError(
            f"discarding {discarded} non-increasing running timestamps would exceed 0.1%"
        )
    return timestamps[keep], values[keep], discarded


def regular_grid(timestamps: np.ndarray) -> np.ndarray:
    interval = 1 / SAMPLE_RATE_HZ
    grid_start = math.ceil(timestamps[0] * SAMPLE_RATE_HZ) / SAMPLE_RATE_HZ
    grid_stop = math.floor(timestamps[-1] * SAMPLE_RATE_HZ) / SAMPLE_RATE_HZ
    interval_count = round((grid_stop - grid_start) * SAMPLE_RATE_HZ)
    grid = grid_start + np.arange(interval_count + 1) * interval
    if len(grid) < 2:
        raise RuntimeError("Running data is shorter than one analysis bin.")
    return grid


def binned_running_from_velocity(
    timestamps: np.ndarray, velocity: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    timestamps, velocity, _ = increasing_samples(timestamps, velocity)
    grid = regular_grid(timestamps)
    increments = np.diff(timestamps) * (velocity[:-1] + velocity[1:]) / 2
    position = np.concatenate(([0.0], np.cumsum(increments)))
    binned_position = np.interp(grid, timestamps, position)
    return (grid[:-1] + grid[1:]) / 2, np.diff(binned_position) * SAMPLE_RATE_HZ


def unwrap_quadrature_counts(raw_counts: np.ndarray) -> np.ndarray:
    raw_counts = np.asarray(raw_counts, dtype=np.int64)
    if raw_counts.ndim != 1 or not len(raw_counts):
        raise RuntimeError("SLAP2 encoder counts must be a non-empty vector.")
    modulus = 1 << SLAP2_COUNTER_BITS
    half_modulus = modulus // 2
    deltas = np.diff(raw_counts)
    deltas = (deltas + half_modulus) % modulus - half_modulus
    return raw_counts[0] + np.concatenate(([0], np.cumsum(deltas, dtype=np.int64)))


def binned_velocity_from_counts(
    timestamps: np.ndarray, raw_counts: np.ndarray
) -> np.ndarray:
    _, binned_velocity = binned_running_from_counts(timestamps, raw_counts)
    return binned_velocity


def binned_running_from_counts(
    timestamps: np.ndarray, raw_counts: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    timestamps = np.asarray(timestamps, dtype=float)
    raw_counts = np.asarray(raw_counts)
    paired_length = min(len(timestamps), len(raw_counts))
    if abs(len(timestamps) - len(raw_counts)) > 3:
        raise RuntimeError("SLAP2 timestamps and encoder counts differ by more than 3.")
    timestamps = timestamps[:paired_length]
    unwrapped = unwrap_quadrature_counts(raw_counts[:paired_length])
    timestamps, unwrapped, _ = increasing_samples(timestamps, unwrapped)
    grid = regular_grid(timestamps)
    distance_per_count = (
        2
        * np.pi
        * SLAP2_WHEEL_RADIUS_CM
        * SLAP2_SUBJECT_POSITION
        / SLAP2_COUNTS_PER_REVOLUTION
    )
    position_cm = unwrapped * distance_per_count
    binned_position = np.interp(grid, timestamps, position_cm)
    return (grid[:-1] + grid[1:]) / 2, np.diff(binned_position) * SAMPLE_RATE_HZ


def interval_range(group) -> tuple[float, float]:
    starts = np.asarray(group["start_time"][:], dtype=float)
    stops = np.asarray(group["stop_time"][:], dtype=float)
    return float(np.nanmin(starts)), float(np.nanmax(stops))


def nwb_block_windows(nwb: h5py.File, context_id: str) -> list[dict]:
    intervals = nwb["intervals"]
    context_start, context_end = interval_range(intervals[CONTEXT_TABLE_NAMES[context_id]])
    control_one = intervals["Control block 1_presentations"]
    starts = np.asarray(control_one["start_time"][:], dtype=float)
    stops = np.asarray(control_one["stop_time"][:], dtype=float)
    first_mask = stops <= context_start
    repeat_mask = starts >= context_end
    if not np.any(first_mask) or not np.any(repeat_mask):
        raise RuntimeError("Control block 1 does not flank the context block.")
    movie_groups = [
        group
        for name, group in intervals.items()
        if name.endswith("_presentations")
        and (name.startswith("Zebra") or name.startswith("Trippy"))
    ]
    if not movie_groups:
        raise RuntimeError("NWB natural-movie interval table is unavailable.")
    movie_ranges = [interval_range(group) for group in movie_groups]
    ranges = {
        "standard": (float(np.min(starts[first_mask])), float(np.max(stops[first_mask]))),
        "context": (context_start, context_end),
        "standard_repeat": (
            float(np.min(starts[repeat_mask])),
            float(np.max(stops[repeat_mask])),
        ),
        "sequence": interval_range(intervals["Control block 2_presentations"]),
        "jitter": interval_range(intervals["Control block 3_presentations"]),
        "open_loop": interval_range(intervals["Control block 4_presentations"]),
        "movie": (
            min(start for start, _ in movie_ranges),
            max(stop for _, stop in movie_ranges),
        ),
        "rf": interval_range(intervals["RF mapping_presentations"]),
    }
    return block_records(ranges)


def block_records(ranges: dict[str, tuple[float, float]]) -> list[dict]:
    records = []
    for block_id, label, category in BLOCK_DEFINITIONS:
        start, end = ranges[block_id]
        if not math.isfinite(start) or not math.isfinite(end) or end <= start:
            raise RuntimeError(f"Invalid {block_id} block range: {start}, {end}")
        records.append(
            {
                "category": category,
                "end_time_seconds": round(end, 6),
                "id": block_id,
                "label": label,
                "start_time_seconds": round(start, 6),
            }
        )
    for previous, current in zip(records[:-1], records[1:], strict=True):
        overlap = previous["end_time_seconds"] - current["start_time_seconds"]
        if 0 < overlap <= 2:
            previous["end_time_seconds"] = current["start_time_seconds"]
        elif overlap > 2:
            raise RuntimeError(
                f"Protocol blocks {previous['id']} and {current['id']} overlap by "
                f"{overlap:.3f} seconds."
            )
    if any(
        current["start_time_seconds"] < previous["start_time_seconds"]
        for previous, current in zip(records[:-1], records[1:], strict=True)
    ):
        raise RuntimeError("Protocol blocks are not in acquisition order.")
    return records


def summarize_blocks(
    times: np.ndarray, velocity: np.ndarray, blocks: list[dict]
) -> dict[str, float | int]:
    forward = np.maximum(np.asarray(velocity, dtype=float), 0)
    block_values = {}
    for block in blocks:
        mask = (times >= block["start_time_seconds"]) & (
            times < block["end_time_seconds"]
        )
        if not np.any(mask):
            raise RuntimeError(f"Running data does not cover {block['id']} block.")
        block_values[block["id"]] = forward[mask]
    control = np.concatenate(
        [
            block_values[block_id]
            for block_id in (
                "standard",
                "standard_repeat",
                "sequence",
                "jitter",
                "open_loop",
            )
        ]
    )
    context = block_values["context"]
    return {
        "block_mean_forward_speed_cm_s": {
            block_id: round(float(np.mean(values)), 4)
            for block_id, values in block_values.items()
        },
        "context_analysis_bins": int(len(context)),
        "context_mean_forward_speed_cm_s": round(float(np.mean(context)), 4),
        "control_analysis_bins": int(len(control)),
        "control_mean_forward_speed_cm_s": round(float(np.mean(control)), 4),
    }


def running_profile(
    times: np.ndarray, velocity: np.ndarray, blocks: list[dict]
) -> dict:
    start = blocks[0]["start_time_seconds"]
    end = blocks[-1]["end_time_seconds"]
    edges = np.arange(start, end + PROFILE_BIN_SECONDS, PROFILE_BIN_SECONDS)
    forward = np.maximum(np.asarray(velocity, dtype=float), 0)
    points = []
    for left, right in zip(edges[:-1], edges[1:], strict=True):
        mask = (times >= left) & (times < min(right, end))
        if np.any(mask):
            points.append(
                [
                    round((left + min(right, end)) / 2 - start, 3),
                    round(float(np.mean(forward[mask])), 4),
                ]
            )
    relative_blocks = [
        {
            "category": block["category"],
            "end_seconds": round(block["end_time_seconds"] - start, 3),
            "id": block["id"],
            "label": block["label"],
            "start_seconds": round(block["start_time_seconds"] - start, 3),
        }
        for block in blocks
    ]
    return {
        "bin_seconds": PROFILE_BIN_SECONDS,
        "blocks": relative_blocks,
        "duration_seconds": round(end - start, 3),
        "points": points,
    }


def summarize_velocity(velocity: np.ndarray) -> dict[str, float | int]:
    velocity = np.asarray(velocity, dtype=float)
    finite = velocity[np.isfinite(velocity)]
    if not len(finite):
        raise RuntimeError("Running data has no finite analysis bins.")
    forward = np.maximum(finite, 0)
    return {
        "analysis_bins": int(len(forward)),
        "duration_seconds": round(len(forward) / SAMPLE_RATE_HZ, 3),
        "mean_forward_speed_cm_s": round(float(np.mean(forward)), 4),
        "running_fraction": round(
            float(np.mean(forward > RUNNING_THRESHOLD_CM_S)), 6
        ),
    }


def nwb_running_summary(
    asset: dict, context_id: str, include_profile: bool = False
) -> tuple[dict, dict]:
    asset_id = asset["asset_id"]
    download_url = f"{DANDI_API}/assets/{asset_id}/download/"
    remote = remfile.File(download_url)
    try:
        with h5py.File(remote, "r") as nwb:
            if "processing/running/running_speed" not in nwb:
                raise RunningDataUnavailableError(asset["path"])
            series = nwb["processing/running/running_speed"]
            data = series["data"]
            timestamps = np.asarray(series["timestamps"][:], dtype=float)
            velocity = np.asarray(data[:], dtype=float)
            unit = decode_attribute(data.attrs.get("unit", series.attrs.get("unit", "")))
            if unit.lower().replace(" ", "") not in {"cm/s", "cmps"}:
                raise RuntimeError(f"Unsupported NWB running unit {unit!r}: {asset['path']}")
            blocks = nwb_block_windows(nwb, context_id)
    finally:
        remote.close()
    binned_times, binned_velocity = binned_running_from_velocity(timestamps, velocity)
    summary = {
        **summarize_velocity(binned_velocity),
        **summarize_blocks(binned_times, binned_velocity, blocks),
        "blocks": blocks,
    }
    if include_profile:
        summary["profile"] = running_profile(binned_times, binned_velocity, blocks)
    source = {
        "asset_id": asset_id,
        "download_url": download_url,
        "modified": asset["modified"],
        "path": asset["path"],
        "size": asset["size"],
    }
    return summary, source


def remote_metadata(url: str) -> dict[str, str | int | None]:
    request = urllib.request.Request(url, method="HEAD")
    last_error = None
    for _ in range(5):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return {
                    "content_length": int(response.headers["Content-Length"]),
                    "etag": response.headers.get("ETag", "").strip('"'),
                    "last_modified": response.headers.get("Last-Modified"),
                    "url": url,
                }
        except urllib.error.HTTPError:
            raise
        except (ConnectionError, TimeoutError, urllib.error.URLError) as exc:
            last_error = exc
    raise RuntimeError(f"Metadata request failed after 5 attempts: {url}") from last_error


def download_with_sha256(url: str, output: Path) -> tuple[dict, str]:
    last_error = None
    for _ in range(5):
        digest = hashlib.sha256()
        try:
            with (
                urllib.request.urlopen(url, timeout=180) as response,
                output.open("wb") as stream,
            ):
                metadata = {
                    "content_length": int(response.headers["Content-Length"]),
                    "etag": response.headers.get("ETag", "").strip('"'),
                    "last_modified": response.headers.get("Last-Modified"),
                    "url": url,
                }
                while chunk := response.read(1024 * 1024):
                    digest.update(chunk)
                    stream.write(chunk)
            return metadata, digest.hexdigest()
        except urllib.error.HTTPError:
            raise
        except (ConnectionError, TimeoutError, urllib.error.URLError) as exc:
            last_error = exc
    output.unlink(missing_ok=True)
    raise RuntimeError(f"Download failed after 5 attempts: {url}") from last_error


def cached_download_with_sha256(url: str, output: Path) -> tuple[dict, str]:
    metadata = remote_metadata(url)
    if output.exists() and output.stat().st_size == metadata["content_length"]:
        return metadata, hashlib.sha256(output.read_bytes()).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    return download_with_sha256(url, output)


def align_slap2_stimulus(
    rows: list[dict[str, str]], trial_times: np.ndarray
) -> tuple[list[dict[str, str]], np.ndarray]:
    difference = len(rows) - len(trial_times)
    if abs(difference) > 3:
        raise RuntimeError("SLAP2 stimulus rows and Harp grating pulses differ by more than 3.")
    if difference > 0:
        rows = rows[difference:]
    elif difference < 0:
        trial_times = trial_times[-difference:]
    return rows, trial_times


def slap2_block_windows(
    rows: list[dict[str, str]], trial_times: np.ndarray, context_id: str
) -> list[dict]:
    expected_context_tokens = {
        "sensorimotor": "sensory-motor",
        "standard": "standard",
        "sequence": "sequence",
        "duration": "duration",
    }
    grouped = {}
    for block_number in range(1, 10):
        indices = np.asarray(
            [
                index
                for index, row in enumerate(rows)
                if int(row["BlockNumber"]) == block_number
            ],
            dtype=int,
        )
        if not len(indices):
            raise ProtocolDataUnavailableError(
                f"SLAP2 stimulus table lacks protocol block {block_number}"
            )
        last = rows[int(indices[-1])]
        grouped[block_number] = (
            float(trial_times[indices[0]]),
            float(trial_times[indices[-1]])
            + float(last["Duration"])
            + float(last["Delay"]),
        )
    context_label = rows[
        next(index for index, row in enumerate(rows) if int(row["BlockNumber"]) == 2)
    ]["BlockLabel"].lower()
    if expected_context_tokens[context_id] not in context_label:
        raise ProtocolDataUnavailableError(
            f"SLAP2 context block {context_label!r} does not match {context_id}."
        )
    ranges = {
        "standard": grouped[1],
        "context": grouped[2],
        "standard_repeat": grouped[3],
        "sequence": grouped[4],
        "jitter": grouped[5],
        "open_loop": grouped[6],
        "movie": (grouped[7][0], grouped[8][1]),
        "rf": grouped[9],
    }
    return block_records(ranges)


def slap2_running_summary(
    session_id: str,
    context_id: str,
    include_profile: bool = False,
    cache_dir: Path | None = None,
) -> tuple[dict, dict]:
    base = f"{S3_ROOT}/{session_id}/behavior/VCO1_Behavior.harp"
    stimulus_url = (
        f"{S3_ROOT}/{session_id}/behavior/stimuli/orientations_orientations0.csv"
    )
    temporary = (
        tempfile.TemporaryDirectory(prefix="openscope-running-")
        if cache_dir is None
        else contextlib.nullcontext(str(cache_dir / session_id))
    )
    with temporary as temp_dir:
        directory = Path(temp_dir)
        sources = {}
        for filename in ("device.yml", "Behavior_44.bin", "Behavior_56.bin", "Behavior_58.bin"):
            url = f"{base}/{filename}"
            source, sha256 = cached_download_with_sha256(url, directory / filename)
            sources[filename] = {**source, "sha256": sha256}
        stimulus_path = directory / "orientations_orientations0.csv"
        stimulus_source, stimulus_sha256 = cached_download_with_sha256(
            stimulus_url, stimulus_path
        )
        with stimulus_path.open(encoding="utf-8-sig", newline="") as stream:
            stimulus_rows = list(csv.DictReader(stream))
        analog = harp.create_reader(directory).AnalogData.read()
        reader = harp.create_reader(directory)
        reference = float(reader.PulseDO0.read().index[0])
        trial_times = reader.PulseDO2.read().index.to_numpy(dtype=float) - reference
    stimulus_rows, trial_times = align_slap2_stimulus(stimulus_rows, trial_times)
    blocks = slap2_block_windows(stimulus_rows, trial_times, context_id)
    timestamps = analog.index.to_numpy(dtype=float) - reference
    counts = analog["Encoder"].to_numpy(dtype=np.int64)
    binned_times, binned_velocity = binned_running_from_counts(timestamps, counts)
    summary = {
        **summarize_velocity(binned_velocity),
        **summarize_blocks(binned_times, binned_velocity, blocks),
        "blocks": blocks,
    }
    if include_profile:
        summary["profile"] = running_profile(binned_times, binned_velocity, blocks)
    source = {
        "device": sources["device.yml"],
        "encoder": sources["Behavior_44.bin"],
        "pulse_do0": sources["Behavior_56.bin"],
        "pulse_do2": sources["Behavior_58.bin"],
        "stimulus": {**stimulus_source, "sha256": stimulus_sha256},
    }
    return summary, source


def available_slap2_sources(session_id: str) -> bool:
    urls = [
        f"{S3_ROOT}/{session_id}/behavior/VCO1_Behavior.harp/{filename}"
        for filename in ("Behavior_44.bin", "Behavior_56.bin", "Behavior_58.bin")
    ]
    urls.append(
        f"{S3_ROOT}/{session_id}/behavior/stimuli/orientations_orientations0.csv"
    )
    for url in urls:
        try:
            remote_metadata(url)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return False
            raise
    return True


def session_result(
    row: dict[str, str], context_id: str, context_label: str, summary: dict, source: dict
) -> dict:
    return {
        "context": context_id,
        "context_label": context_label,
        "date": row["date"],
        "modality": row["modality"],
        "mouse_id": row["mouse_id"],
        "source": source,
        "source_row": int(row["source_row"]),
        "source_session_id": row["source_session_id"],
        **summary,
    }


def extract_nwb_sessions(
    rows_by_key: dict[tuple[str, str], dict[str, str]], cache_dir: Path | None = None
) -> tuple[list[dict], list[dict], list[dict]]:
    sessions = []
    manifests = []
    exclusions = []
    for modality, config in DANDISETS.items():
        assets = dandi_assets(config["id"])
        manifest = sorted(
            [
            {
                "asset_id": asset["asset_id"],
                "modified": asset["modified"],
                "path": asset["path"],
                "size": asset["size"],
            }
            for asset in assets
            ],
            key=lambda record: record["path"],
        )
        manifest_bytes = json.dumps(
            manifest, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode()
        manifests.append(
            {
                "asset_count": len(assets),
                "asset_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                "dandiset_id": config["id"],
                "modality": modality,
                "version": "draft",
            }
        )
        for asset in assets:
            if not asset["path"].endswith(".nwb") or "probe" in asset["path"].lower():
                continue
            session_id = source_session_id(asset["path"], config["session_prefix"])
            row = rows_by_key.get((modality, session_id or ""))
            if row is None:
                raise RuntimeError(f"DANDI NWB does not match the worksheet: {asset['path']}")
            context = context_record(row["session_stimulus"])
            if context is None:
                raise RuntimeError(f"Matched NWB lacks a P3 context: {asset['path']}")
            include_profile = session_id == PROFILE_SESSION_IDS[modality]
            cache_path = (
                cache_dir / "nwb-summaries" / f"{asset['asset_id']}.json"
                if cache_dir is not None
                else None
            )
            cached = None
            if cache_path is not None and cache_path.exists():
                candidate = json.loads(cache_path.read_text(encoding="utf-8"))
                if (
                    candidate.get("cache_version") == SESSION_CACHE_VERSION
                    and candidate.get("asset_modified") == asset["modified"]
                    and candidate.get("context") == context[0]
                    and candidate.get("include_profile") == include_profile
                ):
                    cached = candidate
            try:
                if cached is None:
                    summary, source = nwb_running_summary(
                        asset, context[0], include_profile
                    )
                    if cache_path is not None:
                        cache_path.parent.mkdir(parents=True, exist_ok=True)
                        cache_path.write_text(
                            json.dumps(
                                {
                                    "asset_modified": asset["modified"],
                                    "cache_version": SESSION_CACHE_VERSION,
                                    "context": context[0],
                                    "include_profile": include_profile,
                                    "source": source,
                                    "summary": summary,
                                },
                                ensure_ascii=True,
                                sort_keys=True,
                            ),
                            encoding="utf-8",
                        )
                else:
                    summary = cached["summary"]
                    source = cached["source"]
            except RunningDataUnavailableError:
                exclusions.append(
                    {
                        "asset_id": asset["asset_id"],
                        "modality": modality,
                        "reason": "NWB processed running series unavailable",
                        "source_row": int(row["source_row"]),
                        "source_session_id": row["source_session_id"],
                    }
                )
                continue
            print(f"extracted {modality}: {session_id}", flush=True)
            sessions.append(session_result(row, *context, summary, source))
    return sessions, manifests, exclusions


def extract_slap2_sessions(
    rows: list[dict[str, str]], cache_dir: Path | None = None
) -> tuple[list[dict], list[dict]]:
    sessions = []
    exclusions = []
    for row in rows:
        if row["modality"] != "slap2":
            continue
        context = context_record(row["session_stimulus"])
        if context is None:
            continue
        session_id = row["source_session_id"].removeprefix("SLAP2_")
        if row["source_session_id"] == "aborted" or not available_slap2_sources(
            session_id
        ):
            exclusions.append(
                {
                    "modality": "slap2",
                    "reason": "public Harp encoder file unavailable",
                    "source_row": int(row["source_row"]),
                    "source_session_id": row["source_session_id"],
                }
            )
            continue
        try:
            summary, source = slap2_running_summary(
                session_id,
                context[0],
                session_id == PROFILE_SESSION_IDS["slap2"],
                cache_dir,
            )
        except RunningDataUnavailableError as exc:
            exclusions.append(
                {
                    "modality": "slap2",
                    "reason": str(exc),
                    "source_row": int(row["source_row"]),
                    "source_session_id": row["source_session_id"],
                }
            )
            continue
        print(f"extracted slap2: {session_id}", flush=True)
        sessions.append(session_result(row, *context, summary, source))
    return sessions, exclusions


def aggregate_mouse_context(sessions: list[dict]) -> list[dict]:
    grouped = defaultdict(list)
    for session in sessions:
        grouped[(session["modality"], session["mouse_id"], session["context"])].append(
            session
        )
    results = []
    for (modality, mouse_id, context_id), records in sorted(grouped.items()):
        results.append(
            {
                "context": context_id,
                "context_label": records[0]["context_label"],
                "mean_forward_speed_cm_s": round(
                    sum(record["mean_forward_speed_cm_s"] for record in records)
                    / len(records),
                    4,
                ),
                "context_mean_forward_speed_cm_s": round(
                    sum(
                        record["context_mean_forward_speed_cm_s"]
                        for record in records
                    )
                    / len(records),
                    4,
                ),
                "control_mean_forward_speed_cm_s": round(
                    sum(
                        record["control_mean_forward_speed_cm_s"]
                        for record in records
                    )
                    / len(records),
                    4,
                ),
                "modality": modality,
                "mouse_id": mouse_id,
                "running_fraction": round(
                    sum(record["running_fraction"] for record in records) / len(records),
                    6,
                ),
                "session_count": len(records),
                "source_session_ids": sorted(
                    record["source_session_id"] for record in records
                ),
            }
        )
    return results


def aggregate_mouse_blocks(sessions: list[dict]) -> list[dict]:
    grouped = defaultdict(list)
    for session in sessions:
        grouped[(session["modality"], session["mouse_id"])].append(session)
    results = []
    for (modality, mouse_id), records in sorted(grouped.items()):
        for block_id, _, _ in BLOCK_DEFINITIONS:
            results.append(
                {
                    "block": block_id,
                    "mean_forward_speed_cm_s": round(
                        sum(
                            record["block_mean_forward_speed_cm_s"][block_id]
                            for record in records
                        )
                        / len(records),
                        4,
                    ),
                    "modality": modality,
                    "mouse_id": mouse_id,
                    "session_count": len(records),
                    "source_session_ids": sorted(
                        record["source_session_id"] for record in records
                    ),
                }
            )
    return results


def collect_example_profiles(sessions: list[dict]) -> list[dict]:
    profiles = []
    for session in sessions:
        profile = session.pop("profile", None)
        if profile is None:
            continue
        profiles.append(
            {
                "context": session["context"],
                "modality": session["modality"],
                "mouse_id": session["mouse_id"],
                "source_session_id": session["source_session_id"],
                **profile,
            }
        )
    if {record["modality"] for record in profiles} != set(PROFILE_SESSION_IDS):
        raise RuntimeError("One full-session example profile is required per modality.")
    return sorted(profiles, key=lambda record: tuple(PROFILE_SESSION_IDS).index(record["modality"]))


def coverage_records(rows: list[dict[str, str]], sessions: list[dict]) -> list[dict]:
    results = []
    for modality in ("neuropixels", "mesoscope", "slap2"):
        for _, context_id, context_label in CONTEXTS:
            worksheet = [
                row
                for row in rows
                if row["modality"] == modality
                and context_record(row["session_stimulus"])
                == (context_id, context_label)
            ]
            included = [
                session
                for session in sessions
                if session["modality"] == modality and session["context"] == context_id
            ]
            results.append(
                {
                    "context": context_id,
                    "context_label": context_label,
                    "included_mice": len({record["mouse_id"] for record in included}),
                    "included_sessions": len(included),
                    "modality": modality,
                    "worksheet_mice": len({record["mouse_id"] for record in worksheet}),
                    "worksheet_sessions": len(worksheet),
                }
            )
    return results


def main() -> None:
    args = parse_args()
    rows = load_session_records()
    rows_by_key = {
        (row["modality"], row["source_session_id"]): row
        for row in rows
        if context_record(row["session_stimulus"]) is not None
    }
    nwb_sessions, dandisets, nwb_exclusions = extract_nwb_sessions(
        rows_by_key, args.cache_dir
    )
    slap2_sessions, slap2_exclusions = extract_slap2_sessions(rows, args.cache_dir)
    exclusions = [*nwb_exclusions, *slap2_exclusions]
    sessions = sorted(
        [*nwb_sessions, *slap2_sessions],
        key=lambda record: (
            record["modality"],
            record["mouse_id"],
            record["date"],
            record["source_session_id"],
        ),
    )
    example_profiles = collect_example_profiles(sessions)
    session_provenance = json.loads(SESSION_PROVENANCE_PATH.read_text(encoding="utf-8"))
    included_ids = {
        (session["modality"], session["source_session_id"]) for session in sessions
    }
    excluded_ids = {
        (record["modality"], record["source_session_id"]) for record in exclusions
    }
    for row in rows:
        key = (row["modality"], row["source_session_id"])
        if (
            context_record(row["session_stimulus"]) is not None
            and key not in included_ids
            and key not in excluded_ids
        ):
            exclusions.append(
                {
                    "modality": row["modality"],
                    "reason": "matching public running source unavailable",
                    "source_row": int(row["source_row"]),
                    "source_session_id": row["source_session_id"],
                }
            )
    payload = {
        "calibration": {
            "slap2": {
                "counter_bits": SLAP2_COUNTER_BITS,
                "counts_per_revolution": SLAP2_COUNTS_PER_REVOLUTION,
                "source_url": SLAP2_CALIBRATION_URL,
                "subject_position": SLAP2_SUBJECT_POSITION,
                "wheel_radius_cm": SLAP2_WHEEL_RADIUS_CM,
            }
        },
        "contexts": [
            {"id": context_id, "label": label} for _, context_id, label in CONTEXTS
        ],
        "coverage": coverage_records(rows, sessions),
        "dandisets": dandisets,
        "exclusions": sorted(
            exclusions,
            key=lambda record: (record["modality"], record["source_row"]),
        ),
        "example_profiles": example_profiles,
        "method": {
            "aggregation": (
                "Session metrics are arithmetic means within each mouse and context; "
                "each mouse contributes one plotted value per context."
            ),
            "binning": (
                "Velocity is integrated to position and differenced in non-overlapping "
                "50 ms bins; SLAP2 encoder position is calibrated before differencing."
            ),
            "block_comparison": (
                "Context means use the context-specific 26-minute block. Control means "
                "pool standard, standard-repeat, sequence, jitter, and open-loop blocks; "
                "natural-movie and receptive-field blocks are excluded."
            ),
            "forward_speed": "Negative velocity is set to zero before summarization.",
            "running_fraction": (
                f"Fraction of {1000 // SAMPLE_RATE_HZ} ms bins with forward speed above "
                f"{RUNNING_THRESHOLD_CM_S:g} cm/s."
            ),
            "profile": (
                f"Example profiles average forward speed in {PROFILE_BIN_SECONDS}-second "
                "bins over measured protocol-block boundaries."
            ),
            "scope": "Finite running samples within measured protocol blocks.",
        },
        "mouse_context": aggregate_mouse_context(sessions),
        "mouse_block": aggregate_mouse_blocks(sessions),
        "retrieved_date": "2026-07-31",
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "sessions": sessions,
        "source_session_records": {
            "sha256": hashlib.sha256(SESSION_RECORDS_PATH.read_bytes()).hexdigest(),
            "source_url": session_provenance["source_url"],
        },
        "threshold_cm_s": RUNNING_THRESHOLD_CM_S,
        "version": 2,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(
        (json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True) + "\n").encode()
    )


if __name__ == "__main__":
    main()