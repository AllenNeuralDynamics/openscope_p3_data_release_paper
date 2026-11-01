"""Wide-window alignment must not change the frozen central activity."""

from __future__ import annotations

import numpy as np
import pytest

from openscope_p3_publication.standard_oddball_examples import trial_mean_sdf
from openscope_p3_publication.standard_oddball_explorer_window import (
    average_recorded,
    verify_central,
    wide_native_trial,
    wide_sdf,
)


def test_wide_sdf_matches_frozen_central_smoothing() -> None:
    spikes = np.array([-1.46, -0.85, -0.72, -0.5, 0.1, 0.3, 0.74, 1.0, 1.4, 10.2, 10.4])
    onsets = np.array([0.0, 10.0])
    time, mean = wide_sdf(spikes, onsets)
    assert len(time) == len(mean) == 600
    assert time[0] == -1.4975
    assert time[-1] == 1.4975
    central_trials = [
        (spikes[(spikes >= onset - 0.995) & (spikes < onset + 0.75)] - onset).tolist()
        for onset in onsets
    ]
    reference = trial_mean_sdf(central_trials, bin_seconds=0.005, tau_seconds=0.025)
    verify_central(time, mean, -0.75 + (np.arange(300) + 0.5) * 0.005, reference)
    np.testing.assert_allclose(mean[150:450], reference, atol=1e-12, rtol=0)
    assert np.any(mean[:150] > 0) and np.any(mean[450:] > 0)


def test_native_display_masks_pauses_not_recorded_samples() -> None:
    times = np.array([0, 0.1, 0.2, 1, 1.1, 1.2])
    values = times[:, None] * 2
    time = np.array([0.05, 0.15, 0.5, 1.05, 1.15, 1.3])
    displayed = wide_native_trial(times, values, 0, time)
    np.testing.assert_allclose(displayed[0, [0, 1, 3, 4]], [0.1, 0.3, 2.1, 2.3])
    assert np.isnan(displayed[0, 2]) and np.isnan(displayed[0, 5])


def test_preserve_trials_with_explicit_recorded_counts() -> None:
    trials = np.array([[[1, 2], [np.nan, 4]]], dtype=np.float32)
    mean, counts = average_recorded(trials)
    np.testing.assert_array_equal(mean, [[1, 3]])
    np.testing.assert_array_equal(counts, [[1, 2]])
    assert mean.dtype == np.float32
    with pytest.raises(ValueError, match="entirely unobserved"):
        average_recorded(np.array([[[np.nan, 2], [np.nan, 4]]]))
