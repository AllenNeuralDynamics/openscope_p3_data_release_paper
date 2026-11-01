"""Stream all four standard-oddball events into a separate explorer-only snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import h5py
import numpy as np
from extract_standard_oddball_explorer_window import (
    checkpoint,
    native_tables,
    onset_rows,
    optical_piece,
    pinned_url,
    presentations,
)

from openscope_p3_publication.mesoscope_standard_oddball import ROOT, sha256
from openscope_p3_publication.mesoscope_standard_oddball import load_snapshot as load_mesoscope
from openscope_p3_publication.mesoscope_standard_oddball_cohort import optical_event_windows
from openscope_p3_publication.neural_responses import NEURAL_SESSIONS
from openscope_p3_publication.slap2_standard_oddball import load_snapshot as load_slap2
from openscope_p3_publication.standard_oddball_baselines import summarize_baseline_bins
from openscope_p3_publication.standard_oddball_cohort import EVENTS
from openscope_p3_publication.standard_oddball_examples import (
    aligned_trial_spikes,
    example_trial_records,
    load_example_spikes,
)
from openscope_p3_publication.standard_oddball_explorer_events import DIRECTORY
from openscope_p3_publication.standard_oddball_explorer_window import (
    WINDOW,
    load_wide_population,
    wide_sdf,
)
from openscope_p3_publication.standard_oddball_neuropixels import load_diagnostic
from openscope_p3_publication.standard_oddball_population import load_population


def statistical_tables(nwb: h5py.File, names: tuple[str, str]) -> dict:
    """Read the same native protocol columns used by the frozen cohort analyses."""
    return {
        condition: {
            key: np.asarray(nwb[f"intervals/{name}/{source}"]).astype(
                "U" if key == "trial_type" else float
            )
            for key, source in (
                ("trial_type", "TrialType"), ("orientation", "Orientation"),
                ("delay", "Delay"), ("block_number", "BlockNumber"),
                ("start", "start_time"), ("stop", "stop_time"),
            )
        }
        for condition, name in zip(("context", "control"), names, strict=True)
    }


def verify_90(modality: str, keys: list[str], arrays: dict, events: dict) -> None:
    """Require identical retained 90-degree trials and agreement with verified displays."""
    previous, reference = load_wide_population(modality, keys)
    index = list(EVENTS).index("orientation_90")
    np.testing.assert_array_equal(arrays["time"], reference["time"])
    np.testing.assert_allclose(
        arrays["delta"][index], reference["delta"], atol=2e-6, rtol=2e-7,
    )
    np.testing.assert_array_equal(arrays["counts"][index], reference["counts"])
    old, new = previous["trials"], events["orientation_90"]["trials"]
    if modality == "neuropixels":
        old, new = {"units": old}, {"units": new}
    for group in old:
        for c in ("context", "control"):
            if [r["index"] for r in old[group][c]] != [r["index"] for r in new[group][c]]:
                raise ValueError(f"{modality}/{group}/{c}: 90-degree retained rows changed.")


def extract_neuropixels(remote_type: type, stage: Path) -> tuple[dict, dict]:
    """Read each checksum-verified spike train once and align all four retained events."""
    diagnostic = load_diagnostic()
    source = load_population(diagnostic, load_example_spikes(diagnostic)["events"][1])
    asset, units = diagnostic.session["asset"], source["units"]
    config = next(s for s in NEURAL_SESSIONS if s.context == "standard")
    names = (config.context_table, config.control_table)
    pieces, trials, excluded = [], {}, {}
    url = pinned_url(asset["assetId"], asset)
    with closing(remote_type(url, _max_cache_size=64 * 1024**2)) as r:
        with h5py.File(r, "r") as nwb:
            native, tables = native_tables(nwb, names), statistical_tables(nwb, names)
            for record in example_trial_records(tables):
                event, rows = record["id"], {}
                excluded[event] = {}
                for c in ("context", "control"):
                    retained = record["conditions"][c]
                    rows[c] = [t for t in retained["trials"] if t["baseline_window"] is not None]
                    excluded[event][c] = [
                        {"index": i, "reason": "adjacent_mismatch_or_block_boundary"}
                        for i in retained["excluded_rows"]
                    ] + [
                        {"index": t["row_index"], "reason": "missing_preceding_grey"}
                        for t in retained["trials"] if t["baseline_window"] is None
                    ]
                    if len(rows[c]) < 2:
                        raise ValueError(f"{event}/{c}: fewer than two baseline-testable trials.")
                    print(
                        f"{event}/{c}: {len(rows[c])} retained, "
                        f"{len(excluded[event][c])} protocol/baseline exclusions", flush=True,
                    )
                trials[event] = onset_rows(native, rows)
            ids, ends = np.asarray(nwb["units/id"]), np.asarray(nwb["units/spike_times_index"])
            for i, unit in enumerate(units):
                path = stage / f"neuropixels-binned-baseline-{unit['id']}.npz"
                if not path.exists():
                    matches = np.flatnonzero(ids == unit["id"])
                    if len(matches) != 1:
                        raise ValueError("Native NWB unit identity is not unique.")
                    row = int(matches[0])
                    spikes = np.asarray(nwb["units/spike_times"][
                        0 if row == 0 else ends[row - 1]:ends[row]
                    ])
                    if hashlib.sha256(spikes.astype("<f8").tobytes()).hexdigest() != (
                        unit["source_spike_array_sha256"]
                    ):
                        raise ValueError("Pinned spike array differs from frozen population.")
                    curves, counts = [], []
                    for event in EVENTS:
                        event_curves, event_counts = [], []
                        for c in ("context", "control"):
                            retained = trials[event][c]
                            time, mean = wide_sdf(
                                spikes, np.array([t["onset"] for t in retained]),
                            )
                            baseline = summarize_baseline_bins(
                                aligned_trial_spikes(spikes, retained), retained,
                            )["mean_hz"]
                            event_curves.append(mean - baseline)
                            event_counts.append(np.full(len(time), len(retained), dtype=np.int32))
                        curves.append(event_curves)
                        counts.append(event_counts)
                    checkpoint(path, time, np.asarray(curves), np.asarray(counts))
                with np.load(path, allow_pickle=False) as piece:
                    pieces.append({k: piece[k] for k in piece.files})
                if (i + 1) % 20 == 0:
                    print(f"Neuropixels {i + 1}/{len(units)} complete", flush=True)
    arrays = {
        "time": pieces[0]["time"], "delta": np.stack([p["delta"] for p in pieces], axis=2),
        "counts": np.stack([p["counts"] for p in pieces], axis=2),
    }
    events = {
        e: {"trials": trials[e], "excluded_trials": excluded[e],
            "presentations": presentations(native, trials[e]["context"])}
        for e in EVENTS
    }
    keys = [str(u["id"]) for u in units]
    verify_90("neuropixels", keys, arrays, events)
    return {"source_ids": keys, "asset": asset, "events": events}, arrays


def extract_optical(modality: str, remote_type: type, stage: Path) -> tuple[dict, dict]:
    """Align native primary-signal slabs using existing event-specific optical trial rules."""
    payload, statistics, original = load_mesoscope() if modality == "mesoscope" else load_slap2()
    mesoscope = modality == "mesoscope"
    asset = payload["asset"]
    identifier = asset["identifier" if mesoscope else "asset_id"]
    names = (
        ("Standard mismatch block_presentations", "Control block 1_presentations")
        if mesoscope else ("standard_oddball", "standard_control")
    )
    groups = [p["plane"] for p in payload["planes"]] if mesoscope else [1, 2]
    dt = payload["planes"][0]["dt_seconds"] if mesoscope else 0.005
    time = (
        np.arange(np.ceil(WINDOW[0] / dt), np.floor(WINDOW[1] / dt) + 1) * dt
        if mesoscope else np.arange(-300, 301) / 200
    )
    pieces, events = [], {e: {"trials": {}, "native_slices": []} for e in EVENTS}
    with closing(remote_type(pinned_url(identifier, asset), _max_cache_size=64 * 1024**2)) as r:
        with h5py.File(r, "r") as nwb:
            native = native_tables(nwb, names)
            protocol = optical_event_windows(statistical_tables(nwb, names)) if mesoscope else None
            for group in groups:
                if mesoscope:
                    series = nwb[f"processing/{group}/dff_timeseries/dff_timeseries"]
                    selected = statistics.loc[
                        statistics.plane.eq(group) & statistics.signal.eq("dff")
                        & statistics.eligible
                    ]
                    ids = np.asarray(nwb[f"processing/{group}/image_segmentation/roi_table/id"])
                    matches = [np.flatnonzero(ids == i) for i in selected.roi_id]
                    if any(len(m) != 1 for m in matches):
                        raise ValueError("Native mesoscope ROI identity is not unique.")
                    columns = np.array([int(m[0]) for m in matches])
                else:
                    series = nwb[f"processing/ophys/Fluorescence_DMD{group}/DMD{group}_dFF_green"]
                    selected = statistics.loc[
                        statistics.dmd.eq(group) & statistics.signal.eq("glutamate")
                        & statistics.event_id.eq("orientation_90") & statistics.eligible
                    ]
                    columns = selected.roi_id.to_numpy(dtype=int)
                times = np.asarray(series["timestamps"])
                group_pieces = []
                for event in EVENTS:
                    retained = (
                        protocol[event] if mesoscope
                        else payload["all_event_trials_by_dmd"][str(group)][event]
                    )
                    trials = onset_rows(native, retained)
                    events[event]["trials"][str(group)] = trials
                    path = stage / f"{modality}-{group}-{event}.npz"
                    record_path = path.with_suffix(".json")
                    if not path.exists():
                        baselines = None if mesoscope else {
                            c: original[
                                f"native:DMD{group}:glutamate:{event}:{c}_baseline"
                            ][columns]
                            for c in ("context", "control")
                        }
                        delta, counts, slices = optical_piece(
                            series, times, columns, trials, time, slap_baselines=baselines,
                        )
                        record_path.write_text(json.dumps(slices, indent=2) + "\n")
                        checkpoint(path, time, delta, counts)
                    events[event]["native_slices"].extend(json.loads(record_path.read_text()))
                    with np.load(path, allow_pickle=False) as piece:
                        group_pieces.append({k: piece[k] for k in piece.files})
                    print(f"{modality} {group} {event} complete", flush=True)
                pieces.append({
                    k: np.stack([p[k] for p in group_pieces]) for k in ("delta", "counts")
                })
    arrays = {
        "time": time,
        **{k: np.concatenate([p[k] for p in pieces], axis=2) for k in ("delta", "counts")},
    }
    for event in EVENTS:
        combined = {
            t["index"]: t for rows in events[event]["trials"].values() for t in rows["context"]
        }
        events[event]["presentations"] = presentations(native, list(combined.values()))
    verify_90(modality, payload["roi_keys"], arrays, events)
    return {"source_ids": payload["roi_keys"], "asset": asset, "events": events}, arrays


def main() -> None:
    """Freeze all modalities only after checkpointed extraction and 90-degree validation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DIRECTORY)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite existing snapshot: {args.output}")
    import remfile

    args.stage.mkdir(parents=True, exist_ok=True)
    sources = [
        Path(__file__).resolve(),
        Path(__file__).with_name("extract_standard_oddball_explorer_window.py"),
        *[ROOT / "src/openscope_p3_publication" / f"{p}.py" for p in (
            "standard_oddball_explorer_events", "standard_oddball_explorer_window",
            "standard_oddball_cohort", "mesoscope_standard_oddball_cohort",
            "standard_oddball_examples", "standard_oddball_baselines",
        )],
        *[ROOT / "figure_sources/data" / p / "provenance.json" for p in (
            "standard-oddball-explorer-window", "mesoscope-standard-oddball-832700-2026-01-30",
            "slap2-standard-oddball-828408-2025-11-18",
        )],
    ]
    metadata = {
        "version": 1, "window": list(WINDOW), "events": list(EVENTS),
        "retrieved_date": datetime.now(UTC).date().isoformat(),
        "alignment": "Native stimulus-table start_time; existing event-specific retained rows.",
        "coverage": "Recorded samples only; no extrapolation or acquisition-gap interpolation.",
        "inputs": [{"path": str(p.relative_to(ROOT)), "sha256": sha256(p)} for p in sources],
        "modalities": {}, "outputs": {},
    }
    all_arrays = {}
    for modality in ("neuropixels", "mesoscope", "slap2"):
        view, arrays = (
            extract_neuropixels(remfile.File, args.stage) if modality == "neuropixels"
            else extract_optical(modality, remfile.File, args.stage)
        )
        for e, event in enumerate(EVENTS):
            view["events"][event]["count_ranges"] = {
                c: [int(arrays["counts"][e, i].min()), int(arrays["counts"][e, i].max())]
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
    print(f"Frozen all four events at {args.output}", flush=True)


if __name__ == "__main__":
    main()
