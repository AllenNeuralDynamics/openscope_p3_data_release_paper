#!/usr/bin/env python3
"""Freeze separate pre/post-C1 displays for the 203 Figure 9 example-session units."""

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

from openscope_p3_publication.ephys_c1_population import (
    CONDITIONS,
    DIRECTORY,
    validate_c1_population,
)
from openscope_p3_publication.ephys_c1_pseudocontext import DIRECTORY as STATISTICS
from openscope_p3_publication.ephys_c1_pseudocontext import load_pseudo, pseudo_windows
from openscope_p3_publication.neural_responses import NEURAL_SESSIONS
from openscope_p3_publication.standard_oddball_baselines import summarize_baseline_bins
from openscope_p3_publication.standard_oddball_cohort import ROOT, sha256
from openscope_p3_publication.standard_oddball_examples import (
    aligned_trial_spikes,
    example_trial_records,
    load_example_spikes,
)
from openscope_p3_publication.standard_oddball_neuropixels import load_diagnostic
from openscope_p3_publication.standard_oddball_ordering import ORDER_PATH, load_context_order
from openscope_p3_publication.standard_oddball_population import (
    PARAMETERS,
    POPULATION_PATH,
    POPULATION_PROVENANCE,
    load_population,
    summarize_spike_trials,
)


def main() -> None:
    """Extract native spikes once and verify against the original pooled display."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DIRECTORY)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Output exists; choose a fresh directory.")
    import remfile

    diagnostic = load_diagnostic()
    population = load_population(diagnostic, load_example_spikes(diagnostic)["events"][1])
    order = load_context_order(population)
    _, _, statistics_provenance = load_pseudo()
    reference = next(
        session for session in statistics_provenance["sessions"]
        if session["session_id"] == population["session_id"]
    )
    original_trials = population["event"]["conditions"]["control"]["trials"]
    trials = {
        condition: [
            trial for trial in original_trials
            if trial["row_index"] in reference["trials"][f"{condition}_indices"]
        ]
        for condition in CONDITIONS
    }
    if any(
        [t["row_index"] for t in trials[c]] != reference["trials"][f"{c}_indices"]
        for c in CONDITIONS
    ):
        raise ValueError("Display trials differ from the pseudo-context statistical trials.")
    asset = population["asset"]
    with urllib.request.urlopen(
        f"https://api.dandiarchive.org/api/assets/{asset['assetId']}/", timeout=180,
    ) as response:
        detail = json.load(response)
    if detail["path"] != asset["path"] or detail["digest"] != asset["digest"]:
        raise ValueError("Pinned example NWB source identity changed.")
    means = {condition: [] for condition in CONDITIONS}
    baselines = {condition: [] for condition in CONDITIONS}
    baseline_bin_counts = None
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
        if (
            example_trial_records(tables, event_ids=("orientation_90",)) != [population["event"]]
            or json.loads(json.dumps(pseudo_windows(tables)[1])) != reference["trials"]
        ):
            raise ValueError("Pinned NWB original or pseudo-context trial identities changed.")
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
            if hashlib.sha256(spikes.astype("<f8").tobytes()).hexdigest() != unit[
                "source_spike_array_sha256"
            ]:
                raise ValueError(f"Display unit {unit['id']} spike digest changed.")
            bin_counts = []
            for condition in CONDITIONS:
                aligned = aligned_trial_spikes(spikes, trials[condition])
                summary = summarize_spike_trials(aligned, trials[condition])
                baseline = summarize_baseline_bins(aligned, trials[condition])
                np.testing.assert_allclose(
                    summary["baseline_mean_hz"], baseline["mean_hz"],
                    rtol=64 * np.finfo(float).eps, atol=0,
                )
                means[condition].append(summary["mean_hz"])
                baselines[condition].append(summary["baseline_mean_hz"])
                bin_counts.append(baseline["bin_count"])
            if baseline_bin_counts is not None and baseline_bin_counts != bin_counts:
                raise ValueError("Display baseline-bin coverage varies between units.")
            baseline_bin_counts = bin_counts
            if (number + 1) % 25 == 0:
                print(f"Verified and summarized {number + 1}/{len(population['units'])} units.")
    payload = {
        "version": 1, "session_id": population["session_id"], "asset": asset,
        "unit_ids": [unit["id"] for unit in population["units"]],
        "order": order.tolist(), "parameters": PARAMETERS, "conditions": list(CONDITIONS),
        "trials": trials, "mean_hz": [means[c] for c in CONDITIONS],
        "baseline_mean_hz": [baselines[c] for c in CONDITIONS],
        "baseline_bin_counts": baseline_bin_counts,
    }
    validate_c1_population(payload, population, order)
    sources = [
        Path(__file__).resolve(), POPULATION_PATH, POPULATION_PROVENANCE, ORDER_PATH,
        STATISTICS / "provenance.json",
        *[
            ROOT / f"src/openscope_p3_publication/{name}.py"
            for name in (
                "ephys_c1_population", "standard_oddball_population",
                "standard_oddball_baselines", "standard_oddball_examples",
                "standard_oddball_ordering", "neural_responses",
            )
        ],
    ]
    content = json.dumps(payload, allow_nan=False, separators=(",", ":")) + "\n"
    if len(content.encode()) >= 10 * 1024**2:
        raise ValueError("C1 display snapshot exceeds the 10 MiB size tier.")
    args.output_dir.mkdir(parents=True)
    path = args.output_dir / "population.json"
    path.write_text(content, encoding="utf-8", newline="\n")
    provenance = {
        "version": 1, "session_id": population["session_id"], "asset": asset,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "sources": [
            {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)} for path in sources
        ],
        "output_sha256": sha256(path),
        "unit_count": len(population["units"]),
        "trial_counts": {condition: len(trials[condition]) for condition in CONDITIONS},
        "source_verification": "All 203 full-unit spike digests match Figure 9.",
        "pooled_replay": "Separate pre/post raw SDFs and display baselines replay pooled C1.",
        "difference": "Post minus pre, after separate condition/unit display baselines.",
    }
    (args.output_dir / "provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n",
    )
    print(f"Published verified pre/post displays to {args.output_dir}.")


if __name__ == "__main__":
    main()
