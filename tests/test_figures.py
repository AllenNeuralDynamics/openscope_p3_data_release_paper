import hashlib
import json
from pathlib import Path

import pytest

from openscope_p3_publication.figures import (
    ANIMAL_RECORDS_PATH,
    ANIMAL_RECORDS_PROVENANCE_PATH,
    BLOCKS,
    SESSIONS,
    STIMULUS_SOURCES_PATH,
    load_publication_table_data,
    total_duration_minutes,
    write_data_explorer_html,
    write_interactive_html,
    write_static_svg,
)


def test_experimental_design_data() -> None:
    assert len(SESSIONS) == 4
    assert len(BLOCKS) == 8
    assert total_duration_minutes() == pytest.approx(71.3)


def test_stimulus_sources_are_pinned() -> None:
    sources = json.loads(STIMULUS_SOURCES_PATH.read_text(encoding="utf-8"))

    assert sources["upstream_revision"] == "0365ae32f0f0473320ed202b7c5d2bce6cf5df6b"
    assert len(sources["sessions"]) == 4
    for source in sources["sessions"]:
        assert source["example_table_url"].endswith("_example.csv")
        assert len(source["sha256"]) == 64


def test_figure_outputs_are_accessible_and_interactive(tmp_path: Path) -> None:
    html_path = write_interactive_html(tmp_path / "experimental-design.html")
    svg_path = write_static_svg(tmp_path / "experimental-design.svg")

    html = html_path.read_text(encoding="utf-8")
    svg = svg_path.read_text(encoding="utf-8")

    assert 'id="stimulus-viewer"' in html
    assert 'id="stimulus-canvas"' in html
    assert 'id="session-selector"' in html
    assert 'id="play-toggle"' in html
    assert 'id="block-track"' in html
    assert 'id="table-source"' in html
    assert 'id="stimulus-video"' in html
    assert 'id="workflow-source"' in html
    assert "0365ae32f0f0473320ed202b7c5d2bce6cf5df6b" in html
    assert "setInterval" in html
    assert "Standard oddball" in html
    assert "Duration mismatch" in html
    assert 'id="mock-mouse"' not in html
    assert 'id="event-log"' not in html
    assert 'id="trigger-mismatch"' not in html
    assert "__SIMULATOR_" not in html
    assert 'role="img"' in svg
    assert "Session 4" in svg

    first_render = html
    write_interactive_html(html_path)
    assert html_path.read_text(encoding="utf-8") == first_render


def test_data_explorer_is_deterministic(tmp_path: Path) -> None:
    explorer_path = write_data_explorer_html(tmp_path / "data-explorer.html")
    html = explorer_path.read_text(encoding="utf-8")

    assert 'id="data-explorer"' in html
    assert "Download visible rows as CSV" in html
    assert "Two-photon mesoscope" in html
    assert "832700_2026-01-30" in html
    assert "841193" in html

    write_data_explorer_html(explorer_path)
    assert explorer_path.read_text(encoding="utf-8") == html


def test_publication_table_data() -> None:
    data = load_publication_table_data()

    animals = data["tables"]["animals"]
    sessions = data["tables"]["sessions"]
    assert len(animals["rows"]) == 39
    assert len(sessions["rows"]) == 164
    assert len({row["values"][0] for row in animals["rows"]}) == 39
    assert len({row["values"][0] for row in sessions["rows"]}) == 164
    assert sessions["headers"] == ["Session ID", "Mouse ID", "Date", "Modality", "Context"]
    failed_mouse = next(row for row in animals["rows"] if row["values"][0] == "841193")
    assert failed_mouse["values"][3] == "FAILED"
    assert failed_mouse["qc"] == "failed"


def test_animal_record_provenance() -> None:
    provenance = json.loads(
        ANIMAL_RECORDS_PROVENANCE_PATH.read_text(encoding="utf-8")
    )

    assert len(provenance["source_sha256"]) == 64
    assert provenance["vendored_sha256"] == hashlib.sha256(
        ANIMAL_RECORDS_PATH.read_bytes()
    ).hexdigest()