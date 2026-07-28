from pathlib import Path

import pytest

from openscope_p3_publication.figures import (
    BLOCKS,
    SESSIONS,
    total_duration_minutes,
    write_interactive_html,
    write_static_svg,
)


def test_experimental_design_data() -> None:
    assert len(SESSIONS) == 4
    assert len(BLOCKS) == 8
    assert total_duration_minutes() == pytest.approx(71.3)


def test_figure_outputs_are_accessible_and_interactive(tmp_path: Path) -> None:
    html_path = write_interactive_html(tmp_path / "experimental-design.html")
    svg_path = write_static_svg(tmp_path / "experimental-design.svg")

    html = html_path.read_text(encoding="utf-8")
    svg = svg_path.read_text(encoding="utf-8")

    assert "plotly" in html.lower()
    assert "Shared session structure" in html
    assert 'id="experimental-design-plot"' in html
    assert 'role="img"' in svg
    assert "Session 4" in svg