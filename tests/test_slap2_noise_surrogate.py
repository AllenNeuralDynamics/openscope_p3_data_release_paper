"""Checks for the spectrum-matched SLAP2 noise-only reference."""

import numpy as np

from openscope_p3_publication.slap2_noise_surrogate import (
    EVENT_SAMPLES_AFTER,
    EVENT_SAMPLES_BEFORE,
    event_free,
    phase_surrogate,
    surrogate_events,
)


def _red_noise(size: int, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    noise = rng.normal(size=size)
    for index in range(1, size):
        noise[index] += 0.9 * noise[index - 1]
    return noise


def test_phase_surrogate_keeps_mean_and_power_spectrum_but_not_the_signal() -> None:
    signal = _red_noise(4000) + 3.0
    surrogate = phase_surrogate(signal, np.random.default_rng(0))
    np.testing.assert_allclose(surrogate.mean(), signal.mean(), atol=1e-3)
    np.testing.assert_allclose(
        np.abs(np.fft.rfft(surrogate - surrogate.mean())),
        np.abs(np.fft.rfft(signal - signal.mean())),
        rtol=1e-2, atol=1.0,
    )
    assert abs(np.corrcoef(signal, surrogate)[0, 1]) < 0.2


def test_event_free_bridges_only_the_detection_windows() -> None:
    trace = np.zeros(400, dtype=np.float32)
    trace[200:210] = 50.0
    filled = event_free(trace, np.array([200]))
    assert filled.max() == 0.0
    window = slice(200 - EVENT_SAMPLES_BEFORE, 200 + EVENT_SAMPLES_AFTER)
    np.testing.assert_array_equal(filled[:window.start], trace[:window.start])
    np.testing.assert_array_equal(filled[window.stop:], trace[window.stop:])


def test_surrogate_events_ignore_large_events_in_the_source_trace() -> None:
    dt = 0.005
    noise = _red_noise(40000).astype(np.float32)
    with_events = noise.copy()
    kernel = np.exp(-np.arange(40) * dt / 0.02).astype(np.float32)
    for start in range(500, 39000, 500):
        with_events[start:start + 40] += 50 * noise.std() * kernel
    plain_rate, _ = surrogate_events(noise, dt, np.random.default_rng(0))
    event_rate, amplitudes = surrogate_events(with_events, dt, np.random.default_rng(0))
    assert np.isfinite(amplitudes).all()
    assert event_rate < 2 * max(plain_rate, 1 / (40000 * dt))
