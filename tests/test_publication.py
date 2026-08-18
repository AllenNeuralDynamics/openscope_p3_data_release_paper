import csv
import datetime as dt
import hashlib
import json
import re
import runpy
import struct
import urllib.parse
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def test_checksum_sensitive_snapshots_use_lf_line_endings() -> None:
    figure_sources = REPO_ROOT / "figure_sources"
    paths = sorted(figure_sources.rglob("*.csv")) + sorted(
        figure_sources.rglob("*.json")
    )
    assert paths
    crlf_paths = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in paths
        if b"\r\n" in path.read_bytes()
    ]
    assert crlf_paths == [], (
        "Checksum-sensitive snapshots must use LF line endings; check .gitattributes: "
        f"{crlf_paths}"
    )


def test_pages_deployment_only_runs_for_main_events() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "deploy.yml").read_text(
        encoding="utf-8"
    )
    main_deployment_guard = (
        "if: (github.event_name == 'push' || "
        "github.event_name == 'workflow_dispatch') && "
        "github.ref == 'refs/heads/main'"
    )

    assert workflow.count(main_deployment_guard) == 3
    assert "github.event_name != 'pull_request'" not in workflow


def publication_snapshot_updater() -> dict:
    return runpy.run_path(
        str(REPO_ROOT / "scripts" / "update_publication_snapshots.py")
    )


def test_session_snapshot_extracts_qc_and_qc_tags() -> None:
    extractor = runpy.run_path(
        str(REPO_ROOT / "scripts" / "extract_experimental_sessions.py")
    )
    source_row = {
        "Modality": "MESO",
        "Mouse id": 101,
        "Experimental date": dt.datetime(2026, 1, 1),
        "Session id": "session-a",
        "Session stimulus": "OPTICAL_SESSION1_SEQUENCE",
        "QC": "Fail",
        "QC Tags": "Motion correction, Mouse stressed",
    }

    class FakeFrame:
        def __len__(self) -> int:
            return 1

        def iterrows(self):
            return iter([(0, source_row)])

    class FakePandas:
        @staticmethod
        def isna(value: object) -> bool:
            return value is None

        @staticmethod
        def read_excel(*args, **kwargs):
            return FakeFrame()

    rows, worksheet_rows = extractor["normalized_source_rows"](
        b"workbook", FakePandas
    )

    assert worksheet_rows == 1
    assert rows[0]["qc"] == "Fail"
    assert rows[0]["qc_tags"] == "Motion correction, Mouse stressed"
    assert extractor["OUTPUT_FIELDS"][-3:] == ("qc", "qc_tags", "source_row")


def test_session_snapshot_refresh_repins_derived_provenance(tmp_path: Path) -> None:
    updater = publication_snapshot_updater()
    session_path = tmp_path / "experimental-sessions.csv"
    running_path = tmp_path / "running-statistics.json"
    behavior_path = tmp_path / "behavior-static-frames.provenance.json"
    previous = (
        b"source_session_id,mouse_id,date,modality,session_stimulus,qc,qc_tags,source_row\n"
        b"session-a,101,2026-01-01,mesoscope,OPTICAL_SESSION1_SEQUENCE,Pass,,8\n"
        b"session-a,101,2026-01-01,mesoscope,OPTICAL_SESSION1_SEQUENCE,Pass,,12\n"
    )
    session_path.write_text(
        "source_session_id,mouse_id,date,modality,session_stimulus,qc,qc_tags,source_row\n"
        "session-a,101,2026-01-01,mesoscope,OPTICAL_SESSION1_SEQUENCE,Pass,,8\n",
        encoding="utf-8",
    )
    running_path.write_text(
        json.dumps(
            {
                "source_session_records": {"sha256": "old"},
                "sessions": [
                    {
                        "modality": "mesoscope",
                        "source_row": 12,
                        "source_session_id": "session-a",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    behavior_path.write_text(
        json.dumps({"running_statistics_sha256": "old"}), encoding="utf-8"
    )
    updater["refresh_session_snapshot_dependents"].__globals__.update(
        {
            "RUNNING_STATISTICS_PATH": running_path,
            "BEHAVIOR_STATIC_PROVENANCE_PATH": behavior_path,
        }
    )

    updater["refresh_session_snapshot_dependents"](session_path, previous)

    running = json.loads(running_path.read_text(encoding="utf-8"))
    behavior = json.loads(behavior_path.read_text(encoding="utf-8"))
    assert running["source_session_records"]["sha256"] == file_sha256(session_path)
    assert running["sessions"][0]["source_row"] == 8
    assert behavior["running_statistics_sha256"] == file_sha256(running_path)


def test_session_snapshot_refresh_rejects_semantic_changes(tmp_path: Path) -> None:
    updater = publication_snapshot_updater()
    session_path = tmp_path / "experimental-sessions.csv"
    session_path.write_text(
        "source_session_id,mouse_id,date,modality,session_stimulus,qc,qc_tags,source_row\n"
        "session-a,101,2026-01-01,mesoscope,OPTICAL_SESSION1_SEQUENCE,Pass,,8\n",
        encoding="utf-8",
    )
    previous = session_path.read_bytes().replace(
        b"OPTICAL_SESSION1_SEQUENCE", b"OPTICAL_SESSION2_DURATION"
    )

    with pytest.raises(RuntimeError, match="Session semantics changed"):
        updater["refresh_session_snapshot_dependents"](session_path, previous)


def test_session_snapshot_qc_tag_changes_do_not_invalidate_analysis() -> None:
    updater = publication_snapshot_updater()
    current = (
        b"source_session_id,mouse_id,date,modality,session_stimulus,qc,qc_tags,source_row\n"
        b'session-a,101,2026-01-01,mesoscope,OPTICAL_SESSION1_SEQUENCE,Fail,"Motion, Stress",8\n'
    )
    previous = current.replace(b"Motion, Stress", b"Motion")

    assert updater["derived_session_records"](previous) == updater[
        "derived_session_records"
    ](current)
    assert updater["semantic_session_records"](previous) != updater[
        "semantic_session_records"
    ](current)


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
    avatars = json.loads((REPO_ROOT / "author_avatars.json").read_text(encoding="utf-8"))

    commit = re.search(r'^  commit: "([0-9a-f]{32})"$', authors, re.MULTILINE)
    assert commit
    assert 'project: "p3_data_release"' in authors
    assert f"commit={commit.group(1)}&format=json" in authors
    assert authors.count('\n      name: "') == 19
    for contributor in (
        "Jérôme Lecoq",
        "Peter A Groblewski",
        "Maedeh Seyedolmohadesin",
        "Ivana Bussi",
        "Karim Oweiss",
        "Alexander Maier",
        "Manni He",
    ):
        assert f'name: "{contributor}"' in authors
    assert avatars["version"] == 1
    assert len(avatars["contributors"]) == 18
    assert len(avatars["unresolved"]) == 1
    assert set(avatars["contributors"]).isdisjoint(avatars["unresolved"])
    assert authors.count('\n      avatar_url: "https://') == 18
    for author_id, record in avatars["contributors"].items():
        assert record["source_page"].startswith("https://")
        assert urllib.parse.urlparse(record["avatar_url"]).netloc in {
            "cdn.prod.website-files.com",
            "static1.squarespace.com",
            "faculty.eng.ufl.edu",
            "cdn.vanderbilt.edu",
        }
        assert record["width"] >= 400
        assert record["height"] >= 400
        author_block = re.search(
            rf'      id: "{re.escape(author_id)}"\n(.*?)(?=\n    -|\Z)',
            authors,
            re.DOTALL,
        )
        assert author_block
        assert f'avatar_url: "{record["avatar_url"]}"' in author_block.group(1)
    for author_id in avatars["unresolved"]:
        author_block = re.search(
            rf'      id: "{re.escape(author_id)}"\n(.*?)(?=\n    -|\Z)',
            authors,
            re.DOTALL,
        )
        assert author_block
        assert "avatar_url:" not in author_block.group(1)


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
    assert len(figures) == 6
    assert manuscript.count(":::{figure} ./images/figures/imported/") == 1
    assert manuscript.count(":::{figure} ./images/figures/generated/") == 5
    assert "./images/figures/generated/figure-01-overview.svg" in manuscript
    assert "./images/figures/generated/figure-01-panel-c-cohorts.svg" not in manuscript
    assert ":label: fig-experimental-design" not in manuscript
    for options in figures:
        assert ":label:" in options
        assert ":alt:" in options

    assert (
        "Distributed predictive-processing hypotheses motivate multimodal recordings"
        in manuscript
    )
    assert "**C,** Five cohort timelines" in manuscript
    assert "Within-session architecture for cross-context comparison" in manuscript
    assert "see [Figure 1](#fig-graphical-abstract)" in manuscript
    assert "see [Figure 3](#fig-multimodal-pipelines)" in manuscript
    assert "./images/figures/generated/multimodal-hardware.svg" in manuscript
    assert "./images/figures/generated/figure-06-segmentation-viewers.svg" in manuscript
    assert "./images/figures/generated/figure-07-unit-extraction-plan.svg" in manuscript
    assert "./images/figures/generated/figure-08-basic-stimuli-plan.svg" in manuscript
    assert "./images/figures/generated/figure-10-standard-oddball-plan.svg" in manuscript
    assert "nine native-resolution images" in manuscript
    hardware_start = manuscript.index("## Multimodal recording hardware")
    methods_start = manuscript.index("# Methods")
    hardware_section = manuscript[hardware_start:methods_start]
    assert "Behavior cohorts" not in hardware_section
    assert "cohort-specific order" not in hardware_section


def test_importer_preserves_opening_figure_narrative() -> None:
    importer = runpy.run_path(str(REPO_ROOT / "scripts" / "import_google_doc.py"))
    render_figure = importer["render_figure"]
    normalize = importer["normalize_figure_references"]

    figure_1 = render_figure("image12.png")
    assert "./images/figures/generated/figure-01-overview.svg" in figure_1
    assert "Distributed predictive-processing hypotheses" in figure_1
    assert "**B,** To sample these nested scales" in figure_1
    assert "**C,** Five cohort timelines" in figure_1

    figure_2 = render_figure("image10.png")
    assert figure_2 == ""

    hardware = render_figure("image8.png")
    assert "./images/figures/generated/multimodal-hardware.svg" in hardware
    assert "Multimodal recording hardware" in hardware
    assert "nine native-resolution images" in hardware
    assert "cohort-specific order" not in hardware
    assert "[Figure 2](#fig-interactive-experimental-design)" in importer[
        "INTERACTIVE_DESIGN_BLOCK"
    ]
    assert "[Figure 4](#fig-recording-session-inventory)" in importer[
        "DATA_EXPLORER_BLOCK"
    ]
    assert "[Figure 5](#fig-aligned-neural-signals)" in importer["NEURAL_VIEWER_BLOCK"]
    assert "Supplementary Figure 3" in importer["NEUROPIXELS_TRAJECTORY_BLOCK"]
    assert "332 probe" in importer["NEUROPIXELS_TRAJECTORY_BLOCK"]
    trajectory_text = " ".join(
        importer["NEUROPIXELS_TRAJECTORY_BLOCK"].split()
    )
    assert "trajectories extend laterally toward the L direction marker" in trajectory_text

    source = (
        "brain fixation and brain histology (see **Figure 2**). "
        "The screen was positioned 15 cm from the mouse's right eye (see **Figure 2**). "
        "The rig can insert six Neuropixels probes simultaneously (see **Figure 2**)."
    )
    normalized = normalize(source)
    assert "[Figure 1](#fig-graphical-abstract)" in normalized
    assert "[Figure 3](#fig-multimodal-pipelines)" in normalized
    assert "see **Figure 2**" not in normalized


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


def test_methods_are_collapsed_as_one_section() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    hardware_start = manuscript.index("## Multimodal recording hardware")
    methods_start = manuscript.index("# Methods")
    records_start = manuscript.index("# Data records")
    methods = manuscript[methods_start:records_start]
    hardware = manuscript[hardware_start:methods_start]

    assert hardware_start < methods_start
    assert ":::{figure} ./images/figures/generated/multimodal-hardware.svg" in hardware
    assert methods.startswith(
        "# Methods\n\n::::{dropdown} Show complete Methods\n"
        ":class: manuscript-methods-dropdown\n"
    )
    assert methods.rstrip().endswith("::::")
    assert "## Experimental animals" in methods
    assert ":label: fig-multimodal-pipelines" not in methods
    assert "[Figure 3](#fig-multimodal-pipelines)" in methods
    assert "#### Neuropixels Ephys NWB Packaging Pipeline" in methods
    assert "#### SLAP2 synchronization" in methods
    assert "#### SLAP2 NWB Packaging Pipeline" in methods
    assert "11f8d942-a12c-44b5-84db-d084164294d1" in methods
    assert "f8d26d18-3daf-45fd-9671-32b68d2a9441" in methods

    import_script = runpy.run_path(
        str(REPO_ROOT / "scripts" / "import_google_doc.py")
    )
    wrap_methods_dropdown = import_script["wrap_methods_dropdown"]
    relocate_figure = import_script["relocate_multimodal_pipeline_figure"]
    source = "# Background\n\n# Methods\n\n## Procedure\n\nText.\n\n# Data records\n"
    wrapped = wrap_methods_dropdown(source)
    assert wrapped.count("::::{dropdown} Show complete Methods") == 1
    assert wrap_methods_dropdown(wrapped) == wrapped

    figure_source = (
        "# Background\n\n# Methods\n\n"
        ":::{figure} figure.png\n:label: fig-multimodal-pipelines\n\nCaption.\n:::\n\n"
        "## Procedure\n\nText.\n\n# Data records\n"
    )
    relocated = relocate_figure(figure_source)
    assert relocated.index("## Multimodal recording hardware") < relocated.index("# Methods")
    assert relocate_figure(relocated) == relocated


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


def test_supplementary_and_power_figures_are_current() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")

    for number in range(1, 6):
        assert manuscript.count(f"**Supplementary Figure {number}.**") == 1
    assert manuscript.count(":enumerated: false\n:width: 100%") >= 3
    assert "supplementary-neuropixels-implant-trajectories.png" in manuscript
    assert "./interactive/unit-yield.html" in manuscript
    assert ":label: fig-supp-neuropixels-unit-yield\n" in manuscript
    assert manuscript.count(
        "[Supplementary Figure 2](#fig-supp-neuropixels-unit-yield)"
    ) == 2
    assert "images/figures/generated/supplementary-neuropixels-unit-yield.svg" not in manuscript
    assert "60 sessions from 16 mice" in manuscript
    assert "./interactive/neuropixels-trajectories.html" in manuscript
    assert ":label: fig-supp-neuropixels-recorded-trajectories" in manuscript
    assert (
        ":placeholder: ./images/figures/generated/"
        "supplementary-neuropixels-trajectories.svg"
    ) in manuscript
    assert "332 probe trajectories from 57 sessions and 16 mice" in manuscript
    assert "Three of the 60 source sessions are excluded" in manuscript
    assert "100-micrometer mesh derived from the Allen CCF 2017" in manuscript
    assert "**A,** an oblique projection" in manuscript
    assert "trajectories extend laterally toward the L direction marker" in manuscript
    assert "### Eye tracking across modalities" in manuscript
    assert manuscript.count("[Supplementary Figure 4](#fig-supp-eye-tracking)") == 1
    assert "./interactive/eye-tracking-viewer.html" in manuscript
    assert ":label: fig-supp-eye-tracking\n:enumerated: false" in manuscript
    assert "Eye fits, blink flags, and stimulus rows" in manuscript
    assert "Fit-source tabs switch the center field" in manuscript
    assert "standard-oddball Neuropixels, mesoscope, and SLAP2 sessions" in manuscript
    assert "5th–95th percentile nonblink range" in manuscript
    assert "**B,** a dorsal projection" in manuscript
    assert manuscript.count(
        "[Supplementary Figure 5](#fig-supp-optotagging-heatmaps)"
    ) == 1
    assert "./interactive/optotagging-heatmaps.html" in manuscript
    assert ":label: fig-supp-optotagging-heatmaps\n:enumerated: false" in manuscript
    assert (
        ":placeholder: ./images/figures/generated/optotagging-heatmaps.svg"
        in manuscript
    )
    assert "all 60 source sessions" in manuscript
    assert "exact laser-on windows" in manuscript
    assert "**A,** the 5 Hz response" in manuscript
    assert "five teal marks denote the exact 10 ms laser pulses" in manuscript
    assert "**B,** Overall optotagged-cell yield" in manuscript
    assert "**C,** Yield by Allen major parent area" in manuscript
    assert "**D,** The 18 structures with the highest mean yield" in manuscript
    assert "selectors constrain the view to available values" in manuscript
    assert "gray dots denote individual sessions and teal bars or lines denote means" in manuscript
    assert "include only sessions sampling that area" in manuscript
    for obsolete in (
        "segmentation-neuropixels.html",
        "segmentation-mesoscope.html",
        "segmentation-slap2.html",
    ):
        assert obsolete not in manuscript
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
    assert "SLAP2 NWB files" in records
    assert "DANDI:001424" in records
    assert records.count(":::{tab-item}") == 4
    assert records.count(
        "| Question | NWB contents | Representative PyNWB entry point |"
    ) == 4
    assert "nwbfile.units.to_dataframe()" in records
    assert 'nwbfile.processing[plane]["dff_timeseries"]' in records
    assert 'nwbfile.processing["ophys"]["ImageSegmentation"]' in records
    assert 'nwbfile.processing["ophys"]["Fluorescence_DMD1"]["DMD1_dFF"]' in records


def test_segmentation_viewers_are_captioned_and_importer_preserved() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    raw_start = manuscript.index(":label: fig-aligned-neural-signals")
    segmentation_start = manuscript.index(":label: fig-segmentation-viewers")
    segmentation_stop = manuscript.index(":label: fig-unit-extraction-plan")
    segmentation_captions = manuscript[segmentation_start:segmentation_stop]
    segmentation_text = " ".join(segmentation_captions.split())
    assert raw_start < segmentation_start < segmentation_stop
    assert ":enumerated: false" not in segmentation_captions
    assert (
        ":placeholder: ./images/figures/generated/figure-06-segmentation-viewers.svg"
        in segmentation_captions
    )
    assert "same platform logos as the other multimodal figures" in segmentation_text
    assert "all six probes" in segmentation_text
    assert "all eight VISp and VISl planes" in segmentation_text
    assert "provides DMD1 and DMD2" in segmentation_text
    assert "every probe or imaging plane" in segmentation_text
    assert "complete NWB segmentation" in segmentation_text
    assert "complete source segmentation" in segmentation_text
    assert "30 s ΔF/F (%)" in segmentation_text
    assert "30 s, approximately 200 Hz ΔF/F (%) trace" in segmentation_text
    assert "waveform-spread band" in segmentation_text
    assert "common-mode correction is enabled by default" in segmentation_text
    assert (
        "fast-scanning x axis is horizontal for mesoscope and vertical for SLAP2"
        in segmentation_text
    )
    assert "mark its direction" not in segmentation_text
    assert "twenty activity-bearing filters sampled evenly across filter order" in segmentation_text
    assert "grayscale average projection" in segmentation_text
    assert "arrays and masks receive the same publication-level axis transpose" in segmentation_text
    assert "background controls alter only" in segmentation_text
    assert "activity image" not in segmentation_text.lower()
    assert "QC-passing" not in segmentation_text
    assert "No tab shows stimulus annotations" in segmentation_text
    assert "first sequence omission" not in segmentation_text
    assert "first motor mismatch" not in segmentation_text
    assert "fig-supp-segmentation-viewers" not in manuscript
    assert (
        "[796630_2025-08-28_14-25-34]"
        "(https://open.quiltdata.com/b/aind-open-data/tree/"
        "796630_2025-08-28_14-25-34/) "
        "([DANDI:001424](https://dandiarchive.org/dandiset/001424/draft/files))"
    ) in manuscript

    importer = runpy.run_path(str(REPO_ROOT / "scripts" / "import_google_doc.py"))
    for function_name in (
        "add_segmentation_viewer_figures",
        "add_slap2_nwb_contents",
    ):
        assert importer[function_name](manuscript) == manuscript
    assert "DANDI:001424" in importer["SLAP2_RAW_SOURCE"]
    assert importer["SEGMENTATION_VIEWER_BLOCK"].count(":::{iframe}") == 1
    assert ":label: fig-segmentation-viewers" in importer["SEGMENTATION_VIEWER_BLOCK"]


def test_data_explorer_uses_generated_assets_without_manuscript_data() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")

    assert manuscript.count("interactive/data-explorer.html") == 1
    assert ":placeholder: ./images/figures/generated/session-inventory.svg" in manuscript
    assert ":label: fig-recording-session-inventory" in manuscript
    assert "Recording-session inventory and quality-control summary" in manuscript
    assert "Failed sessions are unfilled with borders colored by session\ntype" in manuscript
    assert re.search(
        r"numbered\s+markers identify descriptive QC tags",
        manuscript,
    )
    assert "whitespace\nseparates the motor-first and sequence-first groups" in manuscript
    assert "publication-data-source" not in manuscript
    assert "publication-data-table" not in manuscript
    assert "View grouped static summary tables" not in manuscript


def test_figure_captions_and_interactive_placement() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")

    assert "A visual sequence establishes an expectation" in manuscript
    assert "**B,** To sample these nested scales" in manuscript
    assert "Neuropixels sampled every context once" in manuscript
    assert "mesoscope repeated each context twice" in manuscript
    assert "SLAP2 sampled the motor-habituated cohort" in manuscript
    assert "eight outlined habituation and training sessions" in manuscript
    assert "a standard control precedes each context" in manuscript
    assert "control and system-identification stimuli" in manuscript
    assert "vertical selector above\nthe Context block" in manuscript
    assert "Sources: pinned\n[example tables]" in manuscript
    assert "generate_experiment_csv.py" in manuscript
    assert "**D,** Context panels summarize" not in manuscript
    assert "Rows compare Neuropixels electrophysiology" in manuscript
    assert "Columns show each rig geometry" in manuscript
    assert "nine native-resolution images" in manuscript
    assert re.search(
        r"searchable, filterable tables sourced from local\s+CSV snapshots",
        manuscript,
    )
    assert "./interactive/neural-viewer.html" in manuscript
    assert ":label: fig-aligned-neural-signals" in manuscript
    assert ":placeholder: ./images/figures/generated/raw-neural-recordings.svg" in manuscript
    assert "Representative raw-data excerpts from one public session" in manuscript
    assert "**Static** view arranges all available recordings" in manuscript
    assert "overlapping raw-image cards" in manuscript
    assert "**A,** all six Neuropixels probe heatmaps" in manuscript
    assert "eight mesoscope plane stills" in manuscript
    assert "two merged SLAP2 plane previews" in manuscript
    assert "black-referenced display gain" in manuscript
    assert "1st–99.5th max-channel percentiles" in manuscript
    assert "400 × 640 lossless WebP frames" in manuscript
    assert "transpose it for\npublication display" in manuscript
    assert "fast-scanning x axis vertical" in manuscript
    assert "single aligned source frame without temporal averaging" in manuscript
    assert "hue-preserving gamma of 0.55" in manuscript
    assert "shown to introduce the native acquisition formats" in manuscript
    assert "Event-aligned raw data across recording modalities" not in manuscript
    assert "prediction-violating event" not in manuscript
    assert re.search(r"Microscopy\s+playback uses elapsed time", manuscript)
    assert "raw AP acquisition stream supplied to spike sorting" in manuscript
    assert "AP samples are not median-corrected" in manuscript
    assert "remain visible as vertical stripes" in manuscript
    assert "ecephys_830846_2026-03-09_10-32-54" in manuscript
    assert "ecephys_820459_2025-11-10_15-07-13" not in manuscript
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
        < manuscript.index("fig-segmentation-viewers")
        < manuscript.index("fig-unit-extraction-plan")
        < manuscript.index("## Receptive field analysis across modalities")
        < manuscript.index("fig-basic-stimuli-plan")
    )
    assert "[Figure 6](#fig-segmentation-viewers)" in manuscript
    assert "[Figure 7](#fig-unit-extraction-plan) and the modality subsections below" in manuscript
    assert "This analysis and [Figure 8](#fig-basic-stimuli-plan)" in manuscript
    assert "[Figure 10](#fig-standard-oddball-plan) are planning placeholders" in manuscript
    assert "./interactive/behavior-viewer.html" in manuscript
    assert ":placeholder: ./images/figures/generated/synchronized-behavior.svg" in manuscript
    assert "Synchronized behavior and running across recording modalities" in manuscript
    assert "**A–C,** Camera\nviews and complete-session running profiles" in manuscript
    assert "Neuropixels\n(**A**), mesoscope (**B**), and SLAP2 (**C**)" in manuscript
    assert "same mouse and source\nsession" in manuscript
    assert "share one time axis" in manuscript
    assert "using the Figure\n2 block colors" in manuscript
    assert "**D,** Mean forward running speed in each protocol block" in manuscript
    assert "compared on one shared cm/s axis" in manuscript
    assert "each bar is the\nmean across mice" in manuscript
    assert "legend values report included mice" in manuscript
    assert "and reconstructed stimulus state for the selected modality" in manuscript
    assert "paired control-versus-context running" not in manuscript
    assert "8192 counts/revolution, an 8.255 cm disc radius" in manuscript
    assert "1st–99th luminance percentiles" in manuscript
    assert "maps median luminance to 35%" in manuscript
    assert "Event-centered excerpts from real Neuropixels" not in manuscript
    assert "figure-06-behavior-tracking-plan.png" not in manuscript
    assert "continuous raw\nbehavioral videos" in manuscript
    assert "[Figure 9](#fig-behavior-tracking) show these streams" in manuscript
    assert "[](#fig-behavior-tracking)" not in manuscript
    for number, label in (
        (1, "fig-graphical-abstract"),
        (2, "fig-interactive-experimental-design"),
        (3, "fig-multimodal-pipelines"),
        (4, "fig-recording-session-inventory"),
        (5, "fig-aligned-neural-signals"),
        (6, "fig-segmentation-viewers"),
        (7, "fig-unit-extraction-plan"),
        (8, "fig-basic-stimuli-plan"),
        (9, "fig-behavior-tracking"),
        (10, "fig-standard-oddball-plan"),
    ):
        assert f"[Figure {number}](#{label})" in manuscript
    assert re.search(r"\[\]\(#fig-", manuscript) is None
    assert "NWB running\nspeed and stimulus rows share the sync-file clock" in manuscript
    assert "reported dropped frames are removed before mapping" in manuscript
    assert "per-frame Harp timestamps on the acquisition clock" in manuscript
    assert "DeepLabCut" in manuscript
    assert "SLEAP" in manuscript
    assert "Lightning Pose" in manuscript
    assert "facial and\nbody motion energy" in manuscript
    assert "per-frame Harp timestamps for SLAP2" in manuscript
    assert "- Motion energy of the face?" not in manuscript

    figure_1 = manuscript.index(":label: fig-graphical-abstract")
    cohort_link = manuscript.index("[Figure 1C](#fig-graphical-abstract)")
    explanation = manuscript.index("The four distinct session contexts")
    viewer = manuscript.index(":label: fig-interactive-experimental-design")
    assert figure_1 < cohort_link < explanation < viewer


def test_custom_layout_widens_article_and_hides_duplicate_sidebar() -> None:
    stylesheet = (REPO_ROOT / "styles.css").read_text(encoding="utf-8")

    assert ".myst-primary-sidebar" in stylesheet
    assert "display: none !important" in stylesheet
    assert "minmax(10ch, 20ch)" in stylesheet
    assert "#fig-graphical-abstract" in stylesheet
    assert "#fig-experimental-design" not in stylesheet
    assert "#fig-interactive-experimental-design .relative.inline-block" in stylesheet
    assert "height: 704px" in stylesheet
    assert "height: 560px" in stylesheet
    assert "#fig-supp-neuropixels-unit-yield" in stylesheet
    assert "max-width: 660px" in stylesheet
    assert "#fig-supp-neuropixels-recorded-trajectories" in stylesheet
    assert "max-width: 1200px" in stylesheet
    assert "grid-template-columns: minmax(0, 660px) minmax(0, 1fr)" in stylesheet
    assert "@media (min-width: 1280px)" in stylesheet
    assert "@media (max-width: 1100px)" not in stylesheet
    assert "article > figure.table-hover-source" in stylesheet
    assert ".hover-card-content:has(.table-hover-source) .hover-document" in stylesheet
    assert "max-height: min(460px, calc(100vh - 2rem))" in stylesheet
    assert "#fig-behavior-tracking" in stylesheet
    assert "container-type: inline-size" in stylesheet
    assert "max-width: 900px" not in stylesheet
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
        ":placeholder: ./images/figures/generated/figure-02-context-controls.svg"
        in manuscript
    )
    assert "The **Interactive** view" in manuscript
    assert "control and system-identification stimuli" in manuscript