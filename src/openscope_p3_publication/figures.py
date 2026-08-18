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
import zlib
from dataclasses import asdict, dataclass
from html import escape
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIGURE_SANS_FONT = "Myriad Pro, Arial, sans-serif"
FIGURE_MONO_FONT = "IBM Plex Mono, monospace"
FIGURE_REFERENCE_WIDTH = 1200
FIGURE_TEXT_MARGIN = 8
HARDWARE_DESCRIPTION_FONT_SIZE = 12
FIGURE_TYPE_SCALE = {
    "panel": 34,
    "title": 28,
    "heading": 24,
    "modality": 20,
    "label": 15,
    "small": 12,
}
FIGURE_TYPE_SMALL = FIGURE_TYPE_SCALE["small"]
SESSION_TYPE_COLORS = {
    "sensorimotor": "#283185",
    "standard": "#22BCAD",
    "sequence": "#B16027",
    "duration": "#CCAF2D",
}


def write_svg_output(output: Path, svg: list[str]) -> None:
    content = "\n".join(svg)
    for previous_font in (
        "Source Sans 3, sans-serif",
        "IBM Plex Sans, sans-serif",
    ):
        content = content.replace(previous_font, FIGURE_SANS_FONT)

    width_match = re.search(r'<svg\b[^>]*\bwidth="([0-9.]+)"', content)
    if width_match is None:
        raise RuntimeError("Generated SVG is missing a numeric canvas width.")
    font_scale = float(width_match.group(1)) / FIGURE_REFERENCE_WIDTH

    def normalized_font_size(match: re.Match[str]) -> str:
        value = float(match.group(1)) * font_scale
        formatted = f"{value:.2f}".rstrip("0").rstrip(".")
        return f'font-size="{formatted}"'

    def normalized_text_tag(match: re.Match[str]) -> str:
        tag = match.group(0)
        if not any(
            f'font-family="{font}"' in tag
            for font in (FIGURE_SANS_FONT, FIGURE_MONO_FONT)
        ):
            return tag
        return re.sub(r'font-size="([0-9.]+)"', normalized_font_size, tag)

    content = re.sub(r"<text\b[^>]*>", normalized_text_tag, content)
    output.write_text(content + "\n", encoding="utf-8", newline="\n")


DATA_DIR = REPO_ROOT / "figure_sources" / "data"
JAVASCRIPT_DIR = REPO_ROOT / "figure_sources" / "javascript"
STIMULUS_SOURCES_PATH = DATA_DIR / "stimulus-viewer-sources.json"
STIMULUS_EXCERPT_DIR = DATA_DIR / "stimulus-table-excerpts"
STIMULUS_EXCERPT_PROVENANCE_PATH = STIMULUS_EXCERPT_DIR / "provenance.json"
ANIMAL_RECORDS_PATH = DATA_DIR / "experimental-animals.csv"
ANIMAL_RECORDS_PROVENANCE_PATH = DATA_DIR / "experimental-animals.provenance.json"
SESSION_RECORDS_PATH = DATA_DIR / "experimental-sessions.csv"
SESSION_RECORDS_PROVENANCE_PATH = SESSION_RECORDS_PATH.with_suffix(".provenance.json")
DATA_ACCESS_PATH = DATA_DIR / "data-access.csv"
DATA_ACCESS_PROVENANCE_PATH = DATA_ACCESS_PATH.with_suffix(".provenance.json")
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
HARDWARE_SOURCE_PROVENANCE_PATH = (
    REPO_ROOT / "figure_sources" / "powerpoint" / "hardware" / "provenance.json"
)
HARDWARE_STATIC_OUTPUT = (
    REPO_ROOT / "images" / "figures" / "generated" / "multimodal-hardware.svg"
)
IMPORTED_FIGURE_DIR = REPO_ROOT / "images" / "figures" / "imported"
UNIT_EXTRACTION_PLAN_SOURCE = IMPORTED_FIGURE_DIR / "figure-04-unit-extraction-plan.png"
BASIC_STIMULI_PLAN_SOURCE = IMPORTED_FIGURE_DIR / "figure-05-basic-stimuli-plan.png"
STANDARD_ODDBALL_PLAN_SOURCE = IMPORTED_FIGURE_DIR / "figure-07-standard-oddball-plan.png"
UNIT_EXTRACTION_PLAN_OUTPUT = (
    REPO_ROOT / "images" / "figures" / "generated" / "figure-07-unit-extraction-plan.svg"
)
BASIC_STIMULI_PLAN_OUTPUT = (
    REPO_ROOT / "images" / "figures" / "generated" / "figure-08-basic-stimuli-plan.svg"
)
STANDARD_ODDBALL_PLAN_OUTPUT = (
    REPO_ROOT / "images" / "figures" / "generated" / "figure-10-standard-oddball-plan.svg"
)
LITERATURE_COMPARISON_OUTPUT = REPO_ROOT / "interactive" / "literature-comparison.html"
BEHAVIOR_VIEWER_OUTPUT = REPO_ROOT / "interactive" / "behavior-viewer.html"
BEHAVIOR_EXCERPTS_PATH = DATA_DIR / "behavior-excerpts.json"
EYE_TRACKING_VIEWER_OUTPUT = REPO_ROOT / "interactive" / "eye-tracking-viewer.html"
EYE_TRACKING_EXCERPTS_PATH = DATA_DIR / "eye-tracking-excerpts.json"
EYE_TRACKING_STATIC_OUTPUT = (
    REPO_ROOT / "images" / "figures" / "generated" / "synchronized-eye-tracking.svg"
)
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
SEGMENTATION_VIEWER_DATA_PATH = DATA_DIR / "segmentation-viewers.json"
SEGMENTATION_VIEWER_PROVENANCE_PATH = SEGMENTATION_VIEWER_DATA_PATH.with_suffix(
    ".provenance.json"
)
SEGMENTATION_VIEWER_MEDIA_DIR = (
    REPO_ROOT / "figure_sources" / "media" / "segmentation-viewers"
)
SEGMENTATION_VIEWER_OUTPUT = REPO_ROOT / "interactive" / "segmentation-viewer.html"
SEGMENTATION_VIEWER_TITLES = {
    "neuropixels": "Neuropixels unit-template viewer",
    "mesoscope": "Mesoscope ROI segmentation viewer",
    "slap2": "SLAP2 source-segmentation viewer",
}
SEGMENTATION_PANEL_LABELS = {
    "neuropixels": ("A", "B"),
    "mesoscope": ("C", "D"),
    "slap2": ("E", "F"),
}
SEGMENTATION_FILTER_COLORS = (
    (37, 170, 225),
    (140, 198, 63),
    (204, 175, 45),
    (214, 92, 72),
    (36, 188, 173),
    (177, 96, 173),
)
SEGMENTATION_VIEWER_STATIC_OUTPUTS = {
    "neuropixels": (
        REPO_ROOT
        / "images"
        / "figures"
        / "generated"
        / "figure-06-neuropixels-unit-filters.svg"
    ),
    "mesoscope": (
        REPO_ROOT
        / "images"
        / "figures"
        / "generated"
        / "figure-06-mesoscope-roi-filters.svg"
    ),
    "slap2": (
        REPO_ROOT
        / "images"
        / "figures"
        / "generated"
        / "figure-06-slap2-source-filters.svg"
    ),
}
SEGMENTATION_VIEWER_STATIC_OUTPUT = (
    REPO_ROOT
    / "images"
    / "figures"
    / "generated"
    / "figure-06-segmentation-viewers.svg"
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
NEUROPIXELS_TRAJECTORY_DATA_PATH = DATA_DIR / "neuropixels-trajectories.json"
NEUROPIXELS_TRAJECTORY_PROVENANCE_PATH = (
    NEUROPIXELS_TRAJECTORY_DATA_PATH.with_suffix(".provenance.json")
)
NEUROPIXELS_TRAJECTORY_STATIC_OUTPUT = (
    REPO_ROOT
    / "images"
    / "figures"
    / "generated"
    / "supplementary-neuropixels-trajectories.svg"
)
NEUROPIXELS_TRAJECTORY_INTERACTIVE_OUTPUT = (
    REPO_ROOT / "interactive" / "neuropixels-trajectories.html"
)
OPTOTAGGING_HEATMAP_DATA_PATH = DATA_DIR / "optotagging-heatmaps.json"
OPTOTAGGING_HEATMAP_PROVENANCE_PATH = OPTOTAGGING_HEATMAP_DATA_PATH.with_suffix(
    ".provenance.json"
)
OPTOTAGGING_STATIC_SUMMARY_PATH = DATA_DIR / "optotagging-static-summary.json"
OPTOTAGGING_HEATMAP_SOURCE_DIR = (
    REPO_ROOT / "figure_sources" / "media" / "optotagging"
)
OPTOTAGGING_STATIC_LEGACY_SOURCE = (
    OPTOTAGGING_HEATMAP_SOURCE_DIR / "optotagging-static-legacy.svg"
)
OPTOTAGGING_STATIC_SOURCE = (
    OPTOTAGGING_HEATMAP_SOURCE_DIR / "optotagging-static-composite.svg"
)
OPTOTAGGING_HEATMAP_INTERACTIVE_OUTPUT = (
    REPO_ROOT / "interactive" / "optotagging-heatmaps.html"
)
OPTOTAGGING_HEATMAP_STATIC_OUTPUT = (
    REPO_ROOT / "images" / "figures" / "generated" / "optotagging-heatmaps.svg"
)
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


def load_hardware_sources() -> dict[str, dict]:
    provenance = json.loads(HARDWARE_SOURCE_PROVENANCE_PATH.read_text(encoding="utf-8"))
    assets = provenance.get("assets", {})
    expected_assets = {
        f"{modality}_{panel}"
        for modality in ("neuropixels", "mesoscope", "slap2")
        for panel in ("rig_geometry", "mouse_platform", "brain_targeting")
    }
    source_path = REPO_ROOT / provenance["source_path"]
    if (
        provenance.get("version") != 1
        or provenance.get("slide_count") != 1
        or set(assets) != expected_assets
        or hashlib.sha256(source_path.read_bytes()).hexdigest()
        != provenance["source_sha256"]
    ):
        raise RuntimeError("Hardware PowerPoint provenance is not supported.")

    validated = {}
    for asset_id, record in assets.items():
        path = REPO_ROOT / record["output_path"]
        data = path.read_bytes()
        dimensions = struct.unpack(">II", data[16:24])
        if (
            hashlib.sha256(data).hexdigest() != record["sha256"]
            or not data.startswith(b"\x89PNG\r\n\x1a\n")
            or dimensions != (record["width"], record["height"])
            or record["mode"] != "RGBA"
            or data[25] != 6
        ):
            raise RuntimeError(f"Hardware PowerPoint asset is invalid: {asset_id}")
        validated[asset_id] = {**record, "path": path}
    return validated


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
        f"{base64.b64encode(normalized_text_bytes(cohort_panel_path)).decode()}"
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
        '<rect class="workflow-label-mask" x="464" y="188" width="124" height="22" '
        'fill="#FFFFFF"/>',
        '<text class="workflow-modality-label" x="526" y="203" text-anchor="middle" '
        'font-family="Source Sans 3, sans-serif" font-size="8" font-weight="600" '
        'fill="#303536">Mesoscope</text>',
        '</svg>',
        '<text class="panel-label" x="20" y="48" font-family="Source Sans 3, sans-serif" '
        'font-size="28" font-weight="700" fill="#293133">A</text>',
        '<text class="panel-label" x="1020" y="48" font-family="Source Sans 3, sans-serif" '
        'font-size="28" font-weight="700" fill="#293133">B</text>',
        f'<image href="{cohort_panel}" x="40" y="825" width="1920" height="768" '
        'preserveAspectRatio="xMidYMid meet"/>',
        '<text class="panel-label" x="20" y="818" font-family="Source Sans 3, sans-serif" '
        'font-size="28" font-weight="700" fill="#293133">C</text>',
        '</svg>',
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    write_svg_output(output, svg)
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
        'font-family="Source Sans 3, sans-serif" font-size="24" font-weight="700" '
        'fill="#4D5553">Habituation / training</text>',
        '<text x="1110" y="105" text-anchor="middle" '
        'font-family="Source Sans 3, sans-serif" font-size="24" font-weight="700" '
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
                'font-family="Source Sans 3, sans-serif" font-size="15" '
                f'font-weight="600" fill="#4D5553">{label}</text>',
            ]
        )
        legend_x += 120 + len(label) * 7
    svg.extend(
        [
            '<rect x="1225" y="27" width="26" height="26" rx="2" '
            'fill="#FFFFFF" stroke="#283185" stroke-width="3"/>',
            '<text x="1261" y="48" font-family="Source Sans 3, sans-serif" '
            'font-size="15" font-weight="600" fill="#4D5553">'
            'Habituation without mismatch</text>',
        ]
    )

    for modality, label, summary, cohort_lines, repeats, heading_y, icon_y in modality_groups:
        logo_data = base64.b64encode(logo_paths[modality].read_bytes()).decode()
        svg.extend(
            [
                f'<g class="modality-cohort" data-modality="{modality}">',
                f'<text class="modality-title" x="42" y="{heading_y}" '
                'font-family="Source Sans 3, sans-serif" '
                f'font-size="{FIGURE_TYPE_SCALE["modality"]}" '
                f'font-weight="700" fill="#293133">{label}</text>',
                f'<text x="42" y="{heading_y + 30}" '
                'font-family="Source Sans 3, sans-serif" font-size="15" '
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
                    'font-family="Source Sans 3, sans-serif" font-size="15" '
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
    write_svg_output(output, svg)
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
    write_svg_output(output, svg)
    return output


def append_hardware_image(
    svg: list[str],
    *,
    asset_id: str,
    asset: dict,
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    image_data = base64.b64encode(asset["path"].read_bytes()).decode()
    href = f"data:image/png;base64,{image_data}"
    crop_left, crop_top, crop_right, crop_bottom = asset["crop_fractions"]
    if any((crop_left, crop_top, crop_right, crop_bottom)):
        source_x = asset["width"] * crop_left
        source_y = asset["height"] * crop_top
        source_width = asset["width"] * (1 - crop_left - crop_right)
        source_height = asset["height"] * (1 - crop_top - crop_bottom)
        svg.extend(
            [
                f'<svg class="hardware-image" data-asset="{asset_id}" '
                f'x="{x}" y="{y}" width="{width}" height="{height}" '
                f'viewBox="{source_x:.2f} {source_y:.2f} '
                f'{source_width:.2f} {source_height:.2f}" overflow="hidden" '
                'preserveAspectRatio="xMidYMid meet">',
                f'<image href="{href}" width="{asset["width"]}" '
                f'height="{asset["height"]}"/>',
                "</svg>",
            ]
        )
        return
    svg.append(
        f'<image class="hardware-image" data-asset="{asset_id}" href="{href}" '
        f'x="{x}" y="{y}" width="{width}" height="{height}" '
        'preserveAspectRatio="xMidYMid meet"/>'
    )


def fitted_image_bounds(asset: dict, box: tuple[float, float, float, float]) -> tuple[float, ...]:
    x, y, width, height = box
    aspect_ratio = asset["width"] / asset["height"]
    rendered_width = min(width, height * aspect_ratio)
    rendered_height = rendered_width / aspect_ratio
    return (
        x + (width - rendered_width) / 2,
        y + (height - rendered_height) / 2,
        rendered_width,
        rendered_height,
    )


def image_point(bounds: tuple[float, ...], x: float, y: float) -> tuple[float, float]:
    return bounds[0] + x * bounds[2], bounds[1] + y * bounds[3]


def line_intersection_y(
    start: tuple[float, float], end: tuple[float, float], y: float
) -> tuple[float, float]:
    fraction = (y - start[1]) / (end[1] - start[1])
    return start[0] + fraction * (end[0] - start[0]), y


def write_hardware_figure_svg(output: Path = HARDWARE_STATIC_OUTPUT) -> Path:
    assets = load_hardware_sources()
    logo_paths = load_platform_logos()
    rows = (
        {
            "modality": "neuropixels",
            "label": "Neuropixels",
            "top": 100,
            "rig": (220, 105, 515, 360),
            "platform": (775, 112, 410, 343),
            "target": (1320, 120, 390, 330),
        },
        {
            "modality": "mesoscope",
            "label": "Mesoscope",
            "top": 500,
            "rig": (220, 505, 515, 365),
            "platform": (765, 525, 430, 312),
            "target": (1235, 505, 520, 350),
        },
        {
            "modality": "slap2",
            "label": "SLAP2",
            "top": 900,
            "rig": (220, 920, 515, 335),
            "platform": (765, 925, 430, 312),
            "target": (1290, 905, 380, 345),
        },
    )
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1800" height="1310" '
        'viewBox="0 0 1800 1310" role="img" aria-labelledby="title description">',
        '<title id="title">Multimodal recording hardware and brain targeting</title>',
        '<desc id="description">Neuropixels, mesoscope, and SLAP2 rows compare rig '
        'geometry, the head-fixed mouse platform, and the corresponding brain-targeting '
        'strategy using nine source images extracted directly from the hardware PowerPoint.</desc>',
        '<rect width="1800" height="1310" fill="#FFFFFF"/>',
        '<text x="458" y="58" text-anchor="middle" '
        'font-family="Source Sans 3, sans-serif" font-size="28" font-weight="700" '
        'fill="#293133">Rig geometry</text>',
        '<text x="980" y="58" text-anchor="middle" '
        'font-family="Source Sans 3, sans-serif" font-size="28" font-weight="700" '
        'fill="#293133">Mouse platform</text>',
        '<text x="1490" y="58" text-anchor="middle" '
        'font-family="Source Sans 3, sans-serif" font-size="28" font-weight="700" '
        'fill="#293133">Brain targeting</text>',
    ]
    for row in rows:
        modality = row["modality"]
        logo_data = base64.b64encode(logo_paths[modality].read_bytes()).decode()
        svg.extend(
            [
                f'<g class="hardware-modality" data-modality="{modality}">',
                f'<text class="modality-title" x="15" y="{row["top"] + 32}" '
                'font-family="Source Sans 3, sans-serif" '
                f'font-size="{FIGURE_TYPE_SCALE["modality"]}" '
                f'font-weight="700" fill="#293133">{row["label"]}</text>',
                f'<image class="platform-logo" href="data:image/png;base64,{logo_data}" '
                f'x="15" y="{row["top"] + 48}" width="190" height="190" '
                'preserveAspectRatio="xMidYMid meet"/>',
                "</g>",
            ]
        )
        append_hardware_image(
            svg,
            asset_id=f"{modality}_rig_geometry",
            asset=assets[f"{modality}_rig_geometry"],
            x=row["rig"][0],
            y=row["rig"][1],
            width=row["rig"][2],
            height=row["rig"][3],
        )
        append_hardware_image(
            svg,
            asset_id=f"{modality}_mouse_platform",
            asset=assets[f"{modality}_mouse_platform"],
            x=row["platform"][0],
            y=row["platform"][1],
            width=row["platform"][2],
            height=row["platform"][3],
        )
        append_hardware_image(
            svg,
            asset_id=f"{modality}_brain_targeting",
            asset=assets[f"{modality}_brain_targeting"],
            x=row["target"][0],
            y=row["target"][1],
            width=row["target"][2],
            height=row["target"][3],
        )
    neuropixels_bounds = fitted_image_bounds(
        assets["neuropixels_brain_targeting"], rows[0]["target"]
    )
    mesoscope_bounds = fitted_image_bounds(
        assets["mesoscope_brain_targeting"], rows[1]["target"]
    )
    slap2_bounds = fitted_image_bounds(
        assets["slap2_brain_targeting"], rows[2]["target"]
    )
    layer_segments = (
        ("I", "#8CC63F", 0.493417, 0.229884, 0.424762, 0.269578),
        ("II/III", "#CCE8F8", 0.505738, 0.258951, 0.437083, 0.298644),
        ("IV", "#53A8DC", 0.518471, 0.295771, 0.449816, 0.335465),
        ("V", "#2B388D", 0.530740, 0.329113, 0.462085, 0.368806),
        ("I", "#8CC63F", 0.277891, 0.368789, 0.209253, 0.408468),
        ("II/III", "#CCE8F8", 0.295134, 0.393071, 0.226495, 0.432749),
        ("IV", "#53A8DC", 0.314185, 0.424745, 0.245547, 0.464424),
        ("V", "#2B388D", 0.332154, 0.453192, 0.263515, 0.492871),
    )
    _, _, layer_x1, layer_y1, layer_x2, layer_y2 = layer_segments[0]
    mesoscope_layer_angle = round(
        math.degrees(
            math.atan2(
                (layer_y1 - layer_y2) * mesoscope_bounds[3],
                (layer_x1 - layer_x2) * mesoscope_bounds[2],
            )
        ),
        2,
    )
    focus_boxes = (
        (
            "neuropixels",
            neuropixels_bounds,
            (0.478519, 0.286880, 0.252385, 0.236911),
            "#000000",
            0,
        ),
        (
            "mesoscope",
            mesoscope_bounds,
            (0.396731, 0.211857, 0.134138, 0.092089),
            "#FFFFFF",
            mesoscope_layer_angle,
        ),
    )
    mesoscope_focus_geometry = None
    for modality, bounds, (x, y, width, height), color, rotation in focus_boxes:
        rect_x = bounds[0] + x * bounds[2]
        rect_y = bounds[1] + y * bounds[3]
        rect_width = width * bounds[2]
        rect_height = height * bounds[3]
        center_x = rect_x + rect_width / 2
        center_y = rect_y + rect_height / 2
        transform = (
            f' transform="rotate({rotation} {center_x:.2f} {center_y:.2f})"'
            if rotation
            else ""
        )
        svg.append(
            f'<rect class="zoom-focus-box" data-modality="{modality}" '
            f'x="{rect_x:.2f}" y="{rect_y:.2f}" width="{rect_width:.2f}" '
            f'height="{rect_height:.2f}" fill="none" stroke="{color}" '
            f'stroke-width="4"{transform}/>'
        )
        if modality == "mesoscope":
            mesoscope_focus_geometry = (
                rect_x,
                rect_y,
                rect_width,
                rect_height,
                center_x,
                center_y,
                rotation,
            )
    svg.append(
        f'<rect class="mesoscope-target-border" x="{mesoscope_bounds[0]:.2f}" '
        f'y="{mesoscope_bounds[1]:.2f}" width="{mesoscope_bounds[2]:.2f}" '
        f'height="{mesoscope_bounds[3]:.2f}" fill="none" stroke="#000000" '
        'stroke-width="3"/>'
    )
    top_connectors = (
        ((0.480969, 0.524737), (-0.004021, -0.001210)),
        ((0.730887, 0.524737), (0.999592, -0.001210)),
    )
    for start, end in top_connectors:
        x1, y1 = image_point(neuropixels_bounds, *start)
        x2, y2 = image_point(mesoscope_bounds, *end)
        svg.append(
            '<line class="zoom-connector" data-stage="neuropixels-to-mesoscope" '
            f'x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
            'stroke="#000000" stroke-width="4" stroke-linecap="round" '
            'stroke-dasharray="2 10"/>'
        )
    if mesoscope_focus_geometry is None:
        raise RuntimeError("Mesoscope focus geometry is missing.")
    rect_x, rect_y, rect_width, rect_height, center_x, center_y, rotation = (
        mesoscope_focus_geometry
    )
    angle = math.radians(rotation)

    def rotate_focus_point(x: float, y: float) -> tuple[float, float]:
        offset_x = x - center_x
        offset_y = y - center_y
        return (
            center_x + offset_x * math.cos(angle) - offset_y * math.sin(angle),
            center_y + offset_x * math.sin(angle) + offset_y * math.cos(angle),
        )

    focus_corners = (
        rotate_focus_point(rect_x, rect_y + rect_height),
        rotate_focus_point(rect_x + rect_width, rect_y + rect_height),
    )
    middle_connectors = (
        ((0.036540, 0.197174), (0.042669, 0.210744)),
        ((0.957882, 0.132872), (0.954828, 0.126090)),
    )
    mesoscope_bottom = mesoscope_bounds[1] + mesoscope_bounds[3]
    for start_point, (dark_end, white_end) in zip(
        focus_corners, middle_connectors, strict=True
    ):
        dark_end_point = image_point(slap2_bounds, *dark_end)
        white_end_point = image_point(slap2_bounds, *white_end)
        white_intersection = line_intersection_y(
            start_point, white_end_point, mesoscope_bottom
        )
        dark_intersection = line_intersection_y(
            start_point, dark_end_point, mesoscope_bottom
        )
        svg.extend(
            [
                '<line class="zoom-connector" data-stage="mesoscope-internal" '
                f'x1="{start_point[0]:.2f}" y1="{start_point[1]:.2f}" '
                f'x2="{white_intersection[0]:.2f}" y2="{white_intersection[1]:.2f}" '
                'stroke="#FFFFFF" stroke-width="4" stroke-linecap="round" '
                'stroke-dasharray="2 10"/>',
                '<line class="zoom-connector" data-stage="mesoscope-to-slap2" '
                f'x1="{dark_intersection[0]:.2f}" y1="{dark_intersection[1]:.2f}" '
                f'x2="{dark_end_point[0]:.2f}" y2="{dark_end_point[1]:.2f}" '
                'stroke="#000000" stroke-width="4" stroke-linecap="round" '
                'stroke-dasharray="2 10"/>',
            ]
        )
    rendered_x, rendered_y, rendered_width, rendered_height = mesoscope_bounds
    for layer, color, x1, y1, x2, y2 in layer_segments:
        svg.append(
            f'<line class="mesoscope-layer-plane" data-layer="{layer}" '
            f'x1="{rendered_x + x1 * rendered_width:.2f}" '
            f'y1="{rendered_y + y1 * rendered_height:.2f}" '
            f'x2="{rendered_x + x2 * rendered_width:.2f}" '
            f'y2="{rendered_y + y2 * rendered_height:.2f}" '
            f'stroke="{color}" stroke-width="7" stroke-linecap="round"/>'
        )
    slap2_plane_label_x = (
        image_point(slap2_bounds, 426 / assets["slap2_brain_targeting"]["width"], 0)[0]
        + FIGURE_TEXT_MARGIN
    )
    apical_plane_label_y = image_point(
        slap2_bounds, 0, 115 / assets["slap2_brain_targeting"]["height"]
    )[1] + 6
    proximal_plane_label_y = image_point(
        slap2_bounds, 0, 242 / assets["slap2_brain_targeting"]["height"]
    )[1] + 6
    svg.extend(
        [
            '<g class="mesoscope-target-legend">',
            '<rect x="1277" y="507" width="160" height="104" rx="3" '
            'fill="#FFFFFF" fill-opacity="0.9"/>',
            '<line x1="1288" y1="525" x2="1317" y2="525" '
            'stroke="#8FD246" stroke-width="4"/>',
            '<text x="1325" y="531" font-family="Source Sans 3, sans-serif" '
            'font-size="12" fill="#303536">Layer I</text>',
            '<line x1="1288" y1="548" x2="1317" y2="548" '
            'stroke="#B8E3F5" stroke-width="4"/>',
            '<text x="1325" y="554" font-family="Source Sans 3, sans-serif" '
            'font-size="12" fill="#303536">Layer II/III</text>',
            '<line x1="1288" y1="571" x2="1317" y2="571" '
            'stroke="#5DBCEB" stroke-width="4"/>',
            '<text x="1325" y="577" font-family="Source Sans 3, sans-serif" '
            'font-size="12" fill="#303536">Layer IV</text>',
            '<line x1="1288" y1="594" x2="1317" y2="594" '
            'stroke="#334DB3" stroke-width="4"/>',
            '<text x="1325" y="600" font-family="Source Sans 3, sans-serif" '
            'font-size="12" fill="#303536">Layer V</text>',
            '<text x="1318" y="746" font-family="Source Sans 3, sans-serif" '
            'font-size="15" font-weight="700" fill="#172126" stroke="#FFFFFF" '
            'stroke-width="4" paint-order="stroke">VISlm</text>',
            '<text x="1460" y="716" font-family="Source Sans 3, sans-serif" '
            'font-size="15" font-weight="700" fill="#172126" stroke="#FFFFFF" '
            'stroke-width="4" paint-order="stroke">VISp</text>',
            '</g>',
            f'<text class="slap2-plane-label" x="{slap2_plane_label_x:.2f}" '
            f'y="{apical_plane_label_y:.2f}" '
            'font-family="Source Sans 3, sans-serif" '
            f'font-size="{HARDWARE_DESCRIPTION_FONT_SIZE}" font-weight="700" '
            'fill="#172126" stroke="#FFFFFF" stroke-width="4" '
            'paint-order="stroke">Apical plane</text>',
            f'<text class="slap2-plane-label" x="{slap2_plane_label_x:.2f}" '
            f'y="{proximal_plane_label_y:.2f}" '
            'font-family="Source Sans 3, sans-serif" '
            f'font-size="{HARDWARE_DESCRIPTION_FONT_SIZE}" font-weight="700" '
            'fill="#172126" stroke="#FFFFFF" stroke-width="4" '
            'paint-order="stroke">Proximal plane</text>',
        ]
    )
    svg.append("</svg>")
    output.parent.mkdir(parents=True, exist_ok=True)
    write_svg_output(output, svg)
    return output


def write_placeholder_plan_svg(
    source: Path,
    output: Path,
    *,
    title_lines: tuple[str, ...],
    mask_height: int,
    first_baseline: int,
    font_size: int,
    line_gap: int,
) -> Path:
    image_data = png_data_uri(source, (2048, 1024))
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="2048" height="1024" '
        'viewBox="0 0 2048 1024" role="img" aria-labelledby="title description">',
        f'<title id="title">{escape(" ".join(title_lines))}</title>',
        '<desc id="description">Draft analysis-panel plan retained as a work-in-progress '
        'placeholder; its obsolete embedded figure number is masked so manuscript numbering '
        'is supplied only by MyST.</desc>',
        '<rect width="2048" height="1024" fill="#FFFFFF"/>',
        f'<image href="{image_data}" width="2048" height="1024"/>',
        f'<rect class="stale-title-mask" x="0" y="0" width="2048" '
        f'height="{mask_height}" fill="#FFFFFF"/>',
    ]
    for line_index, line in enumerate(title_lines):
        svg.append(
            f'<text class="placeholder-title" x="64" '
            f'y="{first_baseline + line_index * line_gap}" '
            'font-family="Source Sans 3, sans-serif" '
            f'font-size="{font_size}" font-weight="600" fill="#111111">'
            f'{escape(line)}</text>'
        )
    svg.append("</svg>")
    output.parent.mkdir(parents=True, exist_ok=True)
    write_svg_output(output, svg)
    return output


def write_unit_extraction_plan_svg(output: Path = UNIT_EXTRACTION_PLAN_OUTPUT) -> Path:
    return write_placeholder_plan_svg(
        UNIT_EXTRACTION_PLAN_SOURCE,
        output,
        title_lines=(
            "Unit extraction → signal and noise amplitude",
            "Distributions across areas, sessions, and modalities",
        ),
        mask_height=140,
        first_baseline=52,
        font_size=FIGURE_TYPE_SCALE["title"],
        line_gap=60,
    )


def write_basic_stimuli_plan_svg(output: Path = BASIC_STIMULI_PLAN_OUTPUT) -> Path:
    return write_placeholder_plan_svg(
        BASIC_STIMULI_PLAN_SOURCE,
        output,
        title_lines=(
            "Basic stimuli → unit/system identification → distributions across areas and "
            "modalities",
        ),
        mask_height=94,
        first_baseline=62,
        font_size=FIGURE_TYPE_SCALE["title"],
        line_gap=44,
    )


def write_standard_oddball_plan_svg(
    output: Path = STANDARD_ODDBALL_PLAN_OUTPUT,
) -> Path:
    return write_placeholder_plan_svg(
        STANDARD_ODDBALL_PLAN_SOURCE,
        output,
        title_lines=(
            "Responses to standard oddball stimuli",
            "Demonstrate stimulus alignment",
        ),
        mask_height=285,
        first_baseline=118,
        font_size=FIGURE_TYPE_SCALE["title"],
        line_gap=82,
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
PROTOCOL_CONTEXT_COLORS = {
    **SESSION_TYPE_COLORS,
}
PROTOCOL_BLOCK_COLORS = {
    "standard": SHARED_COLORS[0],
    "context": "#68706E",
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
        if not text_sha256_matches(path, metadata["vendored_sha256"]):
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
    if not text_sha256_matches(path, metadata["vendored_sha256"]):
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


def load_figure_stylesheet(name: str) -> str:
    typography = (JAVASCRIPT_DIR / "figure-typography.css").read_text(
        encoding="utf-8"
    )
    stylesheet = (JAVASCRIPT_DIR / name).read_text(encoding="utf-8")
    return f"{typography}\n\n{stylesheet}"


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
    stylesheet = load_figure_stylesheet("stimulus-viewer.css")
    javascript = (JAVASCRIPT_DIR / "stimulus-viewer.js").read_text(encoding="utf-8")
    static_output = write_context_controls_svg()
    static_data = base64.b64encode(normalized_text_bytes(static_output)).decode()
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
    output.write_text(html, encoding="utf-8", newline="\n")
    return output


def write_data_explorer_html(
    output: Path = DATA_EXPLORER_OUTPUT,
    static_output: Path = SESSION_INVENTORY_STATIC_OUTPUT,
    refresh_static: bool = True,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = load_publication_table_data()
    if refresh_static:
        write_session_inventory_svg(static_output)
    static_data = base64.b64encode(normalized_text_bytes(static_output)).decode()
    template = (JAVASCRIPT_DIR / "data-explorer.html").read_text(encoding="utf-8")
    stylesheet = load_figure_stylesheet("data-explorer.css")
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
    output.write_text(html, encoding="utf-8", newline="\n")
    return output


def write_literature_comparison_html(
    output: Path = LITERATURE_COMPARISON_OUTPUT,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    provenance = json.loads(OTHER_STUDIES_PROVENANCE_PATH.read_text(encoding="utf-8"))
    if not text_sha256_matches(OTHER_STUDIES_PATH, provenance["vendored_sha256"]):
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
    stylesheet = load_figure_stylesheet("literature-comparison.css")
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
    output.write_text(html, encoding="utf-8", newline="\n")
    return output


def write_unit_yield_html(
    output: Path = UNIT_YIELD_INTERACTIVE_OUTPUT,
    data_path: Path = UNIT_YIELD_DATA_PATH,
    provenance_path: Path = UNIT_YIELD_PROVENANCE_PATH,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = load_unit_yield_data(data_path, provenance_path)
    template = (JAVASCRIPT_DIR / "unit-yield.html").read_text(encoding="utf-8")
    stylesheet = load_figure_stylesheet("unit-yield.css")
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
    output.write_text(html, encoding="utf-8", newline="\n")
    return output


def load_optotagging_heatmap_data(
    data_path: Path = OPTOTAGGING_HEATMAP_DATA_PATH,
    provenance_path: Path = OPTOTAGGING_HEATMAP_PROVENANCE_PATH,
    media_dir: Path = OPTOTAGGING_HEATMAP_SOURCE_DIR,
) -> dict:
    """Load and validate the committed representative optotagging snapshot."""

    payload = json.loads(data_path.read_text(encoding="utf-8"))
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    version = payload.get("version")
    if version not in {1, 2} or provenance.get("version") != version:
        raise RuntimeError("Optotagging heatmap snapshot version is not supported.")
    if not text_sha256_matches(data_path, provenance.get("manifest_sha256", "")):
        raise RuntimeError("Optotagging heatmap manifest checksum does not match.")

    sessions = payload.get("sessions", [])
    if (
        not sessions
        or payload.get("session_count") != len(sessions)
        or provenance.get("session_count") != len(sessions)
        or payload.get("total_unit_count")
        != sum(session.get("unit_count", 0) for session in sessions)
        or provenance.get("total_unit_count") != payload.get("total_unit_count")
    ):
        raise RuntimeError("Optotagging heatmap coverage metadata is inconsistent.")

    asset_manifest = provenance.get("asset_manifest", [])
    skipped_assets = provenance.get("skipped_assets", [])
    failed_assets = provenance.get("failed_assets", [])
    expected_asset_count = provenance.get(
        "source_session_count",
        len(sessions) + len(skipped_assets) + len(failed_assets),
    )
    asset_manifest_sha256 = hashlib.sha256(
        json.dumps(asset_manifest, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    if (
        expected_asset_count < len(sessions)
        or len(asset_manifest) != expected_asset_count
        or asset_manifest_sha256 != provenance.get("asset_manifest_sha256")
        or any(
            not asset.get("digest", {}).get("dandi:sha2-256")
            for asset in asset_manifest
        )
    ):
        raise RuntimeError("Optotagging source asset manifest is invalid.")

    session_ids = [session.get("session_id") for session in sessions]
    if (
        session_ids != sorted(session_ids)
        or len(session_ids) != len(set(session_ids))
        or payload.get("default_session_id") not in session_ids
    ):
        raise RuntimeError("Optotagging heatmap session inventory is invalid.")

    media_manifest = []
    for session in sessions:
        if version == 2:
            atlas_file = session.get("atlas_file", "")
            numeric_png_file = session.get("numeric_png_file", "")
            if (
                Path(atlas_file).name != atlas_file
                or not atlas_file.endswith(".atlas.json")
                or Path(numeric_png_file).name != numeric_png_file
                or not numeric_png_file.endswith(".atlas.png")
            ):
                raise RuntimeError("Invalid optotagging numeric atlas path.")
            atlas_bytes = (media_dir / atlas_file).read_bytes()
            numeric_png = (media_dir / numeric_png_file).read_bytes()
            if (
                hashlib.sha256(atlas_bytes).hexdigest() != session.get("atlas_sha256")
                or hashlib.sha256(numeric_png).hexdigest()
                != session.get("numeric_png_sha256")
                or len(numeric_png) < 24
                or not numeric_png.startswith(b"\x89PNG\r\n\x1a\n")
                or numeric_png[24:26] != b"\x08\x00"
            ):
                raise RuntimeError(
                    f"Optotagging numeric atlas is invalid: {atlas_file}"
                )
            atlas = json.loads(atlas_bytes)
            unit_count = session.get("unit_count")
            parent_areas = atlas.get("parent_areas", [])
            parent_codes = atlas.get("parent_codes", [])
            orders = atlas.get("strongest_first_unit_indices", {})
            condition_names = [
                condition["table_name"] for condition in payload["conditions"]
            ]
            expected_offsets = {
                condition_name: index * unit_count
                for index, condition_name in enumerate(condition_names)
            }
            quantization = atlas.get("quantization", {})
            time_seconds = atlas.get("time_seconds", [])
            expected_units = list(range(unit_count))
            png_width, png_height = struct.unpack(">II", numeric_png[16:24])
            if (
                atlas.get("version") != 2
                or atlas.get("unit_count") != unit_count
                or atlas.get("numeric_png_file") != numeric_png_file
                or parent_areas != sorted(set(parent_areas))
                or not all(isinstance(area, str) and area for area in parent_areas)
                or len(parent_codes) != unit_count
                or any(code < 0 or code >= len(parent_areas) for code in parent_codes)
                or set(orders) != set(condition_names)
                or any(sorted(order) != expected_units for order in orders.values())
                or atlas.get("condition_row_offsets") != expected_offsets
                or quantization
                != {
                    "dtype": "int8",
                    "scale": 15.875,
                    "range": [-8.0, 8.0],
                    "nan_sentinel": -128,
                    "png_channels": "single-channel uint8 viewed as signed int8",
                }
                or len(time_seconds) != 2
                or not all(isinstance(value, int | float) for value in time_seconds)
                or not math.isfinite(time_seconds[0])
                or not math.isfinite(time_seconds[1])
                or time_seconds[0] >= time_seconds[1]
                or png_width != atlas.get("time_bin_count")
                or png_width <= 0
                or png_height != unit_count * len(condition_names)
            ):
                raise RuntimeError(
                    f"Optotagging numeric atlas metadata is invalid: {atlas_file}"
                )
            media_manifest.extend(
                [
                    {"file": atlas_file, "sha256": session["atlas_sha256"]},
                    {
                        "file": numeric_png_file,
                        "sha256": session["numeric_png_sha256"],
                    },
                ]
            )
            if "image_file" not in session:
                continue
        image_file = session.get("image_file", "")
        relative_image = Path(image_file)
        if (
            not image_file
            or relative_image.name != image_file
            or relative_image.suffix.lower() != ".webp"
        ):
            raise RuntimeError(f"Invalid optotagging image path: {image_file}")
        image_path = media_dir / image_file
        image = image_path.read_bytes()
        if (
            len(image) < 12
            or not image.startswith(b"RIFF")
            or image[8:12] != b"WEBP"
            or hashlib.sha256(image).hexdigest() != session.get("image_sha256")
            or not isinstance(session.get("image_width"), int)
            or not isinstance(session.get("image_height"), int)
            or session["image_width"] <= 0
            or session["image_height"] <= 0
        ):
            raise RuntimeError(f"Optotagging heatmap image is invalid: {image_file}")
        if version == 1:
            media_manifest.append(
                {
                    "image_file": image_file,
                    "image_sha256": session["image_sha256"],
                }
            )
        else:
            media_manifest.append(
                {"file": image_file, "sha256": session["image_sha256"]}
            )

    media_manifest_sha256 = hashlib.sha256(
        json.dumps(media_manifest, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    if media_manifest_sha256 != provenance.get("media_manifest_sha256"):
        raise RuntimeError("Optotagging heatmap media manifest checksum does not match.")
    return payload


def write_optotagging_heatmap_html(
    output: Path = OPTOTAGGING_HEATMAP_INTERACTIVE_OUTPUT,
    data_path: Path = OPTOTAGGING_HEATMAP_DATA_PATH,
    provenance_path: Path = OPTOTAGGING_HEATMAP_PROVENANCE_PATH,
    media_dir: Path = OPTOTAGGING_HEATMAP_SOURCE_DIR,
    static_output: Path = OPTOTAGGING_HEATMAP_STATIC_OUTPUT,
    static_source: Path | None = None,
) -> Path:
    """Build the standalone representative-session optotagging heatmap explorer."""

    output.parent.mkdir(parents=True, exist_ok=True)
    payload = load_optotagging_heatmap_data(data_path, provenance_path, media_dir)
    if static_source is None:
        static_source = media_dir / OPTOTAGGING_STATIC_SOURCE.name
    write_optotagging_heatmap_svg(
        static_output,
        data_path,
        provenance_path,
        media_dir,
        static_source=static_source,
    )
    template = (JAVASCRIPT_DIR / "optotagging-heatmaps.html").read_text(
        encoding="utf-8"
    )
    stylesheet = load_figure_stylesheet("optotagging-heatmaps.css")
    javascript = (JAVASCRIPT_DIR / "optotagging-heatmaps.js").read_text(
        encoding="utf-8"
    )
    embedded_atlases = {}
    if payload["version"] == 2:
        for session in payload["sessions"]:
            atlas = json.loads(
                (media_dir / session["atlas_file"]).read_text(encoding="utf-8")
            )
            numeric_png = (media_dir / session["numeric_png_file"]).read_bytes()
            embedded_atlases[session["session_id"]] = {
                "metadata": atlas,
                "image": (
                    "data:image/png;base64,"
                    + base64.b64encode(numeric_png).decode("ascii")
                ),
            }
    html = (
        template.replace("__OPTOTAGGING_CSS__", stylesheet)
        .replace(
            "__OPTOTAGGING_STATIC_IMAGE__",
            f"media/optotagging/{static_output.name}",
        )
        .replace(
            "__OPTOTAGGING_DATA__",
            json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
        )
        .replace(
            "__OPTOTAGGING_ATLASES__",
            json.dumps(
                embedded_atlases,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
        .replace("__OPTOTAGGING_JS__", javascript)
        .replace("__EMBED_AUTO_HEIGHT_JS__", load_embed_auto_height())
    )
    output.write_text(html, encoding="utf-8", newline="\n")

    media_output = output.parent / "media" / "optotagging"
    if media_output.exists():
        shutil.rmtree(media_output)
    media_output.mkdir(parents=True)
    if payload["version"] == 1:
        for session in payload["sessions"]:
            shutil.copy2(
                media_dir / session["image_file"],
                media_output / session["image_file"],
            )
    shutil.copy2(static_output, media_output / static_output.name)
    return output


def load_optotagging_static_summary(
    summary_path: Path = OPTOTAGGING_STATIC_SUMMARY_PATH,
) -> dict:
    """Load and validate yield distributions extracted from the legacy static SVG."""

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    source_path = REPO_ROOT / summary.get("source", "")
    source_session_count = summary.get("source_session_count")
    if (
        summary.get("version") != 1
        or not isinstance(source_session_count, int)
        or source_session_count <= 0
        or not source_path.is_file()
        or hashlib.sha256(source_path.read_bytes()).hexdigest()
        != summary.get("source_sha256")
    ):
        raise RuntimeError("Optotagging static-summary provenance is invalid.")

    def validate_records(records: list[dict], expected_count: int | None = None) -> None:
        labels = [record.get("label") for record in records]
        if len(labels) != len(set(labels)) or any(not label for label in labels):
            raise RuntimeError("Optotagging static-summary labels are invalid.")
        for record in records:
            counts = record.get("counts", [])
            sampled_session_count = record.get("sampled_session_count")
            if (
                not counts
                or sampled_session_count != len(counts)
                or len(counts) > source_session_count
                or expected_count is not None
                and len(counts) != expected_count
                or any(not isinstance(count, int) or count < 0 for count in counts)
                or not math.isclose(
                    statistics.fmean(counts),
                    record.get("mean", math.nan),
                    abs_tol=1e-6,
                )
            ):
                raise RuntimeError(
                    f"Optotagging static-summary values are invalid: {record.get('label')}"
                )

    overall = summary.get("overall")
    major_parent = summary.get("major_parent", [])
    structures = summary.get("structures", [])
    if not isinstance(overall, dict) or len(major_parent) != 10 or len(structures) != 48:
        raise RuntimeError("Optotagging static-summary dimensions changed.")
    validate_records([overall], expected_count=source_session_count)
    validate_records(major_parent)
    validate_records(structures)
    return summary


def optotagging_heatmap_color(value: float | None, limit: float = 3.0) -> tuple[int, int, int]:
    if value is None or not math.isfinite(value):
        return (230, 230, 230)
    fraction = max(-1.0, min(1.0, value / limit))
    cold = (59, 76, 192)
    middle = (247, 247, 247)
    warm = (180, 4, 38)
    start, end = (cold, middle) if fraction < 0 else (middle, warm)
    amount = fraction + 1 if fraction < 0 else fraction
    return tuple(
        round(left + amount * (right - left))
        for left, right in zip(start, end, strict=True)
    )


def optotagging_static_heatmap_png(
    payload: dict,
    media_dir: Path,
    *,
    session_id: str,
    condition_name: str,
) -> tuple[bytes, dict]:
    session = next(
        (record for record in payload["sessions"] if record["session_id"] == session_id),
        None,
    )
    if session is None:
        raise RuntimeError(f"Static optotagging session is unavailable: {session_id}")
    metadata = json.loads((media_dir / session["atlas_file"]).read_text(encoding="utf-8"))
    width, height, scalars = decode_grayscale_png(media_dir / session["numeric_png_file"])
    unit_count = metadata["unit_count"]
    if height != unit_count * len(payload["conditions"]):
        raise RuntimeError("Optotagging static atlas dimensions changed.")
    row_offset = metadata["condition_row_offsets"][condition_name]
    order = metadata["strongest_first_unit_indices"][condition_name]
    scale = metadata["quantization"]["scale"]
    nan_sentinel = metadata["quantization"]["nan_sentinel"]
    pixels = bytearray(width * unit_count * 3)
    for display_row, unit_index in enumerate(order):
        source_offset = (row_offset + unit_index) * width
        target_offset = display_row * width * 3
        for column in range(width):
            unsigned = scalars[source_offset + column]
            quantized = unsigned if unsigned < 128 else unsigned - 256
            value = None if quantized == nan_sentinel else quantized / scale
            color = optotagging_heatmap_color(value)
            target = target_offset + column * 3
            pixels[target : target + 3] = bytes(color)
    return encode_rgb_png(width, unit_count, bytes(pixels)), metadata


def append_optotagging_panel_heading(
    svg: list[str],
    *,
    label: str,
    title: str | None,
    x: float,
    y: float,
) -> None:
    svg.append(
        f'<text x="{x}" y="{y}" font-family="{FIGURE_SANS_FONT}" '
        f'font-size="{FIGURE_TYPE_SCALE["panel"]}" font-weight="700" '
        f'fill="#263033">{label}</text>'
    )
    if title:
        svg.append(
            f'<text x="{x + 46}" y="{y - 2}" font-family="{FIGURE_SANS_FONT}" '
            f'font-size="{FIGURE_TYPE_SCALE["modality"]}" font-weight="700" '
            f'fill="#263033">{escape(title)}</text>'
        )


def append_optotagging_yield_panel(
    svg: list[str],
    records: list[dict],
    *,
    label: str,
    y_axis_label: str,
    x: float,
    y: float,
    width: float,
    height: float,
    tick_step: int,
    label_width: float,
    bar_height: float = 12,
    point_radius: float = 2.1,
) -> None:
    records = sorted(records, key=lambda record: (-record["mean"], record["label"]))
    append_optotagging_panel_heading(svg, label=label, title=None, x=x, y=y + 32)
    plot_left = x + label_width
    plot_right = x + width - 48
    plot_top = y + 70
    plot_bottom = y + height - 54
    maximum = max(max(record["counts"]) for record in records)
    axis_max = max(tick_step, math.ceil(maximum / tick_step) * tick_step)
    plot_width = plot_right - plot_left
    row_height = (plot_bottom - plot_top) / len(records)
    for tick in range(0, axis_max + 1, tick_step):
        tick_x = plot_left + tick / axis_max * plot_width
        svg.extend(
            [
                f'<line x1="{tick_x:.2f}" y1="{plot_bottom}" x2="{tick_x:.2f}" '
                f'y2="{plot_bottom + 6}" stroke="#69716F" stroke-width="1.2"/>',
                f'<text x="{tick_x:.2f}" y="{plot_bottom + 19}" text-anchor="middle" '
                f'font-family="{FIGURE_MONO_FONT}" font-size="{FIGURE_TYPE_SMALL}" '
                f'fill="#68706E">{tick}</text>',
            ]
        )
    for row_index, record in enumerate(records):
        center_y = plot_top + (row_index + 0.5) * row_height
        mean_x = plot_left + record["mean"] / axis_max * plot_width
        half_bar = bar_height / 2
        svg.extend(
            [
                f'<text x="{plot_left - 9}" y="{center_y + 4:.2f}" text-anchor="end" '
                f'font-family="{FIGURE_SANS_FONT}" font-size="{FIGURE_TYPE_SMALL}" '
                f'font-weight="600" fill="#303536">{escape(record["label"])}</text>',
                f'<rect x="{plot_left}" y="{center_y - half_bar:.2f}" '
                f'width="{max(0, mean_x - plot_left):.2f}" height="{bar_height:g}" '
                'fill="#315F73" fill-opacity="0.68"/>',
                f'<line x1="{mean_x:.2f}" y1="{center_y - half_bar - 2:.2f}" '
                f'x2="{mean_x:.2f}" y2="{center_y + half_bar + 2:.2f}" '
                'stroke="#1F434F" stroke-width="2"/>',
                f'<text x="{x + width - 2}" y="{center_y + 4:.2f}" text-anchor="end" '
                f'font-family="{FIGURE_MONO_FONT}" font-size="{FIGURE_TYPE_SMALL}" '
                f'fill="#68706E">n={record["sampled_session_count"]}</text>',
            ]
        )
        for point_index, count in enumerate(record["counts"]):
            point_x = plot_left + count / axis_max * plot_width
            jitter = (((point_index * 37) % 13) - 6) / 6 * min(4, row_height * 0.18)
            svg.append(
                f'<circle cx="{point_x:.2f}" cy="{center_y + jitter:.2f}" '
                f'r="{point_radius:g}" '
                'fill="#596663" fill-opacity="0.48"/>'
            )
    svg.extend(
        [
            f'<text x="{plot_left - 9}" y="{plot_top - 12}" text-anchor="end" '
            f'font-family="{FIGURE_SANS_FONT}" font-size="15" '
            f'fill="#303536">{escape(y_axis_label)}</text>',
            f'<line x1="{plot_left}" y1="{plot_bottom}" x2="{plot_right}" '
            f'y2="{plot_bottom}" stroke="#69716F" stroke-width="1.4"/>',
            f'<text x="{(plot_left + plot_right) / 2:.2f}" y="{y + height - 8}" '
            f'text-anchor="middle" font-family="{FIGURE_SANS_FONT}" font-size="15" '
            'fill="#303536">Optotagged cells per session</text>',
        ]
    )


def write_optotagging_static_source(
    output: Path = OPTOTAGGING_STATIC_SOURCE,
    data_path: Path = OPTOTAGGING_HEATMAP_DATA_PATH,
    provenance_path: Path = OPTOTAGGING_HEATMAP_PROVENANCE_PATH,
    media_dir: Path = OPTOTAGGING_HEATMAP_SOURCE_DIR,
    summary_path: Path = OPTOTAGGING_STATIC_SUMMARY_PATH,
) -> Path:
    """Render the publication-style static optotagging figure from committed data."""

    payload = load_optotagging_heatmap_data(data_path, provenance_path, media_dir)
    summary = load_optotagging_static_summary(summary_path)
    session_id = payload["default_session_id"]
    condition_name = "5 hz pulse train_presentations"
    condition = next(
        item for item in payload["conditions"] if item["table_name"] == condition_name
    )
    heatmap_png, metadata = optotagging_static_heatmap_png(
        payload,
        media_dir,
        session_id=session_id,
        condition_name=condition_name,
    )
    session = next(item for item in payload["sessions"] if item["session_id"] == session_id)
    condition_counts = session["condition_counts"][condition_name]
    pulse_count = round(
        condition_counts["pulses"] / condition_counts["presentations"]
    )
    heatmap_uri = base64.b64encode(heatmap_png).decode("ascii")
    width, height = 1200, 960
    yield_color = "#315F73"
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title description">',
        '<title id="title">Optotagging response and yield summary</title>',
        '<desc id="description">Four panels show a representative five-hertz '
        f'laser-aligned response from {escape(session_id)}, overall optotagged-cell '
        'yield, yield by major parent area, and the eighteen structures with the highest '
        'mean yield.</desc>',
        '<defs><linearGradient id="optotagging-z" x1="0" x2="1" y1="0" y2="0">'
        '<stop offset="0" stop-color="#3B4CC0"/><stop offset="0.5" '
        'stop-color="#F7F7F7"/><stop offset="1" stop-color="#B40426"/>'
        '</linearGradient></defs>',
        f'<rect width="{width}" height="{height}" fill="#FFFFFF"/>',
    ]

    append_optotagging_panel_heading(
        svg,
        label="A",
        title=None,
        x=35,
        y=64,
    )
    plot_left, plot_top, plot_width, plot_height = 92, 116, 646, 265
    svg.append(
        f'<image href="data:image/png;base64,{heatmap_uri}" x="{plot_left}" '
        f'y="{plot_top}" width="{plot_width}" height="{plot_height}" '
        'preserveAspectRatio="none"/>'
    )
    time_start, time_end = metadata["time_seconds"]

    def time_x(value: float) -> float:
        return plot_left + (value - time_start) / (time_end - time_start) * plot_width

    pulse_width = max(
        3,
        condition["pulse_width_seconds"] / (time_end - time_start) * plot_width,
    )
    for pulse_index in range(pulse_count):
        pulse_x = time_x(pulse_index / condition["pulse_frequency_hz"])
        svg.append(
            f'<rect x="{pulse_x:.2f}" y="100" width="{pulse_width:.2f}" height="9" '
            f'fill="{yield_color}"/>'
        )
    laser_x = time_x(0)
    svg.extend(
        [
            f'<line x1="{laser_x:.2f}" y1="{plot_top}" x2="{laser_x:.2f}" '
            f'y2="{plot_top + plot_height}" stroke="#263033" stroke-width="1.4" '
            'stroke-dasharray="6 5"/>',
            f'<rect x="{plot_left}" y="{plot_top}" width="{plot_width}" '
            f'height="{plot_height}" fill="none" stroke="#69716F" stroke-width="1.2"/>',
            f'<text x="48" y="{plot_top + plot_height / 2:.2f}" '
            f'transform="rotate(-90 48 {plot_top + plot_height / 2:.2f})" '
            f'text-anchor="middle" font-family="{FIGURE_SANS_FONT}" font-size="15" '
            'fill="#303536">Units</text>',
            f'<text x="82" y="{plot_top + 5}" text-anchor="end" '
            f'font-family="{FIGURE_MONO_FONT}" font-size="{FIGURE_TYPE_SMALL}" '
            'fill="#68706E">1</text>',
            f'<text x="82" y="{plot_top + plot_height}" text-anchor="end" '
            f'font-family="{FIGURE_MONO_FONT}" font-size="{FIGURE_TYPE_SMALL}" '
            f'fill="#68706E">{metadata["unit_count"]:,}</text>',
        ]
    )
    for tick in (-0.5, 0, 0.5, 1.0):
        if not time_start <= tick <= time_end:
            continue
        tick_x = time_x(tick)
        svg.extend(
            [
                f'<line x1="{tick_x:.2f}" y1="{plot_top + plot_height}" '
                f'x2="{tick_x:.2f}" y2="{plot_top + plot_height + 7}" '
                'stroke="#69716F" stroke-width="1.2"/>',
                f'<text x="{tick_x:.2f}" y="{plot_top + plot_height + 23}" '
                f'text-anchor="middle" font-family="{FIGURE_MONO_FONT}" '
                f'font-size="{FIGURE_TYPE_SMALL}" fill="#68706E">{tick:g}</text>',
            ]
        )
    svg.extend(
        [
            f'<text x="{plot_left + plot_width / 2:.2f}" y="419" text-anchor="middle" '
            f'font-family="{FIGURE_SANS_FONT}" font-size="15" fill="#303536">'
            'Time from laser onset (s)</text>',
            '<rect x="92" y="438" width="245" height="12" fill="url(#optotagging-z)"/>',
            f'<text x="92" y="466" text-anchor="middle" font-family="{FIGURE_MONO_FONT}" '
            f'font-size="{FIGURE_TYPE_SMALL}" fill="#68706E">-3</text>',
            f'<text x="214.5" y="466" text-anchor="middle" font-family="{FIGURE_MONO_FONT}" '
            f'font-size="{FIGURE_TYPE_SMALL}" fill="#68706E">0</text>',
            f'<text x="337" y="466" text-anchor="middle" font-family="{FIGURE_MONO_FONT}" '
            f'font-size="{FIGURE_TYPE_SMALL}" fill="#68706E">+3</text>',
            f'<text x="353" y="449" font-family="{FIGURE_SANS_FONT}" font-size="13" '
            'fill="#303536">Baseline z score</text>',
        ]
    )

    append_optotagging_panel_heading(
        svg,
        label="B",
        title=None,
        x=790,
        y=64,
    )
    overall = summary["overall"]
    overall_left, overall_right = 820, 1145
    overall_top, overall_bottom = 126, 390
    overall_max = max(20, math.ceil(max(overall["counts"]) / 20) * 20)
    for tick in range(0, overall_max + 1, 20):
        tick_x = overall_left + tick / overall_max * (overall_right - overall_left)
        svg.extend(
            [
                f'<line x1="{tick_x:.2f}" y1="{overall_bottom}" x2="{tick_x:.2f}" '
                f'y2="{overall_bottom + 6}" stroke="#69716F" stroke-width="1.2"/>',
                f'<text x="{tick_x:.2f}" y="{overall_bottom + 19}" text-anchor="middle" '
                f'font-family="{FIGURE_MONO_FONT}" font-size="{FIGURE_TYPE_SMALL}" '
                f'fill="#68706E">{tick}</text>',
            ]
        )
    for point_index, count in enumerate(overall["counts"]):
        point_x = overall_left + count / overall_max * (overall_right - overall_left)
        point_y = overall_top + 24 + ((point_index * 37) % 17) / 16 * (
            overall_bottom - overall_top - 48
        )
        svg.append(
            f'<circle cx="{point_x:.2f}" cy="{point_y:.2f}" r="3.1" '
            'fill="#596663" fill-opacity="0.58"/>'
        )
    overall_mean_x = overall_left + overall["mean"] / overall_max * (
        overall_right - overall_left
    )
    svg.extend(
        [
            f'<line x1="{overall_mean_x:.2f}" y1="{overall_top}" '
            f'x2="{overall_mean_x:.2f}" y2="{overall_bottom}" '
            f'stroke="{yield_color}" stroke-width="4"/>',
            f'<text x="{overall_mean_x + 7:.2f}" y="{overall_top + 15}" '
            f'font-family="{FIGURE_SANS_FONT}" font-size="13" font-weight="700" '
            f'fill="{yield_color}">Mean {overall["mean"]:.1f}</text>',
            f'<line x1="{overall_left}" y1="{overall_bottom}" x2="{overall_right}" '
            f'y2="{overall_bottom}" stroke="#69716F" stroke-width="1.4"/>',
            f'<text x="{(overall_left + overall_right) / 2:.2f}" y="427" '
            f'text-anchor="middle" font-family="{FIGURE_SANS_FONT}" font-size="15" '
            'fill="#303536">Optotagged cells per session</text>',
        ]
    )

    append_optotagging_yield_panel(
        svg,
        summary["major_parent"],
        label="C",
        y_axis_label="Major parent area",
        x=35,
        y=500,
        width=545,
        height=430,
        tick_step=10,
        label_width=112,
    )
    top_structures = sorted(
        summary["structures"],
        key=lambda record: (-record["mean"], record["label"]),
    )[:18]
    append_optotagging_yield_panel(
        svg,
        top_structures,
        label="D",
        y_axis_label="Structure acronym",
        x=620,
        y=500,
        width=545,
        height=430,
        tick_step=5,
        label_width=104,
        bar_height=8,
        point_radius=1.7,
    )
    svg.append("</svg>")
    output.parent.mkdir(parents=True, exist_ok=True)
    write_svg_output(output, svg)
    return output


def write_optotagging_heatmap_svg(
    output: Path = OPTOTAGGING_HEATMAP_STATIC_OUTPUT,
    data_path: Path = OPTOTAGGING_HEATMAP_DATA_PATH,
    provenance_path: Path = OPTOTAGGING_HEATMAP_PROVENANCE_PATH,
    media_dir: Path = OPTOTAGGING_HEATMAP_SOURCE_DIR,
    static_source: Path | None = None,
) -> Path:
    """Copy the source static composite into the publication outputs."""

    load_optotagging_heatmap_data(data_path, provenance_path, media_dir)
    if static_source is None:
        static_source = media_dir / OPTOTAGGING_STATIC_SOURCE.name
    svg = static_source.read_text(encoding="utf-8")
    required_text = (
        "Optotagging response and yield summary",
        "Major parent area",
        "Structure acronym",
    )
    if "<svg" not in svg or any(text not in svg for text in required_text):
        raise RuntimeError("Optotagging static composite does not match its source figure.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(svg, encoding="utf-8", newline="\n")
    return output


def write_neuropixels_trajectory_html(
    output: Path = NEUROPIXELS_TRAJECTORY_INTERACTIVE_OUTPUT,
    static_output: Path = NEUROPIXELS_TRAJECTORY_STATIC_OUTPUT,
    data_path: Path = NEUROPIXELS_TRAJECTORY_DATA_PATH,
    provenance_path: Path = NEUROPIXELS_TRAJECTORY_PROVENANCE_PATH,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = load_neuropixels_trajectory_data(data_path, provenance_path)
    write_neuropixels_trajectory_svg(static_output, data_path, provenance_path)
    template = (JAVASCRIPT_DIR / "neuropixels-trajectories.html").read_text(
        encoding="utf-8"
    )
    stylesheet = load_figure_stylesheet("neuropixels-trajectories.css")
    javascript = (JAVASCRIPT_DIR / "neuropixels-trajectories.js").read_text(
        encoding="utf-8"
    )
    html = (
        template.replace("__NEUROPIXELS_TRAJECTORY_CSS__", stylesheet)
        .replace(
            "__NEUROPIXELS_TRAJECTORY_STATIC_IMAGE__",
            f"media/neuropixels-trajectories/{static_output.name}",
        )
        .replace(
            "__NEUROPIXELS_TRAJECTORY_DATA__",
            json.dumps(
                payload,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
        .replace("__NEUROPIXELS_TRAJECTORY_JS__", javascript)
        .replace("__EMBED_AUTO_HEIGHT_JS__", load_embed_auto_height())
    )
    output.write_text(html, encoding="utf-8", newline="\n")
    media_output = output.parent / "media" / "neuropixels-trajectories"
    if media_output.exists():
        shutil.rmtree(media_output)
    media_output.mkdir(parents=True)
    shutil.copy2(static_output, media_output / static_output.name)
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


def load_eye_tracking_excerpts(path: Path = EYE_TRACKING_EXCERPTS_PATH) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 2 or payload.get("durationSeconds") != 16.0:
        raise RuntimeError("Eye-tracking excerpt schema or duration is not supported.")
    sessions = payload.get("sessions", [])
    if [session.get("id") for session in sessions] != [
        "neuropixels",
        "mesoscope",
        "slap2",
    ]:
        raise RuntimeError("Eye-tracking excerpts must contain the supported modalities in order.")
    expected_fields = ["time", "x", "y", "width", "height", "area", "blink"]
    expected_fits = {"pupil", "corneal_reflection", "ellipse"}
    for session in sessions:
        fits = session.get("fits", {})
        mapping = session.get("camera", {}).get("timeMap", [])
        if set(fits) != expected_fits:
            raise RuntimeError(f"Eye-tracking fit sources are invalid: {session['id']}")
        for fit_id, fit in fits.items():
            samples = fit.get("samples", [])
            reference = fit.get("fieldReference", {})
            if fit.get("sampleFields") != expected_fields:
                raise RuntimeError(
                    f"Eye-tracking sample fields are invalid: {session['id']}/{fit_id}"
                )
            if (
                not samples
                or samples[0][0] > 0.04
                or samples[-1][0] < 15.95
                or not any(sample[-1] for sample in samples)
                or any(len(sample) != len(expected_fields) for sample in samples)
            ):
                raise RuntimeError(
                    f"Eye-tracking samples are incomplete: {session['id']}/{fit_id}"
                )
            if (
                reference.get("frameWidth", 0) <= 0
                or reference.get("frameHeight", 0) <= 0
                or not 0 <= reference.get("medianX", -1) < reference["frameWidth"]
                or not 0 <= reference.get("medianY", -1) < reference["frameHeight"]
                or reference.get("areaLow", 0) >= reference.get("areaHigh", 0)
                or reference.get("validNonblinkSamples", 0) < 100
            ):
                raise RuntimeError(
                    f"Eye-tracking field reference is invalid: {session['id']}/{fit_id}"
                )
        if (
            len(mapping) < 2
            or mapping[0][0] > 0
            or mapping[-1][0] < payload["durationSeconds"]
            or any(
                current[0] <= previous[0] or current[1] <= previous[1]
                for previous, current in zip(mapping[:-1], mapping[1:], strict=True)
            )
        ):
            raise RuntimeError(f"Eye-camera frame map is invalid: {session['id']}")
        event_time = session.get("event", {}).get("time")
        if event_time != 5.0 or not any(
            row["start"] <= event_time <= row["end"]
            for row in session.get("stimulus", [])
        ):
            raise RuntimeError(f"Eye-tracking event lacks stimulus coverage: {session['id']}")
    return payload


def write_eye_tracking_static_svg(
    output: Path = EYE_TRACKING_STATIC_OUTPUT,
) -> Path:
    payload = load_eye_tracking_excerpts()
    width = 1400
    height = 1050
    plot_left = 205
    plot_width = 1145
    row_tops = (92, 397, 702)
    trace_height = 70
    trace_gap = 12
    duration = payload["durationSeconds"]
    accents = {
        "neuropixels": "#4B79C6",
        "mesoscope": "#14866C",
        "slap2": "#168EA0",
    }

    def x_position(time: float) -> float:
        return plot_left + plot_width * time / duration

    def limits(values: list[float]) -> tuple[float, float]:
        ordered = sorted(values)
        low = ordered[max(0, round((len(ordered) - 1) * 0.01))]
        high = ordered[min(len(ordered) - 1, round((len(ordered) - 1) * 0.99))]
        padding = max((high - low) * 0.08, 1.0)
        return low - padding, high + padding

    def trace_paths(
        samples: list[list[float | bool]],
        field_index: int,
        top: float,
        low: float,
        high: float,
    ) -> list[str]:
        paths: list[str] = []
        points: list[str] = []
        for sample in samples:
            value = float(sample[field_index])
            invalid = bool(sample[6]) or (field_index == 5 and value <= 0)
            if invalid or not math.isfinite(value) or value < low or value > high:
                if len(points) > 1:
                    paths.append("M" + " L".join(points))
                points = []
                continue
            y_position = top + trace_height * (high - value) / (high - low)
            points.append(f"{x_position(float(sample[0])):.2f},{y_position:.2f}")
        if len(points) > 1:
            paths.append("M" + " L".join(points))
        return paths

    def blink_intervals(samples: list[list[float | bool]]) -> list[tuple[float, float]]:
        intervals: list[tuple[float, float]] = []
        start: float | None = None
        for index, sample in enumerate(samples):
            if sample[6] and start is None:
                start = float(sample[0])
            if start is not None and (
                not sample[6] or index == len(samples) - 1
            ):
                intervals.append((start, float(sample[0])))
                start = None
        return intervals

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title description">',
        '<title id="title">Synchronized eye-tracking signals across recording modalities</title>',
        '<desc id="description">Neuropixels, mesoscope, and SLAP2 eye-tracking excerpts '
        'with vertically aligned pupil x position, y position, and area traces. The '
        'orientation oddball period and likely blinks are highlighted.</desc>',
        f'<rect width="{width}" height="{height}" fill="#FFFFFF"/>',
        '<text x="35" y="42" font-family="Myriad Pro, Arial, sans-serif" '
        'font-size="28" font-weight="700" fill="#293133">'
        'Eye tracking around a visual oddball</text>',
        '<rect x="870" y="23" width="22" height="15" fill="#22BCAD" fill-opacity="0.22"/>',
        '<text x="900" y="36" font-family="Myriad Pro, Arial, sans-serif" font-size="14" '
        'fill="#59615F">90° orientation deviant</text>',
        '<rect x="1110" y="23" width="22" height="15" fill="#B9C1BE" fill-opacity="0.55"/>',
        '<text x="1140" y="36" font-family="Myriad Pro, Arial, sans-serif" font-size="14" '
        'fill="#59615F">Likely blink</text>',
    ]
    signal_specs = ((1, "X position", "px"), (2, "Y position", "px"), (5, "Pupil area", "px²"))
    for row_index, (session, row_top) in enumerate(
        zip(payload["sessions"], row_tops, strict=True)
    ):
        samples = session["fits"]["pupil"]["samples"]
        modality = session["id"]
        accent = accents[modality]
        event_row = next(
            row
            for row in session["stimulus"]
            if row["start"] <= session["event"]["time"] <= row["end"]
        )
        svg.extend(
            [
                f'<text x="35" y="{row_top}" font-family="Myriad Pro, Arial, sans-serif" '
                f'font-size="22" font-weight="700" fill="{accent}">'
                f'{escape(session["label"])}</text>',
                f'<text x="35" y="{row_top + 24}" font-family="IBM Plex Mono, monospace" '
                f'font-size="13" fill="#59615F">mouse {escape(session["subject"])} · trial '
                f'{session["event"]["trialNumber"]}</text>',
            ]
        )
        for signal_index, (field_index, label, unit) in enumerate(signal_specs):
            top = row_top + 38 + signal_index * (trace_height + trace_gap)
            valid_values = [
                float(sample[field_index])
                for sample in samples
                if not sample[6]
                and math.isfinite(float(sample[field_index]))
                and (field_index != 5 or float(sample[field_index]) > 0)
            ]
            low, high = limits(valid_values)
            event_left = x_position(event_row["start"])
            event_width = x_position(event_row["end"]) - event_left
            svg.extend(
                [
                    f'<rect x="{plot_left}" y="{top}" width="{plot_width}" height="{trace_height}" '
                    'fill="#FAFBFB" stroke="#D7DBD9"/>',
                    f'<rect class="oddball-period" x="{event_left:.2f}" y="{top}" '
                    f'width="{event_width:.2f}" height="{trace_height}" fill="#22BCAD" '
                    'fill-opacity="0.22"/>',
                ]
            )
            for blink in blink_intervals(samples):
                blink_left = x_position(max(0, blink[0]))
                blink_width = x_position(min(duration, blink[1])) - blink_left
                if blink_width > 0:
                    svg.append(
                        f'<rect class="blink-period" x="{blink_left:.2f}" y="{top}" '
                        f'width="{blink_width:.2f}" height="{trace_height}" '
                        'fill="#B9C1BE" fill-opacity="0.55"/>'
                    )
            for path in trace_paths(samples, field_index, top, low, high):
                svg.append(
                    f'<path d="{path}" fill="none" stroke="{accent}" stroke-width="2" '
                    'stroke-linejoin="round" stroke-linecap="round"/>'
                )
            svg.extend(
                [
                    f'<text x="{plot_left - 14}" y="{top + 29}" text-anchor="end" '
                    'font-family="Myriad Pro, Arial, sans-serif" font-size="15" font-weight="700" '
                    f'fill="#303536">{label}</text>',
                    f'<text x="{plot_left - 14}" y="{top + 48}" text-anchor="end" '
                    'font-family="Myriad Pro, Arial, sans-serif" font-size="12" '
                    f'fill="#707674">{unit}</text>',
                    f'<text x="{plot_left + 6}" y="{top + 14}" '
                    'font-family="IBM Plex Mono, monospace" '
                    f'font-size="{FIGURE_TYPE_SMALL}" fill="#707674">{high:.0f}</text>',
                    f'<text x="{plot_left + 6}" y="{top + trace_height - 5}" '
                    f'font-family="IBM Plex Mono, monospace" font-size="{FIGURE_TYPE_SMALL}" '
                    f'fill="#707674">{low:.0f}</text>',
                ]
            )
        axis_y = row_top + 38 + 3 * trace_height + 2 * trace_gap
        for time in (0, 4, 8, 12, 16):
            axis_x = x_position(time)
            svg.extend(
                [
                    f'<line x1="{axis_x:.2f}" y1="{axis_y}" x2="{axis_x:.2f}" '
                    f'y2="{axis_y + 6}" stroke="#6F7774"/>',
                    f'<text x="{axis_x:.2f}" y="{axis_y + 22}" text-anchor="middle" '
                    'font-family="IBM Plex Mono, monospace" font-size="12" '
                    f'fill="#59615F">{time} s</text>',
                ]
            )
        if row_index < len(row_tops) - 1:
            svg.append(
                f'<line x1="35" y1="{axis_y + 38}" x2="1350" y2="{axis_y + 38}" '
                'stroke="#E3E6E5"/>'
            )
    svg.append("</svg>")
    output.parent.mkdir(parents=True, exist_ok=True)
    write_svg_output(output, svg)
    return output


def write_eye_tracking_viewer_html(
    output: Path = EYE_TRACKING_VIEWER_OUTPUT,
    static_output: Path = EYE_TRACKING_STATIC_OUTPUT,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = load_eye_tracking_excerpts()
    write_eye_tracking_static_svg(static_output)
    template = (JAVASCRIPT_DIR / "eye-tracking-viewer.html").read_text(encoding="utf-8")
    stylesheet = load_figure_stylesheet("eye-tracking-viewer.css")
    javascript = (JAVASCRIPT_DIR / "eye-tracking-viewer.js").read_text(encoding="utf-8")
    html = (
        template.replace("__EYE_TRACKING_CSS__", stylesheet)
        .replace(
            "__EYE_TRACKING_STATIC_IMAGE__",
            f"media/eye-tracking-viewer/{static_output.name}",
        )
        .replace(
            "__EYE_TRACKING_DATA__",
            json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
        )
        .replace("__EYE_TRACKING_JS__", javascript)
        .replace("__EMBED_AUTO_HEIGHT_JS__", load_embed_auto_height())
    )
    output.write_text(html, encoding="utf-8", newline="\n")
    media_output = output.parent / "media" / "eye-tracking-viewer"
    if media_output.exists():
        shutil.rmtree(media_output)
    media_output.mkdir(parents=True)
    shutil.copy2(static_output, media_output / static_output.name)
    return output


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
        or not text_sha256_matches(SESSION_RECORDS_PATH, source.get("sha256", ""))
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
    if (
        provenance.get("version") != 2
        or not text_sha256_matches(
            BEHAVIOR_EXCERPTS_PATH, provenance.get("behavior_excerpts_sha256", "")
        )
        or not text_sha256_matches(
            RUNNING_STATISTICS_PATH, provenance.get("running_statistics_sha256", "")
        )
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
        block_color = (
            SESSION_TYPE_COLORS[profile["context"]]
            if block["id"] == "context"
            else PROTOCOL_BLOCK_COLORS[block["id"]]
        )
        block_left = x(block["start_seconds"])
        block_right = x(block["end_seconds"])
        svg.extend(
            [
                f'<rect class="running-profile-block" data-block="{block["id"]}" '
                f'x="{block_left:.2f}" y="{top + 1}" '
                f'width="{max(0, block_right - block_left):.2f}" height="{height - 2}" '
                f'fill="{block_color}" fill-opacity="0.18"/>',
                f'<rect x="{block_left:.2f}" y="{top + 1}" '
                f'width="{max(0, block_right - block_left):.2f}" height="18" '
                f'fill="{block_color}"/>',
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
                f'<text class="modality-title" x="125" y="{row_top}" '
                'font-family="Source Sans 3, sans-serif" '
                f'font-size="{FIGURE_TYPE_SCALE["modality"]}" '
                'font-weight="700" fill="#293133">'
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
    write_svg_output(output, svg)
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
    stylesheet = load_figure_stylesheet("behavior-viewer.css")
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
    output.write_text(html, encoding="utf-8", newline="\n")
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
    if (
        payload.get("version") != 8
        or payload.get("windowStartSeconds") != -1.0
        or payload.get("windowEndSeconds") != 3.0
        or not text_sha256_matches(
            behavior_path, payload.get("behaviorExcerptSha256", "")
        )
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
                        option.get("frameWidth") == 400
                        and option.get("frameHeight") == 640
                        and option.get("displayWidth") == 800
                        and option.get("displayHeight") == 1280
                        and option.get("nativeWidth") == 1280
                        and option.get("nativeHeight") == 800
                        and option.get("storedWidth") == 1280
                        and option.get("storedHeight") == 800
                        and option.get("displayTransform")
                        == "transpose-for-publication"
                        and option.get("fastScanAxis") == "vertical"
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


def load_segmentation_viewers(
    path: Path = SEGMENTATION_VIEWER_DATA_PATH,
    provenance_path: Path = SEGMENTATION_VIEWER_PROVENANCE_PATH,
) -> dict:
    source_bytes = path.read_bytes()
    payload = json.loads(source_bytes)
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if (
        payload.get("version") != 4
        or hashlib.sha256(source_bytes).hexdigest() != provenance.get("vendored_sha256")
        or hashlib.sha256(NEURAL_EXCERPTS_PATH.read_bytes()).hexdigest()
        != provenance.get("source_raw_neural_sha256")
    ):
        raise RuntimeError("Segmentation viewer snapshot provenance is invalid.")

    viewers = payload.get("viewers", [])
    expected_sources = {
        "neuropixels": {
            "probe-a": 569,
            "probe-b": 502,
            "probe-c": 534,
            "probe-d": 799,
            "probe-e": 542,
            "probe-f": 604,
        },
        "mesoscope": {
            "visp_0": 399,
            "visp_1": 463,
            "visp_2": 70,
            "visp_3": 277,
            "visl_4": 374,
            "visl_5": 356,
            "visl_6": 124,
            "visl_7": 321,
        },
        "slap2": {"dmd1": 45, "dmd2": 74},
    }
    if [viewer.get("id") for viewer in viewers] != list(expected_sources):
        raise RuntimeError("Segmentation viewers must contain the three modalities in order.")
    for modality in viewers:
        modality_id = modality["id"]
        expected_asset = provenance.get("assets", {}).get(modality_id)
        if modality.get("asset") != expected_asset:
            raise RuntimeError(f"Segmentation viewer DANDI asset changed: {modality_id}")
        sources = modality.get("sources", [])
        expected_counts = expected_sources[modality_id]
        if [source.get("sourceId") for source in sources] != list(expected_counts):
            raise RuntimeError(f"Segmentation source inventory changed: {modality_id}")
        for source in sources:
            source_id = source["sourceId"]
            if modality_id != "neuropixels":
                source["traceLabel"] = "ΔF/F (%)"
                source["traceScale"] = 100
                source["traceUnit"] = "%"
            filter_count = expected_counts[source_id]
            rows = source.get("traceRows")
            columns = source.get("traceColumns")
            try:
                trace_data = base64.b64decode(
                    source.get("traceDataBase64", ""),
                    validate=True,
                )
            except ValueError as exc:
                raise RuntimeError(
                    f"Segmentation trace encoding is invalid: {modality_id}/{source_id}"
                ) from exc
            if (
                source.get("asset") != expected_asset
                or source.get("filterCount") != filter_count
                or len(source.get("filters", [])) != filter_count
                or rows != filter_count
                or not isinstance(columns, int)
                or columns < 100
                or len(trace_data) != rows * columns * 4
                or len(source.get("traceTimesSeconds", [])) != columns
                or source["traceTimesSeconds"][0] < 0
                or "activityImage" in source
                or "eventLabel" in source
                or "context" in source
                or any(
                    "snr" in record or "firingRateHz" in record
                    for record in source.get("filters", [])
                )
            ):
                raise RuntimeError(
                    f"Segmentation source dimensions changed: {modality_id}/{source_id}"
                )

            if modality_id != "neuropixels" and (
                source.get("fastScanAxis")
                != ("horizontal" if modality_id == "mesoscope" else "vertical")
                or source.get("displayTransform")
                != ("stored-yx" if modality_id == "mesoscope" else "transpose-for-publication")
            ):
                raise RuntimeError(
                    f"Segmentation scan orientation changed: {modality_id}/{source_id}"
                )

            for field in ("baseImage", "labelImage", "filterOverlay"):
                record = source.get(field)
                if not record:
                    continue
                media_path = REPO_ROOT / "figure_sources" / record["assetPath"]
                expected_sha256 = provenance["vendored_media_sha256"].get(
                    media_path.name
                )
                if (
                    not media_path.is_file()
                    or hashlib.sha256(media_path.read_bytes()).hexdigest()
                    != record["sha256"]
                    or record["sha256"] != expected_sha256
                ):
                    raise RuntimeError(
                        f"Segmentation viewer media checksum changed: {media_path.name}"
                    )

            if modality_id != "neuropixels":
                continue
            waveform_columns = source.get("waveformColumns")
            waveform_data = base64.b64decode(
                source.get("waveformDataBase64", ""),
                validate=True,
            )
            raw_data = base64.b64decode(
                source.get("rawDataBase64", ""),
                validate=True,
            )
            spike_events = source.get("spikeEvents", [])
            if (
                source.get("waveformRows") != filter_count
                or waveform_columns != 210
                or len(waveform_data) != filter_count * waveform_columns * 4
                or source.get("viewType") != "spike-map"
                or source.get("rawRows") != 96
                or source.get("rawColumns") != 3000
                or len(raw_data) != source["rawRows"] * source["rawColumns"]
                or not spike_events
                or any(
                    event.get("filterIndex") not in range(filter_count)
                    or event.get("row") not in range(source["rawRows"])
                    or not source["rawTimeStartMs"]
                    <= event.get("timeMs", -1)
                    <= source["rawTimeEndMs"]
                    for event in spike_events
                )
            ):
                raise RuntimeError(
                    f"Neuropixels spike-map dimensions changed: {source_id}"
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


def paeth_predictor(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    left_distance = abs(estimate - left)
    above_distance = abs(estimate - above)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= above_distance and left_distance <= upper_left_distance:
        return left
    if above_distance <= upper_left_distance:
        return above
    return upper_left


def decode_rgb_png(path: Path) -> tuple[int, int, bytes]:
    encoded = path.read_bytes()
    if not encoded.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError(f"PNG signature is invalid: {path.name}")
    position = 8
    width = height = None
    compressed = []
    while position < len(encoded):
        length = struct.unpack(">I", encoded[position : position + 4])[0]
        chunk_type = encoded[position + 4 : position + 8]
        chunk = encoded[position + 8 : position + 8 + length]
        position += length + 12
        if chunk_type == b"IHDR":
            width, height, depth, color, compression, filtering, interlace = (
                struct.unpack(">IIBBBBB", chunk)
            )
            if (depth, color, compression, filtering, interlace) != (8, 2, 0, 0, 0):
                raise RuntimeError(f"PNG format is unsupported: {path.name}")
        elif chunk_type == b"IDAT":
            compressed.append(chunk)
        elif chunk_type == b"IEND":
            break
    if width is None or height is None or not compressed:
        raise RuntimeError(f"PNG data is incomplete: {path.name}")

    raw = zlib.decompress(b"".join(compressed))
    stride = width * 3
    expected = height * (stride + 1)
    if len(raw) != expected:
        raise RuntimeError(f"PNG scanline length changed: {path.name}")
    pixels = bytearray()
    previous = bytearray(stride)
    for row_index in range(height):
        offset = row_index * (stride + 1)
        filter_type = raw[offset]
        scanline = bytearray(raw[offset + 1 : offset + stride + 1])
        for index, value in enumerate(scanline):
            left = scanline[index - 3] if index >= 3 else 0
            above = previous[index]
            upper_left = previous[index - 3] if index >= 3 else 0
            if filter_type == 1:
                value += left
            elif filter_type == 2:
                value += above
            elif filter_type == 3:
                value += (left + above) // 2
            elif filter_type == 4:
                value += paeth_predictor(left, above, upper_left)
            elif filter_type != 0:
                raise RuntimeError(f"PNG filter is unsupported: {filter_type}")
            scanline[index] = value & 0xFF
        pixels.extend(scanline)
        previous = scanline
    return width, height, bytes(pixels)


def decode_grayscale_png(path: Path) -> tuple[int, int, bytes]:
    encoded = path.read_bytes()
    if not encoded.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError(f"PNG signature is invalid: {path.name}")
    position = 8
    width = height = None
    compressed = []
    while position < len(encoded):
        length = struct.unpack(">I", encoded[position : position + 4])[0]
        chunk_type = encoded[position + 4 : position + 8]
        chunk = encoded[position + 8 : position + 8 + length]
        position += length + 12
        if chunk_type == b"IHDR":
            width, height, depth, color, compression, filtering, interlace = (
                struct.unpack(">IIBBBBB", chunk)
            )
            if (depth, color, compression, filtering, interlace) != (8, 0, 0, 0, 0):
                raise RuntimeError(f"PNG format is unsupported: {path.name}")
        elif chunk_type == b"IDAT":
            compressed.append(chunk)
        elif chunk_type == b"IEND":
            break
    if width is None or height is None or not compressed:
        raise RuntimeError(f"PNG data is incomplete: {path.name}")

    raw = zlib.decompress(b"".join(compressed))
    stride = width
    if len(raw) != height * (stride + 1):
        raise RuntimeError(f"PNG scanline length changed: {path.name}")
    pixels = bytearray()
    previous = bytearray(stride)
    for row_index in range(height):
        offset = row_index * (stride + 1)
        filter_type = raw[offset]
        scanline = bytearray(raw[offset + 1 : offset + stride + 1])
        for index, value in enumerate(scanline):
            left = scanline[index - 1] if index else 0
            above = previous[index]
            upper_left = previous[index - 1] if index else 0
            if filter_type == 1:
                value += left
            elif filter_type == 2:
                value += above
            elif filter_type == 3:
                value += (left + above) // 2
            elif filter_type == 4:
                value += paeth_predictor(left, above, upper_left)
            elif filter_type != 0:
                raise RuntimeError(f"PNG filter is unsupported: {filter_type}")
            scanline[index] = value & 0xFF
        pixels.extend(scanline)
        previous = scanline
    return width, height, bytes(pixels)


def represented_filter_fill_png(viewer: dict, indices: list[int]) -> bytes:
    label_path = REPO_ROOT / "figure_sources" / viewer["labelImage"]["assetPath"]
    width, height, labels = decode_rgb_png(label_path)
    color_by_label = {
        index + 1: SEGMENTATION_FILTER_COLORS[index % len(SEGMENTATION_FILTER_COLORS)]
        for index in indices
    }
    pixels = bytearray(width * height * 4)
    for pixel_index in range(width * height):
        source = pixel_index * 3
        label = labels[source] + (labels[source + 1] << 8) + (labels[source + 2] << 16)
        color = color_by_label.get(label)
        if color is None:
            continue
        target = pixel_index * 4
        pixels[target : target + 4] = bytes((*color, 120))
    return encode_rgba_png(width, height, bytes(pixels))


def common_median_corrected_rgb(
    raw: bytes,
    rows: int,
    columns: int,
    contrast: float,
) -> bytes:
    if len(raw) != rows * columns:
        raise RuntimeError("Raw AP buffer does not match its declared dimensions.")
    common_mode = [
        statistics.median(raw[column::columns])
        for column in range(columns)
    ]
    rgb = bytearray(len(raw) * 3)
    for index, value in enumerate(raw):
        centered = value - common_mode[index % columns]
        gray = max(0, min(255, round(127.5 + centered * contrast)))
        rgb[index * 3 : index * 3 + 3] = bytes((gray, gray, gray))
    return bytes(rgb)


def encode_rgba_png(width: int, height: int, pixels: bytes) -> bytes:
    if len(pixels) != width * height * 4:
        raise RuntimeError("RGBA pixel buffer does not match its declared dimensions.")
    stride = width * 4
    scanlines = b"".join(
        b"\x00" + pixels[row * stride : (row + 1) * stride]
        for row in range(height)
    )
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)),
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
    if (
        provenance.get("version") != 2
        or not text_sha256_matches(
            NEURAL_EXCERPTS_PATH,
            provenance.get("raw_neural_excerpts_sha256", ""),
        )
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
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{card_width}" '
            f'height="{card_height}" rx="3" fill="#FFFFFF" stroke="#8F9996"/>',
            f'<text x="{x + 9:.2f}" y="{y + 19:.2f}" '
            'font-family="Source Sans 3, sans-serif" font-size="13" '
            f'font-weight="700" fill="#303536">{escape(option["label"])}</text>',
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
                    f'font-family="IBM Plex Mono, monospace" font-size="{FIGURE_TYPE_SMALL}" '
                    f'text-anchor="middle" fill="#59615F">{milliseconds}</text>',
                ]
            )
        svg.append(
            f'<text x="{heatmap_x + heatmap_width / 2:.2f}" y="{axis_y + 29:.2f}" '
            f'font-family="Source Sans 3, sans-serif" font-size="{FIGURE_TYPE_SMALL}" '
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
    display_width = option.get("displayWidth", option["nativeWidth"])
    display_height = option.get("displayHeight", option["nativeHeight"])
    image_height = image_width * display_height / display_width
    card_height = header_height + image_height + padding
    image_x = x + padding
    image_y = y + header_height
    image_data = base64.b64encode(path.read_bytes()).decode()
    svg.extend(
        [
            f'<g class="raw-image-card" data-modality="{modality}" '
            f'data-option-id="{option["id"]}" data-card-width="{card_width:.0f}">',
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
            native_width=display_width,
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
    height = 700
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
                f'<text class="modality-title" x="{left + 136}" y="35" '
                'font-family="Source Sans 3, sans-serif" '
                f'font-size="{FIGURE_TYPE_SCALE["modality"]}" '
                f'font-weight="700" fill="#293133">{label}</text>',
                f'<text class="modality-scale" x="{left + 136}" y="67" '
                'font-family="Source Sans 3, sans-serif" font-size="12" '
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
    detail_label_y = 122
    detail_card_y = 135
    mesoscope_stacks = (
        ("VISp · 4 planes", 650, ("visp_2", "visp_0", "visp_1", "visp_3")),
        ("VISl · 4 planes", 915, ("visl_6", "visl_4", "visl_5", "visl_7")),
    )
    for stack_index, (stack_label, left, option_ids) in enumerate(mesoscope_stacks):
        svg.append(
            f'<text class="neural-detail-label" x="{left}" y="{detail_label_y}" '
            'font-family="Source Sans 3, sans-serif" '
            f'font-size="12" font-weight="700" fill="#303536">{stack_label}</text>'
        )
        for index, option_id in enumerate(option_ids):
            option = mesoscope_options[option_id]
            append_microscopy_raw_card(
                svg,
                x=left + index * 8,
                y=detail_card_y + index * 45,
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
        f'<text class="neural-detail-label" x="1240" y="{detail_label_y}" '
        'font-family="Source Sans 3, sans-serif" '
        'font-size="12" font-weight="700" fill="#303536">'
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
            x=1240 + index * 270,
            y=detail_card_y,
            card_width=265,
            option=option,
            path=frame_paths[("slap2", composite_id)],
            modality="slap2",
            label=f"{dmd} · {depth:g} µm",
            show_scale=index == len(SLAP2_STATIC_COMPOSITES) - 1,
        )
    svg.append("</svg>")
    output.parent.mkdir(parents=True, exist_ok=True)
    write_svg_output(output, svg)
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
    stylesheet = load_figure_stylesheet("neural-viewer.css")
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
    output.write_text(html, encoding="utf-8", newline="\n")
    media_output = output.parent / "media" / "neural-viewer"
    if media_output.exists():
        shutil.rmtree(media_output)
    shutil.copytree(NEURAL_MEDIA_DIR, media_output)
    shutil.copy2(static_output, media_output / static_output.name)
    return output


def write_segmentation_viewer_html(
    output: Path = SEGMENTATION_VIEWER_OUTPUT,
    data_path: Path = SEGMENTATION_VIEWER_DATA_PATH,
    provenance_path: Path = SEGMENTATION_VIEWER_PROVENANCE_PATH,
    static_output: Path = SEGMENTATION_VIEWER_STATIC_OUTPUT,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = load_segmentation_viewers(data_path, provenance_path)
    logo_data_uris = platform_logo_data_uris()
    for modality in payload["viewers"]:
        modality["logo"] = logo_data_uris[modality["id"]]
    template = (JAVASCRIPT_DIR / "segmentation-viewer.html").read_text(
        encoding="utf-8"
    )
    stylesheet = load_figure_stylesheet("segmentation-viewer.css")
    javascript = (JAVASCRIPT_DIR / "segmentation-viewer.js").read_text(
        encoding="utf-8"
    )
    html = (
        template.replace("__SEGMENTATION_CSS__", stylesheet)
        .replace(
            "__SEGMENTATION_STATIC_IMAGE__",
            f"media/segmentation-viewers/{static_output.name}",
        )
        .replace("__SEGMENTATION_JS__", javascript)
        .replace("__EMBED_AUTO_HEIGHT_JS__", load_embed_auto_height())
        .replace(
            "__SEGMENTATION_DATA__",
            json.dumps(
                payload,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
    )
    output.write_text(html, encoding="utf-8", newline="\n")
    media_output = output.parent / "media" / "segmentation-viewers"
    if media_output.exists():
        shutil.rmtree(media_output)
    shutil.copytree(SEGMENTATION_VIEWER_MEDIA_DIR, media_output)
    shutil.copy2(static_output, media_output / static_output.name)
    return output


def segmentation_trace_rows(viewer: dict) -> list[list[float]]:
    rows = viewer["traceRows"]
    columns = viewer["traceColumns"]
    encoded = base64.b64decode(viewer["traceDataBase64"], validate=True)
    values = struct.unpack(f"<{rows * columns}f", encoded)
    scale = viewer.get("traceScale", 1)
    return [
        [value * scale for value in values[index * columns : (index + 1) * columns]]
        for index in range(rows)
    ]


def static_segmentation_trace_indices(
    rows: list[list[float]],
    count: int = 20,
) -> list[int]:
    active_indices = []
    for index, values in enumerate(rows):
        finite = [value for value in values if math.isfinite(value)]
        if finite and max(finite) > min(finite):
            active_indices.append(index)
    if len(active_indices) <= count:
        return active_indices
    return [
        active_indices[round(position * (len(active_indices) - 1) / (count - 1))]
        for position in range(count)
    ]


def nice_trace_scale(value: float) -> float:
    if not math.isfinite(value) or value <= 0:
        return 1.0
    magnitude = 10 ** math.floor(math.log10(value))
    normalized = value / magnitude
    factor = 5 if normalized >= 5 else 2 if normalized >= 2 else 1
    return factor * magnitude


def append_segmentation_trace_stack(
    svg: list[str],
    viewer: dict,
    indices: list[int],
    rows: list[list[float]],
    *,
    left: float,
    top: float,
    width: float,
    height: float,
) -> None:
    selected_rows = [rows[index] for index in indices]
    finite = [
        value for row in selected_rows for value in row if math.isfinite(value)
    ]
    minimum = min(finite)
    maximum = max(finite)
    if viewer["id"] == "neuropixels":
        minimum = 0.0
    if minimum == maximum:
        maximum = minimum + 1
    times = viewer["traceTimesSeconds"]
    minimum_time = times[0]
    maximum_time = times[-1]
    plot_left = left + 94
    plot_right = left + width - 18
    traces_top = top + 8
    scale_height = 38
    row_height = (height - 8 - scale_height) / len(selected_rows)
    trace_height = row_height * 0.62
    vertical_gain = {"neuropixels": 1.0, "mesoscope": 3.0, "slap2": 2.0}[
        viewer["id"]
    ]

    if vertical_gain > 1:
        clip_paths = []
        for row_position, index in enumerate(indices):
            clip_paths.append(
                f'<clipPath id="{viewer["id"]}-trace-{index}-clip">'
                f'<rect x="{plot_left:.2f}" '
                f'y="{traces_top + row_position * row_height:.2f}" '
                f'width="{plot_right - plot_left:.2f}" height="{row_height:.2f}"/>'
                "</clipPath>"
            )
        svg.append(f'<defs>{"".join(clip_paths)}</defs>')

    for row_position, (index, values) in enumerate(
        zip(indices, selected_rows, strict=True)
    ):
        row_top = traces_top + row_position * row_height
        row_finite = sorted(value for value in values if math.isfinite(value))
        middle = len(row_finite) // 2
        row_median = (
            row_finite[middle]
            if len(row_finite) % 2
            else (row_finite[middle - 1] + row_finite[middle]) / 2
        )
        commands = []
        drawing = False
        stride = max(1, math.ceil(len(values) / 900))
        for sample_index in range(0, len(values), stride):
            value = values[sample_index]
            if not math.isfinite(value):
                drawing = False
                continue
            horizontal = plot_left + (times[sample_index] - minimum_time) / (
                maximum_time - minimum_time
            ) * (plot_right - plot_left)
            if vertical_gain > 1:
                vertical = (
                    row_top
                    + row_height / 2
                    + (row_median - value)
                    / (maximum - minimum)
                    * trace_height
                    * vertical_gain
                )
            else:
                vertical = (
                    row_top
                    + (maximum - value) / (maximum - minimum) * trace_height
                )
            commands.append(
                f'{"L" if drawing else "M"}{horizontal:.2f},{vertical:.2f}'
            )
            drawing = True
        color = SEGMENTATION_FILTER_COLORS[index % len(SEGMENTATION_FILTER_COLORS)]
        stroke = f"#{color[0]:02X}{color[1]:02X}{color[2]:02X}"
        clip_attribute = (
            f'clip-path="url(#{viewer["id"]}-trace-{index}-clip)" '
            if vertical_gain > 1
            else ""
        )
        svg.extend(
            [
                f'<text x="{plot_left - 10:.2f}" y="{row_top + trace_height / 2 + 4:.2f}" '
                f'text-anchor="end" font-family="{FIGURE_SANS_FONT}" '
                f'font-size="{FIGURE_TYPE_SMALL}" fill="#4D5553">'
                f'{escape(viewer["filters"][index]["label"])}</text>',
                f'<path class="static-activity-trace" data-filter-index="{index}" '
                f'data-vertical-gain="{vertical_gain:g}" '
                f'{clip_attribute}'
                f'd="{" ".join(commands)}" fill="none" stroke="{stroke}" '
                'stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/>',
            ]
        )

    scale_y = top + height - 18
    x_scale = 2.0 if viewer["id"] == "neuropixels" else 5.0
    x_scale_width = x_scale / (maximum_time - minimum_time) * (
        plot_right - plot_left
    )
    y_scale = nice_trace_scale((maximum - minimum) * 0.25)
    y_scale_height = (
        y_scale / (maximum - minimum) * trace_height * vertical_gain
    )
    scale_x = plot_left
    unit = "Hz" if viewer["id"] == "neuropixels" else "%"
    y_scale_label = f"{y_scale:g}%" if unit == "%" else f"{y_scale:g} {unit}"
    svg.extend(
        [
            f'<line class="trace-scale-bar" x1="{scale_x:.2f}" y1="{scale_y:.2f}" '
            f'x2="{scale_x + x_scale_width:.2f}" y2="{scale_y:.2f}" '
            'stroke="#000000" stroke-width="4" stroke-linecap="square"/>',
            f'<text x="{scale_x + x_scale_width / 2:.2f}" y="{scale_y + 18:.2f}" '
            f'text-anchor="middle" font-family="{FIGURE_MONO_FONT}" '
            f'font-size="{FIGURE_TYPE_SMALL}" fill="#000000">{x_scale:g} s</text>',
            f'<line class="trace-scale-bar" x1="{scale_x:.2f}" '
            f'y1="{scale_y:.2f}" x2="{scale_x:.2f}" '
            f'y2="{scale_y - y_scale_height:.2f}" stroke="#000000" '
            'stroke-width="4" stroke-linecap="square"/>',
            f'<text x="{scale_x - 10:.2f}" y="{scale_y - y_scale_height - 7:.2f}" '
            f'text-anchor="end" font-family="{FIGURE_MONO_FONT}" '
            f'font-size="{FIGURE_TYPE_SMALL}" fill="#000000">{y_scale_label}</text>',
        ]
    )


def write_segmentation_viewer_svg(
    modality: str,
    output: Path | None = None,
    data_path: Path = SEGMENTATION_VIEWER_DATA_PATH,
    provenance_path: Path = SEGMENTATION_VIEWER_PROVENANCE_PATH,
) -> Path:
    if modality not in SEGMENTATION_VIEWER_STATIC_OUTPUTS:
        raise ValueError(f"Unsupported segmentation viewer modality: {modality}")
    output = output or SEGMENTATION_VIEWER_STATIC_OUTPUTS[modality]
    payload = load_segmentation_viewers(data_path, provenance_path)
    modality_record = next(
        record for record in payload["viewers"] if record["id"] == modality
    )
    viewer = modality_record["sources"][0]
    trace_rows = segmentation_trace_rows(viewer)
    trace_indices = static_segmentation_trace_indices(trace_rows)
    represented_filters = set(trace_indices)
    left_panel_label, right_panel_label = SEGMENTATION_PANEL_LABELS[modality]
    logo_data = base64.b64encode(load_platform_logos()[modality].read_bytes()).decode()
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="760" '
        'viewBox="0 0 1400 760" role="img" aria-labelledby="title description">',
        f'<title id="title">{escape(SEGMENTATION_VIEWER_TITLES[modality])}</title>',
        '<desc id="description">A source projection shows all extraction filters; '
        'twenty representative filters are paired with vertically stacked activity traces.</desc>',
        '<rect width="1400" height="760" fill="#FFFFFF"/>',
        f'<image class="static-modality-logo" data-modality="{modality}" '
        f'href="data:image/png;base64,{logo_data}" x="52" y="10" '
        'width="54" height="54"/>',
        f'<text x="52" y="85" font-family="{FIGURE_SANS_FONT}" font-size="20" '
        f'font-weight="700" fill="#293133">{left_panel_label}</text>',
        f'<text x="755" y="85" font-family="{FIGURE_SANS_FONT}" font-size="20" '
        f'font-weight="700" fill="#293133">{right_panel_label}</text>',
    ]

    visual_left = 78.0
    visual_top = 100.0
    visual_width = 620.0
    visual_height = 590.0
    if modality == "neuropixels":
        raw = base64.b64decode(viewer["rawDataBase64"], validate=True)
        rgb = common_median_corrected_rgb(
            raw,
            viewer["rawRows"],
            viewer["rawColumns"],
            1.2,
        )
        raw_image = base64.b64encode(
            encode_rgb_png(viewer["rawColumns"], viewer["rawRows"], rgb)
        ).decode()
        image_x = visual_left + 46
        image_y = visual_top + 20
        image_width = visual_width - 56
        image_height = visual_height - 58

        def spike_x(time_ms: float) -> float:
            return image_x + (time_ms - viewer["rawTimeStartMs"]) / (
                viewer["rawTimeEndMs"] - viewer["rawTimeStartMs"]
            ) * image_width

        def spike_y(row: float) -> float:
            return image_y + (row + 0.5) / viewer["rawRows"] * image_height

        svg.extend(
            [
                f'<image href="data:image/png;base64,{raw_image}" x="{image_x:.2f}" '
                f'y="{image_y:.2f}" width="{image_width:.2f}" '
                f'height="{image_height:.2f}" preserveAspectRatio="none"/>',
            ]
        )
        for event in viewer["spikeEvents"]:
            is_represented = event["filterIndex"] in represented_filters
            color = SEGMENTATION_FILTER_COLORS[
                event["filterIndex"] % len(SEGMENTATION_FILTER_COLORS)
            ]
            fill = f"#{color[0]:02X}{color[1]:02X}{color[2]:02X}"
            svg.append(
                f'<circle cx="{spike_x(event["timeMs"]):.2f}" '
                f'cy="{spike_y(event["row"]):.2f}" '
                f'r="{3.7 if is_represented else 2.1}" fill="{fill}" '
                f'fill-opacity="{1 if is_represented else 0.82}" '
                f'stroke="{"#FFFFFF" if is_represented else "none"}" '
                f'stroke-width="{1.2 if is_represented else 0}"/>'
            )
        svg.append(
            f'<rect x="{image_x:.2f}" y="{image_y:.2f}" width="{image_width:.2f}" '
            f'height="{image_height:.2f}" fill="none" stroke="#68716F"/>'
        )
        for index in range(5):
            fraction = index / 4
            vertical = image_y + fraction * image_height
            depth = viewer["rawDepthMaxUm"] - fraction * (
                viewer["rawDepthMaxUm"] - viewer["rawDepthMinUm"]
            )
            horizontal = image_x + fraction * image_width
            time_ms = viewer["rawTimeStartMs"] + fraction * (
                viewer["rawTimeEndMs"] - viewer["rawTimeStartMs"]
            )
            svg.extend(
                [
                    f'<line x1="{image_x - 6:.2f}" y1="{vertical:.2f}" '
                    f'x2="{image_x:.2f}" y2="{vertical:.2f}" stroke="#68716F"/>',
                    f'<text x="{image_x - 8:.2f}" y="{vertical + 4:.2f}" '
                    f'text-anchor="end" font-family="{FIGURE_MONO_FONT}" '
                    f'font-size="{FIGURE_TYPE_SMALL}" fill="#68716F">{depth:.0f}</text>',
                    f'<line x1="{horizontal:.2f}" y1="{image_y + image_height:.2f}" '
                    f'x2="{horizontal:.2f}" y2="{image_y + image_height + 6:.2f}" '
                    'stroke="#68716F"/>',
                    f'<text x="{horizontal:.2f}" y="{image_y + image_height + 18:.2f}" '
                    f'text-anchor="middle" font-family="{FIGURE_MONO_FONT}" '
                    f'font-size="{FIGURE_TYPE_SMALL}" fill="#68716F">{time_ms:.0f}</text>',
                ]
            )
        svg.extend(
            [
                f'<text x="{image_x + image_width / 2:.2f}" '
                f'y="{image_y + image_height + 34:.2f}" text-anchor="middle" '
                f'font-family="{FIGURE_SANS_FONT}" font-size="{FIGURE_TYPE_SMALL}" '
                'font-weight="600" fill="#68716F">Excerpt time (ms)</text>',
                f'<text x="{image_x:.2f}" y="{image_y - 8:.2f}" '
                f'text-anchor="start" font-family="{FIGURE_SANS_FONT}" '
                f'font-size="{FIGURE_TYPE_SMALL}" font-weight="600" '
                'fill="#68716F">Probe length from tip (µm)</text>',
            ]
        )
    else:
        base_path = REPO_ROOT / "figure_sources" / viewer["baseImage"]["assetPath"]
        overlay_path = (
            REPO_ROOT / "figure_sources" / viewer["filterOverlay"]["assetPath"]
        )
        source_width = viewer["baseImage"]["width"]
        source_height = viewer["baseImage"]["height"]
        scale = min(visual_width / source_width, visual_height / source_height)
        rendered_width = source_width * scale
        rendered_height = source_height * scale
        image_x = visual_left + (visual_width - rendered_width) / 2
        image_y = visual_top + (visual_height - rendered_height) / 2

        def image_uri(path: Path) -> str:
            return base64.b64encode(path.read_bytes()).decode()

        svg.append(
            f'<image href="data:image/png;base64,{image_uri(base_path)}" '
            f'x="{image_x:.2f}" y="{image_y:.2f}" width="{rendered_width:.2f}" '
            f'height="{rendered_height:.2f}"/>'
        )
        represented_fill = base64.b64encode(
            represented_filter_fill_png(viewer, trace_indices)
        ).decode()
        svg.extend(
            [
                f'<image class="represented-filter-fills" '
                f'data-filter-indices="{",".join(map(str, trace_indices))}" '
                f'href="data:image/png;base64,{represented_fill}" x="{image_x:.2f}" '
                f'y="{image_y:.2f}" width="{rendered_width:.2f}" '
                f'height="{rendered_height:.2f}"/>',
                f'<image href="data:image/png;base64,{image_uri(overlay_path)}" '
                f'x="{image_x:.2f}" y="{image_y:.2f}" width="{rendered_width:.2f}" '
                f'height="{rendered_height:.2f}"/>',
            ]
        )
        scale_microns = 25 if modality == "slap2" else 50
        scale_width = scale_microns / viewer["micronsPerPixel"] * scale
        scale_x = image_x + rendered_width - scale_width - 17
        scale_y = image_y + rendered_height - 18
        svg.extend(
            [
                f'<line x1="{scale_x:.2f}" y1="{scale_y:.2f}" '
                f'x2="{scale_x + scale_width:.2f}" y2="{scale_y:.2f}" '
                'stroke="#FFFFFF" stroke-width="4"/>',
                f'<text x="{scale_x + scale_width / 2:.2f}" y="{scale_y - 8:.2f}" '
                f'text-anchor="middle" font-family="{FIGURE_SANS_FONT}" '
                f'font-size="{FIGURE_TYPE_SMALL}" font-weight="700" fill="#FFFFFF">'
                f'{scale_microns} µm</text>',
            ]
        )

    append_segmentation_trace_stack(
        svg,
        viewer,
        trace_indices,
        trace_rows,
        left=774,
        top=116,
        width=548,
        height=548,
    )
    svg.append("</svg>")
    output.parent.mkdir(parents=True, exist_ok=True)
    write_svg_output(output, svg)
    return output


def write_segmentation_viewer_static_svg(
    output: Path = SEGMENTATION_VIEWER_STATIC_OUTPUT,
    static_outputs: dict[str, Path] | None = None,
) -> Path:
    static_outputs = static_outputs or SEGMENTATION_VIEWER_STATIC_OUTPUTS
    panel_height = 760
    panels = []
    for index, (modality, panel_path) in enumerate(static_outputs.items()):
        panel_path = write_segmentation_viewer_svg(modality, panel_path)
        encoded = base64.b64encode(panel_path.read_bytes()).decode()
        panels.append(
            f'<image href="data:image/svg+xml;base64,{encoded}" x="0" '
            f'y="{index * panel_height}" width="1400" height="{panel_height}"/>'
        )
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="2280" '
        'viewBox="0 0 1400 2280" role="img" aria-labelledby="title description">',
        '<title id="title">Unit extraction across recording modalities</title>',
        '<desc id="description">Neuropixels, mesoscope, and SLAP2 panels show '
        'representative extraction filters with twenty stacked activity traces.</desc>',
        *panels,
        "</svg>",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    write_svg_output(output, svg)
    return output


def write_segmentation_viewers() -> Path:
    write_segmentation_viewer_static_svg(SEGMENTATION_VIEWER_STATIC_OUTPUT)
    return write_segmentation_viewer_html(SEGMENTATION_VIEWER_OUTPUT)


def load_publication_table_data() -> dict:
    animal_table = load_individual_animal_table()
    session_table = load_individual_session_table()
    data_access_table = load_data_access_table()
    return {
        "tables": {
            "animals": animal_table,
            "sessions": session_table,
            "dataAccess": data_access_table,
        },
        "version": 3,
    }


def load_data_access_table(
    data_path: Path = DATA_ACCESS_PATH,
    provenance_path: Path = DATA_ACCESS_PROVENANCE_PATH,
) -> dict:
    """Load the vendored Data Access Summary snapshot."""
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if not text_sha256_matches(data_path, provenance["vendored_sha256"]):
        raise RuntimeError("Data Access checksum does not match its provenance record.")
    with data_path.open(newline="", encoding="utf-8-sig") as stream:
        source_rows = list(csv.DictReader(stream))
    if not source_rows:
        raise RuntimeError("Vendored Data Access Summary is empty.")
    if len(source_rows) != provenance["rows"]:
        raise RuntimeError("Data Access row count does not match its provenance record.")

    expected_headers = [
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
    if list(source_rows[0]) != expected_headers:
        raise RuntimeError("Vendored Data Access Summary schema is not supported.")

    modality_lookup = {
        "Mesoscope": "mesoscope",
        "Neuropixels": "neuropixels",
        "SLAP2": "slap2",
    }
    column_views = {
        "neuropixels": [
            "Session ID", "Mouse ID", "Date", "Context", "Dandiset ID",
            "DANDI path", "DANDI link", "Source session S3 asset",
            "Spike-sorted S3 asset", "CCF S3 asset", "NWB S3 asset",
        ],
        "mesoscope": [
            "Session ID", "Mouse ID", "Date", "Context", "Dandiset ID",
            "DANDI path", "DANDI link", "Source session S3 asset",
            "Behavior S3 asset", "Processed S3 asset",
            "Behavior videos S3 asset", "NWB S3 asset",
        ],
        "slap2": [
            "Session ID", "Mouse ID", "Date", "Context", "Dandiset ID",
            "DANDI path", "DANDI link", "Source session S3 asset",
            "Motion-corrected S3 asset", "Annotated S3 asset",
            "Processed S3 asset", "NWB S3 asset",
        ],
    }
    rows = []
    session_ids = set()
    for source in source_rows:
        modality = modality_lookup.get(source["Modality"].strip())
        session_id = source["Session ID"].strip()
        if modality is None or not session_id:
            raise RuntimeError(f"Invalid Data Access row: {source}")
        if session_id in session_ids:
            raise RuntimeError(f"Duplicate Data Access session ID: {session_id}")
        session_ids.add(session_id)
        values = [source[header].strip() for header in expected_headers]
        rows.append(
            {
                "context": source["Context"].strip().lower(),
                "csvValues": values,
                "details": [],
                "modality": modality,
                "qc": "",
                "values": values,
            }
        )
    rows.sort(key=lambda row: (row["modality"], row["values"][2], row["values"][0]))
    return {
        "columnViews": column_views,
        "csvHeaders": expected_headers,
        "detailsColumn": None,
        "headers": expected_headers,
        "linkColumns": [
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
        ],
        "rows": rows,
        "sourceUrl": provenance["source_url"],
    }


def normalized_text_bytes(path: Path) -> bytes:
    """Read text bytes with platform-specific line endings normalized to LF."""
    data = path.read_bytes()
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def text_sha256_matches(path: Path, expected: str) -> bool:
    """Match text content regardless of Git's platform-specific line endings."""
    data = path.read_bytes()
    lf_data = normalized_text_bytes(path)
    candidates = (data, lf_data, lf_data.replace(b"\n", b"\r\n"))
    return any(hashlib.sha256(candidate).hexdigest() == expected for candidate in candidates)


def load_individual_animal_table() -> dict:
    modality_lookup = {
        "MESO": ("mesoscope", "Two-photon mesoscope"),
        "EPHYS": ("neuropixels", "Neuropixels"),
        "SLAP2": ("slap2", "SLAP2"),
    }
    provenance = json.loads(ANIMAL_RECORDS_PROVENANCE_PATH.read_text(encoding="utf-8"))
    if not text_sha256_matches(ANIMAL_RECORDS_PATH, provenance["vendored_sha256"]):
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
        details = [
            {"label": "Genotype / preparation", "value": source["Transgenic details"].strip()},
            {"label": "Virus(es)", "value": source["Virus(es)"].strip()},
            {"label": "Birth date", "value": source["Birth date"].strip()},
            {"label": "Surgery date(s)", "value": source["Surgery date(s)"].strip()},
            {"label": "Notes", "value": source["Notes"].strip()},
        ]
        details = [detail for detail in details if detail["value"]]
        csv_values = [source[header] for header in source]
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
    return {
        "csvHeaders": list(source_rows[0]),
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
    if not text_sha256_matches(data_path, provenance["vendored_sha256"]):
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


def load_neuropixels_trajectory_data(
    data_path: Path = NEUROPIXELS_TRAJECTORY_DATA_PATH,
    provenance_path: Path = NEUROPIXELS_TRAJECTORY_PROVENANCE_PATH,
) -> dict:
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    data_bytes = data_path.read_bytes()
    if provenance.get("version") != 1 or not text_sha256_matches(
        data_path, provenance.get("vendored_sha256", "")
    ):
        raise RuntimeError(
            "Neuropixels trajectory checksum does not match its provenance record."
        )
    payload = json.loads(data_bytes)
    summary = payload.get("summary", {})
    if (
        payload.get("version") != 1
        or summary.get("insertions") != provenance.get("trajectories")
        or summary.get("sourceSessions") != provenance.get("source_sessions")
        or summary.get("localizedSessions")
        != provenance.get("localized_sessions")
        or summary.get("subjects") != provenance.get("subjects")
        or summary.get("excludedSessions")
        != len(provenance.get("exclusions", []))
    ):
        raise RuntimeError("Neuropixels trajectory summary does not match provenance.")

    surface = payload.get("brainSurface", {})
    vertices = surface.get("vertices", [])
    faces = surface.get("faces", [])
    if (
        not vertices
        or not faces
        or any(len(vertex) != 3 for vertex in vertices)
        or any(
            len(face) != 3
            or min(face) < 0
            or max(face) >= len(vertices)
            for face in faces
        )
    ):
        raise RuntimeError("Neuropixels trajectory brain surface is invalid.")

    insertions = payload.get("insertions", [])
    if len(insertions) != summary["insertions"]:
        raise RuntimeError("Neuropixels trajectory insertion count changed.")
    insertion_ids = [record.get("id") for record in insertions]
    if len(insertion_ids) != len(set(insertion_ids)):
        raise RuntimeError("Neuropixels trajectory IDs are not unique.")
    probe_colors = payload.get("probeColors", {})
    if set(probe_colors) != set("ABCDEF"):
        raise RuntimeError("Neuropixels trajectory probe palette changed.")
    for record in insertions:
        points = record.get("points", [])
        areas = record.get("areas", [])
        if (
            record.get("probe") not in probe_colors
            or record.get("color") != probe_colors[record["probe"]]
            or len(points) < 2
            or any(len(point) != 3 for point in points)
            or not areas
            or any(
                area.get("endDepthUm", -1) < area.get("startDepthUm", 0)
                for area in areas
            )
        ):
            raise RuntimeError(
                f"Neuropixels trajectory record is invalid: {record.get('id')}"
            )
    return payload


def load_individual_session_table(
    data_path: Path = SESSION_RECORDS_PATH,
    provenance_path: Path = SESSION_RECORDS_PROVENANCE_PATH,
) -> dict:
    payload = load_experimental_session_records(data_path, provenance_path)
    modality_labels = {
        "mesoscope": "Two-photon mesoscope",
        "neuropixels": "Neuropixels",
        "slap2": "SLAP2",
    }
    rows = []
    for record in payload["records"]:
        session_id = record["source_session_id"].strip()
        if record["qc"].strip().casefold() != "pass" or session_id in {"", "aborted"}:
            continue
        modality = record["modality"]
        context = session_context(record)
        values = [
            session_id,
            record["mouse_id"],
            record["date"],
            modality_labels[modality],
            SESSION_CONTEXT_LABELS[context],
        ]
        rows.append(
            {
                "context": context,
                "csvValues": [record[header] for header in record],
                "details": [],
                "modality": modality,
                "qc": "pass",
                "values": values,
            }
        )
    rows.sort(key=lambda row: (row["values"][2], row["values"][0]))
    session_ids = [row["values"][0] for row in rows]
    if len(session_ids) != len(set(session_ids)):
        raise RuntimeError("Passing session records contain duplicate session IDs.")
    headers = ["Session ID", "Mouse ID", "Date", "Modality", "Context"]
    return {
        "csvHeaders": list(payload["records"][0]) if payload["records"] else [],
        "detailsColumn": None,
        "headers": headers,
        "rows": rows,
    }


SESSION_CONTEXT_COLORS = {
    "sensorimotor": SESSION_TYPE_COLORS["sensorimotor"],
    "standard oddball": SESSION_TYPE_COLORS["standard"],
    "sequence": SESSION_TYPE_COLORS["sequence"],
    "duration": SESSION_TYPE_COLORS["duration"],
    "other/pilot": "#9CA3AF",
}
SESSION_CONTEXT_LABELS = {
    "sensorimotor": "Sensorimotor",
    "standard oddball": "Standard",
    "sequence": "Sequence",
    "duration": "Duration",
    "other/pilot": "Pilot / other",
}
SESSION_QC_TAGS = (
    ("pilot session", "Pilot session"),
    ("missing running", "Missing running"),
    ("high frequency noise contamination", "High-frequency noise contamination"),
    ("z-drift", "Z-drift"),
    ("motion correction failure", "Motion correction problems"),
    ("cell matching", "Cell matching problems"),
    ("slap2 stopped early", "SLAP2 stopped early"),
    ("blood at insertion", "Blood at insertion site"),
    ("mouse stress", "Mouse stress"),
    ("mouse suspected asleep", "Mouse suspected asleep"),
    (
        "1 probe excluded for saturation events",
        "One probe excluded for saturation events",
    ),
)
SESSION_QC_TAG_NUMBERS = {
    tag: index for index, (tag, _) in enumerate(SESSION_QC_TAGS, start=1)
}
SESSION_QC_TAG_ALIASES = {
    "1 probe excluded": "1 probe excluded for saturation events",
    "cell matching failure": "cell matching",
    "motion correction": "motion correction failure",
    "mouse asleep": "mouse suspected asleep",
    "zdrift": "z-drift",
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
    if not text_sha256_matches(data_path, provenance["vendored_sha256"]):
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
    qc = record["qc"].strip().casefold()
    if qc == "fail":
        return "session-fail"
    return "ok"


def normalized_session_qc_tags(record: dict | None) -> list[str]:
    if record is None:
        return []
    tags = []
    for raw_tag in record.get("qc_tags", "").split(","):
        tag = raw_tag.strip().casefold()
        if tag in {"", "-", "?"}:
            continue
        tag = SESSION_QC_TAG_ALIASES.get(tag, tag)
        if tag not in SESSION_QC_TAG_NUMBERS:
            raise RuntimeError(f"Unsupported session QC tag: {raw_tag.strip()}")
        if tag not in tags:
            tags.append(tag)
    return tags


def session_qc_tag_numbers(
    record: dict | None,
    tag_numbers: dict[str, int] | None = None,
) -> list[int]:
    tag_numbers = tag_numbers or SESSION_QC_TAG_NUMBERS
    numbers = [
        tag_numbers[tag]
        for tag in normalized_session_qc_tags(record)
        if tag in tag_numbers
    ]
    return sorted(numbers)


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
        if sessions and all(
            session["record"] is not None
            and session["record"]["qc"].strip().casefold() == "fail"
            for session in sessions
        ):
            continue
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


def append_session_block(
    svg: list[str],
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    context: str,
    qc_kind: str,
    qc_tag_numbers: list[int] | None = None,
    element_class: str | None = None,
    overlays: list[str] | None = None,
) -> None:
    color = SESSION_CONTEXT_COLORS[context]
    class_attribute = f' class="{element_class}"' if element_class else ""
    block_inset = 1.5
    block_x = x + block_inset
    block_y = y + block_inset
    block_width = width - 2 * block_inset
    block_height = height - 2 * block_inset
    if qc_kind == "session-fail":
        svg.append(
            f'<rect{class_attribute} x="{block_x:.2f}" y="{block_y:.2f}" '
            f'width="{block_width:.2f}" height="{block_height:.2f}" fill="none" '
            f'stroke="{color}" stroke-width="2"/>'
        )
        overlay_target = overlays if overlays is not None else svg
        overlay_target.append(
            f'<rect class="session-qc-outline" data-qc-kind="{qc_kind}" '
            f'x="{block_x:.2f}" y="{block_y:.2f}" '
            f'width="{block_width:.2f}" height="{block_height:.2f}" '
            f'fill="none" stroke="{color}" stroke-width="2"/>'
        )
    elif qc_kind == "missing":
        svg.append(
            f'<rect{class_attribute} x="{block_x:.2f}" y="{block_y:.2f}" '
            f'width="{block_width:.2f}" height="{block_height:.2f}" fill="#FFFFFF" '
            'stroke="#8A9290" stroke-width="1.5" stroke-dasharray="3 2"/>'
        )
    else:
        svg.append(
            f'<rect{class_attribute} x="{block_x:.2f}" y="{block_y:.2f}" '
            f'width="{block_width:.2f}" height="{block_height:.2f}" '
            f'fill="{color}" stroke="{color}" stroke-width="2"/>'
        )
    if qc_tag_numbers:
        overlay_target = overlays if overlays is not None else svg
        label = ",".join(str(number) for number in qc_tag_numbers)
        center_x = x + width / 2
        number_fill = "#000000" if qc_kind == "session-fail" else "#FFFFFF"
        number_stroke = "#FFFFFF" if qc_kind == "session-fail" else "#000000"
        text_style = (
            'text-anchor="middle" font-family="IBM Plex Mono, monospace" '
            f'font-weight="700" fill="{number_fill}" stroke="{number_stroke}" '
            'stroke-width="1" paint-order="stroke"'
        )
        if len(qc_tag_numbers) > 3:
            first_line = ",".join(str(number) for number in qc_tag_numbers[:3])
            second_line = ",".join(str(number) for number in qc_tag_numbers[3:])
            overlay_target.append(
                f'<text class="session-qc-tags" data-qc-tags="{label}" '
                f'font-size="{FIGURE_TYPE_SMALL}" {text_style}>'
                f'<tspan x="{center_x:.2f}" y="{y + height / 2 - 1.25:.2f}">'
                f'{first_line}</tspan>'
                f'<tspan x="{center_x:.2f}" y="{y + height / 2 + 7.25:.2f}">'
                f'{second_line}</tspan></text>'
            )
        else:
            overlay_target.append(
                f'<text class="session-qc-tags" data-qc-tags="{label}" '
                f'x="{center_x:.2f}" y="{y + height / 2 + 3.6:.2f}" '
                f'font-size="{FIGURE_TYPE_SMALL}" {text_style}>{label}</text>'
            )


def write_session_inventory_svg(
    output: Path = SESSION_INVENTORY_STATIC_OUTPUT,
) -> Path:
    payload = load_experimental_session_records()
    logo_paths = load_platform_logos()
    records = payload["records"]
    panel_specs = (
        ("A", "Neuropixels", "neuropixels", 28),
        ("B", "Mesoscope", "mesoscope", 28),
        ("C", "SLAP2", "slap2", 28),
    )
    width = 1150
    height = 680
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
    active_qc_tags = {
        tag
        for rows in panel_rows.values()
        for row in rows
        for session in row["sessions"]
        for tag in normalized_session_qc_tags(session["record"])
    }
    displayed_qc_tags = tuple(
        tag_record for tag_record in SESSION_QC_TAGS if tag_record[0] in active_qc_tags
    )
    displayed_qc_tag_numbers = {
        tag: index for index, (tag, _) in enumerate(displayed_qc_tags, start=1)
    }
    has_missing_sessions = any(
        session["record"] is None
        for rows in panel_rows.values()
        for row in rows
        for session in row["sessions"]
    )
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
    ]

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
                f'<text class="platform-title modality-title" '
                f'x="{title_x + 86:.2f}" y="47" '
                'font-family="Source Sans 3, sans-serif" '
                f'font-size="{FIGURE_TYPE_SCALE["modality"]}" font-weight="700" '
                f'fill="#293133">{panel_title}</text>',
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
                y += row_step
                previous_cohort = row["cohort"]
            y_positions.append(y)
            svg.append(
                f'<text class="mouse-id" data-modality="{modality}" '
                f'x="{panel_left + chart_offset - 12}" y="{y + 4:.2f}" '
                'font-family="IBM Plex Mono, monospace" font-size="12" '
                f'text-anchor="end" fill="#4D5553">{escape(row["mouseId"])}</text>'
            )
            session_overlays = []
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
                    qc_tag_numbers=session_qc_tag_numbers(
                        record, displayed_qc_tag_numbers
                    ),
                    element_class="session-block",
                    overlays=session_overlays,
                )
            svg.extend(session_overlays)
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
                        f'font-family="IBM Plex Mono, monospace" font-size="{FIGURE_TYPE_SMALL}" '
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
            'transform="translate(310 421)" '
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
    svg.extend(
        [
            '<text x="0" y="55" font-family="Source Sans 3, sans-serif" '
            'font-size="13" font-weight="700" fill="#4D5553">Quality control</text>',
            '<rect x="120" y="42" width="24" height="16" fill="none" '
            'stroke="#69716F" stroke-width="2"/>',
            '<text x="152" y="55" font-family="Source Sans 3, sans-serif" '
            'font-size="12" fill="#68706E">Failed session (type-colored border)</text>',
            '<text x="0" y="86" font-family="Source Sans 3, sans-serif" '
            'font-size="13" font-weight="700" fill="#4D5553">QC tags</text>',
        ]
    )
    if has_missing_sessions:
        svg.extend(
            [
                '<rect x="300" y="42" width="24" height="16" fill="#FFFFFF" '
                'stroke="#8A9290" stroke-width="1.5" stroke-dasharray="3 2"/>',
                '<text x="332" y="55" font-family="Source Sans 3, sans-serif" '
                'font-size="12" fill="#68706E">Missing expected session</text>',
            ]
        )
    legend_columns = (120, 322, 524)
    for index, (_, label) in enumerate(displayed_qc_tags, start=1):
        column = (index - 1) % len(legend_columns)
        row = (index - 1) // len(legend_columns)
        x = legend_columns[column]
        y = 73 + row * 22
        svg.extend(
            [
                f'<text x="{x + 9}" y="{y + 10}" text-anchor="middle" '
                f'font-family="IBM Plex Mono, monospace" font-size="{FIGURE_TYPE_SMALL}" '
                f'font-weight="700" fill="#293133">{index}</text>',
                f'<text x="{x + 22}" y="{y + 11}" '
                'font-family="Source Sans 3, sans-serif" '
                f'font-size="12" fill="#68706E">{label}</text>',
            ]
        )
    svg.extend(
        [
            "</g>",
            "</svg>",
        ]
    )
    svg = [
        re.sub(
            r'(<text\b(?![^>]*class="session-qc-tags")[^>]*\bfill=")#[0-9A-Fa-f]{6}(")',
            r"\g<1>#000000\g<2>",
            element,
        )
        for element in svg
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    write_svg_output(output, svg)
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
        f'<text x="40" y="52" font-family="{FIGURE_SANS_FONT}" font-size="28" '
        'font-weight="600" fill="#172126">Shared structure of the four predictive-processing '
        "sessions</text>",
    ]

    for session_index, session in enumerate(SESSIONS):
        y = top + session_index * row_height
        svg.append(
            f'<text x="40" y="{y + 18}" font-family="{FIGURE_SANS_FONT}" '
            f'font-size="17" font-weight="600" fill="#172126">Session {session.number}</text>'
        )
        svg.append(
            f'<text x="40" y="{y + 39}" font-family="{FIGURE_SANS_FONT}" '
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
                    f'font-family="{FIGURE_SANS_FONT}" font-size="{FIGURE_TYPE_SMALL}" '
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
                f'font-family="{FIGURE_SANS_FONT}" font-size="12" '
                f'text-anchor="middle" fill="#49565C">{minute} min</text>',
            ]
        )
    svg.append("</svg>")
    write_svg_output(output, svg)
    return output


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
    y_max = 140

    def x_position(day: int) -> float:
        if min_day == max_day:
            return left + plot_width / 2
        return left + (day - min_day) / (max_day - min_day) * plot_width

    def y_position(value: float) -> float:
        return top + plot_height - value / y_max * plot_height

    mouse_ids = sorted({record["mouse_id"] for record in records})
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

    for value in range(0, y_max + 1, 20):
        y = y_position(value)
        svg.extend(
            [
                f'<line x1="{left - 7}" y1="{y:.2f}" x2="{left}" y2="{y:.2f}" '
                'stroke="#69716F" stroke-width="1.5"/>',
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

    for mouse_records in records_by_mouse.values():
        points = " ".join(
            f'{x_position(record["day"]):.2f},{y_position(record["percentOfDay1"]):.2f}'
            for record in mouse_records
        )
        svg.append(
            f'<polyline points="{points}" fill="none" stroke="#9AA29F" '
            'stroke-width="1.5" stroke-opacity="0.62"/>'
        )
        for record in mouse_records:
            svg.append(
                f'<circle cx="{x_position(record["day"]):.2f}" '
                f'cy="{y_position(record["percentOfDay1"]):.2f}" r="4" '
                'fill="#9AA29F" fill-opacity="0.72"/>'
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
            '<line x1="1055" y1="43" x2="1093" y2="43" stroke="#9AA29F" '
            'stroke-width="1.5" stroke-opacity="0.72"/>',
            '<circle cx="1074" cy="43" r="4" fill="#9AA29F"/>',
            '<text x="1102" y="48" font-family="Source Sans 3, sans-serif" '
            'font-size="14" fill="#303536">Mouse</text>',
            "</svg>",
        ]
    )
    write_svg_output(output, svg)
    return output

CCF_STATIC_SURFACE_OPACITY = 0.12
_CCF_SURFACE_RENDER_CACHE: dict[tuple[str, str, int, int, float], bytes] = {}


def vector_dot(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
) -> float:
    return sum(left * right for left, right in zip(first, second, strict=True))


def vector_cross(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def normalized_vector(
    vector: tuple[float, float, float],
) -> tuple[float, float, float]:
    length = math.sqrt(vector_dot(vector, vector))
    if length == 0:
        raise RuntimeError("Cannot normalize a zero-length vector.")
    return tuple(component / length for component in vector)


def ccf_static_view_axes(
    view: str,
) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
]:
    if view == "dorsal":
        return (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)
    if view != "oblique":
        raise RuntimeError(f"Unsupported static CCF view: {view}")
    toward_camera = normalized_vector((11_200.0, 7_300.0, 11_600.0))
    right = normalized_vector(vector_cross((0.0, 1.0, 0.0), toward_camera))
    up = normalized_vector(vector_cross(toward_camera, right))
    return right, up, toward_camera


def ccf_static_projection(
    point: tuple[float, float, float],
    view: str,
) -> tuple[float, float, float]:
    right, up, toward_camera = ccf_static_view_axes(view)
    return (
        vector_dot(point, right),
        vector_dot(point, up),
        vector_dot(point, toward_camera),
    )


def render_ccf_surface_png(
    surface: dict,
    world_vertices: list[tuple[float, float, float]],
    projected_vertices: list[tuple[float, float, float]],
    transform,
    view: str,
    width: int,
    height: int,
    surface_digest: str,
) -> bytes:
    cache_key = (surface_digest, view, width, height, CCF_STATIC_SURFACE_OPACITY)
    cached = _CCF_SURFACE_RENDER_CACHE.get(cache_key)
    if cached is not None:
        return cached

    pixels = bytearray((0, 0, 0, 0) * (width * height))
    z_buffer = [-math.inf] * (width * height)
    screen_vertices = [
        (*transform((horizontal, vertical)), depth)
        for horizontal, vertical, depth in projected_vertices
    ]
    minimum_depth = min(point[2] for point in projected_vertices)
    depth_range = max(point[2] for point in projected_vertices) - minimum_depth
    light = normalized_vector((0.4, 0.82, 0.4))
    _, _, toward_camera = ccf_static_view_axes(view)

    normal_sums = [[0.0, 0.0, 0.0] for _ in world_vertices]
    for first_index, second_index, third_index in surface["faces"]:
        first_world = world_vertices[first_index]
        second_world = world_vertices[second_index]
        third_world = world_vertices[third_index]
        first_edge = tuple(
            second_world[index] - first_world[index] for index in range(3)
        )
        second_edge = tuple(
            third_world[index] - first_world[index] for index in range(3)
        )
        face_normal = vector_cross(first_edge, second_edge)
        for vertex_index in (first_index, second_index, third_index):
            for component in range(3):
                normal_sums[vertex_index][component] += face_normal[component]

    vertex_shades = []
    for normal_sum, projected in zip(
        normal_sums,
        projected_vertices,
        strict=True,
    ):
        normal_length = math.sqrt(sum(component**2 for component in normal_sum))
        normal = (
            tuple(component / normal_length for component in normal_sum)
            if normal_length
            else toward_camera
        )
        facing = abs(vector_dot(normal, toward_camera))
        lambert = abs(vector_dot(normal, light))
        depth_fraction = (projected[2] - minimum_depth) / depth_range
        vertex_shades.append(
            0.68 + 0.2 * lambert + 0.08 * facing + 0.08 * depth_fraction
        )

    for first_index, second_index, third_index in surface["faces"]:
        first = screen_vertices[first_index]
        second = screen_vertices[second_index]
        third = screen_vertices[third_index]
        denominator = (second[1] - third[1]) * (first[0] - third[0]) + (
            third[0] - second[0]
        ) * (first[1] - third[1])
        if abs(denominator) < 1e-6:
            continue
        minimum_x = max(0, math.floor(min(first[0], second[0], third[0])))
        maximum_x = min(width - 1, math.ceil(max(first[0], second[0], third[0])))
        minimum_y = max(0, math.floor(min(first[1], second[1], third[1])))
        maximum_y = min(height - 1, math.ceil(max(first[1], second[1], third[1])))
        if minimum_x > maximum_x or minimum_y > maximum_y:
            continue

        for pixel_y in range(minimum_y, maximum_y + 1):
            vertical = pixel_y + 0.5
            for pixel_x in range(minimum_x, maximum_x + 1):
                horizontal = pixel_x + 0.5
                first_weight = (
                    (second[1] - third[1]) * (horizontal - third[0])
                    + (third[0] - second[0]) * (vertical - third[1])
                ) / denominator
                second_weight = (
                    (third[1] - first[1]) * (horizontal - third[0])
                    + (first[0] - third[0]) * (vertical - third[1])
                ) / denominator
                third_weight = 1 - first_weight - second_weight
                if min(first_weight, second_weight, third_weight) < -1e-6:
                    continue
                depth = (
                    first_weight * first[2]
                    + second_weight * second[2]
                    + third_weight * third[2]
                )
                pixel_index = pixel_y * width + pixel_x
                if depth <= z_buffer[pixel_index]:
                    continue
                z_buffer[pixel_index] = depth
                shade = (
                    first_weight * vertex_shades[first_index]
                    + second_weight * vertex_shades[second_index]
                    + third_weight * vertex_shades[third_index]
                )
                brain_color = tuple(
                    min(255, round(component * shade))
                    for component in (174, 197, 188)
                )
                color = (*brain_color, round(CCF_STATIC_SURFACE_OPACITY * 255))
                offset = pixel_index * 4
                pixels[offset : offset + 4] = bytes(color)

    outlined = bytearray(pixels)
    outline_color = (103, 124, 117, 171)
    for pixel_y in range(1, height - 1):
        for pixel_x in range(1, width - 1):
            pixel_index = pixel_y * width + pixel_x
            depth = z_buffer[pixel_index]
            if not math.isfinite(depth):
                continue
            neighbors = (
                z_buffer[pixel_index - 1],
                z_buffer[pixel_index + 1],
                z_buffer[pixel_index - width],
                z_buffer[pixel_index + width],
            )
            if any(not math.isfinite(neighbor) for neighbor in neighbors) or any(
                abs(depth - neighbor) > 450 for neighbor in neighbors
            ):
                offset = pixel_index * 4
                outlined[offset : offset + 4] = bytes(outline_color)

    encoded = encode_rgba_png(width, height, bytes(outlined))
    _CCF_SURFACE_RENDER_CACHE[cache_key] = encoded
    return encoded

def write_neuropixels_trajectory_svg(
    output: Path = NEUROPIXELS_TRAJECTORY_STATIC_OUTPUT,
    data_path: Path = NEUROPIXELS_TRAJECTORY_DATA_PATH,
    provenance_path: Path = NEUROPIXELS_TRAJECTORY_PROVENANCE_PATH,
) -> Path:
    payload = load_neuropixels_trajectory_data(data_path, provenance_path)
    surface = payload["brainSurface"]
    shape = surface["annotationShape"]
    center = (shape[0] * 12.5, shape[1] * 12.5, shape[2] * 12.5)
    panels = {
        "oblique": (50.0, 100.0, 975.0, 710.0),
        "dorsal": (1060.0, 100.0, 490.0, 710.0),
    }

    def atlas_coordinates(point: list[int]) -> tuple[float, float, float]:
        anterior_posterior, dorsal_ventral, medial_lateral = point
        return (
            center[2] - medial_lateral,
            center[1] - dorsal_ventral,
            center[0] - anterior_posterior,
        )

    world_vertices = [atlas_coordinates(point) for point in surface["vertices"]]

    def panel_transform(view: str):
        left, top, width, height = panels[view]
        projected = [ccf_static_projection(point, view) for point in world_vertices]
        minimum_x = min(point[0] for point in projected)
        maximum_x = max(point[0] for point in projected)
        minimum_y = min(point[1] for point in projected)
        maximum_y = max(point[1] for point in projected)
        scale = min(
            (width - 36) / (maximum_x - minimum_x),
            (height - 46) / (maximum_y - minimum_y),
        )
        content_width = (maximum_x - minimum_x) * scale
        content_height = (maximum_y - minimum_y) * scale
        offset_x = left + (width - content_width) / 2
        offset_y = top + (height - content_height) / 2

        def local_transform(point: tuple[float, float]) -> tuple[float, float]:
            return (
                offset_x - left + (point[0] - minimum_x) * scale,
                offset_y - top + content_height - (point[1] - minimum_y) * scale,
            )

        def transform(point: tuple[float, float]) -> tuple[float, float]:
            horizontal, vertical = local_transform(point)
            return left + horizontal, top + vertical

        return projected, local_transform, transform, scale

    transforms = {}
    scales = {}
    brain_images = {}
    surface_digest = hashlib.sha256(
        json.dumps(surface, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    for view in panels:
        projected, local_transform, transform, scale = panel_transform(view)
        transforms[view] = transform
        scales[view] = scale
        _, _, width, height = panels[view]
        rendered = render_ccf_surface_png(
            surface,
            world_vertices,
            projected,
            local_transform,
            view,
            int(width),
            int(height),
            surface_digest,
        )
        brain_images[view] = base64.b64encode(rendered).decode()

    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" '
        'viewBox="0 0 1600 900" role="img" aria-labelledby="title description">',
        '<title id="title">All localized Neuropixels insertions in the Allen CCF</title>',
        '<desc id="description">Oblique and dorsal projections show all localized '
        'Neuropixels insertions over semi-transparent, depth-shaded projections of the '
        'Allen CCF whole-brain surface. Line color denotes probe A through F; each panel '
        'includes a 2 millimeter scale bar and anatomical direction marker.</desc>',
        '<defs><marker id="ccf-arrow" markerWidth="6" markerHeight="6" refX="5" '
        'refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#41504C"/>'
        '</marker></defs>',
        '<rect width="1600" height="900" fill="#FFFFFF"/>',
        f'<image class="ccf-brain-render" data-surface-opacity="'
        f'{CCF_STATIC_SURFACE_OPACITY}" href="data:image/png;base64,'
        f'{brain_images["oblique"]}" x="50" y="100" width="975" height="710"/>',
        f'<image class="ccf-brain-render" data-surface-opacity="'
        f'{CCF_STATIC_SURFACE_OPACITY}" href="data:image/png;base64,'
        f'{brain_images["dorsal"]}" x="1060" y="100" width="490" height="710"/>',
    ]

    for view in panels:
        transform = transforms[view]
        for record in payload["insertions"]:
            points = [
                transform(ccf_static_projection(atlas_coordinates(point), view)[:2])
                for point in record["points"]
            ]
            polyline = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
            svg.append(
                f'<polyline points="{polyline}" fill="none" '
                f'stroke="{record["color"]}" stroke-width="2.2" '
                'stroke-opacity="0.32" stroke-linecap="round"/>'
            )

    for view, (left, top, width, height) in panels.items():
        scale_length = 2_000 * scales[view]
        scale_x = left + 28
        scale_y = top + height - 28
        svg.extend(
            [
                f'<rect x="{scale_x - 10:.2f}" y="{scale_y - 28:.2f}" '
                f'width="{scale_length + 20:.2f}" height="42" rx="3" '
                'fill="#FFFFFF" fill-opacity="0.88"/>',
                f'<line class="ccf-scale-bar" x1="{scale_x:.2f}" y1="{scale_y:.2f}" '
                f'x2="{scale_x + scale_length:.2f}" y2="{scale_y:.2f}" '
                'stroke="#293133" stroke-width="4"/>',
                f'<line x1="{scale_x:.2f}" y1="{scale_y - 5:.2f}" '
                f'x2="{scale_x:.2f}" y2="{scale_y + 5:.2f}" '
                'stroke="#293133" stroke-width="2"/>',
                f'<line x1="{scale_x + scale_length:.2f}" y1="{scale_y - 5:.2f}" '
                f'x2="{scale_x + scale_length:.2f}" y2="{scale_y + 5:.2f}" '
                'stroke="#293133" stroke-width="2"/>',
                f'<text x="{scale_x + scale_length / 2:.2f}" y="{scale_y - 10:.2f}" '
                'text-anchor="middle" font-family="Source Sans 3, sans-serif" '
                'font-size="14" font-weight="700" fill="#293133">2 mm</text>',
            ]
        )

        origin_x = left + width - 68
        origin_y = top + 68
        for label, axis in (
            ("L", (1.0, 0.0, 0.0)),
            ("D", (0.0, 1.0, 0.0)),
            ("A", (0.0, 0.0, 1.0)),
        ):
            horizontal, vertical, _ = ccf_static_projection(axis, view)
            screen_horizontal = horizontal
            screen_vertical = -vertical
            length = math.hypot(screen_horizontal, screen_vertical)
            if length < 0.1:
                continue
            end_x = origin_x + 31 * screen_horizontal / length
            end_y = origin_y + 31 * screen_vertical / length
            label_x = origin_x + 41 * screen_horizontal / length
            label_y = origin_y + 41 * screen_vertical / length + 4
            svg.extend(
                [
                    f'<line class="ccf-orientation-axis" x1="{origin_x:.2f}" '
                    f'y1="{origin_y:.2f}" x2="{end_x:.2f}" y2="{end_y:.2f}" '
                    'stroke="#41504C" stroke-width="2" marker-end="url(#ccf-arrow)"/>',
                    f'<text x="{label_x:.2f}" y="{label_y:.2f}" text-anchor="middle" '
                    'font-family="Source Sans 3, sans-serif" font-size="13" '
                    f'font-weight="700" fill="#293133">{label}</text>',
                ]
            )
        svg.append(
            f'<circle cx="{origin_x:.2f}" cy="{origin_y:.2f}" r="3" fill="#41504C"/>'
        )

    svg.extend(
        [
            '<text x="74" y="77" font-family="Source Sans 3, sans-serif" '
            'font-size="24" font-weight="700" fill="#293133">A</text>',
            '<text x="1084" y="77" font-family="Source Sans 3, sans-serif" '
            'font-size="24" font-weight="700" fill="#293133">B</text>',
        ]
    )
    legend_x = 620
    svg.append(
        '<text class="probe-legend-title" x="555" y="851" text-anchor="end" '
        'font-family="Source Sans 3, sans-serif" font-size="14" '
        'font-weight="700" fill="#293133">Probe:</text>'
    )
    for index, probe in enumerate("ABCDEF"):
        x = legend_x + index * 78
        color = payload["probeColors"][probe]
        svg.extend(
            [
                f'<line x1="{x}" y1="846" x2="{x + 25}" y2="846" '
                f'stroke="{color}" stroke-width="5"/>',
                f'<text class="probe-legend-label" x="{x + 32}" y="851" '
                'font-family="Source Sans 3, sans-serif" font-size="13" '
                f'fill="#414A48">{probe}</text>',
            ]
        )
    svg.append("</svg>")
    output.parent.mkdir(parents=True, exist_ok=True)
    write_svg_output(output, svg)
    return output


def main() -> None:
    merged_figure_1_path = write_merged_figure_1_svg()
    figure_1_panel_c_path = write_figure_1_panel_c_svg()
    hardware_path = write_hardware_figure_svg()
    unit_extraction_plan_path = write_unit_extraction_plan_svg()
    basic_stimuli_plan_path = write_basic_stimuli_plan_svg()
    standard_oddball_plan_path = write_standard_oddball_plan_svg()
    html_path = write_interactive_html()
    data_explorer_path = write_data_explorer_html()
    literature_comparison_path = write_literature_comparison_html()
    behavior_viewer_path = write_behavior_viewer_html()
    eye_tracking_viewer_path = write_eye_tracking_viewer_html()
    neural_viewer_path = write_neural_viewer_html()
    segmentation_viewer_path = write_segmentation_viewers()
    unit_yield_html_path = write_unit_yield_html()
    trajectory_html_path = write_neuropixels_trajectory_html()
    optotagging_source_path = write_optotagging_static_source()
    optotagging_html_path = write_optotagging_heatmap_html()
    optotagging_svg_path = OPTOTAGGING_HEATMAP_STATIC_OUTPUT
    svg_path = write_static_svg()
    unit_yield_svg_path = write_unit_yield_svg()
    print(f"Wrote {merged_figure_1_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {figure_1_panel_c_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {hardware_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {unit_extraction_plan_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {basic_stimuli_plan_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {standard_oddball_plan_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {CONTEXT_CONTROLS_STATIC_OUTPUT.relative_to(REPO_ROOT)}")
    print(f"Wrote {html_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {data_explorer_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {SESSION_INVENTORY_STATIC_OUTPUT.relative_to(REPO_ROOT)}")
    print(f"Wrote {literature_comparison_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {behavior_viewer_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {BEHAVIOR_STATIC_OUTPUT.relative_to(REPO_ROOT)}")
    print(f"Wrote {eye_tracking_viewer_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {neural_viewer_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {NEURAL_STATIC_OUTPUT.relative_to(REPO_ROOT)}")
    print(f"Wrote {segmentation_viewer_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {SEGMENTATION_VIEWER_STATIC_OUTPUT.relative_to(REPO_ROOT)}")
    print(f"Wrote {unit_yield_html_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {trajectory_html_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {NEUROPIXELS_TRAJECTORY_STATIC_OUTPUT.relative_to(REPO_ROOT)}")
    print(f"Wrote {optotagging_source_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {optotagging_html_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {optotagging_svg_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {svg_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {unit_yield_svg_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
