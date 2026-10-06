"""Extract per-unit optotagging statistics from the public Neuropixels NWBs."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from openscope_p3_publication.optotagging import (
    DEFAULT_OUTPUT_DIR,
    SessionSkipped,
    analyze_asset,
    discover_session_assets,
    write_results,
)


def extract_results(output_dir: Path) -> tuple[Path, Path]:
    """Analyze all available sessions and write metrics only after they succeed."""

    assets = discover_session_assets()
    frames = []
    skipped = []
    for asset_index, asset in enumerate(assets, start=1):
        print(f"[{asset_index}/{len(assets)}] {asset['asset_path']}", flush=True)
        try:
            analysis = analyze_asset(asset)
        except SessionSkipped as error:
            skipped.append({"asset_path": asset["asset_path"], "reason": str(error)})
            print(f"Skipped: {error}", flush=True)
            continue
        frames.append(analysis.metrics)

    if not frames:
        raise RuntimeError("No sessions produced optotagging metrics; no results were written.")

    return write_results(
        pd.concat(frames, ignore_index=True),
        assets=assets,
        skipped=skipped,
        failed=[],
        output_dir=output_dir,
    )


def main() -> None:
    """Run the explicit, cloud-backed optotagging snapshot refresh."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for the Parquet results and provenance; existing outputs are replaced.",
    )
    args = parser.parse_args()
    for output_path in extract_results(args.output_dir):
        print(output_path)


if __name__ == "__main__":
    main()