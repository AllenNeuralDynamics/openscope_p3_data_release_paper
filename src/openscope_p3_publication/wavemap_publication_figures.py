from __future__ import annotations

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import TwoSlopeNorm

from .wavemap_figure import REPO_ROOT, load_wavemap_snapshot


OUT = REPO_ROOT / "images" / "figures" / "generated"

GROUP_ORDER = ["MO", "PFC", "VIS", "STR", "HPC", "THAL"]

GROUP_NAMES = {
    "MO": "Motor cortex",
    "PFC": "Prefrontal cortex",
    "VIS": "Visual cortex",
    "STR": "Striatum",
    "HPC": "Hippocampus",
    "THAL": "Thalamus",
}

CONTEXT_ORDER = [
    "Standard oddball",
    "Sensorimotor mismatch",
    "Sequence mismatch",
    "Duration mismatch",
]

CONTEXT_SHORT = {
    "Standard oddball": "Standard",
    "Sensorimotor mismatch": "Sensorimotor",
    "Sequence mismatch": "Sequence",
    "Duration mismatch": "Duration",
}


mpl.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "DejaVu Sans"],
    "font.size": 8,
    "axes.titlesize": 9,
    "axes.labelsize": 8,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "legend.fontsize": 6,
    "axes.linewidth": 0.6,
    "xtick.major.width": 0.6,
    "ytick.major.width": 0.6,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "savefig.dpi": 600,
})


def _panel_letter(fig, letter, x=0.018, y=0.985):
    fig.text(
        x, y, letter,
        ha="left",
        va="top",
        fontsize=12,
        fontweight="bold",
    )


def _clean_umap(ax):
    # Preserve true UMAP geometry.
    ax.set_aspect("equal", adjustable="box")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_xlabel("")
    ax.set_ylabel("")

    for spine in ax.spines.values():
        spine.set_visible(False)


def _save(fig, stem):
    OUT.mkdir(parents=True, exist_ok=True)

    png = OUT / f"{stem}.png"
    pdf = OUT / f"{stem}.pdf"

    fig.savefig(
        png,
        dpi=600,
        bbox_inches="tight",
        facecolor="white",
    )

    fig.savefig(
        pdf,
        bbox_inches="tight",
        facecolor="white",
    )

    plt.close(fig)

    print(f"Wrote {png.relative_to(REPO_ROOT)}")
    print(f"Wrote {pdf.relative_to(REPO_ROOT)}")

    return png, pdf


def _context_matrix(df, group, value):
    sub = df[df["group"] == group].copy()

    classes = (
        sub[["wavemap_local", "wavemap_label"]]
        .drop_duplicates()
        .sort_values("wavemap_local")
    )

    order = classes["wavemap_local"].tolist()
    labels = classes["wavemap_label"].astype(str).tolist()

    matrix = (
        sub.pivot(
            index="wavemap_local",
            columns="context",
            values=value,
        )
        .reindex(
            index=order,
            columns=CONTEXT_ORDER,
        )
        .to_numpy(dtype=float)
    )

    return matrix, labels


# ============================================================
# A — WAVEMAP UMAPS
# ============================================================

def build_umap_figure(snapshot):
    units = snapshot["units_df"]
    colours = snapshot["AREA_CLUSTER_COLORS"]

    fig, axes = plt.subplots(
        2,
        3,
        figsize=(7.2, 5.25),
    )

    fig.subplots_adjust(
        left=0.055,
        right=0.985,
        top=0.94,
        bottom=0.055,
        wspace=0.12,
        hspace=0.16,
    )

    for ax, group in zip(axes.flat, GROUP_ORDER):

        sub = units[
            (units["wavemap_group"] == group)
            & units["wavemap_local"].notna()
            & (units["wavemap_local"] > 0)
        ].copy()

        for local in sorted(
            sub["wavemap_local"].astype(int).unique()
        ):
            pts = sub[
                sub["wavemap_local"].astype(int) == local
            ]

            ax.scatter(
                pts["umap_x"],
                pts["umap_y"],
                s=2.2,
                color=colours[(group, int(local))],
                alpha=0.82,
                linewidths=0,
                rasterized=True,
            )

        ax.set_title(
            GROUP_NAMES[group],
            fontweight="bold",
            pad=3,
        )

        _clean_umap(ax)

    _panel_letter(fig, "A")

    return _save(fig, "wavemap-umap")


# ============================================================
# B — MEAN WAVEMAP WAVEFORMS
# ============================================================

def build_waveform_figure(snapshot):
    units = snapshot["units_df"]
    norm_wfs = np.asarray(snapshot["normWFs"])
    colours = snapshot["AREA_CLUSTER_COLORS"]

    if len(units) != len(norm_wfs):
        raise RuntimeError(
            "Waveform matrix and unit metadata are not row-aligned."
        )

    # Taller figure deliberately gives each waveform panel room
    # for its own legend underneath.
    fig, axes = plt.subplots(
        2,
        3,
        figsize=(7.2, 6.3),
    )

    fig.subplots_adjust(
        left=0.09,
        right=0.985,
        top=0.94,
        bottom=0.10,
        wspace=0.28,
        hspace=0.68,
    )

    sampling_rate = float(snapshot["WF_SAMPLING_RATE"])
    n_samples = norm_wfs.shape[1]

    if np.isfinite(sampling_rate) and sampling_rate > 0:
        x = np.arange(n_samples) / sampling_rate * 1000.0
        xlabel = "Time (ms)"
    else:
        x = np.arange(n_samples)
        xlabel = "Waveform sample"

    groups = units["wavemap_group"].to_numpy()

    local_values = pd.to_numeric(
        units["wavemap_local"],
        errors="coerce",
    ).to_numpy()

    for ax, group in zip(axes.flat, GROUP_ORDER):

        group_mask = groups == group

        local_classes = sorted(
            units.loc[
                group_mask
                & units["wavemap_local"].notna()
                & (units["wavemap_local"] > 0),
                "wavemap_local",
            ]
            .astype(int)
            .unique()
        )

        for local in local_classes:

            mask = (
                group_mask
                & np.isfinite(local_values)
                & (local_values == local)
            )

            # Same mean-waveform definition already used in the
            # approved WaveMAP analysis.
            mean_wave = norm_wfs[mask].mean(axis=0)

            ax.plot(
                x,
                mean_wave,
                color=colours[(group, int(local))],
                linewidth=1.5,
                alpha=1.0,
                label=f"{group}-{local}",
            )

        ax.axhline(
            0,
            color="#BDBDBD",
            linewidth=0.5,
            zorder=0,
        )

        ax.set_title(
            GROUP_NAMES[group],
            fontweight="bold",
            pad=4,
        )

        ax.set_xlabel(xlabel)
        ax.set_ylabel("Normalized amplitude")

        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        # IMPORTANT:
        # legend is completely outside the data area.
        ncol = min(4, max(1, len(local_classes)))

        ax.legend(
            loc="upper center",
            bbox_to_anchor=(0.5, -0.25),
            frameon=False,
            ncol=ncol,
            fontsize=6,
            handlelength=1.5,
            handletextpad=0.35,
            columnspacing=0.8,
            borderaxespad=0,
        )

    _panel_letter(fig, "B")

    return _save(fig, "wavemap-waveforms")


# ============================================================
# C — FS / SST
# ============================================================

def build_fs_sst_figure(snapshot):
    df = snapshot["map_df"]

    # More vertical room than previous version so each UMAP can
    # retain equal aspect without becoming tiny.
    fig = plt.figure(figsize=(7.2, 6.5))

    gs = fig.add_gridspec(
        3,
        7,
        left=0.035,
        right=0.99,
        top=0.94,
        bottom=0.035,
        width_ratios=[0.90, 1, 1, 1, 1, 1, 1],
        wspace=0.035,
        hspace=0.08,
    )

    rows = [
        ("putative_fs", "Putative\nFS/PV-like", "#2878B5"),
        ("sst_optotagged", "Optotagged\nSST", "#C13C84"),
        ("sst_fs_overlap", "SST ∩ FS", "#74469A"),
    ]

    for row, (column, label, colour) in enumerate(rows):

        label_ax = fig.add_subplot(gs[row, 0])
        label_ax.axis("off")

        label_ax.text(
            0.98,
            0.5,
            label,
            ha="right",
            va="center",
            fontsize=8,
            fontweight="bold",
        )

        for col, group in enumerate(GROUP_ORDER):

            ax = fig.add_subplot(
                gs[row, col + 1]
            )

            sub = df[
                (df["wavemap_group"] == group)
                & df["umap_x"].notna()
                & df["umap_y"].notna()
            ]

            ax.scatter(
                sub["umap_x"],
                sub["umap_y"],
                s=1.3,
                color="#D8D8D8",
                alpha=0.50,
                linewidths=0,
                rasterized=True,
            )

            selected = sub[
                sub[column]
                .fillna(False)
                .astype(bool)
            ]

            ax.scatter(
                selected["umap_x"],
                selected["umap_y"],
                s=4.5,
                color=colour,
                alpha=0.95,
                linewidths=0,
                rasterized=True,
            )

            if row == 0:
                ax.set_title(
                    GROUP_NAMES[group],
                    fontweight="bold",
                    fontsize=7.5,
                    pad=3,
                )

            _clean_umap(ax)

    _panel_letter(fig, "C")

    return _save(fig, "wavemap-fs-sst")


# ============================================================
# D — CONTEXT
# D1 = composition
# D2 = enrichment
# ============================================================

def build_context_figure(snapshot):

    absolute = snapshot["region_context_summary"]
    enrichment = snapshot["enrich_df"]

    fig = plt.figure(figsize=(7.2, 8.1))

    outer = fig.add_gridspec(
        2,
        1,
        left=0.075,
        right=0.88,
        top=0.95,
        bottom=0.075,
        hspace=0.38,
    )

    gs_top = outer[0].subgridspec(
        2,
        3,
        wspace=0.34,
        hspace=0.46,
    )

    gs_bottom = outer[1].subgridspec(
        2,
        3,
        wspace=0.34,
        hspace=0.46,
    )

    im_abs = None

    for i, group in enumerate(GROUP_ORDER):

        ax = fig.add_subplot(
            gs_top[i // 3, i % 3]
        )

        matrix, labels = _context_matrix(
            absolute,
            group,
            "mean_percent",
        )

        im_abs = ax.imshow(
            matrix,
            aspect="auto",
            interpolation="nearest",
            cmap="viridis",
            vmin=0,
            vmax=20,
        )

        ax.set_title(
            GROUP_NAMES[group],
            loc="left",
            fontweight="bold",
            pad=3,
        )

        ax.set_yticks(np.arange(len(labels)))
        ax.set_yticklabels(labels, fontsize=6.5)

        ax.set_xticks(np.arange(len(CONTEXT_ORDER)))
        ax.set_xticklabels(
            [CONTEXT_SHORT[c] for c in CONTEXT_ORDER],
            rotation=30,
            ha="right",
            rotation_mode="anchor",
            fontsize=6.2,
        )

        ax.tick_params(length=0)

        for spine in ax.spines.values():
            spine.set_visible(False)

    norm = TwoSlopeNorm(
        vmin=-1.0,
        vcenter=0.0,
        vmax=1.0,
    )

    im_enr = None

    for i, group in enumerate(GROUP_ORDER):

        ax = fig.add_subplot(
            gs_bottom[i // 3, i % 3]
        )

        matrix, labels = _context_matrix(
            enrichment,
            group,
            "log2_enrichment",
        )

        im_enr = ax.imshow(
            matrix,
            aspect="auto",
            interpolation="nearest",
            cmap="RdBu_r",
            norm=norm,
        )

        ax.set_title(
            GROUP_NAMES[group],
            loc="left",
            fontweight="bold",
            pad=3,
        )

        ax.set_yticks(np.arange(len(labels)))
        ax.set_yticklabels(labels, fontsize=6.5)

        ax.set_xticks(np.arange(len(CONTEXT_ORDER)))
        ax.set_xticklabels(
            [CONTEXT_SHORT[c] for c in CONTEXT_ORDER],
            rotation=30,
            ha="right",
            rotation_mode="anchor",
            fontsize=6.2,
        )

        ax.tick_params(length=0)

        for spine in ax.spines.values():
            spine.set_visible(False)

    # Colourbars have their own columns outside all heatmaps.
    cax1 = fig.add_axes(
        [0.91, 0.575, 0.016, 0.27]
    )

    cb1 = fig.colorbar(
        im_abs,
        cax=cax1,
    )

    cb1.set_label(
        "Mean units per class (%)",
        fontsize=7,
    )

    cb1.ax.tick_params(
        labelsize=6.5,
        width=0.5,
    )

    cax2 = fig.add_axes(
        [0.91, 0.155, 0.016, 0.27]
    )

    cb2 = fig.colorbar(
        im_enr,
        cax=cax2,
    )

    cb2.set_label(
        "log$_2$ enrichment",
        fontsize=7,
    )

    cb2.set_ticks(
        [-1, -0.5, 0, 0.5, 1]
    )

    cb2.ax.tick_params(
        labelsize=6.5,
        width=0.5,
    )

    # Main panel + internal subpanel lettering.
    _panel_letter(fig, "D")

    fig.text(
        0.055,
        0.94,
        "D1",
        fontsize=9,
        fontweight="bold",
        ha="left",
        va="top",
    )

    fig.text(
        0.055,
        0.505,
        "D2",
        fontsize=9,
        fontweight="bold",
        ha="left",
        va="top",
    )

    return _save(fig, "wavemap-context")


def main():
    snapshot = load_wavemap_snapshot()

    build_umap_figure(snapshot)
    build_waveform_figure(snapshot)
    build_fs_sst_figure(snapshot)
    build_context_figure(snapshot)


if __name__ == "__main__":
    main()
