from __future__ import annotations

import base64
import io
import json
import re
import zlib
from pathlib import Path
from xml.etree import ElementTree

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfFile, PdfPages, Verbatim
from matplotlib.cm import ScalarMappable
from matplotlib.colors import LinearSegmentedColormap, Normalize, TwoSlopeNorm
from matplotlib.text import Text
from PIL import Image

from openscope_p3_publication.figure_typography import normalize_figure_svg
from openscope_p3_publication.image_encoding import canonical_png as _canonical_png
from openscope_p3_publication.image_encoding import canonical_svg_images
from openscope_p3_publication.wavemap_figure import (
    REPO_ROOT,
    load_wavemap_snapshot,
    verified_waveform_sampling_rate,
)

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


mpl.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["DejaVu Sans"],
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
    }
)


def _panel_letter(fig, letter, x=0.018, y=0.985):
    fig.text(
        x,
        y,
        letter,
        ha="left",
        va="top",
        fontsize=12,
        fontweight="bold",
        gid=f"panel-label-{letter}",
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


class _CanonicalPdfFile(PdfFile):
    """Normalize platform-dependent lossless image and path encodings."""

    @staticmethod
    def pathOperations(path, transform, clip=None, simplify=None, sketch=None):
        operations = PdfFile.pathOperations(path, transform, clip, simplify, sketch)
        return [
            Verbatim(re.sub(rb"(?<!\S)-0(?!\S)", b"0", operation.pdfRepr()))
            for operation in operations
        ]

    def _writePng(self, image: Image.Image) -> tuple[bytes, int, bytes | None]:
        compressed, bit_depth, palette = super()._writePng(image)
        return zlib.compress(zlib.decompress(compressed)), bit_depth, palette


class _CanonicalPdfPages(PdfPages):
    def _ensure_file(self) -> PdfFile:
        if self._file is None:
            self._file = _CanonicalPdfFile(self._filename, metadata=self._metadata)
        return self._file


def _save(fig, stem, output_dir=None, pages=None):
    output_dir = OUT if output_dir is None else output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    png = output_dir / f"{stem}.png"
    pdf = output_dir / f"{stem}.pdf"

    fig.savefig(
        png,
        dpi=600,
        bbox_inches="tight",
        facecolor="white",
    )
    png.write_bytes(_canonical_png(png.read_bytes()))

    with _CanonicalPdfPages(
        pdf,
        metadata={"CreationDate": None, "ModDate": None},
    ) as individual_pages:
        individual_pages.savefig(fig, bbox_inches="tight", facecolor="white")

    if pages is not None:
        pages.savefig(fig, bbox_inches="tight", facecolor="white")
    svg_stem = {
        "wavemap-regional-waveforms": "supplementary-wavemap-regions",
        "wavemap-composition": "supplementary-wavemap-composition",
    }.get(stem)
    if svg_stem is not None:
        buffer = io.StringIO()
        with mpl.rc_context({"svg.fonttype": "none", "svg.hashsalt": "openscope-wavemap"}):
            fig.savefig(buffer, format="svg", bbox_inches="tight", facecolor="white",
                        metadata={"Date": None, "Creator": None})
        (output_dir / f"{svg_stem}.svg").write_text(
            normalize_figure_svg(canonical_svg_images(buffer.getvalue())),
            encoding="utf-8", newline="\n",
        )
    plt.close(fig)

    return png, pdf


def _context_matrix(df, group, value):
    sub = df[df["group"] == group].copy()

    classes = sub[["wavemap_local", "wavemap_label"]].drop_duplicates().sort_values("wavemap_local")

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


def build_umap_figure(snapshot: dict, output_dir: Path | None = None, pages=None) -> tuple:
    """Render the contributed region-specific embeddings without re-embedding."""
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

    for ax, group in zip(axes.flat, GROUP_ORDER, strict=False):
        sub = units[
            (units["wavemap_group"] == group)
            & units["wavemap_local"].notna()
            & (units["wavemap_local"] > 0)
        ].copy()

        for local in sorted(sub["wavemap_local"].astype(int).unique()):
            pts = sub[sub["wavemap_local"].astype(int) == local]

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

    return _save(fig, "wavemap-umap", output_dir, pages)


# ============================================================
# B — MEAN WAVEMAP WAVEFORMS
# ============================================================


def build_waveform_figure(snapshot: dict, output_dir: Path | None = None, pages=None) -> tuple:
    """Render cluster-mean waveforms with only source-supported time calibration."""
    units = snapshot["units_df"]
    norm_wfs = np.asarray(snapshot["normWFs"])
    colours = snapshot["AREA_CLUSTER_COLORS"]

    if len(units) != len(norm_wfs):
        raise RuntimeError("Waveform matrix and unit metadata are not row-aligned.")

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

    sampling_rate = verified_waveform_sampling_rate(snapshot)
    n_samples = norm_wfs.shape[1]

    if sampling_rate is not None:
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

    for ax, group in zip(axes.flat, GROUP_ORDER, strict=False):
        group_mask = groups == group

        local_classes = sorted(
            units.loc[
                group_mask & units["wavemap_local"].notna() & (units["wavemap_local"] > 0),
                "wavemap_local",
            ]
            .astype(int)
            .unique()
        )

        for local in local_classes:
            mask = group_mask & np.isfinite(local_values) & (local_values == local)

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

    return _save(fig, "wavemap-waveforms", output_dir, pages)


# ============================================================
# C — FS / SST
# ============================================================


def build_fs_sst_figure(
    snapshot: dict, output_dir: Path | None = None, pages=None,
    *, panel_letter: str = "C", stem: str = "wavemap-fs-sst",
) -> tuple:
    """Locate the existing operational cell labels within waveform space."""
    df = snapshot["map_df"]

    fig = plt.figure(figsize=(7.2, 3.8))

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
            ax = fig.add_subplot(gs[row, col + 1])

            sub = df[(df["wavemap_group"] == group) & df["umap_x"].notna() & df["umap_y"].notna()]

            ax.scatter(
                sub["umap_x"],
                sub["umap_y"],
                s=1.3,
                color="#D8D8D8",
                alpha=0.50,
                linewidths=0,
                rasterized=True,
            )

            selected = sub[sub[column].fillna(False).astype(bool)]

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
                    GROUP_NAMES[group].replace(" cortex", "\ncortex"),
                    fontweight="bold",
                    fontsize=7.5,
                    pad=3,
                )

            _clean_umap(ax)

    _panel_letter(fig, panel_letter)

    return _save(fig, stem, output_dir, pages)


# ============================================================
# D — CONTEXT
# D1 = composition
# D2 = enrichment
# ============================================================


def build_context_figure(
    snapshot: dict, output_dir: Path | None = None, pages=None, *, standalone: bool = False
) -> tuple:
    """Render the saved context summaries with row spacing based on class counts."""
    absolute = snapshot["region_context_summary"]
    enrichment = snapshot["enrich_df"]

    class_counts = absolute.groupby("group")["wavemap_local"].nunique()
    row_heights = [
        max(int(class_counts[group]) for group in GROUP_ORDER[start:start + 3]) * 0.18 + 0.5
        for start in (0, 3)
    ]
    if standalone:
        fig = plt.figure(figsize=(12.4, max(7.6, sum(row_heights) + 0.8)))
        outer = fig.add_gridspec(
            1, 2, left=0.055, right=0.91, top=0.93, bottom=0.1, wspace=0.55,
        )
        top_slot, bottom_slot = outer[0, 0], outer[0, 1]
    else:
        fig = plt.figure(figsize=(7.2, max(10.0, 2 * sum(row_heights) + 1.0)))
        outer = fig.add_gridspec(
            2, 1, left=0.075, right=0.88, top=0.95, bottom=0.075, hspace=0.38,
        )
        top_slot, bottom_slot = outer[0], outer[1]

    gs_top = top_slot.subgridspec(
        2,
        3,
        height_ratios=row_heights,
        wspace=0.8 if standalone else 0.34,
        hspace=0.46,
    )

    gs_bottom = bottom_slot.subgridspec(
        2,
        3,
        height_ratios=row_heights,
        wspace=0.8 if standalone else 0.34,
        hspace=0.46,
    )

    im_abs = None

    for i, group in enumerate(GROUP_ORDER):
        ax = fig.add_subplot(gs_top[i // 3, i % 3])

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
        ax.set_yticklabels(labels, fontsize=8 if standalone else 6.5)

        ax.set_xticks(np.arange(len(CONTEXT_ORDER)))
        ax.set_xticklabels(
            [CONTEXT_SHORT[c] for c in CONTEXT_ORDER],
            rotation=30,
            ha="right",
            rotation_mode="anchor",
            fontsize=7.5 if standalone else 6.2,
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
        ax = fig.add_subplot(gs_bottom[i // 3, i % 3])

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
        ax.set_yticklabels(labels, fontsize=8 if standalone else 6.5)

        ax.set_xticks(np.arange(len(CONTEXT_ORDER)))
        ax.set_xticklabels(
            [CONTEXT_SHORT[c] for c in CONTEXT_ORDER],
            rotation=30,
            ha="right",
            rotation_mode="anchor",
            fontsize=7.5 if standalone else 6.2,
        )

        ax.tick_params(length=0)

        for spine in ax.spines.values():
            spine.set_visible(False)

    # Colourbars have their own columns outside all heatmaps.
    cax1 = fig.add_axes(
        [top_slot.get_position(fig).x1 + 0.017, 0.19, 0.012, 0.65]
        if standalone else [0.91, 0.575, 0.016, 0.27]
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
        [bottom_slot.get_position(fig).x1 + 0.017, 0.19, 0.012, 0.65]
        if standalone else [0.91, 0.155, 0.016, 0.27]
    )

    cb2 = fig.colorbar(
        im_enr,
        cax=cax2,
    )

    cb2.set_label(
        "log$_2$ enrichment",
        fontsize=7,
    )

    cb2.set_ticks([-1, -0.5, 0, 0.5, 1])

    cb2.ax.tick_params(
        labelsize=6.5,
        width=0.5,
    )

    # Main panel + internal subpanel lettering.
    if not standalone:
        _panel_letter(fig, "D")

    fig.text(
        top_slot.get_position(fig).x0 if standalone else 0.075,
        0.973,
        "A" if standalone else "D1",
        fontsize=16 if standalone else 9,
        fontweight="bold",
        gid="panel-label-A" if standalone else None,
        ha="left",
        va="top",
    )

    fig.text(
        bottom_slot.get_position(fig).x0 if standalone else 0.075,
        0.973 if standalone else gs_bottom[0, 0].get_position(fig).y1 + 0.035,
        "B" if standalone else "D2",
        fontsize=16 if standalone else 9,
        fontweight="bold",
        gid="panel-label-B" if standalone else None,
        ha="left",
        va="top",
    )

    return _save(fig, "wavemap-composition" if standalone else "wavemap-context", output_dir, pages)


def build_wavemap_static_figures(
    snapshot: dict | None = None, output_dir: Path = OUT
) -> tuple[Path, ...]:
    """Build four panels, a self-contained SVG, and a four-page PDF."""
    snapshot = load_wavemap_snapshot() if snapshot is None else snapshot
    output_dir.mkdir(parents=True, exist_ok=True)
    supplementary_pdf = output_dir / "supplementary-wavemap.pdf"
    outputs = []
    with _CanonicalPdfPages(
        supplementary_pdf,
        metadata={
            "CreationDate": None,
            "ModDate": None,
            "Title": "WaveMAP waveform characterization",
        },
    ) as pages:
        for builder in (
            build_umap_figure, build_waveform_figure, build_fs_sst_figure, build_context_figure
        ):
            outputs.extend(builder(snapshot, output_dir, pages))
    images = []
    top = 0.0
    for image_path in outputs:
        if image_path.suffix != ".png":
            continue
        with Image.open(image_path) as image:
            height = image.height * 1200 / image.width
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        images.append(
            f'<image x="0" y="{top:.3f}" width="1200" height="{height:.3f}" '
            f'href="data:image/png;base64,{encoded}"/>'
        )
        top += height + 24
    svg_path = output_dir / "supplementary-wavemap.svg"
    svg_path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{top:.3f}" '
        f'viewBox="0 0 1200 {top:.3f}" role="img" aria-labelledby="wavemap-title">\n'
        '<title id="wavemap-title">WaveMAP waveform characterization</title>\n'
        '<desc>A: regional embeddings. B: cluster mean waveforms in sample coordinates. '
        'C: putative FS and optotagged SST overlays. D: saved context composition and enrichment.'
        '</desc>\n<rect width="100%" height="100%" fill="white"/>\n'
        + "\n".join(images) + "\n</svg>\n",
        encoding="utf-8",
        newline="\n",
    )
    return (*outputs, supplementary_pdf, svg_path)


def _plot_region_embedding(axis, snapshot: dict, group: str) -> None:
    units = snapshot["units_df"]
    region = units[(units["wavemap_group"] == group) & (units["wavemap_local"] > 0)]
    for local in sorted(region["wavemap_local"].astype(int).unique()):
        selected = region[region["wavemap_local"] == local]
        axis.scatter(
            selected["umap_x"], selected["umap_y"], s=3,
            color=snapshot["AREA_CLUSTER_COLORS"][(group, local)],
            alpha=0.82, linewidths=0, rasterized=True,
        )
    _clean_umap(axis)


def _plot_region_waveforms(
    axis, snapshot: dict, group: str, *, legend_columns: int = 4
) -> None:
    units = snapshot["units_df"]
    waveforms = np.asarray(snapshot["normWFs"])
    if len(units) != len(waveforms):
        raise RuntimeError("Waveform matrix and unit metadata are not row-aligned.")
    rate = verified_waveform_sampling_rate(snapshot)
    samples = np.arange(waveforms.shape[1])
    horizontal = samples if rate is None else samples / rate * 1000
    local_values = pd.to_numeric(units["wavemap_local"], errors="coerce").to_numpy()
    region = units["wavemap_group"].to_numpy() == group
    for local in sorted(set(local_values[region & np.isfinite(local_values) & (local_values > 0)])):
        selected = region & (local_values == local)
        axis.plot(
            horizontal, waveforms[selected].mean(axis=0),
            color=snapshot["AREA_CLUSTER_COLORS"][(group, int(local))],
            linewidth=1.3, label=f"{group}-{int(local)}",
        )
    axis.axhline(0, color="#BDBDBD", linewidth=0.5, zorder=0)
    axis.set_xlabel("Waveform sample" if rate is None else "Time (ms)")
    axis.set_ylabel("Normalized amplitude")
    axis.spines[["top", "right"]].set_visible(False)
    axis.legend(
        loc="upper center", bbox_to_anchor=(0.5, -0.3), frameon=False,
        ncol=legend_columns, fontsize=6, handlelength=1.2, columnspacing=0.8,
    )


def build_visual_cortex_figure(
    snapshot: dict, output_dir: Path = OUT, *, type_scale: float = 1.0
) -> tuple[Path, Path]:
    """Show unchanged VIS communities, waveforms, and operational phenotype overlays."""
    figure = plt.figure(figsize=(7.2, 5.3))
    outer = figure.add_gridspec(
        2, 1, left=0.085, right=0.985, top=0.92, bottom=0.07,
        hspace=1.15, height_ratios=[1.15, 1],
    )
    top = outer[0].subgridspec(1, 2, wspace=0.7)
    bottom = outer[1].subgridspec(1, 3, wspace=0.3)
    embedding = figure.add_subplot(top[0, 0])
    _plot_region_embedding(embedding, snapshot, "VIS")
    embedding.set_title("Visual cortex", fontweight="bold")
    waveform = figure.add_subplot(top[0, 1])
    _plot_region_waveforms(waveform, snapshot, "VIS", legend_columns=3)
    waveform.set_title("VIS community waveforms", fontweight="bold")
    _panel_letter(figure, "C", x=0.01, y=0.98)
    _panel_letter(figure, "D", x=0.525, y=0.98)
    mapping = snapshot["map_df"]
    region = mapping[(mapping["wavemap_group"] == "VIS") & mapping["umap_x"].notna()
                     & mapping["umap_y"].notna()]
    for index, (column, title, color) in enumerate((
        ("putative_fs", "Putative FS/PV-like", "#2878B5"),
        ("sst_optotagged", "Optotagged SST", "#C13C84"),
        ("sst_fs_overlap", "SST and FS overlap", "#74469A"),
    )):
        axis = figure.add_subplot(bottom[0, index])
        selected = region[region[column].fillna(False).astype(bool)]
        axis.scatter(region["umap_x"], region["umap_y"], s=2, color="#D8D8D8",
                     alpha=0.5, linewidths=0, rasterized=True)
        axis.scatter(selected["umap_x"], selected["umap_y"], s=6, color=color,
                     alpha=0.95, linewidths=0, rasterized=True)
        axis.set_title(f"{title}\n{len(selected)} / {len(region)} units", fontsize=8,
                       fontweight="bold", pad=8)
        _clean_umap(axis)
        _panel_letter(figure, chr(ord("E") + index), x=0.01 + index * 0.335, y=0.42)
    for label in figure.findobj(match=Text):
        label.set_fontsize(label.get_fontsize() * type_scale)
    return _save(figure, "wavemap-visual-cortex", output_dir)


def build_regional_embedding_figure(snapshot: dict, output_dir: Path = OUT) -> tuple[Path, Path]:
    """Show all six unchanged regional embeddings in the main figure's right column."""
    figure, axes = plt.subplots(3, 2, figsize=(5.4, 8.0))
    figure.subplots_adjust(left=0.055, right=0.99, top=0.94, bottom=0.025,
                           wspace=0.18, hspace=0.22)
    units = snapshot["units_df"]
    for axis, group in zip(axes.flat, GROUP_ORDER, strict=True):
        _plot_region_embedding(axis, snapshot, group)
        count = ((units["wavemap_group"] == group) & (units["wavemap_local"] > 0)).sum()
        axis.set_title(f"{GROUP_NAMES[group]}\n{count:,} units", fontweight="bold", fontsize=9)
    _panel_letter(figure, "H", x=0.01, y=0.99)
    return _save(figure, "wavemap-regional-embeddings", output_dir)


def build_regional_waveform_figure(snapshot: dict, output_dir: Path = OUT) -> tuple[Path, Path]:
    """Pair each region's saved embedding with its matching community mean waveforms."""
    figure = plt.figure(figsize=(13.2, 7.2))
    grid = figure.add_gridspec(
        3, 2, left=0.04, right=0.99, top=0.95, bottom=0.08,
        wspace=0.15, hspace=0.42,
    )
    for index, group in enumerate(GROUP_ORDER):
        slot = grid[index // 2, index % 2]
        panels = slot.subgridspec(1, 3, width_ratios=[1, 1.2, 0.92], wspace=0.53)
        embedding = figure.add_subplot(panels[0])
        _plot_region_embedding(embedding, snapshot, group)
        embedding.set_title(GROUP_NAMES[group], fontsize=10.5, fontweight="bold", pad=3)
        box = slot.get_position(figure)
        figure.text(box.x0 - 0.025, box.y1 + 0.008, chr(ord("A") + index),
                fontsize=14, fontweight="bold", va="top", ha="left",
                gid=f"panel-label-{chr(ord('A') + index)}")
        waveform = figure.add_subplot(panels[1])
        _plot_region_waveforms(waveform, snapshot, group)
        waveform.get_legend().remove()
        waveform.set_xlabel(waveform.get_xlabel(), fontsize=9.6)
        waveform.set_ylabel(waveform.get_ylabel(), fontsize=9.6)
        waveform.tick_params(labelsize=9.6)
        handles, labels = waveform.get_legend_handles_labels()
        legend = figure.add_subplot(panels[2])
        legend.axis("off")
        legend.legend(handles, labels, loc="center left", frameon=False, ncol=2,
                      fontsize=9.6, handlelength=1, handletextpad=0.35,
                      columnspacing=0.5, labelspacing=0.25, borderaxespad=0)
    return _save(figure, "wavemap-regional-waveforms", output_dir)


def _image_svg(path: Path, output: Path, title: str, description: str) -> Path:
    if path.suffix == ".svg":
        root = ElementTree.fromstring(path.read_text(encoding="utf-8"))
        namespace = "http://www.w3.org/2000/svg"
        root.attrib.update({"role": "img", "aria-labelledby": "title"})
        ElementTree.SubElement(root, f"{{{namespace}}}title", {"id": "title"}).text = title
        ElementTree.SubElement(root, f"{{{namespace}}}desc").text = description
        output.write_text(
            normalize_figure_svg(ElementTree.tostring(root, encoding="unicode")),
            encoding="utf-8", newline="\n",
        )
        return output
    with Image.open(path) as image:
        height = image.height * 1200 / image.width
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    root = ElementTree.Element(
        "svg", {"xmlns": "http://www.w3.org/2000/svg", "width": "1200",
                "height": f"{height:.3f}", "viewBox": f"0 0 1200 {height:.3f}",
                "role": "img", "aria-labelledby": "title"},
    )
    ElementTree.SubElement(root, "title", {"id": "title"}).text = title
    ElementTree.SubElement(root, "desc").text = description
    ElementTree.SubElement(root, "image", {
        "width": "1200", "height": f"{height:.3f}",
        "href": "data:image/png;base64," + encoded,
    })
    output.write_text(ElementTree.tostring(root, encoding="unicode") + "\n",
                      encoding="utf-8", newline="\n")
    return output


def _draw_optotagging_controls(figure, response_slot, yield_slot) -> None:
    """Draw unchanged response and session-yield controls in their supplied slots."""
    from openscope_p3_publication.figures import (
        OPTOTAGGING_HEATMAP_SOURCE_DIR,
        load_optotagging_heatmap_data,
        load_optotagging_static_summary,
        optotagging_static_heatmap_png,
    )

    payload = load_optotagging_heatmap_data()
    summary = load_optotagging_static_summary()["overall"]
    heatmap, metadata = optotagging_static_heatmap_png(
        payload, OPTOTAGGING_HEATMAP_SOURCE_DIR,
        session_id=payload["default_session_id"], condition_name="5 hz pulse train_presentations",
    )
    response = figure.add_subplot(response_slot)
    response.set_gid("panel-A-opto-response")
    with Image.open(io.BytesIO(heatmap)) as image:
        response.imshow(np.asarray(image), aspect="auto", interpolation="nearest",
                        extent=(*metadata["time_seconds"], metadata["unit_count"], 0))
    for pulse in range(5):
        response.axvspan(pulse / 5, pulse / 5 + 0.01, ymin=1.015, ymax=1.05,
                        color="#315F73", linewidth=0, clip_on=False)
    response.axvline(0, color="#263033", linewidth=0.7, linestyle="--")
    response.set(title="5 Hz optotagging control", xlabel="Time (s)", ylabel="Units")
    palette = LinearSegmentedColormap.from_list(
        "baseline-z", ["#3B4CC0", "#F7F7F7", "#B40426"]
    )
    colorbar = figure.colorbar(ScalarMappable(norm=Normalize(-2, 2), cmap=palette),
                              ax=response, fraction=0.045, pad=0.035, ticks=[-2, 0, 2])
    colorbar.set_label("Baseline z score")
    yield_axis = figure.add_subplot(yield_slot)
    yield_axis.set_gid("panel-B-opto-yield")
    counts = np.asarray(summary["counts"])
    jitter = ((np.arange(len(counts)) * 7) % 19 - 9) / 50
    yield_axis.scatter(counts, jitter, s=14, color="#8F9996", alpha=0.7, linewidths=0)
    yield_axis.axvline(summary["mean"], color="#315F73", linewidth=1.5)
    yield_axis.text(0.02, 0.95, f"n = {len(counts)} sessions\nMean {summary['mean']:.1f}",
                    transform=yield_axis.transAxes, ha="left", va="top")
    yield_axis.set(title="Overall optotagged-cell yield", xlabel="Cells / session",
                   ylim=(-0.45, 0.65))
    yield_axis.set_yticks([])
    yield_axis.spines[["top", "left", "right"]].set_visible(False)


def build_unified_cell_type_figure(
    snapshot: dict, output_dir: Path = OUT
) -> tuple[Path, Path, Path]:
    """Render regional maps, enlarged VIS waveforms, and phenotype extensions together."""
    from openscope_p3_publication.ecephys_qc_figure import _canonicalize_svg_embedded_pngs
    from openscope_p3_publication.figures import FIGURE_SANS_FONT

    type_roles = {
        "font.size": 9.6, "axes.labelsize": 9.6, "axes.titlesize": 10.5,
        "xtick.labelsize": 9.6, "ytick.labelsize": 9.6, "legend.fontsize": 9.6,
        "svg.fonttype": "none", "svg.hashsalt": "openscope-cell-type-shared-renderer",
    }
    with mpl.rc_context(type_roles):
        figure = plt.figure(figsize=(13.2, 7.8))
        grid = figure.add_gridspec(
            2, 2, left=0.06, right=0.985, top=0.94, bottom=0.075,
            width_ratios=[1.15, 2.15], height_ratios=[1.75, 1],
            wspace=0.12, hspace=0.24,
        )

        def panel_label(slot, letter: str) -> None:
            box = slot.get_position(figure)
            label = figure.text(box.x0 - 0.024, box.y1 + 0.018, letter,
                                fontsize=18, fontweight="bold", ha="left", va="bottom")
            label.set_gid(f"panel-label-{letter}")

        waveform_grid = grid[0, 0].subgridspec(2, 1, height_ratios=[1, 0.25], hspace=0.45)
        waveform = figure.add_subplot(waveform_grid[0])
        waveform.set_gid("panel-A-visual-cortex-waveforms")
        _plot_region_waveforms(waveform, snapshot, "VIS", legend_columns=3)
        waveform.get_legend().remove()
        waveform.set_title("Visual cortex\ncommunity mean waveforms", fontweight="bold")
        handles, labels = waveform.get_legend_handles_labels()
        legend_axis = figure.add_subplot(waveform_grid[1])
        legend_axis.set_gid("panel-A-waveform-legend")
        legend_axis.axis("off")
        legend_axis.legend(handles, labels, loc="center", ncol=3, frameon=False,
                           fontsize=9.6, handlelength=1.1, columnspacing=0.8)
        panel_label(grid[0, 0], "A")

        regions = grid[0, 1].subgridspec(2, 3, hspace=0.26, wspace=0.18)
        units = snapshot["units_df"]
        for index, group in enumerate(GROUP_ORDER):
            axis = figure.add_subplot(regions[index // 3, index % 3])
            axis.set_gid(f"panel-B-{group}")
            _plot_region_embedding(axis, snapshot, group)
            count = ((units["wavemap_group"] == group) & (units["wavemap_local"] > 0)).sum()
            axis.set_title(f"{GROUP_NAMES[group]}\n{count:,} units", fontsize=9.6,
                           fontweight="bold")
        panel_label(grid[0, 1], "B")

        phenotypes = grid[1, :].subgridspec(1, 3, wspace=0.18)
        mapping = snapshot["map_df"]
        visual = mapping[(mapping["wavemap_group"] == "VIS") & mapping["umap_x"].notna()
                         & mapping["umap_y"].notna()]
        for index, (column, title, color) in enumerate((
            ("putative_fs", "Putative FS/PV-like", "#2878B5"),
            ("sst_optotagged", "Optotagged SST", "#C13C84"),
            ("sst_fs_overlap", "SST and FS overlap", "#74469A"),
        )):
            axis = figure.add_subplot(phenotypes[0, index])
            letter = chr(ord("C") + index)
            axis.set_gid(f"panel-{letter}")
            selected = visual[visual[column].fillna(False).astype(bool)]
            axis.scatter(visual["umap_x"], visual["umap_y"], s=2, color="#D8D8D8",
                         alpha=0.5, linewidths=0, rasterized=True)
            axis.scatter(selected["umap_x"], selected["umap_y"], s=6, color=color,
                         alpha=0.95, linewidths=0, rasterized=True)
            axis.set_title(f"Visual cortex: {title}\n{len(selected)} / {len(visual)} units",
                           fontsize=10.5)
            _clean_umap(axis)
            panel_label(phenotypes[0, index], letter)

        figure.canvas.draw()
        buffer = io.StringIO()
        figure.savefig(buffer, format="svg", metadata={"Date": None}, facecolor="white")
        root = ElementTree.fromstring(_canonicalize_svg_embedded_pngs(buffer.getvalue()))
        namespace = "http://www.w3.org/2000/svg"
        link_namespace = "http://www.w3.org/1999/xlink"
        for image in root.iter(f"{{{namespace}}}image"):
            attribute = (
                f"{{{link_namespace}}}href" if image.get(f"{{{link_namespace}}}href") else "href"
            )
            href = image.get(attribute, "")
            if href.startswith("data:image/png;base64,"):
                encoded = _canonical_png(base64.b64decode(href.split(",", 1)[1]))
                image.set(attribute, "data:image/png;base64," + base64.b64encode(encoded).decode())
        _, _, width, height = map(float, root.get("viewBox").split())
        root.set("width", f"{width:g}")
        root.set("height", f"{height:g}")
        root.attrib.update({"role": "img", "aria-labelledby": "cell-type-title",
                            "data-region": "VIS", "data-regions": " ".join(GROUP_ORDER),
                            "data-unified-renderer": "true"})
        ElementTree.SubElement(root, f"{{{namespace}}}title", {"id": "cell-type-title"}).text = (
            "Regional waveform maps and visual-cortex waveform phenotypes"
        )
        ElementTree.SubElement(root, f"{{{namespace}}}desc").text = (
            "A shows the enlarged visual-cortex mean waveforms first, on the left. "
            "B shows all six independently fitted regional maps, including visual cortex. "
            "C-E extend the visual-cortex map "
            "with the unchanged FS, optotagged SST, and overlap labels. "
            "All panels share one plotting canvas and one typography scale."
        )
        for element in root.iter(f"{{{namespace}}}text"):
            style = element.get("style", "")
            size = re.search(r"font-size:\s*([0-9.]+)px", style)
            if size:
                element.set("font-size", size.group(1))
            element.set("font-family", FIGURE_SANS_FONT)
            element.set("style", re.sub(r"font-family:[^;]+",
                                       f"font-family: {FIGURE_SANS_FONT}", style))
        root.set("data-print-panels", json.dumps([
            ["A-E", [0, 0, width, height]],
        ], separators=(",", ":")))
        output_dir.mkdir(parents=True, exist_ok=True)
        svg = output_dir / "cell-type-characterization.svg"
        svg.write_text(normalize_figure_svg(ElementTree.tostring(root, encoding="unicode")),
                       encoding="utf-8", newline="\n")
        png, pdf = _save(figure, "cell-type-characterization", output_dir)
    return png, pdf, svg


def build_cell_type_validation_figure(
    snapshot: dict, output_dir: Path = OUT
) -> tuple[Path, Path, Path]:
    """Render optotagging controls, anatomical yield, and regional FS/SST overlays."""
    from openscope_p3_publication.ecephys_qc_figure import _canonicalize_svg_embedded_pngs
    from openscope_p3_publication.figures import FIGURE_SANS_FONT, load_optotagging_static_summary

    summary = load_optotagging_static_summary()
    with mpl.rc_context({"font.size": 9.6, "axes.labelsize": 9.6, "axes.titlesize": 10.5,
                         "xtick.labelsize": 9.6, "ytick.labelsize": 9.6,
                         "svg.fonttype": "none", "svg.hashsalt": "openscope-cell-type-validation"}):
        figure = plt.figure(figsize=(13.2, 9.4))
        grid = figure.add_gridspec(
            3, 7, left=0.11, right=0.985, top=0.94, bottom=0.04,
            width_ratios=[0.8, 1, 1, 1, 1, 1, 1], height_ratios=[1.25, 1.55, 2],
            wspace=0.35, hspace=0.4,
        )
        controls = grid[0, :].subgridspec(1, 2, wspace=0.55)
        _draw_optotagging_controls(figure, controls[0, 0], controls[0, 1])
        for index, letter in enumerate("AB"):
            box = controls[0, index].get_position(figure)
            label = figure.text(box.x0 - 0.045, box.y1 + 0.005, letter, fontsize=20,
                                fontweight="bold", ha="left", va="bottom")
            label.set_gid(f"panel-label-{letter}")
        anatomy = grid[1, :].subgridspec(1, 3, wspace=0.45)
        structures = sorted(summary["structures"],
                            key=lambda record: (-record["mean"], record["label"]))[:18]
        structure_maximum = max(max(record["counts"]) for record in structures)
        distributions = (
            (anatomy[0, 0], summary["major_parent"], "panel-C-anatomical-yield",
             "Yield by major\nparent area"),
            (anatomy[0, 1], structures[:9], "panel-D-anatomical-yield",
             "Highest-yield structures\nRanks 1-9"),
            (anatomy[0, 2], structures[9:], "panel-D-anatomical-yield-continued",
             "Highest-yield structures\nRanks 10-18"),
        )
        for slot, records, panel_id, title in distributions:
            axis = figure.add_subplot(slot)
            axis.set_gid(panel_id)
            positions = np.arange(len(records))
            axis.barh(positions, [record["mean"] for record in records],
                      color="#315F73", alpha=0.7, height=0.55)
            for index, record in enumerate(records):
                counts = np.asarray(record["counts"])
                jitter = ((np.arange(len(counts)) * 7) % 17 - 8) / 45
                axis.scatter(counts, index + jitter, s=5, color="#8F9996",
                             alpha=0.65, linewidths=0)
            axis.set_yticks(positions, [f"{record['label']}  n={record['sampled_session_count']}"
                                       for record in records])
            axis.invert_yaxis()
            axis.set(title=title, xlabel="Optotagged cells / session")
            axis.spines[["top", "right"]].set_visible(False)
            if panel_id.startswith("panel-D-"):
                axis.set_xlim(0, structure_maximum * 1.05)
        for slot, letter in ((anatomy[0, 0], "C"), (anatomy[0, 1:], "D")):
            box = slot.get_position(figure)
            label = figure.text(box.x0 - 0.045, box.y1 + 0.005, letter, fontsize=20,
                                fontweight="bold", ha="left", va="bottom")
            label.set_gid(f"panel-label-{letter}")

        overlays = grid[2, :].subgridspec(
            3, 7, width_ratios=[0.8, 1, 1, 1, 1, 1, 1], hspace=0.08, wspace=0.24,
        )
        mapping = snapshot["map_df"]
        for row, (column, title, color) in enumerate((
            ("putative_fs", "Putative\nFS/PV-like", "#2878B5"),
            ("sst_optotagged", "Optotagged\nSST", "#C13C84"),
            ("sst_fs_overlap", "SST and FS\noverlap", "#74469A"),
        )):
            label_axis = figure.add_subplot(overlays[row, 0])
            label_axis.axis("off")
            label_axis.text(1, 0.5, title, ha="right", va="center", fontsize=9.6)
            for index, group in enumerate(GROUP_ORDER):
                axis = figure.add_subplot(overlays[row, index + 1])
                axis.set_gid(f"panel-E-{column}-{group}")
                units = mapping[(mapping["wavemap_group"] == group)
                                & mapping["umap_x"].notna() & mapping["umap_y"].notna()]
                selected = units[units[column].fillna(False).astype(bool)]
                axis.scatter(units["umap_x"], units["umap_y"], s=1.5, color="#D8D8D8",
                             alpha=0.5, linewidths=0, rasterized=True)
                axis.scatter(selected["umap_x"], selected["umap_y"], s=5, color=color,
                             alpha=0.95, linewidths=0, rasterized=True)
                if row == 0:
                    axis.set_title(GROUP_NAMES[group].replace(" cortex", "\ncortex"),
                                   fontsize=9.6, fontweight="bold")
                _clean_umap(axis)
        box = overlays[0, 0].get_position(figure)
        label = figure.text(box.x0 - 0.045, box.y1 + 0.005, "E", fontsize=20,
                            fontweight="bold", ha="left", va="bottom")
        label.set_gid("panel-label-E")
        buffer = io.StringIO()
        figure.savefig(buffer, format="svg", metadata={"Date": None}, facecolor="white")
        root = ElementTree.fromstring(_canonicalize_svg_embedded_pngs(buffer.getvalue()))
        namespace, link_namespace = "http://www.w3.org/2000/svg", "http://www.w3.org/1999/xlink"
        _, _, width, height = map(float, root.get("viewBox").split())
        root.set("width", f"{width:g}")
        root.set("height", f"{height:g}")
        root.attrib.update({"role": "img", "aria-labelledby": "cell-validation-title",
                            "data-regions": " ".join(GROUP_ORDER)})
        title = ElementTree.SubElement(root, f"{{{namespace}}}title",
                           {"id": "cell-validation-title"})
        title.text = (
            "Optotagging controls, anatomical yield, and regional waveform phenotype overlays"
        )
        ElementTree.SubElement(root, f"{{{namespace}}}desc").text = (
            "A-B show the optotagging response and overall yield controls. C-D show "
            "anatomical yields using the 60-session yield criterion. "
            "E retains the separately QC-selected "
            "FS, optotagged SST, and overlap labels in all six regional embeddings. "
            "The two tagging criteria are not interchangeable."
        )
        for element in root.iter(f"{{{namespace}}}text"):
            style = element.get("style", "")
            size = re.search(r"font-size:\s*([0-9.]+)px", style)
            if size:
                element.set("font-size", size.group(1))
            element.set("font-family", FIGURE_SANS_FONT)
            element.set("style", re.sub(r"font-family:[^;]+",
                                       f"font-family: {FIGURE_SANS_FONT}", style))
        for image in root.iter(f"{{{namespace}}}image"):
            attribute = (
                f"{{{link_namespace}}}href" if image.get(f"{{{link_namespace}}}href") else "href"
            )
            href = image.get(attribute, "")
            if href.startswith("data:image/png;base64,"):
                data = _canonical_png(base64.b64decode(href.split(",", 1)[1]))
                image.set(attribute, "data:image/png;base64," + base64.b64encode(data).decode())
        first_split = 1 - (
            grid[0, 0].get_position(figure).y0 + grid[1, 0].get_position(figure).y1
        ) / 2
        second_split = 1 - (
            grid[1, 0].get_position(figure).y0 + grid[2, 0].get_position(figure).y1
        ) / 2
        root.set("data-print-panels", json.dumps([
            ["A-B", [0, 0, width, first_split * height]],
            ["C-D", [0, first_split * height, width, (second_split - first_split) * height]],
            ["E", [0, second_split * height, width, (1 - second_split) * height]],
        ], separators=(",", ":")))
        output_dir.mkdir(parents=True, exist_ok=True)
        svg = output_dir / "supplementary-cell-type-validation.svg"
        svg.write_text(normalize_figure_svg(ElementTree.tostring(root, encoding="unicode")),
                       encoding="utf-8", newline="\n")
        png, pdf = _save(figure, "supplementary-cell-type-validation", output_dir)
    return png, pdf, svg


def build_cell_type_static_figures(
    snapshot: dict, output_dir: Path = OUT
) -> tuple[Path, ...]:
    """Compose the VIS-focused main figure and three scientific supplements offline."""
    from openscope_p3_publication.figures import write_optotagging_static_source

    output_dir.mkdir(parents=True, exist_ok=True)
    visual = build_visual_cortex_figure(snapshot, output_dir, type_scale=1.6)
    embeddings = build_regional_embedding_figure(snapshot, output_dir)
    regional = build_regional_waveform_figure(snapshot, output_dir)
    overlays = build_fs_sst_figure(
        snapshot, output_dir, panel_letter="G", stem="wavemap-regional-overlays"
    )
    composition = build_context_figure(snapshot, output_dir, standalone=True)
    validation = build_cell_type_validation_figure(snapshot, output_dir)
    optotagging = write_optotagging_static_source(output_dir / "optotagging-heatmaps.svg")
    namespace = "http://www.w3.org/2000/svg"
    ElementTree.register_namespace("", namespace)
    opto_root = ElementTree.fromstring(optotagging.read_text(encoding="utf-8"))
    opto_root.set("height", "460")
    opto_root.set("viewBox", "0 0 1200 460")
    opto_root.set("overflow", "hidden")
    opto_root.attrib.pop("aria-labelledby", None)
    for element in opto_root.iter():
        if element.tag.endswith(("title", "desc")):
            element.attrib.pop("id", None)
    visual_svg = output_dir / "wavemap-visual-cortex.svg"
    _image_svg(
        visual[0], visual_svg, "VIS waveform communities and phenotype overlays",
        "C: VIS embedding. D: matched mean waveforms. E-G: saved FS, SST, and overlap.",
    )
    main = build_unified_cell_type_figure(snapshot, output_dir)
    for element in opto_root.iter(f"{{{namespace}}}text"):
        if element.text in {"C", "D"}:
            element.text = {"C": "A", "D": "B"}[element.text]
    opto_root.attrib.update({"height": "490", "viewBox": "0 470 1200 490"})
    opto_root.find(f"{{{namespace}}}title").text = (
        "Anatomical distribution of optotagged-cell yield"
    )
    opto_root.find(f"{{{namespace}}}desc").text = (
        "A: yield by Allen major parent area. B: the eighteen structures with highest mean yield."
    )
    anatomy = output_dir / "supplementary-optotagging-anatomy.svg"
    anatomy.write_text(ElementTree.tostring(opto_root, encoding="unicode") + "\n",
                       encoding="utf-8", newline="\n")
    regional_svg = _image_svg(
        output_dir / "supplementary-wavemap-regions.svg",
        output_dir / "supplementary-wavemap-regions.svg",
        "Regional waveform communities and matching embeddings",
        "A-F pair the saved MO, PFC, VIS, STR, HPC, and THAL embeddings with their mean waveforms.",
    )
    composition_svg = _image_svg(
        output_dir / "supplementary-wavemap-composition.svg",
        output_dir / "supplementary-wavemap-composition.svg",
        "Waveform-community composition and enrichment across contexts",
        "A: session-normalized class composition. B: saved log2 enrichment relative to baseline.",
    )
    return (
        *visual, *embeddings, *regional, *overlays, *composition, visual_svg,
        *main, *validation, anatomy, regional_svg, composition_svg,
    )


def main() -> None:
    """Regenerate the static WaveMAP figure from the committed snapshot."""
    for output in build_wavemap_static_figures():
        print(f"Wrote {output.name}")


if __name__ == "__main__":
    main()
