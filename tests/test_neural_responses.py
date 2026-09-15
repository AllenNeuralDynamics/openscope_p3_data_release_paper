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
    sequence_control_segments,
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
    SEQUENCE_CONTROL_BASELINE_TABLE,
    SEQUENCE_REFERENCE_ORIENTATION_DEGREES,
    SEQUENCE_REFERENCE_TRIAL_TYPE,
    adjacent_blank_windows,
    blank_interval_windows,
    classify_neuron_type,
    context_event_definitions,
    context_window_seconds,
    event_indices,
    neural_baseline_windows,
    neural_response_windows,
    qc_passes,
    relative_bin_centers,
    relative_bin_edges,
    sample_windows_evenly,
    sdf_kernel,
    sequence_comparison_span,
    sequence_reference_indices,
    smooth_trace,
)


def test_neural_sessions_cover_four_contexts_for_one_mouse() -> None:
    assert {session.context for session in NEURAL_SESSIONS} == {
        "standard",
        "sensorimotor",
        "sequence",
        "duration",
    }
    assert all("830794" in session.session_id for session in NEURAL_SESSIONS)
    assert len({session.asset_id for session in NEURAL_SESSIONS}) == 4
    assert all(
        session.asset_path.startswith("sub-830794/") for session in NEURAL_SESSIONS
    )


def test_neural_time_grid_uses_two_point_five_millisecond_bins() -> None:
    assert BIN_SECONDS == 0.0025
    assert BASELINE_BIN_SECONDS == 0.02
    assert SDF_SOURCE_BIN_SECONDS == 0.0025
    assert CONTEXT_WINDOWS_SECONDS == {
        "standard": (-0.75, 0.75),
        "sensorimotor": (-0.75, 0.75),
        "sequence": (-2.0, 1.0),
        "duration": (-1.5, 1.5),
    }
    for context, expected_count in (
        ("standard", 600),
        ("sensorimotor", 600),
        ("sequence", 1200),
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


def test_sequence_baseline_is_the_grey_inter_sequence_interval() -> None:
    """The grey interval three rows back, not the preceding grating element.

    Sequences are five contiguous 266.9 ms rows -- four gratings then a grey
    inter-sequence interval -- with the substitution always at element three.
    """
    period = 0.2669
    starts = [round(index * period, 6) for index in range(20)]
    stops = [round(value + period, 6) for value in starts]
    blocks = [2.0] * 20
    # Element three of the fourth sequence.
    substitution = 3 * 5 + 2

    windows = neural_baseline_windows(starts, stops, [substitution], "sequence", blocks)
    grey = substitution - 3
    assert windows == [(starts[grey], stops[grey])]

    # The old rule used the preceding element, a 45 degree grating.
    assert windows != [(starts[substitution - 1], starts[substitution])]

    # The baseline is a full row, not the run up to the event onset.
    start, stop = windows[0]
    assert stop - start == pytest.approx(period)


def test_sequence_baseline_is_unavailable_without_a_preceding_grey() -> None:
    period = 0.2669
    starts = [round(index * period, 6) for index in range(20)]
    stops = [round(value + period, 6) for value in starts]
    blocks = [2.0] * 20
    # Element three of the first sequence has no previous sequence.
    assert neural_baseline_windows(starts, stops, [2], "sequence", blocks) == [None]


def test_sequence_baseline_respects_block_boundaries() -> None:
    period = 0.2669
    starts = [round(index * period, 6) for index in range(20)]
    stops = [round(value + period, 6) for value in starts]
    blocks = [2.0] * 10 + [3.0] * 10
    assert neural_baseline_windows(starts, stops, [11], "sequence", blocks) == [None]


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

    assert payload["version"] == 12
    assert payload["subject"] == "830794"
    assert payload["sessionOrder"] == [
        "standard",
        "sensorimotor",
        "sequence",
        "duration",
    ]
    assert [session["windowSeconds"] for session in payload["sessions"]] == [
        [-0.75, 0.75],
        [-0.75, 0.75],
        # Wide enough to reach element three of the previous sequence at -1.3345 s.
        [-2.0, 1.0],
        [-1.5, 1.5],
    ]
    assert [session["unitCount"] for session in payload["sessions"]] == [
        3018,
        3966,
        2902,
        3082,
    ]
    assert sum(
        unit["qcPass"]
        for session in payload["sessions"]
        for unit in session["units"]
    ) == 8093
    assert all(len(session["events"]) == 4 for session in payload["sessions"])
    assert [
        len(session["events"][0]["timing"]["context"]["presentationWindows"])
        for session in payload["sessions"]
    ] == [3, 1, 12, 5]
    assert [
        session["sdfMeanAtlas"]["shape"][-1]
        for session in payload["sessions"]
    ] == [600, 600, 1200, 1200]
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
        {"RS": 2218, "FS": 512, "SST": 288},
        {"RS": 2916, "FS": 715, "SST": 335},
        {"RS": 2052, "FS": 498, "SST": 352},
        {"RS": 2006, "FS": 574, "SST": 502},
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
    } == {"mua": 4459, "noise": 3672, "sua": 4837}
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
    assert payload["analysisParameters"]["ontology"] == {
        "areaSource": "Allen CCF location of each unit's extremum-channel electrode",
        "graphOrderSource": (
            "Allen structure-tree graph_order via iblatlas BrainRegions.order"
        ),
        "packageVersion": "1.2.0",
        "parentAreaRule": (
            "collapse Allen layer nodes and hyphenated subdivisions to the nearest "
            "non-collapsible ancestor; retain an already canonical area"
        ),
    }
    ontology_by_location = {
        unit["location"]: {
            key: unit[key]
            for key in (
                "areaGraphOrder",
                "areaId",
                "areaLevel",
                "parentArea",
                "parentAreaGraphOrder",
                "parentAreaId",
                "parentAreaLevel",
            )
        }
        for session in payload["sessions"]
        for unit in session["units"]
    }
    assert ontology_by_location["VISp2/3"] == {
        "areaGraphOrder": 187,
        "areaId": 821,
        "areaLevel": 8,
        "parentArea": "VISp",
        "parentAreaGraphOrder": 185,
        "parentAreaId": 385,
        "parentAreaLevel": 7,
    }
    assert ontology_by_location["LGd-co"] == {
        "areaGraphOrder": 664,
        "areaId": 496345668,
        "areaLevel": 8,
        "parentArea": "LGd",
        "parentAreaGraphOrder": 662,
        "parentAreaId": 170,
        "parentAreaLevel": 7,
    }
    assert ontology_by_location["CA1"]["parentArea"] == "CA1"
    assert ontology_by_location["CA1"]["areaGraphOrder"] == 457
    assert ontology_by_location["ACAv6a"]["parentArea"] == "ACAv"
    assert ontology_by_location["ACAv6b"]["parentArea"] == "ACAv"
    assert ontology_by_location["DG-sg"]["parentArea"] == "DG"
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

    assert len(areas) == 50
    assert len(columns) == 16
    assert areas == sorted(areas, key=sort_key)
    categories = [
        next(group for group in STATIC_AREA_GROUP_ORDER if group in area_groups[area])
        for area in areas
    ]
    assert {
        group: categories.count(group) for group in STATIC_AREA_GROUP_ORDER
    } == {
        "frontal": 17,
        "visual": 20,
        "hippocampal": 6,
        "thalamic": 7,
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
    assert "Area-level responsiveness and mismatch-minus-control effect" in svg
    assert "Responsive unit dynamics" in svg
    # Two matrices over the same rows, and a hatch so an unmeasured cell is
    # never drawn as a fraction on either panel's own scale.
    assert svg.count('id="responsive-no-data"') == 1
    assert 'url(#responsive-no-data)' in svg
    assert "chance 5%" in svg
    assert "% responsive" in svg
    # Rows are selected on the test, not on the effect the panel plots.
    assert "Rows are selected on the test, not on the plotted effect" in svg
    assert "Top 150 QC-passing MUA/SUA units" not in svg
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
    assert 'id="response-selection-label"' not in html
    assert 'aria-label="Area for response filtering"' in html
    assert 'id="probe-select"' not in html
    assert html.count('id="response-canvas"') == 1
    assert 'id="baseline-response-canvas"' not in html
    assert 'id="baseline-subtracted"' in html
    assert 'id="response-note"' not in html
    # A different element from the one 365c616 removed: that was static chrome
    # restating the dashed guides. This one states what the control curve is,
    # which the sequence segmentation makes necessary rather than redundant.
    assert 'id="sequence-control-note"' in html
    assert "drawn only inside the two shaded windows" in html
    assert "function sequenceControlSegments(" in html
    assert 'id="heatmap-detail"' not in html
    assert 'id="source-note"' not in html
    assert "Response conditioning" in html
    assert "Mismatch z-score" in html
    assert "Control z-score" in html
    assert "Mismatch response averaged over units in" in html
    assert "Mismatch response for unit" in html
    assert 'class="interactive-controls"' in html
    assert "baselineSubtracted && yRange[0] <= 0" in html
    assert "function plotHorizontalBounds()" in html
    assert "const plot = { ...plotHorizontalBounds(), top: 22, bottom: 280 }" in html
    assert "waveform-canvas" not in html
    assert "Time from mismatch stimulus (s)" in html
    assert '<option value="area">Area</option>' in html
    assert "Time to positive peak" in html
    assert ">Rastermap<" in html
    assert '<option value="depth">' not in html
    assert '<option value="unit">' not in html
    assert 'sort: "area"' in html
    assert "Sorted unit ordering" in html
    assert "Depth on probe" in html
    assert "Parent area" in html
    assert "parentAreaGraphOrder" in html
    assert "areaGraphOrder" in html
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
    assert "±1 SEM across the same" in svg
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


class TestBlankIntervalWindows:
    """The sequence control baseline, borrowed from control block 1.

    Control block 2 is contiguous, so the sequence row offset lands on a
    grating rather than a blank. See docs/neuropixels-mismatch-responsiveness.md.
    """

    def _repeats(self):
        # Two repeats of the same block, numbered 1 and 3 as in the protocol.
        starts, stops, blocks = [], [], []
        for block, origin in ((1.0, 0.0), (3.0, 100.0)):
            for row in range(4):
                starts.append(origin + row * 0.7)
                stops.append(origin + row * 0.7 + 0.367)
                blocks.append(block)
        return starts, stops, blocks

    def test_gaps_are_grouped_by_block(self):
        windows = blank_interval_windows(*self._repeats())
        assert sorted(windows) == [1.0, 3.0]
        assert len(windows[1.0]) == len(windows[3.0]) == 3

    def test_a_gap_runs_from_one_stop_to_the_next_start(self):
        windows = blank_interval_windows(*self._repeats())
        assert windows[1.0][0] == pytest.approx((0.367, 0.7))

    def test_block_boundaries_do_not_produce_a_gap(self):
        windows = blank_interval_windows(*self._repeats())
        assert all(stop <= 2.5 for _start, stop in windows[1.0])

    def test_contiguous_rows_yield_no_blanks(self):
        # Control block 2's shape: no inter-row gap anywhere.
        starts = [row * 0.2669 for row in range(10)]
        stops = [start + 0.2669 for start in starts]
        assert blank_interval_windows(starts, stops, [4.0] * 10) == {}

    def test_display_jitter_is_not_a_blank(self):
        starts = [0.0, 0.2680, 0.5360]
        stops = [0.2669, 0.5349, 0.8029]
        assert blank_interval_windows(starts, stops, [4.0] * 3) == {}

    def test_rows_out_of_order_are_sorted_first(self):
        windows = blank_interval_windows([0.7, 0.0], [1.067, 0.367], [1.0, 1.0])
        assert windows[1.0] == [pytest.approx((0.367, 0.7))]

    def test_mismatched_lengths_raise(self):
        with pytest.raises(ValueError, match="same length"):
            blank_interval_windows([0.0, 1.0], [0.5], [1.0, 1.0])


class TestAdjacentBlankWindows:
    def _repeats(self):
        starts, stops, blocks = [], [], []
        for block, origin in ((1.0, 0.0), (3.0, 100.0)):
            for row in range(4):
                starts.append(origin + row * 0.7)
                stops.append(origin + row * 0.7 + 0.367)
                blocks.append(block)
        return starts, stops, blocks

    def test_the_repeat_ending_just_before_the_target_is_chosen(self):
        windows = adjacent_blank_windows(*self._repeats(), 102.5)
        assert windows[0][0] == pytest.approx(100.367)

    def test_a_later_repeat_is_not_preferred_over_a_preceding_one(self):
        # The first repeat precedes the target; the second is nearer but later.
        windows = adjacent_blank_windows(*self._repeats(), 3.0)
        assert windows[0][0] == pytest.approx(0.367)

    def test_a_following_repeat_is_used_when_none_precedes(self):
        windows = adjacent_blank_windows(*self._repeats(), -10.0)
        assert windows[0][0] == pytest.approx(0.367)

    def test_the_borrow_table_is_control_block_one(self):
        # Not the sequence session's own control table, which is block 2.
        assert SEQUENCE_CONTROL_BASELINE_TABLE == "Control block 1_presentations"
        sequence = next(
            config for config in NEURAL_SESSIONS if config.context == "sequence"
        )
        assert sequence.control_table == "Control block 2_presentations"
        assert SEQUENCE_CONTROL_BASELINE_TABLE != sequence.control_table

    def test_a_table_without_blanks_raises(self):
        starts = [row * 0.2669 for row in range(10)]
        stops = [start + 0.2669 for start in starts]
        with pytest.raises(ValueError, match="No blank"):
            adjacent_blank_windows(starts, stops, [4.0] * 10, 5.0)


class TestSampleWindowsEvenly:
    def _windows(self, count: int):
        return [(float(index), index + 0.3336) for index in range(count)]

    def test_one_window_is_returned_per_trial(self):
        assert len(sample_windows_evenly(self._windows(543), 70)) == 70

    def test_the_sample_spans_the_whole_repeat(self):
        sampled = sample_windows_evenly(self._windows(543), 70)
        assert sampled[0][0] == pytest.approx(0.0)
        assert sampled[-1][0] > 530.0

    def test_windows_are_distinct_when_there_are_enough_of_them(self):
        assert len(set(sample_windows_evenly(self._windows(543), 70))) == 70

    def test_more_trials_than_windows_reuses_windows_without_failing(self):
        sampled = sample_windows_evenly(self._windows(3), 7)
        assert len(sampled) == 7
        assert set(sampled) <= set(self._windows(3))

    def test_no_trials_needs_no_windows(self):
        assert sample_windows_evenly(self._windows(10), 0) == []

    def test_sampling_from_nothing_raises(self):
        with pytest.raises(ValueError, match="empty"):
            sample_windows_evenly([], 4)


class TestSequenceReferenceIndices:
    """The stimulus-matched control alignment for the comparison window."""

    def _table(self):
        types = ["single", "halt", "single", "omission", "single", "single"]
        oris = [
            0.0,
            0.0,
            math.radians(45),
            0.0,
            math.radians(90),
            1e-5,
        ]
        return types, oris

    def test_only_single_rows_at_zero_degrees_match(self):
        assert sequence_reference_indices(*self._table()) == [0, 5]

    def test_a_halt_at_zero_degrees_is_not_a_grating(self):
        # halt and omission also carry orientation 0 but are not the stimulus.
        types, oris = self._table()
        assert 1 not in sequence_reference_indices(types, oris)
        assert 3 not in sequence_reference_indices(types, oris)

    def test_orientation_is_matched_within_tolerance(self):
        # Stored orientations are radians and carry float error.
        assert sequence_reference_indices(["single"], [1e-5]) == [0]
        assert sequence_reference_indices(["single"], [0.01]) == []

    def test_the_matched_orientation_is_element_three(self):
        assert SEQUENCE_REFERENCE_ORIENTATION_DEGREES == 0.0
        assert SEQUENCE_REFERENCE_TRIAL_TYPE == "single"

    def test_mismatched_lengths_raise(self):
        with pytest.raises(ValueError, match="same length"):
            sequence_reference_indices(["single", "single"], [0.0])


class TestSequenceComparisonSpan:
    def _rows(self, count: int, period: float = 0.2669):
        starts = [index * period for index in range(count)]
        stops = [start + period for start in starts]
        return starts, stops

    def test_the_span_is_five_rows_back(self):
        starts, stops = self._rows(12)
        span = sequence_comparison_span(starts, stops, [7])
        assert span == pytest.approx((-1.3345, -1.0676))

    def test_the_span_width_is_one_element(self):
        starts, stops = self._rows(12)
        start, stop = sequence_comparison_span(starts, stops, [7])
        assert stop - start == pytest.approx(0.2669)

    def test_the_median_is_taken_across_trials(self):
        starts, stops = self._rows(30)
        span = sequence_comparison_span(starts, stops, [7, 12, 17])
        assert span == pytest.approx((-1.3345, -1.0676))

    def test_trials_without_a_comparison_row_are_skipped(self):
        starts, stops = self._rows(12)
        span = sequence_comparison_span(starts, stops, [2, 7])
        assert span == pytest.approx((-1.3345, -1.0676))

    def test_no_trial_with_a_comparison_row_raises(self):
        starts, stops = self._rows(12)
        with pytest.raises(ValueError, match="within the table"):
            sequence_comparison_span(starts, stops, [1, 2])

    def test_no_trials_raises(self):
        starts, stops = self._rows(12)
        with pytest.raises(ValueError, match="No trials"):
            sequence_comparison_span(starts, stops, [])


class TestSequenceControlSegments:
    """Restricting the control trace to the two stimulus-matched windows."""

    def _inputs(self):
        # 1.0 s at 100 ms bins, comparison window at [-0.6, -0.4].
        time = [round(-1.0 + index * 0.1, 3) for index in range(21)]
        control = [1.0] * len(time)
        sem = [0.1] * len(time)
        reference = [5.0, 6.0]
        reference_sem = [0.5, 0.6]
        return time, control, sem, reference, reference_sem

    def _call(self, **overrides):
        time, control, sem, reference, reference_sem = self._inputs()
        kwargs = dict(
            comparison_span=(-0.6, -0.4),
            mismatch_stop=0.2,
            reference_bin_seconds=0.1,
        )
        kwargs.update(overrides)
        return time, sequence_control_segments(
            time, control, sem, reference, reference_sem, **kwargs
        )

    def test_the_mismatch_window_keeps_the_control_block_trace(self):
        time, (values, _sem) = self._call()
        for index, seconds in enumerate(time):
            if 0.0 <= seconds <= 0.2:
                assert values[index] == 1.0

    def test_the_comparison_window_is_filled_from_the_reference(self):
        time, (values, _sem) = self._call()
        assert values[time.index(-0.6)] == 5.0
        assert values[time.index(-0.5)] == 6.0

    def test_everything_outside_both_windows_is_a_gap(self):
        time, (values, _sem) = self._call()
        for index, seconds in enumerate(time):
            inside = (0.0 <= seconds <= 0.2) or (-0.6 <= seconds <= -0.4)
            if not inside:
                assert values[index] is None

    def test_the_sem_follows_the_same_segmentation(self):
        time, (values, sem) = self._call()
        assert sem[time.index(-0.6)] == 0.5
        assert sem[time.index(0.0)] == 0.1
        assert sem[time.index(-1.0)] is None
        assert len(sem) == len(values)

    def test_a_reference_shorter_than_the_window_leaves_a_gap(self):
        # Only two reference bins cover a 200 ms window at 100 ms bins.
        time, (values, _sem) = self._call(comparison_span=(-0.6, -0.2))
        assert values[time.index(-0.6)] == 5.0
        assert values[time.index(-0.3)] is None

    def test_absent_sem_is_propagated_as_absent(self):
        time, control, _sem, reference, _reference_sem = self._inputs()
        values, sem = sequence_control_segments(
            time,
            control,
            None,
            reference,
            None,
            comparison_span=(-0.6, -0.4),
            mismatch_stop=0.2,
            reference_bin_seconds=0.1,
        )
        assert sem is None
        assert values[time.index(-0.6)] == 5.0

    def test_mismatched_lengths_raise(self):
        with pytest.raises(ValueError, match="same length"):
            sequence_control_segments(
                [0.0, 0.1],
                [1.0],
                None,
                [1.0],
                None,
                comparison_span=(-0.6, -0.4),
                mismatch_stop=0.2,
                reference_bin_seconds=0.1,
            )

    def test_a_non_increasing_span_raises(self):
        with pytest.raises(ValueError, match="increasing"):
            self._call(comparison_span=(-0.4, -0.6))

    def test_a_non_positive_bin_raises(self):
        with pytest.raises(ValueError, match="positive"):
            self._call(reference_bin_seconds=0.0)
