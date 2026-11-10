"""Checksummed pre/post-C1 population displays for the Figure 9 ephys example."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .standard_oddball_cohort import ROOT, sha256
from .standard_oddball_examples import WINDOW, load_example_spikes
from .standard_oddball_neuropixels import load_diagnostic
from .standard_oddball_ordering import load_context_order
from .standard_oddball_population import (
    BIN_SECONDS,
    PARAMETERS,
    load_population,
    population_arrays,
)

DIRECTORY = ROOT / "figure_sources/data/ephys-c1-population"
CONDITIONS = ("pre", "post")


def validate_c1_population(payload: dict, population: dict, order: np.ndarray) -> dict:
    """Verify shared identities, baselines, original pooled replay, and difference arithmetic."""
    ids = [unit["id"] for unit in population["units"]]
    if (
        payload.get("version") != 1
        or payload.get("session_id") != population["session_id"]
        or payload.get("asset") != population["asset"]
        or payload.get("unit_ids") != ids
        or payload.get("order") != order.tolist()
        or payload.get("parameters") != PARAMETERS
        or payload.get("conditions") != list(CONDITIONS)
    ):
        raise ValueError("C1 display unit, session, parameters, or frozen row order changed.")
    original_trials = population["event"]["conditions"]["control"]["trials"]
    trials = payload["trials"]
    if (
        not all(trials[condition] for condition in CONDITIONS)
        or trials["pre"] + trials["post"] != original_trials
    ):
        raise ValueError("Pre/post C1 displays do not partition the original matched trials.")
    rates = np.asarray(payload["mean_hz"], dtype=float)
    baselines = np.asarray(payload["baseline_mean_hz"], dtype=float)
    bins = np.asarray(payload["baseline_bin_counts"], dtype=int)
    shape = (2, len(ids), round((WINDOW[1] - WINDOW[0]) / BIN_SECONDS))
    if (
        rates.shape != shape or baselines.shape != shape[:2] or bins.shape != (2,)
        or not np.isfinite(rates).all() or np.any(rates < 0)
        or not np.isfinite(baselines).all() or np.any(baselines < 0)
        or np.any(bins <= 0)
    ):
        raise ValueError("C1 display rates/baselines have invalid shapes or values.")
    original_rates, original_baselines = population_arrays(population)
    weights = np.array([len(trials[c]) for c in CONDITIONS], dtype=float)
    tolerance = 64 * np.finfo(float).eps
    np.testing.assert_allclose(
        np.average(rates, axis=0, weights=weights), original_rates[1],
        rtol=tolerance, atol=0, err_msg="Pre/post SDFs do not replay original pooled controls.",
    )
    np.testing.assert_allclose(
        np.average(baselines, axis=0, weights=bins), original_baselines[1],
        rtol=tolerance, atol=0, err_msg="Pre/post display baselines do not replay pooled controls.",
    )
    delta = rates - baselines[..., None]
    heatmaps = np.stack([delta[0, order], delta[1, order], (delta[1] - delta[0])[order]])
    return {
        "time": WINDOW[0] + (np.arange(shape[-1]) + 0.5) * BIN_SECONDS,
        "rates": rates, "baselines": baselines, "heatmaps": heatmaps,
        "order": order, "trials": trials, "payload": payload,
    }


def load_c1_population(directory: Path = DIRECTORY) -> dict:
    """Load frozen displays offline without downloading spikes or fitting a new order."""
    provenance = json.loads((directory / "provenance.json").read_text())
    for source in provenance["sources"]:
        if sha256(ROOT / source["path"]) != source["sha256"]:
            raise ValueError(f"C1 display source changed: {source['path']}")
    path = directory / "population.json"
    if sha256(path) != provenance["output_sha256"]:
        raise ValueError("C1 population display checksum mismatch.")
    diagnostic = load_diagnostic()
    population = load_population(diagnostic, load_example_spikes(diagnostic)["events"][1])
    return validate_c1_population(
        json.loads(path.read_text()), population, load_context_order(population),
    )
