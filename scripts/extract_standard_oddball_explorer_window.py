"""Stream wider onset-aligned primary-signal displays, without changing static snapshots."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import h5py
import numpy as np

from openscope_p3_publication.mesoscope_standard_oddball import (
    ROOT,
    sha256,
    window_means,
)
from openscope_p3_publication.mesoscope_standard_oddball import (
    load_snapshot as load_mesoscope,
)
from openscope_p3_publication.neural_responses import NEURAL_SESSIONS
from openscope_p3_publication.slap2_standard_oddball import load_snapshot as load_slap2
from openscope_p3_publication.standard_oddball_examples import load_example_spikes
from openscope_p3_publication.standard_oddball_explorer_window import (
    DIRECTORY,
    WINDOW,
    average_recorded,
    verify_central,
    wide_native_trial,
    wide_sdf,
)
from openscope_p3_publication.standard_oddball_neuropixels import load_diagnostic
from openscope_p3_publication.standard_oddball_population import load_population, population_arrays


def native_tables(nwb: h5py.File, names: tuple[str, str]) -> dict:
    """Read actual start/stop times and verify retained row indices before alignment."""
    return {
        condition: {
            k: np.asarray(nwb[f"intervals/{name}/{k}"]) for k in ("start_time", "stop_time")
        }
        for condition, name in zip(("context", "control"), names, strict=True)
    }


def pinned_url(identifier: str, asset: dict) -> str:
    """Verify immutable asset metadata before selecting its direct content URL."""
    with urllib.request.urlopen(
        f"https://api.dandiarchive.org/api/assets/{identifier}/", timeout=60,
    ) as response:
        current = json.load(response)
    if current["path"] != asset["path"] or current["digest"] != asset["digest"]:
        raise ValueError("Pinned NWB asset path or digest changed.")
    return current["contentUrl"][-1]


def onset_rows(tables: dict, trials: dict) -> dict:
    """Use native stimulus start times, retaining all frozen trial identities."""
    result = {}
    for condition in ("context", "control"):
        rows = trials[condition]
        result[condition] = []
        for trial in rows:
            index = trial.get("index", trial.get("row_index"))
            onset = float(tables[condition]["start_time"][index])
            expected = trial.get("onset", trial.get("onset_seconds"))
            if onset != expected:
                raise ValueError("Frozen trial onset differs from native stimulus start_time.")
            result[condition].append({**trial, "index": int(index), "onset": onset})
    return result


def presentations(tables: dict, trials: list[dict]) -> list[dict]:
    """Retain source-backed median neighboring presentation bounds, not invented periods."""
    result = []
    table = tables["context"]
    for offset in range(-2, 3):
        spans = [
            [float(table[k][t["index"] + offset] - t["onset"]) for k in ("start_time", "stop_time")]
            for t in trials if 0 <= t["index"] + offset < len(table["start_time"])
        ]
        if spans:
            result.append({
                "offset": offset, "span": np.median(spans, axis=0).tolist(),
                "label": "Mismatch" if offset == 0 else f"{offset:+d}",
            })
    return result


def checkpoint(
    path: Path, time: np.ndarray, delta: np.ndarray, counts: np.ndarray,
) -> None:
    """Persist completed source groups so a failed remote read does not lose prior work."""
    np.savez_compressed(path, time=time, delta=delta, counts=counts)


def extract_neuropixels(remote_type: type, stage: Path) -> tuple[dict, dict]:
    diagnostic = load_diagnostic()
    original = load_population(diagnostic, load_example_spikes(diagnostic)["events"][1])
    rates, baselines = population_arrays(original)
    asset = diagnostic.session["asset"]
    config = next(s for s in NEURAL_SESSIONS if s.context == "standard")
    pieces = []
    url = pinned_url(asset["assetId"], asset)
    with closing(remote_type(url, _max_cache_size=64 * 1024**2)) as remote:
        with h5py.File(remote, "r") as nwb:
            tables = native_tables(nwb, (config.context_table, config.control_table))
            trials = onset_rows(tables, {
                c: original["event"]["conditions"][c]["trials"] for c in ("context", "control")
            })
            ids, ends = np.asarray(nwb["units/id"]), np.asarray(nwb["units/spike_times_index"])
            for i, unit in enumerate(original["units"]):
                path = stage / f"neuropixels-{unit['id']}.npz"
                if not path.exists():
                    rows = np.flatnonzero(ids == unit["id"])
                    if len(rows) != 1:
                        raise ValueError("Native NWB unit identity is not unique.")
                    row = int(rows[0])
                    spikes = np.asarray(nwb["units/spike_times"][
                        0 if row == 0 else ends[row - 1]:ends[row]
                    ])
                    if hashlib.sha256(spikes.astype("<f8").tobytes()).hexdigest() != (
                        unit["source_spike_array_sha256"]
                    ):
                        raise ValueError("Pinned unit spike array differs from frozen population.")
                    curves, counts = [], []
                    for c, condition in enumerate(("context", "control")):
                        onsets = np.array([t["onset"] for t in trials[condition]])
                        time, mean = wide_sdf(spikes, onsets)
                        curves.append(mean - baselines[c, i])
                        counts.append(np.full(len(time), len(onsets), dtype=np.int32))
                    checkpoint(path, time, np.asarray(curves), np.asarray(counts))
                with np.load(path) as piece:
                    pieces.append({k: piece[k] for k in piece.files})
                if (i + 1) % 20 == 0:
                    print(
                        f"Neuropixels {i + 1}/{len(original['units'])} units complete", flush=True,
                    )
    time = pieces[0]["time"]
    delta = np.stack([p["delta"] for p in pieces], axis=1)
    reference_time = -0.75 + (np.arange(rates.shape[-1]) + 0.5) * 0.005
    verify_central(time, delta, reference_time, rates - baselines[..., None])
    return {
        "source_ids": [str(u["id"]) for u in original["units"]], "asset": asset,
        "trials": trials, "presentations": presentations(tables, trials["context"]),
    }, {"time": time, "delta": delta, "counts": np.stack([p["counts"] for p in pieces], axis=1)}


def optical_piece(
    series: h5py.Group, times: np.ndarray, columns: np.ndarray,
    trials: dict, time: np.ndarray, *, slap_baselines: dict | None = None,
) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    curves, coverage, slices = [], [], []
    if series["data"].attrs["conversion"] != 1 or series["data"].attrs["offset"] != 0:
        raise ValueError("Native optical signal calibration changed.")
    dt = np.median(np.diff(times))
    for condition in ("context", "control"):
        aligned = []
        for number, trial in enumerate(trials[condition]):
            first = max(0, int(np.searchsorted(times, trial["onset"] + WINDOW[0] - 2 * dt)))
            last = min(len(times), int(np.searchsorted(
                times, trial["onset"] + WINDOW[1] + 2 * dt,
            )) + 1)
            values = np.asarray(series["data"][first:last])
            slices.append({
                "condition": condition, "trial_index": trial["index"],
                "frame_slice": [first, last],
                "sha256": hashlib.sha256(values.tobytes()).hexdigest(),
            })
            if slap_baselines is None:
                values = values.astype(np.float32)
                baseline = window_means(
                    times[first:last], values, [trial["baseline"]],
                )[0][columns, 0]
            else:
                baseline = slap_baselines[condition][:, number]
            displayed = wide_native_trial(
                times[first:last], values[:, columns], trial["onset"], time,
            )
            if not np.isfinite(baseline).all():
                raise ValueError("Frozen trial baseline is unavailable in native frames.")
            if slap_baselines is None:
                displayed = displayed - baseline[:, None]
            else:
                displayed -= baseline[:, None]
            aligned.append(displayed)
        mean, counts = average_recorded(np.stack(aligned, axis=1))
        curves.append(mean)
        coverage.append(counts)
    return np.asarray(curves), np.asarray(coverage), slices


def extract_optical(
    modality: str, remote_type: type, stage: Path,
) -> tuple[dict, dict]:
    payload, statistics, original = (load_mesoscope() if modality == "mesoscope" else load_slap2())
    if modality == "mesoscope":
        url = pinned_url(payload["asset"]["identifier"], payload["asset"])
        table_names = ("Standard mismatch block_presentations", "Control block 1_presentations")
        groups = [p["plane"] for p in payload["planes"]]
        dt = payload["planes"][0]["dt_seconds"]
        time = np.arange(np.ceil(WINDOW[0] / dt), np.floor(WINDOW[1] / dt) + 1) * dt
        signal = "dff"
    else:
        url = pinned_url(payload["asset"]["asset_id"], payload["asset"])
        table_names, groups = ("standard_oddball", "standard_control"), [1, 2]
        time, signal = np.arange(-300, 301) / 200, "glutamate"
    pieces, records, trial_records = [], [], {}
    with closing(remote_type(url, _max_cache_size=64 * 1024**2)) as remote:
        with h5py.File(remote, "r") as nwb:
            tables = native_tables(nwb, table_names)
            for group in groups:
                path = stage / f"{modality}-{group}.npz"
                record_path = stage / f"{modality}-{group}.json"
                if modality == "mesoscope":
                    series = nwb[f"processing/{group}/dff_timeseries/dff_timeseries"]
                    selected = statistics.loc[
                        statistics.plane.eq(group) & statistics.signal.eq(signal)
                    ]
                    columns = selected.loc[selected.eligible, "roi_id"].to_numpy(dtype=int)
                    ids = np.asarray(nwb[f"processing/{group}/image_segmentation/roi_table/id"])
                    matches = [np.flatnonzero(ids == i) for i in columns]
                    if any(len(m) != 1 for m in matches):
                        raise ValueError("Native optical ROI identity is not unique.")
                    columns = np.array([int(m[0]) for m in matches])
                    trials = onset_rows(tables, payload["trials"])
                    baselines = None
                else:
                    series = nwb[f"processing/ophys/Fluorescence_DMD{group}/DMD{group}_dFF_green"]
                    selected = statistics.loc[
                        statistics.dmd.eq(group) & statistics.signal.eq(signal)
                        & statistics.event_id.eq("orientation_90")
                    ]
                    columns = selected.loc[selected.eligible, "roi_id"].to_numpy(dtype=int)
                    trials = onset_rows(tables, payload["trials_by_dmd"][str(group)])
                    baselines = {
                        c: original[
                            f"native:DMD{group}:glutamate:orientation_90:{c}_baseline"
                        ][columns]
                        for c in ("context", "control")
                    }
                trial_records[str(group)] = trials
                if not path.exists():
                    times = np.asarray(series["timestamps"])
                    delta, counts, slices = optical_piece(
                        series, times, columns, trials, time, slap_baselines=baselines,
                    )
                    record_path.write_text(json.dumps(slices, indent=2) + "\n")
                    checkpoint(path, time, delta, counts)
                records.extend(json.loads(record_path.read_text()))
                with np.load(path) as piece:
                    pieces.append({k: piece[k] for k in piece.files})
                print(f"{modality} {group} complete", flush=True)
    delta = np.concatenate([p["delta"] for p in pieces], axis=1)
    verify_central(time, delta, original["time"], original[f"delta_{signal}"])
    combined = {
        t["index"]: t for trials in trial_records.values() for t in trials["context"]
    }
    return {
        "source_ids": payload["roi_keys"], "asset": payload["asset"], "trials": trial_records,
        "presentations": presentations(tables, list(combined.values())), "native_slices": records,
    }, {"time": time, "delta": delta,
        "counts": np.concatenate([p["counts"] for p in pieces], axis=1)}


def main() -> None:
    """Freeze a separate wider display snapshot, resuming completed source groups."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DIRECTORY)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite existing explorer snapshot: {args.output}")
    import remfile

    args.stage.mkdir(parents=True, exist_ok=True)
    paths = [
        Path(__file__).resolve(),
        ROOT / "src/openscope_p3_publication/standard_oddball_explorer_window.py",
        ROOT / "figure_sources/data/neuropixels-standard-oddball-90-population.json",
        *[ROOT / "figure_sources/data" / p / "provenance.json" for p in (
            "mesoscope-standard-oddball-832700-2026-01-30",
            "slap2-standard-oddball-828408-2025-11-18",
        )],
    ]
    metadata = {
        "version": 1, "window": list(WINDOW), "event": "orientation_90",
        "retrieved_date": datetime.now(UTC).date().isoformat(),
        "alignment": "Native stimulus-table start_time; unchanged retained trial rows.",
        "coverage": "Recorded samples only; no extrapolation or acquisition-gap interpolation.",
        "modalities": {}, "outputs": {},
        "inputs": [{"path": str(p.relative_to(ROOT)), "sha256": sha256(p)} for p in paths],
    }
    all_arrays = {}
    for modality in ("neuropixels", "mesoscope", "slap2"):
        view, arrays = (
            extract_neuropixels(remfile.File, args.stage) if modality == "neuropixels"
            else extract_optical(modality, remfile.File, args.stage)
        )
        view["count_ranges"] = {
            c: [int(arrays["counts"][i].min()), int(arrays["counts"][i].max())]
            for i, c in enumerate(("context", "control"))
        }
        metadata["modalities"][modality], all_arrays[modality] = view, arrays
    args.output.mkdir(parents=True)
    for modality, arrays in all_arrays.items():
        path = args.output / f"{modality}.npz"
        np.savez_compressed(path, **arrays)
        metadata["outputs"][modality] = sha256(path)
    (args.output / "provenance.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n"
    )
    print(f"Wrote wider display snapshot: {args.output}", flush=True)


if __name__ == "__main__":
    main()
