"""Clean-trial baseline-bin statistics for standard-oddball normalization."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np

from .neural_responses import BASELINE_BIN_SECONDS
from .standard_oddball_examples import SOURCE_START, WINDOW
from .standard_oddball_neuropixels import REPO_ROOT
from .standard_oddball_population import POPULATION_PATH

BASELINES_PATH = POPULATION_PATH.with_name("neuropixels-standard-oddball-90-baselines.json")
BASELINES_PROVENANCE = BASELINES_PATH.with_suffix(".provenance.json")
BASELINE_RULE = (
    "condition-specific clean-trial preceding-grey baseline; complete half-open 20 ms bins; "
    "pooled bin-rate mean and population SD (ddof=0); trailing fractional bin omitted"
)


def _baseline_edges(trial: dict) -> np.ndarray:
    window = trial["baseline_window"]
    if (
        window is None or len(window) != 2 or not np.all(np.isfinite(window))
        or window[1] <= window[0] or window[0] < SOURCE_START or window[1] > WINDOW[1]
    ):
        raise ValueError("Invalid or unavailable clean-trial baseline window.")
    bins = math.floor((window[1] - window[0]) / BASELINE_BIN_SECONDS)
    if bins < 1:
        raise ValueError("Baseline window has no complete 20 ms bins.")
    return window[0] + np.arange(bins + 1) * BASELINE_BIN_SECONDS


def _histogram_statistics(histogram: list[int]) -> tuple[float, float, int]:
    if (
        not isinstance(histogram, list) or not histogram
        or any(type(n) is not int or n < 0 for n in histogram) or sum(histogram) <= 0
    ):
        raise ValueError("Baseline spike-count histogram is invalid or empty.")
    rates = np.arange(len(histogram)) / BASELINE_BIN_SECONDS
    mean = float(np.average(rates, weights=histogram))
    sd = float(np.sqrt(np.average((rates - mean) ** 2, weights=histogram)))
    return mean, sd, sum(histogram)


def summarize_baseline_bins(spike_trials: list[list[float]], trials: list[dict]) -> dict:
    """Pool actual complete-bin spike counts, including every zero-spike bin."""
    if len(spike_trials) != len(trials) or not trials:
        raise ValueError("Baseline spike/trial alignment is inconsistent or empty.")
    counts = []
    for spikes, trial in zip(spike_trials, trials, strict=True):
        values = np.asarray(spikes, dtype=float)
        if values.ndim != 1 or not np.all(np.isfinite(values)) or np.any(np.diff(values) < 0):
            raise ValueError("Baseline spikes must be finite and sorted.")
        counts.extend(np.diff(np.searchsorted(values, _baseline_edges(trial), side="left")))
    histogram = np.bincount(counts).tolist()
    mean, sd, bins = _histogram_statistics(histogram)
    return {
        "bin_count": bins, "spike_count_histogram": histogram,
        "mean_hz": mean, "sd_hz": sd,
    }


def validate_baselines(payload: dict, population: dict) -> None:
    """Check clean-trial identity, source spikes, and reproducible baseline moments."""
    if (
        payload.get("version") != 1
        or payload.get("session_id") != population["session_id"]
        or payload.get("asset") != population["asset"]
        or payload.get("event") != population["event"]
        or payload.get("baseline_rule") != BASELINE_RULE
        or [u["id"] for u in payload.get("units", [])]
        != [u["id"] for u in population["units"]]
    ):
        raise ValueError("Clean baseline identity, trial membership, or units changed.")
    for unit, reference in zip(payload["units"], population["units"], strict=True):
        if (
            unit.get("source_spike_array_sha256") != reference["source_spike_array_sha256"]
            or set(unit["conditions"]) != {"context", "control"}
        ):
            raise ValueError("Clean baseline source spikes or conditions changed.")
        for condition, summary in unit["conditions"].items():
            mean, sd, bins = _histogram_statistics(summary["spike_count_histogram"])
            expected_bins = sum(
                len(_baseline_edges(trial)) - 1
                for trial in population["event"]["conditions"][condition]["trials"]
            )
            values = [summary["mean_hz"], summary["sd_hz"]]
            if (
                not np.all(np.isfinite(values)) or min(values) < 0
                or summary["bin_count"] != bins or bins != expected_bins
                or not np.isclose(summary["mean_hz"], mean, atol=1e-12, rtol=0)
                or not np.isclose(summary["sd_hz"], sd, atol=1e-12, rtol=0)
                or not np.isclose(
                    mean, reference["conditions"][condition]["baseline_mean_hz"],
                    atol=1e-12, rtol=0,
                )
            ):
                raise ValueError("Clean baseline moments, bin counts, or population means changed.")


def load_baselines(
    population: dict, path: Path = BASELINES_PATH,
    provenance_path: Path = BASELINES_PROVENANCE,
) -> dict:
    """Load a checksummed baseline sidecar without reading NWB or network data."""
    provenance = json.loads(provenance_path.read_text())
    if hashlib.sha256(path.read_bytes()).hexdigest() != provenance["output_sha256"]:
        raise ValueError("Clean baseline snapshot checksum mismatch.")
    for source in provenance["sources"]:
        actual = hashlib.sha256((REPO_ROOT / source["path"]).read_bytes()).hexdigest()
        if actual != source["sha256"]:
            raise ValueError(f"Clean baseline extraction source changed: {source['path']}")
    payload = json.loads(path.read_text())
    validate_baselines(payload, population)
    return payload
