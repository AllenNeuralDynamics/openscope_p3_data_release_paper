"""Native-frame statistics and frozen inputs for the mesoscope oddball comparison."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .mismatch_responsiveness import benjamini_hochberg
from .standard_oddball_cohort import event_windows, response_statistics

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "figure_sources/data/mesoscope-standard-oddball-832700-2026-01-30"
QUALITY_PATH = ROOT / "figure_sources/data/mesoscope-unit-extraction-roi-metrics.csv.gz"
SESSION_ID = "multiplane-ophys_832700_2026-01-30_09-32-25"
ASSET_ID = "8b7e9f4a-2544-4c47-b1a9-e65cb58e62cd"
ASSET_SHA256 = "b1dbf2a68b126d117df95e0df2d03130cbb3c8f6d5c9578c4b9b49c8c15cf267"
SIGNALS = ("dff", "oasis")
WINDOW = (-0.75, 0.75)
RESPONSE_SECONDS = 0.5


def sha256(path: Path) -> str:
    """Hash a committed input or small derived output."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def trial_windows(tables: dict) -> dict:
    """Select clean 90-degree trials and equal 500-ms test/comparison windows."""
    original = event_windows(tables)["orientation_90"]
    result: dict = {"excluded": {}}
    for condition in ("context", "control"):
        table = tables[condition]
        indices = original[f"{condition}_indices"]
        rows = []
        excluded = []
        for number, index in enumerate(indices):
            start = float(table["start"][index])
            comparison = original["context_comparison"][number] if condition == "context" else None
            clean = condition == "control" or original["clean"][number]
            reason = None
            if not clean:
                reason = "adjacent_mismatch_or_block_boundary"
            elif comparison is None and condition == "context":
                reason = "missing_preceding_standard"
            elif index + 1 < len(table["start"]) and (
                start + RESPONSE_SECONDS > table["start"][index + 1] + 1e-8
            ):
                reason = "response_overlaps_next_stimulus"
            elif comparison is not None and comparison[0] + RESPONSE_SECONDS > start + 1e-8:
                reason = "comparison_overlaps_oddball"
            baseline = original[f"{condition}_baseline"][number]
            if reason is None and baseline is None:
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
            raise ValueError(f"{condition}: fewer than two clean, nonoverlapping trials.")
        result[condition] = rows
        result["excluded"][condition] = excluded
    return result


def validate_frames(timestamps: np.ndarray, values: np.ndarray) -> None:
    """Reject invalid timestamp alignment without replacing missing signal samples."""
    if (
        timestamps.ndim != 1 or len(timestamps) < 2 or values.ndim != 2
        or values.shape[0] != len(timestamps) or not np.isfinite(timestamps).all()
        or np.any(np.diff(timestamps) <= 0)
    ):
        raise ValueError("Native signal frames require finite, increasing aligned timestamps.")


def window_means(
    timestamps: np.ndarray, values: np.ndarray, windows: list,
) -> tuple[np.ndarray, np.ndarray]:
    """Average finite native frames in half-open windows; retain per-ROI sample counts."""
    validate_frames(timestamps, values)
    means = np.full((values.shape[1], len(windows)), np.nan)
    counts = np.zeros(means.shape, dtype=np.int32)
    half_frame = float(np.median(np.diff(timestamps))) / 2
    for j, bounds in enumerate(windows):
        if bounds is None:
            continue
        start, stop = bounds
        if not np.isfinite(bounds).all() or stop <= start:
            raise ValueError("Frame windows must be finite and positive.")
        if start < timestamps[0] - half_frame or stop > timestamps[-1] + half_frame:
            continue
        left, right = np.searchsorted(timestamps, [start, stop], side="left")
        subset = values[left:right]
        valid = np.isfinite(subset)
        count = valid.sum(axis=0)
        counts[:, j] = count
        means[:, j] = np.divide(
            np.where(valid, subset, 0).sum(axis=0, dtype=np.float64), count,
            out=np.full(values.shape[1], np.nan), where=count > 0,
        )
    return means, counts


def display_trials(
    timestamps: np.ndarray, values: np.ndarray, onsets: np.ndarray, time: np.ndarray,
) -> np.ndarray:
    """Linearly align native samples for display only, never extrapolating or testing them."""
    validate_frames(timestamps, values)
    targets = np.asarray(onsets)[:, None] + np.asarray(time)[None, :]
    right = np.searchsorted(timestamps, targets, side="right")
    inside = (targets >= timestamps[0]) & (targets <= timestamps[-1])
    right = np.clip(right, 1, len(timestamps) - 1)
    left = right - 1
    weight = (targets - timestamps[left]) / (timestamps[right] - timestamps[left])
    aligned = values[left] * (1 - weight[..., None]) + values[right] * weight[..., None]
    aligned[~inside] = np.nan
    return aligned.transpose(2, 0, 1).astype(np.float32)


def signal_statistics(collected: dict) -> pd.DataFrame:
    """Reuse the established Wilcoxon/MI and baseline-subtracted Mann-Whitney/MI definitions."""
    statistics = response_statistics(
        collected, [True] * collected["context_test"].shape[1],
    )
    for screen in ("q1", "q2"):
        p = statistics[f"{screen}_p"]
        mi = statistics[f"{screen}_mi"]
        valid = np.isfinite(p) & np.isfinite(mi)
        statistics[f"{screen}_q"] = benjamini_hochberg(p)
        statistics[f"{screen}_testable"] = valid
        statistics[f"{screen}_responsive"] = valid & p.lt(0.05) & mi.abs().gt(0.1)
        statistics[f"{screen}_status"] = np.where(
            ~np.isfinite(p), "insufficient_valid_trials",
            np.where(~np.isfinite(mi), "undefined_mi", "testable"),
        )
    statistics["joint_testable"] = statistics.q1_testable & statistics.q2_testable
    statistics["joint_responsive"] = statistics.q1_responsive & statistics.q2_responsive
    statistics["positive_joint"] = (
        statistics.joint_responsive & statistics.q1_mi.gt(0.1) & statistics.q2_mi.gt(0.1)
    )
    statistics["q2_nonsignificant"] = statistics.q2_testable & statistics.q2_p.ge(0.05)
    return statistics


def matched_examples(statistics: pd.DataFrame, roi_keys: list[str]) -> list[str]:
    """Choose one common positive responder and one active common Q2-nonsignificant ROI."""
    frames = [
        statistics.loc[statistics.signal.eq(signal)].set_index("roi_key").loc[roi_keys]
        for signal in SIGNALS
    ]
    positive = np.logical_and.reduce([frame.positive_joint.to_numpy() for frame in frames])
    nonq2 = np.logical_and.reduce([
        (frame.q2_nonsignificant & frame.q2_mi.abs().lt(0.25)).to_numpy()
        for frame in frames
    ])
    strengths = np.stack([
        np.minimum(frame.q1_mi.to_numpy(), frame.q2_mi.to_numpy()) for frame in frames
    ]).min(axis=0)
    event_frame = frames[1]
    active = event_frame.context_response_mean.to_numpy()
    nonq2 &= np.isfinite(active) & (active > 0)
    if not positive.any() or not nonq2.any():
        raise ValueError(
            f"No suitable matched examples: positive={positive.sum()}, non-Q2={nonq2.sum()}."
        )
    responder = np.flatnonzero(positive)[np.argmax(strengths[positive])]
    comparison = np.flatnonzero(nonq2)[np.argmax(active[nonq2])]
    return [roi_keys[responder], roi_keys[comparison]]


def load_snapshot(directory: Path = SNAPSHOT) -> tuple[dict, pd.DataFrame, dict]:
    """Validate all frozen inputs and identities without remote I/O or fitting."""
    provenance = json.loads((directory / "provenance.json").read_text())
    if (
        provenance.get("version") != 1 or provenance.get("session_id") != SESSION_ID
        or provenance.get("asset", {}).get("identifier") != ASSET_ID
        or provenance["asset"]["digest"]["dandi:sha2-256"] != ASSET_SHA256
    ):
        raise ValueError("Unsupported mesoscope session or source asset.")
    for source in provenance["sources"]:
        if sha256(ROOT / source["path"]) != source["sha256"]:
            raise ValueError(f"Mesoscope extraction source changed: {source['path']}")
    for output in provenance["outputs"]:
        if sha256(directory / output["path"]) != output["sha256"]:
            raise ValueError(f"Mesoscope snapshot checksum changed: {output['path']}")
    statistics = pd.read_csv(directory / "statistics.csv.gz", float_precision="round_trip")
    with np.load(directory / "responses.npz", allow_pickle=False) as archive:
        arrays = {key: archive[key] for key in archive.files}
    keys = provenance["roi_keys"]
    if len(set(keys)) != len(keys) or sorted(provenance["order"]) != list(range(len(keys))):
        raise ValueError("Invalid shared ROI identity or Rastermap permutation.")
    if provenance["example_roi_keys"] != matched_examples(statistics, keys):
        raise ValueError("Matched example selection changed.")
    if hashlib.sha256(arrays["delta_dff"][0].tobytes()).hexdigest() != (
        provenance["rastermap"]["input_sha256"]
    ):
        raise ValueError("Shared dF/F context Rastermap input changed.")
    for signal in SIGNALS:
        rows = statistics.loc[statistics.signal.eq(signal)]
        if rows.roi_key.duplicated().any() or rows.loc[rows.eligible, "roi_key"].tolist() != keys:
            raise ValueError("Signal-specific ROI eligibility or identity changed.")
        shape = (2, len(keys), len(arrays["time"]))
        if arrays[f"delta_{signal}"].shape != shape or not np.isfinite(
            arrays[f"delta_{signal}"]
        ).all():
            raise ValueError(f"Invalid mesoscope {signal} population values.")
        for condition in ("context", "control"):
            expected = (2, len(provenance["trials"][condition]), len(arrays["time"]))
            examples = arrays[f"examples_{signal}_{condition}"]
            if examples.shape != expected or not np.isfinite(examples).all():
                raise ValueError("Example trial dimensions changed.")
    return provenance, statistics, arrays
