"""Build the optotagging yield summary from per-unit metrics and the unit table.

Inputs (both committed):
- ``figure_sources/data/optotagging-results.parquet`` (per-unit optotagging metrics)
- ``figure_sources/data/neuropixels-units.parquet`` (``brain_division``/``brain_area``)

Output: ``figure_sources/data/optotagging-static-summary.json`` with per-session tagged
counts overall, per Allen major division, and per brain area.

Run with::

    uv run --with pyarrow --with scipy python scripts/build_optotagging_yield_summary.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from openscope_p3_publication.optotagging import optotagging_yield_summary
from openscope_p3_publication.units import UNIT_TABLE_NAME, UNIT_TABLE_PROVENANCE_NAME

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_PATH = REPO_ROOT / "figure_sources" / "data" / "optotagging-results.parquet"
UNIT_TABLE_PATH = REPO_ROOT / "figure_sources" / "data" / UNIT_TABLE_NAME
OUTPUT_PATH = REPO_ROOT / "figure_sources" / "data" / "optotagging-static-summary.json"
REPRESENTATIVE_SESSIONS = (
    "ecephys_830851_2026-03-19_10-49-11",
    "ecephys_848390_2026-05-06_09-54-56",
    "ecephys_832691_2026-03-24_10-04-30",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def representative_sessions(sessions: list[str], counts: list[int]) -> list[dict]:
    """Report each fixed example session's tagged count and all-session yield percentile.

    The percentile is the share of sessions with a tagged count at or below the example's.
    """

    values = np.asarray(counts, dtype=int)
    picks = []
    for session_id in REPRESENTATIVE_SESSIONS:
        count = int(values[sessions.index(session_id)])
        picks.append(
            {
                "session_id": session_id,
                "tagged_units": count,
                "rank": int(np.sum(values < count)) + 1,
                "percentile": round(100.0 * float(np.mean(values <= count)), 1),
            }
        )
    return picks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--results", type=Path, default=RESULTS_PATH)
    parser.add_argument("--unit-table", type=Path, default=UNIT_TABLE_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()

    results = pd.read_parquet(args.results)
    unit_table = pd.read_parquet(
        args.unit_table, columns=["session_id", "unit_id", "brain_division", "brain_area"]
    )
    summary = optotagging_yield_summary(results, unit_table)
    unit_provenance = json.loads(
        args.unit_table.with_name(UNIT_TABLE_PROVENANCE_NAME).read_text(encoding="utf-8")
    )
    summary["source"] = args.results.resolve().relative_to(REPO_ROOT).as_posix()
    summary["source_sha256"] = sha256(args.results)
    summary["unit_table"] = {
        "source": args.unit_table.resolve().relative_to(REPO_ROOT).as_posix(),
        "sha256": sha256(args.unit_table),
        "retrieved_date": unit_provenance["retrieved_date"],
        "major_parent_column": "brain_division",
        "structure_column": "brain_area",
    }
    summary["representative_sessions"] = representative_sessions(
        summary["sessions"], summary["overall"]["counts"]
    )
    args.output.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"Wrote {args.output}")
    print(json.dumps(summary["representative_sessions"], indent=2))


if __name__ == "__main__":
    main()
