#!/usr/bin/env python3
"""Extract the mesoscope per-plane ROI SNR intermediate for Figure 7.

This is the expensive half of the figure: it opens one processed mesoscope
session over S3, walks all eight simultaneously-acquired imaging planes, and for
every ROI computes the three candidate SNR definitions in a single pass over its
dF/F trace.  It also carries the anatomy needed to draw the plane -- the average
projection image, per-ROI pixel-mask run-lengths, area and centroid -- and a
short dF/F + event excerpt so the reader can see the trace behind any ROI.

Output is one deterministic JSON file.  Nothing downstream touches the cloud:
the renderer reads this file and emits the interactive page and its static
counterpart, so a fresh clone reproduces both figures byte-for-byte without
network access or credentials.

The three definitions (named for what they measure; provenance in the paper's
figure caption and in ``snr_three_metrics.py``):

  frac_events_gt4sd    Fraction of detected events whose amplitude exceeds 4 SD
                       of a non-event baseline of the raw trace.
  event_amplitude_snr  95th-percentile peak amplitude over a successive-
                       difference noise floor, std(diff(f))/sqrt(2).
  percentile_range_snr (P95 - P50) of dF/F over the MAD-SD of the residual left
                       after Gaussian-smoothing the trace.

Usage
-----
    python extract_mesoscope_plane_snr.py \
        --session s3://aind-open-data/multiplane-ophys_839909_2026-02-20_12-53-27_processed_.../ \
        --qc-src /path/to/openscope-ophys-qc/src \
        --out mesoscope-plane-snr.json
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import time
import zlib
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Display-excerpt configuration.  Fixed constants, not tuned per session, so the
# intermediate is a pure function of the session it names.
# ---------------------------------------------------------------------------
EXCERPT_SECONDS = 60.0
EXCERPT_START_FRACTION = 0.25   # excerpt begins a quarter of the way in
PROJECTION_CLIP = (1.0, 99.5)   # robust percentile stretch for the backdrop

# Headline metric columns, keyed by the definitional name used in the figure and
# valued by the key ``snr_three_metrics.all_metrics`` returns.
METRIC_KEYS = {
    "frac_events_gt4sd": "ido_frac_gt4sd",
    "event_amplitude_snr": "maedeh_snr",
    "percentile_range_snr": "davis_robust_event_snr",
}
# Supporting per-ROI columns carried for the tooltip and the covariate panel.
EXTRA_KEYS = {
    "event_rate_hz": "ido_event_rate_hz",
    "n_events": "ido_n_events",
    "baseline_noise_sd": "ido_noise_sd_raw",
    "successive_diff_noise": "maedeh_noise_floor",
    "fast_residual_mad_sd": "davis_noise_fast_mad",
}


# ---------------------------------------------------------------------------
# Deterministic, dependency-free encoders.  The publication package declares no
# third-party runtime dependencies, and a plotting library would additionally
# stamp its version into the PNG, so images are written with zlib alone.
# ---------------------------------------------------------------------------
AREA_ORDER = ("VISp", "VISl")


def order_planes(planes: list[dict]) -> list[dict]:
    """Primary visual area first, then ascending recorded depth within area."""
    def key(p: dict) -> tuple:
        area = p.get("structure") or ""
        rank = AREA_ORDER.index(area) if area in AREA_ORDER else len(AREA_ORDER)
        depth = p.get("depthUm")
        return (rank, area, float("inf") if depth is None else depth, p["plane"])
    return sorted(planes, key=key)


def session_id(s3_path: str) -> str:
    """s3://.../multiplane-ophys_839909_2026-02-20_12-53-27_processed_.../pophys.nwb.zarr
    -> multiplane-ophys_839909_2026-02-20_12-53-27.  The path may point at the
    asset folder or at the zarr inside it, so find the asset component rather
    than taking the basename."""
    for part in reversed(str(s3_path).rstrip("/").split("/")):
        if part.startswith("multiplane-ophys"):
            return part.split("_processed_")[0]
    return Path(str(s3_path).rstrip("/")).name


def _finite(value) -> float | None:
    """JSON has no NaN.  Non-finite metric values become null, which the browser
    reads as 'not computable for this ROI' rather than as a number."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None


def _png_chunk(tag: bytes, payload: bytes) -> bytes:
    body = tag + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def encode_gray_png(image: np.ndarray) -> bytes:
    """8-bit grayscale PNG.  Fixed compression level keeps output byte-stable."""
    arr = np.ascontiguousarray(image, dtype=np.uint8)
    height, width = arr.shape
    raw = b"".join(b"\x00" + arr[row].tobytes() for row in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(raw, 9))
        + _png_chunk(b"IEND", b"")
    )


def quantize(values: np.ndarray) -> tuple[str, float]:
    """int16 quantization with an explicit scale, mirroring the repo's
    ``traceScale`` convention.  Returns (base64 little-endian int16, scale)."""
    import base64

    arr = np.asarray(values, dtype=np.float64)
    arr = np.where(np.isfinite(arr), arr, 0.0)
    peak = float(np.max(np.abs(arr))) if arr.size else 0.0
    scale = peak / 32767.0 if peak > 0 else 1.0
    q = np.rint(arr / scale).astype("<i2")
    return base64.b64encode(q.tobytes()).decode("ascii"), scale


def mask_runs(mask: np.ndarray) -> list[int]:
    """Flatten a boolean ROI mask to [row, col_start, length, ...] runs.

    The browser rasterizes a label image from these, which is both smaller than
    a dense label mask and exact -- no outline approximation.
    """
    runs: list[int] = []
    for row in np.flatnonzero(mask.any(axis=1)):
        cols = np.flatnonzero(mask[row])
        breaks = np.flatnonzero(np.diff(cols) > 1)
        starts = np.concatenate(([0], breaks + 1))
        ends = np.concatenate((breaks, [cols.size - 1]))
        for s, e in zip(starts, ends, strict=True):
            runs.extend((int(row), int(cols[s]), int(cols[e] - cols[s] + 1)))
    return runs


def normalize_projection(projection: np.ndarray) -> np.ndarray:
    arr = np.asarray(projection, dtype=np.float64)
    finite = np.isfinite(arr)
    if not finite.any():
        return np.zeros(arr.shape, dtype=np.uint8)
    lo, hi = np.percentile(arr[finite], PROJECTION_CLIP)
    if not np.isfinite(hi - lo) or hi <= lo:
        lo, hi = float(np.min(arr[finite])), float(np.max(arr[finite]))
    if hi <= lo:
        return np.zeros(arr.shape, dtype=np.uint8)
    scaled = (np.clip(arr, lo, hi) - lo) / (hi - lo)
    return np.rint(scaled * 255.0).astype(np.uint8)


# ---------------------------------------------------------------------------
def build_plane(qc, materialize, metrics_mod, nwb, plane_name: str) -> dict | None:
    import base64

    proc = nwb.processing[plane_name]
    dff_series = qc.get_timeseries_from_proc(proc, [("dff_timeseries", "dff_timeseries"),
                                                    ("dff_timeseries",), ("dff", "dff")])
    if dff_series is None:
        print(f"  [{plane_name}] no dF/F timeseries -- skipped", flush=True)
        return None

    t0 = time.time()
    dff, timestamps = qc.load_timeseries_matrix(dff_series)
    dt = float(np.median(np.diff(np.asarray(timestamps, dtype=float))))

    ev_series = qc.get_timeseries_from_proc(proc, [("event_timeseries", "event_timeseries"),
                                                   ("event_timeseries",), ("events", "events")])
    events = None
    if ev_series is not None:
        events, _ = qc.load_timeseries_matrix(ev_series)
        if events.shape != dff.shape:
            print(f"  [{plane_name}] event shape {events.shape} != dff {dff.shape}"
                  " -- matched-filter fallback", flush=True)
            events = None
    t_read = time.time() - t0

    n_frames, n_roi = dff.shape
    meta = qc.get_roi_metadata_for_plane(nwb, plane_name, load_masks=True)
    if len(meta) < n_roi:
        n_roi = len(meta)

    plane_obj = nwb.imaging_planes.get(plane_name) if hasattr(nwb, "imaging_planes") else None
    structure, depth_um = qc.parse_structure_depth(qc.safe_getattr(plane_obj, "location"))
    structure = structure or (plane_name.split("_")[0] if "_" in plane_name else plane_name)

    projection, projection_label = materialize.get_plane_projection(nwb, plane_name)
    if projection is not None:
        projection = (
            np.asarray(projection)[..., 0]
            if projection.ndim == 3
            else np.asarray(projection)
        )
        height, width = projection.shape[:2]
    else:
        height = width = 0

    # ROI masks -> run-lengths.  get_roi_metadata_for_plane already pulled the
    # image_mask column, so this re-reads it from the same table rather than the
    # cloud a second time.
    roi_table = proc["image_segmentation"]["roi_table"]
    image_masks = roi_table["image_mask"].data
    if height == 0:
        sample = np.asarray(image_masks[0])
        height, width = sample.shape[:2]
        projection = np.zeros((height, width), dtype=np.float64)
        projection_label = "No projection in NWB"

    # Fixed display excerpt, identical across planes (they are simultaneous).
    n_excerpt = min(n_frames, int(round(EXCERPT_SECONDS / dt)))
    start = min(int(round(n_frames * EXCERPT_START_FRACTION)), max(0, n_frames - n_excerpt))
    stop = start + n_excerpt

    t0 = time.time()
    rows, dff_excerpt, event_excerpt, runs_flat, run_offsets = [], [], [], [], [0]
    for i in range(n_roi):
        trace = dff[:, i]
        ev = events[:, i] if events is not None else None
        m = metrics_mod.all_metrics(trace, dt, event_trace=ev)
        row = {name: _finite(m.get(key)) for name, key in METRIC_KEYS.items()}
        row.update({name: _finite(m.get(key)) for name, key in EXTRA_KEYS.items()})
        row["roi_index"] = int(i)
        for col in ("roi_area_pix", "roi_centroid_x_pix", "roi_centroid_y_pix", "soma_probability"):
            row[col] = _finite(meta[col].iloc[i]) if col in meta.columns else None
        rows.append(row)

        dff_excerpt.append(trace[start:stop])
        event_excerpt.append((ev if ev is not None else np.zeros(n_frames))[start:stop])

        mask = np.asarray(image_masks[i])
        runs_flat.extend(mask_runs(mask > 0))
        run_offsets.append(len(runs_flat))
    t_metric = time.time() - t0

    dff_b64, dff_scale = quantize(np.asarray(dff_excerpt, dtype=np.float64))
    ev_b64, ev_scale = quantize(np.asarray(event_excerpt, dtype=np.float64))
    runs_b64 = base64.b64encode(np.asarray(runs_flat, dtype="<u2").tobytes()).decode("ascii")

    print(f"  [{plane_name}] {n_roi} ROIs x {n_frames} frames"
          f" | read {t_read:.0f}s metrics {t_metric:.0f}s"
          f" | excerpt frames {start}:{stop}", flush=True)

    return {
        "plane": plane_name,
        "structure": structure,
        "depthUm": None if depth_um is None or not np.isfinite(depth_um) else float(depth_um),
        "nRois": int(n_roi),
        "nFrames": int(n_frames),
        "dtSeconds": dt,
        "durationSeconds": float(n_frames * dt),
        "imageWidth": int(width),
        "imageHeight": int(height),
        "projectionLabel": projection_label,
        "projectionPng": base64.b64encode(
            encode_gray_png(normalize_projection(projection))
        ).decode("ascii"),
        "maskRunsBase64": runs_b64,
        "maskRunOffsets": run_offsets,
        "excerptStartFrame": int(start),
        "excerptFrames": int(n_excerpt),
        "eventDetector": "allen_oasis" if events is not None else "matched_filter",
        "dffBase64": dff_b64,
        "dffScale": dff_scale,
        "eventsBase64": ev_b64,
        "eventsScale": ev_scale,
        "rois": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", required=True, help="s3:// path to the processed session asset")
    ap.add_argument("--qc-src", required=True, help="path to openscope-ophys-qc/src")
    ap.add_argument("--qc-scripts", default=None, help="path to openscope-ophys-qc/scripts")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument(
        "--planes", nargs="*", default=None,
        help="subset of plane names (default: all)",
    )
    args = ap.parse_args()

    sys.path.insert(0, args.qc_src)
    sys.path.insert(0, args.qc_scripts or str(Path(args.qc_src).parent / "scripts"))
    import materialize_session_cache as materialize
    import mesoscope_qc_pipeline as qc
    import snr_three_metrics as metrics_mod

    opened = qc.open_nwb_from_s3(args.session)
    nwb = opened.nwb if hasattr(opened, "nwb") else opened["nwb"]

    plane_names = args.planes or qc.get_plane_names(nwb)
    print(f"session: {args.session}\nplanes: {plane_names}", flush=True)

    planes = []
    for name in sorted(plane_names):
        plane = build_plane(qc, materialize, metrics_mod, nwb, name)
        if plane is not None:
            planes.append(plane)

    doc = {
        "schemaVersion": 1,
        "sessionId": session_id(args.session),
        "sessionSource": str(args.session),
        "excerptSeconds": EXCERPT_SECONDS,
        "excerptStartFraction": EXCERPT_START_FRACTION,
        "metricDefinitions": {
            "frac_events_gt4sd": (
                "Fraction of detected events exceeding 4 SD of the non-event "
                "baseline of the raw trace."
            ),
            "event_amplitude_snr": (
                "95th-percentile peak amplitude divided by the successive-difference "
                "noise floor, std(diff(f))/sqrt(2)."
            ),
            "percentile_range_snr": (
                "(P95 - P50) of dF/F divided by the MAD-SD of the residual after "
                "Gaussian smoothing."
            ),
        },
        # Plane index does not track depth in this pipeline -- VISp_2 is the
        # most superficial of the VISp planes while VISp_0 sits third. Order by
        # recorded depth within area so any figure reading this file top to
        # bottom is reading a depth sequence, not an acquisition-order sequence.
        "planes": order_planes(planes),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=1, sort_keys=True, allow_nan=False,
                                   default=lambda o: None) + "\n", encoding="utf-8")
    total = sum(p["nRois"] for p in planes)
    print(f"wrote {args.out} | {len(planes)} planes | {total} ROIs |"
          f" {args.out.stat().st_size / 1e6:.1f} MB", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
