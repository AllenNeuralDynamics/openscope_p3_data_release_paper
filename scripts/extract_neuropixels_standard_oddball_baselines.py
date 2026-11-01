#!/usr/bin/env python3
"""Extract condition-specific baseline moments for the clean 90-degree visual population."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import urllib.request
from contextlib import closing
from pathlib import Path

import h5py
import numpy as np

from openscope_p3_publication.neural_responses import NEURAL_SESSIONS
from openscope_p3_publication.standard_oddball_baselines import (
    BASELINE_RULE,
    BASELINES_PATH,
    BASELINES_PROVENANCE,
    summarize_baseline_bins,
    validate_baselines,
)
from openscope_p3_publication.standard_oddball_examples import (
    aligned_trial_spikes,
    example_trial_records,
    load_example_spikes,
)
from openscope_p3_publication.standard_oddball_neuropixels import REPO_ROOT, load_diagnostic
from openscope_p3_publication.standard_oddball_population import (
    EVENT_ID,
    POPULATION_PATH,
    POPULATION_PROVENANCE,
    load_population,
)


def main() -> None:
    """Read pinned source ranges and write only compact, auditable baseline statistics."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=BASELINES_PATH)
    parser.add_argument("--provenance-output", type=Path, default=BASELINES_PROVENANCE)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if not args.overwrite and (args.output.exists() or args.provenance_output.exists()):
        raise SystemExit("Baseline output exists; inspect it before passing --overwrite.")
    import remfile

    data = load_diagnostic()
    population = load_population(data, load_example_spikes(data)["events"][1])
    asset = data.session["asset"]
    with urllib.request.urlopen(
        f"https://api.dandiarchive.org/api/assets/{asset['assetId']}/", timeout=180,
    ) as response:
        detail = json.load(response)
    if detail["path"] != asset["path"] or detail["digest"] != asset["digest"]:
        raise ValueError("Pinned standard-session asset identity or digest changed.")
    config = next(s for s in NEURAL_SESSIONS if s.context == "standard")
    units = []
    with closing(remfile.File(asset["downloadUrl"])) as remote, h5py.File(remote, "r") as nwb:
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
        event, = example_trial_records(tables, event_ids=(EVENT_ID,))
        if event != population["event"]:
            raise ValueError("Pinned NWB clean trial identities or baseline windows changed.")
        ids = np.asarray(nwb["units/id"][:])
        ends = np.asarray(nwb["units/spike_times_index"][:], dtype=int)
        for expected, reference in zip(data.units, population["units"], strict=True):
            matching = np.flatnonzero(ids == expected["id"])
            if len(matching) != 1:
                raise ValueError(f"Baseline unit {expected['id']} did not match one NWB row.")
            row = int(matching[0])
            label = nwb["units/decoder_label"][row]
            label = label.decode() if isinstance(label, bytes) else str(label)
            if (
                label != "sua" or nwb["units/ks_unit_id"][row] != expected["ksUnitId"]
                or not np.isclose(
                    nwb["units/firing_rate"][row], expected["firingRateHz"], atol=1e-6, rtol=0,
                )
            ):
                raise ValueError(f"Baseline unit {expected['id']} metadata changed.")
            spikes = np.asarray(
                nwb["units/spike_times"][0 if row == 0 else ends[row - 1]:ends[row]], dtype=float,
            )
            digest = hashlib.sha256(spikes.astype("<f8").tobytes()).hexdigest()
            if digest != reference["source_spike_array_sha256"]:
                raise ValueError(f"Baseline unit {expected['id']} source spike digest changed.")
            units.append({
                "id": expected["id"], "source_spike_array_sha256": digest,
                "conditions": {
                    condition: summarize_baseline_bins(
                        aligned_trial_spikes(spikes, record["trials"]), record["trials"],
                    )
                    for condition, record in event["conditions"].items()
                },
            })
            print(f"Read clean baseline bins for unit {expected['id']}", flush=True)
    payload = {
        "version": 1, "session_id": population["session_id"], "asset": asset,
        "event": event, "baseline_rule": BASELINE_RULE, "units": units,
    }
    validate_baselines(payload, population)
    content = json.dumps(payload, separators=(",", ":"), allow_nan=False) + "\n"
    paths = [
        Path(__file__).resolve(), POPULATION_PATH, POPULATION_PROVENANCE,
        REPO_ROOT / "src/openscope_p3_publication/standard_oddball_baselines.py",
        REPO_ROOT / "src/openscope_p3_publication/standard_oddball_examples.py",
        REPO_ROOT / "src/openscope_p3_publication/standard_oddball_population.py",
        REPO_ROOT / "src/openscope_p3_publication/standard_oddball_neuropixels.py",
        REPO_ROOT / "src/openscope_p3_publication/neural_responses.py",
        REPO_ROOT / "src/openscope_p3_publication/mismatch_responsiveness.py",
        REPO_ROOT / "src/openscope_p3_publication/pupil_responses.py",
    ]
    provenance = {
        "version": 1, "asset": asset, "baseline_rule": BASELINE_RULE,
        "retrieved_date": dt.datetime.now(dt.UTC).date().isoformat(),
        "output_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "sources": [
            {"path": str(path.relative_to(REPO_ROOT)),
             "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in paths
        ],
        "trial_counts": {
            condition: len(record["trials"]) for condition, record in event["conditions"].items()
        },
        "source_verification": (
            "pinned asset metadata path/digest, clean trial records, unit metadata, and "
            "all full-unit spike-array SHA256 digests match committed population; "
            "full NWB not downloaded or rehashed"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.provenance_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content)
    args.provenance_output.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {args.output} ({len(content):,} bytes) and {args.provenance_output}")


if __name__ == "__main__":
    main()
