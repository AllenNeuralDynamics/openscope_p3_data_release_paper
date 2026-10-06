"""Verify the existing WaveMAP asset manifest using DANDI metadata only."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVENANCE = ROOT / "figure_sources/data/wavemap/wavemap-analysis.provenance.json"
ORIGINAL_COMMIT = "e7bc61f07e105e65672f25bab830e62dd06f426a"


def verified_asset(record: dict, metadata: dict, snapshot_date: str) -> dict:
    """Match current archive metadata to an existing snapshot source record."""
    if (
        metadata["identifier"] != record["asset_id"]
        or metadata["path"] != record["path"]
        or metadata["contentSize"] != record["size_bytes"]
    ):
        raise RuntimeError(f"DANDI asset identity changed: {record['asset_id']}")
    digest = metadata.get("digest", {}).get("dandi:sha2-256", "")
    if len(digest) != 64:
        raise RuntimeError(f"DANDI asset lacks SHA-256: {record['asset_id']}")
    modified = metadata["blobDateModified"]
    if dt.datetime.fromisoformat(modified) > dt.datetime.fromisoformat(snapshot_date):
        raise RuntimeError(f"Asset blob postdates the snapshot: {record['asset_id']}")
    return {
        **record,
        "metadata_url": f"https://api.dandiarchive.org/api/assets/{record['asset_id']}/",
        "content_urls": metadata["contentUrl"],
        "digest": metadata["digest"],
        "blob_modified": modified,
    }


def main() -> None:
    """Enrich provenance only after all source records pass metadata verification."""
    provenance = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    snapshot = PROVENANCE.parent / provenance["snapshot"]
    snapshot_digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    if snapshot_digest != provenance["snapshot_sha256"]:
        raise RuntimeError("Refusing to update provenance for a changed snapshot.")

    def fetch_record(record: dict) -> dict:
        url = f"https://api.dandiarchive.org/api/assets/{record['asset_id']}/"
        request = urllib.request.Request(url, headers={"User-Agent": "OpenScope-provenance"})
        with urllib.request.urlopen(request, timeout=60) as response:
            metadata = json.load(response)
        return verified_asset(record, metadata, provenance["generated_utc"])

    with ThreadPoolExecutor(max_workers=4) as executor:
        records = list(executor.map(fetch_record, provenance["source"]["assets"]))
    provenance["source"]["assets"] = records
    provenance["metadata_verified_utc"] = dt.datetime.now(dt.UTC).isoformat()
    provenance["metadata_verification"] = (
        "Asset IDs, paths, sizes and blob modification dates were checked against "
        "the existing manifest. Checksums are from archive metadata; NWB payloads "
        "were not downloaded or reanalysed. The original snapshot is unchanged."
    )
    provenance["analysis"]["random_seed"] = 42
    provenance["analysis"]["seed_source"] = f"RAND_STATE in contributed source {ORIGINAL_COMMIT}"
    provenance["analysis"]["original_source_url"] = (
        "https://github.com/AllenNeuralDynamics/openscope_p3_data_release_paper/"
        f"blob/{ORIGINAL_COMMIT}/scripts/extract_wavemap_analysis.py"
    )
    provenance["analysis"]["software_versions"] = None
    provenance["analysis"]["software_versions_note"] = (
        "The original extraction environment was not recorded in the contribution. "
        "The publication renderer's dependencies are locked separately in uv.lock."
    )
    provenance["waveform_time_calibration"] = {
        "recorded_rates_available": False,
        "original_fallback_hz": 30000.0,
        "publication_axis": "sample index",
        "note": "Per-unit waveform rates are absent; the fallback is not treated as verified.",
    }
    provenance["exclusions"] = [
        {
            "session_id": "ecephys_832691_2026-03-25_10-22-33",
            "reason": "FAIL: mouse stress in the committed experimental session inventory",
            "source": "figure_sources/data/experimental-sessions.csv",
        }
    ]
    if hashlib.sha256(snapshot.read_bytes()).hexdigest() != snapshot_digest:
        raise RuntimeError("Snapshot changed during metadata verification.")
    PROVENANCE.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"Verified {len(records)} source asset records; snapshot bytes unchanged.")


if __name__ == "__main__":
    main()
