"""Checkpoint the verified December glutamate session; reuse November's frozen results."""

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
import pandas as pd

from openscope_p3_publication.mesoscope_standard_oddball import ROOT, sha256, signal_statistics
from openscope_p3_publication.mesoscope_standard_oddball_cohort import (
    native_window_statistics,
    optical_event_windows,
)
from openscope_p3_publication.mismatch_responsiveness import benjamini_hochberg
from openscope_p3_publication.slap2_standard_oddball import (
    ASSETS,
    QUALITY,
    SNAPSHOT,
    finite_native_trials,
    recorded_trial_windows,
)
from openscope_p3_publication.slap2_standard_oddball_cohort import (
    DATA,
    VERIFIED_SESSIONS,
    freeze_inventory,
    november_reference,
    quality_rows,
)


def extract_december(stage: Path) -> None:
    """Stream both channels for coverage but compute statistics only for native glutamate."""
    import remfile

    if stage.exists():
        raise FileExistsError(f"Refusing to overwrite completed cohort stage: {stage}")
    asset = next(
        r for r in json.loads(ASSETS.read_text())["source_assets"]
        if r["session_id"] == VERIFIED_SESSIONS[1]
    )
    with urllib.request.urlopen(
        f"https://api.dandiarchive.org/api/assets/{asset['asset_id']}/", timeout=60,
    ) as response:
        actual = json.load(response)
    if any(actual[k] != asset[v] for k, v in (
        ("path", "path"), ("contentSize", "size"), ("digest", "digest"),
    )):
        raise ValueError("December pinned asset metadata changed.")
    stats, sources, all_windows, native_arrays = [], [], {}, {}
    with closing(remfile.File(
        asset["content_url"][-1], _max_cache_size=64 * 1024**2,
    )) as remote, h5py.File(remote, "r") as nwb:
        tables = {}
        for condition, name in (("context", "standard_oddball"), ("control", "standard_control")):
            group = nwb[f"intervals/{name}"]
            tables[condition] = {
                k: np.asarray(group[v]).astype(str if k == "trial_type" else float)
                for k, v in (
                    ("trial_type", "TrialType"), ("orientation", "Orientation"),
                    ("delay", "Delay"), ("block_number", "BlockNumber"),
                    ("start", "start_time"), ("stop", "stop_time"),
                )
            }
        protocol = optical_event_windows(tables)
        for dmd in (1, 2):
            group = nwb[f"processing/ophys/Fluorescence_DMD{dmd}"]
            green = group[f"DMD{dmd}_dFF_green"]
            timestamps = np.asarray(green["timestamps"])
            region = np.asarray(green["rois"])
            native_table = nwb[green["rois"].attrs["table"]]
            ids = np.asarray(native_table["id"])[region]
            quality = quality_rows(asset["session_id"], dmd, ids)
            eligible = quality.eligible.to_numpy()
            windows = recorded_trial_windows(timestamps, protocol)
            collected = {e: {} for e in windows}
            validities = {c: {} for c in ("context", "control")}
            source = {
                "dmd": dmd, "roi_ids": ids.tolist(),
                "timestamps_sha256": hashlib.sha256(timestamps.tobytes()).hexdigest(),
                "median_native_hz": float(1 / np.median(np.diff(timestamps))), "slabs": [],
            }
            for condition in ("context", "control"):
                requests = {}
                for event, spec in windows.items():
                    for field, suffix in (("response", "test"), ("baseline", "baseline")):
                        requests[f"{event}:{condition}_{suffix}"] = [
                            r[field] for r in spec[condition]
                        ]
                    if condition == "context":
                        requests[f"{event}:context_comparison"] = [
                            r["comparison"] for r in spec[condition]
                        ]
                bounds = [b for rows in requests.values() for b in rows if b is not None]
                onsets = [r["onset"] for r in windows["orientation_90"][condition]]
                start = min(min(b[0] for b in bounds), min(onsets) - 0.75)
                stop = max(max(b[1] for b in bounds), max(onsets) + 0.75)
                left = max(0, int(np.searchsorted(timestamps, start)) - 2)
                right = min(len(timestamps), int(np.searchsorted(timestamps, stop)) + 2)
                for channel in ("green", "red"):
                    series = group[f"DMD{dmd}_dFF_{channel}"]
                    data = series["data"]
                    if (
                        not np.array_equal(series["timestamps"][:], timestamps)
                        or not np.array_equal(series["rois"][:], region)
                        or nwb[series["rois"].attrs["table"]].name != native_table.name
                        or data.shape != (len(timestamps), len(ids))
                        or data.attrs["conversion"] != 1 or data.attrs["offset"] != 0
                    ):
                        raise ValueError(f"DMD{dmd}/{channel}: alignment/calibration differs.")
                    values = np.asarray(data[left:right])
                    unit = data.attrs["unit"]
                    unit = unit.decode() if isinstance(unit, bytes) else str(unit)
                    record = {
                        "channel": channel, "path": data.name, "shape": list(data.shape),
                        "dtype": str(data.dtype), "unit": unit, "conversion": 1, "offset": 0,
                        "condition": condition, "frame_slice": [left, right],
                        "sha256": hashlib.sha256(values.tobytes()).hexdigest(),
                    }
                    print(
                        f"December DMD{dmd}/{channel}/{condition}: "
                        f"{values.nbytes / 1024**2:.1f} MiB", flush=True,
                    )
                    validities[condition][channel] = {
                        e: finite_native_trials(
                            timestamps[left:right], values, spec[condition], eligible,
                            include_display=e == "orientation_90",
                        ) for e, spec in windows.items()
                    }
                    if channel == "green":
                        def read_frames(
                            a: int, b: int, offset: int = left, end: int = right,
                            slab: np.ndarray = values,
                        ) -> np.ndarray:
                            if a < offset or b > end:
                                raise ValueError("Requested native frames exceed recorded slab.")
                            return slab[a - offset:b - offset]

                        means, audit = native_window_statistics(
                            timestamps, read_frames, len(ids), requests,
                        )
                        record["native_statistics_candidates"] = audit
                        for name, value in means.items():
                            event, key = name.split(":")
                            collected[event][key] = value
                        del read_frames
                    source["slabs"].append(record)
                    del values
            for event, spec in windows.items():
                masks = {}
                for condition in ("context", "control"):
                    mask = (
                        validities[condition]["green"][event] & validities[condition]["red"][event]
                    )
                    masks[condition] = mask
                    spec["excluded"][condition].extend(
                        {"index": r["index"], "reason": "nonfinite_native_signal_coverage"}
                        for r, valid in zip(spec[condition], mask, strict=True) if not valid
                    )
                    spec[condition] = [
                        r for r, valid in zip(spec[condition], mask, strict=True) if valid
                    ]
                    if len(spec[condition]) < 2:
                        raise ValueError(f"December DMD{dmd}/{event}/{condition}: <2 trials.")
                values = {
                    key: v[:, masks[key.split("_")[0]]] for key, v in collected[event].items()
                }
                frame = signal_statistics(values)
                for column in ("roi_key", "quality_class", "eligible"):
                    frame[column] = quality[column].to_numpy()
                for condition in ("context", "control"):
                    frame[f"{condition}_response_mean"] = pd.DataFrame(
                        values[f"{condition}_test"].T,
                    ).mean().to_numpy()
                frame["roi_id"], frame["dmd"] = ids, dmd
                frame["event_id"], frame["signal"] = event, "glutamate"
                stats.append(frame)
                for key, value in values.items():
                    native_arrays[f"DMD{dmd}:{event}:{key}"] = value
            sources.append(source)
            all_windows[str(dmd)] = windows
    table = pd.concat(stats, ignore_index=True)
    table["session_id"], table["subject_id"], table["asset_id"] = (
        asset["session_id"], "829704", asset["asset_id"],
    )
    for event in protocol:
        rows = table.event_id.eq(event)
        for screen in ("q1", "q2", "q2_raw"):
            table.loc[rows, f"{screen}_q"] = benjamini_hochberg(table.loc[rows, f"{screen}_p"])
    stage.mkdir(parents=True)
    table.to_csv(stage / "units.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    np.savez_compressed(stage / "native-inputs.npz", **native_arrays)
    provenance = {
        "asset": asset, "retrieved_at": datetime.now(UTC).isoformat(),
        "protocol_clean_trials": protocol, "retained_trials_by_dmd": all_windows,
        "sources": sources,
        "extractor_sha256": sha256(Path(__file__)),
        "outputs": [{"path": n, "sha256": sha256(stage / n)}
                    for n in ("units.csv.gz", "native-inputs.npz")],
    }
    (stage / "provenance.json").write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")


def finalize(stage: Path) -> None:
    """Combine a verified native checkpoint with the source-replayed November snapshot."""
    if (DATA / "provenance.json").exists():
        raise FileExistsError("Refusing to overwrite frozen cohort statistics.")
    december = json.loads((stage / "provenance.json").read_text())
    if december["extractor_sha256"] != sha256(Path(__file__)):
        raise ValueError("December checkpoint extractor source changed.")
    for record in december["outputs"]:
        if sha256(stage / record["path"]) != record["sha256"]:
            raise ValueError("December native checkpoint changed.")
    november, reference = november_reference()
    units = pd.concat([november, pd.read_csv(stage / "units.csv.gz")], ignore_index=True)
    units.to_csv(DATA / "units.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    with np.load(stage / "native-inputs.npz", allow_pickle=False) as archive:
        np.savez_compressed(
            DATA / "december-native-inputs.npz", **{k: archive[k] for k in archive.files},
        )
    inputs = [
        Path(__file__), QUALITY, ASSETS, ROOT / "figure_sources/data/experimental-sessions.csv",
        *[ROOT / f"src/openscope_p3_publication/{name}.py" for name in (
            "slap2_standard_oddball_cohort", "slap2_standard_oddball", "mesoscope_standard_oddball",
            "mesoscope_standard_oddball_cohort", "standard_oddball_cohort",
            "mismatch_responsiveness",
        )],
        *[SNAPSHOT / n for n in ("provenance.json", "statistics.csv.gz", "responses.npz")],
    ]
    provenance = {
        "version": 1, "events": list(reference["all_event_trials_by_dmd"]["1"]),
        "sessions": list(VERIFIED_SESSIONS), "december": december,
        "november_reference": "Unchanged frozen glutamate rows; primary native replay verified.",
        "coverage_rule": reference["recording_coverage"], "response_seconds": 0.5,
        "minimum_eligible_sources": 20,
        "uncertainty": "Individual session/mouse points; no bootstrap.",
        "statistics": (
            "Raw p<0.05 and abs(MI)>0.1, either sign; denominator eligible joint-testable."
        ),
        "inputs": [{"path": str(p.relative_to(ROOT)), "sha256": sha256(p)} for p in inputs],
        "outputs": [{"path": n, "sha256": sha256(DATA / n)} for n in (
            "sessions.csv", "stimulus-audit.json", "units.csv.gz", "december-native-inputs.npz",
        )],
    }
    (DATA / "provenance.json").write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    print(f"Froze {len(units)} source/event observations in two sessions.", flush=True)


def main() -> None:
    """Require deliberate new paths; retain checkpoints for offline finalization."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-dir", type=Path)
    parser.add_argument("--stage-dir", type=Path, required=True)
    args = parser.parse_args()
    if not DATA.exists():
        if args.audit_dir is None:
            parser.error("--audit-dir is required to freeze the initial inventory.")
        freeze_inventory(args.audit_dir)
    if not args.stage_dir.exists():
        extract_december(args.stage_dir)
    finalize(args.stage_dir)


if __name__ == "__main__":
    main()
