"""Extract per-unit brain locations for the optotagging sessions.

Kept separate from ``optotagging-results.parquet`` so the metrics table stays
stats-only; join the two on ``session_id`` + ``unit_id``. The output is a local,
uncommitted cache (``.optotagging_work/``) read by
``scripts/build_optotagging_yield_summary.py``; only that compact summary is committed.

By default the exact asset IDs recorded in ``optotagging-results.provenance.json`` are
read, so unit IDs match the committed results even after the draft dandiset changes.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from openscope_p3_publication.optotagging import (
    SessionSkipped,
    discover_session_assets,
    pinned_session_assets,
    stream_unit_locations,
    write_unit_locations,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / ".optotagging_work"
RESULTS_PROVENANCE = REPO_ROOT / "figure_sources" / "data" / "optotagging-results.provenance.json"


def _read(asset: dict) -> tuple[dict, pd.DataFrame | None, str | None]:
    try:
        return asset, stream_unit_locations(asset), None
    except SessionSkipped as error:
        return asset, None, str(error)


def extract_unit_areas(
    output_dir: Path, workers: int, *, pin_to: Path | None = RESULTS_PROVENANCE
) -> tuple[Path, Path]:
    """Read every session's unit locations and write them only after all succeed."""

    assets = pinned_session_assets(pin_to) if pin_to else discover_session_assets()
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

    if not frames:
        raise RuntimeError("No sessions produced unit locations; nothing was written.")
    return write_unit_locations(
        pd.concat(frames, ignore_index=True),
        assets=assets,
        skipped=skipped,
        output_dir=output_dir,
    )


def main() -> None:
    """Run the explicit, cloud-backed unit-location snapshot refresh."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--current-draft",
        action="store_true",
        help="Read the current draft assets instead of the results snapshot's asset IDs.",
    )
    args = parser.parse_args()
    pin_to = None if args.current_draft else RESULTS_PROVENANCE
    for output_path in extract_unit_areas(args.output_dir, args.workers, pin_to=pin_to):
        print(output_path)


if __name__ == "__main__":
    main()
