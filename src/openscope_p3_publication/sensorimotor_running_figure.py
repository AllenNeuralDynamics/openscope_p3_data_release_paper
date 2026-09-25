"""Supplementary figure: locomotion during the sensorimotor mismatch block.

Renders the committed ``sensorimotor-running.json`` intermediate as a static SVG.
Three panels share one row axis of sessions ordered by block mean speed, so
speed, threshold sensitivity, and the limiting per-event trial count can be read
across for the same session.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .figures import (
    JAVASCRIPT_DIR,
    REPO_ROOT,
    load_embed_auto_height,
    load_figure_stylesheet,
    write_svg_output,
)
from .sensorimotor_running import (
    DEFAULT_RUNNING_THRESHOLD_CM_S,
    MINIMUM_QUALIFYING_TRIALS,
    RUNNING_THRESHOLDS_CM_S,
)

DATA_PATH = REPO_ROOT / "figure_sources" / "data" / "sensorimotor-running.json"
PROVENANCE_PATH = DATA_PATH.with_suffix(".provenance.json")
STATIC_OUTPUT = (
    REPO_ROOT
    / "images"
    / "figures"
    / "generated"
    / "supplementary-sensorimotor-running.svg"
)
INTERACTIVE_OUTPUT = REPO_ROOT / "interactive" / "sensorimotor-running.html"

SPEED_COLOR = "#2A788E"
AVAILABLE_COLOR = "#2A788E"
UNAVAILABLE_COLOR = "#B16027"
# Sequential ramp, one hue, monotonically decreasing lightness.
SEQUENTIAL_RAMP = ("#F0F4F6", "#C9DCE2", "#9CBFCA", "#6A9DAE", "#2A788E")
INK_PRIMARY = "#263033"
INK_SECONDARY = "#68706E"
INK_TICK = "#303536"
AXIS_COLOR = "#69716F"
GRID_COLOR = "#D0D4D2"
REFERENCE_COLOR = "#5E6664"
SURFACE = "#FFFFFF"
FONT = "Source Sans 3, sans-serif"
TYPE_SMALL = 12

MODALITY_LABELS = {
    "neuropixels": "Neuropixels",
    "mesoscope": "Mesoscope",
}

EVENT_HEADERS = {
    "motor_halt": "halt",
    "motor_omission": "omission",
    "motor_orientation_45": "45°",
    "motor_orientation_90": "90°",
}
EVENT_ORDER = (
    "motor_halt",
    "motor_omission",
    "motor_orientation_45",
    "motor_orientation_90",
)


def load_running_data(
    data_path: Path = DATA_PATH,
    provenance_path: Path = PROVENANCE_PATH,
) -> dict[str, Any]:
    """Load the committed intermediate and attach its provenance."""
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    sessions = payload.get("sessions")
    if not sessions:
        raise RuntimeError(f"{data_path} has no session records.")
    if provenance_path.exists():
        payload["provenance"] = json.loads(provenance_path.read_text(encoding="utf-8"))
    return payload


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _text(
    x: float,
    y: float,
    content: str,
    *,
    size: float = TYPE_SMALL,
    fill: str = INK_SECONDARY,
    weight: str | None = None,
    anchor: str | None = None,
) -> str:
    parts = [f'<text x="{x:.2f}" y="{y:.2f}"']
    if anchor:
        parts.append(f'text-anchor="{anchor}"')
    parts.append(f'font-family="{FONT}" font-size="{size:g}"')
    if weight:
        parts.append(f'font-weight="{weight}"')
    parts.append(f'fill="{fill}">{_escape(content)}</text>')
    return " ".join(parts)


def _ramp_color(value: float, maximum: float) -> str:
    """Pick a sequential step for a count, light for low and dark for high."""
    if maximum <= 0:
        return SEQUENTIAL_RAMP[0]
    fraction = max(0.0, min(1.0, value / maximum))
    index = min(len(SEQUENTIAL_RAMP) - 1, int(fraction * len(SEQUENTIAL_RAMP)))
    return SEQUENTIAL_RAMP[index]


def write_sensorimotor_running_svg(
    output: Path = STATIC_OUTPUT,
    data_path: Path = DATA_PATH,
    provenance_path: Path = PROVENANCE_PATH,
) -> Path:
    """Render the sensorimotor locomotion supplementary figure to ``output``."""
    payload = load_running_data(data_path, provenance_path)
    sessions = [record for record in payload["sessions"] if "context" in record]
    if not sessions:
        raise RuntimeError("Locomotion figure has no sessions with a running series.")
    modality_order = [
        modality
        for modality in MODALITY_LABELS
        if any(record.get("modality") == modality for record in sessions)
    ]
    if not modality_order:
        modality_order = [None]
    grouped: list[tuple[str | None, list[dict]]] = []
    for modality in modality_order:
        rows = [
            record
            for record in sessions
            if modality is None or record.get("modality") == modality
        ]
        rows.sort(key=lambda record: -record["context"]["block"]["mean_cm_s"])
        if rows:
            grouped.append((modality, rows))
    sessions = [record for _modality, rows in grouped for record in rows]
    default_key = f"{DEFAULT_RUNNING_THRESHOLD_CM_S:g}"
    thresholds = [f"{value:g}" for value in RUNNING_THRESHOLDS_CM_S]

    width = 1200
    row_height = 22
    group_header_height = 26
    label_x = 96
    # Values live in fixed right-aligned columns rather than tracking the bar
    # ends: with an 800x dynamic range, bar-anchored labels collide with the
    # threshold and minimum-trial reference lines.
    panel_a_x, panel_a_w = 176, 290
    panel_a_value_x = 524
    panel_b_x, panel_b_w = 556, 216
    panel_c_x, panel_c_w = 818, 300
    top = 196
    rows_bottom = (
        top
        + len(sessions) * row_height
        + len(grouped) * group_header_height
    )

    speed_max = max(
        record["context"]["block"]["mean_cm_s"] for record in sessions
    )
    trial_max = max(
        record["context"]["mismatch_trials"] for record in sessions
    )
    event_order = [
        label
        for label in EVENT_ORDER
        if any(label in r["context"]["thresholds"][default_key]["per_label"] for r in sessions)
    ] or sorted(sessions[0]["context"]["thresholds"][default_key]["per_label"])

    svg: list[str] = []

    # --- panel headings -------------------------------------------------
    svg.append(_text(label_x, top - 52, "A", size=19, fill=INK_PRIMARY, weight="700"))
    svg.append(
        _text(
            panel_a_x,
            top - 52,
            "Block mean forward speed",
            size=15,
            fill=INK_PRIMARY,
            weight="600",
        )
    )
    svg.append(_text(panel_a_x, top - 33, "cm/s during the sensorimotor block"))
    svg.append(_text(panel_b_x, top - 52, "B", size=19, fill=INK_PRIMARY, weight="700"))
    svg.append(
        _text(
            panel_b_x + 20,
            top - 52,
            "Qualifying trials by threshold",
            size=15,
            fill=INK_PRIMARY,
            weight="600",
        )
    )
    svg.append(
        _text(
            panel_b_x + 20, top - 33, f"of {trial_max} mismatch trials, cm/s gate"
        )
    )
    svg.append(_text(panel_c_x, top - 52, "C", size=19, fill=INK_PRIMARY, weight="700"))
    svg.append(
        _text(
            panel_c_x + 20,
            top - 52,
            "Qualifying trials per event type",
            size=15,
            fill=INK_PRIMARY,
            weight="600",
        )
    )
    svg.append(
        _text(
            panel_c_x + 20,
            top - 33,
            f"of 35 each, at the {DEFAULT_RUNNING_THRESHOLD_CM_S:g} cm/s gate",
        )
    )

    # --- panel A axis ---------------------------------------------------
    for value in (0, 20, 40, 60, 80):
        if value > speed_max * 1.08:
            continue
        x = panel_a_x + value / (speed_max * 1.08) * panel_a_w
        svg.append(
            f'<line x1="{x:.2f}" y1="{top - 12}" x2="{x:.2f}" y2="{rows_bottom}" '
            f'stroke="{GRID_COLOR}" stroke-width="1" stroke-dasharray="4 5"/>'
        )
        svg.append(_text(x, top - 18, str(value), anchor="middle"))

    threshold_x = panel_a_x + DEFAULT_RUNNING_THRESHOLD_CM_S / (speed_max * 1.08) * panel_a_w
    svg.append(
        f'<line x1="{threshold_x:.2f}" y1="{top - 12}" x2="{threshold_x:.2f}" '
        f'y2="{rows_bottom}" stroke="{UNAVAILABLE_COLOR}" stroke-width="1.5" '
        'stroke-dasharray="5 4"/>'
    )

    # --- panel B column headers ----------------------------------------
    cell_w = panel_b_w / len(thresholds)
    for index, key in enumerate(thresholds):
        cx = panel_b_x + index * cell_w + cell_w / 2
        svg.append(_text(cx, top - 14, f"≥{key}", anchor="middle"))

    # --- panel C column headers -----------------------------------------
    event_cell_w = panel_c_w / len(event_order)
    for index, label in enumerate(event_order):
        cx = panel_c_x + index * event_cell_w + event_cell_w / 2
        svg.append(
            _text(cx, top - 14, EVENT_HEADERS.get(label, label), anchor="middle")
        )

    # --- rows -----------------------------------------------------------
    y_cursor = top
    row_index = 0
    for modality, group_rows in grouped:
        label = MODALITY_LABELS.get(modality, "Sessions") if modality else "Sessions"
        # Opaque backing so the panel A gridlines and threshold rule do not
        # strike through the group label.
        svg.append(
            f'<rect x="{label_x - 8}" y="{y_cursor}" '
            f'width="{width - label_x - 66}" height="{group_header_height}" '
            f'fill="{SURFACE}"/>'
        )
        svg.append(
            _text(
                label_x,
                y_cursor + group_header_height - 9,
                f"{label} — {len(group_rows)} sessions",
                fill=INK_PRIMARY,
                weight="700",
            )
        )
        y_cursor += group_header_height

        for record in group_rows:
            y = y_cursor
            centre = y + row_height / 2
            block = record["context"]["block"]
            entry = record["context"]["thresholds"][default_key]
            index = row_index
            row_index += 1
            y_cursor += row_height

            if index % 2 == 0:
                svg.append(
                    f'<rect x="{label_x - 8}" y="{y}" width="{width - label_x - 66}" '
                    f'height="{row_height}" fill="#F7F8F8"/>'
                )

            svg.append(
                _text(
                    label_x,
                    centre + 4,
                    str(record["subject"]),
                    fill=INK_TICK,
                    weight="600",
                )
            )

            # Panel A — mean speed bar with the median as an inner tick.
            bar_w = block["mean_cm_s"] / (speed_max * 1.08) * panel_a_w
            bar_h = 11
            svg.append(
                f'<rect x="{panel_a_x}" y="{centre - bar_h / 2:.2f}" '
                f'width="{max(bar_w, 1.0):.2f}" height="{bar_h}" rx="3" '
                f'fill="{SPEED_COLOR}"/>'
            )
            svg.append(
                _text(
                    panel_a_value_x,
                    centre + 4,
                    f"{block['mean_cm_s']:.2f}",
                    fill=INK_TICK,
                    anchor="end",
                )
            )

            # Panel B — sequential cells, one per threshold.
            for t_index, key in enumerate(thresholds):
                count = record["context"]["thresholds"][key]["qualifying_trials"]
                cx = panel_b_x + t_index * cell_w
                fill = _ramp_color(count, trial_max)
                svg.append(
                    f'<rect x="{cx + 1:.2f}" y="{y + 3}" width="{cell_w - 2:.2f}" '
                    f'height="{row_height - 6}" rx="3" fill="{fill}"/>'
                )
                label_fill = SURFACE if count > trial_max * 0.6 else INK_TICK
                svg.append(
                    _text(
                        cx + cell_w / 2,
                        centre + 4,
                        str(count),
                        fill=label_fill,
                        anchor="middle",
                    )
                )

            # Panel C — qualifying trials for each mismatch event type. Status
            # fill, not magnitude: whether that event type is analysable at all.
            for e_index, label in enumerate(event_order):
                count = entry["per_label"].get(label, 0)
                cx = panel_c_x + e_index * event_cell_w
                passes = count >= MINIMUM_QUALIFYING_TRIALS
                fill = AVAILABLE_COLOR if passes else UNAVAILABLE_COLOR
                svg.append(
                    f'<rect x="{cx + 1:.2f}" y="{y + 3}" width="{event_cell_w - 2:.2f}" '
                    f'height="{row_height - 6}" rx="3" fill="{fill}" '
                    f'fill-opacity="{0.92 if passes else 0.82:g}"/>'
                )
                svg.append(
                    _text(
                        cx + event_cell_w / 2,
                        centre + 4,
                        str(count),
                        fill=SURFACE,
                        anchor="middle",
                    )
                )

    svg.append(
        f'<line x1="{panel_a_x}" y1="{rows_bottom}" x2="{panel_a_x + panel_a_w}" '
        f'y2="{rows_bottom}" stroke="{AXIS_COLOR}" stroke-width="1.5"/>'
    )

    # --- legend ---------------------------------------------------------
    legend_y = rows_bottom + 34
    for offset, (colour, label) in enumerate(
        (
            (
                AVAILABLE_COLOR,
                f"Event type reaches the {MINIMUM_QUALIFYING_TRIALS}-trial minimum",
            ),
            (UNAVAILABLE_COLOR, "Below the minimum: not analysable"),
        )
    ):
        lx = label_x + offset * 330
        svg.append(
            f'<rect x="{lx}" y="{legend_y - 9}" width="13" height="13" rx="3" '
            f'fill="{colour}"/>'
        )
        svg.append(_text(lx + 20, legend_y + 2, label))
    svg.append(
        _text(
            label_x + 700,
            legend_y + 2,
            "Panel B: darker is more qualifying trials",
        )
    )

    cohort = payload.get("cohort", {})
    available = (
        cohort.get("by_threshold", {}).get(default_key, {}).get("sessions_available")
    )
    stationary = cohort.get("stationary_median_sessions")
    median = cohort.get("block_mean_cm_s_median")

    height = int(legend_y + 34)
    header = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        'aria-labelledby="title description">',
        '<title id="title">Locomotion during the sensorimotor mismatch block</title>',
        '<desc id="description">Per session, the block mean forward speed, the number '
        'of mismatch trials in which the animal was running at each threshold, and the '
        'number of trials surviving in the worst event type, which limits any '
        'per-event analysis.</desc>',
        f'<rect width="{width}" height="{height}" fill="{SURFACE}"/>',
        _text(
            label_x,
            52,
            "Locomotion during the sensorimotor mismatch block",
            size=26,
            fill=INK_PRIMARY,
            weight="650",
        ),
        _text(
            label_x,
            78,
            "Optic flow is generated by locomotion, so a stationary animal has no flow "
            "to decouple and the mismatch is not a stimulus",
            size=14.5,
        ),
        _text(
            label_x,
            100,
            f"A trial qualifies when mean forward speed reaches the threshold in both "
            f"the {1000 * 0.343:.0f} ms pre-event window and the mismatch window",
            size=12.5,
        ),
        _text(
            label_x,
            120,
            (
                f"Median session speed {median:.2f} cm/s; "
                f"{stationary} of {len(sessions)} sessions have a median of 0.00 cm/s; "
                f"{available} sessions clear the minimum in all four event types "
                f"at {DEFAULT_RUNNING_THRESHOLD_CM_S:g} cm/s"
            )
            if median is not None and stationary is not None and available is not None
            else f"{len(sessions)} sessions with a processed running series",
            size=12.5,
        ),
    ]

    output.parent.mkdir(parents=True, exist_ok=True)
    write_svg_output(output, header + svg + ["</svg>"])
    return output


def write_sensorimotor_running_html(
    output: Path = INTERACTIVE_OUTPUT,
    data_path: Path = DATA_PATH,
    provenance_path: Path = PROVENANCE_PATH,
) -> Path:
    """Render the interactive locomotion table to ``output``."""
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = load_running_data(data_path, provenance_path)
    template = (JAVASCRIPT_DIR / "sensorimotor-running.html").read_text(
        encoding="utf-8"
    )
    stylesheet = load_figure_stylesheet("sensorimotor-running.css")
    javascript = (JAVASCRIPT_DIR / "sensorimotor-running.js").read_text(
        encoding="utf-8"
    )
    html = (
        template.replace("__SENSORIMOTOR_RUNNING_CSS__", stylesheet)
        .replace(
            "__SENSORIMOTOR_RUNNING_DATA__",
            json.dumps(
                payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
            ),
        )
        .replace("__SENSORIMOTOR_RUNNING_JS__", javascript)
        .replace("__EMBED_AUTO_HEIGHT_JS__", load_embed_auto_height())
    )
    output.write_text(html, encoding="utf-8", newline="\n")
    return output
