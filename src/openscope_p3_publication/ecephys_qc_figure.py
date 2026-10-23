from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import re
import shutil
import struct
import zlib
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image

from .figures import load_figure_controls, load_figure_stylesheet

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_JSON_PATH = REPO_ROOT / "figure_sources" / "data" / "ecephys-qc-dashboard.json.gz"
PROVENANCE_JSON_PATH = (
    REPO_ROOT / "figure_sources" / "data" / "ecephys-qc-dashboard.provenance.json"
)
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
    "axes.titlesize": 12,
    "axes.labelsize": 10,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "svg.fonttype": "none",
    "svg.hashsalt": "openscope_qc_dashboard",
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

    return _EMBEDDED_PNG_RE.sub(_replace, svg_text)


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


def write_ecephys_qc_svg(output: Path = OUT_SVG_PATH, data_path: Path = DATA_JSON_PATH) -> Path:
    if not data_path.exists():
        print(f"Skipping Ecephys QC SVG generation: {data_path.name} not found locally.")
        return output

    print("Generating polished 4-panel static SVG using Matplotlib...")
    master_data = load_ecephys_qc_data(data_path)

    df = pd.DataFrame(master_data.get("units", {}))

    qc_df = df[
        (df["isi_violations_ratio"] < 0.01)
        & (df["presence_ratio"] > 0.90)
        & (df["amplitude_cutoff"] < 0.10)
        & (df["snr"] >= 3.0)
        & (df["depth_from_cortex_um"] >= 0.0)
        & (df["area"] != "void")
    ].copy()

    with mpl.rc_context(_SVG_RC_PARAMS):
        fig, axs = plt.subplots(2, 2, figsize=(10, 8.5))
        fig.subplots_adjust(
            wspace=0.25, hspace=0.35, top=0.92, bottom=0.08, left=0.08, right=0.95
        )
        fig.suptitle(
            "Neuropixels Unit Quality Control and Stability",
            fontsize=16,
            fontweight="bold",
            x=0.05,
            ha="left",
        )

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
            ax.grid(True, linestyle="--", alpha=0.5)

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

            ax.legend(loc="lower right", frameon=True, fancybox=True, shadow=False, borderpad=1)

        # A: SNR
        plot_ecdf(axs[0, 0], "snr", "SNR Degradation", log_x=True)
        axs[0, 0].set_xlabel("SNR")
        axs[0, 0].text(
            -0.15,
            1.1,
            "A",
            transform=axs[0, 0].transAxes,
            fontsize=18,
            fontweight="bold",
            va="top",
            ha="right",
        )

        # B: ISI
        plot_ecdf(axs[0, 1], "isi_violations_ratio", "ISI Violations", log_x=True)
        axs[0, 1].set_xlabel("ISI Violations Ratio")
        axs[0, 1].text(
            -0.15,
            1.1,
            "B",
            transform=axs[0, 1].transAxes,
            fontsize=18,
            fontweight="bold",
            va="top",
            ha="right",
        )

        # C: Drift
        plot_ecdf(axs[1, 0], "drift_ptp", "Physical Drift", clip_99=True)
        axs[1, 0].set_xlabel("Peak-to-Peak Drift (µm)")
        axs[1, 0].text(
            -0.15,
            1.1,
            "C",
            transform=axs[1, 0].transAxes,
            fontsize=18,
            fontweight="bold",
            va="top",
            ha="right",
        )

        # D: Heatmap
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

        im = ax.imshow(
            z_matrix,
            aspect="auto",
            interpolation="none",
            cmap="viridis",
            vmin=0,
            vmax=vmax,
            extent=[-0.5, len(mice) - 0.5, y_bins[-1], y_bins[0]],
        )
        ax.set_xticks(range(len(mice)))
        ax.set_xticklabels(mice, rotation=-45, ha="left")
        ax.set_title("SNR Depth Profile", fontweight="bold")
        ax.set_ylabel("Depth from Cortical Entry (µm)")
        ax.set_xlabel("Mouse ID")
        ax.text(
            -0.15,
            1.1,
            "D",
            transform=ax.transAxes,
            fontsize=18,
            fontweight="bold",
            va="top",
            ha="right",
        )

        cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        cbar.solids.set_rasterized(False)
        cbar.set_label("Mean SNR")

        svg_buf = io.StringIO()
        fig.savefig(
            svg_buf,
            format="svg",
            bbox_inches="tight",
            metadata={"Date": None, "Creator": None},
        )
        plt.close(fig)

    svg_text = _canonicalize_svg_embedded_pngs(svg_buf.getvalue())
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
