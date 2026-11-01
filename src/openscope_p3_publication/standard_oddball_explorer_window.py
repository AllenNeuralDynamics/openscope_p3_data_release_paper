"""Onset-aligned, display-only wider windows; static analyses remain frozen."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .mesoscope_standard_oddball import ROOT, display_trials, sha256
from .neural_responses import sdf_kernel

DIRECTORY = ROOT / "figure_sources/data/standard-oddball-explorer-window"
WINDOW = (-1.5, 1.5)
MODALITIES = ("neuropixels", "mesoscope", "slap2")


def wide_sdf(spikes: np.ndarray, onsets: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Average native spikes in 5-ms bins with the frozen causal 25-ms kernel."""
    if (
        spikes.ndim != 1 or not np.isfinite(spikes).all() or np.any(np.diff(spikes) < 0)
        or onsets.ndim != 1 or not len(onsets) or not np.isfinite(onsets).all()
    ):
        raise ValueError("Wide SDF requires finite sorted spikes and stimulus onsets.")
    dt = 0.005
    kernel = sdf_kernel(bin_seconds=dt, tau_seconds=0.025)
    padding = len(kernel) - 1
    n = round((WINDOW[1] - WINDOW[0]) / dt)
    # Retain the exact frozen edges: reanchoring them shifts boundary spikes by one bin.
    central_edges = -0.75 - padding * dt + np.arange(300 + padding + 1) * dt
    extra = 150
    edges = np.concatenate((
        central_edges[0] - np.arange(extra, 0, -1) * dt,
        central_edges,
        central_edges[-1] + np.arange(1, extra + 1) * dt,
    ))
    counts = np.zeros(n + padding)
    for onset in onsets:
        first, last = np.searchsorted(spikes, [onset + edges[0], onset + WINDOW[1]])
        counts += np.histogram(spikes[first:last] - onset, bins=edges)[0]
    rates = np.convolve(counts / len(onsets) / dt, kernel, mode="full")[padding:n + padding]
    return WINDOW[0] + (np.arange(n) + 0.5) * dt, rates


def wide_native_trial(
    times: np.ndarray, values: np.ndarray, onset: float, time: np.ndarray,
) -> np.ndarray:
    """Reuse native display alignment, masking extrapolation and acquisition pauses."""
    aligned = display_trials(times, values, np.array([onset]), time)[:, 0]
    targets = onset + time
    right = np.clip(np.searchsorted(times, targets, side="right"), 1, len(times) - 1)
    dt = np.median(np.diff(times))
    gap = (times[right] - times[right - 1] > 3 * dt) & (
        targets > times[right - 1]
    ) & (targets < times[right])
    aligned[:, gap] = np.nan
    return aligned


def average_recorded(trials: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Keep every trial; average only observed samples and expose their counts."""
    counts = np.isfinite(trials).sum(axis=1)
    if np.any(counts == 0) or np.isinf(trials).any():
        raise ValueError("Wide display has an entirely unobserved or infinite source/time bin.")
    return np.nanmean(trials, axis=1), counts


def verify_central(
    time: np.ndarray, delta: np.ndarray, reference_time: np.ndarray, reference: np.ndarray,
) -> None:
    """Verify the unchanged central data, allowing only numerical SDF roundoff."""
    indices = np.argmin(np.abs(time[:, None] - reference_time[None, :]), axis=0)
    np.testing.assert_allclose(time[indices], reference_time, atol=1e-12, rtol=0)
    np.testing.assert_allclose(delta[..., indices], reference, atol=2e-6, rtol=2e-7)


def load_wide_population(
    modality: str, keys: list[str], directory: Path = DIRECTORY,
) -> tuple[dict, dict[str, np.ndarray]]:
    """Load checksummed explorer-only displays without remote source access."""
    metadata = json.loads((directory / "provenance.json").read_text())
    if metadata.get("version") != 1 or metadata.get("window") != list(WINDOW):
        raise ValueError("Unsupported wider explorer snapshot.")
    for record in metadata["inputs"]:
        if sha256(ROOT / record["path"]) != record["sha256"]:
            raise ValueError(f"Wider explorer source changed: {record['path']}")
    path = directory / f"{modality}.npz"
    if sha256(path) != metadata["outputs"][modality]:
        raise ValueError(f"Wider {modality} display checksum changed.")
    view = metadata["modalities"][modality]
    with np.load(path, allow_pickle=False) as archive:
        arrays = {k: archive[k] for k in archive.files}
    time, delta, counts = (arrays[k] for k in ("time", "delta", "counts"))
    if (
        view["source_ids"] != keys or delta.shape != (2, len(keys), len(time))
        or counts.shape != delta.shape or not np.isfinite(delta).all()
        or not np.isfinite(time).all() or not np.all(np.diff(time) > 0)
        or time[0] < WINDOW[0] or time[-1] > WINDOW[1]
        or not np.issubdtype(counts.dtype, np.integer) or np.any(counts <= 0)
    ):
        raise ValueError("Wider explorer identity, shape, samples or coverage changed.")
    return view, arrays
