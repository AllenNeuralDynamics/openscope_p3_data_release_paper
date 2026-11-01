"""Frozen-source SLAP2 optical responsiveness and independently selected examples."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd

from .mesoscope_standard_oddball import ROOT, sha256, validate_frames
from .neural_responses import RASTERMAP_PARAMETERS, RASTERMAP_VERSION

SESSION = "sub-828408_ses-828408-2025-11-18-14-44-48"
ASSET_ID = "686c579b-eddf-4e7d-b9b2-c633e2d1fb15"
SIGNALS = {"glutamate": "green", "calcium": "red"}
SNAPSHOT = ROOT / "figure_sources/data/slap2-standard-oddball-828408-2025-11-18"
QUALITY = ROOT / "figure_sources/data/slap2-glutamate-qc/slap2_metrics_all_sessions.csv"
ASSETS = ROOT / "figure_sources/media/slap2-glutamate-qc/example.provenance.json"


def source_quality(dmd: int, ids: np.ndarray, path: Path = QUALITY) -> pd.DataFrame:
    """Join every original source exactly; both channels inherit frozen glutamate labels."""
    quality = pd.read_csv(path)
    rows = quality.loc[quality.session.eq(SESSION) & quality.dmd.eq(dmd)].copy()
    if (
        rows.roi.duplicated().any() or len(rows) != len(ids)
        or not np.array_equal(ids, np.arange(len(ids)))
        or set(rows.roi) != set(ids)
        or not rows.layout.eq("dual").all() or not rows.has_calcium.eq(True).all()
    ):
        raise ValueError(f"DMD{dmd}: native source identity/layout and frozen labels differ.")
    rows = rows.set_index("roi").loc[ids].reset_index()
    rows["roi_key"] = [f"DMD{dmd}:{i}" for i in ids]
    rows["eligible"] = rows.quality_class.isin(["High SNR", "Intermediate"])
    return rows


def select_examples(
    statistics: pd.DataFrame, keys: list[str], signal: str, *, positive_only: bool = True,
) -> list[str]:
    """Choose positive Q1/Q2 and active Q2-nonsignificant examples per signal, without a gate."""
    if signal not in SIGNALS:
        raise ValueError(f"Unknown SLAP2 signal: {signal}")
    rows = statistics.loc[
        statistics.signal.eq(signal) & statistics.event_id.eq("orientation_90")
    ].set_index("roi_key").loc[keys]
    positive = rows.positive_joint if positive_only else rows.joint_responsive
    comparison = (
        rows.q2_nonsignificant & rows.q2_mi.abs().lt(0.25)
        & np.isfinite(rows.context_response_mean) & rows.context_response_mean.gt(0)
    )
    if not positive.any() or not comparison.any():
        raise ValueError(
            f"{signal}: no eligible examples; positive={positive.sum()}, "
            f"active Q2-nonsignificant={comparison.sum()}."
        )
    strengths = rows[["q1_mi", "q2_mi"]]
    strength = (strengths if positive_only else strengths.abs()).min(axis=1)
    return [
        str(strength.loc[positive].idxmax()),
        str(rows.loc[comparison, "context_response_mean"].idxmax()),
    ]


def recorded_trial_windows(timestamps: np.ndarray, windows: dict) -> dict:
    """Keep each DMD's fully observed trials, never bridging acquisition interruptions."""
    validate_frames(timestamps, np.empty((len(timestamps), 0)))
    dt = float(np.median(np.diff(timestamps)))
    gaps = np.flatnonzero(np.diff(timestamps) > 3 * dt)
    bands = np.column_stack((
        timestamps[np.r_[0, gaps + 1]] - dt / 2,
        timestamps[np.r_[gaps, len(timestamps) - 1]] + dt / 2,
    ))
    result = deepcopy(windows)
    for event, spec in result.items():
        for condition in ("context", "control"):
            kept = []
            for row in spec[condition]:
                bounds = [row["baseline"], row["response"], row["comparison"]]
                if event == "orientation_90":
                    bounds.append([row["onset"] - 0.75, row["onset"] + 0.75])
                observed = all(
                    np.any((bands[:, 0] <= b[0]) & (bands[:, 1] >= b[1]))
                    for b in bounds if b is not None
                )
                if observed:
                    kept.append(row)
                else:
                    spec["excluded"][condition].append({
                        "index": row["index"], "reason": "native_acquisition_coverage",
                    })
            if len(kept) < 2:
                raise ValueError(f"{event}/{condition}: fewer than two recorded native trials.")
            spec[condition] = kept
    return result


def finite_native_trials(
    timestamps: np.ndarray, values: np.ndarray, rows: list, eligible: np.ndarray,
    *, include_display: bool,
) -> np.ndarray:
    """Identify complete eligible-source coverage, including stored NaN warm-up frames."""
    validate_frames(timestamps, values)
    if eligible.shape != (values.shape[1],) or not eligible.any():
        raise ValueError("Finite-frame screening requires aligned eligible source identities.")
    frame_valid = np.ones(len(values), dtype=bool)
    for index in np.flatnonzero(eligible):
        frame_valid &= np.isfinite(values[:, index])
    missing = np.r_[0, np.cumsum(~frame_valid)]
    result = []
    for row in rows:
        bounds = [row["baseline"], row["response"], row["comparison"]]
        good = True
        for bound in bounds:
            if bound is None:
                continue
            left, right = np.searchsorted(timestamps, bound)
            good &= right > left and missing[right] == missing[left]
        if include_display:
            left, right = np.searchsorted(
                timestamps, [row["onset"] - 0.75, row["onset"] + 0.75],
            )
            left, right = max(0, left - 1), min(len(values), right + 1)
            good &= right > left and missing[right] == missing[left]
        result.append(bool(good))
    return np.asarray(result, dtype=bool)


def load_snapshot(directory: Path = SNAPSHOT) -> tuple[dict, pd.DataFrame, dict]:
    """Validate pinned local inputs, original/eligible identities, fit and display arrays."""
    payload = json.loads((directory / "provenance.json").read_text())
    for record in payload["inputs"]:
        if sha256(ROOT / record["path"]) != record["sha256"]:
            raise ValueError(f"SLAP2 snapshot input changed: {record['path']}")
    for record in payload["outputs"]:
        if sha256(directory / record["path"]) != record["sha256"]:
            raise ValueError(f"SLAP2 snapshot output changed: {record['path']}")
    statistics = pd.read_csv(directory / "statistics.csv.gz")
    with np.load(directory / "responses.npz", allow_pickle=False) as archive:
        arrays = {key: archive[key] for key in archive.files}
    keys, original = payload["roi_keys"], payload["original_roi_keys"]
    expected = pd.MultiIndex.from_product(
        [original, list(SIGNALS), ["orientation_45", "orientation_90", "halt", "omission"]],
        names=["roi_key", "signal", "event_id"],
    )
    observed = pd.MultiIndex.from_frame(statistics[expected.names])
    if (
        payload["version"] != 1
        or payload["session_id"] != SESSION or payload["asset"]["asset_id"] != ASSET_ID
        or len(set(keys)) != len(keys) or not set(keys) <= set(original)
        or observed.has_duplicates or set(observed) != set(expected)
        or sorted(payload["order"]) != list(range(len(keys)))
    ):
        raise ValueError("SLAP2 snapshot source, statistical family or order is inconsistent.")
    time = arrays["time"]
    if time.ndim != 1 or not np.isfinite(time).all() or np.any(np.diff(time) <= 0):
        raise ValueError("SLAP2 display grid must be finite and increasing.")
    for signal in SIGNALS:
        delta = arrays[f"delta_{signal}"]
        if delta.shape != (2, len(keys), len(time)) or not np.isfinite(delta).all():
            raise ValueError(f"{signal}: invalid population display values.")
        rows = statistics.loc[
            statistics.signal.eq(signal) & statistics.event_id.eq("orientation_90")
        ].set_index("roi_key")
        if rows.loc[rows.eligible].index.tolist() != keys:
            raise ValueError(f"{signal}: display and eligible source identities differ.")
        if select_examples(
            statistics, keys, signal, positive_only=payload["positive_examples_only"][signal],
        ) != payload["examples"][signal]:
            raise ValueError(f"{signal}: frozen example selection differs.")
        for condition in ("context", "control"):
            for i, key in enumerate(payload["examples"][signal]):
                dmd = key.split(":")[0].removeprefix("DMD")
                values = arrays[f"examples_{signal}_{condition}_{i}"]
                n = len(payload["trials_by_dmd"][dmd][condition])
                if values.shape != (n, len(time)) or not np.isfinite(values).all():
                    raise ValueError(f"{signal}/{condition}/{key}: invalid trial display values.")
    matrix_hash = hashlib.sha256(
        arrays["delta_glutamate"][0].astype("<f4").tobytes()
    ).hexdigest()
    if matrix_hash != payload["rastermap"]["matrix_sha256"]:
        raise ValueError("Frozen glutamate Rastermap fitting matrix changed.")
    fit = payload["rastermap"]
    parameters = {
        **RASTERMAP_PARAMETERS, "n_PCs": min(arrays["delta_glutamate"][0].shape) - 1,
        "n_clusters": min(RASTERMAP_PARAMETERS["n_clusters"], len(keys) // 2),
    }
    order_hash = hashlib.sha256(np.asarray(payload["order"], dtype="<u4").tobytes()).hexdigest()
    if (
        fit["version"] != RASTERMAP_VERSION or fit["parameters"] != parameters
        or fit["fit_signal"] != "glutamate" or fit["fit_condition"] != "context"
        or fit["order_sha256"] != order_hash
    ):
        raise ValueError("Frozen SLAP2 Rastermap specification/order changed.")
    return payload, statistics, arrays
