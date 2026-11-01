import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from openscope_p3_publication.ecephys_qc_figure import (
    UNIT_TRACE_PATH,
    load_ecephys_qc_data,
    load_ecephys_unit_trace,
)
from openscope_p3_publication.figures import text_sha256_matches


def test_unit_qc_methods_report_snapshot_population_and_gates() -> None:
    manuscript = (UNIT_TRACE_PATH.parents[2] / "index.md").read_text(encoding="utf-8")
    paragraph = manuscript.split("#### Neuropixels unit quality control\n", 1)[1].split(
        "\n#### ", 1,
    )[0]
    prose = " ".join(paragraph.split())
    units = load_ecephys_qc_data()["units"]
    count = len(units["snr"])
    assert f"{count:,} sorted units" in prose
    assert f"{len(set(units['session_key']))} CCF-aligned sessions" in prose
    assert f"{len(set(units['mouse_id']))} mice" in prose
    keep = np.ones(count, dtype=bool)
    for metric, operation, threshold in (
        ("isi_violations_ratio", np.less, 0.01),
        ("presence_ratio", np.greater, 0.90),
        ("amplitude_cutoff", np.less, 0.10),
        ("snr", np.greater_equal, 3.0),
        ("depth_from_cortex_um", np.greater_equal, 0.0),
    ):
        keep &= operation(np.asarray(units[metric], dtype=float), threshold)
    keep &= np.asarray(units["area"]) != "void"
    assert f"retained {np.count_nonzero(keep):,} units" in prose
    for requirement in (
        "ISI violations ratio < 0.01",
        "1.5 ms refractory threshold",
        "presence ratio > 0.90",
        "amplitude cutoff < 0.10",
        "waveform SNR ≥ 3.0",
        "non-negative depth from cortical entry",
        "unannotated (`void`) channels",
        "initial and final session groups",
        "where available",
        "unit-location drift",
        "$10^{-6}$",
        "99th percentile without discarding retained values",
        "not tracking the same neurons",
        "panel D used broader gates",
        "ISI violations ratio < 0.5",
        "presence ratio > 0.8",
        "amplitude cutoff < 0.1",
        "without an SNR threshold",
    ):
        assert requirement in prose
    assert "first and fourth" not in prose
    assert "current source density" not in prose
    assert "power spectral density" not in prose


def test_recorded_unit_trace_preserves_native_samples_and_identity() -> None:
    trace = load_ecephys_unit_trace()
    provenance = json.loads(
        UNIT_TRACE_PATH.with_suffix(".provenance.json").read_text(encoding="utf-8")
    )
    assert trace["unit_id"] == 201
    assert trace["probe"] == "ProbeA" and trace["channel"] == "AP192"
    assert trace["waveform_peak_channel_index"] == 192
    assert trace["sorter_extremum_channel_index"] == 191
    assert trace["location"] == "ACAv5"
    assert trace["sample_rate_hz"] == 30_000
    assert len(trace["raw_adc"]) == len(trace["time_ms"]) == 6_000
    assert np.diff(trace["time_ms"]) == pytest.approx(
        np.diff(trace["time_ms"]).mean(), abs=1e-6,
    )
    assert len(trace["unit_spike_times_ms"]) == 10
    assert trace["time_start_seconds"] == pytest.approx(88.6730610668979)
    assert trace["unit_spike_times_ms"][0] == pytest.approx(9.999992, abs=1e-6)
    assert trace["unit_metrics"]["snr"] == pytest.approx(13.39568102489356)
    assert trace["unit_metrics"]["isi_violations_ratio"] == 0
    voltage = np.asarray(trace["raw_adc"]) * trace["gain_to_uv"] + trace["offset_to_uv"]
    times = np.asarray(trace["time_ms"])
    for spike in trace["unit_spike_times_ms"]:
        snippet = voltage[np.abs(times - spike) < 0.5]
        assert snippet.min() < -100
    assert provenance["asset_id"] == "03973a42-cf55-476f-80d7-85bc402fa57b"
    assert provenance["asset_path"].endswith("_ecephys.nwb")
    assert provenance["ap_chunks"]
    assert all(len(chunk["sha256"]) == 64 for chunk in provenance["ap_chunks"])
    assert "No filtering, interpolation, smoothing" in provenance["selection"]
    assert provenance["diagnostics"]["analyzer_cluster_id"] == 259
    assert provenance["diagnostics"]["analyzer_channel_id"] == trace["channel"]
    assert provenance["diagnostics"]["sorter"]["parameters"]["sorter_name"] == "kilosort4"
    assert text_sha256_matches(
        UNIT_TRACE_PATH.parents[2] / "scripts" / "extract_ecephys_unit_trace.py",
        provenance["script_sha256"],
    )


def test_recorded_diagnostics_reproduce_source_metrics() -> None:
    trace = load_ecephys_unit_trace()
    diagnostic = trace["diagnostics"]
    assert diagnostic["isi_threshold_ms"] == 1.5
    assert np.diff(diagnostic["ordinary_pair_ms"])[0] == pytest.approx(2.766665, abs=1e-6)
    bad = diagnostic["violating_trace"]
    assert bad["unit_id"] == 60 and bad["channel"] == "AP83"
    assert bad["sorter_cluster_id"] == 81
    assert np.diff(bad["unit_spike_times_ms"])[0] == pytest.approx(0.666666, abs=1e-6)
    assert bad["isi_violations_ratio"] > 0.01
    assert bad["unit_metrics"]["snr"] >= 3
    assert bad["unit_metrics"]["presence_ratio"] > 0.9
    assert bad["unit_metrics"]["amplitude_cutoff"] < 0.1
    bad_volts = np.asarray(bad["raw_adc"]) * bad["gain_to_uv"] + bad["offset_to_uv"]
    for spike in bad["unit_spike_times_ms"]:
        assert bad_volts[np.abs(np.asarray(bad["time_ms"]) - spike) < 0.4].min() < -40
    snr = diagnostic["snr"]
    assert snr["amplitude_uv"] == pytest.approx(abs(min(snr["template_uv"])))
    assert snr["noise_sigma_uv"] == pytest.approx(14.917945861816406)
    assert snr["amplitude_uv"] / snr["noise_sigma_uv"] == pytest.approx(
        trace["unit_metrics"]["snr"]
    )
    recording = snr["recording"]
    assert len(recording["time_ms"]) == len(recording["voltage_uv"]) == 15_000
    assert recording["sample_rate_hz"] == 30_000
    assert recording["sample_start"] == trace["sample_start"]
    assert recording["channel"] == trace["channel"]
    assert recording["time_ms"][-1] == pytest.approx(500 - 1000 / 30_000)
    assert snr["noise_sampling"]["num_chunks"] == 20
    assert snr["noise_sampling"]["chunk_duration_s"] == 0.5
    assert min(recording["voltage_uv"]) < -200
    drift = diagnostic["drift"]
    depths = np.asarray(drift["median_depth_um"], dtype=float)
    counts = np.asarray(drift["spike_counts"])
    assert drift["interval_s"] == 60 and drift["min_spikes_per_interval"] == 100
    assert np.isnan(depths).any() and np.isfinite(depths).any()
    assert np.array_equal(np.isnan(depths), counts < 100)
    assert np.nanmax(depths) - np.nanmin(depths) == pytest.approx(31.09246826171875)
    assert drift["ptp_um"] == pytest.approx(trace["unit_metrics"]["drift_ptp"])


@pytest.mark.parametrize("failure", [
    "checksum", "raw_samples", "spike_time", "time_order", "violating_samples",
    "ordinary_isi", "violating_isi", "snr", "template", "drift", "drift_gap",
    "snr_recording_samples", "snr_recording_time", "noise_sampling",
])
def test_recorded_unit_trace_rejects_corruption(tmp_path: Path, failure: str) -> None:
    path = tmp_path / "trace.json"
    trace = json.loads(UNIT_TRACE_PATH.read_text(encoding="utf-8"))
    provenance = json.loads(
        UNIT_TRACE_PATH.with_suffix(".provenance.json").read_text(encoding="utf-8")
    )
    if failure in ("checksum", "raw_samples"):
        trace["raw_adc"][0] += 1
    elif failure == "spike_time":
        trace["unit_spike_times_ms"] = [trace["time_ms"][-1] + 1]
    elif failure == "time_order":
        trace["time_ms"][1] = trace["time_ms"][0]
    elif failure == "violating_samples":
        trace["diagnostics"]["violating_trace"]["raw_adc"][0] += 1
    elif failure == "ordinary_isi":
        trace["diagnostics"]["ordinary_pair_ms"][1] = (
            trace["diagnostics"]["ordinary_pair_ms"][0] + 1
        )
    elif failure == "violating_isi":
        trace["diagnostics"]["violating_trace"]["unit_spike_times_ms"][1] = (
            trace["diagnostics"]["violating_trace"]["unit_spike_times_ms"][0] + 2
        )
    elif failure == "snr":
        trace["diagnostics"]["snr"]["noise_sigma_uv"] *= 2
    elif failure == "template":
        trace["diagnostics"]["snr"]["template_uv"][0] = -999
    elif failure == "drift":
        trace["diagnostics"]["drift"]["ptp_um"] += 1
    elif failure == "drift_gap":
        trace["diagnostics"]["drift"]["median_depth_um"][0] = 1900
    elif failure == "snr_recording_samples":
        trace["diagnostics"]["snr"]["recording"]["voltage_uv"][0] += 1
    elif failure == "snr_recording_time":
        trace["diagnostics"]["snr"]["recording"]["time_ms"][1] = 0
    elif failure == "noise_sampling":
        trace["diagnostics"]["snr"]["noise_sampling"]["num_chunks"] = 1
    path.write_text(json.dumps(trace), encoding="utf-8")
    if failure != "checksum":
        provenance["snapshot_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_suffix(".provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
    with pytest.raises(ValueError, match="Figure 6"):
        load_ecephys_unit_trace(path)
