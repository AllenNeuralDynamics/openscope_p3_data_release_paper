import hashlib
import json
from pathlib import Path

import pytest

from openscope_p3_publication.figures import (
    ANIMAL_RECORDS_PATH,
    ANIMAL_RECORDS_PROVENANCE_PATH,
    BEHAVIOR_EXCERPTS_PATH,
    BLOCKS,
    SESSIONS,
    STIMULUS_EXCERPT_PROVENANCE_PATH,
    STIMULUS_SOURCES_PATH,
    ZEBRA_MOVIE_SOURCE,
    ZEBRA_POSTER_SOURCE,
    load_behavior_excerpts,
    load_publication_table_data,
    load_shared_stimulus_table_excerpts,
    load_stimulus_table_excerpts,
    total_duration_minutes,
    write_behavior_viewer_html,
    write_data_explorer_html,
    write_interactive_html,
    write_literature_comparison_html,
    write_static_svg,
)


def test_experimental_design_data() -> None:
    assert len(SESSIONS) == 4
    assert len(BLOCKS) == 8
    assert total_duration_minutes() == pytest.approx(71.3)


def test_stimulus_sources_are_pinned() -> None:
    sources = json.loads(STIMULUS_SOURCES_PATH.read_text(encoding="utf-8"))

    assert sources["upstream_revision"] == "0365ae32f0f0473320ed202b7c5d2bce6cf5df6b"
    assert sources["zebra_movie_sha256"] == (
        "3ee4d88356dba7220eb67e53f7d117400932f3adf95132d6301fe212ff7cf899"
    )
    assert len(sources["sessions"]) == 4
    for source in sources["sessions"]:
        assert source["example_table_url"].endswith("_example.csv")
        assert len(source["sha256"]) == 64


def test_stimulus_excerpts_preserve_pinned_source_order() -> None:
    sources = json.loads(STIMULUS_SOURCES_PATH.read_text(encoding="utf-8"))
    provenance = json.loads(
        STIMULUS_EXCERPT_PROVENANCE_PATH.read_text(encoding="utf-8")
    )
    contexts = load_stimulus_table_excerpts(sources)
    shared = load_shared_stimulus_table_excerpts(sources)

    assert provenance["upstream_revision"] == sources["upstream_revision"]
    assert set(contexts) == {"1", "2", "3", "4"}
    assert set(shared) == {"0", "2", "3", "4", "5", "7"}
    assert contexts["1"]["firstMismatchTrial"] == 572
    assert contexts["2"]["firstMismatchTrial"] == 1070
    assert contexts["1"]["rows"][0]["trialNumber"] == 560
    assert contexts["1"]["rows"][0]["sourceRow"] == 561
    assert contexts["1"]["rows"][12]["trialNumber"] == 572
    assert [row["orientation"] for row in shared["0"]["rows"][:4]] == [
        45.0,
        45.0,
        247.5,
        90.0,
    ]
    assert shared["7"]["rows"][0]["diameterX"] == 20.0
    assert shared["0"]["rows"][0]["sourceRow"] == 2
    c4_phases = [row["phaseCycles"] for row in shared["5"]["rows"]]
    assert all(phase is not None for phase in c4_phases)
    assert max(
        abs(current - previous)
        for previous, current in zip(c4_phases[:-1], c4_phases[1:], strict=True)
    ) < 0.17


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
    assert 'width="480" height="380"' in html
    assert "stimulusTableExcerpts" in html
    assert "sharedTableExcerpts" in html
    assert '"trialNumber":572' in html
    assert "pinned table (source order)" in html
    assert "angularDistanceDegrees" in html
    assert "normalizedX * 120 / 2" in html
    assert "normalizedY * 95 / 2" in html
    assert "zebra-stimulus-excerpt.m4v" in html
    assert "zebra-stimulus-poster.png" in html
    assert "#stimulus-video[hidden]" in html
    assert "display: none !important" in html
    assert "Open-loop playback" in html
    assert "nextRow.phaseCycles" in html
    assert ".block-tab.context {\n  background: var(--accent);" in html
    assert 'id="sync-square"' not in html
    assert "drawZebraFallback" not in html
    for removed_function in (
        "oddballSpec",
        "sensorimotorSpec",
        "sequenceSpec",
        "durationSpec",
        "standardControlSpec",
        "receptiveFieldSpec",
    ):
        assert removed_function not in html
    assert 'id="mock-mouse"' not in html
    assert 'id="event-log"' not in html
    assert 'id="trigger-mismatch"' not in html
    assert 'document.querySelector("body > main")' in html
    assert 'classList.add("is-embedded")' in html
    assert "__EMBED_AUTO_HEIGHT_JS__" not in html
    assert "__SIMULATOR_" not in html
    assert 'role="img"' in svg
    assert "Session 4" in svg

    assert hashlib.sha256(
        (tmp_path / ZEBRA_MOVIE_SOURCE.name).read_bytes()
    ).hexdigest() == hashlib.sha256(ZEBRA_MOVIE_SOURCE.read_bytes()).hexdigest()
    assert hashlib.sha256(
        (tmp_path / ZEBRA_POSTER_SOURCE.name).read_bytes()
    ).hexdigest() == hashlib.sha256(ZEBRA_POSTER_SOURCE.read_bytes()).hexdigest()

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
    assert 'document.querySelector("body > main")' in html
    assert 'classList.add("is-embedded")' in html
    assert "__EMBED_AUTO_HEIGHT_JS__" not in html

    write_data_explorer_html(explorer_path)
    assert explorer_path.read_text(encoding="utf-8") == html


def test_literature_comparison_is_deterministic(tmp_path: Path) -> None:
    comparison_path = write_literature_comparison_html(
        tmp_path / "literature-comparison.html"
    )
    html = comparison_path.read_text(encoding="utf-8")

    assert 'id="literature-comparison"' in html
    assert "Compare parameter" in html
    assert "Study profile" in html
    assert "Attinger et al 2017" in html
    assert "Westerberg et al 2025" in html
    assert "Download visible rows as CSV" in html
    assert 'document.querySelector("body > main")' in html
    assert 'classList.add("is-embedded")' in html
    assert "__EMBED_AUTO_HEIGHT_JS__" not in html
    assert "__LITERATURE_" not in html

    write_literature_comparison_html(comparison_path)
    assert comparison_path.read_text(encoding="utf-8") == html


def test_behavior_excerpts_are_source_backed_and_synchronized() -> None:
    payload = load_behavior_excerpts(BEHAVIOR_EXCERPTS_PATH)
    expected_video_times = {
        "neuropixels": {
            "behavior": (443.49, 448.49),
            "face": (442.953, 447.953),
            "eye": (443.18, 448.18),
        },
        "mesoscope": {
            "behavior": (429.922, 434.922),
            "face": (429.185, 434.185),
            "eye": (429.521, 434.521),
            "nose": (428.857, 433.857),
        },
        "slap2": {
            "body": (841.285, 846.812),
            "face": (833.228, 838.703),
            "eye": (828.016, 833.456),
        },
    }

    def video_time_at(time_map: list[list[float]], local_time: float) -> float:
        for first, second in zip(time_map[:-1], time_map[1:], strict=True):
            if first[0] <= local_time <= second[0]:
                fraction = (local_time - first[0]) / (second[0] - first[0])
                return first[1] + fraction * (second[1] - first[1])
        raise AssertionError(f"No frame-map interval covers {local_time}")

    assert [session["id"] for session in payload["sessions"]] == [
        "neuropixels",
        "mesoscope",
        "slap2",
    ]
    assert [session["event"]["trialNumber"] for session in payload["sessions"]] == [
        1070,
        1070,
        112,
    ]
    for session in payload["sessions"]:
        assert len(session["trace"]) == 321
        assert session["trace"][0][0] == 0.0
        assert session["trace"][-1][0] == payload["durationSeconds"]
        assert session["event"]["time"] == 5.0
        assert any(
            row["start"] <= session["event"]["time"] <= row["end"]
            for row in session["stimulus"]
        )
        assert all(
            camera["url"].startswith(
                "https://aind-open-data.s3.us-west-2.amazonaws.com/"
            )
            for camera in session["cameras"]
        )
        for camera in session["cameras"]:
            if session["id"] in {"neuropixels", "mesoscope"}:
                assert camera["timing"]["clock"] == "NI-DAQ sync"
                assert camera["timing"]["clockRateHz"] == 100_000.0
                assert camera["timing"]["encodedRateHz"] == 60.0
                assert camera["timing"]["leadingMetadataFrames"] == 1
                assert "syncLine" in camera["timing"]
            else:
                assert camera["timing"] == {
                    "clock": "Harp CameraFrameTime",
                    "encodedRateHz": 30.0,
                    "leadingMetadataFrames": 0,
                    "reportedDroppedFrames": 0,
                }
            expected_start, expected_event = expected_video_times[session["id"]][
                camera["id"]
            ]
            assert video_time_at(camera["timeMap"], 0.0) == pytest.approx(
                expected_start, abs=0.002
            )
            assert video_time_at(camera["timeMap"], 5.0) == pytest.approx(
                expected_event, abs=0.002
            )
        assert all(
            camera["timeMap"][0][0] <= 0
            and camera["timeMap"][-1][0] >= payload["durationSeconds"]
            and all(
                current[0] > previous[0] and current[1] > previous[1]
                for previous, current in zip(
                    camera["timeMap"][:-1], camera["timeMap"][1:], strict=True
                )
            )
            for camera in session["cameras"]
        )
        assert all(
            source.get("sha256") or source.get("etag")
            for source in session["sources"]
        )


def test_behavior_viewer_is_deterministic(tmp_path: Path) -> None:
    viewer_path = write_behavior_viewer_html(tmp_path / "behavior-viewer.html")
    html = viewer_path.read_text(encoding="utf-8")

    assert 'id="behavior-viewer"' in html
    assert "Neuropixels" in html
    assert "Mesoscope" in html
    assert "SLAP2" in html
    assert "820459" in html
    assert "832700" in html
    assert "796630" in html
    assert "aind-open-data.s3.us-west-2.amazonaws.com" in html
    assert "Wheel recording trace with synchronized playback cursor" in html
    assert "videoTimeAt" in html
    assert "localTimeAt" in html
    assert 'document.querySelector("body > main")' in html
    assert 'classList.add("is-embedded")' in html
    assert 'document.documentElement.style.overflow = "hidden"' in html
    assert 'addEventListener("resize", syncHeight)' in html
    assert "@media (max-width: 560px)" in html
    assert 'id="alignment-label"' not in html
    assert "offsetSeconds" not in html
    assert "__EMBED_AUTO_HEIGHT_JS__" not in html
    assert "__BEHAVIOR_" not in html

    write_behavior_viewer_html(viewer_path)
    assert viewer_path.read_text(encoding="utf-8") == html


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