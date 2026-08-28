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
    BASELINE_BIN_SECONDS,
    BIN_SECONDS,
    CONTEXT_WINDOWS_SECONDS,
    NEURAL_SESSIONS,
    QC_THRESHOLDS,
    RASTERMAP_PARAMETERS,
    RASTERMAP_VERSION,
    SDF_KERNEL_DURATION_TAU,
    SDF_QUANTIZATION_SCALE,
    SDF_SOURCE_BIN_SECONDS,
    SDF_TAU_SECONDS,
    classify_neuron_type,
    context_window_seconds,
    relative_bin_centers,
    sdf_kernel,
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
    / "figure-10-neuropixels-event-responses.svg"
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
STATIC_AREA_GROUP_ORDER = ("frontal", "visual", "hippocampal", "thalamic")
STATIC_AREA_MIN_QC_UNITS = 10


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


def uint16_base64_values(encoded: str) -> array:
    values = array("H")
    values.frombytes(base64.b64decode(encoded))
    if sys.byteorder != "little":
        values.byteswap()
    return values


def load_neuropixels_event_responses(
    data_path: Path = DATA_PATH,
    provenance_path: Path = PROVENANCE_PATH,
) -> dict:
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if payload.get("version") != 9 or provenance.get("version") != 9:
        raise RuntimeError("Neuropixels event-response snapshot version is unsupported.")
    if provenance.get("rastermap") != {
        "packageVersion": RASTERMAP_VERSION,
        "parameters": RASTERMAP_PARAMETERS,
    }:
        raise RuntimeError("Neuropixels Rastermap provenance is invalid.")
    ontology_provenance = provenance.get("ontology", {})
    if (
        ontology_provenance.get("graphOrderField") != "BrainRegions.order"
        or not ontology_provenance.get("packageVersion")
        or ontology_provenance.get("sourceField")
        != "Allen structure-tree graph_order"
    ):
        raise RuntimeError("Neuropixels ontology provenance is invalid.")
    if file_sha256(data_path) != provenance.get("outputSha256"):
        raise RuntimeError("Neuropixels event-response checksum does not match provenance.")
    for key in ("module", "script"):
        record = provenance[key]
        if file_sha256(source_path(record)) != record["sha256"]:
            raise RuntimeError(f"Neuropixels event-response {key} checksum changed.")
    parameters = payload.get("analysisParameters", {})
    if (
        parameters.get("binSeconds") != BIN_SECONDS
        or parameters.get("baselineBinSeconds") != BASELINE_BIN_SECONDS
        or parameters.get("contextWindowsSeconds")
        != {
            context: list(window)
            for context, window in CONTEXT_WINDOWS_SECONDS.items()
        }
        or parameters.get("sdf")
        != {
            "causalPrepaddingSeconds": (
                (len(sdf_kernel()) - 1) * SDF_SOURCE_BIN_SECONDS
            ),
            "displayBinSeconds": BIN_SECONDS,
            "kernel": "causal exponential",
            "kernelDurationTau": SDF_KERNEL_DURATION_TAU,
            "kernelSamples": len(sdf_kernel()),
            "quantizationScalePerHz": SDF_QUANTIZATION_SCALE,
            "sourceBinSeconds": SDF_SOURCE_BIN_SECONDS,
            "tauSeconds": SDF_TAU_SECONDS,
        }
        or parameters.get("cellTypeClassification")
        != {
            "defaultFastSpikingMaximumMs": 0.4,
            "striatum": "RS",
            "sst": {
                "condition": "5 hz pulse train_presentations",
                "modulationIndexMinimum": 0.1,
                "pValueMaximum": 0.05,
            },
            "sstOverridesWaveformClass": True,
            "thalamicFastSpikingMaximumMs": 0.28,
        }
        or parameters.get("qcThresholds") != QC_THRESHOLDS
        or parameters.get("firingRateSource") != "NWB Units firing_rate"
        or parameters.get("ontology")
        != {
            "areaSource": (
                "Allen CCF location of each unit's extremum-channel electrode"
            ),
            "graphOrderSource": (
                "Allen structure-tree graph_order via iblatlas BrainRegions.order"
            ),
            "packageVersion": ontology_provenance["packageVersion"],
            "parentAreaRule": (
                "collapse Allen layer nodes and hyphenated subdivisions to the "
                "nearest non-collapsible ancestor; retain an already canonical area"
            ),
        }
        or parameters.get("rastermap")
        != {
            "input": (
                "native 1 ms causal-exponential SDF mismatch baseline z score "
                "over the displayed peri-event window"
            ),
            "packageVersion": RASTERMAP_VERSION,
            "parameters": RASTERMAP_PARAMETERS,
        }
        or parameters.get("responseWindow")
        != "selected row NWB start_time through stop_time"
        or parameters.get("unitDefault")
        != {
            "decoderLabels": ["mua", "sua"],
            "minimumFiringRateHz": 1.0,
            "neuronTypes": ["RS", "FS", "SST"],
            "numericalQc": "manuscript QC passing",
        }
        or parameters.get("baselineRules")
        != {
            "duration": "row i-2 stop_time through row i-1 start_time",
            "sensorimotor": "343 ms immediately preceding event start_time",
            "sequence": "previous row start_time through event start_time",
            "standard": "previous row stop_time through event start_time",
        }
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
        expected_window = list(context_window_seconds(session["context"]))
        expected_time = relative_bin_centers(session["context"])
        if (
            session.get("windowSeconds") != expected_window
            or session.get("timeBinCentersSeconds") != expected_time
        ):
            raise RuntimeError("Neuropixels session time grid is invalid.")
        for event in session["events"]:
            for condition in ("context", "control"):
                windows = event["timing"][condition].get(
                    "presentationWindows",
                    [],
                )
                if (
                    not windows
                    or not any(window["rowOffset"] == 0 for window in windows)
                    or any(
                        window["startSeconds"] >= window["stopSeconds"]
                        for window in windows
                    )
                    or (
                        session["context"] == "sensorimotor"
                        and len(windows) != 1
                    )
                ):
                    raise RuntimeError(
                        "Neuropixels neighboring presentation timing is invalid."
                    )
        total_units += unit_count
        total_qc += sum(unit["qcPass"] for unit in session["units"])
        if any(
            "majorParent" not in unit
            or "areaGroups" not in unit
            or not isinstance(unit.get("areaId"), int)
            or unit["areaId"] < 0
            or not isinstance(unit.get("areaGraphOrder"), int)
            or unit["areaGraphOrder"] < 0
            or not isinstance(unit.get("areaLevel"), int)
            or unit["areaLevel"] < 0
            or not isinstance(unit.get("parentArea"), str)
            or not unit["parentArea"]
            or not isinstance(unit.get("parentAreaId"), int)
            or unit["parentAreaId"] < 0
            or not isinstance(unit.get("parentAreaGraphOrder"), int)
            or unit["parentAreaGraphOrder"] < 0
            or not isinstance(unit.get("parentAreaLevel"), int)
            or unit["parentAreaLevel"] < 0
            or unit["parentAreaLevel"] > unit["areaLevel"]
            or (
                unit["location"] == unit["parentArea"]
                and (
                    unit["areaId"] != unit["parentAreaId"]
                    or unit["areaGraphOrder"] != unit["parentAreaGraphOrder"]
                    or unit["areaLevel"] != unit["parentAreaLevel"]
                )
            )
            or not math.isfinite(unit.get("firingRateHz", math.nan))
            or unit["firingRateHz"] < 0
            or not math.isfinite(unit.get("peakToValleyMs", math.nan))
            or unit["peakToValleyMs"] < 0
            or unit.get("neuronType") not in {"RS", "FS", "SST"}
            or not isinstance(unit.get("sstOptotagged"), bool)
            or (
                unit.get("sstOptotaggingPValue") is not None
                and not math.isfinite(unit["sstOptotaggingPValue"])
            )
            or (
                unit.get("sstOptotaggingModulationIndex") is not None
                and not math.isfinite(unit["sstOptotaggingModulationIndex"])
            )
            or unit["neuronType"]
            != classify_neuron_type(
                peak_to_valley_ms=unit["peakToValleyMs"],
                major_parent=unit["majorParent"],
                sst_optotagged=unit["sstOptotagged"],
            )
            for unit in session["units"]
        ):
            raise RuntimeError("Neuropixels unit metadata are invalid.")
        rastermap = session.get("rastermapRank", {})
        if (
            rastermap.get("dtype") != "uint16 little-endian"
            or rastermap.get("shape") != [4, unit_count]
        ):
            raise RuntimeError("Neuropixels Rastermap descriptor is invalid.")
        rastermap_ranks = uint16_base64_values(rastermap.get("base64", ""))
        if len(rastermap_ranks) != 4 * unit_count:
            raise RuntimeError("Neuropixels Rastermap rank length is invalid.")
        expected_ranks = list(range(unit_count))
        for event_index in range(4):
            start = event_index * unit_count
            if sorted(rastermap_ranks[start : start + unit_count]) != expected_ranks:
                raise RuntimeError("Neuropixels Rastermap ranks are not a permutation.")
        for key in ("sdfMeanAtlas",):
            descriptor = session[key]
            path = SOURCE_MEDIA_DIR / Path(descriptor["path"]).name
            if (
                not path.is_file()
                or file_sha256(path) != descriptor["sha256"]
                or path.stat().st_size != descriptor["size"]
            ):
                raise RuntimeError(f"Neuropixels event-response {key} is invalid.")
            referenced_media.add(path.name)
        mean_shape = session["sdfMeanAtlas"]["shape"]
        if mean_shape != [4, 2, unit_count, len(expected_time)]:
            raise RuntimeError("Neuropixels SDF-mean atlas shape is invalid.")
        if any(
            session[key].get("quantizationScalePerHz")
            != SDF_QUANTIZATION_SCALE
            for key in ("sdfMeanAtlas",)
        ):
            raise RuntimeError("Neuropixels SDF quantization is invalid.")
        for field in ("baselineMeanHzBase64", "baselineStdHzBase64"):
            values = float32_values(session[field])
            if (
                len(values) != 4 * 2 * unit_count
                or not all(math.isfinite(value) for value in values)
            ):
                raise RuntimeError(f"Neuropixels numeric field {field} is invalid.")
        for field in (
            "responseContextHzBase64",
            "responseControlHzBase64",
            "responseDeltaHzBase64",
        ):
            if len(float32_values(session[field])) != 4 * unit_count:
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
        for key in ("sdfMeanAtlas",):
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
        for key in ("sdfMeanAtlas",):
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


def atlas_index(
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
    sdf_mean: array,
    session: dict,
    event_index: int,
    unit_index: int,
    condition_index: int,
) -> list[float]:
    bin_count = session["sdfMeanAtlas"]["shape"][-1]
    return [
        sdf_mean[
            atlas_index(
                event_index,
                condition_index,
                unit_index,
                bin_index,
                session["unitCount"],
                bin_count,
            )
        ]
        / SDF_QUANTIZATION_SCALE
        for bin_index in range(bin_count)
    ]


def heatmap_png(
    session: dict,
    sdf_mean: array,
    event_index: int,
    unit_indices: list[int],
    limit: float,
    time: list[float],
    display_start: float,
) -> bytes:
    first_visible = next(
        index for index, value in enumerate(time) if value >= display_start
    )
    visible_bin_count = len(time) - first_visible
    pixels = bytearray()
    for unit_index in unit_indices:
        context = unit_rate_trace(sdf_mean, session, event_index, unit_index, 0)
        control = unit_rate_trace(sdf_mean, session, event_index, unit_index, 1)
        for context_value, control_value in zip(
            context[first_visible:],
            control[first_visible:],
            strict=True,
        ):
            pixels.extend(
                optotagging_heatmap_color(context_value - control_value, limit)
            )
    return encode_rgb_png(visible_bin_count, len(unit_indices), bytes(pixels))


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
    area_groups = {}
    sessions = {}
    for session in payload["sessions"]:
        delta = float32_values(session["responseDeltaHzBase64"])
        sessions[session["context"]] = (session, delta)
        for unit in session["units"]:
            if unit["qcPass"] and unit["location"] != "void":
                area_counts[unit["location"]] += 1
                area_groups[unit["location"]] = unit["areaGroups"]

    def area_sort_key(area: str) -> tuple[int, str]:
        groups = area_groups[area]
        priority = next(
            index
            for index, group in enumerate(STATIC_AREA_GROUP_ORDER)
            if group in groups
        )
        return priority, area

    areas = sorted(
        (
            area
            for area, count in area_counts.items()
            if count >= STATIC_AREA_MIN_QC_UNITS
            and any(group in area_groups[area] for group in STATIC_AREA_GROUP_ORDER)
        ),
        key=area_sort_key,
    )
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


def nice_tick_step(span: float, target_ticks: int = 4) -> float:
    raw = max(span / target_ticks, 1e-9)
    magnitude = 10 ** math.floor(math.log10(raw))
    normalized = raw / magnitude
    step = next(value for value in (1, 2, 5, 10) if normalized <= value)
    return step * magnitude


def static_rate_axis(
    values: list[float],
    baseline_subtracted: bool,
) -> tuple[float, float, list[float]]:
    data_minimum = min(values + [0])
    data_maximum = max(values + [0])
    span = max(data_maximum - data_minimum, 1)
    padded_minimum = data_minimum - span * 0.05 if baseline_subtracted else 0
    padded_maximum = data_maximum + span * 0.05
    step = nice_tick_step(padded_maximum - padded_minimum)
    lower = math.floor(padded_minimum / step) * step if baseline_subtracted else 0
    upper = math.ceil(padded_maximum / step) * step
    if upper <= lower:
        upper = lower + step
    tick_count = round((upper - lower) / step)
    ticks = [lower + index * step for index in range(tick_count + 1)]
    return lower, upper, ticks


def format_rate_tick(value: float) -> str:
    return "0" if abs(value) < 1e-9 else f"{value:g}"


def presentation_timing_values(
    timing: dict,
    minimum: float,
    maximum: float,
) -> list[float]:
    start = float(timing["presentationStartSeconds"])
    stop = float(timing["presentationStopSeconds"])
    if (
        not math.isfinite(start)
        or not math.isfinite(stop)
        or start >= stop
        or start < minimum
        or stop > maximum
    ):
        raise RuntimeError("Mismatch presentation timing is invalid for display.")
    return [start, stop]


def mean_sem_traces(traces: list[list[float]]) -> tuple[list[float], list[float]]:
    if not traces:
        raise ValueError("At least one trace is required.")
    bin_count = len(traces[0])
    if any(len(trace) != bin_count for trace in traces):
        raise ValueError("All traces must have the same length.")
    means = []
    sems = []
    for bin_index in range(bin_count):
        values = [trace[bin_index] for trace in traces]
        mean = sum(values) / len(values)
        variance = (
            sum((value - mean) ** 2 for value in values) / (len(values) - 1)
            if len(values) > 1
            else 0
        )
        means.append(mean)
        sems.append(math.sqrt(variance / len(values)))
    return means, sems


def append_static_rate_plot(
    svg: list[str],
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    time: list[float],
    event_values: list[float],
    event_sem: list[float],
    control_values: list[float],
    control_sem: list[float],
    timing: dict,
    baseline_subtracted: bool,
    display_start: float,
    display_end: float,
    unit_count: int,
) -> None:
    visible = [
        index for index, value in enumerate(time) if value >= display_start
    ]
    values = [
        value
        for trace, sem in (
            (event_values, event_sem),
            (control_values, control_sem),
        )
        for index in visible
        for value in (trace[index] - sem[index], trace[index] + sem[index])
    ]
    lower, upper, y_ticks = static_rate_axis(values, baseline_subtracted)

    def px(value: float) -> float:
        return x + (value - display_start) / (display_end - display_start) * width

    def py(value: float) -> float:
        return y + height - (value - lower) / (upper - lower) * height

    svg.append(
        f'<rect x="{x:.2f}" y="{y:.2f}" width="{width:.2f}" '
        f'height="{height:.2f}" fill="#FAFBFA" stroke="#D0D4D2"/>'
    )
    for tick in y_ticks:
        tick_y = py(tick)
        svg.extend(
            [
                (
                    f'<line x1="{x:.2f}" y1="{tick_y:.2f}" x2="{x + width:.2f}" '
                    f'y2="{tick_y:.2f}" stroke="'
                    f'{"#9CA29F" if abs(tick) < 1e-9 else "#E1E4E2"}" '
                    'stroke-width="1"/>'
                ),
                svg_text(
                    x - 7,
                    tick_y + 5,
                    format_rate_tick(tick),
                    size=FIGURE_TYPE_SCALE["small"],
                    anchor="end",
                    fill="#646B68",
                ),
            ]
        )
    for value in presentation_timing_values(timing, display_start, display_end):
        svg.append(
            f'<line x1="{px(value):.2f}" y1="{y:.2f}" '
            f'x2="{px(value):.2f}" y2="{y + height:.2f}" '
            'stroke="#707674" stroke-width="1" stroke-dasharray="5 4"/>'
        )
    for values, sem, color in (
        (control_values, control_sem, "#8A918E"),
        (event_values, event_sem, "#315F73"),
    ):
        upper_path = [
            f"{'L' if position else 'M'} {px(time[index]):.2f} "
            f"{py(values[index] + sem[index]):.2f}"
            for position, index in enumerate(visible)
        ]
        lower_path = [
            f"L {px(time[index]):.2f} {py(values[index] - sem[index]):.2f}"
            for index in reversed(visible)
        ]
        svg.append(
            f'<path d="{" ".join([*upper_path, *lower_path, "Z"])}" '
            f'fill="{color}" fill-opacity="0.14" stroke="none"/>'
        )
    for values, color, dash in (
        (control_values, "#8A918E", ' stroke-dasharray="8 6"'),
        (event_values, "#315F73", ""),
    ):
        path = [
            f"{'L' if position else 'M'} {px(time[index]):.2f} "
            f"{py(values[index]):.2f}"
            for position, index in enumerate(visible)
        ]
        svg.append(
            f'<path d="{" ".join(path)}" fill="none" stroke="{color}" '
            f'stroke-width="3"{dash}/>'
        )
    svg.extend(
        [
            svg_text(
                x + 8,
                y + 20,
                f"n={unit_count} units",
                size=FIGURE_TYPE_SCALE["small"],
                fill="#646B68",
            ),
        ]
    )
    ticks = (
        (-1.5, -1, 0, 1, 1.5)
        if display_start == -1.5
        else (-0.75, -0.5, 0, 0.5, 0.75)
    )
    for tick in ticks:
        svg.append(
            svg_text(
                px(tick),
                y + height + 22,
                str(tick),
                size=FIGURE_TYPE_SCALE["small"],
                anchor="middle",
                fill="#646B68",
            )
        )


def write_neuropixels_event_svg(
    output: Path = STATIC_OUTPUT,
    payload: dict | None = None,
) -> Path:
    payload = load_neuropixels_event_responses() if payload is None else payload
    width = 1800
    left = 245
    right = 45
    matrix_top = 180
    row_height = 32
    areas, columns = response_matrix(payload)
    matrix_height = len(areas) * row_height
    column_width = (width - left - right) / len(columns)
    heatmap_top = matrix_top + matrix_height + 330
    heatmap_height = 260
    line_top = heatmap_top + heatmap_height + 100
    line_height = 145
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
            f"control firing-rate effects across {len(areas)} frontal, visual, "
            "hippocampal, and "
            "thalamic areas for all events. Panel B shows representative unit heatmaps "
            "plus baseline-subtracted population spike-density functions for one event "
            "per context.</desc>"
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
            (
                "Mean response-window firing rate: mismatch minus matched control; "
                "areas with ≥10 pooled QC-passing units"
            ),
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
                    "Top 150 QC-passing MUA/SUA units ≥1 Hz by absolute response effect; "
                    "heatmap color is mismatch minus control SDF spikes/s"
                ),
                size=FIGURE_TYPE_SCALE["label"],
                fill="#646B68",
            ),
            svg_text(
                98,
                heatmap_top - 35,
                "Lower traces show baseline-subtracted mean SDF ±1 SEM across units",
                size=FIGURE_TYPE_SCALE["small"],
                fill="#646B68",
            ),
        ]
    )
    sessions = {session["context"]: session for session in payload["sessions"]}
    panel_gap = 48
    panel_width = (width - left - right - 3 * panel_gap) / 4
    svg.extend(
        [
            svg_text(
                left - 80,
                line_top + line_height / 2,
                "Δ firing rate",
                size=FIGURE_TYPE_SCALE["label"],
                weight=700,
                anchor="end",
            ),
        ]
    )
    for context_index, context in enumerate(CONTEXT_ORDER):
        session = sessions[context]
        event_id = DEFAULT_EVENTS[context]
        event_index = next(
            index for index, event in enumerate(session["events"]) if event["id"] == event_id
        )
        time = session["timeBinCentersSeconds"]
        display_start, display_end = session["windowSeconds"]
        first_visible = next(
            index for index, value in enumerate(time) if value >= display_start
        )
        timing = session["events"][event_index]["timing"]["context"]
        delta = float32_values(session["responseDeltaHzBase64"])
        selected = [
            index
            for index, unit in enumerate(session["units"])
            if unit["qcPass"]
            and unit["decoderLabel"] in {"mua", "sua"}
            and unit["firingRateHz"] >= 1
        ]
        selected.sort(
            key=lambda index: abs(
                delta[event_index * session["unitCount"] + index]
            ),
            reverse=True,
        )
        selected = selected[:150]
        sdf_mean_path = SOURCE_MEDIA_DIR / Path(
            session["sdfMeanAtlas"]["path"]
        ).name
        sdf_mean = uint16_values(sdf_mean_path)
        heatmap_traces = []
        for unit_index in selected:
            event_trace = unit_rate_trace(
                sdf_mean,
                session,
                event_index,
                unit_index,
                0,
            )
            control_trace = unit_rate_trace(
                sdf_mean,
                session,
                event_index,
                unit_index,
                1,
            )
            heatmap_traces.extend(
                event_value - control_value
                for event_value, control_value in zip(
                    event_trace[first_visible:],
                    control_trace[first_visible:],
                    strict=True,
                )
            )
        heat_limit = nice_limit(
            sorted(abs(value) for value in heatmap_traces)[
                math.floor(len(heatmap_traces) * 0.98)
            ]
        )
        png = heatmap_png(
            session,
            sdf_mean,
            event_index,
            selected,
            heat_limit,
            time,
            display_start,
        )
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
                    x - 7,
                    heatmap_top + 34,
                    "0",
                    size=FIGURE_TYPE_SCALE["small"],
                    anchor="end",
                    fill="#646B68",
                ),
                svg_text(
                    x - 7,
                    heatmap_top + 28 + heatmap_height,
                    str(len(selected)),
                    size=FIGURE_TYPE_SCALE["small"],
                    anchor="end",
                    fill="#646B68",
                ),
            ]
        )
        colorbar_width = min(190, panel_width * 0.62)
        colorbar_x = x + (panel_width - colorbar_width) / 2
        colorbar_y = heatmap_top + heatmap_height + 36
        for step in range(round(colorbar_width)):
            value = -heat_limit + (step / (colorbar_width - 1)) * heat_limit * 2
            color = optotagging_heatmap_color(value, heat_limit)
            svg.append(
                f'<rect x="{colorbar_x + step:.2f}" y="{colorbar_y:.2f}" '
                f'width="1.2" height="10" fill="rgb{color}"/>'
            )
        svg.extend(
            [
                svg_text(
                    colorbar_x,
                    colorbar_y + 27,
                    f"−{heat_limit:g}",
                    size=FIGURE_TYPE_SCALE["small"],
                    anchor="middle",
                    fill="#646B68",
                ),
                svg_text(
                    colorbar_x + colorbar_width / 2,
                    colorbar_y + 27,
                    "0",
                    size=FIGURE_TYPE_SCALE["small"],
                    anchor="middle",
                    fill="#646B68",
                ),
                svg_text(
                    colorbar_x + colorbar_width,
                    colorbar_y + 27,
                    f"+{heat_limit:g} spikes/s",
                    size=FIGURE_TYPE_SCALE["small"],
                    anchor="middle",
                    fill="#646B68",
                ),
            ]
        )
        for value in presentation_timing_values(
            timing,
            display_start,
            display_end,
        ):
            guide_x = (
                x
                + (value - display_start)
                / (display_end - display_start)
                * panel_width
            )
            svg.append(
                f'<line x1="{guide_x:.2f}" y1="{heatmap_top + 28:.2f}" '
                f'x2="{guide_x:.2f}" y2="{heatmap_top + 28 + heatmap_height:.2f}" '
                'stroke="#303536" stroke-width="1" stroke-dasharray="5 4"/>'
            )
        baseline_means = float32_values(session["baselineMeanHzBase64"])
        baseline_event_traces = [
            [
                value
                - baseline_means[
                    (event_index * 2) * session["unitCount"] + unit_index
                ]
                for value in unit_rate_trace(
                    sdf_mean,
                    session,
                    event_index,
                    unit_index,
                    0,
                )
            ]
            for unit_index in selected
        ]
        baseline_control_traces = [
            [
                value
                - baseline_means[
                    (event_index * 2 + 1) * session["unitCount"] + unit_index
                ]
                for value in unit_rate_trace(
                    sdf_mean,
                    session,
                    event_index,
                    unit_index,
                    1,
                )
            ]
            for unit_index in selected
        ]
        baseline_event_means, baseline_event_sem = mean_sem_traces(
            baseline_event_traces
        )
        baseline_control_means, baseline_control_sem = mean_sem_traces(
            baseline_control_traces
        )
        append_static_rate_plot(
            svg,
            x=x,
            y=line_top,
            width=panel_width,
            height=line_height,
            time=time,
            event_values=baseline_event_means,
            event_sem=baseline_event_sem,
            control_values=baseline_control_means,
            control_sem=baseline_control_sem,
            timing=timing,
            baseline_subtracted=True,
            display_start=display_start,
            display_end=display_end,
            unit_count=len(selected),
        )
    svg.append("</svg>")
    output.parent.mkdir(parents=True, exist_ok=True)
    write_svg_output(output, svg)
    return output
