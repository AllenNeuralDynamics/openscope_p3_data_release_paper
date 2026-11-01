#!/usr/bin/env python3
"""Extract standard-oddball examples or clean visual population means from the pinned NWB."""

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
from openscope_p3_publication.standard_oddball_examples import (
    EXAMPLES_PATH,
    EXAMPLES_PROVENANCE,
    PADDING_BINS,
    SELECTION_RULE,
    SOURCE_START,
    WINDOW,
    aligned_trial_spikes,
    example_trial_records,
    load_example_spikes,
    trial_mean_sdf,
    validate_example_spikes,
)
from openscope_p3_publication.standard_oddball_neuropixels import (
    DATA_PATH,
    EVENTS,
    REPO_ROOT,
    example_selections,
    load_diagnostic,
)
from openscope_p3_publication.standard_oddball_population import (
    EVENT_ID,
    PARAMETERS,
    POPULATION_PATH,
    POPULATION_PROVENANCE,
    POPULATION_RULE,
    summarize_spike_trials,
    validate_population,
)
from openscope_p3_publication.standard_oddball_regional_examples import (
    ORIENTATIONS,
    REGIONAL_PATH,
    REGIONAL_PROVENANCE,
    REGIONAL_SELECTION_RULE,
    regional_selections,
)


def main() -> None:
    """Read versioned public source ranges and write a compact traceable snapshot."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gallery", choices=("visual", "regional", "population90"), default="visual",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--provenance-output", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    regional = args.gallery == "regional"
    population = args.gallery == "population90"
    args.output = args.output or (
        POPULATION_PATH if population else REGIONAL_PATH if regional else EXAMPLES_PATH
    )
    args.provenance_output = args.provenance_output or (
        POPULATION_PROVENANCE if population else
        REGIONAL_PROVENANCE if regional else EXAMPLES_PROVENANCE
    )
    selection_rule = (
        POPULATION_RULE if population else REGIONAL_SELECTION_RULE if regional else SELECTION_RULE
    )
    event_ids = (EVENT_ID,) if population else ORIENTATIONS if regional else EVENTS
    if not args.overwrite and (args.output.exists() or args.provenance_output.exists()):
        raise SystemExit(
            "Output already exists; inspect it first, then pass --overwrite deliberately."
        )
    import remfile

    data = load_diagnostic(visual_only=not regional)
    asset = data.session["asset"]
    detail_url = f"https://api.dandiarchive.org/api/assets/{asset['assetId']}/"
    with urllib.request.urlopen(detail_url, timeout=180) as response:
        detail = json.load(response)
    if detail["path"] != asset["path"] or detail["digest"] != asset["digest"]:
        raise ValueError("Pinned standard-session asset identity or digest changed.")
    selection = (
        [{"index": i, "unit_id": u["id"], "label": u["location"]}
         for i, u in enumerate(data.units)]
        if population else regional_selections(data) if regional else example_selections(data)
    )
    config = next(s for s in NEURAL_SESSIONS if s.context == "standard")
    print(
        f"Reading pinned asset {asset['assetId']}; "
        f"selected units {[s['unit_id'] for s in selection]}"
    )
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
        events = example_trial_records(tables, event_ids=event_ids)
        ids = np.asarray(nwb["units/id"][:])
        ends = np.asarray(nwb["units/spike_times_index"][:], dtype=int)
        units = []
        for record in selection:
            matching = np.flatnonzero(ids == record["unit_id"])
            if len(matching) != 1:
                raise ValueError(f"Selected unit {record['unit_id']} did not match one NWB row.")
            row = int(matching[0])
            expected = data.units[record["index"]]
            label = nwb["units/decoder_label"][row]
            label = label.decode() if isinstance(label, bytes) else str(label)
            if (
                label != "sua" or nwb["units/ks_unit_id"][row] != expected["ksUnitId"]
                or not np.isclose(
                    nwb["units/firing_rate"][row], expected["firingRateHz"], atol=1e-6, rtol=0,
                )
            ):
                raise ValueError(f"Selected unit {record['unit_id']} metadata changed.")
            spikes = np.asarray(
                nwb["units/spike_times"][0 if row == 0 else ends[row - 1]:ends[row]],
                dtype=float,
            )
            spike_trials = {
                event["id"]: {
                    condition: aligned_trial_spikes(spikes, values["trials"])
                    for condition, values in event["conditions"].items()
                }
                for event in events
            }
            unit_record = {
                "id": record["unit_id"], "nwb_units_row": row,
                "source_spike_array_sha256": hashlib.sha256(
                    spikes.astype("<f8").tobytes()
                ).hexdigest(),
            }
            if population:
                unit_record["conditions"] = {
                    condition: summarize_spike_trials(
                        spike_trials[EVENT_ID][condition], values["trials"],
                    )
                    for condition, values in events[0]["conditions"].items()
                }
                native_control = trial_mean_sdf(spike_trials[EVENT_ID]["control"])
                if (
                    not np.allclose(
                        native_control, data.rates[1, 1, record["index"]], atol=0.0251, rtol=0,
                    )
                    or not np.isclose(
                        unit_record["conditions"]["control"]["baseline_mean_hz"],
                        data.baseline_mean[1, 1, record["index"]], atol=1e-5, rtol=1e-6,
                    )
                ):
                    raise ValueError(
                        f"Released control reconstruction failed: unit {record['unit_id']}"
                    )
            else:
                unit_record["spikes"] = spike_trials
            units.append(unit_record)
            print(
                f"Read unit {record['unit_id']} ({record['label']}), {len(spikes)} assigned spikes"
            )
    payload = {
        "version": 1, "session_id": data.session["sessionId"], "asset": asset,
        "selection_rule": selection_rule, "selection": selection,
        "source_window_seconds": [SOURCE_START, WINDOW[1]], "display_window_seconds": list(WINDOW),
        "padding_bins": PADDING_BINS, "bin_seconds": SDF_SOURCE_BIN_SECONDS,
        "events": events, "units": units,
    }
    if population:
        payload = {
            "version": 1, "session_id": data.session["sessionId"], "asset": asset,
            "selection_rule": POPULATION_RULE, "parameters": PARAMETERS,
            "event": events[0], "units": units,
        }
        reference = load_example_spikes(data)["events"][1]
        validate_population(payload, data, reference)
    else:
        validate_example_spikes(
            payload, data, selection=selection, selection_rule=selection_rule, event_ids=event_ids,
        )
    content = json.dumps(payload, separators=(",", ":"), allow_nan=False) + "\n"
    paths = [
        DATA_PATH, Path(__file__).resolve(),
        REPO_ROOT / "src/openscope_p3_publication/standard_oddball_neuropixels.py",
        REPO_ROOT / "src/openscope_p3_publication/standard_oddball_examples.py",
        REPO_ROOT / "src/openscope_p3_publication/neural_responses.py",
        REPO_ROOT / "src/openscope_p3_publication/mismatch_responsiveness.py",
        REPO_ROOT / "src/openscope_p3_publication/pupil_responses.py",
    ]
    if regional:
        paths.append(
            REPO_ROOT / "src/openscope_p3_publication/standard_oddball_regional_examples.py"
        )
    if population:
        paths.extend([
            REPO_ROOT / "src/openscope_p3_publication/standard_oddball_population.py",
            EXAMPLES_PATH, EXAMPLES_PROVENANCE,
        ])
    provenance = {
        "version": 1, "asset": asset, "retrieved_date": dt.datetime.now(dt.UTC).date().isoformat(),
        "output_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "sources": [
            {
                "path": str(path.relative_to(REPO_ROOT)),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in paths
        ],
        "selection_rule": selection_rule, "source_window_seconds": [SOURCE_START, WINDOW[1]],
        "trial_rule": (
            "clean context using existing adjacent-mismatch exclusion; all matched controls"
        ),
        "spike_offsets": (
            "native float64 differences; only condition mean SDFs and baselines retained"
            if population else
            "native float64 differences from trial onsets; no rounding or quantization"
        ),
        "source_verification": (
            "pinned asset metadata digest/path; full NWB not downloaded or rehashed"
        ),
        "empty_trials": "retained as empty arrays",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.provenance_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content, encoding="utf-8")
    args.provenance_output.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    print(f"Wrote {args.output} ({len(content):,} bytes) and {args.provenance_output}")


if __name__ == "__main__":
    main()
