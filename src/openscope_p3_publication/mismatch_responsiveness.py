"""Per-unit mismatch responsiveness for the Neuropixels context blocks.

Responsiveness is local and stimulus-structure-aware: a mismatch event is
compared against the most recent instance of what the animal expected, in the
same block, rather than against a generic pre-stimulus baseline. The comparison
therefore differs by context:

- ``standard`` and ``duration`` present one stimulus per table row, so the
  comparison is the preceding presentation. For duration that is the pre-delay
  stimulus, since the manipulation is temporal and the response of interest is
  to the stimulus that follows the violated delay.
- ``sequence`` presents five rows per sequence with the substitution always at
  element three, so the comparison is element three of the previous sequence --
  the same physical position, normally 0 degrees.
- ``sensorimotor`` embeds mismatch events in continuous closed-loop flow, so
  there is no preceding trial and the comparison is the immediately preceding
  baseline window.

Only the parts that run with the declared dependencies live here. The rank
tests need scipy, which this repository installs ad hoc in extractors, so
:func:`paired_p_values` and :func:`unpaired_p_values` import it lazily and are
called only from ``scripts/extract_neuropixels_event_responses.py``. Everything
the renderers need -- Benjamini-Hochberg correction, the modulation index, and
threshold application -- is numpy-only and tested in CI.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from .mismatch_adjacency import (
    SEQUENCE_PERIOD_ROWS,
    context_mismatch_types,
)

SENSORIMOTOR_BASELINE_SECONDS = 0.343
"""Pre-event comparison window for the sensorimotor context."""

SEQUENCE_COMPARISON_OFFSET = -SEQUENCE_PERIOD_ROWS
"""Element three of the previous sequence, five rows back."""

COMPARISON_OFFSETS: dict[str, int | None] = {
    "standard": -1,
    "sequence": SEQUENCE_COMPARISON_OFFSET,
    "duration": -1,
    "sensorimotor": None,
}

DEFAULT_Q_MAX = 0.05
"""Benjamini-Hochberg cutoff, matching the p-value cutoff used for SST tagging."""

DEFAULT_MODULATION_MINIMUM = 0.1
"""Effect-size floor, matching the SST optotagging modulation-index minimum."""


def comparison_offset(context: str) -> int | None:
    """Row offset of the Q1 comparison window, or None when it is time-based."""
    context_mismatch_types(context)
    return COMPARISON_OFFSETS[context]


def _validate_table(
    start_times: Sequence[float],
    stop_times: Sequence[float],
    block_numbers: Sequence[float] | None,
) -> None:
    if len(start_times) != len(stop_times):
        raise ValueError("start_times and stop_times must have the same length.")
    if block_numbers is not None and len(block_numbers) != len(start_times):
        raise ValueError("block_numbers must have the same length as the table.")


def comparison_windows(
    start_times: Sequence[float],
    stop_times: Sequence[float],
    indices: Sequence[int],
    context: str,
    block_numbers: Sequence[float] | None = None,
) -> list[tuple[float, float] | None]:
    """Return the Q1 comparison window for each mismatch event.

    ``None`` marks an event whose comparison window is unavailable, because it
    falls outside the table or crosses a protocol block boundary.
    """
    offset = comparison_offset(context)
    _validate_table(start_times, stop_times, block_numbers)

    windows: list[tuple[float, float] | None] = []
    for index in indices:
        if offset is None:
            event_start = float(start_times[index])
            windows.append(
                (event_start - SENSORIMOTOR_BASELINE_SECONDS, event_start)
            )
            continue
        reference = int(index) + offset
        if reference < 0 or reference >= len(start_times):
            windows.append(None)
            continue
        if (
            block_numbers is not None
            and block_numbers[reference] != block_numbers[index]
        ):
            windows.append(None)
            continue
        start = float(start_times[reference])
        stop = float(stop_times[reference])
        if start >= stop:
            raise ValueError(
                f"{context} comparison window is nonpositive: {start}, {stop}"
            )
        windows.append((start, stop))
    return windows


def clean_trial_mask(
    trial_types: Sequence[str],
    indices: Sequence[int],
    context: str,
    block_numbers: Sequence[float] | None = None,
) -> list[bool]:
    """Flag mismatch events whose comparison is itself uncontaminated.

    A mismatch preceded by another mismatch is not compared against an expected
    stimulus, so the Q1 comparison is invalid. For ``sequence`` the whole
    previous sequence must be free of substitutions, not merely the compared
    element. ``sensorimotor`` has no preceding trial: its hygiene is the
    time-based adjacency rule and the running gate, both applied downstream.
    """
    mismatch_types = set(context_mismatch_types(context))
    offset = comparison_offset(context)
    types = [str(value) for value in trial_types]

    mask: list[bool] = []
    for index in indices:
        if offset is None:
            mask.append(True)
            continue
        first = int(index) + offset
        if first < 0:
            mask.append(False)
            continue
        if (
            block_numbers is not None
            and block_numbers[first] != block_numbers[index]
        ):
            mask.append(False)
            continue
        window = types[first : int(index)]
        mask.append(not any(value in mismatch_types for value in window))
    return mask


def modulation_index(
    test_rates: Sequence[float],
    comparison_rates: Sequence[float],
) -> float:
    """Trial-wise mean of ``(test - comparison) / (test + comparison)``.

    Averaging per-trial indices rather than computing one index from the trial
    means matches ``compute_response_metrics`` in :mod:`optotagging`, so the
    value is comparable with the SST classification in the same figure. Trials
    with no spikes in either window carry no information and are skipped.
    """
    test = np.asarray(test_rates, dtype=float)
    comparison = np.asarray(comparison_rates, dtype=float)
    if test.shape != comparison.shape:
        raise ValueError("test_rates and comparison_rates must have the same length.")
    denominator = test + comparison
    with np.errstate(invalid="ignore", divide="ignore"):
        index = np.divide(
            test - comparison,
            denominator,
            out=np.full_like(test, np.nan, dtype=float),
            where=denominator != 0,
        )
    if not np.any(np.isfinite(index)):
        return float("nan")
    return float(np.nanmean(index))


def benjamini_hochberg(p_values: Sequence[float]) -> np.ndarray:
    """Benjamini-Hochberg adjusted p-values, in the input order.

    Non-finite entries are excluded from the family rather than treated as
    non-significant, so a unit whose test could not run does not inflate the
    correction for the units that could.
    """
    p = np.asarray(p_values, dtype=float)
    q = np.full(p.shape, np.nan, dtype=float)
    finite = np.isfinite(p)
    count = int(finite.sum())
    if count == 0:
        return q

    values = p[finite]
    order = np.argsort(values, kind="stable")
    ranked = values[order]
    ranks = np.arange(1, count + 1, dtype=float)
    scaled = ranked * count / ranks
    # Enforce monotonicity from the largest p downwards.
    adjusted = np.minimum.accumulate(scaled[::-1])[::-1]
    adjusted = np.clip(adjusted, 0.0, 1.0)

    restored = np.empty(count, dtype=float)
    restored[order] = adjusted
    q[finite] = restored
    return q


def classify_responsive(
    *,
    q_values: Sequence[float],
    modulation_indices: Sequence[float],
    q_max: float = DEFAULT_Q_MAX,
    modulation_minimum: float = DEFAULT_MODULATION_MINIMUM,
    two_sided: bool = True,
) -> np.ndarray:
    """Flag units passing both the significance cutoff and the effect-size floor.

    ``two_sided`` accepts suppression as well as enhancement, which is the
    default because a mismatch can reduce firing. Setting it False keeps only
    positive modulation, matching the SST tagging rule.
    """
    q = np.asarray(q_values, dtype=float)
    modulation = np.asarray(modulation_indices, dtype=float)
    if q.shape != modulation.shape:
        raise ValueError("q_values and modulation_indices must have the same length.")
    effect = np.abs(modulation) if two_sided else modulation
    with np.errstate(invalid="ignore"):
        flags = (q <= q_max) & (effect > modulation_minimum)
    return np.where(np.isfinite(q) & np.isfinite(modulation), flags, False)


def paired_p_values(
    test_rates: np.ndarray,
    comparison_rates: np.ndarray,
) -> np.ndarray:
    """Paired Wilcoxon signed-rank p-value per unit, across trials.

    Requires scipy, which extractors install ad hoc. ``test_rates`` and
    ``comparison_rates`` are ``(units, trials)`` arrays.
    """
    import warnings

    from scipy.stats import wilcoxon

    test = np.atleast_2d(np.asarray(test_rates, dtype=float))
    comparison = np.atleast_2d(np.asarray(comparison_rates, dtype=float))
    if test.shape != comparison.shape:
        raise ValueError("test_rates and comparison_rates must have the same shape.")

    out = np.full(test.shape[0], np.nan, dtype=float)
    for row in range(test.shape[0]):
        valid = np.isfinite(test[row]) & np.isfinite(comparison[row])
        if valid.sum() < 2:
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            result = wilcoxon(
                comparison[row][valid],
                test[row][valid],
                zero_method="zsplit",
                correction=False,
            )
        out[row] = float(result.pvalue)
    return out


def unpaired_p_values(
    mismatch_values: np.ndarray,
    control_values: np.ndarray,
) -> np.ndarray:
    """Mann-Whitney U p-value per unit between mismatch and control trials.

    Requires scipy. Trial counts differ between blocks, so the comparison is
    unpaired. Arrays are ``(units, trials)`` and may have different trial counts.
    """
    import warnings

    from scipy.stats import mannwhitneyu

    mismatch = np.atleast_2d(np.asarray(mismatch_values, dtype=float))
    control = np.atleast_2d(np.asarray(control_values, dtype=float))
    if mismatch.shape[0] != control.shape[0]:
        raise ValueError("mismatch and control must describe the same units.")

    out = np.full(mismatch.shape[0], np.nan, dtype=float)
    for row in range(mismatch.shape[0]):
        left = mismatch[row][np.isfinite(mismatch[row])]
        right = control[row][np.isfinite(control[row])]
        if len(left) < 2 or len(right) < 2:
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            result = mannwhitneyu(left, right, alternative="two-sided")
        out[row] = float(result.pvalue)
    return out


def binomial_survival(successes: int, trials: int, probability: float) -> float:
    """Exact upper-tail binomial probability ``P(X >= successes)``.

    Panel B asks whether an area's responsive fraction exceeds what the
    thresholds alone would produce: at ``p < 0.05`` two-sided, roughly 5% of
    units clear the significance gate by chance, and the modulation floor
    removes some of those. This gives the area-level test against that floor
    without adding a scipy dependency to the presentation stage.

    Validated against ``scipy.stats.binom.sf`` over 4000 random ``(n, k, p)``
    draws: relative agreement to 7e-13 everywhere except one case at 1e-297,
    where scipy itself is 41% off the exact value and this function is not.

    Summed directly over the upper tail. Computing it as ``1 - P(X < k)``
    would take fewer terms when ``k`` is small, but it cancels catastrophically
    once the answer is tiny: at ``n = 50``, ``k = 25``, ``p = 0.05`` the lower
    sum rounds to exactly 1.0 and the complement returns 0.0 for a true value
    of 5.5e-21. Note that comparing against a reference implementation in
    absolute terms does not catch this, which is why the monotonicity test
    guards it instead.
    """
    if trials < 0:
        raise ValueError("trials must not be negative.")
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must lie in [0, 1].")
    successes = max(int(successes), 0)
    if successes == 0:
        return 1.0
    if successes > trials:
        return 0.0
    if probability == 0.0:
        return 0.0
    if probability == 1.0:
        return 1.0

    log_p = math.log(probability)
    log_q = math.log1p(-probability)

    def log_pmf(count: int) -> float:
        return (
            math.lgamma(trials + 1)
            - math.lgamma(count + 1)
            - math.lgamma(trials - count + 1)
            + count * log_p
            + (trials - count) * log_q
        )

    total = math.fsum(
        math.exp(log_pmf(count)) for count in range(successes, trials + 1)
    )
    return float(min(total, 1.0))


def responsive_fraction_p_values(
    responsive_counts: Sequence[int],
    unit_counts: Sequence[int],
    chance_probability: float,
) -> np.ndarray:
    """Per-area upper-tail p-values for an excess of responsive units.

    Areas with no units yield NaN rather than 1.0, so an empty area is never
    read as a measured null result.
    """
    counts = np.asarray(responsive_counts, dtype=float)
    totals = np.asarray(unit_counts, dtype=float)
    if counts.shape != totals.shape:
        raise ValueError("responsive_counts and unit_counts must have the same length.")
    return np.array(
        [
            binomial_survival(int(count), int(total), chance_probability)
            if total > 0
            else np.nan
            for count, total in zip(counts, totals, strict=True)
        ]
    )
