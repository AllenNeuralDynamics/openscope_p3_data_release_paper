"""Tests for per-unit mismatch responsiveness.

Covers the parts that run with the declared dependencies: the context-specific
comparison windows, the trial-hygiene masks, the modulation index, Benjamini-
Hochberg correction, and responsiveness classification. The rank tests
themselves live behind a lazy scipy import used only by the extractor.
"""

from __future__ import annotations

import numpy as np
import pytest

from openscope_p3_publication.mismatch_responsiveness import (
    DEFAULT_MODULATION_MINIMUM,
    DEFAULT_Q_MAX,
    SEQUENCE_COMPARISON_OFFSET,
    benjamini_hochberg,
    binomial_survival,
    classify_responsive,
    clean_trial_mask,
    comparison_offset,
    comparison_windows,
    modulation_index,
    responsive_fraction_p_values,
)


class TestComparisonOffsets:
    def test_standard_and_duration_compare_with_the_previous_presentation(self):
        assert comparison_offset("standard") == -1
        assert comparison_offset("duration") == -1

    def test_sequence_compares_with_the_previous_sequence(self):
        assert comparison_offset("sequence") == -5
        assert SEQUENCE_COMPARISON_OFFSET == -5

    def test_sensorimotor_has_no_row_offset(self):
        assert comparison_offset("sensorimotor") is None

    def test_unknown_context_raises(self):
        with pytest.raises(ValueError, match="Unknown"):
            comparison_offset("nonsense")


class TestComparisonWindows:
    def _rows(self, n: int, duration: float, period: float):
        starts = [i * period for i in range(n)]
        stops = [s + duration for s in starts]
        return starts, stops, [2.0] * n

    def test_standard_uses_the_previous_presentation_window(self):
        starts, stops, blocks = self._rows(10, 0.367, 0.686)
        windows = comparison_windows(starts, stops, [5], "standard", blocks)
        assert windows == [(starts[4], stops[4])]

    def test_duration_uses_the_pre_delay_stimulus(self):
        starts, stops, blocks = self._rows(10, 0.367, 0.686)
        windows = comparison_windows(starts, stops, [5], "duration", blocks)
        assert windows == [(starts[4], stops[4])]

    def test_sequence_reaches_five_rows_back(self):
        starts, stops, blocks = self._rows(20, 0.2669, 0.2669)
        windows = comparison_windows(starts, stops, [12], "sequence", blocks)
        assert windows == [(starts[7], stops[7])]

    def test_sensorimotor_uses_the_preceding_baseline(self):
        starts, stops, blocks = self._rows(10, 0.350, 8.0)
        windows = comparison_windows(starts, stops, [5], "sensorimotor", blocks)
        assert windows[0] == pytest.approx((starts[5] - 0.343, starts[5]))

    def test_windows_outside_the_table_are_none(self):
        starts, stops, blocks = self._rows(20, 0.2669, 0.2669)
        assert comparison_windows(starts, stops, [3], "sequence", blocks) == [None]

    def test_block_boundaries_are_respected(self):
        starts, stops, blocks = self._rows(20, 0.2669, 0.2669)
        blocks = [2.0] * 10 + [3.0] * 10
        assert comparison_windows(starts, stops, [11], "sequence", blocks) == [None]

    def test_mismatched_lengths_raise(self):
        with pytest.raises(ValueError, match="same length"):
            comparison_windows([0.0, 1.0], [0.5], [1], "standard", [2.0, 2.0])


class TestCleanTrialMask:
    def test_standard_excludes_a_deviant_preceded_by_a_deviant(self):
        trial_types = ["standard"] * 12
        trial_types[5] = "halt"
        trial_types[6] = "omission"
        mask = clean_trial_mask(trial_types, [5, 6], "standard", [2.0] * 12)
        assert mask == [True, False]

    def test_sequence_excludes_a_substitution_after_a_substitution(self):
        # Five rows per sequence, substitution at element three.
        trial_types = ["standard"] * 40
        for row in (7, 12):
            trial_types[row] = "halt"
        mask = clean_trial_mask(trial_types, [7, 12], "sequence", [2.0] * 40)
        assert mask == [True, False]

    def test_sequence_keeps_substitutions_two_sequences_apart(self):
        trial_types = ["standard"] * 40
        for row in (7, 17):
            trial_types[row] = "halt"
        mask = clean_trial_mask(trial_types, [7, 17], "sequence", [2.0] * 40)
        assert mask == [True, True]

    def test_duration_excludes_consecutive_deviants(self):
        trial_types = ["standard"] * 12
        trial_types[5] = "jitter"
        trial_types[6] = "jitter"
        mask = clean_trial_mask(trial_types, [5, 6], "duration", [2.0] * 12)
        assert mask == [True, False]

    def test_sensorimotor_keeps_every_trial_at_this_stage(self):
        # Sensorimotor hygiene is time-based and running-based, applied later.
        trial_types = ["standard"] * 200
        trial_types[10] = "motor_halt"
        trial_types[23] = "motor_omission"
        mask = clean_trial_mask(
            trial_types, [10, 23], "sensorimotor", [2.0] * 200
        )
        assert mask == [True, True]

    def test_trials_without_a_reference_are_excluded(self):
        trial_types = ["standard"] * 40
        trial_types[2] = "halt"
        assert clean_trial_mask(trial_types, [2], "sequence", [2.0] * 40) == [False]


class TestModulationIndex:
    def test_no_change_is_zero(self):
        assert modulation_index([10.0, 10.0], [10.0, 10.0]) == pytest.approx(0.0)

    def test_pure_increase_approaches_one(self):
        assert modulation_index([10.0], [0.0]) == pytest.approx(1.0)

    def test_pure_decrease_approaches_minus_one(self):
        assert modulation_index([0.0], [10.0]) == pytest.approx(-1.0)

    def test_averaged_across_trials_not_computed_from_means(self):
        # Matches compute_response_metrics: mean of per-trial indices.
        value = modulation_index([10.0, 1.0], [0.0, 1.0])
        assert value == pytest.approx(0.5)

    def test_trials_with_no_spikes_in_either_window_are_ignored(self):
        assert modulation_index([0.0, 10.0], [0.0, 0.0]) == pytest.approx(1.0)

    def test_all_empty_trials_give_nan(self):
        assert np.isnan(modulation_index([0.0, 0.0], [0.0, 0.0]))

    def test_mismatched_lengths_raise(self):
        with pytest.raises(ValueError, match="same length"):
            modulation_index([1.0, 2.0], [1.0])


class TestBenjaminiHochberg:
    def test_uniform_ramp_maps_to_the_same_q(self):
        q = benjamini_hochberg([0.01, 0.02, 0.03, 0.04, 0.05])
        assert q == pytest.approx([0.05] * 5)

    def test_single_strong_result_survives(self):
        q = benjamini_hochberg([0.001, 0.5])
        assert q == pytest.approx([0.002, 0.5])

    def test_q_is_never_below_p(self):
        p = np.array([0.001, 0.01, 0.2, 0.9])
        assert np.all(benjamini_hochberg(p) >= p)

    def test_q_is_monotonic_in_sorted_p(self):
        p = np.array([0.04, 0.001, 0.3, 0.02, 0.9])
        q = benjamini_hochberg(p)
        order = np.argsort(p)
        assert np.all(np.diff(q[order]) >= -1e-12)

    def test_q_is_capped_at_one(self):
        assert np.all(benjamini_hochberg([0.6, 0.7, 0.8, 0.9]) <= 1.0)

    def test_order_is_preserved(self):
        q = benjamini_hochberg([0.5, 0.001])
        assert q[1] < q[0]

    def test_nonfinite_p_values_are_excluded_from_the_family(self):
        q = benjamini_hochberg([0.01, np.nan, 0.02])
        assert np.isnan(q[1])
        # The family size is two, not three.
        assert q[0] == pytest.approx(0.02)

    def test_empty_input_returns_empty(self):
        assert benjamini_hochberg([]).size == 0


class TestClassifyResponsive:
    def test_requires_both_significance_and_effect_size(self):
        flags = classify_responsive(
            q_values=[0.01, 0.01, 0.20, 0.20],
            modulation_indices=[0.5, 0.01, 0.5, 0.01],
        )
        assert flags.tolist() == [True, False, False, False]

    def test_thresholds_are_inclusive_on_q_and_exclusive_on_effect(self):
        assert classify_responsive(
            q_values=[DEFAULT_Q_MAX], modulation_indices=[0.5]
        ).tolist() == [True]
        assert classify_responsive(
            q_values=[0.01], modulation_indices=[DEFAULT_MODULATION_MINIMUM]
        ).tolist() == [False]

    def test_negative_modulation_counts_when_two_sided(self):
        flags = classify_responsive(
            q_values=[0.01], modulation_indices=[-0.5], two_sided=True
        )
        assert flags.tolist() == [True]

    def test_negative_modulation_is_rejected_when_one_sided(self):
        flags = classify_responsive(
            q_values=[0.01], modulation_indices=[-0.5], two_sided=False
        )
        assert flags.tolist() == [False]

    def test_nonfinite_values_are_not_responsive(self):
        flags = classify_responsive(
            q_values=[np.nan, 0.01], modulation_indices=[0.5, np.nan]
        )
        assert flags.tolist() == [False, False]

    def test_default_thresholds_match_the_house_convention(self):
        # The SST classification in this figure uses p < 0.05 and MI > 0.1.
        assert DEFAULT_Q_MAX == 0.05
        assert DEFAULT_MODULATION_MINIMUM == 0.1


class TestBinomialSurvival:
    """Reimplemented here because the presentation stage declares only numpy.

    Validated against scipy.stats.binom.sf and against exact mpmath sums over
    4000 random cases; see the function docstring.
    """

    def test_every_outcome_is_at_least_one_success(self):
        assert binomial_survival(0, 10, 0.05) == 1.0

    def test_more_successes_than_trials_is_impossible(self):
        assert binomial_survival(11, 10, 0.05) == 0.0

    def test_a_fair_coin_splits_around_the_middle(self):
        assert binomial_survival(1, 2, 0.5) == pytest.approx(0.75)
        assert binomial_survival(2, 2, 0.5) == pytest.approx(0.25)

    def test_a_known_small_case(self):
        # P(X >= 2) for n=3, p=0.5 is 4/8.
        assert binomial_survival(2, 3, 0.5) == pytest.approx(0.5)

    def test_the_chance_floor_is_not_significant(self):
        # 5 of 100 responsive is exactly the chance expectation at p < 0.05.
        assert binomial_survival(5, 100, 0.05) > 0.4

    def test_a_clear_excess_is_significant(self):
        # 35 of 100 is the signal level measured in these blocks.
        assert binomial_survival(35, 100, 0.05) == pytest.approx(2.387e-14, rel=1e-3)

    def test_the_far_upper_tail_underflows_to_zero_not_to_a_negative(self):
        assert binomial_survival(500, 500, 0.05) == 0.0

    def test_the_deep_tail_is_not_lost_to_cancellation(self):
        # A complement-based implementation returns 0.0 here.
        assert binomial_survival(25, 50, 0.05) == pytest.approx(5.547e-21, rel=1e-3)

    def test_probability_is_monotonic_in_the_count(self):
        values = [binomial_survival(count, 50, 0.05) for count in range(51)]
        pairs = zip(values, values[1:], strict=False)
        assert all(later <= earlier for earlier, later in pairs)

    def test_degenerate_probabilities(self):
        assert binomial_survival(1, 10, 0.0) == 0.0
        assert binomial_survival(10, 10, 1.0) == 1.0

    def test_no_trials_means_no_successes(self):
        assert binomial_survival(1, 0, 0.05) == 0.0

    def test_an_invalid_probability_raises(self):
        with pytest.raises(ValueError, match="probability"):
            binomial_survival(1, 10, 1.5)

    def test_negative_trials_raise(self):
        with pytest.raises(ValueError, match="negative"):
            binomial_survival(1, -1, 0.05)


class TestResponsiveFractionPValues:
    def test_one_p_value_per_area(self):
        p = responsive_fraction_p_values([12, 3, 40], [100, 100, 100], 0.05)
        assert p.shape == (3,)
        assert p[2] < p[0] < p[1]

    def test_an_empty_area_is_not_a_measured_null(self):
        p = responsive_fraction_p_values([0, 12], [0, 100], 0.05)
        assert np.isnan(p[0])
        assert p[1] < 0.01

    def test_mismatched_lengths_raise(self):
        with pytest.raises(ValueError, match="same length"):
            responsive_fraction_p_values([1, 2], [10], 0.05)
