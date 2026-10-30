#!/usr/bin/env python3
"""Render publication Figure 5 with panels A through H.

The original multimodal plan was a 4-column x 3-row grid:

    columns : Neuropixels | Mesoscope | SLAP2 glutamate | SLAP2 voltage
    row 1   : A B C D  example 2D projection, single source, trace + events
    row 2   : E F G H  measure of signal and noise on traces, class definitions
    row 3   : I J K L  distribution of classes across context / neurons

  A–B  one raw trace with its noise reference and amplitude measurement,
       and the individual synapse footprint;
  C–E  three class-example amplitude histograms;
  F    the example-session DMD2 dendritic map, beside
  G    archive-wide event-amplitude feature space;
  H    three-class compartment and session composition on one percentage axis.

All panels now read the committed example snapshot and archive tables by default,
without opening an NWB or accessing the network. An external NWB remains an optional
input for deliberate refreshes. Legacy C/G/K filenames and CLI selectors are retained,
but displayed letters progress A–H. Other modalities are not included. The original analysis
is recorded at https://github.com/AllenNeuralDynamics/openscope-community-predictive-processing/pull/171.

Usage:
    uv run python -m openscope_p3_publication.slap2_glutamate_figure7_panels --output <dir>
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import matplotlib as mpl
import numpy as np
import pandas as pd

mpl.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import patheffects  # noqa: E402
from matplotlib.axes import Axes  # noqa: E402
from matplotlib.cm import ScalarMappable  # noqa: E402
from matplotlib.colors import Normalize, to_rgba  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from openscope_p3_publication.figure_typography import normalize_figure_svg  # noqa: E402
from openscope_p3_publication.image_encoding import (  # noqa: E402
    canonical_png,
    canonical_svg_images,
)
from openscope_p3_publication.slap2_glutamate_qc_events import (  # noqa: E402
    SD_LARGE,
    TAU_IGLUSNFR4F_S,
    baseline_noise,
    detect_events,
    event_amplitudes_raw,
    resolve_layout,
    sampling_interval,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "figure_sources/data/slap2-glutamate-qc"
EXAMPLE_PATH = REPO_ROOT / "figure_sources/media/slap2-glutamate-qc/example.npz"

# ───────────────────────── palette & style ─────────────────────────

CLASS_COLORS = {"Low SNR": "#E69F00", "Intermediate": "#56B4E9", "High SNR": "#009E73"}
CLASS_ORDER = ["Low SNR", "Intermediate", "High SNR"]
QUALITY_GROUPS = ("Low SNR", "Non-low SNR")
QUALITY_GROUP_COLORS = {"Low SNR": "#D55E00", "Non-low SNR": "#0072B2"}


def quality_groups(metrics: pd.DataFrame) -> pd.Series:
    """Preserve the archived low-quality boundary without reclassifying excluded sources."""
    return metrics["quality_class"].map({
        "Low SNR": "Low SNR", "Intermediate": "Non-low SNR", "High SNR": "Non-low SNR",
    })


# Neutral greys for the three event-amplitude bins, so the bins never compete
# with the class ramp.
BIN_GREYS = {"lt2": "#c6c5c0", "gt4": "#2e2d2b"}
BIN_LABELS = {"lt2": "< 2 SD", "gt4": "≥ 4 SD"}

INK, INK_2, MUTED = "#0b0b0b", "#52514e", "#8a8985"
GRID, NOISE_GREY = "#e3e2de", "#b6b5b0"
ORANGE = "#eb6834"      # single accent: the example synapse, nothing else

COMPARTMENT = {1: "DMD1 · proximal dendrites", 2: "DMD2 · apical dendrites"}
COMP_SHORT = {1: "DMD1 · proximal", 2: "DMD2 · apical"}
COHORT = {False: "Glutamate only", True: "Glutamate + calcium"}

# Stimulus contexts of the 12 glutamate-only sessions (standard oddball
# paradigm; labels inferred from orientation statistics) …
CONTEXT_ORDER = ["Control (random ori)", "Oddball standard", "Oddball deviant",
                 "RF mapping", "Blank", "Inter-stimulus"]
CONTEXT_LABELS = {"Control (random ori)": "control\n(random)",
                  "Oddball standard": "oddball\nstandard",
                  "Oddball deviant": "oddball\ndeviant",
                  "RF mapping": "RF\nmapping", "Blank": "blank",
                  "Inter-stimulus": "inter-\nstimulus"}
# … and the named stimulus blocks of the 8 glutamate + calcium sessions,
# grouped by role so the four oddball paradigms sit next to their controls.
CONTEXT_GROUPS = [
    ("standard oddball", "standard\noddball"),
    ("motor oddball", "motor\noddball"),
    ("sequential oddball", "sequential\noddball"),
    ("jitter oddball", "jitter\noddball"),
    ("standard control", "standard\ncontrol"),
    ("sequential control block", "sequential\ncontrol"),
    ("jitter control", "jitter\ncontrol"),
    ("rf mapping", "RF\nmapping"),
    ("movie", "movie"),
    ("open loop prerecorded", "open-loop\nprerec."),
    ("Inter-stimulus", "inter-\nstimulus"),
]


def set_style() -> None:
    mpl.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica"],
        "font.size": 7, "axes.labelsize": 7, "axes.titlesize": 7.5,
        "xtick.labelsize": 6.5, "ytick.labelsize": 6.5, "legend.fontsize": 6.5,
        "axes.edgecolor": INK_2, "axes.labelcolor": INK, "axes.linewidth": 0.6,
        "xtick.color": INK_2, "ytick.color": INK_2, "text.color": INK,
        "axes.spines.top": False, "axes.spines.right": False,
        "xtick.major.width": 0.6, "ytick.major.width": 0.6,
        "xtick.major.size": 2.5, "ytick.major.size": 2.5,
        "grid.color": GRID, "grid.linewidth": 0.5,
        "legend.frameon": False,
        "savefig.bbox": "tight", "savefig.pad_inches": 0.02,
        "svg.hashsalt": "openscope-p3-slap2-glutamate-qc",
    })


def panel_tag(fig, letter: str, *, axis: Axes | None = None, pad: float = 0.055) -> None:
    x, y = 0.005, 0.995
    if axis is not None:
        bounds = axis.get_position()
        x, y = max(0.005, bounds.x0 - 0.06), bounds.y1 + pad
    fig.text(x, y, letter, fontsize=11, fontweight="bold",
             va="bottom" if axis is not None else "top",
             ha="left", color=INK, gid=f"panel-label-{letter}")


def save_panel(fig, out: Path, name: str, *, preview_png: bool = True) -> None:
    out.mkdir(parents=True, exist_ok=True)
    svg = io.StringIO()
    with mpl.rc_context({"svg.fonttype": "none"}):
        fig.savefig(svg, format="svg", dpi=300, metadata={"Date": None})
    svg_text = canonical_svg_images(svg.getvalue())
    svg_text = normalize_figure_svg(svg_text)
    (out / f"{name}.svg").write_text(svg_text, encoding="utf-8", newline="\n")
    if preview_png:
        png = io.BytesIO()
        fig.savefig(png, format="png", dpi=300, metadata={"Software": "OpenScope P3 publication"})
        (out / f"{name}.png").write_bytes(canonical_png(png.getvalue()))
    plt.close(fig)


def hide_frame(ax) -> None:
    ax.set_xticks([])
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)


def class_legend(ax, n: dict | None = None, **kw):
    handles = [Patch(facecolor=CLASS_COLORS[c],
                     label=f"{c} (n={n[c]:,})" if n is not None else c)
               for c in CLASS_ORDER]
    return ax.legend(handles=handles, labelcolor=INK_2, **kw)


# ───────────────────────── session loading ─────────────────────────

def session_id(nwb_path: Path) -> str:
    return nwb_path.name.replace("_image+ophys.nwb", "").replace(".nwb", "")


def session_date(session: str) -> pd.Timestamp:
    """Acquisition date from either session-id convention in DANDI 001424."""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", session)
    if m:
        return pd.Timestamp(f"{m[1]}-{m[2]}-{m[3]}")
    m = re.search(r"(\d{4})(\d{2})(\d{2})T", session)
    return pd.Timestamp(f"{m[1]}-{m[2]}-{m[3]}") if m else pd.NaT


def mask_outlines(masks: np.ndarray) -> list[np.ndarray]:
    """Binary footprints with NaNs cleared, one per source."""
    return [np.nan_to_num(masks[i], nan=0.0) > 0 for i in range(masks.shape[0])]


def _plane_images(layout, dmd: int):
    """Activity image, mean image and per-source footprints for one plane."""
    activity = layout["image"](dmd, "activity")
    mean_img = layout["image"](dmd, "mean")
    seg = layout["segmentation"](dmd)
    if activity is None or seg is None:
        return None
    if mean_img is None:
        mean_img = activity
    # Older sessions store weighted `pixel_mask`; newer ones store `image_mask`.
    if "image_mask" in seg.colnames:
        outlines = mask_outlines(np.asarray(seg["image_mask"][:]))
    else:
        h, w = activity.shape[:2]
        outlines = []
        for pix in seg["pixel_mask"][:]:
            m = np.zeros((h, w), dtype=bool)
            for entry in pix:
                x, y = int(entry[0]), int(entry[1])
                if 0 <= y < h and 0 <= x < w:
                    m[y, x] = True
            outlines.append(m)
    return activity, mean_img, outlines


def load_session(nwb_path: Path) -> dict:
    """Traces and plane images of one session.

    Returns {"traces": {dmd: {"data", "ts", "dt"}}, "planes": {dmd: (activity,
    mean image, outlines)}}. The NWB layout is resolved, not assumed: DANDI
    001424 ships three of them.
    """
    from pynwb import NWBHDF5IO

    io = NWBHDF5IO(str(nwb_path), "r", load_namespaces=True)
    try:
        nwb = io.read()
        layout = resolve_layout(nwb)
        sess = {"traces": {}, "planes": {}}
        for dmd in layout["dmds"]:
            s = layout["dff_series"][dmd]
            ts = np.asarray(s.timestamps)
            sess["traces"][dmd] = {"data": np.asarray(s.data, dtype=np.float32),
                                   "ts": ts, "dt": sampling_interval(ts)}
            planes = _plane_images(layout, dmd)
            if planes is not None:
                sess["planes"][dmd] = planes
    finally:
        io.close()
    return sess


def load_session_cached(nwb_path: Path, cache: Path | None) -> dict:
    """`load_session`, with the arrays stashed as .npz under `cache`.

    The NWBs live on slow shared storage, and re-reading 2–4 GB for every
    figure iteration costs minutes; the arrays the panels need are a few
    hundred MB and load in a second from local disk.
    """
    f = None if cache is None else cache / (session_id(nwb_path) + ".npz")
    if f is not None and f.exists():
        z = np.load(f, allow_pickle=False)
        sess = {"traces": {}, "planes": {}}
        for d in [int(x) for x in z["dmds"]]:
            sess["traces"][d] = {"data": z[f"data{d}"], "ts": z[f"ts{d}"],
                                 "dt": float(z[f"dt{d}"])}
            if f"activity{d}" in z:
                sess["planes"][d] = (z[f"activity{d}"], z[f"mean{d}"],
                                     list(z[f"outlines{d}"]))
        print(f"loaded session arrays from {f}")
        return sess

    sess = load_session(nwb_path)
    if f is not None:
        f.parent.mkdir(parents=True, exist_ok=True)
        arrays = {"dmds": np.array(sorted(sess["traces"]))}
        for d, tr in sess["traces"].items():
            arrays[f"data{d}"], arrays[f"ts{d}"], arrays[f"dt{d}"] = tr["data"], tr["ts"], tr["dt"]
        for d, (act, mean_img, outs) in sess["planes"].items():
            arrays[f"activity{d}"], arrays[f"mean{d}"] = act, mean_img
            arrays[f"outlines{d}"] = np.stack(outs)
        np.savez(f, **arrays)
        print(f"cached session arrays under {cache}")
    return sess


def load_example_snapshot(path: Path) -> dict:
    """Load the checksummed, numeric-only subset used by the publication panels."""
    provenance = json.loads(path.with_suffix(".provenance.json").read_text(encoding="utf-8"))
    if hashlib.sha256(path.read_bytes()).hexdigest() != provenance["output_sha256"]:
        raise ValueError("SLAP2 example snapshot checksum does not match its provenance.")
    session = {"traces": {}, "planes": {}}
    with np.load(path, allow_pickle=False) as arrays:
        if int(arrays["schema_version"]) != 1:
            raise ValueError("Unsupported SLAP2 example snapshot schema.")
        session["session_id"] = str(arrays["session_id"])
        for stored_dmd in arrays["trace_dmds"]:
            dmd = int(stored_dmd)
            trace_data = {
                "data": arrays[f"data{dmd}"],
                "ts": arrays[f"ts{dmd}"],
                "dt": float(arrays[f"dt{dmd}"]),
                "roi_ids": arrays[f"roi_ids{dmd}"],
            }
            if trace_data["data"].shape != (
                len(trace_data["ts"]), len(trace_data["roi_ids"])
            ):
                raise ValueError(f"DMD{dmd} trace dimensions do not match their identifiers.")
            session["traces"][dmd] = trace_data
        for stored_dmd in arrays["plane_dmds"]:
            dmd = int(stored_dmd)
            activity = arrays[f"activity{dmd}"]
            mean_image = arrays[f"mean{dmd}"]
            outlines = arrays[f"outlines{dmd}"]
            if activity.shape != mean_image.shape or outlines.shape[1:] != activity.shape:
                raise ValueError(f"DMD{dmd} images and source masks have inconsistent shapes.")
            session["planes"][dmd] = (activity, mean_image, list(outlines))
    return session


# ───────────────────────── shared helpers ─────────────────────────

def usable(m: pd.DataFrame) -> pd.DataFrame:
    """Synapses that carry a class (measurable noise floor, ≥ 1 event)."""
    return m[m.quality_class.isin(CLASS_ORDER)]


def example_synapse(metrics: pd.DataFrame, dmd: int = 1) -> int:
    """The synapse with the largest > 4 SD event fraction on `dmd`."""
    md = usable(metrics[metrics.dmd == dmd])
    return int(md.sort_values("frac_events_gt4sd", ascending=False).iloc[0]["roi"])


def class_examples(metrics: pd.DataFrame) -> dict[str, tuple[int, int]]:
    """One representative (dmd, roi) per class: nearest to the class median."""
    m = usable(metrics).dropna(subset=["frac_events_lt2sd", "frac_events_gt4sd"])
    feats = m[["frac_events_lt2sd", "frac_events_gt4sd"]].to_numpy()
    sd = feats.std(0)
    sd[sd == 0] = 1
    out = {}
    for cls in CLASS_ORDER:
        sel = (m.quality_class == cls).to_numpy()
        if not sel.any():
            continue
        centre = np.median(feats[sel], axis=0)
        d = (((feats - centre) / sd) ** 2).sum(1)
        d[~sel] = np.inf
        row = m.iloc[int(np.argmin(d))]
        out[cls] = (int(row.dmd), int(row.roi))
    return out


def raw_event_peak_indices(
    trace: np.ndarray, detected_indices: np.ndarray, dt: float,
) -> np.ndarray:
    """Locate raw maxima in the event-amplitude measurement's 40 ms search window."""
    post = max(1, int(round(2 * TAU_IGLUSNFR4F_S / dt)))
    peaks = []
    for index in detected_indices:
        segment = trace[index:index + post + 1]
        peaks.append(index + int(np.nanargmax(segment)) if np.isfinite(segment).any() else index)
    return np.asarray(peaks, dtype=int)


def event_table(trace: np.ndarray, ts: np.ndarray, dt: float) -> dict:
    """Detection + raw-σ amplitudes for one trace, as the QC pipeline does it."""
    res = detect_events(trace, dt, stable_filter=True)
    finite = trace[np.isfinite(trace)]
    raw_sd, raw_med = baseline_noise(finite)
    amp_raw = event_amplitudes_raw(trace, res["idx"], dt, raw_sd)
    return {
        **res,
        "peak_idx": raw_event_peak_indices(trace, res["idx"], dt),
        "amp_raw": amp_raw,
        "raw_sd": raw_sd,
        "raw_med": raw_med,
        "t": ts[res["idx"]],
    }


def source_trace(trace_data: dict, roi: int) -> np.ndarray:
    """Read a source from a full session or an explicitly indexed compact subset."""
    if "roi_ids" not in trace_data:
        return trace_data["data"][:, roi]
    matches = np.flatnonzero(np.asarray(trace_data["roi_ids"]) == roi)
    if len(matches) != 1:
        raise KeyError(f"Expected one trace for ROI {roi}, found {len(matches)}.")
    return trace_data["data"][:, int(matches[0])]


def amplitude_bin(amp: np.ndarray) -> np.ndarray:
    return np.where(amp < 2.0, "lt2", np.where(amp < SD_LARGE, "mid", "gt4"))


def pick_window(ev: dict, ts: np.ndarray, width: float, t_from: float = 900.0,
                step: float = 1.0, n_min: int = 6) -> float:
    """Start time of a window that holds ≥ n_min events spanning all three bins.

    Scans forward from `t_from` so the example is a typical stretch mid-session
    rather than a cherry-picked burst.
    """
    t, amp = ev["t"], ev["amp_raw"]
    ok = np.isfinite(amp)
    t, b = t[ok], amplitude_bin(amp[ok])
    t0 = float(np.nanmin(ts)) + t_from
    for start in np.arange(t0, float(np.nanmax(ts)) - width, step):
        m = (t >= start) & (t < start + width)
        if m.sum() >= n_min and len(set(b[m])) == 3:
            return float(start)
    return t0


def stacked_composition(ax, table: pd.DataFrame, labels, fontsize=6, min_label=7.0,
                        thickness=0.55) -> None:
    """Horizontal 100 % stacked class composition, one bar per row of `table` (%)."""
    base = np.zeros(len(table))
    pos = np.arange(len(table))
    for cls in CLASS_ORDER:
        vals = table[cls].values
        ax.barh(pos, vals, left=base, height=thickness, color=CLASS_COLORS[cls],
                edgecolor="white", linewidth=1.0, label=cls)
        for p, (v, b) in enumerate(zip(vals, base, strict=True)):
            if v > min_label:
                ax.text(b + v / 2, p, f"{v:.0f}", ha="center", va="center", fontsize=fontsize,
                        color="white" if cls != "Low SNR" else INK)
        base += vals
    ax.set_yticks(pos)
    ax.set_yticklabels(labels)
    ax.set_xlim(0, 100)
    ax.set_xlabel("% of synapses")
    ax.grid(axis="x", alpha=0.7)
    ax.set_axisbelow(True)


# ─────────────────── optional continuous colour ───────────────────

# `--color-by` swaps the three-class palette of panels C and G for a
# continuous scale on one per-synapse number. The default stays the classes:
# panel K stacks and groups by them, and the 3-class scheme is what keeps this
# column comparable to the mesoscope column (#156). `robust_snr` is offered
# because it is the obvious "SNR", but it is a poor gradient — its class
# medians (2.32 / 2.65 / 2.70 archive-wide) overlap almost completely, and
# every synapse above 10 is in the glutamate + calcium cohort, whose
# non-negative dF/F shrinks sigma. `median_event_raw_sd` is the default: same
# unit as the rest of panel G, and spearman 0.99 with the > 4 SD fraction the
# classes are ordered by.
GRADIENT_CMAP = plt.get_cmap("viridis")
GRADIENT_HALO = "#111111"
GRADIENT_LABELS = {
    "median_event_raw_sd": "median event amplitude (SD of noise)",
    "robust_snr": "95/50 SNR  (P95 − P50) / σ",
    "frac_events_gt4sd": "% of the synapse's events > 4 SD",
}


def gradient_values(m: pd.DataFrame, col: str) -> pd.Series:
    """Per-synapse values in the unit the colourbar is labelled with."""
    v = pd.to_numeric(m[col], errors="coerce")
    return 100 * v if col.startswith("frac_") else v


def gradient_norm(m: pd.DataFrame, col: str) -> Normalize:
    """2–98th percentile scale; the colourbar is drawn with both extends."""
    v = gradient_values(m, col).to_numpy(dtype=float)
    return Normalize(*np.percentile(v[np.isfinite(v)], [2, 98]))


def gradient_colorbar(fig, rect, norm, label: str, orientation: str = "horizontal"):
    """Colourbar at `rect` (figure coordinates), labelled in real units."""
    cax = fig.add_axes(rect)
    cb = fig.colorbar(ScalarMappable(norm=norm, cmap=GRADIENT_CMAP), cax=cax,
                      orientation=orientation, extend="both")
    cb.outline.set_visible(False)
    cb.ax.tick_params(labelsize=6, color=INK_2, labelcolor=INK_2, width=0.5, length=2.0)
    if orientation == "horizontal":
        cax.set_title(label, fontsize=6.3, color=INK, loc="right", pad=3)
    else:
        cb.set_label(label, fontsize=6.3, color=INK)
    return cb


def gradient_suffix(color_by: str | None) -> str:
    """Gradient variants are written next to the default panels, not over them."""
    return "" if color_by is None else "_gradient"


# ───────────────────────── panel C ─────────────────────────

def coverage_bbox(outlines: list[np.ndarray], pad: int = 12) -> tuple[int, int, int, int]:
    """Bounding box of imaged pixels. SLAP2 samples only selected pixels of
    the field, so the stored frame is mostly empty; panels crop to the data."""
    any_mask = np.zeros_like(outlines[0], dtype=bool)
    for ol in outlines:
        any_mask |= ol
    ys, xs = np.where(any_mask)
    h, w = any_mask.shape
    return (max(0, ys.min() - pad), min(h, ys.max() + pad + 1),
            max(0, xs.min() - pad), min(w, xs.max() + pad + 1))


def imaged_segments(activity: np.ndarray, outlines: list[np.ndarray]) -> list[dict]:
    """Connected islands of imaged pixels, each with its synapse count.

    SLAP2 images only user-selected regions, so a plane is a set of disjoint
    islands. Islands without a synapse (small targeting stubs) are dropped.
    """
    from scipy import ndimage

    imaged = np.isfinite(activity) & (activity != 0)
    labels, n = ndimage.label(imaged)
    segs = []
    for i in range(1, n + 1):
        region = labels == i
        n_syn = sum(bool(ol[region].any()) for ol in outlines)
        if n_syn < 1:
            continue
        ys, xs = np.where(region)
        segs.append({"n_synapses": n_syn, "bbox": (ys.min(), ys.max(), xs.min(), xs.max())})
    segs.sort(key=lambda s: s["bbox"][2])  # left to right
    return segs


def render_panel_c(sess: dict, metrics: pd.DataFrame, out: Path, dmd: int = 1,
                   color_by: str | None = None, *, preview_png: bool = True) -> int:
    """Show one raw event measurement and its individual spatial footprint."""
    if dmd not in sess["planes"]:
        raise RuntimeError(f"DMD{dmd} is missing its activity image or segmentation.")
    _, mean_image, outlines = sess["planes"][dmd]
    ex = example_synapse(metrics, dmd)
    norm = None if color_by is None else gradient_norm(usable(metrics), color_by)
    tr = sess["traces"][dmd]
    trace, ts = source_trace(tr, ex), tr["ts"]
    ev = event_table(trace, ts, tr["dt"])
    t_start = float(np.nanmin(ts)) + 900.0
    win = (ts >= t_start) & (ts < t_start + 20.0)
    tt, yy = ts[win] - t_start, trace[win]
    in_win = (ev["t"] >= t_start) & (ev["t"] < t_start + 20.0)
    peak_times = ts[ev["peak_idx"]] - t_start
    candidates = np.flatnonzero(
        in_win & np.isfinite(ev["amp_raw"]) & (peak_times >= 0) & (peak_times < 20)
    )
    if not len(candidates):
        raise ValueError(f"No measurable event in the displayed DMD{dmd} source {ex} trace.")
    event_index = int(candidates[np.argmax(ev["amp_raw"][candidates])])
    peak = float(trace[ev["peak_idx"][event_index]])
    baseline = peak - ev["amp_raw"][event_index] * ev["raw_sd"]
    peak_time = float(peak_times[event_index])
    band_half_width = 3 * ev["raw_sd"]
    band_low = ev["raw_med"] - band_half_width
    band_high = ev["raw_med"] + band_half_width

    fig = plt.figure(figsize=(7.2, 1.95 if color_by is None else 2.25))
    grid = fig.add_gridspec(1, 2, width_ratios=[4.2, 1], wspace=0.25,
                           left=0.085, right=0.985, top=0.78, bottom=0.27)
    ax = fig.add_subplot(grid[0])
    ax.set_gid(f"example-trace-DMD{dmd}-{ex}")
    band = ax.axhspan(band_low, band_high, color=NOISE_GREY, alpha=0.25, lw=0)
    band.set_gid("raw-noise-reference-band")
    ax.plot(tt, yy, lw=0.5, color=INK_2)
    lo, hi = min(np.nanmin(yy), band_low), max(np.nanmax(yy), band_high)
    span = hi - lo
    marker_y = hi + 0.12 * span
    event_times = ev["t"][in_win] - t_start
    ax.scatter(event_times, np.full(in_win.sum(), marker_y),
               marker="v", s=8, color=ORANGE, linewidths=0)
    label_time = float(event_times[np.argmin(np.abs(event_times - 10))])
    ax.annotate("detected event", (label_time, marker_y), xytext=(0, 7),
                textcoords="offset points", ha="center", va="bottom", color=ORANGE,
                fontsize=6.5, gid="detected-event-label")
    arrow_direction = -1 if peak_time > 18 else 1
    arrow_x = peak_time + arrow_direction * 0.3
    arrow = ax.annotate("", (arrow_x, peak), xytext=(arrow_x, baseline),
                        arrowprops={"arrowstyle": "<->", "color": INK, "linewidth": 0.7})
    arrow.set_gid("example-event-amplitude")
    arrow.arrow_patch.set_gid("example-event-amplitude")
    for level in (baseline, peak):
        ax.plot([peak_time, arrow_x + arrow_direction * 0.07], [level, level], color=INK, lw=0.5)
    ax.annotate("Event\namplitude", (arrow_x, peak),
                xytext=(5 * arrow_direction, 2), textcoords="offset points",
                fontsize=6, va="top", ha="left" if arrow_direction == 1 else "right",
                gid="event-amplitude-label")
    ax.annotate("±3 raw-noise SD", (0.925, band_high),
                xycoords=ax.get_yaxis_transform(), xytext=(0, 7.5),
                textcoords="offset points", ha="right", va="bottom",
                fontsize=6, color=INK_2, gid="raw-noise-reference-label")
    ax.set(xlim=(0, 20), ylim=(lo - 0.08 * span, hi + 0.5 * span))
    ax.set_xlabel("time (s, from 900 s into the session)")
    ax.set_ylabel("ΔF/F")
    panel_tag(fig, "A", axis=ax)

    ys, xs = np.argwhere(outlines[ex]).T
    y0, y1 = max(0, ys.min() - 14), min(mean_image.shape[0], ys.max() + 15)
    x0, x1 = max(0, xs.min() - 14), min(mean_image.shape[1], xs.max() + 15)
    crop = mean_image[y0:y1, x0:x1]
    footprint = fig.add_subplot(grid[1])
    panel_tag(fig, "B", axis=footprint)
    slot = grid[1].get_position(fig)
    trace_right = ax.get_position().x1
    footprint.set_position([trace_right, slot.y0, grid.right - trace_right, slot.height])
    footprint.set_gid(f"single-synapse-footprint-DMD{dmd}-{ex}")
    footprint.imshow(crop, cmap="gray", vmin=np.nanpercentile(crop, 2),
                     vmax=np.nanpercentile(crop, 99.5), interpolation="nearest")
    footprint.set_aspect("equal", adjustable="datalim")
    colour = ORANGE
    if color_by is not None:
        value = gradient_values(metrics.loc[metrics.dmd.eq(dmd) & metrics.roi.eq(ex)],
                                color_by).iloc[0]
        colour = GRADIENT_CMAP(norm(value))
        gradient_colorbar(fig, [0.76, 0.88, 0.2, 0.035], norm, GRADIENT_LABELS[color_by])
    footprint.contour(outlines[ex][y0:y1, x0:x1], levels=[0.5], colors=[colour], linewidths=0.9)
    hide_frame(footprint)

    save_panel(fig, out, "figure7_panelC_slap2_glutamate" + gradient_suffix(color_by),
               preview_png=preview_png)
    print(f"panel C -> example synapse {ex} (DMD{dmd}), {ev['idx'].size} events, "
          f"class {metrics[(metrics.dmd == dmd) & (metrics.roi == ex)].quality_class.iloc[0]}")
    return ex


# ───────────────────────── panel G ─────────────────────────

def _draw_class_examples(axes, sess, metrics: pd.DataFrame, examples: dict,
                         color_by: str | None = None, norm=None) -> None:
    """G-i: the event-amplitude histogram of one synapse per class."""
    lo_edge, hi_edge = -2.0, 14.0
    bins = np.arange(lo_edge, hi_edge + 0.01, 0.25)
    for k, cls in enumerate(reversed(CLASS_ORDER)):
        ax = axes[k]
        if cls not in examples:
            ax.set_axis_off()
            continue
        d, r = examples[cls]
        tr = sess["traces"][d]
        ev = event_table(source_trace(tr, r), tr["ts"], tr["dt"])
        amps = ev["amp_raw"][np.isfinite(ev["amp_raw"])]
        if color_by is None:
            colour, title = CLASS_COLORS[cls], f"{cls} — synapse {r}, DMD{d}"
        else:
            v = gradient_values(metrics[(metrics.dmd == d) & (metrics.roi == r)],
                                color_by).iloc[0]
            colour, title = GRADIENT_CMAP(norm(v)), f"synapse {r}, DMD{d} — {v:.1f}"
        ax.axvspan(lo_edge, 2, color=BIN_GREYS["lt2"], alpha=0.45, lw=0)
        ax.axvspan(SD_LARGE, hi_edge, color=BIN_GREYS["gt4"], alpha=0.18, lw=0)
        counts, _, _ = ax.hist(np.clip(amps, lo_edge, hi_edge - 1e-6), bins=bins,
                               color=colour, edgecolor="white", linewidth=0.3)
        ax.set_ylim(0, 1.55 * counts.max())
        f = [(amps < 2).mean(), (amps >= SD_LARGE).mean()]
        for x, frac, b in zip((0.0, 9.0), f, ("lt2", "gt4"), strict=True):
            txt = f"{BIN_LABELS[b]}\n{100 * frac:.0f} %" if k == 0 else f"{100 * frac:.0f} %"
            ax.text(x, 0.95, txt, transform=ax.get_xaxis_transform(), ha="center",
                    va="top", fontsize=6, color=INK, linespacing=1.3)
        ax.set_xlim(lo_edge, hi_edge)
        ax.set_yticks([])
        ax.spines["left"].set_visible(False)
        ax.set_title(title, loc="left", color=INK, fontsize=6.2, pad=3)
        ax.set_xticks([0, 2, 4, 8, 12])
        if k == 2:
            ax.set_xlabel("event amplitude (SD of raw ΔF/F noise)")
        else:
            ax.tick_params(labelbottom=False)


def _draw_feature_space(ax, m: pd.DataFrame, title: str, rings: pd.DataFrame | None,
                        xlim, ylim, legend_loc="upper right",
                        color_by: str | None = None, norm=None) -> None:
    """G-iii: every classified synapse of the archive in the (<2 SD %, >4 SD %) plane."""
    if color_by is None:
        for cls in CLASS_ORDER:
            sel = m[m.quality_class == cls]
            ax.scatter(100 * sel.frac_events_lt2sd, 100 * sel.frac_events_gt4sd, s=4,
                       alpha=0.6, color=CLASS_COLORS[cls], linewidths=0, rasterized=True)
    else:
        ax.scatter(100 * m.frac_events_lt2sd, 100 * m.frac_events_gt4sd, s=4, alpha=0.75,
                   c=gradient_values(m, color_by), cmap=GRADIENT_CMAP, norm=norm,
                   linewidths=0, rasterized=True)
    if rings is not None:
        for row in rings.itertuples():
            mark_example(ax, 100 * row.frac_events_lt2sd, 100 * row.frac_events_gt4sd,
                         int(row.dmd), int(row.roi),
                         below=row.quality_class == "Low SNR" or row.dmd == 1)
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_xlabel("% of the synapse's events < 2 SD")
    ax.set_title(title, loc="left", color=INK, fontsize=6.8)
    if color_by is None:
        class_legend(ax, loc=legend_loc, handlelength=0.9, handleheight=0.9,
                     handletextpad=0.4, borderpad=0.25, labelspacing=0.3, fontsize=6)
    ax.grid(False)
    ax.set_axisbelow(True)


def mark_example(
    ax: Axes, x: float, y: float, dmd: int, roi: int, *, below: bool = False,
) -> None:
    """Use identical, background-independent rings and source IDs on maps and scatter."""
    identifier = f"{ax.get_gid()}-source-DMD{dmd}-{roi}"
    ax.plot(x, y, "o", ms=8, mfc="none", mec="white", mew=1, zorder=6, gid=identifier,
            path_effects=[patheffects.Stroke(linewidth=2.2, foreground=INK),
                          patheffects.Normal()])
    ax.annotate(str(roi), (x, y), xytext=(7, -8 if below else 8),
                textcoords="offset points", color="white", fontsize=6, zorder=7,
                gid=f"{identifier}-label",
                bbox={"facecolor": INK, "alpha": 0.8, "edgecolor": "none", "pad": 1})


def draw_class_footprints(
    ax, sess: dict, metrics: pd.DataFrame, dmd: int, examples: dict,
    *, color_by: str | None = None, norm: Normalize | None = None,
) -> None:
    """Overlay classified masks on a native example-session mean image."""
    _, mean_image, outlines = sess["planes"][dmd]
    y0, y1, x0, x1 = coverage_bbox(outlines)
    crop = mean_image[y0:y1, x0:x1]
    ax.set_gid(f"class-footprints-DMD{dmd}")
    ax.imshow(crop, cmap="gray", vmin=np.nanpercentile(crop, 2),
              vmax=np.nanpercentile(crop, 99.5), interpolation="nearest")
    plane = usable(metrics.loc[metrics.dmd == dmd])
    for cls in CLASS_ORDER:
        selected = plane.loc[plane.quality_class == cls]
        masks = [outlines[int(roi)][y0:y1, x0:x1] for roi in selected.roi]
        if not masks:
            continue
        mask = np.logical_or.reduce(masks)
        rgba = np.zeros((*mask.shape, 4))
        if color_by is None:
            rgba[mask] = to_rgba(CLASS_COLORS[cls], alpha=0.55)
        else:
            scale = gradient_norm(plane, color_by) if norm is None else norm
            for roi_mask, value in zip(masks, gradient_values(selected, color_by), strict=True):
                rgba[roi_mask] = (*GRADIENT_CMAP(scale(value))[:3], 0.55)
        image = ax.imshow(rgba, interpolation="nearest")
        image.set_gid(f"filled-rois-DMD{dmd}-{cls.lower().replace(' ', '-')}")
        ax.contour(mask, levels=[0.5],
                   colors=[CLASS_COLORS[cls] if color_by is None else "white"], linewidths=0.45)
    for role, (plane_id, roi) in examples.items():
        if plane_id != dmd:
            continue
        y, x = np.argwhere(outlines[roi]).mean(axis=0)
        mark_example(ax, float(x - x0), float(y - y0), dmd, roi,
                     below=role in {"Low SNR", "Trace example"})
    ax.set_title(COMPARTMENT[dmd], loc="left", fontsize=7)
    ax.set_anchor("N")
    hide_frame(ax)


def render_panel_g(sess: dict, m_ex: pd.DataFrame, m_all: pd.DataFrame,
                   summary: pd.DataFrame, out: Path, dmd: int = 2,
                   color_by: str | None = None, *, preview_png: bool = True) -> None:
    """Show class histograms above one DMD map beside the full-archive scatter."""
    if dmd not in sess["planes"]:
        raise RuntimeError(f"DMD{dmd} is missing its activity image or segmentation.")
    examples = class_examples(m_ex)
    norm = None if color_by is None else gradient_norm(usable(m_all), color_by)

    fig = plt.figure(figsize=(7.2, 3.65))
    outer = fig.add_gridspec(2, 1, height_ratios=[0.9, 1.65],
                             hspace=0.65, left=0.095,
                             right=0.965 if color_by is None else 0.915,
                             top=0.90, bottom=0.15)

    hist_gs = outer[0].subgridspec(1, 3, wspace=0.22)
    hist_axes = [fig.add_subplot(hist_gs[i]) for i in range(3)]
    _draw_class_examples(hist_axes, sess, m_ex, examples, color_by, norm)
    for index, ax in enumerate(hist_axes):
        ax.set_gid(f"class-amplitudes-{CLASS_ORDER[2 - index].lower().replace(' ', '-')}")
        ax.tick_params(labelbottom=True)
        ax.set_xlabel("Event amplitude (raw-noise SD)", fontsize=6)
        panel_tag(fig, "CDE"[index], axis=ax)

    middle = outer[1].subgridspec(1, 2, width_ratios=[1, 2], wspace=0.5)
    ax = fig.add_subplot(middle[0])
    slot = ax.get_position()
    panel_tag(fig, "F", axis=ax, pad=0.035)
    draw_class_footprints(ax, sess, m_ex, dmd, examples, color_by=color_by, norm=norm)
    ax.set_title("", loc="left")
    fig.text(slot.x0, slot.y1 - 0.017, COMPARTMENT[dmd],
             va="top", fontsize=7, color=INK, gid=f"compartment-title-DMD{dmd}")
    ax.set_position([slot.x0, slot.y0, slot.width, slot.height - 0.055])

    # Feature space: every classified synapse of the archive, one class fit
    # over all sessions (slap2_glutamate_qc_batch.fit_archive_classes).
    m = usable(m_all)
    xlim = (0, np.ceil(100 * m.frac_events_lt2sd.max() / 5) * 5)
    ylim = (np.floor(100 * m.frac_events_gt4sd.min() / 10) * 10, 100)
    ax_fs = fig.add_subplot(middle[1])
    ax_fs.set_gid("archive-class-feature-space")
    keys = set(examples.values())
    rings = m_ex[[(d, r) in keys for d, r in zip(m_ex.dmd, m_ex.roi, strict=True)]]
    _draw_feature_space(
        ax_fs, m, "",
        rings, xlim, ylim, legend_loc="upper right", color_by=color_by, norm=norm)
    ax_fs.set_ylabel("Synapse's events ≥ 4 SD (%)")
    ax_fs.set_xlabel("Synapse's events < 2 SD (%)")
    if color_by is not None:
        fig.canvas.draw()
        pos = ax_fs.get_position()
        gradient_colorbar(fig, [pos.x1 + 0.016, pos.y0, 0.013, pos.height], norm,
                          GRADIENT_LABELS[color_by], orientation="vertical")

    panel_tag(fig, "G", axis=ax_fs, pad=0.035)
    save_panel(fig, out, "figure7_panelG_slap2_glutamate" + gradient_suffix(color_by),
               preview_png=preview_png)
    print(f"panel G -> example-session DMD{dmd}; class examples {examples}")


# ───────────────────────── panel K ─────────────────────────

MIN_CLASS_N = 10   # a class with fewer synapses in a cohort gets no bars


def _rate_bars(ax, d: pd.DataFrame, contexts: list[tuple[str, str]],
               n_cls: dict) -> None:
    """Grouped bars: mean ± SEM event rate per synapse, by context and class."""
    width = 0.26
    xs = np.arange(len(contexts))
    for k, cls in enumerate(CLASS_ORDER):
        means, errs = [], []
        for c, _ in contexts:
            v = d[(d.context == c) & (d.quality_class == cls)]["rate_hz"].dropna()
            if n_cls[cls] < MIN_CLASS_N:
                v = v.iloc[:0]
            means.append(v.mean() if len(v) else np.nan)
            errs.append(v.std(ddof=1) / np.sqrt(len(v)) if len(v) > 1 else np.nan)
        ax.bar(xs + (k - 1) * width, means, width * 0.92, yerr=errs, capsize=1.3,
               color=CLASS_COLORS[cls], label=f"{cls} (n={n_cls[cls]:,})",
               error_kw={"lw": 0.5, "ecolor": INK_2})
    ax.set_xticks(xs)
    ax.set_xticklabels([lbl for _, lbl in contexts], fontsize=5.6)
    ax.set_xlim(-0.6, len(contexts) - 0.4)
    ax.grid(axis="y", alpha=0.7)
    ax.set_axisbelow(True)


def render_panel_k(
    m_all: pd.DataFrame, ctx: pd.DataFrame, out: Path, *, preview_png: bool = True
) -> None:
    """Show compartment/cohort pools and individual sessions on one percentage axis.

    The unused context table is retained for compatibility with existing notebook callers.
    """
    table = class_composition_summary(m_all)
    fig, ax = plt.subplots(figsize=(7.2, 2.9))
    fig.subplots_adjust(left=0.075, right=0.985, top=0.81, bottom=0.39)
    ax.set_gid("three-class-composition")
    positions = np.arange(len(table), dtype=float)
    sessions = table.group.eq("Session")
    positions[sessions] += 1.5
    positions[sessions & table.has_calcium] += 1
    for index, (_, rows) in enumerate(table.loc[sessions].groupby("subject", sort=False)):
        positions[rows.index] += 0.35 * index
    base = np.zeros(len(table))
    for cls in CLASS_ORDER:
        values = table[cls].to_numpy(dtype=float)
        bars = ax.bar(positions, values, bottom=base, width=0.72, color=CLASS_COLORS[cls],
                      edgecolor="white", linewidth=0.3, label=cls)
        for index, bar in enumerate(bars):
            bar.set_gid(f"composition-{index}-{cls.lower().replace(' ', '-')}")
        base += values
    for (group, cohort), rows in table.groupby(["group", "has_calcium"], sort=False):
        x = positions[rows.index]
        cohort_label = "Glu + Ca" if cohort else "Glu only"
        ax.text(float(x.mean()), 1.18, f"{cohort_label}\n"
                + ("DMDs" if group == "Compartment" else "sessions"),
                transform=ax.get_xaxis_transform(), ha="center", va="bottom",
                fontsize=6, color=INK, linespacing=1.2)
    for subject, rows in table.loc[sessions].groupby("subject", sort=False):
        x = positions[rows.index]
        ax.plot([x.min() - 0.4, x.min() - 0.4, x.max() + 0.4, x.max() + 0.4],
                [-0.47, -0.5, -0.5, -0.47], transform=ax.get_xaxis_transform(),
                clip_on=False, color=INK_2, lw=0.5, gid=f"mouse-group-{subject}")
        ax.text(float(x.mean()), -0.57,
                str(subject).removeprefix("sub-"), transform=ax.get_xaxis_transform(),
                ha="center", va="top", fontsize=5.2, color=INK_2,
                gid=f"mouse-id-{subject}")
    label_x = positions[sessions][0] - 1.6
    for text, y in (("Date", -0.24), ("Mouse ID", -0.6)):
        ax.text(label_x, y, text, transform=ax.get_xaxis_transform(),
                ha="right", va="center", fontsize=6, color=INK,
                gid=f"session-{text.lower().replace(' ', '-')}-label")
    ax.set_xticks(positions, table.label, rotation=60, ha="right", fontsize=5.5)
    ax.set(xlim=(-0.6, positions[-1] + 0.6), ylim=(0, 100), ylabel="Synapses (%)")
    ax.grid(axis="y", alpha=0.7)
    ax.set_axisbelow(True)
    panel_tag(fig, "H")
    save_panel(fig, out, "figure7_panelK_slap2_glutamate", preview_png=preview_png)


def class_composition_summary(metrics: pd.DataFrame) -> pd.DataFrame:
    """Count archived classes within four compartment pools and each recording session."""
    classified = usable(metrics)
    selections = [
        ("Compartment", cohort, "", "", f"DMD{dmd}", classified.loc[
            classified.has_calcium.eq(cohort) & classified.dmd.eq(dmd)
        ])
        for cohort in (False, True) for dmd in (1, 2)
    ]
    sessions = classified.groupby(["subject", "session"]).has_calcium.first().reset_index()
    sessions["date"] = sessions.session.map(session_date)
    sessions["first_date"] = sessions.groupby("subject").date.transform("min")
    sessions = sessions.sort_values(["has_calcium", "first_date", "subject", "date"])
    selections.extend(
        ("Session", row.has_calcium, row.subject, row.session, row.date.strftime("%Y-%m-%d"),
         classified.loc[classified.session == row.session])
        for row in sessions.itertuples()
    )
    records = []
    for group, cohort, subject, session, label, subset in selections:
        if subset.empty:
            raise ValueError(f"No classified sources for {label} in {COHORT[cohort]}.")
        counts = subset.quality_class.value_counts().reindex(CLASS_ORDER, fill_value=0)
        records.append({
            "group": group, "has_calcium": cohort, "subject": subject, "session": session,
            "label": label,
            "n": len(subset),
            **{cls: 100 * int(counts[cls]) / len(subset) for cls in CLASS_ORDER},
        })
    return pd.DataFrame.from_records(records)


def publication_tables(
    data_dir: Path = DATA_DIR,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read the archive tables used by the three panels."""
    return (
        pd.read_csv(data_dir / "slap2_metrics_all_sessions.csv"),
        pd.read_csv(data_dir / "slap2_context_rates_all_sessions.csv"),
        pd.read_csv(data_dir / "slap2_session_summary.csv"),
    )


def _publication_source_pair(session: dict, metrics: pd.DataFrame) -> tuple[int, dict[str, int]]:
    for dmd, traces in sorted(session["traces"].items()):
        available = metrics[(metrics.dmd == dmd) & metrics.roi.isin(traces["roi_ids"])]
        low = available.loc[available.quality_class == "Low SNR"]
        high = available.loc[available.quality_class == "High SNR"]
        if not low.empty and not high.empty:
            return dmd, {"Low SNR": int(low.iloc[0].roi), "Non-low SNR": int(high.iloc[0].roi)}
    raise ValueError(
        "The committed example must contain low- and high-quality traces in one plane."
    )


def render_publication_sources(
    session: dict, metrics: pd.DataFrame, output: Path, *, preview_png: bool = False,
) -> None:
    """Show one native dendrite segment and two matched source/event measurements."""
    dmd, sources = _publication_source_pair(session, metrics)
    activity, mean_image, outlines = session["planes"][dmd]
    masks = {group: np.asarray(outlines[roi], dtype=bool) for group, roi in sources.items()}
    vertical, horizontal = np.where(np.logical_or.reduce(list(masks.values())))
    crop = (
          slice(max(0, int(vertical.min()) - 10), min(activity.shape[0], int(vertical.max()) + 11)),
          slice(max(0, int(horizontal.min()) - 30),
              min(activity.shape[1], int(horizontal.max()) + 41)),
    )
    figure = plt.figure(figsize=(7.8, 7.3))
    grid = figure.add_gridspec(
        5, 1, left=0.1, right=0.985, top=0.89, bottom=0.07,
        height_ratios=[1.15, 1, 0.6, 1, 0.6], hspace=0.65,
    )
    images = grid[0].subgridspec(1, 3, width_ratios=[2, 1, 1], wspace=0.25)
    field = figure.add_subplot(images[0])
    field.set_gid("two-source-dendrite")
    field.imshow(mean_image[crop], cmap="gray", interpolation="nearest",
                 vmin=float(np.nanpercentile(mean_image[crop], 2)),
                 vmax=float(np.nanpercentile(mean_image[crop], 99.5)))
    field.set_title(f"DMD{dmd}: one dendrite segment", fontsize=9.6, loc="left")
    hide_frame(field)
    trace_data = session["traces"][dmd]
    times = trace_data["ts"]
    start = float(times[0]) + 920
    duration = 10
    stop = start + duration
    window = (times >= start) & (times < stop)
    if window.sum() < 2:
        raise ValueError("The source-backed shared 920-930 s example window is unavailable.")
    recordings = {}
    for group, roi in sources.items():
        trace = source_trace(trace_data, roi)
        events = event_table(trace, times, trace_data["dt"])
        normalized = (trace - events["raw_med"]) / events["raw_sd"]
        recordings[group] = (events, normalized)
    displayed = np.concatenate([normalized[window] for _, normalized in recordings.values()])
    minimum, maximum = np.nanmin(displayed), np.nanmax(displayed)
    padding = max(0.5, (maximum - minimum) * 0.1)
    amplitude_maximum = max(
        np.nanmax(events["amp_raw"][(times[events["peak_idx"]] >= start)
                                   & (times[events["peak_idx"]] < stop)])
        for events, _ in recordings.values()
    )
    for index, (group, roi) in enumerate(sources.items()):
        color = QUALITY_GROUP_COLORS[group]
        field.contour(masks[group][crop], levels=[0.5], colors=[color], linewidths=1)
        source_y, source_x = np.where(masks[group])
        local_crop = (
            slice(max(0, int(source_y.min()) - 8),
                min(mean_image.shape[0], int(source_y.max()) + 9)),
            slice(max(0, int(source_x.min()) - 8),
                min(mean_image.shape[1], int(source_x.max()) + 9)),
        )
        footprint = figure.add_subplot(images[index + 1])
        footprint.set_gid(f"source-mask-DMD{dmd}-{roi}")
        footprint.imshow(mean_image[local_crop], cmap="gray", interpolation="nearest")
        footprint.contour(masks[group][local_crop], levels=[0.5], colors=[color], linewidths=1.2)
        footprint.set_title(f"{group}\nSource {roi}", color=color, fontsize=9.6)
        hide_frame(footprint)
        events, normalized = recordings[group]
        peak_times = times[events["peak_idx"]]
        event_window = (peak_times >= start) & (peak_times < stop)
        event_times = peak_times[event_window] - start
        peak_indices = events["peak_idx"][event_window]
        trace_axis = figure.add_subplot(grid[1 + 2 * index])
        trace_axis.set_gid(f"raw-source-DMD{dmd}-{roi}")
        trace_axis.plot(times[window] - start, normalized[window], color=INK_2, linewidth=0.65)
        trace_axis.scatter(event_times, normalized[peak_indices],
                           marker="v", s=14, color=color, linewidths=0, zorder=3)
        trace_axis.set_title(f"{group}: source {roi}",
                             color=color, fontsize=9.6, loc="left")
        trace_axis.set_ylabel("Raw trace\n(noise SD)", fontsize=9)
        trace_axis.set_xlim(0, duration)
        trace_axis.set_ylim(minimum - padding, maximum + padding)
        trace_axis.tick_params(labelbottom=False, labelsize=9)
        measurement = figure.add_subplot(grid[2 + 2 * index], sharex=trace_axis)
        measurement.set_gid(f"event-amplitudes-DMD{dmd}-{roi}")
        measurement.vlines(event_times, 0, events["amp_raw"][event_window],
                            color=color, linewidth=1)
        measurement.axhline(4, color=MUTED, linestyle=":", linewidth=0.7)
        measurement.text(duration + 0.05, 4, "4 SD", va="center", fontsize=8, color=MUTED)
        measurement.set_ylabel("Event amplitude\n(noise SD)", fontsize=9)
        measurement.set_ylim(0, max(5, amplitude_maximum * 1.1))
        if index == len(sources) - 1:
            measurement.set_xlabel("Time (s)", fontsize=9)
        else:
            measurement.tick_params(labelbottom=False)
        measurement.tick_params(labelsize=9)
    figure.suptitle("SLAP2 glutamate", fontsize=10.5,
                     x=0.1, y=0.98, ha="left")
    panel_tag(figure, "C")
    save_panel(figure, output, "figure7_panelC_slap2_glutamate", preview_png=preview_png)


def quality_group_ecdfs(metrics: pd.DataFrame) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Return empirical source distributions, retaining the archived Low-SNR assignment."""
    groups = quality_groups(metrics)
    result = {}
    for group in QUALITY_GROUPS:
        values = metrics.loc[groups == group, "frac_events_gt4sd"].to_numpy(dtype=float) * 100
        values = np.sort(values[np.isfinite(values)])
        result[group] = (values, np.arange(1, len(values) + 1) / max(1, len(values)) * 100)
    return result


def combined_quality_ecdf(metrics: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Pool all classified sources without averaging separately normalized group curves."""
    groups = quality_group_ecdfs(metrics)
    values = np.sort(np.concatenate([horizontal for horizontal, _ in groups.values()]))
    return values, np.arange(1, len(values) + 1) / max(1, len(values)) * 100


def low_snr_group_summary(metrics: pd.DataFrame) -> pd.DataFrame:
    """Count low-quality sources once per requested group, excluding unclassified sources."""
    classified = metrics.loc[quality_groups(metrics).notna()]
    selections = [("Overall", "All", classified)]
    selections.extend(("Compartment", f"DMD{dmd}", classified.loc[classified.dmd == dmd])
                      for dmd in (1, 2))
    selections.extend(("Processing cohort", label, classified.loc[classified.has_calcium.eq(flag)])
                      for flag, label in ((False, "Glu\nonly"), (True, "Glu\n+ Ca")))
    selections.extend(("Mouse", str(subject).removeprefix("sub-"),
                       classified.loc[classified.subject == subject])
                      for subject in sorted(classified.subject.unique()))
    records = []
    for kind, label, subset in selections:
        low = int(subset.quality_class.eq("Low SNR").sum())
        session_percentages = [100 * session.quality_class.eq("Low SNR").mean()
                               for _, session in subset.groupby("session", sort=True)]
        records.append({"group": kind, "label": label, "n": len(subset), "low": low,
                        "percent_low": 100 * low / len(subset) if len(subset) else np.nan,
                        "session_percent_low": session_percentages})
    return pd.DataFrame.from_records(records)


def render_publication_distribution(
    metrics: pd.DataFrame, output: Path, *, preview_png: bool = False,
) -> None:
    """Pool source distributions and show archived group overlap without a false cutoff."""
    figure, axis = plt.subplots(figsize=(7.8, 3.2))
    figure.subplots_adjust(left=0.1, right=0.985, top=0.7, bottom=0.22)
    axis.set_gid("session-quality-ecdf")
    sessions = list(metrics.groupby("session", sort=True))
    for index, (session_id, session) in enumerate(sessions):
        horizontal, vertical = combined_quality_ecdf(session)
        axis.step(horizontal, vertical, where="post", color="#8F9996", linewidth=0.6,
                   alpha=0.45, label=f"Sessions (n={len(sessions)})" if index == 0 else None,
                   gid=f"session-ecdf-individual-{session_id}", zorder=1)
    pooled, cumulative = combined_quality_ecdf(metrics)
    axis.step(pooled, cumulative, where="post", color=INK_2, linewidth=1.8,
               label=f"All sources (n={len(pooled)})", gid="session-ecdf-combined", zorder=3)
    grouped = quality_group_ecdfs(metrics)
    for index, (group, (values, _)) in enumerate(grouped.items()):
        axis.scatter(values, np.full(len(values), 1.04 + index * 0.08),
                       transform=axis.get_xaxis_transform(), clip_on=False, marker="|", s=30,
                       color=QUALITY_GROUP_COLORS[group], label=f"{group} (n={len(values)})",
                       gid="session-rug-" + group.lower().replace(" ", "-"))
    if all(len(values) for values, _ in grouped.values()):
        overlap_left = max(values.min() for values, _ in grouped.values())
        overlap_right = min(values.max() for values, _ in grouped.values())
        if overlap_left < overlap_right:
            overlap = axis.axvspan(overlap_left, overlap_right, color="#8F9996", alpha=0.18)
            overlap.set_gid("quality-group-overlap")
            axis.annotate("", xy=(overlap_left, 1.21), xytext=(overlap_right, 1.21),
                           xycoords=axis.get_xaxis_transform(), annotation_clip=False,
                           arrowprops={"arrowstyle": "|-|", "color": MUTED, "linewidth": 0.8})
            axis.text((overlap_left + overlap_right) / 2, 1.27,
                       "Overlapping groups (no single cutoff)",
                       transform=axis.get_xaxis_transform(), ha="center", va="bottom", fontsize=9)
    axis.set(xlim=(0, 100), ylim=(0, 100), xlabel="Events at least 4 raw-noise SD per source (%)",
              ylabel="Cumulative sources (%)")
    axis.legend(loc="lower right", fontsize=9.6)
    axis.tick_params(labelsize=9.6)
    axis.xaxis.label.set_fontsize(9.6)
    axis.yaxis.label.set_fontsize(9.6)
    axis.grid(alpha=0.5)
    figure.suptitle(f"All sources - {len(sessions)} sessions", fontsize=10.5,
                     x=0.1, y=0.98, ha="left")
    panel_tag(figure, "G")
    save_panel(figure, output, "figure7_panelG_slap2_glutamate", preview_png=preview_png)


def render_publication_prevalence(
    metrics: pd.DataFrame, output: Path, *, preview_png: bool = False,
) -> None:
    """Compare pooled source bars with unconnected session dots and grouped bottom labels."""
    summary = low_snr_group_summary(metrics)
    figure, axis = plt.subplots(figsize=(9.2, 3.6))
    figure.subplots_adjust(left=0.09, right=0.99, top=0.92, bottom=0.42)
    axis.set_gid("low-snr-prevalence")
    positions = np.arange(len(summary))
    bars = axis.bar(positions, summary.percent_low, width=0.65,
                     color=QUALITY_GROUP_COLORS["Low SNR"], alpha=0.5, zorder=2)
    for index, bar in enumerate(bars):
        bar.set_gid(f"low-snr-bar-{index}")
    for kind, rows in summary.groupby("group", sort=False):
        horizontal = positions[rows.index]
        label = axis.text(float(horizontal.mean()), -0.5, kind.replace(" ", "\n"),
               transform=axis.get_xaxis_transform(),
                   ha="center", va="top", fontsize=9.6, fontweight="bold")
        label.set_gid("prevalence-group-label-" + kind.lower().replace(" ", "-"))
        if horizontal[0] > 0:
            axis.axvline(horizontal[0] - 0.5, color=GRID, linewidth=0.8,
                           gid="prevalence-group-divider-" + kind.lower().replace(" ", "-"))
    for position, row in summary.iterrows():
        session_values = row.session_percent_low
        offsets = np.linspace(-0.2, 0.2, len(session_values)) if len(session_values) > 1 else [0]
        axis.scatter(position + np.asarray(offsets), session_values, color="#69716F",
                       s=14, linewidths=0, zorder=3, gid=f"session-prevalence-dots-{position}")
    axis.set_xticks(positions, [f"{row.label}\nn={row.n:,}" for row in summary.itertuples()])
    axis.tick_params(labelsize=9)
    axis.set(ylim=(0, 100), ylabel="Low-SNR sources (%)", xlim=(-0.6, len(summary) - 0.4))
    axis.yaxis.label.set_fontsize(9.6)
    axis.grid(axis="y", alpha=0.5)
    axis.set_axisbelow(True)
    axis.legend(handles=[
        Patch(facecolor=QUALITY_GROUP_COLORS["Low SNR"], alpha=0.5, label="Pooled sources"),
        Line2D([], [], color="#69716F", marker="o", linestyle="none", label="Individual sessions"),
    ], loc="upper right", ncol=2, fontsize=9)
    panel_tag(figure, "K")
    save_panel(figure, output, "figure7_panelK_slap2_glutamate", preview_png=preview_png)


def write_publication_panels(
    output: Path, *, data_dir: Path = DATA_DIR, example_path: Path = EXAMPLE_PATH,
    preview_png: bool = False,
) -> list[Path]:
    """Regenerate every migrated panel offline from checksummed publication inputs."""
    provenance = json.loads(
        example_path.with_suffix(".provenance.json").read_text(encoding="utf-8")
    )
    for filename, record in provenance["archive_tables"].items():
        if hashlib.sha256((data_dir / filename).read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError(f"SLAP2 archive table checksum mismatch: {filename}")
    session = load_example_snapshot(example_path)
    metrics, contexts, summary = publication_tables(data_dir)
    example = metrics.loc[metrics.session == session["session_id"]].reset_index(drop=True)
    if len(metrics) != provenance["archive_rows"] or len(summary) != provenance["archive_sessions"]:
        raise ValueError("SLAP2 archive coverage differs from the recorded snapshot.")
    output.mkdir(parents=True, exist_ok=True)
    with mpl.rc_context():
        set_style()
        render_panel_c(session, example, output, preview_png=preview_png)
        render_panel_g(session, example, metrics, summary, output, preview_png=preview_png)
        render_panel_k(metrics, contexts, output, preview_png=preview_png)
        render_panel_c(session, example, output, color_by="median_event_raw_sd",
                   preview_png=preview_png)
        render_panel_g(session, example, metrics, summary, output, color_by="median_event_raw_sd",
                   preview_png=preview_png)
    names = (
        "figure7_panelC_slap2_glutamate", "figure7_panelG_slap2_glutamate",
        "figure7_panelK_slap2_glutamate", "figure7_panelC_slap2_glutamate_gradient",
        "figure7_panelG_slap2_glutamate_gradient",
    )
    extensions = ("svg", "png") if preview_png else ("svg",)
    return [output / f"{name}.{extension}" for name in names for extension in extensions]


def write_slap2_glutamate_figure(output: Path) -> Path:
    """Compose the legacy three SVG sections with publication panels A through H."""
    write_publication_panels(output.parent)
    width, padding, gap = 1600, 24, 28
    elements = []
    y_position = padding
    for panel in "CGK":
        panel_path = output.parent / f"figure7_panel{panel}_slap2_glutamate.svg"
        root = ET.parse(panel_path).getroot()
        _, _, panel_width, panel_height = map(float, root.attrib["viewBox"].split())
        height = (width - 2 * padding) * panel_height / panel_width
        identifiers = {
            node.get("id"): f"slap2-{panel}-{node.get('id')}"
            for node in root.iter() if node.get("id")
        }
        for node in root.iter():
            for attribute, value in list(node.attrib.items()):
                if attribute == "id":
                    node.set(attribute, identifiers[value])
                    continue
                for old, new in identifiers.items():
                    if value == f"#{old}":
                        value = f"#{new}"
                    value = value.replace(f"url(#{old})", f"url(#{new})")
                node.set(attribute, value)
        root.attrib.update({
            "x": str(padding), "y": f"{y_position:.6f}",
            "width": str(width - 2 * padding), "height": f"{height:.6f}",
            "preserveAspectRatio": "xMidYMid meet",
        })
        elements.append(ET.tostring(root, encoding="unicode"))
        y_position += height + gap
    height = y_position - gap + padding
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width}" height="{height:.6f}" viewBox="0 0 {width} {height:.6f}" '
        'role="img" aria-labelledby="title description">',
        '<title id="title">SLAP2 glutamate signal-quality analysis</title>',
        '<desc id="description">A shows one raw trace and amplitude measurement; B its '
        'individual footprint; C through E the three class histograms; F the '
        'example-session DMD2 dendritic map beside G, the archive feature space with matching '
        'example-source rings and IDs; H shows Low SNR, Intermediate '
        'and High SNR composition in four compartment/cohort pools and 20 sessions '
        'on one shared vertical percentage axis, without stimulus-context plots. '
        'The archive includes 2,540 sources from 20 sessions and 8 mice, with 2,521 classified '
        'sources and 19 exclusions. Other modalities remain outside this figure.</desc>',
        f'<rect width="{width}" height="{height:.6f}" fill="white"/>',
        *elements,
        '</svg>',
    ]
    output.write_text(normalize_figure_svg("\n".join(svg)), encoding="utf-8", newline="\n")
    return output


# ───────────────────────── main ─────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    inputs = ap.add_mutually_exclusive_group()
    inputs.add_argument("--nwb", type=Path, help="optional external example NWB")
    inputs.add_argument("--example", type=Path, default=None,
                        help="checksummed example NPZ; defaults to the committed snapshot")
    ap.add_argument("--metrics", default=DATA_DIR, type=Path,
                    help="directory holding slap2_metrics_all_sessions.csv, "
                         "slap2_context_rates_all_sessions.csv, slap2_session_summary.csv")
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--cache", type=Path, default=None,
                    help="local directory to cache the example session's arrays (.npz)")
    ap.add_argument("--only", default="CGK", help="subset of panels to render, e.g. GK")
    ap.add_argument("--color-by", default=None, choices=list(GRADIENT_LABELS),
                    help="colour panels C and G by this per-synapse value on a continuous "
                         "scale instead of the three quality classes; writes *_gradient "
                         "files next to the defaults (panel K always uses the classes)")
    args = ap.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    set_style()

    m_all = pd.read_csv(args.metrics / "slap2_metrics_all_sessions.csv")
    ctx_all = pd.read_csv(args.metrics / "slap2_context_rates_all_sessions.csv")
    summary = pd.read_csv(args.metrics / "slap2_session_summary.csv")
    if "quality_class" not in m_all.columns or not m_all.quality_class.isin(CLASS_ORDER).any():
        raise SystemExit("metrics table has no quality classes — run "
                         "`slap2_glutamate_qc_batch.py --refit-only` first")

    sess = None
    if set("CG") & set(args.only):
        sess = (load_session_cached(args.nwb, args.cache) if args.nwb is not None
                else load_example_snapshot(args.example or EXAMPLE_PATH))
    sid = session_id(args.nwb) if args.nwb is not None else (
        sess["session_id"] if sess is not None else "sub-794237_ses-20250508T145040"
    )
    m_ex = m_all[m_all.session == sid].reset_index(drop=True)
    if m_ex.empty:
        raise SystemExit(f"{sid} is not in {args.metrics}/slap2_metrics_all_sessions.csv")
    print(f"example session {sid}: {len(m_ex)} synapses, classes "
          f"{m_ex.quality_class.value_counts().to_dict()}")

    if "C" in args.only:
        render_panel_c(sess, m_ex, args.output, color_by=args.color_by)
    if "G" in args.only:
        render_panel_g(sess, m_ex, m_all, summary, args.output, color_by=args.color_by)
    if "K" in args.only:
        render_panel_k(m_all, ctx_all, args.output)
    print(f"\nWrote panels to {args.output}")


if __name__ == "__main__":
    main()
