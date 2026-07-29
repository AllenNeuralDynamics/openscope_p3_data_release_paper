from __future__ import annotations

import csv
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from html import escape
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "figure_sources" / "data"
JAVASCRIPT_DIR = REPO_ROOT / "figure_sources" / "javascript"
STIMULUS_SOURCES_PATH = DATA_DIR / "stimulus-viewer-sources.json"
ANIMAL_RECORDS_PATH = DATA_DIR / "experimental-animals.csv"
ANIMAL_RECORDS_PROVENANCE_PATH = DATA_DIR / "experimental-animals.provenance.json"
MESOSCOPE_LASER_POWER_PATH = DATA_DIR / "mesoscope-laser-power.csv"
INTERACTIVE_OUTPUT = REPO_ROOT / "interactive" / "experimental-design.html"
DATA_EXPLORER_OUTPUT = REPO_ROOT / "interactive" / "data-explorer.html"
STATIC_OUTPUT = REPO_ROOT / "images" / "figures" / "generated" / "experimental-design.svg"
MESOSCOPE_DEPTH_POWER_OUTPUT = (
    REPO_ROOT
    / "images"
    / "figures"
    / "generated"
    / "supplementary-mesoscope-depth-power.svg"
)


@dataclass(frozen=True)
class Session:
    number: int
    name: str
    mismatch: str
    color: str


@dataclass(frozen=True)
class Block:
    name: str
    duration_minutes: float
    category: str


def load_sessions(
    path: Path = DATA_DIR / "experimental-design-sessions.csv",
) -> tuple[Session, ...]:
    with path.open(newline="", encoding="utf-8") as stream:
        return tuple(
            Session(
                number=int(row["number"]),
                name=row["name"],
                mismatch=row["mismatch"],
                color=row["color"],
            )
            for row in csv.DictReader(stream)
        )


def load_blocks(path: Path = DATA_DIR / "experimental-design-blocks.csv") -> tuple[Block, ...]:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = sorted(csv.DictReader(stream), key=lambda row: int(row["order"]))
        return tuple(
            Block(
                name=row["name"],
                duration_minutes=float(row["duration_minutes"]),
                category=row["category"],
            )
            for row in rows
        )


SESSIONS = load_sessions()
BLOCKS = load_blocks()

SHARED_COLORS = (
    "#D9DFE3",
    "#C7D0D6",
    "#B5C1C8",
    "#A4B2BA",
    "#92A3AC",
    "#80949E",
    "#6F858F",
)


def total_duration_minutes() -> float:
    return sum(block.duration_minutes for block in BLOCKS)


def write_interactive_html(output: Path = INTERACTIVE_OUTPUT) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    sources = json.loads(STIMULUS_SOURCES_PATH.read_text(encoding="utf-8"))
    payload = {
        "blocks": [asdict(block) for block in BLOCKS],
        "playback_duration_seconds": 24,
        "sessions": [asdict(session) for session in SESSIONS],
        "sources": sources,
    }
    template = (JAVASCRIPT_DIR / "stimulus-viewer.html").read_text(encoding="utf-8")
    stylesheet = (JAVASCRIPT_DIR / "stimulus-viewer.css").read_text(encoding="utf-8")
    javascript = (JAVASCRIPT_DIR / "stimulus-viewer.js").read_text(encoding="utf-8")
    html = (
        template.replace("__SIMULATOR_CSS__", stylesheet)
        .replace(
            "__SIMULATOR_DATA__",
            json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
        )
        .replace("__SIMULATOR_JS__", javascript)
    )
    output.write_text(html, encoding="utf-8")
    return output


def write_data_explorer_html(output: Path = DATA_EXPLORER_OUTPUT) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = load_publication_table_data()
    template = (JAVASCRIPT_DIR / "data-explorer.html").read_text(encoding="utf-8")
    stylesheet = (JAVASCRIPT_DIR / "data-explorer.css").read_text(encoding="utf-8")
    javascript = (JAVASCRIPT_DIR / "data-explorer.js").read_text(encoding="utf-8")
    html = (
        template.replace("__DATA_EXPLORER_CSS__", stylesheet)
        .replace(
            "__DATA_EXPLORER_DATA__",
            json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
        )
        .replace("__DATA_EXPLORER_JS__", javascript)
    )
    output.write_text(html, encoding="utf-8")
    return output


def load_publication_table_data(manuscript_path: Path = REPO_ROOT / "index.md") -> dict:
    manuscript = manuscript_path.read_text(encoding="utf-8")
    pattern = re.compile(
        r'<table class="publication-data-table table-(?P<kind>animals|sessions)".*?'
        r'</table>',
        re.DOTALL,
    )
    grouped_tables = {}
    for match in pattern.finditer(manuscript):
        kind = match.group("kind")
        table = ET.fromstring(match.group())
        header_rows = table.findall("./thead/tr")
        headers = [" ".join("".join(cell.itertext()).split()) for cell in header_rows[-1]]
        rows = []
        for row in table.findall("./tbody/tr"):
            values = [
                cell.attrib.get("data-full-value")
                or " ".join("".join(cell.itertext()).split())
                for cell in row
            ]
            rows.append(
                {
                    "context": row.attrib.get("data-context", ""),
                    "modality": row.attrib.get("data-modality", "other"),
                    "values": values,
                }
            )
        grouped_tables[kind] = {"headers": headers, "rows": rows}
    if set(grouped_tables) != {"animals", "sessions"}:
        raise RuntimeError("Expected animals and sessions tables in manuscript.")

    summary_mouse_ids = split_grouped_identifiers(grouped_tables["animals"], count_index=4)
    animal_table = load_individual_animal_table(summary_mouse_ids)
    session_table = expand_individual_session_table(grouped_tables["sessions"])
    return {
        "tables": {"animals": animal_table, "sessions": session_table},
        "version": 2,
    }


def split_grouped_identifiers(table: dict, count_index: int) -> set[str]:
    identifiers = []
    for row in table["rows"]:
        row_ids = [value.strip() for value in row["values"][-1].split(",") if value.strip()]
        declared_count = int(row["values"][count_index].split()[0])
        if declared_count != len(row_ids):
            raise RuntimeError(
                f"Declared count {declared_count} does not match {len(row_ids)} identifiers."
            )
        identifiers.extend(row_ids)
    if len(identifiers) != len(set(identifiers)):
        raise RuntimeError("Grouped table contains duplicate identifiers.")
    return set(identifiers)


def load_individual_animal_table(summary_mouse_ids: set[str]) -> dict:
    modality_lookup = {
        "MESO": ("mesoscope", "Two-photon mesoscope"),
        "EPHYS": ("neuropixels", "Neuropixels"),
        "SLAP2": ("slap2", "SLAP2"),
    }
    provenance = json.loads(ANIMAL_RECORDS_PROVENANCE_PATH.read_text(encoding="utf-8"))
    checksum = hashlib.sha256(ANIMAL_RECORDS_PATH.read_bytes()).hexdigest()
    if checksum != provenance["vendored_sha256"]:
        raise RuntimeError("Animal worksheet checksum does not match its provenance record.")
    with ANIMAL_RECORDS_PATH.open(newline="", encoding="utf-8") as stream:
        source_rows = list(csv.DictReader(stream))
    if len(source_rows) != provenance["rows"]:
        raise RuntimeError("Animal worksheet row count does not match its provenance record.")

    rows = []
    for source in source_rows:
        mouse_id = source["Mouse id"].strip()
        modality, modality_label = modality_lookup[source["Modality"].strip()]
        qc_value = source["QC (true/false)"].strip() or "Not marked"
        sex = source["Sex"].strip()
        if not sex or sex == "?":
            sex = "Unknown"
        included = "Yes" if mouse_id in summary_mouse_ids else "No"
        details = [
            {"label": "Genotype / preparation", "value": source["Transgenic details"].strip()},
            {"label": "Virus(es)", "value": source["Virus(es)"].strip()},
            {"label": "Birth date", "value": source["Birth date"].strip()},
            {"label": "Surgery date(s)", "value": source["Surgery date(s)"].strip()},
            {"label": "Notes", "value": source["Notes"].strip()},
            {"label": "Included in grouped manuscript table", "value": included},
        ]
        details = [detail for detail in details if detail["value"]]
        csv_values = [source[header] for header in source]
        csv_values.append(included)
        rows.append(
            {
                "context": "",
                "csvValues": csv_values,
                "details": details,
                "modality": modality,
                "qc": normalize_qc(qc_value),
                "values": [mouse_id, modality_label, sex, qc_value, ""],
            }
        )

    rows.sort(key=lambda row: int(row["values"][0]))
    mouse_ids = [row["values"][0] for row in rows]
    if len(mouse_ids) != len(set(mouse_ids)):
        raise RuntimeError("Animal worksheet contains duplicate mouse IDs.")
    if not summary_mouse_ids.issubset(mouse_ids):
        missing = sorted(summary_mouse_ids - set(mouse_ids))
        raise RuntimeError(f"Animal worksheet is missing manuscript mouse IDs: {missing}")
    return {
        "csvHeaders": [*source_rows[0].keys(), "Included in grouped manuscript table"],
        "detailsColumn": 4,
        "headers": ["Mouse ID", "Modality", "Sex", "QC", "Metadata"],
        "rows": rows,
    }


def normalize_qc(value: str) -> str:
    normalized = value.lower()
    if normalized.startswith("true"):
        return "pass"
    if normalized.startswith("false") or "failed" in normalized:
        return "failed"
    return "not marked"


def expand_individual_session_table(grouped_table: dict) -> dict:
    rows = []
    session_ids = split_grouped_identifiers(grouped_table, count_index=2)
    for group in grouped_table["rows"]:
        modality_label, context_label = group["values"][:2]
        for session_id in [
            value.strip() for value in group["values"][-1].split(",") if value.strip()
        ]:
            mouse_id, session_date = session_id.split("_", maxsplit=1)
            values = [session_id, mouse_id, session_date, modality_label, context_label]
            rows.append(
                {
                    "context": group["context"],
                    "csvValues": values,
                    "details": [],
                    "modality": group["modality"],
                    "qc": "",
                    "values": values,
                }
            )
    rows.sort(key=lambda row: (row["values"][2], row["values"][0]))
    if {row["values"][0] for row in rows} != session_ids:
        raise RuntimeError("Expanded session IDs do not match grouped session IDs.")
    headers = ["Session ID", "Mouse ID", "Date", "Modality", "Context"]
    return {
        "csvHeaders": headers,
        "detailsColumn": None,
        "headers": headers,
        "rows": rows,
    }


def load_mesoscope_laser_power_rows(
    path: Path = MESOSCOPE_LASER_POWER_PATH,
) -> tuple[dict[str, int], ...]:
    columns = (
        "depth_min_um",
        "depth_max_um",
        "laser_power_min_mw",
        "laser_power_max_mw",
    )
    with path.open(newline="", encoding="utf-8") as stream:
        rows = tuple(
            {column: int(row[column]) for column in columns}
            for row in csv.DictReader(stream)
        )

    for index, row in enumerate(rows):
        if row["depth_min_um"] >= row["depth_max_um"]:
            raise RuntimeError("Mesoscope depth intervals must be increasing.")
        if row["laser_power_min_mw"] > row["laser_power_max_mw"]:
            raise RuntimeError("Mesoscope minimum power cannot exceed maximum power.")
        if index and rows[index - 1]["depth_max_um"] != row["depth_min_um"]:
            raise RuntimeError("Mesoscope depth intervals must be contiguous.")
    return rows


def write_mesoscope_depth_power_svg(
    output: Path = MESOSCOPE_DEPTH_POWER_OUTPUT,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = load_mesoscope_laser_power_rows()
    width = 900
    table_x = 50
    table_y = 118
    table_width = 800
    header_height = 46
    row_height = 39
    height = table_y + header_height + len(rows) * row_height + 58
    columns = (
        ("Imaging depth", 70),
        ("Minimum power", 465),
        ("Maximum power", 680),
    )

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        'aria-labelledby="title description">',
        '<title id="title">Mesoscope laser power by imaging depth</title>',
        '<desc id="description">Minimum and maximum laser power lookup ranges for '
        'twelve contiguous 50 micrometer imaging-depth intervals from the cortical '
        'surface to 600 micrometers.</desc>',
        f'<rect width="{width}" height="{height}" fill="#FFFFFF"/>',
        '<text x="50" y="48" font-family="IBM Plex Sans, sans-serif" font-size="27" '
        'font-weight="600" fill="#172126">Mesoscope laser power by imaging depth</text>',
        '<text x="50" y="77" font-family="IBM Plex Sans, sans-serif" font-size="15" '
        'fill="#52615A">Lookup ranges used to guide two-photon imaging settings</text>',
        f'<rect x="{table_x}" y="{table_y}" width="{table_width}" '
        f'height="{header_height}" rx="5" fill="#174641"/>',
    ]
    for label, x in columns:
        svg.append(
            f'<text x="{x}" y="{table_y + 29}" '
            'font-family="IBM Plex Sans, sans-serif" font-size="15" font-weight="600" '
            f'fill="#FFFFFF">{label}</text>'
        )

    for index, row in enumerate(rows):
        y = table_y + header_height + index * row_height
        fill = "#F2F7F5" if index % 2 else "#FFFFFF"
        depth = f'{row["depth_min_um"]}–{row["depth_max_um"]} µm'
        minimum = f'{row["laser_power_min_mw"]} mW'
        maximum = f'{row["laser_power_max_mw"]} mW'
        svg.extend(
            [
                f'<rect x="{table_x}" y="{y}" width="{table_width}" '
                f'height="{row_height}" fill="{fill}" stroke="#D7E2DE"/>',
                f'<rect x="{table_x}" y="{y}" width="5" height="{row_height}" '
                'fill="#2B83BA"/>',
                f'<text x="70" y="{y + 25}" font-family="IBM Plex Sans, sans-serif" '
                f'font-size="14" font-weight="600" fill="#26342E">{depth}</text>',
                f'<text x="500" y="{y + 25}" font-family="IBM Plex Sans, sans-serif" '
                f'font-size="14" fill="#26342E">{minimum}</text>',
                f'<text x="720" y="{y + 25}" font-family="IBM Plex Sans, sans-serif" '
                f'font-size="14" fill="#26342E">{maximum}</text>',
            ]
        )

    svg.extend(
        [
            f'<text x="50" y="{height - 20}" font-family="IBM Plex Sans, sans-serif" '
            'font-size="12" fill="#64736C">Source: '
            'figure_sources/data/mesoscope-laser-power.csv</text>',
            "</svg>",
        ]
    )
    output.write_text("\n".join(svg) + "\n", encoding="utf-8")
    return output


def write_static_svg(output: Path = STATIC_OUTPUT) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    width = 1200
    height = 500
    label_width = 220
    plot_width = 920
    top = 105
    row_height = 72
    bar_height = 44
    scale = plot_width / total_duration_minutes()

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        'aria-labelledby="title description">',
        '<title id="title">Shared structure of the four predictive-processing sessions</title>',
        '<desc id="description">Four horizontal session timelines with a context-specific '
        'mismatch block and seven shared control and characterization blocks.</desc>',
        '<rect width="1200" height="500" fill="#FFFFFF"/>',
        '<text x="40" y="52" font-family="IBM Plex Sans, sans-serif" font-size="28" '
        'font-weight="600" fill="#172126">Shared structure of the four predictive-processing '
        "sessions</text>",
    ]

    for session_index, session in enumerate(SESSIONS):
        y = top + session_index * row_height
        svg.append(
            f'<text x="40" y="{y + 18}" font-family="IBM Plex Sans, sans-serif" '
            f'font-size="17" font-weight="600" fill="#172126">Session {session.number}</text>'
        )
        svg.append(
            f'<text x="40" y="{y + 39}" font-family="IBM Plex Sans, sans-serif" '
            f'font-size="14" fill="#49565C">{escape(session.name)}</text>'
        )
        x = label_width
        shared_index = 0
        for block in BLOCKS:
            block_width = block.duration_minutes * scale
            color = session.color if block.category == "context" else SHARED_COLORS[shared_index]
            svg.append(
                f'<rect x="{x:.2f}" y="{y}" width="{block_width:.2f}" height="{bar_height}" '
                f'fill="{color}" stroke="#FFFFFF" stroke-width="1"/>'
            )
            if block_width >= 80:
                svg.append(
                    f'<text x="{x + block_width / 2:.2f}" y="{y + 27}" '
                    'font-family="IBM Plex Sans, sans-serif" font-size="11" '
                    f'text-anchor="middle" fill="#172126">{escape(block.name)}</text>'
                )
            x += block_width
            if block.category == "shared":
                shared_index += 1

    axis_y = top + len(SESSIONS) * row_height + 12
    svg.append(
        f'<line x1="{label_width}" y1="{axis_y}" x2="{label_width + plot_width}" '
        f'y2="{axis_y}" stroke="#49565C" stroke-width="1"/>'
    )
    for minute in range(0, 71, 10):
        x = label_width + minute * scale
        svg.extend(
            [
                f'<line x1="{x:.2f}" y1="{axis_y}" x2="{x:.2f}" y2="{axis_y + 6}" '
                'stroke="#49565C" stroke-width="1"/>',
                f'<text x="{x:.2f}" y="{axis_y + 24}" '
                'font-family="IBM Plex Sans, sans-serif" font-size="12" '
                f'text-anchor="middle" fill="#49565C">{minute} min</text>',
            ]
        )
    svg.append("</svg>")
    output.write_text("\n".join(svg) + "\n", encoding="utf-8")
    return output


def main() -> None:
    html_path = write_interactive_html()
    data_explorer_path = write_data_explorer_html()
    svg_path = write_static_svg()
    depth_power_path = write_mesoscope_depth_power_svg()
    print(f"Wrote {html_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {data_explorer_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {svg_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {depth_power_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()