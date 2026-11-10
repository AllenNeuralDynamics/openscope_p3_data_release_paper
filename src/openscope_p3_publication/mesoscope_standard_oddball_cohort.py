"""Pinned mesoscope cohort inventory and native-frame, all-event responsiveness inputs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

from .mesoscope_standard_oddball import (
    QUALITY_PATH,
    ROOT,
    sha256,
    trial_windows,
    validate_frames,
    window_means,
)
from .standard_oddball_cohort import EVENTS, event_windows

COHORT_DIR = ROOT / "figure_sources/data/mesoscope-standard-oddball-cohort"
LEDGER = ROOT / "figure_sources/data/experimental-sessions.csv"
RUNNING = ROOT / "figure_sources/data/running-statistics.json"
KEYS = ["asset_id", "plane", "roi_id", "event_id", "signal"]
SIGNALS = ("dff", "oasis")
RESPONSE_SECONDS = 0.5
COHORT_COLUMNS = (
    "session_id", "subject_id", "asset_id", "event_id", "signal", "roi_id",
    "plane", "area", "is_soma", "quality_class", "eligible", "eligibility_reason",
    "q1_testable", "q1_responsive", "q2_testable", "q2_responsive",
    "joint_testable", "joint_responsive", "q2_pre_testable", "q2_pre_responsive",
    "joint_pre_testable", "joint_pre_responsive", "q2_post_testable", "q2_post_responsive",
    "joint_post_testable", "joint_post_responsive",
)


def cohort_inventory() -> pd.DataFrame:
    """Keep every standard ledger row and explicitly distinguish QC and SNR exclusions."""
    ledger = pd.read_csv(LEDGER, dtype=str, keep_default_na=False)
    ledger = ledger.loc[
        ledger.modality.str.lower().eq("mesoscope")
        & ledger.session_stimulus.str.endswith("_STANDARD")
    ]
    if ledger.empty or not ledger.qc.isin(["Pass", "Fail"]).all():
        raise ValueError("Mesoscope standard cohort has empty or unreviewed QC.")
    quality = pd.read_csv(QUALITY_PATH, usecols=["session"])
    available = set(quality.session)
    sources = {}
    for session in json.loads(RUNNING.read_text())["sessions"]:
        if session["modality"] != "mesoscope":
            continue
        key = session["source_session_id"]
        if key in sources:
            raise ValueError(f"Duplicate mesoscope source session: {key}")
        sources[key] = session["source"]
    records = []
    for row in ledger.to_dict("records"):
        key = f"{row['mouse_id']}_{row['date']}"
        included = row["qc"] == "Pass" and key in available
        reason = (
            "session_qc_fail" if row["qc"] != "Pass"
            else "missing_frozen_quality_labels" if key not in available else ""
        )
        source = sources.get(row["source_session_id"])
        if included and source is None:
            raise ValueError(f"{row['source_session_id']}: no pinned source asset.")
        record = {
            "session_id": row["source_session_id"], "subject_id": row["mouse_id"],
            "date": row["date"], "quality_key": key, "protocol": row["session_stimulus"],
            "session_qc": row["qc"], "qc_tags": row["qc_tags"],
            "ledger_source_row": row["source_row"], "included": included,
            "exclusion_reason": reason, "asset_id": "", "asset_path": "", "asset_size": "",
        }
        if source is not None:
            record.update(
                asset_id=source["asset_id"], asset_path=source["path"], asset_size=source["size"],
            )
        records.append(record)
    result = pd.DataFrame(records).sort_values(["subject_id", "date"], kind="stable")
    selected = result.loc[result.included]
    if any(
        selected[column].duplicated().any() for column in ("session_id", "quality_key", "asset_id")
    ):
        raise ValueError("Cohort session, quality or immutable asset identities are ambiguous.")
    return result.reset_index(drop=True)


def optical_event_windows(tables: dict) -> dict:
    """Extend established identities/cleaning to equal 500-ms optical windows for all events."""
    original = event_windows(tables)
    result = {}
    for event_id in EVENTS:
        spec = original[event_id]
        event: dict = {"excluded": {}}
        condition_indices = {
            "context": spec["context_indices"],
            "control": spec["control_indices"],
            "control_pre": spec["control_pre_indices"],
            "control_post": spec["control_post_indices"],
        }
        source_conditions = {
            "context": "context", "control": "control",
            "control_pre": "control", "control_post": "control",
        }
        for condition, indices in condition_indices.items():
            source_condition = source_conditions[condition]
            table = tables[source_condition]
            rows, excluded = [], []
            baseline_by_index = dict(zip(
                spec[f"{source_condition}_indices"],
                spec[f"{source_condition}_baseline"],
                strict=True,
            ))
            comparison_by_index = dict(zip(
                spec["context_indices"], spec["context_comparison"], strict=True,
            ))
            clean_by_index = dict(zip(spec["context_indices"], spec["clean"], strict=True))
            for index in indices:
                start = float(table["start"][index])
                comparison = comparison_by_index[index] if condition == "context" else None
                baseline = baseline_by_index[index]
                reason = None
                if condition == "context" and not clean_by_index[index]:
                    reason = "adjacent_mismatch_or_block_boundary"
                elif condition == "context" and comparison is None:
                    reason = "missing_preceding_standard"
                elif index + 1 < len(table["start"]) and (
                    start + RESPONSE_SECONDS > table["start"][index + 1] + 1e-8
                ):
                    reason = "response_overlaps_next_stimulus"
                elif comparison is not None and comparison[0] + RESPONSE_SECONDS > start + 1e-8:
                    reason = "comparison_overlaps_oddball"
                elif baseline is None:
                    reason = "missing_preceding_grey"
                if reason is not None:
                    excluded.append({"index": int(index), "reason": reason})
                    continue
                rows.append({
                    "index": int(index), "onset": start,
                    "response": [start, start + RESPONSE_SECONDS],
                    "baseline": [float(x) for x in baseline],
                    "comparison": (
                        [float(comparison[0]), float(comparison[0]) + RESPONSE_SECONDS]
                        if comparison is not None else None
                    ),
                })
            if len(rows) < 2:
                raise ValueError(f"{event_id}/{condition}: fewer than two usable optical trials.")
            event[condition], event["excluded"][condition] = rows, excluded
        result[event_id] = event
    reference = trial_windows(tables)
    if any(
        result["orientation_90"][condition] != reference[condition]
        for condition in ("context", "control")
    ):
        raise ValueError("Cohort 90-degree optical windows differ from the existing analysis.")
    return result


def native_window_statistics(
    timestamps: np.ndarray, read_frames: Callable[[int, int], np.ndarray],
    roi_count: int, windows: dict[str, list], *, contiguous: bool = False,
) -> tuple[dict, dict]:
    """Read complete contiguous native slabs and return finite-frame means/count provenance."""
    validate_frames(timestamps, np.empty((len(timestamps), 0)))
    output = {key: np.full((roi_count, len(bounds)), np.nan) for key, bounds in windows.items()}
    counts = {key: np.zeros(values.shape, dtype=np.int32) for key, values in output.items()}
    requests = []
    half_frame = float(np.median(np.diff(timestamps))) / 2
    for key, bounds in windows.items():
        for j, window in enumerate(bounds):
            if window is None:
                continue
            start, stop = window
            if not np.isfinite(window).all() or stop <= start:
                raise ValueError("Native statistic windows must be finite and positive.")
            if start < timestamps[0] - half_frame or stop > timestamps[-1] + half_frame:
                continue
            left, right = np.searchsorted(timestamps, [start, stop], side="left")
            left = max(0, min(int(left) - 1, len(timestamps) - 2))
            right = min(len(timestamps), max(int(right) + 1, left + 2))
            requests.append((left, right, key, j, window))
    requests.sort(key=lambda row: row[:2])
    groups = []
    for left, right, key, j, window in requests:
        if groups and (contiguous or left <= groups[-1][1]):
            groups[-1][1] = max(right, groups[-1][1])
            groups[-1][2].append((key, j, window))
        else:
            groups.append([left, right, [(key, j, window)]])
    digest = hashlib.sha256()
    frames = 0
    for left, right, members in groups:
        values = np.asarray(read_frames(left, right))
        if values.shape != (right - left, roi_count) or values.dtype.kind not in "fi":
            raise ValueError("Native signal slab has an invalid ROI/frame shape or dtype.")
        digest.update(np.asarray([left, right], dtype="<i8").tobytes())
        digest.update(values.tobytes())
        frames += len(values)
        # Coverage was checked against the full recording, not the slab's local median dt.
        local_windows = []
        for _, _, (start, stop) in members:
            start = max(start, timestamps[left])
            stop = min(stop, np.nextafter(timestamps[right - 1], np.inf))
            local_windows.append([start, stop] if stop > start else None)
        means, n = window_means(timestamps[left:right], values, local_windows)
        for column, (key, j, _) in enumerate(members):
            output[key][:, j], counts[key][:, j] = means[:, column], n[:, column]
    return output, {
        "read_strategy": "contiguous" if contiguous else "coalesced_complete_native_slabs",
        "frame_count_read": frames, "frame_slice_count": len(groups),
        "frame_slice_span": [groups[0][0], groups[-1][1]] if groups else None,
        "values_and_slices_sha256": digest.hexdigest(),
        "native_frame_count_range": {
            key: [int(value.min()), int(value.max())] for key, value in counts.items()
        },
    }


def finite_row_means(values: np.ndarray) -> np.ndarray:
    """Retain undefined means without suppressing warnings or inventing zero activity."""
    finite = np.isfinite(values)
    return np.divide(
        np.where(finite, values, 0).sum(axis=1), finite.sum(axis=1),
        out=np.full(len(values), np.nan), where=finite.any(axis=1),
    )


def load_cohort(directory: Path = COHORT_DIR) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Load verified original-ROI classifications without cloud access."""
    provenance = json.loads((directory / "provenance.json").read_text())
    if provenance.get("version") != 1 or tuple(provenance.get("events", [])) != EVENTS:
        raise ValueError("Unsupported mesoscope cohort schema/events.")
    for source in provenance["sources"]:
        if sha256(ROOT / source["path"]) != source["sha256"]:
            raise ValueError(f"Mesoscope cohort source changed: {source['path']}")
    for output in provenance["outputs"]:
        if sha256(directory / output["path"]) != output["sha256"]:
            raise ValueError(f"Mesoscope cohort checksum changed: {output['path']}")
    units = pd.read_csv(
        directory / "units.csv.gz", float_precision="round_trip", dtype={"subject_id": str},
    )
    if units.columns.tolist() != list(COHORT_COLUMNS):
        raise ValueError("Mesoscope cohort unit-summary columns changed.")
    sessions = pd.read_csv(
        directory / "sessions.csv", keep_default_na=False, dtype={"subject_id": str},
    )
    included = sessions.loc[sessions.included]
    if (
        units.duplicated(KEYS).any() or set(units.session_id) != set(included.session_id)
        or set(units.signal) != set(SIGNALS) or set(units.event_id) != set(EVENTS)
        or not units.groupby(["asset_id", "plane", "roi_id"]).size().eq(8).all()
    ):
        raise ValueError("Mesoscope cohort has missing/duplicate ROI, event or signal identities.")
    if (
        not units.joint_testable.eq(units.q1_testable & units.q2_testable).all()
        or not units.joint_responsive.eq(units.q1_responsive & units.q2_responsive).all()
    ):
        raise ValueError("Mesoscope cohort joint classifications changed.")
    for repeat in ("pre", "post"):
        if (
            not units[f"joint_{repeat}_testable"].eq(
                units.q1_testable & units[f"q2_{repeat}_testable"]
            ).all()
            or not units[f"joint_{repeat}_responsive"].eq(
                units.q1_responsive & units[f"q2_{repeat}_responsive"]
            ).all()
        ):
            raise ValueError(f"Mesoscope C1 {repeat} classifications changed.")
    return units, sessions, provenance
