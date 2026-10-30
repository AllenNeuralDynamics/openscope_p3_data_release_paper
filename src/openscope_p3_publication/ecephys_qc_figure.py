from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import re
import shutil
import struct
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image

from .figure_typography import normalize_figure_svg
from .figures import (
    FIGURE_SANS_FONT,
    load_figure_controls,
    load_figure_stylesheet,
    load_unit_yield_data,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_JSON_PATH = REPO_ROOT / "figure_sources" / "data" / "ecephys-qc-dashboard.json.gz"
PROVENANCE_JSON_PATH = (
    REPO_ROOT / "figure_sources" / "data" / "ecephys-qc-dashboard.provenance.json"
)
UNIT_TRACE_PATH = REPO_ROOT / "figure_sources" / "data" / "ecephys-unit-trace.json"
OUT_HTML_PATH = REPO_ROOT / "interactive" / "openscope_qc_dashboard.html"
OUT_SVG_PATH = REPO_ROOT / "images" / "figures" / "generated" / "openscope_qc_dashboard_static.svg"
DEPLOY_JSON_PATH = (
    REPO_ROOT / "interactive" / "media" / "ecephys-qc-dashboard" / "ecephys-qc-dashboard.json.gz"
)
DEPLOY_SVG_PATH = DEPLOY_JSON_PATH.parent / "openscope_qc_dashboard_static.svg"
JAVASCRIPT_DIR = REPO_ROOT / "figure_sources" / "javascript"

_EMBEDDED_PNG_RE = re.compile(r"data:image/png;base64,([A-Za-z0-9+/=\s]+)")

_SVG_RC_PARAMS = {
    "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans"],
    "font.size": 10,
    "legend.fontsize": 10,
    "axes.titlesize": 12,
    "axes.labelsize": 10,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "svg.fonttype": "none",
    "svg.hashsalt": "openscope_qc_dashboard",
    "path.simplify": False,
}


def _deterministic_rgba_png(png_bytes: bytes) -> bytes:
    """Encode a PNG deterministically across all Python/zlib/libpng versions."""
    image = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    width, height = image.size
    raw_rgba = image.tobytes()
    stride = width * 4
    scanlines = b"".join(
        b"\x00" + raw_rgba[y * stride : (y + 1) * stride] for y in range(height)
    )

    blocks = [b"\x78\x01"]
    pos = 0
    total = len(scanlines)
    while pos < total or total == 0:
        chunk = scanlines[pos : pos + 65535]
        pos += len(chunk)
        is_last = 1 if pos >= total else 0
        n = len(chunk)
        blocks.append(struct.pack("<BHH", is_last, n, n ^ 0xFFFF) + chunk)
        if total == 0:
            break
    blocks.append(struct.pack(">I", zlib.adler32(scanlines) & 0xFFFFFFFF))
    idat_payload = b"".join(blocks)

    def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", idat_payload)
        + _png_chunk(b"IEND", b"")
    )


def _canonicalize_svg_embedded_pngs(svg_text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        raw_b64 = re.sub(r"\s+", "", match.group(1))
        png_bytes = _deterministic_rgba_png(base64.b64decode(raw_b64))
        b64_str = base64.b64encode(png_bytes).decode("ascii")
        wrapped = "\n".join(b64_str[i : i + 76] for i in range(0, len(b64_str), 76))
        return f"data:image/png;base64,{wrapped}\n"

    root = ET.fromstring(_EMBEDDED_PNG_RE.sub(_replace, svg_text))
    svg_namespace = "http://www.w3.org/2000/svg"
    link_namespace = "http://www.w3.org/1999/xlink"
    replacements = {}
    for index, image in enumerate(root.iter(f"{{{svg_namespace}}}image")):
        href = image.get(f"{{{link_namespace}}}href", image.get("href", ""))
        original_id = image.get("id")
        if original_id and href.startswith("data:image/png;base64,"):
            png_bytes = base64.b64decode(href.partition(",")[2])
            digest = hashlib.sha256(png_bytes).hexdigest()[:12]
            image_id = f"image-{index}-{digest}"
            image.set("id", image_id)
            replacements[original_id] = image_id
    for element in root.iter():
        for attribute, value in list(element.attrib.items()):
            for original_id, image_id in replacements.items():
                if value == f"#{original_id}":
                    value = f"#{image_id}"
                value = value.replace(f"url(#{original_id})", f"url(#{image_id})")
            element.set(attribute, value)
    ET.register_namespace("", svg_namespace)
    ET.register_namespace("xlink", link_namespace)
    serialized = ET.tostring(root, encoding="unicode")
    return "\n".join(line.rstrip() for line in serialized.splitlines()) + "\n"


def load_ecephys_qc_data(
    data_path: Path = DATA_JSON_PATH,
    provenance_path: Path | None = PROVENANCE_JSON_PATH,
) -> dict:
    raw_bytes = data_path.read_bytes()
    if (
        data_path == DATA_JSON_PATH
        and provenance_path is not None
        and provenance_path.exists()
    ):
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        expected_sha = provenance.get("snapshot_sha256")
        if expected_sha:
            actual_sha = hashlib.sha256(raw_bytes).hexdigest()
            if actual_sha != expected_sha:
                raise ValueError(
                    "Ecephys QC dashboard snapshot checksum mismatch: "
                    f"expected {expected_sha}, got {actual_sha}"
                )

    if raw_bytes[:2] == b"\x1f\x8b" or data_path.suffix == ".gz":
        json_text = gzip.decompress(raw_bytes).decode("utf-8")
    else:
        json_text = raw_bytes.decode("utf-8")
    return json.loads(json_text)


def _validate_ap_excerpt(payload: dict, dtype: str, expected_hash: str) -> None:
    times = np.asarray(payload["time_ms"], dtype=float)
    raw = np.asarray(payload["raw_adc"], dtype=float)
    spikes = np.asarray(payload["unit_spike_times_ms"], dtype=float)
    if (
        times.ndim != 1 or raw.shape != times.shape or len(times) < 2
        or not np.isfinite(times).all() or not np.isfinite(raw).all()
        or not np.all(np.diff(times) > 0) or not np.isfinite(spikes).all()
        or spikes.ndim != 1 or not len(spikes)
        or not np.all(np.diff(spikes) > 0)
        or np.any(spikes < times[0]) or np.any(spikes > times[-1])
        or len(times) != payload["sample_stop"] - payload["sample_start"]
        or not np.isfinite(payload["gain_to_uv"]) or payload["gain_to_uv"] <= 0
        or not np.isfinite(payload["offset_to_uv"])
        or not np.isfinite(payload["sample_rate_hz"]) or payload["sample_rate_hz"] <= 0
        or not np.allclose(np.diff(times), 1000 / payload["sample_rate_hz"], atol=1e-5)
        or times[0] != 0
    ):
        raise ValueError("The Figure 6 unit trace has invalid samples, times, or scaling.")
    native = np.asarray(payload["raw_adc"], dtype=dtype)
    if not np.array_equal(native, raw) or (
        hashlib.sha256(native.tobytes()).hexdigest() != expected_hash
    ):
        raise ValueError("The Figure 6 raw ADC samples do not match the extracted source.")


def load_ecephys_unit_trace(path: Path = UNIT_TRACE_PATH) -> dict:
    """Validate the native voltage, genuine ISIs, and measured SNR/drift ingredients."""
    provenance = json.loads(path.with_suffix(".provenance.json").read_text(encoding="utf-8"))
    if hashlib.sha256(path.read_bytes()).hexdigest() != provenance["snapshot_sha256"]:
        raise ValueError("The Figure 6 unit-trace snapshot checksum does not match provenance.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    _validate_ap_excerpt(payload, provenance["raw_adc_dtype"], provenance["raw_adc_sha256"])
    diagnostic = payload["diagnostics"]
    bad = diagnostic["violating_trace"]
    _validate_ap_excerpt(
        bad, provenance["raw_adc_dtype"], provenance["violating_raw_adc_sha256"],
    )
    threshold = diagnostic["isi_threshold_ms"]
    ordinary = np.asarray(diagnostic["ordinary_pair_ms"], dtype=float)
    violating = np.asarray(bad["unit_spike_times_ms"], dtype=float)
    assigned = np.asarray(payload["unit_spike_times_ms"], dtype=float)
    if (
        not np.isfinite(threshold) or threshold <= 0
        or threshold != provenance["diagnostics"]["quality_metric_parameters"][
            "isi_violation"
        ]["isi_threshold_ms"]
        or ordinary.shape != (2,) or violating.shape != (2,)
        or not np.isfinite(ordinary).all()
        or ordinary[1] - ordinary[0] < threshold
        or not 0 < violating[1] - violating[0] < threshold
        or not all(np.any(np.isclose(assigned, t, rtol=0, atol=1e-6)) for t in ordinary)
        or np.count_nonzero(
            (assigned >= ordinary[0] - 1e-6) & (assigned <= ordinary[1] + 1e-6)
        ) != 2
        or bad["unit_id"] == payload["unit_id"] or bad["isi_violations_ratio"] < 0.01
    ):
        raise ValueError("The Figure 6 ISI examples do not match the recorded classifications.")
    snr = diagnostic["snr"]
    template = np.asarray(snr["template_uv"], dtype=float)
    template_times = np.asarray(snr["template_time_ms"], dtype=float)
    if (
        template.ndim != 1 or len(template) < 2 or template.shape != template_times.shape
        or not np.isfinite(template).all() or not np.isfinite(template_times).all()
        or not np.all(np.diff(template_times) > 0)
        or not np.isfinite(snr["noise_sigma_uv"]) or snr["noise_sigma_uv"] <= 0
        or not np.isclose(snr["amplitude_uv"], abs(template.min()))
        or not np.isclose(snr["value"], snr["amplitude_uv"] / snr["noise_sigma_uv"])
        or not np.isclose(snr["value"], payload["unit_metrics"]["snr"])
    ):
        raise ValueError("The Figure 6 SNR ingredients do not reproduce the saved metric.")
    recording = snr["recording"]
    voltage = np.asarray(recording["voltage_uv"], dtype=float)
    recording_times = np.asarray(recording["time_ms"], dtype=float)
    sampling = snr["noise_sampling"]
    source = provenance["diagnostics"]
    native_voltage = np.asarray(recording["voltage_uv"], dtype=source["snr_recording_dtype"])
    if (
        voltage.ndim != 1 or len(voltage) < 2 or voltage.shape != recording_times.shape
        or not np.isfinite(voltage).all() or not np.isfinite(recording_times).all()
        or recording["sample_rate_hz"] != payload["sample_rate_hz"]
        or len(voltage) != recording["sample_stop"] - recording["sample_start"]
        or len(voltage) / recording["sample_rate_hz"] < 0.5
        or recording["sample_start"] != payload["sample_start"]
        or recording["channel"] != payload["channel"]
        or not np.allclose(
            recording_times, np.arange(len(voltage)) * 1000 / recording["sample_rate_hz"],
        )
        or not np.array_equal(native_voltage, voltage)
        or hashlib.sha256(native_voltage.tobytes()).hexdigest()
        != source["snr_recording_voltage_sha256"]
        or sampling["num_chunks"] != source["noise_parameters"]["num_chunks_per_segment"]
        or sampling["chunk_duration_s"] != 0.5
        or sampling["num_chunks"] * sampling["chunk_duration_s"]
        <= len(voltage) / recording["sample_rate_hz"]
        or hashlib.sha256(json.dumps(
            source["snr_recording_specification"], sort_keys=True,
        ).encode()).hexdigest() != source["snr_recording_specification_sha256"]
    ):
        raise ValueError("The Figure 6 SNR recording or noise-sampling provenance is invalid.")
    drift = diagnostic["drift"]
    depths = np.asarray(drift["median_depth_um"], dtype=float)
    counts = np.asarray(drift["spike_counts"], dtype=float)
    minutes = np.asarray(drift["time_minutes"], dtype=float)
    if (
        depths.ndim != 1 or len(depths) < 2 or depths.shape != counts.shape
        or depths.shape != minutes.shape or not np.isfinite(minutes).all()
        or not np.isfinite(counts).all() or np.any(counts < 0)
        or np.any(counts != counts.astype(int))
        or np.isinf(depths).any() or np.isfinite(depths).sum() < len(depths) / 2
        or not np.isfinite(drift["reference_depth_um"])
        or drift["interval_s"] <= 0 or drift["min_spikes_per_interval"] <= 0
        or not np.array_equal(np.isfinite(depths), counts >= drift["min_spikes_per_interval"])
        or not np.allclose(minutes, (np.arange(len(depths)) + 0.5) * drift["interval_s"] / 60)
        or not np.isclose(drift["ptp_um"], np.nanmax(depths) - np.nanmin(depths))
        or not np.isclose(drift["ptp_um"], payload["unit_metrics"]["drift_ptp"])
    ):
        raise ValueError("The Figure 6 drift bins do not reproduce the saved drift metric.")
    return payload


def _draw_metric_guide(figure, slot, trace: dict) -> None:
    """Show recorded spike pairs and preprocessing-matched SNR measurements."""
    grid = slot.subgridspec(2, 3, height_ratios=[0.8, 1], wspace=0.55, hspace=0.85)
    raw = figure.add_subplot(grid[0, :])
    raw.set_gid("panel-A-raw-trace")
    time_ms = np.asarray(trace["time_ms"])
    voltage = np.asarray(trace["raw_adc"]) * trace["gain_to_uv"] + trace["offset_to_uv"]
    assigned_spikes = np.asarray(trace["unit_spike_times_ms"])
    marker_level = float(voltage.max() + np.ptp(voltage) * 0.12)
    raw.plot(time_ms, voltage, color="#293133", linewidth=0.8,
             gid="recorded-raw-voltage")
    spike_color = "#0072B2"
    raw.scatter(assigned_spikes, np.full(len(assigned_spikes), marker_level), marker="v", s=18,
                color=spike_color, linewidths=0, gid="recorded-unit-spikes")
    raw.annotate("assigned spikes", (assigned_spikes[0], marker_level),
                  xytext=(0, 8), textcoords="offset points", ha="center", va="bottom",
                  fontsize=9, color=spike_color, gid="assigned-spikes-label")
    raw.set(xlim=(0, 200), xlabel="Time (ms)")
    raw.set_ylabel("Voltage (µV)", fontsize=9)
    raw.set_xticks([0, 50, 100, 150, 200])
    raw.tick_params(labelsize=9)
    raw.xaxis.label.set_fontsize(9)
    raw.spines[["top", "right"]].set_visible(False)
    diagnostic = trace["diagnostics"]
    threshold = diagnostic["isi_threshold_ms"]
    pair = np.asarray(diagnostic["ordinary_pair_ms"])
    start = pair[0] - 1.5
    selected = (time_ms >= start) & (time_ms <= pair[1] + 1.5)
    bad = diagnostic["violating_trace"]
    for column, (times, volts, spikes, title, color) in enumerate((
        (time_ms[selected] - start, voltage[selected], pair - start,
         "Non-violating pair", "#0072B2"),
        (np.asarray(bad["time_ms"]),
         np.asarray(bad["raw_adc"]) * bad["gain_to_uv"] + bad["offset_to_uv"],
         np.asarray(bad["unit_spike_times_ms"]),
         "Violating pair", "#B44235"),
    )):
        axis = figure.add_subplot(grid[1, column])
        axis.set_gid("panel-A-ordinary-isi" if column == 0 else "panel-A-violating-isi")
        axis.plot(times, volts, color="#293133", linewidth=0.9,
                  gid="recorded-ordinary-pair" if column == 0 else "recorded-violating-pair")
        span = np.ptp(volts)
        level = volts.max() + 0.1 * span
        axis.scatter(spikes, np.full(2, level), color=color, marker="v", s=18, linewidths=0)
        axis.annotate("", (spikes[0], level + 0.2 * span),
                      (spikes[1], level + 0.2 * span),
                      arrowprops={"arrowstyle": "<->", "color": color, "lw": 1})
        sign = "≥" if column == 0 else "<"
        axis.text(np.mean(spikes), level + 0.28 * span,
                  f"{np.diff(spikes)[0]:.2f} ms {sign} {threshold:g} ms",
                  ha="center", va="bottom", color=color, fontsize=10)
        axis.set(xlim=(times[0], times[-1]),
                 ylim=(volts.min() - 0.1 * span, level + 0.65 * span),
                 xlabel="Time in zoom (ms)", ylabel="Voltage (µV)")
        axis.set_title(title, fontsize=10, fontweight="bold", pad=5)
        axis.tick_params(labelsize=9)

    snr = diagnostic["snr"]
    axis = figure.add_subplot(grid[1, 2])
    axis.set_gid("panel-A-measured-snr")
    noise = snr["noise_sigma_uv"]
    recording = snr["recording"]
    rate = recording["sample_rate_hz"]
    center = round(assigned_spikes[1] * rate / 1000)
    half_window = round(0.01 * rate)
    recording_voltage = np.asarray(recording["voltage_uv"])[
        center - half_window:center + half_window
    ]
    recording_time = np.arange(len(recording_voltage)) * 1000 / rate
    axis.axhspan(-noise, noise, color="#D3D3D3", alpha=0.6, zorder=0,
                 gid="saved-noise-band")
    axis.axhline(0, color="#9AA29F", linewidth=0.7)
    axis.plot(recording_time, recording_voltage, color="#293133", linewidth=0.9,
              gid="recorded-snr-voltage")
    span = np.ptp(recording_voltage)
    axis.set(
        xlim=(0, 20), ylim=(recording_voltage.min() - 0.1 * span,
                           recording_voltage.max() + 0.1 * span),
        xlabel="Time (ms)", ylabel="Voltage (µV)", xticks=[0, 10, 20],
    )
    trough = int(np.argmin(recording_voltage))
    arrow_x = recording_time[trough] + 2
    axis.hlines([0, recording_voltage[trough]], recording_time[trough], arrow_x,
                 color="#69716F", linewidth=0.7)
    axis.annotate("", (arrow_x, 0), (arrow_x, recording_voltage[trough]),
                  arrowprops={"arrowstyle": "<->", "color": "#293133", "lw": 1,
                              "gid": "recorded-spike-amplitude"})
    axis.text(arrow_x + 0.6, recording_voltage[trough] / 2, "Amplitude",
              fontsize=9, va="center")
    axis.set_title("SNR: amplitude / noise", fontsize=10, fontweight="bold", pad=5)
    axis.tick_params(labelsize=9)
    box = slot.get_position(figure)
    figure.text(box.x0 - 0.045, box.y1 + 0.035, "A", fontsize=18,
                fontweight="bold", ha="left", va="bottom", gid="panel-label-A")


def write_ecephys_qc_svg(output: Path = OUT_SVG_PATH, data_path: Path = DATA_JSON_PATH) -> Path:
    if not data_path.exists():
        print(f"Skipping Ecephys QC SVG generation: {data_path.name} not found locally.")
        return output

    print("Generating QC metric guide, distributions, and recording-day yield SVG...")
    master_data = load_ecephys_qc_data(data_path)
    unit_trace = load_ecephys_unit_trace()

    df = pd.DataFrame(master_data.get("units", {}))

    qc_df = df[
        (df["isi_violations_ratio"] < 0.01)
        & (df["presence_ratio"] > 0.90)
        & (df["amplitude_cutoff"] < 0.10)
        & (df["snr"] >= 3.0)
        & (df["depth_from_cortex_um"] >= 0.0)
        & (df["area"] != "void")
    ].copy()

    with mpl.rc_context():
        mpl.rcdefaults()
        mpl.rcParams.update(_SVG_RC_PARAMS)
        fig = plt.figure(figsize=(12.4, 10.0))
        layout = fig.add_gridspec(3, 6, height_ratios=[1.12, 1, 1.15])
        drift_grid = layout[2, :3].subgridspec(1, 2, width_ratios=[1, 1.2], wspace=0.4)
        axs = np.array([
            [fig.add_subplot(layout[1, :2]), fig.add_subplot(layout[1, 2:4])],
            [fig.add_subplot(drift_grid[0, 1]), fig.add_subplot(layout[2, 3:])],
        ])
        fig.subplots_adjust(
            wspace=1.2, hspace=0.36, top=0.88, bottom=0.10, left=0.08, right=0.96
        )
        _draw_metric_guide(fig, layout[0, :], unit_trace)
        for axis, label in zip(axs.flat, "BCFG", strict=True):
            axis.set_gid(f"panel-{label}-metrics")

        mice = sorted(qc_df["mouse_id"].dropna().unique())
        color_first = "#0072B2"
        color_last = "#D55E00"

        def plot_ecdf(ax, metric, title, log_x=False, clip_99=False):
            for mouse in mice:
                mouse_df = qc_df[qc_df["mouse_id"] == mouse]
                first_m = (
                    mouse_df[mouse_df["session_stage"] == "First"][metric].dropna().sort_values()
                )
                last_m = (
                    mouse_df[mouse_df["session_stage"] == "Last"][metric].dropna().sort_values()
                )

                if metric == "isi_violations_ratio":
                    first_m = first_m.replace(0, 1e-6)
                    last_m = last_m.replace(0, 1e-6)

                if len(first_m) > 0:
                    y_f = np.arange(1, len(first_m) + 1) / len(first_m) * 100
                    ax.step(
                        first_m, y_f, where="post", color=color_first, alpha=0.25, linewidth=1
                    )
                if len(last_m) > 0:
                    y_l = np.arange(1, len(last_m) + 1) / len(last_m) * 100
                    ax.step(last_m, y_l, where="post", color=color_last, alpha=0.25, linewidth=1)

            first_vals = qc_df[qc_df["session_stage"] == "First"][metric].dropna().sort_values()
            last_vals = qc_df[qc_df["session_stage"] == "Last"][metric].dropna().sort_values()

            if metric == "isi_violations_ratio":
                first_vals = first_vals.replace(0, 1e-6)
                last_vals = last_vals.replace(0, 1e-6)

            y_first = np.arange(1, len(first_vals) + 1) / len(first_vals) * 100
            y_last = np.arange(1, len(last_vals) + 1) / len(last_vals) * 100

            ax.step(
                first_vals,
                y_first,
                where="post",
                color=color_first,
                linewidth=2,
                label="First Session",
            )
            ax.step(
                last_vals,
                y_last,
                where="post",
                color=color_last,
                linewidth=2,
                label="Last Session",
            )

            ax.set_title(title, fontweight="bold")
            ax.set_ylabel("Cumulative % of Units")
            ax.set_ylim(0, 105)
            ax.grid(False)

            if log_x:
                ax.set_xscale("log")
                if metric == "isi_violations_ratio":
                    ax.set_xlim(left=1e-6, right=1e-2)
                elif metric == "snr":
                    ax.set_xlim(left=min(first_vals.min(), last_vals.min()), right=100)
            else:
                ax.set_xlim(left=0)

            if clip_99:
                limit = qc_df[metric].quantile(0.99)
                if pd.isna(limit) or limit == 0:
                    limit = 100
                ax.set_xlim(left=0, right=limit)

            ax.legend(loc="lower right", frameon=False, borderpad=1)

        plot_ecdf(axs[0, 0], "snr", "SNR Degradation", log_x=True)
        axs[0, 0].set_xlabel("SNR")

        plot_ecdf(axs[0, 1], "isi_violations_ratio", "ISI Violations", log_x=True)
        axs[0, 1].set_xlabel("ISI Violations Ratio")

        plot_ecdf(axs[1, 0], "drift_ptp", "Unit-location Drift", clip_99=True)
        axs[1, 0].set_title("Unit-location Drift", fontsize=11, fontweight="bold")
        axs[1, 0].set_xlabel("Peak-to-Peak Drift (µm)", fontsize=9)
        axs[1, 0].legend(loc="lower right", frameon=False, borderpad=0.6)
        drift = unit_trace["diagnostics"]["drift"]
        measured = fig.add_subplot(drift_grid[0, 0])
        measured.set_gid("panel-E-measured-drift")
        relative_depth = np.asarray(drift["median_depth_um"], dtype=float)
        relative_depth -= drift["reference_depth_um"]
        measured.plot(drift["time_minutes"], relative_depth, color="#000000",
                      linestyle="-", marker="o", linewidth=1.2, markersize=2,
                      gid="recorded-unit-drift")
        low, high = np.nanmin(relative_depth), np.nanmax(relative_depth)
        measured.annotate("", (99, low), (99, high),
                          arrowprops={"arrowstyle": "<->", "color": "#293133", "lw": 1})
        measured.set(xlim=(0, 120), ylim=(low - 3, high + 3), xticks=[0, 45, 90])
        measured.text(107, (low + high) / 2, "Measure unit drift",
                      fontsize=9, rotation=90, va="center", ha="left",
                      gid="measured-drift-label")
        measured.set_xlabel("Session time (min)", fontsize=9)
        measured.set_ylabel("Δ depth (µm)", fontsize=9)
        measured.tick_params(labelsize=9)
        ax = axs[1, 1]
        bin_size = 50
        max_depth = int(np.ceil(qc_df["depth_from_cortex_um"].max() / bin_size) * bin_size)
        y_bins = np.arange(0, max_depth + bin_size, bin_size)

        z_matrix = np.full((len(y_bins) - 1, len(mice)), np.nan)
        for m_idx, mouse in enumerate(mice):
            mouse_df = qc_df[qc_df["mouse_id"] == mouse]
            for b_idx in range(len(y_bins) - 1):
                bin_df = mouse_df[
                    (mouse_df["depth_from_cortex_um"] >= y_bins[b_idx])
                    & (mouse_df["depth_from_cortex_um"] < y_bins[b_idx + 1])
                ]
                if not bin_df.empty:
                    z_matrix[b_idx, m_idx] = bin_df["snr"].mean()

        z_flat = z_matrix[~np.isnan(z_matrix)]
        vmax = np.percentile(z_flat, 99) if len(z_flat) > 0 else 25

        im = ax.pcolormesh(
            np.arange(len(mice) + 1) - 0.5,
            y_bins,
            z_matrix,
            shading="flat",
            antialiased=False,
            rasterized=False,
            edgecolors="face",
            linewidth=0.15,
            cmap="viridis",
            vmin=0,
            vmax=vmax,
        )
        im.set_gid("panel-G-snr-depth-cells")
        ax.set_ylim(y_bins[-1], y_bins[0])
        ax.set_xticks(range(len(mice)))
        ax.set_xticklabels(mice, rotation=-45, ha="left")
        ax.set_title("SNR Depth Profile", fontweight="bold")
        ax.set_ylabel("Depth from Cortical Entry (µm)")
        ax.set_xlabel("Mouse ID")

        cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        cbar.solids.set_rasterized(False)
        cbar.set_label("Mean SNR")

        yield_payload = load_unit_yield_data()
        yield_records = [record for record in yield_payload["records"] if record["included"]]
        yield_axis = fig.add_subplot(layout[1, 4:])
        yield_axis.set_gid("panel-D-unit-yield")
        for index, mouse_id in enumerate(sorted({record["mouse_id"] for record in yield_records})):
            records = [record for record in yield_records if record["mouse_id"] == mouse_id]
            yield_axis.plot([record["day"] for record in records],
                            [record["percentOfDay1"] for record in records],
                            color="#9AA29F", alpha=0.6, linewidth=1,
                            label="Individual mice" if index == 0 else None)
        days = [record["day"] for record in yield_payload["summary"]]
        means = [record["meanPercent"] for record in yield_payload["summary"]]
        mean_line, = yield_axis.plot(days, means, "o-", color="#222829", linewidth=2.2,
                                    label="Daily mean", markersize=5)
        mean_line.set_gid("unit-yield-daily-mean")
        yield_axis.axhline(100, color="#69716F", linestyle="--", linewidth=0.8)
        yield_axis.set_title("Unit yield across days", fontweight="bold")
        yield_axis.set(xlabel="Recording day", ylabel="Yield (% of day 1)", ylim=(0, 145),
                       xlim=(min(days) - 0.5, max(days) + 0.5))
        yield_axis.set_xticks(days)
        yield_axis.legend(loc="lower left", frameon=False)
        for record in yield_payload["summary"]:
            yield_axis.text(record["day"], 0.96, f"n = {record['sessionCount']}",
                            transform=yield_axis.get_xaxis_transform(),
                            ha="center", va="top", fontsize=9,
                            gid=f"yield-session-count-day-{record['day']}")
        for axis, letter in (
            (axs[0, 0], "B"), (axs[0, 1], "C"), (yield_axis, "D"),
            (measured, "E"), (axs[1, 0], "F"), (axs[1, 1], "G"),
        ):
            axis.text(-0.15, 1.1, letter, transform=axis.transAxes, fontsize=18,
                      fontweight="bold", va="top", ha="right", gid=f"panel-label-{letter}")

        svg_buf = io.StringIO()
        fig.savefig(
            svg_buf,
            format="svg",
            bbox_inches="tight",
            metadata={"Date": None, "Creator": None},
        )
        plt.close(fig)

    svg_text = _canonicalize_svg_embedded_pngs(svg_buf.getvalue())
    root = ET.fromstring(svg_text)
    root.set("data-metric-guide", "recorded-isi-snr-and-unit-location-drift")
    root.set("data-trace-unit", str(unit_trace["unit_id"]))
    root.set("data-trace-session", unit_trace["session"])
    root.set("data-panel-layout", "A/BCD/EFG")
    for label in root.iter("{http://www.w3.org/2000/svg}text"):
        label.set("font-family", FIGURE_SANS_FONT)
        label.set("style", re.sub(r"font-family:[^;]+", f"font-family: {FIGURE_SANS_FONT}",
                                  label.get("style", "")))
    svg_text = normalize_figure_svg(ET.tostring(root, encoding="unicode"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(svg_text, encoding="utf-8", newline="\n")

    if output == OUT_SVG_PATH:
        DEPLOY_SVG_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(output, DEPLOY_SVG_PATH)

    print(f"Static SVG saved to: {output}")
    return output


def write_ecephys_qc_html(
    output: Path = OUT_HTML_PATH, data_path: Path = DATA_JSON_PATH
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)

    if output == OUT_HTML_PATH:
        DEPLOY_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        if data_path.exists():
            shutil.copy2(data_path, DEPLOY_JSON_PATH)
        if OUT_SVG_PATH.exists():
            shutil.copy2(OUT_SVG_PATH, DEPLOY_SVG_PATH)

    template = (JAVASCRIPT_DIR / "openscope_qc_dashboard.html").read_text(encoding="utf-8")
    stylesheet = load_figure_stylesheet("openscope_qc_dashboard.css")
    javascript = (JAVASCRIPT_DIR / "openscope_qc_dashboard.js").read_text(encoding="utf-8")

    html = (
        template.replace("__QC_DASHBOARD_CSS__", stylesheet)
        .replace("__QC_DASHBOARD_JS__", javascript)
        .replace("__EMBED_AUTO_HEIGHT_JS__", load_figure_controls())
    )
    output.write_text(html, encoding="utf-8", newline="\n")
    return output
