"""Refresh publication table snapshots from the public P3 Google workbook."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "figure_sources" / "data"
SPREADSHEET_ID = "1wAeloFJgvRjrseoVeNm4YQd8BezGWRon-Z-b1iJAz9c"
WORKBOOK_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit?usp=sharing"
XLSX_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=xlsx"

ANIMAL_URL = (
    f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/"
    "export?format=csv&gid=520414570"
)
DATA_ACCESS_URL = (
    f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/"
    "export?format=csv&gid=2007007400"
)
ANIMAL_HEADERS = [
    "Mouse id",
    "Modality",
    "QC (true/false)",
    "Sex",
    "Transgenic details",
    "Virus(es)",
    "Birth date",
    "Surgery date(s)",
    "Notes",
]
DATA_ACCESS_HEADERS = [
    "Session ID",
    "Mouse ID",
    "Date",
    "Modality",
    "Context",
    "Dandiset ID",
    "DANDI path",
    "DANDI link",
    "Source session S3 asset",
    "Spike-sorted S3 asset",
    "CCF S3 asset",
    "Behavior S3 asset",
    "Behavior videos S3 asset",
    "Motion-corrected S3 asset",
    "Annotated S3 asset",
    "Processed S3 asset",
    "NWB S3 asset",
]
SNAPSHOTS = ("experimental-animals", "experimental-sessions", "data-access")


def download(url: str, timeout: int = 180) -> bytes:
    """Download a public worksheet export."""
    with urlopen(url, timeout=timeout) as response:  # noqa: S310
        return response.read()


def parse_csv(source_bytes: bytes, headers: list[str]) -> list[dict[str, str]]:
    """Parse a worksheet CSV while enforcing its publication schema."""
    reader = csv.DictReader(io.StringIO(source_bytes.decode("utf-8-sig")))
    if reader.fieldnames != headers:
        raise RuntimeError(f"Unsupported worksheet schema: {reader.fieldnames}")
    rows = [{header: (row[header] or "").strip() for header in headers} for row in reader]
    if not rows:
        raise RuntimeError("Worksheet export is empty.")
    return rows


def serialize_csv(rows: list[dict[str, str]], headers: list[str]) -> bytes:
    """Serialize records as deterministic UTF-8 CSV with LF line endings."""
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def write_snapshot(
    name: str,
    source_bytes: bytes,
    vendored_bytes: bytes,
    provenance: dict,
) -> Path:
    """Write one snapshot and its checksum-bearing provenance record."""
    output = DATA_DIR / f"{name}.csv"
    output.write_bytes(vendored_bytes)
    provenance.update(
        {
            "version": 1,
            "retrieved_date": dt.date.today().isoformat(),
            "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "vendored_sha256": hashlib.sha256(vendored_bytes).hexdigest(),
        }
    )
    output.with_suffix(".provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {provenance['rows']} rows to {output}")
    return output


def update_animals(source_bytes: bytes | None = None) -> Path:
    """Refresh the complete mouse-table snapshot."""
    source_bytes = source_bytes if source_bytes is not None else download(ANIMAL_URL)
    rows = parse_csv(source_bytes, ANIMAL_HEADERS)
    mouse_ids = [row["Mouse id"] for row in rows]
    if any(not mouse_id for mouse_id in mouse_ids) or len(mouse_ids) != len(set(mouse_ids)):
        raise RuntimeError("Mouse worksheet contains empty or duplicate Mouse IDs.")
    if {row["Modality"] for row in rows} - {"EPHYS", "MESO", "SLAP2"}:
        raise RuntimeError("Mouse worksheet contains an unsupported modality.")
    return write_snapshot(
        "experimental-animals",
        source_bytes,
        serialize_csv(rows, ANIMAL_HEADERS),
        {
            "source_url": ANIMAL_URL.replace("export?format=csv&", "edit?"),
            "export_url": ANIMAL_URL,
            "rows": len(rows),
            "notes": (
                "Complete public MICE TABLE snapshot, normalized to UTF-8 CSV with LF "
                "line endings. Publication builds read only this local file."
            ),
        },
    )


def update_sessions(source_bytes: bytes | None = None) -> Path:
    """Refresh the normalized complete session-table snapshot."""
    from extract_experimental_sessions import (  # imported only for this snapshot
        MODALITY_NAMES,
        OUTPUT_FIELDS,
        normalized_source_rows,
    )

    source_bytes = source_bytes if source_bytes is not None else download(XLSX_URL)
    rows, worksheet_rows = normalized_source_rows(source_bytes)
    if not rows:
        raise RuntimeError("Session worksheet produced no publication records.")
    modality_rows = {
        modality: sum(row["modality"] == modality for row in rows)
        for modality in MODALITY_NAMES.values()
    }
    return write_snapshot(
        "experimental-sessions",
        source_bytes,
        serialize_csv(rows, list(OUTPUT_FIELDS)),
        {
            "source_url": WORKBOOK_URL,
            "export_url": XLSX_URL,
            "worksheet_rows": worksheet_rows,
            "source_rows": len(rows),
            "rows": len(rows),
            "modality_rows": modality_rows,
            "notes": (
                "Complete EPHYS, MESO, and SLAP2 worksheet rows in source order. Repeated "
                "and aborted records are retained to reproduce the supplied static plots; "
                "the interactive explorer remains a separate grouped-session inventory."
            ),
        },
    )


def update_data_access(source_bytes: bytes | None = None) -> Path:
    """Refresh the released-session Data Access snapshot."""
    source_bytes = source_bytes if source_bytes is not None else download(DATA_ACCESS_URL)
    rows = parse_csv(source_bytes, DATA_ACCESS_HEADERS)
    session_ids = [row["Session ID"] for row in rows]
    if any(not session_id for session_id in session_ids):
        raise RuntimeError("Data Access worksheet contains an empty Session ID.")
    if len(session_ids) != len(set(session_ids)):
        raise RuntimeError("Data Access worksheet contains duplicate Session IDs.")
    if {row["Modality"] for row in rows} - {"Neuropixels", "Mesoscope", "SLAP2"}:
        raise RuntimeError("Data Access worksheet contains an unsupported modality.")
    if any(len(row["Dandiset ID"]) != 6 or not row["Dandiset ID"].isdigit() for row in rows):
        raise RuntimeError("Dandiset IDs must be six-digit strings.")
    return write_snapshot(
        "data-access",
        source_bytes,
        serialize_csv(rows, DATA_ACCESS_HEADERS),
        {
            "source_url": DATA_ACCESS_URL,
            "export_url": DATA_ACCESS_URL,
            "rows": len(rows),
            "modality_rows": {
                modality: sum(row["Modality"] == modality for row in rows)
                for modality in ("Neuropixels", "Mesoscope", "SLAP2")
            },
            "notes": (
                "Released-session snapshot of DATA ACCESS SUMMARY. Publication builds "
                "read this local CSV and never query Google Sheets."
            ),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", choices=("all", *SNAPSHOTS), default="all")
    args = parser.parse_args()
    updates = {
        "experimental-animals": update_animals,
        "experimental-sessions": update_sessions,
        "data-access": update_data_access,
    }
    selected = SNAPSHOTS if args.snapshot == "all" else (args.snapshot,)
    for name in selected:
        updates[name]()


if __name__ == "__main__":
    main()