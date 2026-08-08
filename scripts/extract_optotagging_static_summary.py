#!/usr/bin/env python3
"""Extract plotted optotagging yield values from the legacy Matplotlib SVG."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = (
    REPO_ROOT
    / "figure_sources"
    / "media"
    / "optotagging"
    / "optotagging-static-legacy.svg"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "figure_sources" / "data" / "optotagging-static-summary.json"
)
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
NUMBER_PATTERN = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")


def element_by_id(root: ET.Element, identifier: str) -> ET.Element:
    element = next(
        (candidate for candidate in root.iter() if candidate.get("id") == identifier),
        None,
    )
    if element is None:
        raise RuntimeError(f"Legacy SVG is missing {identifier}.")
    return element


def comment_text(element: ET.Element) -> str:
    comments = [
        str(candidate.text).strip()
        for candidate in element.iter()
        if candidate.tag is ET.Comment and candidate.text
    ]
    if len(comments) != 1:
        raise RuntimeError(
            f"Expected one text label in {element.get('id')}; found {comments}."
        )
    return comments[0]


def axis_categories(root: ET.Element, identifier: str) -> list[str]:
    axis = element_by_id(root, identifier)
    return [
        comment_text(tick)
        for tick in axis
        if (tick.get("id") or "").startswith("xtick_")
    ]


def y_value_converter(root: ET.Element, identifier: str):
    axis = element_by_id(root, identifier)
    ticks = []
    for tick in axis:
        if not (tick.get("id") or "").startswith("ytick_"):
            continue
        label = float(comment_text(tick).replace("−", "-"))
        marker = tick.find(f".//{{{SVG_NAMESPACE}}}use")
        if marker is None or marker.get("y") is None:
            raise RuntimeError(f"Legacy SVG tick has no y coordinate: {tick.get('id')}")
        ticks.append((float(marker.get("y")), label))
    if len(ticks) < 2:
        raise RuntimeError(f"Legacy SVG axis has too few y ticks: {identifier}")
    first_y, first_value = ticks[0]
    second_y, second_value = ticks[1]
    slope = (second_value - first_value) / (second_y - first_y)
    intercept = first_value - slope * first_y
    if any(abs(intercept + slope * y - value) > 1e-6 for y, value in ticks):
        raise RuntimeError(f"Legacy SVG y axis is not linear: {identifier}")
    return lambda y: intercept + slope * y


def rectangle_top(path: ET.Element) -> float:
    coordinates = [float(value) for value in NUMBER_PATTERN.findall(path.get("d", ""))]
    if len(coordinates) < 8:
        raise RuntimeError("Legacy SVG bar path is malformed.")
    return min(coordinates[1::2])


def panel_summary(
    root: ET.Element,
    *,
    axes_id: str,
    x_axis_id: str,
    y_axis_id: str,
    maximum_sessions: int,
    expected_sessions: int | None = None,
) -> list[dict]:
    axes = element_by_id(root, axes_id)
    labels = axis_categories(root, x_axis_id)
    to_value = y_value_converter(root, y_axis_id)
    bars = []
    collections = []
    for child in axes:
        identifier = child.get("id") or ""
        if identifier.startswith("patch_"):
            path = child.find(f"{{{SVG_NAMESPACE}}}path")
            if path is not None and path.get("clip-path"):
                bars.append(to_value(rectangle_top(path)))
        elif identifier.startswith("PathCollection_"):
            uses = child.findall(f".//{{{SVG_NAMESPACE}}}use")
            counts = [round(to_value(float(use.get("y")))) for use in uses]
            if (
                not counts
                or len(counts) > maximum_sessions
                or expected_sessions is not None
                and len(counts) != expected_sessions
                or any(count < 0 for count in counts)
            ):
                raise RuntimeError(
                    f"{axes_id} {identifier} has an invalid session-count distribution."
                )
            collections.append(counts)
    if not (len(labels) == len(bars) == len(collections)):
        raise RuntimeError(
            f"Legacy SVG {axes_id} dimensions disagree: "
            f"{len(labels)} labels, {len(bars)} bars, {len(collections)} distributions."
        )

    records = []
    for label, bar_mean, counts in zip(labels, bars, collections, strict=True):
        extracted_mean = statistics.fmean(counts)
        if abs(extracted_mean - bar_mean) > 0.02:
            raise RuntimeError(
                f"Legacy SVG mean mismatch for {label}: "
                f"bar={bar_mean:.4f}, extracted={extracted_mean:.4f}."
            )
        records.append(
            {
                "label": label,
                "counts": counts,
                "mean": round(extracted_mean, 6),
                "sampled_session_count": len(counts),
            }
        )
    return records


def extract_summary(source: Path) -> dict:
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    root = ET.fromstring(source.read_bytes(), parser=parser)
    source_session_count = 60
    overall = panel_summary(
        root,
        axes_id="axes_3",
        x_axis_id="matplotlib.axis_5",
        y_axis_id="matplotlib.axis_6",
        maximum_sessions=source_session_count,
        expected_sessions=source_session_count,
    )
    major_parent = panel_summary(
        root,
        axes_id="axes_4",
        x_axis_id="matplotlib.axis_7",
        y_axis_id="matplotlib.axis_8",
        maximum_sessions=source_session_count,
    )
    structures = panel_summary(
        root,
        axes_id="axes_5",
        x_axis_id="matplotlib.axis_9",
        y_axis_id="matplotlib.axis_10",
        maximum_sessions=source_session_count,
    )
    if len(overall) != 1 or overall[0]["label"] != "All areas":
        raise RuntimeError("Legacy overall-yield panel changed.")
    return {
        "version": 1,
        "source": source.relative_to(REPO_ROOT).as_posix(),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "source_session_count": source_session_count,
        "overall": overall[0],
        "major_parent": major_parent,
        "structures": structures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    summary = extract_summary(args.input.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()