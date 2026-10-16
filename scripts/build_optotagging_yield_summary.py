"""Build the optotagging yield summary from per-unit metrics and unit locations.

Inputs:
- ``figure_sources/data/optotagging-results.parquet`` (committed per-unit metrics)
- ``.optotagging_work/optotagging-unit-areas.parquet`` (local, from
  ``scripts/extract_optotagging_unit_areas.py``; not committed)

Output: ``figure_sources/data/optotagging-static-summary.json`` with per-session tagged
counts overall, per Allen major division, and per structure (cortical layers collapsed).

Run with::

    uv run --with pyarrow --with iblatlas python scripts/build_optotagging_yield_summary.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from openscope_p3_publication.optotagging import optotagging_yield_summary

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_PATH = REPO_ROOT / "figure_sources" / "data" / "optotagging-results.parquet"
AREAS_PATH = REPO_ROOT / ".optotagging_work" / "optotagging-unit-areas.parquet"
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
    parser.add_argument("--areas", type=Path, default=AREAS_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()

    results = pd.read_parquet(args.results)
    areas = pd.read_parquet(args.areas)
    summary = optotagging_yield_summary(results, areas)
    areas_provenance_path = args.areas.with_name("optotagging-unit-areas.provenance.json")
    areas_provenance = json.loads(areas_provenance_path.read_text(encoding="utf-8"))
    summary["source"] = args.results.resolve().relative_to(REPO_ROOT).as_posix()
    summary["source_sha256"] = sha256(args.results)
    summary["unit_areas"] = {
        "generator": "scripts/extract_optotagging_unit_areas.py",
        "sha256": sha256(args.areas),
        "rows": len(areas),
        "retrieved_date": areas_provenance.get("retrieved_date"),
        "location_column": areas_provenance["columns"]["location"],
        "structure_rule": "cortical layer suffixes collapsed (e.g. VISp2/3 -> VISp)",
        "major_parent_rule": "nearest Allen major-division ancestor via iblatlas, else Other",
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
