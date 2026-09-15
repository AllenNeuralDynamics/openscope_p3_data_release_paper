"""Tests for locomotion gating of sensorimotor mismatch trials."""

from __future__ import annotations

import numpy as np
import pytest

from openscope_p3_publication.sensorimotor_running import (
    BASELINE_SECONDS,
    DEFAULT_RUNNING_THRESHOLD_CM_S,
    MINIMUM_QUALIFYING_TRIALS,
    RUNNING_THRESHOLDS_CM_S,
    block_speed_summary,
    forward_speed,
    qualifying_trials,
    summarize_session,
    window_means,
)


def constant_series(speed: float, duration: float = 100.0, rate: float = 60.0):
    times = np.arange(0.0, duration, 1.0 / rate)
    return times, np.full(len(times), speed)


class TestForwardSpeed:
    def test_negative_velocity_is_clipped_to_zero(self):
        result = forward_speed(np.array([-5.0, 0.0, 3.0]))
        assert result.tolist() == [0.0, 0.0, 3.0]

    def test_nonfinite_samples_are_dropped_by_the_caller_not_clipped(self):
        result = forward_speed(np.array([np.nan, 2.0]))
        assert np.isnan(result[0])
        assert result[1] == 2.0


class TestWindowMeans:
    def test_constant_speed_recovers_that_speed(self):
        times, velocity = constant_series(12.0)
        means, counts = window_means(
            times, forward_speed(velocity), np.array([10.0]), np.array([10.35])
        )
        assert means[0] == pytest.approx(12.0)
        assert counts[0] > 0

    def test_sample_count_matches_the_window_length(self):
        times, velocity = constant_series(1.0)
        means, counts = window_means(
            times, forward_speed(velocity), np.array([10.0]), np.array([10.0 + 0.343])
        )
        # 0.343 s at 60 Hz is about 20 samples.
        assert 19 <= counts[0] <= 22

    def test_empty_window_yields_nan(self):
        times, velocity = constant_series(5.0, duration=10.0)
        means, counts = window_means(
            times, forward_speed(velocity), np.array([50.0]), np.array([50.1])
        )
        assert np.isnan(means[0])
        assert counts[0] == 0

    def test_windows_are_independent(self):
        times = np.arange(0.0, 10.0, 1 / 60)
        velocity = np.where(times < 5.0, 2.0, 20.0)
        means, _counts = window_means(
            times, forward_speed(velocity), np.array([1.0, 6.0]), np.array([2.0, 7.0])
        )
        assert means[0] == pytest.approx(2.0)
        assert means[1] == pytest.approx(20.0)

    def test_mismatched_lengths_raise(self):
        times, velocity = constant_series(1.0)
        with pytest.raises(ValueError, match="same length"):
            window_means(
                times, forward_speed(velocity), np.array([1.0, 2.0]), np.array([2.0])
            )


class TestQualifyingTrials:
    def test_both_windows_must_clear_the_threshold(self):
        pre = np.array([10.0, 10.0, 0.0, 0.0])
        event = np.array([10.0, 0.0, 10.0, 0.0])
        assert qualifying_trials(pre, event, 5.0).tolist() == [True, False, False, False]

    def test_threshold_is_inclusive(self):
        assert qualifying_trials(np.array([5.0]), np.array([5.0]), 5.0).tolist() == [True]

    def test_nan_never_qualifies(self):
        assert qualifying_trials(
            np.array([np.nan]), np.array([10.0]), 1.0
        ).tolist() == [False]

    def test_default_threshold_is_stricter_than_the_repository_floor(self):
        assert DEFAULT_RUNNING_THRESHOLD_CM_S == 5.0
        assert 1.0 in RUNNING_THRESHOLDS_CM_S
        assert DEFAULT_RUNNING_THRESHOLD_CM_S in RUNNING_THRESHOLDS_CM_S


class TestBlockSpeedSummary:
    def test_reports_mean_median_and_p90(self):
        forward = np.array([0.0, 0.0, 10.0, 20.0, 30.0])
        summary = block_speed_summary(forward, 1.0)
        assert summary["mean_cm_s"] == pytest.approx(12.0)
        assert summary["median_cm_s"] == pytest.approx(10.0)
        assert summary["p90_cm_s"] == pytest.approx(26.0)

    def test_running_fraction_uses_strict_comparison_like_running_statistics(self):
        # Matches extract_running_statistics.py, which counts forward > threshold.
        forward = np.array([1.0, 1.0, 2.0, 2.0])
        assert block_speed_summary(forward, 1.0)["running_fraction"] == pytest.approx(0.5)

    def test_empty_series_raises(self):
        with pytest.raises(ValueError, match="no finite"):
            block_speed_summary(np.array([]), 1.0)


class TestSummarizeSession:
    def _session(self, speed: float, n_trials: int = 8):
        times, velocity = constant_series(speed, duration=200.0)
        onsets = np.arange(20.0, 20.0 + n_trials * 10.0, 10.0)
        offsets = onsets + 0.350
        labels = ["motor_halt", "motor_omission"] * (n_trials // 2)
        return times, forward_speed(velocity), onsets, offsets, labels

    def test_fast_session_qualifies_every_trial(self):
        # Sixteen trials across two labels leaves eight per label, meeting the rule.
        times, forward, onsets, offsets, labels = self._session(30.0, n_trials=16)
        summary = summarize_session(times, forward, onsets, offsets, labels)
        at_five = summary["thresholds"]["5"]
        assert at_five["qualifying_trials"] == len(onsets)
        assert at_five["minimum_per_label"] == 8
        assert at_five["available"] is True

    def test_stationary_session_qualifies_nothing(self):
        times, forward, onsets, offsets, labels = self._session(0.0)
        summary = summarize_session(times, forward, onsets, offsets, labels)
        assert summary["thresholds"]["1"]["qualifying_trials"] == 0
        assert summary["thresholds"]["1"]["available"] is False

    def test_minimum_per_label_is_reported(self):
        times, forward, onsets, offsets, labels = self._session(30.0, n_trials=8)
        summary = summarize_session(times, forward, onsets, offsets, labels)
        at_five = summary["thresholds"]["5"]
        assert at_five["minimum_per_label"] == 4
        assert set(at_five["per_label"]) == {"motor_halt", "motor_omission"}

    def test_availability_follows_the_minimum_trial_rule(self):
        times, forward, onsets, offsets, labels = self._session(30.0, n_trials=4)
        summary = summarize_session(times, forward, onsets, offsets, labels)
        # Four trials split across two labels leaves two per label, below the rule.
        assert MINIMUM_QUALIFYING_TRIALS == 8
        assert summary["thresholds"]["5"]["minimum_per_label"] == 2
        assert summary["thresholds"]["5"]["available"] is False

    def test_baseline_window_precedes_the_onset(self):
        assert BASELINE_SECONDS == pytest.approx(0.343)
        times = np.arange(0.0, 60.0, 1 / 60)
        # Running only before the event: the gate must still fail.
        velocity = np.where(times < 20.0, 30.0, 0.0)
        onsets = np.array([20.0])
        summary = summarize_session(
            times, forward_speed(velocity), onsets, onsets + 0.350, ["motor_halt"]
        )
        assert summary["thresholds"]["5"]["qualifying_trials"] == 0

    def test_label_count_must_match_trial_count(self):
        times, forward, onsets, offsets, _labels = self._session(10.0)
        with pytest.raises(ValueError, match="same length"):
            summarize_session(times, forward, onsets, offsets, ["motor_halt"])


class TestBlockWindow:
    def _series(self):
        times = np.arange(0.0, 100.0, 1 / 60)
        # Stationary for the first half of the block, running for the second.
        velocity = np.where(times < 50.0, 0.0, 20.0)
        return times, forward_speed(velocity)

    def test_explicit_block_window_is_honoured(self):
        times, forward = self._series()
        onsets = np.array([60.0, 70.0, 80.0])
        summary = summarize_session(
            times,
            forward,
            onsets,
            onsets + 0.35,
            ["motor_halt"] * 3,
            block_window=(0.0, 100.0),
        )
        # Averaged over the whole block, half of which was stationary.
        assert summary["block"]["mean_cm_s"] == pytest.approx(10.0, abs=0.2)
        assert summary["block_window_seconds"] == [0.0, 100.0]

    def test_inferred_window_spans_only_the_mismatch_events(self):
        times, forward = self._series()
        onsets = np.array([60.0, 70.0, 80.0])
        summary = summarize_session(
            times, forward, onsets, onsets + 0.35, ["motor_halt"] * 3
        )
        # Inferred from the events, all of which fall in the running half.
        assert summary["block"]["mean_cm_s"] == pytest.approx(20.0, abs=0.2)

    def test_the_two_windows_disagree_which_is_why_it_is_explicit(self):
        times, forward = self._series()
        onsets = np.array([60.0, 70.0, 80.0])
        explicit = summarize_session(
            times, forward, onsets, onsets + 0.35, ["motor_halt"] * 3,
            block_window=(0.0, 100.0),
        )["block"]["mean_cm_s"]
        inferred = summarize_session(
            times, forward, onsets, onsets + 0.35, ["motor_halt"] * 3
        )["block"]["mean_cm_s"]
        assert explicit != pytest.approx(inferred)
