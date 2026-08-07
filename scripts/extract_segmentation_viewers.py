#!/usr/bin/env python3
"""Extract compact segmentation-viewer snapshots from representative NWBs."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.request import urlopen

try:
    import h5py
    import numpy as np
    import remfile
    from PIL import Image
except ImportError as exc:  # pragma: no cover - optional extraction environment
    raise SystemExit(
        "Run with: uv run --with h5py --with numpy --with remfile "
        "--with pillow==12.3.0 python scripts/extract_segmentation_viewers.py"
    ) from exc


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "figure_sources" / "data" / "segmentation-viewers.json"
DEFAULT_PROVENANCE = DEFAULT_OUTPUT.with_suffix(".provenance.json")
DEFAULT_MEDIA_DIR = REPO_ROOT / "figure_sources" / "media" / "segmentation-viewers"
RAW_NEURAL_PATH = REPO_ROOT / "figure_sources" / "data" / "raw-neural-excerpts.json"
RETRIEVED_DATE = "2026-08-06"
TRACE_WINDOW_START_SECONDS = -2.0
TRACE_WINDOW_END_SECONDS = 10.0
CALCIUM_TRACE_WINDOW_SECONDS = 30.0
NEUROPIXELS_BIN_SECONDS = 0.02
NEUROPIXELS_PROBES = tuple(f"Probe{probe}" for probe in "ABCDEF")
NEUROPIXELS_UNIT_COUNTS = {
    "ProbeA": 569,
    "ProbeB": 502,
    "ProbeC": 534,
    "ProbeD": 799,
    "ProbeE": 542,
    "ProbeF": 604,
}
MESOSCOPE_PLANES = (
    "VISp_0",
    "VISp_1",
    "VISp_2",
    "VISp_3",
    "VISl_4",
    "VISl_5",
    "VISl_6",
    "VISl_7",
)
MESOSCOPE_ROI_COUNTS = {
    "VISp_0": 399,
    "VISp_1": 463,
    "VISp_2": 70,
    "VISp_3": 277,
    "VISl_4": 374,
    "VISl_5": 356,
    "VISl_6": 124,
    "VISl_7": 321,
}
SLAP2_PLANES = ("DMD1", "DMD2")
SLAP2_SOURCE_COUNTS = {"DMD1": 45, "DMD2": 74}
MEDIA_ASSET_ROOT = "media/segmentation-viewers"
FILTER_COLORS = (
    (37, 170, 225),
    (140, 198, 63),
    (204, 175, 45),
    (214, 92, 72),
    (36, 188, 173),
    (177, 96, 173),
)


@dataclass(frozen=True)
class DandiAsset:
    dandiset_id: str
    asset_id: str
    path: str
    url: str
    sha256: str

    @property
    def api_url(self) -> str:
        return f"https://api.dandiarchive.org/api/assets/{self.asset_id}/"

    @property
    def dandiset_url(self) -> str:
        return f"https://dandiarchive.org/dandiset/{self.dandiset_id}/draft/files"


ASSETS = {
    "neuropixels": DandiAsset(
        dandiset_id="001637",
        asset_id="03973a42-cf55-476f-80d7-85bc402fa57b",
        path=(
            "sub-830846/"
            "sub-830846_ses-ecephys-830846-2026-03-09-10-32-54_ecephys.nwb"
        ),
        url=(
            "https://dandiarchive.s3.amazonaws.com/blobs/"
            "1a3/a02/1a3a0214-c40e-49ed-9ada-9379c9fca1e8"
        ),
        sha256="75c425992a9443a6b7bb19b00469469788d6be4dd8c721714d0692e214fe7bf9",
    ),
    "mesoscope": DandiAsset(
        dandiset_id="001768",
        asset_id="ab44a0f7-2864-4a30-8988-0b76aec28fa6",
        path=(
            "sub-832700/"
            "sub-832700_ses-multiplane-ophys-832700-2026-01-29-11-18-09_ophys.nwb"
        ),
        url=(
            "https://dandiarchive.s3.amazonaws.com/blobs/"
            "bd5/3f7/bd53f709-6243-44c9-bb36-51fb0e84b234"
        ),
        sha256="af52b3cbb224e85bc80ab5883eab4c0b40a6be42d134bfd3b8d3e66aa8f733dd",
    ),
    "slap2": DandiAsset(
        dandiset_id="001424",
        asset_id="1b6509ef-70d7-46e4-9c8e-587bb6ace95f",
        path=(
            "sub-796630/"
            "sub-796630_ses-SLAP2-796630-2025-08-28-14-25-34_image+ophys.nwb"
        ),
        url=(
            "https://dandiarchive.s3.amazonaws.com/blobs/"
            "e95/21c/e9521c86-5587-473c-990d-ed432bb65d28"
        ),
        sha256="af8798fbd52184adfce210ad1e6442c49dfc3488f1195062b48d00f25e3206b6",
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE)
    parser.add_argument("--media-dir", type=Path, default=DEFAULT_MEDIA_DIR)
    return parser.parse_args()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def encode_float32(values: np.ndarray) -> str:
    packed = np.asarray(values, dtype="<f4", order="C")
    return base64.b64encode(packed.tobytes()).decode()


def decode_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


def validate_asset(asset: DandiAsset) -> dict:
    with urlopen(asset.api_url, timeout=60) as response:
        metadata = json.load(response)
    actual_sha256 = metadata["digest"]["dandi:sha2-256"]
    if metadata["path"] != asset.path or actual_sha256 != asset.sha256:
        raise RuntimeError(f"DANDI asset metadata changed: {asset.asset_id}")
    if asset.url not in metadata["contentUrl"]:
        raise RuntimeError(f"DANDI asset content URL changed: {asset.asset_id}")
    return {
        **asdict(asset),
        "api_url": asset.api_url,
        "content_size": metadata["contentSize"],
        "dandiset_url": asset.dandiset_url,
    }


def normalize(values: np.ndarray, low_percentile: float, high_percentile: float) -> np.ndarray:
    finite = np.asarray(values, dtype=float)
    valid = finite[np.isfinite(finite)]
    if not len(valid):
        raise RuntimeError("Image contains no finite values.")
    low, high = np.percentile(valid, [low_percentile, high_percentile])
    if high <= low:
        raise RuntimeError("Image contrast range is empty.")
    finite = np.nan_to_num(finite, nan=low, posinf=high, neginf=low)
    return np.clip((finite - low) / (high - low), 0, 1)


def grayscale(values: np.ndarray) -> np.ndarray:
    scaled = normalize(values, 1, 99.5)
    gray = np.rint(8 + scaled * 239).astype(np.uint8)
    return np.repeat(gray[..., np.newaxis], 3, axis=-1)


def encoded_label_image(labels: np.ndarray) -> np.ndarray:
    labels = np.asarray(labels, dtype=np.uint32)
    return np.stack(
        (
            labels & 255,
            (labels >> 8) & 255,
            (labels >> 16) & 255,
        ),
        axis=-1,
    ).astype(np.uint8)


def boundary_overlay(labels: np.ndarray) -> np.ndarray:
    labels = np.asarray(labels, dtype=np.uint32)
    boundary = np.zeros(labels.shape, dtype=bool)
    boundary[1:, :] |= labels[1:, :] != labels[:-1, :]
    boundary[:-1, :] |= labels[:-1, :] != labels[1:, :]
    boundary[:, 1:] |= labels[:, 1:] != labels[:, :-1]
    boundary[:, :-1] |= labels[:, :-1] != labels[:, 1:]
    boundary &= labels > 0
    rgba = np.zeros((*labels.shape, 4), dtype=np.uint8)
    for index, color in enumerate(FILTER_COLORS):
        selected = boundary & (((labels - 1) % len(FILTER_COLORS)) == index)
        rgba[selected, :3] = color
    rgba[boundary, 3] = 255
    return rgba


def save_png(array: np.ndarray, output: Path) -> dict[str, str | int]:
    output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(array).save(output, format="PNG", compress_level=9)
    return {
        "assetPath": f"{MEDIA_ASSET_ROOT}/{output.name}",
        "height": int(array.shape[0]),
        "sha256": sha256(output),
        "width": int(array.shape[1]),
    }


def filter_geometry(labels: np.ndarray, filter_count: int) -> list[dict[str, float | int]]:
    flat = np.asarray(labels, dtype=np.int64).ravel()
    y_coordinates, x_coordinates = np.indices(labels.shape)
    counts = np.bincount(flat, minlength=filter_count + 1)
    x_sums = np.bincount(
        flat,
        weights=x_coordinates.ravel(),
        minlength=filter_count + 1,
    )
    y_sums = np.bincount(
        flat,
        weights=y_coordinates.ravel(),
        minlength=filter_count + 1,
    )
    result = []
    for label in range(1, filter_count + 1):
        if not counts[label]:
            raise RuntimeError(f"Filter {label} contains no display pixels.")
        result.append(
            {
                "centroidX": round(float(x_sums[label] / counts[label]), 3),
                "centroidY": round(float(y_sums[label] / counts[label]), 3),
                "pixelCount": int(counts[label]),
            }
        )
    return result


def trace_payload(
    values: np.ndarray,
    times: np.ndarray,
) -> dict[str, int | list[float] | str]:
    if values.ndim != 2 or values.shape[1] != len(times):
        raise RuntimeError("Trace matrix must be filters by time.")
    return {
        "traceColumns": int(values.shape[1]),
        "traceDataBase64": encode_float32(values),
        "traceRows": int(values.shape[0]),
        "traceTimesSeconds": np.round(times, 6).tolist(),
    }


def first_mismatch_event(nwb: h5py.File, table_name: str) -> tuple[float, str]:
    table = nwb[f"intervals/{table_name}"]
    trial_types = np.asarray(table["TrialType"][:]).astype("U")
    mismatch = np.flatnonzero(trial_types != "standard")
    if not len(mismatch):
        raise RuntimeError(f"No mismatch event found in {table_name}.")
    index = int(mismatch[0])
    return float(table["start_time"][index]), str(trial_types[index])


def raw_session_options(modality: str) -> tuple[dict[str, dict], str]:
    source_bytes = RAW_NEURAL_PATH.read_bytes()
    payload = json.loads(source_bytes)
    session = next(item for item in payload["sessions"] if item["id"] == modality)
    return (
        {option["id"]: option for option in session["options"]},
        hashlib.sha256(source_bytes).hexdigest(),
    )


def raw_probe_excerpt(option: dict) -> dict:
    return {
        "rawColumns": int(option["columns"]),
        "rawDataBase64": option["dataBase64"],
        "rawDepthMaxUm": round(float(option["depthMaxUm"]), 3),
        "rawDepthMinUm": round(float(option["depthMinUm"]), 3),
        "rawRows": int(option["rows"]),
        "rawSourceChannels": [int(channel) for channel in option["sourceChannels"]],
        "rawTimeEndMs": round(
            (float(option["timeEndSeconds"]) - float(option["timeStartSeconds"]))
            * 1000,
            6,
        ),
        "rawTimeStartMs": 0.0,
        "rawValueLimitUv": round(float(option["valueLimit"]), 6),
        "sourceTimeEndSeconds": float(option["timeEndSeconds"]),
        "sourceTimeStartSeconds": float(option["timeStartSeconds"]),
    }


def extract_neuropixels(asset_record: dict) -> dict:
    asset = ASSETS["neuropixels"]
    raw_options, raw_excerpt_sha256 = raw_session_options("neuropixels")
    sources = []
    with closing(remfile.File(asset.url)) as remote, h5py.File(remote, "r") as nwb:
        units = nwb["units"]
        device_names = np.asarray(units["device_name"][:]).astype("U")
        event_time, _ = first_mismatch_event(
            nwb,
            "Sequence mismatch block_presentations",
        )
        trace_window_start = event_time + TRACE_WINDOW_START_SECONDS
        bin_edges = np.arange(
            trace_window_start,
            event_time + TRACE_WINDOW_END_SECONDS + NEUROPIXELS_BIN_SECONDS / 2,
            NEUROPIXELS_BIN_SECONDS,
        )
        bin_times = (bin_edges[:-1] + bin_edges[1:]) / 2 - trace_window_start
        electrode_table = nwb["general/extracellular_ephys/electrodes"]
        electrode_ends = np.asarray(units["electrodes_index"][:], dtype=int)
        electrode_refs = np.asarray(units["electrodes"][:], dtype=int)
        spike_ends = np.asarray(units["spike_times_index"][:], dtype=int)
        waveform_unit = decode_text(units["waveform_mean"].attrs["unit"])

        for probe_name in NEUROPIXELS_PROBES:
            probe_letter = probe_name.removeprefix("Probe")
            source_id = f"probe-{probe_letter.lower()}"
            option = raw_options[source_id]
            raw_excerpt = raw_probe_excerpt(option)
            rows = np.flatnonzero(device_names == probe_name)
            if len(rows) != NEUROPIXELS_UNIT_COUNTS[probe_name]:
                raise RuntimeError(f"Representative {probe_name} unit inventory changed.")
            spike_rates = np.empty((len(rows), len(bin_times)), dtype=np.float32)
            waveforms = np.empty(
                (len(rows), units["waveform_mean"].shape[1]),
                dtype=np.float32,
            )
            raw_source_channels = np.asarray(
                raw_excerpt["rawSourceChannels"],
                dtype=int,
            )
            raw_window_start = event_time + raw_excerpt["sourceTimeStartSeconds"]
            raw_window_stop = event_time + raw_excerpt["sourceTimeEndSeconds"]
            spike_events = []
            filters = []
            for filter_index, row in enumerate(rows):
                electrode_start = 0 if row == 0 else int(electrode_ends[row - 1])
                electrode_stop = int(electrode_ends[row])
                region = electrode_refs[electrode_start:electrode_stop]
                peak_channel = int(units["extremum_channel_index"][row])
                electrode = int(region[peak_channel])
                spike_start = 0 if row == 0 else int(spike_ends[row - 1])
                spike_stop = int(spike_ends[row])
                spikes = np.asarray(
                    units["spike_times"][spike_start:spike_stop],
                    dtype=float,
                )
                spike_rates[filter_index] = (
                    np.histogram(spikes, bins=bin_edges)[0]
                    / NEUROPIXELS_BIN_SECONDS
                )
                peak_row = int(
                    np.argmin(np.abs(raw_source_channels - peak_channel))
                )
                raw_spikes = spikes[
                    (spikes >= raw_window_start) & (spikes <= raw_window_stop)
                ]
                spike_events.extend(
                    {
                        "filterIndex": filter_index,
                        "row": peak_row,
                        "timeMs": round(
                            float((spike - raw_window_start) * 1000),
                            6,
                        ),
                    }
                    for spike in raw_spikes
                )
                waveforms[filter_index] = np.asarray(
                    units["waveform_mean"][row, :, peak_channel],
                    dtype=np.float32,
                )
                filters.append(
                    {
                        "depthUm": round(float(units["depth"][row]), 3),
                        "id": int(units["id"][row]),
                        "ksUnitId": int(units["ks_unit_id"][row]),
                        "label": f"Unit {int(units['id'][row])}",
                        "location": decode_text(
                            electrode_table["location"][electrode]
                        ),
                        "peakChannel": peak_channel,
                        "probeXUm": round(
                            float(electrode_table["rel_x"][electrode]),
                            3,
                        ),
                        "probeYUm": round(
                            float(electrode_table["rel_y"][electrode]),
                            3,
                        ),
                        "rawRow": peak_row,
                        "spreadUm": int(units["spread"][row]),
                    }
                )
            template_amplitudes = np.nanmax(waveforms, axis=1) - np.nanmin(
                waveforms,
                axis=1,
            )
            default_index = int(np.nanargmax(template_amplitudes))
            sources.append(
                {
                    **trace_payload(spike_rates, bin_times),
                    **{
                        key: value
                        for key, value in raw_excerpt.items()
                        if not key.startswith("sourceTime")
                    },
                    "asset": asset_record,
                    "defaultFilterIndex": default_index,
                    "filterCount": len(filters),
                    "filters": filters,
                    "id": "neuropixels",
                    "label": option["label"],
                    "panelLabel": f"Probe {probe_letter}",
                    "rawExcerptSha256": raw_excerpt_sha256,
                    "session": "ecephys_830846_2026-03-09_10-32-54",
                    "sourceId": source_id,
                    "spikeEvents": sorted(
                        spike_events,
                        key=lambda event: event["timeMs"],
                    ),
                    "subject": "830846",
                    "traceLabel": "Binned spike rate",
                    "traceUnit": "spikes/s",
                    "viewType": "spike-map",
                    "waveformColumns": int(waveforms.shape[1]),
                    "waveformDataBase64": encode_float32(waveforms),
                    "waveformRows": int(waveforms.shape[0]),
                    "waveformSampleRateHz": 30000,
                    "waveformUnit": waveform_unit,
                }
            )

    return {
        "asset": asset_record,
        "id": "neuropixels",
        "label": "Neuropixels",
        "session": "ecephys_830846_2026-03-09_10-32-54",
        "sourceLabel": "Probe",
        "sources": sources,
        "subject": "830846",
    }


def extract_mesoscope(asset_record: dict, media_dir: Path) -> dict:
    asset = ASSETS["mesoscope"]
    raw_options, _ = raw_session_options("mesoscope")
    sources = []
    with closing(remfile.File(asset.url)) as remote, h5py.File(remote, "r") as nwb:
        event_time, _ = first_mismatch_event(
            nwb,
            "Sensory-motor mismatch block_presentations",
        )
        for plane in MESOSCOPE_PLANES:
            plane_path = f"processing/{plane}"
            source_id = plane.lower()
            option = raw_options[source_id]
            images = nwb[f"{plane_path}/images"]
            base_image = np.asarray(images["average_projection"][:], dtype=float)
            labels = np.asarray(
                images["segmentation_mask_image"][:],
                dtype=np.uint32,
            )
            segmentation = nwb[f"{plane_path}/image_segmentation/roi_table"]
            ids = np.asarray(segmentation["id"][:], dtype=int)
            if (
                len(ids) != MESOSCOPE_ROI_COUNTS[plane]
                or not np.array_equal(ids, np.arange(len(ids)))
                or int(labels.max()) != len(ids)
            ):
                raise RuntimeError(f"Representative {plane} ROI inventory changed.")

            series = nwb[f"{plane_path}/dff_timeseries/dff_timeseries"]
            timestamps = np.asarray(series["timestamps"][:], dtype=float)
            window_start = event_time + TRACE_WINDOW_START_SECONDS
            selected = np.flatnonzero(
                (timestamps >= window_start)
                & (timestamps < window_start + CALCIUM_TRACE_WINDOW_SECONDS)
            )
            traces = np.asarray(
                series["data"][selected[0] : selected[-1] + 1, :],
                dtype=np.float32,
            ).T
            trace_times = timestamps[selected] - timestamps[selected[0]]

            geometry = filter_geometry(labels, len(ids))
            dendrite_probability = np.asarray(
                segmentation["dendrite_probability"][:],
                dtype=float,
            )
            soma_probability = np.asarray(
                segmentation["soma_probability"][:],
                dtype=float,
            )
            filters = []
            for index, roi_id in enumerate(ids):
                filters.append(
                    {
                        **geometry[index],
                        "dendriteProbability": round(
                            float(dendrite_probability[index]),
                            6,
                        ),
                        "id": int(roi_id),
                        "isDendrite": bool(segmentation["is_dendrite"][index]),
                        "isSoma": bool(segmentation["is_soma"][index]),
                        "label": f"ROI {int(roi_id) + 1}",
                        "somaProbability": round(
                            float(soma_probability[index]),
                            6,
                        ),
                    }
                )
            filename_stem = f"mesoscope-{plane.lower().replace('_', '-')}"
            base_asset = save_png(
                grayscale(base_image),
                media_dir / f"{filename_stem}-mean.png",
            )
            label_asset = save_png(
                encoded_label_image(labels),
                media_dir / f"{filename_stem}-labels.png",
            )
            overlay_asset = save_png(
                boundary_overlay(labels),
                media_dir / f"{filename_stem}-filters.png",
            )
            default_index = int(np.nanargmax(np.nanstd(traces, axis=1)))
            sources.append(
                {
                    **trace_payload(traces, trace_times),
                    "asset": asset_record,
                    "baseImage": base_asset,
                    "defaultFilterIndex": default_index,
                    "displayTransform": "stored-yx",
                    "fastScanAxis": "horizontal",
                    "filterCount": len(filters),
                    "filterOverlay": overlay_asset,
                    "filters": filters,
                    "id": "mesoscope",
                    "label": option["label"],
                    "labelImage": label_asset,
                    "micronsPerPixel": 0.78,
                    "panelLabel": option["label"].split(" ·", maxsplit=1)[0],
                    "session": "multiplane-ophys_832700_2026-01-29_11-18-09",
                    "sourceId": source_id,
                    "subject": "832700",
                    "traceLabel": "ΔF/F (%)",
                    "traceScale": 100,
                    "traceUnit": "%",
                    "viewType": "image",
                }
            )

    return {
        "asset": asset_record,
        "id": "mesoscope",
        "label": "Mesoscope",
        "session": "multiplane-ophys_832700_2026-01-29_11-18-09",
        "sourceLabel": "Imaging plane",
        "sources": sources,
        "subject": "832700",
    }


def slap2_labels(segmentation: h5py.Group, shape: tuple[int, int]) -> np.ndarray:
    ids = np.asarray(segmentation["id"][:], dtype=int)
    masks = np.asarray(segmentation["pixel_mask"][:])
    ends = np.asarray(segmentation["pixel_mask_index"][:], dtype=int)
    labels = np.zeros(shape, dtype=np.uint32)
    start = 0
    for index, (roi_id, stop) in enumerate(zip(ids, ends, strict=True)):
        pixels = masks[start:stop]
        valid = (
            (pixels["x"] < shape[1])
            & (pixels["y"] < shape[0])
            & (pixels["weight"] > 0)
        )
        labels[pixels["y"][valid], pixels["x"][valid]] = index + 1
        start = int(stop)
        if roi_id != index:
            raise RuntimeError("SLAP2 ROI IDs are not contiguous.")
    return labels


def extract_slap2(asset_record: dict, media_dir: Path) -> dict:
    asset = ASSETS["slap2"]
    module_path = "processing/ophys"
    raw_options, _ = raw_session_options("slap2")
    sources = []
    with closing(remfile.File(asset.url)) as remote, h5py.File(remote, "r") as nwb:
        for plane in SLAP2_PLANES:
            source_id = plane.lower()
            option = raw_options[f"{source_id}-detector-1"]
            base_image = np.asarray(
                nwb[f"{module_path}/{plane}_mean_image_channel0/data"][0],
                dtype=float,
            ).T
            segmentation = nwb[
                f"{module_path}/ImageSegmentation/PlaneSegmentation_{plane}"
            ]
            ids = np.asarray(segmentation["id"][:], dtype=int)
            if len(ids) != SLAP2_SOURCE_COUNTS[plane]:
                raise RuntimeError(f"Representative {plane} source inventory changed.")
            labels = slap2_labels(segmentation, base_image.shape)
            # Apply the publication transpose to the normalized image and mask together.
            base_image = np.ascontiguousarray(base_image.T)
            labels = np.ascontiguousarray(labels.T)
            geometry = filter_geometry(labels, len(ids))

            series = nwb[f"{module_path}/Fluorescence_{plane}/{plane}_dFF"]
            timestamps = np.asarray(series["timestamps"][:], dtype=float)
            window_start = max(130.0, float(timestamps[0]) + 1.0)
            selected = np.flatnonzero(
                (timestamps >= window_start)
                & (timestamps < window_start + CALCIUM_TRACE_WINDOW_SECONDS)
            )
            traces = np.asarray(
                series["data"][selected[0] : selected[-1] + 1, :],
                dtype=np.float32,
            ).T
            trace_times = timestamps[selected] - window_start
            if np.isfinite(traces).mean() < 0.9:
                raise RuntimeError(
                    f"Representative {plane} trace window is too sparse."
                )
            filters = [
                {
                    **geometry[index],
                    "id": int(roi_id),
                    "label": f"Source {int(roi_id) + 1}",
                }
                for index, roi_id in enumerate(ids)
            ]
            filename_stem = f"slap2-{source_id}"
            base_asset = save_png(
                grayscale(base_image),
                media_dir / f"{filename_stem}-mean.png",
            )
            label_asset = save_png(
                encoded_label_image(labels),
                media_dir / f"{filename_stem}-labels.png",
            )
            overlay_asset = save_png(
                boundary_overlay(labels),
                media_dir / f"{filename_stem}-filters.png",
            )
            default_index = int(np.nanargmax(np.nanstd(traces, axis=1)))
            sources.append(
                {
                    **trace_payload(traces, trace_times),
                    "asset": asset_record,
                    "baseImage": base_asset,
                    "defaultFilterIndex": default_index,
                    "displayTransform": "transpose-for-publication",
                    "fastScanAxis": "vertical",
                    "filterCount": len(filters),
                    "filterOverlay": overlay_asset,
                    "filters": filters,
                    "id": "slap2",
                    "label": option["label"].replace(" · iGluSnFR4f", ""),
                    "labelImage": label_asset,
                    "micronsPerPixel": 0.25,
                    "panelLabel": plane,
                    "session": "SLAP2_796630_2025-08-28-14-25-34",
                    "sourceId": source_id,
                    "subject": "796630",
                    "traceLabel": "ΔF/F (%)",
                    "traceScale": 100,
                    "traceUnit": "%",
                    "viewType": "image",
                }
            )

    return {
        "asset": asset_record,
        "id": "slap2",
        "label": "SLAP2",
        "session": "SLAP2_796630_2025-08-28-14-25-34",
        "sourceLabel": "Imaging plane",
        "sources": sources,
        "subject": "796630",
    }


def main() -> None:
    args = parse_args()
    asset_records = {key: validate_asset(asset) for key, asset in ASSETS.items()}
    if args.media_dir.exists():
        shutil.rmtree(args.media_dir)
    args.media_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "retrievedDate": RETRIEVED_DATE,
        "version": 4,
        "viewers": [
            extract_neuropixels(asset_records["neuropixels"]),
            extract_mesoscope(asset_records["mesoscope"], args.media_dir),
            extract_slap2(asset_records["slap2"], args.media_dir),
        ],
    }
    write_json(args.output, payload)

    media_hashes = {
        path.name: sha256(path)
        for path in sorted(args.media_dir.glob("*.png"))
    }
    provenance = {
        "assets": asset_records,
        "notes": (
            "Each modality exposes every probe or imaging plane in one representative "
            "session. Filters and traces come from the matched DANDI NWB; Neuropixels "
            "time-by-depth views reuse the pinned public AP excerpts recorded in "
            "raw-neural-excerpts.json and overlay sorted-unit spike times from the "
            "matched NWB. Mesoscope images retain display (y, x), with fast x "
            "horizontal. SLAP2 base images, labels, and overlays share a publication-"
            "level axis transpose, placing fast x vertically."
        ),
        "retrieved_date": RETRIEVED_DATE,
        "source_raw_neural_sha256": sha256(RAW_NEURAL_PATH),
        "vendored_media_sha256": media_hashes,
        "vendored_sha256": sha256(args.output),
    }
    write_json(args.provenance, provenance)
    print(
        f"Wrote {args.output}, {args.provenance}, and {len(media_hashes)} media files"
    )


if __name__ == "__main__":
    main()