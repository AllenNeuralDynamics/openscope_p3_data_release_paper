"""Native-size matched Neuropixels/mesoscope composites from existing offline columns."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from xml.etree import ElementTree as ET

import matplotlib as mpl

from .figure_typography import FIGURE_FONT, SVG_NS, XLINK_NS, normalize_figure_svg
from .mesoscope_standard_oddball import ROOT, sha256

COLUMN_MM = 54.0
GUTTER_MM = 4.0
WIDTH_MM, HEIGHT_MM = 2 * COLUMN_MM + GUTTER_MM, 174.0
POINTS_PER_MM = 72 / 25.4
OUTPUT_DIR = ROOT / "images/figures/generated"
AUDIT_DIR = ROOT / "figure_sources/derived/standard-oddball-matched-columns"
NEUROPIXELS = OUTPUT_DIR / "neuropixels-standard-oddball-90-column.svg"
NEUROPIXELS_PROVENANCE = (
    ROOT / "figure_sources/derived/neuropixels-standard-oddball-90-column/provenance.json"
)
MESOSCOPE_PROVENANCE = ROOT / "figure_sources/derived/mesoscope-standard-oddball-90/provenance.json"
SLAP2_PROVENANCE = ROOT / "figure_sources/derived/slap2-standard-oddball-90/provenance.json"
LETTERS = {"neuropixels": dict(zip("ABC", "ACE", strict=True)),
           "mesoscope": dict(zip("ABC", "BDF", strict=True))}
THREE_LETTERS = {
    "neuropixels": dict(zip("ABC", "ADG", strict=True)),
    "mesoscope": dict(zip("ABC", "BEH", strict=True)),
    "slap2": dict(zip("AB", "CF", strict=True)),
}
THREE_WIDTH_MM = 3 * COLUMN_MM + 2 * GUTTER_MM
MAIN_LEFT_GUTTER_MM = 4.0
MAIN_WIDTH_MM = THREE_WIDTH_MM + MAIN_LEFT_GUTTER_MM
MAIN_HEIGHT_MM = HEIGHT_MM + 10.0
COHORT_SHIFT_MM = 7.1
COHORT_LETTER_SHIFT_MM = 4.6
NS = {"s": SVG_NS}
URL_REFERENCE = re.compile(r"url\(#([^)]*)\)")


def _source_column(path: Path, provenance_path: Path, output_key: str) -> ET.Element:
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    matching = [p for p in provenance["outputs"] if p[output_key] == path.name]
    if len(matching) != 1 or sha256(path) != matching[0]["sha256"]:
        raise ValueError(f"Source column checksum missing or changed: {path.name}")
    root = ET.parse(path).getroot()
    box = tuple(map(float, root.attrib["viewBox"].split()))
    if (
        root.tag != f"{{{SVG_NS}}}svg" or len(box) != 4 or box[:2] != (0, 0)
        or not all(math.isfinite(v) for v in box)
        or not math.isclose(box[2], COLUMN_MM * POINTS_PER_MM, abs_tol=1e-6)
        or not root.get("data-event-id") == "orientation_90"
    ):
        raise ValueError(f"Unsupported source column geometry/event: {path.name}")
    description = root.find("s:desc", NS)
    if description is None or not description.text:
        raise ValueError(f"Source column needs a scientific description: {path.name}")
    return root


def _place_column(
    root: ET.Element, modality: str, x_mm: float,
    *, letter_mapping: dict[str, str] | None = None,
) -> ET.Element:
    mapping = LETTERS[modality] if letter_mapping is None else letter_mapping
    label_groups = {
        letter: root.findall(f".//s:g[@id='panel-label-{letter}']", NS) for letter in mapping
    }
    for old, new in mapping.items():
        groups = label_groups[old]
        if len(groups) != 1:
            raise ValueError(f"{modality}: missing or duplicate panel letter {old}.")
        texts = groups[0].findall(".//s:text", NS)
        if len(texts) != 1 or "".join(texts[0].itertext()) != old:
            raise ValueError(f"{modality}: unexpected panel-label text {old}.")
        texts[0].text = new
        texts[0].set("data-panel-letter", new)
        groups[0].set("id", f"panel-label-{new}")
        if modality == "neuropixels" and old == "C":
            groups[0].set(
                "transform", f"translate(0 {COHORT_LETTER_SHIFT_MM * POINTS_PER_MM:.8f})",
            )
    if modality == "neuropixels":
        axes = root.findall(".//s:g[@id='cohort-responsiveness-proportions']", NS)
        if len(axes) != 1:
            raise ValueError("Neuropixels needs exactly one cohort panel.")
        axes[0].set("transform", f"translate(0 {COHORT_SHIFT_MM * POINTS_PER_MM:.8f})")
        sessions, mice = (int(root.attrib[f"data-cohort-{k}-count"]) for k in ("session", "mouse"))
        if min(sessions, mice) < 1:
            raise ValueError("Neuropixels cohort counts must be positive.")
        ET.SubElement(root, f"{{{SVG_NS}}}text", {
            "id": "cohort-sample-size", "x": f"{10.8 * POINTS_PER_MM:.8f}",
            "y": f"{136 * POINTS_PER_MM:.8f}", "font-family": FIGURE_FONT,
            "style": f"font-family: {FIGURE_FONT}; font-size: 5.5px",
        }).text = f"{sessions} sessions, {mice} mice"
    for description in root.findall("s:desc", NS):
        description.text = re.sub(r"\b[ABC]\b", lambda m: mapping[m[0]], description.text)
    for metadata in root.findall("s:metadata", NS):
        root.remove(metadata)
    identifiers = [node.attrib["id"] for node in root.iter() if "id" in node.attrib]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError(f"{modality}: duplicate source SVG identifiers.")
    renamed = {identifier: f"{modality}-{identifier}" for identifier in identifiers}

    def reference(match: re.Match) -> str:
        identifier = match[1]
        if identifier not in renamed:
            raise ValueError(f"{modality}: unresolved SVG reference {identifier}.")
        return f"url(#{renamed[identifier]})"

    for node in root.iter():
        for attribute, value in list(node.attrib.items()):
            if attribute == "id":
                value = renamed[value]
            elif attribute in ("href", f"{{{XLINK_NS}}}href") and value.startswith("#"):
                if value[1:] not in renamed:
                    raise ValueError(f"{modality}: unresolved SVG link {value}.")
                value = f"#{renamed[value[1:]]}"
            else:
                value = URL_REFERENCE.sub(reference, value)
            node.set(attribute, value)
    original = tuple(map(float, root.attrib["viewBox"].split()))
    root.attrib.update({
        "id": f"column-{modality}", "x": f"{x_mm * POINTS_PER_MM:.8f}", "y": "0",
        "width": f"{COLUMN_MM * POINTS_PER_MM:.8f}",
        "height": f"{HEIGHT_MM * POINTS_PER_MM:.8f}",
        "viewBox": f"0 0 {original[2]:.8f} {HEIGHT_MM * POINTS_PER_MM:.8f}",
        "preserveAspectRatio": "xMinYMin meet", "overflow": "hidden",
        "data-source-height-mm": f"{original[3] / POINTS_PER_MM:g}",
        "data-intended-height-mm": f"{HEIGHT_MM:g}",
        "data-composite-panel-letters": ",".join(mapping.values()),
    })
    return root


def _add_white_background(
    root: ET.Element, width_mm: float, height_mm: float = HEIGHT_MM,
) -> None:
    ET.SubElement(root, f"{{{SVG_NS}}}rect", {
        "id": "figure-background", "x": "0", "y": "0",
        "width": f"{width_mm * POINTS_PER_MM:.8f}",
        "height": f"{height_mm * POINTS_PER_MM:.8f}",
        "fill": "#ffffff", "fill-opacity": "1",
    })


def _main_figure_annotations(root: ET.Element, columns: list[ET.Element]) -> dict:
    limits = [
        float(columns[0].attrib["data-heatmap-limit-hz"]),
        *[float(c.attrib["data-population-heatmap-limit"]) for c in columns[1:]],
    ]
    if any(not math.isfinite(limit) or limit <= 0 for limit in limits):
        raise ValueError("Shared population color legend needs positive finite native limits.")
    for label, y_mm in (("Single Unit", 32), ("All Units", 91)):
        x, y = 2 * POINTS_PER_MM, y_mm * POINTS_PER_MM
        ET.SubElement(root, f"{{{SVG_NS}}}text", {
            "class": "modality-row-label", "x": f"{x:.8f}", "y": f"{y:.8f}",
            "transform": f"rotate(-90 {x:.8f} {y:.8f})", "text-anchor": "middle",
            "font-family": FIGURE_FONT, "font-size": "7",
        }).text = label
    legend = ET.SubElement(root, f"{{{SVG_NS}}}g", {
        "id": "shared-population-colorbar", "data-palette": "RdBu_r",
        "data-normalization": "fraction of each panel's unchanged native color limit",
    })
    ET.SubElement(legend, f"{{{SVG_NS}}}desc").text = (
        "One shared color gradient: negative limit, zero, positive limit. "
        "D/E/F use separate native-unit limits; signal values are not normalized."
    )
    gradient = ET.SubElement(
        ET.SubElement(legend, f"{{{SVG_NS}}}defs"), f"{{{SVG_NS}}}linearGradient",
        {"id": "shared-population-gradient", "x1": "0%", "x2": "100%", "y1": "0%", "y2": "0%"},
    )
    for i in range(256):
        ET.SubElement(gradient, f"{{{SVG_NS}}}stop", {
            "offset": f"{i / 255:.8f}",
            "stop-color": mpl.colors.to_hex(mpl.colormaps["RdBu_r"](i / 255)),
        })
    left, width = 66 * POINTS_PER_MM, 42 * POINTS_PER_MM
    top, height = 175 * POINTS_PER_MM, 1.5 * POINTS_PER_MM
    ET.SubElement(legend, f"{{{SVG_NS}}}rect", {
        "x": f"{left:.8f}", "y": f"{top:.8f}", "width": f"{width:.8f}",
        "height": f"{height:.8f}", "fill": "url(#shared-population-gradient)",
        "stroke": "#293133", "stroke-width": "0.4",
    })
    for position, label in ((0, "-limit"), (0.5, "0"), (1, "+limit")):
        ET.SubElement(legend, f"{{{SVG_NS}}}text", {
            "x": f"{left + position * width:.8f}", "y": f"{179 * POINTS_PER_MM:.8f}",
            "text-anchor": "middle", "font-family": FIGURE_FONT, "font-size": "6.5",
        }).text = label
    scales = {}
    for i, (panel, limit, unit) in enumerate(zip(
        "DEF", limits, ("spikes/s", "%", "a.u."), strict=True,
    )):
        scales[panel] = {"limit": limit, "unit": unit}
        ET.SubElement(legend, f"{{{SVG_NS}}}text", {
            "data-panel-scale": panel, "data-limit": str(limit), "data-unit": unit,
            "x": f"{(MAIN_LEFT_GUTTER_MM + i * 58 + 27) * POINTS_PER_MM:.8f}",
            "y": f"{182 * POINTS_PER_MM:.8f}", "text-anchor": "middle",
            "font-family": FIGURE_FONT, "font-size": "7",
        }).text = f"{panel}: +/-{limit:g} {unit}"
    return scales


def build_matched_standard_oddball_columns(
    output_dir: Path = OUTPUT_DIR, audit_dir: Path = AUDIT_DIR,
) -> list[Path]:
    """Build two row-lettered native-size composites without rerunning scientific analyses."""
    paths = []
    mesoscope_sources = [
        OUTPUT_DIR / f"mesoscope-standard-oddball-90-{signal}.svg" for signal in ("dff", "oasis")
    ]
    for signal, source in zip(("dff", "oasis"), mesoscope_sources, strict=True):
        left = _place_column(
            _source_column(NEUROPIXELS, NEUROPIXELS_PROVENANCE, "name"), "neuropixels", 0,
        )
        right_source = _source_column(source, MESOSCOPE_PROVENANCE, "path")
        if right_source.get("data-signal") != signal:
            raise ValueError(f"Mesoscope source has the wrong signal: {signal}")
        right = _place_column(right_source, "mesoscope", COLUMN_MM + GUTTER_MM)
        root = ET.Element(f"{{{SVG_NS}}}svg", {
            "width": f"{WIDTH_MM:g}mm", "height": f"{HEIGHT_MM:g}mm",
            "viewBox": f"0 0 {WIDTH_MM * POINTS_PER_MM:.8f} {HEIGHT_MM * POINTS_PER_MM:.8f}",
            "data-event-id": "orientation_90", "data-mesoscope-signal": signal,
            "data-panel-order": "row-major", "data-column-width-mm": f"{COLUMN_MM:g}",
            "data-gutter-mm": f"{GUTTER_MM:g}",
            "data-neuropixels-cohort-shift-mm": f"{COHORT_SHIFT_MM:g}",
            "data-background-color": "#ffffff",
        })
        ET.SubElement(root, f"{{{SVG_NS}}}title").text = (
            f"Standard oddball: Neuropixels and mesoscope {signal}"
        )
        ET.SubElement(root, f"{{{SVG_NS}}}desc").text = (
            "Two matched native-size modality columns, not matched individual neurons. "
            "A/B: Neuropixels/mesoscope single-session examples; "
            "C/D: their single-session context populations and descriptive means; "
            "E/F: their distinct cohort proportions and mouse-bootstrap intervals. "
            "No new analyses or cross-modality statistical comparisons. "
            "All source artwork, scientific values, units, selections and ordering are retained. "
            "Only Neuropixels' cohort artwork is translated 7.1 mm downward to align E/F; "
            "its E label moves 4.6 mm downward and a source-backed cohort sample header is added. "
            f"Neuropixels: {left.find('s:desc', NS).text} "
            f"Mesoscope: {right.find('s:desc', NS).text}"
        )
        _add_white_background(root, WIDTH_MM)
        root.extend([left, right])
        path = output_dir / f"standard-oddball-neuropixels-mesoscope-{signal}.svg"
        output_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(normalize_figure_svg(
            ET.tostring(root, encoding="unicode"), target_width_mm=WIDTH_MM,
            target_height_mm=HEIGHT_MM,
        ), encoding="utf-8", newline="\n")
        paths.append(path)
    sources = [
        Path(__file__), ROOT / "src/openscope_p3_publication/figure_typography.py",
        NEUROPIXELS, NEUROPIXELS_PROVENANCE, *mesoscope_sources, MESOSCOPE_PROVENANCE,
    ]
    provenance = {
        "version": 1, "footprint_mm": [WIDTH_MM, HEIGHT_MM], "gutter_mm": GUTTER_MM,
        "column_width_mm": COLUMN_MM, "panel_letters": LETTERS,
        "background_color": "#ffffff",
        "neuropixels_cohort_shift_mm": COHORT_SHIFT_MM,
        "neuropixels_cohort_letter_shift_mm": COHORT_LETTER_SHIFT_MM,
        "analysis": "None; compose canonical source columns without rescaling artwork.",
        "sources": [{"path": p.relative_to(ROOT).as_posix(), "sha256": sha256(p)} for p in sources],
        "outputs": [{"path": p.name, "sha256": sha256(p)} for p in paths],
    }
    audit_dir.mkdir(parents=True, exist_ok=True)
    path = audit_dir / "provenance.json"
    path.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n",
    )
    return [*paths, path]


def build_three_modality_standard_oddball_columns(
    output_dir: Path = OUTPUT_DIR, audit_dir: Path = AUDIT_DIR,
    *, primary_only: bool = False,
) -> list[Path]:
    """Compose four native-size comparisons; SLAP2 deliberately has no cohort panel."""
    paths, sources = [], []
    for mesoscope in ("dff", "oasis"):
        for slap2 in ("glutamate", "calcium"):
            is_main = mesoscope == "dff" and slap2 == "glutamate"
            if primary_only and not is_main:
                continue
            left_gutter = MAIN_LEFT_GUTTER_MM if is_main else 0
            width_mm = MAIN_WIDTH_MM if is_main else THREE_WIDTH_MM
            height_mm = MAIN_HEIGHT_MM if is_main else HEIGHT_MM
            has_cohort = slap2 == "glutamate"
            specs = [
                ("neuropixels", NEUROPIXELS, NEUROPIXELS_PROVENANCE, "name"),
                ("mesoscope", OUTPUT_DIR / f"mesoscope-standard-oddball-90-{mesoscope}.svg",
                 MESOSCOPE_PROVENANCE, "path"),
                ("slap2", OUTPUT_DIR / f"slap2-standard-oddball-90-{slap2}.svg",
                 SLAP2_PROVENANCE, "path"),
            ]
            columns = []
            for i, (modality, source, provenance, output_key) in enumerate(specs):
                column = _source_column(source, provenance, output_key)
                expected = {"mesoscope": mesoscope, "slap2": slap2}.get(modality)
                if expected is not None and column.get("data-signal") != expected:
                    raise ValueError(f"{modality}: wrong signal in three-column source.")
                if modality == "slap2" and column.get("data-cohort-panel") != (
                    "present" if has_cohort else "absent"
                ):
                    raise ValueError("SLAP2 source cohort scope differs from its signal.")
                mapping = (
                    dict(zip("ABC", "CFI", strict=True))
                    if modality == "slap2" and has_cohort else THREE_LETTERS[modality]
                )
                columns.append(_place_column(
                    column, modality, left_gutter + i * (COLUMN_MM + GUTTER_MM),
                    letter_mapping=mapping,
                ))
                sources.extend([source, provenance])
            root = ET.Element(f"{{{SVG_NS}}}svg", {
                "width": f"{width_mm:g}mm", "height": f"{height_mm:g}mm",
                "viewBox": (
                    f"0 0 {width_mm * POINTS_PER_MM:.8f} "
                    f"{height_mm * POINTS_PER_MM:.8f}"
                ),
                "data-event-id": "orientation_90", "data-panel-order": "row-major",
                "data-mesoscope-signal": mesoscope, "data-slap2-signal": slap2,
                "data-column-width-mm": "54", "data-gutter-mm": "4",
                "data-background-color": "#ffffff",
                "data-slap2-cohort-panel": "present" if has_cohort else "absent",
            })
            ET.SubElement(root, f"{{{SVG_NS}}}title").text = (
                f"Standard oddball: Neuropixels, mesoscope {mesoscope}, SLAP2 {slap2}"
            )
            ET.SubElement(root, f"{{{SVG_NS}}}desc").text = (
                "Three native-size modality columns, not matched cells or experiments. "
                "A/B/C: single-session examples; D/E/F: single-session populations. "
                + (
                    "G/H/I: distinct Neuropixels, mesoscope and verified-subset SLAP2 glutamate "
                    "cohorts. I shows pooled proportions plus two mouse/session points, no CI. "
                    if has_cohort else
                    "G/H: distinct Neuropixels/mesoscope cohorts. No SLAP2 cohort or panel I. "
                )
                +
                "SLAP2 channels share 119 glutamate-SNR-selected sources, not calcium-specific "
                "quality selection. Each DMD uses its own fully recorded trials; "
                "signals share the trial set within each DMD. No cross-modality statistical test. "
                + " ".join(
                    f"{modality}: {column.find('s:desc', NS).text}"
                    for modality, column in zip(THREE_LETTERS, columns, strict=True)
                )
            )
            _add_white_background(root, width_mm, height_mm)
            root.extend(columns)
            if is_main:
                scales = _main_figure_annotations(root, columns)
                root.set("data-row-labels", "Single Unit,All Units")
                root.set("data-shared-population-colorbar", json.dumps(scales, sort_keys=True))
                root.find("s:desc", NS).text += (
                    " The composite adds vertical Single Unit/All Units row labels and one "
                    "shared population color gradient with separate D/E/F native-unit limits. "
                    "The original source columns have no individual colorbars."
                )
            output_dir.mkdir(parents=True, exist_ok=True)
            path = output_dir / f"standard-oddball-three-modality-{mesoscope}-{slap2}.svg"
            path.write_text(normalize_figure_svg(
                ET.tostring(root, encoding="unicode"), target_width_mm=THREE_WIDTH_MM,
                target_height_mm=height_mm,
            ), encoding="utf-8", newline="\n")
            paths.append(path)
    sources.extend([Path(__file__), ROOT / "src/openscope_p3_publication/figure_typography.py"])
    audit_dir.mkdir(parents=True, exist_ok=True)
    provenance = audit_dir / "three-modality-provenance.json"
    provenance.write_text(json.dumps({
        "version": 1, "footprint_mm": [THREE_WIDTH_MM, HEIGHT_MM],
        "main_footprint_mm": [MAIN_WIDTH_MM, MAIN_HEIGHT_MM],
        "main_left_gutter_mm": MAIN_LEFT_GUTTER_MM,
        "main_shared_colorbar": scales,
        "column_width_mm": COLUMN_MM, "gutter_mm": GUTTER_MM,
        "background_color": "#ffffff", "panel_letters": {
            "glutamate": {**THREE_LETTERS, "slap2": dict(zip("ABC", "CFI", strict=True))},
            "calcium": THREE_LETTERS,
        },
        "slap2_cohort_panel": {"glutamate": "present", "calcium": "absent"},
        "neuropixels_cohort_shift_mm": COHORT_SHIFT_MM,
        "neuropixels_cohort_letter_shift_mm": COHORT_LETTER_SHIFT_MM,
        "sources": [{"path": p.relative_to(ROOT).as_posix(), "sha256": sha256(p)}
                    for p in dict.fromkeys(sources)],
        "outputs": [{"path": p.name, "sha256": sha256(p)} for p in paths],
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return [*paths, provenance]


if __name__ == "__main__":
    for path in build_matched_standard_oddball_columns():
        print(f"Wrote {path}")
