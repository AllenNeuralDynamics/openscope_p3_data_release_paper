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
    NEURAL_SUBJECT,
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


SNAPSHOT_VERSION = 12
"""Schema version of the committed snapshot.

Must match ``VERSION`` in scripts/extract_neuropixels_event_responses.py. Version
10 added the per-unit responsiveness block, the duration delay-epoch statistic,
and per-event running-gate summaries.
"""


def load_neuropixels_event_responses(
    data_path: Path = DATA_PATH,
    provenance_path: Path = PROVENANCE_PATH,
) -> dict:
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if payload.get("version") != SNAPSHOT_VERSION or (
        provenance.get("version") != SNAPSHOT_VERSION
    ):
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
            # The grey inter-sequence interval, corrected from the preceding
            # grating element, and the borrowed control baseline. See
            # docs/neuropixels-mismatch-responsiveness.md.
            "sequence": (
                "context: grey inter-sequence interval at row i-3, the full row "
                "from its start_time through its stop_time. control: control "
                "block 2 is contiguous and contains no grey, so baselines are "
                "the blank inter-stimulus intervals of the control block 1 "
                "repeat that ends where control block 2 begins, sampled evenly "
                "across that repeat, one per trial"
            ),
            "standard": "previous row stop_time through event start_time",
        }
    ):
        raise RuntimeError("Neuropixels event-response parameters are invalid.")
    if payload.get("subject") != NEURAL_SUBJECT or len(payload.get("sessions", [])) != 4:
        raise RuntimeError("Neuropixels event-response session coverage is invalid.")
    if payload.get("sessionOrder") != list(CONTEXT_ORDER):
        raise RuntimeError("Neuropixels event-response context order is invalid.")

    sequence_payload = next(
        (
            session
            for session in payload["sessions"]
            if session.get("context") == "sequence"
        ),
        None,
    )
    reference = (sequence_payload or {}).get("sequenceComparisonReference")
    if reference is None:
        raise RuntimeError(
            "The sequence session must carry its stimulus-matched control "
            "reference; without it the control trace cannot be segmented."
        )
    if (
        reference.get("stimulus") != "single@0deg"
        or reference.get("trials") != 70
        or len(reference.get("spanSeconds", [])) != 2
        or reference["spanSeconds"][0] >= reference["spanSeconds"][1]
    ):
        raise RuntimeError("Sequence comparison reference is invalid.")

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


def copy_neuropixels_event_media(
    payload: dict,
    output_dir: Path = INTERACTIVE_MEDIA_DIR,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    expected = set()
    outputs = []
    for session in payload["sessions"]:
        for key in ("sdfMeanAtlas",):
            name = Path(session[key]["path"]).name
            source = SOURCE_MEDIA_DIR / name
            target = output_dir / name
            shutil.copy2(source, target)
            expected.add(name)
            outputs.append(target)
    for path in output_dir.glob("*"):
        if path.is_file() and path.name not in expected:
            path.unlink()
    return outputs


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
                    "eventId": event["id"],
                    "values": values,
                }
            )
    return areas, columns


RESPONSIVE_P_MAX = 0.05
"""Uncorrected significance threshold, matching the interactive figure.

Section 6.3a of docs/neuropixels-mismatch-responsiveness.md records why the
uncorrected p is reported with its chance expectation displayed rather than a
Benjamini-Hochberg q: for 13 of 16 events the measured signal is 7-12 times
chance, so correction changes no conclusion while costing power on the three
events where it would matter.
"""

RESPONSIVE_MODULATION_MIN = 0.1
"""Minimum absolute modulation index, matching the SST optotagging convention."""

RESPONSIVE_CHANCE_FRACTION = RESPONSIVE_P_MAX
"""Fraction of units expected to clear the significance gate by chance.

A two-sided test at p < 0.05 admits 5% of units under the null. The modulation
floor removes some of those, so this is an upper bound on the noise floor and
is drawn on the panel as a reference rather than subtracted.
"""

RESPONSIVE_MIN_AREA_UNITS = 10
"""Below this many units, an area's fraction is not drawn for that event."""


SHORT_CONTEXT_LABELS = {
    "standard": "Standard",
    "sensorimotor": "Sensorimotor",
    "sequence": "Sequence",
    "duration": "Duration",
}
"""Context group headers for the area matrices.

Each group spans four columns, about 180 px, and "Standard oddball" overruns
that into the neighbouring group's header.
"""

SHORT_EVENT_LABELS = {
    "orientation_45": "45°",
    "orientation_90": "90°",
    "halt": "Halt",
    "omission": "Omission",
    "motor_orientation_45": "45°",
    "motor_orientation_90": "90°",
    "motor_halt": "Halt",
    "motor_omission": "Omission",
    "delay_150": "150 ms",
    "delay_500": "500 ms",
    "delay_1000": "1000 ms",
}
"""Column labels for the area matrices.

The full labels ("45 degree motor orientation") are 26 characters, and rotated
at -55 degrees they run off the left edge of the figure and are clipped. The
context group header above each block of four already names the context, so
"motor" and "substitution" are redundant in the column label.
"""


def short_event_label(event_id: str, fallback: str) -> str:
    """Axis label for one event column."""
    return SHORT_EVENT_LABELS.get(event_id, fallback)


STATIC_EXAMPLE_UNIT_TARGET = 150
"""Rows drawn in the responsive-unit heatmap.

Fixed so the four context panels share a row thickness. Where more units
qualify, they are subsampled evenly across the anatomical order rather than
truncated, so the panel represents the whole responsive population instead of
one end of it. The panel label reports both counts.
"""


def responsive_unit_indices(
    session: dict,
    event_index: int,
    *,
    target: int = STATIC_EXAMPLE_UNIT_TARGET,
) -> tuple[list[int], int]:
    """Q1-responsive units for one event, in anatomical order.

    Returns the drawn indices and the number that qualified. Selecting on the
    statistical test rather than on the displayed mismatch-minus-control effect
    matters: the previous criterion, the largest absolute effect, selected on
    the very quantity the panel plots, so the panel was guaranteed to look
    strong whether or not the effect was real.
    """
    unit_count = session["unitCount"]
    offset = event_index * unit_count
    p_values = float32_values(session["responsiveness"]["q1_p"]["base64"])
    modulation = float32_values(session["responsiveness"]["q1_modulation"]["base64"])
    group_priority = {
        group: index for index, group in enumerate(STATIC_AREA_GROUP_ORDER)
    }

    def sort_key(index: int) -> tuple[int, str, float]:
        unit = session["units"][index]
        priority = min(
            (group_priority[group] for group in unit["areaGroups"] if group in group_priority),
            default=len(group_priority),
        )
        return priority, unit["location"], unit["depthUm"]

    qualified = sorted(
        (
            index
            for index, unit in enumerate(session["units"])
            if unit["qcPass"]
            and unit["decoderLabel"] in {"mua", "sua"}
            and unit["firingRateHz"] >= 1
            and math.isfinite(p_values[offset + index])
            and math.isfinite(modulation[offset + index])
            and p_values[offset + index] < RESPONSIVE_P_MAX
            and abs(modulation[offset + index]) > RESPONSIVE_MODULATION_MIN
        ),
        key=sort_key,
    )
    if len(qualified) <= target:
        return qualified, len(qualified)
    # Even subsample across the anatomical order, not the first `target`.
    step = len(qualified) / target
    drawn = [qualified[min(len(qualified) - 1, math.floor(i * step))] for i in range(target)]
    return drawn, len(qualified)


def responsive_fraction_matrix(payload: dict) -> tuple[list[str], list[dict]]:
    """Fraction of units responsive per area and event.

    Shares the row and column order of :func:`response_matrix` so the two
    panels can be read across: the same area occupies the same row in both,
    and the same event the same column.

    Responsiveness is the Q1 test -- the mismatch response against the same
    unit's own most recent expected comparison -- at an uncorrected
    ``p < RESPONSIVE_P_MAX`` with ``|modulation index| > RESPONSIVE_MODULATION_MIN``.
    Cells backed by fewer than ``RESPONSIVE_MIN_AREA_UNITS`` units are ``None``
    rather than a fraction, so a small denominator is never drawn as a
    measurement.
    """
    areas, _ = response_matrix(payload)
    sessions = {session["context"]: session for session in payload["sessions"]}
    columns = []
    for context in CONTEXT_ORDER:
        session = sessions[context]
        unit_count = session["unitCount"]
        p_values = float32_values(session["responsiveness"]["q1_p"]["base64"])
        modulation = float32_values(
            session["responsiveness"]["q1_modulation"]["base64"]
        )
        by_area: dict[str, list[int]] = {}
        for index, unit in enumerate(session["units"]):
            if unit["qcPass"]:
                by_area.setdefault(unit["location"], []).append(index)
        for event_index, event in enumerate(session["events"]):
            offset = event_index * unit_count
            values: dict[str, float | None] = {}
            counts: dict[str, int] = {}
            for area in areas:
                indices = by_area.get(area, [])
                tested = [
                    index
                    for index in indices
                    if math.isfinite(p_values[offset + index])
                    and math.isfinite(modulation[offset + index])
                ]
                counts[area] = len(tested)
                if len(tested) < RESPONSIVE_MIN_AREA_UNITS:
                    values[area] = None
                    continue
                responsive = sum(
                    1
                    for index in tested
                    if p_values[offset + index] < RESPONSIVE_P_MAX
                    and abs(modulation[offset + index]) > RESPONSIVE_MODULATION_MIN
                )
                values[area] = responsive / len(tested)
            columns.append(
                {
                    "context": context,
                    "event": event["label"],
                    "eventId": event["id"],
                    "counts": counts,
                    "values": values,
                }
            )
    return areas, columns


RESPONSIVE_RAMP_LIGHT = (242, 247, 245)
RESPONSIVE_RAMP_DARK = (17, 74, 63)
RESPONSIVE_NO_DATA_PATTERN = "responsive-no-data"
"""Hatch pattern id for cells with too few units.

A flat grey cannot be used. Any grey light enough to read as "empty" lands
inside the ramp's own lightness range -- the obvious choice, #E6E8E7, sits at
OKLab L 0.929 between the first and second ramp steps, so an area with no
measurement would have been indistinguishable from a real low fraction. A
hatch is categorically not a ramp value.
"""


def responsive_fraction_color(
    value: float | None, limit: float
) -> tuple[int, int, int] | None:
    """Sequential single-hue ramp for a responsive fraction.

    Sequential rather than diverging, because a fraction is a magnitude with no
    meaningful midpoint -- unlike the mismatch-minus-control panel, whose
    diverging ramp encodes the sign of an effect. The hue is deliberately
    neither pole of that ramp so the two panels are not confused. Lightness is
    monotone across the ramp (OKLab L 0.972 to 0.370).

    Returns ``None`` for an absent value, which callers must render as
    :data:`RESPONSIVE_NO_DATA_PATTERN` rather than as any colour. Returning a
    colour here would let "no measurement" be drawn as a fraction.
    """
    if value is None or not math.isfinite(value) or limit <= 0:
        return None
    fraction = max(0.0, min(1.0, value / limit))
    return tuple(
        round(start + fraction * (end - start))
        for start, end in zip(
            RESPONSIVE_RAMP_LIGHT, RESPONSIVE_RAMP_DARK, strict=True
        )
    )


def responsive_cell_fill(value: float | None, limit: float) -> str:
    """SVG fill for one responsive-fraction cell, hatched when unmeasured."""
    color = responsive_fraction_color(value, limit)
    if color is None:
        return f"url(#{RESPONSIVE_NO_DATA_PATTERN})"
    return f"rgb{color}"


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


def sequence_control_segments(
    time: list[float],
    control_values: list[float],
    control_sem: list[float] | None,
    reference_values: list[float],
    reference_sem: list[float] | None,
    *,
    comparison_span: tuple[float, float],
    mismatch_stop: float,
    reference_bin_seconds: float,
) -> tuple[list[float | None], list[float | None] | None]:
    """Restrict the sequence control trace to the two stimulus-matched windows.

    Control block 2 presents single gratings in random order, so outside the
    mismatch window its trace averages over an arbitrary draw of fourteen
    orientations and carries no sequence structure. Drawing it continuously
    invites the reader to compare epochs that are not comparable. Both windows
    are matched on stimulus: the mismatch window keeps the control block's own
    matched event, and the comparison window is filled from a separate
    alignment to a single 0 degree grating, the stimulus the context block
    shows as element three.

    Values outside both windows become ``None``, which every renderer here
    treats as a break in the line rather than as zero.
    """
    if len(time) != len(control_values):
        raise ValueError("time and control_values must have the same length.")
    if control_sem is not None and len(control_sem) != len(time):
        raise ValueError("control_sem must match the time axis.")
    if reference_bin_seconds <= 0:
        raise ValueError("reference_bin_seconds must be positive.")
    span_start, span_stop = comparison_span
    if span_stop <= span_start:
        raise ValueError("comparison_span must be increasing.")

    values: list[float | None] = []
    sems: list[float | None] | None = [] if control_sem is not None else None
    for index, seconds in enumerate(time):
        if 0.0 <= seconds <= mismatch_stop:
            values.append(control_values[index])
            if sems is not None:
                sems.append(control_sem[index])
            continue
        if span_start <= seconds <= span_stop:
            bin_index = round((seconds - span_start) / reference_bin_seconds)
            if 0 <= bin_index < len(reference_values):
                values.append(reference_values[bin_index])
                if sems is not None:
                    sems.append(
                        reference_sem[bin_index] if reference_sem is not None else None
                    )
                continue
        values.append(None)
        if sems is not None:
            sems.append(None)
    return values, sems


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
    control_values: list[float | None],
    control_sem: list[float | None],
    timing: dict,
    baseline_subtracted: bool,
    display_start: float,
    display_end: float,
    unit_count: int,
    qualified_count: int | None = None,
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
        if trace[index] is not None and sem[index] is not None
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
    def runs(values, sem=None):
        # A gap is None, which the sequence control trace uses to mark the
        # epochs where control block 2 is not comparable. Each contiguous run
        # is drawn as its own sub-path so no line spans a gap.
        grouped = []
        current = []
        for index in visible:
            missing = values[index] is None or (
                sem is not None and sem[index] is None
            )
            if missing:
                if current:
                    grouped.append(current)
                    current = []
                continue
            current.append(index)
        if current:
            grouped.append(current)
        return grouped

    for values, sem, color in (
        (control_values, control_sem, "#8A918E"),
        (event_values, event_sem, "#315F73"),
    ):
        for run in runs(values, sem):
            upper_path = [
                f"{'L' if position else 'M'} {px(time[index]):.2f} "
                f"{py(values[index] + sem[index]):.2f}"
                for position, index in enumerate(run)
            ]
            lower_path = [
                f"L {px(time[index]):.2f} {py(values[index] - sem[index]):.2f}"
                for index in reversed(run)
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
            segment
            for run in runs(values)
            for position, index in enumerate(run)
            for segment in (
                f"{'L' if position else 'M'} {px(time[index]):.2f} "
                f"{py(values[index]):.2f}",
            )
        ]
        if not path:
            continue
        svg.append(
            f'<path d="{" ".join(path)}" fill="none" stroke="{color}" '
            f'stroke-width="3"{dash}/>'
        )
    svg.extend(
        [
            svg_text(
                x + 8,
                y + 20,
                f"n={unit_count} of {qualified_count} responsive"
                if qualified_count is not None and qualified_count != unit_count
                else f"n={unit_count} units",
                size=FIGURE_TYPE_SCALE["small"],
                fill="#646B68",
            ),
        ]
    )
    ticks = time_axis_ticks(display_start, display_end)
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


def time_axis_ticks(start: float, stop: float) -> tuple[float, ...]:
    """Time ticks derived from the window rather than hardcoded per context.

    Reproduces the previous tick sets exactly for the 1.5 s and 3 s symmetric
    windows, and labels the sequence window's full ``[-2, 1]`` span, which a
    per-context literal left unlabelled beyond +/-0.75 s.
    """
    step = 1.0 if stop - start > 2 else 0.5
    values = {start, 0.0, stop}
    current = math.ceil(start / step) * step
    while current < stop:
        if current > start:
            values.add(round(current, 3))
        current += step
    return tuple(sorted(values))


def append_area_matrix(
    svg: list[str],
    *,
    areas: list[str],
    columns: list[dict],
    x: float,
    y: float,
    matrix_width: float,
    row_height: float,
    cell_fill,
    draw_row_labels: bool,
) -> None:
    """Draw one area-by-event matrix.

    Shared by both area panels so their rows and columns stay aligned and any
    fix to one applies to both. ``cell_fill`` maps a cell value to an SVG fill
    string, which lets an absent value render as a hatch rather than as a
    colour on the panel's own scale.
    """
    column_width = matrix_width / len(columns)
    for row_index, area in enumerate(areas):
        row_y = y + row_index * row_height
        if draw_row_labels:
            svg.append(
                svg_text(
                    x - 15,
                    row_y + row_height * 0.67,
                    area,
                    size=FIGURE_TYPE_SCALE["label"],
                    anchor="end",
                )
            )
        for column_index, column in enumerate(columns):
            cell_x = x + column_index * column_width
            svg.append(
                f'<rect x="{cell_x:.2f}" y="{row_y:.2f}" '
                f'width="{column_width:.2f}" height="{row_height:.2f}" '
                f'fill="{cell_fill(column["values"][area])}" stroke="#ffffff"/>'
            )
    label_y = y + len(areas) * row_height + 18
    for column_index, column in enumerate(columns):
        center = x + (column_index + 0.5) * column_width
        svg.append(
            svg_text(
                center,
                label_y,
                short_event_label(column["eventId"], column["event"]),
                size=FIGURE_TYPE_SCALE["small"],
                anchor="end",
                fill="#646B68",
                transform=f"rotate(-55 {center:.2f} {label_y:.2f})",
            )
        )
    context_start = 0
    for context in CONTEXT_ORDER:
        count = sum(1 for column in columns if column["context"] == context)
        if not count:
            continue
        center = x + (context_start + count / 2) * column_width
        svg.append(
            svg_text(
                center,
                y - 18,
                SHORT_CONTEXT_LABELS[context],
                size=FIGURE_TYPE_SCALE["small"],
                weight=750,
                anchor="middle",
            )
        )
        context_start += count


def append_matrix_legend(
    svg: list[str],
    *,
    x: float,
    y: float,
    legend_width: float,
    ramp,
    ticks: list[tuple[float, str, bool]],
    span: tuple[float, float],
) -> None:
    """Colour bar for an area matrix, with labelled ticks under it."""
    steps = int(legend_width)
    low, high = span
    for step in range(steps):
        value = low + (step / max(steps - 1, 1)) * (high - low)
        svg.append(
            f'<rect x="{x + step:.2f}" y="{y:.2f}" width="1.2" height="14" '
            f'fill="rgb{ramp(value)}"/>'
        )
    for position, label, above in ticks:
        tick_x = x + position * legend_width
        if above:
            # Interior ticks are labelled above the bar; a label below would
            # collide with the end labels when the tick sits near an end.
            svg.append(
                f'<line x1="{tick_x:.2f}" y1="{y - 5:.2f}" x2="{tick_x:.2f}" '
                f'y2="{y:.2f}" stroke="#303536" stroke-width="1.4"/>'
            )
            svg.append(
                svg_text(
                    tick_x,
                    y - 10,
                    label,
                    size=FIGURE_TYPE_SCALE["small"],
                    anchor="middle",
                    fill="#303536",
                )
            )
            continue
        svg.append(
            f'<line x1="{tick_x:.2f}" y1="{y + 14:.2f}" x2="{tick_x:.2f}" '
            f'y2="{y + 19:.2f}" stroke="#646B68" stroke-width="1"/>'
        )
        svg.append(
            svg_text(
                tick_x,
                y + 32,
                label,
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
    fraction_areas, fraction_columns = responsive_fraction_matrix(payload)
    if fraction_areas != areas:
        raise RuntimeError(
            "The two area matrices must share their rows to be read across."
        )
    matrix_height = len(areas) * row_height
    matrix_gap = 76
    matrix_width = (width - left - right - matrix_gap) / 2
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
            '<desc id="neural-response-description">Panel A pairs two matrices over the '
            f"same {len(areas)} frontal, visual, hippocampal and thalamic areas and the "
            "same sixteen events: on the left the fraction of units responding to the "
            "mismatch relative to their own expected comparison, on the right the mean "
            "mismatch-minus-control firing rate. Panel B shows responsive-unit heatmaps "
            "plus baseline-subtracted population spike-density functions for one event "
            "per context.</desc>"
        ),
        (
            "<defs>"
            f'<pattern id="{RESPONSIVE_NO_DATA_PATTERN}" width="6" height="6" '
            'patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
            '<rect width="6" height="6" fill="#ffffff"/>'
            '<line x1="0" y1="0" x2="0" y2="6" stroke="#C9CFCC" '
            'stroke-width="1.6"/>'
            "</pattern></defs>"
        ),
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        svg_text(36, 52, "A", size=FIGURE_TYPE_SCALE["panel"], weight=800),
        svg_text(
            98,
            50,
            "Area-level responsiveness and mismatch-minus-control effect",
            size=FIGURE_TYPE_SCALE["title"],
            weight=750,
        ),
        svg_text(
            98,
            78,
            (
                f"Left: fraction of units responsive (Q1, uncorrected "
                f"p < {RESPONSIVE_P_MAX:g}, |modulation| > "
                f"{RESPONSIVE_MODULATION_MIN:g}).  "
                "Right: mismatch minus matched control firing rate."
            ),
            size=FIGURE_TYPE_SCALE["label"],
            fill="#646B68",
        ),
        svg_text(
            98,
            100,
            (
                "Areas with ≥10 pooled QC-passing units. Hatched where an area has "
                f"fewer than {RESPONSIVE_MIN_AREA_UNITS} tested units for that event."
            ),
            size=FIGURE_TYPE_SCALE["small"],
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
    fractions = [
        value
        for column in fraction_columns
        for value in column["values"].values()
        if value is not None
    ]
    fraction_limit = min(
        1.0,
        max(0.2, math.ceil(max(fractions) * 10) / 10) if fractions else 0.5,
    )

    def contrast_fill(value: float | None) -> str:
        # An absent cell is hatched, not grey. The obvious grey, #E6E8E7, is
        # darker than this ramp's white midpoint, so "no units of this area in
        # this session" was being drawn as a small real effect.
        if value is None or not math.isfinite(value):
            return f"url(#{RESPONSIVE_NO_DATA_PATTERN})"
        return f"rgb{optotagging_heatmap_color(value, matrix_limit)}"

    append_area_matrix(
        svg,
        areas=areas,
        columns=fraction_columns,
        x=left,
        y=matrix_top,
        matrix_width=matrix_width,
        row_height=row_height,
        cell_fill=lambda value: responsive_cell_fill(value, fraction_limit),
        draw_row_labels=True,
    )
    append_area_matrix(
        svg,
        areas=areas,
        columns=columns,
        x=left + matrix_width + matrix_gap,
        y=matrix_top,
        matrix_width=matrix_width,
        row_height=row_height,
        cell_fill=contrast_fill,
        draw_row_labels=False,
    )
    append_matrix_legend(
        svg,
        x=left,
        y=matrix_top + matrix_height + 108,
        legend_width=190,
        ramp=lambda value: responsive_fraction_color(value, fraction_limit)
        or RESPONSIVE_RAMP_LIGHT,
        ticks=[
            (0.0, "0", False),
            (
                RESPONSIVE_CHANCE_FRACTION / fraction_limit,
                f"chance {RESPONSIVE_CHANCE_FRACTION:.0%}",
                True,
            ),
            (1.0, f"{fraction_limit:.0%} responsive", False),
        ],
        span=(0.0, fraction_limit),
    )
    append_matrix_legend(
        svg,
        x=left + matrix_width + matrix_gap,
        y=matrix_top + matrix_height + 108,
        legend_width=190,
        ramp=lambda value: optotagging_heatmap_color(value, matrix_limit),
        ticks=[
            (0.0, f"−{matrix_limit:g}", False),
            (0.5, "0", False),
            (1.0, f"+{matrix_limit:g} spikes/s", False),
        ],
        span=(-matrix_limit, matrix_limit),
    )

    svg.extend(
        [
            svg_text(
                36,
                heatmap_top - 118,
                "B",
                size=FIGURE_TYPE_SCALE["panel"],
                weight=800,
            ),
            svg_text(
                98,
                heatmap_top - 116,
                "Responsive unit dynamics",
                size=FIGURE_TYPE_SCALE["title"],
                weight=750,
            ),
            svg_text(
                98,
                heatmap_top - 84,
                (
                    "Q1-responsive QC-passing MUA/SUA units ≥1 Hz, in anatomical "
                    "order; heatmap color is mismatch minus control SDF spikes/s"
                ),
                size=FIGURE_TYPE_SCALE["label"],
                fill="#646B68",
            ),
            svg_text(
                98,
                heatmap_top - 58,
                (
                    "Rows are selected on the test, not on the plotted effect. Lower "
                    "traces show baseline-subtracted mean SDF ±1 SEM across the same "
                    "units"
                ),
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
        selected, qualified_count = responsive_unit_indices(session, event_index)
        if not selected:
            raise RuntimeError(
                f"{session['context']} {event_id} has no responsive units to draw."
            )
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
        reference = session.get("sequenceComparisonReference")
        if reference is not None:
            # Same restriction the interactive applies: control block 2 has no
            # sequence structure to trace between the two matched windows.
            reference_scale = reference["quantizationScalePerHz"]
            reference_bins = reference["shape"][1]
            reference_counts = uint16_base64_values(reference["sdfBase64"])
            reference_baselines = float32_values(reference["baselineHzBase64"])
            reference_traces = [
                [
                    reference_counts[unit_index * reference_bins + bin_index]
                    / reference_scale
                    - reference_baselines[unit_index]
                    for bin_index in range(reference_bins)
                ]
                for unit_index in selected
            ]
            reference_means, reference_sem = mean_sem_traces(reference_traces)
            baseline_control_means, baseline_control_sem = (
                sequence_control_segments(
                    time,
                    baseline_control_means,
                    baseline_control_sem,
                    reference_means,
                    reference_sem,
                    comparison_span=tuple(reference["spanSeconds"]),
                    mismatch_stop=timing["presentationStopSeconds"],
                    reference_bin_seconds=reference["binSeconds"],
                )
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
            qualified_count=qualified_count,
        )
    svg.append("</svg>")
    output.parent.mkdir(parents=True, exist_ok=True)
    write_svg_output(output, svg)
    return output
