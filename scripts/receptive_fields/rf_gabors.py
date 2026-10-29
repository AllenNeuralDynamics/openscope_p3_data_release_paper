# Author: Marcel C. Raabe
# Contributors: Lucas Rudelt
# Date: 2026-10-29
"""Receptive field mapping of the local Gabor patches.

The shared core of the three Gabor drivers, `compute_rf_gabors_ecephys.py`,
`compute_rf_gabors_mesoscope.py` and `compute_rf_gabors_slap2.py`: the
permutation test, the result-file layout, the pooled / per-trial blocks and the
reduction over the delay x duration grid. The ecephys driver feeds spike rates,
the imaging drivers the mean fluorescence (or event amplitude) over the response
window; everything after the response grid is the same, so all three produce
result files with exactly the same layout.

Three points that the imaging signal forced and that now hold for all modalities:

* **Test statistic.** The classic test uses chi-squared, Σ(O − E)²/E. Under a
  permutation of the trial responses E is invariant, so Σ(O − E)² ranks the shuffles
  identically and gives the same p-value — but it stays well defined when the
  responses are ΔF/F and can be negative. That is what is used here.
* **Response windows.** Each modality uses the delay x duration grid and the
  window rule of its Zebra (waven) analysis, so both stimuli are tested over
  the same windows. SLAP2 records in ~30 s bouts and drops short stretches of
  samples to NaN, so a window counts only if at least `MIN_COVERAGE` (95 %) of
  its time was imaged (`imaged_means`, as `waven_pipeline.imaged_window_means`);
  other windows are NaN and excluded from both the observed and the shuffled
  statistic. The mesoscope samples at ~10 Hz, slower than most windows, so a
  window holding no sample takes the first sample at or after its start
  (`sample_means`, as `waven_pipeline.average_signal_over_window`).
* **Baseline.** Optionally the mean over a pre-stimulus window is subtracted
  from each trial response, which removes slow drift that the fluorescence
  carries and the spike rate does not.

Pooled vs per trial follows the waven drivers: the whole RF block is analysed by
default; `--per-trial` splits it into its earlier and later half (`trial_0`,
`trial_1`, see `gabor_blocks`). The halves are scored at the (delay, duration)
the pooled run chose per unit and orientation, so the pooled run comes first.

File names, below <results-path>/<session>/[<signal>/], with delay and duration
in seconds to four decimals as in the waven result files:

    <session>__<tag>__<group>__[trial_<i>__]delay_<d>__duration_<u>.h5   one per sweep point
    <session>__<tag>__<group>__[trial_<i>__]optimized.h5                 reduced

The optimized files carry the swept grid as the attributes ``sweep_delays`` and
``sweep_durations``.
"""

import contextlib
import multiprocessing
import os
import shutil
from datetime import datetime
from functools import partial
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
from tqdm import tqdm

# the window rules are shared with the waven maps
from waven_pipeline import average_signal_over_window, imaged_window_means

N_SHUFFLE = 1000
# Relative tolerance for a surrogate statistic to count as equal to the observed
# one: a permutation that reproduces the observed configuration (common for
# sparse units) sums in another order and can land a rounding error below it.
TIE_RTOL = 1e-9


def at_least(surrogate, observed):
    """``surrogate >= observed``, with ties up to ``TIE_RTOL`` counted as equal.

    Counting ties keeps the permutation p-value ``(1 + #{surrogate >= observed})
    / (n + 1)`` exact when the statistic takes few distinct values.
    """
    observed = np.asarray(observed, dtype=float)
    return surrogate >= observed - TIE_RTOL * np.maximum(np.abs(observed), 1.0)


# ---------------------------------------------------------------------------
# Trial responses
# ---------------------------------------------------------------------------

def grid_indices(df_rf, x_pos, y_pos, orientations):
    """Per-presentation (orientation, repeat, x, y) indices into the response grid.

    Repeats are numbered in presentation order within each (orientation, x, y)
    cell.
    """
    keys = pd.DataFrame({
        'o': np.searchsorted(orientations, df_rf['Orientation'].to_numpy(float)),
        'x': np.searchsorted(x_pos, df_rf['X'].to_numpy(float)),
        'y': np.searchsorted(y_pos, df_rf['Y'].to_numpy(float)),
    })
    keys['rep'] = keys.groupby(['o', 'x', 'y']).cumcount()
    return keys['o'].values, keys['rep'].values, keys['x'].values, keys['y'].values


def fill_grids(resp, df_rf, x_pos, y_pos, orientations):
    """Per-presentation responses (n_units, n_presentations) on the stimulus grid.

    Returns R (n_units, n_orientations, n_repeats, nx, ny), NaN for cells a
    presentation never reached or whose response is missing, and the per-cell
    count of usable trials n_valid (n_orientations, nx, ny).
    """
    o_i, r_i, x_i, y_i = grid_indices(df_rf, x_pos, y_pos, orientations)
    shape = (len(orientations), r_i.max() + 1, len(x_pos), len(y_pos))

    R = np.full((resp.shape[0],) + shape, np.nan)
    R[:, o_i, r_i, x_i, y_i] = resp

    # window coverage depends only on the timestamps, so it is the same for every unit
    n_valid = np.isfinite(R[0]).sum(axis=1) if len(R) else np.zeros(shape[:1] + shape[2:], int)
    return R, n_valid


def imaged_means(times, traces, starts, duration):
    """Mean over [start, start + duration), NaN unless ≥ 95 % of it was imaged (SLAP2).

    A negative duration extends the window backwards. Returns (n_units, n_windows).
    """
    starts = np.asarray(starts, dtype=float)
    lo, hi = np.minimum(starts, starts + duration), np.maximum(starts, starts + duration)
    return imaged_window_means(times, traces, lo, hi)[0]


def sample_means(times, traces, starts, duration):
    """Mean over [start, start + duration) of a continuously sampled trace (mesoscope).

    A window holding no sample, e.g. duration 0, takes the first sample at or
    after its start. The traces must be NaN-free. Returns (n_units, n_windows).
    """
    return average_signal_over_window(times, traces, np.asarray(starts, dtype=float), duration)


def response_grids(traces, times, df_rf, x_pos, y_pos, orientations,
                   delay, duration, baseline=0.0, window_means=imaged_means):
    """Trial response grid of fluorescence traces and its per-cell count of usable trials.

    The response is the mean over [onset + delay, onset + delay + duration),
    by the modality's `window_means` rule.
    R:       (n_rois, n_orientations, n_repeats, nx, ny), NaN for unsampled trials
    n_valid: (n_orientations, nx, ny)
    """
    onsets = df_rf['start_time'].to_numpy(float)

    resp = window_means(times, traces, onsets + delay, duration)
    if baseline > 0:
        resp = resp - window_means(times, traces, onsets, -baseline)
    return fill_grids(resp, df_rf, x_pos, y_pos, orientations)


# ---------------------------------------------------------------------------
# Permutation test
# ---------------------------------------------------------------------------

def _unit_stats(args, n_shuffle=N_SHUFFLE):
    """Permutation statistics for one unit. `args` is (seed, R_unit).

    R_unit: (n_orientations, n_repeats, nx, ny). Returns (E, O, Z, P) with
    E/P shaped (n_orientations,) and O/Z shaped (n_orientations, nx, ny).
    """
    seed, R_unit = args
    rng = np.random.default_rng(seed)
    n_or, _, nx, ny = R_unit.shape

    E = np.full(n_or, np.nan)
    O = np.full((n_or, nx, ny), np.nan)  # noqa: E741  (observed counts, as in Σ(O − E)²)
    Z = np.full((n_or, nx, ny), np.nan)
    P = np.ones(n_or)

    for o in range(n_or):
        R = R_unit[o]
        finite = np.isfinite(R)
        vals = R[finite]
        if vals.size == 0:
            continue

        e = vals.mean()
        with np.errstate(invalid='ignore'):
            o_map = np.nanmean(R, axis=0)
        stat = np.nansum((o_map - e) ** 2)

        # all shuffles at once: permute the observed values, keep the NaNs in place
        shuffled = np.full((n_shuffle,) + R.shape, np.nan)
        shuffled[:, finite] = rng.permuted(np.tile(vals, (n_shuffle, 1)), axis=1)
        with np.errstate(invalid='ignore'):
            o_shuf = np.nanmean(shuffled, axis=1)
        stat_shuf = np.nansum((o_shuf - e) ** 2, axis=(1, 2))

        E[o] = e
        O[o] = o_map
        Z[o] = (o_map - e) / (vals.std() + 1e-10)
        P[o] = (np.sum(at_least(stat_shuf, stat)) + 1) / (n_shuffle + 1)

    return E, O, Z, P


def gabor_test(R, n_shuffle=N_SHUFFLE, seed=0, n_procs=None, desc='units'):
    """`_unit_stats` for every unit of R, in parallel; returns the stacked (E, O, Z, P)."""
    worker = partial(_unit_stats, n_shuffle=n_shuffle)
    tasks = ((seed + i, R[i]) for i in range(len(R)))
    with multiprocessing.Pool(processes=n_procs) as pool:
        results = list(tqdm(pool.imap(worker, tasks), total=len(R), desc=desc))
    return tuple(np.stack([r[k] for r in results]) for k in range(4))


def write_result(path, attributes, unit_names, orientations, x_pos, y_pos, stats, n_valid):
    """One sweep-point result file, written atomically."""
    mean_rates, mean_responses, z_score_response, p_values = stats
    path = Path(path).with_suffix('.h5')
    print(f'Saving results to {path}...')
    with atomic_h5(path) as hf:
        for key, value in attributes.items():
            hf.attrs[key] = value
        hf.create_dataset('unit_names', data=np.asarray(unit_names).astype('S'))
        hf.create_dataset('orientations', data=np.asarray(orientations, dtype=float))
        hf.create_dataset('x_positions', data=np.asarray(x_pos, dtype=float))
        hf.create_dataset('y_positions', data=np.asarray(y_pos, dtype=float))
        hf.create_dataset('n_valid_trials', data=n_valid)
        hf.create_dataset('mean_rate', data=mean_rates)
        hf.create_dataset('mean_response', data=mean_responses,
                          compression='gzip', compression_opts=4)
        hf.create_dataset('z_score_response', data=z_score_response,
                          compression='gzip', compression_opts=4)
        hf.create_dataset('p_value', data=p_values)
    return path


def compute_gabor_ophys(traces, times, unit_names, df_rf, x_pos, y_pos, orientations,
                        delay, duration, results_path, attributes,
                        baseline=0.0, n_shuffle=N_SHUFFLE, seed=0, n_procs=None,
                        window_means=imaged_means):
    """Run the Gabor RF test on every ROI and write one HDF5 result file.

    traces: (n_rois, n_t) fluorescence, times: (n_t,) sample times in seconds.
    """
    if len(unit_names) != traces.shape[0]:
        raise ValueError(f'{len(unit_names)} unit names for {traces.shape[0]} traces')

    R, n_valid = response_grids(traces, times, df_rf, x_pos, y_pos, orientations,
                                delay, duration, baseline, window_means)
    stats = gabor_test(R, n_shuffle, seed, n_procs, desc='rois')
    return write_result(results_path, attributes, unit_names, orientations, x_pos, y_pos,
                        stats, n_valid)


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def _text(value) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


@contextlib.contextmanager
def atomic_h5(path):
    """An HDF5 file written under a temporary name and renamed into place on success."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f'.tmp{os.getpid()}.h5')
    try:
        with h5py.File(tmp, 'w') as hf:
            yield hf
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


@contextlib.contextmanager
def atomic_h5_update(path):
    """Like `atomic_h5`, for adding to an existing file: edits a copy, then renames it."""
    path = Path(path)
    tmp = path.with_suffix(f'.tmp{os.getpid()}.h5')
    shutil.copy2(path, tmp)
    try:
        with h5py.File(tmp, 'a') as hf:
            yield hf
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def sweep_path(results_dir, session, tag, group, trial_part, delay, duration):
    """Result file of one (block, delay, duration)."""
    stem = '__'.join([session, tag, group, *trial_part,
                      f'delay_{delay:.4f}', f'duration_{duration:.4f}'])
    return Path(results_dir) / f'{stem}.h5'


def optimized_path(results_dir, session, tag, group, trial_part=()):
    """Reduced file of one block; the pooled one without a trial part."""
    return Path(results_dir) / ('__'.join([session, tag, group, *trial_part, 'optimized']) + '.h5')


def reusable(path, unit_names, recompute=False):
    """True if `path` already holds this sweep point for `unit_names`, so it can be skipped.

    A file computed on another unit list (an older release of the NWB file) is
    never reused silently: that raises, and --recompute overwrites it.
    """
    path = Path(path)
    if recompute or not path.exists():
        return False
    with h5py.File(path, 'r') as hf:
        saved = [_text(name) for name in hf['unit_names'][:]]
    if saved != [_text(name) for name in unit_names]:
        raise ValueError(
            f'{path.name} holds {len(saved)} units that differ from the {len(unit_names)} units '
            'of this recording (computed on another release of the NWB file?). '
            'Rerun with --recompute to replace it.')
    return True


# ---------------------------------------------------------------------------
# Stimulus table helpers
# ---------------------------------------------------------------------------

def rf_grid(df_rf):
    """Sorted x positions, y positions and orientations of an RF mapping table."""
    x_pos = np.sort(np.unique(df_rf['X'].to_numpy(float)))
    y_pos = np.sort(np.unique(df_rf['Y'].to_numpy(float)))
    orientations = np.sort(np.unique(df_rf['Orientation'].to_numpy(float)))
    return x_pos, y_pos, orientations


def slice_to_stimulus(traces, times, df_rf, margin):
    """Restrict traces to the RF mapping block, plus `margin` seconds either side."""
    keep = ((times >= df_rf['start_time'].min() - margin) &
            (times <= df_rf['stop_time'].max() + margin))
    return traces[:, keep], times[keep]


def split_gabor_block(df_rf):
    """First and second half of one Gabor RF block, in presentation order.

    Trial 0 is the earlier half and trial 1 the later half, so the two maps
    mimic Zebra trial 0 and trial 1. An odd presentation count gives the extra
    presentation to trial 1.
    """
    ordered = df_rf.sort_values('start_time')
    mid = len(ordered) // 2
    if mid == 0 or mid == len(ordered):
        raise ValueError(
            f'RF block has {len(ordered)} presentations; cannot split it in half'
        )
    return {0: ordered.iloc[:mid].copy(), 1: ordered.iloc[mid:].copy()}


def gabor_blocks(df_rf, per_trial=False):
    """The presentation blocks a run is computed on, as (trial_part, df_block).

    The counterpart of `waven_pipeline.zebra_blocks`. Pooled (the default) is the
    whole RF block with an empty trial part, so its file names carry no trial;
    `per_trial` gives the two halves of `split_gabor_block` as trial_0 and trial_1.
    """
    if not per_trial:
        return [([], df_rf)]
    return [([f'trial_{trial}'], block) for trial, block in split_gabor_block(df_rf).items()]


# ---------------------------------------------------------------------------
# The sweep and its reduction
# ---------------------------------------------------------------------------

def run_sweep(compute, df_rf, delays, durations, results_dir, session, tag, group,
              unit_names, attributes, per_trial=False, recompute=False, optimize=True):
    """Every (delay, duration) of every block, then one reduced file per block.

    compute(df_block, delay, duration, path, attributes) writes one result file.
    Existing files on the same unit list are skipped unless `recompute`.
    """
    if per_trial and optimize:
        pooled = optimized_path(results_dir, session, tag, group)
        if not pooled.is_file():
            raise FileNotFoundError(
                f'{pooled} not found. The trial halves are scored at the windows of the '
                'pooled run, so run without --per-trial first.')

    for trial_part, df_block in gabor_blocks(df_rf, per_trial):
        trial = trial_part[0] if trial_part else 'pooled_trials'
        print(f'\n{group} {trial}: {len(df_block)} presentations')
        sweep = []
        for delay in delays:
            for duration in durations:
                path = sweep_path(results_dir, session, tag, group, trial_part, delay, duration)
                sweep.append(path)
                if reusable(path, unit_names, recompute):
                    print(f'exists, skipping {path.name}')
                    continue
                attrs = dict(attributes,
                             trial=trial,
                             n_presentations=int(len(df_block)),
                             date_computed=datetime.today().strftime('%Y-%m-%d'),
                             delay_s=float(delay),
                             duration_s=float(duration))
                print(f'\n{group} {trial}  delay={float(delay)}s  duration={float(duration)}s')
                compute(df_block, float(delay), float(duration), path, attrs)
        if optimize:
            reduce_block(results_dir, session, tag, group, trial_part, sweep)


def reduce_block(results_dir, session, tag, group, trial_part, sweep):
    """Pooled: the lowest p per (unit, orientation). Per trial: the pooled run's windows."""
    out = optimized_path(results_dir, session, tag, group, trial_part)
    if not trial_part:
        return _optimize_probe_files(sweep, out)
    return assemble_fixed_windows(optimized_path(results_dir, session, tag, group), sweep, out)


def _optimize_probe_files(h5_files, output_path):
    """Per (unit, orientation), the (delay, duration) with the lowest p-value.

    All files must hold the same units in the same order.
    """
    output_path = Path(output_path).with_suffix('.h5')
    with h5py.File(h5_files[0], 'r', locking=False) as hf:
        unit_names = hf['unit_names'][:]
        orientations = hf['orientations'][:]
        x_positions = hf['x_positions'][:]
        y_positions = hf['y_positions'][:]
        session_attrs = dict(hf.attrs)

    n_units = len(unit_names)
    n_orientations = len(orientations)
    nx, ny = len(x_positions), len(y_positions)

    best_p_values = np.full((n_units, n_orientations), np.inf)
    best_mean_rate = np.zeros((n_units, n_orientations))
    best_mean_response = np.zeros((n_units, n_orientations, nx, ny))
    best_z_score_response = np.zeros((n_units, n_orientations, nx, ny))
    best_delay = np.full((n_units, n_orientations), np.nan)
    best_duration = np.full((n_units, n_orientations), np.nan)
    swept = []

    for fpath in tqdm(h5_files, desc=str(output_path.name)):
        with h5py.File(fpath, 'r', locking=False) as hf:
            if not np.array_equal(hf['unit_names'][:], unit_names):
                raise ValueError(f'{Path(fpath).name} holds other units than '
                                 f'{Path(h5_files[0]).name}')
            p_values = hf['p_value'][:]
            mean_rate = hf['mean_rate'][:]
            mean_response = hf['mean_response'][:]
            z_score_response = hf['z_score_response'][:]
            delay = hf.attrs['delay_s']
            duration = hf.attrs['duration_s']
        swept.append((float(delay), float(duration)))

        better = p_values < best_p_values                           # (n_units, n_orientations)
        best_p_values = np.where(better, p_values, best_p_values)
        best_mean_rate = np.where(better, mean_rate, best_mean_rate)
        best_delay = np.where(better, delay, best_delay)
        best_duration = np.where(better, duration, best_duration)

        better_4d = better[:, :, np.newaxis, np.newaxis]           # broadcast to spatial dims
        best_mean_response = np.where(better_4d, mean_response, best_mean_response)
        best_z_score_response = np.where(better_4d, z_score_response, best_z_score_response)

    print(f'Saving optimized results to {output_path}...')
    with atomic_h5(output_path) as hf:
        for key, value in session_attrs.items():
            if key not in ('delay_s', 'duration_s', 'date_computed'):
                hf.attrs[key] = value
        hf.attrs['date_optimized'] = datetime.today().strftime('%Y-%m-%d')
        # the grid the minimum was taken over; the unit-level null must use the same
        hf.attrs['sweep_delays'] = np.unique([d for d, _ in swept])
        hf.attrs['sweep_durations'] = np.unique([u for _, u in swept])
        hf.create_dataset('unit_names', data=unit_names)
        hf.create_dataset('orientations', data=orientations)
        hf.create_dataset('x_positions', data=x_positions)
        hf.create_dataset('y_positions', data=y_positions)
        hf.create_dataset('best_delay', data=best_delay)
        hf.create_dataset('best_duration', data=best_duration)
        hf.create_dataset('p_value', data=best_p_values)
        hf.create_dataset('mean_rate', data=best_mean_rate)
        hf.create_dataset('mean_response', data=best_mean_response,
                          compression='gzip', compression_opts=4)
        hf.create_dataset('z_score_response', data=best_z_score_response,
                          compression='gzip', compression_opts=4)

    return output_path


def _window_key(delay, duration):
    return (round(float(delay), 5), round(float(duration), 5))


def assemble_fixed_windows(full_optimized, sweep_files, output_path):
    """Build one half-block file using the pooled run's delay and duration.

    ``best_delay`` and ``best_duration`` are copied from the pooled optimized
    file. Each unit and orientation keeps that window; the half block is not
    allowed to pick a new one.
    """
    full_optimized = Path(full_optimized)
    with h5py.File(full_optimized, 'r') as hf:
        unit_names = hf['unit_names'][:]
        names = unit_names.astype(str)
        orientations = hf['orientations'][:]
        x_positions = hf['x_positions'][:]
        y_positions = hf['y_positions'][:]
        best_delay = np.asarray(hf['best_delay'][:], dtype=float)
        best_duration = np.asarray(hf['best_duration'][:], dtype=float)
        session_attrs = dict(hf.attrs)

    needed = {
        _window_key(delay, duration)
        for delay, duration in zip(best_delay.ravel(), best_duration.ravel(), strict=False)
        if np.isfinite(delay) and np.isfinite(duration)
    }
    found = {}
    trial = None
    for path in sweep_files:
        with h5py.File(path, 'r') as hf:
            if 'delay_s' not in hf.attrs:
                continue
            key = _window_key(hf.attrs['delay_s'], hf.attrs['duration_s'])
            trial = hf.attrs.get('trial', trial)
            got = hf['unit_names'][:].astype(str)
            if len(got) != len(names) or not np.array_equal(got, names):
                raise ValueError(
                    f'Unit list in {Path(path).name} does not match {full_optimized.name}'
                )
            found[key] = dict(
                p=hf['p_value'][:],
                rate=hf['mean_rate'][:],
                mean=hf['mean_response'][:],
                z=hf['z_score_response'][:],
            )
    missing = sorted(needed - set(found))
    if missing:
        raise FileNotFoundError(
            'Half-block files are missing the pooled run\'s windows: '
            + ', '.join(f'delay={d:g} duration={u:g}' for d, u in missing)
        )

    n_units, n_ori = best_delay.shape
    nx, ny = len(x_positions), len(y_positions)
    p_values = np.full((n_units, n_ori), np.nan)
    mean_rate = np.full((n_units, n_ori), np.nan)
    mean_response = np.full((n_units, n_ori, nx, ny), np.nan)
    z_score = np.full((n_units, n_ori, nx, ny), np.nan)
    for unit in range(n_units):
        for ori in range(n_ori):
            if not np.isfinite(best_delay[unit, ori]):
                continue
            src = found[_window_key(best_delay[unit, ori], best_duration[unit, ori])]
            p_values[unit, ori] = src['p'][unit, ori]
            mean_rate[unit, ori] = src['rate'][unit, ori]
            mean_response[unit, ori] = src['mean'][unit, ori]
            z_score[unit, ori] = src['z'][unit, ori]

    output_path = Path(output_path).with_suffix('.h5')
    print(f'Saving fixed-window results to {output_path}...')
    with atomic_h5(output_path) as hf:
        for key, value in session_attrs.items():
            if key not in ('trial', 'n_presentations', 'date_optimized'):
                hf.attrs[key] = value
        if trial is not None:
            hf.attrs['trial'] = trial
        hf.attrs['date_optimized'] = datetime.today().strftime('%Y-%m-%d')
        hf.attrs['parameter_source'] = str(full_optimized)
        hf.attrs['parameters'] = 'full_run_delay_duration'
        hf.create_dataset('unit_names', data=unit_names)
        hf.create_dataset('orientations', data=orientations)
        hf.create_dataset('x_positions', data=x_positions)
        hf.create_dataset('y_positions', data=y_positions)
        hf.create_dataset('best_delay', data=best_delay)
        hf.create_dataset('best_duration', data=best_duration)
        hf.create_dataset('p_value', data=p_values)
        hf.create_dataset('mean_rate', data=mean_rate)
        hf.create_dataset('mean_response', data=mean_response,
                          compression='gzip', compression_opts=4)
        hf.create_dataset('z_score_response', data=z_score, compression='gzip', compression_opts=4)
    return output_path


def optimize_over_delay_duration(session_dir, pattern, output_path):
    """Reduce the pooled sweep files matching `pattern` in `session_dir` to one file.

    `pattern` is a glob selecting the files of a single probe / plane / DMD.
    Per-trial and optimized files are left out.
    """
    files = sorted(
        f for f in Path(session_dir).glob(pattern)
        if 'optimized' not in f.stem and '__trial_' not in f.stem
    )
    if not files:
        raise FileNotFoundError(f'No result files matching {pattern!r} in {session_dir}')
    return _optimize_probe_files(files, Path(output_path))
