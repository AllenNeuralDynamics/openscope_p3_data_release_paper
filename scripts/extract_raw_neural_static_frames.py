#!/usr/bin/env python3
"""Extract deterministic microscopy stills for the static raw-data figure."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from openscope_p3_publication.figures import (
    NEURAL_EXCERPTS_PATH,
    NEURAL_MEDIA_DIR,
    NEURAL_STATIC_FRAME_DIR,
    NEURAL_STATIC_FRAME_PROVENANCE_PATH,
    NEURAL_STATIC_SELECTIONS,
    SLAP2_STATIC_COMPOSITES,
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


def apply_hue_preserving_gamma(
    image: Image.Image,
    gamma: float,
) -> Image.Image:
    if not 0 < gamma <= 1:
        raise ValueError("Static-frame gamma must be in the interval (0, 1].")
    image = image.convert("RGB")
    data = image.tobytes()
    pixels = zip(data[0::3], data[1::3], data[2::3], strict=True)
    lookup = [round(255 * (value / 255) ** gamma) for value in range(256)]
    adjusted = []
    for pixel in pixels:
        value = max(pixel)
        if value == 0:
            adjusted.append((0, 0, 0))
            continue
        scale = lookup[value] / value
        adjusted.append(tuple(min(255, round(component * scale)) for component in pixel))
    output = Image.new("RGB", image.size)
    output.putdata(adjusted)
    return output


def main() -> None:
    payload = load_neural_excerpts()
    sessions = {session["id"]: session for session in payload["sessions"]}
    if NEURAL_STATIC_FRAME_DIR.exists():
        shutil.rmtree(NEURAL_STATIC_FRAME_DIR)
    NEURAL_STATIC_FRAME_DIR.mkdir(parents=True, exist_ok=True)
    records = []

    mesoscope_options = {
        option["id"]: option for option in sessions["mesoscope"]["options"]
    }
    for option_id in NEURAL_STATIC_SELECTIONS["mesoscope"]:
        option = mesoscope_options[option_id]
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
        output_path = NEURAL_STATIC_FRAME_DIR / f"mesoscope-{option_id}.png"
        with Image.open(source_path) as sheet:
            frame, display_low, display_high = stretch_display_contrast(sheet.crop(box))
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
                "modality": "mesoscope",
                "option_id": option_id,
                "output_sha256": file_sha256(output_path),
                "source_sheet_sha256": option["sheetSha256"],
            }
        )

    slap2_options = {option["id"]: option for option in sessions["slap2"]["options"]}
    for composite_id, source_option_ids in SLAP2_STATIC_COMPOSITES.items():
        green_option, red_option = (
            slap2_options[option_id] for option_id in source_option_ids
        )
        if (
            green_option["detectorChannel"] != 1
            or red_option["detectorChannel"] != 2
            or green_option["frameTimes"] != red_option["frameTimes"]
            or green_option["compositeAssetPath"]
            != red_option["compositeAssetPath"]
            or green_option["compositeSheetSha256"]
            != red_option["compositeSheetSha256"]
        ):
            raise RuntimeError(f"SLAP2 composite channels are not aligned: {composite_id}")
        frame_index = len(green_option["frameTimes"]) // 2
        source_path = NEURAL_MEDIA_DIR / Path(
            green_option["compositeAssetPath"]
        ).name
        if file_sha256(source_path) != green_option["compositeSheetSha256"]:
            raise RuntimeError(f"SLAP2 composite checksum mismatch: {source_path.name}")
        column = frame_index % green_option["sheetColumns"]
        row = frame_index // green_option["sheetColumns"]
        left = column * green_option["frameWidth"]
        top = row * green_option["frameHeight"]
        box = (
            left,
            top,
            left + green_option["frameWidth"],
            top + green_option["frameHeight"],
        )
        output_path = NEURAL_STATIC_FRAME_DIR / f"slap2-{composite_id}.png"
        with Image.open(source_path) as sheet:
            frame = apply_hue_preserving_gamma(sheet.crop(box), gamma=0.55)
            frame.save(
                output_path,
                format="PNG",
                compress_level=9,
                optimize=False,
            )
        records.append(
            {
                "asset_path": output_path.name,
                "channel_composite": {
                    "green": green_option["measurement"],
                    "red": red_option["measurement"],
                    "source_high_percentile": 99.5,
                    "source_low_percentile": 1.0,
                },
                "display_contrast": {
                    "gamma": 0.55,
                    "method": "max-channel hue-preserving gamma",
                },
                "frame_index": frame_index,
                "frame_time_seconds": green_option["frameTimes"][frame_index],
                "frame_size": [
                    green_option["frameWidth"],
                    green_option["frameHeight"],
                ],
                "modality": "slap2",
                "option_id": composite_id,
                "output_sha256": file_sha256(output_path),
                "source_option_ids": list(source_option_ids),
                "source_sheet_sha256": green_option["compositeSheetSha256"],
                "spatial_downsample_factor": green_option["spatialDownsampleFactor"],
                "temporal_averaging_frames": 1,
            }
        )

    provenance = {
        "version": 2,
        "raw_neural_excerpts_sha256": file_sha256(NEURAL_EXCERPTS_PATH),
        "frames": records,
        "notes": (
            "Representative middle frames extracted from committed lossless movie "
            "sheets for dependency-free HTML and PDF figure generation. Mesoscope "
            "stills are independently contrast-scaled. Each SLAP2 still merges its "
            "aligned green iGluSnFR4f and red RCaMP3 channels without temporal averaging "
            "and applies a max-channel hue-preserving gamma of 0.55 after the shared "
            "stored-(x, y) to display-(y, x) transpose."
        ),
    }
    NEURAL_STATIC_FRAME_PROVENANCE_PATH.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(records)} frames to {NEURAL_STATIC_FRAME_DIR}")


if __name__ == "__main__":
    main()