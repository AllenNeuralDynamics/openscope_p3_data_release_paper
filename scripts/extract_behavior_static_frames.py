#!/usr/bin/env python3
"""Extract synchronized camera stills for Figure 9's static view."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import urllib.request
from pathlib import Path

from openscope_p3_publication.figures import (
    BEHAVIOR_EXCERPTS_PATH,
    BEHAVIOR_STATIC_FRAME_DIR,
    BEHAVIOR_STATIC_FRAME_PROVENANCE_PATH,
    BEHAVIOR_STATIC_LOCAL_TIME_SECONDS,
    RUNNING_STATISTICS_PATH,
    load_behavior_excerpts,
)

try:
    import av
    from PIL import Image
except ImportError as exc:  # pragma: no cover - optional extraction environment
    raise SystemExit(
        "Run with: uv run --with av --with pillow python "
        "scripts/extract_behavior_static_frames.py"
    ) from exc


STATIC_SLAP2_SESSION = {
    "id": "slap2",
    "session": "828408_2025-11-13_10-30-53",
    "subject": "828408",
    "target_video_time_seconds": 600.0,
    "cameras": (
        ("body", "Body", "BodyCamera"),
        ("face", "Face", "FaceCamera"),
        ("eye", "Eye", "EyeCamera"),
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--modality",
        choices=("neuropixels", "mesoscope", "slap2"),
        help="Refresh one modality while preserving the other verified records.",
    )
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def histogram_percentile(histogram: list[int], percentile: float) -> int:
    target = sum(histogram) * percentile / 100
    cumulative = 0
    for value, count in enumerate(histogram):
        cumulative += count
        if cumulative >= target:
            return value
    return 255


def illuminate_frame(
    image: Image.Image,
    low_percentile: float = 1.0,
    high_percentile: float = 99.0,
    target_median: float = 0.35,
) -> tuple[Image.Image, dict]:
    image = image.convert("RGB")
    data = image.tobytes()
    pixels = list(zip(data[0::3], data[1::3], data[2::3], strict=True))
    luminance = [
        round(0.2126 * red + 0.7152 * green + 0.0722 * blue)
        for red, green, blue in pixels
    ]
    histogram = [0] * 256
    for value in luminance:
        histogram[value] += 1
    low = histogram_percentile(histogram, low_percentile)
    median = histogram_percentile(histogram, 50.0)
    high = histogram_percentile(histogram, high_percentile)
    if high <= low:
        raise RuntimeError("Behavior-frame contrast window is empty.")
    normalized_median = max(0.001, min(0.999, (median - low) / (high - low)))
    gamma = max(
        0.35,
        min(1.0, math.log(target_median) / math.log(normalized_median)),
    )
    adjusted = []
    for pixel, value in zip(pixels, luminance, strict=True):
        if value <= low:
            display_value = 0
        elif value >= high:
            display_value = 255
        else:
            normalized = (value - low) / (high - low)
            display_value = round(normalized**gamma * 255)
        scale = display_value / max(1, value)
        adjusted.append(
            tuple(min(255, round(component * scale)) for component in pixel)
        )
    output = Image.new("RGB", image.size)
    output.putdata(adjusted)
    return output, {
        "gamma": round(gamma, 6),
        "high_percentile": high_percentile,
        "high_value": high,
        "low_percentile": low_percentile,
        "low_value": low,
        "median_value": median,
        "method": "luminance percentile stretch with adaptive gamma",
        "target_median": target_median,
    }


def video_time_at(time_map: list[list[float]], local_time: float) -> float:
    if local_time <= time_map[0][0]:
        return time_map[0][1]
    if local_time >= time_map[-1][0]:
        return time_map[-1][1]
    low = 0
    high = len(time_map) - 1
    while low + 1 < high:
        middle = (low + high) // 2
        if time_map[middle][0] <= local_time:
            low = middle
        else:
            high = middle
    first = time_map[low]
    second = time_map[high]
    fraction = (local_time - first[0]) / (second[0] - first[0])
    return first[1] + (second[1] - first[1]) * fraction


def video_source(session: dict, url: str) -> dict:
    matching = [source for source in session["sources"] if source.get("url") == url]
    if len(matching) != 1 or "etag" not in matching[0]:
        raise RuntimeError(f"Expected one ETag-backed video source: {url}")
    return matching[0]


def remote_metadata(url: str) -> dict:
    request = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(request, timeout=60) as response:
        return {
            "contentLength": int(response.headers["Content-Length"]),
            "etag": response.headers.get("ETag", "").strip('"'),
        }


def static_sessions(payload: dict) -> list[dict]:
    sessions = []
    for session in payload["sessions"]:
        if session["id"] != "slap2":
            sessions.append(
                {
                    **session,
                    "selection": "excerpt_local_time_seconds",
                    "target_video_time_seconds": None,
                }
            )
            continue
        cameras = []
        for camera_id, label, directory in STATIC_SLAP2_SESSION["cameras"]:
            cameras.append(
                {
                    "id": camera_id,
                    "label": label,
                    "url": (
                        "https://aind-open-data.s3.us-west-2.amazonaws.com/"
                        f'{STATIC_SLAP2_SESSION["session"]}/behavior-videos/'
                        f"{directory}/video.mp4"
                    ),
                }
            )
        sessions.append(
            {
                **STATIC_SLAP2_SESSION,
                "cameras": cameras,
                "selection": "video_time_seconds",
            }
        )
    return sessions


def decode_frame(url: str, target_seconds: float) -> tuple[Image.Image, float]:
    with av.open(url, options={"rw_timeout": "60000000"}) as container:
        stream = container.streams.video[0]
        container.seek(
            int(target_seconds / float(stream.time_base)),
            stream=stream,
            backward=True,
        )
        selected = None
        for frame in container.decode(stream):
            selected = frame
            if frame.time is not None and frame.time >= target_seconds:
                break
    if selected is None or selected.time is None:
        raise RuntimeError(f"Could not decode synchronized frame from {url}")
    return selected.to_image().convert("RGB"), float(selected.time)


def resize_frame(image: Image.Image, maximum_width: int = 520) -> Image.Image:
    if image.width <= maximum_width:
        return image
    height = round(image.height * maximum_width / image.width)
    return image.resize((maximum_width, height), Image.Resampling.LANCZOS)


def main() -> None:
    args = parse_args()
    payload = load_behavior_excerpts()
    BEHAVIOR_STATIC_FRAME_DIR.mkdir(parents=True, exist_ok=True)
    existing_records = {}
    if BEHAVIOR_STATIC_FRAME_PROVENANCE_PATH.exists():
        existing = json.loads(
            BEHAVIOR_STATIC_FRAME_PROVENANCE_PATH.read_text(encoding="utf-8")
        )
        existing_records = {
            (record["modality"], record["camera_id"]): record
            for record in existing.get("frames", [])
        }
    source_sessions = static_sessions(payload)
    payload_sessions = {session["id"]: session for session in payload["sessions"]}
    records = dict(existing_records)
    for session in source_sessions:
        if args.modality is not None and session["id"] != args.modality:
            continue
        for camera in session["cameras"]:
            if session["selection"] == "excerpt_local_time_seconds":
                target_video_time = video_time_at(
                    camera["timeMap"], BEHAVIOR_STATIC_LOCAL_TIME_SECONDS
                )
                source = video_source(payload_sessions[session["id"]], camera["url"])
            else:
                target_video_time = session["target_video_time_seconds"]
                source = remote_metadata(camera["url"])
            image, decoded_time = decode_frame(camera["url"], target_video_time)
            image, display_contrast = illuminate_frame(image)
            image = resize_frame(image)
            output_path = (
                BEHAVIOR_STATIC_FRAME_DIR
                / f"{session['id']}-{camera['id']}.jpg"
            )
            image.save(
                output_path,
                format="JPEG",
                quality=90,
                subsampling=0,
                optimize=False,
                progressive=False,
            )
            records[(session["id"], camera["id"])] = {
                "asset_path": output_path.name,
                "camera_id": camera["id"],
                "camera_label": camera["label"],
                "decoded_video_time_seconds": decoded_time,
                "display_contrast": display_contrast,
                "local_time_seconds": (
                    BEHAVIOR_STATIC_LOCAL_TIME_SECONDS
                    if session["selection"] == "excerpt_local_time_seconds"
                    else None
                ),
                "modality": session["id"],
                "mouse_id": session["subject"],
                "output_sha256": file_sha256(output_path),
                "selection": session["selection"],
                "source_content_length": source["contentLength"],
                "source_etag": source["etag"],
                "source_session_id": session["session"],
                "source_url": camera["url"],
                "target_video_time_seconds": target_video_time,
            }
    for session in source_sessions:
        for camera in session["cameras"]:
            key = (session["id"], camera["id"])
            if key not in records:
                raise RuntimeError(f"Static camera record is unavailable: {key}")
            record = records[key]
            record.setdefault("mouse_id", session["subject"])
            record.setdefault("source_session_id", session["session"])
            record.setdefault("selection", session["selection"])
    provenance = {
        "version": 2,
        "behavior_excerpts_sha256": file_sha256(BEHAVIOR_EXCERPTS_PATH),
        "running_statistics_sha256": file_sha256(RUNNING_STATISTICS_PATH),
        "local_time_seconds": BEHAVIOR_STATIC_LOCAL_TIME_SECONDS,
        "frames": [
            records[(session["id"], camera["id"])]
            for session in source_sessions
            for camera in session["cameras"]
        ],
        "notes": (
            "Camera frames decoded from ETag-pinned public MP4 sources for Figure 9's "
            "static view. Neuropixels and mesoscope retain the common synchronized "
            "excerpt time; SLAP2 uses the same session and mouse as its full-session "
            "running profile. Each still is independently illuminated from luminance "
            "percentiles."
        ),
    }
    BEHAVIOR_STATIC_FRAME_PROVENANCE_PATH.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(records)} frames to {BEHAVIOR_STATIC_FRAME_DIR}")


if __name__ == "__main__":
    main()
