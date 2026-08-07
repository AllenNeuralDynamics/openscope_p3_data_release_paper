#!/usr/bin/env python3
"""Extract compact event-aligned raw-data views from public recordings."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import math
import shutil
import tempfile
import urllib.request
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

try:
    import h5py
    import numpy as np
    import remfile
    import s3fs
    import tifffile
    import zarr
    from PIL import Image
    from wavpack_numcodecs import WavPack
except ImportError as exc:  # pragma: no cover - optional extraction environment
    raise SystemExit(
        "Install WavPack (`brew install wavpack` on macOS), then run with: "
        "uv run --with h5py --with numpy --with remfile --with s3fs "
        "--with 'zarr<3' --with wavpack-numcodecs --with pillow==12.3.0 "
        "--with tifffile==2026.7.14 "
        "python scripts/extract_raw_neural_excerpts.py"
    ) from exc


REPO_ROOT = Path(__file__).resolve().parents[1]
BEHAVIOR_PATH = REPO_ROOT / "figure_sources" / "data" / "behavior-excerpts.json"
DEFAULT_OUTPUT = REPO_ROOT / "figure_sources" / "data" / "raw-neural-excerpts.json"
DEFAULT_MEDIA_DIR = REPO_ROOT / "figure_sources" / "media" / "neural-viewer"
WINDOW_START_SECONDS = -1.0
WINDOW_END_SECONDS = 3.0
RETRIEVED_DATE = "2026-08-03"

NEUROPIXELS_NWB = {
    "url": (
        "https://dandiarchive.s3.amazonaws.com/blobs/"
        "1a3/a02/1a3a0214-c40e-49ed-9ada-9379c9fca1e8"
    ),
    "sha256": "75c425992a9443a6b7bb19b00469469788d6be4dd8c721714d0692e214fe7bf9",
    "dandiUrl": "https://dandiarchive.org/dandiset/001637/draft/files",
}
NEUROPIXELS_SESSION = {
    "context": "Sequence mismatch",
    "interval": "Sequence mismatch block_presentations",
    "session": "ecephys_830846_2026-03-09_10-32-54",
    "subject": "830846",
}
NEUROPIXELS_AP_PREFIX = (
    "ecephys_830846_2026-03-09_10-32-54/ecephys/ecephys_compressed"
)
NEUROPIXELS_AP_STORES = {
    "A": "experiment1_Record Node 101#Neuropix-PXI-100.ProbeA-AP.zarr",
    "B": "experiment1_Record Node 101#Neuropix-PXI-100.ProbeB-AP.zarr",
    "C": "experiment1_Record Node 101#Neuropix-PXI-100.ProbeC-AP.zarr",
    "D": "experiment1_Record Node 103#Neuropix-PXI-100.ProbeD-AP.zarr",
    "E": "experiment1_Record Node 103#Neuropix-PXI-100.ProbeE-AP.zarr",
    "F": "experiment1_Record Node 103#Neuropix-PXI-100.ProbeF-AP.zarr",
}
NEUROPIXELS_ANATOMY = {
    "A": {
        "selector": "MOs / ACA / TH",
        "summary": "MOs L1–L5 · ACA · TH",
    },
    "B": {
        "selector": "VISa / CA / LGv",
        "summary": "VISa L1–L6b · CA1–CA3 · LGv / RT",
    },
    "C": {
        "selector": "VISp / CA / LGd",
        "summary": "VISp L1–L6a · CA1–CA3 / DG · LGd / VPM",
    },
    "D": {
        "selector": "VISp / CA / LGd",
        "summary": "VISp L1–L6b · CA1 / CA3 / DG · LGd",
    },
    "E": {
        "selector": "MOp / MOs / OLF",
        "summary": "MOp L1–L5 · MOs L5–L6b · OLF",
    },
    "F": {
        "selector": "MOs / PFC / STR",
        "summary": "MOs L1–L5 · ACA / PL / ILA · STR / OLF",
    },
}
MESOSCOPE_NWB = {
    "url": (
        "https://dandiarchive.s3.amazonaws.com/blobs/"
        "bd5/3f7/bd53f709-6243-44c9-bb36-51fb0e84b234"
    ),
    "sha256": "af52b3cbb224e85bc80ab5883eab4c0b40a6be42d134bfd3b8d3e66aa8f733dd",
    "dandiUrl": "https://dandiarchive.org/dandiset/001768/draft/files",
}
MESOSCOPE_TIFF_URL = (
    "https://aind-open-data.s3.us-west-2.amazonaws.com/"
    "multiplane-ophys_832700_2026-01-29_11-18-09/pophys/"
    "1489075012_timeseries.tiff"
)
MESOSCOPE_PAGE_DATA_OFFSET = 31_530
MESOSCOPE_PAGE_STRIDE = 526_672
MESOSCOPE_PAGE_BYTES = 524_288
MESOSCOPE_FIELDS = (
    ("VISp_0", 0, 1, 152),
    ("VISp_1", 0, 0, 300),
    ("VISp_2", 1, 1, 49),
    ("VISp_3", 1, 0, 402),
    ("VISl_4", 2, 1, 149),
    ("VISl_5", 2, 0, 300),
    ("VISl_6", 3, 1, 50),
    ("VISl_7", 3, 0, 404),
)

SLAP2_ROOT = (
    "https://aind-open-data.s3.us-west-2.amazonaws.com/"
    "796630_2025-08-28_14-25-34/slap2/dynamic_data"
)
SLAP2_TRIAL_NUMBER = 26
SLAP2_EVENT_OFFSET_SECONDS = 16.1669759999495
SLAP2_PLANES = ("DMD1", "DMD2")
SLAP2_HEADER_FIELDS = (
    "firstCycleOffsetBytes",
    "lineHeaderSizeBytes",
    "laserPathIdx",
    "bytesPerCycle",
    "linesPerCycle",
    "superPixelsPerCycle",
    "dmdPixelsPerRow",
    "dmdPixelsPerColumn",
    "numChannels",
    "channelMask",
    "numSlices",
    "channelsInterleave",
    "fpgaSystemClock_Hz",
    "referenceTimestamp_lower",
    "referenceTimestamp_upper",
)
SLAP2_MAGIC_NUMBER = 322379495
SLAP2_MOVIE_FRAMES = 60
SLAP2_MICRONS_PER_PIXEL = 0.25
SLAP2_NATIVE_SIZE = (1280, 800)  # (width, height)
SLAP2_DISPLAY_SIZE = tuple(reversed(SLAP2_NATIVE_SIZE))
SLAP2_DOWNSAMPLE_FACTOR = 2

AP_EXCERPT_SECONDS = 0.1
MOVIE_FRAME_SIZE = (256, 256)
SLAP2_FRAME_SIZE = tuple(
    dimension // SLAP2_DOWNSAMPLE_FACTOR for dimension in SLAP2_NATIVE_SIZE
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--media-dir", type=Path, default=DEFAULT_MEDIA_DIR)
    return parser.parse_args()


def remote_metadata(url: str) -> dict[str, str | int | None]:
    request = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(request, timeout=60) as response:
        return {
            "contentLength": int(response.headers["Content-Length"]),
            "contentType": response.headers.get("Content-Type"),
            "etag": response.headers.get("ETag", "").strip('"'),
            "lastModified": response.headers.get("Last-Modified"),
            "url": url,
        }


def fetch_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=180) as response:
        return response.read()


def fetch_range(url: str, start: int, stop: int) -> bytes:
    request = urllib.request.Request(url, headers={"Range": f"bytes={start}-{stop - 1}"})
    with urllib.request.urlopen(request, timeout=300) as response:
        content = response.read()
        if response.status != 206 or len(content) != stop - start:
            raise RuntimeError(f"Unexpected byte-range response for {url}")
        return content


def fetch_file(url: str, output: Path) -> dict[str, str | int | None]:
    digest = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=300) as response, output.open("wb") as stream:
        while chunk := response.read(1024 * 1024):
            digest.update(chunk)
            stream.write(chunk)
    return {**remote_metadata(url), "sha256": digest.hexdigest()}


def sample_rate(times: np.ndarray) -> float:
    differences = np.diff(times)
    finite = differences[np.isfinite(differences) & (differences > 0)]
    if not len(finite):
        raise RuntimeError("Signal timestamps do not contain a positive interval.")
    return float(1.0 / np.median(finite))


def event_time(nwb: h5py.File) -> float:
    table = nwb["intervals/Sensory-motor mismatch block_presentations"]
    trial_types = np.asarray(table["TrialType"][:]).astype("U")
    mismatch_indices = np.flatnonzero(trial_types != "standard")
    return float(table["start_time"][int(mismatch_indices[0])])


def neuropixels_event(nwb: h5py.File) -> tuple[float, dict, list[dict]]:
    table = nwb[f"intervals/{NEUROPIXELS_SESSION['interval']}"]
    trial_types = np.asarray(table["TrialType"][:]).astype("U")
    mismatch_indices = np.flatnonzero(trial_types != "standard")
    if not len(mismatch_indices):
        raise RuntimeError("Neuropixels session has no nonstandard sequence event.")
    event_index = int(mismatch_indices[0])
    aligned_event = float(table["start_time"][event_index])
    starts = np.asarray(table["start_time"][:], dtype=float)
    stops = np.asarray(table["stop_time"][:], dtype=float)
    included = np.flatnonzero(
        (starts < aligned_event + WINDOW_END_SECONDS)
        & (stops >= aligned_event + WINDOW_START_SECONDS)
    )
    stimulus = []
    for index in included:
        stimulus.append(
            {
                "contrast": round(float(table["contrast"][index]), 4),
                "end": round(float(stops[index] - aligned_event), 6),
                "orientationDegrees": round(
                    math.degrees(float(table["Orientation"][index])) % 360, 3
                ),
                "phaseCycles": round(
                    float(table["phase"][index]) / (2 * math.pi), 6
                ),
                "spatialFrequency": round(
                    float(table["SpatialFrequency"][index]), 4
                ),
                "start": round(float(starts[index] - aligned_event), 6),
                "temporalFrequency": round(
                    float(table["TemporalFrequency"][index]), 4
                ),
                "trialNumber": int(float(table["TrialNumber"][index])),
                "trialType": str(trial_types[index]),
            }
        )
    event_trial_type = str(trial_types[event_index])
    event = {
        "label": event_trial_type.replace("_", " ").capitalize(),
        "time": 0.0,
        "trialNumber": int(float(table["TrialNumber"][event_index])),
    }
    return aligned_event, event, stimulus


def excerpt_stimulus(session: dict) -> list[dict]:
    session_event_time = float(session["event"]["time"])
    rows = []
    for source in session["stimulus"]:
        start = float(source["start"]) - session_event_time
        end = float(source["end"]) - session_event_time
        if start >= WINDOW_END_SECONDS or end <= WINDOW_START_SECONDS:
            continue
        row = dict(source)
        row["start"] = round(start, 6)
        row["end"] = round(end, 6)
        rows.append(row)
    return rows


def save_sprite_sheet(
    images: list[Image.Image],
    output: Path,
    columns: int,
    quality: int = 78,
    lossless: bool = False,
) -> dict[str, int | str]:
    if not images:
        raise RuntimeError(f"No frames were provided for {output.name}")
    width, height = images[0].size
    rows = math.ceil(len(images) / columns)
    sheet = Image.new("RGB", (columns * width, rows * height), (3, 8, 9))
    for index, image in enumerate(images):
        sheet.paste(image, ((index % columns) * width, (index // columns) * height))
    output.parent.mkdir(parents=True, exist_ok=True)
    save_options = {"lossless": True} if lossless else {"quality": quality}
    sheet.save(output, "WEBP", method=6, **save_options)
    return {
        "assetPath": f"media/neural-viewer/{output.name}",
        "frameHeight": height,
        "frameWidth": width,
        "sheetColumns": columns,
        "sheetRows": rows,
        "sheetSha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }


def green_movie_images(frames: np.ndarray) -> tuple[list[Image.Image], float, float]:
    low, high = np.percentile(frames, [1, 99.8])
    scaled = np.clip((frames - low) / (high - low), 0, 1)
    images = []
    for frame in scaled:
        gray = (frame * 255).astype(np.uint8)
        rgb = np.stack((gray * 0.12, gray, gray * 0.42), axis=-1).astype(np.uint8)
        image = Image.fromarray(rgb).resize(MOVIE_FRAME_SIZE, Image.Resampling.BILINEAR)
        images.append(image)
    return images, float(low), float(high)


def cortical_layer(depth_um: int) -> str:
    if depth_um < 100:
        return "L1"
    if depth_um < 300:
        return "L2/3"
    if depth_um < 400:
        return "L4"
    return "L5"


def neuropixels_channel_locations(nwb: h5py.File) -> dict[str, dict[int, str]]:
    electrodes = nwb["general/extracellular_ephys/electrodes"]
    channel_names = np.asarray(electrodes["channel_name"][:]).astype("U")
    group_names = np.asarray(electrodes["group_name"][:]).astype("U")
    locations = np.asarray(electrodes["location"][:]).astype("U")
    result = {probe_id: {} for probe_id in NEUROPIXELS_AP_STORES}
    for channel_name, group_name, location in zip(
        channel_names,
        group_names,
        locations,
        strict=True,
    ):
        if not channel_name.startswith("AP") or not channel_name[2:].isdigit():
            continue
        probe_id = group_name.removeprefix("Probe")
        if probe_id in result:
            result[probe_id][int(channel_name[2:])] = str(location)
    return result


def anatomy_segments(
    ordered_channels: np.ndarray,
    channel_locations: dict[int, str],
) -> list[dict[str, int | str]]:
    segments = []
    for row, channel in enumerate(ordered_channels):
        label = channel_locations.get(int(channel))
        if not label:
            raise RuntimeError(f"Missing CCF location for AP channel {channel}")
        if segments and segments[-1]["label"] == label:
            segments[-1]["endRow"] = row + 1
        else:
            segments.append({"endRow": row + 1, "label": label, "startRow": row})
    return segments


def extract_ap_excerpt(
    probe_id: str,
    aligned_event: float,
    channel_locations: dict[int, str],
    file_system: s3fs.S3FileSystem,
) -> tuple[dict, dict]:
    if WavPack.codec_id != "wavpack":
        raise RuntimeError("WavPack codec is not registered for AP extraction.")
    store_key = f"{NEUROPIXELS_AP_PREFIX}/{NEUROPIXELS_AP_STORES[probe_id]}"
    store = s3fs.S3Map(
        root=f"aind-open-data/{store_key}",
        s3=file_system,
        check=False,
    )
    group = zarr.open_group(store, mode="r")
    traces = group["traces_seg0"]
    timestamps = group["times_seg0"]
    sample_rate_hz = float(group.attrs["sampling_frequency"])
    estimated_sample = int(round((aligned_event - float(timestamps[0])) * sample_rate_hz))
    search_start = max(0, estimated_sample - 100)
    search_stop = min(len(timestamps), estimated_sample + 101)
    search_times = np.asarray(timestamps[search_start:search_stop], dtype=float)
    event_sample = search_start + int(np.searchsorted(search_times, aligned_event))
    excerpt_samples = int(round(AP_EXCERPT_SECONDS * sample_rate_hz))
    first = event_sample - excerpt_samples // 2
    last = first + excerpt_samples
    times = np.asarray(timestamps[first:last], dtype=float)
    source_channels = np.arange(0, traces.shape[1], 4)
    raw = np.asarray(traces[first:last, ::4], dtype=np.int16)
    gains_uv = np.asarray(group["properties/gain_to_uV"][::4], dtype=float)
    depths = np.asarray(group["properties/location"][::4, 1], dtype=float)
    if raw.shape != (excerpt_samples, len(depths)):
        raise RuntimeError(f"Unexpected AP excerpt shape for Probe {probe_id}: {raw.shape}")
    values_uv = raw * gains_uv
    depth_order = np.argsort(depths)[::-1]
    shaft_uv = values_uv[:, depth_order].T
    value_limit = float(np.percentile(np.abs(shaft_uv), 99.9))
    ordered_channels = source_channels[depth_order]
    quantized = np.rint(
        (np.clip(shaft_uv, -value_limit, value_limit) + value_limit)
        / (2 * value_limit)
        * 255
    ).astype(np.uint8)

    attrs_url = (
        "https://aind-open-data.s3.us-west-2.amazonaws.com/"
        f"{quote(store_key, safe='/')}/.zattrs"
    )
    source = {
        **remote_metadata(attrs_url),
        "dataExcerptSha256": hashlib.sha256(raw.tobytes()).hexdigest(),
        "fileFormat": "Zarr v2 with WavPack compression",
        "probe": probe_id,
        "sampleStart": first,
        "sampleStop": last,
        "storeUrl": (
            "https://aind-open-data.s3.us-west-2.amazonaws.com/"
            f"{quote(store_key, safe='/')}"
        ),
    }
    excerpt = {
        "anatomySegments": anatomy_segments(ordered_channels, channel_locations),
        "columns": quantized.shape[1],
        "dataBase64": base64.b64encode(quantized.tobytes()).decode(),
        "depthMaxUm": round(float(depths.max()), 3),
        "depthMinUm": round(float(depths.min()), 3),
        "nativeSampleRateHz": round(sample_rate_hz, 6),
        "rows": quantized.shape[0],
        "sourceChannels": ordered_channels.astype(int).tolist(),
        "timeEndSeconds": round(float(times[-1] - aligned_event), 9),
        "timeStartSeconds": round(float(times[0] - aligned_event), 9),
        "valueLimit": round(value_limit, 6),
    }
    return excerpt, source


def extract_neuropixels() -> dict:
    options = []
    ap_sources = []
    file_system = s3fs.S3FileSystem(anon=True)
    with closing(remfile.File(NEUROPIXELS_NWB["url"])) as remote:
        with h5py.File(remote, mode="r") as nwb:
            aligned_event, event, stimulus = neuropixels_event(nwb)
            channel_locations = neuropixels_channel_locations(nwb)
            for probe_id in sorted(NEUROPIXELS_AP_STORES):
                anatomy = NEUROPIXELS_ANATOMY[probe_id]
                ap_excerpt, ap_source = extract_ap_excerpt(
                    probe_id,
                    aligned_event,
                    channel_locations[probe_id],
                    file_system,
                )
                ap_sources.append(ap_source)
                options.append(
                    {
                        **ap_excerpt,
                        "anatomyLabel": anatomy["summary"],
                        "id": f"probe-{probe_id.lower()}",
                        "label": f"Probe {probe_id} · {anatomy['selector']}",
                    }
                )
    return {
        "alignment": (
            "The raw AP acquisition timestamps and stimulus intervals share the "
            "synchronized acquisition clock. Each display matrix contains unaveraged "
            "30-kHz samples from 96 regularly spaced shaft contacts during the 100-ms "
            "event-centered excerpt. CCF structure and layer boundaries come from the "
            "NWB electrode-location annotations."
        ),
        "context": NEUROPIXELS_SESSION["context"],
        "event": event,
        "id": "neuropixels",
        "label": "Neuropixels",
        "optionLabel": "Probe",
        "options": options,
        "session": NEUROPIXELS_SESSION["session"],
        "signalLabel": "Raw AP acquisition voltage",
        "signalUnit": "uV",
        "sourceLinks": [
            {"label": "DANDI:001637", "url": NEUROPIXELS_NWB["dandiUrl"]},
            {
                "label": "Raw S3 session",
                "url": (
                    "https://open.quiltdata.com/b/aind-open-data/tree/"
                    f"{NEUROPIXELS_SESSION['session']}/"
                ),
            },
        ],
        "sources": [
            {"sha256": NEUROPIXELS_NWB["sha256"], "url": NEUROPIXELS_NWB["url"]},
            *ap_sources,
        ],
        "stimulus": stimulus,
        "subject": NEUROPIXELS_SESSION["subject"],
        "viewType": "heatmap",
    }


def extract_mesoscope(session: dict, media_dir: Path) -> dict:
    options = []
    selections = []
    with closing(remfile.File(MESOSCOPE_NWB["url"])) as remote:
        with h5py.File(remote, mode="r") as nwb:
            aligned_event = event_time(nwb)
            for plane, phase, channel, depth in MESOSCOPE_FIELDS:
                grid_spacing = nwb[f"general/optophysiology/{plane}/grid_spacing"]
                unit = grid_spacing.attrs.get("unit", "")
                if isinstance(unit, bytes):
                    unit = unit.decode()
                spacing = np.asarray(grid_spacing[:], dtype=float)
                if (
                    unit != "micrometer"
                    or spacing.shape != (2,)
                    or not np.allclose(spacing, spacing[0])
                ):
                    raise RuntimeError(f"Unsupported spatial calibration: {plane}")
                timestamps = np.asarray(
                    nwb[f"processing/{plane}/dff_timeseries/dff_timeseries/timestamps"][:],
                    dtype=float,
                )
                indices = np.flatnonzero(
                    (timestamps >= aligned_event + WINDOW_START_SECONDS)
                    & (timestamps < aligned_event + WINDOW_END_SECONDS)
                )
                pages = (indices * 4 + phase) * 2 + channel
                selections.append(
                    (
                        plane,
                        phase,
                        channel,
                        depth,
                        timestamps,
                        indices,
                        float(spacing[0]),
                        pages,
                    )
                )

    all_pages = np.concatenate([selection[-1] for selection in selections])
    first_page = int(all_pages.min())
    last_page = int(all_pages.max())
    range_start = MESOSCOPE_PAGE_DATA_OFFSET + first_page * MESOSCOPE_PAGE_STRIDE
    range_stop = (
        MESOSCOPE_PAGE_DATA_OFFSET
        + last_page * MESOSCOPE_PAGE_STRIDE
        + MESOSCOPE_PAGE_BYTES
    )
    excerpt = fetch_range(MESOSCOPE_TIFF_URL, range_start, range_stop)
    for (
        plane,
        phase,
        channel,
        depth,
        timestamps,
        indices,
        microns_per_pixel,
        pages,
    ) in selections:
        frames = []
        for page in pages:
            offset = (
                MESOSCOPE_PAGE_DATA_OFFSET
                + int(page) * MESOSCOPE_PAGE_STRIDE
                - range_start
            )
            frames.append(
                np.frombuffer(
                    excerpt,
                    dtype="<i2",
                    count=512 * 512,
                    offset=offset,
                ).reshape(512, 512)
            )
        frame_array = np.stack(frames)
        images, contrast_low, contrast_high = green_movie_images(frame_array)
        filename = f"mesoscope-{plane.lower().replace('_', '-')}.webp"
        sprite = save_sprite_sheet(images, media_dir / filename, columns=8)
        area = plane.split("_")[0]
        layer = cortical_layer(depth)
        options.append(
            {
                **sprite,
                "anatomyLabel": f"{area} · {layer} · {depth} µm",
                "channel": channel + 1,
                "contrastHigh": round(contrast_high, 6),
                "contrastLow": round(contrast_low, 6),
                "frameCount": len(images),
                "frameRateHz": round(sample_rate(timestamps[indices]), 6),
                "frameTimes": np.round(timestamps[indices] - aligned_event, 6).tolist(),
                "id": plane.lower(),
                "imagingDepthUm": depth,
                "label": f"{plane.replace('_', ' ')} · {layer} · {depth} µm",
                "micronsPerPixel": round(microns_per_pixel, 6),
                "nativeHeight": 512,
                "nativeWidth": 512,
                "phase": phase + 1,
                "targetArea": area,
                "targetLayer": layer,
            }
        )
    tiff_source = {
        **remote_metadata(MESOSCOPE_TIFF_URL),
        "fileFormat": "ScanImage BigTIFF",
        "pageBytes": MESOSCOPE_PAGE_BYTES,
        "pageDataOffset": MESOSCOPE_PAGE_DATA_OFFSET,
        "pageStride": MESOSCOPE_PAGE_STRIDE,
        "rangeSha256": hashlib.sha256(excerpt).hexdigest(),
        "rangeStart": range_start,
        "rangeStop": range_stop,
    }
    return {
        "alignment": (
            "Raw ScanImage page indices are mapped to synchronized NWB plane timestamps. "
            "The source pages are uncompressed 512 x 512 int16 frames; WebP sheets retain "
            "the event-centered frames for browser playback. NWB grid spacing calibrates "
            "each native pixel in micrometers."
        ),
        "context": session["context"],
        "event": {**session["event"], "time": 0.0},
        "id": "mesoscope",
        "label": "Mesoscope",
        "optionLabel": "Raw field",
        "options": options,
        "session": session["session"],
        "signalLabel": "Raw two-photon frames",
        "signalUnit": "detector counts",
        "sourceLinks": [
            {"label": "DANDI:001768", "url": MESOSCOPE_NWB["dandiUrl"]},
            *session["sourceLinks"],
        ],
        "sources": [
            {"sha256": MESOSCOPE_NWB["sha256"], "url": MESOSCOPE_NWB["url"]},
            tiff_source,
        ],
        "stimulus": excerpt_stimulus(session),
        "subject": session["subject"],
        "viewType": "movie",
    }


def parse_slap2_header(blob: bytes, content_length: int) -> dict[str, int]:
    raw = np.frombuffer(blob, dtype="<u4")
    if int(raw[0]) != SLAP2_MAGIC_NUMBER or int(raw[1]) != 2:
        raise RuntimeError("Unsupported SLAP2 data-file header.")
    header_entries = int(raw[2]) // 4
    pairs = raw[3 : header_entries - 1].reshape(-1, 2)
    header = {
        SLAP2_HEADER_FIELDS[int(key)]: int(value)
        for key, value in pairs
        if int(key) < len(SLAP2_HEADER_FIELDS)
    }
    available = content_length - header["firstCycleOffsetBytes"]
    cycles, remainder = divmod(available, header["bytesPerCycle"])
    if remainder:
        raise RuntimeError("SLAP2 data file does not contain complete cycles.")
    header["numCycles"] = cycles
    return header


def matlab_scalar(metadata: h5py.File, name: str) -> float:
    value = np.asarray(metadata[name][()]).reshape(-1)
    if not len(value):
        raise RuntimeError(f"SLAP2 metadata field is empty: {name}")
    return float(value[0])


def slap2_line_plan(
    cycle: bytes,
    header: dict[str, int],
    metadata: h5py.File,
) -> tuple[list[tuple[int, int]], np.ndarray, np.ndarray]:
    references = metadata["AcquisitionContainer/AcquisitionPlan/superPixelIDs"][...].flat
    line_ids = [
        np.asarray(metadata[reference][()]).reshape(-1).astype(int)
        for reference in references
    ]
    specifications = []
    ids = []
    cursor = 0
    for index in range(header["linesPerCycle"]):
        line_size = int(np.frombuffer(cycle, dtype="<u2", count=1, offset=cursor)[0])
        count = (line_size - header["lineHeaderSizeBytes"]) // 2 // header["numChannels"]
        specifications.append((cursor + header["lineHeaderSizeBytes"], count))
        if count:
            if len(line_ids[index]) != count:
                raise RuntimeError("SLAP2 line samples do not match superpixel IDs.")
            ids.extend(line_ids[index].tolist())
        cursor += line_size
    if cursor != header["bytesPerCycle"]:
        raise RuntimeError("SLAP2 cycle layout does not match its file header.")
    ids_array = np.asarray(ids, dtype=int)
    counts = np.bincount(ids_array, minlength=1280 * 800)
    return specifications, ids_array, counts


def slap2_sparse_frame(
    cycle: bytes,
    specifications: list[tuple[int, int]],
    ids: np.ndarray,
    counts: np.ndarray,
    channel: int,
) -> np.ndarray:
    parts = []
    for data_start, count in specifications:
        if not count:
            continue
        parts.append(
            np.frombuffer(
                cycle,
                dtype="<i2",
                count=count,
                offset=data_start + channel * count * 2,
            )
        )
    values = np.concatenate(parts).astype(float)
    sums = np.bincount(ids, weights=values, minlength=len(counts))
    flat = np.zeros(len(counts), dtype=float)
    valid = counts > 0
    flat[valid] = sums[valid] / counts[valid]
    native_width, native_height = SLAP2_NATIVE_SIZE
    frame = flat.reshape((native_width, native_height), order="F").T
    frame_width, frame_height = SLAP2_FRAME_SIZE
    factor = SLAP2_DOWNSAMPLE_FACTOR
    downsampled = np.max(
        frame.reshape((frame_height, factor, frame_width, factor)), axis=(1, 3)
    )
    return slap2_display_frame(downsampled)


def slap2_display_frame(frame: np.ndarray) -> np.ndarray:
    # NumPy arrays are (height, width); this yields a 400 x 640 portrait image.
    return np.ascontiguousarray(frame.T)


def slap2_overlay_images(
    frames: np.ndarray,
    background: np.ndarray,
    channel: int,
) -> tuple[list[Image.Image], float, float]:
    acquired = frames != 0
    low, high = np.percentile(frames[acquired], [1, 99.5])
    background_low, background_high = np.percentile(background, [1, 99.8])
    context = np.clip(
        (background - background_low) / (background_high - background_low), 0, 1
    )
    colors = ((0, 220, 255), (255, 86, 185))
    color = colors[channel]
    images = []
    for frame, mask in zip(frames, acquired, strict=True):
        dynamic = np.clip((frame - low) / (high - low), 0, 1)
        rgb = np.stack((context * 45, context * 58, context * 63), axis=-1)
        for component, target in enumerate(color):
            rgb[..., component] = np.where(
                mask,
                rgb[..., component] * (1 - dynamic) + target * dynamic,
                rgb[..., component],
            )
        images.append(Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)))
    return images, float(low), float(high)


def slap2_composite_images(
    green_frames: np.ndarray,
    red_frames: np.ndarray,
    background: np.ndarray,
) -> list[Image.Image]:
    channel_frames = (green_frames, red_frames)
    channel_masks = tuple(frames != 0 for frames in channel_frames)
    channel_ranges = tuple(
        np.percentile(frames[mask], [1, 99.5])
        for frames, mask in zip(channel_frames, channel_masks, strict=True)
    )
    background_low, background_high = np.percentile(background, [1, 99.8])
    context = np.clip(
        (background - background_low) / (background_high - background_low), 0, 1
    )
    images = []
    for green, red, green_mask, red_mask in zip(
        green_frames,
        red_frames,
        channel_masks[0],
        channel_masks[1],
        strict=True,
    ):
        green_low, green_high = channel_ranges[0]
        red_low, red_high = channel_ranges[1]
        green_signal = np.clip((green - green_low) / (green_high - green_low), 0, 1)
        red_signal = np.clip((red - red_low) / (red_high - red_low), 0, 1)
        rgb = np.repeat((context * 52)[..., np.newaxis], 3, axis=-1)
        rgb[..., 0] = np.where(
            red_mask,
            rgb[..., 0] * (1 - red_signal) + 255 * red_signal,
            rgb[..., 0],
        )
        rgb[..., 1] = np.where(
            green_mask,
            rgb[..., 1] * (1 - green_signal) + 255 * green_signal,
            rgb[..., 1],
        )
        combined_signal = np.maximum(green_signal, red_signal)
        combined_mask = green_mask | red_mask
        rgb[..., 2] = np.where(
            combined_mask,
            rgb[..., 2] * (1 - combined_signal),
            rgb[..., 2],
        )
        images.append(Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)))
    return images


def extract_slap2_plane(plane: str, media_dir: Path) -> tuple[list[dict], list[dict]]:
    stem = f"activity_20250828_142403_{plane}"
    data_url = f"{SLAP2_ROOT}/{stem}-TRIAL{SLAP2_TRIAL_NUMBER:06d}.dat"
    metadata_url = f"{SLAP2_ROOT}/{stem}.meta"
    annotation_url = f"{SLAP2_ROOT}/{stem}.annotation.json"
    reference_url = (
        f"{SLAP2_ROOT}/reference_stack/refStack_20250828_140250_{plane}-REFERENCE.tif"
    )
    data_source = remote_metadata(data_url)
    metadata_source = remote_metadata(metadata_url)
    header_blob = fetch_range(data_url, 0, min(1_048_576, data_source["contentLength"]))
    header = parse_slap2_header(header_blob, int(data_source["contentLength"]))
    metadata_blob = fetch_bytes(metadata_url)
    annotation_blob = fetch_bytes(annotation_url)
    annotation = json.loads(annotation_blob)
    with h5py.File(io.BytesIO(metadata_blob), mode="r") as metadata:
        line_period = matlab_scalar(metadata, "linePeriod_s")
        cycle_duration = line_period * header["linesPerCycle"]
        first_cycle = max(
            0,
            math.floor(
                (SLAP2_EVENT_OFFSET_SECONDS + WINDOW_START_SECONDS) / cycle_duration
            ),
        )
        last_cycle = min(
            header["numCycles"],
            math.ceil(
                (SLAP2_EVENT_OFFSET_SECONDS + WINDOW_END_SECONDS) / cycle_duration
            ),
        )
        range_start = (
            header["firstCycleOffsetBytes"] + first_cycle * header["bytesPerCycle"]
        )
        range_stop = (
            header["firstCycleOffsetBytes"] + last_cycle * header["bytesPerCycle"]
        )
        excerpt = fetch_range(data_url, range_start, range_stop)
        specifications, ids, counts = slap2_line_plan(
            excerpt[: header["bytesPerCycle"]], header, metadata
        )

    selected = np.linspace(0, last_cycle - first_cycle - 1, SLAP2_MOVIE_FRAMES)
    selected = np.unique(np.rint(selected).astype(int))
    frames_by_channel = [[], []]
    for local_cycle in selected:
        start = local_cycle * header["bytesPerCycle"]
        stop = start + header["bytesPerCycle"]
        cycle = excerpt[start:stop]
        for channel in range(header["numChannels"]):
            frames_by_channel[channel].append(
                slap2_sparse_frame(
                    cycle, specifications, ids, counts, channel
                )
            )

    with tempfile.NamedTemporaryFile(suffix=".tif") as reference_file:
        reference_source = fetch_file(reference_url, Path(reference_file.name))
        reference = tifffile.imread(reference_file.name).max(axis=0)
    frame_width, frame_height = SLAP2_FRAME_SIZE
    factor = SLAP2_DOWNSAMPLE_FACTOR
    background = slap2_display_frame(
        reference.reshape(frame_height, factor, frame_width, factor).mean(axis=(1, 3))
    )
    cycle_indices = first_cycle + selected.astype(float) + 0.5
    frame_times = cycle_indices * cycle_duration - SLAP2_EVENT_OFFSET_SECONDS
    options = []
    measurements = (
        annotation["intended_green_channel_target"],
        annotation["intended_red_channel_target"],
    )
    colors = ("green", "red")
    frame_arrays = tuple(np.stack(frames) for frames in frames_by_channel)
    composite_images = slap2_composite_images(*frame_arrays, background)
    composite_filename = f"slap2-{plane.lower()}-composite.webp"
    composite_sprite = save_sprite_sheet(
        composite_images,
        media_dir / composite_filename,
        columns=10,
        lossless=True,
    )
    for channel, frame_array in enumerate(frame_arrays):
        images, contrast_low, contrast_high = slap2_overlay_images(
            frame_array, background, channel
        )
        filename = f"slap2-{plane.lower()}-detector-{channel + 1}.webp"
        sprite = save_sprite_sheet(
            images,
            media_dir / filename,
            columns=10,
            lossless=True,
        )
        options.append(
            {
                **sprite,
                "anatomyLabel": (
                    f"{plane} · {annotation['targeted_structure']} L2/3 · "
                    f"{abs(annotation['pia_depth_on_remote_focus_um']):g} µm below pia · "
                    f"{measurements[channel]}"
                ),
                "channelColor": colors[channel],
                "compositeAssetPath": composite_sprite["assetPath"],
                "compositeSheetSha256": composite_sprite["sheetSha256"],
                "contrastHigh": round(contrast_high, 6),
                "contrastLow": round(contrast_low, 6),
                "detectorChannel": channel + 1,
                "displayTransform": "transpose-for-publication",
                "fastScanAxis": "vertical",
                "frameCount": len(images),
                "frameRateHz": round(len(images) / (WINDOW_END_SECONDS - WINDOW_START_SECONDS), 6),
                "frameTimes": np.round(frame_times, 6).tolist(),
                "id": f"{plane.lower()}-detector-{channel + 1}",
                "label": (
                    f"{plane} · {annotation['targeted_structure']} L2/3 · "
                    f"{abs(annotation['pia_depth_on_remote_focus_um']):g} µm below pia · "
                    f"{measurements[channel]}"
                ),
                "measurement": measurements[channel],
                "micronsPerPixel": SLAP2_MICRONS_PER_PIXEL,
                "displayHeight": SLAP2_DISPLAY_SIZE[1],
                "displayWidth": SLAP2_DISPLAY_SIZE[0],
                "nativeHeight": SLAP2_NATIVE_SIZE[1],
                "nativeWidth": SLAP2_NATIVE_SIZE[0],
                "recordedPixels": int(np.count_nonzero(counts)),
                "remoteFocusDepthBelowPiaUm": abs(
                    annotation["pia_depth_on_remote_focus_um"]
                ),
                "spatialDownsampleFactor": SLAP2_DOWNSAMPLE_FACTOR,
                "spriteEncoding": "lossless WebP",
                "storedHeight": SLAP2_NATIVE_SIZE[1],
                "storedWidth": SLAP2_NATIVE_SIZE[0],
                "structureType": "dendrite",
                "targetArea": annotation["targeted_structure"],
                "targetLayer": "L2/3",
            }
        )
    sources = [
        {
            **data_source,
            "fileFormatVersion": 2,
            "rangeSha256": hashlib.sha256(excerpt).hexdigest(),
            "rangeStart": range_start,
            "rangeStop": range_stop,
            "trialNumber": SLAP2_TRIAL_NUMBER,
        },
        {**metadata_source, "sha256": hashlib.sha256(metadata_blob).hexdigest()},
        {
            **remote_metadata(annotation_url),
            "sha256": hashlib.sha256(annotation_blob).hexdigest(),
        },
        reference_source,
    ]
    return options, sources


def extract_slap2(session: dict, media_dir: Path) -> dict:
    options = []
    sources = []
    for plane in SLAP2_PLANES:
        plane_options, plane_sources = extract_slap2_plane(plane, media_dir)
        options.extend(plane_options)
        sources.extend(plane_sources)
    return {
        "alignment": (
            "The selected Harp event falls 16.167 s after the start pulse for raw "
            "acquisition trial 26. Each movie frame maps native detector samples onto "
            "the acquisition-plan superpixel IDs; the dim structural reference supplies "
            "unrecorded spatial context. The reconstructed acquisition raster is "
            "transposed for publication display, placing the fast-scanning x axis "
            "vertically; each native DMD pixel spans 0.25 micrometers."
        ),
        "context": session["context"],
        "event": {**session["event"], "time": 0.0},
        "id": "slap2",
        "label": "SLAP2",
        "optionLabel": "Raw field",
        "options": options,
        "session": session["session"],
        "signalLabel": "Sparse raw detector frames",
        "signalUnit": "detector counts",
        "sourceLinks": session["sourceLinks"],
        "sources": sources,
        "stimulus": excerpt_stimulus(session),
        "subject": session["subject"],
        "viewType": "movie",
    }


def main() -> None:
    args = parse_args()
    behavior_bytes = BEHAVIOR_PATH.read_bytes()
    behavior = json.loads(behavior_bytes)
    sessions = {session["id"]: session for session in behavior["sessions"]}
    if set(sessions) != {"neuropixels", "mesoscope", "slap2"}:
        raise RuntimeError("Behavior excerpts do not contain all three modalities.")

    args.media_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="neural-viewer-media-", dir=args.media_dir.parent
    ) as temporary_directory:
        temporary_media = Path(temporary_directory)
        payload = {
            "behaviorExcerptSha256": hashlib.sha256(behavior_bytes).hexdigest(),
            "retrievedDate": RETRIEVED_DATE,
            "sessions": [
                extract_neuropixels(),
                extract_mesoscope(sessions["mesoscope"], temporary_media),
                extract_slap2(sessions["slap2"], temporary_media),
            ],
            "version": 8,
            "windowEndSeconds": WINDOW_END_SECONDS,
            "windowStartSeconds": WINDOW_START_SECONDS,
        }
        if args.media_dir.exists():
            shutil.rmtree(args.media_dir)
        shutil.copytree(temporary_media, args.media_dir)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {args.output} and {len(list(args.media_dir.glob('*.webp')))} movie sheets"
    )


if __name__ == "__main__":
    main()