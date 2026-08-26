#!/usr/bin/env python3
"""Extract mouse-ready peri-event pupil and running responses from public P3 NWBs."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import importlib
import json
import math
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from types import ModuleType

from openscope_p3_publication.figures import session_cohort
from openscope_p3_publication.pupil_responses import (
    EVENT_DEFINITIONS,
    EventDefinition,
    combine_mean_and_std_traces,
    event_baseline_windows,
    event_matches,
    event_response_windows,
    event_start_times,
    pupil_response_window_label,
    remove_isolated_outliers_with_interpolation,
    subtract_traces,
)

EXTRACTION_ENVIRONMENT_HINT = (
    "Run with: uv run --with h5py --with numpy --with remfile "
    "python scripts/extract_pupil_event_responses.py"
)

try:
    np = importlib.import_module("numpy")
except ImportError as exc:  # pragma: no cover - optional extraction environment
    raise SystemExit(EXTRACTION_ENVIRONMENT_HINT) from exc


def import_optional_module(name: str) -> ModuleType | None:
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


h5py = import_optional_module("h5py")
remfile = import_optional_module("remfile")

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "figure_sources" / "data"
DATA_ACCESS_PATH = DATA_DIR / "data-access.csv"
DATA_ACCESS_PROVENANCE_PATH = DATA_ACCESS_PATH.with_suffix(".provenance.json")
SESSION_RECORDS_PATH = DATA_DIR / "experimental-sessions.csv"
SESSION_PROVENANCE_PATH = SESSION_RECORDS_PATH.with_suffix(".provenance.json")
DEFAULT_OUTPUT = DATA_DIR / "pupil-event-responses.json"
DEFAULT_PROVENANCE_OUTPUT = DATA_DIR / "pupil-event-responses.provenance.json"

DANDI_API = "https://api.dandiarchive.org/api"
DANDISET_VERSIONS = {
    "001424": "draft",
    "001637": "draft",
    "001768": "draft",
}
MODALITY_IDS = {
    "Mesoscope": "mesoscope",
    "Neuropixels": "neuropixels",
    "SLAP2": "slap2",
}
MODALITY_ORDER = {"neuropixels": 0, "mesoscope": 1, "slap2": 2}
CONTEXT_IDS = {
    "Sensorimotor": "sensorimotor",
    "Standard oddball": "standard",
    "Sequence": "sequence",
    "Duration": "duration",
}
CONTEXT_ORDER = {
    "standard": 0,
    "sensorimotor": 1,
    "sequence": 2,
    "duration": 3,
}
TABLE_CANDIDATES = {
    "standard": {
        "context": ("Standard mismatch block_presentations", "standard_oddball"),
        "control": ("Control block 1_presentations", "standard_control"),
    },
    "sensorimotor": {
        "context": ("Sensory-motor mismatch block_presentations", "motor_oddball"),
        "control": ("Control block 4_presentations", "open_loop_prerecorded"),
    },
    "sequence": {
        "context": ("Sequence mismatch block_presentations", "sequential_oddball"),
        "control": ("Control block 2_presentations", "sequential_control_block"),
    },
    "duration": {
        "context": ("Duration mismatch block_presentations", "jitter_oddball"),
        "control": ("Control block 3_presentations", "jitter_control"),
    },
}

EXTRACTION_VERSION = 2
CACHE_VERSION = 3
COMPATIBLE_CACHE_SIGNATURES = {
    "5f3b9b7207d80be291515967adf2562c486fccedc083162d2c7bf588e5f36072",
}
TRACE_RATE_HZ = 20
WINDOW_START_SECONDS = -2.0
WINDOW_END_SECONDS = 4.0
TIME_GRID = np.round(
    np.arange(
        WINDOW_START_SECONDS,
        WINDOW_END_SECONDS + 0.5 / TRACE_RATE_HZ,
        1 / TRACE_RATE_HZ,
    ),
    6,
)
BLINK_PADDING_SECONDS = 0.1
MAX_INTERPOLATION_GAP_SECONDS = 0.2
MAX_NONINCREASING_SAMPLE_FRACTION = 0.001
OUTLIER_WINDOW_SECONDS = 3.0
OUTLIER_ZSCORE_THRESHOLD = 3.0
MAX_ISOLATED_OUTLIER_SAMPLES = 3
PUPIL_QUANTILES = (0.01, 0.99)
MINIMUM_BASELINE_FRACTION = 0.8
MINIMUM_PUPIL_WINDOW_FRACTION = 0.75
MINIMUM_RUNNING_WINDOW_FRACTION = 0.75
BOOTSTRAP_RESAMPLES = 2_000


class SessionUnavailableError(RuntimeError):
    """Raised when a source NWB cannot support the requested event analysis."""


class SignalUnavailableError(RuntimeError):
    """Raised when one behavioral signal is absent or structurally invalid."""


def require_extraction_environment() -> None:
    if h5py is None or remfile is None:
        raise SystemExit(EXTRACTION_ENVIRONMENT_HINT)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--provenance-output",
        type=Path,
        default=DEFAULT_PROVENANCE_OUTPUT,
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="Optional accelerator for verified per-session derived summaries.",
    )
    parser.add_argument(
        "--modality",
        action="append",
        choices=tuple(MODALITY_ORDER),
        help="Extract only this modality; may be repeated.",
    )
    parser.add_argument(
        "--session-id",
        action="append",
        help="Extract only this source session ID; may be repeated.",
    )
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--bootstrap-resamples", type=int, default=BOOTSTRAP_RESAMPLES)
    parser.add_argument(
        "--retrieved-date",
        default=dt.date.today().isoformat(),
        help="ISO date recorded in provenance.",
    )
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized_session_id(value: str) -> str:
    return value.removeprefix("SLAP2_")


def session_date_from_id(value: str) -> str:
    candidates = []
    for part in normalized_session_id(value).split("_"):
        try:
            dt.date.fromisoformat(part)
        except ValueError:
            continue
        candidates.append(part)
    if len(candidates) != 1:
        raise RuntimeError(f"Session ID does not contain one ISO date: {value}")
    return candidates[0]


def decode(value):
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, np.generic):
        return value.item()
    return value


def column(group: h5py.Group, name: str) -> h5py.Dataset:
    for candidate in (name, name[0].lower() + name[1:], name.lower()):
        if candidate in group:
            return group[candidate]
    raise SessionUnavailableError(f"{group.name} is missing {name}.")


def resolve_table(intervals: h5py.Group, candidates: tuple[str, ...]) -> str:
    for candidate in candidates:
        if candidate in intervals:
            return candidate
    raise SessionUnavailableError(
        f"No interval table among {candidates}; found {sorted(intervals)}."
    )


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    last_error = None
    for _ in range(5):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.load(response)
        except urllib.error.HTTPError:
            raise
        except (ConnectionError, TimeoutError, urllib.error.URLError) as exc:
            last_error = exc
    raise RuntimeError(f"Request failed after five attempts: {url}") from last_error


def load_csv_snapshot(path: Path, provenance_path: Path) -> list[dict[str, str]]:
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if file_sha256(path) != provenance["vendored_sha256"]:
        raise RuntimeError(f"{path.name} does not match its provenance checksum.")
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != provenance["rows"]:
        raise RuntimeError(f"{path.name} row count does not match its provenance.")
    return rows


def load_session_configs() -> tuple[list[dict], dict]:
    access_rows = load_csv_snapshot(DATA_ACCESS_PATH, DATA_ACCESS_PROVENANCE_PATH)
    session_rows = load_csv_snapshot(SESSION_RECORDS_PATH, SESSION_PROVENANCE_PATH)

    source_rows_by_key = {}
    grouped_source_rows = defaultdict(list)
    for row in session_rows:
        normalized_id = normalized_session_id(row["source_session_id"])
        key = (
            row["modality"],
            normalized_id,
        )
        if normalized_id and normalized_id != "aborted":
            if key in source_rows_by_key:
                raise RuntimeError(f"Duplicate experimental-session key: {key}")
            source_rows_by_key[key] = row
        grouped_source_rows[(row["modality"], row["mouse_id"])].append(row)

    cohort_by_mouse = {
        key: session_cohort(records, key[0])
        for key, records in grouped_source_rows.items()
    }
    configs = []
    for row in access_rows:
        context = CONTEXT_IDS.get(row["Context"])
        if context is None:
            continue
        modality = MODALITY_IDS[row["Modality"]]
        session_id = normalized_session_id(row["Session ID"])
        source_row = source_rows_by_key.get((modality, session_id))
        if source_row is None:
            raise RuntimeError(
                f"Data-access session has no worksheet source row: {row['Session ID']}"
            )
        if source_row["mouse_id"] != row["Mouse ID"]:
            raise RuntimeError(f"Mouse mismatch for data-access session {row['Session ID']}.")
        session_date = session_date_from_id(session_id)
        if row["Date"] != session_date:
            raise RuntimeError(
                f"Data-access date does not match session ID: {row['Session ID']}."
            )
        configs.append(
            {
                "cohort": (
                    "motor"
                    if cohort_by_mouse[(modality, row["Mouse ID"])] == 1
                    else "sequence"
                ),
                "context": context,
                "dandi_path": row["DANDI path"],
                "dandi_url": row["DANDI link"],
                "dandiset_id": row["Dandiset ID"],
                "date": session_date,
                "modality": modality,
                "mouse_id": row["Mouse ID"],
                "qc": source_row["qc"],
                "session_id": session_id,
                "source_row": int(source_row["source_row"]),
            }
        )
    configs.sort(
        key=lambda record: (
            MODALITY_ORDER[record["modality"]],
            record["cohort"],
            CONTEXT_ORDER[record["context"]],
            record["mouse_id"],
            record["date"],
            record["session_id"],
        )
    )
    source_snapshots = {
        "data_access": {
            "path": str(DATA_ACCESS_PATH.relative_to(REPO_ROOT)),
            "sha256": file_sha256(DATA_ACCESS_PATH),
        },
        "experimental_sessions": {
            "path": str(SESSION_RECORDS_PATH.relative_to(REPO_ROOT)),
            "sha256": file_sha256(SESSION_RECORDS_PATH),
        },
    }
    return configs, source_snapshots


def load_dandi_assets(
    dandiset_ids: set[str],
) -> tuple[dict[str, dict[str, dict]], list[dict]]:
    assets_by_dandiset = {}
    manifests = []
    for dandiset_id in sorted(dandiset_ids):
        version = DANDISET_VERSIONS[dandiset_id]
        url = (
            f"{DANDI_API}/dandisets/{dandiset_id}/versions/{version}/assets/"
            "?page_size=100"
        )
        assets = []
        while url:
            page = fetch_json(url)
            assets.extend(page["results"])
            url = page["next"]
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
            manifest,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        manifests.append(
            {
                "asset_count": len(manifest),
                "asset_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                "dandiset_id": dandiset_id,
                "version": version,
            }
        )
        assets_by_dandiset[dandiset_id] = {
            asset["path"]: asset for asset in assets
        }
    return assets_by_dandiset, manifests


def analysis_parameters(bootstrap_resamples: int) -> dict:
    return {
        "aggregation": {
            "inference_unit": "mouse",
            "mouse_sessions": "unweighted mean across repeated sessions",
            "session_trials": "unweighted mean across valid trials",
        },
        "baseline": {
            "duration": (
                "unmanipulated interval from row i-2 stop_time to row i-1 start_time"
            ),
            "sensorimotor": "343 ms immediately preceding current start_time",
            "sequence": "recorded previous start_time to current start_time",
            "standard": "recorded previous stop_time to current start_time",
        },
        "bootstrap": {
            "confidence_interval": 0.95,
            "resamples": bootstrap_resamples,
            "sampling_unit": "mouse",
            "seed": "sha256 of summary key",
        },
        "event_alignment": (
            "NWB interval-table start_time for every selected context and control row; "
            "start_time is the display-synchronized, frame-quantized stimulus boundary"
        ),
        "events": {
            context: [asdict(definition) for definition in definitions]
            for context, definitions in EVENT_DEFINITIONS.items()
        },
        "matched_controls": {
            "duration": "same delay or omission in jitter control",
            "sensorimotor": "same motor event in open-loop prerecorded control",
            "sequence": "same physical event in sequential control",
            "standard": "same physical event in standard control blocks",
        },
        "pupil": {
            "blink_padding_seconds": BLINK_PADDING_SECONDS,
            "invalid_fit_rule": "finite positive area, width, and height",
            "maximum_interpolation_gap_seconds": MAX_INTERPOLATION_GAP_SECONDS,
            "minimum_baseline_fraction": MINIMUM_BASELINE_FRACTION,
            "minimum_window_fraction": MINIMUM_PUPIL_WINDOW_FRACTION,
            "normalization": "percent change from each trial's median baseline",
            "outlier_max_isolated_samples": MAX_ISOLATED_OUTLIER_SAMPLES,
            "outlier_window_seconds": OUTLIER_WINDOW_SECONDS,
            "outlier_zscore_threshold": OUTLIER_ZSCORE_THRESHOLD,
            "quantile_range": list(PUPIL_QUANTILES),
            "response_window": {
                "duration": (
                    "start_time + 0.343 s through start_time + 0.343 s + row Delay"
                ),
                "sensorimotor": "NWB start_time through stop_time",
                "sequence": "NWB start_time through stop_time",
                "standard": "NWB start_time through stop_time",
            },
        },
        "running": {
            "direction": "forward speed; negative source velocities set to zero",
            "maximum_interpolation_gap_seconds": MAX_INTERPOLATION_GAP_SECONDS,
            "minimum_baseline_fraction": MINIMUM_BASELINE_FRACTION,
            "minimum_window_fraction": MINIMUM_RUNNING_WINDOW_FRACTION,
            "normalization": "subtract each trial's mean baseline speed",
            "response_window": {
                "duration": (
                    "start_time + 0.343 s through start_time + 0.343 s + row Delay"
                ),
                "sensorimotor": "NWB start_time through stop_time",
                "sequence": "NWB start_time through stop_time",
                "standard": "NWB start_time through stop_time",
            },
            "timestamp_cleanup": (
                "discard non-increasing samples only when at most 0.1% of the series"
            ),
            "unit": "cm/s",
        },
        "trace_sampling": {
            "filter": "none",
            "method": "linear interpolation at the common time-grid timestamps",
        },
        "time_grid_seconds": TIME_GRID.tolist(),
        "trace_rate_hz": TRACE_RATE_HZ,
        "window_seconds": [WINDOW_START_SECONDS, WINDOW_END_SECONDS],
    }


def analysis_signature(bootstrap_resamples: int) -> str:
    parameters = analysis_parameters(bootstrap_resamples)
    parameters.pop("bootstrap")
    content = json.dumps(
        {
            "analysis_module_sha256": file_sha256(
                REPO_ROOT
                / "src"
                / "openscope_p3_publication"
                / "pupil_responses.py"
            ),
            "parameters": parameters,
            "script_sha256": file_sha256(Path(__file__)),
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(content).hexdigest()


def source_asset_record(config: dict, asset: dict) -> dict:
    detail = fetch_json(f"{DANDI_API}/assets/{asset['asset_id']}/")
    if detail["path"] != asset["path"]:
        raise RuntimeError(f"DANDI asset detail path changed: {asset['asset_id']}")
    digest = detail.get("digest", {})
    if "dandi:sha2-256" not in digest:
        raise RuntimeError(f"DANDI asset lacks SHA-256: {asset['asset_id']}")
    return {
        "asset_id": asset["asset_id"],
        "dandiset_id": config["dandiset_id"],
        "digest": digest,
        "download_url": f"{DANDI_API}/assets/{asset['asset_id']}/download/",
        "modified": asset["modified"],
        "path": asset["path"],
        "size": asset["size"],
        "version": DANDISET_VERSIONS[config["dandiset_id"]],
    }


def padded_blinks(timestamps: np.ndarray, blinks: np.ndarray) -> np.ndarray:
    sample_interval = float(np.median(np.diff(timestamps)))
    radius = max(1, int(math.ceil(BLINK_PADDING_SECONDS / sample_interval)))
    kernel = np.ones(2 * radius + 1, dtype=np.uint8)
    return np.convolve(blinks.astype(np.uint8), kernel, mode="same") > 0


def interpolate_with_gap_limit(
    timestamps: np.ndarray,
    values: np.ndarray,
    targets: np.ndarray,
) -> np.ndarray:
    right = np.searchsorted(timestamps, targets)
    left = right - 1
    result = np.full(len(targets), np.nan, dtype=float)
    within = (left >= 0) & (right < len(timestamps))
    target_indices = np.flatnonzero(within)
    if not len(target_indices):
        return result
    left_indices = left[target_indices]
    right_indices = right[target_indices]
    gaps = timestamps[right_indices] - timestamps[left_indices]
    close = gaps <= MAX_INTERPOLATION_GAP_SECONDS
    target_indices = target_indices[close]
    left_indices = left_indices[close]
    right_indices = right_indices[close]
    fractions = (
        (targets[target_indices] - timestamps[left_indices])
        / (timestamps[right_indices] - timestamps[left_indices])
    )
    result[target_indices] = values[left_indices] + fractions * (
        values[right_indices] - values[left_indices]
    )
    return result


def signal_window_values(
    signal: dict,
    start: float,
    end: float,
    *,
    include_end: bool = False,
) -> np.ndarray:
    left = int(np.searchsorted(signal["timestamps"], start, side="left"))
    right = int(
        np.searchsorted(
            signal["timestamps"],
            end,
            side="right" if include_end else "left",
        )
    )
    return signal["values"][left:right]


def prepare_pupil(nwb: h5py.File) -> dict:
    path = "processing/eye_tracking"
    if path not in nwb:
        raise SignalUnavailableError("processed eye-tracking module unavailable")
    eye = nwb[path]
    required = (
        "pupil/timestamps",
        "pupil/area",
        "pupil/width",
        "pupil/height",
        "likely_blink_times/timestamps",
        "likely_blink_times/data",
    )
    missing = [name for name in required if name not in eye]
    if missing:
        raise SignalUnavailableError(f"eye tracking is missing {missing}")
    timestamps = np.asarray(eye["pupil/timestamps"][:], dtype=float)
    blink_timestamps = np.asarray(
        eye["likely_blink_times/timestamps"][:],
        dtype=float,
    )
    if not np.array_equal(timestamps, blink_timestamps):
        raise SignalUnavailableError(
            "pupil fits and blink flags do not share one timestamp array"
        )
    if len(timestamps) < 2 or np.any(np.diff(timestamps) <= 0):
        raise SignalUnavailableError("pupil timestamps are not strictly increasing")

    area = np.asarray(eye["pupil/area"][:], dtype=float)
    widths = np.asarray(eye["pupil/width"][:], dtype=float)
    heights = np.asarray(eye["pupil/height"][:], dtype=float)
    blinks = np.asarray(eye["likely_blink_times/data"][:], dtype=bool)
    if not (len(area) == len(widths) == len(heights) == len(blinks) == len(timestamps)):
        raise SignalUnavailableError("pupil fit arrays have inconsistent lengths")
    sample_rate_hz = float(1 / np.median(np.diff(timestamps)))
    cleaned, outlier_indices = remove_isolated_outliers_with_interpolation(
        area,
        sample_rate_hz,
        window_seconds=OUTLIER_WINDOW_SECONDS,
        zscore_threshold=OUTLIER_ZSCORE_THRESHOLD,
        max_isolated_length=MAX_ISOLATED_OUTLIER_SAMPLES,
    )
    area = np.asarray(cleaned, dtype=float)
    padded = padded_blinks(timestamps, blinks)
    preliminary = (
        np.isfinite(area)
        & np.isfinite(widths)
        & np.isfinite(heights)
        & (area > 0)
        & (widths > 0)
        & (heights > 0)
        & ~padded
    )
    if np.count_nonzero(preliminary) < 100:
        raise SignalUnavailableError("fewer than 100 valid nonblink pupil fits")
    low, high = np.quantile(area[preliminary], PUPIL_QUANTILES)
    valid = preliminary & (area >= low) & (area <= high)
    return {
        "blink_fraction": float(np.mean(blinks)),
        "interpolated_outlier_count": len(outlier_indices),
        "sample_rate_hz": sample_rate_hz,
        "timestamps": timestamps[valid],
        "total_samples": len(timestamps),
        "valid_fraction": float(np.mean(valid)),
        "valid_range_px2": [float(low), float(high)],
        "values": area[valid],
    }


def prepare_running(nwb: h5py.File) -> dict:
    path = "processing/running/running_speed"
    if path not in nwb:
        raise SignalUnavailableError("processed running-speed series unavailable")
    series = nwb[path]
    if "data" not in series or "timestamps" not in series:
        raise SignalUnavailableError("running-speed series lacks data or timestamps")
    data = series["data"]
    timestamps = np.asarray(series["timestamps"][:], dtype=float)
    velocity = np.asarray(data[:], dtype=float)
    if timestamps.ndim != 1 or velocity.ndim != 1 or len(timestamps) != len(velocity):
        raise SignalUnavailableError("running-speed arrays are not paired vectors")
    if len(timestamps) < 2:
        raise SignalUnavailableError("running-speed series has fewer than two samples")
    conversion = float(data.attrs.get("conversion", 1.0))
    offset = float(data.attrs.get("offset", 0.0))
    velocity = velocity * conversion + offset
    unit = str(decode(data.attrs.get("unit", series.attrs.get("unit", ""))))
    if unit.lower().replace(" ", "") not in {"cm/s", "cmps"}:
        raise SignalUnavailableError(f"unsupported running-speed unit {unit!r}")
    finite = np.isfinite(timestamps) & np.isfinite(velocity)
    timestamps = timestamps[finite]
    velocity = velocity[finite]
    if len(timestamps) < 2:
        raise SignalUnavailableError(
            "running-speed series has fewer than two finite samples"
        )
    previous_maximum = np.concatenate(
        ([-np.inf], np.maximum.accumulate(timestamps[:-1]))
    )
    increasing = timestamps > previous_maximum
    discarded = int(np.count_nonzero(~increasing))
    if discarded > max(
        3,
        round(len(timestamps) * MAX_NONINCREASING_SAMPLE_FRACTION),
    ):
        raise SignalUnavailableError(
            f"discarding {discarded} non-increasing running timestamps would exceed 0.1%"
        )
    timestamps = timestamps[increasing]
    velocity = velocity[increasing]
    sample_rate_hz = float(1 / np.median(np.diff(timestamps)))
    return {
        "discarded_nonincreasing_sample_count": discarded,
        "negative_sample_fraction": float(np.mean(velocity < 0)),
        "sample_rate_hz": sample_rate_hz,
        "timestamps": timestamps,
        "total_samples": len(finite),
        "unit": "cm/s",
        "valid_fraction": float(np.mean(finite)),
        "values": np.maximum(velocity, 0),
    }


def table_arrays(table: h5py.Group) -> dict:
    return {
        "block_number": np.asarray(column(table, "BlockNumber")[:], dtype=float),
        "delay": np.asarray(column(table, "Delay")[:], dtype=float),
        "orientation": np.asarray(column(table, "Orientation")[:], dtype=float),
        "start": np.asarray(column(table, "start_time")[:], dtype=float),
        "stop": np.asarray(column(table, "stop_time")[:], dtype=float),
        "trial_type": np.asarray(column(table, "TrialType")[:]).astype("U"),
    }


def selected_indices(
    arrays: dict,
    definition: EventDefinition,
    *,
    control: bool,
) -> np.ndarray:
    return np.asarray(
        [
            index
            for index, (trial_type, orientation, delay) in enumerate(
                zip(
                    arrays["trial_type"],
                    arrays["orientation"],
                    arrays["delay"],
                    strict=True,
                )
            )
            if event_matches(
                definition,
                str(trial_type),
                control=control,
                orientation=float(orientation),
                delay=float(delay),
            )
        ],
        dtype=int,
    )


def rounded_optional_trace(values: np.ndarray) -> list[float | None]:
    return [
        None if not np.isfinite(value) else round(float(value), 5)
        for value in values
    ]


def averaged_trace(traces: list[np.ndarray]) -> list[float | None]:
    matrix = np.vstack(traces)
    finite_counts = np.sum(np.isfinite(matrix), axis=0)
    averaged = np.divide(
        np.nansum(matrix, axis=0),
        finite_counts,
        out=np.full(matrix.shape[1], np.nan),
        where=finite_counts > 0,
    )
    return rounded_optional_trace(averaged)


def standard_deviation_trace(traces: list[np.ndarray]) -> list[float | None]:
    matrix = np.vstack(traces)
    finite_counts = np.sum(np.isfinite(matrix), axis=0)
    means = np.divide(
        np.nansum(matrix, axis=0),
        finite_counts,
        out=np.full(matrix.shape[1], np.nan),
        where=finite_counts > 0,
    )
    squared_deviations = np.where(
        np.isfinite(matrix),
        (matrix - means) ** 2,
        0,
    )
    variances = np.divide(
        np.sum(squared_deviations, axis=0),
        finite_counts,
        out=np.full(matrix.shape[1], np.nan),
        where=finite_counts > 0,
    )
    return rounded_optional_trace(np.sqrt(variances))


def summarize_trial_traces(
    raw_traces: list[np.ndarray],
    percent_change_traces: list[np.ndarray],
    baselines: list[float],
    baseline_durations: list[float],
    response_starts: list[float],
    response_ends: list[float],
    responses: list[float],
    available_trials: int,
    rejections: Counter,
) -> dict:
    if not percent_change_traces:
        return {
            "available_trials": available_trials,
            "baseline_mean_px2": None,
            "baseline_duration_mean_seconds": None,
            "percent_change_mean_trace": None,
            "percent_change_std_trace": None,
            "raw_mean_trace": None,
            "raw_std_trace": None,
            "rejections": dict(sorted(rejections.items())),
            "response_percent_change_mean": None,
            "response_percent_change_std": None,
            "response_start_mean_seconds": None,
            "response_end_mean_seconds": None,
            "valid_trials": 0,
        }

    return {
        "available_trials": available_trials,
        "baseline_mean_px2": round(float(np.mean(baselines)), 5),
        "baseline_duration_mean_seconds": round(
            float(np.mean(baseline_durations)),
            6,
        ),
        "percent_change_mean_trace": averaged_trace(percent_change_traces),
        "percent_change_std_trace": standard_deviation_trace(
            percent_change_traces
        ),
        "raw_mean_trace": averaged_trace(raw_traces),
        "raw_std_trace": standard_deviation_trace(raw_traces),
        "rejections": dict(sorted(rejections.items())),
        "response_percent_change_mean": round(float(np.mean(responses)), 5),
        "response_percent_change_std": round(float(np.std(responses)), 5),
        "response_start_mean_seconds": round(
            float(np.mean(response_starts)),
            6,
        ),
        "response_end_mean_seconds": round(
            float(np.mean(response_ends)),
            6,
        ),
        "valid_trials": len(percent_change_traces),
    }


def pupil_event_summary(
    signal: dict,
    onsets: np.ndarray,
    baseline_windows: list[tuple[float, float] | None],
    response_windows: list[tuple[float, float]],
) -> dict:
    raw_traces = []
    percent_change_traces = []
    baselines = []
    baseline_durations = []
    response_starts = []
    response_ends = []
    responses = []
    rejections = Counter()
    minimum_window = math.ceil(len(TIME_GRID) * MINIMUM_PUPIL_WINDOW_FRACTION)
    for onset, baseline_window, response_window in zip(
        onsets,
        baseline_windows,
        response_windows,
        strict=True,
    ):
        if baseline_window is None:
            rejections["no preceding within-block baseline"] += 1
            continue
        baseline_start, baseline_end = baseline_window
        trace = interpolate_with_gap_limit(
            signal["timestamps"],
            signal["values"],
            onset + TIME_GRID,
        )
        baseline_duration = baseline_end - baseline_start
        baseline_values = signal_window_values(
            signal,
            baseline_start,
            baseline_end,
        )
        expected_baseline_samples = baseline_duration * signal["sample_rate_hz"]
        minimum_baseline_samples = max(
            2,
            math.ceil(expected_baseline_samples * MINIMUM_BASELINE_FRACTION),
        )
        if len(baseline_values) < minimum_baseline_samples:
            rejections["incomplete baseline"] += 1
            continue
        if np.count_nonzero(np.isfinite(trace)) < minimum_window:
            rejections["incomplete event window"] += 1
            continue
        baseline = float(np.nanmedian(baseline_values))
        if baseline <= 0:
            rejections["nonpositive baseline"] += 1
            continue
        normalized = (trace / baseline - 1) * 100
        response_start, response_end = response_window
        response_values = signal_window_values(
            signal,
            response_start,
            response_end,
            include_end=True,
        )
        response_duration = response_end - response_start
        minimum_response_samples = max(
            2,
            math.ceil(
                response_duration
                * signal["sample_rate_hz"]
                * MINIMUM_PUPIL_WINDOW_FRACTION
            ),
        )
        if len(response_values) < minimum_response_samples:
            rejections["incomplete response window"] += 1
            continue
        response = float(np.mean((response_values / baseline - 1) * 100))
        raw_traces.append(trace)
        percent_change_traces.append(normalized)
        baselines.append(baseline)
        baseline_durations.append(baseline_duration)
        response_starts.append(response_start - onset)
        response_ends.append(response_end - onset)
        responses.append(response)
    return summarize_trial_traces(
        raw_traces,
        percent_change_traces,
        baselines,
        baseline_durations,
        response_starts,
        response_ends,
        responses,
        len(onsets),
        rejections,
    )


def summarize_running_trial_traces(
    raw_traces: list[np.ndarray],
    baseline_change_traces: list[np.ndarray],
    baselines: list[float],
    baseline_durations: list[float],
    response_starts: list[float],
    response_ends: list[float],
    response_speeds: list[float],
    response_changes: list[float],
    available_trials: int,
    rejections: Counter,
) -> dict:
    if not raw_traces:
        return {
            "available_trials": available_trials,
            "baseline_change_mean_trace": None,
            "baseline_change_std_trace": None,
            "baseline_duration_mean_seconds": None,
            "baseline_mean_cm_s": None,
            "raw_mean_trace": None,
            "raw_std_trace": None,
            "rejections": dict(sorted(rejections.items())),
            "response_change_mean_cm_s": None,
            "response_change_std_cm_s": None,
            "response_end_mean_seconds": None,
            "response_mean_cm_s": None,
            "response_start_mean_seconds": None,
            "response_std_cm_s": None,
            "valid_trials": 0,
        }
    return {
        "available_trials": available_trials,
        "baseline_change_mean_trace": averaged_trace(baseline_change_traces),
        "baseline_change_std_trace": standard_deviation_trace(
            baseline_change_traces
        ),
        "baseline_duration_mean_seconds": round(
            float(np.mean(baseline_durations)),
            6,
        ),
        "baseline_mean_cm_s": round(float(np.mean(baselines)), 5),
        "raw_mean_trace": averaged_trace(raw_traces),
        "raw_std_trace": standard_deviation_trace(raw_traces),
        "rejections": dict(sorted(rejections.items())),
        "response_change_mean_cm_s": round(float(np.mean(response_changes)), 5),
        "response_change_std_cm_s": round(float(np.std(response_changes)), 5),
        "response_end_mean_seconds": round(float(np.mean(response_ends)), 6),
        "response_mean_cm_s": round(float(np.mean(response_speeds)), 5),
        "response_start_mean_seconds": round(float(np.mean(response_starts)), 6),
        "response_std_cm_s": round(float(np.std(response_speeds)), 5),
        "valid_trials": len(raw_traces),
    }


def running_event_summary(
    signal: dict,
    onsets: np.ndarray,
    baseline_windows: list[tuple[float, float] | None],
    response_windows: list[tuple[float, float]],
) -> dict:
    raw_traces = []
    baseline_change_traces = []
    baselines = []
    baseline_durations = []
    response_starts = []
    response_ends = []
    response_speeds = []
    response_changes = []
    rejections = Counter()
    minimum_window = math.ceil(len(TIME_GRID) * MINIMUM_RUNNING_WINDOW_FRACTION)
    for onset, baseline_window, response_window in zip(
        onsets,
        baseline_windows,
        response_windows,
        strict=True,
    ):
        if baseline_window is None:
            rejections["no preceding within-block baseline"] += 1
            continue
        baseline_start, baseline_end = baseline_window
        baseline_duration = baseline_end - baseline_start
        baseline_values = signal_window_values(
            signal,
            baseline_start,
            baseline_end,
        )
        expected_baseline_samples = baseline_duration * signal["sample_rate_hz"]
        minimum_baseline_samples = max(
            2,
            math.ceil(expected_baseline_samples * MINIMUM_BASELINE_FRACTION),
        )
        if len(baseline_values) < minimum_baseline_samples:
            rejections["incomplete baseline"] += 1
            continue
        trace = interpolate_with_gap_limit(
            signal["timestamps"],
            signal["values"],
            onset + TIME_GRID,
        )
        if np.count_nonzero(np.isfinite(trace)) < minimum_window:
            rejections["incomplete event window"] += 1
            continue
        response_start, response_end = response_window
        response_values = signal_window_values(
            signal,
            response_start,
            response_end,
            include_end=True,
        )
        response_duration = response_end - response_start
        minimum_response_samples = max(
            2,
            math.ceil(
                response_duration
                * signal["sample_rate_hz"]
                * MINIMUM_RUNNING_WINDOW_FRACTION
            ),
        )
        if len(response_values) < minimum_response_samples:
            rejections["incomplete response window"] += 1
            continue
        baseline = float(np.mean(baseline_values))
        response_speed = float(np.mean(response_values))
        raw_traces.append(trace)
        baseline_change_traces.append(trace - baseline)
        baselines.append(baseline)
        baseline_durations.append(baseline_duration)
        response_starts.append(response_start - onset)
        response_ends.append(response_end - onset)
        response_speeds.append(response_speed)
        response_changes.append(response_speed - baseline)
    return summarize_running_trial_traces(
        raw_traces,
        baseline_change_traces,
        baselines,
        baseline_durations,
        response_starts,
        response_ends,
        response_speeds,
        response_changes,
        len(onsets),
        rejections,
    )


def extract_event(
    definition: EventDefinition,
    context: str,
    context_arrays: dict,
    control_arrays: dict,
    pupil: dict,
    running: dict | None,
) -> dict:
    conditions = {}
    running_conditions = {}
    for condition, arrays, control in (
        ("event", context_arrays, False),
        ("control", control_arrays, True),
    ):
        indices = selected_indices(arrays, definition, control=control)
        if not len(indices):
            raise SessionUnavailableError(
                f"{context} {definition.id} has no {condition} trials"
            )
        onsets = np.asarray(
            event_start_times(arrays["start"], indices),
            dtype=float,
        )
        baseline_windows = event_baseline_windows(
            arrays["start"],
            arrays["stop"],
            indices,
            context,
            arrays["block_number"],
        )
        response_windows = event_response_windows(
            arrays["start"],
            arrays["stop"],
            arrays["delay"],
            indices,
            context,
        )
        conditions[condition] = pupil_event_summary(
            pupil,
            onsets,
            baseline_windows,
            response_windows,
        )
        if running is not None:
            running_conditions[condition] = running_event_summary(
                running,
                onsets,
                baseline_windows,
                response_windows,
            )
    return {
        "alignment": "start_time",
        "conditions": conditions,
        "id": definition.id,
        "label": definition.label,
        "response_window_label": pupil_response_window_label(
            context,
            definition.id,
        ),
        "static_group": definition.static_group or definition.id,
        "running": running_conditions or None,
    }


def signal_metadata(signal: dict) -> dict:
    hidden = {"timestamps", "values"}
    return {
        **{
            key: (
                round(value, 6)
                if isinstance(value, float)
                else value
            )
            for key, value in signal.items()
            if key not in hidden
        },
    }


def extract_session(config: dict, asset: dict) -> dict:
    require_extraction_environment()
    source = source_asset_record(config, asset)
    with closing(remfile.File(source["download_url"])) as remote:
        with h5py.File(remote, "r") as nwb:
            if "intervals" not in nwb:
                raise SessionUnavailableError("NWB intervals group unavailable")
            intervals = nwb["intervals"]
            context_table_name = resolve_table(
                intervals,
                TABLE_CANDIDATES[config["context"]]["context"],
            )
            control_table_name = resolve_table(
                intervals,
                TABLE_CANDIDATES[config["context"]]["control"],
            )
            context_arrays = table_arrays(intervals[context_table_name])
            control_arrays = table_arrays(intervals[control_table_name])

            try:
                pupil = prepare_pupil(nwb)
            except SignalUnavailableError as exc:
                raise SessionUnavailableError(
                    f"processed pupil area unavailable ({exc})"
                ) from exc
            try:
                running = prepare_running(nwb)
                running_unavailable_reason = None
            except SignalUnavailableError as exc:
                running = None
                running_unavailable_reason = str(exc)

            events = [
                extract_event(
                    definition,
                    config["context"],
                    context_arrays,
                    control_arrays,
                    pupil,
                    running,
                )
                for definition in EVENT_DEFINITIONS[config["context"]]
            ]
    return {
        "cohort": config["cohort"],
        "context": config["context"],
        "context_table": context_table_name,
        "control_table": control_table_name,
        "date": config["date"],
        "events": events,
        "modality": config["modality"],
        "mouse_id": config["mouse_id"],
        "qc": config["qc"],
        "session_id": config["session_id"],
        "pupil": signal_metadata(pupil),
        "running": signal_metadata(running) if running is not None else None,
        "running_unavailable_reason": running_unavailable_reason,
        "source": source,
        "source_row": config["source_row"],
    }


def cached_session(
    config: dict,
    asset: dict,
    cache_dir: Path | None,
    signature: str,
) -> dict:
    cache_path = (
        cache_dir / "sessions" / f"{asset['asset_id']}.json"
        if cache_dir is not None
        else None
    )
    if cache_path is not None and cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if (
            cached.get("cache_version") == CACHE_VERSION
            and cached.get("asset_modified") == asset["modified"]
            and (
                cached.get("analysis_signature") == signature
                or cached.get("analysis_signature") in COMPATIBLE_CACHE_SIGNATURES
            )
        ):
            session = cached["session"]
            needs_running_retry = (
                session.get("running_unavailable_reason")
                == "finite running-speed timestamps are not strictly increasing"
            )
            if cached.get("analysis_signature") != signature and not needs_running_retry:
                if session.get("running") is not None:
                    session["running"].setdefault(
                        "discarded_nonincreasing_sample_count",
                        0,
                    )
                cached["analysis_signature"] = signature
                cache_path.write_text(
                    json.dumps(cached, ensure_ascii=True, sort_keys=True) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                return session
            if not needs_running_retry:
                return session
    session = extract_session(config, asset)
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "analysis_signature": signature,
                    "asset_modified": asset["modified"],
                    "cache_version": CACHE_VERSION,
                    "session": session,
                },
                ensure_ascii=True,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return session


def average_numbers(values: list[float | None]) -> float | None:
    finite = [
        float(value)
        for value in values
        if value is not None and math.isfinite(value)
    ]
    return sum(finite) / len(finite) if finite else None


def averaged_pupil(records: list[dict], condition: str) -> dict | None:
    values = [
        record["conditions"][condition]
        for record in records
        if record["conditions"][condition]["valid_trials"] > 0
    ]
    if not values:
        return None
    percent_change_mean, percent_change_std = combine_mean_and_std_traces(
        [record["percent_change_mean_trace"] for record in values],
        [record["percent_change_std_trace"] for record in values],
    )
    raw_mean, raw_std = combine_mean_and_std_traces(
        [record["raw_mean_trace"] for record in values],
        [record["raw_std_trace"] for record in values],
    )
    response_mean, response_std = combine_mean_and_std_traces(
        [[record["response_percent_change_mean"]] for record in values],
        [[record["response_percent_change_std"]] for record in values],
    )
    rejections = Counter()
    for record in values:
        rejections.update(record["rejections"])
    return {
        "available_trials": sum(record["available_trials"] for record in values),
        "baseline_duration_mean_seconds": average_numbers(
            [record["baseline_duration_mean_seconds"] for record in values]
        ),
        "baseline_mean_px2": average_numbers(
            [record["baseline_mean_px2"] for record in values]
        ),
        "percent_change_mean_trace": percent_change_mean,
        "percent_change_std_trace": percent_change_std,
        "raw_mean_trace": raw_mean,
        "raw_std_trace": raw_std,
        "rejections": dict(sorted(rejections.items())),
        "response_percent_change_mean": response_mean[0],
        "response_percent_change_std": response_std[0],
        "response_start_mean_seconds": average_numbers(
            [record["response_start_mean_seconds"] for record in values]
        ),
        "response_end_mean_seconds": average_numbers(
            [record["response_end_mean_seconds"] for record in values]
        ),
        "session_count": len(values),
        "valid_trials": sum(record["valid_trials"] for record in values),
    }


def averaged_running(records: list[dict], condition: str) -> dict | None:
    values = [
        record["running"][condition]
        for record in records
        if record["running"] is not None
        and record["running"][condition]["valid_trials"] > 0
    ]
    if not values:
        return None
    baseline_change_mean, baseline_change_std = combine_mean_and_std_traces(
        [record["baseline_change_mean_trace"] for record in values],
        [record["baseline_change_std_trace"] for record in values],
    )
    raw_mean, raw_std = combine_mean_and_std_traces(
        [record["raw_mean_trace"] for record in values],
        [record["raw_std_trace"] for record in values],
    )
    response_mean, response_std = combine_mean_and_std_traces(
        [[record["response_mean_cm_s"]] for record in values],
        [[record["response_std_cm_s"]] for record in values],
    )
    response_change_mean, response_change_std = combine_mean_and_std_traces(
        [[record["response_change_mean_cm_s"]] for record in values],
        [[record["response_change_std_cm_s"]] for record in values],
    )
    rejections = Counter()
    for record in values:
        rejections.update(record["rejections"])
    return {
        "available_trials": sum(record["available_trials"] for record in values),
        "baseline_change_mean_trace": baseline_change_mean,
        "baseline_change_std_trace": baseline_change_std,
        "baseline_duration_mean_seconds": average_numbers(
            [record["baseline_duration_mean_seconds"] for record in values]
        ),
        "baseline_mean_cm_s": average_numbers(
            [record["baseline_mean_cm_s"] for record in values]
        ),
        "raw_mean_trace": raw_mean,
        "raw_std_trace": raw_std,
        "rejections": dict(sorted(rejections.items())),
        "response_change_mean_cm_s": response_change_mean[0],
        "response_change_std_cm_s": response_change_std[0],
        "response_end_mean_seconds": average_numbers(
            [record["response_end_mean_seconds"] for record in values]
        ),
        "response_mean_cm_s": response_mean[0],
        "response_start_mean_seconds": average_numbers(
            [record["response_start_mean_seconds"] for record in values]
        ),
        "response_std_cm_s": response_std[0],
        "session_count": len(values),
        "valid_trials": sum(record["valid_trials"] for record in values),
    }


def build_mouse_records(sessions: list[dict]) -> list[dict]:
    grouped = defaultdict(list)
    for session in sessions:
        grouped[
            (
                session["modality"],
                session["cohort"],
                session["context"],
                session["mouse_id"],
            )
        ].append(session)
    mouse_records = []
    for (modality, cohort, context, mouse_id), records in sorted(
        grouped.items(),
        key=lambda item: (
            MODALITY_ORDER[item[0][0]],
            item[0][1],
            CONTEXT_ORDER[item[0][2]],
            item[0][3],
        ),
    ):
        events = []
        for definition in EVENT_DEFINITIONS[context]:
            session_events = [
                next(event for event in record["events"] if event["id"] == definition.id)
                for record in records
            ]
            paired_session_events = [
                event
                for event in session_events
                if event["conditions"]["event"]["valid_trials"] > 0
                and event["conditions"]["control"]["valid_trials"] > 0
            ]
            event_pupil = averaged_pupil(paired_session_events, "event")
            control_pupil = averaged_pupil(paired_session_events, "control")
            pupil = None
            if event_pupil is not None and control_pupil is not None:
                pupil = {
                    "control": control_pupil,
                    "event": event_pupil,
                    "percent_change_difference_trace": subtract_traces(
                        event_pupil["percent_change_mean_trace"],
                        control_pupil["percent_change_mean_trace"],
                    ),
                    "response_percent_change_difference": (
                        float(event_pupil["response_percent_change_mean"])
                        - float(control_pupil["response_percent_change_mean"])
                    ),
                    "response_percent_change_difference_std": math.sqrt(
                        float(event_pupil["response_percent_change_std"]) ** 2
                        + float(control_pupil["response_percent_change_std"]) ** 2
                    ),
                }
            paired_running_events = [
                event
                for event in session_events
                if event["running"] is not None
                and event["running"]["event"]["valid_trials"] > 0
                and event["running"]["control"]["valid_trials"] > 0
            ]
            event_running = averaged_running(paired_running_events, "event")
            control_running = averaged_running(paired_running_events, "control")
            running = None
            if event_running is not None and control_running is not None:
                running = {
                    "baseline_change_difference_trace": subtract_traces(
                        event_running["baseline_change_mean_trace"],
                        control_running["baseline_change_mean_trace"],
                    ),
                    "control": control_running,
                    "event": event_running,
                    "response_change_difference_cm_s": (
                        float(event_running["response_change_mean_cm_s"])
                        - float(control_running["response_change_mean_cm_s"])
                    ),
                    "response_change_difference_std_cm_s": math.sqrt(
                        float(event_running["response_change_std_cm_s"]) ** 2
                        + float(control_running["response_change_std_cm_s"]) ** 2
                    ),
                }
            events.append(
                {
                    "id": definition.id,
                    "label": definition.label,
                    "pupil": pupil,
                    "response_window_label": pupil_response_window_label(
                        context,
                        definition.id,
                    ),
                    "static_group": definition.static_group or definition.id,
                    "running": running,
                }
            )
        mouse_records.append(
            {
                "cohort": cohort,
                "context": context,
                "events": events,
                "modality": modality,
                "mouse_id": mouse_id,
                "running_source_session_count": sum(
                    record["running"] is not None for record in records
                ),
                "session_count": len(records),
                "source_session_ids": sorted(
                    record["session_id"] for record in records
                ),
            }
        )
    return mouse_records


def stable_seed(key: str) -> int:
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big")


def trace_matrix(traces: list[list[float | None]]) -> np.ndarray:
    return np.asarray(
        [
            [np.nan if value is None else float(value) for value in trace]
            for trace in traces
        ],
        dtype=float,
    )


def bootstrap_trace(
    traces: list[list[float | None]],
    key: str,
    resamples: int,
) -> dict:
    matrix = trace_matrix(traces)
    counts = np.sum(np.isfinite(matrix), axis=0)
    mean = np.divide(
        np.nansum(matrix, axis=0),
        counts,
        out=np.full(matrix.shape[1], np.nan),
        where=counts > 0,
    )
    if len(matrix) == 1:
        lower = upper = mean
    else:
        rng = np.random.default_rng(stable_seed(key))
        indices = rng.integers(0, len(matrix), size=(resamples, len(matrix)))
        sampled = matrix[indices]
        sampled_counts = np.sum(np.isfinite(sampled), axis=1)
        bootstrap_means = np.divide(
            np.nansum(sampled, axis=1),
            sampled_counts,
            out=np.full((resamples, matrix.shape[1]), np.nan),
            where=sampled_counts > 0,
        )
        lower, upper = np.nanquantile(bootstrap_means, [0.025, 0.975], axis=0)
    return {
        "lower": rounded_optional_trace(lower),
        "mean": rounded_optional_trace(mean),
        "upper": rounded_optional_trace(upper),
    }


def bootstrap_scalar(values: list[float], key: str, resamples: int) -> dict:
    array = np.asarray(values, dtype=float)
    mean = float(np.mean(array))
    if len(array) == 1:
        lower = upper = mean
    else:
        rng = np.random.default_rng(stable_seed(key))
        indices = rng.integers(0, len(array), size=(resamples, len(array)))
        bootstrap_means = np.mean(array[indices], axis=1)
        lower, upper = np.quantile(bootstrap_means, [0.025, 0.975])
    return {
        "lower": round(float(lower), 5),
        "mean": round(mean, 5),
        "upper": round(float(upper), 5),
    }


def build_summaries(mouse_records: list[dict], resamples: int) -> list[dict]:
    grouped = defaultdict(list)
    for mouse in mouse_records:
        for event in mouse["events"]:
            grouped[
                (
                    mouse["modality"],
                    mouse["cohort"],
                    mouse["context"],
                    event["id"],
                )
            ].append((mouse, event))
    summaries = []
    for (modality, cohort, context, event_id), records in sorted(
        grouped.items(),
        key=lambda item: (
            MODALITY_ORDER[item[0][0]],
            item[0][1],
            CONTEXT_ORDER[item[0][2]],
            [
                definition.id for definition in EVENT_DEFINITIONS[item[0][2]]
            ].index(item[0][3]),
        ),
    ):
        definition = next(
            candidate
            for candidate in EVENT_DEFINITIONS[context]
            if candidate.id == event_id
        )
        valid = [
            (mouse, event["pupil"])
            for mouse, event in records
            if event["pupil"] is not None
        ]
        pupil_key = f"{modality}:{cohort}:{context}:{event_id}:pupil"
        response_points = [
            {
                "mouse_id": mouse["mouse_id"],
                "value": round(
                    float(pupil["response_percent_change_difference"]),
                    5,
                ),
            }
            for mouse, pupil in valid
        ]
        pupil = None
        if valid:
            pupil = {
                "control_percent_change_trace": bootstrap_trace(
                    [
                        pupil_record["control"]["percent_change_mean_trace"]
                        for _, pupil_record in valid
                    ],
                    f"{pupil_key}:control",
                    resamples,
                ),
                "difference_percent_change_trace": bootstrap_trace(
                    [
                        pupil_record["percent_change_difference_trace"]
                        for _, pupil_record in valid
                    ],
                    f"{pupil_key}:difference",
                    resamples,
                ),
                "event_percent_change_trace": bootstrap_trace(
                    [
                        pupil_record["event"]["percent_change_mean_trace"]
                        for _, pupil_record in valid
                    ],
                    f"{pupil_key}:event",
                    resamples,
                ),
                "mouse_count": len(valid),
                "response_percent_change": {
                    **bootstrap_scalar(
                        [point["value"] for point in response_points],
                        f"{pupil_key}:response",
                        resamples,
                    ),
                    "points": response_points,
                },
            }
        valid_running = [
            (mouse, event["running"])
            for mouse, event in records
            if event["running"] is not None
        ]
        running_key = f"{modality}:{cohort}:{context}:{event_id}:running"
        running_response_points = [
            {
                "mouse_id": mouse["mouse_id"],
                "value": round(
                    float(running["response_change_difference_cm_s"]),
                    5,
                ),
            }
            for mouse, running in valid_running
        ]
        running = None
        if valid_running:
            running = {
                "control_baseline_change_trace": bootstrap_trace(
                    [
                        running_record["control"]["baseline_change_mean_trace"]
                        for _, running_record in valid_running
                    ],
                    f"{running_key}:control",
                    resamples,
                ),
                "difference_baseline_change_trace": bootstrap_trace(
                    [
                        running_record["baseline_change_difference_trace"]
                        for _, running_record in valid_running
                    ],
                    f"{running_key}:difference",
                    resamples,
                ),
                "event_baseline_change_trace": bootstrap_trace(
                    [
                        running_record["event"]["baseline_change_mean_trace"]
                        for _, running_record in valid_running
                    ],
                    f"{running_key}:event",
                    resamples,
                ),
                "mouse_count": len(valid_running),
                "response_change_cm_s": {
                    **bootstrap_scalar(
                        [point["value"] for point in running_response_points],
                        f"{running_key}:response",
                        resamples,
                    ),
                    "points": running_response_points,
                },
            }
        summaries.append(
            {
                "cohort": cohort,
                "context": context,
                "event_id": event_id,
                "label": definition.label,
                "modality": modality,
                "pupil": pupil,
                "response_window_label": pupil_response_window_label(
                    context,
                    event_id,
                ),
                "static_group": definition.static_group or definition.id,
                "running": running,
            }
        )
    return summaries


def coverage_records(sessions: list[dict], exclusions: list[dict]) -> list[dict]:
    included = Counter(
        (record["modality"], record["cohort"], record["context"])
        for record in sessions
    )
    excluded = Counter(
        (record["modality"], record["cohort"], record["context"])
        for record in exclusions
    )
    running_included = Counter(
        (record["modality"], record["cohort"], record["context"])
        for record in sessions
        if record["running"] is not None
    )
    running_unavailable = Counter(
        (record["modality"], record["cohort"], record["context"])
        for record in sessions
        if record["running"] is None
    )
    keys = sorted(
        set(included) | set(excluded),
        key=lambda key: (
            MODALITY_ORDER[key[0]],
            key[1],
            CONTEXT_ORDER[key[2]],
        ),
    )
    return [
        {
            "cohort": cohort,
            "context": context,
            "excluded_sessions": excluded[(modality, cohort, context)],
            "included_sessions": included[(modality, cohort, context)],
            "modality": modality,
            "running_sessions": running_included[(modality, cohort, context)],
            "running_unavailable_sessions": running_unavailable[
                (modality, cohort, context)
            ],
        }
        for modality, cohort, context in keys
    ]


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    args = parse_args()
    if args.max_workers < 1:
        raise SystemExit("--max-workers must be at least one.")
    if args.bootstrap_resamples < 100:
        raise SystemExit("--bootstrap-resamples must be at least 100.")
    dt.date.fromisoformat(args.retrieved_date)
    require_extraction_environment()

    configs, source_snapshots = load_session_configs()
    selected_modalities = set(args.modality or ())
    selected_sessions = {
        normalized_session_id(session_id) for session_id in (args.session_id or ())
    }
    if selected_modalities:
        configs = [
            config for config in configs if config["modality"] in selected_modalities
        ]
    if selected_sessions:
        configs = [
            config for config in configs if config["session_id"] in selected_sessions
        ]
    if not configs:
        raise SystemExit("No publication sessions matched the requested filters.")

    assets_by_dandiset, manifests = load_dandi_assets(
        {config["dandiset_id"] for config in configs}
    )
    jobs = []
    for config in configs:
        asset = assets_by_dandiset[config["dandiset_id"]].get(
            config["dandi_path"]
        )
        if asset is None:
            raise RuntimeError(
                f"DANDI path is unavailable in the pinned draft: {config['dandi_path']}"
            )
        jobs.append((config, asset))

    signature = analysis_signature(args.bootstrap_resamples)
    sessions = []
    exclusions = []
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        future_jobs = {
            executor.submit(
                cached_session,
                config,
                asset,
                args.cache_dir,
                signature,
            ): (config, asset)
            for config, asset in jobs
        }
        for future in as_completed(future_jobs):
            config, asset = future_jobs[future]
            try:
                session = future.result()
            except SessionUnavailableError as exc:
                exclusions.append(
                    {
                        "asset_id": asset["asset_id"],
                        "cohort": config["cohort"],
                        "context": config["context"],
                        "modality": config["modality"],
                        "mouse_id": config["mouse_id"],
                        "reason": str(exc),
                        "session_id": config["session_id"],
                    }
                )
                print(
                    f"excluded {config['modality']}: {config['session_id']} ({exc})",
                    flush=True,
                )
                continue
            sessions.append(session)
            print(
                f"extracted {config['modality']}: {config['session_id']}",
                flush=True,
            )
    sessions.sort(
        key=lambda record: (
            MODALITY_ORDER[record["modality"]],
            record["cohort"],
            CONTEXT_ORDER[record["context"]],
            record["mouse_id"],
            record["date"],
            record["session_id"],
        )
    )
    exclusions.sort(
        key=lambda record: (
            MODALITY_ORDER[record["modality"]],
            record["cohort"],
            CONTEXT_ORDER[record["context"]],
            record["mouse_id"],
            record["session_id"],
        )
    )
    mouse_records = build_mouse_records(sessions)
    summaries = build_summaries(mouse_records, args.bootstrap_resamples)
    running_exclusions = [
        {
            "cohort": session["cohort"],
            "context": session["context"],
            "modality": session["modality"],
            "mouse_id": session["mouse_id"],
            "reason": session["running_unavailable_reason"],
            "session_id": session["session_id"],
        }
        for session in sessions
        if session["running"] is None
    ]
    payload = {
        "analysis_parameters": analysis_parameters(args.bootstrap_resamples),
        "coverage": coverage_records(sessions, exclusions),
        "exclusions": exclusions,
        "mice": mouse_records,
        "running_exclusions": running_exclusions,
        "sessions": sessions,
        "summaries": summaries,
        "version": EXTRACTION_VERSION,
    }
    write_json(args.output, payload)
    provenance = {
        "analysis_module": {
            "path": "src/openscope_p3_publication/pupil_responses.py",
            "sha256": file_sha256(
                REPO_ROOT
                / "src"
                / "openscope_p3_publication"
                / "pupil_responses.py"
            ),
        },
        "analysis_signature": signature,
        "dandisets": manifests,
        "exclusion_count": len(exclusions),
        "mouse_record_count": len(mouse_records),
        "output_path": str(args.output.resolve().relative_to(REPO_ROOT.resolve()))
        if args.output.resolve().is_relative_to(REPO_ROOT.resolve())
        else str(args.output),
        "output_sha256": file_sha256(args.output),
        "retrieved_date": args.retrieved_date,
        "running_exclusion_count": len(running_exclusions),
        "script": {
            "path": "scripts/extract_pupil_event_responses.py",
            "sha256": file_sha256(Path(__file__)),
        },
        "session_count": len(sessions),
        "source_snapshots": source_snapshots,
        "summary_count": len(summaries),
        "version": EXTRACTION_VERSION,
    }
    write_json(args.provenance_output, provenance)
    print(f"Wrote {args.output}")
    print(f"Wrote {args.provenance_output}")


if __name__ == "__main__":
    main()
