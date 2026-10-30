#!/usr/bin/env python3
"""Extract Figure 6A's unit-linked raw voltage from the pinned public AP recording.

Optional readers: uv run --with h5py --with remfile --with s3fs --with "zarr<3"
--with wavpack-numcodecs python scripts/extract_ecephys_unit_trace.py
Add --with "spikeinterface==0.103.0" to replay the saved SNR preprocessing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import h5py
import numpy as np
import remfile
import s3fs
import zarr
from spikeinterface import __version__ as SI_VERSION
from spikeinterface.core import (
    BaseRecording,
    ChannelSliceRecording,
    SelectSegmentRecording,
    ZarrRecordingExtractor,
)
from spikeinterface.preprocessing.common_reference import CommonReferenceRecording
from spikeinterface.preprocessing.filter import HighpassFilterRecording
from spikeinterface.preprocessing.phase_shift import PhaseShiftRecording
from wavpack_numcodecs import WavPack

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = REPO_ROOT / "figure_sources" / "data" / "ecephys-unit-trace.json"
UNIT_ID = 201
VIOLATING_UNIT_ID = 60
ASSET_ID = "03973a42-cf55-476f-80d7-85bc402fa57b"
ASSET_PATH = "sub-830846/sub-830846_ses-ecephys-830846-2026-03-09-10-32-54_ecephys.nwb"
SORTED_PREFIX = (
    "ecephys_830846_2026-03-09_10-32-54_sorted_2026-06-27_16-20-44"
)
ANALYZER_PATH = (
    f"aind-open-data/{SORTED_PREFIX}/postprocessed/"
    "experiment1_Record Node 101#Neuropix-PXI-100.ProbeA-AP_recording1.zarr"
)


def read_ap_trace(group, column: int, start: float, duration: float) -> dict:
    """Read native AP samples using the synchronized acquisition timestamps."""
    rate = float(group.attrs["sampling_frequency"])
    timestamps = group["times_seg0"]
    estimate = round((start - float(timestamps[0])) * rate)
    search_start = max(0, estimate - 100)
    nearby = np.asarray(timestamps[search_start:estimate + 101], dtype=float)
    first = search_start + int(np.searchsorted(nearby, start))
    last = first + round(duration * rate)
    times = np.asarray(timestamps[first:last], dtype=float)
    if len(times) != round(duration * rate) or abs(times[0] - start) > 1 / rate:
        raise ValueError("The AP timestamp search did not align the requested excerpt.")
    trace = np.asarray(group["traces_seg0"][first:last, column])
    return {
        "sample_rate_hz": rate, "sample_start": first, "sample_stop": last,
        "gain_to_uv": float(group["properties/gain_to_uV"][column]),
        "offset_to_uv": float(group["properties/offset_to_uV"][column]),
        "time_start_seconds": float(times[0]), "time_stop_seconds": float(times[-1]),
        "time_ms": np.round((times - times[0]) * 1000, 6).tolist(),
        "raw_adc": trace.astype(int).tolist(),
    }


def replay_analyzer_recording(spec: dict, raw_source: str) -> BaseRecording:
    """Replay only the known saved preprocessing classes against the public raw store."""
    constructors = {
        "spikeinterface.core.channelslice.ChannelSliceRecording": ChannelSliceRecording,
        "spikeinterface.core.segmentutils.SelectSegmentRecording": SelectSegmentRecording,
        "spikeinterface.preprocessing.common_reference.CommonReferenceRecording":
            CommonReferenceRecording,
        "spikeinterface.preprocessing.filter.HighpassFilterRecording": HighpassFilterRecording,
        "spikeinterface.preprocessing.phase_shift.PhaseShiftRecording": PhaseShiftRecording,
    }
    if spec["version"] != SI_VERSION or SI_VERSION != "0.103.0":
        raise ValueError("SNR replay requires the source analyzer's SpikeInterface 0.103.0.")
    kwargs = dict(spec["kwargs"])
    if spec["class"] == "spikeinterface.core.zarrextractors.ZarrRecordingExtractor":
        if not raw_source.endswith(Path(kwargs["folder_path"]).name):
            raise ValueError("The SNR preprocessing refers to a different raw recording.")
        return ZarrRecordingExtractor(
            raw_source, storage_options={"anon": True},
            load_compression_ratio=kwargs["load_compression_ratio"],
        )
    if spec["class"] not in constructors:
        raise ValueError(f"Unsupported saved SNR preprocessing: {spec['class']}")
    for key in ("recording", "parent_recording"):
        if key in kwargs:
            kwargs[key] = replay_analyzer_recording(kwargs[key], raw_source)
    return constructors[spec["class"]](**kwargs)


def measured_diagnostics(
    fs, cluster_id: int, channel: str, expected: dict, raw_source: str, sample_start: int,
) -> tuple[dict, dict]:
    """Extract the saved SNR ingredients and reproduce the saved per-unit drift metric."""
    store = s3fs.S3Map(root=ANALYZER_PATH, s3=fs, check=False)
    analyzer = zarr.open_group(store, mode="r")
    unit_ids = analyzer["sorting/unit_ids"][:]
    matches = np.flatnonzero(unit_ids == cluster_id)
    if len(matches) != 1:
        raise ValueError("The source cluster is not unique in the sorting analyzer.")
    unit_index = int(matches[0])
    extensions = analyzer["extensions"]
    metric_params = dict(extensions["quality_metrics"].attrs)["params"]["metric_params"]
    metrics = extensions["quality_metrics/metrics"]
    for name in ("snr", "isi_violations_ratio", "presence_ratio", "amplitude_cutoff", "drift_ptp"):
        if not np.isclose(float(metrics[name][unit_index]), expected[name], rtol=1e-6):
            raise ValueError(f"NWB/analyzer mismatch for {name}; refusing to mix processing runs.")
    attrs = analyzer["recording_info"].attrs["recording_attributes"]
    channel_index = attrs["channel_ids"].index(channel)
    template = np.asarray(extensions["templates/average"][unit_index, :, channel_index])
    noise = float(extensions["noise_levels/noise_levels"][channel_index])
    amplitude = float(abs(template.min()))
    if not np.isclose(amplitude / noise, expected["snr"], rtol=1e-5):
        raise ValueError("The saved template and noise level do not reproduce the source SNR.")
    rate = float(attrs["sampling_frequency"])
    source_recording = analyzer["recording"]
    if [codec.get_config()["id"] for codec in source_recording.filters] != ["json2"]:
        raise ValueError("The saved SNR recording must use safe JSON provenance, not pickle.")
    recording_spec = source_recording[0]
    recording = replay_analyzer_recording(recording_spec, raw_source)
    padding = 0
    node = recording_spec
    while node is not None:
        padding += round(node["kwargs"].get("margin_ms", 0) * rate / 1000)
        node = next((
            value for value in node["kwargs"].values()
            if isinstance(value, dict) and "class" in value
        ), None)
    if (
        list(recording.channel_ids) != attrs["channel_ids"]
        or recording.sampling_frequency != rate
        or recording.get_num_samples() != attrs["num_samples"][0]
    ):
        raise ValueError("The replayed SNR recording does not match the saved analyzer.")
    sample_stop = sample_start + round(0.5 * rate)
    voltage = recording.get_traces(
        start_frame=sample_start, end_frame=sample_stop, channel_ids=[channel], return_in_uV=True,
    )[:, 0]
    noise_params = dict(extensions["noise_levels"].attrs)["params"]
    if set(noise_params) - {"num_chunks_per_segment", "seed"}:
        raise ValueError("Review the changed source noise-sampling parameters before refreshing.")
    drift_params = metric_params["drift"]
    interval = int(drift_params["interval_s"] * rate)
    num_bins = int(attrs["num_samples"][0]) // interval
    counts = np.zeros(num_bins, dtype=int)
    medians = np.full(num_bins, np.nan)
    unit_vector = analyzer["sorting/spikes/unit_index"]
    sample_vector = analyzer["sorting/spikes/sample_index"]
    locations = extensions["spike_locations/spike_locations"]
    selected_samples, selected_locations = [], []
    for start in range(0, len(unit_vector), unit_vector.chunks[0]):
        indices = np.flatnonzero(
            unit_vector[start:start + unit_vector.chunks[0]] == unit_index
        ) + start
        if len(indices):
            selected_samples.append(sample_vector.oindex[indices])
            selected_locations.append(locations.oindex[indices][drift_params["direction"]])
    samples = np.concatenate(selected_samples)
    depths = np.concatenate(selected_locations)
    reference = float(np.median(depths))
    for index in range(num_bins):
        values = depths[(samples >= index * interval) & (samples < (index + 1) * interval)]
        counts[index] = len(values)
        if len(values) >= drift_params["min_spikes_per_interval"]:
            medians[index] = np.median(values)
    ptp = float(np.nanmax(medians) - np.nanmin(medians))
    if np.isnan(medians).sum() > 0.5 * len(medians) or not np.isclose(
        ptp, expected["drift_ptp"], atol=1e-5,
    ):
        raise ValueError("Reconstructed drift does not reproduce the NWB drift_ptp.")
    template_params = dict(extensions["templates"].attrs)["params"]
    processing_bytes = fs.cat(f"aind-open-data/{SORTED_PREFIX}/processing.json")
    processes = json.loads(processing_bytes)["data_processes"]
    sorter = next(
        process["code"] for process in processes
        if "ProbeA-AP" in process["name"]
        and process["code"].get("parameters", {}).get("sorter_name") == "kilosort4"
    )
    data = {
        "isi_threshold_ms": metric_params["isi_violation"]["isi_threshold_ms"],
        "snr": {
            "template_time_ms": (
                np.arange(len(template)) * 1000 / rate - template_params["ms_before"]
            ).tolist(),
            "template_uv": template.astype(float).tolist(),
            "noise_sigma_uv": noise, "amplitude_uv": amplitude,
            "value": amplitude / noise,
            "recording": {
                "sample_start": sample_start, "sample_stop": sample_stop,
                "sample_rate_hz": rate, "channel": channel,
                "time_ms": (np.arange(len(voltage)) * 1000 / rate).tolist(),
                "voltage_uv": voltage.astype(float).tolist(),
            },
            "noise_sampling": {
                "num_chunks": noise_params["num_chunks_per_segment"],
                "chunk_duration_s": 0.5, "seed": noise_params["seed"],
                "method": "mean of per-chunk MAD / 0.6744897501960817",
            },
        },
        "drift": {
            "time_minutes": ((np.arange(num_bins) + 0.5) * interval / rate / 60).tolist(),
            "median_depth_um": [float(x) if np.isfinite(x) else None for x in medians],
            "spike_counts": counts.tolist(), "reference_depth_um": reference,
            "interval_s": drift_params["interval_s"],
            "min_spikes_per_interval": drift_params["min_spikes_per_interval"],
            "ptp_um": ptp,
        },
    }
    provenance = {
        "analyzer_url": "https://aind-open-data.s3.us-west-2.amazonaws.com/"
        + ANALYZER_PATH.removeprefix("aind-open-data/").replace(" ", "%20").replace("#", "%23"),
        "spikeinterface": dict(analyzer.attrs)["spikeinterface_info"],
        "quality_metric_parameters": metric_params,
        "spike_location_parameters": dict(extensions["spike_locations"].attrs)["params"],
        "noise_parameters": dict(extensions["noise_levels"].attrs)["params"],
        "snr_recording_specification": recording_spec,
        "snr_recording_specification_sha256": hashlib.sha256(
            json.dumps(recording_spec, sort_keys=True).encode(),
        ).hexdigest(),
        "snr_recording_voltage_sha256": hashlib.sha256(
            np.asarray(voltage, dtype="<f4").tobytes(),
        ).hexdigest(),
        "snr_recording_dtype": "<f4",
        "snr_raw_frame_span": [
            max(0, sample_start - padding),
            min(recording.get_num_samples(), sample_stop + padding),
        ],
        "template_parameters": template_params,
        "analyzer_cluster_id": cluster_id, "analyzer_unit_index": unit_index,
        "analyzer_channel_id": channel,
        "selected_spike_frames_sha256": hashlib.sha256(samples.tobytes()).hexdigest(),
        "selected_spike_depths_sha256": hashlib.sha256(depths.tobytes()).hexdigest(),
        "analyzer_metadata_sha256": hashlib.sha256(store[".zattrs"]).hexdigest(),
        "processing_metadata_url": (
            f"https://aind-open-data.s3.us-west-2.amazonaws.com/{SORTED_PREFIX}/processing.json"
        ),
        "processing_metadata_sha256": hashlib.sha256(processing_bytes).hexdigest(),
        "sorter": sorter,
    }
    return data, provenance


def extract_unit_trace() -> tuple[dict, dict]:
    """Read an unfiltered 200-ms AP excerpt on the identified unit's peak channel."""
    pinned_path = REPO_ROOT / "figure_sources" / "data" / "raw-neural-excerpts.json"
    session = next(
        item for item in json.loads(pinned_path.read_text(encoding="utf-8"))["sessions"]
        if item["id"] == "neuropixels"
    )
    nwb_source = session["sources"][0]
    with closing(remfile.File(nwb_source["url"])) as remote, h5py.File(remote, "r") as nwb:
        units = nwb["units"]
        matches = np.flatnonzero(units["id"][:] == UNIT_ID)
        if len(matches) != 1:
            raise ValueError(f"Expected one source unit with ID {UNIT_ID}.")
        row = int(matches[0])
        spike_start = int(units["spike_times_index"][row - 1]) if row else 0
        spike_stop = int(units["spike_times_index"][row])
        spikes = np.asarray(units["spike_times"][spike_start:spike_stop], dtype=float)
        electrode_start = int(units["electrodes_index"][row - 1]) if row else 0
        electrodes = nwb["general/extracellular_ephys/electrodes"]
        electrode_stop = int(units["electrodes_index"][row])
        region = np.asarray(units["electrodes"][electrode_start:electrode_stop], dtype=int)
        region_channels = [electrodes["channel_name"][int(index)].decode() for index in region]
        ap_electrodes = [
            int(index) for index, name in zip(region, region_channels, strict=True)
            if name.startswith("AP") and name[2:].isdigit()
        ]
        waveform = np.asarray(units["waveform_mean"][row], dtype=float)
        if waveform.ndim != 2 or waveform.shape[1] != len(ap_electrodes):
            raise ValueError("The mean waveform channels do not match the AP electrode region.")
        if not np.isfinite(waveform).all():
            raise ValueError("The example unit's recorded mean waveform contains nonfinite values.")
        peak_index = int(np.argmin(np.min(waveform, axis=0)))
        electrode = ap_electrodes[peak_index]
        sorter_index = int(units["extremum_channel_index"][row])
        channel = electrodes["channel_name"][electrode].decode()
        probe = electrodes["group_name"][electrode].decode()
        location = electrodes["location"][electrode].decode()
        metrics = {
            name: float(units[name][row])
            for name in ("snr", "isi_violations_ratio", "presence_ratio", "amplitude_cutoff",
                         "drift_ptp")
        }
        cluster_id = int(units["ks_unit_id"][row])
        bad_matches = np.flatnonzero(units["id"][:] == VIOLATING_UNIT_ID)
        if len(bad_matches) != 1:
            raise ValueError("The refractory-violating source unit is not unique.")
        bad_row = int(bad_matches[0])
        bad_spikes = np.asarray(units["spike_times"][
            int(units["spike_times_index"][bad_row - 1]) if bad_row else 0:
            int(units["spike_times_index"][bad_row])
        ])
        bad_waveform = np.asarray(units["waveform_mean"][bad_row])
        bad_region = np.asarray(units["electrodes"][
            int(units["electrodes_index"][bad_row - 1]) if bad_row else 0:
            int(units["electrodes_index"][bad_row])
        ])
        if not np.array_equal(bad_region, region) or not np.isfinite(bad_waveform).all():
            raise ValueError("The violating example does not share the verified electrode mapping.")
        bad_channel = electrodes["channel_name"][
            ap_electrodes[int(np.argmin(np.min(bad_waveform, axis=0)))]
        ].decode()
        bad_metrics = {name: float(units[name][bad_row]) for name in metrics}
        bad_cluster_id = int(units["ks_unit_id"][bad_row])
    if not (
        metrics["snr"] >= 3 and metrics["isi_violations_ratio"] < 0.01
        and metrics["presence_ratio"] > 0.9 and metrics["amplitude_cutoff"] < 0.1
    ):
        raise ValueError("The example unit no longer passes the Figure 6 QC gates.")
    if not (
        bad_metrics["snr"] >= 3 and bad_metrics["isi_violations_ratio"] >= 0.01
        and bad_metrics["presence_ratio"] > 0.9 and bad_metrics["amplitude_cutoff"] < 0.1
    ):
        raise ValueError("The violating example must fail ISI QC but pass the other signal gates.")
    if not channel.startswith("AP") or not channel[2:].isdigit():
        raise ValueError(f"The unit's peak electrode is not an AP channel: {channel}")
    ap_source = next(item for item in session["sources"] if item.get("probe") == probe[-1])
    parsed = urlparse(ap_source["storeUrl"])
    store_key = unquote(parsed.path.lstrip("/"))
    fs = s3fs.S3FileSystem(anon=True)
    store = s3fs.S3Map(root=f"aind-open-data/{store_key}", s3=fs, check=False)
    if WavPack.codec_id != "wavpack":
        raise RuntimeError("The lossless AP codec is not registered.")
    group = zarr.open_group(store, mode="r")
    channel_names = np.asarray(group["properties/channel_name"][:]).astype("U")
    channel_matches = np.flatnonzero(channel_names == channel)
    if len(channel_matches) != 1:
        raise ValueError(f"Cannot uniquely match NWB electrode {channel} to the AP store.")
    column = int(channel_matches[0])
    candidates = np.flatnonzero((spikes[:-5] >= 60) & (spikes[5:] - spikes[:-5] < 0.18))
    if not len(candidates):
        raise ValueError("No recorded 200-ms window contains the required six assigned spikes.")
    target_start = float(spikes[candidates[0]] - 0.01)
    excerpt = read_ap_trace(group, column, target_start, 0.2)
    diagnostics, diagnostic_provenance = measured_diagnostics(
        fs, cluster_id, channel, metrics, f"s3://aind-open-data/{store_key}",
        excerpt["sample_start"],
    )
    included = spikes[
        (spikes >= excerpt["time_start_seconds"]) & (spikes <= excerpt["time_stop_seconds"])
    ]
    ordinary = int(np.argmin(np.diff(included)))
    if np.diff(included)[ordinary] * 1000 < diagnostics["isi_threshold_ms"]:
        raise ValueError("The intended non-violating example contains an ISI violation.")
    diagnostics["ordinary_pair_ms"] = (
        (included[ordinary:ordinary + 2] - excerpt["time_start_seconds"]) * 1000
    ).tolist()
    intervals = np.diff(bad_spikes) * 1000
    bad_candidates = np.flatnonzero(
        (bad_spikes[:-1] >= 60) & (intervals >= 0.5)
        & (intervals < diagnostics["isi_threshold_ms"])
    )
    if not len(bad_candidates):
        raise ValueError("No genuine refractory-violating pair exists in the example cluster.")
    bad_pair = bad_spikes[bad_candidates[0]:bad_candidates[0] + 2]
    bad_column = int(np.flatnonzero(channel_names == bad_channel)[0])
    bad_excerpt = read_ap_trace(
        group, bad_column, float(bad_pair[0] - 0.002),
        float(bad_pair[1] - bad_pair[0] + 0.004),
    )
    bad_excerpt.update({
        "unit_id": VIOLATING_UNIT_ID, "channel": bad_channel, "probe": probe,
        "sorter_cluster_id": bad_cluster_id, "unit_metrics": bad_metrics,
        "isi_violations_ratio": bad_metrics["isi_violations_ratio"],
        "unit_spike_times_ms": (
            (bad_pair - bad_excerpt["time_start_seconds"]) * 1000
        ).tolist(),
    })
    diagnostics["violating_trace"] = bad_excerpt
    payload = {
        "session": session["session"], "subject": session["subject"],
        "unit_id": UNIT_ID, "probe": probe, "channel": channel, "location": location,
        "waveform_peak_channel_index": peak_index,
        "sorter_extremum_channel_index": sorter_index,
        **excerpt,
        "unit_spike_times_ms": np.round(
            (included - excerpt["time_start_seconds"]) * 1000, 6,
        ).tolist(),
        "unit_metrics": metrics, "diagnostics": diagnostics,
    }
    chunk_size = group["traces_seg0"].chunks[0]
    chunks = []
    chunk_indices = set()
    for item in (excerpt, bad_excerpt):
        chunk_indices.update(range(
            item["sample_start"] // chunk_size, (item["sample_stop"] - 1) // chunk_size + 1,
        ))
    snr_first, snr_last = diagnostic_provenance["snr_raw_frame_span"]
    chunk_indices.update(range(snr_first // chunk_size, (snr_last - 1) // chunk_size + 1))
    for index in sorted(chunk_indices):
        key = f"traces_seg0/{index}.0"
        chunks.append({
            "key": key, "sha256": hashlib.sha256(store[key]).hexdigest(),
            "url": f"{ap_source['storeUrl']}/{key}",
        })
    provenance = {
        "retrieved_date": datetime.now(UTC).date().isoformat(),
        "dandiset_id": "001637", "dandiset_version": "draft",
        "asset_id": ASSET_ID, "asset_path": ASSET_PATH,
        "nwb_source": nwb_source, "ap_store_url": ap_source["storeUrl"],
        "ap_metadata_sha256": hashlib.sha256(store[".zattrs"]).hexdigest(),
        "ap_chunks": chunks,
        "raw_adc_sha256": hashlib.sha256(
            np.asarray(excerpt["raw_adc"], dtype="<i2").tobytes(),
        ).hexdigest(),
        "raw_adc_dtype": "<i2",
        "violating_raw_adc_sha256": hashlib.sha256(
            np.asarray(bad_excerpt["raw_adc"], dtype="<i2").tobytes(),
        ).hexdigest(),
        "diagnostics": diagnostic_provenance,
        "selection": (
            "NWB unit 201, peak electrode selected by the largest negative trough of "
            "its recorded waveform_mean across the AP channels in its units/electrodes "
            "region, matched to the AP store by channel_name. The stored sorter "
            "extremum_channel_index is retained separately, not assumed to be a "
            "physical AP channel index. "
            "The 200-ms excerpt starts 10 ms before the first post-60-s window "
            "containing six assigned spikes within 180 ms. The violating example "
            "uses NWB unit 60's first post-60-s pair between 0.5 and 1.5 ms on "
            "its own mean-waveform peak electrode. This cluster passes SNR, "
            "presence-ratio and amplitude-cutoff gates but fails ISI QC. "
            "All native raw-excerpt samples are retained; only the recorded ADC-to-uV gain "
            "and offset are applied to raw voltage. No filtering, interpolation, smoothing, "
            "clipping or spike-time detection is performed on those raw excerpts. "
            "The separate 500-ms SNR excerpt starts at the same sample and replays the "
            "analyzer's saved phase shift, high-pass filter, channel slices and median "
            "reference using SpikeInterface 0.103.0. It is not the original random sample "
            "used to estimate saved noise: that computation used 20 random 500-ms chunks "
            "with seed=None; their exact original positions were not saved."
        ),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    return payload, provenance


def main() -> None:
    """Write the compact voltage snapshot and its provenance, never an NWB file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    payload, provenance = extract_unit_trace()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    provenance["snapshot_sha256"] = hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_suffix(".provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8", newline="\n",
    )
    print(f"Wrote {args.output}: unit {UNIT_ID}, {len(payload['raw_adc'])} native samples")


if __name__ == "__main__":
    main()
