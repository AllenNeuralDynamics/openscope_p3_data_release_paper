# Author: José Antonio Velázquez Ruiz
# Date: 2026-11-05
"""LFP power changes evoked by standard-oddball events (Supplementary Figure 7).

Draws the static figure from the committed intermediate
``figure_sources/data/lfp-spectral-mi-standard.json`` after checking it against the SHA-256 in
its provenance. Reading it needs no network, so ``build-publication-figures`` reproduces the
SVG from a fresh clone. The intermediate is exported by the analysis notebook
``figure_sources/python/lfp_spectral_mi.ipynb`` (section 8), which streams the pinned NWB
files, selects trials, computes spectra, mutual information and statistics, and chooses the
example; this module only draws what it saved.

* A: example V1 trial (LFP < 100 Hz) above the spectrogram averaged over trials of the same
  event on the same channel.
* B: V1 power spectrum of the standard and each event, mean +/- SEM across mice.
* C: V1 spectra of the standard and the example event (solid) next to the same stimuli in the
  matched control block (dashed).
* D, E: power difference (dB) per area and frequency, each event minus the standard (D) or
  minus the same stimulus in the control block (E). Dots mark cells where single-trial power
  distinguishes the event from its reference across mice (MI > 0, FDR q < alpha).
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import Normalize
from scipy.ndimage import gaussian_filter

from .figure_typography import normalize_figure_svg
from .image_encoding import canonical_svg_images

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = REPO_ROOT / "figure_sources" / "data" / "lfp-spectral-mi-standard.json"
PROVENANCE_PATH = (
    REPO_ROOT / "figure_sources" / "data" / "lfp-spectral-mi-standard.provenance.json"
)
OUTPUT_PATH = (
    REPO_ROOT / "images" / "figures" / "generated" / "supplementary-lfp-spectral-mi.svg"
)

STANDARD = "standard"
COLORS = {"standard": "#1f77b4", "orientation_45": "#d62728", "orientation_90": "#ff7f0e",
          "halt": "#2ca02c", "omission": "#7f7f7f"}
LABELS = {"standard": "Standard", "orientation_45": "45° orientation",
          "orientation_90": "90° orientation", "halt": "Halt", "omission": "Omission"}
CONTRAST_TITLES = {"std": "Each event vs the standard",
                   "ctrl": "Vs the same stimulus in the matched control block"}
CONTRAST_UNITS = {"std": "event − standard", "ctrl": "stimulus − its control"}
FREQ_TICKS = (4, 8, 15, 30, 60, 100)

# Layout, inches at the final 170 mm width.
FIG_W = 6.69
TOP_MARGIN = 0.34             # inches above the top row: room for the panel letters
TICK, LABEL, TITLE, LETTER = 5.0, 5.5, 6.0, 9.0
RC_PARAMS = {
    "font.family": "DejaVu Sans",
    "font.size": LABEL,
    "axes.linewidth": 0.4,
    "axes.labelsize": LABEL,
    "xtick.labelsize": TICK,
    "ytick.labelsize": TICK,
    "xtick.major.width": 0.4,
    "ytick.major.width": 0.4,
    "xtick.major.size": 1.5,
    "ytick.major.size": 1.5,
    "xtick.major.pad": 1.0,
    "ytick.major.pad": 1.0,
    "legend.frameon": False,
    "svg.fonttype": "none",
    "svg.hashsalt": "openscope-p3-lfp-spectral-mi",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_lfp_spectral_mi(path: Path = DATA_PATH, provenance: Path = PROVENANCE_PATH) -> dict:
    """The committed intermediate, after checking it against its provenance checksum."""
    expected = json.loads(provenance.read_text(encoding="utf-8"))["output"]["sha256"]
    if sha256(path) != expected:
        raise ValueError(f"{path.name} does not match the SHA-256 in {provenance.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def as_array(values) -> np.ndarray:
    """Nested lists with None -> float array with NaN."""
    return np.array(values, dtype=float) if values is not None else np.array([])


def mean_sem(rows: list) -> tuple[np.ndarray, np.ndarray, int]:
    """Mean and SEM across mice of the non-missing rows."""
    v = np.array([r for r in rows if r is not None], dtype=float)
    if not len(v):
        raise ValueError("No mice with this spectrum.")
    sem = v.std(0, ddof=1) / np.sqrt(len(v)) if len(v) > 1 else np.zeros(v.shape[1])
    return v.mean(0), sem, len(v)


def colour_limit(values: np.ndarray, percentile: float = 99.0) -> float:
    """Symmetric colour limit: the percentile of |values|, never below 60% of the maximum."""
    finite = np.abs(values[np.isfinite(values)])
    if not finite.size:
        return 1.0
    limit = max(np.percentile(finite, percentile), 0.6 * finite.max())
    return float(limit) if limit > 0 else 1.0


def _log_axis(ax, axis: str = "y", labels: bool = True) -> None:
    getattr(ax, f"set_{axis}scale")("log")
    getattr(ax, f"set_{axis}ticks")(FREQ_TICKS)
    getattr(ax, f"set_{axis}ticklabels")([str(t) for t in FREQ_TICKS] if labels else [])
    ax.minorticks_off()


def _spines(ax) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def _letter(fig, ax, letter: str, dx: float = -0.42) -> None:
    box = ax.get_position()
    fig.text(box.x0 + dx / FIG_W, box.y1 + 0.02, letter, fontsize=LETTER, fontweight="bold",
             ha="left", va="bottom", gid=f"panel-label-{letter}")


def draw_example(fig, ax_trace, ax_spec, cax, ex: dict) -> None:
    t, x = as_array(ex["t_s"]), as_array(ex["lfp_uv"])
    color = COLORS[ex["event"]]
    for a, b, cond in ex["boxes"]:
        ax_trace.axvspan(max(a, t[0]), min(b, t[-1]), color=COLORS.get(cond, color),
                         alpha=0.15 if cond == STANDARD else 0.35, lw=0)
    ax_trace.plot(t, x, color="k", lw=0.4)
    ax_trace.set_xlim(t[0], t[-1])
    ax_trace.set_ylabel(f"LFP (µV, <{ex['lowpass_hz']} Hz)")
    ax_trace.tick_params(labelbottom=False)
    _spines(ax_trace)
    ax_trace.set_title(f"{LABELS[ex['event']]} · V1 ({ex['location']}) · mouse {ex['subject']}",
                       fontsize=TITLE, color=color, pad=2)
    st, sf = as_array(ex["spectrogram_t_s"]), as_array(ex["spectrogram_freqs_hz"])
    db = gaussian_filter(as_array(ex["spectrogram_db_vs_median"]), sigma=(1.0, 2.0))
    vmax = colour_limit(db)
    mesh = ax_spec.pcolormesh(st, sf, db, cmap="RdBu_r", vmin=-vmax, vmax=vmax,
                              shading="gouraud", rasterized=True)
    for f in ex["band_hz"]:
        ax_spec.axhline(f, color="k", lw=0.4, ls=":")
    _log_axis(ax_spec)
    ax_spec.set_ylim(sf[0], sf[-1])
    ax_spec.set_xlim(t[0], t[-1])
    ax_spec.set_ylabel("Frequency (Hz)")
    ax_spec.set_xlabel("Time from stimulus onset (s)")
    bar = fig.colorbar(mesh, cax=cax)
    bar.set_label("dB vs median", fontsize=TICK, labelpad=1)
    bar.ax.tick_params(labelsize=TICK, length=1.5, width=0.4, pad=1)
    bar.outline.set_visible(False)


def draw_spectra(ax, freqs: np.ndarray, spectra: dict, keys: list, title: str) -> int:
    n = 0
    for key, color, ls, label in keys:
        m, sem, n_k = mean_sem(spectra[key])
        n = max(n, n_k)
        ax.plot(freqs, m, color=color, ls=ls, lw=0.9, label=label)
        ax.fill_between(freqs, m - sem, m + sem, color=color, alpha=0.15, lw=0)
    _log_axis(ax, "x")
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("Power (dB)")
    ax.set_title(title, fontsize=TITLE, pad=2)
    ax.legend(fontsize=TICK, handlelength=1.6, loc="lower left", borderaxespad=0.2)
    _spines(ax)
    return n


def draw_heatmaps(fig, axes, cax, block: dict, edges: np.ndarray, freqs: np.ndarray,
                  alpha: float, contrast: str) -> None:
    dpow, q = as_array(block["dpow_db"]), as_array(block["q_fdr"])
    vmax = colour_limit(dpow)
    norm = Normalize(-vmax, vmax)
    areas = block["areas"]
    x_edges = np.arange(len(areas) + 1)
    for k, (ax, event) in enumerate(zip(axes, block["events"], strict=True)):
        ax.set_facecolor("#e6e6e6")                       # grey: area not recorded
        ax.pcolormesh(x_edges, edges, dpow[k].T, cmap="RdBu_r", norm=norm, shading="flat",
                      linewidth=0, rasterized=True)
        for xe in x_edges[1:-1]:
            ax.axvline(xe, color="white", lw=0.3)
        with np.errstate(invalid="ignore"):
            ai, fi = np.nonzero(q[k] < alpha)
        if len(ai):
            ax.scatter(ai + 0.5, freqs[fi], s=1.6, facecolor="white", edgecolor="#222222",
                       linewidth=0.25, zorder=3)
        ax.set_title(LABELS[event] if event != STANDARD else "Standard (adaptation)",
                     fontsize=LABEL, color=COLORS[event], pad=1.5)
        ax.set_xlim(0, len(areas))
        ax.set_ylim(edges[0], edges[-1])
        ax.set_xticks(x_edges[:-1] + 0.5)
        ax.set_xticklabels(areas, rotation=90, fontsize=TICK - 0.5)
        ax.tick_params(axis="x", length=0)
        _log_axis(ax, labels=k == 0)
        for spine in ax.spines.values():
            spine.set_visible(False)
    axes[0].set_ylabel("Frequency (Hz)")
    bar = fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap="RdBu_r"), cax=cax, extend="both")
    bar.set_label(f"Δ power (dB)\n{CONTRAST_UNITS[contrast]}", fontsize=TICK)
    bar.ax.tick_params(labelsize=TICK, length=1.5, width=0.4, pad=1)
    bar.outline.set_visible(False)


def build_figure(data: dict):
    freqs = as_array(data["freqs_hz"])
    edges = as_array(data["freq_edges_hz"])
    spectra = data["v1"]["spectra_db"]
    ex = data["example"]
    event = ex["event"]
    blocks = data["heatmaps"]
    rows = [k for k in ("std", "ctrl") if k in blocks]

    top_h, map_h, label_h, title_h, gap = 1.55, 1.25, 0.3, 0.2, 0.06
    height = TOP_MARGIN + top_h + 0.35 + len(rows) * (title_h + map_h + label_h + gap) - gap
    fig = plt.figure(figsize=(FIG_W, height))

    def axes(x, y_top, w, h):           # inches from the left / top edge
        return fig.add_axes([x / FIG_W, 1 - (y_top + h) / height, w / FIG_W, h / height])

    y = TOP_MARGIN
    ax_trace = axes(0.45, y, 2.4, 0.55)
    ax_spec = axes(0.45, y + 0.6, 2.4, top_h - 0.6)
    cax = axes(2.9, y + 0.6, 0.06, top_h - 0.6)
    draw_example(fig, ax_trace, ax_spec, cax, ex)
    ax_b = axes(3.82, y, 1.2, top_h)
    n_b = draw_spectra(ax_b, freqs, spectra,
                       [(c, COLORS[c], "-", LABELS[c]) for c in COLORS if c in spectra], "")
    ax_b.set_title(f"V1, n = {n_b} mice", fontsize=TITLE, pad=2)
    ax_c = axes(5.42, y, 1.2, top_h)
    n_c = draw_spectra(ax_c, freqs, spectra, [
        (STANDARD, COLORS[STANDARD], "-", "Standard"),
        (f"control_{STANDARD}", COLORS[STANDARD], "--", "same grating, control"),
        (event, COLORS[event], "-", LABELS[event]),
        (f"control_{event}", COLORS[event], "--", "same stimulus, control"),
    ], "")
    ax_c.set_title(f"V1 vs control, n = {n_c} mice", fontsize=TITLE, pad=2)
    ax_c.set_ylabel("")
    for letter, ax in (("A", ax_trace), ("B", ax_b), ("C", ax_c)):
        _letter(fig, ax, letter)

    y += top_h + 0.35
    n_cols = max(len(blocks[k]["events"]) for k in rows)
    col_w = (FIG_W - 0.45 - 0.75 - 0.06 * (n_cols - 1)) / n_cols
    for letter, key in zip("DE", rows, strict=False):
        block = blocks[key]
        fig.text(0.45 / FIG_W, 1 - (y + 0.02) / height, CONTRAST_TITLES[key], fontsize=TITLE,
                 ha="left", va="top", gid=f"panel-title-{letter}")
        y_maps = y + title_h
        row_axes = [axes(0.45 + i * (col_w + 0.06), y_maps, col_w, map_h)
                    for i in range(len(block["events"]))]
        cax = axes(0.45 + n_cols * (col_w + 0.06) + 0.05, y_maps, 0.06, map_h)
        draw_heatmaps(fig, row_axes, cax, block, edges, freqs, data["alpha"], key)
        _letter(fig, row_axes[0], letter)
        y = y_maps + map_h + label_h + gap
    return fig


def write_lfp_spectral_mi_svg(output: Path = OUTPUT_PATH, data_path: Path = DATA_PATH) -> Path:
    """Render Supplementary Figure 7 from the committed intermediate."""
    data = load_lfp_spectral_mi(data_path)
    with mpl.rc_context(RC_PARAMS):
        fig = build_figure(data)
        buffer = io.StringIO()
        fig.savefig(buffer, format="svg", dpi=300, metadata={"Date": None, "Creator": None})
        plt.close(fig)
    svg = normalize_figure_svg(canonical_svg_images(buffer.getvalue()))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(svg, encoding="utf-8", newline="\n")
    return output
