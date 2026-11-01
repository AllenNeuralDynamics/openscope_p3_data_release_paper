#!/usr/bin/env python3
"""Freeze a replacement example and actual stimulus spans without changing statistics."""

from __future__ import annotations

import argparse
import hashlib
import json
from contextlib import closing
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

from openscope_p3_publication.mesoscope_standard_oddball import (
    ASSET_ID,
    QUALITY_PATH,
    ROOT,
    SNAPSHOT,
    WINDOW,
    display_trials,
    load_snapshot,
    sha256,
    signal_statistics,
    window_means,
)
from openscope_p3_publication.mesoscope_standard_oddball_display import (
    PANEL_A_DFF_PEAK_THRESHOLD,
    context_dff_peaks,
    select_display_examples,
)


def main() -> None:
    """Read only one replacement ROI per signal and the small native stimulus tables."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=SNAPSHOT)
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Deliberately replace only the two display supplement files after backing them up.",
    )
    args = parser.parse_args()
    paths = [args.output / name for name in ("display-examples.npz", "display-provenance.json")]
    if any(path.exists() for path in paths) and not args.overwrite:
        raise SystemExit("Refusing to overwrite an existing mesoscope display supplement.")
    try:
        import remfile
    except ImportError as exc:
        raise SystemExit("Run with uv run --with remfile python " + str(Path(__file__))) from exc
    payload, statistics, original = load_snapshot()
    previous = payload["example_roi_keys"][0]
    examples = select_display_examples(payload, statistics, original)
    if examples[1] != payload["example_roi_keys"][1]:
        raise ValueError("The requested unchanged comparison ROI was not retained.")
    plane, roi_id = examples[0].split(":")
    quality = pd.read_csv(QUALITY_PATH)
    quality = quality.loc[quality.session.eq("832700_2026-01-30")]
    planes = []
    for source in payload["planes"]:
        q = quality.loc[quality.plane.eq(source["plane"])]
        if q.depth_um.nunique() != 1 or q.structure.nunique() != 1:
            raise ValueError("Plane area/depth metadata must be unique.")
        planes.append({
            "plane": source["plane"], "area": str(q.structure.iloc[0]),
            "depth_um": float(q.depth_um.iloc[0]),
        })
    arrays, trials, sources = {}, {}, {}
    url = f"https://api.dandiarchive.org/api/assets/{ASSET_ID}/download/"
    with closing(remfile.File(url)) as remote, h5py.File(remote, "r") as nwb:
        for condition, name in (
            ("context", "Standard mismatch block_presentations"),
            ("control", "Control block 1_presentations"),
        ):
            table = nwb[f"intervals/{name}"]
            start, stop = table["start_time"][:], table["stop_time"][:]
            records = []
            for row in payload["trials"][condition]:
                index = row["index"]
                if start[index] != row["onset"] or not start[index] < stop[index]:
                    raise ValueError("Frozen trial onset or source stimulus bounds changed.")
                record = {
                    "index": index, "start_time": float(start[index]),
                    "stop_time": float(stop[index]),
                }
                if condition == "context":
                    if start[index - 1] != row["comparison"][0]:
                        raise ValueError("Frozen paired preceding-standard identity changed.")
                    record.update({
                        "comparison_start_time": float(start[index - 1]),
                        "comparison_stop_time": float(stop[index - 1]),
                    })
                records.append(record)
            trials[condition] = records
        module = nwb[f"processing/{plane}"]
        roi_table = module["image_segmentation/roi_table"]
        ids = roi_table["id"][:]
        position = np.flatnonzero(ids == int(roi_id))
        if len(position) != 1:
            raise ValueError("Replacement ROI identity is not unique in the NWB.")
        column = int(position[0])
        onsets = [
            row["onset"] for condition in ("context", "control")
            for row in payload["trials"][condition]
        ]
        first, last = min(onsets) + WINDOW[0] - 1, max(onsets) + WINDOW[1] + 1
        for signal, path in (
            ("dff", "dff_timeseries/dff_timeseries"), ("oasis", "event_timeseries"),
        ):
            group = module[path]
            if not np.array_equal(group["rois"][:], np.arange(len(ids))):
                raise ValueError("Native signal columns are not ROI-table ordered.")
            if nwb[group["rois"].attrs["table"]].name != roi_table.name:
                raise ValueError("Native signal references a different ROI table.")
            timestamps = group["timestamps"][:]
            left = max(0, int(np.searchsorted(timestamps, first)) - 1)
            right = min(len(timestamps), int(np.searchsorted(timestamps, last)) + 1)
            timestamps = timestamps[left:right]
            values = np.asarray(group["data"][left:right, column:column + 1], dtype=np.float32)
            if group["data"].attrs["conversion"] != 1 or group["data"].attrs["offset"] != 0:
                raise ValueError("Unexpected native signal conversion.")
            collected = {}
            for condition in ("context", "control"):
                rows = payload["trials"][condition]
                for kind, suffix in (("response", "test"), ("baseline", "baseline")):
                    collected[f"{condition}_{suffix}"], _ = window_means(
                        timestamps, values, [r[kind] for r in rows],
                    )
                aligned = display_trials(
                    timestamps, values, np.asarray([r["onset"] for r in rows]), original["time"],
                )
                aligned = aligned - collected[f"{condition}_baseline"][:, :, None]
                arrays[f"examples_{signal}_{condition}"] = np.concatenate([
                    aligned, original[f"examples_{signal}_{condition}"][1:],
                ])
            collected["context_comparison"], _ = window_means(
                timestamps, values, [r["comparison"] for r in payload["trials"]["context"]],
            )
            calculated = signal_statistics(collected).iloc[0]
            frozen = statistics.loc[
                statistics.signal.eq(signal) & statistics.roi_key.eq(examples[0])
            ].iloc[0]
            for field in ("q1_p", "q1_mi", "q2_raw_p", "q2_raw_mi", "q2_p", "q2_mi"):
                np.testing.assert_allclose(
                    calculated[field], frozen[field], rtol=1e-12, atol=1e-14, equal_nan=True,
                    err_msg=f"Replacement {signal}/{field} differs from frozen native statistics",
                )
            if not calculated.positive_joint:
                raise ValueError("Replacement failed the shared positive-joint screen.")
            sources[signal] = {
                "path": group["data"].name, "column": column, "frame_slice": [left, right],
                "values_sha256": hashlib.sha256(values.tobytes()).hexdigest(),
                "timestamps_sha256": hashlib.sha256(timestamps.tobytes()).hexdigest(),
                "native_statistics_verified": True,
            }
    if any(not np.isfinite(values).all() for values in arrays.values()):
        raise ValueError("Nonfinite replacement trial display samples.")
    args.output.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(paths[0], **arrays)
    inputs = [Path(__file__).resolve(), SNAPSHOT / "provenance.json", QUALITY_PATH,
              ROOT / "src/openscope_p3_publication/mesoscope_standard_oddball.py",
              ROOT / "src/openscope_p3_publication/mesoscope_standard_oddball_display.py"]
    provenance = {
        "version": 2, "session_id": payload["session_id"], "asset_id": ASSET_ID,
        "asset_sha256": payload["asset"]["digest"]["dandi:sha2-256"],
        "retrieved_date": datetime.now(UTC).date().isoformat(),
        "example_roi_keys": examples, "excluded_responsive_roi": previous,
        "example_rule": (
            "Common maximin signed-MI rule, excluding the original responder and requiring "
            "peak trial-averaged baseline-subtracted context dF/F >0.5 in [0,0.5) s for "
            "the responsive panel A example only. Population classifications are unchanged."
        ),
        "panel_a_dff_peak_threshold": PANEL_A_DFF_PEAK_THRESHOLD,
        "responsive_dff_peak": float(context_dff_peaks(original)[
            payload["roi_keys"].index(examples[0])
        ]),
        "trials": trials, "planes": planes, "native_sources": sources,
        "sources": [{"path": str(p.relative_to(ROOT)), "sha256": sha256(p)} for p in inputs],
        "output": {"path": paths[0].name, "sha256": sha256(paths[0])},
        "software": {name: version(name) for name in ("numpy", "scipy", "h5py", "remfile")},
    }
    paths[1].write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    print(f"Wrote display supplement: {examples}; original statistics unchanged.")


if __name__ == "__main__":
    main()
