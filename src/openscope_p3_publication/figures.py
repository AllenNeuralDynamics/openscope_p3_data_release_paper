from __future__ import annotations

import base64
import csv
import datetime as dt
import hashlib
import json
import math
import re
import shutil
import xml.etree.ElementTree as ET
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
INTERACTIVE_OUTPUT = REPO_ROOT / "interactive" / "experimental-design.html"
DATA_EXPLORER_OUTPUT = REPO_ROOT / "interactive" / "data-explorer.html"
LITERATURE_COMPARISON_OUTPUT = REPO_ROOT / "interactive" / "literature-comparison.html"
BEHAVIOR_VIEWER_OUTPUT = REPO_ROOT / "interactive" / "behavior-viewer.html"
BEHAVIOR_EXCERPTS_PATH = DATA_DIR / "behavior-excerpts.json"
NEURAL_VIEWER_OUTPUT = REPO_ROOT / "interactive" / "neural-viewer.html"
NEURAL_EXCERPTS_PATH = DATA_DIR / "raw-neural-excerpts.json"
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
NEURAL_MEDIA_DIR = MEDIA_DIR / "neural-viewer"
ZEBRA_MOVIE_SOURCE = MEDIA_DIR / "zebra-stimulus-excerpt.m4v"
ZEBRA_POSTER_SOURCE = MEDIA_DIR / "zebra-stimulus-poster.png"
ZEBRA_PROVENANCE_PATH = MEDIA_DIR / "zebra-stimulus-excerpt.provenance.json"


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
    html = (
        template.replace("__SIMULATOR_CSS__", stylesheet)
        .replace(
            "__SIMULATOR_DATA__",
            json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
        )
        .replace("__SIMULATOR_JS__", javascript)
        .replace("__EMBED_AUTO_HEIGHT_JS__", load_embed_auto_height())
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
    return payload


def write_behavior_viewer_html(output: Path = BEHAVIOR_VIEWER_OUTPUT) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = load_behavior_excerpts()
    template = (JAVASCRIPT_DIR / "behavior-viewer.html").read_text(encoding="utf-8")
    stylesheet = (JAVASCRIPT_DIR / "behavior-viewer.css").read_text(encoding="utf-8")
    javascript = (JAVASCRIPT_DIR / "behavior-viewer.js").read_text(encoding="utf-8")
    html = (
        template.replace("__BEHAVIOR_CSS__", stylesheet)
        .replace(
            "__BEHAVIOR_DATA__",
            json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
        )
        .replace("__BEHAVIOR_JS__", javascript)
        .replace("__EMBED_AUTO_HEIGHT_JS__", load_embed_auto_height())
    )
    output.write_text(html, encoding="utf-8")
    return output


def load_neural_excerpts(
    path: Path = NEURAL_EXCERPTS_PATH,
    behavior_path: Path = BEHAVIOR_EXCERPTS_PATH,
) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    behavior_checksum = hashlib.sha256(behavior_path.read_bytes()).hexdigest()
    if (
        payload.get("version") != 6
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
                ):
                    raise RuntimeError(
                        f"Neural movie asset is invalid: {session['id']}/{option['id']}"
                    )
    return payload


def write_neural_viewer_html(output: Path = NEURAL_VIEWER_OUTPUT) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = load_neural_excerpts()
    template = (JAVASCRIPT_DIR / "neural-viewer.html").read_text(encoding="utf-8")
    stylesheet = (JAVASCRIPT_DIR / "neural-viewer.css").read_text(encoding="utf-8")
    javascript = (JAVASCRIPT_DIR / "neural-viewer.js").read_text(encoding="utf-8")
    html = (
        template.replace("__NEURAL_CSS__", stylesheet)
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
    html_path = write_interactive_html()
    data_explorer_path = write_data_explorer_html()
    literature_comparison_path = write_literature_comparison_html()
    behavior_viewer_path = write_behavior_viewer_html()
    neural_viewer_path = write_neural_viewer_html()
    unit_yield_html_path = write_unit_yield_html()
    svg_path = write_static_svg()
    unit_yield_svg_path = write_unit_yield_svg()
    print(f"Wrote {html_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {data_explorer_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {literature_comparison_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {behavior_viewer_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {neural_viewer_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {unit_yield_html_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {svg_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {unit_yield_svg_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()