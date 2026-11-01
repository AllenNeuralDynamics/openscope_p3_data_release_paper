#!/usr/bin/env python3
"""Extract resumable, full-precision all-event dF/F/OASIS responsiveness, never full NWBs."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

from openscope_p3_publication.mesoscope_standard_oddball import (
    QUALITY_PATH,
    ROOT,
    SESSION_ID,
    load_snapshot,
    sha256,
    signal_statistics,
)
from openscope_p3_publication.mesoscope_standard_oddball_cohort import (
    COHORT_DIR,
    EVENTS,
    KEYS,
    LEDGER,
    RUNNING,
    SIGNALS,
    cohort_inventory,
    finite_row_means,
    native_window_statistics,
    optical_event_windows,
)
from openscope_p3_publication.mismatch_responsiveness import benjamini_hochberg

API = "https://api.dandiarchive.org/api/assets"
SOURCES = [
    Path(__file__).resolve(), LEDGER, RUNNING, QUALITY_PATH,
    ROOT / "figure_sources/data/mesoscope-unit-extraction.provenance.json",
    *[ROOT / f"src/openscope_p3_publication/{name}.py" for name in (
        "mesoscope_standard_oddball_cohort", "mesoscope_standard_oddball",
        "standard_oddball_cohort", "mismatch_responsiveness",
        "neural_responses", "pupil_responses", "mismatch_adjacency",
    )],
]


def verify_asset(record: dict) -> dict:
    """Resolve and freeze digest metadata for an existing immutable UUID, not latest assets."""
    with urllib.request.urlopen(f"{API}/{record['asset_id']}/", timeout=180) as response:
        detail = json.load(response)
    if detail["path"] != record["asset_path"] or detail["contentSize"] != int(record["asset_size"]):
        raise ValueError(f"{record['session_id']}: pinned path/size changed.")
    digest = detail["digest"]
    return {
        **record, "asset_sha256": digest["dandi:sha2-256"],
        "asset_etag": digest["dandi:dandi-etag"],
    }


def csv_bytes(frame: pd.DataFrame) -> bytes:
    """Write deterministic, round-trippable float64 tables."""
    return gzip.compress(
        frame.to_csv(index=False, float_format="%.17g", lineterminator="\n").encode(),
        compresslevel=9, mtime=0,
    )


def extract_session(record: dict, quality: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Read native statistical slabs only, retaining every original source ROI."""
    import remfile

    tables, blocks, plane_sources = {}, [], []
    with closing(remfile.File(
        f"{API}/{record['asset_id']}/download/", _max_cache_size=64 * 1024**2,
    )) as remote, h5py.File(remote, "r") as nwb:
        subject = nwb["general/subject/subject_id"][()]
        if isinstance(subject, bytes):
            subject = subject.decode()
        if str(subject) != record["subject_id"]:
            raise ValueError(f"{record['session_id']}: NWB subject identity changed.")
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
        trials = optical_event_windows(tables)
        windows = {}
        for event, rows in trials.items():
            for condition in ("context", "control"):
                for name, suffix in (("response", "test"), ("baseline", "baseline")):
                    windows[f"{event}/{condition}_{suffix}"] = [
                        row[name] for row in rows[condition]
                    ]
            windows[f"{event}/context_comparison"] = [
                row["comparison"] for row in rows["context"]
            ]
        session_quality = quality.loc[quality.session.eq(record["quality_key"])]
        planes = [
            name for name, module in nwb["processing"].items()
            if "image_segmentation/roi_table" in module
        ]
        if not planes or not set(session_quality.plane).issubset(planes):
            raise ValueError(f"{record['session_id']}: quality/source plane identities changed.")
        for plane in sorted(planes):
            module = nwb[f"processing/{plane}"]
            roi_table = module["image_segmentation/roi_table"]
            ids = np.asarray(roi_table["id"])
            soma = np.asarray(roi_table["is_soma"])
            if (
                len(set(ids)) != len(ids) or not np.isin(soma, [0, 1]).all()
                or not np.equal(ids, ids.astype(np.int64)).all()
            ):
                raise ValueError(f"{plane}: invalid source ROI identities or soma flags.")
            soma = soma.astype(bool)
            q = session_quality.loc[session_quality.plane.eq(plane)].set_index("roi_index")
            if q.index.has_duplicates or not set(q.index).issubset(ids):
                raise ValueError(f"{plane}: frozen quality/source ROI identities changed.")
            location = nwb[f"general/optophysiology/{plane}/location"][()]
            if isinstance(location, bytes):
                location = location.decode()
            match = re.fullmatch(r"Structure:\s*(\S+)\s+Depth:\s*([\d.]+)", location)
            if match is None:
                raise ValueError(f"{plane}: unsupported source anatomy: {location}")
            area, depth = match.group(1), float(match.group(2))
            if not q.empty and (
                not q.structure.eq(area).all() or not q.depth_um.eq(depth).all()
            ):
                raise ValueError(f"{plane}: frozen and NWB area/depth differ.")
            classes = q.reindex(ids).amp_threshold_quality_class.fillna(
                "Unclassified (no frozen label)"
            ).to_numpy()
            if not np.isin(
                classes, ["High SNR", "Intermediate", "Low SNR", "Unclassified (no frozen label)"],
            ).all():
                raise ValueError(f"{plane}: unknown frozen quality classification.")
            eligible = soma & np.isin(classes, ["High SNR", "Intermediate"])
            reason = [
                ";".join(
                    (["not_soma"] if not s else [])
                    + (["missing_frozen_quality_label"] if c == "Unclassified (no frozen label)"
                       else ["low_snr"] if c == "Low SNR" else [])
                ) or "eligible"
                for s, c in zip(soma, classes, strict=True)
            ]
            plane_info = {
                "plane": plane, "area": area, "depth_um": depth, "roi_count": len(ids),
                "eligible_count": int(eligible.sum()),
                "missing_quality_count": int(np.sum(classes == "Unclassified (no frozen label)")),
                "signals": {},
            }
            for signal, path in (
                ("dff", "dff_timeseries/dff_timeseries"), ("oasis", "event_timeseries"),
            ):
                series = module[path]
                region = np.asarray(series["rois"])
                dataset = series["data"]
                if (
                    nwb[series["rois"].attrs["table"]].name != roi_table.name
                    or sorted(region.tolist()) != list(range(len(ids)))
                    or dataset.shape[1] != len(ids)
                    or dataset.attrs["conversion"] != 1 or dataset.attrs["offset"] != 0
                ):
                    raise ValueError(f"{plane}/{signal}: unsupported ROI region or calibration.")
                column_order = np.argsort(region)
                timestamps = np.asarray(series["timestamps"])
                if dataset.shape[0] != len(timestamps):
                    raise ValueError(f"{plane}/{signal}: data/timestamp shape mismatch.")
                means, info = native_window_statistics(
                    timestamps,
                    lambda left, right, data=dataset, order=column_order: (
                        data[left:right][:, order]
                    ),
                    len(ids), windows,
                )
                info.update({
                    "data_path": dataset.name, "unit": str(dataset.attrs["unit"]),
                    "shape": list(dataset.shape), "dtype": str(dataset.dtype),
                    "timestamps_sha256": hashlib.sha256(timestamps.tobytes()).hexdigest(),
                    "roi_region_sha256": hashlib.sha256(region.tobytes()).hexdigest(),
                })
                plane_info["signals"][signal] = info
                for event in EVENTS:
                    collected = {
                        key.split("/", 1)[1]: values
                        for key, values in means.items() if key.startswith(event + "/")
                    }
                    table = signal_statistics(collected)
                    table["context_response_mean"] = finite_row_means(collected["context_test"])
                    table["control_response_mean"] = finite_row_means(collected["control_test"])
                    table["session_id"], table["subject_id"] = (
                        record["session_id"], record["subject_id"]
                    )
                    table["asset_id"], table["event_id"], table["signal"] = (
                        record["asset_id"], event, signal
                    )
                    table["roi_id"], table["roi_table_index"] = ids, np.arange(len(ids))
                    table["signal_column_index"] = column_order
                    table["roi_key"] = [f"{plane}:{int(roi)}" for roi in ids]
                    table["plane"], table["area"], table["depth_um"] = plane, area, depth
                    table["is_soma"], table["quality_class"] = soma, classes
                    table["eligible"], table["eligibility_reason"] = eligible, reason
                    table["negative_joint"] = (
                        table.joint_responsive & table.q1_mi.lt(-0.1) & table.q2_mi.lt(-0.1)
                    )
                    table["mixed_joint"] = (
                        table.joint_responsive & ~(table.positive_joint | table.negative_joint)
                    )
                    blocks.append(table)
                print(
                    f"{record['quality_key']} {plane}/{signal}: {len(ids)} ROIs, "
                    f"{eligible.sum()} eligible, "
                    f"{info['frame_count_read']}/{len(timestamps)} frames",
                    flush=True,
                )
            plane_sources.append(plane_info)
    frame = pd.concat(blocks, ignore_index=True)
    for indices in frame.groupby(["signal", "event_id"]).groups.values():
        for screen in ("q1", "q2", "q2_raw"):
            frame.loc[indices, f"{screen}_q"] = benjamini_hochberg(
                frame.loc[indices, f"{screen}_p"],
            )
    for indices in frame.groupby("signal").groups.values():
        for screen in ("q1", "q2"):
            frame.loc[indices, f"{screen}_q_across_events"] = benjamini_hochberg(
                frame.loc[indices, f"{screen}_p"],
            )
    return frame, {"session_id": record["session_id"], "asset_id": record["asset_id"],
                   "trials": trials, "planes": plane_sources}


def replay_reference(frame: pd.DataFrame) -> None:
    """Require the original January 30 90-degree statistics and classifications for every ROI."""
    _, original, _ = load_snapshot()
    current = frame.loc[frame.event_id.eq("orientation_90")].set_index(["signal", "roi_key"])
    reference = original.set_index(["signal", "roi_key"])
    # The old display sidecar's auxiliary raw-Q2 q values used per-plane families.
    for signal in SIGNALS:
        rows = reference.index.get_level_values("signal") == signal
        reference.loc[rows, "q2_raw_q"] = benjamini_hochberg(reference.loc[rows, "q2_raw_p"])
    if set(current.index) != set(reference.index):
        raise ValueError("Mesoscope reference ROI/signal coverage changed.")
    current = current.loc[reference.index]
    for column in reference.columns:
        if column in ("signal", "roi_key"):
            continue
        if pd.api.types.is_numeric_dtype(reference[column]) and column not in (
            "is_soma", "eligible", "q1_testable", "q2_testable", "joint_testable",
            "q1_responsive", "q2_responsive", "joint_responsive", "positive_joint",
            "q2_nonsignificant",
        ):
            np.testing.assert_allclose(
                current[column], reference[column], rtol=1e-12, atol=1e-14, equal_nan=True,
                err_msg=f"Reference replay differs at {column}",
            )
        elif not current[column].eq(reference[column]).all():
            raise ValueError(f"Mesoscope reference replay differs at {column}.")
    print("Reference replay passed: all 4,742 ROI/signal 90-degree rows.", flush=True)


def main() -> None:
    """Preflight, validate the reference, checkpoint sessions, then publish the complete cohort."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=COHORT_DIR)
    parser.add_argument("--max-workers", type=int, default=2)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--session-id")
    args = parser.parse_args()
    if args.max_workers < 1:
        parser.error("--max-workers must be positive.")
    if args.output_dir.exists() and not args.session_id and not args.preflight_only:
        parser.error("Refusing to overwrite an existing cohort output directory.")
    inventory = cohort_inventory()
    records = inventory.loc[inventory.included].to_dict("records")
    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        selected = list(pool.map(verify_asset, records))
    for record in selected:
        mask = inventory.session_id.eq(record["session_id"])
        for field in ("asset_sha256", "asset_etag"):
            inventory.loc[mask, field] = record[field]
    inventory = inventory.fillna("")
    print(f"Preflight passed: {len(selected)} immutable standard-session assets.", flush=True)
    if args.preflight_only:
        return
    sources = [{"path": str(path.relative_to(ROOT)), "sha256": sha256(path)} for path in SOURCES]
    signature = hashlib.sha256(json.dumps(
        {"sources": sources, "assets": selected}, sort_keys=True,
    ).encode()).hexdigest()
    quality = pd.read_csv(QUALITY_PATH)
    args.work_dir.mkdir(parents=True, exist_ok=True)

    def run(record):
        stem = args.work_dir / record["asset_id"]
        table_path, info_path = stem.with_suffix(".csv.gz"), stem.with_suffix(".json")
        if table_path.exists() and info_path.exists():
            info = json.loads(info_path.read_text())
            if (
                info.get("signature") == signature
                and info.get("table_sha256") == sha256(table_path)
            ):
                print(f"{record['quality_key']}: verified checkpoint", flush=True)
                return pd.read_csv(
                    table_path, float_precision="round_trip", dtype={"subject_id": str},
                ), info
        frame, info = extract_session(record, quality)
        if record["session_id"] == SESSION_ID:
            replay_reference(frame)
        table_path.write_bytes(csv_bytes(frame))
        info.update(signature=signature, table_sha256=sha256(table_path),
                    retrieved_date=datetime.now(UTC).date().isoformat())
        info_path.write_text(json.dumps(info, indent=2, sort_keys=True) + "\n")
        return frame, info

    reference = next(record for record in selected if record["session_id"] == SESSION_ID)
    if args.session_id:
        matches = [r for r in selected if r["session_id"] == args.session_id]
        if len(matches) != 1:
            parser.error("--session-id must identify an included standard session.")
        frame, _ = run(matches[0])
        if args.session_id == SESSION_ID:
            replay_reference(frame)
        return
    reference_result = run(reference)
    replay_reference(reference_result[0])
    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        results = list(pool.map(run, [r for r in selected if r != reference]))
    results.append(reference_result)
    units = pd.concat([frame for frame, _ in results], ignore_index=True).sort_values(
        KEYS, kind="stable",
    )
    if (
        units.duplicated(KEYS).any() or set(units.session_id) != {r["session_id"] for r in selected}
        or not units.groupby(["asset_id", "plane", "roi_id"]).size().eq(8).all()
    ):
        raise ValueError(
            "Incomplete cohort: every original ROI needs both signals and four events."
        )
    content = csv_bytes(units)
    if len(content) > 50 * 1024**2:
        raise ValueError(f"Derived table exceeds approved 50 MiB: {len(content)} bytes.")
    args.output_dir.mkdir(parents=True)
    table_path, inventory_path = args.output_dir / "units.csv.gz", args.output_dir / "sessions.csv"
    table_path.write_bytes(content)
    inventory.to_csv(inventory_path, index=False, lineterminator="\n")
    provenance = {
        "version": 1, "dandiset": "001768", "dandiset_version": "draft",
        "events": list(EVENTS), "signals": list(SIGNALS), "session_count": len(selected),
        "mouse_count": units.subject_id.nunique(), "row_count": len(units),
        "roi_session_observations": len(units.drop_duplicates(["asset_id", "plane", "roi_id"])),
        "sources": sources, "asset_manifest": selected,
        "sessions": [
            info for _, info in sorted(results, key=lambda result: result[1]["session_id"])
        ],
        "definition": (
            "All original ROIs, four events, native half-open 500-ms optical windows; "
            "paired Wilcoxon zsplit Q1 and baseline-subtracted unpaired Mann-Whitney Q2; "
            "raw p<0.05 and abs(MI)>0.1, either sign; no amplitude or Hz gate. "
            "BH across all original ROIs per session/signal/event, plus across-event alternatives."
        ),
        "outputs": [{"path": p.name, "sha256": sha256(p)} for p in (table_path, inventory_path)],
        "software": {
            name: version(name) for name in ("numpy", "scipy", "pandas", "h5py", "remfile")
        },
        "units_csv_gzip_bytes": len(content), "approved_maximum_bytes": 50 * 1024**2,
    }
    (args.output_dir / "provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
    )
    print(f"Published {len(units)} rows; compressed statistics {len(content) / 1024**2:.2f} MiB.")


if __name__ == "__main__":
    main()
