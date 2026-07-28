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


def test_manuscript_local_assets_and_figure_metadata() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    assert "media/media/" not in manuscript

    local_paths = re.findall(r"(?:\./)(images/[^\s]+|interactive/[^\s]+)", manuscript)
    assert local_paths
    for relative_path in local_paths:
        assert (REPO_ROOT / relative_path).is_file(), relative_path

    figures = re.findall(r":::\{figure\} [^\n]+\n(?P<options>.*?)\n\n", manuscript, re.DOTALL)
    assert len(figures) == 14
    for options in figures:
        assert ":label:" in options
        assert ":alt:" in options


def test_interactive_figure_has_static_fallback() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    assert ":::{iframe} ./interactive/experimental-design.html" in manuscript
    assert ":placeholder: ./images/figures/generated/experimental-design.svg" in manuscript