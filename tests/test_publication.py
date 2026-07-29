import csv
import hashlib
import json
import re
import runpy
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

    local_paths = re.findall(
        r"(?:\./)(images/[^\s\"']+|interactive/[^\s\"']+)",
        manuscript,
    )
    assert local_paths
    for relative_path in local_paths:
        assert (REPO_ROOT / relative_path).is_file(), relative_path

    figures = re.findall(r":::\{figure\} [^\n]+\n(?P<options>.*?)\n\n", manuscript, re.DOTALL)
    assert len(figures) == 13
    assert manuscript.count(":::{figure} ./images/figures/imported/") == 13
    assert manuscript.count(":::{figure} ./images/figures/generated/") == 0
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
    assert "supplementary-mesoscope-depth-power.svg" not in manuscript
    assert manuscript.count("(#table-mesoscope-laser-power)") == 1
    assert "Depth-dependent laser-power ranges are provided" in manuscript


def test_glossary_is_an_expandable_final_section() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")

    assert "## Glossary" not in manuscript
    assert manuscript.count("# Glossary") == 1
    assert ":::{dropdown} Terms and abbreviations" in manuscript
    assert manuscript.index("# Glossary") > manuscript.index("# Supplementary Text 1")
    assert manuscript.rstrip().endswith(":::")

    glossary = manuscript[manuscript.index("# Glossary") :]
    assert "**Receptive Field**" in glossary
    assert "Shared across modalities:" not in glossary
    assert "Mesoscope NWB files" not in glossary


def test_nwb_file_contents_are_in_data_records() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")

    records_start = manuscript.index("# Data records")
    nwb_contents = manuscript.index("## NWB file contents")
    validation_start = manuscript.index("# Data validation")
    glossary_start = manuscript.index("# Glossary")
    assert records_start < nwb_contents < validation_start < glossary_start

    records = manuscript[nwb_contents:validation_start]
    assert "Shared across modalities:" in records
    assert "Neuropixels NWB files" in records
    assert "Mesoscope NWB files" in records


def test_imported_data_tables_have_body_cells() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    tables = re.findall(
        r'<table class="publication-data-table [^"]+".*?</table>',
        manuscript,
        re.DOTALL,
    )

    assert len(tables) == 2
    for table in tables:
        assert "<tbody>" in table
        assert "<td" in table
        assert "<thead>" in table
        assert "id-disclosure" in table
        assert "data-full-value" in table

    assert manuscript.count("interactive/data-explorer.html") == 1
    assert '<details class="static-table-fallback">' in manuscript
    assert "View grouped static summary tables" in manuscript


def test_docx_text_formatting_artifacts_are_normalized() -> None:
    normalize_text_export_artifacts = runpy.run_path(
        str(REPO_ROOT / "scripts" / "import_google_doc.py")
    )["normalize_text_export_artifacts"]
    markdown = r"""- Cell extraction ([<u>Suite2p</u>](https://suite2p.org))

> The default configuration used Suite2p's sparse detection mode.

- Packaging used aind-eye-tracking-nwb

> ([<u>repository</u>](https://example.org/repository))

> A genuine quotation remains.

> i\. R(downward, 90° shift) \> R(45° shift),\
> because this is a bigger change in orientation
>
> ii\. R(halt) \< R(90°) and R(45°), because the halt involves a smaller change in velocity

Raw \autocite{noauthor_allenneuraldynamicsgiant-matlab_2026} and
view~\autocite{pnevmatikakis_normcorre_2017} use \textit{activity image} at
\$1.33\$~pixels. A sentence ends.. Neuropixels node**s** were processed with with care.

Paragraph before figure.\

:::{figure} image.png
:::

-
"""

    normalized = normalize_text_export_artifacts(markdown)

    assert "<u>" not in normalized
    assert "\n  The default configuration used Suite2p" in normalized
    assert "aind-eye-tracking-nwb ([repository](https://example.org/repository))" in normalized
    assert "\n> A genuine quotation remains." in normalized
    assert "  1. R(downward, 90° shift) > R(45° shift)" in normalized
    assert "  2. R(halt) < R(90°) and R(45°)" in normalized
    assert "\\autocite" not in normalized
    assert "\\textit" not in normalized
    assert "[$1.33$" not in normalized
    assert "$1.33$ pixels" in normalized
    assert "ends. Neuropixels nodes were processed with care" in normalized
    assert "figure.\\" not in normalized
    assert "\n-\n" not in normalized


def test_manuscript_has_no_docx_formatting_artifacts() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    forbidden_patterns = {
        "empty bullet": r"(?m)^-\s*$",
        "raw LaTeX command": r"\\(?:autocite|textit)\b|\\\$",
        "underlined Markdown link": r"\[<u>[^\n]*?</u>\]\(",
        "split parenthetical link": r"(?m)^\(\[[^\n]+\]\(https?://",
        "double period": r"(?<!\.)\.\.(?!\.)",
        "hard break before figure": r"\\\n\n:::\{figure\}",
        "adjacent JSON filenames": r"\.json,[A-Za-z]",
    }
    for label, pattern in forbidden_patterns.items():
        assert re.search(pattern, manuscript) is None, label

    assert not any(line.startswith(">") for line in manuscript.splitlines())
    assert "| Publication |" not in manuscript
    assert "Recovered row labels: Publication; Type of stimulus;" in manuscript
    assert "Nb of subjects; Session duration; Nb of mismatches" in manuscript
    assert "detection rates beyond a certain number of trials" in manuscript
    assert "our ability to disentangle mechanisms" in manuscript
    assert "our ability\n\n:::{figure}" not in manuscript
    assert "**Supplementary** **Fig. X**" not in manuscript
    assert "**Supplementary** **Table 1**" not in manuscript
    assert "**Supplementary Fig. X)**" not in manuscript

    warning_position = manuscript.index(":::{warning} Supplementary table")
    first_table_reference = manuscript.index("(see **Supplementary Table 1**)")
    simulation_figure = manuscript.index(":label: fig-supp-power-simulation-trials")
    assert first_table_reference < warning_position < simulation_figure


def test_interactive_figure_has_static_fallback() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    assert ":::{iframe} ./interactive/experimental-design.html" in manuscript
    assert ":placeholder: ./images/figures/generated/experimental-design.svg" in manuscript