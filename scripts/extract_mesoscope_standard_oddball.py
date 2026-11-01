#!/usr/bin/env python3
"""Freeze paired dF/F/OASIS oddball statistics from one pinned public NWB asset."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from contextlib import closing
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

from openscope_p3_publication.mesoscope_standard_oddball import (
    ASSET_ID,
    ASSET_SHA256,
    QUALITY_PATH,
    RESPONSE_SECONDS,
    ROOT,
    SESSION_ID,
    SIGNALS,
    SNAPSHOT,
    WINDOW,
    display_trials,
    matched_examples,
    sha256,
    signal_statistics,
    trial_windows,
    window_means,
)
from openscope_p3_publication.mismatch_responsiveness import benjamini_hochberg
from openscope_p3_publication.neural_responses import RASTERMAP_PARAMETERS, RASTERMAP_VERSION


def main() -> None:
    """Read bounded native-signal ranges, then persist only compact derived data."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=SNAPSHOT)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"Refusing to overwrite an existing snapshot: {args.output}")
    try:
        import remfile
        from rastermap import Rastermap
    except ImportError as exc:
        raise SystemExit(
            "Run with uv run --with remfile --with rastermap==1.0 "
            "python scripts/extract_mesoscope_standard_oddball.py"
        ) from exc
    if version("rastermap") != RASTERMAP_VERSION:
        raise SystemExit(f"Rastermap {RASTERMAP_VERSION} is required.")
    api = f"https://api.dandiarchive.org/api/assets/{ASSET_ID}/"
    with urllib.request.urlopen(api, timeout=180) as response:
        asset = json.load(response)
    if asset["digest"]["dandi:sha2-256"] != ASSET_SHA256:
        raise ValueError("Pinned mesoscope asset checksum changed.")
    quality = pd.read_csv(QUALITY_PATH)
    quality = quality.loc[quality.session.eq("832700_2026-01-30")]
    tables, statistics, plane_sources = {}, [], []
    means = {s: [[], []] for s in SIGNALS}
    trial_arrays = {s: {"context": [], "control": []} for s in SIGNALS}
    roi_keys: list[str] = []
    eligible_keys: list[str] = []
    with closing(remfile.File(api + "download/")) as remote, h5py.File(remote, "r") as nwb:
        for condition, name in (
            ("context", "Standard mismatch block_presentations"),
            ("control", "Control block 1_presentations"),
        ):
            table = nwb[f"intervals/{name}"]
            tables[condition] = {
                key: np.asarray(table[source]).astype("U" if key == "trial_type" else float)
                for key, source in (
                    ("trial_type", "TrialType"), ("orientation", "Orientation"),
                    ("delay", "Delay"), ("block_number", "BlockNumber"),
                    ("start", "start_time"), ("stop", "stop_time"),
                )
            }
        trials = trial_windows(tables)
        all_onsets = [r["onset"] for condition in ("context", "control") for r in trials[condition]]
        first, last = min(all_onsets) + WINDOW[0] - 1, max(all_onsets) + WINDOW[1] + 1
        time = None
        for plane_name in (
            "VISp_0", "VISp_1", "VISp_2", "VISp_3", "VISl_4", "VISl_5", "VISl_6", "VISl_7",
        ):
            module = nwb[f"processing/{plane_name}"]
            rois = module["image_segmentation/roi_table"]
            ids = rois["id"][:].astype(int)
            q = quality.loc[quality.plane.eq(plane_name)].set_index("roi_index")
            if q.index.has_duplicates or set(q.index) != set(ids):
                raise ValueError(f"{plane_name}: Figure 4/NWB ROI identities differ.")
            soma = rois["is_soma"][:].astype(bool)
            classes = q.loc[ids, "amp_threshold_quality_class"].to_numpy()
            eligible = soma & np.isin(classes, ["High SNR", "Intermediate"])
            keys = [f"{plane_name}:{roi}" for roi in ids]
            roi_keys.extend(keys)
            eligible_keys.extend(np.asarray(keys)[eligible].tolist())
            times = module["dff_timeseries/dff_timeseries/timestamps"][:]
            dt = float(np.median(np.diff(times)))
            if time is None:
                time = np.arange(
                    int(np.ceil(WINDOW[0] / dt)), int(np.floor(WINDOW[1] / dt)) + 1,
                ) * dt
            left = max(0, int(np.searchsorted(times, first)) - 1)
            right = min(len(times), int(np.searchsorted(times, last)) + 1)
            times = times[left:right]
            location = nwb[f"general/optophysiology/{plane_name}/location"][()]
            if isinstance(location, bytes):
                location = location.decode()
            source = {
                "plane": plane_name, "location": location, "roi_count": len(ids),
                "eligible_count": int(eligible.sum()), "dt_seconds": dt,
                "frame_slice": [left, right], "signals": {},
                "timestamps_sha256": hashlib.sha256(times.tobytes()).hexdigest(),
            }
            for signal, path in (
                ("dff", "dff_timeseries/dff_timeseries"),
                ("oasis", "event_timeseries"),
            ):
                group = module[path]
                signal_times = group["timestamps"][left:right]
                if not np.array_equal(times, signal_times):
                    raise ValueError(f"{plane_name}: dF/F/OASIS timestamps differ.")
                dataset = group["data"]
                values = np.asarray(dataset[left:right], dtype=np.float32)
                if dataset.attrs["conversion"] != 1 or dataset.attrs["offset"] != 0:
                    raise ValueError("Unexpected signal conversion; explicit calibration required.")
                source["signals"][signal] = {
                    "path": dataset.name, "unit": str(dataset.attrs["unit"]),
                    "shape": list(dataset.shape),
                    "slice_sha256": hashlib.sha256(values.tobytes()).hexdigest(),
                }
                collected, frame_counts, displayed = {}, {}, {}
                for condition in ("context", "control"):
                    for kind, suffix in (("response", "test"), ("baseline", "baseline")):
                        key = f"{condition}_{suffix}"
                        collected[key], counts = window_means(
                            times, values, [r[kind] for r in trials[condition]],
                        )
                        frame_counts[key] = [int(counts.min()), int(counts.max())]
                    aligned = display_trials(
                        times, values[:, eligible],
                        np.asarray([r["onset"] for r in trials[condition]]), time,
                    )
                    baseline = collected[f"{condition}_baseline"][eligible]
                    displayed[condition] = aligned - baseline[:, :, None]
                    if not np.isfinite(displayed[condition]).all():
                        raise ValueError(
                            f"{plane_name}/{signal}: nonfinite eligible trial samples."
                        )
                    trial_arrays[signal][condition].append(displayed[condition])
                    means[signal][0 if condition == "context" else 1].append(
                        displayed[condition].mean(axis=1),
                    )
                collected["context_comparison"], counts = window_means(
                    times, values, [r["comparison"] for r in trials["context"]],
                )
                frame_counts["context_comparison"] = [int(counts.min()), int(counts.max())]
                table = signal_statistics(collected)
                table["context_response_mean"] = np.nanmean(collected["context_test"], axis=1)
                table["control_response_mean"] = np.nanmean(collected["control_test"], axis=1)
                table["roi_key"], table["roi_id"] = keys, ids
                table["plane"], table["area"] = plane_name, plane_name.split("_")[0]
                table["signal"], table["is_soma"], table["quality_class"] = signal, soma, classes
                table["eligible"] = eligible
                statistics.append(table)
                source["signals"][signal]["native_frame_count_range"] = frame_counts
                print(
                    f"{plane_name} {signal}: {len(ids)} ROIs, {eligible.sum()} eligible, "
                    f"{len(times)} native frames read", flush=True,
                )
            plane_sources.append(source)
    assert time is not None
    stats = pd.concat(statistics, ignore_index=True)
    for signal in SIGNALS:
        rows = stats.signal.eq(signal)
        for screen in ("q1", "q2"):
            stats.loc[rows, f"{screen}_q"] = benjamini_hochberg(stats.loc[rows, f"{screen}_p"])
    arrays = {"time": time}
    for signal in SIGNALS:
        arrays[f"delta_{signal}"] = np.stack([
            np.concatenate(means[signal][c]) for c in (0, 1)
        ]).astype(np.float32)
    examples = matched_examples(stats, eligible_keys)
    example_indices = [eligible_keys.index(key) for key in examples]
    for signal in SIGNALS:
        for condition in ("context", "control"):
            arrays[f"examples_{signal}_{condition}"] = np.concatenate(
                trial_arrays[signal][condition],
            )[example_indices]
    matrix = arrays["delta_dff"][0]
    if not np.isfinite(matrix).all() or np.any(np.ptp(matrix, axis=1) == 0):
        raise ValueError("Shared dF/F context Rastermap input has nonfinite or constant rows.")
    parameters = {**RASTERMAP_PARAMETERS, "n_PCs": min(matrix.shape) - 1}
    model = Rastermap(**parameters, keep_norm_X=False, verbose=False).fit(
        matrix, compute_X_embedding=False,
    )
    order = np.asarray(model.isort, dtype=int).tolist()
    if sorted(order) != list(range(len(eligible_keys))):
        raise ValueError("Rastermap did not return a complete shared permutation.")
    paths = [
        Path(__file__).resolve(),
        ROOT / "src/openscope_p3_publication/mesoscope_standard_oddball.py",
        ROOT / "src/openscope_p3_publication/standard_oddball_cohort.py",
        ROOT / "src/openscope_p3_publication/mismatch_responsiveness.py",
        ROOT / "src/openscope_p3_publication/neural_responses.py",
        ROOT / "src/openscope_p3_publication/pupil_responses.py",
        ROOT / "src/openscope_p3_publication/mismatch_adjacency.py",
        QUALITY_PATH, ROOT / "figure_sources/data/experimental-sessions.csv",
    ]
    args.output.mkdir(parents=True)
    table_path = args.output / "statistics.csv.gz"
    stats.to_csv(
        table_path, index=False, float_format="%.17g",
        compression={"method": "gzip", "mtime": 0},
    )
    array_path = args.output / "responses.npz"
    np.savez_compressed(array_path, **arrays)
    payload = {
        "version": 1, "session_id": SESSION_ID, "dandiset": "001768",
        "dandiset_version": "draft", "retrieved_date": datetime.now(UTC).date().isoformat(),
        "asset": {k: asset[k] for k in ("identifier", "path", "contentSize", "digest")},
        "download_url": api + "download/", "event": "orientation_90",
        "response_seconds": RESPONSE_SECONDS,
        "statistics": (
            "Native finite-frame means; half-open 500-ms test and paired preceding-standard "
            "windows; Q2 subtracts each trial's full preceding-grey baseline. Paired two-sided "
            "Wilcoxon zsplit for Q1; unpaired two-sided Mann-Whitney for Q2. Exploratory strict "
            "p<0.05 and abs(MI)>0.1. BH q across all 2371 original ROIs, "
            "separately per signal/test."
        ),
        "display": (
            "Linear interpolation at approximately native-frame spacing for visualization only; "
            "per-trial native baseline subtraction; no SDF kernel or spike-rate conversion."
        ),
        "trials": trials, "planes": plane_sources,
        "roi_keys": eligible_keys, "original_roi_count": len(roi_keys),
        "eligibility": "NWB is_soma and Figure 4 class High SNR or Intermediate; no Hz threshold",
        "example_roi_keys": examples,
        "example_rule": (
            "Shared positive Q1/Q2 responder maximizes minimum signed MI across both tests and "
            "signals. Shared Q2 p>=0.05, abs(MI)<0.25 comparison maximizes mean context OASIS "
            "response among active eligible ROIs. Not a claim of absent visual responsiveness."
        ),
        "order": order, "rastermap": {
            "fit_signal": "dff", "fit_condition": "context", "parameters": parameters,
            "version": version("rastermap"),
            "input_sha256": hashlib.sha256(matrix.tobytes()).hexdigest(),
        },
        "sources": [
            {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)} for path in paths
        ],
        "outputs": [
            {"path": path.name, "sha256": sha256(path)} for path in (table_path, array_path)
        ],
        "software": {
            name: version(name)
            for name in ("numpy", "scipy", "pandas", "h5py", "remfile", "rastermap")
        },
    }
    (args.output / "provenance.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
    )
    print(f"Wrote {args.output}; {len(eligible_keys)} eligible ROIs; examples {examples}.")


if __name__ == "__main__":
    main()
