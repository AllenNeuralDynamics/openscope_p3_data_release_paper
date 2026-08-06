#!/usr/bin/env python3
"""Extract synchronized eye-tracking excerpts from representative public NWBs."""

from __future__ import annotations

import argparse
import io
import json
from contextlib import closing
from pathlib import Path

try:
    import h5py
    import numpy as np
    import remfile
except ImportError as exc:  # pragma: no cover - optional extraction environment
    raise SystemExit(
        "Run with: uv run --with h5py --with harp-python --with numpy --with remfile "
        "python scripts/extract_eye_tracking_excerpts.py"
    ) from exc

from extract_behavior_excerpts import (
    EVENT_LEAD_SECONDS,
    EXCERPT_DURATION_SECONDS,
    S3_ROOT,
    decode,
    fetch_bytes,
    lost_frame_indices,
    mvr_time_map,
    nwb_stimulus_rows,
    orientation_degrees,
    rising_edges,
    source_record,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "figure_sources" / "data" / "eye-tracking-excerpts.json"
FIT_SOURCES = (
    ("pupil", "Pupil"),
    ("corneal_reflection", "Corneal reflection"),
    ("ellipse", "Eye ellipse"),
)
STANDARD_SESSIONS = (
    {
        "asset_id": "f7057120-fc07-447c-80ba-bbbc425072b0",
        "asset_path": (
            "sub-820454/sub-820454_ses-ecephys-820454-2025-11-05-15-21-15_ecephys.nwb"
        ),
        "asset_size": 14_443_031_618,
        "camera": ("1473894652_820454_20251105.eye", "eye_cam_exposing"),
        "context": "Standard oddball",
        "dandi_url": "https://dandiarchive.org/dandiset/001637/draft/files",
        "frame_size": (658, 492),
        "id": "neuropixels",
        "label": "Neuropixels",
        "nwb_url": (
            "https://api.dandiarchive.org/api/assets/"
            "f7057120-fc07-447c-80ba-bbbc425072b0/download/"
        ),
        "selected_trial": 863,
        "session": "ecephys_820454_2025-11-05_15-21-15",
        "subject": "820454",
        "sync_url": (
            f"{S3_ROOT}/ecephys_820454_2025-11-05_15-21-15/behavior/"
            "1473894652_820454_20251105.sync"
        ),
        "table": "Standard mismatch block_presentations",
    },
    {
        "asset_id": "8b7e9f4a-2544-4c47-b1a9-e65cb58e62cd",
        "asset_path": (
            "sub-832700/sub-832700_ses-multiplane-ophys-832700-"
            "2026-01-30-09-32-25_ophys.nwb"
        ),
        "asset_size": 4_617_518_378,
        "camera": ("1489257941_Eye_20260130T093157", "eye_cam_exposing"),
        "context": "Standard oddball",
        "dandi_url": "https://dandiarchive.org/dandiset/001768/draft/files",
        "frame_size": (658, 492),
        "id": "mesoscope",
        "label": "Mesoscope",
        "nwb_url": (
            "https://api.dandiarchive.org/api/assets/"
            "8b7e9f4a-2544-4c47-b1a9-e65cb58e62cd/download/"
        ),
        "selected_trial": 1535,
        "session": "multiplane-ophys_832700_2026-01-30_09-32-25",
        "subject": "832700",
        "sync_url": (
            f"{S3_ROOT}/multiplane-ophys_832700_2026-01-30_09-32-25/behavior/"
            "1489257941_sync.h5"
        ),
        "table": "Standard mismatch block_presentations",
    },
    {
        "asset_id": "e36d24b2-ee5d-44d4-8119-b4f3f53e80d1",
        "asset_path": (
            "sub-829704/sub-829704_ses-829704-2025-12-11-12-57-26_image+ophys.nwb"
        ),
        "asset_size": 2_151_916_401,
        "context": "Standard oddball",
        "dandi_url": "https://dandiarchive.org/dandiset/001424/draft/files",
        "frame_size": (728, 544),
        "id": "slap2",
        "label": "SLAP2",
        "nwb_url": (
            "https://api.dandiarchive.org/api/assets/"
            "e36d24b2-ee5d-44d4-8119-b4f3f53e80d1/download/"
        ),
        "selected_trial": 1354,
        "session": "829704_2025-12-11_12-57-26",
        "subject": "829704",
        "table": "standard_oddball",
    },
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def eye_camera(config: dict, excerpt_start: float) -> tuple[dict, list[dict]]:
    stem, sync_line = config["camera"]
    base = f"{S3_ROOT}/{config['session']}/behavior-videos"
    report_url = f"{base}/{stem}.json"
    video_url = f"{base}/{stem}.mp4"
    sync_bytes = fetch_bytes(config["sync_url"])
    report_bytes = fetch_bytes(report_url)
    report = json.loads(report_bytes)["RecordingReport"]
    report_size = tuple(int(value) for value in report["ImageDimensions"].split("x"))
    if report_size != config["frame_size"]:
        raise RuntimeError(f"Eye-camera dimensions changed: {config['id']}")
    with h5py.File(io.BytesIO(sync_bytes), mode="r") as sync_file:
        frame_times, sample_rate = rising_edges(sync_file, sync_line)
    lost = lost_frame_indices(report)
    camera = {
        "id": "eye",
        "label": "Eye",
        "timeMap": mvr_time_map(frame_times, report, excerpt_start),
        "timing": {
            "clock": "NI-DAQ sync",
            "clockRateHz": sample_rate,
            "encodedRateHz": 60.0,
            "leadingMetadataFrames": 1,
            "reportedDroppedFrames": len(lost),
            "frameHeight": report_size[1],
            "frameWidth": report_size[0],
            "syncLine": sync_line,
        },
        "url": video_url,
    }
    return camera, [
        source_record(video_url),
        source_record(report_url, report_bytes),
        source_record(config["sync_url"], sync_bytes),
    ]


def slap2_camera(
    group: h5py.Group,
    config: dict,
    excerpt_start: float,
) -> tuple[dict, list[dict]]:
    timestamps = np.asarray(group["pupil/timestamps"][:], dtype=float)
    frames = np.asarray(group["pupil/frame"][:], dtype=int)
    first = max(0, int(np.searchsorted(timestamps, excerpt_start)) - 2)
    last = min(
        len(timestamps),
        int(np.searchsorted(timestamps, excerpt_start + EXCERPT_DURATION_SECONDS)) + 2,
    )
    time_map = [
        [
            round(float(timestamps[index] - excerpt_start), 6),
            round(float(frames[index] / 30), 6),
        ]
        for index in range(first, last)
    ]
    if any(
        current[0] <= previous[0] or current[1] <= previous[1]
        for previous, current in zip(time_map[:-1], time_map[1:], strict=True)
    ):
        raise RuntimeError("SLAP2 eye timestamps or frame indices are not monotonic.")
    base = f"{S3_ROOT}/{config['session']}/behavior-videos/EyeCamera"
    metadata_url = f"{base}/metadata.csv"
    video_url = f"{base}/video.mp4"
    metadata_bytes = fetch_bytes(metadata_url)
    camera = {
        "id": "eye",
        "label": "Eye",
        "timeMap": time_map,
        "timing": {
            "clock": "Harp CameraFrameTime",
            "encodedRateHz": 30.0,
            "frameIndexSource": "processing/eye_tracking/pupil/frame",
            "frameHeight": config["frame_size"][1],
            "frameWidth": config["frame_size"][0],
        },
        "url": video_url,
    }
    return camera, [
        source_record(video_url),
        source_record(metadata_url, metadata_bytes),
    ]


def slap2_stimulus_rows(table: h5py.Group, excerpt_start: float) -> list[dict]:
    starts = np.asarray(table["start_time"][:], dtype=float)
    stops = np.asarray(table["stop_time"][:], dtype=float)
    mask = (starts < excerpt_start + EXCERPT_DURATION_SECONDS) & (stops >= excerpt_start)
    rows = []
    for index in np.flatnonzero(mask):
        phase = float(decode(table["Phase"][index]))
        rows.append(
            {
                "contrast": round(float(decode(table["Contrast"][index])), 4),
                "end": round(float(stops[index] - excerpt_start), 6),
                "orientationDegrees": round(
                    orientation_degrees(float(decode(table["Orientation"][index]))),
                    3,
                ),
                "phaseCycles": round(phase / (2 * np.pi), 6),
                "spatialFrequency": round(
                    float(decode(table["SpatialFrequency"][index])), 4
                ),
                "start": round(float(starts[index] - excerpt_start), 6),
                "temporalFrequency": round(
                    float(decode(table["TemporalFrequency"][index])), 4
                ),
                "trialNumber": int(float(decode(table["TrialNumber"][index]))),
                "trialType": str(decode(table["TrialType"][index])),
            }
        )
    return rows


def fit_samples(
    group: h5py.Group,
    fit_id: str,
    excerpt_start: float,
) -> list[list[float | bool]]:
    timestamps = np.asarray(group[f"{fit_id}/timestamps"][:], dtype=float)
    first, last = np.searchsorted(
        timestamps,
        [excerpt_start, excerpt_start + EXCERPT_DURATION_SECONDS],
    )
    fields = {
        name: np.asarray(group[f"{fit_id}/{name}"][first:last], dtype=float)
        for name in ("data_x", "data_y", "width", "height", "area")
    }
    blink_timestamps = np.asarray(group["likely_blink_times/timestamps"][:], dtype=float)
    blink_values = np.asarray(group["likely_blink_times/data"][:], dtype=bool)
    if not np.array_equal(timestamps, blink_timestamps):
        raise RuntimeError(f"{fit_id} and blink timestamps do not share one sample clock.")
    samples = []
    for index, timestamp in enumerate(timestamps[first:last]):
        values = [fields[name][index] for name in fields]
        if not all(np.isfinite(value) for value in values):
            continue
        samples.append(
            [
                round(float(timestamp - excerpt_start), 6),
                *(round(float(value), 4) for value in values),
                bool(blink_values[first + index]),
            ]
        )
    return samples


def fit_field_reference(group: h5py.Group, fit_id: str, config: dict) -> dict:
    width, height = config["frame_size"]
    x_values = np.asarray(group[f"{fit_id}/data_x"][:], dtype=float)
    y_values = np.asarray(group[f"{fit_id}/data_y"][:], dtype=float)
    areas = np.asarray(group[f"{fit_id}/area"][:], dtype=float)
    blinks = np.asarray(group["likely_blink_times/data"][:], dtype=bool)
    valid = (
        np.isfinite(x_values)
        & np.isfinite(y_values)
        & np.isfinite(areas)
        & ~blinks
        & (x_values >= 0)
        & (x_values < width)
        & (y_values >= 0)
        & (y_values < height)
        & (areas > 0)
    )
    if np.count_nonzero(valid) < 100:
        raise RuntimeError(f"Too few valid full-session {fit_id} fits: {config['id']}")
    area_low, area_high = np.quantile(areas[valid], [0.05, 0.95])
    return {
        "areaHigh": round(float(area_high), 4),
        "areaLow": round(float(area_low), 4),
        "frameHeight": height,
        "frameWidth": width,
        "medianX": round(float(np.median(x_values[valid])), 4),
        "medianY": round(float(np.median(y_values[valid])), 4),
        "totalSamples": int(len(x_values)),
        "validNonblinkSamples": int(np.count_nonzero(valid)),
    }


def extract_session(config: dict) -> dict:
    selected_trial = config["selected_trial"]
    with closing(remfile.File(config["nwb_url"])) as remote:
        with h5py.File(remote, mode="r") as nwb:
            table = nwb[f"intervals/{config['table']}"]
            trial_numbers = np.asarray(
                [int(float(decode(value))) for value in table["TrialNumber"][:]],
                dtype=int,
            )
            matches = np.flatnonzero(trial_numbers == selected_trial)
            if len(matches) != 1:
                raise RuntimeError(
                    f"Expected one row for {config['id']} trial {selected_trial}."
                )
            selected_index = int(matches[0])
            event_time = float(table["start_time"][selected_index])
            excerpt_start = event_time - EVENT_LEAD_SECONDS
            eye_tracking = nwb["processing/eye_tracking"]
            fits = {
                fit_id: {
                    "fieldReference": fit_field_reference(
                        eye_tracking,
                        fit_id,
                        config,
                    ),
                    "label": label,
                    "sampleFields": [
                        "time",
                        "x",
                        "y",
                        "width",
                        "height",
                        "area",
                        "blink",
                    ],
                    "samples": fit_samples(eye_tracking, fit_id, excerpt_start),
                }
                for fit_id, label in FIT_SOURCES
            }
            if config["id"] == "slap2":
                stimulus = slap2_stimulus_rows(table, excerpt_start)
                camera, camera_sources = slap2_camera(
                    eye_tracking,
                    config,
                    excerpt_start,
                )
            else:
                stimulus, _ = nwb_stimulus_rows(table, excerpt_start)
                camera, camera_sources = eye_camera(config, excerpt_start)
    for fit_id, fit in fits.items():
        samples = fit["samples"]
        blink_count = sum(sample[-1] for sample in samples)
        if (
            not samples
            or samples[0][0] > 0.04
            or samples[-1][0] < 15.95
            or not blink_count
        ):
            raise RuntimeError(
                f"{fit_id} excerpt is incomplete or lacks a blink: {config['id']}"
            )
    return {
        "alignment": (
            "Processed eye fits, likely-blink flags, stimulus rows, and eye-camera frames "
            "share the packaged acquisition clock. Neuropixels and mesoscope use 100 kHz "
            "sync edges; SLAP2 uses aligned Harp timestamps and packaged camera-frame indices."
        ),
        "camera": camera,
        "context": config["context"],
        "event": {
            "label": "90 degree orientation deviant",
            "time": EVENT_LEAD_SECONDS,
            "trialNumber": selected_trial,
        },
        "fits": fits,
        "id": config["id"],
        "label": config["label"],
        "session": config["session"],
        "sourceLinks": [
            {"label": "DANDI", "url": config["dandi_url"]},
            {
                "label": "Raw S3 session",
                "url": (
                    "https://open.quiltdata.com/b/aind-open-data/tree/"
                    f"{config['session']}/"
                ),
            },
        ],
        "sources": [
            {
                "asset_id": config["asset_id"],
                "path": config["asset_path"],
                "size": config["asset_size"],
                "url": config["nwb_url"],
            },
            *camera_sources,
        ],
        "stimulus": stimulus,
        "subject": config["subject"],
    }


def main() -> None:
    args = parse_args()
    payload = {
        "durationSeconds": EXCERPT_DURATION_SECONDS,
        "retrievedDate": "2026-08-05",
        "sessions": [extract_session(config) for config in STANDARD_SESSIONS],
        "version": 2,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()