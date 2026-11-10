"""Shared positive-context-Q1 control means for both ephys C1 figure layouts."""

from __future__ import annotations

import numpy as np
from matplotlib.axes import Axes
from matplotlib.ticker import MaxNLocator

from .standard_oddball_examples import WINDOW
from .standard_oddball_neuropixels import EVENTS, Diagnostic
from .standard_oddball_population import EVENT_ID

SELECTION_RULE = (
    "Same eligible visual units in both control curves; actual-context 90-degree "
    "Q1 raw p <0.05 and signed MI >0.1; finite p and MI; no Q2 restriction."
)
SEM_RULE = "Across-neuron sample SD (ddof=1) / sqrt(n), same cells in both curves."


def prepare_positive_q1_means(data: Diagnostic, split: dict) -> dict:
    """Use one actual-context Q1-positive pool and separate pre/post display baselines."""
    ids = [unit["id"] for unit in data.units]
    if (
        ids != split["payload"]["unit_ids"]
        or data.session["sessionId"] != split["payload"]["session_id"]
        or data.session["asset"] != split["payload"]["asset"]
    ):
        raise ValueError("Q1 mean-trace source unit/session identities disagree.")
    time = np.asarray(split["time"], dtype=float)
    rates = np.asarray(split["rates"], dtype=float)
    baselines = np.asarray(split["baselines"], dtype=float)
    if (
        time.ndim != 1 or not time.size
        or rates.shape != (2, len(ids), time.size) or baselines.shape != (2, len(ids))
        or not all(np.isfinite(values).all() for values in (time, rates, baselines))
    ):
        raise ValueError("Q1 mean-trace rates, baselines, or time have invalid shapes/values.")
    event = EVENTS.index(EVENT_ID)
    p, mi = (data.statistics[key][event] for key in ("q1_p", "q1_modulation"))
    if p.shape != (len(ids),) or mi.shape != (len(ids),):
        raise ValueError("Q1 mean-trace statistics do not align with the displayed units.")
    positive = np.isfinite(p) & np.isfinite(mi) & (p < 0.05) & (mi > 0.1)
    if positive.sum() < 2:
        raise ValueError("At least two actual-context Q1-positive units are required for SEM.")
    selected = (rates - baselines[..., None])[:, positive]
    return {
        "time": time, "positive": positive, "q1_p": p, "q1_mi": mi,
        "mean": selected.mean(axis=1),
        "sem": selected.std(axis=1, ddof=1) / np.sqrt(selected.shape[1]),
    }


def draw_positive_q1_means(ax: Axes, prepared: dict) -> None:
    """Draw the same baseline-subtracted means and across-neuron SEM in either layout."""
    for i, (label, color, linestyle) in enumerate((
        ("Pre-C1", "#777777", "--"), ("Post-C1", "#635aa5", "-"),
    )):
        center, sem = prepared["mean"][i], prepared["sem"][i]
        band = ax.fill_between(
            prepared["time"], center - sem, center + sem,
            color=color, alpha=0.18, linewidth=0,
        )
        band.set_gid(f"mean-sem-{('pre', 'post')[i]}")
        line, = ax.plot(
            prepared["time"], center, color=color, linestyle=linestyle,
            linewidth=0.85, label=label,
        )
        line.set_gid(f"mean-Q1-positive-{('pre', 'post')[i]}")
    ax.axhline(0, color="#777777", linewidth=0.35)
    ax.axvline(0, color="black", linewidth=0.35, linestyle="--")
    ax.set_xlim(WINDOW)
    ax.set_xticks([-0.5, 0, 0.5])
    ax.yaxis.set_major_locator(MaxNLocator(3))
    ax.tick_params(labelsize=6, length=2, pad=1)
    ax.set_ylabel("Rate - baseline (Hz)", fontsize=6)
    ax.set_xlabel("Time from onset (s)", fontsize=6)
    ax.legend(
        loc="lower center", bbox_to_anchor=(0.5, 1.01), ncol=2, frameon=False,
        fontsize=6, handlelength=1.3, columnspacing=0.6, handletextpad=0.3,
    )
