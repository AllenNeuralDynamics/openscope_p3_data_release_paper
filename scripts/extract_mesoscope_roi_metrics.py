#!/usr/bin/env python3
"""Extract the per-ROI cohort table behind the mesoscope unit-extraction column.

This is the expensive half of panels B, F and J of the cross-modality
unit-extraction figure. It has two stages, mirroring the extraction /
presentation split described in CONTRIBUTING.md:

``session``   Open ONE processed mesoscope session over S3, walk its eight
              imaging planes and, for every ROI, compute the event-amplitude
              composition metrics in a single pass over the dF/F trace plus
              the ROI's pixel-mask geometry. Writes ``roi_metrics_<label>.csv``
              with one row per ROI. About nine minutes per session; run it as
              one cluster task per session.

``assemble``  Merge the per-session tables into the committed snapshot
              ``figure_sources/data/mesoscope-unit-extraction-roi-metrics.csv.gz``:
              keep the sessions the release lists as QC ``Pass``, drop ROIs
              with no measurable baseline noise, fit the three quality
              classes once over the whole cohort, bin depth, and write the
              17 columns the renderer needs in a canonical row order with a
              deterministic gzip header. Prints the row count and sha256 to
              paste into the provenance sidecar.

Metric definitions live in ``snr_three_metrics.py`` of the
openscope-ophys-qc repository (commit pinned in the provenance sidecar) and
are imported, not re-implemented; ``mesoscope_qc_pipeline.py`` from the same
checkout does the NWB / S3 access. Pass that checkout's ``src`` directory as
``--qc-src``. Needs pynwb, hdmf-zarr, s3fs/boto3, numpy, pandas and scipy
(k-means and the two continuous SNR definitions); the figure build itself
reads only the committed snapshot and needs none of this.

Usage
-----
    python scripts/extract_mesoscope_roi_metrics.py session \
        --session s3://aind-open-data/multiplane-ophys_839909_2026-02-26_15-11-01_processed_.../ \
        --qc-src /path/to/openscope-ophys-qc/src --out-dir cohort/

    python scripts/extract_mesoscope_roi_metrics.py assemble \
        --inputs 'cohort/roi_metrics_*.csv' \
        --sessions figure_sources/data/experimental-sessions.csv \
        --out figure_sources/data/mesoscope-unit-extraction-roi-metrics.csv.gz

Definitions
-----------
An event is a contiguous strictly-positive run of the Allen pipeline's OASIS
event series, collapsed to the frame of its maximum. Its amplitude is the
raw dF/F peak over [0, +2 tau] minus the median over [-3 tau, -1 tau], in
units of the SD of the below-median half of the trace (a baseline that
transients cannot inflate). ``frac_events_lt2sd`` / ``_2_4sd`` / ``_gt4sd``
are the fractions of an ROI's events below 2, between 2 and 4, and above
4 SD. ``amp_threshold_quality_class`` is k-means (k = 3, k-means++ seeding,
seed 0) on the standardised three fractions over the whole cohort, with
clusters named Low / Intermediate / High SNR by their centroid's > 4 SD
fraction; ``amp_threshold_quality_class_session`` is the same fit within
each session. The k-means objective has several near-equivalent local
optima, so a refit from scratch reproduces the fractions exactly but may
move a few percent of boundary ROIs between neighbouring classes; the
committed snapshot is the record of the labels the panels were drawn from.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import hashlib
import sys
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

# Candidate NWB paths for each series, most specific first (see
# documentation/filetype_reference.md in openscope-ophys-qc).
DFF_PATHS = [("dff_timeseries", "dff_timeseries"), ("dff_timeseries",), ("dff", "dff")]
EVENT_PATHS = [("event_timeseries", "event_timeseries"), ("event_timeseries",),
               ("events", "events")]

MASK_SLAB = 44  # image_mask zarr chunk size along the ROI axis; slab reads are ~30x faster

# Semantic names for the columns the metric library emits.
RENAME = {
    "ido_n_events": "n_events",
    "ido_event_rate_hz": "event_rate_hz",
    "ido_noise_sd_raw": "noise_sd_raw",
    "ido_frac_lt2sd": "frac_events_lt2sd",
    "ido_frac_2_4sd": "frac_events_2_4sd",
    "ido_frac_gt4sd": "frac_events_gt4sd",
    "ido_median_event_sd": "median_event_amp_sd",
    "ido_p90_event_sd": "p90_event_amp_sd",
    "ido_false_pos_frac": "false_positive_frac",
    "ido_detector": "event_detector",
    "ido_qc_flag": "qc_flag",
    "ido_quality_class": "amp_threshold_quality_class",
    "maedeh_noise_floor": "noise_floor",
    "maedeh_baseline": "baseline_dff",
    "maedeh_signal_p95_peaks": "signal_p95_peaks",
    "maedeh_snr": "event_amplitude_snr",
    "maedeh_snr_trace_p95": "trace_p95_snr",
    "maedeh_n_peaks": "n_peaks",
    "maedeh_peak_rate_hz": "peak_rate_hz",
    "davis_robust_event_snr": "percentile_range_snr",
    "davis_signal_p95_p50": "signal_p95_minus_p50",
    "davis_noise_fast_mad": "noise_fast_mad",
    "davis_exceptional_event_score": "exceptional_event_score",
}

FRACTIONS = ["frac_events_lt2sd", "frac_events_2_4sd", "frac_events_gt4sd"]
CLASS_NAMES = ["Low SNR", "Intermediate", "High SNR"]
NO_BASELINE = "Excluded (no baseline noise)"
DEPTH_BINS = [0, 150, 250, 350, np.inf]
DEPTH_LABELS = ["\u2264150", "151\u2013250", "251\u2013350", ">350"]

SNAPSHOT_COLUMNS = [
    "session", "subject_id", "acq_date", "plane", "structure", "depth_um", "depth_bin",
    "roi_index", "roi_area_pix", "n_events", "event_rate_hz",
    "frac_events_lt2sd", "frac_events_2_4sd", "frac_events_gt4sd",
    "amp_threshold_quality_class", "amp_threshold_quality_class_session", "session_label",
]


def session_label(s3_path: str) -> str:
    """multiplane-ophys_839909_2026-02-26_15-11-01_processed_... -> 839909_2026-02-26."""
    for part in reversed(s3_path.rstrip("/").split("/")):
        if part.startswith("multiplane-ophys_"):
            fields = part.split("_processed_")[0].split("_")
            if len(fields) >= 3:
                return f"{fields[1]}_{fields[2]}"
    return s3_path.rstrip("/").split("/")[-1]


# ---------------------------------------------------------------------------
# session stage
# ---------------------------------------------------------------------------

def dt_from_timestamps(ts: np.ndarray, nominal_hz: float) -> float:
    if ts.size < 3:
        return 1.0 / nominal_hz
    dt = float(np.nanmedian(np.diff(ts)))
    return dt if np.isfinite(dt) and dt > 0 else 1.0 / nominal_hz


def plane_segmentation(nwb, plane_name: str):
    proc = nwb.processing[plane_name]
    for key in list(proc.data_interfaces):
        di = proc[key]
        if hasattr(di, "plane_segmentations"):
            segs = di.plane_segmentations
            return segs[list(segs)[0]]
    return None


def mask_geometry(seg, slab: int = MASK_SLAB) -> pd.DataFrame:
    """Pixel area and weighted centroid per ROI, reading chunk-aligned slabs."""
    data = seg["image_mask"].data
    n = int(data.shape[0])
    area = np.full(n, np.nan)
    cx = np.full(n, np.nan)
    cy = np.full(n, np.nan)
    for start in range(0, n, slab):
        block = np.asarray(data[start:min(start + slab, n)])
        for j in range(block.shape[0]):
            mask = block[j]
            yy, xx = np.nonzero(mask > 0)
            i = start + j
            area[i] = float(yy.size)
            if yy.size == 0:
                continue
            w = mask[yy, xx].astype(float)
            tot = float(w.sum())
            cx[i] = float((xx * w).sum() / tot) if tot > 0 else float(xx.mean())
            cy[i] = float((yy * w).sum() / tot) if tot > 0 else float(yy.mean())
    return pd.DataFrame({"roi_index": np.arange(n), "roi_area_pix": area,
                         "roi_centroid_x_pix": cx, "roi_centroid_y_pix": cy})


def process_plane(qc, metrics, nwb, plane_name: str, max_rois: int | None) -> pd.DataFrame | None:
    proc = nwb.processing[plane_name]
    dff_series = qc.get_timeseries_from_proc(proc, DFF_PATHS)
    if dff_series is None:
        print(f"    [{plane_name}] no dF/F series -- skipped", flush=True)
        return None
    dff, ts = qc.load_timeseries_matrix(dff_series)
    dt = dt_from_timestamps(ts, metrics.FRAME_RATE_HZ_NOMINAL)

    events = None
    ev_series = qc.get_timeseries_from_proc(proc, EVENT_PATHS)
    if ev_series is not None:
        events, _ = qc.load_timeseries_matrix(ev_series)
        if events.shape != dff.shape:
            print(f"    [{plane_name}] event shape {events.shape} != dff {dff.shape}"
                  " -- matched-filter fallback", flush=True)
            events = None

    meta = qc.get_roi_metadata_for_plane(nwb, plane_name, load_masks=False)
    n_roi = min(dff.shape[1], len(meta))
    if max_rois is not None:
        n_roi = min(n_roi, max_rois)

    plane = nwb.imaging_planes.get(plane_name) if hasattr(nwb, "imaging_planes") else None
    structure, depth_um = qc.parse_structure_depth(qc.safe_getattr(plane, "location"))
    label_structure = plane_name.split("_")[0] if "_" in plane_name else plane_name
    plane_index = plane_name.split("_")[-1] if "_" in plane_name else ""

    rows = []
    for i in range(n_roi):
        trace = dff[:, i]
        ev = events[:, i] if events is not None else None
        row = metrics.all_metrics(trace, dt, event_trace=ev)
        row.update({
            "plane": plane_name, "roi_index": int(i),
            "structure": structure or label_structure, "plane_index": plane_index,
            "depth_um": depth_um, "dt_s": dt, "n_frames": int(dff.shape[0]),
            "duration_s": float(dff.shape[0] * dt),
            "dff_mean": float(np.nanmean(trace)), "dff_std": float(np.nanstd(trace)),
            "dff_p99": float(np.nanpercentile(trace, 99)),
            "frac_nan": float(np.mean(~np.isfinite(trace))),
        })
        rows.append(row)
    df = pd.DataFrame(rows)

    keep = [c for c in ["roi_index", "is_soma", "is_dendrite", "soma_probability",
                        "dendrite_probability"] if c in meta.columns]
    df = df.merge(meta[keep], on="roi_index", how="left")

    seg = plane_segmentation(nwb, plane_name)
    if seg is not None and "image_mask" in list(seg.colnames):
        df = df.merge(mask_geometry(seg), on="roi_index", how="left")
    else:
        print(f"    [{plane_name}] no image_mask -- geometry left NaN", flush=True)
    print(f"    [{plane_name}] {len(df)} ROIs ({dff.shape[0]} frames)", flush=True)
    return df


def run_session(args: argparse.Namespace) -> int:
    sys.path.insert(0, args.qc_src)
    import mesoscope_qc_pipeline as qc
    import snr_three_metrics as metrics

    label = session_label(args.session)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"roi_metrics_{label}.csv"
    if dest.exists() and not args.force:
        print(f"[{label}] {dest.name} exists -- skipped (use --force to redo)")
        return 0

    t0 = time.time()
    print(f"[{label}] opening {args.session}", flush=True)
    opened = qc.open_nwb_from_s3(args.session)
    frames = []
    try:
        for plane_name in qc.get_plane_names(opened.nwb):
            try:
                df = process_plane(qc, metrics, opened.nwb, plane_name, args.max_rois)
            except Exception:
                print(f"    [{plane_name}] FAILED:\n{traceback.format_exc()}", flush=True)
                continue
            if df is not None and len(df):
                frames.append(df)
    finally:
        try:
            opened.io.close()
        except Exception:
            pass
    if not frames:
        print(f"[{label}] no planes yielded metrics")
        return 1

    session = pd.concat(frames, ignore_index=True)
    session.insert(0, "session_label", label)
    session.insert(1, "s3_path", args.session)
    session.insert(2, "subject_id", label.split("_")[0])
    session.insert(3, "acq_date", label.split("_")[1])
    # Within-session class fit, kept as amp_threshold_quality_class_session by assemble.
    session = metrics.assign_ido_classes(session)
    session = session.rename(columns=RENAME)
    session.to_csv(dest, index=False, lineterminator="\n")
    print(f"[{label}] {len(session)} ROIs in {time.time() - t0:.0f}s -> {dest}")
    return 0


# ---------------------------------------------------------------------------
# assemble stage
# ---------------------------------------------------------------------------

def qc_pass_labels(sessions_csv: Path) -> set[str]:
    """Session labels the release lists as mesoscope QC Pass, from the source id."""
    tab = pd.read_csv(sessions_csv, dtype=str)
    meso = tab[(tab["modality"] == "mesoscope") & (tab["qc"] == "Pass")]
    return {session_label(s) for s in meso["source_session_id"]}


def fit_cohort_classes(frame: pd.DataFrame, seed: int = 0) -> np.ndarray:
    """k-means (k = 3) on the standardised fractions, once over the whole table."""
    from scipy.cluster.vq import kmeans2

    feats = frame[FRACTIONS].to_numpy(dtype=float)
    mu, sigma = feats.mean(0), feats.std(0)
    sigma[sigma == 0] = 1.0
    centroids, labels = kmeans2((feats - mu) / sigma, 3, minit="++", seed=seed)
    order = np.argsort(centroids[:, -1])
    remap = {int(old): new for new, old in enumerate(order)}
    return np.array([CLASS_NAMES[remap[int(lab)]] for lab in labels])


def run_assemble(args: argparse.Namespace) -> int:
    paths = sorted(p for pattern in args.inputs for p in glob.glob(pattern))
    if not paths:
        print("no input tables matched", file=sys.stderr)
        return 2
    roi = pd.concat([pd.read_csv(p, dtype={"session_label": str, "subject_id": str,
                                            "acq_date": str}) for p in paths],
                    ignore_index=True)
    roi = roi.rename(columns={k: v for k, v in RENAME.items() if k in roi.columns})
    roi["session"] = roi["session_label"].astype(str)
    roi = roi.drop_duplicates(subset=["session", "plane", "roi_index"], keep="last")

    passing = qc_pass_labels(Path(args.sessions))
    missing = sorted(passing - set(roi["session"]))
    dropped = sorted(set(roi["session"]) - passing)
    roi = roi[roi["session"].isin(passing)]
    roi = roi[roi["amp_threshold_quality_class"] != NO_BASELINE].copy()

    roi["amp_threshold_quality_class_session"] = roi["amp_threshold_quality_class"]
    roi["amp_threshold_quality_class"] = fit_cohort_classes(roi, seed=args.seed)
    roi["depth_bin"] = pd.cut(roi["depth_um"], DEPTH_BINS, labels=DEPTH_LABELS).astype(str)

    roi["_area"] = (roi["structure"] != "VISp").astype(int)
    roi = roi.sort_values(["session", "_area", "plane", "roi_index"]).drop(columns="_area")
    snapshot = roi[SNAPSHOT_COLUMNS].reset_index(drop=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = snapshot.to_csv(index=False, lineterminator="\n").encode()
    with gzip.GzipFile(out, "wb", compresslevel=9, mtime=0) as handle:
        handle.write(payload)

    counts = snapshot["amp_threshold_quality_class"].value_counts().to_dict()
    print(f"{snapshot['session'].nunique()} sessions, {snapshot['subject_id'].nunique()} mice, "
          f"{len(snapshot):,} ROIs; classes {counts}")
    print(f"QC-Pass sessions without a table: {missing or 'none'}")
    print(f"tables dropped (not QC Pass / not in release listing): {dropped or 'none'}")
    print(f"wrote {out} ({out.stat().st_size / 1e6:.2f} MB)")
    print(f"sha256 {hashlib.sha256(out.read_bytes()).hexdigest()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="stage", required=True)

    s = sub.add_parser("session", help="per-ROI metrics for one processed session")
    s.add_argument("--session", required=True, help="s3:// path to the processed asset")
    s.add_argument("--qc-src", required=True, help="path to openscope-ophys-qc/src")
    s.add_argument("--out-dir", required=True)
    s.add_argument("--max-rois", type=int, default=None, help="smoke test: ROIs per plane")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=run_session)

    a = sub.add_parser("assemble", help="merge per-session tables into the committed snapshot")
    a.add_argument("--inputs", nargs="+", required=True, help="glob(s) of roi_metrics_*.csv")
    a.add_argument("--sessions", required=True,
                   help="release session listing (figure_sources/data/experimental-sessions.csv)")
    a.add_argument("--out", required=True)
    a.add_argument("--seed", type=int, default=0)
    a.set_defaults(func=run_assemble)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
