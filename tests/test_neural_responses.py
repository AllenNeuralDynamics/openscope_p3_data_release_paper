from __future__ import annotations

import math
from pathlib import Path

import pytest

from openscope_p3_publication.neural_response_figure import (
    load_neuropixels_event_responses,
    write_neuropixels_event_html,
    write_neuropixels_event_svg,
)
from openscope_p3_publication.neural_responses import (
    BIN_SECONDS,
    NEURAL_SESSIONS,
    WINDOW_END_SECONDS,
    WINDOW_START_SECONDS,
    context_event_definitions,
    event_indices,
    gaussian_kernel,
    qc_passes,
    relative_bin_centers,
    relative_bin_edges,
    smooth_trace,
)


def test_neural_sessions_cover_four_contexts_for_one_mouse() -> None:
    assert {session.context for session in NEURAL_SESSIONS} == {
        "standard",
        "sensorimotor",
        "sequence",
        "duration",
    }
    assert all("830846" in session.session_id for session in NEURAL_SESSIONS)
    assert len({session.asset_id for session in NEURAL_SESSIONS}) == 4


def test_neural_time_grid_uses_twenty_millisecond_bins() -> None:
    edges = relative_bin_edges()
    centers = relative_bin_centers()
    assert edges[0] == WINDOW_START_SECONDS
    assert edges[-1] == pytest.approx(WINDOW_END_SECONDS)
    assert len(centers) == 150
    assert centers[0] == pytest.approx(WINDOW_START_SECONDS + BIN_SECONDS / 2)


def test_neural_event_matching_reuses_physical_controls() -> None:
    definition = context_event_definitions("standard")[0]
    trial_types = ["orientation_45", "single", "single"]
    orientations = [math.pi / 4, math.pi / 4, math.pi / 2]
    delays = [0.343, 0.343, 0.343]
    assert event_indices(
        trial_types,
        orientations,
        delays,
        definition,
        control=False,
    ) == [0]
    assert event_indices(
        trial_types,
        orientations,
        delays,
        definition,
        control=True,
    ) == [1]


def test_manuscript_qc_thresholds_are_strict() -> None:
    assert qc_passes(
        isi_violations_ratio=0.49,
        presence_ratio=0.81,
        amplitude_cutoff=0.09,
    )
    assert not qc_passes(
        isi_violations_ratio=0.5,
        presence_ratio=0.81,
        amplitude_cutoff=0.09,
    )
    assert not qc_passes(
        isi_violations_ratio=0.49,
        presence_ratio=0.8,
        amplitude_cutoff=0.09,
    )
    assert not qc_passes(
        isi_violations_ratio=0.49,
        presence_ratio=0.81,
        amplitude_cutoff=0.1,
    )


def test_gaussian_smoothing_is_normalized_and_symmetric() -> None:
    kernel = gaussian_kernel()
    assert sum(kernel) == pytest.approx(1)
    assert kernel == pytest.approx(kernel[::-1])
    impulse = [0.0] * 21
    impulse[10] = 1.0
    smoothed = smooth_trace(impulse, kernel)
    assert smoothed[10] == max(smoothed)
    assert smoothed[9] == pytest.approx(smoothed[11])


def test_neuropixels_event_snapshot_is_source_backed() -> None:
    payload = load_neuropixels_event_responses()

    assert payload["version"] == 1
    assert payload["subject"] == "830846"
    assert payload["sessionOrder"] == [
        "standard",
        "sensorimotor",
        "sequence",
        "duration",
    ]
    assert [session["unitCount"] for session in payload["sessions"]] == [
        3355,
        2943,
        3550,
        3834,
    ]
    assert sum(
        unit["qcPass"]
        for session in payload["sessions"]
        for unit in session["units"]
    ) == 7266
    assert all(len(session["events"]) == 4 for session in payload["sessions"])
    assert all(
        session["countAtlas"]["shape"] == [4, 2, session["unitCount"], 150]
        for session in payload["sessions"]
    )


def test_neuropixels_event_outputs_are_deterministic_and_accessible(
    tmp_path: Path,
) -> None:
    svg_path = tmp_path / "neural-response.svg"
    html_path = tmp_path / "neural-response.html"

    write_neuropixels_event_svg(svg_path)
    first_svg = svg_path.read_bytes()
    write_neuropixels_event_svg(svg_path)
    assert svg_path.read_bytes() == first_svg

    write_neuropixels_event_html(html_path, static_output=svg_path)
    first_html = html_path.read_bytes()
    write_neuropixels_event_html(html_path, static_output=svg_path)
    assert html_path.read_bytes() == first_html

    svg = first_svg.decode()
    html = first_html.decode()
    assert 'role="img"' in svg
    assert "Area-level mismatch response across all conditions" in svg
    assert "Representative unit dynamics" in svg
    assert svg.count("<image ") == 4
    assert "./media/neuropixels-event-responses/" in html
    assert 'id="heatmap-canvas"' in html
    assert 'data-metric="difference"' in html
    assert 'data-metric="zscore"' in html
    assert 'data-qc="qc"' in html
    assert 'data-qc="all"' in html
    assert 'data-scope="area"' in html
    assert 'data-scope="unit"' in html
    assert 'id="response-selection-label"' in html
    assert 'aria-label="Area for mean response"' in html
    assert "DecompressionStream" in html
    assert "__NEUROPIXELS_EVENT_" not in html
