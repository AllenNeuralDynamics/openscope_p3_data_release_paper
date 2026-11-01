#!/usr/bin/env python3
"""Extract only the fixed non-modulated cortical example from the pinned NWB."""

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

from openscope_p3_publication.neural_responses import NEURAL_SESSIONS, SDF_SOURCE_BIN_SECONDS
from openscope_p3_publication.standard_oddball_comparison import (
    COMPARISON_PATH,
    COMPARISON_PROVENANCE,
    COMPARISON_RULE,
    comparison_selection,
    validate_comparison_spikes,
)
from openscope_p3_publication.standard_oddball_examples import (
    PADDING_BINS,
    SOURCE_START,
    WINDOW,
    aligned_trial_spikes,
    example_trial_records,
    load_example_spikes,
)
from openscope_p3_publication.standard_oddball_neuropixels import (
    DATA_PATH,
    REPO_ROOT,
    load_diagnostic,
)
from openscope_p3_publication.standard_oddball_population import (
    EVENT_ID,
    POPULATION_PATH,
    POPULATION_PROVENANCE,
    load_population,
)

SOURCE_VERIFICATION = (
    "pinned asset metadata path/digest, exact clean trials, unit metadata, and "
    "full-unit spike digest; float64-roundoff SDF/exact baseline matches committed "
    "population; full NWB not downloaded or rehashed"
)


def refresh_validation_provenance(path: Path, provenance_path: Path) -> None:
    """Revalidate frozen spikes offline, preserving extraction hashes and payload bytes."""
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if hashlib.sha256(path.read_bytes()).hexdigest() != provenance["output_sha256"]:
        raise ValueError("Comparison spike snapshot checksum mismatch.")
    validation_sources = {
        "scripts/extract_neuropixels_standard_oddball_comparison.py",
        "src/openscope_p3_publication/standard_oddball_comparison.py",
    }
    for source in provenance["sources"]:
        actual = hashlib.sha256((REPO_ROOT / source["path"]).read_bytes()).hexdigest()
        if actual != source["sha256"]:
            if source["path"].replace("\\", "/") not in validation_sources:
                raise ValueError(f"Comparison extraction source changed: {source['path']}")
            source.setdefault("extraction_sha256", source["sha256"])
            source["sha256"] = actual
    data = load_diagnostic()
    population = load_population(data, load_example_spikes(data)["events"][1])
    validate_comparison_spikes(json.loads(path.read_text(encoding="utf-8")), data, population)
    provenance["source_verification"] = SOURCE_VERIFICATION
    provenance["validation_refreshed_date"] = dt.datetime.now(dt.UTC).date().isoformat()
    provenance_path.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n",
    )
    print(f"Revalidated {path}; refreshed {provenance_path} without changing spike data.")


def main() -> None:
    """Write a one-unit spike sidecar, or refresh its validation provenance offline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=COMPARISON_PATH)
    parser.add_argument("--provenance-output", type=Path, default=COMPARISON_PROVENANCE)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--refresh-validation-provenance", action="store_true")
    args = parser.parse_args()
    if args.refresh_validation_provenance:
        refresh_validation_provenance(args.output, args.provenance_output)
        return
    if not args.overwrite and (args.output.exists() or args.provenance_output.exists()):
        raise SystemExit("Comparison output exists; inspect it before passing --overwrite.")
    import remfile

    data = load_diagnostic()
    selection = comparison_selection(data)
    population = load_population(data, load_example_spikes(data)["events"][1])
    asset = data.session["asset"]
    with urllib.request.urlopen(
        f"https://api.dandiarchive.org/api/assets/{asset['assetId']}/", timeout=180,
    ) as response:
        detail = json.load(response)
    if detail["path"] != asset["path"] or detail["digest"] != asset["digest"]:
        raise ValueError("Pinned standard-session asset identity or digest changed.")
    config = next(s for s in NEURAL_SESSIONS if s.context == "standard")
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
        events = example_trial_records(tables, event_ids=(EVENT_ID,))
        if events != [population["event"]]:
            raise ValueError("Pinned NWB clean trial identities or timing changed.")
        record, = selection
        expected = data.units[record["index"]]
        ids = np.asarray(nwb["units/id"][:])
        matching = np.flatnonzero(ids == record["unit_id"])
        if len(matching) != 1:
            raise ValueError("Comparison unit did not match exactly one NWB row.")
        row = int(matching[0])
        label = nwb["units/decoder_label"][row]
        label = label.decode() if isinstance(label, bytes) else str(label)
        if (
            label != "sua" or nwb["units/ks_unit_id"][row] != expected["ksUnitId"]
            or not np.isclose(
                nwb["units/firing_rate"][row], expected["firingRateHz"], atol=1e-6, rtol=0,
            )
        ):
            raise ValueError("Comparison unit NWB metadata changed.")
        ends = np.asarray(nwb["units/spike_times_index"][:], dtype=int)
        spikes = np.asarray(
            nwb["units/spike_times"][0 if row == 0 else ends[row - 1]:ends[row]], dtype=float,
        )
        unit = {
            "id": record["unit_id"], "nwb_units_row": row,
            "source_spike_array_sha256": hashlib.sha256(spikes.astype("<f8").tobytes()).hexdigest(),
            "spikes": {
                EVENT_ID: {
                    condition: aligned_trial_spikes(spikes, trial_record["trials"])
                    for condition, trial_record in events[0]["conditions"].items()
                },
            },
        }
    payload = {
        "version": 1, "session_id": data.session["sessionId"], "asset": asset,
        "selection_rule": COMPARISON_RULE, "selection": selection,
        "source_window_seconds": [SOURCE_START, WINDOW[1]], "display_window_seconds": list(WINDOW),
        "padding_bins": PADDING_BINS, "bin_seconds": SDF_SOURCE_BIN_SECONDS,
        "events": events, "units": [unit],
    }
    validate_comparison_spikes(payload, data, population)
    content = json.dumps(payload, separators=(",", ":"), allow_nan=False) + "\n"
    paths = [
        Path(__file__).resolve(), DATA_PATH, POPULATION_PATH, POPULATION_PROVENANCE,
        REPO_ROOT / "src/openscope_p3_publication/standard_oddball_comparison.py",
        REPO_ROOT / "src/openscope_p3_publication/standard_oddball_candidates.py",
        REPO_ROOT / "src/openscope_p3_publication/standard_oddball_examples.py",
        REPO_ROOT / "src/openscope_p3_publication/standard_oddball_population.py",
        REPO_ROOT / "src/openscope_p3_publication/standard_oddball_neuropixels.py",
        REPO_ROOT / "src/openscope_p3_publication/neural_responses.py",
        REPO_ROOT / "src/openscope_p3_publication/mismatch_responsiveness.py",
        REPO_ROOT / "src/openscope_p3_publication/pupil_responses.py",
    ]
    provenance = {
        "version": 1, "asset": asset, "selection_rule": COMPARISON_RULE,
        "retrieved_date": dt.datetime.now(dt.UTC).date().isoformat(),
        "output_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "sources": [
            {"path": path.relative_to(REPO_ROOT).as_posix(),
             "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in paths
        ],
        "trial_counts": {
            condition: len(record["trials"])
            for condition, record in events[0]["conditions"].items()
        },
        "spike_offsets": "native float64 differences in padded half-open trial windows",
        "source_verification": SOURCE_VERIFICATION,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.provenance_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content, encoding="utf-8", newline="\n")
    args.provenance_output.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n",
    )
    print(f"Wrote {args.output} ({len(content):,} bytes) and {args.provenance_output}")


if __name__ == "__main__":
    main()
