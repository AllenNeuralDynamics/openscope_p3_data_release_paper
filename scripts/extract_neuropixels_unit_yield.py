#!/usr/bin/env python3
"""Extract per-session Neuropixels unit yield from a public DANDI dandiset."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    import h5py
    import numpy as np
    import remfile
except ImportError as exc:  # pragma: no cover - optional extraction environment
    raise SystemExit(
        "Run with: uv run --with h5py --with numpy --with remfile "
        "python scripts/extract_neuropixels_unit_yield.py"
    ) from exc


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "figure_sources" / "data" / "neuropixels-unit-yield.csv"
DEFAULT_PROVENANCE_OUTPUT = DEFAULT_OUTPUT.with_suffix(".provenance.json")
DANDISET_ID = "001637"
DANDI_VERSION = "draft"
ASSET_LIST_URL = (
    f"https://api.dandiarchive.org/api/dandisets/{DANDISET_ID}/"
    f"versions/{DANDI_VERSION}/assets/?page_size=100"
)
SOURCE_URL = f"https://dandiarchive.org/dandiset/{DANDISET_ID}/{DANDI_VERSION}"
SESSION_PATTERN = re.compile(
    r"sub-(?P<mouse_id>\d+)/sub-(?P=mouse_id)_ses-ecephys-"
    r"(?P=mouse_id)-(?P<date>\d{4}-\d{2}-\d{2})-(?P<time>\d{2}-\d{2}-\d{2})"
)
QC_THRESHOLDS = {
    "amplitude_cutoff_max": 0.1,
    "isi_violations_ratio_max": 0.5,
    "presence_ratio_min": 0.8,
}
CSV_FIELDS = (
    "dandiset_id",
    "asset_id",
    "asset_path",
    "session_id",
    "mouse_id",
    "date",
    "total_unit_count",
    "qc_unit_count",
    "probe_count",
    "probe_names",
)


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    token = os.environ.get("DANDI_API_KEY")
    if token:
        request.add_header("Authorization", f"token {token}")
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def list_assets() -> list[dict]:
    page_url = ASSET_LIST_URL
    assets = []
    while page_url:
        page = fetch_json(page_url)
        assets.extend(page["results"])
        page_url = page["next"]
    return sorted(assets, key=lambda asset: asset["path"])


def parse_session(path: str) -> dict[str, str]:
    match = SESSION_PATTERN.search(path)
    if not match:
        raise ValueError(f"Could not parse ecephys session from asset path: {path}")
    values = match.groupdict()
    return {
        "date": values["date"],
        "mouse_id": values["mouse_id"],
        "session_id": f"{values['mouse_id']}_{values['date']}_{values['time']}",
    }


def inspect_asset(asset: dict) -> tuple[dict | None, dict | None]:
    path = asset["path"]
    if not path.endswith(".nwb") or "probe" in path.lower():
        return None, {"asset_id": asset["asset_id"], "path": path, "reason": "not-session-nwb"}

    remote = remfile.File(
        f"https://api.dandiarchive.org/api/assets/{asset['asset_id']}/download/"
    )
    try:
        with h5py.File(remote, mode="r") as nwb:
            if "units" not in nwb:
                return None, {
                    "asset_id": asset["asset_id"],
                    "path": path,
                    "reason": "missing-units-table",
                }
            units = nwb["units"]
            required = {"id", "isi_violations_ratio", "presence_ratio", "amplitude_cutoff"}
            missing = sorted(required - set(units))
            if missing:
                return None, {
                    "asset_id": asset["asset_id"],
                    "path": path,
                    "reason": f"missing-unit-columns:{','.join(missing)}",
                }
            ephys = nwb.get("general/extracellular_ephys")
            probe_names = sorted(
                name
                for name, value in (ephys.items() if ephys is not None else [])
                if name.lower().startswith("probe") and isinstance(value, h5py.Group)
            )
            if not probe_names:
                return None, {
                    "asset_id": asset["asset_id"],
                    "path": path,
                    "reason": "missing-probe-groups",
                }

            isi_violations = np.asarray(units["isi_violations_ratio"], dtype=float)
            presence_ratio = np.asarray(units["presence_ratio"], dtype=float)
            amplitude_cutoff = np.asarray(units["amplitude_cutoff"], dtype=float)
            qc_mask = (
                (isi_violations < QC_THRESHOLDS["isi_violations_ratio_max"])
                & (presence_ratio > QC_THRESHOLDS["presence_ratio_min"])
                & (amplitude_cutoff < QC_THRESHOLDS["amplitude_cutoff_max"])
            )
            session = parse_session(path)
            return (
                {
                    "dandiset_id": DANDISET_ID,
                    "asset_id": asset["asset_id"],
                    "asset_path": path,
                    **session,
                    "total_unit_count": len(units["id"]),
                    "qc_unit_count": int(np.count_nonzero(qc_mask)),
                    "probe_count": len(probe_names),
                    "probe_names": ";".join(probe_names),
                },
                None,
            )
    finally:
        remote.close()


def extract_assets(assets: list[dict], max_workers: int) -> tuple[list[dict], list[dict]]:
    records = []
    skipped = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(inspect_asset, asset): asset for asset in assets}
        for completed, future in enumerate(as_completed(futures), start=1):
            asset = futures[future]
            record, skip = future.result()
            if record:
                records.append(record)
                detail = (
                    f"{record['qc_unit_count']}/{record['total_unit_count']} QC units, "
                    f"{record['probe_count']} probes"
                )
            else:
                skipped.append(skip)
                detail = skip["reason"]
            print(f"[{completed}/{len(assets)}] {asset['path']}: {detail}")
    records.sort(key=lambda row: (row["mouse_id"], row["date"], row["session_id"]))
    skipped.sort(key=lambda row: row["path"])
    return records, skipped


def write_outputs(
    records: list[dict],
    skipped: list[dict],
    assets: list[dict],
    output: Path,
    provenance_output: Path,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
    manifest = [
        {
            "asset_id": asset["asset_id"],
            "modified": asset["modified"],
            "path": asset["path"],
            "size": asset["size"],
        }
        for asset in assets
    ]
    provenance = {
        "version": 1,
        "dandiset_id": DANDISET_ID,
        "dandiset_version": DANDI_VERSION,
        "source_url": SOURCE_URL,
        "asset_api_url": ASSET_LIST_URL,
        "retrieved_date": dt.date.today().isoformat(),
        "asset_manifest_sha256": hashlib.sha256(
            json.dumps(manifest, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest(),
        "vendored_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "rows": len(records),
        "subjects": len({row["mouse_id"] for row in records}),
        "qc_thresholds": QC_THRESHOLDS,
        "skipped_assets": skipped,
        "notes": (
            "Session NWBs are streamed with remfile. QC-passing units satisfy all three "
            "thresholds; probe count is the number of Probe* electrode groups."
        ),
    }
    provenance_output.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--provenance-output", type=Path, default=DEFAULT_PROVENANCE_OUTPUT)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    assets = list_assets()
    selected_assets = assets[: args.limit] if args.limit else assets
    print(f"Dandiset {DANDISET_ID}: inspecting {len(selected_assets)} of {len(assets)} assets")
    records, skipped = extract_assets(selected_assets, args.max_workers)
    if not records:
        raise SystemExit("No unit-bearing ecephys sessions were found.")
    write_outputs(records, skipped, selected_assets, args.output, args.provenance_output)
    print(f"Wrote {len(records)} rows to {args.output}")
    print(f"Wrote provenance to {args.provenance_output}")


if __name__ == "__main__":
    main()