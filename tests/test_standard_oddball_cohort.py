import numpy as np
import pandas as pd
import pytest

from openscope_p3_publication.mesoscope_standard_oddball import signal_statistics
from openscope_p3_publication.mesoscope_standard_oddball_cohort_figure import (
    prepare_cohort_panel as prepare_mesoscope_panel,
)
from openscope_p3_publication.standard_oddball_cohort import (
    classify_units,
    response_statistics,
    split_control_repeats,
    summarize_units,
)
from openscope_p3_publication.standard_oddball_cohort_figure import (
    prepare_cohort_panel as prepare_neuropixels_panel,
)


def test_split_control_repeats_uses_context_bounds_and_covers_all_rows():
    repeats = split_control_repeats(
        context_start=np.array([10.0, 20.0]),
        context_stop=np.array([15.0, 25.0]),
        control_start=np.array([0.0, 5.0, 25.0, 30.0]),
        control_stop=np.array([2.0, 10.0, 27.0, 35.0]),
    )

    np.testing.assert_array_equal(repeats["pre"], [True, True, False, False])
    np.testing.assert_array_equal(repeats["post"], [False, False, True, True])
    assert np.all(repeats["pre"] ^ repeats["post"])


@pytest.mark.parametrize(
    ("control_start", "control_stop"),
    [
        ([0.0, 15.0, 25.0], [2.0, 18.0, 27.0]),
        ([0.0, 8.0, 25.0], [2.0, 12.0, 27.0]),
    ],
)
def test_split_control_repeats_rejects_context_overlap(control_start, control_stop):
    with pytest.raises(ValueError, match="both flanking C1 repeats"):
        split_control_repeats(
            context_start=np.array([10.0]),
            context_stop=np.array([25.0]),
            control_start=np.asarray(control_start),
            control_stop=np.asarray(control_stop),
        )


def test_split_control_repeats_rejects_missing_repeat():
    with pytest.raises(ValueError, match="both flanking C1 repeats"):
        split_control_repeats(
            context_start=np.array([10.0]),
            context_stop=np.array([25.0]),
            control_start=np.array([0.0, 5.0]),
            control_stop=np.array([2.0, 8.0]),
        )


def test_split_control_repeats_rejects_invalid_intervals():
    with pytest.raises(ValueError, match="aligned finite positive"):
        split_control_repeats(
            context_start=np.array([10.0]),
            context_stop=np.array([25.0]),
            control_start=np.array([0.0, np.nan]),
            control_stop=np.array([2.0, 8.0]),
        )


def test_repeat_statistics_preserve_pooled_q2_and_compute_independent_sensitivity_tests():
    pooled = {
        "context_test": np.array([[8.0, 9.0, 7.0, 8.0], [1.0, 1.0, 1.0, 1.0]]),
        "context_comparison": np.array([[2.0, 3.0, 2.0, 3.0], [1.0, 1.0, 1.0, 1.0]]),
        "context_baseline": np.zeros((2, 4)),
        "control_test": np.array([[3.0, 4.0, 2.0, 3.0], [1.0, 1.0, 1.0, 1.0]]),
        "control_baseline": np.zeros((2, 4)),
    }
    with_repeats = {
        **pooled,
        "control_pre_test": pooled["control_test"][:, :2],
        "control_pre_baseline": pooled["control_baseline"][:, :2],
        "control_post_test": pooled["control_test"][:, 2:],
        "control_post_baseline": pooled["control_baseline"][:, 2:],
    }

    pooled_result = response_statistics(pooled, [True] * 4)
    repeat_result = response_statistics(with_repeats, [True] * 4)

    for column in pooled_result:
        np.testing.assert_array_equal(repeat_result[column], pooled_result[column])
    assert {"q2_pre_p", "q2_post_p", "q2_pre_mi", "q2_post_mi"} <= set(repeat_result)
    optical = signal_statistics(with_repeats)
    assert {"q2_pre_testable", "q2_post_testable", "joint_pre_testable"} <= set(optical)
    np.testing.assert_array_equal(optical.q2_p, signal_statistics(pooled).q2_p)


def test_repeat_classification_and_summary_keep_separate_testable_denominators():
    frame = pd.DataFrame({
        "amplitude_cutoff": [0.05, 0.05], "isi_violations_ratio": [0.1, 0.1],
        "presence_ratio": [0.9, 0.9], "decoder_label": ["sua", "sua"],
        "firing_rate": [2.0, 2.0], "probe": ["ProbeA", "ProbeB"], "session_id": ["s", "s"],
        "subject_id": ["m", "m"], "event_id": ["orientation_90"] * 2,
        "brain_division": ["Isocortex"] * 2, "brain_area": ["VISp"] * 2,
        "q1_p": [0.01, np.nan], "q1_mi": [0.2, np.nan],
        "q2_p": [0.01, 0.01], "q2_mi": [0.2, 0.2],
        "q2_pre_p": [0.01, 0.01], "q2_pre_mi": [0.2, 0.2],
        "q2_post_p": [0.01, np.nan], "q2_post_mi": [0.2, np.nan],
    })

    classified = classify_units(frame)
    summary = summarize_units(classified, "session").iloc[0]

    assert summary.n_joint_testable == 1
    assert summary.n_joint_pre_testable == 1
    assert summary.n_joint_post_testable == 1
    assert summary.n_positive_joint_pre == 1
    assert summary.n_positive_joint_post == 1


def test_neuropixels_panel_uses_repeat_response_flags():
    pre = np.arange(20) < 5
    post = np.arange(20) < 7
    units = pd.DataFrame({
        "session_id": ["s"] * 20, "subject_id": ["m"] * 20, "asset_id": ["a"] * 20,
        "nwb_unit_id": np.arange(20), "event_id": ["orientation_90"] * 20,
        "brain_division": ["Isocortex"] * 20, "brain_area": ["VISp"] * 20,
        "qc_pass": [True] * 20, "decoder_label": ["sua"] * 20,
        "probe_excluded": [False] * 20, "eligible": [True] * 20,
        "joint_testable": [True] * 20, "q1_responsive": [True] * 20,
        "q2_responsive": [True] * 20, "joint_responsive": [True] * 20,
        "joint_pre_testable": [True] * 20, "q2_pre_responsive": pre,
        "joint_pre_responsive": pre, "joint_post_testable": [True] * 20,
        "q2_post_responsive": post, "joint_post_responsive": post,
    })

    areas = prepare_neuropixels_panel(units, event="orientation_90")["areas"]

    assert areas.loc[0, "n_q2_responsive_pre"] == 5
    assert areas.loc[0, "n_q2_responsive_post"] == 7


def test_mesoscope_panel_uses_repeat_response_flags():
    pre = np.arange(20) < 5
    post = np.arange(20) < 7
    units = pd.DataFrame({
        "session_id": ["s"] * 20, "subject_id": ["m"] * 20, "asset_id": ["a"] * 20,
        "plane": ["VISp_0"] * 20, "roi_id": np.arange(20), "area": ["VISp"] * 20,
        "event_id": ["orientation_90"] * 20, "signal": ["dff"] * 20,
        "is_soma": [True] * 20, "eligible": [True] * 20,
        "q1_testable": [True] * 20, "q2_testable": [True] * 20,
        "joint_testable": [True] * 20, "q1_responsive": [True] * 20,
        "q2_responsive": [True] * 20, "joint_responsive": [True] * 20,
        "joint_pre_testable": [True] * 20, "q2_pre_responsive": pre,
        "joint_pre_responsive": pre, "joint_post_testable": [True] * 20,
        "q2_post_responsive": post, "joint_post_responsive": post,
    })

    areas = prepare_mesoscope_panel(units)["areas"]

    assert areas.loc[0, "n_q2_responsive_pre"] == 5
    assert areas.loc[0, "n_q2_responsive_post"] == 7
