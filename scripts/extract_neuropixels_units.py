"""Extract the release-wide Neuropixels unit table with brain areas from DANDI:001637.

Streams every session NWB in the current draft, records one row per unit (noise
included) with QC metrics, the extremum-channel location and CCF coordinates, and the
Allen parent area and major division. Writes ``neuropixels-units.parquet`` and its
provenance only after every session has been read.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from openscope_p3_publication.optotagging import discover_session_assets
from openscope_p3_publication.units import (
    SessionSkipped,
    build_unit_table,
    stream_session_unit_table,
    write_unit_table,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "figure_sources" / "data"


def _read(asset: dict) -> tuple[dict, pd.DataFrame | None, str | None]:
    try:
        return asset, stream_session_unit_table(asset), None
    except SessionSkipped as error:
        return asset, None, str(error)


def extract_units(output_dir: Path, workers: int) -> tuple[Path, Path]:
    """Read every session and write the table only if all reads succeed."""

    assets = discover_session_assets()
    frames = []
    skipped = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for index, (asset, frame, reason) in enumerate(pool.map(_read, assets), start=1):
            print(f"[{index}/{len(assets)}] {asset['asset_path']}", flush=True)
            if reason is not None:
                skipped.append({"asset_path": asset["asset_path"], "reason": reason})
                print(f"Skipped: {reason}", flush=True)
                continue
            frames.append(frame)
    if skipped:
        raise RuntimeError(
            f"{len(skipped)} of {len(assets)} sessions were skipped; nothing was written."
        )
    if not frames:
        raise RuntimeError("No sessions produced unit rows; nothing was written.")
    return write_unit_table(
        build_unit_table(frames),
        assets=assets,
        skipped=skipped,
        output_dir=output_dir,
    )


def main() -> None:
    """Run the explicit, cloud-backed unit-table refresh."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    for output_path in extract_units(args.output_dir, args.workers):
        print(output_path)


if __name__ == "__main__":
    main()
