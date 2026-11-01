#!/usr/bin/env python3
"""Extract standard-oddball counts/statistics, never SDF atlases or full NWBs."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import gzip
import hashlib
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from importlib.metadata import version
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

from openscope_p3_publication.mismatch_responsiveness import benjamini_hochberg
from openscope_p3_publication.standard_oddball_cohort import (
    COHORT_DIR,
    CONFIG,
    EVENTS,
    KEYS,
    LEDGER,
    MANIFEST,
    METADATA,
    ROOT,
    classify_units,
    cohort_inventory,
    event_windows,
    rates_in_windows,
    response_statistics,
    sha256,
    summarize_units,
    visual_rows,
)
from openscope_p3_publication.units import session_unit_table

API = "https://api.dandiarchive.org/api/assets"
SOURCES = [
    Path(__file__).resolve(), LEDGER, MANIFEST, METADATA,
    *[
        ROOT / f"src/openscope_p3_publication/{name}.py"
        for name in (
            "standard_oddball_cohort", "mismatch_responsiveness", "neural_responses",
            "pupil_responses", "mismatch_adjacency", "units",
        )
    ],
]


def verify_asset(record: dict) -> dict:
    """Verify immutable asset identity before reading any remote data."""
    with urllib.request.urlopen(f"{API}/{record['asset_id']}/", timeout=180) as response:
        detail = json.load(response)
    if (
        detail["path"] != record["asset_path"]
        or detail["contentSize"] != record["asset_size"]
        or detail["digest"]["dandi:sha2-256"] != record["asset_sha256"]
        or detail["digest"]["dandi:dandi-etag"] != record["asset_etag"]
    ):
        raise ValueError(f"{record['session_id']}: pinned source metadata changed.")
    return detail


def csv_bytes(frame: pd.DataFrame) -> bytes:
    """Serialize round-trippable float64 values and deterministic compressed tables."""
    return gzip.compress(
        frame.to_csv(index=False, float_format="%.17g", lineterminator="\n").encode(),
        compresslevel=9, mtime=0,
    )


def extract_session(record: dict, metadata: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Stream a single pinned session, validating metadata and every spike vector."""
    import remfile

    session_id = record["session_id"]
    asset_id = record["asset_id"]
    verify_asset(record)
    reference = metadata.loc[metadata.session_id.eq(session_id)].sort_values("nwb_unit_index")
    if reference.empty or set(reference.asset_id) != {asset_id}:
        raise ValueError(f"{session_id}: unit metadata asset join failed.")
    reference = reference.reset_index(drop=True)
    with closing(remfile.File(f"{API}/{asset_id}/download/")) as remote, h5py.File(remote) as nwb:
        fresh = session_unit_table(nwb)
        if (
            set(fresh.session_id) != {session_id}
            or set(fresh.subject_id) != {record["subject_id"]}
            or len(fresh) != len(reference)
        ):
            raise ValueError(f"{session_id}: source session/subject/unit count changed.")
        for column in ("nwb_unit_index", "unit_id", "probe", "decoder_label", "brain_structure"):
            if not np.array_equal(
                fresh[column].astype("string").fillna(""),
                reference[column].astype("string").fillna(""),
            ):
                raise ValueError(f"{session_id}: metadata join changed at {column}.")
        for column in ("firing_rate", "amplitude_cutoff", "isi_violations_ratio", "presence_ratio"):
            if not np.array_equal(fresh[column], reference[column], equal_nan=True):
                raise ValueError(f"{session_id}: committed metric changed: {column}.")
            fresh[column] = np.asarray(nwb[f"units/{column}"], dtype=float)
        fresh = fresh.rename(columns={"unit_id": "unit_name"})
        fresh["nwb_unit_id"] = np.asarray(nwb["units/id"], dtype=np.int64)
        if fresh.nwb_unit_id.duplicated().any():
            raise ValueError(f"{session_id}: duplicate numeric NWB unit IDs.")
        fresh["ks_unit_id"] = np.asarray(nwb["units/ks_unit_id"], dtype=np.int64)
        fresh["asset_id"] = asset_id
        fresh["brain_area"] = reference.brain_area.to_numpy()
        fresh["brain_division"] = reference.brain_division.to_numpy()
        fresh = fresh[[
            "session_id", "subject_id", "asset_id", "nwb_unit_id", "unit_name",
            "nwb_unit_index", "ks_unit_id", "probe", "decoder_label", "default_qc",
            "brain_structure", "brain_area", "brain_division",
            "ccf_ap_um", "ccf_dv_um", "ccf_ml_um", "firing_rate",
            "amplitude_cutoff", "isi_violations_ratio", "presence_ratio",
        ]]
        tables = {}
        for condition, table_name in (
            ("context", CONFIG.context_table), ("control", CONFIG.control_table),
        ):
            group = nwb[f"intervals/{table_name}"]
            tables[condition] = {
                key: np.asarray(group[source]).astype("U" if key == "trial_type" else float)
                for key, source in (
                    ("trial_type", "TrialType"), ("orientation", "Orientation"),
                    ("delay", "Delay"), ("block_number", "BlockNumber"),
                    ("start", "start_time"), ("stop", "stop_time"),
                )
            }
        windows = event_windows(tables)
        collected = {
            event: {
                key: np.full((len(fresh), len(bounds)), np.nan)
                for key, bounds in spec.items()
                if key.endswith(("_test", "_baseline", "_comparison"))
            }
            for event, spec in windows.items()
        }
        ends = np.asarray(nwb["units/spike_times_index"], dtype=np.int64)
        source = nwb["units/spike_times"]
        if (
            len(ends) != len(fresh) or np.any(np.diff(ends) < 0)
            or ends[-1] != len(source)
        ):
            raise ValueError(f"{session_id}: invalid ragged spike offsets.")
        spike_digest = hashlib.sha256()
        for row, end in enumerate(ends):
            start = 0 if row == 0 else ends[row - 1]
            spikes = np.asarray(source[start:end], dtype=float)
            if not np.isfinite(spikes).all() or np.any(np.diff(spikes) < 0):
                raise ValueError(f"{session_id}: invalid spike vector for NWB row {row}.")
            spike_digest.update(spikes.astype("<f8").tobytes())
            for event, arrays in collected.items():
                for key in arrays:
                    arrays[key][row] = rates_in_windows(spikes, windows[event][key])
            if row % 500 == 0:
                print(f"{session_id}: counted {row}/{len(fresh)} units", flush=True)
        blocks = []
        for event, arrays in collected.items():
            stats = response_statistics(arrays, windows[event]["clean"])
            block = pd.concat([fresh.copy(), stats], axis=1)
            block["event_id"] = event
            blocks.append(block)
        result = pd.concat(blocks, ignore_index=True)
        for prefix in ("q1", "q2"):
            result[f"{prefix}_q_across_events"] = benjamini_hochberg(result[f"{prefix}_p"])
        result = classify_units(result)
        trial_inventory = {
            event: {
                "context_total": len(spec["context_indices"]),
                "context_clean": sum(spec["clean"]),
                "context_excluded_adjacent": len(spec["clean"]) - sum(spec["clean"]),
                "control_total": len(spec["control_indices"]),
                "context_table": CONFIG.context_table, "control_table": CONFIG.control_table,
                "windows": spec,
            }
            for event, spec in windows.items()
        }
        notes = {}
        for name in ("notes", "experiment_description", "data_collection"):
            path = f"general/{name}"
            if path in nwb:
                value = nwb[path][()]
                notes[name] = value.decode() if isinstance(value, bytes) else str(value)
    return result, {
        "session_id": session_id, "asset_id": asset_id,
        "source_spikes_sha256": spike_digest.hexdigest(),
        "spike_digest_definition": "concatenated row-order native float64 spikes, little endian",
        "retrieved_date": dt.datetime.now(dt.UTC).date().isoformat(),
        "trial_inventory": trial_inventory, "source_notes": notes,
        "probe_counts": result.loc[result.event_id.eq(EVENTS[0])].groupby("probe").agg(
            recorded=("eligible", "size"), eligible=("eligible", "sum"),
        ).to_dict("index"),
    }


def replay_reference(frame: pd.DataFrame) -> None:
    """Require agreement with the original all-unit mouse-830794 standard results."""
    from openscope_p3_publication.standard_oddball_neuropixels import (
        joint_example_mask,
        load_diagnostic,
    )

    data = load_diagnostic()
    session = data.session
    expected_keys = pd.DataFrame({
        "event_id": np.repeat(EVENTS, session["unitCount"]),
        "nwb_unit_id": [u["id"] for u in session["units"]] * len(EVENTS),
    })
    joined = expected_keys.merge(
        frame, on=["event_id", "nwb_unit_id"], validate="one_to_one",
    )
    if len(joined) != len(frame) or len(joined) != len(expected_keys):
        raise ValueError("Reference replay has missing/extra units or events.")
    for current, reference in (
        ("q1_p", "q1_p"), ("q1_mi", "q1_modulation"),
        ("q1_baseline_mi", "q1_modulation_baseline_subtracted"),
        ("q2_raw_p", "q2_p"), ("q2_raw_mi", "q2_modulation"),
        ("q2_p", "q2_delta_p"), ("q2_mi", "q2_delta_modulation"),
        ("q1_q", "q1_q"), ("q2_q", "q2_delta_q"),
        ("q1_q_across_events", "q1_q_across_events"),
        ("q2_q_across_events", "q2_delta_q_across_events"),
        ("q1_trials", "q1_trials"), ("context_raw_trials", "q2_trials"),
        ("control_raw_trials", "q2_control_trials"),
    ):
        expected = np.frombuffer(
            base64.b64decode(session["responsiveness"][reference]["base64"]), dtype="<f4",
        )
        np.testing.assert_array_equal(
            joined[current].to_numpy(dtype=np.float32), expected,
            err_msg=f"Reference replay differs at {current}",
        )
    event = frame.loc[frame.event_id.eq("orientation_90") & frame.eligible & visual_rows(frame)]
    if set(event.nwb_unit_id) != {u["id"] for u in data.units}:
        raise ValueError("Replay does not recover the 203 eligible visual units.")
    expected_joint = {
        u["id"] for u, keep in zip(data.units, joint_example_mask(data)[1], strict=True) if keep
    }
    if set(event.loc[event.joint_responsive, "nwb_unit_id"]) != expected_joint:
        raise ValueError("Replay changed the existing per-unit joint response classifications.")
    counts = (
        len(event), int(event.joint_responsive.sum()), int(event.positive_joint.sum()),
        int((event.q2_nonsignificant & event.brain_division.eq("Isocortex")).sum()),
    )
    if counts != (203, 55, 37, 92):
        raise ValueError(f"Reference masks/counts changed: {counts}")
    print(f"Reference replay passed: visual/joint/positive/nonQ2-cortex = {counts}", flush=True)


def main() -> None:
    """Preflight, replay, extract, and publish only a completely verified cohort."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=COHORT_DIR)
    parser.add_argument("--max-workers", type=int, default=2)
    parser.add_argument(
        "--session-id", help="Extract/checkpoint only this session; do not publish.",
    )
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.max_workers < 1:
        parser.error("--max-workers must be positive.")
    if args.output_dir.exists() and not args.overwrite and not args.session_id:
        parser.error("Output exists; inspect it before using --overwrite.")
    inventory = cohort_inventory()
    selected = inventory.loc[inventory.included].to_dict("records")
    sources = [{"path": str(p.relative_to(ROOT)), "sha256": sha256(p)} for p in SOURCES]
    signature = hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()
    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        list(pool.map(verify_asset, selected))
    print(f"Preflight passed: {len(selected)} pinned QC-pass standard sessions.", flush=True)
    if args.preflight_only:
        return
    metadata = pd.read_parquet(METADATA)
    args.work_dir.mkdir(parents=True, exist_ok=True)

    def run(record: dict) -> tuple[pd.DataFrame, dict]:
        stem = args.work_dir / record["asset_id"]
        table_path, info_path = stem.with_suffix(".csv.gz"), stem.with_suffix(".json")
        if table_path.exists() and info_path.exists():
            info = json.loads(info_path.read_text())
            if (
                info["signature"] == signature
                and info["table_sha256"] == sha256(table_path)
                and info["asset_id"] == record["asset_id"]
            ):
                print(f"{record['session_id']}: using verified checkpoint", flush=True)
                return pd.read_csv(table_path, float_precision="round_trip", dtype={
                    "subject_id": str, "unit_name": str,
                }), info
        frame, info = extract_session(record, metadata)
        if record["subject_id"] == "830794":
            replay_reference(frame)
        info["signature"] = signature
        table_path.write_bytes(csv_bytes(frame))
        info["table_sha256"] = sha256(table_path)
        info_path.write_text(json.dumps(info, indent=2, sort_keys=True) + "\n")
        print(f"{record['session_id']}: checkpoint complete", flush=True)
        return frame, info

    reference = next(r for r in selected if r["subject_id"] == "830794")
    if args.session_id:
        matches = [r for r in selected if r["session_id"] == args.session_id]
        if len(matches) != 1:
            parser.error("--session-id must identify a selected QC-pass standard session.")
        run(matches[0])
        return
    reference_frame, reference_info = run(reference)
    replay_reference(reference_frame)
    remaining = [r for r in selected if r != reference]
    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        extracted = list(pool.map(run, remaining))
    extracted.append((reference_frame, reference_info))
    frame = pd.concat([f for f, _ in extracted], ignore_index=True).sort_values(KEYS, kind="stable")
    if (
        frame.duplicated(KEYS).any() or set(frame.session_id) != {r["session_id"] for r in selected}
        or set(frame.event_id) != set(EVENTS)
        or not frame.groupby(["asset_id", "nwb_unit_id"]).size().eq(len(EVENTS)).all()
    ):
        raise ValueError("Cohort keys or complete session/event coverage failed validation.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {"units.csv.gz": csv_bytes(frame)}
    outputs["sessions.csv"] = inventory.to_csv(index=False, lineterminator="\n").encode()
    for level in ("session", "mouse", "area"):
        name = f"{level}-area.csv" if level != "area" else "area.csv"
        outputs[name] = summarize_units(frame, level).to_csv(
            index=False, float_format="%.17g", lineterminator="\n",
        ).encode()
    for name, content in outputs.items():
        (args.output_dir / name).write_bytes(content)
    provenance = {
        "version": 1, "dandiset": "001637", "dandiset_version": "draft",
        "source_identity": "pinned UUID/path/size/SHA256/ETag verified; no full NWB rehash",
        "session_count": len(selected), "mouse_count": frame.subject_id.nunique(),
        "unit_count": len(frame.drop_duplicates(["asset_id", "nwb_unit_id"])),
        "unit_event_rows": len(frame), "events": list(EVENTS), "sources": sources,
        "software": {
            name: version(name) for name in ("numpy", "scipy", "pandas", "h5py", "remfile")
        },
        "classification": "exploratory strict p<0.05 and abs(MI)>0.1; positive joint both MI>0.1",
        "denominator": "eligible QC-pass SUA FR>1 Hz with finite p and MI for relevant tests",
        "bh_families": (
            "all original units per session/event/test; across_events: all units x four events "
            "per session/test; independent of QC or anatomy; Q2 denotes baseline-subtracted test"
        ),
        "spike_count_windows": "start and stop inclusive, matching original Figure 9 extractor",
        "sessions": sorted([info for _, info in extracted], key=lambda i: i["session_id"]),
        "probe_exclusions": [{
            "session_id": "ecephys_820454_2025-11-05_15-21-15", "probe": "ProbeC",
            "reason": "saturation events",
            "source": "session ledger QC tag; probe identity explicitly confirmed by maintainer",
        }],
        "outputs": [
            {"name": name, "sha256": sha256(args.output_dir / name)} for name in sorted(outputs)
        ],
    }
    (args.output_dir / "provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n"
    )
    print(f"Published {len(frame):,} unit/event rows to {args.output_dir}", flush=True)


if __name__ == "__main__":
    main()
