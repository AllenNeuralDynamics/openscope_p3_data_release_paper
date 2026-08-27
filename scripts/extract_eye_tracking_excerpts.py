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
        "asset_id": "a7f50043-8883-4c0e-a956-2ff3e0f1b0ef",
        "asset_path": (
            "sub-834687/sub-834687_ses-ecephys-834687-2026-03-18-15-50-10_ecephys.nwb"
        ),
        "asset_size": 12_819_445_281,
        "camera": ("1499077798_834687_20260318.eye", "eye_cam_exposing"),
        "context": "Neuropixels example",
        "dandi_url": "https://dandiarchive.org/dandiset/001637/draft/files",
        "frame_size": (658, 492),
        "id": "neuropixels",
        "label": "Neuropixels",
        "nwb_url": (
            "https://api.dandiarchive.org/api/assets/"
            "a7f50043-8883-4c0e-a956-2ff3e0f1b0ef/download/"
        ),
        "session": "ecephys_834687_2026-03-18_15-50-10",
        "subject": "834687",
        "sync_url": (
            f"{S3_ROOT}/ecephys_834687_2026-03-18_15-50-10/behavior/"
            "1499077798_834687_20260318.sync"
        ),
        "window_start": 3570.52535,
    },
    {
        "asset_id": "b980f6a1-0c34-4f2b-ba4e-72b2563e42de",
        "asset_path": (
            "sub-839909/sub-839909_ses-multiplane-ophys-839909-"
            "2026-02-26-15-11-01_ophys.nwb"
        ),
        "asset_size": 4_086_984_781,
        "camera": ("1772143800_Eye_20260226T151022", "eye_cam_exposing"),
        "context": "Mesoscope example",
        "dandi_url": "https://dandiarchive.org/dandiset/001768/draft/files",
        "frame_size": (658, 492),
        "id": "mesoscope",
        "label": "Mesoscope",
        "nwb_url": (
            "https://api.dandiarchive.org/api/assets/"
            "b980f6a1-0c34-4f2b-ba4e-72b2563e42de/download/"
        ),
        "session": "multiplane-ophys_839909_2026-02-26_15-11-01",
        "subject": "839909",
        "sync_url": (
            f"{S3_ROOT}/multiplane-ophys_839909_2026-02-26_15-11-01/behavior/"
            "1772143800_sync.h5"
        ),
        "window_start": 2109.061245,
    },
    {
        "asset_id": "e03a3c9e-1699-4742-b352-7385c3a90610",
        "asset_path": (
            "sub-828409/sub-828409_ses-828409-2025-11-21-11-14-03_image+ophys.nwb"
        ),
        "asset_size": 2_831_214_109,
        "context": "SLAP2 example",
        "dandi_url": "https://dandiarchive.org/dandiset/001424/draft/files",
        "frame_size": (728, 544),
        "id": "slap2",
        "label": "SLAP2",
        "nwb_url": (
            "https://api.dandiarchive.org/api/assets/"
            "e03a3c9e-1699-4742-b352-7385c3a90610/download/"
        ),
        "platform": "slap2",
        "session": "828409_2025-11-21_11-14-03",
        "subject": "828409",
        "window_start": 728.582976,
    },
)

NEUROPIXELS_CANDIDATES = (
    {
        "asset_id": "fbfc5171-af65-408e-bfec-d72d9f7f0c4a",
        "asset_path": "sub-848390/sub-848390_ses-ecephys-848390-2026-05-06-09-54-56_ecephys.nwb",
        "asset_size": 13_309_249_183,
        "camera": ("1508786295_848390_20260506.eye", "eye_cam_exposing"),
        "id": "neuropixels-candidate-1",
        "label": "Candidate 1",
        "session": "ecephys_848390_2026-05-06_09-54-56",
        "subject": "848390",
        "window_start": 939.4749,
    },
    {
        "asset_id": "ab8ec755-2b87-45c3-a29d-dd88955334b8",
        "asset_path": "sub-830849/sub-830849_ses-ecephys-830849-2026-03-07-09-48-16_ecephys.nwb",
        "asset_size": 10_330_875_850,
        "camera": ("1496996778_830849_20260307.eye", "eye_cam_exposing"),
        "id": "neuropixels-candidate-2",
        "label": "Candidate 2",
        "session": "ecephys_830849_2026-03-07_09-48-16",
        "subject": "830849",
        "window_start": 1050.74958,
    },
    {
        "asset_id": "a7f50043-8883-4c0e-a956-2ff3e0f1b0ef",
        "asset_path": "sub-834687/sub-834687_ses-ecephys-834687-2026-03-18-15-50-10_ecephys.nwb",
        "asset_size": 12_819_445_281,
        "camera": ("1499077798_834687_20260318.eye", "eye_cam_exposing"),
        "id": "neuropixels-candidate-3",
        "label": "Candidate 3",
        "session": "ecephys_834687_2026-03-18_15-50-10",
        "subject": "834687",
        "window_start": 3570.52535,
    },
    {
        "asset_id": "0b7227e9-0c03-46ea-be70-618a73efb67d",
        "asset_path": "sub-834686/sub-834686_ses-ecephys-834686-2026-03-23-17-08-31_ecephys.nwb",
        "asset_size": 13_156_860_075,
        "camera": ("1500167786_834686_20260323.eye", "eye_cam_exposing"),
        "id": "neuropixels-candidate-4",
        "label": "Candidate 4",
        "session": "ecephys_834686_2026-03-23_17-08-31",
        "subject": "834686",
        "window_start": 1533.584335,
    },
    {
        "asset_id": "680d1c0c-e338-4d0b-ba29-4329436d2ae2",
        "asset_path": "sub-830846/sub-830846_ses-ecephys-830846-2026-03-11-10-19-32_ecephys.nwb",
        "asset_size": 13_095_960_631,
        "camera": ("1497719081_830846_20260311.eye", "eye_cam_exposing"),
        "id": "neuropixels-candidate-5",
        "label": "Candidate 5",
        "session": "ecephys_830846_2026-03-11_10-19-32",
        "subject": "830846",
        "window_start": 4873.896315,
    },
)

for candidate in NEUROPIXELS_CANDIDATES:
    candidate["context"] = "Neuropixels candidate"
    candidate["dandi_url"] = "https://dandiarchive.org/dandiset/001637/draft/files"
    candidate["frame_size"] = (658, 492)
    candidate["nwb_url"] = (
        f"https://api.dandiarchive.org/api/assets/{candidate['asset_id']}/download/"
    )
    candidate["sync_url"] = (
        f"{S3_ROOT}/{candidate['session']}/behavior/{candidate['camera'][0].removesuffix('.eye')}.sync"
    )

MESOSCOPE_CANDIDATES = (
    {
        "asset_id": "ab44a0f7-2864-4a30-8988-0b76aec28fa6",
        "asset_path": "sub-832700/sub-832700_ses-multiplane-ophys-832700-2026-01-29-11-18-09_ophys.nwb",
        "asset_size": 4_671_820_041,
        "camera": ("1489075012_Eye_20260129T111733", "eye_cam_exposing"),
        "id": "mesoscope-candidate-1", "label": "Candidate 1",
        "session": "multiplane-ophys_832700_2026-01-29_11-18-09",
        "subject": "832700", "window_start": 4302.05602,
    },
    {
        "asset_id": "6dc5f369-7199-4242-b0c9-3874f23e644e",
        "asset_path": "sub-846289/sub-846289_ses-multiplane-ophys-846289-2026-04-16-13-56-40_ophys.nwb",
        "asset_size": 4_291_076_055,
        "camera": ("1776371364_Eye_20260416T135611", "eye_cam_exposing"),
        "id": "mesoscope-candidate-2", "label": "Candidate 2",
        "session": "multiplane-ophys_846289_2026-04-16_13-56-40",
        "subject": "846289", "window_start": 2152.037075,
    },
    {
        "asset_id": "b980f6a1-0c34-4f2b-ba4e-72b2563e42de",
        "asset_path": "sub-839909/sub-839909_ses-multiplane-ophys-839909-2026-02-26-15-11-01_ophys.nwb",
        "asset_size": 4_086_984_781,
        "camera": ("1772143800_Eye_20260226T151022", "eye_cam_exposing"),
        "id": "mesoscope-candidate-3", "label": "Candidate 3",
        "session": "multiplane-ophys_839909_2026-02-26_15-11-01",
        "subject": "839909", "window_start": 2109.061245,
    },
    {
        "asset_id": "cc63761d-360b-440f-ae0a-e2533334513f",
        "asset_path": "sub-837568/sub-837568_ses-multiplane-ophys-837568-2026-02-19-13-22-26_ophys.nwb",
        "asset_size": 4_321_701_528,
        "camera": ("1771534202_Eye_20260219T132157", "eye_cam_exposing"),
        "id": "mesoscope-candidate-4", "label": "Candidate 4",
        "session": "multiplane-ophys_837568_2026-02-19_13-22-26",
        "subject": "837568", "window_start": 227.99571,
    },
    {
        "asset_id": "31b0789e-de41-4c40-97c3-915919d0397a",
        "asset_path": "sub-842971/sub-842971_ses-multiplane-ophys-842971-2026-05-06-09-36-56_ophys.nwb",
        "asset_size": 4_574_181_998,
        "camera": ("1778083903_Eye_20260506T093629", "eye_cam_exposing"),
        "id": "mesoscope-candidate-5", "label": "Candidate 5",
        "session": "multiplane-ophys_842971_2026-05-06_09-36-56",
        "subject": "842971", "window_start": 2112.95059,
    },
)

for candidate in MESOSCOPE_CANDIDATES:
    candidate["context"] = "Mesoscope candidate"
    candidate["dandi_url"] = "https://dandiarchive.org/dandiset/001768/draft/files"
    candidate["frame_size"] = (658, 492)
    candidate["nwb_url"] = (
        f"https://api.dandiarchive.org/api/assets/{candidate['asset_id']}/download/"
    )
    camera_stem = candidate["camera"][0].split("_")[0]
    candidate["sync_url"] = (
        f"{S3_ROOT}/{candidate['session']}/behavior/{camera_stem}_sync.h5"
    )

SLAP2_CANDIDATES = (
    {
        "asset_id": "0929c67a-7eca-46d8-836d-430a8df136ae",
        "asset_path": "sub-828408/sub-828408_ses-828408-2025-11-13-10-30-53_image+ophys.nwb",
        "asset_size": 2_616_654_491,
        "id": "slap2-candidate-1", "label": "Candidate 1",
        "session": "828408_2025-11-13_10-30-53", "subject": "828408",
        "window_start": 1985.946512,
    },
    {
        "asset_id": "e03a3c9e-1699-4742-b352-7385c3a90610",
        "asset_path": "sub-828409/sub-828409_ses-828409-2025-11-21-11-14-03_image+ophys.nwb",
        "asset_size": 2_831_214_109,
        "id": "slap2-candidate-2", "label": "Candidate 2",
        "session": "828409_2025-11-21_11-14-03", "subject": "828409",
        "window_start": 728.582976,
    },
    {
        "asset_id": "e36d24b2-ee5d-44d4-8119-b4f3f53e80d1",
        "asset_path": "sub-829704/sub-829704_ses-829704-2025-12-11-12-57-26_image+ophys.nwb",
        "asset_size": 2_151_916_401,
        "id": "slap2-candidate-3", "label": "Candidate 3",
        "session": "829704_2025-12-11_12-57-26", "subject": "829704",
        "window_start": 3654.234,
    },
    {
        "asset_id": "686c579b-eddf-4e7d-b9b2-c633e2d1fb15",
        "asset_path": "sub-828408/sub-828408_ses-828408-2025-11-18-14-44-48_image+ophys.nwb",
        "asset_size": 3_846_456_589,
        "id": "slap2-candidate-4", "label": "Candidate 4",
        "session": "828408_2025-11-18_14-44-48", "subject": "828408",
        "window_start": 226.551488,
    },
    {
        "asset_id": "018a6c38-a3e6-4246-abb4-01c01281f392",
        "asset_path": "sub-829704/sub-829704_ses-829704-2025-12-18-10-57-36_image+ophys.nwb",
        "asset_size": 3_709_531_648,
        "id": "slap2-candidate-5", "label": "Candidate 5",
        "session": "829704_2025-12-18_10-57-36", "subject": "829704",
        "window_start": 349.859488,
    },
)

for candidate in SLAP2_CANDIDATES:
    candidate["context"] = "SLAP2 candidate"
    candidate["dandi_url"] = "https://dandiarchive.org/dandiset/001424/draft/files"
    candidate["frame_size"] = (728, 544)
    candidate["nwb_url"] = (
        f"https://api.dandiarchive.org/api/assets/{candidate['asset_id']}/download/"
    )
    candidate["platform"] = "slap2"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--neuropixels-candidates", action="store_true")
    parser.add_argument("--mesoscope-candidates", action="store_true")
    parser.add_argument("--slap2-candidates", action="store_true")
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
        for name in ("data_x", "data_y", "width", "height", "area", "angle")
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


def extract_candidate_session(config: dict) -> dict:
    excerpt_start = config["window_start"]
    with closing(remfile.File(config["nwb_url"])) as remote:
        with h5py.File(remote, mode="r") as nwb:
            eye_tracking = nwb["processing/eye_tracking"]
            fits = {
                fit_id: {
                    "fieldReference": fit_field_reference(eye_tracking, fit_id, config),
                    "label": label,
                    "sampleFields": [
                        "time", "x", "y", "width", "height", "area", "angle", "blink"
                    ],
                    "samples": fit_samples(eye_tracking, fit_id, excerpt_start),
                }
                for fit_id, label in FIT_SOURCES
            }
            if config.get("platform") == "slap2":
                camera, camera_sources = slap2_camera(eye_tracking, config, excerpt_start)
            else:
                camera, camera_sources = eye_camera(config, excerpt_start)
    return {
        "alignment": (
            "Processed eye fits, likely-blink flags, and eye-camera frames share the "
            "packaged acquisition clock and are aligned through 100 kHz sync edges."
        ),
        "camera": camera,
        "context": config["context"],
        "fits": fits,
        "id": config["id"],
        "label": config["label"],
        "session": config["session"],
        "sourceLinks": [
            {"label": "DANDI", "url": config["dandi_url"]},
            {
                "label": "Raw S3 session",
                "url": f"https://open.quiltdata.com/b/aind-open-data/tree/{config['session']}/",
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
        "subject": config["subject"],
        "windowStart": excerpt_start,
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
                        "angle",
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
    candidate_modes = sum(
        (args.neuropixels_candidates, args.mesoscope_candidates, args.slap2_candidates)
    )
    if candidate_modes > 1:
        raise SystemExit("Choose only one candidate set.")
    if args.neuropixels_candidates:
        configs = NEUROPIXELS_CANDIDATES
    elif args.mesoscope_candidates:
        configs = MESOSCOPE_CANDIDATES
    elif args.slap2_candidates:
        configs = SLAP2_CANDIDATES
    else:
        configs = STANDARD_SESSIONS
    sessions = [
        extract_candidate_session(config) if "window_start" in config else extract_session(config)
        for config in configs
    ]
    payload = {
        "durationSeconds": EXCERPT_DURATION_SECONDS,
        "retrievedDate": "2026-08-26",
        "sessions": sessions,
        "version": 3,
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