#!/usr/bin/env python3
"""Vendor session-level stimulus and QC metadata for the publication inventory."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import urllib.request
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPO_ROOT / "figure_sources" / "data" / "experimental-sessions.csv"
PROVENANCE_PATH = OUTPUT_PATH.with_suffix(".provenance.json")
SOURCE_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1wAeloFJgvRjrseoVeNm4YQd8BezGWRon-Z-b1iJAz9c/"
    "edit?usp=sharing"
)
EXPORT_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1wAeloFJgvRjrseoVeNm4YQd8BezGWRon-Z-b1iJAz9c/"
    "export?format=xlsx"
)
RETRIEVED_DATE = "2026-07-31"
MODALITY_NAMES = {
    "EPHYS": "neuropixels",
    "MESO": "mesoscope",
    "SLAP2": "slap2",
}
OUTPUT_FIELDS = (
    "source_session_id",
    "mouse_id",
    "date",
    "modality",
    "session_stimulus",
    "qc",
    "qc_tags",
    "source_row",
)


def normalize_mouse_id(value: object, pandas_module) -> str:
    if pandas_module.isna(value):
        return ""
    if isinstance(value, (int, float)):
        return str(int(value))
    return str(value).strip().removesuffix(".0")


def normalize_date(value: object) -> str:
    if hasattr(value, "date"):
        return value.date().isoformat()
    text = str(value).strip()
    for format_string in ("%m/%d/%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, format_string).date().isoformat()
        except ValueError:
            continue
    raise RuntimeError(f"Unsupported worksheet date: {value!r}")


def clean_cell(value: object, pandas_module) -> str:
    return "" if pandas_module.isna(value) else str(value).strip()


def normalized_source_rows(
    source_bytes: bytes,
    pandas_module=None,
) -> tuple[list[dict[str, str]], int]:
    if pandas_module is None:
        try:
            import pandas as pandas_module
        except ImportError as exc:  # pragma: no cover - optional extraction environment
            raise RuntimeError(
                "Run with: uv run --with pandas --with python-calamine "
                "python scripts/extract_experimental_sessions.py"
            ) from exc
    frame = pandas_module.read_excel(
        io.BytesIO(source_bytes),
        sheet_name=" SESSIONS TABLE",
        header=1,
        engine="calamine",
    )
    rows = []
    for index, row in frame.iterrows():
        source_modality = clean_cell(row.get("Modality"), pandas_module)
        mouse_id = normalize_mouse_id(row.get("Mouse id"), pandas_module)
        date_value = row.get("Experimental date")
        if (
            source_modality not in MODALITY_NAMES
            or not mouse_id
            or pandas_module.isna(date_value)
        ):
            continue
        rows.append(
            {
                "date": normalize_date(date_value),
                "modality": MODALITY_NAMES[source_modality],
                "mouse_id": mouse_id,
                "qc": clean_cell(row.get("QC"), pandas_module),
                "qc_tags": clean_cell(row.get("QC Tags"), pandas_module),
                "session_stimulus": clean_cell(
                    row.get("Session stimulus"), pandas_module
                ),
                "source_row": str(index + 3),
                "source_session_id": clean_cell(row.get("Session id"), pandas_module),
            }
        )
    return rows, len(frame)


def serialize_records(records: list[dict]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(records)
    return stream.getvalue().encode()


def main() -> None:
    with urllib.request.urlopen(EXPORT_URL, timeout=180) as response:
        source_bytes = response.read()
    records, worksheet_rows = normalized_source_rows(source_bytes)
    vendored_bytes = serialize_records(records)

    OUTPUT_PATH.write_bytes(vendored_bytes)
    provenance = {
        "version": 1,
        "source_url": SOURCE_URL,
        "export_url": EXPORT_URL,
        "retrieved_date": RETRIEVED_DATE,
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "vendored_sha256": hashlib.sha256(vendored_bytes).hexdigest(),
        "worksheet_rows": worksheet_rows,
        "source_rows": len(records),
        "rows": len(records),
        "modality_rows": {
            modality: sum(record["modality"] == modality for record in records)
            for modality in ("neuropixels", "mesoscope", "slap2")
        },
        "notes": (
            "Complete EPHYS, MESO, and SLAP2 worksheet rows in source order. Repeated "
            "and aborted records are retained to reproduce the supplied static plots; "
            "the interactive explorer selects valid session IDs whose QC status is Pass."
        ),
    }
    PROVENANCE_PATH.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUTPUT_PATH} ({len(records)} records)")


if __name__ == "__main__":
    main()