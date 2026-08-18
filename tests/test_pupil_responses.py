from __future__ import annotations

import math
from collections import Counter
from pathlib import Path

import pytest

from openscope_p3_publication.pupil_figure import (
    load_pupil_event_responses,
    write_pupil_event_html,
    write_pupil_event_svg,
)
from openscope_p3_publication.pupil_responses import (
    EVENT_DEFINITIONS,
    combine_mean_and_std_traces,
    event_baseline_windows,
    event_matches,
    event_response_windows,
    event_start_times,
    mean_trace,
    pupil_response_window_label,
    remove_isolated_outliers_with_interpolation,
    subtract_traces,
)


def event(context: str, event_id: str):
    return next(
        definition
        for definition in EVENT_DEFINITIONS[context]
        if definition.id == event_id
    )


def test_event_definitions_match_context_and_control_rows() -> None:
    orientation = event("standard", "orientation_45")
    assert event_matches(
        orientation,
        "orientation_45",
        control=False,
        orientation=math.pi / 4,
    )
    assert event_matches(
        orientation,
        "single",
        control=True,
        orientation=math.pi / 4,
    )
    assert not event_matches(
        orientation,
        "single",
        control=True,
        orientation=math.pi / 2,
    )

    motor_halt = event("sensorimotor", "motor_halt")
    assert event_matches(motor_halt, "motor_halt", control=False)
    assert event_matches(motor_halt, "motor_halt", control=True)

    sequence_omission = event("sequence", "omission")
    assert event_matches(sequence_omission, "omission", control=False)
    assert event_matches(sequence_omission, "omission", control=True)
    assert not event_matches(sequence_omission, "sequence_omission", control=False)

    delay = event("duration", "delay_500")
    assert event_matches(delay, "jitter", control=False, delay=0.5)
    assert event_matches(delay, "single", control=True, delay=0.5)
    assert not event_matches(delay, "jitter", control=False, delay=0.15)


def test_event_alignment_uses_selected_nwb_start_times() -> None:
    start_times = [100.0, 100.7, 101.55, 102.25]
    assert event_start_times(start_times, [1, 3]) == [100.7, 102.25]


def test_context_specific_pupil_baseline_windows() -> None:
    starts = [100.0, 100.7, 101.4, 102.1]
    stops = [100.37, 101.07, 101.77, 102.47]

    assert event_baseline_windows(starts, stops, [2], "standard") == [
        (101.07, 101.4)
    ]
    assert event_baseline_windows(starts, stops, [2], "duration") == [
        (101.07, 101.4)
    ]
    assert event_baseline_windows(starts, stops, [2], "sequence") == [
        (100.7, 101.4)
    ]
    sensorimotor = event_baseline_windows(
        starts,
        stops,
        [2],
        "sensorimotor",
    )
    assert sensorimotor[0][0] == pytest.approx(101.057)
    assert sensorimotor[0][1] == 101.4


def test_first_or_cross_block_event_has_no_preceding_baseline() -> None:
    starts = [100.0, 100.7, 200.0]
    stops = [100.37, 101.07, 200.37]
    blocks = [1, 1, 3]
    assert event_baseline_windows(
        starts,
        stops,
        [0, 2],
        "standard",
        blocks,
    ) == [None, None]


def test_context_specific_pupil_response_windows() -> None:
    starts = [100.0, 100.7, 101.4, 102.1]
    stops = [100.37, 101.07, 101.77, 102.47]
    delays = [0.343, 0.15, 0.5, 1.0]

    assert event_response_windows(
        starts,
        stops,
        delays,
        [1, 2],
        "standard",
    ) == [(100.7, 101.07), (101.4, 101.77)]
    duration = event_response_windows(
        starts,
        stops,
        delays,
        [1, 2, 3],
        "duration",
    )
    assert duration[0] == pytest.approx((101.043, 101.193))
    assert duration[1] == pytest.approx((101.743, 102.243))
    assert duration[2] == pytest.approx((102.443, 103.443))


def test_pupil_response_window_labels() -> None:
    assert pupil_response_window_label("standard", "halt") == "NWB start_time–stop_time"
    assert pupil_response_window_label("duration", "delay_150") == "0.343–0.493 s"
    assert pupil_response_window_label("duration", "delay_500") == "0.343–0.843 s"
    assert pupil_response_window_label("duration", "delay_1000") == "0.343–1.343 s"
    assert pupil_response_window_label("duration", "omission") == "0.343–0.686 s"


def test_isolated_pupil_outlier_is_interpolated() -> None:
    trace = [10.0] * 100
    trace[50] = 100.0

    cleaned, indices = remove_isolated_outliers_with_interpolation(
        trace,
        sample_rate_hz=10,
        window_seconds=3,
        zscore_threshold=3,
        max_isolated_length=3,
    )

    assert indices == [50]
    assert cleaned[50] == pytest.approx(10.0)
    assert cleaned[:50] == trace[:50]
    assert cleaned[51:] == trace[51:]


def test_sustained_tracking_excursion_is_not_interpolated() -> None:
    trace = [10.0] * 100
    trace[48:52] = [100.0] * 4

    cleaned, indices = remove_isolated_outliers_with_interpolation(
        trace,
        sample_rate_hz=10,
        window_seconds=3,
        zscore_threshold=1,
        max_isolated_length=3,
    )

    assert indices == []
    assert cleaned == trace


def test_trace_aggregation_preserves_missing_samples() -> None:
    assert mean_trace([[1.0, None, 3.0], [3.0, 4.0, None]]) == [
        2.0,
        4.0,
        3.0,
    ]
    assert subtract_traces([4.0, None, 2.0], [1.5, 2.0, None]) == [
        2.5,
        None,
        None,
    ]


def test_mouse_variability_combines_trial_and_session_variation() -> None:
    mean, std = combine_mean_and_std_traces(
        [[0.0, 5.0, None], [2.0, 5.0, 4.0]],
        [[1.0, 2.0, None], [1.0, 4.0, 3.0]],
    )
    assert mean == [1.0, 5.0, 4.0]
    assert std[0] == pytest.approx(2**0.5)
    assert std[1] == pytest.approx((10.0) ** 0.5)
    assert std[2] == 3.0


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"sample_rate_hz": 0}, "sample_rate_hz"),
        ({"sample_rate_hz": 10, "window_seconds": 0}, "window_seconds"),
        ({"sample_rate_hz": 10, "zscore_threshold": 0}, "zscore_threshold"),
        ({"sample_rate_hz": 10, "max_isolated_length": 0}, "max_isolated_length"),
    ],
)
def test_outlier_cleanup_rejects_invalid_parameters(
    kwargs: dict,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        remove_isolated_outliers_with_interpolation([1.0, 2.0, 3.0], **kwargs)


def test_pupil_event_snapshot_is_source_backed() -> None:
    payload = load_pupil_event_responses()

    assert payload["version"] == 1
    assert len(payload["sessions"]) == 132
    assert len(payload["mice"]) == 98
    assert len(payload["summaries"]) == 80
    assert payload["exclusions"] == []
    assert payload["analysis_parameters"]["event_alignment"].startswith(
        "NWB interval-table start_time"
    )
    assert payload["analysis_parameters"]["baseline"] == {
        "duration": "recorded previous stop_time to current start_time",
        "sensorimotor": "343 ms immediately preceding current start_time",
        "sequence": "recorded previous start_time to current start_time",
        "standard": "recorded previous stop_time to current start_time",
    }
    assert payload["analysis_parameters"]["pupil"]["response_window"] == {
        "duration": "start_time + 0.343 s through start_time + 0.343 s + row Delay",
        "sensorimotor": "NWB start_time through stop_time",
        "sequence": "NWB start_time through stop_time",
        "standard": "NWB start_time through stop_time",
    }
    assert Counter(session["modality"] for session in payload["sessions"]) == {
        "neuropixels": 60,
        "mesoscope": 64,
        "slap2": 8,
    }
    assert {
        modality: len(
            {
                session["mouse_id"]
                for session in payload["sessions"]
                if session["modality"] == modality
            }
        )
        for modality in ("neuropixels", "mesoscope", "slap2")
    } == {"neuropixels": 16, "mesoscope": 8, "slap2": 3}
    for mouse in payload["mice"]:
        for event in mouse["events"]:
            if event["pupil"] is None:
                continue
            for condition in ("event", "control"):
                record = event["pupil"][condition]
                assert len(record["raw_std_trace"]) == 121
                assert len(record["percent_change_std_trace"]) == 121
                assert record["response_percent_change_std"] >= 0

    unavailable = {
        (
            summary["modality"],
            summary["cohort"],
            summary["context"],
            summary["event_id"],
        )
        for summary in payload["summaries"]
        if not summary["availability"]["available"]
    }
    assert unavailable == {
        ("slap2", "motor", "duration", event_id)
        for event_id in ("delay_150", "delay_500", "delay_1000", "omission")
    }


def test_pupil_event_outputs_are_deterministic_and_accessible(
    tmp_path: Path,
) -> None:
    svg_path = tmp_path / "pupil.svg"
    html_path = tmp_path / "pupil.html"

    write_pupil_event_svg(svg_path)
    first_svg = svg_path.read_bytes()
    write_pupil_event_svg(svg_path)
    assert svg_path.read_bytes() == first_svg

    write_pupil_event_html(html_path, static_output=svg_path)
    first_html = html_path.read_bytes()
    write_pupil_event_html(html_path, static_output=svg_path)
    assert html_path.read_bytes() == first_html

    svg = first_svg.decode()
    html = first_html.decode()
    assert 'role="img"' in svg
    assert "Population peri-event pupil response difference" in svg
    assert "Mouse-level response-window effects" in svg
    assert "insufficient tracking" in svg
    assert svg.count("<path ") >= 50
    assert svg.count("<circle ") >= 300

    assert 'id="modality-tabs"' in html
    assert 'id="cohort-tabs"' in html
    assert 'id="context-tabs"' in html
    assert 'id="event-select"' in html
    assert 'data-scale="percent"' in html
    assert 'data-scale="raw"' in html
    assert 'data-scope="population"' in html
    assert 'data-scope="mouse"' in html
    assert 'id="mouse-select"' in html
    assert "plus or minus one standard deviation" in html
    assert "Matched control" in html
    assert "Static" in html
    assert "__PUPIL_EVENT_" not in html
