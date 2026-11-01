"""Clean-trial population intermediate for the compact 90-degree visual column."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np

from .neural_responses import BASELINE_BIN_SECONDS
from .standard_oddball_examples import SOURCE_START, WINDOW, trial_mean_sdf
from .standard_oddball_neuropixels import DATA_PATH, REPO_ROOT, Diagnostic

EVENT_ID = "orientation_90"
BIN_SECONDS = 0.005
TAU_SECONDS = 0.025
POPULATION_PATH = DATA_PATH.with_name("neuropixels-standard-oddball-90-population.json")
POPULATION_PROVENANCE = POPULATION_PATH.with_suffix(".provenance.json")
POPULATION_RULE = (
    "all Figure 9 visual cortex/thalamus QC-passing SUA with firingRateHz > 1; "
    "90-degree event; clean context and all matched controls; no responsiveness filter"
)
PARAMETERS = {
    "bin_seconds": BIN_SECONDS, "tau_seconds": TAU_SECONDS, "support_tau": 10,
    "display_window_seconds": list(WINDOW),
    "source_window_seconds": [SOURCE_START, WINDOW[1]],
    "baseline_bin_seconds": BASELINE_BIN_SECONDS,
    "baseline_rule": "released full 20 ms bins within each trial's preceding grey interval",
}


def summarize_spike_trials(spike_trials: list[list[float]], trials: list[dict]) -> dict:
    """Compute a causal mean and released-bin baseline from identical clean trials."""
    if len(spike_trials) != len(trials) or not trials:
        raise ValueError("Population spike/trial alignment is inconsistent or empty.")
    mean = trial_mean_sdf(spike_trials, bin_seconds=BIN_SECONDS, tau_seconds=TAU_SECONDS)
    total_spikes = 0
    total_bins = 0
    for spikes, trial in zip(spike_trials, trials, strict=True):
        window = trial["baseline_window"]
        if (
            window is None or len(window) != 2 or not np.all(np.isfinite(window))
            or window[1] <= window[0] or window[0] < SOURCE_START or window[1] > WINDOW[1]
        ):
            raise ValueError("Population trial has an invalid or unavailable baseline window.")
        start, stop = window
        bins = math.floor((stop - start) / BASELINE_BIN_SECONDS)
        if bins < 1:
            raise ValueError("Population trial has no complete released baseline bins.")
        end = start + bins * BASELINE_BIN_SECONDS
        first, last = np.searchsorted(spikes, [start, end], side="left")
        total_spikes += int(last - first)
        total_bins += bins
    return {
        "mean_hz": mean.tolist(),
        "baseline_mean_hz": total_spikes / (total_bins * BASELINE_BIN_SECONDS),
    }


def population_arrays(payload: dict) -> tuple[np.ndarray, np.ndarray]:
    """Return condition-by-unit mean SDFs and their matching baseline means."""
    rates = np.asarray([
        [unit["conditions"][condition]["mean_hz"] for unit in payload["units"]]
        for condition in ("context", "control")
    ], dtype=float)
    baselines = np.asarray([
        [unit["conditions"][condition]["baseline_mean_hz"] for unit in payload["units"]]
        for condition in ("context", "control")
    ], dtype=float)
    return rates, baselines


def validate_population(payload: dict, data: Diagnostic, reference_event: dict) -> None:
    """Reject changed eligibility, trial identity, smoothing, or unavailable values."""
    if (
        payload.get("version") != 1
        or payload.get("session_id") != data.session["sessionId"]
        or payload.get("asset") != data.session["asset"]
        or payload.get("selection_rule") != POPULATION_RULE
        or payload.get("parameters") != PARAMETERS
        or payload.get("event") != reference_event
        or reference_event["id"] != EVENT_ID
        or [u["id"] for u in payload.get("units", [])] != [u["id"] for u in data.units]
    ):
        raise ValueError("Clean population identity, eligibility, parameters, or trials changed.")
    for unit in payload["units"]:
        if (
            set(unit["conditions"]) != {"context", "control"}
            or re.fullmatch(r"[0-9a-f]{64}", unit["source_spike_array_sha256"]) is None
        ):
            raise ValueError("Population condition coverage or source spike digest is invalid.")
    rates, baselines = population_arrays(payload)
    n_bins = round((WINDOW[1] - WINDOW[0]) / BIN_SECONDS)
    if (
        rates.shape != (2, len(data.units), n_bins)
        or baselines.shape != (2, len(data.units))
        or not np.all(np.isfinite(rates)) or np.any(rates < 0)
        or not np.all(np.isfinite(baselines)) or np.any(baselines < 0)
    ):
        raise ValueError("Population rates/baselines have invalid shapes or values.")


def load_population(
    data: Diagnostic, reference_event: dict, path: Path = POPULATION_PATH,
    provenance_path: Path = POPULATION_PROVENANCE,
) -> dict:
    """Load checksummed clean means offline, validating against the trial-spike record."""
    provenance = json.loads(provenance_path.read_text())
    if hashlib.sha256(path.read_bytes()).hexdigest() != provenance["output_sha256"]:
        raise ValueError("Clean population snapshot checksum mismatch.")
    for source in provenance["sources"]:
        actual = hashlib.sha256((REPO_ROOT / source["path"]).read_bytes()).hexdigest()
        if actual != source["sha256"]:
            raise ValueError(f"Clean population extraction source changed: {source['path']}")
    payload = json.loads(path.read_text())
    validate_population(payload, data, reference_event)
    return payload
