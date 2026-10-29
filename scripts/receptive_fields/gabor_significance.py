# Authors: Lucas Rudelt, Marcel C. Raabe
# Date: 2026-10-29
"""Time the Gabor unit-level null on three units of each modality.

Each of 1000 shuffles reassigns presentations to positions once per
orientation and applies that same reassignment to every delay x duration
window. Two tests are computed from those shuffles:

* the previous counting p-value, one per window and orientation,
  ``(1 + #{surrogate >= observed}) / (n_shuffle + 1)``, ties counted
* the studentized maximum over windows and orientations, with a Gumbel
  fit by method of moments and a survival-function p-value

Dividing the map statistic by the grand mean, as the spike-rate chi-squared
does, does not change either p-value: the mean is invariant under a
permutation, and studentizing each window removes a window-specific scale.

The responses are those of the Gabor drivers, whose delay x duration grids and
window rules are those of the Zebra analysis: half-open spike-count windows for
ecephys, and for imaging the drivers' window means (`WINDOW_MEANS`) on their
traces (mesoscope events from the NWB, SLAP2 events from `utils.deconvolution`).
The Gumbel fit and BH are those of `filter_significant_maps.py`. Sessions are
streamed from DANDI.

    python gabor_significance.py
"""
from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

import numpy as np

sys.path.append(str(Path(__file__).resolve().parent))

import compute_rf_gabors_ecephys as ecephys_gabors
import compute_rf_gabors_mesoscope as meso_gabors
import compute_rf_gabors_slap2 as slap2_gabors
import rf_gabors
import utils
from filter_significant_maps import bh_fdr, gumbel_mom

N_SHUFFLE = 1000
N_UNITS = 3

# (dandiset, asset path) of the example session of each modality
EPHYS_ASSET = ("001637", "sub-830794/sub-830794_ses-ecephys-830794-2026-01-26-12-02-05_ecephys.nwb")
MESO_ASSET = (
    "001768",
    "sub-832700/sub-832700_ses-multiplane-ophys-832700-2026-01-24-12-06-12_ophys.nwb",
)
SLAP2_ASSET = ("001424", "sub-829704/sub-829704_ses-829704-2025-12-18-10-57-36_image+ophys.nwb")

# The drivers' grids, so the null is taken over the windows the maps were chosen from
EPHYS_DELAYS, EPHYS_DURATIONS = ecephys_gabors.DELAYS, ecephys_gabors.DURATIONS
MESO_DELAYS, MESO_DURATIONS = meso_gabors.DELAYS, meso_gabors.DURATIONS
SLAP2_DELAYS, SLAP2_DURATIONS = slap2_gabors.grid("green")


def counting_p(observed, surrogate):
    """Previous test. ``surrogate`` is (n_shuffle, ...) and ``observed`` is (...)."""
    at_least = np.sum(rf_gabors.at_least(surrogate, observed), axis=0)
    return (at_least + 1) / (surrogate.shape[0] + 1)


def gumbel_sf(x, mu, beta):
    """Gumbel survival function. A non-positive scale returns 1."""
    x, mu, beta = np.broadcast_arrays(
        np.asarray(x, dtype=float), np.asarray(mu, dtype=float), np.asarray(beta, dtype=float)
    )
    out = np.ones(x.shape, dtype=float)
    ok = np.isfinite(beta) & (beta > 0) & np.isfinite(mu) & np.isfinite(x)
    z = (x[ok] - mu[ok]) / beta[ok]
    out[ok] = -np.expm1(-np.exp(-z))
    return out


def _cell_slots(x, y):
    cells = {}
    for i, (xi, yi) in enumerate(zip(x, y, strict=False)):
        cells.setdefault((int(xi), int(yi)), []).append(i)
    return [np.asarray(slots, dtype=int) for slots in cells.values()]


def _cell_means(values, perms, cell_slots):
    """Mean response in each grid cell after each presentation permutation.

    values: (n_units, n_windows, n_presentations)
    perms:  (n_shuffle, n_presentations), or (1, n_presentations) for the observed
    returns (n_cells, n_shuffle, n_units, n_windows)
    """
    means = []
    for slots in cell_slots:
        gathered = np.moveaxis(values[:, :, perms[:, slots]], 2, 0)
        with np.errstate(invalid="ignore"):
            means.append(np.nanmean(gathered, axis=-1))
    return np.stack(means, axis=0)


def _sum_of_squares(values, perms, cell_slots, grand):
    """Map statistic for each permutation, accumulated one grid cell at a time.

    ``perms`` is (n_shuffle, n_presentations). The result is
    (n_shuffle, n_units, n_windows). Cells are not stacked, so a full probe
    stays in memory.
    """
    acc = np.zeros((perms.shape[0],) + grand.shape, dtype=np.float64)
    for slots in cell_slots:
        gathered = np.moveaxis(values[:, :, perms[:, slots]], 2, 0)
        with np.errstate(invalid="ignore"):
            cell_mean = np.nanmean(gathered, axis=-1)
        diff = cell_mean - grand[None]
        acc += np.where(np.isfinite(diff), diff * diff, 0.0)
    return acc


def orientation_statistics(values, x, y, n_shuffle, rng):
    """Observed and surrogate map statistics for one orientation.

    ``values`` is (n_units, n_windows, n_presentations). One permutation of
    those presentations is drawn per shuffle and applied to every window.
    The statistic is the sum of squared deviations of the repeat-mean map
    from the grand mean. Returns ``observed`` (n_units, n_windows) and
    ``surrogate`` (n_shuffle, n_units, n_windows).
    """
    n_pres = values.shape[-1]
    slots = _cell_slots(x, y)
    with np.errstate(invalid="ignore"):
        grand = np.nanmean(values, axis=-1)

    identity = np.arange(n_pres, dtype=int)[None, :]
    observed = _sum_of_squares(values, identity, slots, grand)[0]

    order = np.tile(np.arange(n_pres), (n_shuffle, 1))
    perms = rng.permuted(order, axis=1)
    surrogate = _sum_of_squares(values, perms, slots, grand)
    return observed, surrogate


def studentized_max_gumbel(observed, surrogate):
    """Studentize each window, take the maximum, and fit a Gumbel to that maximum.

    ``observed`` is (n_units, n_tests) and ``surrogate`` is
    (n_shuffle, n_units, n_tests). Windows with no surrogate spread are left
    out of the maximum. Returns the Gumbel p-value per unit, the per-test
    counting p-value, and the location of the largest studentized statistic.
    """
    null_mean = surrogate.mean(axis=0)
    with np.errstate(invalid="ignore"):
        null_spread = surrogate.std(axis=0, ddof=1)
    usable = np.isfinite(null_spread) & (null_spread > 0) & np.isfinite(observed)

    student_obs = np.full(observed.shape, -np.inf)
    student_sur = np.full(surrogate.shape, -np.inf)
    student_obs[usable] = (observed[usable] - null_mean[usable]) / null_spread[usable]
    student_sur[:, usable] = (
        (surrogate[:, usable] - null_mean[usable]) / null_spread[usable]
    )
    none = ~usable.any(axis=1)
    student_obs[none] = 0.0
    student_sur[:, none] = 0.0

    maximum_obs = student_obs.max(axis=1)
    maximum_sur = student_sur.max(axis=-1)
    mu, beta = gumbel_mom(maximum_sur.T)
    return {
        "gumbel_p": gumbel_sf(maximum_obs, mu, beta),
        "counting_p": counting_p(observed, surrogate),
        "maximum_index": student_obs.argmax(axis=1),
        "maximum_T": maximum_obs,
        "n_usable": usable.sum(axis=1),
        "null_mean_T": mu,
        "null_spread_T": beta,
    }


def previous_counting_test(responses, df_rf, x_pos, y_pos, orientations, n_shuffle, seed):
    """The existing per-window test, via ``rf_gabors._unit_stats``.

    Each window is shuffled on its own, with missing responses left in place.
    Returns p-values of shape (n_units, n_windows, n_orientations).
    """
    o_i, r_i, x_i, y_i = rf_gabors.grid_indices(df_rf, x_pos, y_pos, orientations)
    n_rep = int(r_i.max()) + 1
    n_units, n_windows, _ = responses.shape
    n_ori = len(orientations)
    p_values = np.ones((n_units, n_windows, n_ori))
    for window in range(n_windows):
        grid = np.full((n_units, n_ori, n_rep, len(x_pos), len(y_pos)), np.nan)
        grid[:, o_i, r_i, x_i, y_i] = responses[:, window]
        for unit in range(n_units):
            _, _, _, p_orient = rf_gabors._unit_stats(
                (seed + unit + window * n_units, grid[unit]), n_shuffle=n_shuffle
            )
            p_values[unit, window] = p_orient
    return p_values


def window_list(delays, durations):
    return [(float(delay), float(duration)) for delay in delays for duration in durations]


def spike_responses(spikes, df_rf, delays, durations):
    """(n_units, n_windows, n_presentations) rates, as `compute_rf_gabors_ecephys.py`
    computes them."""
    windows = window_list(delays, durations)
    out = np.empty((len(spikes), len(windows), len(df_rf)))
    sorted_spikes = [np.sort(np.asarray(times, dtype=float)) for times in spikes]
    for i, (delay, duration) in enumerate(windows):
        out[:, i] = ecephys_gabors.spike_rates(sorted_spikes, df_rf, delay, duration)
    return out, windows


def trace_responses(traces, times, df_rf, delays, durations, window_means=rf_gabors.imaged_means):
    """(n_units, n_windows, n_presentations) window means by the driver's rule.

    ``window_means`` is the driver's ``WINDOW_MEANS``: NaN where < 95 % of a
    window was imaged for SLAP2, the first sample of an empty window for the
    mesoscope.
    """
    onsets = df_rf["start_time"].to_numpy(float)
    windows = window_list(delays, durations)
    out = np.empty((traces.shape[0], len(windows), len(onsets)))
    for i, (delay, duration) in enumerate(windows):
        out[:, i] = window_means(times, traces, onsets + delay, duration)
    return out, windows


def by_orientation(responses, df_rf, x_pos, y_pos, orientations):
    o_i, _, x_i, y_i = rf_gabors.grid_indices(df_rf, x_pos, y_pos, orientations)
    groups = []
    for o, orientation in enumerate(orientations):
        chosen = o_i == o
        groups.append({
            "values": responses[:, :, chosen],
            "x": x_i[chosen],
            "y": y_i[chosen],
            "orientation": float(orientation),
        })
    return groups


def joint_null(responses, df_rf, x_pos, y_pos, orientations, n_shuffle, seed):
    """1000 joint shuffles, then the counting p-values and the Gumbel p-value."""
    groups = by_orientation(responses, df_rf, x_pos, y_pos, orientations)
    observed = []
    surrogate = []
    rng = np.random.default_rng(seed)
    windows = responses.shape[1]
    for group in groups:
        obs, sur = orientation_statistics(
            group["values"], group["x"], group["y"], n_shuffle, rng
        )
        observed.append(obs)
        surrogate.append(sur)
    result = studentized_max_gumbel(
        np.concatenate(observed, axis=1), np.concatenate(surrogate, axis=2)
    )
    result["orientation_of_test"] = np.concatenate([
        np.full(windows, group["orientation"]) for group in groups
    ])
    return result


def _text(value) -> str:
    if isinstance(value, bytes):
        value = value.decode()
    return str(value)


def open_stream(dandiset, asset_path):
    """Stream one asset; returns the stream and the session name."""
    print(f"  streaming {asset_path} from dandiset {dandiset}", flush=True)
    return utils.open_session(asset_path, dandiset), Path(asset_path).stem


def load_ephys():
    stream, session = open_stream(*EPHYS_ASSET)
    with stream:
        units = stream.units_df(include_spikes=False)
        units["probe"] = units["probe"].map(_text)
        units["unit_name"] = units["unit_name"].map(_text)
        picked = units.loc[units["probe"] == "ProbeC"].head(N_UNITS)
        if len(picked) < N_UNITS:
            raise RuntimeError(f"ProbeC has {len(picked)} units, need {N_UNITS}")
        bounds = np.concatenate([[0], np.asarray(
            stream._h5["units"]["spike_times_index"][:], dtype=np.int64
        )])
        spikes = []
        for row in picked.index.to_numpy():
            spikes.append(np.asarray(
                stream._h5["units"]["spike_times"][int(bounds[row]):int(bounds[row + 1])],
                dtype=float,
            ))
        df_rf = stream.gabor_rf_df()
    return {
        "session": session,
        "unit_names": picked["unit_name"].tolist(),
        "kind": "spikes",
        "spikes": spikes,
        "df_rf": df_rf,
        "delays": EPHYS_DELAYS,
        "durations": EPHYS_DURATIONS,
    }


def load_mesoscope():
    stream, session = open_stream(*MESO_ASSET)
    plane = "VISp_0"
    with stream:
        df_rf = stream.stim_df(meso_gabors.STIM_TABLE)
        traces, times, names = meso_gabors.load_traces(stream, plane, "events")
    margin = float(max(MESO_DELAYS) + max(MESO_DURATIONS) + 1.0)
    traces, times = rf_gabors.slice_to_stimulus(traces[:N_UNITS], times, df_rf, margin)
    return {
        "session": session,
        "unit_names": names[:N_UNITS],
        "kind": "traces",
        "traces": traces,
        "times": times,
        "df_rf": df_rf,
        "delays": MESO_DELAYS,
        "durations": MESO_DURATIONS,
        "window_means": meso_gabors.WINDOW_MEANS,
    }


def load_slap2():
    stream, session = open_stream(*SLAP2_ASSET)
    with stream:
        df_rf = stream.stim_df(slap2_gabors.STIM_TABLE)
        margin = float(max(SLAP2_DELAYS) + max(SLAP2_DURATIONS) + 1.0)
        traces, times, names = slap2_gabors.load_traces(
            stream, "DMD1", "green",
            t_start=float(df_rf["start_time"].min() - margin),
            t_stop=float(df_rf["stop_time"].max() + margin),
            signal="events", nwb_path=SLAP2_ASSET[1],
        )
    return {
        "session": session,
        "unit_names": names[:N_UNITS],
        "kind": "traces",
        "traces": traces[:N_UNITS],
        "times": times,
        "df_rf": df_rf,
        "delays": SLAP2_DELAYS,
        "durations": SLAP2_DURATIONS,
        "window_means": slap2_gabors.WINDOW_MEANS,
    }


def responses_for(loaded):
    if loaded["kind"] == "spikes":
        return spike_responses(
            loaded["spikes"], loaded["df_rf"], loaded["delays"], loaded["durations"]
        )
    return trace_responses(
        loaded["traces"], loaded["times"], loaded["df_rf"],
        loaded["delays"], loaded["durations"], loaded["window_means"],
    )


def _fmt_p(value):
    if not np.isfinite(value):
        return "nan"
    if value < 1e-3:
        return f"{value:.2e}"
    return f"{value:.4f}"


def report(name, loaded, responses, windows, joint, previous, times):
    x_pos, y_pos, orientations = rf_gabors.rf_grid(loaded["df_rf"])
    n_tests = joint["counting_p"].shape[1]
    print(
        f"{name}  session={loaded['session']}  units={len(loaded['unit_names'])}  "
        f"windows={len(windows)}  orientations={len(orientations)}  "
        f"presentations={responses.shape[-1]}  grid={len(x_pos)}x{len(y_pos)}  "
        f"shuffles={N_SHUFFLE}",
        flush=True,
    )
    print(f"  load                  {times['load']:.2f} s", flush=True)
    print(f"  response windows      {times['responses']:.2f} s", flush=True)
    print(f"  previous counting     {times['previous']:.2f} s", flush=True)
    print(f"  joint null + Gumbel   {times['joint']:.2f} s", flush=True)
    print(
        f"  joint null per unit   {times['joint'] / len(loaded['unit_names']):.2f} s",
        flush=True,
    )
    q_values = bh_fdr(joint["gumbel_p"])
    for unit, unit_name in enumerate(loaded["unit_names"]):
        test = int(joint["maximum_index"][unit])
        window = test % len(windows)
        delay, duration = windows[window]
        orientation = joint["orientation_of_test"][test]
        if joint["n_usable"][unit] == 0:
            chosen = "no window had surrogate spread"
        else:
            chosen = (
                f"best T={joint['maximum_T'][unit]:.2f} at "
                f"delay={delay:g}s duration={duration:g}s orientation={orientation:g}"
            )
        print(
            f"  {_text(unit_name)}  "
            f"Gumbel p={_fmt_p(joint['gumbel_p'][unit])}  "
            f"BH q={_fmt_p(q_values[unit])}  "
            f"min counting p={_fmt_p(joint['counting_p'][unit].min())}  "
            f"min previous p={_fmt_p(previous[unit].min())}  "
            f"{chosen}",
            flush=True,
        )
    print(
        f"  ({n_tests} window x orientation tests; "
        "BH q is only over these three units)",
        flush=True,
    )
    return {
        "modality": name,
        "load_s": times["load"],
        "previous_s": times["previous"],
        "joint_s": times["joint"],
    }


def run_modality(name, loader):
    print(f"\n=== {name} ===", flush=True)
    started = time.perf_counter()
    loaded = loader()
    load_s = time.perf_counter() - started

    started = time.perf_counter()
    responses, windows = responses_for(loaded)
    response_s = time.perf_counter() - started

    x_pos, y_pos, orientations = rf_gabors.rf_grid(loaded["df_rf"])
    started = time.perf_counter()
    previous = previous_counting_test(
        responses, loaded["df_rf"], x_pos, y_pos, orientations, N_SHUFFLE, seed=0
    )
    previous_s = time.perf_counter() - started

    started = time.perf_counter()
    joint = joint_null(
        responses, loaded["df_rf"], x_pos, y_pos, orientations, N_SHUFFLE, seed=0
    )
    joint_s = time.perf_counter() - started

    return report(
        name, loaded, responses, windows, joint, previous,
        {"load": load_s, "responses": response_s, "previous": previous_s, "joint": joint_s},
    )


def _self_check():
    """A single bright cell must be detected, and a flat map must get p = 1.

    Every shuffle of a flat map ties with it, so counting the ties puts it at 1.
    """
    n_rep, n_shuffle = 4, 200
    x, y = [], []
    values = np.zeros((1, 2, n_rep * 4))
    cursor = 0
    for yi in range(2):
        for xi in range(2):
            x.extend([xi] * n_rep)
            y.extend([yi] * n_rep)
            if xi == 0 and yi == 0:
                values[0, 0, cursor:cursor + n_rep] = 5.0
            cursor += n_rep
    observed, surrogate = orientation_statistics(
        values, np.asarray(x), np.asarray(y), n_shuffle, np.random.default_rng(0)
    )
    expected = (5 - 1.25) ** 2 + 3 * (0 - 1.25) ** 2
    if abs(observed[0, 0] - expected) > 1e-6:
        raise AssertionError(f"map statistic {observed[0, 0]} != {expected}")
    if observed[0, 1] != 0:
        raise AssertionError("a flat window produced a non-zero statistic")
    result = studentized_max_gumbel(observed, surrogate)
    if result["counting_p"][0, 1] != 1:
        raise AssertionError(f"flat-map counting p {result['counting_p'][0, 1]} != 1")
    if result["counting_p"][0, 0] > 0.05 or result["gumbel_p"][0] > 0.05:
        raise AssertionError(
            f"bright cell was not detected: counting {result['counting_p'][0, 0]}, "
            f"Gumbel {result['gumbel_p'][0]}"
        )
    q = bh_fdr(np.array([result["gumbel_p"][0], 0.5]))
    if not (q[0] <= q[1] and q[0] <= 1):
        raise AssertionError(f"BH q-values out of order: {q}")


def main():
    _self_check()
    summaries = []
    for name, loader in (
        ("ephys", load_ephys),
        ("mesoscope", load_mesoscope),
        ("slap2", load_slap2),
    ):
        try:
            summaries.append(run_modality(name, loader))
        except Exception:
            print(f"\n{name} failed:", flush=True)
            traceback.print_exc()
    if summaries:
        print("\nruntime summary (seconds)", flush=True)
        print(f"  {'modality':<12} {'load':>8} {'previous':>10} {'joint null':>12}", flush=True)
        for row in summaries:
            print(
                f"  {row['modality']:<12} {row['load_s']:8.2f} "
                f"{row['previous_s']:10.2f} {row['joint_s']:12.2f}",
                flush=True,
            )


if __name__ == "__main__":
    main()
