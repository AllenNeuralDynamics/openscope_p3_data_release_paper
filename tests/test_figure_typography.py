"""Regression checks for publication SVG text and final-size panel lettering."""

import base64
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from openscope_p3_publication.figure_typography import (
    FIGURE_FONT,
    SVG_NS,
    normalize_figure_svg,
)


def _svg(content: str, dimensions: str = 'viewBox="0 0 1200 800"') -> str:
    return f'<svg xmlns="{SVG_NS}" {dimensions}>{content}</svg>'


def test_text_and_math_tspans_use_arial_without_resizing_direction_labels() -> None:
    svg = _svg(
        '<text font-family="DejaVu Sans" style="font: 12px serif">10'
        '<tspan style="font-family: DejaVu Sans; font-size: 8px">2</tspan></text>'
        '<text font-size="12" font-weight="400">A</text>'
        '<text class="panel-label" y="12">B</text>'
    )
    root = ET.fromstring(normalize_figure_svg(svg))
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] in {"text", "tspan"}:
            assert node.get("font-family") == FIGURE_FONT
            assert node.get("style").endswith("font-family: Arial, sans-serif") or (
                node.get("data-panel-letter") == "B"
            )
    direction = root.findall(f"{{{SVG_NS}}}text")[1]
    assert direction.get("font-size") == "12"
    assert direction.get("font-weight") == "400"
    assert direction.get("data-panel-letter") is None


@pytest.mark.parametrize(
    ("dimensions", "points_per_unit"),
    [
        ('viewBox="0 0 1200 800"', 170 / 1200 * 72 / 25.4),
        ('viewBox="0 0 800 2400"', 205 / 2400 * 72 / 25.4),
        ('width="170mm" height="100mm"', 72 / 96),
    ],
)
def test_panel_size_accounts_for_final_width_height_cap_and_absolute_units(
    dimensions: str, points_per_unit: float,
) -> None:
    svg = _svg(
        '<g transform="translate(30 20) scale(0.5)">'
        '<g id="panel-label-A"><text y="100" font-weight="800">A</text></g></g>',
        dimensions,
    )
    root = ET.fromstring(normalize_figure_svg(svg))
    letter = root.find(f".//{{{SVG_NS}}}text")
    assert float(letter.get("font-size")) * 0.5 * points_per_unit == pytest.approx(9)
    assert letter.get("font-weight") == "700"
    assert "font-weight: 700" in letter.get("style")


def test_nested_svg_viewports_images_and_raster_bytes_are_preserved() -> None:
    panel = _svg('<text class="panel-label" y="50">C</text>', 'viewBox="0 0 200 100"')
    encoded = base64.b64encode(panel.encode()).decode()
    svg = _svg(
        '<svg width="300" height="150" viewBox="0 0 200 100">'
        '<text class="panel-label" y="50"><tspan style="font-size: 2px">B</tspan></text>'
        '</svg>'
        f'<image href="data:image/svg+xml;base64,{encoded}" width="400" height="200"/>'
        '<image href="data:image/png;base64,unmodified" width="100" height="80"/>'
    )
    normalized = normalize_figure_svg(svg)
    root = ET.fromstring(normalized)
    images = root.findall(f"{{{SVG_NS}}}image")
    child = ET.fromstring(base64.b64decode(images[0].get("href").split(",")[1]))
    points_per_unit = 170 / 1200 * 72 / 25.4
    for node in root.findall(".//*[@data-panel-letter]"):
        assert float(node.get("font-size")) * 1.5 * points_per_unit == pytest.approx(9)
    assert float(child.find(f"{{{SVG_NS}}}text").get("font-size")) * (
        2 * points_per_unit
    ) == pytest.approx(9)
    assert images[1].get("href") == "data:image/png;base64,unmodified"
    assert normalize_figure_svg(normalized) == normalized


def test_invalid_figure_dimensions_are_reported() -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        normalize_figure_svg(_svg("", 'viewBox="0 0 0 800"'))
    with pytest.raises(ValueError, match="Unsupported SVG dimension"):
        normalize_figure_svg(_svg("", 'width="100%" height="800"'))


@pytest.mark.parametrize(
    ("asset", "letters"),
    [
        ("figure-01-overview", "ABCDE"),
        ("session-inventory", "ABC"),
        ("raw-neural-recordings", "ABCDEFGHIJKL"),
        ("figure-07-unit-extraction-plan", "ABCDEFGH"),
        ("figure-06-unit-extraction-mesoscope", "ABCDEFGHI"),
        ("openscope_qc_dashboard_static", "ABCDEFG"),
        ("receptive-fields", "ABC"),
        ("cell-type-characterization", "ABCDE"),
        ("figure-10-neuropixels-event-responses", "AB"),
        ("synchronized-behavior", "ABCDEFG"),
        ("supplementary-neuropixels-implant-trajectories", "ABCD"),
        ("supplementary-recording-hardware", ""),
        ("supplementary-wavemap-regions", "ABCDEF"),
        ("supplementary-wavemap-composition", "AB"),
        ("supplementary-cell-type-validation", "ABCDE"),
    ],
)
def test_committed_publication_svgs_use_shared_editable_typography(
    asset: str, letters: str,
) -> None:
    directory = Path(__file__).resolve().parents[1] / "images" / "figures" / "generated"
    root = ET.parse(directory / f"{asset}.svg").getroot()
    assert root.get("data-publication-font") == "Arial"
    assert root.get("data-panel-letter-points") == "9"
    found = set()

    def check(svg: ET.Element) -> None:
        for node in svg.iter():
            tag = node.tag.rsplit("}", 1)[-1]
            if tag in {"text", "tspan"}:
                assert node.get("font-family") == FIGURE_FONT
                assert f"font-family: {FIGURE_FONT}" in node.get("style", "")
            if node.get("data-panel-letter"):
                found.add(node.get("data-panel-letter"))
                assert node.get("font-weight") == "700"
            href = node.get("href", node.get("{http://www.w3.org/1999/xlink}href", ""))
            if href.startswith("data:image/svg+xml;base64,"):
                check(ET.fromstring(base64.b64decode(href.split(",", 1)[1])))

    check(root)
    assert found == set(letters)


@pytest.mark.parametrize(
    "family",
    ["Source Sans 3, sans-serif", "IBM Plex Sans, sans-serif",
     "Myriad Pro, Arial, sans-serif", "IBM Plex Mono, monospace"],
)
def test_common_writer_preserves_body_size_when_replacing_legacy_fonts(
    tmp_path: Path, family: str,
) -> None:
    from openscope_p3_publication.figures import write_svg_output

    output = tmp_path / "figure.svg"
    write_svg_output(output, [
        _svg(f'<text font-family="{family}" font-size="12">Metadata</text>',
             'width="1400" height="1000"'),
    ])
    text = ET.parse(output).find(f"{{{SVG_NS}}}text")
    assert text.get("font-family") == FIGURE_FONT
    assert float(text.get("font-size")) == pytest.approx(14)
