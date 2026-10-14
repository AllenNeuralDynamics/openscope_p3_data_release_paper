from __future__ import annotations

import json
import shutil
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .figures import load_figure_controls, load_figure_stylesheet

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_JSON_PATH = REPO_ROOT / "figure_sources" / "data" / "ecephys-qc-dashboard.json"
OUT_HTML_PATH = REPO_ROOT / "interactive" / "openscope_qc_dashboard.html"
OUT_SVG_PATH = REPO_ROOT / "images" / "figures" / "generated" / "openscope_qc_dashboard_static.svg"
DEPLOY_JSON_PATH = (
    REPO_ROOT / "interactive" / "media" / "ecephys-qc-dashboard" / "ecephys-qc-dashboard.json"
)
DEPLOY_SVG_PATH = DEPLOY_JSON_PATH.parent / "openscope_qc_dashboard_static.svg"
JAVASCRIPT_DIR = REPO_ROOT / "figure_sources" / "javascript"


def write_ecephys_qc_svg(output: Path = OUT_SVG_PATH, data_path: Path = DATA_JSON_PATH) -> Path:
    if not data_path.exists():
        print(f"Skipping Ecephys QC SVG generation: {data_path.name} not found locally.")
        return output

    print("Generating polished 4-panel static SVG using Matplotlib...")
    with open(data_path, encoding="utf-8") as f:
        master_data = json.load(f)

    df = pd.DataFrame(master_data.get("units", []))

    qc_df = df[
        (df["isi_violations_ratio"] < 0.01)
        & (df["presence_ratio"] > 0.90)
        & (df["amplitude_cutoff"] < 0.10)
        & (df["snr"] >= 3.0)
        & (df["depth_from_cortex_um"] >= 0.0)
        & (df["area"] != "void")
    ].copy()

    mpl.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "DejaVu Sans"],
            "font.size": 10,
            "axes.titlesize": 12,
            "axes.labelsize": 10,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "svg.fonttype": "none",
        }
    )

    fig, axs = plt.subplots(2, 2, figsize=(10, 8.5))
    fig.subplots_adjust(wspace=0.25, hspace=0.35, top=0.92, bottom=0.08, left=0.08, right=0.95)
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
            first_m = mouse_df[mouse_df["session_stage"] == "First"][metric].dropna().sort_values()
            last_m = mouse_df[mouse_df["session_stage"] == "Last"][metric].dropna().sort_values()

            if metric == "isi_violations_ratio":
                first_m = first_m.replace(0, 1e-6)
                last_m = last_m.replace(0, 1e-6)

            if len(first_m) > 0:
                y_f = np.arange(1, len(first_m) + 1) / len(first_m) * 100
                ax.step(first_m, y_f, where="post", color=color_first, alpha=0.25, linewidth=1)
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
            first_vals, y_first, where="post", color=color_first, linewidth=2, label="First Session"
        )
        ax.step(
            last_vals, y_last, where="post", color=color_last, linewidth=2, label="Last Session"
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
    cbar.set_label("Mean SNR")

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, format="svg", bbox_inches="tight")
    plt.close(fig)

    # Automatically deploy copy for the interactive web viewer
    DEPLOY_SVG_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output, DEPLOY_SVG_PATH)

    print(f"Static SVG saved to: {output} and deployed to: {DEPLOY_SVG_PATH}")
    return output


def write_ecephys_qc_html(
    output: Path = OUT_HTML_PATH, data_path: Path = DATA_JSON_PATH
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
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
