import csv
import hashlib
import json
import re
import runpy
import struct
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def test_manuscript_marks_author_list_as_provisional() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")

    assert ":::{warning} Author list not final" in manuscript
    assert "author list and author order are provisional" in manuscript
    assert (
        "https://data.allenneuraldynamics.org/contributions/add?project=p3_data_release"
        in manuscript
    )


def test_manuscript_marks_unfinished_content() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")

    assert ":::{note} Manuscript status" in manuscript
    assert manuscript.count(":::{warning} Work in progress") == 8
    assert manuscript.count('class="manuscript-wip-inline"') == 2
    for stale_marker in (
        "To be written",
        "Supplementary Fig. X",
        "XXXX",
        "CITE PAPER WHEN AVAILABLE",
        '<span class="mark">',
        "More caveats?",
    ):
        assert stale_marker not in manuscript


def test_authorship_snapshot_is_portal_backed() -> None:
    authors = (REPO_ROOT / "authors.yml").read_text(encoding="utf-8")

    commit = re.search(r'^  commit: "([0-9a-f]{32})"$', authors, re.MULTILINE)
    assert commit
    assert 'project: "p3_data_release"' in authors
    assert f"commit={commit.group(1)}&format=json" in authors
    assert authors.count('\n      name: "') == 14
    assert 'name: "Jérôme Lecoq"' in authors
    assert 'name: "Peter A Groblewski"' in authors


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

    behavior_source = next(
        asset for asset in manifest["assets"]
        if asset["filename"] == "figure-06-behavior-tracking-plan.png"
    )
    assert behavior_source["status"] == "source-only"

    implant = next(
        asset for asset in manifest["assets"]
        if asset["filename"] == "supplementary-neuropixels-implant-trajectories.png"
    )
    assert implant["source_kind"] == "google-slides-rendered-png"
    assert implant["supplementary_number"] == 1
    assert implant["sha256"] == (
        "e705404cc2d3bef0cbe5f76aaeef89bdee619f996304552b137eb26761555f33"
    )
    assert implant["replaces_google_doc_source"] == "image14.png"

    removed = {asset["source_name"] for asset in manifest["assets"] if asset["status"] == "removed"}
    assert removed == {"image1.png", "image2.png", "image7.png", "image11.png"}

    figure_one = next(
        asset for asset in manifest["assets"]
        if asset["filename"] == "figure-01-graphical-abstract.png"
    )
    assert figure_one["source_kind"] == "illustrator-rendered-png"
    assert figure_one["source_asset_sha256"] == (
        "85306f647bee704c66332cc26924a0b7e77b99449016bd7271b94d072e5112be"
    )
    assert figure_one["sha256"] == (
        "40ee64ef312cd9b2915ac7bcc8b748cdeee8e455edbf94c334bbfc3e50fba334"
    )
    assert png_dimensions(REPO_ROOT / figure_one["path"]) == (3200, 2400)

    expected_crops = {
        "figure-02-experimental-design.png": ([20, 55, 1128, 835], (1108, 780)),
        "figure-03-multimodal-pipelines.png": ([45, 70, 1600, 965], (1555, 895)),
    }
    for filename, (crop_box, dimensions) in expected_crops.items():
        asset = next(asset for asset in manifest["assets"] if asset["filename"] == filename)
        assert asset["source_kind"] == "google-doc-derived-crop"
        assert asset["crop_box_px"] == crop_box
        assert png_dimensions(REPO_ROOT / asset["path"]) == dimensions

    provenance = json.loads(
        (REPO_ROOT / "figure_sources/derived/cropped-figures.provenance.json").read_text(
            encoding="utf-8"
        )
    )
    panel_d = provenance["assets"]["image10-panel-d"]
    assert panel_d["crop_box_px"] == [1128, 55, 2040, 835]
    assert panel_d["sha256"] == (
        "80a30e0cdd4c4e9a27dd88e5d9fa2c4a51094ca1aaa238bb53dee0a7a3acaa74"
    )
    assert png_dimensions(REPO_ROOT / panel_d["output_path"]) == (912, 780)


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
    assert len(figures) == 7
    assert manuscript.count(":::{figure} ./images/figures/imported/") == 7
    assert manuscript.count(":::{figure} ./images/figures/generated/") == 0
    for options in figures:
        assert ":label:" in options
        assert ":alt:" in options


def test_bibliography_uses_resolved_myst_citations() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    bibliography = (REPO_ROOT / "references.bib").read_text(encoding="utf-8")

    assert not re.search(r"paperpile[.]com", manuscript)
    assert " and others" not in bibliography
    citation_keys = set(re.findall(r"@([A-Za-z0-9][A-Za-z0-9_-]*)", manuscript))
    bibliography_keys = set(re.findall(r"^@\w+\{([^,]+),", bibliography, re.MULTILINE))
    assert citation_keys
    assert citation_keys == bibliography_keys


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
    assert "Laser power was selected from the [depth-dependent lookup ranges]" in manuscript
    assert "table-hover-source" in manuscript
    supplementary = manuscript[manuscript.index("## Supplementary figures") :]
    assert "mesoscope laser-power lookup table" not in supplementary


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


def test_supplementary_studies_table_is_complete() -> None:
    data_path = REPO_ROOT / "figure_sources" / "data" / "other-oddball-studies.csv"
    provenance_path = data_path.with_suffix(".provenance.json")
    with data_path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.reader(stream))
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))

    assert len(rows) == 17
    assert {len(row) for row in rows} == {6}
    assert rows[0] == [
        "Publication",
        "Attinger et al 2017",
        "Homann et al 2022",
        "Bastos et al 2023",
        "Knudstrup et al 2025",
        "Westerberg et al 2025",
    ]
    assert rows[14][1:] == ["0.07", "0.1666666667", "0.125", "0.1", "0.2"]
    assert file_sha256(data_path) == provenance["vendored_sha256"]

    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    supplementary_start = manuscript.index(
        "# Supplementary Text 1: Published oddball paradigms"
    )
    main_text = manuscript[:supplementary_start]
    assert "[Supplementary Table 1](#table-supplementary-oddball-studies)" in main_text
    assert "approximately 35 repeats per deviant type" in main_text
    assert ":label: table-supplementary-oddball-studies" in manuscript
    assert (
        ":label: table-supplementary-oddball-studies\n:enumerated: false"
        in manuscript
    )
    assert manuscript.count("**Supplementary Table 1.**") == 1
    assert "./interactive/literature-comparison.html" in manuscript
    assert "Supplementary Text 1: Published oddball paradigms" in manuscript
    assert "Reported oddball probabilities ranged from 0.07 to 0.20" in manuscript

    comparison = (REPO_ROOT / "interactive" / "literature-comparison.html").read_text(
        encoding="utf-8"
    )
    assert "Attinger et al 2017" in comparison
    assert "Westerberg et al 2025" in comparison
    assert "Compare parameter" in comparison
    assert "Study profile" in comparison


def test_late_figures_are_supplementary_and_power_figures_are_removed() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")

    for number in range(1, 3):
        assert manuscript.count(f"**Supplementary Figure {number}.**") == 1
    assert manuscript.count(":enumerated: false\n:width: 100%") >= 2
    assert "supplementary-neuropixels-implant-trajectories.png" in manuscript
    assert "./interactive/unit-yield.html" in manuscript
    assert ":label: fig-supp-neuropixels-unit-yield\n" in manuscript
    assert manuscript.count(
        "[Supplementary Figure 2](#fig-supp-neuropixels-unit-yield)"
    ) == 2
    assert "images/figures/generated/supplementary-neuropixels-unit-yield.svg" not in manuscript
    assert "60 sessions from 16 mice" in manuscript
    assert "supplementary-neuropixels-unit-yield.png" not in manuscript
    assert "supplementary-neuropixels-targeting.png" not in manuscript
    assert "figure-11-analysis-framework.png" not in manuscript
    assert "fig-supp-power-simulation-trials" not in manuscript
    assert "fig-supp-power-simulation-sessions" not in manuscript
    assert "fig-supp-neuropixels-visual-responses" not in manuscript
    assert "Simulation of responsive-neuron detection rate" not in manuscript


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
    assert records.count(":::{tab-item}") == 3
    assert records.count(
        "| Question | NWB contents | Representative PyNWB entry point |"
    ) == 3
    assert "nwbfile.units.to_dataframe()" in records
    assert 'nwbfile.processing[plane]["dff_timeseries"]' in records


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
    assert ":placeholder: ./images/figures/generated/session-inventory.svg" in manuscript
    assert ":label: fig-recording-session-inventory" in manuscript
    assert "Recording-session inventory and quality-control summary" in manuscript
    assert "**A,** Neuropixels uses 62 worksheet rows" in manuscript
    assert '<div class="publication-data-source" hidden aria-hidden="true">' in manuscript
    assert "View grouped static summary tables" not in manuscript


def test_figure_captions_and_interactive_placement() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")

    assert "A visual sequence establishes an expectation" in manuscript
    assert "**A,** Animals progressed from surgery" in manuscript
    assert "**D,** Context panels summarize" not in manuscript
    assert "Rows summarize Neuropixels, mesoscope two-photon" in manuscript
    assert "searchable, filterable tables for 39 mice and 164" in manuscript
    assert "./interactive/neural-viewer.html" in manuscript
    assert ":label: fig-aligned-neural-signals" in manuscript
    assert "Representative raw-data excerpts from one public session" in manuscript
    assert "shown to introduce the native acquisition formats" in manuscript
    assert "Event-aligned raw data across recording modalities" not in manuscript
    assert "prediction-violating event" not in manuscript
    assert re.search(r"Microscopy\s+playback uses elapsed time", manuscript)
    assert "raw AP acquisition stream supplied to spike sorting" in manuscript
    assert "AP samples are not median-corrected" in manuscript
    assert "remain visible as vertical stripes" in manuscript
    assert "ecephys_820459_2025-11-10_15-07-13" in manuscript
    assert "multiplane-ophys_832700_2026-01-29_11-18-09" in manuscript
    assert "796630_2025-08-28_14-25-34" in manuscript
    assert ":label: fig-interactive-experimental-design\n:width: 100%" in manuscript
    assert (
        ":label: fig-interactive-experimental-design\n:enumerated: false"
        not in manuscript
    )
    assert ":label: fig-recording-session-inventory\n:width: 100%" in manuscript
    assert ":label: fig-recording-session-inventory\n:enumerated: false" not in manuscript
    assert (
        manuscript.index("# Data validation")
        < manuscript.index("## Raw data across recording modalities")
        < manuscript.index("fig-aligned-neural-signals")
        < manuscript.index("## Units extraction")
        < manuscript.index("fig-unit-extraction-plan")
        < manuscript.index("## Receptive field analysis across modalities")
        < manuscript.index("fig-basic-stimuli-plan")
    )
    assert "Figure 7 and the modality subsections below" in manuscript
    assert "This analysis and Figure 8 are planning placeholders" in manuscript
    assert "Figure 10 are planning placeholders" in manuscript
    assert "./interactive/behavior-viewer.html" in manuscript
    assert "Event-centered excerpts from real Neuropixels" in manuscript
    assert "figure-06-behavior-tracking-plan.png" not in manuscript
    assert "continuous raw\nbehavioral videos" in manuscript
    assert "[](#fig-behavior-tracking) show these streams" in manuscript
    assert "NWB running\nspeed and stimulus rows share the sync-file clock" in manuscript
    assert "reported dropped frames are removed before mapping" in manuscript
    assert "per-frame Harp timestamps on the acquisition clock" in manuscript
    assert "DeepLabCut" in manuscript
    assert "SLEAP" in manuscript
    assert "Lightning Pose" in manuscript
    assert "facial and\nbody motion energy" in manuscript
    assert "per-frame Harp timestamps for SLAP2" in manuscript
    assert "- Motion energy of the face?" not in manuscript

    figure_2 = manuscript.index(":label: fig-experimental-design")
    explanation = manuscript.index("The four distinct session contexts")
    viewer = manuscript.index(":label: fig-interactive-experimental-design")
    assert figure_2 < explanation < viewer


def test_custom_layout_widens_article_and_hides_duplicate_sidebar() -> None:
    stylesheet = (REPO_ROOT / "styles.css").read_text(encoding="utf-8")

    assert ".myst-primary-sidebar" in stylesheet
    assert "display: none !important" in stylesheet
    assert "minmax(10ch, 20ch)" in stylesheet
    assert "#fig-graphical-abstract" in stylesheet
    assert "#fig-experimental-design" in stylesheet
    assert "#fig-interactive-experimental-design .relative.inline-block" in stylesheet
    assert "#fig-supp-neuropixels-unit-yield" in stylesheet
    assert "max-width: 660px" in stylesheet
    assert "grid-template-columns: minmax(0, 660px) minmax(0, 1fr)" in stylesheet
    assert "@media (min-width: 1280px)" in stylesheet
    assert "@media (max-width: 1100px)" not in stylesheet
    assert "article > figure.table-hover-source" in stylesheet
    assert ".hover-card-content:has(.table-hover-source) .hover-document" in stylesheet
    assert "max-height: min(460px, calc(100vh - 2rem))" in stylesheet
    assert "#fig-behavior-tracking" in stylesheet
    assert "container-type: inline-size" in stylesheet
    assert "@container (max-width: 560px)" in stylesheet


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
    assert "| Publication |\n|----|" not in manuscript
    assert "our ability to disentangle mechanisms" in manuscript
    assert "our ability\n\n:::{figure}" not in manuscript
    assert "**Supplementary** **Fig. X**" not in manuscript
    assert "**Supplementary** **Table 1**" not in manuscript
    assert "**Supplementary Fig. X)**" not in manuscript

    assert ":::{warning} Supplementary table" not in manuscript
    assert "Recovered row labels:" not in manuscript


def test_interactive_figure_has_static_fallback() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    assert ":::{iframe} ./interactive/experimental-design.html" in manuscript
    assert (
        ":placeholder: ./images/figures/generated/experimental-design-panel-d.png"
        in manuscript
    )
    assert "Toggle between Interactive and Static" in manuscript