import numpy as np
import pandas as pd
import pytest

from openscope_p3_publication import mesoscope_standard_oddball
from openscope_p3_publication.ephys_c1_pseudocontext import (
    EVENT,
    assign_regions,
    load_pseudo,
    pseudo_statistics,
    pseudo_windows,
    summarize_pseudo,
)


def tables():
    types = ["single", "single", "single", "halt", "omission"]
    orientations = [0, np.pi / 2, np.pi / 4, 0, 0]
    return {
        "context": {
            "start": np.arange(10.0, 15.0), "stop": np.arange(10.5, 15.5),
            "trial_type": np.array(["standard", "orientation_90", "orientation_45",
                                    "halt", "omission"]),
            "orientation": np.array(orientations), "delay": np.zeros(5),
            "block_number": np.zeros(5),
        },
        "control": {
            "start": np.r_[np.arange(0.0, 5.0), np.arange(20.0, 25.0)],
            "stop": np.r_[np.arange(0.5, 5.5), np.arange(20.5, 25.5)],
            "trial_type": np.array(types * 2), "orientation": np.array(orientations * 2),
            "delay": np.zeros(10), "block_number": np.repeat([1.0, 2.0], 5),
        },
    }


def repeated_tables():
    result = tables()
    control = result["control"]
    for key in control:
        control[key] = np.tile(control[key], 2)
    control["start"][10:] += 30
    control["stop"][10:] += 30
    # Keep both early repeats before the real context.
    result["context"]["start"] += 30
    result["context"]["stop"] += 30
    control["start"] = np.r_[np.arange(0.0, 10.0), np.arange(60.0, 70.0)]
    control["stop"] = control["start"] + 0.5
    control["block_number"] = np.repeat([1.0, 2.0], 10)
    return result


def test_pseudo_windows_selects_post_not_actual_context():
    windows, audit = pseudo_windows(repeated_tables())
    assert audit["post_indices"] == [11, 16]
    assert audit["pre_indices"] == [1, 6]
    assert audit["predecessor_trial_types"] == {"single": 2}
    assert windows["context_test"] == [(61.0, 61.5), (66.0, 66.5)]
    assert windows["context_comparison"] == [(60.0, 60.5), (65.0, 65.5)]
    assert windows["control_test"] == [(1.0, 1.5), (6.0, 6.5)]
    assert windows["context_baseline"] == [(60.5, 61.0), (65.5, 66.0)]


def test_pseudo_windows_rejects_too_few_valid_post_predecessors():
    data = repeated_tables()
    data["control"]["block_number"][11] = 3
    with pytest.raises(ValueError, match="two valid post-C1"):
        pseudo_windows(data)


def test_pseudo_windows_records_boundary_exclusion_without_filtering_pre_pool():
    data = repeated_tables()
    data["control"]["block_number"][11] = 3
    data["control"]["trial_type"][18] = "single"
    data["control"]["orientation"][18] = np.pi / 2
    _, audit = pseudo_windows(data)
    assert audit["post_indices"] == [16, 18]
    assert audit["pre_indices"] == [1, 6]
    assert audit["excluded_post"] == [
        {"index": 11, "reason": "missing_or_cross_block_predecessor"},
    ]


def test_pseudo_statistics_recomputes_q1_in_post_and_subtracts_q2_baseline():
    n = 30
    arrays = {
        "context_test": np.full((2, n), 10.0),
        "context_comparison": np.full((2, n), 1.0),
        "context_baseline": np.array([np.full(n, 9.0), np.full(n, 0.0)]),
        "control_test": np.full((2, n), 1.0),
        "control_baseline": np.zeros((2, n)),
    }
    stats = pseudo_statistics(arrays)
    assert stats.q1_responsive.tolist() == [True, True]
    assert stats.q2_responsive.tolist() == [False, True]
    assert stats.joint_responsive.tolist() == [False, True]
    assert stats.q2_mi.iloc[0] == 0
    with pytest.raises(ValueError, match="exactly"):
        pseudo_statistics({**arrays, "control_post_test": arrays["context_test"]})


def test_pseudo_response_screen_uses_strict_thresholds_and_finite_statistics(monkeypatch):
    statistics = pd.DataFrame({
        "q1_p": [0.049, 0.05, 0.01, np.nan, 0.01],
        "q1_mi": [0.101, 0.5, 0.1, 0.5, -0.5],
        "q2_p": [0.01] * 5, "q2_mi": [0.5] * 5,
    })
    monkeypatch.setattr(
        mesoscope_standard_oddball, "response_statistics",
        lambda collected, clean: statistics.copy(),
    )
    arrays = {
        key: np.ones((5, 2)) for key in (
            "context_test", "context_comparison", "context_baseline",
            "control_test", "control_baseline",
        )
    }
    result = pseudo_statistics(arrays)
    assert result.q1_responsive.tolist() == [True, False, False, False, True]
    assert result.joint_responsive.tolist() == [True, False, False, False, True]
    assert result.joint_testable.tolist() == [True, True, True, False, True]


def test_summary_preserves_qc_gate_and_joint_denominator():
    units = pd.DataFrame({
        "session_id": ["s"] * 20, "subject_id": ["m"] * 20,
        "asset_id": ["a"] * 20, "nwb_unit_id": np.arange(20), "event_id": [EVENT] * 20,
        "brain_division": ["Isocortex"] * 20, "brain_area": ["VISp"] * 20,
        "qc_pass": [True] * 20, "decoder_label": ["sua"] * 20,
        "probe_excluded": [False] * 20, "eligible": [True] * 20,
        "q1_testable": [True] * 20, "q2_testable": [True] * 19 + [False],
        "joint_testable": [True] * 19 + [False], "q1_responsive": [True] * 20,
        "q2_responsive": [True] * 5 + [False] * 15,
        "joint_responsive": [True] * 5 + [False] * 15,
    })
    sessions, areas = summarize_pseudo(units)
    assert sessions.included.all()
    assert areas.n_joint_testable.iloc[0] == 19
    assert areas.n_q1_responsive.iloc[0] == 19
    assert areas.n_q2_responsive.iloc[0] == 5
    assert areas.n_joint_responsive.iloc[0] == 5
    assert areas.fraction_joint_responsive.iloc[0] == 5 / 19
    with pytest.raises(ValueError, match="inclusion gate"):
        summarize_pseudo(units.iloc[:19])


def test_region_assignment_matches_figure9():
    units = pd.DataFrame({
        "brain_division": ["Isocortex", "TH", "Isocortex", "HPF", "STR", "TH"],
        "brain_area": ["VISp", "LGd", "MOs", "CA1", "CP", "LP"],
    })
    assert assign_regions(units).iloc[:5].tolist() == [
        "VISp", "LGd", "Frontal", "Hippocampus", "STR",
    ]
    assert pd.isna(assign_regions(units).iloc[5])


def test_frozen_ephys_pseudo_context_counts_and_source_replay():
    units, areas, provenance = load_pseudo()
    assert provenance["session_count"] == 13
    assert provenance["unit_count"] == len(units) == 41809
    assert provenance["partial_cohort"] is False
    assert all(session["matches_original_spikes"] for session in provenance["sessions"])
    for session in provenance["sessions"]:
        assert len(session["trials"]["pre_indices"]) == 34
        assert len(session["trials"]["post_indices"]) == 34
    for screen in ("q1", "q2"):
        expected = (
            np.isfinite(units[f"{screen}_p"]) & np.isfinite(units[f"{screen}_mi"])
            & units[f"{screen}_p"].lt(0.05) & units[f"{screen}_mi"].abs().gt(0.1)
        )
        pd.testing.assert_series_equal(
            units[f"{screen}_responsive"], expected, check_names=False,
        )
    assert units.joint_testable.eq(units.q1_testable & units.q2_testable).all()
    assert units.joint_responsive.eq(units.q1_responsive & units.q2_responsive).all()
    assert areas.n_joint_testable.sum() == 6642
    assert areas.n_q1_responsive.sum() == 619
    assert areas.n_q2_responsive.sum() == 693
    assert areas.n_joint_responsive.sum() == 140
    assert areas.n_joint_responsive.tolist() == [42, 51, 12, 6, 13, 4, 10, 2]
