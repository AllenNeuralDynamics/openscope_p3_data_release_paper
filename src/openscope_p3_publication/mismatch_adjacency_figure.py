"""Supplementary figure: consecutive-mismatch adjacency in the P3 context blocks.

Renders the committed ``mismatch-adjacency.json`` intermediate as a static SVG.
Colour carries one meaning only — whether a mismatch event followed another
mismatch — so event identity is encoded positionally and by direct label.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .figures import (
    REPO_ROOT,
    write_svg_output,
)

DATA_PATH = REPO_ROOT / "figure_sources" / "data" / "mismatch-adjacency.json"
PROVENANCE_PATH = DATA_PATH.with_suffix(".provenance.json")
STATIC_OUTPUT = (
    REPO_ROOT
    / "images"
    / "figures"
    / "generated"
    / "supplementary-mismatch-adjacency.svg"
)

# Colour carries adjacency, never event identity. Validated pair from the
# repository palette: CVD ΔE 14.2 (protan), normal-vision ΔE 21.0, contrast pass.
ADJACENT_COLOR = "#B16027"
DIFFERENT_TYPE_COLOR = "#2A788E"
ISOLATED_COLOR = "#9AA29F"
INK_PRIMARY = "#263033"
INK_SECONDARY = "#68706E"
INK_TICK = "#303536"
AXIS_COLOR = "#69716F"
GRID_COLOR = "#D0D4D2"
SURFACE = "#FFFFFF"
FONT = "Source Sans 3, sans-serif"

CONTEXT_LABELS = {
    "standard": "Standard oddball",
    "sequence": "Sequence",
    "duration": "Duration",
    "sensorimotor": "Sensorimotor",
}
# Interval buckets per unit. Row-based contexts count presentations or sequences;
# sensorimotor counts elapsed seconds.
ROW_BUCKETS = ((1, 1, "1"), (2, 2, "2"), (3, 3, "3"), (4, 5, "4–5"),
               (6, 10, "6–10"), (11, None, ">10"))
SECOND_BUCKETS = ((0.0, 0.5, "<0.5"), (0.5, 1.0, "0.5–1"), (1.0, 2.0, "1–2"),
                  (2.0, 5.0, "2–5"), (5.0, 10.0, "5–10"), (10.0, None, ">10"))


def load_adjacency_data(
    data_path: Path = DATA_PATH,
    provenance_path: Path = PROVENANCE_PATH,
) -> dict[str, Any]:
    """Load the committed intermediate and attach its provenance."""
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    if "contexts" not in payload or not payload["contexts"]:
        raise RuntimeError(f"{data_path} has no context records.")
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
    size: float,
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


def _bucket_counts(intervals: list[float], unit: str) -> list[tuple[str, int, bool]]:
    """Bin intervals, flagging the bucket that corresponds to an adjacent event."""
    if unit == "seconds":
        out = []
        for index, (low, high, label) in enumerate(SECOND_BUCKETS):
            count = sum(
                1
                for value in intervals
                if value >= low and (high is None or value < high)
            )
            # Adjacency for sensorimotor is < 2 s, i.e. the first three buckets.
            out.append((label, count, index < 3))
        return out
    out = []
    for low, high, label in ROW_BUCKETS:
        count = sum(
            1
            for value in intervals
            if value >= low and (high is None or value <= high)
        )
        out.append((label, count, low == 1))
    return out


def _panel_a(
    contexts: dict[str, Any],
    order: list[str],
    left: int,
    top: int,
    plot_width: int,
) -> tuple[list[str], float]:
    """Realised mismatch schedule: one timeline per context, adjacency highlighted."""
    svg: list[str] = []
    row_height = 44
    tick_height = 15
    y = top

    svg.append(_text(left, y - 30, "A", size=19, fill=INK_PRIMARY, weight="700"))
    svg.append(
        _text(
            left + 22,
            y - 30,
            "Realised mismatch schedule within each context block",
            size=15,
            fill=INK_PRIMARY,
            weight="600",
        )
    )
    svg.append(
        _text(
            left + 22,
            y - 11,
            "Each tick is one mismatch event, positioned by time within the block",
            size=12.5,
        )
    )

    for context in order:
        entry = contexts[context]
        events = entry["events"]
        offsets = [event["onset_offset_seconds"] for event in events]
        span = max(offsets) if offsets else 1.0
        baseline = y + row_height - 14

        svg.append(
            _text(
                left,
                baseline - tick_height - 8,
                CONTEXT_LABELS.get(context, context),
                size=12.5,
                fill=INK_TICK,
                weight="600",
            )
        )
        svg.append(
            f'<line x1="{left}" y1="{baseline:.2f}" x2="{left + plot_width}" '
            f'y2="{baseline:.2f}" stroke="{GRID_COLOR}" stroke-width="1.5"/>'
        )

        for event in events:
            x = left + (event["onset_offset_seconds"] / span) * plot_width
            if event["adjacent"]:
                colour = ADJACENT_COLOR if event["same_type"] else DIFFERENT_TYPE_COLOR
                height, stroke_width, opacity = tick_height, 2.0, 1.0
            else:
                colour, height, stroke_width, opacity = ISOLATED_COLOR, 8, 1.5, 0.75
            svg.append(
                f'<line x1="{x:.2f}" y1="{baseline:.2f}" x2="{x:.2f}" '
                f'y2="{baseline - height:.2f}" stroke="{colour}" '
                f'stroke-width="{stroke_width:g}" stroke-opacity="{opacity:g}"/>'
            )

        adjacent = entry["summary"]["adjacent_count"]
        total = entry["summary"]["mismatch_trials"]
        svg.append(
            _text(
                left + plot_width + 10,
                baseline - 3,
                f"{adjacent}/{total}",
                size=12.5,
                fill=INK_TICK,
                weight="600",
            )
        )
        svg.append(
            _text(
                left,
                baseline + 16,
                "0 s",
                size=12,
            )
        )
        svg.append(
            _text(
                left + plot_width,
                baseline + 16,
                f"{span / 60:.0f} min",
                size=12,
                anchor="end",
            )
        )
        y += row_height + 20

    return svg, y


def _panel_b(
    contexts: dict[str, Any],
    order: list[str],
    left: int,
    top: float,
    plot_width: int,
) -> tuple[list[str], float]:
    """Interval to the previous mismatch, binned, per context."""
    svg: list[str] = []
    svg.append(_text(left, top, "B", size=19, fill=INK_PRIMARY, weight="700"))
    svg.append(
        _text(
            left + 22,
            top,
            "Interval to the previous mismatch event",
            size=15,
            fill=INK_PRIMARY,
            weight="600",
        )
    )
    svg.append(
        _text(
            left + 22,
            top + 19,
            "Highlighted bars are intervals short enough to count as adjacent",
            size=12.5,
        )
    )

    column_gap = 34
    column_width = (plot_width - column_gap * (len(order) - 1)) / len(order)
    chart_top = top + 40
    chart_height = 120

    for index, context in enumerate(order):
        entry = contexts[context]
        unit = entry["summary"]["interval_unit"]
        intervals = [
            event["interval"] for event in entry["events"] if event["interval"] is not None
        ]
        buckets = _bucket_counts(intervals, unit)
        y_max = max((count for _label, count, _flag in buckets), default=1) or 1
        x0 = left + index * (column_width + column_gap)

        svg.append(
            _text(
                x0,
                chart_top - 8,
                f"{CONTEXT_LABELS.get(context, context)} ({unit})",
                size=12,
                fill=INK_TICK,
                weight="600",
            )
        )

        bar_gap = 4
        bar_width = (column_width - bar_gap * (len(buckets) - 1)) / len(buckets)
        baseline = chart_top + chart_height
        for bar_index, (label, count, is_adjacent) in enumerate(buckets):
            height = (count / y_max) * chart_height
            bx = x0 + bar_index * (bar_width + bar_gap)
            colour = ADJACENT_COLOR if is_adjacent else ISOLATED_COLOR
            if height > 0:
                radius = min(4.0, bar_width / 2, height)
                svg.append(
                    f'<rect x="{bx:.2f}" y="{baseline - height:.2f}" '
                    f'width="{bar_width:.2f}" height="{height:.2f}" rx="{radius:.2f}" '
                    f'fill="{colour}"/>'
                )
                svg.append(
                    _text(
                        bx + bar_width / 2,
                        baseline - height - 6,
                        str(count),
                        size=12,
                        fill=INK_TICK,
                        anchor="middle",
                    )
                )
            svg.append(
                _text(
                    bx + bar_width / 2,
                    baseline + 15,
                    label,
                    size=12,
                    anchor="middle",
                )
            )
        svg.append(
            f'<line x1="{x0:.2f}" y1="{baseline:.2f}" '
            f'x2="{x0 + column_width:.2f}" y2="{baseline:.2f}" '
            f'stroke="{AXIS_COLOR}" stroke-width="1.5"/>'
        )

    return svg, chart_top + chart_height + 44


def _panel_c(
    contexts: dict[str, Any],
    order: list[str],
    left: int,
    top: float,
    plot_width: int,
) -> tuple[list[str], float]:
    """Fraction of mismatch events that follow another, split by repeat identity."""
    svg: list[str] = []
    svg.append(_text(left, top, "C", size=19, fill=INK_PRIMARY, weight="700"))
    svg.append(
        _text(
            left + 22,
            top,
            "Mismatch events preceded by another mismatch",
            size=15,
            fill=INK_PRIMARY,
            weight="600",
        )
    )
    svg.append(
        _text(
            left + 22,
            top + 19,
            "The second event is not preceded by the standard context it violates",
            size=12.5,
        )
    )

    chart_top = top + 46
    chart_height = 150
    baseline = chart_top + chart_height
    y_max = 20.0

    for value in range(0, int(y_max) + 1, 5):
        y = baseline - (value / y_max) * chart_height
        svg.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{left + plot_width}" y2="{y:.2f}" '
            f'stroke="{GRID_COLOR}" stroke-width="1" stroke-dasharray="4 5"/>'
        )
        svg.append(
            _text(left - 10, y + 4, f"{value}%", size=12, anchor="end")
        )

    slot = plot_width / len(order)
    bar_width = min(96.0, slot * 0.46)
    for index, context in enumerate(order):
        summary = contexts[context]["summary"]
        total = summary["mismatch_trials"]
        same = summary["adjacent_same_type_count"]
        different = summary["adjacent_different_type_count"]
        centre = left + slot * (index + 0.5)
        bx = centre - bar_width / 2

        different_height = (different / total * 100 / y_max) * chart_height
        same_height = (same / total * 100 / y_max) * chart_height

        # 2px surface gap between stacked segments.
        y_different = baseline - different_height
        svg.append(
            f'<rect x="{bx:.2f}" y="{y_different:.2f}" width="{bar_width:.2f}" '
            f'height="{different_height:.2f}" fill="{DIFFERENT_TYPE_COLOR}"/>'
        )
        if same_height > 0:
            y_same = y_different - 2 - same_height
            radius = min(4.0, same_height)
            svg.append(
                f'<rect x="{bx:.2f}" y="{y_same:.2f}" width="{bar_width:.2f}" '
                f'height="{same_height:.2f}" rx="{radius:.2f}" '
                f'fill="{ADJACENT_COLOR}"/>'
            )
            top_of_bar = y_same
        else:
            top_of_bar = y_different

        percent = (same + different) / total * 100
        svg.append(
            _text(
                centre,
                top_of_bar - 9,
                f"{percent:.1f}%",
                size=13,
                fill=INK_PRIMARY,
                weight="650",
                anchor="middle",
            )
        )
        svg.append(
            _text(
                centre,
                baseline + 19,
                CONTEXT_LABELS.get(context, context),
                size=12.5,
                fill=INK_TICK,
                weight="600",
                anchor="middle",
            )
        )
        svg.append(
            _text(
                centre,
                baseline + 36,
                f"{same + different} of {total}",
                size=12,
                anchor="middle",
            )
        )
        svg.append(
            _text(
                centre,
                baseline + 51,
                f"same deviant: {same}",
                size=12,
                anchor="middle",
            )
        )

    svg.append(
        f'<line x1="{left}" y1="{baseline:.2f}" x2="{left + plot_width}" '
        f'y2="{baseline:.2f}" stroke="{AXIS_COLOR}" stroke-width="1.5"/>'
    )

    # Legend — two series, so a legend is always present.
    legend_y = baseline + 74
    for offset, (colour, label) in enumerate(
        (
            (ADJACENT_COLOR, "Preceded by the same deviant type"),
            (DIFFERENT_TYPE_COLOR, "Preceded by a different deviant type"),
            (ISOLATED_COLOR, "Isolated mismatch (panels A–B)"),
        )
    ):
        lx = left + offset * 300
        svg.append(
            f'<rect x="{lx}" y="{legend_y - 9}" width="13" height="13" rx="3" '
            f'fill="{colour}"/>'
        )
        svg.append(_text(lx + 20, legend_y + 2, label, size=12))

    return svg, legend_y + 24


def write_mismatch_adjacency_svg(
    output: Path = STATIC_OUTPUT,
    data_path: Path = DATA_PATH,
    provenance_path: Path = PROVENANCE_PATH,
) -> Path:
    """Render the adjacency supplementary figure to ``output``."""
    payload = load_adjacency_data(data_path, provenance_path)
    contexts = payload["contexts"]
    order = [c for c in payload.get("context_order", sorted(contexts)) if c in contexts]
    if not order:
        raise RuntimeError("Adjacency figure has no contexts to render.")

    width = 1200
    left = 96
    right = 74
    plot_width = width - left - right

    svg_body: list[str] = []
    panel_a, y = _panel_a(contexts, order, left, 158, plot_width)
    svg_body.extend(panel_a)
    panel_b, y = _panel_b(contexts, order, left, y + 10, plot_width)
    svg_body.extend(panel_b)
    panel_c, y = _panel_c(contexts, order, left, y + 10, plot_width)
    svg_body.extend(panel_c)
    height = int(y + 26)

    sessions = ", ".join(
        f"{CONTEXT_LABELS.get(context, context).lower()} {contexts[context]['sessions']}"
        for context in order
    )
    header = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        'aria-labelledby="title description">',
        '<title id="title">Consecutive mismatch events in the predictive-processing '
        'context blocks</title>',
        '<desc id="description">Per context, the realised schedule of mismatch events, '
        'the distribution of intervals to the previous mismatch, and the percentage of '
        'mismatch events that immediately follow another mismatch, split by whether the '
        'preceding event was the same deviant type.</desc>',
        f'<rect width="{width}" height="{height}" fill="{SURFACE}"/>',
        _text(
            left,
            52,
            "Consecutive mismatch events across predictive-processing contexts",
            size=26,
            fill=INK_PRIMARY,
            weight="650",
        ),
        _text(
            left,
            78,
            "A mismatch that follows another mismatch is not preceded by the standard "
            "context it violates",
            size=14.5,
        ),
        _text(
            left,
            99,
            f"Each context block uses one pre-generated schedule identical across "
            f"sessions ({sessions})",
            size=12.5,
        ),
    ]

    output.parent.mkdir(parents=True, exist_ok=True)
    write_svg_output(output, header + svg_body + ["</svg>"])
    return output
