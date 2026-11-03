"""Spectrum-matched noise-only reference for the SLAP2 event detector.

Event-free SLAP2 noise is strongly autocorrelated, so a white-noise null misstates what the
matched filter does to noise. These helpers remove the detected events from a trace, randomize
the Fourier phases of the remainder, and run the unchanged detector on the result. Every
detection on such a surrogate comes from noise alone.
"""

from __future__ import annotations

import numpy as np

from openscope_p3_publication.slap2_glutamate_qc_events import (
    baseline_noise,
    detect_events,
    event_amplitudes_raw,
    interpolate_gaps,
)

EVENT_SAMPLES_BEFORE = 20
EVENT_SAMPLES_AFTER = 40


def event_free(trace: np.ndarray, indices: np.ndarray) -> np.ndarray:
    """Return the trace with detection windows removed and linearly bridged."""
    masked = trace.astype(np.float64).copy()
    for index in indices:
        masked[max(0, index - EVENT_SAMPLES_BEFORE):index + EVENT_SAMPLES_AFTER] = np.nan
    filled, _ = interpolate_gaps(masked.astype(np.float32))
    return filled.astype(np.float64)


def phase_surrogate(signal: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Return a Gaussian surrogate with the mean and power spectrum of `signal`."""
    mean = signal.mean()
    spectrum = np.fft.rfft(signal - mean)
    phases = rng.uniform(0, 2 * np.pi, spectrum.size)
    phases[0] = 0
    surrogate = np.fft.irfft(np.abs(spectrum) * np.exp(1j * phases), n=signal.size)
    return (surrogate + mean).astype(np.float32)


def surrogate_events(
    trace: np.ndarray, dt: float, rng: np.random.Generator,
) -> tuple[float, np.ndarray]:
    """Return the noise-only event rate (Hz) and finite raw-SD amplitudes for one source."""
    observed = detect_events(trace, dt)
    surrogate = phase_surrogate(event_free(trace, observed["idx"]), rng)
    detected = detect_events(surrogate, dt)
    noise, _ = baseline_noise(surrogate)
    amplitudes = event_amplitudes_raw(surrogate, detected["idx"], dt, noise)
    return detected["idx"].size / (surrogate.size * dt), amplitudes[np.isfinite(amplitudes)]
