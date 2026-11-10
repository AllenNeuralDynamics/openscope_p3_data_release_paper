#!/usr/bin/env python3
"""Freeze 45-degree, halt and omission C1 displays alongside the unchanged 90-degree data."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import h5py
import numpy as np

from openscope_p3_publication.ephys_c1_event_populations import (
    CONDITIONS,
    DIRECTORY,
    EVENT_ORDER,
    EXTRA_EVENTS,
    baseline_bin_counts,
    validate_event_population,
)
from openscope_p3_publication.ephys_c1_population import DIRECTORY as REFERENCE_DIRECTORY
from openscope_p3_publication.ephys_c1_population import load_c1_population
from openscope_p3_publication.neural_responses import NEURAL_SESSIONS
from openscope_p3_publication.standard_oddball_cohort import ROOT, event_windows, sha256
from openscope_p3_publication.standard_oddball_examples import (
    EXAMPLES_PATH,
    EXAMPLES_PROVENANCE,
    aligned_trial_spikes,
    example_trial_records,
    load_example_spikes,
)
from openscope_p3_publication.standard_oddball_neuropixels import EVENTS, load_diagnostic
from openscope_p3_publication.standard_oddball_population import (
    POPULATION_PATH,
    POPULATION_PROVENANCE,
    load_population,
    summarize_spike_trials,
)


def main() -> None:
    """Verify native unit spikes once, then save compact three-event pre/post snapshots."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DIRECTORY)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Output exists; choose a fresh directory.")
    import remfile

    reference = load_c1_population()
    diagnostic = load_diagnostic()
    examples = load_example_spikes(diagnostic)
    population = load_population(diagnostic, examples["events"][1])
    asset = population["asset"]
    with urllib.request.urlopen(
        f"https://api.dandiarchive.org/api/assets/{asset['assetId']}/", timeout=180,
    ) as response:
        detail = json.load(response)
    if detail["path"] != asset["path"] or detail["digest"] != asset["digest"]:
        raise ValueError("Pinned example NWB source identity changed.")
    payloads = {}
    source_digests = []
    with closing(remfile.File(asset["downloadUrl"])) as remote, h5py.File(remote, "r") as nwb:
        config = next(s for s in NEURAL_SESSIONS if s.context == "standard")
        tables = {}
        for condition, table_name in (
            ("context", config.context_table), ("control", config.control_table),
        ):
            group = nwb[f"intervals/{table_name}"]
            tables[condition] = {
                key: np.asarray(group[source][:]).astype("U" if key == "trial_type" else float)
                for key, source in (
                    ("trial_type", "TrialType"), ("orientation", "Orientation"),
                    ("delay", "Delay"), ("block_number", "BlockNumber"),
                    ("start", "start_time"), ("stop", "stop_time"),
                )
            }
        records = example_trial_records(tables, event_ids=EVENTS)
        if records != examples["events"]:
            raise ValueError("Pinned NWB four-event trial identities or timing changed.")
        windows = event_windows(tables)
        interval = [float(tables["context"]["start"].min()), float(tables["context"]["stop"].max())]
        for event in EVENT_ORDER:
            record = next(e for e in records if e["id"] == event)
            trials = {
                condition: [
                    t for t in record["conditions"]["control"]["trials"]
                    if t["row_index"] in windows[event][f"control_{condition}_indices"]
                ]
                for condition in CONDITIONS
            }
            if any(
                [t["row_index"] for t in trials[c]] != windows[event][f"control_{c}_indices"]
                for c in CONDITIONS
            ):
                raise ValueError(f"C1 display and native control indices disagree: {event}")
            excluded = [
                {"row_index": t["row_index"], "condition": c, "reason": "missing_preceding_grey"}
                for c in CONDITIONS for t in trials[c] if t["baseline_window"] is None
            ]
            trials = {
                c: [t for t in trials[c] if t["baseline_window"] is not None] for c in CONDITIONS
            }
            payloads[event] = {
                **{
                    key: reference["payload"][key]
                    for key in (
                        "version", "session_id", "asset", "unit_ids", "order",
                        "parameters", "conditions",
                    )
                },
                "event_id": event, "context_interval_seconds": interval, "trials": trials,
                "excluded_trials": excluded,
                "baseline_bin_counts": baseline_bin_counts(trials),
                "mean_hz": [[], []], "baseline_mean_hz": [[], []],
            }
        ids = np.asarray(nwb["units/id"], dtype=np.int64)
        ends = np.asarray(nwb["units/spike_times_index"], dtype=np.int64)
        if len(set(ids)) != len(ids) or len(ends) != len(ids):
            raise ValueError("NWB ragged unit identities are invalid.")
        for number, unit in enumerate(population["units"]):
            matching = np.flatnonzero(ids == unit["id"])
            if len(matching) != 1:
                raise ValueError(f"Display unit {unit['id']} is missing or ambiguous.")
            row = int(matching[0])
            first = 0 if row == 0 else int(ends[row - 1])
            spikes = np.asarray(nwb["units/spike_times"][first:int(ends[row])], dtype=float)
            digest = hashlib.sha256(spikes.astype("<f8").tobytes()).hexdigest()
            if digest != unit["source_spike_array_sha256"]:
                raise ValueError(f"Native display unit spike digest changed: {unit['id']}")
            source_digests.append({"unit_id": unit["id"], "sha256": digest})
            for payload in payloads.values():
                for c, condition in enumerate(CONDITIONS):
                    trials = payload["trials"][condition]
                    summary = summarize_spike_trials(aligned_trial_spikes(spikes, trials), trials)
                    payload["mean_hz"][c].append(summary["mean_hz"])
                    payload["baseline_mean_hz"][c].append(summary["baseline_mean_hz"])
            if (number + 1) % 25 == 0:
                print(f"Verified and summarized {number + 1}/{len(population['units'])} units.")
    for payload in payloads.values():
        validate_event_population(payload, reference, examples)
    for key in ("trials", "baseline_bin_counts", "mean_hz", "baseline_mean_hz"):
        np.testing.assert_equal(payloads["orientation_90"][key], reference["payload"][key])
    sources = [
        Path(__file__).resolve(), POPULATION_PATH, POPULATION_PROVENANCE,
        EXAMPLES_PATH, EXAMPLES_PROVENANCE, REFERENCE_DIRECTORY / "provenance.json",
        *[
            ROOT / f"src/openscope_p3_publication/{name}.py"
            for name in (
                "ephys_c1_event_populations", "standard_oddball_population",
                "standard_oddball_examples", "standard_oddball_cohort", "neural_responses",
            )
        ],
    ]
    contents = {
        event: json.dumps(payloads[event], allow_nan=False, separators=(",", ":")) + "\n"
        for event in EXTRA_EVENTS
    }
    if any(len(content.encode()) >= 10 * 1024**2 for content in contents.values()):
        raise ValueError("An event snapshot exceeds the 10 MiB size tier.")
    args.output_dir.mkdir(parents=True)
    outputs = []
    for event, content in contents.items():
        path = args.output_dir / f"{event}.json"
        path.write_text(content, encoding="utf-8", newline="\n")
        outputs.append({"event_id": event, "path": path.name, "sha256": sha256(path)})
    provenance = {
        "version": 1, "events": list(EXTRA_EVENTS), "session_id": population["session_id"],
        "asset": asset, "retrieved_at": datetime.now(UTC).isoformat(),
        "source_spike_digests": source_digests,
        "source_verification": "All 203 full-unit spike digests exactly match Figure 9.",
        "replay": "Exact 90-degree split replay; six native trial-spike examples in all events.",
        "trial_counts": {
            event: {c: len(payloads[event]["trials"][c]) for c in CONDITIONS}
            for event in EVENT_ORDER
        },
        "exclusions": {event: payloads[event]["excluded_trials"] for event in EVENT_ORDER},
        "sources": [
            {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)} for path in sources
        ],
        "outputs": outputs,
    }
    (args.output_dir / "provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8", newline="\n",
    )
    print(f"Saved verified additional event displays to {args.output_dir}.")


if __name__ == "__main__":
    main()
