"""Validated, offline context-only Rastermap permutation for the main column."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from .neural_responses import RASTERMAP_PARAMETERS, RASTERMAP_VERSION
from .standard_oddball_neuropixels import DATA_PATH, REPO_ROOT
from .standard_oddball_population import EVENT_ID, population_arrays

ORDER_PATH = DATA_PATH.with_name("neuropixels-standard-oddball-90-rastermap.json")
INPUT_RULE = (
    "context-only clean trial-mean SDF minus context baseline, float32 Hz; "
    "full displayed window; Rastermap normalize=True; all eligible visual units"
)


def context_matrix(population: dict) -> np.ndarray:
    """Prepare fitting input without accessing the control response values."""
    matrix = np.asarray([
        np.asarray(unit["conditions"]["context"]["mean_hz"])
        - unit["conditions"]["context"]["baseline_mean_hz"]
        for unit in population["units"]
    ], dtype="<f4")
    if (
        matrix.ndim != 2 or min(matrix.shape) < 2
        or not np.all(np.isfinite(matrix)) or np.any(np.ptp(matrix, axis=1) == 0)
    ):
        raise ValueError("Context Rastermap input must be finite and variable for every unit.")
    return matrix


def matrix_sha256(population: dict) -> str:
    """Fingerprint exactly the context matrix used for fitting."""
    return hashlib.sha256(context_matrix(population).tobytes()).hexdigest()


def order_sha256(order: list[int]) -> str:
    """Fingerprint a validated permutation in a fixed byte representation."""
    return hashlib.sha256(np.asarray(order, dtype="<u4").tobytes()).hexdigest()


def validate_context_order(payload: dict, population: dict) -> np.ndarray:
    """Reject stale input, wrong parameters, or incomplete/duplicate ordering."""
    unit_ids = [unit["id"] for unit in population["units"]]
    order = payload.get("isort")
    if (
        payload.get("version") != 1
        or payload.get("event_id") != EVENT_ID
        or payload.get("fit_condition") != "context"
        or payload.get("input_rule") != INPUT_RULE
        or payload.get("unit_ids") != unit_ids
        or payload.get("input_shape") != list(context_matrix(population).shape)
        or payload.get("input_parameters") != population["parameters"]
        or payload.get("matrix_sha256") != matrix_sha256(population)
        or payload.get("rastermap_version") != RASTERMAP_VERSION
        or payload.get("rastermap_parameters") != RASTERMAP_PARAMETERS
        or not isinstance(order, list)
        or any(type(i) is not int for i in order)
        or sorted(order) != list(range(len(unit_ids)))
    ):
        raise ValueError("Context Rastermap input, parameters, or permutation changed.")
    if (
        payload.get("order_sha256") != order_sha256(order)
        or payload.get("ordered_unit_ids") != [unit_ids[i] for i in order]
    ):
        raise ValueError("Context Rastermap ordering checksum or unit mapping is inconsistent.")
    return np.asarray(order, dtype=int)


def load_context_order(population: dict, path: Path = ORDER_PATH) -> np.ndarray:
    """Load a frozen context-only fit; never run Rastermap during rendering."""
    payload = json.loads(path.read_text())
    for source in payload["sources"]:
        actual = hashlib.sha256((REPO_ROOT / source["path"]).read_bytes()).hexdigest()
        if actual != source["sha256"]:
            raise ValueError(f"Context Rastermap fitting source changed: {source['path']}")
    return validate_context_order(payload, population)


def ordered_heatmaps(population: dict, order: np.ndarray) -> np.ndarray:
    """Apply one context-derived order to context, control, and their difference."""
    rates, baselines = population_arrays(population)
    delta = rates - baselines[..., None]
    return np.stack([delta[0, order], delta[1, order], (delta[0] - delta[1])[order]])
