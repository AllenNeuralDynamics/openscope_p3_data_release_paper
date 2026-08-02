from __future__ import annotations

import base64
import csv
import datetime as dt
import hashlib
import json
import math
import re
import shutil
import statistics
import struct
import xml.etree.ElementTree as ET
import zlib
from dataclasses import asdict, dataclass
from html import escape
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "figure_sources" / "data"
JAVASCRIPT_DIR = REPO_ROOT / "figure_sources" / "javascript"
STIMULUS_SOURCES_PATH = DATA_DIR / "stimulus-viewer-sources.json"
STIMULUS_EXCERPT_DIR = DATA_DIR / "stimulus-table-excerpts"
STIMULUS_EXCERPT_PROVENANCE_PATH = STIMULUS_EXCERPT_DIR / "provenance.json"
ANIMAL_RECORDS_PATH = DATA_DIR / "experimental-animals.csv"
ANIMAL_RECORDS_PROVENANCE_PATH = DATA_DIR / "experimental-animals.provenance.json"
SESSION_RECORDS_PATH = DATA_DIR / "experimental-sessions.csv"
SESSION_RECORDS_PROVENANCE_PATH = SESSION_RECORDS_PATH.with_suffix(".provenance.json")
INTERACTIVE_OUTPUT = REPO_ROOT / "interactive" / "experimental-design.html"
DATA_EXPLORER_OUTPUT = REPO_ROOT / "interactive" / "data-explorer.html"
SESSION_INVENTORY_STATIC_OUTPUT = (
    REPO_ROOT / "images" / "figures" / "generated" / "session-inventory.svg"
)
GRAPHICAL_ABSTRACT_SOURCE = (
    REPO_ROOT / "images" / "figures" / "imported" / "figure-01-graphical-abstract.png"
)
EXPERIMENTAL_DESIGN_SOURCE = (
    REPO_ROOT / "images" / "figures" / "imported" / "figure-02-experimental-design.png"
)
MERGED_FIGURE_1_OUTPUT = (
    REPO_ROOT / "images" / "figures" / "generated" / "figure-01-overview.svg"
)
FIGURE_1_PANEL_C_OUTPUT = (
    REPO_ROOT / "images" / "figures" / "generated" / "figure-01-panel-c-cohorts.svg"
)
EXPERIMENTAL_DESIGN_SOURCE_PROVENANCE_PATH = (
    REPO_ROOT
    / "figure_sources"
    / "illustrator"
    / "experimental-design-sources.provenance.json"
)
CONTEXT_CONTROLS_STATIC_OUTPUT = (
    REPO_ROOT / "images" / "figures" / "generated" / "figure-02-context-controls.svg"
)
LITERATURE_COMPARISON_OUTPUT = REPO_ROOT / "interactive" / "literature-comparison.html"
BEHAVIOR_VIEWER_OUTPUT = REPO_ROOT / "interactive" / "behavior-viewer.html"
BEHAVIOR_EXCERPTS_PATH = DATA_DIR / "behavior-excerpts.json"
RUNNING_STATISTICS_PATH = DATA_DIR / "running-statistics.json"
BEHAVIOR_STATIC_LOCAL_TIME_SECONDS = 8.0
SLAP2_COUNTS_PER_REVOLUTION = 8192
SLAP2_WHEEL_RADIUS_CM = 8.255
SLAP2_SUBJECT_POSITION = 2 / 3
SLAP2_DISTANCE_PER_COUNT_CM = (
    2
    * math.pi
    * SLAP2_WHEEL_RADIUS_CM
    * SLAP2_SUBJECT_POSITION
    / SLAP2_COUNTS_PER_REVOLUTION
)
BEHAVIOR_STATIC_FRAME_PROVENANCE_PATH = (
    DATA_DIR / "behavior-static-frames.provenance.json"
)
BEHAVIOR_STATIC_OUTPUT = (
    REPO_ROOT / "images" / "figures" / "generated" / "synchronized-behavior.svg"
)
NEURAL_VIEWER_OUTPUT = REPO_ROOT / "interactive" / "neural-viewer.html"
NEURAL_EXCERPTS_PATH = DATA_DIR / "raw-neural-excerpts.json"
NEURAL_STATIC_FRAME_PROVENANCE_PATH = (
    DATA_DIR / "raw-neural-static-frames.provenance.json"
)
NEURAL_STATIC_OUTPUT = (
    REPO_ROOT / "images" / "figures" / "generated" / "raw-neural-recordings.svg"
)
SLAP2_STATIC_COMPOSITES = {
    "dmd1-composite": ("dmd1-detector-1", "dmd1-detector-2"),
    "dmd2-composite": ("dmd2-detector-1", "dmd2-detector-2"),
}
NEURAL_STATIC_SELECTIONS = {
    "neuropixels": (
        "probe-a",
        "probe-b",
        "probe-c",
        "probe-d",
        "probe-e",
        "probe-f",
    ),
    "mesoscope": (
        "visp_0",
        "visp_1",
        "visp_2",
        "visp_3",
        "visl_4",
        "visl_5",
        "visl_6",
        "visl_7",
    ),
    "slap2": tuple(SLAP2_STATIC_COMPOSITES),
}
OTHER_STUDIES_PATH = DATA_DIR / "other-oddball-studies.csv"
OTHER_STUDIES_PROVENANCE_PATH = OTHER_STUDIES_PATH.with_suffix(".provenance.json")
UNIT_YIELD_DATA_PATH = DATA_DIR / "neuropixels-unit-yield.csv"
UNIT_YIELD_PROVENANCE_PATH = UNIT_YIELD_DATA_PATH.with_suffix(".provenance.json")
STATIC_OUTPUT = REPO_ROOT / "images" / "figures" / "generated" / "experimental-design.svg"
UNIT_YIELD_STATIC_OUTPUT = (
    REPO_ROOT / "images" / "figures" / "generated" / "supplementary-neuropixels-unit-yield.svg"
)
UNIT_YIELD_INTERACTIVE_OUTPUT = REPO_ROOT / "interactive" / "unit-yield.html"
MEDIA_DIR = REPO_ROOT / "figure_sources" / "media"
PLATFORM_LOGO_PROVENANCE_PATH = (
    REPO_ROOT / "figure_sources" / "illustrator" / "platform-logos.provenance.json"
)
BEHAVIOR_STATIC_FRAME_DIR = MEDIA_DIR / "behavior-viewer-static"
NEURAL_MEDIA_DIR = MEDIA_DIR / "neural-viewer"
NEURAL_STATIC_FRAME_DIR = MEDIA_DIR / "neural-viewer-static"
ZEBRA_MOVIE_SOURCE = MEDIA_DIR / "zebra-stimulus-excerpt.m4v"
ZEBRA_POSTER_SOURCE = MEDIA_DIR / "zebra-stimulus-poster.png"
ZEBRA_PROVENANCE_PATH = MEDIA_DIR / "zebra-stimulus-excerpt.provenance.json"


def load_platform_logos() -> dict[str, Path]:
    provenance = json.loads(PLATFORM_LOGO_PROVENANCE_PATH.read_text(encoding="utf-8"))
    assets = provenance.get("assets", {})
    expected_modalities = {"neuropixels", "mesoscope", "slap2"}
    if provenance.get("version") != 1 or set(assets) != expected_modalities:
        raise RuntimeError("Platform logo provenance is not supported.")

    paths = {}
    for modality, record in assets.items():
        source_path = REPO_ROOT / record["source_path"]
        rendered_path = REPO_ROOT / record["rendered_path"]
        rendered = rendered_path.read_bytes()
        dimensions = list(struct.unpack(">II", rendered[16:24]))
        if (
            hashlib.sha256(source_path.read_bytes()).hexdigest()
            != record["source_sha256"]
            or hashlib.sha256(rendered).hexdigest() != record["rendered_sha256"]
            or not rendered.startswith(b"\x89PNG\r\n\x1a\n")
            or dimensions != [record["width"], record["height"]]
            or rendered[25] != 6
        ):
            raise RuntimeError(f"Platform logo asset is invalid: {modality}")
        paths[modality] = rendered_path
    return paths


def platform_logo_data_uris() -> dict[str, str]:
    return {
        modality: f"data:image/png;base64,{base64.b64encode(path.read_bytes()).decode()}"
        for modality, path in load_platform_logos().items()
    }


def png_data_uri(path: Path, expected_dimensions: tuple[int, int]) -> str:
    data = path.read_bytes()
    dimensions = struct.unpack(">II", data[16:24])
    if not data.startswith(b"\x89PNG\r\n\x1a\n") or dimensions != expected_dimensions:
        raise RuntimeError(f"Figure source PNG is invalid: {path.name}")
    return f"data:image/png;base64,{base64.b64encode(data).decode()}"


def load_experimental_design_sources() -> dict[str, Path]:
    provenance = json.loads(
        EXPERIMENTAL_DESIGN_SOURCE_PROVENANCE_PATH.read_text(encoding="utf-8")
    )
    assets = provenance.get("assets", {})
    expected_assets = {
        "figure_1_panel_c_modality_cohorts",
        "figure_1_panel_c_training_cohorts",
        "figure_2_detailed_blocks",
        "figure_2_stimulus_timeline",
    }
    if provenance.get("version") != 1 or set(assets) != expected_assets:
        raise RuntimeError("Experimental-design source provenance is not supported.")

    rendered_paths = {}
    for asset_id, record in assets.items():
        source_path = REPO_ROOT / record["source_path"]
        if hashlib.sha256(source_path.read_bytes()).hexdigest() != record["source_sha256"]:
            raise RuntimeError(f"Experimental-design source is invalid: {asset_id}")
        if "rendered_path" not in record:
            continue
        rendered_path = REPO_ROOT / record["rendered_path"]
        rendered = rendered_path.read_bytes()
        dimensions = struct.unpack(">II", rendered[16:24])
        if (
            hashlib.sha256(rendered).hexdigest() != record["rendered_sha256"]
            or not rendered.startswith(b"\x89PNG\r\n\x1a\n")
            or dimensions != (record["width"], record["height"])
        ):
            raise RuntimeError(f"Experimental-design rendering is invalid: {asset_id}")
        rendered_paths[asset_id] = rendered_path
    return rendered_paths


def write_merged_figure_1_svg(output: Path = MERGED_FIGURE_1_OUTPUT) -> Path:
    graphical_abstract = png_data_uri(GRAPHICAL_ABSTRACT_SOURCE, (3200, 2400))
    experimental_design = png_data_uri(EXPERIMENTAL_DESIGN_SOURCE, (1108, 780))
    cohort_panel_path = write_figure_1_panel_c_svg()
    cohort_panel = (
        "data:image/svg+xml;base64,"
        f"{base64.b64encode(cohort_panel_path.read_bytes()).decode()}"
    )
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="2000" height="1620" '
        'viewBox="0 0 2000 1620" role="img" aria-labelledby="title description">',
        '<title id="title">Predictive-processing framework and experimental workflow</title>',
        '<desc id="description">Panel A links predictions and errors across brain-wide, '
        'local-circuit, and single-cell scales. Panel B follows animals from surgery through '
        'intrinsic-signal-imaging mapping and habituation to one of three recording '
        'modalities. Panel C shows habituation and recording-context order across modalities '
        'and cohorts.</desc>',
        '<rect width="2000" height="1620" fill="#FFFFFF"/>',
        f'<image href="{graphical_abstract}" x="40" y="60" width="960" height="720" '
        'preserveAspectRatio="xMidYMid meet"/>',
        '<svg x="1040" y="60" width="924" height="720" viewBox="0 60 580 460" '
        'overflow="hidden" preserveAspectRatio="xMidYMid meet">',
        f'<image href="{experimental_design}" x="0" y="0" width="1108" height="780"/>',
        '</svg>',
        '<text class="panel-label" x="20" y="48" font-family="Source Sans 3, sans-serif" '
        'font-size="34" font-weight="700" fill="#293133">A</text>',
        '<text class="panel-label" x="1020" y="48" font-family="Source Sans 3, sans-serif" '
        'font-size="34" font-weight="700" fill="#293133">B</text>',
        f'<image href="{cohort_panel}" x="40" y="825" width="1920" height="768" '
        'preserveAspectRatio="xMidYMid meet"/>',
        '<text class="panel-label" x="20" y="818" font-family="Source Sans 3, sans-serif" '
        'font-size="34" font-weight="700" fill="#293133">C</text>',
        '</svg>',
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(svg) + "\n", encoding="utf-8")
    return output


def write_figure_1_panel_c_svg(output: Path = FIGURE_1_PANEL_C_OUTPUT) -> Path:
    load_experimental_design_sources()
    logo_paths = load_platform_logos()
    modality_groups = (
        (
            "neuropixels",
            "Neuropixels",
            "4 recording days · each context once",
            ((1, 190), (2, 245)),
            1,
            125,
            160,
        ),
        (
            "mesoscope",
            "Mesoscope",
            "8 recording sessions · each context twice",
            ((1, 365), (2, 420)),
            2,
            300,
            335,
        ),
        (
            "slap2",
            "SLAP2",
            "4 recording sessions · motor cohort only",
            ((1, 565),),
            1,
            480,
            515,
        ),
    )
    session_square_size = 38
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="640" '
        'viewBox="0 0 1600 640" role="img" aria-labelledby="title description">',
        '<title id="title">Predictive-context cohorts across recording modalities</title>',
        '<desc id="description">Five dedicated cohort timelines show eight outlined '
        'habituation sessions followed by filled recording sessions. Neuropixels and '
        'mesoscope sampled motor- and sequence-habituated cohorts in opposite context orders; '
        'SLAP2 sampled the motor-habituated cohort only.</desc>',
        '<rect width="1600" height="640" fill="#FFFFFF"/>',
        '<text x="680" y="105" text-anchor="middle" '
        'font-family="Source Sans 3, sans-serif" font-size="22" font-weight="700" '
        'fill="#4D5553">Habituation / training</text>',
        '<text x="1110" y="105" text-anchor="middle" '
        'font-family="Source Sans 3, sans-serif" font-size="22" font-weight="700" '
        'fill="#4D5553">Neural recording contexts</text>',
    ]

    legend_x = 260
    for context in ("sensorimotor", "standard oddball", "sequence", "duration"):
        label = SESSION_CONTEXT_LABELS[context]
        color = SESSION_CONTEXT_COLORS[context]
        svg.extend(
            [
                f'<rect x="{legend_x}" y="27" width="26" height="26" rx="2" '
                f'fill="{color}"/>',
                f'<text x="{legend_x + 36}" y="48" '
                'font-family="Source Sans 3, sans-serif" font-size="19" '
                f'font-weight="600" fill="#4D5553">{label}</text>',
            ]
        )
        legend_x += 120 + len(label) * 7
    svg.extend(
        [
            '<rect x="1225" y="27" width="26" height="26" rx="2" '
            'fill="#FFFFFF" stroke="#283185" stroke-width="3"/>',
            '<text x="1261" y="48" font-family="Source Sans 3, sans-serif" '
            'font-size="19" font-weight="600" fill="#4D5553">'
            'Habituation without mismatch</text>',
        ]
    )

    for modality, label, summary, cohort_lines, repeats, heading_y, icon_y in modality_groups:
        logo_data = base64.b64encode(logo_paths[modality].read_bytes()).decode()
        svg.extend(
            [
                f'<g class="modality-cohort" data-modality="{modality}">',
                f'<text x="42" y="{heading_y}" '
                'font-family="Source Sans 3, sans-serif" font-size="30" '
                f'font-weight="700" fill="#293133">{label}</text>',
                f'<text x="42" y="{heading_y + 27}" '
                'font-family="Source Sans 3, sans-serif" font-size="19" '
                f'font-weight="600" fill="#68706E">{summary}</text>',
                f'<image class="platform-logo" href="data:image/png;base64,{logo_data}" '
                f'x="42" y="{icon_y}" width="110" height="110" '
                'preserveAspectRatio="xMidYMid meet"/>',
                '</g>',
            ]
        )
        for cohort, line_y in cohort_lines:
            contexts = SESSION_ORDER[cohort]
            svg.extend(
                [
                    f'<g class="cohort-line" data-modality="{modality}" '
                    f'data-cohort="{cohort}">',
                    f'<text x="360" y="{line_y + 7}" text-anchor="end" '
                    'font-family="Source Sans 3, sans-serif" font-size="21" '
                    f'font-weight="700" fill="#4D5553">'
                    f'{"Motor cohort" if cohort == 1 else "Sequence cohort"}</text>',
                    f'<line x1="405" y1="{line_y}" x2="1540" y2="{line_y}" '
                    'stroke="#303536" stroke-width="3"/>',
                    f'<polygon points="1540,{line_y} 1522,{line_y - 10} '
                    f'1522,{line_y + 10}" fill="#303536"/>',
                ]
            )
            training_color = SESSION_CONTEXT_COLORS[contexts[0]]
            training_x = 500
            for training_index in range(8):
                svg.append(
                    f'<rect class="habituation-session" data-cohort="{cohort}" '
                    f'x="{training_x + training_index * 46}" '
                    f'y="{line_y - session_square_size / 2}" '
                    f'width="{session_square_size}" height="{session_square_size}" '
                    'rx="2" fill="#FFFFFF" '
                    f'stroke="{training_color}" stroke-width="3"/>'
                )
            repeat_gap = 8
            context_gap = 18
            group_width = (
                repeats * session_square_size + (repeats - 1) * repeat_gap
            )
            total_width = len(contexts) * group_width + (len(contexts) - 1) * context_gap
            square_x = 1085 - total_width / 2
            for context in contexts:
                for _ in range(repeats):
                    svg.append(
                        f'<rect class="cohort-session" data-cohort="{cohort}" '
                        f'data-context="{context}" x="{square_x:.2f}" '
                        f'y="{line_y - session_square_size / 2:.2f}" '
                        f'width="{session_square_size}" height="{session_square_size}" '
                        'rx="3" '
                        f'fill="{SESSION_CONTEXT_COLORS[context]}" stroke="#FFFFFF" '
                        'stroke-width="2"/>'
                    )
                    square_x += session_square_size + repeat_gap
                square_x += context_gap - repeat_gap
            svg.append('</g>')
    svg.append('</svg>')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(svg) + "\n", encoding="utf-8")
    return output


def write_context_controls_svg(output: Path = CONTEXT_CONTROLS_STATIC_OUTPUT) -> Path:
    assets = load_experimental_design_sources()
    timeline = png_data_uri(assets["figure_2_stimulus_timeline"], (1836, 375))
    details = png_data_uri(assets["figure_2_detailed_blocks"], (2250, 1628))
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1600" '
        'viewBox="0 0 1600 1600" role="img" aria-labelledby="title description">',
        '<title id="title">Within-session controls enable cross-context comparisons</title>',
        '<desc id="description">Panel A shows the common session timeline, with a control '
        'block repeated immediately after the context block and additional controls, '
        'receptive-field mapping, and a zebra movie. Panel B details the four context blocks '
        'and shared control and system-identification stimuli.</desc>',
        '<rect width="1600" height="1600" fill="#FFFFFF"/>',
        '<text class="panel-label" x="22" y="54" '
        'font-family="Source Sans 3, sans-serif" font-size="34" font-weight="700" '
        'fill="#293133">A</text>',
        '<text x="78" y="54" font-family="Source Sans 3, sans-serif" '
        'font-size="28" font-weight="700" fill="#293133">'
        'Shared session architecture</text>',
        f'<image href="{timeline}" x="40" y="82" width="1520" height="310" '
        'preserveAspectRatio="xMidYMid meet"/>',
        '<text class="panel-label" x="22" y="455" '
        'font-family="Source Sans 3, sans-serif" font-size="34" font-weight="700" '
        'fill="#293133">B</text>',
        '<text x="78" y="455" font-family="Source Sans 3, sans-serif" '
        'font-size="28" font-weight="700" fill="#293133">'
        'Context, control, and system-identification blocks</text>',
        f'<image href="{details}" x="40" y="480" width="1520" height="1100" '
        'preserveAspectRatio="xMidYMid meet"/>',
        '</svg>',
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(svg) + "\n", encoding="utf-8")
    return output


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
PROTOCOL_CONTEXT_COLORS = {
    "standard": "#008F80",
    "sensorimotor": "#3157B7",
    "sequence": "#C65D13",
    "duration": "#A47C00",
}
PROTOCOL_BLOCK_COLORS = {
    "standard": SHARED_COLORS[0],
    "context": PROTOCOL_CONTEXT_COLORS["sensorimotor"],
    "standard_repeat": SHARED_COLORS[1],
    "sequence": SHARED_COLORS[2],
    "jitter": SHARED_COLORS[3],
    "open_loop": SHARED_COLORS[4],
    "movie": SHARED_COLORS[5],
    "rf": SHARED_COLORS[6],
}


def total_duration_minutes() -> float:
    return sum(block.duration_minutes for block in BLOCKS)


def stimulus_row_is_mismatch(session_number: int, trial_type: str) -> bool:
    if session_number == 1:
        return trial_type != "standard"
    if session_number == 2:
        return trial_type.startswith("motor_")
    if session_number == 3:
        return trial_type in {"orientation_45", "orientation_90", "halt", "omission"}
    return trial_type in {"jitter", "omission"}


def normalize_stimulus_rows(
    source_rows: list[dict[str, str]], session_number: int | None = None
) -> tuple[list[dict], float]:
    rows = []
    elapsed = 0.0
    previous_phase = None
    unwrapped_phase = 0.0
    for source_row in source_rows:
        duration = float(source_row["Duration"] or 0)
        delay = float(source_row["Delay"] or 0)
        row_duration = duration + delay
        try:
            numeric_phase = float(source_row["Phase"])
        except ValueError:
            phase_cycles = None
        else:
            if previous_phase is None:
                unwrapped_phase = numeric_phase
            else:
                delta = math.atan2(
                    math.sin(numeric_phase - previous_phase),
                    math.cos(numeric_phase - previous_phase),
                )
                unwrapped_phase += delta
            previous_phase = numeric_phase
            phase_cycles = unwrapped_phase / (2 * math.pi)
        rows.append(
            {
                "contrast": float(source_row["Contrast"] or 0),
                "delay": delay,
                "diameterX": float(source_row["DiameterX"] or 0),
                "diameterY": float(source_row["DiameterY"] or 0),
                "duration": duration,
                "end": elapsed + row_duration,
                "isMismatch": (
                    stimulus_row_is_mismatch(
                        session_number, source_row["Trial_Type"]
                    )
                    if session_number is not None
                    else False
                ),
                "orientation": float(source_row["Orientation"] or 0),
                "phase": source_row["Phase"],
                "phaseCycles": phase_cycles,
                "sequenceNumber": int(source_row["Sequence_Number"] or 0),
                "sourceRow": int(source_row["Source_Row"]),
                "spatialFrequency": float(source_row["Spatial_Frequency"] or 0),
                "start": elapsed,
                "temporalFrequency": float(
                    source_row["Temporal_Frequency"] or 0
                ),
                "trialInSequence": int(source_row["Trial_In_Sequence"] or 0),
                "trialNumber": int(source_row["Trial_Number"]),
                "trialType": source_row["Trial_Type"],
                "x": float(source_row["X"] or 0),
                "y": float(source_row["Y"] or 0),
            }
        )
        elapsed += row_duration
    return rows, elapsed


def load_stimulus_table_excerpts(sources: dict) -> dict[str, dict]:
    provenance = json.loads(
        STIMULUS_EXCERPT_PROVENANCE_PATH.read_text(encoding="utf-8")
    )
    if provenance["upstream_revision"] != sources["upstream_revision"]:
        raise RuntimeError("Stimulus excerpt and source revisions do not match.")
    provenance_by_name = {
        table["filename"]: table for table in provenance["tables"]
    }
    excerpts = {}
    for source in sources["sessions"]:
        filename = source["example_table_url"].rsplit("/", maxsplit=1)[-1]
        metadata = provenance_by_name[filename]
        path = STIMULUS_EXCERPT_DIR / filename
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        if checksum != metadata["vendored_sha256"]:
            raise RuntimeError(f"Stimulus excerpt checksum mismatch: {filename}")
        if source["sha256"] != metadata["source_sha256"]:
            raise RuntimeError(f"Stimulus source checksum mismatch: {filename}")
        with path.open(newline="", encoding="utf-8-sig") as stream:
            source_rows = list(csv.DictReader(stream))
        if len(source_rows) != metadata["rows"]:
            raise RuntimeError(f"Stimulus excerpt row-count mismatch: {filename}")

        rows, elapsed = normalize_stimulus_rows(source_rows, source["number"])
        excerpts[str(source["number"])] = {
            "durationSeconds": elapsed,
            "firstMismatchTrial": metadata["first_mismatch_trial"],
            "rows": rows,
            "shuffledOrderPreserved": metadata["shuffled_order_preserved"],
            "sourceTrialEnd": metadata["source_trial_end"],
            "sourceTrialStart": metadata["source_trial_start"],
        }
    return excerpts


def load_shared_stimulus_table_excerpts(sources: dict) -> dict[str, dict]:
    provenance = json.loads(
        STIMULUS_EXCERPT_PROVENANCE_PATH.read_text(encoding="utf-8")
    )
    metadata = provenance["shared_blocks"]
    source = sources["sessions"][0]
    if source["sha256"] != metadata["source_sha256"]:
        raise RuntimeError("Shared stimulus source checksum mismatch.")
    path = STIMULUS_EXCERPT_DIR / metadata["filename"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != metadata["vendored_sha256"]:
        raise RuntimeError("Shared stimulus excerpt checksum mismatch.")
    with path.open(newline="", encoding="utf-8-sig") as stream:
        source_rows = list(csv.DictReader(stream))
    metadata_by_index = {
        str(block["viewer_block_index"]): block for block in metadata["blocks"]
    }
    excerpts = {}
    for block_index, block_metadata in metadata_by_index.items():
        block_rows = [
            row for row in source_rows if row["Viewer_Block_Index"] == block_index
        ]
        if len(block_rows) != block_metadata["rows"]:
            raise RuntimeError(f"Shared block row-count mismatch: {block_index}")
        rows, elapsed = normalize_stimulus_rows(block_rows)
        excerpts[block_index] = {
            "durationSeconds": elapsed,
            "rows": rows,
            "sourceOrderPreserved": block_metadata["source_order_preserved"],
            "sourceTrialEnd": block_metadata["source_trial_end"],
            "sourceTrialStart": block_metadata["source_trial_start"],
        }
    return excerpts


def copy_zebra_media(output_dir: Path, sources: dict) -> None:
    provenance = json.loads(ZEBRA_PROVENANCE_PATH.read_text(encoding="utf-8"))
    if provenance["upstream_revision"] != sources["upstream_revision"]:
        raise RuntimeError("Zebra movie and stimulus source revisions do not match.")
    if provenance["source_sha256"] != sources["zebra_movie_sha256"]:
        raise RuntimeError("Zebra movie source checksums do not match.")
    checks = (
        (ZEBRA_MOVIE_SOURCE, provenance["excerpt_sha256"]),
        (ZEBRA_POSTER_SOURCE, provenance["poster_sha256"]),
    )
    for path, expected in checks:
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Zebra media checksum mismatch: {path.name}")
        shutil.copy2(path, output_dir / path.name)


def load_embed_auto_height() -> str:
    return (JAVASCRIPT_DIR / "embed-auto-height.js").read_text(encoding="utf-8")


def write_interactive_html(output: Path = INTERACTIVE_OUTPUT) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    sources = json.loads(STIMULUS_SOURCES_PATH.read_text(encoding="utf-8"))
    sources["zebra_movie_asset"] = f"./{ZEBRA_MOVIE_SOURCE.name}"
    sources["zebra_movie_poster_asset"] = f"./{ZEBRA_POSTER_SOURCE.name}"
    copy_zebra_media(output.parent, sources)
    payload = {
        "blocks": [asdict(block) for block in BLOCKS],
        "playback_duration_seconds": 24,
        "sessions": [asdict(session) for session in SESSIONS],
        "sharedTableExcerpts": load_shared_stimulus_table_excerpts(sources),
        "sources": sources,
        "stimulusTableExcerpts": load_stimulus_table_excerpts(sources),
    }
    template = (JAVASCRIPT_DIR / "stimulus-viewer.html").read_text(encoding="utf-8")
    stylesheet = (JAVASCRIPT_DIR / "stimulus-viewer.css").read_text(encoding="utf-8")
    javascript = (JAVASCRIPT_DIR / "stimulus-viewer.js").read_text(encoding="utf-8")
    static_output = write_context_controls_svg()
    static_data = base64.b64encode(static_output.read_bytes()).decode()
    html = (
        template.replace("__SIMULATOR_CSS__", stylesheet)
        .replace("__PANEL_D_IMAGE__", f"data:image/svg+xml;base64,{static_data}")
        .replace(
            "__SIMULATOR_DATA__",
            json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
        )
        .replace("__SIMULATOR_JS__", javascript)
        .replace("__EMBED_AUTO_HEIGHT_JS__", load_embed_auto_height())
    )
    output.write_text(html, encoding="utf-8")
    return output


def write_data_explorer_html(
    output: Path = DATA_EXPLORER_OUTPUT,
    static_output: Path = SESSION_INVENTORY_STATIC_OUTPUT,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = load_publication_table_data()
    write_session_inventory_svg(static_output)
    static_data = base64.b64encode(static_output.read_bytes()).decode()
    template = (JAVASCRIPT_DIR / "data-explorer.html").read_text(encoding="utf-8")
    stylesheet = (JAVASCRIPT_DIR / "data-explorer.css").read_text(encoding="utf-8")
    javascript = (JAVASCRIPT_DIR / "data-explorer.js").read_text(encoding="utf-8")
    html = (
        template.replace("__DATA_EXPLORER_CSS__", stylesheet)
        .replace("__SESSION_INVENTORY_IMAGE__", f"data:image/svg+xml;base64,{static_data}")
        .replace(
            "__DATA_EXPLORER_DATA__",
            json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
        )
        .replace("__DATA_EXPLORER_JS__", javascript)
        .replace("__EMBED_AUTO_HEIGHT_JS__", load_embed_auto_height())
    )
    output.write_text(html, encoding="utf-8")
    return output


def write_literature_comparison_html(
    output: Path = LITERATURE_COMPARISON_OUTPUT,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    provenance = json.loads(OTHER_STUDIES_PROVENANCE_PATH.read_text(encoding="utf-8"))
    checksum = hashlib.sha256(OTHER_STUDIES_PATH.read_bytes()).hexdigest()
    if checksum != provenance["vendored_sha256"]:
        raise RuntimeError("Other-studies table checksum does not match its provenance.")
    with OTHER_STUDIES_PATH.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.reader(stream))
    if len(rows) != provenance["rows"]:
        raise RuntimeError("Other-studies table row count does not match its provenance.")
    if not rows or {len(row) for row in rows} != {provenance["columns"]}:
        raise RuntimeError("Other-studies table column count does not match its provenance.")
    payload = {
        "studies": rows[0][1:],
        "parameters": [row[0] for row in rows[1:]],
        "values": [row[1:] for row in rows[1:]],
    }
    template = (JAVASCRIPT_DIR / "literature-comparison.html").read_text(
        encoding="utf-8"
    )
    stylesheet = (JAVASCRIPT_DIR / "literature-comparison.css").read_text(
        encoding="utf-8"
    )
    javascript = (JAVASCRIPT_DIR / "literature-comparison.js").read_text(
        encoding="utf-8"
    )
    html = (
        template.replace("__LITERATURE_CSS__", stylesheet)
        .replace(
            "__LITERATURE_DATA__",
            json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
        )
        .replace("__LITERATURE_JS__", javascript)
        .replace("__EMBED_AUTO_HEIGHT_JS__", load_embed_auto_height())
    )
    output.write_text(html, encoding="utf-8")
    return output


def write_unit_yield_html(
    output: Path = UNIT_YIELD_INTERACTIVE_OUTPUT,
    data_path: Path = UNIT_YIELD_DATA_PATH,
    provenance_path: Path = UNIT_YIELD_PROVENANCE_PATH,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = load_unit_yield_data(data_path, provenance_path)
    template = (JAVASCRIPT_DIR / "unit-yield.html").read_text(encoding="utf-8")
    stylesheet = (JAVASCRIPT_DIR / "unit-yield.css").read_text(encoding="utf-8")
    javascript = (JAVASCRIPT_DIR / "unit-yield.js").read_text(encoding="utf-8")
    html = (
        template.replace("__UNIT_YIELD_CSS__", stylesheet)
        .replace(
            "__UNIT_YIELD_DATA__",
            json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
        )
        .replace("__UNIT_YIELD_JS__", javascript)
        .replace("__EMBED_AUTO_HEIGHT_JS__", load_embed_auto_height())
    )
    output.write_text(html, encoding="utf-8")
    return output


def load_behavior_excerpts(path: Path = BEHAVIOR_EXCERPTS_PATH) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1 or payload.get("durationSeconds") != 16.0:
        raise RuntimeError("Behavior excerpt schema or duration is not supported.")
    sessions = payload.get("sessions", [])
    if [session.get("id") for session in sessions] != [
        "neuropixels",
        "mesoscope",
        "slap2",
    ]:
        raise RuntimeError("Behavior excerpts must contain the three modalities in order.")
    for session in sessions:
        trace = session.get("trace", [])
        event_time = session.get("event", {}).get("time")
        if not trace or trace[0][0] != 0.0 or trace[-1][0] != 16.0:
            raise RuntimeError(f"Behavior trace does not cover its excerpt: {session['id']}")
        if event_time != 5.0 or not any(
            row["start"] <= event_time <= row["end"]
            for row in session.get("stimulus", [])
        ):
            raise RuntimeError(f"Behavior event is not covered by stimulus data: {session['id']}")
        if not session.get("cameras") or not session.get("sources"):
            raise RuntimeError(f"Behavior excerpt lacks source records: {session['id']}")
        for camera in session["cameras"]:
            time_map = camera.get("timeMap", [])
            if (
                len(time_map) < 2
                or time_map[0][0] > 0
                or time_map[-1][0] < payload["durationSeconds"]
                or any(
                    current[0] <= previous[0] or current[1] <= previous[1]
                    for previous, current in zip(time_map[:-1], time_map[1:], strict=True)
                )
            ):
                raise RuntimeError(
                    f"Behavior camera frame map is invalid: {session['id']}/{camera['id']}"
                )
    slap2 = sessions[-1]
    if slap2.get("traceLabel") != "Wheel encoder velocity" or slap2.get(
        "traceUnit"
    ) != "counts/s":
        raise RuntimeError("SLAP2 behavior trace is not the expected raw encoder velocity.")
    slap2["trace"] = [
        [time, round(value * SLAP2_DISTANCE_PER_COUNT_CM, 4)]
        for time, value in slap2["trace"]
    ]
    slap2["traceLabel"] = "Running speed"
    slap2["traceUnit"] = "cm/s"
    return payload


def load_running_statistics(path: Path = RUNNING_STATISTICS_PATH) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected_contexts = ["sensorimotor", "standard", "sequence", "duration"]
    expected_blocks = [
        "standard",
        "context",
        "standard_repeat",
        "sequence",
        "jitter",
        "open_loop",
        "movie",
        "rf",
    ]
    calibration = payload.get("calibration", {}).get("slap2", {})
    source = payload.get("source_session_records", {})
    if (
        payload.get("version") != 2
        or payload.get("sample_rate_hz") != 20
        or payload.get("threshold_cm_s") != 1.0
        or [context.get("id") for context in payload.get("contexts", [])]
        != expected_contexts
        or source.get("sha256")
        != hashlib.sha256(SESSION_RECORDS_PATH.read_bytes()).hexdigest()
        or calibration.get("counts_per_revolution") != SLAP2_COUNTS_PER_REVOLUTION
        or calibration.get("wheel_radius_cm") != SLAP2_WHEEL_RADIUS_CM
        or not math.isclose(
            calibration.get("subject_position", 0), SLAP2_SUBJECT_POSITION
        )
    ):
        raise RuntimeError("Running-statistics schema or calibration is not supported.")

    sessions = payload.get("sessions", [])
    mouse_context = payload.get("mouse_context", [])
    mouse_block = payload.get("mouse_block", [])
    coverage = payload.get("coverage", [])
    profiles = payload.get("example_profiles", [])
    expected_cells = {
        (modality, context)
        for modality in ("neuropixels", "mesoscope", "slap2")
        for context in expected_contexts
    }
    expected_block_cells = {
        (modality, block)
        for modality in ("neuropixels", "mesoscope", "slap2")
        for block in expected_blocks
    }
    if (
        not sessions
        or not mouse_context
        or not mouse_block
        or len(coverage) != len(expected_cells)
        or {(record.get("modality"), record.get("context")) for record in coverage}
        != expected_cells
        or {
            (record.get("modality"), record.get("context"))
            for record in mouse_context
        }
        != expected_cells
        or [record.get("modality") for record in profiles]
        != ["neuropixels", "mesoscope", "slap2"]
        or {
            (record.get("modality"), record.get("block"))
            for record in mouse_block
        }
        != expected_block_cells
    ):
        raise RuntimeError("Running-statistics coverage is incomplete.")
    for profile in profiles:
        if (
            profile.get("bin_seconds") != 5
            or not profile.get("points")
            or [block.get("id") for block in profile.get("blocks", [])]
            != expected_blocks
            or not 4200 < profile.get("duration_seconds", 0) < 4400
        ):
            raise RuntimeError("Running-statistics example profile is invalid.")
    for session in sessions:
        if (
            [block.get("id") for block in session.get("blocks", [])]
            != expected_blocks
            or set(session.get("block_mean_forward_speed_cm_s", {}))
            != set(expected_blocks)
            or session.get("control_mean_forward_speed_cm_s", -1) < 0
            or session.get("context_mean_forward_speed_cm_s", -1) < 0
        ):
            raise RuntimeError("Running-statistics session blocks are invalid.")
    for record in mouse_block:
        if (
            (record.get("modality"), record.get("block"))
            not in expected_block_cells
            or not record.get("mouse_id")
            or record.get("session_count", 0) < 1
            or record.get("mean_forward_speed_cm_s", -1) < 0
        ):
            raise RuntimeError("Running-statistics mouse/block summary is invalid.")
    for record in mouse_context:
        if (
            (record.get("modality"), record.get("context")) not in expected_cells
            or not record.get("mouse_id")
            or record.get("session_count", 0) < 1
            or record.get("mean_forward_speed_cm_s", -1) < 0
            or record.get("control_mean_forward_speed_cm_s", -1) < 0
            or record.get("context_mean_forward_speed_cm_s", -1) < 0
            or not 0 <= record.get("running_fraction", -1) <= 1
        ):
            raise RuntimeError("Running-statistics mouse summary is invalid.")
    for record in coverage:
        matching_sessions = [
            session
            for session in sessions
            if session["modality"] == record["modality"]
            and session["context"] == record["context"]
        ]
        matching_mice = [
            summary
            for summary in mouse_context
            if summary["modality"] == record["modality"]
            and summary["context"] == record["context"]
        ]
        if (
            len(matching_sessions) != record["included_sessions"]
            or len(matching_mice) != record["included_mice"]
        ):
            raise RuntimeError("Running-statistics counts do not match coverage.")
    return payload


def behavior_video_time_at(time_map: list[list[float]], local_time: float) -> float:
    if local_time <= time_map[0][0]:
        return time_map[0][1]
    if local_time >= time_map[-1][0]:
        return time_map[-1][1]
    low = 0
    high = len(time_map) - 1
    while low + 1 < high:
        middle = (low + high) // 2
        if time_map[middle][0] <= local_time:
            low = middle
        else:
            high = middle
    first = time_map[low]
    second = time_map[high]
    fraction = (local_time - first[0]) / (second[0] - first[0])
    return first[1] + (second[1] - first[1]) * fraction


def load_behavior_static_frames(
    payload: dict, profiles: dict[str, dict]
) -> dict[tuple[str, str], Path]:
    provenance = json.loads(
        BEHAVIOR_STATIC_FRAME_PROVENANCE_PATH.read_text(encoding="utf-8")
    )
    source_checksum = hashlib.sha256(BEHAVIOR_EXCERPTS_PATH.read_bytes()).hexdigest()
    running_checksum = hashlib.sha256(RUNNING_STATISTICS_PATH.read_bytes()).hexdigest()
    if (
        provenance.get("version") != 2
        or provenance.get("behavior_excerpts_sha256") != source_checksum
        or provenance.get("running_statistics_sha256") != running_checksum
        or provenance.get("local_time_seconds") != BEHAVIOR_STATIC_LOCAL_TIME_SECONDS
    ):
        raise RuntimeError("Static behavior frame provenance is not supported.")

    sessions = {session["id"]: session for session in payload["sessions"]}
    expected_keys = {
        (session["id"], camera["id"])
        for session in payload["sessions"]
        for camera in session["cameras"]
    }
    records = {
        (record["modality"], record["camera_id"]): record
        for record in provenance.get("frames", [])
    }
    if set(records) != expected_keys:
        raise RuntimeError("Static behavior frame selections do not match provenance.")

    paths = {}
    for modality, camera_id in sorted(expected_keys):
        session = sessions[modality]
        camera = next(camera for camera in session["cameras"] if camera["id"] == camera_id)
        record = records[(modality, camera_id)]
        profile = profiles[modality]
        if record.get("selection") == "excerpt_local_time_seconds":
            source = next(
                source
                for source in session["sources"]
                if source.get("url") == camera["url"]
            )
            target_time = behavior_video_time_at(
                camera["timeMap"], BEHAVIOR_STATIC_LOCAL_TIME_SECONDS
            )
            source_matches = (
                record["source_url"] == camera["url"]
                and record["source_etag"] == source["etag"]
                and record["source_content_length"] == source["contentLength"]
                and record.get("local_time_seconds")
                == BEHAVIOR_STATIC_LOCAL_TIME_SECONDS
            )
        elif record.get("selection") == "video_time_seconds" and modality == "slap2":
            target_time = record["target_video_time_seconds"]
            expected_url = (
                "https://aind-open-data.s3.us-west-2.amazonaws.com/"
                f'{profile["source_session_id"]}/behavior-videos/'
                f'{camera["label"]}Camera/video.mp4'
            )
            source_matches = (
                record["source_url"] == expected_url
                and record["source_etag"]
                and record["source_content_length"] > 0
                and record.get("local_time_seconds") is None
            )
        else:
            raise RuntimeError(
                f"Static behavior frame selection is invalid: {modality}/{camera_id}"
            )
        path = BEHAVIOR_STATIC_FRAME_DIR / record["asset_path"]
        frame_interval = 1 / camera["timing"]["encodedRateHz"]
        contrast = record.get("display_contrast", {})
        if (
            record["camera_label"] != camera["label"]
            or record.get("mouse_id") != profile["mouse_id"]
            or record.get("source_session_id") != profile["source_session_id"]
            or not source_matches
            or contrast.get("method")
            != "luminance percentile stretch with adaptive gamma"
            or contrast.get("low_percentile") != 1.0
            or contrast.get("high_percentile") != 99.0
            or contrast.get("target_median") != 0.35
            or not 0
            <= contrast.get("low_value", -1)
            < contrast.get("high_value", -1)
            <= 255
            or not 0.35 <= contrast.get("gamma", 0) <= 1.0
            or not math.isclose(record["target_video_time_seconds"], target_time)
            or record["decoded_video_time_seconds"] < target_time
            or record["decoded_video_time_seconds"] - target_time > frame_interval * 1.1
            or hashlib.sha256(path.read_bytes()).hexdigest()
            != record["output_sha256"]
        ):
            raise RuntimeError(f"Static behavior frame checksum mismatch: {path.name}")
        paths[(modality, camera_id)] = path
    return paths


def running_profile_svg(
    profile: dict,
    modality: str,
    accent: str,
    left: float,
    top: float,
    width: float,
    height: float,
    speed_limit: float,
    shared_duration: float,
    show_block_labels: bool,
    show_time_axis: bool,
) -> list[str]:
    margin_left = 46
    margin_right = 12
    margin_top = 20
    margin_bottom = 22
    plot_left = left + margin_left
    plot_top = top + margin_top
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    duration = shared_duration

    def x(time: float) -> float:
        return plot_left + time / duration * plot_width

    def y(value: float) -> float:
        return plot_top + (speed_limit - value) / speed_limit * plot_height

    block_labels = {
        "standard": "Std",
        "context": "Context",
        "standard_repeat": "Std 2",
        "sequence": "Seq",
        "jitter": "Jitter",
        "open_loop": "Open",
        "movie": "Movie",
        "rf": "RF",
    }
    svg = [
        f'<rect x="{left}" y="{top}" width="{width}" height="{height}" '
        'fill="#FFFFFF" stroke="#D0D4D2"/>',
    ]
    for block in profile["blocks"]:
        block_left = x(block["start_seconds"])
        block_right = x(block["end_seconds"])
        svg.extend(
            [
                f'<rect class="running-profile-block" data-block="{block["id"]}" '
                f'x="{block_left:.2f}" y="{top + 1}" '
                f'width="{max(0, block_right - block_left):.2f}" height="{height - 2}" '
                f'fill="{PROTOCOL_BLOCK_COLORS[block["id"]]}" fill-opacity="0.18"/>',
                f'<rect x="{block_left:.2f}" y="{top + 1}" '
                f'width="{max(0, block_right - block_left):.2f}" height="18" '
                f'fill="{PROTOCOL_BLOCK_COLORS[block["id"]]}"/>',
                f'<line x1="{block_left:.2f}" y1="{top}" x2="{block_left:.2f}" '
                f'y2="{top + height}" stroke="#C8CECB"/>',
            ]
        )
        if show_block_labels:
            label_fill = "#FFFFFF" if block["id"] in {"context", "movie", "rf"} else "#172126"
            svg.append(
                f'<text x="{(block_left + block_right) / 2:.2f}" y="{top + 14}" '
                'font-family="Source Sans 3, sans-serif" font-size="12" '
                f'font-weight="600" text-anchor="middle" fill="{label_fill}">'
                f'{block_labels[block["id"]]}</text>'
            )
    for fraction in (0, 0.5, 1):
        grid_y = plot_top + (1 - fraction) * plot_height
        svg.extend(
            [
                f'<line x1="{plot_left}" y1="{grid_y:.2f}" '
                f'x2="{plot_left + plot_width}" y2="{grid_y:.2f}" '
                'stroke="#D8DCDA"/>',
                f'<text x="{plot_left - 7}" y="{grid_y + 4:.2f}" '
                'font-family="IBM Plex Mono, monospace" font-size="12" '
                f'text-anchor="end" fill="#68706E">{fraction * speed_limit:.0f}</text>',
            ]
        )
    points = " ".join(
        f'{x(point[0]):.2f},{y(min(speed_limit, point[1])):.2f}'
        for point in profile["points"]
    )
    svg.append(
        f'<polyline class="running-profile" data-modality="{modality}" '
        f'points="{points}" fill="none" stroke="{accent}" stroke-width="1.6"/>'
    )
    if show_time_axis:
        tick_minutes = [0, 20, 40, 60, round(duration / 60)]
        for minute in dict.fromkeys(tick_minutes):
            tick_time = min(duration, minute * 60)
            svg.append(
                f'<text x="{x(tick_time):.2f}" y="{top + height - 6}" '
                'font-family="IBM Plex Mono, monospace" font-size="12" '
                f'text-anchor="middle" fill="#68706E">{minute}m</text>'
            )
    return svg


def running_speed_limit(maximum: float) -> int:
    step = 10 if maximum > 25 else 5
    return max(step, math.ceil(maximum * 1.05 / step) * step)


def running_summary_svg(payload: dict) -> list[str]:
    summaries = payload["mouse_block"]
    modality_colors = {
        "neuropixels": "#4B79C6",
        "mesoscope": "#14866C",
        "slap2": "#168EA0",
    }
    modality_labels = {
        "neuropixels": "Neuropixels",
        "mesoscope": "Mesoscope",
        "slap2": "SLAP2",
    }
    block_labels = {
        "standard": "Standard",
        "context": "Context",
        "standard_repeat": "Standard repeat",
        "sequence": "Sequence",
        "jitter": "Jitter",
        "open_loop": "Open loop",
        "movie": "Natural movie",
        "rf": "RF mapping",
    }
    block_order = tuple(PROTOCOL_BLOCK_COLORS)
    profile_block_order = tuple(block["id"] for block in payload["example_profiles"][0]["blocks"])
    if block_order != profile_block_order:
        raise RuntimeError("Panel D block order does not match the example profiles.")
    speed_limit = running_speed_limit(
        max(record["mean_forward_speed_cm_s"] for record in summaries)
    )
    plot_left = 185
    plot_width = 1560
    block_label_y = 735
    plot_top = 745
    plot_height = 255
    plot_bottom = plot_top + plot_height
    modality_offsets = {
        "neuropixels": -52,
        "mesoscope": 0,
        "slap2": 52,
    }
    mouse_counts = {
        modality: len(
            {
                record["mouse_id"]
                for record in summaries
                if record["modality"] == modality
            }
        )
        for modality in modality_labels
    }
    svg = [
        '<text class="running-panel-label" x="35" y="704" '
        'font-family="Source Sans 3, sans-serif" font-size="24" '
        'font-weight="700" fill="#293133">D</text>',
        '<text class="running-y-axis-title" x="72" y="704" '
        'font-family="Source Sans 3, sans-serif" font-size="16" '
        'font-weight="700" fill="#3F4745">Mean forward speed (cm/s)</text>',
    ]
    legend_left = 980
    for index, modality in enumerate(modality_labels):
        left = legend_left + index * 250
        color = modality_colors[modality]
        svg.extend(
            [
                f'<rect x="{left}" y="686" width="18" height="18" '
                f'fill="{color}" fill-opacity="0.42" stroke="{color}" '
                'stroke-width="1.5"/>',
                f'<text x="{left + 27}" y="701" '
                'font-family="Source Sans 3, sans-serif" font-size="16" '
                f'font-weight="700" fill="{color}">{modality_labels[modality]} '
                f'(n={mouse_counts[modality]})</text>',
            ]
        )
    svg.append('<g class="running-summary-plot" data-shared-y-axis="true">')
    block_width = plot_width / len(block_order)
    for block_index, block_id in enumerate(block_order):
        left = plot_left + block_index * block_width
        color = PROTOCOL_BLOCK_COLORS[block_id]
        svg.extend(
            [
                f'<rect class="running-block-region" data-block="{block_id}" '
                f'x="{left:.2f}" y="{plot_top}" width="{block_width:.2f}" '
                f'height="{plot_height}" fill="{color}" fill-opacity="0.08"/>',
                f'<text x="{left + block_width / 2:.2f}" y="{block_label_y}" '
                'font-family="Source Sans 3, sans-serif" font-size="14" '
                'font-weight="700" text-anchor="middle" fill="#3F4745">'
                f'{block_labels[block_id]}</text>',
            ]
        )
        if block_index:
            svg.append(
                f'<line x1="{left:.2f}" y1="{plot_top}" '
                f'x2="{left:.2f}" y2="{plot_bottom}" stroke="#C8CECB"/>'
            )
    tick_step = 30 if speed_limit > 80 else 20 if speed_limit > 40 else 10
    tick_values = list(range(0, speed_limit, tick_step)) + [speed_limit]
    for tick_value in tick_values:
        y = plot_bottom - tick_value / speed_limit * plot_height
        grid_color = "#AEB5B2" if tick_value == 0 else "#DDE1DF"
        svg.append(
            f'<line x1="{plot_left}" y1="{y:.2f}" '
            f'x2="{plot_left + plot_width}" y2="{y:.2f}" stroke="{grid_color}"/>'
        )
        svg.append(
            f'<text x="{plot_left - 10}" y="{y + 4:.2f}" '
            'font-family="IBM Plex Mono, monospace" font-size="13" '
            f'text-anchor="end" fill="#68706E">{tick_value}</text>'
        )
    for block_index, block_id in enumerate(block_order):
        block_center = plot_left + (block_index + 0.5) * block_width
        for modality, offset in modality_offsets.items():
            center = block_center + offset
            records = [
                record
                for record in summaries
                if record["modality"] == modality
                and record["block"] == block_id
            ]
            values = [record["mean_forward_speed_cm_s"] for record in records]
            mean = statistics.fmean(values)
            mean_y = plot_bottom - min(1, mean / speed_limit) * plot_height
            color = modality_colors[modality]
            svg.append(
                f'<rect class="running-block-mean" data-block="{block_id}" '
                f'data-modality="{modality}" x="{center - 19:.2f}" '
                f'y="{mean_y:.2f}" width="38" height="{plot_bottom - mean_y:.2f}" '
                f'fill="{color}" fill-opacity="0.38" stroke="{color}" '
                'stroke-width="1.4"/>'
            )
            svg.append(
                f'<line class="running-block-mean-cap" data-block="{block_id}" '
                f'data-modality="{modality}" x1="{center - 20:.2f}" '
                f'y1="{mean_y:.2f}" x2="{center + 20:.2f}" y2="{mean_y:.2f}" '
                f'stroke="{color}" stroke-width="2.4"/>'
            )
            for record in records:
                value = record["mean_forward_speed_cm_s"]
                jitter_hash = 0
                for character in f'{modality}:{block_id}:{record["mouse_id"]}':
                    jitter_hash = (jitter_hash * 31 + ord(character)) & 0xFFFFFFFF
                jitter = ((jitter_hash % 1001) / 1000 - 0.5) * 28
                point_y = plot_bottom - min(1, value / speed_limit) * plot_height
                svg.append(
                    '<circle class="running-block-point" '
                    f'data-block="{block_id}" data-modality="{modality}" '
                    f'cx="{center + jitter:.2f}" cy="{point_y:.2f}" r="3" '
                    f'fill="{color}" fill-opacity="0.72" stroke="#FFFFFF" '
                    'stroke-width="0.5"/>'
                )
    svg.append("</g>")
    return svg


def write_behavior_static_svg(output: Path = BEHAVIOR_STATIC_OUTPUT) -> Path:
    payload = load_behavior_excerpts()
    running_statistics = load_running_statistics()
    logo_paths = load_platform_logos()
    profiles = {
        profile["modality"]: profile
        for profile in running_statistics["example_profiles"]
    }
    shared_profile_duration = max(
        profile["duration_seconds"] for profile in profiles.values()
    )
    profile_speed_limits = {
        modality: running_speed_limit(max(point[1] for point in profile["points"]))
        for modality, profile in profiles.items()
    }
    frame_paths = load_behavior_static_frames(payload, profiles)
    width = 1800
    height = 1080
    row_tops = (40, 276, 512)
    accents = {
        "neuropixels": "#4B79C6",
        "mesoscope": "#14866C",
        "slap2": "#168EA0",
    }
    modality_labels = {
        "neuropixels": "Neuropixels",
        "mesoscope": "Mesoscope",
        "slap2": "SLAP2",
    }
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title description">',
        '<title id="title">Synchronized behavior recordings across three modalities</title>',
        '<desc id="description">Camera stills and full-session running profiles '
        'from the same Neuropixels, mesoscope, and SLAP2 mice and sessions, followed '
        'by a shared-axis comparison of mouse-level mean running speed in each '
        'protocol block.</desc>',
        f'<rect width="{width}" height="{height}" fill="#FFFFFF"/>',
    ]
    for row_index, (letter, session, row_top) in enumerate(
        zip("ABC", payload["sessions"], row_tops, strict=True)
    ):
        modality = session["id"]
        cameras = session["cameras"]
        profile = profiles[modality]
        logo_data = base64.b64encode(logo_paths[modality].read_bytes()).decode()
        svg.extend(
            [
                f'<g class="platform-heading" data-modality="{modality}">',
                f'<text x="35" y="{row_top}" font-family="Source Sans 3, sans-serif" '
                f'font-size="24" font-weight="700" fill="#293133">{letter}</text>',
                f'<image class="platform-logo" href="data:image/png;base64,{logo_data}" '
                f'x="63" y="{row_top - 38}" width="54" height="54" '
                'preserveAspectRatio="xMidYMid meet"/>',
                f'<text x="125" y="{row_top}" font-family="Source Sans 3, sans-serif" '
                'font-size="24" font-weight="700" fill="#293133">'
                f'{modality_labels[modality]} · mouse {escape(profile["mouse_id"])}</text>',
                "</g>",
            ]
        )
        camera_width = 198
        camera_height = 148
        camera_gap = 12
        camera_top = row_top + 42
        for index, camera in enumerate(cameras):
            left = 35 + index * (camera_width + camera_gap)
            image_data = base64.b64encode(
                frame_paths[(modality, camera["id"])].read_bytes()
            ).decode()
            svg.extend(
                [
                    f'<g class="behavior-camera-card" data-modality="{modality}" '
                    f'data-camera-id="{camera["id"]}">',
                    f'<text x="{left}" y="{camera_top - 8}" '
                    'font-family="Source Sans 3, sans-serif" font-size="15" '
                    f'font-weight="700" fill="#303536">{escape(camera["label"])} camera</text>',
                    f'<rect x="{left}" y="{camera_top}" width="{camera_width}" '
                    f'height="{camera_height}" fill="#171A19"/>',
                    f'<image href="data:image/jpeg;base64,{image_data}" x="{left}" '
                    f'y="{camera_top}" width="{camera_width}" height="{camera_height}" '
                    'preserveAspectRatio="xMidYMid meet"/>',
                    f'<rect x="{left}" y="{camera_top}" width="{camera_width}" '
                    f'height="{camera_height}" fill="none" stroke="#8F9996"/>',
                    "</g>",
                ]
            )

        svg.extend(
            running_profile_svg(
                profile,
                modality,
                accents[modality],
                910,
                row_top + 28,
                850,
                148,
                profile_speed_limits[modality],
                shared_profile_duration,
                row_index == 0,
                row_index == 2,
            )
        )
    svg.append('<g class="running-summary" transform="translate(0 30)">')
    svg.extend(running_summary_svg(running_statistics))
    svg.append("</g>")
    svg.append("</svg>")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(svg) + "\n", encoding="utf-8")
    return output


def write_behavior_viewer_html(
    output: Path = BEHAVIOR_VIEWER_OUTPUT,
    static_output: Path = BEHAVIOR_STATIC_OUTPUT,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = load_behavior_excerpts()
    logo_data_uris = platform_logo_data_uris()
    for session in payload["sessions"]:
        session["logo"] = logo_data_uris[session["id"]]
    write_behavior_static_svg(static_output)
    template = (JAVASCRIPT_DIR / "behavior-viewer.html").read_text(encoding="utf-8")
    stylesheet = (JAVASCRIPT_DIR / "behavior-viewer.css").read_text(encoding="utf-8")
    javascript = (JAVASCRIPT_DIR / "behavior-viewer.js").read_text(encoding="utf-8")
    html = (
        template.replace("__BEHAVIOR_CSS__", stylesheet)
        .replace(
            "__BEHAVIOR_STATIC_IMAGE__",
            f"media/behavior-viewer/{static_output.name}",
        )
        .replace(
            "__BEHAVIOR_DATA__",
            json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
        )
        .replace("__BEHAVIOR_JS__", javascript)
        .replace("__EMBED_AUTO_HEIGHT_JS__", load_embed_auto_height())
    )
    output.write_text(html, encoding="utf-8")
    media_output = output.parent / "media" / "behavior-viewer"
    if media_output.exists():
        shutil.rmtree(media_output)
    media_output.mkdir(parents=True)
    shutil.copy2(static_output, media_output / static_output.name)
    return output


def load_neural_excerpts(
    path: Path = NEURAL_EXCERPTS_PATH,
    behavior_path: Path = BEHAVIOR_EXCERPTS_PATH,
) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    behavior_checksum = hashlib.sha256(behavior_path.read_bytes()).hexdigest()
    if (
        payload.get("version") != 7
        or payload.get("windowStartSeconds") != -1.0
        or payload.get("windowEndSeconds") != 3.0
        or payload.get("behaviorExcerptSha256") != behavior_checksum
    ):
        raise RuntimeError("Neural excerpt schema or behavior source is not supported.")
    sessions = payload.get("sessions", [])
    expected_options = {"neuropixels": 6, "mesoscope": 8, "slap2": 4}
    expected_views = {"neuropixels": "heatmap", "mesoscope": "movie", "slap2": "movie"}
    if [session.get("id") for session in sessions] != list(expected_options):
        raise RuntimeError("Neural excerpts must contain the three modalities in order.")
    for session in sessions:
        options = session.get("options", [])
        if (
            len(options) != expected_options[session["id"]]
            or session.get("viewType") != expected_views[session["id"]]
        ):
            raise RuntimeError(f"Neural excerpt option count changed: {session['id']}")
        if session.get("event", {}).get("time") != 0.0 or not any(
            row["start"] <= 0 <= row["end"] for row in session.get("stimulus", [])
        ):
            raise RuntimeError(f"Neural event lacks a stimulus row: {session['id']}")
        if not session.get("sources") or not all(
            source.get("sha256")
            or source.get("etag")
            or source.get("rangeSha256")
            for source in session["sources"]
        ):
            raise RuntimeError(f"Neural excerpt lacks source provenance: {session['id']}")
        for option in options:
            if not isinstance(option.get("anatomyLabel"), str) or not option[
                "anatomyLabel"
            ].strip():
                raise RuntimeError(
                    f"Neural excerpt lacks anatomical context: "
                    f"{session['id']}/{option['id']}"
                )
            if session["viewType"] == "heatmap":
                rows = option.get("rows")
                columns = option.get("columns")
                try:
                    encoded = base64.b64decode(option.get("dataBase64", ""), validate=True)
                except ValueError as exc:
                    raise RuntimeError(
                        f"Neural heatmap encoding is invalid: {option['id']}"
                    ) from exc
                if (
                    rows != 96
                    or columns != 3000
                    or len(encoded) != rows * columns
                    or len(option.get("sourceChannels", [])) != 96
                    or option.get("nativeSampleRateHz") != 30_000.0
                    or option.get("timeStartSeconds", 0) > -0.0499
                    or option.get("timeEndSeconds", 0) < 0.0498
                    or not math.isfinite(option.get("valueLimit", math.nan))
                ):
                    raise RuntimeError(f"Neural heatmap is invalid: {option['id']}")
                expected_start = 0
                for segment in option.get("anatomySegments", []):
                    start = segment.get("startRow")
                    end = segment.get("endRow")
                    if (
                        start != expected_start
                        or not isinstance(end, int)
                        or end <= start
                        or end > rows
                        or not isinstance(segment.get("label"), str)
                        or not segment["label"].strip()
                    ):
                        raise RuntimeError(
                            f"Neural anatomy segment is invalid: {option['id']}"
                        )
                    expected_start = end
                if expected_start != rows:
                    raise RuntimeError(
                        f"Neural anatomy does not cover the shaft: {option['id']}"
                    )
            else:
                times = option.get("frameTimes", [])
                asset_path = NEURAL_MEDIA_DIR / Path(option.get("assetPath", "")).name
                expected_pixel_size = 0.78 if session["id"] == "mesoscope" else 0.25
                slap2_asset_valid = True
                if session["id"] == "slap2":
                    composite_path = NEURAL_MEDIA_DIR / Path(
                        option.get("compositeAssetPath", "")
                    ).name
                    slap2_asset_valid = (
                        option.get("frameWidth") == 640
                        and option.get("frameHeight") == 400
                        and option.get("spatialDownsampleFactor") == 2
                        and option.get("spriteEncoding") == "lossless WebP"
                        and composite_path.is_file()
                        and hashlib.sha256(composite_path.read_bytes()).hexdigest()
                        == option.get("compositeSheetSha256")
                    )
                if (
                    len(times) != option.get("frameCount")
                    or len(times) < 2
                    or times[0] > -0.9
                    or times[-1] < 2.89
                    or any(
                        current <= previous
                        for previous, current in zip(times[:-1], times[1:], strict=True)
                    )
                    or not asset_path.is_file()
                    or hashlib.sha256(asset_path.read_bytes()).hexdigest()
                    != option.get("sheetSha256")
                    or not math.isclose(
                        option.get("micronsPerPixel", math.nan),
                        expected_pixel_size,
                    )
                    or not slap2_asset_valid
                ):
                    raise RuntimeError(
                        f"Neural movie asset is invalid: {session['id']}/{option['id']}"
                    )
    return payload


def png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type)
    checksum = zlib.crc32(data, checksum)
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", checksum)


def encode_rgb_png(width: int, height: int, pixels: bytes) -> bytes:
    if len(pixels) != width * height * 3:
        raise RuntimeError("RGB pixel buffer does not match its declared dimensions.")
    stride = width * 3
    scanlines = b"".join(
        b"\x00" + pixels[row * stride : (row + 1) * stride]
        for row in range(height)
    )
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
            png_chunk(b"IDAT", zlib.compress(scanlines, level=9)),
            png_chunk(b"IEND", b""),
        )
    )


def neural_voltage_rgb(encoded: int) -> tuple[int, int, int]:
    centered = max(-1.0, min(1.0, (encoded - 127.5) / 127.5))
    if centered < 0:
        amount = centered + 1
        return (
            round(28 + amount * 218),
            round(77 + amount * 169),
            round(151 + amount * 95),
        )
    return (
        round(246 - centered * 57),
        round(246 - centered * 192),
        round(246 - centered * 205),
    )


def neural_heatmap_png(option: dict) -> bytes:
    encoded = base64.b64decode(option["dataBase64"], validate=True)
    pixels = bytearray()
    for value in encoded:
        pixels.extend(neural_voltage_rgb(value))
    return encode_rgb_png(option["columns"], option["rows"], bytes(pixels))


def load_neural_static_frames(payload: dict) -> dict[tuple[str, str], Path]:
    provenance = json.loads(
        NEURAL_STATIC_FRAME_PROVENANCE_PATH.read_text(encoding="utf-8")
    )
    source_checksum = hashlib.sha256(NEURAL_EXCERPTS_PATH.read_bytes()).hexdigest()
    if (
        provenance.get("version") != 2
        or provenance.get("raw_neural_excerpts_sha256") != source_checksum
    ):
        raise RuntimeError("Static neural frame provenance is not supported.")

    sessions = {session["id"]: session for session in payload["sessions"]}
    records = {
        (record["modality"], record["option_id"]): record
        for record in provenance.get("frames", [])
    }
    expected_keys = {
        (modality, option_id)
        for modality in ("mesoscope", "slap2")
        for option_id in NEURAL_STATIC_SELECTIONS[modality]
    }
    if set(records) != expected_keys:
        raise RuntimeError("Static neural frame selections do not match provenance.")

    paths = {}
    for modality, option_id in sorted(expected_keys):
        record = records[(modality, option_id)]
        path = NEURAL_STATIC_FRAME_DIR / record["asset_path"]
        if modality == "mesoscope":
            option = next(
                option
                for option in sessions[modality]["options"]
                if option["id"] == option_id
            )
            frame_index = len(option["frameTimes"]) // 2
            contrast = record.get("display_contrast", {})
            valid = (
                record["frame_index"] == frame_index
                and record["frame_time_seconds"] == option["frameTimes"][frame_index]
                and record["source_sheet_sha256"] == option["sheetSha256"]
                and contrast.get("method")
                == "max-channel hue-preserving linear stretch"
                and contrast.get("low_percentile") == 1.0
                and contrast.get("high_percentile") == 99.5
                and 0
                <= contrast.get("low_value", -1)
                < contrast.get("high_value", -1)
                <= 255
            )
        else:
            source_option_ids = SLAP2_STATIC_COMPOSITES[option_id]
            source_options = [
                next(
                    option
                    for option in sessions[modality]["options"]
                    if option["id"] == source_option_id
                )
                for source_option_id in source_option_ids
            ]
            green_option, red_option = source_options
            frame_index = len(green_option["frameTimes"]) // 2
            composite = record.get("channel_composite", {})
            display_contrast = record.get("display_contrast", {})
            valid = (
                record.get("source_option_ids") == list(source_option_ids)
                and green_option["frameTimes"] == red_option["frameTimes"]
                and green_option["compositeAssetPath"]
                == red_option["compositeAssetPath"]
                and green_option["compositeSheetSha256"]
                == red_option["compositeSheetSha256"]
                and record["source_sheet_sha256"]
                == green_option["compositeSheetSha256"]
                and record["frame_index"] == frame_index
                and record["frame_time_seconds"]
                == green_option["frameTimes"][frame_index]
                and record.get("frame_size")
                == [green_option["frameWidth"], green_option["frameHeight"]]
                and record.get("spatial_downsample_factor") == 2
                and record.get("temporal_averaging_frames") == 1
                and composite.get("green") == green_option["measurement"]
                and composite.get("red") == red_option["measurement"]
                and composite.get("source_low_percentile") == 1.0
                and composite.get("source_high_percentile") == 99.5
                and display_contrast.get("method")
                == "max-channel hue-preserving gamma"
                and display_contrast.get("gamma") == 0.55
            )
        if (
            not valid
            or hashlib.sha256(path.read_bytes()).hexdigest()
            != record["output_sha256"]
        ):
            raise RuntimeError(f"Static neural frame checksum mismatch: {path.name}")
        paths[(modality, option_id)] = path
    return paths


def append_static_scale_bar(
    svg: list[str],
    *,
    x: float,
    y: float,
    display_width: float,
    native_width: int,
    microns_per_pixel: float,
    microns: int,
) -> None:
    bar_width = display_width * microns / (native_width * microns_per_pixel)
    svg.extend(
        [
            f'<line x1="{x:.2f}" y1="{y:.2f}" x2="{x + bar_width:.2f}" '
            f'y2="{y:.2f}" stroke="#111111" stroke-width="7"/>',
            f'<line x1="{x:.2f}" y1="{y:.2f}" x2="{x + bar_width:.2f}" '
            f'y2="{y:.2f}" stroke="#FFFFFF" stroke-width="4"/>',
            f'<text x="{x + bar_width / 2:.2f}" y="{y - 9:.2f}" '
            'font-family="Source Sans 3, sans-serif" font-size="12" '
            f'font-weight="700" text-anchor="middle" fill="#FFFFFF">{microns} µm</text>',
        ]
    )


def append_neuropixels_raw_card(
    svg: list[str],
    *,
    x: float,
    y: float,
    option: dict,
    show_axis: bool,
) -> None:
    card_width = 540
    card_height = 225
    header_height = 28
    image_height = 145
    anatomy_x = x + 7
    anatomy_width = 62
    heatmap_x = anatomy_x + anatomy_width + 7
    heatmap_width = 445
    image_y = y + header_height
    image_data = base64.b64encode(neural_heatmap_png(option)).decode()
    svg.extend(
        [
            f'<g class="raw-image-card" data-modality="neuropixels" '
            f'data-option-id="{option["id"]}">',
            f'<rect x="{x + 5:.2f}" y="{y + 6:.2f}" width="{card_width}" '
            f'height="{card_height}" rx="3" fill="#D9DEDC" opacity="0.65"/>',
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{card_width}" '
            f'height="{card_height}" rx="3" fill="#FFFFFF" stroke="#8F9996"/>',
            f'<text x="{x + 9:.2f}" y="{y + 19:.2f}" '
            'font-family="Source Sans 3, sans-serif" font-size="13" '
            f'font-weight="700" fill="#303536">{escape(option["label"])}</text>',
            f'<text x="{x + card_width - 9:.2f}" y="{y + 19:.2f}" '
            'font-family="IBM Plex Mono, monospace" font-size="10" '
            f'text-anchor="end" fill="#59615F">±{option["valueLimit"]:.0f} µV</text>',
        ]
    )
    for index, segment in enumerate(option["anatomySegments"]):
        segment_y = image_y + segment["startRow"] / option["rows"] * image_height
        segment_height = (
            (segment["endRow"] - segment["startRow"])
            / option["rows"]
            * image_height
        )
        fill = "#F5F6F6" if segment["label"] == "void" else (
            "#E2E7E5" if index % 2 == 0 else "#EEF1F0"
        )
        svg.append(
            f'<rect x="{anatomy_x:.2f}" y="{segment_y:.2f}" '
            f'width="{anatomy_width}" height="{segment_height:.2f}" fill="{fill}"/>'
        )
        if segment_height >= 11:
            svg.append(
                f'<text x="{anatomy_x + anatomy_width / 2:.2f}" '
                f'y="{segment_y + segment_height / 2 + 3:.2f}" '
                'font-family="Source Sans 3, sans-serif" font-size="8" '
                f'font-weight="600" text-anchor="middle" fill="#3F4745">'
                f'{escape(segment["label"])}</text>'
            )
    svg.extend(
        [
            f'<rect x="{anatomy_x:.2f}" y="{image_y:.2f}" width="{anatomy_width}" '
            f'height="{image_height}" fill="none" stroke="#8F9996"/>',
            f'<image class="raw-card-image" href="data:image/png;base64,{image_data}" '
            f'x="{heatmap_x:.2f}" y="{image_y:.2f}" width="{heatmap_width}" '
            f'height="{image_height}" preserveAspectRatio="none"/>',
            f'<rect x="{heatmap_x:.2f}" y="{image_y:.2f}" width="{heatmap_width}" '
            f'height="{image_height}" fill="none" stroke="#8F9996"/>',
        ]
    )
    if show_axis:
        axis_y = image_y + image_height + 6
        for tick_index, milliseconds in enumerate((0, 25, 50, 75, 100)):
            tick_x = heatmap_x + tick_index / 4 * heatmap_width
            svg.extend(
                [
                    f'<line x1="{tick_x:.2f}" y1="{image_y + image_height:.2f}" '
                    f'x2="{tick_x:.2f}" y2="{axis_y:.2f}" stroke="#6C7572"/>',
                    f'<text x="{tick_x:.2f}" y="{axis_y + 13:.2f}" '
                    'font-family="IBM Plex Mono, monospace" font-size="9" '
                    f'text-anchor="middle" fill="#59615F">{milliseconds}</text>',
                ]
            )
        svg.append(
            f'<text x="{heatmap_x + heatmap_width / 2:.2f}" y="{axis_y + 29:.2f}" '
            'font-family="Source Sans 3, sans-serif" font-size="10" '
            'text-anchor="middle" fill="#4D5553">100 ms raw AP excerpt</text>'
        )
    svg.append("</g>")


def append_microscopy_raw_card(
    svg: list[str],
    *,
    x: float,
    y: float,
    card_width: float,
    option: dict,
    path: Path,
    modality: str,
    label: str,
    show_scale: bool,
) -> float:
    padding = 7
    header_height = 27
    image_width = card_width - 2 * padding
    image_height = image_width * option["nativeHeight"] / option["nativeWidth"]
    card_height = header_height + image_height + padding
    image_x = x + padding
    image_y = y + header_height
    image_data = base64.b64encode(path.read_bytes()).decode()
    svg.extend(
        [
            f'<g class="raw-image-card" data-modality="{modality}" '
            f'data-option-id="{option["id"]}" data-card-width="{card_width:.0f}">',
            f'<rect x="{x + 5:.2f}" y="{y + 6:.2f}" width="{card_width}" '
            f'height="{card_height:.2f}" rx="3" fill="#D9DEDC" opacity="0.65"/>',
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{card_width}" '
            f'height="{card_height:.2f}" rx="3" fill="#FFFFFF" stroke="#8F9996"/>',
            f'<text x="{x + padding:.2f}" y="{y + 18:.2f}" '
            'font-family="Source Sans 3, sans-serif" font-size="12" '
            f'font-weight="700" fill="#303536">{escape(label)}</text>',
            f'<image class="raw-card-image" href="data:image/png;base64,{image_data}" '
            f'x="{image_x:.2f}" y="{image_y:.2f}" width="{image_width:.2f}" '
            f'height="{image_height:.2f}"/>',
            f'<rect x="{image_x:.2f}" y="{image_y:.2f}" width="{image_width:.2f}" '
            f'height="{image_height:.2f}" fill="none" stroke="#8F9996"/>',
        ]
    )
    if show_scale:
        append_static_scale_bar(
            svg,
            x=image_x + 12,
            y=image_y + image_height - 14,
            display_width=image_width,
            native_width=option["nativeWidth"],
            microns_per_pixel=option["micronsPerPixel"],
            microns=50 if modality == "mesoscope" else 25,
        )
    svg.append("</g>")
    return card_height


def write_neural_static_svg(output: Path = NEURAL_STATIC_OUTPUT) -> Path:
    payload = load_neural_excerpts()
    sessions = {session["id"]: session for session in payload["sessions"]}
    frame_paths = load_neural_static_frames(payload)
    logo_paths = load_platform_logos()
    width = 1800
    height = 660
    panel_lefts = {"neuropixels": 35, "mesoscope": 645, "slap2": 1235}
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title description">',
        '<title id="title">Raw recording stacks across three modalities</title>',
        '<desc id="description">Six stacked Neuropixels probe heatmaps, two stacks '
        'containing eight mesoscope plane images, and two SLAP2 plane images merging '
        'green iGluSnFR4f with red RCaMP3 show the native raw-data formats.</desc>',
        f'<rect width="{width}" height="{height}" fill="#FFFFFF"/>',
    ]
    summaries = {
        "neuropixels": "6 probe recordings · all raw excerpts stacked",
        "mesoscope": "8 planes · 4 VISp + 4 VISl · all raw frames stacked",
        "slap2": "2 VISp planes · merged green + red channels",
    }
    for letter, label, modality in (
        ("A", "Neuropixels", "neuropixels"),
        ("B", "Mesoscope", "mesoscope"),
        ("C", "SLAP2", "slap2"),
    ):
        left = panel_lefts[modality]
        logo_size = 96
        logo_data = base64.b64encode(logo_paths[modality].read_bytes()).decode()
        svg.extend(
            [
                f'<g class="platform-heading" data-modality="{modality}">',
                f'<text x="{left}" y="36" '
                'font-family="Source Sans 3, sans-serif" font-size="24" '
                f'font-weight="700" fill="#293133">{letter}</text>',
                f'<image class="platform-logo" href="data:image/png;base64,{logo_data}" '
                f'x="{left + 28}" y="1" width="{logo_size}" height="{logo_size}" '
                'preserveAspectRatio="xMidYMid meet"/>',
                f'<text x="{left + 136}" y="35" '
                'font-family="Source Sans 3, sans-serif" font-size="24" '
                f'font-weight="700" fill="#293133">{label}</text>',
                f'<text class="modality-scale" x="{left + 136}" y="61" '
                'font-family="Source Sans 3, sans-serif" font-size="15" '
                f'font-weight="600" fill="#59615F">{escape(summaries[modality])}</text>',
                "</g>",
            ]
        )

    neuropixels_options = {
        option["id"]: option for option in sessions["neuropixels"]["options"]
    }
    for index, option_id in enumerate(NEURAL_STATIC_SELECTIONS["neuropixels"]):
        append_neuropixels_raw_card(
            svg,
            x=35 + index * 8,
            y=102 + index * 62,
            option=neuropixels_options[option_id],
            show_axis=index == len(NEURAL_STATIC_SELECTIONS["neuropixels"]) - 1,
        )

    mesoscope_options = {
        option["id"]: option for option in sessions["mesoscope"]["options"]
    }
    mesoscope_stacks = (
        ("VISp · 4 planes", 650, ("visp_2", "visp_0", "visp_1", "visp_3")),
        ("VISl · 4 planes", 915, ("visl_6", "visl_4", "visl_5", "visl_7")),
    )
    for stack_index, (stack_label, left, option_ids) in enumerate(mesoscope_stacks):
        svg.append(
            f'<text x="{left}" y="111" font-family="Source Sans 3, sans-serif" '
            f'font-size="14" font-weight="700" fill="#303536">{stack_label}</text>'
        )
        for index, option_id in enumerate(option_ids):
            option = mesoscope_options[option_id]
            append_microscopy_raw_card(
                svg,
                x=left + index * 8,
                y=122 + index * 45,
                card_width=255,
                option=option,
                path=frame_paths[("mesoscope", option_id)],
                modality="mesoscope",
                label=f'{option["targetLayer"]} · {option["imagingDepthUm"]:g} µm',
                show_scale=(
                    stack_index == len(mesoscope_stacks) - 1
                    and index == len(option_ids) - 1
                ),
            )

    slap2_options = {
        option["id"]: option for option in sessions["slap2"]["options"]
    }
    svg.append(
        '<text x="1240" y="111" font-family="Source Sans 3, sans-serif" '
        'font-size="14" font-weight="700" fill="#303536">'
        'iGluSnFR4f (green) + RCaMP3 (red)</text>'
    )
    for index, (composite_id, source_option_ids) in enumerate(
        SLAP2_STATIC_COMPOSITES.items()
    ):
        option = {**slap2_options[source_option_ids[0]], "id": composite_id}
        dmd = composite_id.split("-", maxsplit=1)[0].upper()
        depth = option["remoteFocusDepthBelowPiaUm"]
        append_microscopy_raw_card(
            svg,
            x=1240 + index * 10,
            y=122 + index * 205,
            card_width=500,
            option=option,
            path=frame_paths[("slap2", composite_id)],
            modality="slap2",
            label=f"{dmd} · {depth:g} µm · green + red composite",
            show_scale=index == len(SLAP2_STATIC_COMPOSITES) - 1,
        )
    svg.append("</svg>")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(svg) + "\n", encoding="utf-8")
    return output


def write_neural_viewer_html(
    output: Path = NEURAL_VIEWER_OUTPUT,
    static_output: Path = NEURAL_STATIC_OUTPUT,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = load_neural_excerpts()
    logo_data_uris = platform_logo_data_uris()
    write_neural_static_svg(static_output)
    for session in payload["sessions"]:
        session["logo"] = logo_data_uris[session["id"]]
        for field in ("alignment", "context", "event", "stimulus"):
            session.pop(field, None)
    template = (JAVASCRIPT_DIR / "neural-viewer.html").read_text(encoding="utf-8")
    stylesheet = (JAVASCRIPT_DIR / "neural-viewer.css").read_text(encoding="utf-8")
    javascript = (JAVASCRIPT_DIR / "neural-viewer.js").read_text(encoding="utf-8")
    html = (
        template.replace("__NEURAL_CSS__", stylesheet)
        .replace(
            "__NEURAL_STATIC_IMAGE__",
            f"media/neural-viewer/{static_output.name}",
        )
        .replace(
            "__NEURAL_DATA__",
            json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
        )
        .replace("__NEURAL_JS__", javascript)
        .replace("__EMBED_AUTO_HEIGHT_JS__", load_embed_auto_height())
    )
    output.write_text(html, encoding="utf-8")
    media_output = output.parent / "media" / "neural-viewer"
    if media_output.exists():
        shutil.rmtree(media_output)
    shutil.copytree(NEURAL_MEDIA_DIR, media_output)
    shutil.copy2(static_output, media_output / static_output.name)
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


def load_unit_yield_data(
    data_path: Path = UNIT_YIELD_DATA_PATH,
    provenance_path: Path = UNIT_YIELD_PROVENANCE_PATH,
) -> dict:
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    checksum = hashlib.sha256(data_path.read_bytes()).hexdigest()
    if checksum != provenance["vendored_sha256"]:
        raise RuntimeError("Unit-yield data checksum does not match its provenance record.")
    with data_path.open(newline="", encoding="utf-8") as stream:
        source_rows = list(csv.DictReader(stream))
    if len(source_rows) != provenance["rows"]:
        raise RuntimeError("Unit-yield row count does not match its provenance record.")

    records = []
    for source in source_rows:
        qc_unit_count = int(source["qc_unit_count"])
        probe_count = int(source["probe_count"])
        if probe_count <= 0:
            raise RuntimeError(f"Unit-yield session has no probes: {source['session_id']}")
        records.append(
            {
                **source,
                "dateValue": dt.date.fromisoformat(source["date"]),
                "probeCount": probe_count,
                "qcUnitCount": qc_unit_count,
                "unitsPerProbe": qc_unit_count / probe_count,
            }
        )

    records.sort(key=lambda row: (row["mouse_id"], row["dateValue"], row["session_id"]))
    session_ids = [row["session_id"] for row in records]
    if len(session_ids) != len(set(session_ids)):
        raise RuntimeError("Unit-yield data contains duplicate session IDs.")

    first_dates = {}
    day_one_yields = {}
    for record in records:
        mouse_id = record["mouse_id"]
        first_dates.setdefault(mouse_id, record["dateValue"])
        record["day"] = (record["dateValue"] - first_dates[mouse_id]).days + 1
        if record["day"] == 1 and record["qcUnitCount"] > 0:
            day_one_yields[mouse_id] = record["unitsPerProbe"]

    plotted_records = []
    for record in records:
        baseline = day_one_yields.get(record["mouse_id"])
        record["included"] = record["qcUnitCount"] > 0 and bool(baseline)
        record["percentOfDay1"] = (
            100 * record["unitsPerProbe"] / baseline if record["included"] else None
        )
        record["exclusionReason"] = (
            ""
            if record["included"]
            else "zero QC-passing units"
            if record["qcUnitCount"] <= 0
            else "no nonzero day-1 baseline"
        )
        record.pop("dateValue")
        if record["included"]:
            plotted_records.append(record)

    summary_by_day = {}
    for record in plotted_records:
        summary_by_day.setdefault(record["day"], []).append(record)
    summary = [
        {
            "day": day,
            "meanPercent": sum(record["percentOfDay1"] for record in day_records)
            / len(day_records),
            "meanUnitsPerProbe": sum(record["unitsPerProbe"] for record in day_records)
            / len(day_records),
            "sessionCount": len(day_records),
        }
        for day, day_records in sorted(summary_by_day.items())
    ]
    return {
        "dandisetId": provenance["dandiset_id"],
        "records": records,
        "sourceUrl": provenance["source_url"],
        "summary": summary,
        "version": 1,
    }


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


SESSION_CONTEXT_COLORS = {
    "sensorimotor": "#283185",
    "standard oddball": "#22BCAD",
    "sequence": "#B16027",
    "duration": "#CCAF2D",
    "other/pilot": "#9CA3AF",
}
SESSION_CONTEXT_LABELS = {
    "sensorimotor": "Sensorimotor",
    "standard oddball": "Standard",
    "sequence": "Sequence",
    "duration": "Duration",
    "other/pilot": "Pilot / other",
}
SESSION_ORDER = {
    1: ("sensorimotor", "standard oddball", "sequence", "duration"),
    2: ("sequence", "duration", "standard oddball", "sensorimotor"),
}
SLAP2_P3_STIMULI = {
    "SLAP2_SESSION1_PROD_P3_SENSORYMOTOR",
    "SLAP2_SESSION2_PROD_P3_STANDARD",
    "SLAP2_SESSION3_PROD_P3_SEQUENCE",
    "SLAP2_SESSION4_PROD_P3_DURATION",
    "SLAP2_SESSION1_PROD_P3_SEQUENCE",
    "SLAP2_SESSION2_PROD_P3_DURATION",
    "SLAP2_SESSION3_PROD_P3_STANDARD",
    "SLAP2_SESSION4_PROD_P3_SENSORYMOTOR",
}


def load_experimental_session_records(
    data_path: Path = SESSION_RECORDS_PATH,
    provenance_path: Path = SESSION_RECORDS_PROVENANCE_PATH,
) -> dict:
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    checksum = hashlib.sha256(data_path.read_bytes()).hexdigest()
    if checksum != provenance["vendored_sha256"]:
        raise RuntimeError("Session worksheet checksum does not match its provenance.")
    with data_path.open(newline="", encoding="utf-8") as stream:
        records = list(csv.DictReader(stream))
    if len(records) != provenance["rows"]:
        raise RuntimeError("Session worksheet row count does not match its provenance.")

    source_rows = [int(record["source_row"]) for record in records]
    if len(source_rows) != len(set(source_rows)) or source_rows != sorted(source_rows):
        raise RuntimeError("Session worksheet source rows must be unique and ordered.")
    modality_rows = {
        modality: sum(record["modality"] == modality for record in records)
        for modality in ("neuropixels", "mesoscope", "slap2")
    }
    if modality_rows != provenance["modality_rows"]:
        raise RuntimeError("Session worksheet modality counts do not match provenance.")
    return {
        "records": records,
        "sourceUrl": provenance["source_url"],
        "version": provenance["version"],
    }


def normalized_session_stimulus(record: dict) -> str:
    return record["session_stimulus"].upper().removesuffix(" (WITH TRIPPY)")


def session_qc_kind(record: dict | None, modality: str) -> str:
    if record is None:
        return "missing"
    qc = record["qc"].lower()
    if modality == "neuropixels":
        if "session fail" in qc:
            return "session-fail"
        if "fail" in qc:
            return "probe-fail"
    elif modality == "mesoscope" and "fail" in qc:
        return "session-fail"
    elif modality == "slap2":
        if "motion correction" in qc:
            return "motion"
        if "stressed" in qc:
            return "stressed"
        if "asleep" in qc:
            return "asleep"
        if "stopped" in qc:
            return "stopped"
    return "ok"


def session_context(record: dict) -> str:
    stimulus = normalized_session_stimulus(record)
    for context, token in (
        ("sensorimotor", "SENSORYMOTOR"),
        ("standard oddball", "STANDARD"),
        ("sequence", "SEQUENCE"),
        ("duration", "DURATION"),
    ):
        if token in stimulus:
            return context
    return "other/pilot"


def session_cohort(records: list[dict], modality: str) -> int:
    if modality == "neuropixels":
        session_one = [
            record
            for record in records
            if re.search(r"SESSION1(?:_|$)", normalized_session_stimulus(record))
        ]
        if not session_one:
            return 1
        return 1 if session_context(session_one[0]) == "sensorimotor" else 2
    if modality == "mesoscope":
        first_record = min(
            records,
            key=lambda row: (row["date"], row["source_session_id"], int(row["source_row"])),
        )
        first_context = session_context(first_record)
        if first_context == "sensorimotor":
            return 1
        if first_context == "sequence":
            return 2
    else:
        stimuli = {normalized_session_stimulus(record) for record in records}
        if "SLAP2_SESSION1_PROD_P3_SENSORYMOTOR" in stimuli:
            return 1
        if "SLAP2_SESSION1_PROD_P3_SEQUENCE" in stimuli:
            return 2
        return 1
    raise RuntimeError(f"Cannot infer cohort for mouse {records[0]['mouse_id']}")


def modality_session_records(records: list[dict], modality: str) -> list[dict]:
    selected = [record for record in records if record["modality"] == modality]
    if modality == "slap2":
        selected = [
            record
            for record in selected
            if normalized_session_stimulus(record) in SLAP2_P3_STIMULI
        ]
    return selected


def session_panel_rows(records: list[dict], modality: str) -> list[dict]:
    selected = modality_session_records(records, modality)
    grouped = {}
    for record in selected:
        grouped.setdefault(record["mouse_id"], []).append(record)

    rows = []
    for mouse_id, mouse_records in grouped.items():
        cohort = session_cohort(mouse_records, modality)
        if modality == "neuropixels":
            by_context = {}
            for record in mouse_records:
                by_context.setdefault(session_context(record), record)
            sessions = [
                {"context": context, "record": by_context.get(context)}
                for context in SESSION_ORDER[cohort]
            ]
        else:
            mouse_records.sort(
                key=lambda row: (
                    row["date"],
                    row["source_session_id"],
                    int(row["source_row"]),
                )
            )
            sessions = [
                {"context": session_context(record), "record": record}
                for record in mouse_records
            ]
        rows.append(
            {
                "cohort": cohort,
                "mouseId": mouse_id,
                "sessions": sessions,
            }
        )
    rows.sort(key=lambda row: (row["cohort"], int(row["mouseId"])))
    if modality == "slap2":
        rows.reverse()
    return rows


def svg_star(cx: float, cy: float, outer: float = 7, inner: float = 3) -> str:
    points = []
    for index in range(10):
        angle = -math.pi / 2 + index * math.pi / 5
        radius = outer if index % 2 == 0 else inner
        points.append(f"{cx + math.cos(angle) * radius:.2f},{cy + math.sin(angle) * radius:.2f}")
    return " ".join(points)


def append_session_block(
    svg: list[str],
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    context: str,
    qc_kind: str,
    element_class: str | None = None,
) -> None:
    color = SESSION_CONTEXT_COLORS[context]
    class_attribute = f' class="{element_class}"' if element_class else ""
    border_colors = {
        "missing": "#FF0000",
        "session-fail": "#FF0000",
        "motion": "#FF0000",
        "stressed": "#FF69B4",
        "asleep": "#32CD32",
        "stopped": "#F5C400",
    }
    if qc_kind in border_colors:
        svg.append(
            f'<rect{class_attribute} x="{x:.2f}" y="{y:.2f}" '
            f'width="{width:.2f}" height="{height:.2f}" '
            f'fill="url(#hatch-{context.replace("/", "-").replace(" ", "-")})" '
            f'stroke="{border_colors[qc_kind]}" stroke-width="2"/>'
        )
    else:
        svg.append(
            f'<rect{class_attribute} x="{x:.2f}" y="{y:.2f}" '
            f'width="{width:.2f}" height="{height:.2f}" '
            f'fill="{color}" stroke="#FFFFFF" stroke-width="1"/>'
        )
    if qc_kind == "probe-fail":
        svg.append(
            f'<polygon points="{svg_star(x + width / 2, y + height / 2)}" '
            'fill="#FFFFFF" stroke="#222829" stroke-width="1"/>'
        )


def write_session_inventory_svg(
    output: Path = SESSION_INVENTORY_STATIC_OUTPUT,
) -> Path:
    payload = load_experimental_session_records()
    logo_paths = load_platform_logos()
    records = payload["records"]
    panel_specs = (
        ("A", "Neuropixels", "neuropixels", 28),
        ("B", "Mesoscope", "mesoscope", 38),
        ("C", "SLAP2", "slap2", 38),
    )
    width = 1150
    height = 640
    panel_gap = 75
    chart_top = 85
    chart_bottom = 570
    chart_offset = 104
    heading_label_offset = 66
    chart_width = 410
    bar_height = 20

    panel_rows = {
        modality: session_panel_rows(records, modality)
        for _, _, modality, _ in panel_specs
    }
    global_max_sessions = max(
        len(row["sessions"])
        for rows in panel_rows.values()
        for row in rows
    )
    slot_width = chart_width / (global_max_sessions + 0.5)
    panel_axis_maxima = {
        modality: max(len(row["sessions"]) for row in panel_rows[modality])
        + (2 if modality == "slap2" else 0.5)
        for _, _, modality, _ in panel_specs
    }
    relative_panel_lefts = [0.0]
    for _, _, modality, _ in panel_specs[:-1]:
        relative_panel_lefts.append(
            relative_panel_lefts[-1]
            + panel_axis_maxima[modality] * slot_width
            + panel_gap
        )
    final_modality = panel_specs[-1][2]
    panel_group_width = (
        relative_panel_lefts[-1]
        + chart_offset
        + panel_axis_maxima[final_modality] * slot_width
    )
    panel_margin = (width - panel_group_width) / 2
    panel_lefts = tuple(panel_margin + left for left in relative_panel_lefts)

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title description">',
        '<title id="title">Recording sessions per mouse across three modalities</title>',
        '<desc id="description">Three panels show context-colored sessions for Neuropixels, '
        'mesoscope, and SLAP2 mice, grouped by predictive-processing cohort and annotated '
        'with session quality-control status.</desc>',
        f'<rect width="{width}" height="{height}" fill="#FFFFFF"/>',
        "<defs>",
    ]
    for context, color in SESSION_CONTEXT_COLORS.items():
        pattern_id = context.replace("/", "-").replace(" ", "-")
        svg.append(
            f'<pattern id="hatch-{pattern_id}" width="8" height="8" '
            'patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
            '<rect width="8" height="8" fill="#FFFFFF"/>'
            f'<line x1="0" y1="0" x2="0" y2="8" stroke="{color}" stroke-width="3"/>'
            "</pattern>"
        )
    svg.append(
        '<pattern id="hatch-qc" width="8" height="8" patternUnits="userSpaceOnUse" '
        'patternTransform="rotate(45)"><rect width="8" height="8" fill="#FFFFFF"/>'
        '<line x1="0" y1="0" x2="0" y2="8" stroke="#666666" stroke-width="3"/>'
        "</pattern>"
    )
    svg.append("</defs>")

    for (panel_letter, panel_title, modality, row_step), panel_left in zip(
        panel_specs, panel_lefts, strict=True
    ):
        rows = panel_rows[modality]
        max_sessions = max(len(row["sessions"]) for row in rows)
        if modality == "neuropixels":
            tick_values = range(max_sessions + 1)
        elif modality == "mesoscope":
            tick_values = range(max_sessions + 1)
        else:
            tick_values = range(1, max_sessions + 2)
        axis_max = panel_axis_maxima[modality]
        axis_width = slot_width * axis_max
        title_x = panel_left + chart_offset - heading_label_offset
        logo_data = base64.b64encode(logo_paths[modality].read_bytes()).decode()
        svg.extend(
            [
                f'<g class="platform-heading" data-modality="{modality}">',
                f'<text class="panel-title" x="{title_x:.2f}" y="34" '
                'font-family="Source Sans 3, sans-serif" '
                f'font-size="22" font-weight="700" fill="#293133">'
                f"{panel_letter}</text>",
                f'<image class="platform-logo" href="data:image/png;base64,{logo_data}" '
                f'x="{title_x + 24:.2f}" y="1" width="54" height="54" '
                'preserveAspectRatio="xMidYMid meet"/>',
                f'<text class="platform-title" x="{title_x + 86:.2f}" y="47" '
                'font-family="Source Sans 3, sans-serif" '
                f'font-size="22" font-weight="700" fill="#293133">{panel_title}</text>',
                "</g>",
            ]
        )
        if modality == "neuropixels":
            svg.append(
                f'<text id="mouse-id-axis-label" '
                f'x="{panel_left + chart_offset - 12}" y="72" '
                'font-family="Source Sans 3, sans-serif" font-size="13" '
                'font-weight="600" text-anchor="end" fill="#4D5553">Mouse ID</text>'
            )
        y_positions = []
        previous_cohort = rows[0]["cohort"]
        y = chart_top
        for row in rows:
            if row["cohort"] != previous_cohort:
                y += 18
                previous_cohort = row["cohort"]
            y_positions.append(y)
            svg.append(
                f'<text x="{panel_left + chart_offset - 12}" y="{y + 4:.2f}" '
                'font-family="IBM Plex Mono, monospace" font-size="12" '
                f'text-anchor="end" fill="#4D5553">{escape(row["mouseId"])}</text>'
            )
            for index, session in enumerate(row["sessions"]):
                record = session["record"]
                append_session_block(
                    svg,
                    x=panel_left + chart_offset + index * slot_width,
                    y=y - bar_height / 2,
                    width=slot_width,
                    height=bar_height,
                    context=session["context"],
                    qc_kind=session_qc_kind(record, modality),
                    element_class="session-block",
                )
            y += row_step

        if modality == "neuropixels":
            svg.append(
                f'<line class="session-axis" x1="{panel_left + chart_offset}" '
                f'y1="{chart_bottom}" '
                f'x2="{panel_left + chart_offset + axis_width}" y2="{chart_bottom}" '
                'stroke="#69716F" stroke-width="1.2"/>'
            )
            for tick_value in tick_values:
                x = panel_left + chart_offset + tick_value * slot_width
                svg.extend(
                    [
                        f'<line x1="{x:.2f}" y1="{chart_bottom}" x2="{x:.2f}" '
                        f'y2="{chart_bottom + 6}" stroke="#69716F" stroke-width="1"/>',
                        f'<text x="{x:.2f}" y="{chart_bottom + 23}" '
                        'font-family="IBM Plex Mono, monospace" font-size="11" '
                        f'text-anchor="middle" fill="#68706E">{tick_value}</text>',
                    ]
                )
            svg.append(
                f'<text x="{panel_left + chart_offset + axis_width / 2}" '
                f'y="{chart_bottom + 43}" '
                'font-family="Source Sans 3, sans-serif" font-size="13" '
                'text-anchor="middle" fill="#4D5553">Session number</text>'
            )

    svg.extend(
        [
            '<g id="session-inventory-legend" '
            f'transform="translate({panel_lefts[1] + chart_offset:.2f} 480)" '
            'aria-label="Session type and quality-control legend">',
            '<text x="0" y="13" font-family="Source Sans 3, sans-serif" '
            'font-size="13" font-weight="700" fill="#4D5553">Session type</text>',
        ]
    )
    for x, context_name in zip(
        (120, 300, 465, 610),
        ("sensorimotor", "standard oddball", "sequence", "duration"),
        strict=True,
    ):
        svg.extend(
            [
                f'<rect x="{x}" y="0" width="24" height="16" '
                f'fill="{SESSION_CONTEXT_COLORS[context_name]}"/>',
                f'<text x="{x + 32}" y="13" font-family="Source Sans 3, sans-serif" '
                f'font-size="12" fill="#68706E">'
                f"{escape(SESSION_CONTEXT_LABELS[context_name])}</text>",
            ]
        )
    svg.append(
        '<text x="0" y="55" font-family="Source Sans 3, sans-serif" '
        'font-size="13" font-weight="700" fill="#4D5553">Quality control</text>'
    )
    qc_items = (
        (120, 42, "#FF0000", "Missing / failed session"),
        (520, 42, "#FF0000", "Motion correction partially failed"),
        (120, 77, "#FF69B4", "Mouse stressed"),
        (340, 77, "#32CD32", "Mouse asleep"),
        (520, 77, "#F5C400", "SLAP2 stopped halfway"),
    )
    for x, y, color, label in qc_items:
        svg.extend(
            [
                f'<rect x="{x}" y="{y}" width="24" height="16" '
                f'fill="url(#hatch-qc)" stroke="{color}" stroke-width="2"/>',
                f'<text x="{x + 32}" y="{y + 13}" '
                'font-family="Source Sans 3, sans-serif" '
                f'font-size="12" fill="#68706E">{label}</text>',
            ]
        )
    append_session_block(
        svg,
        x=340,
        y=42,
        width=24,
        height=16,
        context="sensorimotor",
        qc_kind="probe-fail",
    )
    svg.extend(
        [
            '<text x="372" y="55" font-family="Source Sans 3, sans-serif" '
            'font-size="12" fill="#68706E">One probe failed</text>',
            "</g>",
            "</svg>",
        ]
    )
    output.parent.mkdir(parents=True, exist_ok=True)
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


UNIT_YIELD_COLORS = (
    "#087F8C",
    "#C65D13",
    "#3157B7",
    "#8A4F9E",
    "#4E7B32",
    "#A47C00",
    "#B33C2E",
    "#377D6A",
    "#6D5D9B",
    "#A24B72",
    "#53758C",
    "#7A6A2F",
    "#3E6F41",
    "#985B35",
    "#4F65A8",
    "#7F556D",
)


def write_unit_yield_svg(
    output: Path = UNIT_YIELD_STATIC_OUTPUT,
    data_path: Path = UNIT_YIELD_DATA_PATH,
    provenance_path: Path = UNIT_YIELD_PROVENANCE_PATH,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = load_unit_yield_data(data_path, provenance_path)
    records = [record for record in payload["records"] if record["included"]]
    if not records:
        raise RuntimeError("Unit-yield figure has no included session records.")

    width, height = 1200, 720
    left, right, top, bottom = 105, 45, 82, 112
    plot_width = width - left - right
    plot_height = height - top - bottom
    days = sorted({record["day"] for record in records})
    min_day, max_day = min(days), max(days)
    maximum = max(record["percentOfDay1"] for record in records)
    y_max = max(120, math.ceil(maximum / 20) * 20)

    def x_position(day: int) -> float:
        if min_day == max_day:
            return left + plot_width / 2
        return left + (day - min_day) / (max_day - min_day) * plot_width

    def y_position(value: float) -> float:
        return top + plot_height - value / y_max * plot_height

    mouse_ids = sorted({record["mouse_id"] for record in records})
    color_by_mouse = {
        mouse_id: UNIT_YIELD_COLORS[index % len(UNIT_YIELD_COLORS)]
        for index, mouse_id in enumerate(mouse_ids)
    }
    records_by_mouse = {
        mouse_id: [record for record in records if record["mouse_id"] == mouse_id]
        for mouse_id in mouse_ids
    }

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title description">',
        '<title id="title">Neuropixels unit yield across recording days</title>',
        '<desc id="description">QC-passing units per probe for each mouse, normalized to '
        'that mouse&apos;s first recording day, with the daily mean emphasized.</desc>',
        f'<rect width="{width}" height="{height}" fill="#FFFFFF"/>',
        '<text x="105" y="37" font-family="Source Sans 3, sans-serif" font-size="27" '
        'font-weight="650" fill="#263033">QC-passing Neuropixels unit yield across '
        'recording days</text>',
        '<text x="105" y="63" font-family="Source Sans 3, sans-serif" font-size="15" '
        'fill="#68706E">Each mouse is normalized to its day-1 QC units per probe</text>',
    ]

    tick_step = 20 if y_max <= 200 else 40
    for value in range(0, y_max + 1, tick_step):
        y = y_position(value)
        svg.extend(
            [
                f'<line x1="{left}" y1="{y:.2f}" x2="{width - right}" y2="{y:.2f}" '
                'stroke="#E2E5E4" stroke-width="1"/>',
                f'<text x="{left - 14}" y="{y + 5:.2f}" text-anchor="end" '
                'font-family="Source Sans 3, sans-serif" font-size="13" '
                f'fill="#68706E">{value}</text>',
            ]
        )

    baseline_y = y_position(100)
    svg.append(
        f'<line x1="{left}" y1="{baseline_y:.2f}" x2="{width - right}" '
        f'y2="{baseline_y:.2f}" stroke="#5E6664" stroke-width="1.5" '
        'stroke-dasharray="7 6"/>'
    )

    for mouse_id, mouse_records in records_by_mouse.items():
        points = " ".join(
            f'{x_position(record["day"]):.2f},{y_position(record["percentOfDay1"]):.2f}'
            for record in mouse_records
        )
        color = color_by_mouse[mouse_id]
        svg.append(
            f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2" '
            'stroke-opacity="0.52"/>'
        )
        for record in mouse_records:
            svg.append(
                f'<circle cx="{x_position(record["day"]):.2f}" '
                f'cy="{y_position(record["percentOfDay1"]):.2f}" r="4" '
                f'fill="{color}" fill-opacity="0.72"/>'
            )

    mean_points = " ".join(
        f'{x_position(row["day"]):.2f},{y_position(row["meanPercent"]):.2f}'
        for row in payload["summary"]
    )
    svg.append(
        f'<polyline points="{mean_points}" fill="none" stroke="#222829" stroke-width="5"/>'
    )
    for row in payload["summary"]:
        svg.append(
            f'<circle cx="{x_position(row["day"]):.2f}" '
            f'cy="{y_position(row["meanPercent"]):.2f}" r="8" fill="#222829" '
            'stroke="#FFFFFF" stroke-width="2"/>'
        )

    summary_by_day = {row["day"]: row for row in payload["summary"]}
    axis_y = top + plot_height
    svg.append(
        f'<line x1="{left}" y1="{axis_y}" x2="{width - right}" y2="{axis_y}" '
        'stroke="#69716F" stroke-width="1.5"/>'
    )
    for day in range(min_day, max_day + 1):
        x = x_position(day)
        count = summary_by_day.get(day, {}).get("sessionCount", 0)
        svg.extend(
            [
                f'<line x1="{x:.2f}" y1="{axis_y}" x2="{x:.2f}" y2="{axis_y + 7}" '
                'stroke="#69716F" stroke-width="1.5"/>',
                f'<text x="{x:.2f}" y="{axis_y + 29}" text-anchor="middle" '
                'font-family="Source Sans 3, sans-serif" font-size="15" font-weight="600" '
                f'fill="#303536">Day {day}</text>',
                f'<text x="{x:.2f}" y="{axis_y + 49}" text-anchor="middle" '
                'font-family="Source Sans 3, sans-serif" font-size="13" '
                f'fill="#68706E">n={count}</text>',
            ]
        )
    svg.extend(
        [
            f'<text x="24" y="{top + plot_height / 2:.2f}" '
            'transform="rotate(-90 24 345)" text-anchor="middle" '
            'font-family="Source Sans 3, sans-serif" font-size="16" fill="#303536">'
            'QC units per probe (% of day 1)</text>',
            '<line x1="905" y1="43" x2="943" y2="43" stroke="#222829" '
            'stroke-width="5"/>',
            '<circle cx="924" cy="43" r="7" fill="#222829" stroke="#FFFFFF" '
            'stroke-width="2"/>',
            '<text x="952" y="48" font-family="Source Sans 3, sans-serif" '
            'font-size="14" fill="#303536">Daily mean</text>',
            '<line x1="1055" y1="43" x2="1093" y2="43" stroke="#53758C" '
            'stroke-width="2" stroke-opacity="0.65"/>',
            '<circle cx="1074" cy="43" r="4" fill="#53758C"/>',
            '<text x="1102" y="48" font-family="Source Sans 3, sans-serif" '
            'font-size="14" fill="#303536">Mouse</text>',
            "</svg>",
        ]
    )
    output.write_text("\n".join(svg) + "\n", encoding="utf-8")
    return output


def main() -> None:
    merged_figure_1_path = write_merged_figure_1_svg()
    figure_1_panel_c_path = write_figure_1_panel_c_svg()
    html_path = write_interactive_html()
    data_explorer_path = write_data_explorer_html()
    literature_comparison_path = write_literature_comparison_html()
    behavior_viewer_path = write_behavior_viewer_html()
    neural_viewer_path = write_neural_viewer_html()
    unit_yield_html_path = write_unit_yield_html()
    svg_path = write_static_svg()
    unit_yield_svg_path = write_unit_yield_svg()
    print(f"Wrote {merged_figure_1_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {figure_1_panel_c_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {CONTEXT_CONTROLS_STATIC_OUTPUT.relative_to(REPO_ROOT)}")
    print(f"Wrote {html_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {data_explorer_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {SESSION_INVENTORY_STATIC_OUTPUT.relative_to(REPO_ROOT)}")
    print(f"Wrote {literature_comparison_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {behavior_viewer_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {BEHAVIOR_STATIC_OUTPUT.relative_to(REPO_ROOT)}")
    print(f"Wrote {neural_viewer_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {NEURAL_STATIC_OUTPUT.relative_to(REPO_ROOT)}")
    print(f"Wrote {unit_yield_html_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {svg_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {unit_yield_svg_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()