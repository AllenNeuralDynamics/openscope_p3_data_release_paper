"""Freeze exact Figure 9 cohort summaries without committing analysis-scale unit tables."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import pandas as pd

from openscope_p3_publication.mesoscope_standard_oddball import ROOT, sha256
from openscope_p3_publication.mesoscope_standard_oddball import load_snapshot as load_mesoscope
from openscope_p3_publication.mesoscope_standard_oddball_cohort import (
    COHORT_DIR as MESOSCOPE_COHORT_DIR,
)
from openscope_p3_publication.mesoscope_standard_oddball_cohort import (
    load_cohort as load_mesoscope_analysis,
)
from openscope_p3_publication.mesoscope_standard_oddball_cohort_figure import (
    prepare_cohort_panel as prepare_mesoscope,
)
from openscope_p3_publication.standard_oddball_cohort import COHORT_DIR, EVENTS, load_cohort
from openscope_p3_publication.standard_oddball_cohort_figure import prepare_cohort_panel
from openscope_p3_publication.standard_oddball_neuropixels import load_diagnostic
from openscope_p3_publication.standard_oddball_publication_data import DIRECTORY, STATISTICS


def encode_frame(frame: pd.DataFrame) -> dict:
    """Freeze exact Python float representations, nulls, column order and dtypes."""
    return {
        "columns": frame.columns.tolist(),
        "dtypes": {column: str(dtype) for column, dtype in frame.dtypes.items()},
        "records": frame.astype(object).where(pd.notna(frame), None).to_dict("records"),
    }


def source_statistics(frame: pd.DataFrame, session: str, keys: list[str], id_column: str) -> list:
    """Keep each displayed source's existing statistics, never rerunning its tests."""
    rows = frame.loc[frame.session_id.eq(session)].copy()
    if "signal" in rows:
        rows = rows.loc[rows.signal.eq("dff")]
    rows["id"] = rows[id_column].astype(str)
    rows = rows.loc[rows.id.isin(keys), ["id", "event_id", "eligible", *STATISTICS]]
    if (
        len(rows) != len(keys) * len(EVENTS) or not rows.eligible.all()
        or rows.duplicated(["id", "event_id"]).any()
    ):
        raise ValueError("Publication example source identity or eligibility changed.")
    return rows.astype(object).where(pd.notna(rows), None).to_dict("records")


def refresh_renderer_provenance(directory: Path) -> None:
    """Refresh only serialization-code hashes, keeping frozen scientific bytes intact."""
    provenance_path = directory / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if sha256(directory / "cohorts.json") != provenance["output_sha256"]:
        raise ValueError("Publication cohort snapshot checksum changed.")
    renderer_sources = {
        "scripts/freeze_standard_oddball_publication.py",
        "src/openscope_p3_publication/mesoscope_standard_oddball_cohort_figure.py",
    }
    for source in provenance["inputs"]:
        actual = sha256(ROOT / source["path"])
        if actual != source["sha256"]:
            if source["path"].replace("\\", "/") not in renderer_sources:
                raise ValueError(f"Publication data source changed: {source['path']}")
            source.setdefault("frozen_source_sha256", source["sha256"])
            source["sha256"] = actual
    provenance["renderer_validation_refreshed_date"] = dt.datetime.now(dt.UTC).date().isoformat()
    provenance_path.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n",
    )
    print(f"Refreshed {provenance_path}; frozen counts/statistics were not changed.")


def main() -> None:
    """Freeze compact rendering inputs from the deliberately refreshed full analyses."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DIRECTORY)
    parser.add_argument("--refresh-renderer-provenance", action="store_true")
    args = parser.parse_args()
    if args.refresh_renderer_provenance:
        refresh_renderer_provenance(args.output)
        return
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite publication snapshot: {args.output}")
    _, _, np_provenance = load_cohort()
    np_units = pd.read_csv(
        COHORT_DIR / "units.csv.gz", float_precision="round_trip", dtype={"subject_id": str},
    )
    meso_units, inventory, meso_provenance = load_mesoscope_analysis()
    meso_prepared = prepare_mesoscope(meso_units)
    diagnostic = load_diagnostic()
    meso_payload, _, _ = load_mesoscope()
    data = {
        "version": 1,
        "neuropixels": {
            "events": {
                event: {k: encode_frame(v) for k, v in prepare_cohort_panel(
                    np_units, event=event,
                ).items()}
                for event in EVENTS
            },
            "provenance": {
                k: np_provenance[k] for k in (
                    "dandiset", "dandiset_version", "events", "session_count", "mouse_count",
                )
            },
        },
        "mesoscope": {
            "tables": {
                **{k: encode_frame(v) for k, v in meso_prepared.items()},
                "inventory": encode_frame(inventory),
            },
            "provenance": {
                k: meso_provenance[k] for k in (
                    "dandiset", "dandiset_version", "events", "session_count", "mouse_count",
                    "asset_manifest",
                )
            },
        },
        "example_statistics": {
            "neuropixels": source_statistics(
                np_units, diagnostic.session["sessionId"], [str(u["id"]) for u in diagnostic.units],
                "nwb_unit_id",
            ),
            "mesoscope": source_statistics(
                meso_units, meso_payload["session_id"], meso_payload["roi_keys"], "roi_key",
            ),
        },
    }
    inputs = [
        Path(__file__).resolve(),
        *[ROOT / "src/openscope_p3_publication" / f"{name}.py" for name in (
            "standard_oddball_publication_data", "standard_oddball_cohort_figure",
            "mesoscope_standard_oddball_cohort_figure",
        )],
    ]
    upstream = [
        {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path)}
        for directory in (COHORT_DIR, MESOSCOPE_COHORT_DIR)
        for name in ("units.csv.gz", "sessions.csv", "provenance.json")
        if (path := directory / name).is_file()
    ]
    provenance = {
        "version": 1,
        "purpose": "Exact frozen rendering inputs, not a replacement for full cohort analyses.",
        "events": list(EVENTS), "tests_recomputed": False,
        "upstream_analyses": upstream,
        "neuropixels_sources": [
            {k: v for k, v in session.items() if k != "trial_inventory"}
            for session in np_provenance["sessions"]
        ],
        "inputs": [{"path": p.relative_to(ROOT).as_posix(), "sha256": sha256(p)} for p in inputs],
    }
    args.output.mkdir(parents=True)
    path = args.output / "cohorts.json"
    path.write_text(
        json.dumps(data, allow_nan=False, separators=(",", ":")) + "\n",
        encoding="utf-8", newline="\n",
    )
    provenance["output_sha256"] = sha256(path)
    (args.output / "provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n",
    )
    print(f"Frozen exact publication counts/statistics: {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
