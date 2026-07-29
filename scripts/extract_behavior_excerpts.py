#!/usr/bin/env python3
"""Extract compact synchronized behavior excerpts from public OpenScope data."""

from __future__ import annotations

import argparse
import ast
import bisect
import csv
import hashlib
import io
import json
import math
import tempfile
import urllib.request
from contextlib import closing
from pathlib import Path

try:
    import h5py
    import harp
    import numpy as np
    import remfile
except ImportError as exc:  # pragma: no cover - optional extraction environment
    raise SystemExit(
        "Run with: uv run --with h5py --with harp-python --with numpy --with remfile "
        "python scripts/extract_behavior_excerpts.py"
    ) from exc


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "figure_sources" / "data" / "behavior-excerpts.json"
EXCERPT_DURATION_SECONDS = 16.0
EVENT_LEAD_SECONDS = 5.0
TRACE_RATE_HZ = 20
S3_ROOT = "https://aind-open-data.s3.us-west-2.amazonaws.com"

NWB_SESSIONS = (
    {
        "id": "neuropixels",
        "label": "Neuropixels",
        "subject": "820459",
        "context": "Sensorimotor mismatch",
        "session": "ecephys_820459_2025-11-10_15-07-13",
        "nwb_url": (
            "https://dandiarchive.s3.amazonaws.com/blobs/"
            "afa/8c6/afa8c6bd-518f-4daf-a2b1-67cbcdd0af65"
        ),
        "nwb_sha256": "b6c3642387c872c5a6a10e3530e72d8a8bf14ec5117107eace3823a0f679b497",
        "sync_url": (
            f"{S3_ROOT}/ecephys_820459_2025-11-10_15-07-13/behavior/"
            "1474843187_820459_20251110.sync"
        ),
        "dandi_url": "https://dandiarchive.org/dandiset/001637/draft/files",
        "camera_files": (
            (
                "behavior",
                "Behavior",
                "1474843187_820459_20251110.behavior",
                "beh_cam_exposing",
            ),
            (
                "face",
                "Face",
                "1474843187_820459_20251110.face",
                "face_cam_exposing",
            ),
            (
                "eye",
                "Eye",
                "1474843187_820459_20251110.eye",
                "eye_cam_exposing",
            ),
        ),
    },
    {
        "id": "mesoscope",
        "label": "Mesoscope",
        "subject": "832700",
        "context": "Sensorimotor mismatch",
        "session": "multiplane-ophys_832700_2026-01-29_11-18-09",
        "nwb_url": (
            "https://dandiarchive.s3.amazonaws.com/blobs/"
            "bd5/3f7/bd53f709-6243-44c9-bb36-51fb0e84b234"
        ),
        "nwb_sha256": "af52b3cbb224e85bc80ab5883eab4c0b40a6be42d134bfd3b8d3e66aa8f733dd",
        "sync_url": (
            f"{S3_ROOT}/multiplane-ophys_832700_2026-01-29_11-18-09/behavior/"
            "1489075012_sync.h5"
        ),
        "dandi_url": "https://dandiarchive.org/dandiset/001768/draft/files",
        "camera_files": (
            (
                "behavior",
                "Behavior",
                "1489075012_Behavior_20260129T111732",
                "beh_cam_exposing",
            ),
            (
                "face",
                "Face",
                "1489075012_Face_20260129T111733",
                "face_cam_exposing",
            ),
            (
                "eye",
                "Eye",
                "1489075012_Eye_20260129T111733",
                "eye_cam_exposing",
            ),
            (
                "nose",
                "Nose",
                "1489075012_Nose_20260129T111733",
                "nose_cam_frame_readout",
            ),
        ),
    },
)

SLAP2_SESSION = {
    "id": "slap2",
    "label": "SLAP2",
    "subject": "796630",
    "context": "Standard oddball",
    "session": "796630_2025-08-28_14-25-34",
    "camera_files": (
        ("body", "Body", "BodyCamera"),
        ("face", "Face", "FaceCamera"),
        ("eye", "Eye", "EyeCamera"),
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def fetch_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=180) as response:
        return response.read()


def remote_metadata(url: str) -> dict[str, str | int | None]:
    request = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(request, timeout=60) as response:
        return {
            "contentLength": int(response.headers["Content-Length"]),
            "contentType": response.headers.get("Content-Type"),
            "etag": response.headers.get("ETag", "").strip('"'),
            "lastModified": response.headers.get("Last-Modified"),
        }


def source_record(url: str, content: bytes | None = None) -> dict:
    record = {"url": url, **remote_metadata(url)}
    if content is not None:
        record["sha256"] = hashlib.sha256(content).hexdigest()
    return record


def decode(value):
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value.item() if hasattr(value, "item") else value


def orientation_degrees(value: float) -> float:
    if abs(value) <= 2 * math.pi + 0.01:
        return math.degrees(value) % 360
    return value % 360


def compact_trace(times, values, excerpt_start: float) -> list[list[float]]:
    sample_times = np.linspace(
        excerpt_start,
        excerpt_start + EXCERPT_DURATION_SECONDS,
        round(EXCERPT_DURATION_SECONDS * TRACE_RATE_HZ) + 1,
    )
    finite = np.isfinite(times) & np.isfinite(values)
    interpolated = np.interp(sample_times, times[finite], values[finite])
    return [
        [round(float(time - excerpt_start), 3), round(float(value), 3)]
        for time, value in zip(sample_times, interpolated, strict=True)
    ]


def nwb_stimulus_rows(table, excerpt_start: float) -> tuple[list[dict], int]:
    starts = np.asarray(table["start_time"][:], dtype=float)
    stops = np.asarray(table["stop_time"][:], dtype=float)
    mask = (starts < excerpt_start + EXCERPT_DURATION_SECONDS) & (stops >= excerpt_start)
    indices = np.flatnonzero(mask)
    rows = []
    for index in indices:
        trial_type = str(decode(table["TrialType"][index]))
        phase = float(decode(table["phase"][index]))
        rows.append(
            {
                "contrast": round(float(decode(table["contrast"][index])), 4),
                "end": round(float(stops[index] - excerpt_start), 6),
                "orientationDegrees": round(
                    orientation_degrees(float(decode(table["Orientation"][index]))), 3
                ),
                "phaseCycles": round(phase / (2 * math.pi), 6),
                "spatialFrequency": round(
                    float(decode(table["SpatialFrequency"][index])), 4
                ),
                "start": round(float(starts[index] - excerpt_start), 6),
                "temporalFrequency": round(
                    float(decode(table["TemporalFrequency"][index])), 4
                ),
                "trialNumber": int(float(decode(table["TrialNumber"][index]))),
                "trialType": trial_type,
            }
        )
    return rows, int(indices[0])


def rising_edges(sync_file: h5py.File, line: str) -> tuple[np.ndarray, float]:
    metadata = ast.literal_eval(sync_file["meta"][()].decode("utf-8"))
    try:
        bit = metadata["line_labels"].index(line)
    except ValueError as exc:
        raise RuntimeError(f"Sync line is missing: {line}") from exc
    sample_rate = float(metadata["ni_daq"]["counter_output_freq"])
    data = sync_file["data"][:]
    times = data[:, 0].astype(np.float64) / sample_rate
    states = ((data[:, 1] >> bit) & 1).astype(np.int8)
    return times[np.diff(states, prepend=0) == 1], sample_rate


def lost_frame_indices(report: dict) -> list[int]:
    indices = []
    for entry in report.get("LostFrames", []):
        for part in entry.split(","):
            first, separator, last = part.partition("-")
            start = int(first)
            stop = int(last) if separator else start
            indices.extend(range(start, stop + 1))
    return sorted(indices)


def mvr_time_map(
    frame_times: np.ndarray,
    report: dict,
    excerpt_start: float,
) -> list[list[float]]:
    lost = lost_frame_indices(report)
    encoded_rate = 60.0
    first = max(0, int(np.searchsorted(frame_times, excerpt_start)) - 2)
    last = min(
        len(frame_times),
        int(np.searchsorted(frame_times, excerpt_start + EXCERPT_DURATION_SECONDS)) + 2,
    )
    mapping = []
    for frame_index in range(first, last):
        lost_position = bisect.bisect_left(lost, frame_index)
        if lost_position < len(lost) and lost[lost_position] == frame_index:
            continue
        recorded_frame_index = frame_index - lost_position
        # MVR MP4 files begin with one metadata frame before camera frame zero.
        video_time = (recorded_frame_index + 1) / encoded_rate
        mapping.append(
            [
                round(float(frame_times[frame_index] - excerpt_start), 6),
                round(video_time, 6),
            ]
        )
    if not mapping or mapping[0][0] > 0 or mapping[-1][0] < EXCERPT_DURATION_SECONDS:
        raise RuntimeError("MVR frame map does not span the behavior excerpt.")
    return mapping


def nwb_cameras(config: dict, excerpt_start: float) -> tuple[list[dict], list[dict]]:
    cameras = []
    sources = []
    base = f"{S3_ROOT}/{config['session']}/behavior-videos"
    sync_bytes = fetch_bytes(config["sync_url"])
    with h5py.File(io.BytesIO(sync_bytes), mode="r") as sync_file:
        for camera_id, label, stem, sync_line in config["camera_files"]:
            report_url = f"{base}/{stem}.json"
            video_url = f"{base}/{stem}.mp4"
            report_bytes = fetch_bytes(report_url)
            report = json.loads(report_bytes)["RecordingReport"]
            frame_times, sample_rate = rising_edges(sync_file, sync_line)
            lost = lost_frame_indices(report)
            cameras.append(
                {
                    "id": camera_id,
                    "label": label,
                    "timeMap": mvr_time_map(frame_times, report, excerpt_start),
                    "timing": {
                        "clock": "NI-DAQ sync",
                        "clockRateHz": sample_rate,
                        "encodedRateHz": 60.0,
                        "leadingMetadataFrames": 1,
                        "reportedDroppedFrames": len(lost),
                        "syncLine": sync_line,
                    },
                    "url": video_url,
                }
            )
            sources.extend(
                [source_record(video_url), source_record(report_url, report_bytes)]
            )
    sources.append(source_record(config["sync_url"], sync_bytes))
    return cameras, sources


def extract_nwb_session(config: dict) -> dict:
    with closing(remfile.File(config["nwb_url"])) as remote:
        with h5py.File(remote, mode="r") as nwb:
            table = nwb["intervals/Sensory-motor mismatch block_presentations"]
            trial_types = np.asarray(table["TrialType"][:]).astype("U")
            mismatch_indices = np.flatnonzero(trial_types != "standard")
            mismatch_index = int(mismatch_indices[0])
            mismatch_time = float(table["start_time"][mismatch_index])
            mismatch_trial_number = int(
                float(decode(table["TrialNumber"][mismatch_index]))
            )
            excerpt_start = mismatch_time - EVENT_LEAD_SECONDS
            stimulus, _ = nwb_stimulus_rows(table, excerpt_start)

            running = nwb["processing/running/running_speed"]
            running_times = np.asarray(running["timestamps"][:], dtype=float)
            running_values = np.asarray(running["data"][:], dtype=float)
            running_unit = decode(running.attrs.get("unit", "cm/s"))
            cameras, camera_sources = nwb_cameras(config, excerpt_start)
    return {
        "alignment": (
            "NWB running speed, stimulus rows, and 100 kHz camera exposure/readout "
            "edges share the sync-file clock; dropped camera frames are removed before "
            "mapping hardware frame indices to MP4 presentation time."
        ),
        "cameras": cameras,
        "context": config["context"],
        "event": {
            "label": "90 degree visuomotor mismatch",
            "time": EVENT_LEAD_SECONDS,
            "trialNumber": mismatch_trial_number,
        },
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
                "sha256": config["nwb_sha256"],
                "url": config["nwb_url"],
            },
            *camera_sources,
        ],
        "stimulus": stimulus,
        "subject": config["subject"],
        "trace": compact_trace(running_times, running_values, excerpt_start),
        "traceLabel": "Running speed",
        "traceUnit": str(running_unit),
    }


def download_harp_files(directory: Path, base: str) -> list[dict]:
    sources = []
    files = ("device.yml", "Behavior_44.bin", "Behavior_56.bin", "Behavior_58.bin")
    for filename in files:
        url = f"{base}/behavior/VCO1_Behavior.harp/{filename}"
        content = fetch_bytes(url)
        (directory / filename).write_bytes(content)
        sources.append(source_record(url, content))
    return sources


def slap2_cameras(
    config: dict, reference: float, excerpt_start: float
) -> tuple[list[dict], list[dict]]:
    cameras = []
    sources = []
    base = f"{S3_ROOT}/{config['session']}/behavior-videos"
    for camera_id, label, directory in config["camera_files"]:
        metadata_url = f"{base}/{directory}/metadata.csv"
        video_url = f"{base}/{directory}/video.mp4"
        metadata_bytes = fetch_bytes(metadata_url)
        rows = csv.DictReader(io.StringIO(metadata_bytes.decode("utf-8-sig")))
        frame_times = np.asarray(
            [float(row["CameraFrameTime"]) for row in rows], dtype=float
        )
        target_start = reference + excerpt_start
        first = max(0, int(np.searchsorted(frame_times, target_start)) - 2)
        last = min(
            len(frame_times),
            int(
                np.searchsorted(
                    frame_times, target_start + EXCERPT_DURATION_SECONDS
                )
            )
            + 2,
        )
        time_map = [
            [
                round(float(frame_times[index] - target_start), 6),
                round(index / 30.0, 6),
            ]
            for index in range(first, last)
        ]
        if not time_map or time_map[0][0] > 0 or time_map[-1][0] < EXCERPT_DURATION_SECONDS:
            raise RuntimeError(f"SLAP2 frame map does not span the excerpt: {camera_id}")
        cameras.append(
            {
                "id": camera_id,
                "label": label,
                "timeMap": time_map,
                "timing": {
                    "clock": "Harp CameraFrameTime",
                    "encodedRateHz": 30.0,
                    "leadingMetadataFrames": 0,
                    "reportedDroppedFrames": 0,
                },
                "url": video_url,
            }
        )
        sources.extend(
            [source_record(video_url), source_record(metadata_url, metadata_bytes)]
        )
    return cameras, sources


def extract_slap2_session(config: dict) -> dict:
    base = f"{S3_ROOT}/{config['session']}"
    orientation_url = f"{base}/behavior/stimuli/orientations_orientations0.csv"
    orientation_bytes = fetch_bytes(orientation_url)
    orientation_rows = [
        [float(value) for value in row]
        for row in csv.reader(io.StringIO(orientation_bytes.decode("utf-8-sig")))
    ]

    with tempfile.TemporaryDirectory(prefix="openscope-slap2-harp-") as temp_dir:
        directory = Path(temp_dir)
        harp_sources = download_harp_files(directory, base)
        reader = harp.create_reader(directory)
        analog = reader.AnalogData.read()
        trial_starts = reader.PulseDO0.read().index.to_numpy(dtype=float)
        grating_times = reader.PulseDO2.read().index.to_numpy(dtype=float)

    reference = float(trial_starts[0])
    grating_times = grating_times - reference
    difference = len(orientation_rows) - len(grating_times)
    if abs(difference) > 3:
        raise RuntimeError("SLAP2 orientation rows and Harp grating pulses do not match.")
    if difference > 0:
        orientation_rows = orientation_rows[difference:]
    elif difference < 0:
        grating_times = grating_times[-difference:]

    orientations = np.asarray([row[9] for row in orientation_rows], dtype=float)
    selected_index = None
    for index in range(40, len(orientations) - 40):
        neighborhood = orientations[index - 40 : index + 41]
        if abs(orientations[index]) > 0.1 and np.mean(np.isclose(neighborhood, 0)) > 0.75:
            selected_index = index
            break
    if selected_index is None:
        raise RuntimeError("No locally rare SLAP2 orientation deviant was found.")

    event_time = float(grating_times[selected_index])
    excerpt_start = event_time - EVENT_LEAD_SECONDS
    stimulus = []
    for start, row in zip(grating_times, orientation_rows, strict=True):
        duration = row[1]
        stop = start + duration
        if start >= excerpt_start + EXCERPT_DURATION_SECONDS or stop < excerpt_start:
            continue
        orientation = orientation_degrees(row[9])
        stimulus.append(
            {
                "contrast": round(row[6], 4),
                "end": round(float(stop - excerpt_start), 6),
                "orientationDegrees": round(orientation, 3),
                "phaseCycles": 0.0,
                "spatialFrequency": round(row[7], 4),
                "start": round(float(start - excerpt_start), 6),
                "temporalFrequency": round(row[8], 4),
                "trialNumber": int(row[0]),
                "trialType": "standard" if abs(orientation) < 0.1 else "orientation_deviant",
            }
        )

    analog_times = analog.index.to_numpy(dtype=float) - reference
    encoder = analog["Encoder"].to_numpy(dtype=np.int64)
    encoder_delta = (np.diff(encoder) + 32768) % 65536 - 32768
    encoder_position = np.concatenate(([0], np.cumsum(encoder_delta)))
    sample_times = np.linspace(
        excerpt_start,
        excerpt_start + EXCERPT_DURATION_SECONDS,
        round(EXCERPT_DURATION_SECONDS * TRACE_RATE_HZ) + 1,
    )
    sampled_position = np.interp(sample_times, analog_times, encoder_position)
    encoder_velocity = np.gradient(sampled_position, sample_times)
    trace = [
        [round(float(time - excerpt_start), 3), round(float(value), 3)]
        for time, value in zip(sample_times, encoder_velocity, strict=True)
    ]

    cameras, camera_sources = slap2_cameras(config, reference, excerpt_start)
    return {
        "alignment": (
            "Per-frame camera timestamps, wheel encoder samples, and grating pulses share "
            "the Harp clock; camera frame indices are mapped to the MP4 30 fps time base."
        ),
        "cameras": cameras,
        "context": config["context"],
        "event": {
            "label": "90 degree orientation deviant",
            "time": EVENT_LEAD_SECONDS,
            "trialNumber": int(orientation_rows[selected_index][0]),
        },
        "id": config["id"],
        "label": config["label"],
        "session": config["session"],
        "sourceLinks": [
            {
                "label": "Raw S3 session",
                "url": (
                    "https://open.quiltdata.com/b/aind-open-data/tree/"
                    f"{config['session']}/"
                ),
            },
            {
                "label": "SLAP2 packaging",
                "url": "https://github.com/AllenNeuralDynamics/slap2_packaging_nwb",
            },
        ],
        "sources": [
            source_record(orientation_url, orientation_bytes),
            *harp_sources,
            *camera_sources,
        ],
        "stimulus": stimulus,
        "subject": config["subject"],
        "trace": trace,
        "traceLabel": "Wheel encoder velocity",
        "traceUnit": "counts/s",
    }


def main() -> None:
    args = parse_args()
    payload = {
        "durationSeconds": EXCERPT_DURATION_SECONDS,
        "retrievedDate": "2026-07-29",
        "sessions": [
            *(extract_nwb_session(config) for config in NWB_SESSIONS),
            extract_slap2_session(SLAP2_SESSION),
        ],
        "version": 1,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()