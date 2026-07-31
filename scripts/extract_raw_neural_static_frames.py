#!/usr/bin/env python3
"""Extract deterministic microscopy stills for the static raw-data figure."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from openscope_p3_publication.figures import (
    NEURAL_EXCERPTS_PATH,
    NEURAL_MEDIA_DIR,
    NEURAL_STATIC_FRAME_DIR,
    NEURAL_STATIC_FRAME_PROVENANCE_PATH,
    NEURAL_STATIC_SELECTIONS,
    load_neural_excerpts,
)

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover - optional extraction environment
    raise SystemExit(
        "Run with: uv run --with pillow python "
        "scripts/extract_raw_neural_static_frames.py"
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


def stretch_display_contrast(
    image: Image.Image,
    low_percentile: float = 1.0,
    high_percentile: float = 99.5,
) -> tuple[Image.Image, int, int]:
    image = image.convert("RGB")
    data = image.tobytes()
    pixels = list(zip(data[0::3], data[1::3], data[2::3], strict=True))
    histogram = [0] * 256
    for pixel in pixels:
        histogram[max(pixel)] += 1
    low = histogram_percentile(histogram, low_percentile)
    high = histogram_percentile(histogram, high_percentile)
    if high <= low:
        raise RuntimeError("Static-frame contrast window is empty.")

    adjusted = []
    for pixel in pixels:
        value = max(pixel)
        if value <= low:
            adjusted.append((0, 0, 0))
            continue
        display_value = min(255, round((value - low) / (high - low) * 255))
        scale = display_value / value
        adjusted.append(tuple(min(255, round(component * scale)) for component in pixel))
    output = Image.new("RGB", image.size)
    output.putdata(adjusted)
    return output, low, high


def main() -> None:
    payload = load_neural_excerpts()
    sessions = {session["id"]: session for session in payload["sessions"]}
    NEURAL_STATIC_FRAME_DIR.mkdir(parents=True, exist_ok=True)
    records = []

    for modality in ("mesoscope", "slap2"):
        options = {option["id"]: option for option in sessions[modality]["options"]}
        for option_id in NEURAL_STATIC_SELECTIONS[modality]:
            option = options[option_id]
            frame_index = len(option["frameTimes"]) // 2
            source_path = NEURAL_MEDIA_DIR / Path(option["assetPath"]).name
            column = frame_index % option["sheetColumns"]
            row = frame_index // option["sheetColumns"]
            left = column * option["frameWidth"]
            top = row * option["frameHeight"]
            box = (
                left,
                top,
                left + option["frameWidth"],
                top + option["frameHeight"],
            )
            output_path = NEURAL_STATIC_FRAME_DIR / f"{modality}-{option_id}.png"
            with Image.open(source_path) as sheet:
                frame, display_low, display_high = stretch_display_contrast(
                    sheet.crop(box)
                )
                frame.save(output_path, format="PNG", compress_level=9, optimize=False)
            records.append(
                {
                    "asset_path": output_path.name,
                    "display_contrast": {
                        "high_percentile": 99.5,
                        "high_value": display_high,
                        "low_percentile": 1.0,
                        "low_value": display_low,
                        "method": "max-channel hue-preserving linear stretch",
                    },
                    "frame_index": frame_index,
                    "frame_time_seconds": option["frameTimes"][frame_index],
                    "modality": modality,
                    "option_id": option_id,
                    "output_sha256": file_sha256(output_path),
                    "source_sheet_sha256": option["sheetSha256"],
                }
            )

    provenance = {
        "version": 1,
        "raw_neural_excerpts_sha256": file_sha256(NEURAL_EXCERPTS_PATH),
        "frames": records,
        "notes": (
            "Representative middle frames extracted from the committed raw-data "
            "sprite sheets for dependency-free HTML and PDF figure generation. "
            "Each still is independently contrast-scaled for display."
        ),
    }
    NEURAL_STATIC_FRAME_PROVENANCE_PATH.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(records)} frames to {NEURAL_STATIC_FRAME_DIR}")


if __name__ == "__main__":
    main()