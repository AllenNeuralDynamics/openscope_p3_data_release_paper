#!/usr/bin/env python3
"""Extract synchronized camera stills for Figure 9's static view."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from openscope_p3_publication.figures import (
    BEHAVIOR_EXCERPTS_PATH,
    BEHAVIOR_STATIC_FRAME_DIR,
    BEHAVIOR_STATIC_FRAME_PROVENANCE_PATH,
    BEHAVIOR_STATIC_LOCAL_TIME_SECONDS,
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
    payload = load_behavior_excerpts()
    BEHAVIOR_STATIC_FRAME_DIR.mkdir(parents=True, exist_ok=True)
    records = []
    for session in payload["sessions"]:
        for camera in session["cameras"]:
            target_video_time = video_time_at(
                camera["timeMap"], BEHAVIOR_STATIC_LOCAL_TIME_SECONDS
            )
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
            source = video_source(session, camera["url"])
            records.append(
                {
                    "asset_path": output_path.name,
                    "camera_id": camera["id"],
                    "camera_label": camera["label"],
                    "decoded_video_time_seconds": decoded_time,
                    "display_contrast": display_contrast,
                    "local_time_seconds": BEHAVIOR_STATIC_LOCAL_TIME_SECONDS,
                    "modality": session["id"],
                    "output_sha256": file_sha256(output_path),
                    "source_content_length": source["contentLength"],
                    "source_etag": source["etag"],
                    "source_url": camera["url"],
                    "target_video_time_seconds": target_video_time,
                }
            )
    provenance = {
        "version": 1,
        "behavior_excerpts_sha256": file_sha256(BEHAVIOR_EXCERPTS_PATH),
        "local_time_seconds": BEHAVIOR_STATIC_LOCAL_TIME_SECONDS,
        "frames": records,
        "notes": (
            "Synchronized camera frames decoded from ETag-pinned public MP4 sources "
            "at a common local excerpt time for Figure 9's static view. Each still "
            "is independently illuminated from luminance percentiles."
        ),
    }
    BEHAVIOR_STATIC_FRAME_PROVENANCE_PATH.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(records)} frames to {BEHAVIOR_STATIC_FRAME_DIR}")


if __name__ == "__main__":
    main()
