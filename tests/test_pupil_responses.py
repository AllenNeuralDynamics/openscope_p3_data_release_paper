from __future__ import annotations

import json
import math
import runpy
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

from openscope_p3_publication.pupil_figure import (
    load_pupil_event_responses,
    mean_sem_trace,
    trace_standard_error,
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


def test_pupil_extractor_uses_session_id_date() -> None:
    extractor = runpy.run_path(
        str(Path(__file__).parents[1] / "scripts" / "extract_pupil_event_responses.py")
    )
    session_date_from_id = extractor["session_date_from_id"]

    assert (
        session_date_from_id("multiplane-ophys_850399_2026-05-20_09-37-10")
        == "2026-05-20"
    )
    assert session_date_from_id("SLAP2_715092_2024-07-09_11-32-12") == "2024-07-09"
    with pytest.raises(RuntimeError, match="one ISO date"):
        session_date_from_id("aborted")


def test_pupil_extractor_migrates_compatible_running_cache(tmp_path: Path) -> None:
    extractor = runpy.run_path(
        str(Path(__file__).parents[1] / "scripts" / "extract_pupil_event_responses.py")
    )
    cache_path = tmp_path / "sessions" / "asset-id.json"
    cache_path.parent.mkdir()
    cache_path.write_text(
        json.dumps(
            {
                "analysis_signature": next(
                    iter(extractor["COMPATIBLE_CACHE_SIGNATURES"])
                ),
                "asset_modified": "modified",
                "cache_version": extractor["CACHE_VERSION"],
                "session": {
                    "running": {"sample_rate_hz": 60.0},
                    "running_unavailable_reason": None,
                    "session_id": "cached",
                },
            }
        ),
        encoding="utf-8",
    )

    session = extractor["cached_session"](
        {},
        {"asset_id": "asset-id", "modified": "modified"},
        tmp_path,
        "current-signature",
    )

    assert session["session_id"] == "cached"
    assert session["running"]["discarded_nonincreasing_sample_count"] == 0
    assert json.loads(cache_path.read_text(encoding="utf-8"))[
        "analysis_signature"
    ] == "current-signature"


def test_pupil_extractor_retries_cached_timestamp_failure(tmp_path: Path) -> None:
    extractor = runpy.run_path(
        str(Path(__file__).parents[1] / "scripts" / "extract_pupil_event_responses.py")
    )
    cache_path = tmp_path / "sessions" / "asset-id.json"
    cache_path.parent.mkdir()
    cache_path.write_text(
        json.dumps(
            {
                "analysis_signature": next(
                    iter(extractor["COMPATIBLE_CACHE_SIGNATURES"])
                ),
                "asset_modified": "modified",
                "cache_version": extractor["CACHE_VERSION"],
                "session": {
                    "running": None,
                    "running_unavailable_reason": (
                        "finite running-speed timestamps are not strictly increasing"
                    ),
                    "session_id": "stale",
                },
            }
        ),
        encoding="utf-8",
    )
    cached_session = extractor["cached_session"]
    cached_session.__globals__["extract_session"] = lambda _config, _asset: {
        "running": {"discarded_nonincreasing_sample_count": 4},
        "running_unavailable_reason": None,
        "session_id": "retried",
    }

    session = cached_session(
        {},
        {"asset_id": "asset-id", "modified": "modified"},
        tmp_path,
        "current-signature",
    )

    assert session["session_id"] == "retried"
    assert json.loads(cache_path.read_text(encoding="utf-8"))["session"] == session


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
        (100.37, 100.7)
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
    assert event_baseline_windows(
        starts,
        stops,
        [1, 2],
        "duration",
        blocks,
    ) == [None, None]


def test_running_event_summary_uses_forward_speed_and_trial_baseline() -> None:
    extractor = runpy.run_path(
        str(Path(__file__).parents[1] / "scripts" / "extract_pupil_event_responses.py")
    )
    timestamps = np.arange(0, 6, 0.01)
    speed = np.full(timestamps.shape, 2.0)
    speed[(timestamps >= 3.0) & (timestamps <= 3.5)] = 5.0
    summary = extractor["running_event_summary"](
        {
            "sample_rate_hz": 100.0,
            "timestamps": timestamps,
            "values": speed,
        },
        np.asarray([3.0]),
        [(2.0, 2.5)],
        [(3.0, 3.5)],
    )

    assert summary["valid_trials"] == 1
    assert summary["baseline_mean_cm_s"] == 2.0
    assert summary["response_mean_cm_s"] == 5.0
    assert summary["response_change_mean_cm_s"] == 3.0
    assert len(summary["raw_mean_trace"]) == 121
    assert len(summary["baseline_change_mean_trace"]) == 121


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


def test_individual_trace_sem_uses_valid_trial_count() -> None:
    assert trace_standard_error([2.0, None, 4.0], 4) == [1.0, None, 2.0]
    with pytest.raises(ValueError, match="at least one sample"):
        trace_standard_error([1.0], 0)


def test_population_trace_sem_uses_mouse_means() -> None:
    assert mean_sem_trace([[1.0, 3.0, None], [3.0, 5.0, 7.0]]) == {
        "lower": [1.0, 3.0, 7.0],
        "mean": [2.0, 4.0, 7.0],
        "upper": [3.0, 5.0, 7.0],
    }
    with pytest.raises(ValueError, match="at least one mouse"):
        mean_sem_trace([])


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

    assert payload["version"] == 2
    assert len(payload["sessions"]) == 154
    assert len(payload["mice"]) == 108
    assert len(payload["summaries"]) == 80
    assert payload["exclusions"] == []
    assert {
        (
            record["modality"],
            record["mouse_id"],
            record["context"],
            record["reason"],
        )
        for record in payload["running_exclusions"]
    } == {
        (
            "neuropixels",
            "830846",
            "duration",
            "processed running-speed series unavailable",
        ),
        (
            "neuropixels",
            "830847",
            "sequence",
            "processed running-speed series unavailable",
        ),
    }
    assert payload["analysis_parameters"]["event_alignment"].startswith(
        "NWB interval-table start_time"
    )
    assert payload["analysis_parameters"]["baseline"] == {
        "duration": "unmanipulated interval from row i-2 stop_time to row i-1 start_time",
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
    assert payload["analysis_parameters"]["running"] == {
        "direction": "forward speed; negative source velocities set to zero",
        "maximum_interpolation_gap_seconds": 0.2,
        "minimum_baseline_fraction": 0.8,
        "minimum_window_fraction": 0.75,
        "normalization": "subtract each trial's mean baseline speed",
        "response_window": {
            "duration": "start_time + 0.343 s through start_time + 0.343 s + row Delay",
            "sensorimotor": "NWB start_time through stop_time",
            "sequence": "NWB start_time through stop_time",
            "standard": "NWB start_time through stop_time",
        },
        "timestamp_cleanup": (
            "discard non-increasing samples only when at most 0.1% of the series"
        ),
        "unit": "cm/s",
    }
    assert payload["analysis_parameters"]["trace_sampling"] == {
        "filter": "none",
        "method": "linear interpolation at the common time-grid timestamps",
    }
    assert Counter(session["modality"] for session in payload["sessions"]) == {
        "neuropixels": 60,
        "mesoscope": 86,
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
    } == {"neuropixels": 16, "mesoscope": 10, "slap2": 3}
    assert {
        session["session_id"]: session["running"][
            "discarded_nonincreasing_sample_count"
        ]
        for session in payload["sessions"]
        if session["running"] is not None
        and session["running"]["discarded_nonincreasing_sample_count"]
    } == {
        "828409_2025-11-20_10-01-34": 4,
        "829704_2025-12-18_10-57-36": 2,
    }
    example_mouse = {
        mouse["context"]: mouse
        for mouse in payload["mice"]
        if mouse["modality"] == "neuropixels" and mouse["mouse_id"] == "830846"
    }
    assert set(example_mouse) == {"standard", "sensorimotor", "sequence", "duration"}
    assert example_mouse["standard"]["running_source_session_count"] == 1
    assert example_mouse["duration"]["running_source_session_count"] == 0
    assert all(
        event["running"] is None for event in example_mouse["duration"]["events"]
    )
    for mouse in payload["mice"]:
        for event in mouse["events"]:
            if event["pupil"] is not None:
                for condition in ("event", "control"):
                    record = event["pupil"][condition]
                    assert len(record["raw_std_trace"]) == 121
                    assert len(record["percent_change_std_trace"]) == 121
                    assert record["response_percent_change_std"] >= 0
            if event["running"] is not None:
                for condition in ("event", "control"):
                    running_record = event["running"][condition]
                    assert len(running_record["raw_std_trace"]) == 121
                    assert len(running_record["baseline_change_std_trace"]) == 121
                    assert running_record["response_change_std_cm_s"] >= 0

    unavailable = {
        (
            summary["modality"],
            summary["cohort"],
            summary["context"],
            summary["event_id"],
        )
        for summary in payload["summaries"]
        if not summary["pupil_availability"]["available"]
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
    assert "Population peri-event pupil-area difference" in svg
    assert "Population peri-event forward-running difference" in svg
    assert "Mouse-level pupil response-window effects" in svg
    assert "Mouse-level running response-window effects" in svg
    assert "insufficient tracking" in svg
    assert svg.count("<path ") >= 100
    assert svg.count("<circle ") >= 600

    assert 'id="modality-tabs"' in html
    assert 'id="cohort-tabs"' in html
    assert 'id="context-tabs"' in html
    assert 'id="event-select"' in html
    assert "Baseline change" in html
    assert "Raw signals" in html
    assert 'data-scope="population"' in html
    assert 'data-scope="mouse"' in html
    assert 'id="mouse-select"' in html
    assert 'id="pupil-trace-canvas"' in html
    assert 'id="running-trace-canvas"' in html
    assert 'id="pupil-effect-canvas"' in html
    assert 'id="running-effect-canvas"' in html
    assert 'cohort: "sequence"' in html
    assert 'mouseId: "830846"' in html
    assert "plus or minus one standard error" in html
    assert "no temporal filtering" in html
    assert "Matched control" in html
    assert "Static" in html
    assert "__PUPIL_EVENT_" not in html
