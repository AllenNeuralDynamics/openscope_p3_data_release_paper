import csv
import hashlib
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_imported_figure_manifest_matches_files() -> None:
    manifest_path = REPO_ROOT / "figure_sources" / "google-doc" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["version"] == 1
    assert len(manifest["assets"]) == 14
    for asset in manifest["assets"]:
        path = REPO_ROOT / asset["path"]
        assert path.is_file(), asset["path"]
        assert file_sha256(path) == asset["sha256"]

    laser_power_source = next(
        asset for asset in manifest["assets"]
        if asset["filename"] == "mesoscope-laser-power-table.png"
    )
    assert laser_power_source["status"] == "source-only"


def test_manuscript_local_assets_and_figure_metadata() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    assert "media/media/" not in manuscript

    local_paths = re.findall(r"(?:\./)(images/[^\s]+|interactive/[^\s]+)", manuscript)
    assert local_paths
    for relative_path in local_paths:
        assert (REPO_ROOT / relative_path).is_file(), relative_path

    figures = re.findall(r":::\{figure\} [^\n]+\n(?P<options>.*?)\n\n", manuscript, re.DOTALL)
    assert len(figures) == 13
    for options in figures:
        assert ":label:" in options
        assert ":alt:" in options


def test_mesoscope_laser_power_is_structured_data() -> None:
    data_path = REPO_ROOT / "figure_sources" / "data" / "mesoscope-laser-power.csv"
    with data_path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))

    values = [
        tuple(int(row[column]) for column in row)
        for row in rows
    ]
    assert values == [
        (0, 50, 0, 30),
        (50, 100, 25, 50),
        (100, 150, 50, 80),
        (150, 200, 70, 100),
        (200, 250, 90, 125),
        (250, 300, 110, 170),
        (300, 350, 150, 180),
        (350, 400, 160, 190),
        (400, 450, 200, 240),
        (450, 500, 200, 240),
        (500, 550, 200, 240),
        (550, 600, 200, 240),
    ]

    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    assert "table-mesoscope-laser-power" in manuscript
    assert "Depth from surface (µm)" in manuscript
    assert "mesoscope-laser-power-table.png" not in manuscript
    assert "| 250-300 | 110 | 170 |" in manuscript


def test_imported_data_tables_have_body_cells() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    tables = re.findall(r'<table class="publication-data-table">.*?</table>', manuscript, re.DOTALL)

    assert len(tables) == 2
    for table in tables:
        assert "<tbody>" in table
        assert "<td" in table
        assert "<thead>" in table


def test_interactive_figure_has_static_fallback() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    assert ":::{iframe} ./interactive/experimental-design.html" in manuscript
    assert ":placeholder: ./images/figures/generated/experimental-design.svg" in manuscript