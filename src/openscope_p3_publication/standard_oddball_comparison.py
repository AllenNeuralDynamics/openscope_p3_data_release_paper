"""The user-selected cortical example without detectable Q2 oddball modulation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from .standard_oddball_candidates import COMPARISON_EXAMPLE_RULE, candidate_masks
from .standard_oddball_examples import validate_example_spikes
from .standard_oddball_neuropixels import REPO_ROOT, Diagnostic, visual_group
from .standard_oddball_population import EVENT_ID, POPULATION_PATH, summarize_spike_trials

COMPARISON_UNIT_ID = 993
COMPARISON_PATH = POPULATION_PATH.with_name("neuropixels-standard-oddball-90-comparison.json")
COMPARISON_PROVENANCE = COMPARISON_PATH.with_suffix(".provenance.json")
SDF_REPLAY_RTOL = 64 * np.finfo(np.float64).eps
COMPARISON_RULE = (
    f"fixed user-selected VISp4 unit 993; {COMPARISON_EXAMPLE_RULE}; "
    "90-degree event; Q1 may be significant; "
    "not evidence of equivalence or absent visual responsiveness"
)


def spike_summary_matches(replayed: dict, frozen: dict) -> bool:
    """Allow float64 convolution roundoff, but require exact baselines and schema."""
    keys = {"mean_hz", "baseline_mean_hz"}
    if (
        replayed.keys() != keys or frozen.keys() != keys
        or replayed["baseline_mean_hz"] != frozen["baseline_mean_hz"]
        or not np.isfinite(replayed["baseline_mean_hz"])
        or not np.isfinite(frozen["baseline_mean_hz"])
    ):
        return False
    actual = np.asarray(replayed["mean_hz"], dtype=np.float64)
    expected = np.asarray(frozen["mean_hz"], dtype=np.float64)
    return bool(
        actual.ndim == expected.ndim == 1 and actual.shape == expected.shape
        and np.all(np.isfinite(actual)) and np.all(np.isfinite(expected))
        and np.allclose(actual, expected, rtol=SDF_REPLAY_RTOL, atol=0)
    )


def comparison_selection(data: Diagnostic) -> list[dict]:
    """Validate the fixed cortical comparison against the original response tests."""
    matches = [i for i, unit in enumerate(data.units) if unit["id"] == COMPARISON_UNIT_ID]
    if len(matches) != 1:
        raise ValueError("The fixed cortical comparison unit is missing or ambiguous.")
    i, = matches
    unit = data.units[i]
    if (
        visual_group(unit) != 0 or unit["location"] != "VISp4"
        or not candidate_masks(data)["comparison"][i]
    ):
        raise ValueError("Cortical comparison no longer meets the Q2/MI/firing-rate criteria.")
    return [{"index": i, "unit_id": unit["id"], "label": unit["location"]}]


def validate_comparison_spikes(payload: dict, data: Diagnostic, population: dict) -> None:
    """Verify exact clean trials, source spikes, and reconstructed condition means."""
    validate_example_spikes(
        payload, data, selection=comparison_selection(data),
        selection_rule=COMPARISON_RULE, event_ids=(EVENT_ID,),
    )
    if payload["events"] != [population["event"]]:
        raise ValueError("Comparison example clean trial identity or timing changed.")
    unit, = payload["units"]
    reference, = [u for u in population["units"] if u["id"] == COMPARISON_UNIT_ID]
    if unit["source_spike_array_sha256"] != reference["source_spike_array_sha256"]:
        raise ValueError("Comparison source spike digest changed.")
    for condition, record in population["event"]["conditions"].items():
        summary = summarize_spike_trials(unit["spikes"][EVENT_ID][condition], record["trials"])
        if not spike_summary_matches(summary, reference["conditions"][condition]):
            raise ValueError(
                "Comparison spikes do not reproduce the clean population SDF/baseline."
            )


def load_comparison_spikes(
    data: Diagnostic, population: dict, path: Path = COMPARISON_PATH,
    provenance_path: Path = COMPARISON_PROVENANCE,
) -> dict:
    """Load the cortical comparison offline with source and data checksum validation."""
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if hashlib.sha256(path.read_bytes()).hexdigest() != provenance["output_sha256"]:
        raise ValueError("Comparison spike snapshot checksum mismatch.")
    for source in provenance["sources"]:
        actual = hashlib.sha256((REPO_ROOT / source["path"]).read_bytes()).hexdigest()
        if actual != source["sha256"]:
            raise ValueError(f"Comparison extraction source changed: {source['path']}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_comparison_spikes(payload, data, population)
    return payload
