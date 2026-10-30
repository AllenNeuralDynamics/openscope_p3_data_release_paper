"""Shared typography for the publication's original, full-width SVG figures."""

from __future__ import annotations

import base64
import math
import re
from xml.etree import ElementTree as ET

FIGURE_FONT = "Arial, sans-serif"
PANEL_LETTER_POINTS = 9.0
PDF_FIGURE_WIDTH_MM = 170.0
PDF_FIGURE_HEIGHT_MM = 205.0
SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
_PANEL_CLASSES = {"panel-label", "raw-panel-label", "panel-title", "running-panel-label"}


def _number(value: str) -> float:
    match = re.fullmatch(r"([0-9.eE+-]+)(px|pt|in|mm|cm)?", value)
    if match is None:
        raise ValueError(f"Unsupported SVG dimension: {value!r}")
    return float(match.group(1)) * {
        None: 1, "px": 1, "pt": 96 / 72, "in": 96, "mm": 96 / 25.4, "cm": 96 / 2.54,
    }[match.group(2)]


def _dimensions(root: ET.Element) -> tuple[float, float]:
    if "viewBox" in root.attrib:
        _, _, width, height = map(float, root.get("viewBox").replace(",", " ").split())
    else:
        width, height = _number(root.attrib["width"]), _number(root.attrib["height"])
    if not math.isfinite(width + height) or min(width, height) <= 0:
        raise ValueError("Figure dimensions must be finite and positive.")
    return width, height


def _transform_scale(transform: str) -> float:
    scale = 1.0
    for name, arguments in re.findall(r"(\w+)\(([^)]+)\)", transform):
        values = [float(value) for value in re.split(r"[\s,]+", arguments.strip())]
        if name == "scale":
            scale *= abs(values[-1])
        elif name == "matrix":
            scale *= math.hypot(values[2], values[3])
    return scale


def normalize_figure_svg(svg: str) -> str:
    """Set editable text to Arial and marked panel letters to 9 pt at PDF size.

    Nested SVG viewports and SVG images retain their geometry. Raster artwork is
    not modified. Panel letters are explicitly identified by class or Matplotlib
    group ID, so anatomical direction markers and ordinary single-letter labels
    are not mistaken for panel lettering.
    """
    root = ET.fromstring(svg)
    width, height = _dimensions(root)
    points_per_unit = min(
        PDF_FIGURE_WIDTH_MM / width, PDF_FIGURE_HEIGHT_MM / height,
    ) * 72 / 25.4

    def visit(node: ET.Element, scale: float, panel_group: bool = False) -> None:
        tag = node.tag.rsplit("}", 1)[-1]
        scale *= _transform_scale(node.get("transform", ""))
        identifier = node.get("id", "")
        marked = (
            bool(_PANEL_CLASSES.intersection(node.get("class", "").split()))
            or "data-panel-letter" in node.attrib
        )
        panel_group = panel_group or identifier.startswith("panel-label-") or marked
        if tag in {"text", "tspan"}:
            style = dict(re.findall(r"([\w-]+)\s*:\s*([^;]+)", node.get("style", "")))
            node.set("font-family", FIGURE_FONT)
            style.pop("font-family", None)
            style["font-family"] = FIGURE_FONT
            text = "".join(node.itertext()).strip()
            if re.fullmatch(r"[A-P]", text) and panel_group:
                size = PANEL_LETTER_POINTS / scale
                node.set("font-size", f"{size:.8f}")
                node.set("font-weight", "700")
                style.pop("font-size", None)
                style.pop("font-weight", None)
                style["font-size"] = f"{size:.8f}px"
                style["font-weight"] = "700"
                node.set("data-panel-letter", text)
                if "y" in node.attrib and _number(node.get("y")) < size:
                    node.set("y", f"{size:.8f}")
            node.set("style", "; ".join(f"{key}: {value}" for key, value in style.items()))
        if tag == "image":
            attribute = f"{{{XLINK_NS}}}href" if f"{{{XLINK_NS}}}href" in node.attrib else "href"
            href = node.get(attribute, "")
            if href.startswith("data:image/svg+xml;base64,"):
                child = ET.fromstring(base64.b64decode(href.split(",", 1)[1]))
                child_width, child_height = _dimensions(child)
                child_scale = scale * min(
                    _number(node.attrib["width"]) / child_width,
                    _number(node.attrib["height"]) / child_height,
                )
                visit(child, child_scale)
                encoded = base64.b64encode(ET.tostring(child, encoding="utf-8")).decode()
                node.set(attribute, "data:image/svg+xml;base64," + encoded)
        for child in node:
            child_scale = scale
            if child.tag == f"{{{SVG_NS}}}svg":
                child_width, child_height = _dimensions(child)
                child_scale *= min(
                    _number(child.get("width", str(child_width))) / child_width,
                    _number(child.get("height", str(child_height))) / child_height,
                )
            visit(child, child_scale, panel_group)

    ET.register_namespace("", SVG_NS)
    ET.register_namespace("xlink", XLINK_NS)
    visit(root, points_per_unit)
    root.set("data-publication-font", "Arial")
    root.set("data-panel-letter-points", f"{PANEL_LETTER_POINTS:g}")
    return ET.tostring(root, encoding="unicode").rstrip() + "\n"
