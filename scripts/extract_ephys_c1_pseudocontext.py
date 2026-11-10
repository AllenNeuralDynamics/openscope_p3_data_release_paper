#!/usr/bin/env python3
"""Extract 90-degree post-C1 pseudo-context statistics without changing Figure 9."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

from openscope_p3_publication.ephys_c1_pseudocontext import (
    EVENT,
    pseudo_statistics,
    pseudo_windows,
    summarize_pseudo,
)
from openscope_p3_publication.standard_oddball_cohort import (
    COHORT_DIR,
    CONFIG,
    ROOT,
    cohort_inventory,
    load_cohort,
    rates_in_windows,
    sha256,
)

API = "https://api.dandiarchive.org/api/assets"
OUTPUT = ROOT / "figure_sources/data/ephys-c1-pseudocontext"
SOURCES = [
    Path(__file__).resolve(), COHORT_DIR / "provenance.json",
    *[
        ROOT / f"src/openscope_p3_publication/{name}.py"
        for name in (
            "ephys_c1_pseudocontext", "standard_oddball_cohort",
            "standard_oddball_cohort_figure", "mesoscope_standard_oddball",
            "mismatch_responsiveness", "neural_responses", "pupil_responses",
        )
    ],
]


def csv_bytes(frame: pd.DataFrame) -> bytes:
    """Serialize deterministically with round-trippable float64 values."""
    return gzip.compress(
        frame.to_csv(index=False, float_format="%.17g", lineterminator="\n").encode(),
        compresslevel=9, mtime=0,
    )


def extract_session(record: dict, original: pd.DataFrame, previous: dict) -> tuple:
    """Validate a pinned asset and stream original spike vectors in bounded batches."""
    import remfile

    asset_id, session_id = record["asset_id"], record["session_id"]
    with urllib.request.urlopen(f"{API}/{asset_id}/", timeout=180) as response:
        asset = json.load(response)
    if (
        asset["path"] != record["asset_path"]
        or asset["contentSize"] != record["asset_size"]
        or asset["digest"]["dandi:sha2-256"] != record["asset_sha256"]
        or asset["digest"]["dandi:dandi-etag"] != record["asset_etag"]
    ):
        raise ValueError(f"{session_id}: pinned asset identity changed.")
    units = original.loc[original.asset_id.eq(asset_id)].copy()
    with closing(remfile.File(
        f"{API}/{asset_id}/download/", _max_cache_size=64 * 1024**2,
    )) as remote, h5py.File(remote, "r") as nwb:
        ids = np.asarray(nwb["units/id"], dtype=np.int64)
        if len(set(ids)) != len(ids) or set(ids) != set(units.nwb_unit_id):
            raise ValueError(f"{session_id}: NWB unit identity coverage changed.")
        subject = nwb["general/subject/subject_id"][()]
        if isinstance(subject, bytes):
            subject = subject.decode()
        if str(subject) != record["subject_id"]:
            raise ValueError(f"{session_id}: subject identity changed.")
        units = units.set_index("nwb_unit_id").loc[ids].reset_index()
        tables = {}
        for condition, name in (
            ("context", CONFIG.context_table), ("control", CONFIG.control_table),
        ):
            group = nwb[f"intervals/{name}"]
            tables[condition] = {
                key: np.asarray(group[source]).astype("U" if key == "trial_type" else float)
                for key, source in (
                    ("trial_type", "TrialType"), ("orientation", "Orientation"),
                    ("delay", "Delay"), ("block_number", "BlockNumber"),
                    ("start", "start_time"), ("stop", "stop_time"),
                )
            }
        windows, trial_info = pseudo_windows(tables)
        collected = {
            key: np.full((len(ids), len(bounds)), np.nan) for key, bounds in windows.items()
        }
        ends = np.asarray(nwb["units/spike_times_index"], dtype=np.int64)
        source = nwb["units/spike_times"]
        if (
            len(ends) != len(ids) or np.any(np.diff(ends) < 0)
            or ends[-1] != len(source)
        ):
            raise ValueError(f"{session_id}: invalid ragged spike offsets.")
        digest = hashlib.sha256()
        for first in range(0, len(ids), 128):
            last = min(first + 128, len(ids))
            offset = 0 if first == 0 else int(ends[first - 1])
            slab = np.asarray(source[offset:int(ends[last - 1])], dtype=float)
            digest.update(slab.astype("<f8").tobytes())
            for row in range(first, last):
                left = (0 if row == 0 else int(ends[row - 1])) - offset
                right = int(ends[row]) - offset
                spikes = slab[left:right]
                if not np.isfinite(spikes).all() or np.any(np.diff(spikes) < 0):
                    raise ValueError(f"{session_id}: invalid spikes for NWB unit {ids[row]}.")
                for key, bounds in windows.items():
                    collected[key][row] = rates_in_windows(spikes, bounds)
            print(f"{session_id}: {last}/{len(ids)} unit spike vectors counted", flush=True)
        if digest.hexdigest() != previous["source_spikes_sha256"]:
            raise ValueError(f"{session_id}: native spike hash differs from Figure 9 extraction.")
    statistics = pseudo_statistics(collected)
    # Keep frozen eligibility and identities, not the actual-context response flags.
    identity_columns = [
        "session_id", "subject_id", "asset_id", "nwb_unit_id", "event_id",
        "brain_division", "brain_area", "qc_pass", "decoder_label", "probe_excluded", "eligible",
    ]
    result = pd.concat([units[identity_columns], statistics], axis=1)
    return result, {
        "session_id": session_id, "subject_id": record["subject_id"],
        "asset_id": asset_id, "asset_path": record["asset_path"],
        "asset_size": record["asset_size"], "asset_sha256": record["asset_sha256"],
        "asset_etag": record["asset_etag"],
        "url": f"{API}/{asset_id}/download/",
        "source_spikes_sha256": digest.hexdigest(),
        "matches_original_spikes": True, "retrieved_at": datetime.now(UTC).isoformat(),
        "trials": trial_info, "unit_count": len(result),
    }


def main() -> None:
    """Checkpoint example or cohort analyses, publishing only verified complete outputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    parser.add_argument("--session-id")
    parser.add_argument("--max-workers", type=int, default=2)
    args = parser.parse_args()
    if args.max_workers < 1:
        parser.error("--max-workers must be positive.")
    if args.output_dir.exists():
        parser.error("Output exists; choose a fresh output directory.")
    _, _, original_provenance = load_cohort()
    original = pd.read_csv(
        COHORT_DIR / "units.csv.gz", dtype={"subject_id": str},
    ).query("event_id == @EVENT")
    if original.duplicated(["asset_id", "nwb_unit_id"]).any():
        raise ValueError("Original Figure 9 unit identities are duplicated.")
    inventory = cohort_inventory().query("included")
    if args.session_id:
        inventory = inventory.loc[inventory.session_id.eq(args.session_id)]
        if len(inventory) != 1:
            parser.error("--session-id must identify a selected ephys session.")
    records = inventory.to_dict("records")
    previous = {entry["asset_id"]: entry for entry in original_provenance["sessions"]}
    sources = [{"path": str(path.relative_to(ROOT)), "sha256": sha256(path)} for path in SOURCES]
    signature = hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()
    args.work_dir.mkdir(parents=True, exist_ok=True)

    def run(record: dict) -> tuple:
        table_path = args.work_dir / f"{record['asset_id']}.csv.gz"
        info_path = table_path.with_suffix(".json")
        if table_path.exists() and info_path.exists():
            info = json.loads(info_path.read_text())
            if (
                info["signature"] == signature
                and info["table_sha256"] == sha256(table_path)
                and info["asset_id"] == record["asset_id"]
            ):
                print(f"{record['session_id']}: verified pseudo-context checkpoint", flush=True)
                return pd.read_csv(
                    table_path, float_precision="round_trip", dtype={"subject_id": str},
                ), info
            raise ValueError(f"Stale pseudo-context checkpoint: {info_path}; use a fresh work dir.")
        frame, info = extract_session(record, original, previous[record["asset_id"]])
        content = csv_bytes(frame)
        info.update(signature=signature, table_sha256=hashlib.sha256(content).hexdigest())
        table_path.write_bytes(content)
        info_path.write_text(json.dumps(info, indent=2, sort_keys=True) + "\n")
        return frame, info

    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        results = list(pool.map(run, records))
    units = pd.concat([frame for frame, _ in results], ignore_index=True).sort_values(
        ["asset_id", "nwb_unit_id"], kind="stable",
    )
    if set(units.session_id) != set(inventory.session_id):
        raise ValueError("Pseudo-context cohort session coverage is incomplete.")
    sessions, areas = summarize_pseudo(units)
    outputs = {
        "units.csv.gz": csv_bytes(units),
        "session-regions.csv": sessions.to_csv(index=False, float_format="%.17g").encode(),
        "regions.csv": areas.to_csv(index=False, float_format="%.17g").encode(),
    }
    if any(len(content) >= 10 * 1024**2 for content in outputs.values()):
        raise ValueError("Pseudo-context derived output exceeds the 10 MiB size tier.")
    args.output_dir.mkdir(parents=True)
    for name, content in outputs.items():
        (args.output_dir / name).write_bytes(content)
    provenance = {
        "version": 1, "event": EVENT, "analysis": "post-C1 pseudo-context versus pre-C1",
        "q1": "Post-C1 90-degree single versus immediately preceding within-block C1 stimulus.",
        "q2": "Post-C1 versus pre-C1 matched event; preceding-grey baseline subtracted.",
        "screen": "Raw p<0.05 and abs(MI)>0.1, either sign; Both is intersection.",
        "denominator": "Figure 9 eligible units, jointly Q1/Q2 testable; same regional gates.",
        "interpretation": (
            "Control stimulus-history and pre/post differences; not oddball selectivity."
        ),
        "partial_cohort": bool(args.session_id), "unit_count": len(units),
        "session_count": len(records), "sources": sources,
        "sessions": sorted([info for _, info in results], key=lambda info: info["session_id"]),
        "outputs": [
            {"path": name, "sha256": hashlib.sha256(content).hexdigest()}
            for name, content in sorted(outputs.items())
        ],
        "software": {
            name: version(name) for name in ("numpy", "scipy", "pandas", "h5py", "remfile")
        },
    }
    (args.output_dir / "provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
    )
    print(areas.to_string(index=False), flush=True)
    print(f"Published {len(units)} pseudo-context units to {args.output_dir}", flush=True)


if __name__ == "__main__":
    main()
