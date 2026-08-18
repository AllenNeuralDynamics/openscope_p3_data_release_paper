from __future__ import annotations

import base64
import gzip
import hashlib
import json
import math
import shutil
import sys
from array import array
from collections import Counter
from html import escape
from pathlib import Path

from .figures import (
    FIGURE_SANS_FONT,
    FIGURE_TYPE_SCALE,
    JAVASCRIPT_DIR,
    REPO_ROOT,
    encode_rgb_png,
    load_embed_auto_height,
    load_figure_stylesheet,
    normalized_text_bytes,
    optotagging_heatmap_color,
    write_svg_output,
)
from .neural_responses import (
    BIN_SECONDS,
    NEURAL_SESSIONS,
    QC_THRESHOLDS,
    SMOOTHING_SIGMA_SECONDS,
    WINDOW_END_SECONDS,
    WINDOW_START_SECONDS,
    smooth_trace,
)

DATA_PATH = REPO_ROOT / "figure_sources" / "data" / "neuropixels-event-responses.json"
PROVENANCE_PATH = DATA_PATH.with_suffix(".provenance.json")
SOURCE_MEDIA_DIR = (
    REPO_ROOT / "figure_sources" / "media" / "neuropixels-event-responses"
)
INTERACTIVE_MEDIA_DIR = (
    REPO_ROOT / "interactive" / "media" / "neuropixels-event-responses"
)
INTERACTIVE_OUTPUT = REPO_ROOT / "interactive" / "neuropixels-event-responses.html"
STATIC_OUTPUT = (
    REPO_ROOT
    / "images"
    / "figures"
    / "generated"
    / "supplementary-neuropixels-event-responses.svg"
)
CONTEXT_ORDER = ("standard", "sensorimotor", "sequence", "duration")
CONTEXT_LABELS = {
    "standard": "Standard oddball",
    "sensorimotor": "Sensorimotor",
    "sequence": "Sequence",
    "duration": "Duration",
}
DEFAULT_EVENTS = {
    "standard": "orientation_90",
    "sensorimotor": "motor_halt",
    "sequence": "orientation_90",
    "duration": "delay_1000",
}


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_path(record: dict) -> Path:
    path = REPO_ROOT / record["path"]
    if not path.is_file():
        raise RuntimeError(f"Neural-response source is missing: {record['path']}")
    return path


def float32_values(encoded: str) -> array:
    values = array("f")
    values.frombytes(base64.b64decode(encoded))
    if sys.byteorder != "little":
        values.byteswap()
    return values


def uint16_values(path: Path) -> array:
    values = array("H")
    values.frombytes(gzip.decompress(path.read_bytes()))
    if sys.byteorder != "little":
        values.byteswap()
    return values


def load_neuropixels_event_responses(
    data_path: Path = DATA_PATH,
    provenance_path: Path = PROVENANCE_PATH,
) -> dict:
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if payload.get("version") != 1 or provenance.get("version") != 1:
        raise RuntimeError("Neuropixels event-response snapshot version is unsupported.")
    if file_sha256(data_path) != provenance.get("outputSha256"):
        raise RuntimeError("Neuropixels event-response checksum does not match provenance.")
    for key in ("module", "pupilEventModule", "script"):
        record = provenance[key]
        if file_sha256(source_path(record)) != record["sha256"]:
            raise RuntimeError(f"Neuropixels event-response {key} checksum changed.")
    parameters = payload.get("analysisParameters", {})
    if (
        parameters.get("binSeconds") != BIN_SECONDS
        or parameters.get("windowSeconds")
        != [WINDOW_START_SECONDS, WINDOW_END_SECONDS]
        or parameters.get("smoothingSigmaSeconds") != SMOOTHING_SIGMA_SECONDS
        or parameters.get("qcThresholds") != QC_THRESHOLDS
        or len(parameters.get("timeBinCentersSeconds", [])) != 150
    ):
        raise RuntimeError("Neuropixels event-response parameters are invalid.")
    if payload.get("subject") != "830846" or len(payload.get("sessions", [])) != 4:
        raise RuntimeError("Neuropixels event-response session coverage is invalid.")
    if payload.get("sessionOrder") != list(CONTEXT_ORDER):
        raise RuntimeError("Neuropixels event-response context order is invalid.")

    expected_sessions = {session.session_id: session for session in NEURAL_SESSIONS}
    total_units = 0
    total_qc = 0
    referenced_media = set()
    for session in payload["sessions"]:
        configured = expected_sessions.get(session["sessionId"])
        if configured is None or configured.context != session["context"]:
            raise RuntimeError("Neuropixels event-response session identity is invalid.")
        if session["asset"]["assetId"] != configured.asset_id:
            raise RuntimeError("Neuropixels event-response asset ID changed.")
        unit_count = session["unitCount"]
        if unit_count != len(session["units"]) or unit_count < 2_500:
            raise RuntimeError("Neuropixels event-response unit inventory is invalid.")
        if len(session["events"]) != 4:
            raise RuntimeError("Neuropixels event-response event coverage is invalid.")
        total_units += unit_count
        total_qc += sum(unit["qcPass"] for unit in session["units"])
        for key in ("countAtlas", "waveformAtlas"):
            descriptor = session[key]
            path = SOURCE_MEDIA_DIR / Path(descriptor["path"]).name
            if (
                not path.is_file()
                or file_sha256(path) != descriptor["sha256"]
                or path.stat().st_size != descriptor["size"]
            ):
                raise RuntimeError(f"Neuropixels event-response {key} is invalid.")
            referenced_media.add(path.name)
        count_shape = session["countAtlas"]["shape"]
        waveform_shape = session["waveformAtlas"]["shape"]
        if count_shape != [4, 2, unit_count, 150]:
            raise RuntimeError("Neuropixels count-atlas shape is invalid.")
        if waveform_shape[0] != unit_count or waveform_shape[1] != 210:
            raise RuntimeError("Neuropixels waveform-atlas shape is invalid.")
        finite_scales = [
            unit["waveformScaleUv"]
            for unit in session["units"]
            if unit["waveformScaleUv"] is not None
            and math.isfinite(unit["waveformScaleUv"])
        ]
        if not finite_scales or sorted(finite_scales)[len(finite_scales) // 2] > 10_000:
            raise RuntimeError("Neuropixels waveform microvolt scale is invalid.")
        expected_float_count = 4 * unit_count
        for field in (
            "baselineMeanHzBase64",
            "baselineStdHzBase64",
            "responseContextHzBase64",
            "responseControlHzBase64",
            "responseDeltaHzBase64",
        ):
            if len(float32_values(session[field])) != expected_float_count:
                raise RuntimeError(f"Neuropixels numeric field {field} is invalid.")
    if total_units != provenance.get("totalUnits") or total_qc != provenance.get(
        "totalQcUnits"
    ):
        raise RuntimeError("Neuropixels event-response totals do not match provenance.")
    if referenced_media != {Path(record["path"]).name for record in provenance["media"]}:
        raise RuntimeError("Neuropixels event-response media manifest is inconsistent.")
    return payload


def copy_neuropixels_event_media(payload: dict) -> None:
    INTERACTIVE_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    expected = set()
    for session in payload["sessions"]:
        for key in ("countAtlas", "waveformAtlas"):
            name = Path(session[key]["path"]).name
            source = SOURCE_MEDIA_DIR / name
            target = INTERACTIVE_MEDIA_DIR / name
            shutil.copy2(source, target)
            expected.add(name)
    for path in INTERACTIVE_MEDIA_DIR.glob("*"):
        if path.is_file() and path.name not in expected:
            path.unlink()


def presentation_payload(payload: dict) -> dict:
    copy_neuropixels_event_media(payload)
    result = json.loads(json.dumps(payload, allow_nan=False))
    for session in result["sessions"]:
        for key in ("countAtlas", "waveformAtlas"):
            name = Path(session[key]["path"]).name
            session[key]["path"] = f"./media/neuropixels-event-responses/{name}"
    return result


def write_neuropixels_event_html(
    output: Path = INTERACTIVE_OUTPUT,
    static_output: Path = STATIC_OUTPUT,
) -> Path:
    payload = load_neuropixels_event_responses()
    if not static_output.is_file():
        write_neuropixels_event_svg(static_output, payload)
    static_data = base64.b64encode(normalized_text_bytes(static_output)).decode()
    template = (JAVASCRIPT_DIR / "neuropixels-event-responses.html").read_text(
        encoding="utf-8"
    )
    stylesheet = load_figure_stylesheet("neuropixels-event-responses.css")
    javascript = (JAVASCRIPT_DIR / "neuropixels-event-responses.js").read_text(
        encoding="utf-8"
    )
    html = (
        template.replace("__NEUROPIXELS_EVENT_CSS__", stylesheet)
        .replace(
            "__NEUROPIXELS_EVENT_DATA__",
            json.dumps(
                presentation_payload(payload),
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
        .replace(
            "__NEUROPIXELS_EVENT_STATIC_IMAGE__",
            f"data:image/svg+xml;base64,{static_data}",
        )
        .replace("__NEUROPIXELS_EVENT_JS__", javascript)
        .replace("__EMBED_AUTO_HEIGHT_JS__", load_embed_auto_height())
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8", newline="\n")
    return output


def count_index(
    event_index: int,
    condition_index: int,
    unit_index: int,
    bin_index: int,
    unit_count: int,
    bin_count: int,
) -> int:
    return (
        ((event_index * 2 + condition_index) * unit_count + unit_index) * bin_count
        + bin_index
    )


def unit_rate_trace(
    counts: array,
    session: dict,
    event_index: int,
    unit_index: int,
    condition_index: int,
) -> list[float]:
    event = session["events"][event_index]
    trials = (
        event["contextTrialCount"]
        if condition_index == 0
        else event["controlTrialCount"]
    )
    values = [
        counts[
            count_index(
                event_index,
                condition_index,
                unit_index,
                bin_index,
                session["unitCount"],
                150,
            )
        ]
        / trials
        / BIN_SECONDS
        for bin_index in range(150)
    ]
    return smooth_trace(values)


def heatmap_png(
    session: dict,
    counts: array,
    event_index: int,
    unit_indices: list[int],
    limit: float,
) -> bytes:
    pixels = bytearray()
    for unit_index in unit_indices:
        context = unit_rate_trace(counts, session, event_index, unit_index, 0)
        control = unit_rate_trace(counts, session, event_index, unit_index, 1)
        for context_value, control_value in zip(context, control, strict=True):
            pixels.extend(
                optotagging_heatmap_color(context_value - control_value, limit)
            )
    return encode_rgb_png(150, len(unit_indices), bytes(pixels))


def svg_text(
    x: float,
    y: float,
    text: str,
    *,
    size: float,
    weight: int = 400,
    anchor: str = "start",
    fill: str = "#303536",
    transform: str | None = None,
) -> str:
    transform_attribute = f' transform="{transform}"' if transform else ""
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" text-anchor="{anchor}" '
        f'font-family="{FIGURE_SANS_FONT}" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}"{transform_attribute}>'
        f"{escape(text)}</text>"
    )


def response_matrix(payload: dict) -> tuple[list[str], list[dict]]:
    area_counts = Counter()
    sessions = {}
    for session in payload["sessions"]:
        delta = float32_values(session["responseDeltaHzBase64"])
        sessions[session["context"]] = (session, delta)
        for unit in session["units"]:
            if unit["qcPass"] and unit["location"] != "void":
                area_counts[unit["location"]] += 1
    areas = [area for area, _ in area_counts.most_common(16)]
    columns = []
    for context in CONTEXT_ORDER:
        session, delta = sessions[context]
        for event_index, event in enumerate(session["events"]):
            values = {}
            for area in areas:
                selected = [
                    index
                    for index, unit in enumerate(session["units"])
                    if unit["qcPass"] and unit["location"] == area
                ]
                values[area] = (
                    sum(delta[event_index * session["unitCount"] + index] for index in selected)
                    / len(selected)
                    if selected
                    else None
                )
            columns.append(
                {
                    "context": context,
                    "event": event["label"],
                    "values": values,
                }
            )
    return areas, columns


def nice_limit(value: float) -> float:
    raw = max(value * 1.05, 1)
    magnitude = 10 ** math.floor(math.log10(raw))
    normalized = raw / magnitude
    step = next(value for value in (1, 2, 3, 5, 10) if normalized <= value)
    return step * magnitude


def write_neuropixels_event_svg(
    output: Path = STATIC_OUTPUT,
    payload: dict | None = None,
) -> Path:
    payload = load_neuropixels_event_responses() if payload is None else payload
    width = 1800
    left = 245
    right = 45
    matrix_top = 180
    row_height = 42
    areas, columns = response_matrix(payload)
    matrix_height = len(areas) * row_height
    column_width = (width - left - right) / len(columns)
    heatmap_top = matrix_top + matrix_height + 330
    heatmap_height = 260
    line_top = heatmap_top + heatmap_height + 78
    line_height = 180
    height = line_top + line_height + 120
    svg = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" '
            'aria-labelledby="neural-response-title neural-response-description">'
        ),
        '<title id="neural-response-title">Neuropixels mismatch responses</title>',
        (
            '<desc id="neural-response-description">Panel A summarizes mean mismatch-minus-'
            "control firing-rate effects by anatomical area for all events. Panel B shows "
            "representative unit heatmaps and population PSTHs for one event per context.</desc>"
        ),
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        svg_text(36, 52, "A", size=FIGURE_TYPE_SCALE["panel"], weight=800),
        svg_text(
            98,
            50,
            "Area-level mismatch response across all conditions",
            size=FIGURE_TYPE_SCALE["title"],
            weight=750,
        ),
        svg_text(
            98,
            80,
            "Mean response-window firing rate: mismatch minus matched control; QC-passing units",
            size=FIGURE_TYPE_SCALE["label"],
            fill="#646B68",
        ),
    ]
    finite = [
        abs(value)
        for column in columns
        for value in column["values"].values()
        if value is not None
    ]
    matrix_limit = nice_limit(sorted(finite)[math.floor(len(finite) * 0.95)])
    for row_index, area in enumerate(areas):
        y = matrix_top + row_index * row_height
        svg.append(
            svg_text(
                left - 15,
                y + row_height * 0.67,
                area,
                size=FIGURE_TYPE_SCALE["label"],
                anchor="end",
            )
        )
        for column_index, column in enumerate(columns):
            x = left + column_index * column_width
            value = column["values"][area]
            color = (
                optotagging_heatmap_color(value, matrix_limit)
                if value is not None
                else (230, 232, 231)
            )
            svg.append(
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{column_width:.2f}" '
                f'height="{row_height:.2f}" fill="rgb{color}" stroke="#ffffff"/>'
            )
    for column_index, column in enumerate(columns):
        x = left + (column_index + 0.5) * column_width
        svg.append(
            svg_text(
                x,
                matrix_top + matrix_height + 18,
                column["event"],
                size=FIGURE_TYPE_SCALE["small"],
                anchor="end",
                fill="#646B68",
                transform=(
                    f"rotate(-55 {x:.2f} "
                    f"{matrix_top + matrix_height + 18:.2f})"
                ),
            )
        )
    context_start = 0
    for context in CONTEXT_ORDER:
        count = 4
        center = left + (context_start + count / 2) * column_width
        svg.append(
            svg_text(
                center,
                matrix_top - 18,
                CONTEXT_LABELS[context],
                size=FIGURE_TYPE_SCALE["heading"],
                weight=750,
                anchor="middle",
            )
        )
        context_start += count
    legend_width = 190
    legend_x = width - right - legend_width
    legend_y = 103
    for step in range(legend_width):
        value = -matrix_limit + (step / (legend_width - 1)) * matrix_limit * 2
        color = optotagging_heatmap_color(value, matrix_limit)
        svg.append(
            f'<rect x="{legend_x + step:.2f}" y="{legend_y:.2f}" width="1.2" '
            f'height="14" fill="rgb{color}"/>'
        )
    svg.extend(
        [
            svg_text(
                legend_x,
                legend_y + 33,
                f"−{matrix_limit:g}",
                size=FIGURE_TYPE_SCALE["small"],
                anchor="middle",
                fill="#646B68",
            ),
            svg_text(
                legend_x + legend_width / 2,
                legend_y + 33,
                "0",
                size=FIGURE_TYPE_SCALE["small"],
                anchor="middle",
                fill="#646B68",
            ),
            svg_text(
                legend_x + legend_width,
                legend_y + 33,
                f"+{matrix_limit:g} spikes/s",
                size=FIGURE_TYPE_SCALE["small"],
                anchor="middle",
                fill="#646B68",
            ),
        ]
    )

    svg.extend(
        [
            svg_text(
                36,
                heatmap_top - 85,
                "B",
                size=FIGURE_TYPE_SCALE["panel"],
                weight=800,
            ),
            svg_text(
                98,
                heatmap_top - 87,
                "Representative unit dynamics",
                size=FIGURE_TYPE_SCALE["title"],
                weight=750,
            ),
            svg_text(
                98,
                heatmap_top - 57,
                (
                    "Top 150 QC-passing units by absolute response effect; heatmap "
                    "color is mismatch minus control spikes/s"
                ),
                size=FIGURE_TYPE_SCALE["label"],
                fill="#646B68",
            ),
        ]
    )
    sessions = {session["context"]: session for session in payload["sessions"]}
    panel_gap = 22
    panel_width = (width - left - right - 3 * panel_gap) / 4
    time = payload["analysisParameters"]["timeBinCentersSeconds"]
    for context_index, context in enumerate(CONTEXT_ORDER):
        session = sessions[context]
        event_id = DEFAULT_EVENTS[context]
        event_index = next(
            index for index, event in enumerate(session["events"]) if event["id"] == event_id
        )
        delta = float32_values(session["responseDeltaHzBase64"])
        selected = [
            index
            for index, unit in enumerate(session["units"])
            if unit["qcPass"]
        ]
        selected.sort(
            key=lambda index: abs(
                delta[event_index * session["unitCount"] + index]
            ),
            reverse=True,
        )
        selected = selected[:150]
        count_path = SOURCE_MEDIA_DIR / Path(session["countAtlas"]["path"]).name
        counts = uint16_values(count_path)
        heatmap_traces = []
        for unit_index in selected:
            event_trace = unit_rate_trace(counts, session, event_index, unit_index, 0)
            control_trace = unit_rate_trace(counts, session, event_index, unit_index, 1)
            heatmap_traces.extend(
                event_value - control_value
                for event_value, control_value in zip(
                    event_trace,
                    control_trace,
                    strict=True,
                )
            )
        heat_limit = nice_limit(
            sorted(abs(value) for value in heatmap_traces)[
                math.floor(len(heatmap_traces) * 0.98)
            ]
        )
        png = heatmap_png(session, counts, event_index, selected, heat_limit)
        encoded = base64.b64encode(png).decode()
        x = left + context_index * (panel_width + panel_gap)
        svg.extend(
            [
                svg_text(
                    x + panel_width / 2,
                    heatmap_top - 14,
                    CONTEXT_LABELS[context],
                    size=FIGURE_TYPE_SCALE["heading"],
                    weight=750,
                    anchor="middle",
                ),
                svg_text(
                    x + panel_width / 2,
                    heatmap_top + 12,
                    session["events"][event_index]["label"],
                    size=FIGURE_TYPE_SCALE["label"],
                    anchor="middle",
                    fill="#646B68",
                ),
                (
                    f'<image x="{x:.2f}" y="{heatmap_top + 28:.2f}" '
                    f'width="{panel_width:.2f}" height="{heatmap_height:.2f}" '
                    f'preserveAspectRatio="none" href="data:image/png;base64,{encoded}"/>'
                ),
                svg_text(
                    x + 8,
                    heatmap_top + 48,
                    f"±{heat_limit:g} spikes/s",
                    size=FIGURE_TYPE_SCALE["small"],
                    fill="#303536",
                ),
            ]
        )
        event_means = []
        control_means = []
        for bin_index in range(150):
            event_values = []
            control_values = []
            for unit_index in selected:
                event_values.append(
                    counts[
                        count_index(
                            event_index,
                            0,
                            unit_index,
                            bin_index,
                            session["unitCount"],
                            150,
                        )
                    ]
                    / session["events"][event_index]["contextTrialCount"]
                    / BIN_SECONDS
                )
                control_values.append(
                    counts[
                        count_index(
                            event_index,
                            1,
                            unit_index,
                            bin_index,
                            session["unitCount"],
                            150,
                        )
                    ]
                    / session["events"][event_index]["controlTrialCount"]
                    / BIN_SECONDS
                )
            event_means.append(sum(event_values) / len(event_values))
            control_means.append(sum(control_values) / len(control_values))
        event_means = smooth_trace(event_means)
        control_means = smooth_trace(control_means)
        maximum = max(event_means + control_means) * 1.08
        plot_y = line_top
        zero_x = x + ((0 - time[0]) / (time[-1] - time[0])) * panel_width
        svg.extend(
            [
                (
                    f'<rect x="{x:.2f}" y="{plot_y:.2f}" width="{panel_width:.2f}" '
                    f'height="{line_height:.2f}" fill="#FAFBFA" stroke="#D0D4D2"/>'
                ),
                (
                    f'<line x1="{zero_x:.2f}" y1="{plot_y:.2f}" '
                    f'x2="{zero_x:.2f}" y2="{plot_y + line_height:.2f}" '
                    'stroke="#707674" stroke-dasharray="5 4"/>'
                ),
            ]
        )
        for values, color, dash in (
            (control_means, "#8A918E", ' stroke-dasharray="8 6"'),
            (event_means, "#315F73", ""),
        ):
            path = []
            for bin_index, value in enumerate(values):
                px = x + (bin_index / 149) * panel_width
                py = plot_y + line_height - value / maximum * line_height
                path.append(f"{'L' if bin_index else 'M'} {px:.2f} {py:.2f}")
            svg.append(
                f'<path d="{" ".join(path)}" fill="none" stroke="{color}" '
                f'stroke-width="3"{dash}/>'
            )
        svg.append(
            svg_text(
                x + 8,
                plot_y + 20,
                f"n={len(selected)} units",
                size=FIGURE_TYPE_SCALE["small"],
                fill="#646B68",
            )
        )
        svg.append(
            svg_text(
                x + panel_width - 8,
                plot_y + 20,
                f"{maximum:.1f} spikes/s",
                size=FIGURE_TYPE_SCALE["small"],
                anchor="end",
                fill="#646B68",
            )
        )
        for tick in (-1, 0, 1, 2):
            tick_x = (
                x
                + (tick - time[0])
                / (time[-1] - time[0])
                * panel_width
            )
            svg.append(
                svg_text(
                    tick_x,
                    plot_y + line_height + 22,
                    str(tick),
                    size=FIGURE_TYPE_SCALE["small"],
                    anchor="middle",
                    fill="#646B68",
                )
            )
    svg.append("</svg>")
    output.parent.mkdir(parents=True, exist_ok=True)
    write_svg_output(output, svg)
    return output
