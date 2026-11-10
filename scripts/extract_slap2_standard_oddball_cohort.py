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
    EVENTS,
    VERIFIED_SESSIONS,
    freeze_inventory,
    quality_rows,
)


def extract_session(stage: Path, session_id: str) -> None:
    """Stream one pinned session and compute statistics from native glutamate windows."""
    import remfile

    if stage.exists():
        raise FileExistsError(f"Refusing to overwrite completed cohort stage: {stage}")
    asset = next(
        r for r in json.loads(ASSETS.read_text())["source_assets"]
        if r["session_id"] == session_id
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
            conditions = ("context", "control", "control_pre", "control_post")
            validities = {c: {} for c in conditions}
            source = {
                "dmd": dmd, "roi_ids": ids.tolist(),
                "timestamps_sha256": hashlib.sha256(timestamps.tobytes()).hexdigest(),
                "median_native_hz": float(1 / np.median(np.diff(timestamps))), "slabs": [],
            }
            for condition in conditions:
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
                        f"{session_id} DMD{dmd}/{channel}/{condition}: "
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
                for condition in conditions:
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
                        raise ValueError(
                            f"{session_id} DMD{dmd}/{event}/{condition}: <2 trials."
                        )
                values = {
                    key: v[:, masks[next(
                        condition for condition in (
                            "context", "control_pre", "control_post", "control",
                        ) if key.startswith(f"{condition}_")
                    )]] for key, v in collected[event].items()
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
                    native_arrays[f"{session_id}:DMD{dmd}:{event}:{key}"] = value
            sources.append(source)
            all_windows[str(dmd)] = windows
    table = pd.concat(stats, ignore_index=True)
    table["session_id"], table["subject_id"], table["asset_id"] = (
        session_id, session_id.split("_ses-", 1)[0].removeprefix("sub-"), asset["asset_id"],
    )
    for event in protocol:
        rows = table.event_id.eq(event)
        for screen in (
            "q1", "q2", "q2_raw", "q2_pre", "q2_pre_raw", "q2_post", "q2_post_raw",
        ):
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


def finalize(stages: dict[str, Path], *, overwrite: bool = False) -> None:
    """Combine verified native checkpoints into the compact source-backed cohort."""
    if (DATA / "provenance.json").exists() and not overwrite:
        raise FileExistsError("Refusing to overwrite frozen cohort statistics.")
    extractions = {}
    frames, native_arrays = [], {}
    for session, stage in stages.items():
        extraction = json.loads((stage / "provenance.json").read_text())
        if extraction["extractor_sha256"] != sha256(Path(__file__)):
            raise ValueError(f"{session}: native checkpoint extractor source changed.")
        for record in extraction["outputs"]:
            if sha256(stage / record["path"]) != record["sha256"]:
                raise ValueError(f"{session}: native checkpoint changed: {record['path']}")
        if extraction["asset"]["session_id"] != session:
            raise ValueError(f"{session}: checkpoint asset identity differs.")
        frames.append(pd.read_csv(stage / "units.csv.gz", float_precision="round_trip"))
        with np.load(stage / "native-inputs.npz", allow_pickle=False) as archive:
            native_arrays.update({k: archive[k] for k in archive.files})
        extractions[session] = extraction
    units = pd.concat(frames, ignore_index=True)
    if set(units.session_id) != set(VERIFIED_SESSIONS):
        raise ValueError("Refreshed SLAP2 cohort does not contain both verified sessions.")
    reference_provenance = json.loads((SNAPSHOT / "provenance.json").read_text())
    for record in reference_provenance["outputs"]:
        if sha256(SNAPSHOT / record["path"]) != record["sha256"]:
            raise ValueError(f"November pooled reference changed: {record['path']}")
    reference = pd.read_csv(
        SNAPSHOT / "statistics.csv.gz", float_precision="round_trip",
    )
    with np.load(SNAPSHOT / "responses.npz", allow_pickle=False) as archive:
        for dmd in (1, 2):
            for event in EVENTS:
                native = {
                    key: archive[f"native:DMD{dmd}:glutamate:{event}:{key}"]
                    for key in (
                        "context_test", "context_baseline", "context_comparison",
                        "control_test", "control_baseline",
                    )
                }
                replay = signal_statistics(native)
                previous = reference.loc[
                    reference.signal.eq("glutamate") & reference.dmd.eq(dmd)
                    & reference.event_id.eq(event)
                ].sort_values("roi_id").set_index("roi_key")
                current = units.loc[
                    units.session_id.eq(VERIFIED_SESSIONS[0]) & units.dmd.eq(dmd)
                    & units.event_id.eq(event)
                ].sort_values("roi_id").set_index("roi_key")
                if (
                    not previous.index.equals(current.index)
                    or len(current) != len(replay)
                ):
                    raise ValueError(f"{event}/DMD{dmd}: November source identities changed.")
                for column in ("q1_p", "q1_mi", "q2_p", "q2_mi"):
                    np.testing.assert_allclose(
                        replay[column].to_numpy(), previous[column].to_numpy(),
                        rtol=2e-12, atol=2e-12, equal_nan=True,
                        err_msg=f"Frozen pooled November values differ at {column}.",
                    )
                    np.testing.assert_allclose(
                        current[column].to_numpy(), replay[column].to_numpy(),
                        rtol=2e-12, atol=2e-12, equal_nan=True,
                        err_msg=f"Refreshed November values differ at {column}.",
                    )
    DATA.mkdir(parents=True, exist_ok=True)
    units.to_csv(DATA / "units.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    np.savez_compressed(DATA / "native-inputs.npz", **native_arrays)
    inputs = [
        Path(__file__), QUALITY, ASSETS, ROOT / "figure_sources/data/experimental-sessions.csv",
        *[ROOT / f"src/openscope_p3_publication/{name}.py" for name in (
            "slap2_standard_oddball_cohort", "slap2_standard_oddball", "mesoscope_standard_oddball",
            "mesoscope_standard_oddball_cohort", "standard_oddball_cohort",
            "mismatch_responsiveness",
        )],
    ]
    provenance = {
        "version": 1,
        "events": list(extractions[VERIFIED_SESSIONS[0]]["protocol_clean_trials"]),
        "sessions": list(VERIFIED_SESSIONS),
        "extractions": extractions, "response_seconds": 0.5,
        "minimum_eligible_sources": 20,
        "uncertainty": "Individual session/mouse points; no bootstrap.",
        "pooled_primary_replay": (
            "The November pooled Q1/Q2 statistics were replayed from checksummed frozen "
            "native trial arrays and match the refreshed source extraction."
        ),
        "statistics": (
            "Pooled and separate pre/post C1 Q2 tests; raw p<0.05 and abs(MI)>0.1, "
            "either sign; each denominator uses eligible jointly testable observations."
        ),
        "inputs": [{"path": str(p.relative_to(ROOT)), "sha256": sha256(p)} for p in inputs],
        "outputs": [{"path": n, "sha256": sha256(DATA / n)} for n in (
            "sessions.csv", "stimulus-audit.json", "units.csv.gz", "native-inputs.npz",
        )],
    }
    (DATA / "provenance.json").write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    print(f"Froze {len(units)} source/event observations in two sessions.", flush=True)


def refresh_cohort_source_hashes() -> None:
    """Revalidate unchanged cohort tables against reviewed source-only edits."""
    path = DATA / "provenance.json"
    provenance = json.loads(path.read_text())
    for record in provenance["outputs"]:
        if sha256(DATA / record["path"]) != record["sha256"]:
            raise ValueError(f"SLAP2 cohort output changed: {record['path']}")
    refreshable = {
        "scripts/extract_slap2_standard_oddball_cohort.py",
        "src/openscope_p3_publication/mesoscope_standard_oddball_cohort.py",
    }
    for source in provenance["inputs"]:
        actual = sha256(ROOT / source["path"])
        if actual != source["sha256"]:
            normalized = source["path"].replace("\\", "/")
            if normalized not in refreshable:
                raise ValueError(f"Unreviewed SLAP2 cohort source changed: {normalized}")
            source.setdefault("frozen_source_sha256", source["sha256"])
            source["sha256"] = actual
    provenance["source_hashes_refreshed_date"] = datetime.now(UTC).date().isoformat()
    path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    print(f"Refreshed {path}; frozen cohort tables were not changed.", flush=True)


def main() -> None:
    """Require deliberate new paths; retain checkpoints for offline finalization."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-dir", type=Path)
    parser.add_argument("--stage-dir", type=Path)
    parser.add_argument("--refresh-source-hashes", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.refresh_source_hashes:
        if args.audit_dir or args.overwrite:
            parser.error("--refresh-source-hashes cannot be combined with extraction options.")
        refresh_cohort_source_hashes()
        return
    if args.stage_dir is None:
        parser.error("--stage-dir is required for extraction.")
    if not DATA.exists():
        if args.audit_dir is None:
            parser.error("--audit-dir is required to freeze the initial inventory.")
        freeze_inventory(args.audit_dir)
    args.stage_dir.mkdir(parents=True, exist_ok=True)
    stages = {
        session: args.stage_dir / session for session in VERIFIED_SESSIONS
    }
    for session, stage in stages.items():
        if not stage.exists():
            extract_session(stage, session)
    finalize(stages, overwrite=args.overwrite)


if __name__ == "__main__":
    main()
