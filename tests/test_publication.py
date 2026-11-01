import base64
import csv
import datetime as dt
import hashlib
import json
import re
import runpy
import struct
import urllib.parse
from collections import Counter
from copy import deepcopy
from html.parser import HTMLParser
from pathlib import Path

import pytest

from openscope_p3_publication.authorship import apply_author_review
from openscope_p3_publication.figures import (
    load_experimental_session_records,
    load_individual_session_table,
)
from openscope_p3_publication.neural_response_figure import (
    load_neuropixels_event_responses,
    response_matrix,
)

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


def test_snapshot_workflow_commits_refreshed_provenance() -> None:
    workflow = (REPO_ROOT / ".github/workflows/update-publication-snapshots.yml").read_text(
        encoding="utf-8"
    )
    updater = publication_snapshot_updater()

    for constant in (
        "RUNNING_STATISTICS_PATH",
        "BEHAVIOR_STATIC_PROVENANCE_PATH",
        "PUPIL_EVENT_PROVENANCE_PATH",
    ):
        assert updater[constant].relative_to(REPO_ROOT).as_posix() in workflow


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
    pupil_path = tmp_path / "pupil-event-responses.provenance.json"
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
    pupil_path.write_text(
        json.dumps(
            {"source_snapshots": {"experimental_sessions": {"sha256": "old"}}}
        ),
        encoding="utf-8",
    )
    updater["refresh_session_snapshot_dependents"].__globals__.update(
        {
            "RUNNING_STATISTICS_PATH": running_path,
            "BEHAVIOR_STATIC_PROVENANCE_PATH": behavior_path,
            "PUPIL_EVENT_PROVENANCE_PATH": pupil_path,
        }
    )

    updater["refresh_session_snapshot_dependents"](session_path, previous)

    running = json.loads(running_path.read_text(encoding="utf-8"))
    behavior = json.loads(behavior_path.read_text(encoding="utf-8"))
    pupil = json.loads(pupil_path.read_text(encoding="utf-8"))
    assert running["source_session_records"]["sha256"] == file_sha256(session_path)
    assert running["sessions"][0]["source_row"] == 8
    assert behavior["running_statistics_sha256"] == file_sha256(running_path)
    assert pupil["source_snapshots"]["experimental_sessions"]["sha256"] == (
        file_sha256(session_path)
    )


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

    assert re.findall(r"^:::\{warning\} (.+)$", manuscript, re.MULTILINE) == [
        "Author list not final"
    ]
    for stale_marker in (
        "Work in progress",
        "manuscript-wip",
        "Manuscript status",
        "This is a preliminary draft",
        "[Figure 7](#fig-unit-extraction-plan) and the modality subsections",
        "To be written",
        "Supplementary Fig. X",
        "XXXX",
        "CITE PAPER WHEN AVAILABLE",
        '<span class="mark">',
        "More caveats?",
    ):
        assert stale_marker not in manuscript


@pytest.fixture(name="author_review_example")
def author_review_data() -> tuple[dict, dict]:
    payload = {
        "project_name": "example-project",
        "sections": ["Original section", "Corrected section", "Other section"],
        "contributors": [
            {
                "author": {"name": "First Author", "affiliation": ["Example Institute"]},
                "credit_levels": [{"role": "software", "level": "supporting"}],
                "section_levels": [
                    {"section": "Original section", "level": "supporting", "description": "QC"},
                    {"section": "Other section", "level": "equal"},
                ],
            },
            {"author": {"name": "Second Author"}},
            {"author": {"name": "Third Author"}},
        ],
    }
    review = {
        "project": "example-project",
        "commit": "reviewed-version",
        "contributors": {
            "Second Author": {"name": "Corrected Name"},
            "First Author": {"sections": {"Original section": "Corrected section"}},
        },
    }
    return payload, review


def test_author_review_preserves_submissions_and_portal_order(author_review_example) -> None:
    payload, review = author_review_example
    original_payload = deepcopy(payload)
    original_review = deepcopy(review)

    reviewed = apply_author_review(payload, review, "reviewed-version")

    assert payload == original_payload
    assert review == original_review
    assert [entry["author"]["name"] for entry in reviewed["contributors"]] == [
        "First Author", "Corrected Name"
    ]
    expected = deepcopy(payload)
    expected["contributors"] = expected["contributors"][:2]
    expected["contributors"][0]["section_levels"][0]["section"] = "Corrected section"
    expected["contributors"][1]["author"]["name"] = "Corrected Name"
    assert reviewed == expected


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"project": "other-project"}, "project does not match"),
        ({"commit": "other-version"}, "commit does not match"),
        ({"contributors": {}}, "nonempty mapping"),
        ({"contributors": []}, "nonempty mapping"),
        ({"contributors": {"Unknown Author": {}}}, "unknown contributors"),
        ({"contributors": {"First Author": {"roles": []}}}, "Unsupported"),
        ({"contributors": {"First Author": {"name": " "}}}, "nonempty string"),
        ({"contributors": {"First Author": {"sections": []}}}, "must be a mapping"),
        (
            {"contributors": {"First Author": {"sections": {"Absent": "Corrected section"}}}},
            "not present",
        ),
        (
            {"contributors": {"First Author": {"sections": {"Original section": "Absent"}}}},
            "not a project section",
        ),
        (
            {"contributors": {"First Author": {"sections": {"Original section": "Other section"}}}},
            "would contain duplicates",
        ),
        (
            {"contributors": {"First Author": {"name": "Second Author"}, "Second Author": {}}},
            "names would contain duplicates",
        ),
    ],
)
def test_author_review_rejects_invalid_changes(author_review_example, changes, message) -> None:
    payload, review = author_review_example
    review.update(changes)

    with pytest.raises(ValueError, match=message):
        apply_author_review(payload, review, "reviewed-version")


def test_author_review_rejects_ambiguous_portal_names(author_review_example) -> None:
    payload, review = author_review_example
    payload["contributors"][2]["author"]["name"] = "First Author"

    with pytest.raises(ValueError, match="nonempty and unique"):
        apply_author_review(payload, review, "reviewed-version")


def test_authorship_snapshot_is_portal_backed() -> None:
    authors = (REPO_ROOT / "authors.yml").read_text(encoding="utf-8")
    avatars = json.loads((REPO_ROOT / "author_avatars.json").read_text(encoding="utf-8"))
    avatar_source = json.loads(
        (REPO_ROOT / "author_portrait_sources.json").read_text(encoding="utf-8")
    )
    assert avatars == avatar_source

    commit = re.search(r'^  commit: "([0-9a-f]{32})"$', authors, re.MULTILINE)
    assert commit
    assert 'project: "p3_data_release"' in authors
    assert f"commit={commit.group(1)}&format=json" in authors
    author_ids = re.findall(r'^      id: "([^"]+)"$', authors, re.MULTILINE)
    assert len(author_ids) == len(set(author_ids))
    assert authors.count('\n      name: "') == len(author_ids)
    assert len(author_ids) >= len(avatars["contributors"]) + len(avatars["unresolved"])
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
    assert set(avatars["contributors"]) | set(avatars["unresolved"]) <= set(author_ids)
    assert set(avatars["contributors"]).isdisjoint(avatars["unresolved"])
    assert authors.count('\n      avatar_url: "https://') == len(avatars["contributors"])
    for author_id, record in avatars["contributors"].items():
        assert record["source_page"].startswith("https://")
        assert urllib.parse.urlparse(record["avatar_url"]).netloc in {
            "cdn.prod.website-files.com",
            "static1.squarespace.com",
            "faculty.eng.ufl.edu",
            "cdn.vanderbilt.edu",
            "lh7-us.googleusercontent.com",
            "robertodf.github.io",
            "faculty-directory.dartmouth.edu",
            "ido4848.github.io",
            "profiles.ucl.ac.uk",
        }
        assert record["width"] >= 128
        assert record["height"] >= 128
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


def test_consecutive_mismatch_limits_replace_supplementary_figure() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    assert "fig-supp-mismatch-adjacency" not in manuscript
    assert "supplementary-mismatch-adjacency.svg" not in manuscript
    limitations = manuscript.split("## Limitations\n", 1)[1].split("\n## ", 1)[0]
    paragraph = " ".join(limitations.split())
    assert "./figure_sources/data/mismatch-adjacency.json" in limitations
    assert "./figure_sources/data/mismatch-adjacency.provenance.json" in limitations
    path = REPO_ROOT / "figure_sources" / "data" / "mismatch-adjacency.json"
    contexts = json.loads(path.read_text(encoding="utf-8"))["contexts"]
    counts = [contexts[name]["summary"]["adjacent_count"]
              for name in ("standard", "sequence", "duration")]
    assert f"{counts[0]}, {counts[1]}, and {counts[2]} adjacent events among 140" in paragraph
    sensorimotor = contexts["sensorimotor"]
    assert f'{sensorimotor["summary"]["adjacent_count"]} of 140 events' in paragraph
    intervals = [event["interval"] for event in sensorimotor["events"]
                 if event["interval"] is not None]
    assert f"{sum(interval < 1 for interval in intervals)} below 1 s" in paragraph
    assert f"{sum(interval < 0.5 for interval in intervals)} below 0.5 s" in paragraph
    assert f"{min(intervals):.3f} s" in paragraph
    assert sum(context["sessions"] for context in contexts.values()) == 60
    assert all(context["schedule_identical_across_sessions"] for context in contexts.values())
    captions = dict(re.findall(
        r"^:label: ([^\n]+)\n(?:(?!^:::).)*?\*\*Supplementary Figure (\d+)\.\*\*",
        manuscript, re.MULTILINE | re.DOTALL,
    ))
    for number, label in re.findall(r"\[Supplementary Figure (\d+)\]\(#([^)]+)\)", manuscript):
        assert captions[label] == number


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
    assert len(figures) == 5
    assert manuscript.count(":::{figure} ./images/figures/imported/") == 0
    assert manuscript.count(":::{figure} ./images/figures/generated/") == 5
    assert "./images/figures/generated/figure-01-overview.svg" in manuscript
    assert "./images/figures/generated/figure-01-panel-c-cohorts.svg" not in manuscript
    assert ":label: fig-experimental-design" not in manuscript
    for options in figures:
        assert ":label:" in options
        assert ":alt:" in options

    assert (
        "Distributed predictive-processing hypotheses motivate multimodal, multi-context recordings"
        in manuscript
    )
    assert "**C,** Five cohort timelines" in manuscript
    assert "Within-session architecture for cross-context comparison" in manuscript
    assert "see [Figure 1](#fig-graphical-abstract)" in manuscript
    assert "[Supplementary Figure 2](#fig-multimodal-pipelines)" in manuscript
    assert "./images/figures/generated/supplementary-recording-hardware.svg" in manuscript
    assert "./images/figures/generated/figure-06-segmentation-viewers.svg" not in manuscript
    assert "./images/figures/generated/figure-06-unit-extraction-mesoscope.svg" in manuscript
    assert "./images/figures/generated/figure-07-unit-extraction-plan.svg" in manuscript
    assert "./images/figures/generated/receptive-fields.svg" in manuscript
    assert "./images/figures/generated/figure-08-basic-stimuli-plan.svg" not in manuscript
    assert "./images/figures/generated/figure-11-standard-oddball-plan.svg" not in manuscript
    assert "Neuropixels uses six acute trajectories" in manuscript
    hardware_start = manuscript.index("## Multimodal recording hardware")
    methods_start = manuscript.index("# Methods")
    hardware_section = manuscript[hardware_start:methods_start]
    assert "Behavior cohorts" not in hardware_section
    assert "cohort-specific order" not in hardware_section


def test_stimulus_sources_are_plain_methods_prose() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    start = manuscript.index("Pinned generated example tables are available for")
    end = manuscript.index("particular recorded session.", start)
    assert manuscript.index("## Visual stimulation") < start < end
    assert end < manuscript.index("(stimuli-parameters)=")
    assert "Stimulus table and presentation sources" not in manuscript
    visual_methods = manuscript[manuscript.index("## Visual stimulation"):end]
    assert ":::{note}" not in visual_methods
    assert "\n:::\n" not in manuscript[start:end + len("particular recorded session.")]
    assert not any(line.startswith(">") for line in manuscript[start:end].splitlines())
    assert "stored as NWB `TimeIntervals`" in manuscript[start:end]


def test_data_access_explains_archive_code_and_workflow_skills() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    access = manuscript.split("## Accessing the data and code", 1)[1].split("## Limitations", 1)[0]
    assert "(data-access)=" in manuscript
    assert "data-access-code-example" not in manuscript
    assert "{code-cell}" not in access
    for dandiset in ("001637", "001768", "001424"):
        assert f"https://dandiarchive.org/dandiset/{dandiset}" in access
    assert "https://github.com/AllenNeuralDynamics/openscope_p3_data_release_paper" in access
    assert "https://github.com/AllenInstitute/openscope_databook" in access
    assert "openscope_databook/download-nwb" in access
    assert "openscope_databook/stream-nwb" in access
    assert "asset identifiers and checksums" in access
    for skill in ("prompting-conventions", "bash-safety", "authoring-skills"):
        assert f".claude/skills/{skill}/SKILL.md" in access
        assert (REPO_ROOT / ".claude" / "skills" / skill / "SKILL.md").is_file()


def test_static_figure_reorganization_keeps_ten_main_and_six_supplementary_figures() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    blocks = re.findall(
        r"^:::\{(?:figure|iframe)\} [^\n]+\n.*?^:::\s*$",
        manuscript, re.MULTILINE | re.DOTALL,
    )
    main = []
    for block in blocks:
        caption = block.removesuffix(":::").partition("\n\n")[2].strip()
        if ":enumerated: false" not in block and caption:
            main.append(block)
    labels = [re.search(r"^:label: (.+)$", block, re.MULTILINE).group(1) for block in main]
    assert labels == [
        "fig-graphical-abstract", "fig-recording-session-inventory", "fig-aligned-neural-signals",
        "fig-mesoscope-unit-extraction", "fig-unit-extraction-plan", "fig-ecephys-qc-dashboard",
        "fig-basic-stimuli-plan", "fig-supp-wavemap", "fig-standard-oddball-responses",
        "fig-behavior-tracking",
    ]
    for number in range(1, 7):
        assert manuscript.count(f"**Supplementary Figure {number}.**") == 1
    assert len(re.findall(r"\*\*Supplementary Figure \d+\.\*\*", manuscript)) == 6
    assert ":label: fig-supp-eye-tracking" not in manuscript
    assert ":label: fig-supp-pupil-event-responses" not in manuscript
    assert main[7].index("**A,** Enlarged visual-cortex") < main[7].index("**B,** Saved regional")
    assert ":label: fig-supp-sensorimotor-running" not in manuscript
    assert ":::{iframe} ./interactive/unit-yield.html" not in manuscript
    assert "[Figure 6D](#fig-ecephys-qc-dashboard)" in manuscript
    assert "supplementary-cell-type-validation.svg" in manuscript
    assert "(fig-interactive-experimental-design)=" in manuscript
    assert "(fig-supp-optotagging-heatmaps)=" in manuscript
    assert "(fig-supp-neuropixels-recorded-trajectories)=" in manuscript
    assert "| D | -3.9 | 4.2 | 1.2 | 0.75 |" in manuscript
    assert "**(J-L)** Activity traces" in manuscript


def test_mesoscope_and_slap2_quality_figures_remain_separate() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    blocks = re.findall(
        r"^:::\{(?:figure|iframe)\} [^\n]+\n.*?^:::\s*$",
        manuscript,
        re.MULTILINE | re.DOTALL,
    )
    mesoscope = next(
        block for block in blocks if ":label: fig-mesoscope-unit-extraction\n" in block
    )
    slap2 = next(block for block in blocks if ":label: fig-unit-extraction-plan\n" in block)

    assert manuscript.count(":label: fig-mesoscope-unit-extraction\n") == 1
    assert manuscript.count(":label: fig-unit-extraction-plan\n") == 1
    assert ":::{iframe} ./interactive/mesoscope-plane-snr.html" in mesoscope
    assert (
        ":placeholder: ./images/figures/generated/figure-06-unit-extraction-mesoscope.svg"
        in mesoscope
    )
    assert ":::{figure} ./images/figures/generated/figure-07-unit-extraction-plan.svg" in slap2
    assert "columns are in preparation" not in mesoscope
    assert "complete 81-session cohort" in mesoscope
    assert "multiplane-ophys_839909_2026-02-20_12-53-27" in mesoscope
    assert "2,540 sources" in slap2
    assert "individual footprint" in slap2
    assert "900-920 s" in slap2
    assert "20 ms decay" in slap2
    assert "40 ms after" in slap2
    assert "**C–E,** Histograms" in slap2
    assert "**not** the detection threshold" in slap2
    assert "single black arrow" in slap2
    assert "DMD2 map" in slap2 and "59 sources" in slap2
    assert "proximal DMD1 map" not in slap2
    assert "Both DMDs remain in the archive scatter and class-composition summaries" in slap2
    assert "transparent filled ROIs" in slap2
    assert "this session only" in slap2
    assert "all 2,521 classified sources" in slap2
    assert "without refitting" in slap2
    assert "one shared vertical 0-100%" in slap2
    assert "first four bars" in slap2
    assert "remaining 20 bars" in slap2
    assert "1,026 Intermediate, 830 High SNR" in slap2
    assert "Percentage denominators exclude those 19 sources" in slap2
    assert "Non-low SNR" not in slap2
    assert "Stimulus-context event-rate plots are omitted" in slap2
    assert "Mean ± SEM" not in slap2
    assert "all 277 somatic ROIs" in mesoscope
    assert "not amplitude histograms" in mesoscope
    assert "all 81 sessions individually" in mesoscope
    assert "one plane from one session" in mesoscope
    for label in ("A", "C–E", "F", "G", "H", "I"):
        assert f"**{label},**" in mesoscope
    assert "(**B,** orange outline)" in mesoscope
    for label in ("A", "C–E", "F", "G", "H"):
        assert f"**{label},**" in slap2
    assert "**I,**" not in slap2
    assert "(**B**)" in slap2
    assert manuscript.index(mesoscope) < manuscript.index(slap2)
    assert not re.search(r"^(?:<{7}|={7}|>{7})", manuscript, re.MULTILINE)


def test_mesoscope_static_view_matches_its_manuscript_placeholder() -> None:
    svg = (
        REPO_ROOT / "images/figures/generated/figure-06-unit-extraction-mesoscope.svg"
    ).read_text(encoding="utf-8")
    html = (REPO_ROOT / "interactive/mesoscope-plane-snr.html").read_text(encoding="utf-8")
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    assert f'data:image/svg+xml;base64,{encoded}' in html


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
    assert "[Supplementary Figure 2](#fig-multimodal-pipelines)" in hardware
    assert methods.startswith(
        "# Methods\n\n::::{dropdown} Show complete Methods\n"
        ":class: manuscript-methods-dropdown\n"
    )
    assert methods.rstrip().endswith("::::")
    assert "## Experimental animals" in methods
    assert "(registered-movie-excerpts)=" in methods
    assert manuscript.count("### NWB data packaging") == 1
    assert "(data-processing)=\n## Data processing" in methods
    processing = methods.split("(data-processing)=\n", 1)[1]
    assert (
        processing.index("### Neuropixels extracellular electrophysiology")
        < processing.index("### Neuropixels mismatch-response summaries")
        < processing.index("### Mesoscope two-photon calcium imaging")
    )
    assert ":label: fig-multimodal-pipelines" not in methods
    assert "[Supplementary Figure 2](#fig-multimodal-pipelines)" in methods
    assert "#### Neuropixels Ephys NWB Packaging Pipeline" in methods
    assert "#### SLAP2 synchronization" in methods
    assert "#### SLAP2 NWB Packaging Pipeline" in methods
    assert "11f8d942-a12c-44b5-84db-d084164294d1" in methods
    assert "f8d26d18-3daf-45fd-9671-32b68d2a9441" in methods

    protocols = methods.split("## Stimuli parameters\n", 1)[1].split(
        "## Neuronal recording modalities\n", 1
    )[0]
    assert len(re.findall(r"^### Session type [1-4]: ", protocols, re.MULTILINE)) == 4
    assert manuscript.count("### Session type ") == 4
    assert "### Session type " not in manuscript[:methods_start]
    assert "### Shared session design" in protocols
    assert "### Shared session design" not in manuscript[:methods_start]
    assert re.findall(r"^([1-8])\.\s+\S", protocols, re.MULTILINE) == list("12345678")
    assert "[Stimuli parameters](#stimuli-parameters)" in manuscript[:methods_start]
    assert "| Recording position |" not in manuscript
    introduction = " ".join(manuscript[:methods_start].split())
    assert re.search(
        r"The motor cohort was recorded in the order:? sensorimotor mismatch, "
        r"standard oddball, sequence mismatch, and duration mismatch\.",
        introduction,
    )
    assert re.search(
        r"The sequence cohort was recorded in the order:? sequence mismatch, "
        r"duration mismatch, standard oddball, and sensorimotor mismatch\.",
        introduction,
    )
    assert not re.search(
        r"^\s+\d+\.\s+(?:Sequence|Duration|Sensorimotor) mismatch",
        manuscript[:methods_start],
        re.MULTILINE,
    )


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
    prose = " ".join(manuscript.split())

    for number in range(1, 6):
        assert manuscript.count(f"**Supplementary Figure {number}.**") == 1
    assert manuscript.count(":enumerated: false\n:width: 100%") >= 3
    assert "supplementary-neuropixels-implant-trajectories.svg" in manuscript
    assert "./interactive/unit-yield.html" not in manuscript
    assert "(fig-supp-neuropixels-unit-yield)=" in manuscript
    assert "[Figure 6D](#fig-ecephys-qc-dashboard)" in manuscript
    assert "these broader gates differ from b, c, f and g" in prose.lower()
    assert "60 unit-bearing sessions from 16 mice" in prose
    assert "./interactive/neuropixels-trajectories.html" in manuscript
    assert "(fig-supp-neuropixels-recorded-trajectories)=" in manuscript
    assert (
        ":placeholder: ./images/figures/generated/"
        "supplementary-neuropixels-implant-trajectories.svg"
    ) in manuscript
    assert "332 probe trajectories from 57 sessions and 16 mice" in prose
    assert "Three of the 60 source sessions are excluded" in prose
    assert "100-micrometer mesh derived from the Allen CCF 2017" in prose
    assert "**D,** An oblique projection" in prose
    assert "trajectories extend laterally toward the l direction marker" in prose.lower()
    assert "fig-supp-eye-tracking" not in manuscript
    assert "./interactive/eye-tracking-viewer.html" not in manuscript
    assert "isolated runs of one to four samples" in prose.lower()
    assert "single recorded-brain view" in prose
    assert "rostral-left oblique orientation" in prose
    assert "**E,** A dorsal projection" not in prose
    assert "[Figure 8](#fig-supp-wavemap)" in manuscript
    assert "./interactive/optotagging-heatmaps.html" in manuscript
    assert "(fig-supp-optotagging-heatmaps)=" in manuscript
    assert ":label: fig-supp-optotagging-anatomy\n:enumerated: false" in manuscript
    assert (
        ":placeholder: ./images/figures/generated/cell-type-characterization.svg"
        in manuscript
    )
    assert "all 60 source sessions" in manuscript
    assert "mean baseline z score inside the exact laser pulses" in manuscript
    assert "**A,** The 5 Hz response" in manuscript
    assert "five teal marks denote the exact 10 ms laser pulses" in manuscript
    assert "**B,** Overall optotagged-cell yield" in manuscript
    assert "**C,** Yield by Allen major parent area" in prose
    assert "**D,** The 18 structures with the highest mean yield" in prose
    assert "All examples are measured, not schematic" in prose
    assert "a genuine 0.67 ms ISI" in prose
    assert "not Kilosort's global" in prose
    assert "All 6,000 native 30 kHz samples" in prose
    assert "Panels B, C, and D share a row" in prose
    assert "with E, F, and G below in left-to-right order" in prose
    assert "twenty random 500 ms chunks (10 s total)" in prose
    assert (
        "gray dots denote individual sessions and teal bars or lines denote means"
        in prose.lower()
    )
    assert "include only sessions sampling that area" in prose
    assert "./interactive/pupil-event-responses.html" not in manuscript
    assert "fig-supp-pupil-event-responses" not in manuscript
    assert "display-synchronized `start_time`" in manuscript
    assert "row i−2 `stop_time` to row i−1 `start_time`" in manuscript
    assert "row *i−2* `stop_time` to row *i−1* `start_time`" in prose
    assert "both repeats of standard control C1" in prose
    assert "Duration responses use the following commanded interstimulus interval" in prose
    assert "display-recorded stimulus interval" in prose
    assert "[Methods](#pupil-running-response-summaries)" in manuscript
    assert "without any temporal filtering" in manuscript
    assert "Individual traces show means ±1 SEM across valid trials" in prose
    assert "Population trace bands show ±1 SEM across mice" in prose
    assert "Mouse 830846's duration running panel is explicitly unavailable" in prose
    assert "./interactive/neuropixels-event-responses.html" in manuscript
    assert (
        ":label: fig-neuropixels-event-responses\n:enumerated: false\n:width: 100%"
        in manuscript
    )
    assert "**Supplementary Figure 6.** Neuropixels mismatch responses" in manuscript
    assert ":label: fig-standard-oddball-responses\n:width: 100%" in manuscript
    assert "./interactive/standard-oddball-explorer.html" in manuscript
    assert (
        ":placeholder: ./images/figures/generated/"
        "figure-10-neuropixels-event-responses.svg"
    ) in manuscript
    assert "units are distinct across sessions" in manuscript
    assert "and the same 16 events" in manuscript
    assert "z-score limits default to ±3" in manuscript
    assert "Rastermap 1.0 ordering" in manuscript
    assert "**Area** is the default row order" in manuscript
    assert "canonical parent area in Allen graph order" in manuscript
    assert "group and label exact peak-channel CCF locations" in manuscript
    assert "minimum and maximum depth" in manuscript
    assert "shared Greys-scale limit computed from both conditions" in manuscript
    assert "causal exponential spike-density kernel" in manuscript
    assert "Standard-oddball and sensorimotor windows span −0.75 to 0.75 s" in manuscript
    assert "duration windows −1.5 to 1.5 s" in manuscript
    # The sequence window was widened so the Q1 comparison element is visible.
    assert "sequence windows −2 to 1 s" in manuscript
    assert "10τ (100 ms) support" in manuscript
    assert "native 2.5 ms SDF is retained" in manuscript
    assert "hidden 97.5 ms pre-window" in manuscript
    assert "without an uncertainty band" in manuscript
    assert "Dashed guides mark the selected mismatch presentation" in manuscript
    assert "SST units have a positive 5 Hz optotagging response" in manuscript
    assert "±1 SEM across neurons" in manuscript
    assert "**Subtract baseline** control" in manuscript
    matrix_areas, _matrix_columns = response_matrix(load_neuropixels_event_responses())
    assert (
        f"same {len(matrix_areas)} frontal, visual, hippocampal, and thalamic areas"
        in prose
    )
    assert "at least 10 tested units in at least eight of the 16 events" in prose
    assert "12,968 sorted units" in manuscript
    assert "8,093 passed the manuscript QC thresholds" in manuscript
    # The four sessions come from 830794, not the 830846 the figure first used.
    # Scoped to the caption: 830846 is a real session listed under data records.
    figure_caption = manuscript[
        manuscript.index("Neuropixels mismatch responses by predictive-processing")
    :]
    figure_caption = figure_caption[: figure_caption.index("\n:::")]
    assert "mouse 830794" in figure_caption
    assert "830846" not in figure_caption
    assert "sequence-cohort mouse" not in figure_caption
    assert "Solid teal traces" in figure_caption
    assert "dashed gray traces" in figure_caption
    assert len(figure_caption.split()) <= 425
    assert "[Methods](#neuropixels-response-summaries)" in figure_caption
    assert "(neuropixels-response-summaries)=\n" in manuscript
    # Disclosures the caption must carry, each recording a real limitation.
    assert "a subsequence of the fixed order rather than re-embedding" in " ".join(
        (REPO_ROOT / "figure_sources/javascript/neuropixels-event-responses.html")
        .read_text(encoding="utf-8").split()
    )
    assert "hatched, not shaded" in manuscript
    assert "selected on the statistical test rather than on the plotted effect" in prose
    assert "revised upstream in August 2026" in manuscript
    # Responsiveness is defined in prose, not in the caption.
    assert "### Defining responsiveness per mismatch event" in manuscript
    assert "paired Wilcoxon signed-rank test across" in manuscript
    assert "two-sided Mann-Whitney *U*" in manuscript
    # The multiple-comparisons basis was re-measured; guard the corrected
    # numbers so the superseded 7-12x claim cannot return.
    assert "does a single" in manuscript
    assert "0.6 to" in manuscript
    assert "7 to 12 times chance" not in manuscript
    assert "8 to 13 percent" not in manuscript
    assert "with the difference in immediate stimulus history" in manuscript
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
    raw_data_start = manuscript.index("## Raw data across recording modalities")
    glossary_start = manuscript.index("# Glossary")
    assert records_start < nwb_contents < raw_data_start < glossary_start
    assert "# Data validation" not in manuscript

    records = manuscript[nwb_contents:raw_data_start]
    assert "DANDI:001424" in records
    assert "./interactive/nwb-file-contents.html" in records
    assert ":label: nwb-file-contents-viewer" in records
    assert "native collapsible PyNWB structure" in records
    assert "The **Static** view" in records
    assert ":title: Interactive NWB structures and static question tables" in records


def test_nwb_file_contents_explorer_uses_pinned_native_snapshots() -> None:
    viewer = (REPO_ROOT / "interactive" / "nwb-file-contents.html").read_text(
        encoding="utf-8"
    )
    assert 'id="nwb-file-contents-viewer"' in viewer
    assert 'data-view="interactive"' in viewer
    assert 'data-view="static"' in viewer
    assert viewer.count('data-view-panel="interactive"') == 3
    assert viewer.count('class="static-section"') == 4
    assert viewer.count("<table>") == 4
    assert viewer.count(
        "<th>Name</th><th>Description</th><th>Format</th><th>NWB Path</th>"
    ) == 4
    assert "<th>Question</th>" not in viewer
    assert "HDMF location" not in viewer
    assert 'data-tabs="interactive"' in viewer
    assert 'data-tabs="static"' not in viewer
    assert "selectView" in viewer
    assert "selectModality" in viewer
    assert "__NWB_FILE_CONTENTS_" not in viewer
    assert "__NEUROPIXELS_TREE__" not in viewer

    snapshot_dir = REPO_ROOT / "figure_sources" / "data" / "nwb-file-contents"
    for modality in ("neuropixels", "mesoscope", "slap2"):
        snapshot = snapshot_dir / f"{modality}.html"
        assert snapshot.is_file()
        with snapshot.open(encoding="utf-8") as stream:
            prefix = stream.read(20_000)
        assert "container-wrap" in prefix
        assert "PyNWB 3." in prefix
        assert "DANDI:001" in prefix
        assert "<script>" not in prefix


def test_segmentation_viewers_are_captioned_and_importer_preserved() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    raw_start = manuscript.index(":label: fig-aligned-neural-signals")
    segmentation_start = manuscript.index("(fig-segmentation-viewers)=")
    segmentation_stop = manuscript.index(":label: fig-unit-extraction-plan")
    segmentation_captions = manuscript[raw_start:segmentation_start]
    segmentation_text = " ".join(segmentation_captions.split())
    assert raw_start < segmentation_start < segmentation_stop
    assert ":enumerated: false" not in segmentation_captions
    assert (
        ":placeholder: ./images/figures/generated/raw-neural-recordings.svg"
        in segmentation_captions
    )
    assert manuscript.count(":::{iframe} ./interactive/neural-viewer.html") == 1
    assert ":::{iframe} ./interactive/segmentation-viewer.html" not in manuscript
    caption = segmentation_captions.split("\n\n", maxsplit=1)[1].split("\n:::", maxsplit=1)[0]
    assert len(caption.split()) < 250
    assert "**(G-I)** Extracted units or sources" in segmentation_text
    assert (
        "**(J-L)** Activity traces from ten activity-bearing units or sources"
        in segmentation_text
    )
    assert "layer 2/3 plane at 152 µm depth (H), and SLAP2 DMD1 (I)" in segmentation_text
    assert "DMD1, top; DMD2, bottom" in segmentation_text
    assert "common-mode-corrected voltage" in segmentation_text
    assert "sampled evenly across extraction order" in segmentation_text
    assert "annotated somatic region" in segmentation_text
    assert "six targeted raster regions" in segmentation_text
    assert "sampled brain regions indicated" in segmentation_text
    assert "30 s (K, L;" in segmentation_text
    for excluded in ("Scale bars:", "Image contrast", "Interactive", "gamma", "pixel-replacement"):
        assert excluded not in caption

    methods_start = manuscript.index("(recording-display-methods)=")
    methods_stop = manuscript.index("### NWB data packaging", methods_start)
    methods = " ".join(manuscript[methods_start:methods_stop].split())
    assert methods_stop < manuscript.index("# Data records")
    for detail in (
        "all 60 frames of each committed raw movie",
        "complete NWB segmentation",
        "SLAP2 trace samples are approximately 200 Hz",
        "common-mode-corrected AP voltage",
        "user-drawn `soma` ROI",
        "20 ms and 1000 µm",
        "not fluorescence intensity or extracted-source segmentation",
        "without segmentation overlays",
        "Movie excerpts displayed beneath segmentation masks",
        "separate elapsed-time windows",
        "source recordings, not reconstructed from extracted traces",
    ):
        assert detail in methods
    assert "vertical for SLAP2 in F and the interactive views" not in manuscript
    assert "mark its direction" not in segmentation_text
    assert "activity image" not in segmentation_text.lower()
    assert "QC-passing" not in segmentation_text
    assert "first sequence omission" not in segmentation_text
    assert "first motor mismatch" not in segmentation_text
    assert "fig-supp-segmentation-viewers" not in manuscript
    assert (
        "[796630_2025-08-28_14-25-34]"
        "(https://open.quiltdata.com/b/aind-open-data/tree/"
        "796630_2025-08-28_14-25-34/) "
        "([DANDI:001424](https://dandiarchive.org/dandiset/001424/draft/files))"
    ) in manuscript


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


@pytest.mark.parametrize(
    ("heading", "expected_terms"),
    [
        ("## Multimodal recording hardware", ("Neuropixels", "mesoscope", "SLAP2")),
        (
            "# Data records",
            (
                "AWS S3", "Code Ocean", "NWB", "DANDI", "behavioral", "processing code",
                "Neuropixels mismatch responses across predictive contexts",
            ),
        ),
        ("## Data tables", ("Neuropixels", "mesoscope", "SLAP2", "failed", "repeated", "aborted")),
        (
            "## Raw data across recording modalities",
            ("extracellular-voltage", "fluorescence", "sparse"),
        ),
        (
            "## Units extraction",
            ("Kilosort 4", "OASIS", "SILo", "source counts are not neuron counts"),
        ),
        (
            "# Supplementary Figure 6: Neuropixels mismatch responses across predictive contexts",
            ("Panel A", "panel B", "(Q1)", "(Q2)", "*q* values", "exploratory"),
        ),
        (
            "## Standard-oddball responsiveness across recording modalities",
            ("Neuropixels", "mesoscope", "SLAP2", "Q1", "Q2", "jointly", "exploratory"),
        ),
        (
            "## Cell-type characterization",
            ("Optotagging", "WaveMAP", "not molecular", "analysis-specific"),
        ),
        (
            "## Behavioral data analysis across modalities",
            ("All three recording modalities", "eye-ellipse fits", "likely-blink", "noisier"),
        ),
        ("## Limitations", ("passive viewing", "interchangeable", "validated")),
        ("# Conclusion", ("Neuropixels", "mesoscope", "SLAP2", "NWB", "replication")),
    ],
)
def test_manuscript_sections_have_explanatory_prose(
    heading: str, expected_terms: tuple[str, ...]
) -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    section = manuscript.split(f"{heading}\n", 1)[1]
    introduction = re.split(r"^(?:#{1,6} |:::\{)", section, maxsplit=1, flags=re.MULTILINE)[0]
    introduction = " ".join(introduction.split())

    for term in expected_terms:
        assert term in introduction


def test_manuscript_session_statistics_match_committed_inventory() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    section = manuscript.split("## Data tables\n", 1)[1].split(":::{iframe}", 1)[0]
    prose = " ".join(section.split())
    payload = load_experimental_session_records()
    passing = load_individual_session_table(payload=payload)["rows"]
    provenance = json.loads(
        (REPO_ROOT / "figure_sources/data/experimental-sessions.provenance.json").read_text(
            encoding="utf-8"
        )
    )

    assert provenance["retrieved_date"] in prose
    assert f"{len(payload['records'])} acquisition records" in prose
    assert "./figure_sources/data/experimental-sessions.csv" in prose
    assert "./figure_sources/data/experimental-sessions.provenance.json" in prose
    for modality, label in (
        ("neuropixels", "Neuropixels"),
        ("mesoscope", "mesoscope"),
        ("slap2", "SLAP2"),
    ):
        records = [record for record in payload["records"] if record["modality"] == modality]
        mice = {record["mouse_id"] for record in records}
        session_ids = {
            record["source_session_id"].strip()
            for record in records
            if record["source_session_id"].strip() not in {"", "aborted"}
        }
        passed = [row for row in passing if row["modality"].split("-", 1)[0] == modality]
        passed_mice = {row["values"][1] for row in passed}
        assert f"{len(records)} {label} acquisition records from {len(mice)} mice" in prose
        assert f"{len(session_ids)} unique {label} session IDs" in prose
        assert f"{len(passed)} {label} sessions from {len(passed_mice)} mice" in prose

    slap2 = [row for row in passing if row["modality"].split("-", 1)[0] == "slap2"]
    channel_counts = Counter(row["modality"] for row in slap2)
    pilot_count = sum(row["context"] == "other/pilot" for row in slap2)
    assert f"{channel_counts['slap2-glutamate']} glutamate sessions" in prose
    assert f"{channel_counts['slap2-voltage']} voltage sessions" in prose
    assert (
        f"{channel_counts['slap2']} session with an unclassified green recording channel"
        in prose
    )
    assert f"{pilot_count} of these {len(slap2)} sessions are classified as pilot/other" in prose
    assert "Excluding empty session IDs and entries marked `aborted`" in prose
    assert "worksheet QC status `Pass` (case-insensitive)" in prose
    assert "not the number of archived NWB files" in prose
    assert "Here should" not in section


def test_cell_type_figures_are_main_figures_before_responses() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    assert (
        manuscript.index("## Receptive field analysis across modalities")
        < manuscript.index("## Cell-type characterization")
        < manuscript.index("(fig-supp-optotagging-heatmaps)=")
        < manuscript.index(":label: fig-supp-wavemap")
        < manuscript.index("## Standard-oddball responsiveness across recording modalities")
        < manuscript.index("## Behavioral data analysis across modalities")
        < manuscript.index("## Supplementary figures")
    )
    for label in ("fig-supp-wavemap",):
        assert manuscript.count(f":label: {label}\n") == 1
        assert f":label: {label}\n:width: 100%" in manuscript
        assert f":label: {label}\n:enumerated: false" not in manuscript
    for label in ("fig-supp-wavemap-regions", "fig-supp-wavemap-composition",
                  "fig-supp-optotagging-anatomy"):
        assert manuscript.count(f":label: {label}\n") == 1
        assert f":label: {label}\n:enumerated: false" in manuscript
    assert "fig-standard-oddball-plan" not in manuscript
    assert "For sessions with camera acquisition" not in manuscript


def test_analysis_plan_is_concise_prose() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    plan = manuscript.split("## Data analysis plan\n", 1)[1].split("# Conclusion\n", 1)[0]

    assert len(plan.split()) <= 600
    assert len(re.findall(r"^### ", plan, re.MULTILINE)) == 3
    assert not re.search(r"^(?:\s*[-*+] |\s*\d+\. |#### )", plan, re.MULTILINE)
    for term in ("additive", "multiplicative", "subtractive", "adaptation", "held-out"):
        assert term in plan.lower()
    assert "not additional completed results" in plan
    assert "do not track the same units across days" in plan
    assert "@rule2020stable" in plan


def test_all_publication_viewers_default_to_static() -> None:
    class FigureElements(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.elements: list[dict[str, str | None]] = []
            self.parents: list[tuple[str, dict[str, str | None]]] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            attributes = dict(attrs)
            if self.parents:
                attributes["parent_tag"] = self.parents[-1][0]
                attributes["parent_class"] = self.parents[-1][1].get("class")
            if tag in {"button", "section", "div", "header"}:
                self.elements.append(attributes)
            if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input",
                           "link", "meta", "param", "source", "track", "wbr"}:
                self.parents.append((tag, attributes))

        def handle_endtag(self, tag: str) -> None:
            for index in range(len(self.parents) - 1, -1, -1):
                if self.parents[index][0] == tag:
                    del self.parents[index:]
                    break

    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    paths = re.findall(r"^:::\{iframe\} \./(interactive/[^\n]+)", manuscript, re.MULTILINE)
    assert len(paths) == 13
    for relative_path in paths:
        html = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        parser = FigureElements()
        parser.feed(html)
        toolbar = [item for item in parser.elements if item.get("class") == "figure-toolbar"]
        assert len(toolbar) == 1 and toolbar[0].get("parent_tag") == "main", relative_path
        modes = [item for item in parser.elements if item.get("data-view") is not None]
        assert len(modes) == 2, relative_path
        assert modes[0]["data-view"] == "static", relative_path
        assert all(
            item.get("parent_class") == "figure-mode-switch" for item in modes
        ), relative_path
        buttons = [item for item in parser.elements if item.get("data-view") == "static"]
        assert len(buttons) == 1, relative_path
        assert (
            buttons[0].get("aria-pressed") == "true"
            or buttons[0].get("aria-selected") == "true"
        ), relative_path
        static = [item for item in parser.elements
                  if item.get("id") in {"static-view", "static-panel", "panel-static"}]
        assert len(static) == 1 and "hidden" not in static[0], relative_path
        interactive = [item for item in parser.elements
                       if item.get("id") in {"interactive-view", "playback-view"}]
        assert len(interactive) == 1 and "hidden" in interactive[0], relative_path
        legend = [item for item in parser.elements if item.get("id") == "figure-legend"]
        toggle = [item for item in parser.elements if item.get("id") == "figure-legend-toggle"]
        assert len(legend) == 1 and "hidden" in legend[0], relative_path
        assert len(toggle) == 1, relative_path
        assert toggle[0].get("aria-controls") == "figure-legend", relative_path
        assert toggle[0].get("aria-expanded") == "false", relative_path
        assert toggle[0].get("aria-label") == "Figure legend", relative_path
        assert toggle[0].get("title") == "Figure legend", relative_path
        assert toggle[0].get("parent_class") == "figure-toolbar", relative_path
        assert "function syncLegend()" in html and "toggle.focus()" in html, relative_path
        assert "__EMBED_AUTO_HEIGHT_JS__" not in html, relative_path


def test_figure_captions_and_interactive_placement() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    prose = " ".join(manuscript.split())

    captioned_figures = re.findall(
        r"^:::\{(?:figure|iframe)\} [^\n]+\n"
        r"(?P<options>(?::\w[^\n]*\n)+)\n(?P<caption>.*?)\n:::$",
        manuscript,
        re.MULTILINE | re.DOTALL,
    )
    assert captioned_figures
    for options, caption in captioned_figures:
        assert not re.search(r"\*\*(?:Interactive|Static)\*\*|CSV export|checkboxes", caption)
        if ":enumerated: false" not in options:
            assert not re.match(r"(?:\*\*)?(?:Supplementary )?Figure\s+\d", caption)

    assert "A visual sequence establishes an expectation" in manuscript
    assert "**B,** To sample these nested scales" in manuscript
    assert "Neuropixels sampled every context once" in manuscript
    assert "mesoscope repeated each context twice" in manuscript
    assert "SLAP2 sampled the motor-habituated cohort" in manuscript
    assert "eight outlined habituation and training sessions" in manuscript
    assert "a standard control precedes each context" in manuscript
    assert "control and system-identification stimuli" in manuscript
    assert "Sources: pinned\n[example tables]" in manuscript
    assert "generate_experiment_csv.py" in manuscript
    assert "**D,** Context panels summarize" not in manuscript
    assert "Rows compare Neuropixels electrophysiology" in manuscript
    assert "Columns show each rig geometry" in manuscript
    assert "Neuropixels uses six acute trajectories" in manuscript
    assert "Failed, repeated, and aborted acquisition attempts are retained" in manuscript
    assert "./interactive/neural-viewer.html" in manuscript
    assert ":label: fig-aligned-neural-signals" in manuscript
    assert ":placeholder: ./images/figures/generated/raw-neural-recordings.svg" in manuscript
    assert "Representative data from one recording session per modality" in manuscript
    assert "**(D)** Raw voltage heatmaps from six Neuropixels probes" in manuscript
    assert "**(E)** Raw mesoscope images from eight planes" in manuscript
    assert "two imaging depths (DMD1, top; DMD2, bottom)" in manuscript
    assert "black-referenced display gain" in manuscript
    assert "1st–99.5th max-channel percentiles" in manuscript
    assert "640 × 400 lossless grayscale frames" in manuscript
    assert "fast-scanning x axis horizontal" in manuscript
    assert "comes from one acquisition cycle; unsampled pixels are black" in manuscript
    assert "reference or temporally averaged image blended into the raw signal" in manuscript
    assert "reference-stack maximum projection" in manuscript
    assert "99.8th percentiles with gamma 0.6" in manuscript
    assert "Event-aligned raw data across recording modalities" not in manuscript
    assert "prediction-violating event" not in manuscript
    assert re.search(r"Microscopy\s+playback uses elapsed time", manuscript)
    assert re.search(r"raw AP acquisition stream supplied to spike\s+sorting", manuscript)
    assert "AP samples are not median-corrected" in manuscript
    assert "remain visible as vertical stripes" in manuscript
    assert "ecephys_830846_2026-03-09_10-32-54" in manuscript
    assert "ecephys_820459_2025-11-10_15-07-13" not in manuscript
    assert "multiplane-ophys_832700_2026-01-29_11-18-09" in manuscript
    assert "796630_2025-08-28_14-25-34" in manuscript
    assert "(fig-interactive-experimental-design)=" in manuscript
    assert (
        ":label: fig-interactive-experimental-design\n:enumerated: false"
        not in manuscript
    )
    assert ":label: fig-recording-session-inventory\n:width: 100%" in manuscript
    assert ":label: fig-recording-session-inventory\n:enumerated: false" not in manuscript
    assert (
        manuscript.index("# Data records")
        < manuscript.index("## Raw data across recording modalities")
        < manuscript.index(":label: fig-aligned-neural-signals")
        < manuscript.index("(fig-segmentation-viewers)=")
        < manuscript.index("## Units extraction")
        < manuscript.index(":label: fig-unit-extraction-plan")
        < manuscript.index("## Receptive field analysis across modalities")
        < manuscript.index(":label: fig-basic-stimuli-plan")
    )
    assert "[Figure 3](#fig-aligned-neural-signals)" in manuscript
    assert ":label: fig-unit-extraction-plan" in manuscript
    assert "all 2,521 classified sources" in manuscript
    assert "Percentage denominators exclude those 19 sources" in manuscript
    assert "first four bars pool classified sources" in prose
    assert "cross-cohort class differences must not be interpreted" in prose
    assert "The stimulus design enables receptive field (RF) mapping" in manuscript
    assert all(
        f"[Fig. 7{panels}](#fig-basic-stimuli-plan)" in manuscript
        for panels in ("A,B", "B", "C")
    )
    assert "[Figure 7](#fig-basic-stimuli-plan) outlines a comparison" not in manuscript
    assert "fig-standard-oddball-plan" not in manuscript
    assert "./interactive/behavior-viewer.html" in manuscript
    assert ":placeholder: ./images/figures/generated/synchronized-behavior.svg" in manuscript
    assert "Synchronized behavior and running across recording modalities" in manuscript
    assert "**A–C,** Camera views from representative Neuropixels" in prose
    assert "Neuropixels (**A**), mesoscope (**B**), and SLAP2 (**C**)" in prose
    assert "**D–F,** Complete-session running profiles" in prose
    assert "modality columns with available views in 2×2 grids" in prose
    assert "same mouse and source\nsession" in manuscript
    assert "share one time axis" in manuscript
    assert "unshaded axes with dashed separators" in manuscript
    assert "Labels match Figure 1D" in manuscript
    assert "**G,** Mean running speed in each protocol block" in manuscript
    assert "compared on one shared cm/s axis" in manuscript
    assert "each bar is the\nmean across mice" in manuscript
    assert "legend values report included mice" in manuscript
    assert "camera-display processing are described" in manuscript
    assert "paired control-versus-context running" not in manuscript
    assert "8192 counts/revolution, an 8.255 cm disc radius" in manuscript
    assert "1st–99th luminance percentiles" in manuscript
    assert "maps median luminance to 35%" in prose
    assert "Event-centered excerpts from real Neuropixels" not in manuscript
    assert "figure-06-behavior-tracking-plan.png" not in manuscript
    assert "continuous raw behavioral videos" in prose
    assert "[Figure 10](#fig-behavior-tracking)" in manuscript
    assert "[](#fig-behavior-tracking)" not in manuscript
    assert (
        manuscript.index("(fig-supp-optotagging-heatmaps)=")
        < manuscript.index(":label: fig-supp-wavemap")
        < manuscript.index(":label: fig-standard-oddball-responses")
        < manuscript.index(":label: fig-behavior-tracking")
        < manuscript.index(":label: fig-neuropixels-event-responses")
    )
    for number, label in (
        (1, "fig-graphical-abstract"),
        (2, "fig-recording-session-inventory"),
        (3, "fig-aligned-neural-signals"),
        (4, "fig-mesoscope-unit-extraction"),
        (5, "fig-unit-extraction-plan"),
        (6, "fig-ecephys-qc-dashboard"),
        (7, "fig-basic-stimuli-plan"),
        (8, "fig-supp-wavemap"),
        (9, "fig-standard-oddball-responses"),
        (10, "fig-behavior-tracking"),
    ):
        assert re.search(
            rf"\[(?:Figure|Fig\.) {number}[A-Z,–-]*\]\(#{re.escape(label)}\)", manuscript,
        )
    assert re.search(r"\[\]\(#fig-", manuscript) is None
    assert "NWB running speed and stimulus rows share the sync-file clock" in prose
    assert "reported dropped frames are removed before mapping" in prose
    assert "per-frame Harp timestamps on the acquisition clock" in manuscript
    assert "DeepLabCut" in manuscript
    assert "- Motion energy of the face?" not in manuscript

    figure_1 = manuscript.index(":label: fig-graphical-abstract")
    cohort_link = manuscript.index("[Figure 1C](#fig-graphical-abstract)")
    explanation = manuscript.index("**Four predictive contexts**")
    viewer = manuscript.index("(fig-interactive-experimental-design)=")
    assert viewer < figure_1 < cohort_link < explanation


def test_main_figure_links_match_directive_order() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    blocks = re.findall(
        r"^:::\{(?:figure|iframe)\} [^\n]+\n(.*?)^:::\s*$",
        manuscript,
        re.MULTILINE | re.DOTALL,
    )
    labels = []
    for block in blocks:
        options, _, caption = block.partition("\n\n")
        label = re.search(r"^:label: (\S+)$", options, re.MULTILINE)
        if label and caption.strip() and ":enumerated: false" not in options:
            labels.append(label.group(1))
    assert len(labels) == len(set(labels))
    numbers = {label: index for index, label in enumerate(labels, start=1)}
    assert len(numbers) == 10
    assert numbers["fig-ecephys-qc-dashboard"] == 6
    numbers["fig-interactive-experimental-design"] = numbers["fig-graphical-abstract"]
    numbers["fig-supp-optotagging-heatmaps"] = numbers["fig-supp-wavemap"]
    for number, label in re.findall(
        r"\[(?:Figure|Fig\.) (\d+)[A-Z,–-]*\]\(#([^)]+)\)", manuscript,
    ):
        assert numbers[label] == int(number), (label, number, numbers[label])


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
    assert "#fig-neuropixels-event-responses" in stylesheet
    assert "#fig-supp-neuropixels-event-responses" not in stylesheet
    assert "container-type: inline-size" in stylesheet
    assert "max-width: 900px" not in stylesheet
    assert "@container (max-width: 560px)" in stylesheet


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
    assert "Simulated data with known mechanisms" in manuscript
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
        ":placeholder: ./images/figures/generated/figure-01-overview.svg"
        in manuscript
    )
    viewer = (REPO_ROOT / "interactive/experimental-design.html").read_text(encoding="utf-8")
    assert 'aria-controls="figure-legend"' in viewer
    assert 'data-view="static" aria-pressed="true"' in viewer
    assert "control and system-identification stimuli" in manuscript

def test_unit_yield_summary_means_are_order_independent() -> None:
    """Summary means must not depend on record order.

    Left-to-right accumulation reproduces the rounding drift that dirtied the
    committed HTML. Do not use built-in sum() for this counterexample: Python
    3.12 and later use a more accurate floating-point summation algorithm.
    """
    import random
    import statistics

    values = [
        395.5,
        387.0,
        454.1666666666667,
        315.1666666666667,
        320.8333333333333,
        312.8333333333333,
        350.8333333333333,
        260.8,
        276.8333333333333,
        295.8333333333333,
        275.3333333333333,
        297.6666666666667,
        356.1666666666667,
        405.6666666666667,
        375.1666666666667,
        333.5,
    ]
    rng = random.Random(0)
    naive = set()
    for _ in range(200):
        order = rng.sample(values, len(values))
        total = 0.0
        for value in order:
            total += value
        naive.add(total / len(order))
    exact = {
        statistics.mean(order)
        for order in (rng.sample(values, len(values)) for _ in range(200))
    }
    # The bug: naive summation gives more than one answer for one dataset.
    assert len(naive) > 1
    assert len(exact) == 1
    assert exact == {338.33125}
