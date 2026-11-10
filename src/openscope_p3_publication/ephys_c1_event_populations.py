"""Validated four-event C1 differences for the fixed Figure 9 example population."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from .ephys_c1_population import load_c1_population
from .standard_oddball_cohort import ROOT, sha256
from .standard_oddball_examples import load_example_spikes
from .standard_oddball_neuropixels import load_diagnostic
from .standard_oddball_population import PARAMETERS, load_population, summarize_spike_trials

DIRECTORY = ROOT / "figure_sources/data/ephys-c1-event-populations"
EVENT_ORDER = ("orientation_90", "orientation_45", "halt", "omission")
EXTRA_EVENTS = EVENT_ORDER[1:]
CONDITIONS = ("pre", "post")


def baseline_bin_counts(trials: dict) -> list[int]:
    """Count complete released display bins, independently of any unit's spikes."""
    counts = []
    for condition in CONDITIONS:
        total = 0
        for trial in trials[condition]:
            window = trial["baseline_window"]
            if (
                window is None or len(window) != 2 or not np.isfinite(window).all()
                or window[1] <= window[0]
            ):
                raise ValueError("C1 display trial has no valid preceding-grey baseline.")
            bins = math.floor((window[1] - window[0]) / PARAMETERS["baseline_bin_seconds"])
            if bins < 1:
                raise ValueError("C1 display trial has no complete preceding-grey bins.")
            total += bins
        counts.append(total)
    return counts


def validate_event_population(payload: dict, reference: dict, examples: dict) -> dict:
    """Validate identities, pre/post partition, rates and six native-spike example replays."""
    if (
        payload.get("version") != 1
        or payload.get("event_id") not in EVENT_ORDER
        or any(
            payload.get(key) != reference["payload"][key]
            for key in ("session_id", "asset", "unit_ids", "order", "parameters", "conditions")
        )
    ):
        raise ValueError("Four-event C1 population identity, order, or parameters changed.")
    event = next(e for e in examples["events"] if e["id"] == payload["event_id"])
    trials = payload["trials"]
    bounds = np.asarray(payload["context_interval_seconds"], dtype=float)
    if (
        bounds.shape != (2,) or not np.isfinite(bounds).all() or bounds[0] >= bounds[1]
    ):
        raise ValueError("Four-event C1 actual-context interval is invalid.")
    expected, excluded = {c: [] for c in CONDITIONS}, []
    for trial in event["conditions"]["control"]["trials"]:
        if trial["onset_seconds"] + trial["event_window"][1] <= bounds[0]:
            condition = "pre"
        elif trial["onset_seconds"] >= bounds[1]:
            condition = "post"
        else:
            raise ValueError("A C1 control trial overlaps the actual context interval.")
        if trial["baseline_window"] is None:
            excluded.append({
                "row_index": trial["row_index"], "condition": condition,
                "reason": "missing_preceding_grey",
            })
        else:
            expected[condition].append(trial)
    if (
        trials != expected or not all(trials[c] for c in CONDITIONS)
        or payload.get("excluded_trials") != excluded
    ):
        raise ValueError("Four-event C1 trials do not partition the flanking repeats.")
    bins = payload["baseline_bin_counts"]
    if (
        not isinstance(bins, list) or any(type(n) is not int or n <= 0 for n in bins)
        or bins != baseline_bin_counts(trials)
    ):
        raise ValueError("Four-event C1 display baseline-bin coverage changed.")
    rates = np.asarray(payload["mean_hz"], dtype=float)
    baselines = np.asarray(payload["baseline_mean_hz"], dtype=float)
    if (
        rates.shape != reference["rates"].shape or baselines.shape != reference["baselines"].shape
        or not np.isfinite(rates).all() or np.any(rates < 0)
        or not np.isfinite(baselines).all() or np.any(baselines < 0)
    ):
        raise ValueError("Four-event C1 rates/baselines have invalid shapes or values.")
    positions = {
        trial["row_index"]: i for i, trial in enumerate(event["conditions"]["control"]["trials"])
    }
    unit_indices = {unit: i for i, unit in enumerate(payload["unit_ids"])}
    for unit in examples["units"]:
        i = unit_indices[unit["id"]]
        for c, condition in enumerate(CONDITIONS):
            spike_trials = [
                unit["spikes"][payload["event_id"]]["control"][positions[t["row_index"]]]
                for t in trials[condition]
            ]
            summary = summarize_spike_trials(spike_trials, trials[condition])
            np.testing.assert_allclose(
                rates[c, i], summary["mean_hz"], rtol=64 * np.finfo(float).eps, atol=0,
                err_msg="Four-event C1 SDF does not replay native example spikes.",
            )
            np.testing.assert_allclose(
                baselines[c, i], summary["baseline_mean_hz"],
                rtol=64 * np.finfo(float).eps, atol=0,
                err_msg="Four-event C1 baseline does not replay native example spikes.",
            )
    return {
        "rates": rates, "baselines": baselines, "time": reference["time"],
        "order": reference["order"], "trials": trials, "payload": payload,
    }


def prepare_event_differences(events: dict) -> dict:
    """Subtract pre from post per unit before computing the population mean and SEM."""
    if set(events) != set(EVENT_ORDER):
        raise ValueError("C1 difference plots require exactly the four event types.")
    reference = events["orientation_90"]
    for event in events.values():
        if (
            event["payload"]["unit_ids"] != reference["payload"]["unit_ids"]
            or not np.array_equal(event["order"], reference["order"])
            or not np.array_equal(event["time"], reference["time"])
            or event["rates"].shape != reference["rates"].shape
            or event["baselines"].shape != reference["baselines"].shape
            or not np.isfinite(event["rates"]).all()
            or not np.isfinite(event["baselines"]).all()
        ):
            raise ValueError("Four-event differences require identical finite unit/time axes.")
    delta = np.stack([
        events[event]["rates"] - events[event]["baselines"][..., None]
        for event in EVENT_ORDER
    ])
    difference = delta[:, 1] - delta[:, 0]
    if difference.shape[1] < 2:
        raise ValueError("At least two common units are needed for difference SEM.")
    return {
        "events": events, "difference": difference,
        "heatmaps": difference[:, reference["order"]],
        "mean": difference.mean(axis=1),
        "sem": difference.std(axis=1, ddof=1) / np.sqrt(difference.shape[1]),
        "time": reference["time"], "order": reference["order"],
        "unit_ids": reference["payload"]["unit_ids"],
    }


def load_event_differences(directory: Path = DIRECTORY) -> dict:
    """Verify all committed inputs and compute four-event differences without network access."""
    provenance = json.loads((directory / "provenance.json").read_text())
    if provenance["version"] != 1 or provenance["events"] != list(EXTRA_EVENTS):
        raise ValueError("Unsupported four-event C1 snapshot.")
    for source in provenance["sources"]:
        if sha256(ROOT / source["path"]) != source["sha256"]:
            raise ValueError(f"Four-event C1 source changed: {source['path']}")
    reference = load_c1_population()
    diagnostic = load_diagnostic()
    examples = load_example_spikes(diagnostic)
    original = load_population(diagnostic, examples["events"][1])
    expected_digests = [
        {"unit_id": u["id"], "sha256": u["source_spike_array_sha256"]} for u in original["units"]
    ]
    if provenance["source_spike_digests"] != expected_digests:
        raise ValueError("Four-event native unit spike digests differ from Figure 9.")
    events = {"orientation_90": reference}
    for event in EXTRA_EVENTS:
        output, = [o for o in provenance["outputs"] if o["event_id"] == event]
        path = directory / output["path"]
        if sha256(path) != output["sha256"]:
            raise ValueError(f"Four-event C1 checksum mismatch: {event}")
        payload = json.loads(path.read_text())
        if payload["event_id"] != event:
            raise ValueError("Four-event C1 payload has the wrong event ID.")
        events[event] = validate_event_population(payload, reference, examples)
    if len({
        tuple(events[event]["payload"]["context_interval_seconds"]) for event in EXTRA_EVENTS
    }) != 1:
        raise ValueError("Four-event C1 snapshots disagree on the actual-context interval.")
    return prepare_event_differences(events)
