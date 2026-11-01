#!/usr/bin/env python3
"""Fit context-only Rastermap on the committed clean 90-degree visual population."""

from __future__ import annotations

import argparse
import hashlib
import json
from importlib.metadata import version
from pathlib import Path

import numpy as np

from openscope_p3_publication.neural_responses import RASTERMAP_PARAMETERS, RASTERMAP_VERSION
from openscope_p3_publication.standard_oddball_examples import load_example_spikes
from openscope_p3_publication.standard_oddball_neuropixels import REPO_ROOT, load_diagnostic
from openscope_p3_publication.standard_oddball_ordering import (
    INPUT_RULE,
    ORDER_PATH,
    context_matrix,
    matrix_sha256,
    order_sha256,
    validate_context_order,
)
from openscope_p3_publication.standard_oddball_population import EVENT_ID, load_population


def main() -> None:
    """Write a pinned, seeded fit once, leaving ordinary builds entirely offline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ORDER_PATH)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.output.exists() and not args.overwrite:
        raise SystemExit(
            "Order already exists; inspect it first, then pass --overwrite deliberately."
        )
    from rastermap import Rastermap

    installed = version("rastermap")
    if installed != RASTERMAP_VERSION:
        raise SystemExit(f"Rastermap {RASTERMAP_VERSION} is required; found {installed}.")
    data = load_diagnostic()
    population = load_population(data, load_example_spikes(data)["events"][1])
    matrix = context_matrix(population)
    model = Rastermap(
        **RASTERMAP_PARAMETERS, keep_norm_X=False, verbose=False,
    ).fit(matrix, compute_X_embedding=False)
    order = np.asarray(model.isort).tolist()
    unit_ids = [unit["id"] for unit in population["units"]]
    paths = [
        Path(__file__).resolve(),
        REPO_ROOT / "src/openscope_p3_publication/standard_oddball_ordering.py",
        REPO_ROOT / "src/openscope_p3_publication/neural_responses.py",
    ]
    payload = {
        "version": 1, "event_id": EVENT_ID, "fit_condition": "context",
        "input_rule": INPUT_RULE, "input_shape": list(matrix.shape),
        "input_parameters": population["parameters"], "unit_ids": unit_ids,
        "matrix_sha256": matrix_sha256(population), "isort": order,
        "order_sha256": order_sha256(order),
        "ordered_unit_ids": [unit_ids[i] for i in order],
        "rastermap_version": installed, "rastermap_parameters": RASTERMAP_PARAMETERS,
        "sources": [
            {"path": str(path.relative_to(REPO_ROOT)),
             "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in paths
        ],
        "software": {name: version(name) for name in ("numpy", "scipy", "scikit-learn", "numba")},
    }
    validate_context_order(payload, population)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {args.output}; {len(order)} units; context matrix {matrix.shape}.")


if __name__ == "__main__":
    main()
