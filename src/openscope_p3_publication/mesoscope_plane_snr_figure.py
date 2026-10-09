"""Mesoscope ROI signal-to-noise by imaging plane.

Builds the interactive page and its static counterpart from the committed
intermediate ``figure_sources/data/mesoscope-plane-snr.json``. Reading that
intermediate needs no network and no credentials, so ``build-publication-figures``
reproduces both outputs byte-for-byte from a fresh clone.

The intermediate itself is produced off-repo by
``scripts/extract_mesoscope_plane_snr.py``, which reads the processed NWB from
``s3://aind-open-data`` on a cluster; see the ``.provenance.json`` sidecar.

Three signal-to-noise definitions are carried side by side, named for what they
measure rather than for who proposed them; the definition table in the
intermediate records each one's formula and origin.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
from pathlib import Path

from .figures import (
    FIGURE_SANS_FONT,
    FIGURE_TYPE_SCALE,
    JAVASCRIPT_DIR,
    REPO_ROOT,
    load_figure_controls,
    load_figure_stylesheet,
    normalized_text_bytes,
    write_svg_output,
)

DATA_PATH = REPO_ROOT / "figure_sources" / "data" / "mesoscope-plane-snr.json"
PROVENANCE_PATH = DATA_PATH.with_suffix(".provenance.json")
INTERACTIVE_OUTPUT = REPO_ROOT / "interactive" / "mesoscope-plane-snr.html"
STATIC_OUTPUT = (
    REPO_ROOT
    / "images"
    / "figures"
    / "generated"
    / "supplementary-mesoscope-plane-snr.svg"
)

SCHEMA_VERSION = 1
METRICS = (
    ("frac_events_gt4sd", "Events > 4 SD (fraction)", 3),
    ("event_amplitude_snr", "Event amplitude SNR", 1),
    ("percentile_range_snr", "Percentile-range SNR", 1),
)
STRUCTURE_COLOURS = {"VISp": "#167f8c", "VISl": "#b16027"}
# Perceptually ordered ramp, shared with the interactive map so a shade means
# the same value in both views.
RAMP = ((68, 1, 84), (49, 104, 142), (31, 158, 137), (109, 205, 89), (253, 231, 37))


def load_mesoscope_plane_snr(
    path: Path = DATA_PATH,
    provenance_path: Path = PROVENANCE_PATH,
) -> dict:
    source_bytes = path.read_bytes()
    payload = json.loads(source_bytes)
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if (
        payload.get("schemaVersion") != SCHEMA_VERSION
        or hashlib.sha256(source_bytes).hexdigest() != provenance.get("vendored_sha256")
        or payload.get("sessionId") != provenance.get("session_id")
    ):
        raise RuntimeError("Mesoscope plane-SNR snapshot provenance is invalid.")

    # An edited extractor whose output was never refreshed is a silent stale-figure
    # bug, so the scripts are pinned alongside the snapshot they produced.
    for key in ("script", "merge_script"):
        record = provenance[key]
        script_path = REPO_ROOT / record["path"]
        if (
            hashlib.sha256(normalized_text_bytes(script_path)).hexdigest()
            != record["sha256"]
        ):
            raise RuntimeError(
                f"Mesoscope plane-SNR {key} checksum does not match provenance."
            )

    planes = payload.get("planes", [])
    if not planes:
        raise RuntimeError("Mesoscope plane-SNR snapshot contains no planes.")
    for plane in planes:
        if len(plane["rois"]) != plane["nRois"]:
            raise RuntimeError(
                f"Plane {plane['plane']} declares {plane['nRois']} ROIs "
                f"but carries {len(plane['rois'])}."
            )
    return payload


def escape_text(value: object) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def quantile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return float("nan")
    position = (len(sorted_values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    return sorted_values[lower] + (
        sorted_values[upper] - sorted_values[lower]
    ) * (position - lower)


def spearman(xs: list[float], ys: list[float]) -> float:
    """Rank correlation with ties averaged.

    Reported per definition so a reader can see whether a definition tracks ROI
    size rather than signal quality; mask area varies with depth and with
    segmentation quality, so a size-dependent definition partly re-reports those.
    """
    count = len(xs)
    if count < 3:
        return float("nan")

    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(count), key=lambda index: values[index])
        out = [0.0] * count
        start = 0
        while start < count:
            stop = start
            while (
                stop + 1 < count
                and values[order[stop + 1]] == values[order[start]]
            ):
                stop += 1
            average = (start + stop) / 2.0 + 1.0
            for index in range(start, stop + 1):
                out[order[index]] = average
            start = stop + 1
        return out

    rx = ranks(xs)
    ry = ranks(ys)
    mean_x = sum(rx) / count
    mean_y = sum(ry) / count
    numerator = sum((a - mean_x) * (b - mean_y) for a, b in zip(rx, ry, strict=True))
    denominator = math.sqrt(
        sum((a - mean_x) ** 2 for a in rx) * sum((b - mean_y) ** 2 for b in ry)
    )
    return numerator / denominator if denominator else float("nan")


def ramp_colour(fraction: float) -> str:
    if not math.isfinite(fraction):
        return "#68716f"
    fraction = min(1.0, max(0.0, fraction))
    position = fraction * (len(RAMP) - 1)
    index = min(len(RAMP) - 2, int(position))
    weight = position - index
    lower = RAMP[index]
    upper = RAMP[index + 1]
    channels = (
        round(lower[channel] + weight * (upper[channel] - lower[channel]))
        for channel in range(3)
    )
    return "#{:02x}{:02x}{:02x}".format(*channels)


def finite_metric_values(plane: dict, key: str) -> list[float]:
    return sorted(
        value
        for value in (roi[key] for roi in plane["rois"])
        if value is not None and math.isfinite(value)
    )


def build_static_svg(payload: dict) -> list[str]:
    """Per-plane distribution of each definition.

    One row per imaging plane, in depth order within visual area: median,
    interquartile box and 5th-95th percentile whisker over every ROI in that
    plane. Panels share no axis, because the three definitions are on different
    scales; each carries its own pooled 1st-99th percentile range.
    """
    planes = payload["planes"]
    plane_count = len(planes)

    pad_left, pad_right, pad_top, pad_bottom = 140, 22, 128, 76
    panel_width, panel_gap, row_height = 316, 45, 34
    panel_height = plane_count * row_height
    width = (
        pad_left
        + len(METRICS) * panel_width
        + (len(METRICS) - 1) * panel_gap
        + pad_right
    )
    height = pad_top + panel_height + pad_bottom
    total_rois = sum(plane["nRois"] for plane in planes)

    def text(
        x: float,
        y: float,
        size: int,
        body: str,
        fill: str = "#293133",
        anchor: str | None = None,
        weight: str | None = None,
    ) -> str:
        parts = [
            f'<text x="{x:.1f}" y="{y:.1f}"',
            f'font-family="{FIGURE_SANS_FONT}"',
            f'font-size="{size}"',
            f'fill="{fill}"',
        ]
        if anchor:
            parts.append(f'text-anchor="{anchor}"')
        if weight:
            parts.append(f'font-weight="{weight}"')
        return " ".join(parts) + f">{body}</text>"

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="{FIGURE_SANS_FONT}" role="img" '
        f'aria-label="Per-plane distribution of three ROI signal-to-noise '
        f'definitions across {plane_count} mesoscope imaging planes">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        text(
            pad_left,
            32,
            FIGURE_TYPE_SCALE["heading"],
            "ROI signal-to-noise by imaging plane, three definitions",
            weight="600",
        ),
        text(
            pad_left,
            56,
            FIGURE_TYPE_SCALE["label"],
            f'Session {escape_text(payload["sessionId"])} &#183; {total_rois} ROIs '
            f"over {plane_count} simultaneously-acquired planes.",
            fill="#68716f",
        ),
        text(
            pad_left,
            76,
            FIGURE_TYPE_SCALE["label"],
            "Planes ordered by depth within area. Dot, median; bar, interquartile "
            "range; line, 5th&#8211;95th percentile.",
            fill="#68716f",
        ),
    ]

    for index, plane in enumerate(planes):
        row_centre = pad_top + index * row_height + row_height / 2
        colour = STRUCTURE_COLOURS.get(plane["structure"], "#68716f")
        depth = (
            ""
            if plane["depthUm"] is None
            else f' &#183; {round(plane["depthUm"])} &#181;m'
        )
        svg.append(
            text(
                pad_left - 14,
                row_centre + 1,
                FIGURE_TYPE_SCALE["label"],
                escape_text(plane["plane"]),
                fill=colour,
                anchor="end",
                weight="600",
            )
        )
        svg.append(
            text(
                pad_left - 14,
                row_centre + 15,
                FIGURE_TYPE_SCALE["small"],
                f'{plane["nRois"]} ROIs{depth}',
                fill="#8d9693",
                anchor="end",
            )
        )

    for metric_index, (key, label, digits) in enumerate(METRICS):
        panel_left = pad_left + metric_index * (panel_width + panel_gap)
        pooled = sorted(
            value
            for plane in planes
            for value in finite_metric_values(plane, key)
        )
        low = quantile(pooled, 0.01)
        high = quantile(pooled, 0.99)
        if not high > low:
            high = low + 1.0

        def scale_x(
            value: float,
            left: float = panel_left,
            low: float = low,
            high: float = high,
        ) -> float:
            return left + min(1.0, max(0.0, (value - low) / (high - low))) * panel_width

        svg.append(
            text(
                panel_left + panel_width / 2,
                112,
                FIGURE_TYPE_SCALE["modality"],
                escape_text(label),
                anchor="middle",
                weight="600",
            )
        )
        for fraction in (0.0, 0.5, 1.0):
            grid_x = panel_left + fraction * panel_width
            svg.append(
                f'<line x1="{grid_x:.1f}" y1="{pad_top}" x2="{grid_x:.1f}" '
                f'y2="{pad_top + panel_height}" stroke="#e4e8e6" stroke-width="1"/>'
            )
            svg.append(
                text(
                    grid_x,
                    pad_top + panel_height + 20,
                    FIGURE_TYPE_SCALE["small"],
                    f"{low + fraction * (high - low):.{digits}f}",
                    fill="#68716f",
                    anchor="middle",
                )
            )

        areas: list[float] = []
        values: list[float] = []
        for index, plane in enumerate(planes):
            row_centre = pad_top + index * row_height + row_height / 2
            plane_values = finite_metric_values(plane, key)
            if not plane_values:
                continue
            q05, q25, q50, q75, q95 = (
                quantile(plane_values, fraction)
                for fraction in (0.05, 0.25, 0.5, 0.75, 0.95)
            )
            colour = ramp_colour((q50 - low) / (high - low))
            svg.append(
                f'<line x1="{scale_x(q05):.1f}" y1="{row_centre:.1f}" '
                f'x2="{scale_x(q95):.1f}" y2="{row_centre:.1f}" '
                f'stroke="#b9c0bd" stroke-width="1.3"/>'
            )
            svg.append(
                f'<rect x="{scale_x(q25):.1f}" y="{row_centre - 6:.1f}" '
                f'width="{max(1.0, scale_x(q75) - scale_x(q25)):.1f}" height="12" '
                f'rx="2" fill="{colour}" fill-opacity="0.45" stroke="{colour}" '
                f'stroke-width="1"/>'
            )
            svg.append(
                f'<circle cx="{scale_x(q50):.1f}" cy="{row_centre:.1f}" r="4.2" '
                f'fill="{colour}" stroke="#ffffff" stroke-width="1"/>'
            )
            for roi in plane["rois"]:
                value = roi[key]
                area = roi["roi_area_pix"]
                if value is None or area is None or not math.isfinite(value):
                    continue
                values.append(value)
                areas.append(area)

        svg.append(
            text(
                panel_left + panel_width / 2,
                pad_top + panel_height + 44,
                FIGURE_TYPE_SCALE["label"],
                f"Spearman &#961; vs ROI area = {spearman(areas, values):.2f}",
                fill="#68716f",
                anchor="middle",
            )
        )

    reference = planes[0]
    svg.append(
        text(
            pad_left,
            height - 14,
            FIGURE_TYPE_SCALE["small"],
            f"Each definition is computed over the full "
            f'{reference["durationSeconds"] / 60:.0f}-minute recording at '
            f'{1 / reference["dtSeconds"]:.2f} Hz; event-based definitions use the '
            f"processing pipeline&#8217;s own event trace.",
            fill="#8d9693",
        )
    )
    svg.append("</svg>")
    return svg


def write_mesoscope_plane_snr_svg(
    output: Path = STATIC_OUTPUT,
    payload: dict | None = None,
) -> Path:
    payload = load_mesoscope_plane_snr() if payload is None else payload
    output.parent.mkdir(parents=True, exist_ok=True)
    write_svg_output(output, build_static_svg(payload))
    return output


def write_mesoscope_plane_snr_html(
    output: Path = INTERACTIVE_OUTPUT,
    static_output: Path = STATIC_OUTPUT,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = load_mesoscope_plane_snr()
    if not static_output.is_file():
        write_mesoscope_plane_snr_svg(static_output, payload)
    static_data = base64.b64encode(normalized_text_bytes(static_output)).decode()
    template = (JAVASCRIPT_DIR / "mesoscope-plane-snr.html").read_text(
        encoding="utf-8"
    )
    stylesheet = load_figure_stylesheet("mesoscope-plane-snr.css")
    javascript = (JAVASCRIPT_DIR / "mesoscope-plane-snr.js").read_text(
        encoding="utf-8"
    )
    html = (
        template.replace("__MESOSCOPE_CSS__", stylesheet)
        .replace(
            "__MESOSCOPE_DATA__",
            json.dumps(
                payload,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).replace("</", "<\\/"),
        )
        .replace(
            "__MESOSCOPE_STATIC_IMAGE__",
            f"data:image/svg+xml;base64,{static_data}",
        )
        .replace("__MESOSCOPE_JS__", javascript)
        .replace("__MESOSCOPE_CONTROLS_JS__", load_figure_controls())
    )
    output.write_text(html, encoding="utf-8", newline="\n")
    return output
