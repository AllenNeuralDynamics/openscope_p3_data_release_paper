from __future__ import annotations

import math
from pathlib import Path

import pytest

from openscope_p3_publication.neural_response_figure import (
    STATIC_AREA_GROUP_ORDER,
    STATIC_AREA_MIN_QC_UNITS,
    float32_values,
    load_neuropixels_event_responses,
    mean_sem_traces,
    presentation_timing_values,
    response_matrix,
    static_rate_axis,
    uint16_base64_values,
    write_neuropixels_event_html,
    write_neuropixels_event_svg,
)
from openscope_p3_publication.neural_responses import (
    BASELINE_BIN_SECONDS,
    BIN_SECONDS,
    CONTEXT_WINDOWS_SECONDS,
    NEURAL_SESSIONS,
    SDF_KERNEL_DURATION_TAU,
    SDF_QUANTIZATION_SCALE,
    SDF_SOURCE_BIN_SECONDS,
    SDF_TAU_SECONDS,
    classify_neuron_type,
    context_event_definitions,
    context_window_seconds,
    event_indices,
    neural_baseline_windows,
    neural_response_windows,
    qc_passes,
    relative_bin_centers,
    relative_bin_edges,
    sdf_kernel,
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


def test_neural_time_grid_uses_two_point_five_millisecond_bins() -> None:
    assert BIN_SECONDS == 0.0025
    assert BASELINE_BIN_SECONDS == 0.02
    assert SDF_SOURCE_BIN_SECONDS == 0.0025
    assert CONTEXT_WINDOWS_SECONDS == {
        "standard": (-0.75, 0.75),
        "sensorimotor": (-0.75, 0.75),
        "sequence": (-0.75, 0.75),
        "duration": (-1.5, 1.5),
    }
    for context, expected_count in (
        ("standard", 600),
        ("sensorimotor", 600),
        ("sequence", 600),
        ("duration", 1200),
    ):
        edges = relative_bin_edges(context)
        centers = relative_bin_centers(context)
        start, stop = context_window_seconds(context)
        assert edges[0] == start
        assert edges[-1] == pytest.approx(stop)
        assert len(centers) == expected_count
        assert centers[0] == pytest.approx(start + BIN_SECONDS / 2)


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


def test_context_specific_neural_baselines() -> None:
    starts = [100.0, 100.7, 101.4, 102.1]
    stops = [100.37, 101.07, 101.77, 102.47]
    blocks = [2, 2, 2, 2]
    assert neural_baseline_windows(
        starts,
        stops,
        [2],
        "standard",
        blocks,
    ) == [(101.07, 101.4)]
    assert neural_baseline_windows(
        starts,
        stops,
        [2],
        "sequence",
        blocks,
    ) == [(100.7, 101.4)]
    assert neural_baseline_windows(
        starts,
        stops,
        [2],
        "sensorimotor",
        blocks,
    )[0] == pytest.approx((101.057, 101.4))
    assert neural_baseline_windows(
        starts,
        stops,
        [2],
        "duration",
        blocks,
    ) == [(100.37, 100.7)]


def test_neural_response_uses_recorded_presentation_window() -> None:
    assert neural_response_windows(
        [100.0, 100.7],
        [100.37, 101.07],
        [1],
    ) == [(100.7, 101.07)]


def test_sdf_smoothing_is_normalized_and_causal() -> None:
    kernel = sdf_kernel()
    assert SDF_TAU_SECONDS == 0.01
    assert SDF_KERNEL_DURATION_TAU == 10
    assert SDF_QUANTIZATION_SCALE == 20
    assert sum(kernel) == pytest.approx(1)
    assert len(kernel) == 40
    assert kernel[1] / kernel[0] == pytest.approx(
        math.exp(-SDF_SOURCE_BIN_SECONDS / SDF_TAU_SECONDS)
    )
    impulse = [0.0] * 60
    impulse[10] = 1.0
    smoothed = smooth_trace(impulse, kernel)
    assert smoothed[9] == 0
    assert smoothed[10] == max(smoothed)
    assert smoothed[11] < smoothed[10]
    assert smoothed[49] > 0
    assert smoothed[50] == 0
    constant = smooth_trace([10.0] * 50, kernel)
    assert constant[0] == pytest.approx(10 * kernel[0])
    assert constant[39] == pytest.approx(10)


@pytest.mark.parametrize(
    ("peak_to_valley_ms", "major_parent", "sst_optotagged", "expected"),
    [
        (0.2, "Isocortex", False, "FS"),
        (0.5, "Isocortex", False, "RS"),
        (0.3, "TH", False, "RS"),
        (0.2, "TH", False, "FS"),
        (0.2, "STR", False, "RS"),
        (0.2, "Isocortex", True, "SST"),
    ],
)
def test_neuron_type_classification(
    peak_to_valley_ms: float,
    major_parent: str,
    sst_optotagged: bool,
    expected: str,
) -> None:
    assert (
        classify_neuron_type(
            peak_to_valley_ms=peak_to_valley_ms,
            major_parent=major_parent,
            sst_optotagged=sst_optotagged,
        )
        == expected
    )


def test_neuropixels_event_snapshot_is_source_backed() -> None:
    payload = load_neuropixels_event_responses()

    assert payload["version"] == 8
    assert payload["subject"] == "830846"
    assert payload["sessionOrder"] == [
        "standard",
        "sensorimotor",
        "sequence",
        "duration",
    ]
    assert [session["windowSeconds"] for session in payload["sessions"]] == [
        [-0.75, 0.75],
        [-0.75, 0.75],
        [-0.75, 0.75],
        [-1.5, 1.5],
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
    assert [
        len(session["events"][0]["timing"]["context"]["presentationWindows"])
        for session in payload["sessions"]
    ] == [3, 1, 6, 5]
    assert [
        session["sdfMeanAtlas"]["shape"][-1]
        for session in payload["sessions"]
    ] == [600, 600, 600, 1200]
    assert all("waveformAtlas" not in session for session in payload["sessions"])
    assert all(
        math.isfinite(unit["firingRateHz"]) and unit["firingRateHz"] >= 0
        for session in payload["sessions"]
        for unit in session["units"]
    )
    assert all(
        math.isfinite(value)
        for session in payload["sessions"]
        for field in ("baselineMeanHzBase64", "baselineStdHzBase64")
        for value in float32_values(session[field])
    )
    assert {
        unit["neuronType"]
        for session in payload["sessions"]
        for unit in session["units"]
    } == {"RS", "FS", "SST"}
    assert [
        {
            neuron_type: sum(
                unit["neuronType"] == neuron_type for unit in session["units"]
            )
            for neuron_type in ("RS", "FS", "SST")
        }
        for session in payload["sessions"]
    ] == [
        {"RS": 2324, "FS": 527, "SST": 504},
        {"RS": 2166, "FS": 361, "SST": 416},
        {"RS": 2636, "FS": 487, "SST": 427},
        {"RS": 2747, "FS": 583, "SST": 504},
    ]
    assert all(
        math.isfinite(unit["peakToValleyMs"])
        and unit["peakToValleyMs"] >= 0
        and (not unit["sstOptotagged"] or unit["neuronType"] == "SST")
        for session in payload["sessions"]
        for unit in session["units"]
    )
    assert {
        unit["decoderLabel"]
        for session in payload["sessions"]
        for unit in session["units"]
    } == {"mua", "noise", "sua"}
    assert {
        label: sum(
            unit["decoderLabel"] == label
            for session in payload["sessions"]
            for unit in session["units"]
        )
        for label in ("mua", "noise", "sua")
    } == {"mua": 4971, "noise": 4152, "sua": 4559}
    groups = {
        group
        for session in payload["sessions"]
        for unit in session["units"]
        for group in unit["areaGroups"]
    }
    assert groups == {
        "cortical",
        "frontal",
        "hippocampal",
        "motor",
        "thalamic",
        "visual",
    }
    assert all(
        ("motor" in unit["areaGroups"])
        == unit["location"].startswith(("MOp", "MOs"))
        for session in payload["sessions"]
        for unit in session["units"]
    )
    for session in payload["sessions"]:
        ranks = uint16_base64_values(session["rastermapRank"]["base64"])
        assert session["rastermapRank"]["shape"] == [4, session["unitCount"]]
        for event_index in range(4):
            start = event_index * session["unitCount"]
            assert sorted(ranks[start : start + session["unitCount"]]) == list(
                range(session["unitCount"])
            )


def test_static_response_matrix_uses_anatomical_area_order() -> None:
    payload = load_neuropixels_event_responses()
    areas, columns = response_matrix(payload)
    units = [unit for session in payload["sessions"] for unit in session["units"]]
    area_counts = {
        area: sum(unit["qcPass"] and unit["location"] == area for unit in units)
        for area in areas
    }
    area_groups = {
        unit["location"]: unit["areaGroups"]
        for unit in units
        if unit["location"] in areas
    }

    def sort_key(area: str) -> tuple[int, str]:
        return (
            next(
                index
                for index, group in enumerate(STATIC_AREA_GROUP_ORDER)
                if group in area_groups[area]
            ),
            area,
        )

    assert len(areas) == 48
    assert len(columns) == 16
    assert areas == sorted(areas, key=sort_key)
    categories = [
        next(group for group in STATIC_AREA_GROUP_ORDER if group in area_groups[area])
        for area in areas
    ]
    assert {
        group: categories.count(group) for group in STATIC_AREA_GROUP_ORDER
    } == {
        "frontal": 21,
        "visual": 13,
        "hippocampal": 6,
        "thalamic": 8,
    }
    assert all(count >= STATIC_AREA_MIN_QC_UNITS for count in area_counts.values())
    assert all(
        any(group in area_groups[area] for group in STATIC_AREA_GROUP_ORDER)
        for area in areas
    )


def test_static_firing_rate_axes_include_zero_tick() -> None:
    raw_lower, raw_upper, raw_ticks = static_rate_axis([2.5, 6.2], False)
    delta_lower, delta_upper, delta_ticks = static_rate_axis([-2.1, 4.4], True)

    assert raw_lower == 0
    assert raw_upper > 6.2
    assert 0 in raw_ticks
    assert delta_lower < -2.1
    assert delta_upper > 4.4
    assert 0 in delta_ticks


def test_static_trace_summary_is_sem_across_units() -> None:
    mean, sem = mean_sem_traces([[1, 2], [3, 4], [5, 6]])

    assert mean == pytest.approx([3, 4])
    assert sem == pytest.approx([2 / math.sqrt(3), 2 / math.sqrt(3)])


def test_presentation_timing_values_use_only_selected_mismatch() -> None:
    timing = {
        "presentationStartSeconds": 0,
        "presentationStopSeconds": 0.3,
        "presentationWindows": [
            {"rowOffset": -1, "startSeconds": -0.7, "stopSeconds": -0.3},
            {"rowOffset": 0, "startSeconds": 0, "stopSeconds": 0.3},
            {"rowOffset": 1, "startSeconds": 0.7, "stopSeconds": 1.1},
        ],
    }

    assert presentation_timing_values(timing, -1, 1) == [0.0, 0.3]


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
    assert 'data-metric="mismatch"' in html
    assert 'data-metric="control"' in html
    assert 'data-metric="difference"' in html
    assert 'data-metric="mismatch-zscore"' in html
    assert 'data-metric="control-zscore"' in html
    assert 'data-qc="qc"' in html
    assert 'data-qc="all"' in html
    assert 'data-scope="area"' in html
    assert 'data-scope="unit"' in html
    assert 'id="response-selection-label"' in html
    assert 'aria-label="Area for mean response"' in html
    assert html.count('id="response-canvas"') == 1
    assert 'id="baseline-response-canvas"' not in html
    assert 'id="baseline-subtracted"' in html
    assert 'id="response-note"' in html
    assert "dashed guides mark mismatch onset and offset" in html
    assert "waveform-canvas" not in html
    assert "Time from mismatch stimulus (s)" in html
    assert "Time to positive peak" in html
    assert ">Rastermap<" in html
    assert "All cortical areas" in html
    assert "All thalamic areas" in html
    assert "All motor areas" in html
    assert 'data-decoder-label="mua"' in html
    assert 'data-decoder-label="sua"' in html
    assert 'data-neuron-type="RS"' in html
    assert 'data-neuron-type="FS"' in html
    assert 'data-neuron-type="SST"' in html
    assert 'id="minimum-firing-rate"' in html
    assert 'id="unit-count"' not in html
    assert "Δ firing rate" in html
    assert "Δ firing rate" in svg
    assert "spike-density function" in html
    assert "spike-density functions" in svg
    assert "±1 SEM across units" in svg
    assert 'fill-opacity="0.14"' in svg
    assert "zscoreLimit: 3" in html
    assert 'colorLimit.max = "6"' in html
    assert 'id="color-key-min"' in html
    assert 'id="color-key-max"' in html
    assert "DecompressionStream" in html
    assert "sdfMeanAtlas" in html
    assert "sdfSemAtlas" not in html
    assert "function sdfKernel" not in html
    assert "__NEUROPIXELS_EVENT_" not in html
