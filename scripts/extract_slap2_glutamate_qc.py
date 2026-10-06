#!/usr/bin/env python3
"""Run the SLAP2 event-based QC over every session in DANDI 001424.

Downloads one session at a time to a local cache, computes per-synapse metrics
and per-context event rates, then deletes the NWB before moving on — so peak
disk stays around one session (~4 GB) rather than the archive's 43 GB.

The archive ships three NWB layouts and two context conventions; both are
handled by `resolve_layout` / `stimulus_table` in `slap2_glutamate_qc_events`.

Outputs, all keyed by subject and session:

  slap2_metrics_all_sessions.csv        one row per synapse
  slap2_context_rates_all_sessions.csv  one row per synapse x context
  slap2_session_summary.csv             one row per session

Per-event tables are not aggregated — at ~7.9 M events archive-wide that file
would be hundreds of MB, and the panels only need per-context counts.

Quality classes come in two flavours, both kept in the metrics table:

  quality_class_session   k-means fitted within each session (what
                          `slap2_glutamate_qc_events.compute` gives for a single file)
  quality_class           k-means fitted once over all sessions of the archive —
                          this is the label the Figure 7 panels use, and the one
                          copied into the context-rate table.

One yardstick for the whole archive means the two acquisition cohorts are not
on equal footing: the 12 glutamate-only sessions ship two-sided ΔF/F (about a
quarter of the samples below zero), while the 8 glutamate + calcium sessions
ship non-negative, NMF-denoised traces whose noise σ is smaller. Under the
archive-wide fit nearly all synapses of the second cohort land in the High SNR
class; that is a property of how the traces were packaged, not of the preps.

Usage:
    uv run --extra nwb-view python scripts/extract_slap2_glutamate_qc.py \
        --output /tmp/slap2-qc-refresh --cache /tmp/slap2-nwb-cache
    uv run python scripts/extract_slap2_glutamate_qc.py --output <dir> --refit-only
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import shutil
import time
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from openscope_p3_publication.slap2_glutamate_qc_events import (  # noqa: E402
    SD_LARGE,
    assign_classes,
    assign_event_contexts,
    baseline_noise,
    detect_events,
    drop_untimed_events,
    event_amplitudes_raw,
    resolve_layout,
    sampling_interval,
    stimulus_table,
)

DANDISET = "001424"
API = (f"https://api.dandiarchive.org/api/dandisets/{DANDISET}"
       f"/versions/draft/assets/")
UA = {"User-Agent": "Mozilla/5.0"}
REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_SESSION = "sub-794237_ses-20250508T145040"
EXAMPLE_ASSET_ID = "1fccbd05-7ba2-4e40-9cb8-e8814119f756"
EXAMPLE_SHA256 = "375a7ed7c5793cba2aaa24834db5849a71901d36d772a9b94e80df01a619c801"
DEFAULT_EXAMPLE_OUTPUT = REPO_ROOT / "figure_sources/media/slap2-glutamate-qc/example.npz"
UPSTREAM_COMMIT = "a0f6af8a05f296d1c376bd10e1edd70766699c25"
UPSTREAM_REPO = "https://github.com/AllenNeuralDynamics/openscope-community-predictive-processing"


def api_get(url: str) -> dict:
    return json.loads(urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=120).read())


def list_assets() -> list[dict]:
    url, out = API + "?page_size=1000", []
    while url:
        page = api_get(url)
        out += page["results"]
        url = page.get("next")
    return sorted(out, key=lambda a: a["path"])


def write_example_arrays(output: Path, arrays: dict[str, np.ndarray]) -> None:
    """Write a deterministic, lossless NumPy archive using standard LZMA compression."""
    with zipfile.ZipFile(output, "w") as archive:
        for name, values in sorted(arrays.items()):
            buffer = io.BytesIO()
            np.save(buffer, np.asarray(values), allow_pickle=False)
            member = zipfile.ZipInfo(f"{name}.npy", date_time=(1980, 1, 1, 0, 0, 0))
            archive.writestr(member, buffer.getvalue(), compress_type=zipfile.ZIP_LZMA)


def extract_example(
    metrics_dir: Path, output: Path, *, allow_large_example: bool = False
) -> Path:
    """Stream the pinned example and retain only the four plotted source traces."""
    import h5py
    import remfile
    from pynwb import NWBHDF5IO

    from openscope_p3_publication.slap2_glutamate_figure7_panels import (
        _plane_images,
        class_examples,
        event_table,
        example_synapse,
        session_id,
    )

    metrics = pd.read_csv(metrics_dir / "slap2_metrics_all_sessions.csv")
    example_metrics = metrics.loc[metrics.session == EXAMPLE_SESSION]
    selected = {(1, example_synapse(example_metrics)), *class_examples(example_metrics).values()}
    metadata_url = f"https://api.dandiarchive.org/api/assets/{EXAMPLE_ASSET_ID}/"
    source = api_get(metadata_url)
    if source["digest"].get("dandi:sha2-256") != EXAMPLE_SHA256:
        raise ValueError("The pinned SLAP2 example's published checksum has changed.")

    arrays = {"schema_version": np.array(1), "session_id": np.array(EXAMPLE_SESSION)}
    validated_sources = []
    source_url = next(url for url in source["contentUrl"] if ".s3.amazonaws.com/" in url)
    print(f"Streaming {source['path']} ({source['contentSize']:,} bytes in the source NWB)",
          flush=True)
    remote_file = remfile.File(source_url)
    h5_file = h5py.File(remote_file, mode="r")
    io = NWBHDF5IO(file=h5_file, mode="r", load_namespaces=True)
    try:
        layout = resolve_layout(io.read())
        trace_dmds = sorted({dmd for dmd, _ in selected})
        arrays["trace_dmds"] = np.asarray(trace_dmds, dtype=np.int16)
        arrays["plane_dmds"] = np.asarray(layout["dmds"], dtype=np.int16)
        for dmd in layout["dmds"]:
            plane = _plane_images(layout, dmd)
            if plane is None:
                raise ValueError(f"DMD{dmd} is missing an image or source masks.")
            activity, mean_image, outlines = plane
            arrays[f"activity{dmd}"] = activity
            arrays[f"mean{dmd}"] = mean_image
            arrays[f"outlines{dmd}"] = np.stack(outlines)
            if dmd not in trace_dmds:
                continue
            series = layout["dff_series"][dmd]
            roi_ids = sorted(roi for plane_id, roi in selected if plane_id == dmd)
            timestamps = np.asarray(series.timestamps)
            interval = sampling_interval(timestamps)
            print(f"Reading DMD{dmd} source traces {roi_ids}", flush=True)
            traces = np.asarray(series.data[:, roi_ids], dtype=np.float32)
            arrays[f"data{dmd}"] = traces
            arrays[f"ts{dmd}"] = timestamps
            arrays[f"dt{dmd}"] = np.array(interval)
            arrays[f"roi_ids{dmd}"] = np.asarray(roi_ids, dtype=np.int32)
            for column, roi in enumerate(roi_ids):
                events = event_table(traces[:, column], timestamps, interval)
                expected = example_metrics.loc[
                    (example_metrics.dmd == dmd) & (example_metrics.roi == roi)
                ].iloc[0]
                amplitudes = events["amp_raw"][np.isfinite(events["amp_raw"])]
                if len(events["idx"]) != int(expected.n_events):
                    raise ValueError(f"DMD{dmd} ROI {roi} event count differs from the snapshot.")
                if not np.isclose(events["raw_sd"], expected.noise_dff, rtol=1e-6):
                    raise ValueError(f"DMD{dmd} ROI {roi} noise differs from the snapshot.")
                if not np.isclose(np.median(amplitudes), expected.median_event_raw_sd, rtol=1e-6):
                    raise ValueError(f"DMD{dmd} ROI {roi} amplitudes differ from the snapshot.")
                validated_sources.append({
                    "dmd": dmd, "roi": roi, "n_events": int(expected.n_events),
                    "samples": len(timestamps), "source_dtype": str(series.data.dtype),
                    "stored_dtype": str(traces.dtype),
                })
    finally:
        io.close()
        remote_file.close()

    inventory = {session_id(Path(asset["path"])): asset for asset in list_assets()}
    source_assets = []
    for archive_session in sorted(metrics.session.unique()):
        asset = inventory[archive_session]
        asset_metadata = api_get(f"https://api.dandiarchive.org/api/assets/{asset['asset_id']}/")
        source_assets.append({
            "session_id": archive_session, "asset_id": asset["asset_id"],
            "path": asset["path"], "size": asset["size"], "modified": asset["modified"],
            "digest": asset_metadata["digest"], "content_url": asset_metadata["contentUrl"],
        })
    tables = {}
    for table_path in sorted(metrics_dir.glob("*.csv")):
        tables[table_path.name] = {
            "sha256": hashlib.sha256(table_path.read_bytes()).hexdigest(),
            "upstream_path": f"docs/notebooks/plots_figure7_slap2_glutamate/{table_path.name}",
        }

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".npz.tmp")
    write_example_arrays(temporary, arrays)
    size = temporary.stat().st_size
    if size > 100 * 1024 * 1024 or (size >= 10 * 1024 * 1024 and not allow_large_example):
        raise ValueError(
            f"Example snapshot is {size:,} bytes; 10-100 MiB requires maintainer approval "
            "and --allow-large-example, while files above 100 MiB must remain external."
        )
    temporary.replace(output)
    provenance = {
        "version": 1,
        "dandiset_id": DANDISET,
        "dandiset_version": "draft",
        "retrieved_at": dt.datetime.now(dt.UTC).isoformat(),
        "source_pr": f"{UPSTREAM_REPO}/pull/171",
        "upstream_commit": UPSTREAM_COMMIT,
        "archive_tables": tables,
        "archive_rows": len(metrics),
        "archive_sessions": int(metrics.session.nunique()),
        "source_assets": source_assets,
        "inventory_note": "Asset metadata observed during migration; the upstream extraction "
                          "did not record its original NWB asset digests.",
        "example_asset_id": EXAMPLE_ASSET_ID,
        "example_session_id": EXAMPLE_SESSION,
        "example_source_sha256": EXAMPLE_SHA256,
        "source_hash_verification": "Published DANDI digest; source read by HTTPS byte ranges.",
        "selected_sources": validated_sources,
        "selection": "Largest >4 SD event fraction in DMD1 plus the nearest-to-median "
                     "source in each archive-wide quality class within the example session.",
        "parameters": {"tau_seconds": 0.020, "detection_threshold_sd": 3.0,
                       "large_event_minimum_sd": SD_LARGE, "classification_seed": 0,
                       "classification_scope": "one fit over all sessions"},
        "output_file": output.name,
        "compression": "NPY arrays in a lossless ZIP_LZMA archive",
        "large_snapshot_approved": allow_large_example,
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "output_bytes": size,
    }
    output.with_suffix(".provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"Wrote {output} ({size:,} bytes)", flush=True)
    return output


def fetch(asset: dict, cache: Path) -> Path:
    """Download one asset to the cache, resuming nothing — atomic via .part."""
    dest = cache / Path(asset["path"]).name
    if dest.exists() and dest.stat().st_size == asset["size"]:
        print(f"    cached ({dest.stat().st_size/1e9:.2f} GB)", flush=True)
        return dest
    dl = API + f"{asset['asset_id']}/download/"
    part = dest.with_suffix(dest.suffix + ".part")
    t0 = time.time()
    with urllib.request.urlopen(urllib.request.Request(dl, headers=UA),
                                timeout=300) as r, open(part, "wb") as f:
        shutil.copyfileobj(r, f, length=8 << 20)
    part.rename(dest)
    gb = dest.stat().st_size / 1e9
    print(f"    downloaded {gb:.2f} GB in {time.time()-t0:.0f}s", flush=True)
    return dest


def sample_contexts(ts: np.ndarray, stim: pd.DataFrame) -> pd.Categorical:
    """Stimulus context of every sample of a DMD; NaN timestamps get no label.

    Used to count how long each source actually recorded in each context.
    The two DMDs of a session do not always run for the same time, and both
    carry acquisition gaps, so charging every source with the nominal block
    durations would understate its rates; counting its own valid samples per
    context does not. Samples outside every presentation are "Inter-stimulus"
    (the grey-screen ITIs plus any gaps between blocks).
    """
    ts = np.asarray(ts, dtype=float)
    labels = np.full(ts.size, None, dtype=object)
    ok = np.isfinite(ts)
    labels[ok] = assign_event_contexts(ts[ok], stim)
    return pd.Categorical(labels)


def context_seconds(codes: np.ndarray, categories, valid: np.ndarray, dt: float) -> dict:
    """Seconds per context for one source, from its valid samples."""
    counts = np.bincount(codes[valid & (codes >= 0)], minlength=len(categories))
    return {str(c): float(n * dt) for c, n in zip(categories, counts, strict=True) if n}


def process(nwb_path: Path, subject: str, session: str):
    """Per-synapse metrics and per-synapse-per-context event rates."""
    from pynwb import NWBHDF5IO

    io = NWBHDF5IO(str(nwb_path), "r", load_namespaces=True)
    try:
        nwb = io.read()
        layout = resolve_layout(nwb)
        stim = stimulus_table(nwb)
        ctx_source = stim.attrs.get("context_source", "?")

        metric_rows, ctx_rows = [], []
        session_dur = np.nan
        for dmd in layout["dmds"]:
            series = layout["dff_series"][dmd]
            ts = np.asarray(series.timestamps)
            dt = sampling_interval(ts)
            data = np.asarray(series.data, dtype=np.float32)
            span = float(np.nanmax(ts) - np.nanmin(ts))
            session_dur = max(session_dur, span) if np.isfinite(session_dur) else span
            ctx_of_sample = sample_contexts(ts, stim)
            ctx_codes, ctx_names = ctx_of_sample.codes, list(ctx_of_sample.categories)

            for r in range(data.shape[1]):
                trace = data[:, r]
                res = detect_events(trace, dt)
                idx, amp = drop_untimed_events(res["idx"], res["amp_sd"], ts)
                dur_valid = res["n_valid"] * dt
                n_ev = idx.size

                finite = trace[np.isfinite(trace)]
                if finite.size:
                    p95, p50 = np.percentile(finite, [95, 50])
                    raw_noise = baseline_noise(finite)[0]
                    robust_snr = ((p95 - p50) / raw_noise
                                  if raw_noise and np.isfinite(raw_noise) else np.nan)
                else:
                    raw_noise = robust_snr = np.nan

                # Amplitudes in raw-dF/F sigma, comparable to the mesoscope's
                # bins; the filtered-sigma values stay for the detection story.
                amp_raw = event_amplitudes_raw(trace, idx, dt, raw_noise)
                fin = amp_raw[np.isfinite(amp_raw)]
                if fin.size:
                    frac_lt2 = float(np.mean(fin < 2.0))
                    frac_24 = float(np.mean((fin >= 2.0) & (fin < SD_LARGE)))
                    frac_gt4 = float(np.mean(fin >= SD_LARGE))
                    med_raw = float(np.median(fin))
                else:
                    frac_lt2 = frac_24 = frac_gt4 = med_raw = np.nan

                metric_rows.append({
                    "subject": subject, "session": session, "layout": layout["layout"],
                    "has_calcium": layout["has_calcium"], "dmd": dmd, "roi": r,
                    "n_events": n_ev,
                    "duration_valid_s": dur_valid,
                    "event_rate_hz": n_ev / dur_valid if dur_valid > 0 else np.nan,
                    "false_pos_frac": res["n_false_pos"] / n_ev if n_ev else np.nan,
                    "noise_dff": raw_noise, "robust_snr": robust_snr,
                    "qc_flag": ("ok" if np.isfinite(res["noise_sd"])
                                else "rectified_trace"),
                    "median_event_sd": float(np.median(amp)) if n_ev else np.nan,
                    "frac_events_gt4sd_filtered": (float(np.mean(amp >= SD_LARGE))
                                                   if n_ev else np.nan),
                    "median_event_raw_sd": med_raw,
                    "frac_events_lt2sd": frac_lt2,
                    "frac_events_2_4sd": frac_24,
                    "frac_events_gt4sd": frac_gt4,
                })

                if n_ev:
                    valid = np.isfinite(trace) & np.isfinite(ts)
                    ctx_dur = context_seconds(ctx_codes, ctx_names, valid, dt)
                    labels = assign_event_contexts(ts[idx], stim)
                    for ctx, cnt in pd.Series(labels).value_counts().items():
                        secs = ctx_dur.get(ctx, np.nan)
                        ctx_rows.append({
                            "subject": subject, "session": session, "dmd": dmd,
                            "roi": r, "context": ctx, "n_events": int(cnt),
                            "seconds": secs,
                            "rate_hz": cnt / secs if secs and secs > 0 else np.nan,
                        })
            del data

        metrics = (assign_classes(pd.DataFrame(metric_rows))
                   .rename(columns={"quality_class": "quality_class_session"}))
        ctx_df = pd.DataFrame(ctx_rows)

        # Session medians are taken over usable sources only; a rectified trace
        # has no defined SNR and would otherwise drag the summary anywhere.
        ok = metrics[metrics.qc_flag == "ok"]
        summary = {
            "subject": subject, "session": session, "layout": layout["layout"],
            "has_calcium": layout["has_calcium"], "context_source": ctx_source,
            "n_sources": len(metrics), "n_rectified": int((metrics.qc_flag != "ok").sum()),
            "duration_s": round(session_dur, 1),
            "n_contexts": stim["context"].nunique(),
            "median_event_rate_hz": round(float(ok.event_rate_hz.median()), 3),
            "median_false_pos_frac": round(float(ok.false_pos_frac.median()), 4),
            "median_robust_snr": round(float(ok.robust_snr.median()), 3),
            "median_frac_gt4sd": round(float(ok.frac_events_gt4sd.median()), 3),
        }
        return metrics, ctx_df, summary
    finally:
        io.close()


def fit_archive_classes(out_dir: Path) -> pd.DataFrame:
    """Fit quality classes once over every session and write them back.

    Reads `slap2_metrics_all_sessions.csv`, runs `assign_classes` on all
    synapses of the archive together, stores the result as `quality_class`
    (keeping `quality_class_session`), and copies the label into
    `slap2_context_rates_all_sessions.csv`. Safe to re-run; it only touches
    the class columns.
    """
    mpath = out_dir / "slap2_metrics_all_sessions.csv"
    cpath = out_dir / "slap2_context_rates_all_sessions.csv"
    m = pd.read_csv(mpath)
    if "quality_class_session" not in m.columns:      # tables from an older run
        m = m.rename(columns={"quality_class": "quality_class_session"})
    m = m.drop(columns=["quality_class"], errors="ignore")

    m = assign_classes(m.reset_index(drop=True)).sort_values(
        ["subject", "session", "dmd", "roi"]).reset_index(drop=True)
    m.to_csv(mpath, index=False)

    if cpath.exists():
        keys = ["subject", "session", "dmd", "roi"]
        ctx = pd.read_csv(cpath).drop(columns=["quality_class"], errors="ignore")
        ctx = ctx.merge(m[keys + ["quality_class"]], on=keys, how="left")
        ctx.sort_values(keys + ["context"]).to_csv(cpath, index=False)

    spath = out_dir / "slap2_session_summary.csv"
    if spath.exists():
        cols = {"Low SNR": "n_low_snr", "Intermediate": "n_intermediate",
                "High SNR": "n_high_snr"}
        counts = (pd.crosstab([m.subject, m.session], m.quality_class)
                    .reindex(columns=list(cols), fill_value=0).rename(columns=cols)
                    .reset_index())
        summ = pd.read_csv(spath).drop(columns=list(cols.values()), errors="ignore")
        summ.merge(counts, on=["subject", "session"], how="left").to_csv(spath, index=False)

    print("\nQuality classes (one k-means fit over all sessions), by cohort:")
    tab = pd.crosstab(m.has_calcium.map({False: "glutamate only",
                                         True: "glutamate + calcium"}),
                      m.quality_class)
    print(tab.to_string())
    agree = (m.quality_class == m.quality_class_session).mean()
    print(f"{100 * agree:.0f}% of synapses keep their per-session label")
    return m


def write_outputs(args, all_metrics, all_ctx, summaries) -> None:
    """Persist the three aggregate tables, merging by session when asked.

    Merging replaces any rows for the sessions just processed and keeps the
    rest, so a single re-run never duplicates or drops other sessions' rows.
    """
    specs = [
        ("slap2_metrics_all_sessions.csv", all_metrics, ["subject", "session"]),
        ("slap2_context_rates_all_sessions.csv", all_ctx, ["subject", "session"]),
        ("slap2_session_summary.csv",
         [pd.DataFrame(summaries)] if summaries else [], ["subject", "session"]),
    ]
    for fname, frames, keys in specs:
        frames = [f for f in frames if f is not None and not f.empty]
        if not frames:
            continue
        new = pd.concat(frames, ignore_index=True)
        path = args.output / fname
        if args.merge and path.exists():
            old = pd.read_csv(path)
            done = set(map(tuple, new[keys].drop_duplicates().values.tolist()))
            keep = ~old[keys].apply(tuple, axis=1).isin(done)
            new = pd.concat([old[keep], new], ignore_index=True)
        new.sort_values(keys).to_csv(path, index=False)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--example-only", action="store_true",
                    help="Read archive tables from --output and extract only the pinned example.")
    ap.add_argument("--example-output", type=Path, default=DEFAULT_EXAMPLE_OUTPUT,
                    help="Destination NPZ for the compact, offline figure input.")
    ap.add_argument("--allow-large-example", action="store_true",
                    help="Allow a 10-100 MiB example only after explicit maintainer approval.")
    ap.add_argument("--cache", type=Path, default=Path("/tmp/slap2_cache"))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--only", default=None,
                    help="process only assets whose path contains this substring")
    ap.add_argument("--merge", action="store_true",
                    help="merge into existing output CSVs instead of replacing "
                         "them (use with --only to re-run a single session)")
    ap.add_argument("--keep-downloads", action="store_true")
    ap.add_argument("--refit-only", action="store_true",
                    help="skip the per-session pass; only refit the archive-wide "
                         "classes on the existing metrics table")
    args = ap.parse_args()

    if args.example_only:
        extract_example(
            args.output, args.example_output, allow_large_example=args.allow_large_example
        )
        return

    args.output.mkdir(parents=True, exist_ok=True)
    if args.refit_only:
        fit_archive_classes(args.output)
        return
    args.cache.mkdir(parents=True, exist_ok=True)

    assets = list_assets()
    if args.only:
        assets = [a for a in assets if args.only in a["path"]]
        if not assets:
            raise SystemExit(f"No asset path contains {args.only!r}")
    if args.limit:
        assets = assets[:args.limit]
    print(f"{len(assets)} sessions to process "
          f"({sum(a['size'] for a in assets)/1e9:.1f} GB)\n", flush=True)

    all_metrics, all_ctx, summaries, failures = [], [], [], []
    t_start = time.time()
    for i, a in enumerate(assets, 1):
        name = Path(a["path"]).name.replace("_image+ophys.nwb", "")
        subject = a["path"].split("/")[0].replace("sub-", "")
        print(f"[{i}/{len(assets)}] {name}", flush=True)
        try:
            p = fetch(a, args.cache)
            t0 = time.time()
            m, c, s = process(p, subject, name)
            all_metrics.append(m)
            if not c.empty:
                all_ctx.append(c)
            summaries.append(s)
            print(f"    {s['n_sources']} sources · {s['layout']} · "
                  f"rate {s['median_event_rate_hz']} Hz · "
                  f"FP {100*s['median_false_pos_frac']:.2f}% · "
                  f"{time.time()-t0:.0f}s", flush=True)
            if not args.keep_downloads:
                p.unlink(missing_ok=True)
        except Exception as e:
            print(f"    FAILED {type(e).__name__}: {e}", flush=True)
            failures.append({"session": name, "error": f"{type(e).__name__}: {e}"})

        # Write after every session so a crash never loses completed work.
        write_outputs(args, all_metrics, all_ctx, summaries)

    print(f"\n{'='*70}\nDone in {(time.time()-t_start)/60:.1f} min · "
          f"{len(summaries)} ok · {len(failures)} failed", flush=True)
    if summaries:
        df = pd.DataFrame(summaries)
        print(f"\n{df.n_sources.sum()} synapses across {len(df)} sessions, "
              f"{df.subject.nunique()} mice")
        print(df.to_string(index=False))
    for f in failures:
        print(f"  FAILED {f['session']}: {f['error']}")
    if summaries:
        fit_archive_classes(args.output)


if __name__ == "__main__":
    main()
