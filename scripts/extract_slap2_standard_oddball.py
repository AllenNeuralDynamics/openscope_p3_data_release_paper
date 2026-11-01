"""Stream one pinned dual-channel standard session; never download NWBs or refit SNR labels."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import shutil
import time
import urllib.request
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

from openscope_p3_publication.mesoscope_standard_oddball import (
    ROOT,
    display_trials,
    sha256,
    signal_statistics,
    validate_frames,
)
from openscope_p3_publication.mesoscope_standard_oddball_cohort import (
    native_window_statistics,
    optical_event_windows,
)
from openscope_p3_publication.mismatch_responsiveness import benjamini_hochberg
from openscope_p3_publication.neural_responses import RASTERMAP_PARAMETERS, RASTERMAP_VERSION
from openscope_p3_publication.slap2_standard_oddball import (
    ASSET_ID,
    ASSETS,
    QUALITY,
    SESSION,
    SIGNALS,
    SNAPSHOT,
    finite_native_trials,
    recorded_trial_windows,
    select_examples,
    source_quality,
)


def extract_native(stage_dir: Path) -> None:
    """Extract full-precision native statistics and compact display-only summaries."""
    import remfile
    if stage_dir.exists() or SNAPSHOT.exists():
        raise FileExistsError("Refusing to overwrite existing native stage or frozen snapshot.")
    asset = next(r for r in json.loads(ASSETS.read_text())["source_assets"]
                 if r["asset_id"] == ASSET_ID)
    with urllib.request.urlopen(
        f"https://api.dandiarchive.org/api/assets/{ASSET_ID}/", timeout=60,
    ) as response:
        actual = json.load(response)
    if any(actual[k] != asset[v] for k, v in (
        ("path", "path"), ("contentSize", "size"), ("digest", "digest"),
    )):
        raise ValueError("Pinned SLAP2 asset metadata changed.")
    statistics, sources, keys, original = [], [], [], []
    trial_arrays = {s: {c: {} for c in ("context", "control")} for s in SIGNALS}
    arrays = {"time": np.arange(-150, 151, dtype=float) / 200}
    windows_by_dmd, keys_by_dmd = {}, {}
    with closing(remfile.File(asset["content_url"][-1], _max_cache_size=64 * 1024**2)) as remote:
        with h5py.File(remote, "r") as nwb:
            tables = {}
            for condition, name in (
                ("context", "standard_oddball"), ("control", "standard_control"),
            ):
                group = nwb[f"intervals/{name}"]
                tables[condition] = {
                    k: np.asarray(group[v]).astype(str if k == "trial_type" else float)
                    for k, v in (
                        ("trial_type", "TrialType"), ("orientation", "Orientation"),
                        ("delay", "Delay"), ("block_number", "BlockNumber"),
                        ("start", "start_time"), ("stop", "stop_time"),
                    )
                }
            windows = optical_event_windows(tables)
            for dmd in (1, 2):
                group = nwb[f"processing/ophys/Fluorescence_DMD{dmd}"]
                green = group[f"DMD{dmd}_dFF_green"]
                timestamps = np.asarray(green["timestamps"])
                validate_frames(timestamps, np.empty((len(timestamps), 0)))
                region = np.asarray(green["rois"])
                ids = np.asarray(nwb[green["rois"].attrs["table"]]["id"])[region]
                quality = source_quality(dmd, ids)
                eligible = quality.eligible.to_numpy()
                keys_by_dmd[str(dmd)] = quality.loc[eligible, "roi_key"].tolist()
                keys.extend(quality.loc[eligible, "roi_key"])
                original.extend(quality.roi_key)
                dmd_windows = recorded_trial_windows(timestamps, windows)
                windows_by_dmd[str(dmd)] = dmd_windows
                print(
                    f"DMD{dmd}: recorded 90-degree trials "
                    f"{len(dmd_windows['orientation_90']['context'])} context / "
                    f"{len(dmd_windows['orientation_90']['control'])} control", flush=True,
                )
                collected_signals, validity_signals = {}, {}
                for signal, channel in SIGNALS.items():
                    series = group[f"DMD{dmd}_dFF_{channel}"]
                    data = series["data"]
                    if (
                        not np.array_equal(np.asarray(series["timestamps"]), timestamps)
                        or not np.array_equal(np.asarray(series["rois"]), region)
                        or nwb[series["rois"].attrs["table"]].name
                        != nwb[green["rois"].attrs["table"]].name
                        or data.shape != (len(timestamps), len(ids))
                        or data.attrs["conversion"] != 1 or data.attrs["offset"] != 0
                    ):
                        raise ValueError(f"DMD{dmd}/{signal}: alignment/calibration differs.")
                    unit = data.attrs["unit"]
                    unit = unit.decode() if isinstance(unit, bytes) else str(unit)
                    location = nwb[f"general/optophysiology/ImagingPlane_DMD{dmd}/location"][()]
                    location = location.decode() if isinstance(location, bytes) else str(location)
                    source = {
                        "dmd": dmd, "signal": signal, "path": data.name, "unit": unit,
                        "shape": list(data.shape), "dtype": str(data.dtype), "location": location,
                        "roi_ids": ids.tolist(), "eligible_count": int(eligible.sum()),
                        "timestamps_sha256": hashlib.sha256(timestamps.tobytes()).hexdigest(),
                        "median_native_hz": float(1 / np.median(np.diff(timestamps))),
                        "conversion": 1, "offset": 0, "slabs": [],
                    }
                    collected = {e: {} for e in dmd_windows}
                    validity_signals[signal] = {}
                    for condition in ("context", "control"):
                        requests = {}
                        for event, spec in dmd_windows.items():
                            for kind, suffix in (("response", "test"), ("baseline", "baseline")):
                                requests[f"{event}:{condition}_{suffix}"] = [
                                    r[kind] for r in spec[condition]
                                ]
                            if condition == "context":
                                requests[f"{event}:context_comparison"] = [
                                    r["comparison"] for r in spec[condition]
                                ]
                        bounds = [b for row in requests.values() for b in row if b is not None]
                        onsets = np.array([
                            r["onset"] for r in dmd_windows["orientation_90"][condition]
                        ])
                        start = min(min(b[0] for b in bounds), onsets.min() - 0.75)
                        stop = max(max(b[1] for b in bounds), onsets.max() + 0.75)
                        left = max(0, int(np.searchsorted(timestamps, start)) - 2)
                        right = min(len(timestamps), int(np.searchsorted(timestamps, stop)) + 2)
                        began = time.monotonic()
                        values = np.asarray(data[left:right])
                        source["slabs"].append({
                            "condition": condition, "frame_slice": [left, right],
                            "requested_bytes": int(values.nbytes),
                            "sha256": hashlib.sha256(values.tobytes()).hexdigest(),
                        })
                        print(
                            f"DMD{dmd}/{signal}/{condition}: {values.nbytes / 1024**2:.1f} MiB "
                            f"read in {time.monotonic() - began:.1f} s", flush=True,
                        )

                        def read_frames(
                            a: int, b: int, offset: int = left, stop: int = right,
                            slab: np.ndarray = values,
                        ) -> np.ndarray:
                            if a < offset or b > stop:
                                raise ValueError("Native statistic request exceeds recorded slab.")
                            return slab[a - offset:b - offset]

                        means, audit = native_window_statistics(
                            timestamps, read_frames, len(ids), requests,
                        )
                        source["slabs"][-1]["native_statistics"] = audit
                        source["slabs"][-1]["collection_stage"] = (
                            "Timestamp-covered candidates, before cross-channel finite screening."
                        )
                        for name in requests:
                            event, key = name.split(":")
                            collected[event][key] = means[name]
                        displayed = display_trials(
                            timestamps[left:right], values[:, eligible], onsets, arrays["time"],
                        )
                        baseline = means[f"orientation_90:{condition}_baseline"][eligible]
                        displayed -= baseline[:, :, None]
                        validity_signals[signal][condition] = {
                            event: finite_native_trials(
                                timestamps[left:right], values, spec[condition], eligible,
                                include_display=event == "orientation_90",
                            ) for event, spec in dmd_windows.items()
                        }
                        trial_arrays[signal][condition][str(dmd)] = displayed
                        del read_frames, values
                    collected_signals[signal] = collected
                    sources.append(source)
                masks = {event: {} for event in dmd_windows}
                for event, spec in dmd_windows.items():
                    for condition in ("context", "control"):
                        mask = np.logical_and.reduce([
                            validity_signals[s][condition][event] for s in SIGNALS
                        ])
                        masks[event][condition] = mask
                        spec["excluded"][condition].extend({
                            "index": row["index"], "reason": "nonfinite_native_signal_coverage",
                        } for row, valid in zip(spec[condition], mask, strict=True) if not valid)
                        spec[condition] = [
                            row for row, valid in zip(spec[condition], mask, strict=True) if valid
                        ]
                        if len(spec[condition]) < 2:
                            raise ValueError(
                                f"DMD{dmd}/{event}/{condition}: no complete trial set."
                            )
                        print(
                            f"DMD{dmd}/{event}/{condition}: {int(mask.sum())}/{len(mask)} "
                            "trials retained after both-channel finite-frame screening", flush=True,
                        )
                for signal, collected in collected_signals.items():
                    for condition in ("context", "control"):
                        trial_arrays[signal][condition][str(dmd)] = (
                            trial_arrays[signal][condition][str(dmd)][
                                :, masks["orientation_90"][condition]
                            ]
                        )
                        if not np.isfinite(trial_arrays[signal][condition][str(dmd)]).all():
                            raise ValueError(
                                f"DMD{dmd}/{signal}: nonfinite retained trial display."
                            )
                    for event, values in collected.items():
                        values = {
                            k: v[:, masks[event][k.split("_")[0]]] for k, v in values.items()
                        }
                        table = signal_statistics(values)
                        table["context_response_mean"] = pd.DataFrame(
                            values["context_test"].T,
                        ).mean().to_numpy()
                        table["control_response_mean"] = pd.DataFrame(
                            values["control_test"].T,
                        ).mean().to_numpy()
                        for column in ("roi_key", "quality_class", "eligible"):
                            table[column] = quality[column].to_numpy()
                        table["roi_id"], table["dmd"] = ids, dmd
                        table["signal"], table["event_id"] = signal, event
                        statistics.append(table)
                        for key in values:
                            arrays[f"native:DMD{dmd}:{signal}:{event}:{key}"] = values[key]
    stats = pd.concat(statistics, ignore_index=True)
    for signal in SIGNALS:
        for event in windows:
            selected = stats.signal.eq(signal) & stats.event_id.eq(event)
            for screen in ("q1", "q2"):
                stats.loc[selected, f"{screen}_q"] = benjamini_hochberg(
                    stats.loc[selected, f"{screen}_p"],
                )
        arrays[f"delta_{signal}"] = np.stack(
            [
                np.concatenate([
                    trial_arrays[signal][c][str(dmd)].mean(axis=1) for dmd in (1, 2)
                ]) for c in ("context", "control")
            ],
        ).astype("<f4")
        for dmd in keys_by_dmd:
            for condition in ("context", "control"):
                arrays[f"trials:{signal}:DMD{dmd}:{condition}"] = (
                    trial_arrays[signal][condition][dmd]
                )
    spans = {}
    for dmd, specs in windows_by_dmd.items():
        spans[dmd] = {}
        for kind in ("response", "comparison"):
            indices = [r["index"] - (kind == "comparison")
                       for r in specs["orientation_90"]["context"]]
            onsets = np.array([r["onset"] for r in specs["orientation_90"]["context"]])
            spans[dmd][kind] = [
                float(np.median(tables["context"][key][indices] - onsets))
                for key in ("start", "stop")
            ]
    if not all(np.allclose(spans["1"][k], spans["2"][k]) for k in spans["1"]):
        raise ValueError("DMD stimulus spans differ; explicitly separate their display guides.")
    stage_dir.mkdir(parents=True)
    stats.to_csv(
        stage_dir / "statistics.csv.gz", index=False,
        compression={"method": "gzip", "mtime": 0},
    )
    np.savez_compressed(stage_dir / "responses.npz", **arrays)
    inputs = [
        Path(__file__), QUALITY, ASSETS,
        *[ROOT / f"src/openscope_p3_publication/{name}.py" for name in (
            "slap2_standard_oddball", "mesoscope_standard_oddball",
            "mesoscope_standard_oddball_cohort", "standard_oddball_cohort",
            "mismatch_responsiveness", "neural_responses",
        )],
    ]
    payload = {
        "version": 1, "session_id": SESSION, "asset": asset,
        "retrieved_at": datetime.now(UTC).isoformat(), "sources": sources,
        "original_roi_keys": original, "roi_keys": keys,
        "roi_keys_by_dmd": keys_by_dmd,
        "trials_by_dmd": {d: w["orientation_90"] for d, w in windows_by_dmd.items()},
        "recorded_trial_counts": {
            d: [len(w["orientation_90"][c]) for c in ("context", "control")]
            for d, w in windows_by_dmd.items()
        },
        "all_event_trials_by_dmd": windows_by_dmd, "protocol_clean_trials": windows,
        "stimulus_spans": spans["1"], "stimulus_spans_by_dmd": spans, "display_hz": 200,
        "recording_coverage": (
            "Each DMD uses its own fully recorded trials; gaps >3 median frame intervals "
            "split acquisition segments. Every statistical window must fit a segment; "
            "90-degree trials also require complete +/-0.75-s display coverage. "
            "Trials require finite eligible-source native frames in both channels, including "
            "the interpolation bracketing frames; stored NaN warm-up frames are not filled."
        ),
        "eligibility": "Frozen archive-wide glutamate High SNR/Intermediate; both DMDs/channels.",
        "statistics": "Native 500-ms Q1/Q2, raw p<0.05 and |MI|>0.1; no amplitude gate.",
        "multiple_testing": "BH across all original sources per event/channel; raw p is primary.",
        "inputs": [{"path": str(p.relative_to(ROOT)), "sha256": sha256(p)} for p in inputs],
        "outputs": [{"path": name, "sha256": sha256(stage_dir / name)}
                    for name in ("statistics.csv.gz", "responses.npz")],
    }
    (stage_dir / "provenance.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    selected = stats.loc[stats.eligible & stats.event_id.eq("orientation_90")]
    print(selected.groupby("signal")[
        ["q1_responsive", "q2_responsive", "joint_responsive", "positive_joint",
         "q2_nonsignificant"]
    ].sum().to_string(), flush=True)
    print(f"Saved complete native stage: {stage_dir}", flush=True)


def finalize_snapshot(stage_dir: Path, *, calcium_positive_only: bool) -> None:
    """Select display examples offline, without discarding or rereading successful native work."""
    from rastermap import Rastermap

    if SNAPSHOT.exists():
        raise FileExistsError(f"Refusing to overwrite frozen snapshot: {SNAPSHOT}")
    payload = json.loads((stage_dir / "provenance.json").read_text())
    for record in payload["inputs"]:
        if sha256(ROOT / record["path"]) != record["sha256"]:
            raise ValueError(f"Native-stage input changed: {record['path']}")
    for record in payload["outputs"]:
        if sha256(stage_dir / record["path"]) != record["sha256"]:
            raise ValueError(f"Native-stage output changed: {record['path']}")
    stats = pd.read_csv(stage_dir / "statistics.csv.gz")
    with np.load(stage_dir / "responses.npz", allow_pickle=False) as archive:
        arrays = {k: archive[k] for k in archive.files if not k.startswith("trials:")}
        keys = payload["roi_keys"]
        positive_only = {"glutamate": True, "calcium": calcium_positive_only}
        examples = {}
        for signal in SIGNALS:
            examples[signal] = select_examples(
                stats, keys, signal, positive_only=positive_only[signal],
            )
            for i, key in enumerate(examples[signal]):
                dmd = key.split(":")[0].removeprefix("DMD")
                for condition in ("context", "control"):
                    arrays[f"examples_{signal}_{condition}_{i}"] = (
                        archive[f"trials:{signal}:DMD{dmd}:{condition}"][
                            payload["roi_keys_by_dmd"][dmd].index(key)
                        ]
                    )
    matrix = arrays["delta_glutamate"][0]
    if not np.isfinite(matrix).all() or np.any(np.ptp(matrix, axis=1) == 0):
        raise ValueError("Glutamate Rastermap requires finite, nonconstant eligible sources.")
    if importlib.metadata.version("rastermap") != RASTERMAP_VERSION:
        raise ValueError("Installed Rastermap version differs from publication parameters.")
    parameters = {
        **RASTERMAP_PARAMETERS, "n_PCs": min(matrix.shape) - 1,
        "n_clusters": min(RASTERMAP_PARAMETERS["n_clusters"], len(matrix) // 2),
    }
    model = Rastermap(**parameters).fit(matrix)
    order = np.asarray(model.isort).astype(int).tolist()
    if sorted(order) != list(range(len(keys))):
        raise ValueError("Rastermap did not produce a full source permutation.")
    payload.update(
        examples=examples, positive_examples_only=positive_only, order=order,
        rastermap={
            "version": RASTERMAP_VERSION, "parameters": parameters,
            "fit_signal": "glutamate", "fit_condition": "context",
            "matrix_sha256": hashlib.sha256(matrix.astype("<f4").tobytes()).hexdigest(),
            "order_sha256": hashlib.sha256(np.asarray(order, dtype="<u4").tobytes()).hexdigest(),
        },
    )
    SNAPSHOT.mkdir(parents=True)
    shutil.copyfile(stage_dir / "statistics.csv.gz", SNAPSHOT / "statistics.csv.gz")
    np.savez_compressed(SNAPSHOT / "responses.npz", **arrays)
    payload["outputs"] = [
        {"path": name, "sha256": sha256(SNAPSHOT / name)}
        for name in ("statistics.csv.gz", "responses.npz")
    ]
    (SNAPSHOT / "provenance.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {len(stats)} statistical rows / {len(keys)} eligible sources.", flush=True)


def main() -> None:
    """Checkpoint native work independently of scientific display-selection decisions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-dir", type=Path, required=True)
    parser.add_argument("--finalize-only", action="store_true")
    parser.add_argument("--native-only", action="store_true")
    parser.add_argument("--calcium-either-sign", action="store_true")
    args = parser.parse_args()
    if args.native_only and args.finalize_only:
        parser.error("--native-only and --finalize-only cannot be combined.")
    if not args.finalize_only:
        extract_native(args.stage_dir)
    if not args.native_only:
        finalize_snapshot(args.stage_dir, calcium_positive_only=not args.calcium_either_sign)


if __name__ == "__main__":
    main()
