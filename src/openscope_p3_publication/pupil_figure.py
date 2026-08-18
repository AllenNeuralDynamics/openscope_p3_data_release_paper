from __future__ import annotations

import base64
import hashlib
import json
import math
import random
import statistics
from collections import defaultdict
from html import escape
from pathlib import Path

from .figures import (
    FIGURE_SANS_FONT,
    FIGURE_TYPE_SCALE,
    JAVASCRIPT_DIR,
    REPO_ROOT,
    load_embed_auto_height,
    load_figure_stylesheet,
    normalized_text_bytes,
    platform_logo_data_uris,
    write_svg_output,
)

DATA_PATH = REPO_ROOT / "figure_sources" / "data" / "pupil-event-responses.json"
PROVENANCE_PATH = DATA_PATH.with_suffix(".provenance.json")
INTERACTIVE_OUTPUT = REPO_ROOT / "interactive" / "pupil-event-responses.html"
STATIC_OUTPUT = (
    REPO_ROOT
    / "images"
    / "figures"
    / "generated"
    / "supplementary-pupil-event-responses.svg"
)

MINIMUM_GROUP_VALID_TRIALS = 3
MINIMUM_GROUP_RETENTION = 0.10
MODALITY_ORDER = ("neuropixels", "mesoscope", "slap2")
MODALITY_LABELS = {
    "neuropixels": "Neuropixels",
    "mesoscope": "Mesoscope",
    "slap2": "SLAP2",
}
CONTEXT_ORDER = ("standard", "sensorimotor", "sequence", "duration")
CONTEXT_LABELS = {
    "standard": "Standard oddball",
    "sensorimotor": "Sensorimotor",
    "sequence": "Sequence",
    "duration": "Duration",
}
STATIC_GROUP_ORDER = {
    "standard": ("orientation", "halt", "omission"),
    "sensorimotor": ("motor_orientation", "motor_halt", "motor_omission"),
    "sequence": ("orientation", "halt", "omission"),
    "duration": ("delay_150", "delay_500", "delay_1000", "omission"),
}
STATIC_GROUP_LABELS = {
    "orientation": "Orientation",
    "motor_orientation": "Motor orientation",
    "halt": "Halt",
    "motor_halt": "Motor halt",
    "omission": "Omission",
    "motor_omission": "Motor omission",
    "delay_150": "150 ms",
    "delay_500": "500 ms",
    "delay_1000": "1000 ms",
}
STATIC_LEGEND_LABELS = {
    "orientation": "Orient.",
    "motor_orientation": "Orient.",
    "halt": "Halt",
    "motor_halt": "Halt",
    "omission": "Omit.",
    "motor_omission": "Omit.",
    "delay_150": "150 ms",
    "delay_500": "500 ms",
    "delay_1000": "1000 ms",
}
STATIC_GROUP_COLORS = {
    "orientation": "#315F73",
    "motor_orientation": "#315F73",
    "halt": "#B16027",
    "motor_halt": "#B16027",
    "omission": "#CC4C45",
    "motor_omission": "#CC4C45",
    "delay_150": "#22A884",
    "delay_500": "#2A788E",
    "delay_1000": "#414487",
}


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_path(record: dict) -> Path:
    path = REPO_ROOT / record["path"]
    if not path.is_file():
        raise RuntimeError(f"Pupil-response source is missing: {record['path']}")
    return path


def availability_by_summary(payload: dict) -> dict[tuple[str, str, str, str], dict]:
    coverage = defaultdict(
        lambda: {
            "control": {"available": 0, "valid": 0},
            "event": {"available": 0, "valid": 0},
        }
    )
    for session in payload["sessions"]:
        for event in session["events"]:
            key = (
                session["modality"],
                session["cohort"],
                session["context"],
                event["id"],
            )
            for condition in ("event", "control"):
                record = event["conditions"][condition]
                coverage[key][condition]["available"] += record["available_trials"]
                coverage[key][condition]["valid"] += record["valid_trials"]

    availability = {}
    for key, conditions in coverage.items():
        insufficient = []
        for condition, record in conditions.items():
            fraction = record["valid"] / record["available"]
            record["retention"] = round(fraction, 6)
            if (
                record["valid"] < MINIMUM_GROUP_VALID_TRIALS
                or fraction < MINIMUM_GROUP_RETENTION
            ):
                insufficient.append(condition)
        if insufficient:
            condition_labels = " and ".join(insufficient)
            reason = (
                f"Unavailable: insufficient post-QC pupil tracking for {condition_labels} "
                f"trials (requires at least {MINIMUM_GROUP_VALID_TRIALS} valid trials "
                f"and {MINIMUM_GROUP_RETENTION:.0%} retention per condition)."
            )
        else:
            reason = None
        availability[key] = {
            "available": not insufficient,
            "conditions": conditions,
            "reason": reason,
        }
    return availability


def load_pupil_event_responses(
    data_path: Path = DATA_PATH,
    provenance_path: Path = PROVENANCE_PATH,
) -> dict:
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if payload.get("version") != 1 or provenance.get("version") != 1:
        raise RuntimeError("Pupil-response snapshot version is not supported.")
    if file_sha256(data_path) != provenance.get("output_sha256"):
        raise RuntimeError("Pupil-response snapshot checksum does not match provenance.")
    for key in ("analysis_module", "script"):
        record = provenance[key]
        if file_sha256(source_path(record)) != record["sha256"]:
            raise RuntimeError(f"Pupil-response {key} checksum does not match provenance.")
    for record in provenance["source_snapshots"].values():
        if file_sha256(source_path(record)) != record["sha256"]:
            raise RuntimeError("Pupil-response source snapshot checksum does not match.")

    parameters = payload.get("analysis_parameters", {})
    time = parameters.get("time_grid_seconds", [])
    baseline = parameters.get("baseline", {})
    response_window = parameters.get("pupil", {}).get("response_window", {})
    if (
        parameters.get("event_alignment", "").split(";")[0]
        != "NWB interval-table start_time for every selected context and control row"
        or parameters.get("trace_rate_hz") != 20
        or len(time) != 121
        or time[0] != -2.0
        or time[-1] != 4.0
        or baseline
        != {
            "duration": "recorded previous stop_time to current start_time",
            "sensorimotor": "343 ms immediately preceding current start_time",
            "sequence": "recorded previous start_time to current start_time",
            "standard": "recorded previous stop_time to current start_time",
        }
        or response_window
        != {
            "duration": (
                "start_time + 0.343 s through start_time + 0.343 s + row Delay"
            ),
            "sensorimotor": "NWB start_time through stop_time",
            "sequence": "NWB start_time through stop_time",
            "standard": "NWB start_time through stop_time",
        }
    ):
        raise RuntimeError("Pupil-response timing parameters are invalid.")
    if len(payload.get("sessions", [])) != provenance.get("session_count"):
        raise RuntimeError("Pupil-response session count does not match provenance.")
    if len(payload.get("mice", [])) != provenance.get("mouse_record_count"):
        raise RuntimeError("Pupil-response mouse count does not match provenance.")
    if payload.get("exclusions"):
        raise RuntimeError("Pupil-response snapshot contains source-session exclusions.")
    if len(payload.get("summaries", [])) != provenance.get("summary_count"):
        raise RuntimeError("Pupil-response summary count does not match provenance.")

    trace_fields = (
        "percent_change_mean_trace",
        "percent_change_std_trace",
        "raw_mean_trace",
        "raw_std_trace",
    )
    for session in payload["sessions"]:
        if session["modality"] not in MODALITY_ORDER:
            raise RuntimeError("Pupil-response session modality is invalid.")
        for event in session["events"]:
            if event.get("alignment") != "start_time":
                raise RuntimeError("Pupil-response event is not aligned to start_time.")
            for condition in ("event", "control"):
                record = event["conditions"][condition]
                if not 0 <= record["valid_trials"] <= record["available_trials"]:
                    raise RuntimeError("Pupil-response trial counts are invalid.")
                if record["valid_trials"]:
                    if any(len(record[field]) != len(time) for field in trace_fields):
                        raise RuntimeError("Pupil-response session trace length is invalid.")
    for mouse in payload["mice"]:
        for event in mouse["events"]:
            if event["pupil"] is None:
                continue
            for condition in ("event", "control"):
                record = event["pupil"][condition]
                if any(len(record[field]) != len(time) for field in trace_fields):
                    raise RuntimeError("Pupil-response mouse trace length is invalid.")

    availability = availability_by_summary(payload)
    unavailable = []
    for summary in payload["summaries"]:
        key = (
            summary["modality"],
            summary["cohort"],
            summary["context"],
            summary["event_id"],
        )
        summary["availability"] = availability[key]
        if not availability[key]["available"]:
            unavailable.append(key)
        pupil = summary.get("pupil")
        if pupil is None:
            raise RuntimeError("Pupil-response summary lacks a pupil record.")
        if pupil["mouse_count"] != len(pupil["response_percent_change"]["points"]):
            raise RuntimeError("Pupil-response mouse counts are inconsistent.")
        for field in (
            "control_percent_change_trace",
            "difference_percent_change_trace",
            "event_percent_change_trace",
        ):
            trace = pupil[field]
            if any(len(trace[bound]) != len(time) for bound in ("lower", "mean", "upper")):
                raise RuntimeError("Pupil-response population trace length is invalid.")
    expected_unavailable = {
        ("slap2", "motor", "duration", event_id)
        for event_id in ("delay_150", "delay_500", "delay_1000", "omission")
    }
    if set(unavailable) != expected_unavailable:
        raise RuntimeError(
            "Pupil-response availability changed; review tracking coverage explicitly."
        )
    return payload


def camel_condition(record: dict) -> dict:
    return {
        "availableTrials": record["available_trials"],
        "baselineDurationMeanSeconds": record["baseline_duration_mean_seconds"],
        "baselineMeanPx2": record["baseline_mean_px2"],
        "percentChangeMeanTrace": record["percent_change_mean_trace"],
        "percentChangeStdTrace": record["percent_change_std_trace"],
        "rawMeanTrace": record["raw_mean_trace"],
        "rawStdTrace": record["raw_std_trace"],
        "rejections": record["rejections"],
        "responsePercentChangeMean": record["response_percent_change_mean"],
        "responsePercentChangeStd": record["response_percent_change_std"],
        "responseStartMeanSeconds": record["response_start_mean_seconds"],
        "responseEndMeanSeconds": record["response_end_mean_seconds"],
        "validTrials": record["valid_trials"],
    }


def camel_population_trace(record: dict) -> dict:
    return {
        "lower": record["lower"],
        "mean": record["mean"],
        "upper": record["upper"],
    }


def presentation_payload(payload: dict) -> dict:
    mice = []
    for mouse in payload["mice"]:
        mice.append(
            {
                "cohort": mouse["cohort"],
                "context": mouse["context"],
                "events": [
                    {
                        "id": event["id"],
                        "label": event["label"],
                        "conditions": (
                            {
                                condition: camel_condition(event["pupil"][condition])
                                for condition in ("event", "control")
                            }
                            if event["pupil"] is not None
                            else None
                        ),
                    }
                    for event in mouse["events"]
                ],
                "modality": mouse["modality"],
                "mouseId": mouse["mouse_id"],
                "sessionCount": mouse["session_count"],
                "sourceSessionIds": mouse["source_session_ids"],
            }
        )
    summaries = []
    for summary in payload["summaries"]:
        pupil = summary["pupil"]
        summaries.append(
            {
                "availability": summary["availability"],
                "cohort": summary["cohort"],
                "context": summary["context"],
                "eventId": summary["event_id"],
                "label": summary["label"],
                "modality": summary["modality"],
                "pupil": {
                    "controlPercentChangeTrace": camel_population_trace(
                        pupil["control_percent_change_trace"]
                    ),
                    "differencePercentChangeTrace": camel_population_trace(
                        pupil["difference_percent_change_trace"]
                    ),
                    "eventPercentChangeTrace": camel_population_trace(
                        pupil["event_percent_change_trace"]
                    ),
                    "mouseCount": pupil["mouse_count"],
                    "responsePercentChange": pupil["response_percent_change"],
                },
                "responseWindowLabel": summary["response_window_label"],
                "staticGroup": summary["static_group"],
            }
        )
    return {
        "baselineDescriptions": payload["analysis_parameters"]["baseline"],
        "platformLogos": platform_logo_data_uris(),
        "mice": mice,
        "summaries": summaries,
        "timeGridSeconds": payload["analysis_parameters"]["time_grid_seconds"],
        "version": payload["version"],
    }


def write_pupil_event_html(
    output: Path = INTERACTIVE_OUTPUT,
    static_output: Path = STATIC_OUTPUT,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = load_pupil_event_responses()
    if not static_output.is_file():
        write_pupil_event_svg(static_output, payload)
    static_data = base64.b64encode(normalized_text_bytes(static_output)).decode()
    template = (JAVASCRIPT_DIR / "pupil-event-responses.html").read_text(
        encoding="utf-8"
    )
    stylesheet = load_figure_stylesheet("pupil-event-responses.css")
    javascript = (JAVASCRIPT_DIR / "pupil-event-responses.js").read_text(
        encoding="utf-8"
    )
    html = (
        template.replace("__PUPIL_EVENT_CSS__", stylesheet)
        .replace(
            "__PUPIL_EVENT_DATA__",
            json.dumps(
                presentation_payload(payload),
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
        .replace(
            "__PUPIL_EVENT_STATIC_IMAGE__",
            f"data:image/svg+xml;base64,{static_data}",
        )
        .replace("__PUPIL_EVENT_JS__", javascript)
        .replace("__EMBED_AUTO_HEIGHT_JS__", load_embed_auto_height())
    )
    output.write_text(html, encoding="utf-8", newline="\n")
    return output


def optional_mean(traces: list[list[float | None]]) -> list[float | None]:
    result = []
    for values in zip(*traces, strict=True):
        finite = [float(value) for value in values if value is not None]
        result.append(statistics.fmean(finite) if finite else None)
    return result


def grouped_static_records(payload: dict) -> dict[tuple[str, str, str, str], dict]:
    summaries = defaultdict(list)
    for summary in payload["summaries"]:
        summaries[
            (
                summary["modality"],
                summary["cohort"],
                summary["context"],
                summary["static_group"],
            )
        ].append(summary)
    grouped = {}
    for key, records in summaries.items():
        availability = {
            "available": all(record["availability"]["available"] for record in records),
            "reason": next(
                (
                    record["availability"]["reason"]
                    for record in records
                    if not record["availability"]["available"]
                ),
                None,
            ),
        }
        points_by_mouse = defaultdict(list)
        for record in records:
            for point in record["pupil"]["response_percent_change"]["points"]:
                points_by_mouse[point["mouse_id"]].append(float(point["value"]))
        points = {
            mouse_id: statistics.fmean(values)
            for mouse_id, values in sorted(points_by_mouse.items())
        }
        grouped[key] = {
            "availability": availability,
            "label": STATIC_GROUP_LABELS[key[-1]],
            "points": points,
            "trace": optional_mean(
                [
                    record["pupil"]["difference_percent_change_trace"]["mean"]
                    for record in records
                ]
            ),
        }
    return grouped


def row_order(payload: dict) -> list[tuple[str, str]]:
    available = {
        (summary["modality"], summary["cohort"])
        for summary in payload["summaries"]
    }
    return [
        (modality, cohort)
        for modality in MODALITY_ORDER
        for cohort in ("motor", "sequence")
        if (modality, cohort) in available
    ]


def nice_limit(value: float) -> float:
    raw = max(value * 1.08, 1)
    magnitude = 10 ** math.floor(math.log10(raw))
    normalized = raw / magnitude
    step = next(
        candidate
        for candidate in (1, 1.5, 2, 3, 4, 5, 10)
        if normalized <= candidate
    )
    return step * magnitude


def row_limits(
    rows: list[tuple[str, str]],
    grouped: dict[tuple[str, str, str, str], dict],
    value_kind: str,
) -> dict[tuple[str, str], float]:
    limits = {}
    for row in rows:
        values = []
        for key, record in grouped.items():
            if key[:2] != row or not record["availability"]["available"]:
                continue
            if value_kind == "trace":
                values.extend(
                    abs(float(value))
                    for value in record["trace"]
                    if value is not None
                )
            elif value_kind == "points":
                values.extend(abs(value) for value in record["points"].values())
            else:
                raise ValueError(f"Unknown pupil static value kind: {value_kind}")
        limits[row] = nice_limit(max(values, default=1))
    return limits


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


def trace_path(
    values: list[float | None],
    time: list[float],
    x: float,
    y: float,
    width: float,
    height: float,
    limit: float,
    display_end: float,
) -> str:
    commands = []
    drawing = False
    for index, value in enumerate(values):
        if time[index] > display_end:
            break
        if value is None:
            drawing = False
            continue
        px = x + (time[index] - time[0]) / (display_end - time[0]) * width
        py = y + height / 2 - float(value) / limit * height / 2
        commands.append(f"{'L' if drawing else 'M'} {px:.2f} {py:.2f}")
        drawing = True
    return " ".join(commands)


def bootstrap_interval(points: dict[str, float], key: str) -> tuple[float, float, float]:
    values = list(points.values())
    mean = statistics.fmean(values)
    if len(values) == 1:
        return mean, mean, mean
    seed = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big")
    rng = random.Random(seed)
    estimates = sorted(
        statistics.fmean(rng.choice(values) for _ in values) for _ in range(2_000)
    )
    return mean, estimates[49], estimates[1949]


def write_pupil_event_svg(
    output: Path = STATIC_OUTPUT,
    payload: dict | None = None,
) -> Path:
    payload = load_pupil_event_responses() if payload is None else payload
    grouped = grouped_static_records(payload)
    rows = row_order(payload)
    trace_limits = row_limits(rows, grouped, "trace")
    effect_limits = row_limits(rows, grouped, "points")
    time = payload["analysis_parameters"]["time_grid_seconds"]

    width = 1800
    left = 230
    right = 45
    column_gap = 24
    plot_width = (width - left - right - 3 * column_gap) / 4
    plot_height = 165
    row_step = 245
    panel_a_top = 205
    panel_a_bottom = panel_a_top + len(rows) * row_step
    panel_b_top = panel_a_bottom + 165
    effect_height = 118
    effect_step = 178
    height = panel_b_top + len(rows) * effect_step + 150
    svg = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" '
            'aria-labelledby="pupil-title pupil-description">'
        ),
        '<title id="pupil-title">Peri-event pupil responses across P3 modalities</title>',
        (
            '<desc id="pupil-description">Panel A shows population mean event-minus-control '
            "pupil traces for each modality, cohort, context, and mismatch event. Panel B "
            "shows mouse-level response-window effects with bootstrap confidence intervals. "
            "SLAP2 duration is unavailable because too few trials pass pupil tracking quality "
            "control.</desc>"
        ),
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        svg_text(
            42,
            55,
            "A",
            size=FIGURE_TYPE_SCALE["panel"],
            weight=800,
        ),
        svg_text(
            105,
            53,
            "Population peri-event pupil response difference",
            size=FIGURE_TYPE_SCALE["title"],
            weight=750,
        ),
        svg_text(
            105,
            84,
            (
                "Context event minus matched control; orientation angles are pooled "
                "in the static summary"
            ),
            size=FIGURE_TYPE_SCALE["label"],
            fill="#646B68",
        ),
    ]

    for column, context in enumerate(CONTEXT_ORDER):
        x = left + column * (plot_width + column_gap)
        svg.append(
            svg_text(
                x + plot_width / 2,
                145,
                CONTEXT_LABELS[context],
                size=FIGURE_TYPE_SCALE["heading"],
                weight=750,
                anchor="middle",
            )
        )
        groups = STATIC_GROUP_ORDER[context]
        legend_slot = plot_width / len(groups)
        for group_index, group in enumerate(groups):
            legend_x = x + group_index * legend_slot
            legend_label = STATIC_LEGEND_LABELS[group]
            svg.append(
                f'<line x1="{legend_x:.2f}" y1="173" x2="{legend_x + 16:.2f}" '
                f'y2="173" stroke="{STATIC_GROUP_COLORS[group]}" stroke-width="4"/>'
            )
            svg.append(
                svg_text(
                    legend_x + 21,
                    178,
                    legend_label,
                    size=FIGURE_TYPE_SCALE["small"],
                )
            )

    for row_index, row in enumerate(rows):
        modality, cohort = row
        y = panel_a_top + row_index * row_step
        limit = trace_limits[row]
        row_label = (
            f"{MODALITY_LABELS[modality]}\n"
            f"{'Motor' if cohort == 'motor' else 'Sequence'} cohort"
        )
        for line_index, line in enumerate(row_label.splitlines()):
            svg.append(
                svg_text(
                    left - 24,
                    y + 65 + line_index * 23,
                    line,
                    size=FIGURE_TYPE_SCALE["modality"]
                    if line_index == 0
                    else FIGURE_TYPE_SCALE["label"],
                    weight=750 if line_index == 0 else 500,
                    anchor="end",
                )
            )
        for column, context in enumerate(CONTEXT_ORDER):
            x = left + column * (plot_width + column_gap)
            svg.extend(
                [
                    (
                        f'<rect x="{x:.2f}" y="{y:.2f}" width="{plot_width:.2f}" '
                        f'height="{plot_height}" fill="#FAFBFA" stroke="#D0D4D2"/>'
                    ),
                    (
                        f'<line x1="{x:.2f}" y1="{y + plot_height / 2:.2f}" '
                        f'x2="{x + plot_width:.2f}" y2="{y + plot_height / 2:.2f}" '
                        'stroke="#9CA29F" stroke-width="1"/>'
                    ),
                ]
            )
            zero_x = x + (0 - time[0]) / (time[-1] - time[0]) * plot_width
            svg.append(
                f'<line x1="{zero_x:.2f}" y1="{y:.2f}" x2="{zero_x:.2f}" '
                f'y2="{y + plot_height:.2f}" stroke="#707674" stroke-width="1" '
                'stroke-dasharray="5 4"/>'
            )
            records = [
                grouped.get((modality, cohort, context, group))
                for group in STATIC_GROUP_ORDER[context]
            ]
            available_records = [
                record
                for record in records
                if record is not None and record["availability"]["available"]
            ]
            if not available_records:
                svg.append(
                    svg_text(
                        x + plot_width / 2,
                        y + plot_height / 2 - 5,
                        "Unavailable",
                        size=FIGURE_TYPE_SCALE["label"],
                        weight=700,
                        anchor="middle",
                        fill="#8C6C1D",
                    )
                )
                svg.append(
                    svg_text(
                        x + plot_width / 2,
                        y + plot_height / 2 + 20,
                        "insufficient tracking",
                        size=FIGURE_TYPE_SCALE["small"],
                        anchor="middle",
                        fill="#8C6C1D",
                    )
                )
            else:
                display_end = 4.0
                for group, record in zip(
                    STATIC_GROUP_ORDER[context],
                    records,
                    strict=True,
                ):
                    if record is None or not record["availability"]["available"]:
                        continue
                    path = trace_path(
                        record["trace"],
                        time,
                        x,
                        y,
                        plot_width,
                        plot_height,
                        limit,
                        display_end,
                    )
                    svg.append(
                        f'<path d="{path}" fill="none" '
                        f'stroke="{STATIC_GROUP_COLORS[group]}" stroke-width="2.5" '
                        'stroke-linejoin="round" stroke-linecap="round"/>'
                    )
            if column == 0:
                svg.append(
                    svg_text(
                        x - 8,
                        y + 8,
                        f"+{limit:g}",
                        size=FIGURE_TYPE_SCALE["small"],
                        anchor="end",
                        fill="#646B68",
                    )
                )
                svg.append(
                    svg_text(
                        x - 8,
                        y + plot_height,
                        f"−{limit:g}",
                        size=FIGURE_TYPE_SCALE["small"],
                        anchor="end",
                        fill="#646B68",
                    )
                )
            if row_index == len(rows) - 1:
                display_end = 4.0
                for tick in (-2, 0, 2, 4):
                    tick_x = (
                        x
                        + (tick - time[0])
                        / (display_end - time[0])
                        * plot_width
                    )
                    svg.append(
                        svg_text(
                            tick_x,
                            y + plot_height + 22,
                            str(tick),
                            size=FIGURE_TYPE_SCALE["small"],
                            anchor="middle",
                            fill="#646B68",
                        )
                    )

    svg.extend(
        [
            svg_text(
                42,
                panel_b_top - 82,
                "B",
                size=FIGURE_TYPE_SCALE["panel"],
                weight=800,
            ),
            svg_text(
                105,
                panel_b_top - 84,
                "Mouse-level response-window effects",
                size=FIGURE_TYPE_SCALE["title"],
                weight=750,
            ),
            svg_text(
                105,
                panel_b_top - 53,
                (
                    "Mean event-minus-control pupil change during each defined response "
                    "window; bars show 95% mouse-bootstrap intervals"
                ),
                size=FIGURE_TYPE_SCALE["label"],
                fill="#646B68",
            ),
        ]
    )
    categories = [
        (context, group)
        for context in CONTEXT_ORDER
        for group in STATIC_GROUP_ORDER[context]
    ]
    effect_width = width - left - right
    slot_width = effect_width / len(categories)
    context_start = 0
    for context in CONTEXT_ORDER:
        count = len(STATIC_GROUP_ORDER[context])
        center = left + (context_start + count / 2) * slot_width
        svg.append(
            svg_text(
                center,
                panel_b_top - 15,
                CONTEXT_LABELS[context],
                size=FIGURE_TYPE_SCALE["heading"],
                weight=750,
                anchor="middle",
            )
        )
        context_start += count

    for row_index, row in enumerate(rows):
        modality, cohort = row
        y = panel_b_top + row_index * effect_step
        limit = effect_limits[row]
        zero_y = y + effect_height / 2
        svg.extend(
            [
                (
                    f'<rect x="{left}" y="{y:.2f}" width="{effect_width:.2f}" '
                    f'height="{effect_height}" fill="#FAFBFA" stroke="#D0D4D2"/>'
                ),
                (
                    f'<line x1="{left}" y1="{zero_y:.2f}" x2="{left + effect_width:.2f}" '
                    f'y2="{zero_y:.2f}" stroke="#707674" stroke-width="1"/>'
                ),
                svg_text(
                    left - 24,
                    y + 45,
                    MODALITY_LABELS[modality],
                    size=FIGURE_TYPE_SCALE["modality"],
                    weight=750,
                    anchor="end",
                ),
                svg_text(
                    left + 7,
                    y + 13,
                    f"+{limit:g}",
                    size=FIGURE_TYPE_SCALE["small"],
                    fill="#646B68",
                ),
                svg_text(
                    left + 7,
                    y + effect_height - 5,
                    f"−{limit:g}",
                    size=FIGURE_TYPE_SCALE["small"],
                    fill="#646B68",
                ),
                svg_text(
                    left - 24,
                    y + 69,
                    f"{'Motor' if cohort == 'motor' else 'Sequence'} cohort",
                    size=FIGURE_TYPE_SCALE["label"],
                    anchor="end",
                ),
            ]
        )
        for category_index, (context, group) in enumerate(categories):
            x = left + (category_index + 0.5) * slot_width
            record = grouped.get((modality, cohort, context, group))
            if record is None or not record["availability"]["available"]:
                svg.append(
                    f'<line x1="{x - 8:.2f}" y1="{zero_y - 8:.2f}" '
                    f'x2="{x + 8:.2f}" y2="{zero_y + 8:.2f}" '
                    'stroke="#B9A66E" stroke-width="2"/>'
                )
                svg.append(
                    f'<line x1="{x - 8:.2f}" y1="{zero_y + 8:.2f}" '
                    f'x2="{x + 8:.2f}" y2="{zero_y - 8:.2f}" '
                    'stroke="#B9A66E" stroke-width="2"/>'
                )
                continue
            mean, lower, upper = bootstrap_interval(
                record["points"],
                f"{modality}:{cohort}:{context}:{group}",
            )

            def effect_y(
                value: float,
                row_y: float = y,
                row_limit: float = limit,
            ) -> float:
                return (
                    row_y
                    + effect_height / 2
                    - value / row_limit * effect_height / 2
                )

            svg.append(
                f'<line x1="{x:.2f}" y1="{effect_y(lower):.2f}" '
                f'x2="{x:.2f}" y2="{effect_y(upper):.2f}" '
                'stroke="#303536" stroke-width="3"/>'
            )
            for mouse_id, value in record["points"].items():
                digest = hashlib.sha256(f"{mouse_id}:{group}".encode()).digest()
                jitter = (int.from_bytes(digest[:2], "big") / 65535 - 0.5) * slot_width * 0.42
                svg.append(
                    f'<circle cx="{x + jitter:.2f}" cy="{effect_y(value):.2f}" r="4.5" '
                    f'fill="{STATIC_GROUP_COLORS[group]}" fill-opacity="0.72"/>'
                )
            svg.append(
                f'<circle cx="{x:.2f}" cy="{effect_y(mean):.2f}" r="6.5" '
                'fill="#FFFFFF" stroke="#303536" stroke-width="2.5"/>'
            )
        if row_index == len(rows) - 1:
            for category_index, (_context, group) in enumerate(categories):
                x = left + (category_index + 0.5) * slot_width
                svg.append(
                    svg_text(
                        x,
                        y + effect_height + 25,
                        STATIC_GROUP_LABELS[group],
                        size=FIGURE_TYPE_SCALE["small"],
                        anchor="end",
                        fill="#646B68",
                        transform=f"rotate(-45 {x:.2f} {y + effect_height + 25:.2f})",
                    )
                )

    svg.append(
        svg_text(
            width / 2,
            height - 35,
            (
                "Pupil area is expressed as within-trial percent change from the "
                "context-specific preceding interval; all events align to "
                "display-synchronized NWB start_time."
            ),
            size=FIGURE_TYPE_SCALE["label"],
            anchor="middle",
            fill="#646B68",
        )
    )
    svg.append("</svg>")
    output.parent.mkdir(parents=True, exist_ok=True)
    write_svg_output(output, svg)
    return output
