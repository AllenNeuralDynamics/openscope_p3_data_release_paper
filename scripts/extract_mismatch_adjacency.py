"""Measure consecutive-mismatch adjacency across the public P3 Neuropixels NWBs.

Reads only the stimulus interval tables from every Neuropixels NWB in the
released Dandiset, measures how often a mismatch event immediately follows
another mismatch, and writes a compact committed intermediate plus provenance.

Each context block uses one pre-generated stimulus schedule, so the per-context
result is identical in every session. The extractor verifies that rather than
assuming it: the schedule hash must agree across sessions, or extraction fails.

Refresh (maintainer operation):

    uv run --with h5py --with numpy --with remfile \
        python scripts/extract_mismatch_adjacency.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from openscope_p3_publication.mismatch_adjacency import (  # noqa: E402
    SEQUENCE_GREY_TRIAL_TYPE,
    SEQUENCE_PERIOD_ROWS,
    adjacency_records,
    summarize_adjacency,
)

DEFAULT_OUTPUT = REPO_ROOT / "figure_sources" / "data" / "mismatch-adjacency.json"
DEFAULT_PROVENANCE_OUTPUT = DEFAULT_OUTPUT.with_suffix(".provenance.json")
DANDI_API = "https://api.dandiarchive.org/api"
DANDISET_ID = "001637"
DANDI_VERSION = "draft"
PAYLOAD_VERSION = 1
CONTEXT_TABLES = {
    "standard": "Standard mismatch block_presentations",
    "sequence": "Sequence mismatch block_presentations",
    "duration": "Duration mismatch block_presentations",
    "sensorimotor": "Sensory-motor mismatch block_presentations",
}
CONTEXT_ORDER = ("standard", "sequence", "duration", "sensorimotor")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--provenance-output", type=Path, default=DEFAULT_PROVENANCE_OUTPUT
    )
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--retrieved-date", default=dt.date.today().isoformat())
    return parser.parse_args()


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.load(response)


def list_assets() -> tuple[list[dict], str, str]:
    url = f"{DANDI_API}/dandisets/{DANDISET_ID}/versions/{DANDI_VERSION}/assets/?page_size=100"
    assets: list[dict] = []
    page_url = url
    while page_url:
        page = fetch_json(page_url)
        assets.extend(page["results"])
        page_url = page["next"]
    assets = [asset for asset in assets if asset["path"].endswith(".nwb")]
    assets.sort(key=lambda asset: asset["path"])
    manifest = json.dumps(
        [[asset["asset_id"], asset["path"]] for asset in assets],
        separators=(",", ":"),
    )
    return assets, url, hashlib.sha256(manifest.encode()).hexdigest()


def table_arrays(group) -> dict[str, np.ndarray]:
    return {
        "trial_type": np.asarray(group["TrialType"][:]).astype("U"),
        "orientation": np.asarray(group["Orientation"][:], dtype=float),
        "delay": np.asarray(group["Delay"][:], dtype=float),
        "start": np.asarray(group["start_time"][:], dtype=float),
        "stop": np.asarray(group["stop_time"][:], dtype=float),
        "block_number": np.asarray(group["BlockNumber"][:], dtype=float),
    }


def schedule_hash(arrays: dict[str, np.ndarray]) -> str:
    """Hash the schedule: trial-type order, orientation, delay. Excludes wall-clock time."""
    payload = (
        "\n".join(arrays["trial_type"].tolist()).encode()
        + np.round(arrays["orientation"], 6).tobytes()
        + np.round(arrays["delay"], 6).tobytes()
    )
    return hashlib.sha256(payload).hexdigest()


def verify_sequence_structure(arrays: dict[str, np.ndarray]) -> dict[str, int]:
    """Assert the five-row sequence layout the sequence adjacency rule depends on."""
    trial_type = arrays["trial_type"]
    grey = np.flatnonzero(trial_type == SEQUENCE_GREY_TRIAL_TYPE)
    if not len(grey):
        raise RuntimeError("Sequence block has no grey inter-sequence rows.")
    spacing = np.unique(np.diff(grey))
    if spacing.tolist() != [SEQUENCE_PERIOD_ROWS]:
        raise RuntimeError(
            f"Grey rows are not every {SEQUENCE_PERIOD_ROWS} rows: spacing {spacing.tolist()}"
        )
    if len(trial_type) % SEQUENCE_PERIOD_ROWS:
        raise RuntimeError("Sequence block row count is not a multiple of the period.")
    return {"grey_rows": int(len(grey)), "sequences": len(trial_type) // SEQUENCE_PERIOD_ROWS}


def inspect_asset(asset: dict) -> dict:
    import h5py
    import remfile

    url = f"{DANDI_API}/assets/{asset['asset_id']}/download/"
    result: dict = {"asset_id": asset["asset_id"], "path": asset["path"], "contexts": {}}
    with closing(remfile.File(url)) as remote, h5py.File(remote, "r") as nwb:
        result["subject"] = str(nwb["general/subject/subject_id"][()].decode())
        if "intervals" not in nwb:
            return result
        available = set(nwb["intervals"])
        for context, table in CONTEXT_TABLES.items():
            if table not in available:
                continue
            arrays = table_arrays(nwb[f"intervals/{table}"])
            records = adjacency_records(arrays, context)
            entry: dict = {
                "schedule_sha256": schedule_hash(arrays),
                "rows": int(len(arrays["trial_type"])),
                "summary": summarize_adjacency(records, context),
                "events": [
                    {
                        "row": record["row"],
                        "label": record["label"],
                        "adjacent": record["adjacent"],
                        "same_type": record["same_type"],
                        "interval": record["interval"],
                        "onset_offset_seconds": round(
                            record["onset_seconds"] - float(arrays["start"][0]), 4
                        ),
                    }
                    for record in records
                ],
                "block_duration_seconds": round(
                    float(arrays["stop"].max() - arrays["start"].min()), 4
                ),
            }
            if context == "sequence":
                entry["structure"] = verify_sequence_structure(arrays)
            result["contexts"][context] = entry
    return result


def collapse_contexts(results: list[dict]) -> dict[str, dict]:
    """One canonical record per context, after verifying every session agrees."""
    grouped: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for result in results:
        for context, entry in result["contexts"].items():
            grouped[context].append((result["subject"], entry))

    contexts: dict[str, dict] = {}
    for context in CONTEXT_ORDER:
        entries = grouped.get(context)
        if not entries:
            continue
        hashes = {entry["schedule_sha256"] for _subject, entry in entries}
        if len(hashes) != 1:
            raise RuntimeError(
                f"{context} stimulus schedule differs across sessions "
                f"({len(hashes)} distinct); the per-context collapse is invalid."
            )
        canonical = entries[0][1]
        durations = [entry["block_duration_seconds"] for _s, entry in entries]
        contexts[context] = {
            **canonical,
            "sessions": len(entries),
            "subjects": sorted({subject for subject, _entry in entries}),
            "schedule_identical_across_sessions": True,
            "block_duration_seconds_min": min(durations),
            "block_duration_seconds_max": max(durations),
        }
    return contexts


def main() -> None:
    args = parse_args()
    assets, asset_api_url, manifest_sha256 = list_assets()
    print(f"Scanning {len(assets)} Neuropixels assets", flush=True)

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        futures = {pool.submit(inspect_asset, asset): asset for asset in assets}
        for done, future in enumerate(as_completed(futures), 1):
            result = future.result()
            results.append(result)
            found = ",".join(result["contexts"]) or "none"
            print(f"  [{done}/{len(assets)}] {result.get('subject')} -> {found}", flush=True)

    results.sort(key=lambda result: result["path"])
    contexts = collapse_contexts(results)
    if not contexts:
        raise RuntimeError("No context blocks were found in the released assets.")

    payload = {
        "version": PAYLOAD_VERSION,
        "context_order": [c for c in CONTEXT_ORDER if c in contexts],
        "contexts": contexts,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )

    provenance = {
        "asset_api_url": asset_api_url,
        "asset_count": len(assets),
        "asset_manifest_sha256": manifest_sha256,
        "dandiset_id": DANDISET_ID,
        "dandiset_version": DANDI_VERSION,
        "notes": (
            "Interval tables are streamed with remfile; no spike or running data is read. "
            "Each context block uses one pre-generated stimulus schedule, verified by "
            "hashing the trial-type order, orientation, and delay columns and requiring "
            "agreement across every session, so one canonical result is stored per "
            "context. Sensorimotor adjacency is measured in elapsed time because mismatch "
            "events are embedded in a continuous 30 Hz phase-update stream."
        ),
        "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "retrieved_date": args.retrieved_date,
        "sessions_per_context": {
            context: entry["sessions"] for context, entry in contexts.items()
        },
        "source_module_sha256": hashlib.sha256(
            (REPO_ROOT / "src" / "openscope_p3_publication" / "mismatch_adjacency.py")
            .read_bytes()
        ).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    args.provenance_output.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote {args.output.relative_to(REPO_ROOT)}")
    print(f"Wrote provenance to {args.provenance_output.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
