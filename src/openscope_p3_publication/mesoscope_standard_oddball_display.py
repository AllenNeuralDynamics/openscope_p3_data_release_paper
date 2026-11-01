"""Display-example selection rules, independent of frozen population classifications."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .mesoscope_standard_oddball import matched_examples

PANEL_A_DFF_PEAK_THRESHOLD = 0.5


def context_dff_peaks(arrays: dict) -> np.ndarray:
    """Peak trial-averaged baseline-subtracted ΔF/F in the half-open 0–500-ms window."""
    time = np.asarray(arrays["time"])
    response = (time >= 0) & (time < 0.5)
    if not response.any():
        raise ValueError("Panel A peak selection requires display samples in [0, 0.5) s.")
    values = arrays["delta_dff"][0][:, response]
    if not np.isfinite(values).all():
        raise ValueError("Panel A peak selection requires finite context ΔF/F samples.")
    return values.max(axis=1)


def select_display_examples(
    payload: dict, statistics: pd.DataFrame, arrays: dict,
) -> list[str]:
    """Apply the peak gate only to shared positive-joint panel A candidates."""
    peaks = context_dff_peaks(arrays)
    if len(peaks) != len(payload["roi_keys"]):
        raise ValueError("Panel A ΔF/F peak identities are not aligned.")
    passing = np.asarray(payload["roi_keys"])[peaks > PANEL_A_DFF_PEAK_THRESHOLD]
    candidates = statistics.copy()
    candidates["positive_joint"] &= candidates.roi_key.isin(passing)
    previous = payload["example_roi_keys"][0]
    return matched_examples(
        candidates, [key for key in payload["roi_keys"] if key != previous],
    )
