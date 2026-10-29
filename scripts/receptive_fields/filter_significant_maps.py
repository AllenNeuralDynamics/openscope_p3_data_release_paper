# Author: Marcel C. Raabe
# Date: 2026-10-29
"""
Filter the rawresults down to the correlation maps that are significant.

A *map* is one spatial slice of a rawresults file,

    correlation_matrix[unit, :, :, theta, sigma, frequency]      at one (delay, duration),

and its statistic is max |r| over the (x, y) positions. One unit therefore has
n_thetas * n_sigmas * n_frequencies * n_delays * n_durations maps.

Test
----
The null files (compute_null_distribution*.py) hold, per unit, K circularly rolled
surrogates of the maximum over the WHOLE search - every filter at every sweep
point. Comparing a single map's maximum against that null is the single-step maxT
construction: the resulting p-value is already adjusted for every map of the unit
(all filters, all delays, all durations), so nothing more is owed inside a unit.
The null is read off a per-unit Gumbel fit to the K surrogate maxima, as in the
explore_null_results_* notebooks; the counted p is carried alongside and can be
used instead with --p-method count.

A unit's own p is the smallest p over its maps, i.e. the p of its sweep-wide
maximum - the per-unit statistic of the notebooks. Across units Benjamini-Hochberg
is applied at level q over ONE (session, signal, trial, phase), pooled over every
group of it (probes / planes / DMD x channel), or - with --bh-family group - over
each group on its own. The latter is what SLAP2 is run with: a DMD x channel is a
different indicator on a different sweep grid, so each plane and each channel gets
its own R, n and p*, and the many units of one cannot buy or cost discoveries in
another. Either way BH rejects R of the family's n units, and the map level cut is

    p* = q * max(R, 1) / n,        a map is significant  iff  p_map <= p*.

Only the units BH rejects can have significant maps, and inside them each map is
held to the stricter level p* (select-then-test, Benjamini & Bogomolov 2014). With
R = 0 no unit reaches q / n, so no map passes either; the max(R, 1) only keeps the
reported thresholds finite. Several maps of one unit, including the same filter at
different (delay, duration), are expected to pass.

Per unit the threshold is also written as a correlation value: `threshold` is the
max |r| a map of that unit has to reach to be significant (>= for the Gumbel p,
> for the counted p).

Only maps on the null's (delay, duration) grid are tested. Where a null covers only
part of the pipeline's grid (the first ephys nulls took every second delay), the
files in between are skipped, since the surrogates never saw them. The pass-1
cache holds the grid it was scanned on: after a null was extended, run once with
--recompute. Units the null screened out for too little activity
have no null and are not tested.

Check
-----
The largest map maximum of a unit IS the null file's lag 0, computed by different
code. The two must agree to float16 precision of the stored correlation matrix
(--check-tol, default 1e-3), or the null and the rawresults were made against
different libraries, movies or frame onsets - and the script stops.

Passes
------
1. Every rawresults file is scanned once, in parallel over files, keeping only the
   per-map max |r|, the position of the peak and its sign. This is cached per
   (group, trial, phase) as _cache/mapmax__<stem>.h5, so a rerun with a different q
   or cap does not re-read the correlation matrices (--recompute to force).
2. After BH, only the files that hold significant maps are opened again and only
   those maps cut out. At most --max-maps-per-unit maps are kept per unit (the
   strongest; default 100, 0 = all); the full count is still reported.

Layout
------
Run once per (session, signal); every (trial, phase) found under --null-dir is its
own BH family, and with --bh-family group every group of it as well. --raw-dir and
--null-dir are the matching session (and signal) roots: below them the two trees
are identical down to lib_<id>/. The files written are the same for both families;
unit_tests__*.csv still lists every group, each with the p* of its own family.

  <out-dir>/significant__<session>__<group>__<trial_<i>|pooled_trials>__phase_<p>.h5   per group
  <out-dir>/significant__<session>__<group>__<trial_<i>|pooled_trials>__phase_<p>.csv  its map table
  <out-dir>/unit_tests__<session>__<trial_<i>|pooled_trials>__phase_<p>.csv
                                                                    every tested unit

HDF5 contents
  /maps                (n_maps, nx, ny) float16, gzip - the significant maps (signed r)
  /maps_table/<col>    one dataset per column of the .csv, row-aligned with /maps
  /units/<col>         every tested unit of the group: p, q, threshold, counts
  attrs                q_level, p_method, bh_family, p_star, n_units_family,
                       n_significant_family, K, max_maps_per_unit, analysis_coverage,
                       null_file, ...

Usage
-----
  python filter_significant_maps.py \
      --raw-dir  .../zebra/rawresults/mesoscope/<session>/events \
      --null-dir .../zebra/nullresults/mesoscope/<session>/events \
      --out-dir  .../zebra/significant_results/mesoscope/<session>/events \
      --session  <session> --n-workers 128

  # SLAP2: every DMD x channel tested on its own
  python filter_significant_maps.py ... --bh-family group
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import os
from datetime import datetime
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
from tqdm import tqdm
from waven_settings import analysis_coverage

EULER = 0.5772156649015329                 # Euler-Mascheroni, for the Gumbel mean
Q_LEVEL = 0.05
MAX_MAPS_PER_UNIT = 100
CHECK_TOL = 1e-3                           # float16 spacing is 2.4e-4 at |r| ~ 0.3
UNIT_CHUNK = 8                             # units per read in pass 1, per worker


# ---------------------------------------------------------------------------
# statistics - the same definitions as the explore_null_results_* notebooks
# ---------------------------------------------------------------------------

def gumbel_mom(draws):
    """Method-of-moments Gumbel (mu, beta), one fit per ROW of `draws`."""
    beta = draws.std(axis=1, ddof=1) * np.sqrt(6) / np.pi
    return draws.mean(axis=1) - EULER * beta, beta


def gumbel_sf(x, mu, beta):
    """P(X > x) under Gumbel(mu, beta); expm1 keeps its digits when p is tiny."""
    return -np.expm1(-np.exp(-(x - mu) / beta))


def gumbel_isf(p, mu, beta):
    """The x with gumbel_sf(x) = p."""
    return mu - beta * np.log(-np.log1p(-p))


def count_p(x, sur):
    """Counted p of x (n_units, ...) against each unit's K draws sur (n_units, K)."""
    s = np.sort(sur, axis=1)
    K = s.shape[1]
    # number of draws >= x, per unit, for every x of that unit
    n_ge = np.stack([K - np.searchsorted(s[u], x[u].ravel(), side='left')
                     for u in range(len(s))]).reshape(x.shape)
    return (1 + n_ge) / (1 + K)


def count_threshold(sur, p_star):
    """The value a unit's max |r| must strictly exceed for its counted p <= p_star."""
    K = sur.shape[1]
    m = int(np.floor(p_star * (1 + K) + 1e-9)) - 1     # draws >= x still allowed
    if m < 0:                                           # below the floor 1/(1+K)
        return np.full(len(sur), np.inf)
    if m >= K:
        return np.full(len(sur), -np.inf)
    # x above the (m+1)-th largest draw has at most m draws >= it
    return -np.sort(-sur, axis=1)[:, m]


def bh_fdr(p):
    """Benjamini-Hochberg adjusted p-values (q-values)."""
    p = np.asarray(p, dtype=float)
    n = len(p)
    order = np.argsort(p)
    q = np.minimum.accumulate((n / np.arange(n, 0, -1)) * p[order][::-1])[::-1]
    out = np.empty(n)
    out[order] = np.minimum(q, 1.0)
    return out


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------

def _ids(ds) -> np.ndarray:
    """Unit ids as str. The mesoscope rawresults store ints where the null stores bytes."""
    return np.array([v.decode() if isinstance(v, bytes) else str(v) for v in ds[:]])


def discover(null_dir: Path, raw_dir: Path) -> list[dict]:
    """One entry per null file, with the rawresults files of the same (group, trial, phase, lib).

    Below the session (and signal) roots the two trees are identical:
        <group...>/[trial_<i>/ or pooled_trials/]phase_<p>/lib_<id>/
    so the group is whatever precedes the trial / phase level - a probe, a plane,
    or DMD/channel. `pooled_trials` (all Zebra repeats in one map) counts as a trial level.
    """
    jobs = []
    for f in sorted(null_dir.rglob('null__lib_*.h5')):
        rel = f.parent.relative_to(null_dir)
        parts = rel.parts
        lib, phase = parts[-1], parts[-2]
        has_trial = len(parts) >= 3 and (
            parts[-3].startswith('trial_') or parts[-3] == 'pooled_trials'
        )
        trial = parts[-3] if has_trial else None
        group = '_'.join(parts[:-3] if has_trial else parts[:-2])
        raw = sorted((raw_dir / rel).glob(f'*{lib}__delay_*__dur_*.h5'))
        jobs.append({'null_file': f, 'raw_files': raw, 'group': group, 'trial': trial,
                     'phase': phase, 'lib': lib, 'rel': rel,
                     'family': (trial, phase, lib)})
    return jobs


def stem_for(session, *parts) -> str:
    return '__'.join([session, *[p for p in parts if p]])


# ---------------------------------------------------------------------------
# pass 1: per-map maxima
# ---------------------------------------------------------------------------

def _on_grid(delay, duration, grid_pairs) -> bool:
    return bool(np.any(np.isclose(grid_pairs[:, 0], delay, atol=1e-6)
                       & np.isclose(grid_pairs[:, 1], duration, atol=1e-6)))


def scan_file(args):
    """Per-map max |r|, its (x, y) position and sign for every unit of one raw file.

    Returns None when the file's (delay, duration) is not on the null's grid.
    """
    path, grid_pairs, unit_chunk = args
    with h5py.File(path, 'r') as hf:
        delay = float(hf.attrs['delay'])
        duration = float(hf.attrs['duration'])
        if not _on_grid(delay, duration, grid_pairs):
            return None
        cm = hf['correlation_matrix']                  # (n, nx, ny, nt, ns, nf)
        n, nx, ny = cm.shape[:3]
        n_maps = int(np.prod(cm.shape[3:]))
        # read whole HDF5 chunks along the unit axis, or each is decompressed twice
        c0 = cm.chunks[0] if cm.chunks else 1
        step = c0 * int(np.ceil(unit_chunk / c0))

        peak = np.empty((n, n_maps), np.float32)
        pos = np.empty((n, n_maps), np.int32)          # flat index into (nx, ny)
        sign = np.empty((n, n_maps), np.int8)
        for u0 in range(0, n, step):
            blk = cm[u0:u0 + step].astype(np.float32).reshape(-1, nx * ny, n_maps)
            a = np.abs(blk)
            am = a.argmax(axis=1)                      # (b, n_maps)
            peak[u0:u0 + step] = np.take_along_axis(a, am[:, None, :], 1)[:, 0]
            sign[u0:u0 + step] = np.sign(np.take_along_axis(blk, am[:, None, :], 1)[:, 0])
            pos[u0:u0 + step] = am
        return {'path': str(path), 'delay': delay, 'duration': duration,
                'unit_ids': _ids(hf['unit_ids']), 'peak': peak, 'pos': pos, 'sign': sign,
                'shape': tuple(int(s) for s in cm.shape[1:]),
                'thetas': np.asarray(hf.attrs['thetas'], float),
                'sigmas': np.asarray(hf.attrs['sigmas'], float),
                'frequencies': np.asarray(hf.attrs['frequencies'], float)}


def _file_sig(paths) -> np.ndarray:
    """What the cache is keyed on: every raw file with its size and mtime."""
    return np.array([f'{p}|{os.path.getsize(p)}|{os.path.getmtime(p):.0f}' for p in paths],
                    dtype=object)


def load_cache(cache_path: Path, raw_files):
    if not cache_path.exists():
        return None
    with h5py.File(cache_path, 'r') as hf:
        if list(hf['file_sig'][:].astype(str)) != list(_file_sig(raw_files).astype(str)):
            return None
        out = {k: hf[k][:] for k in ('peak', 'pos', 'sign', 'delays', 'durations',
                                     'thetas', 'sigmas', 'frequencies')}
        out['unit_ids'] = _ids(hf['unit_ids'])
        out['paths'] = hf['paths'][:].astype(str)
        out['shape'] = tuple(int(s) for s in hf.attrs['shape'])
    return out


def save_cache(cache_path: Path, raw_files, mm):
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix('.h5.tmp')
    dt = h5py.string_dtype()
    with h5py.File(tmp, 'w') as hf:
        hf.create_dataset('file_sig', data=list(_file_sig(raw_files)), dtype=dt)
        hf.create_dataset('unit_ids', data=list(mm['unit_ids']), dtype=dt)
        hf.create_dataset('paths', data=list(mm['paths']), dtype=dt)
        for k in ('peak', 'pos', 'sign'):
            hf.create_dataset(k, data=mm[k], compression='gzip', compression_opts=4)
        for k in ('delays', 'durations', 'thetas', 'sigmas', 'frequencies'):
            hf.create_dataset(k, data=mm[k])
        hf.attrs['shape'] = mm['shape']
    tmp.rename(cache_path)


def assemble(results: list[dict]) -> dict:
    """Stack the per-file scans of one group to (n_units, n_files, n_maps)."""
    results = sorted(results, key=lambda r: (r['delay'], r['duration']))
    ids = results[0]['unit_ids']
    for r in results[1:]:
        if not np.array_equal(r['unit_ids'], ids):
            raise ValueError(f'unit_ids differ between {results[0]["path"]} and {r["path"]}')
        if r['shape'] != results[0]['shape']:
            raise ValueError(f'correlation_matrix shape differs in {r["path"]}')
    return {'unit_ids': ids,
            'peak': np.stack([r['peak'] for r in results], axis=1),
            'pos': np.stack([r['pos'] for r in results], axis=1),
            'sign': np.stack([r['sign'] for r in results], axis=1),
            'delays': np.array([r['delay'] for r in results]),
            'durations': np.array([r['duration'] for r in results]),
            'paths': np.array([r['path'] for r in results]),
            'shape': results[0]['shape'],
            'thetas': results[0]['thetas'], 'sigmas': results[0]['sigmas'],
            'frequencies': results[0]['frequencies']}


# ---------------------------------------------------------------------------
# null side
# ---------------------------------------------------------------------------

def load_null(path: Path) -> dict:
    with h5py.File(path, 'r') as hf:
        fm = hf['family_max'][:]
        out = {'unit_ids': _ids(hf['unit_ids']), 'n_active': hf['n_spikes'][:],
               'grid_pairs': np.stack([np.asarray(hf.attrs['grid_delays'], float),
                                       np.asarray(hf.attrs['grid_durations'], float)], axis=1),
               'filter_shape': tuple(int(s) for s in hf.attrs['filter_shape'])}
    if fm.shape[2] < 2:
        raise ValueError(f'{path} holds no surrogates.')
    out['max_obs_null'] = fm[:, :, 0].max(axis=1)
    out['M_sur'] = fm[:, :, 1:].max(axis=1)             # (n_units, K)
    return out


def unit_tests(job, nd, mm, p_method, check_tol):
    """Per-unit statistic and p for one group, plus the per-map p-values.

    Returns (units DataFrame, map_p (n_units, n_files, n_maps), map_pc, rows into mm).
    """
    # every tested unit must have raw maps; raw units without a null are untested
    row_of = {u: i for i, u in enumerate(mm['unit_ids'])}
    missing = [u for u in nd['unit_ids'] if u not in row_of]
    if missing:
        raise ValueError(f'{len(missing)} null units have no rawresults in {job["rel"]}: '
                         f'{missing[:5]}')
    rows = np.array([row_of[u] for u in nd['unit_ids']])

    if tuple(mm['shape']) != nd['filter_shape']:
        raise ValueError(f'{job["rel"]}: rawresults filter grid {mm["shape"]} != null '
                         f'{nd["filter_shape"]}')

    peak = mm['peak'][rows]                              # (n_units, n_files, n_maps)
    max_raw = peak.reshape(len(rows), -1).max(axis=1)
    diff = np.abs(max_raw - nd['max_obs_null'])
    if diff.max() > check_tol:
        worst = np.argsort(diff)[::-1][:5]
        raise ValueError(
            f'{job["rel"]}: the rawresults maximum disagrees with the null lag 0 by up to '
            f'{diff.max():.2e} (tol {check_tol:.0e}), e.g. units '
            f'{[str(u) for u in nd["unit_ids"][worst]]}. The null and the rawresults were '
            'not computed '
            'on the same library / movie / frame onsets / grid; nothing here is valid.')

    sur = nd['M_sur']
    mu, beta = gumbel_mom(sur)
    p_fit_map = gumbel_sf(peak, mu[:, None, None], beta[:, None, None])
    p_cnt_map = count_p(peak, sur)

    units = pd.DataFrame({
        'group': job['group'],
        'unit_id': nd['unit_ids'],
        'n_active': nd['n_active'],
        'max_obs': max_raw,
        'max_obs_null': nd['max_obs_null'],
        'null_mean': sur.mean(axis=1),
        'null_p95': np.quantile(sur, 0.95, axis=1),
        'mu': mu,
        'beta': beta,
        'p_fit': gumbel_sf(max_raw, mu, beta),
        'p_count': count_p(max_raw[:, None], sur)[:, 0],
    })
    units['p'] = units['p_fit'] if p_method == 'gumbel' else units['p_count']
    return units, p_fit_map, p_cnt_map, rows


# ---------------------------------------------------------------------------
# pass 2: cut out the selected maps
# ---------------------------------------------------------------------------

def extract_maps(args):
    """The (nx, ny) maps asked for from one raw file. requests: [(out_idx, row, map_idx)]."""
    path, requests = args
    out = []
    with h5py.File(path, 'r') as hf:
        cm = hf['correlation_matrix']
        nx, ny = cm.shape[1:3]
        by_row: dict[int, list] = {}
        for k, row, m in requests:
            by_row.setdefault(row, []).append((k, m))
        for row, items in by_row.items():
            block = cm[row].reshape(nx, ny, -1)          # one unit, all its maps
            for k, m in items:
                out.append((k, block[:, :, m]))
    return out


def select_maps(job, units, mm, rows, p_map, p_fit_map, p_cnt_map, p_star, cap):
    """The table of significant maps of one group, strongest first per unit, capped."""
    nx, ny, nt, ns, nf = mm['shape']
    u_idx, f_idx, m_idx = np.nonzero(p_map <= p_star)
    r_idx = rows[u_idx]                                  # the unit's row in the raw files
    peak = mm['peak'][r_idx, f_idx, m_idx]
    ti, si, fi = np.unravel_index(m_idx, (nt, ns, nf))
    xi, yi = np.unravel_index(mm['pos'][r_idx, f_idx, m_idx], (nx, ny))
    xM, xm, yM, ym = analysis_coverage
    tab = pd.DataFrame({
        'unit_id': units['unit_id'].to_numpy()[u_idx],
        'delay': mm['delays'][f_idx],
        'duration': mm['durations'][f_idx],
        'theta_idx': ti, 'sigma_idx': si, 'frequency_idx': fi,
        'theta_rad': mm['thetas'][ti], 'sigma': mm['sigmas'][si],
        'frequency': mm['frequencies'][fi],
        'xi': xi, 'yi': yi,
        # waven's PearsonCorrelationPinkNoise convention for the best position
        'x_deg': np.abs(xi) * (abs(xm - xM) / nx) + xM,
        'y_deg': np.abs(yi - ny) * (abs(yM - ym) / ny) + ym,
        'peak_sign': mm['sign'][r_idx, f_idx, m_idx],
        'max_abs': peak,
        'p_fit': p_fit_map[u_idx, f_idx, m_idx],
        'p_count': p_cnt_map[u_idx, f_idx, m_idx],
        'source_file': mm['paths'][f_idx],
        '_row': r_idx,
        '_map': m_idx,
    })
    tab = tab.sort_values(['unit_id', 'max_abs'], ascending=[True, False], kind='stable')
    tab['rank_in_unit'] = tab.groupby('unit_id').cumcount()
    n_sig = tab.groupby('unit_id').size()
    if cap > 0:
        tab = tab[tab.rank_in_unit < cap]
    return tab.reset_index(drop=True), n_sig


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------

_MAP_COLS = ['unit_id', 'delay', 'duration', 'theta_idx', 'sigma_idx', 'frequency_idx',
             'theta_rad', 'sigma', 'frequency', 'xi', 'yi', 'x_deg', 'y_deg', 'peak_sign',
             'max_abs', 'p_fit', 'p_count', 'rank_in_unit', 'source_file']


def write_group(out_path: Path, tab: pd.DataFrame, maps: np.ndarray, units: pd.DataFrame,
                attrs: dict, shape):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix('.h5.tmp')
    dt = h5py.string_dtype()
    try:
        with h5py.File(tmp, 'w') as hf:
            for k, v in attrs.items():
                hf.attrs[k] = v
            hf.create_dataset('maps', data=maps.reshape(-1, *shape[:2]).astype(np.float16),
                              compression='gzip', compression_opts=4)
            g = hf.create_group('maps_table')
            for c in _MAP_COLS:
                v = tab[c].to_numpy()
                if v.dtype == object:
                    g.create_dataset(c, data=[str(s) for s in v], dtype=dt)
                else:
                    g.create_dataset(c, data=v)
            g = hf.create_group('units')
            for c in units.columns:
                v = units[c].to_numpy()
                if v.dtype == object:
                    g.create_dataset(c, data=[str(s) for s in v], dtype=dt)
                else:
                    g.create_dataset(c, data=v)
        if out_path.exists():
            out_path.unlink()
        tmp.rename(out_path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    tab[_MAP_COLS].to_csv(out_path.with_suffix('.csv'), index=False)


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------

def run_family(fam_jobs, pool, session, out_dir, q_level, p_method, bh_family, cap,
               check_tol, unit_chunk, recompute):
    """Test one BH family and write its groups. Returns the table of its tested units."""
    trial, phase, lib = (fam_jobs[0][k] for k in ('trial', 'phase', 'lib'))
    who = (fam_jobs[0]['group'] if bh_family == 'group' else f'{len(fam_jobs)} groups')
    print(f'\n=== {trial or "pooled repeats"}, {phase}, {lib}: {who} ===')

    # ---- pass 1 (or cache) ------------------------------------------------
    nulls = [load_null(j['null_file']) for j in fam_jobs]
    mms: list[dict | None] = [None] * len(fam_jobs)
    todo = []
    for gi, (job, nd) in enumerate(zip(fam_jobs, nulls, strict=False)):
        if not job['raw_files']:
            raise FileNotFoundError(f'no rawresults for {job["rel"]}')
        job['cache'] = (
            out_dir / '_cache' / f'mapmax__{stem_for(session, job["group"], trial, phase)}.h5'
        )
        mms[gi] = None if recompute else load_cache(job['cache'], job['raw_files'])
        if mms[gi] is None:
            todo += [(gi, (p, nd['grid_pairs'], unit_chunk)) for p in job['raw_files']]
        else:
            print(f'  {job["group"]}: pass 1 from cache')

    if todo:
        scanned: dict[int, list] = {}
        gi_of = {str(a[0]): gi for gi, a in todo}
        it = pool.imap_unordered(scan_file, [a for _, a in todo])
        for r in tqdm(it, total=len(todo), desc='pass 1: map maxima'):
            if r is not None:
                scanned.setdefault(gi_of[r['path']], []).append(r)
        for gi in {gi for gi, _ in todo}:
            job = fam_jobs[gi]
            if gi not in scanned:
                raise FileNotFoundError(f'no rawresults on the null grid for {job["rel"]}')
            mms[gi] = assemble(scanned[gi])
            save_cache(job['cache'], job['raw_files'], mms[gi])

    # ---- per-unit test, BH over the family ---------------------------------
    parts = []
    for job, nd, mm in zip(fam_jobs, nulls, mms, strict=False):
        got = {
            (round(d, 6), round(u, 6))
            for d, u in zip(mm['delays'], mm['durations'], strict=False)
        }
        want = {(round(d, 6), round(u, 6)) for d, u in nd['grid_pairs']}
        if want - got:
            print(f'  WARNING {job["group"]}: no rawresults for grid points '
                  f'{sorted(want - got)}; fewer maps tested than the null covers.')
        parts.append(unit_tests(job, nd, mm, p_method, check_tol))

    fam_units = pd.concat([u for u, *_ in parts], ignore_index=True)
    n = len(fam_units)
    fam_units['q'] = bh_fdr(fam_units['p'])
    fam_units['significant'] = fam_units['q'] <= q_level
    R = int(fam_units['significant'].sum())
    p_star = q_level * max(R, 1) / n
    K = nulls[0]['M_sur'].shape[1]
    print(f'  BH ({p_method} p) over {n} units: {R} significant, p* = {p_star:.3e}')

    # ---- select maps, pass 2 -----------------------------------------------
    offset = 0
    tables, requests = [], {}
    for job, nd, mm, (units, p_fit_map, p_cnt_map, rows) in zip(
        fam_jobs, nulls, mms, parts, strict=False
    ):
        u = fam_units.iloc[offset:offset + len(units)].reset_index(drop=True)
        offset += len(units)
        u['p_star'] = p_star
        u['threshold'] = (gumbel_isf(p_star, u['mu'], u['beta']) if p_method == 'gumbel'
                          else count_threshold(nd['M_sur'], p_star))
        p_map = p_fit_map if p_method == 'gumbel' else p_cnt_map
        tab, n_sig = select_maps(job, u, mm, rows, p_map, p_fit_map, p_cnt_map, p_star, cap)
        u['n_sig_maps'] = u['unit_id'].map(n_sig).fillna(0).astype(int)
        u['n_saved_maps'] = np.minimum(u['n_sig_maps'], cap) if cap > 0 else u['n_sig_maps']
        tab['_k'] = np.arange(len(tab)) + sum(len(t) for _, t, _ in tables)
        for path, grp in tab.groupby('source_file'):
            requests.setdefault(path, []).extend(
                zip(grp['_k'], grp['_row'], grp['_map'], strict=False)
            )
        tables.append((job, tab, u))

    n_maps = sum(len(t) for _, t, _ in tables)
    shape = mms[0]['shape']
    maps = np.zeros((n_maps, shape[0], shape[1]), np.float16)
    if requests:
        it = pool.imap_unordered(extract_maps, list(requests.items()))
        for res in tqdm(it, total=len(requests), desc='pass 2: cut out maps'):
            for k, m in res:
                maps[k] = m

    # ---- write -------------------------------------------------------------
    k0 = 0
    for (job, tab, u), _nd, mm in zip(tables, nulls, mms, strict=False):
        attrs = {
            'session': session, 'group': job['group'], 'trial': trial or '',
            'phase': phase, 'lib_id': lib.split('_', 1)[1],
            'q_level': q_level, 'p_method': p_method, 'bh_family': bh_family,
            'p_star': p_star,
            'n_units_family': n, 'n_significant_family': R, 'K': K,
            'max_maps_per_unit': cap,
            'analysis_coverage': np.asarray(analysis_coverage, float),
            'delays_tested': np.unique(mm['delays']),
            'durations_tested': np.unique(mm['durations']),
            'null_file': str(job['null_file']),
            'raw_dir': str(job['raw_files'][0].parent),
            'date_computed': datetime.today().strftime('%Y-%m-%d'),
        }
        out = out_dir / f'significant__{stem_for(session, job["group"], trial, phase)}.h5'
        write_group(out, tab, maps[k0:k0 + len(tab)], u, attrs, shape)
        k0 += len(tab)
        print(f'  {job["group"]:>14s}: {int(u.significant.sum()):4d}/{len(u):4d} units, '
              f'{int(u.n_sig_maps.sum()):7d} maps significant, {len(tab):6d} saved -> {out.name}')

    return pd.concat([u for _, _, u in tables], ignore_index=True)


def main():
    parser = argparse.ArgumentParser(
        description='Keep the rawresults correlation maps whose max |r| is significant '
                    '(maxT within a unit, BH across the units of one session/signal/trial/phase, '
                    'or of each group of it).')
    parser.add_argument('--raw-dir', required=True, type=Path,
                        help='rawresults root of ONE session (and signal), e.g. '
                             '.../rawresults/mesoscope/<session>/events')
    parser.add_argument('--null-dir', required=True, type=Path,
                        help='The matching nullresults root, e.g. '
                             '.../nullresults/mesoscope/<session>/events')
    parser.add_argument('--out-dir', required=True, type=Path,
                        help='Where the significant maps go, e.g. '
                             '.../significant_results/mesoscope/<session>/events')
    parser.add_argument('--session', required=True, help='Session name, used in file names')
    parser.add_argument('--q', type=float, default=Q_LEVEL, help='BH level (default 0.05)')
    parser.add_argument('--p-method', choices=['gumbel', 'count'], default='gumbel',
                        help='Gumbel-fitted (default) or counted p-values')
    parser.add_argument('--bh-family', choices=['session', 'group'], default='session',
                        help='What BH runs over: every group of a (trial, phase) pooled '
                             '(default), or each group - probe / plane / DMD x channel - '
                             'on its own, as for SLAP2')
    parser.add_argument('--max-maps-per-unit', type=int, default=MAX_MAPS_PER_UNIT,
                        help='Keep at most this many significant maps per unit, strongest '
                             'first (default 100; 0 keeps all)')
    parser.add_argument('--check-tol', type=float, default=CHECK_TOL,
                        help='Allowed |rawresults max - null lag 0| per unit')
    parser.add_argument('--n-workers', type=int,
                        default=int(os.environ.get('SLURM_CPUS_PER_TASK', os.cpu_count())))
    parser.add_argument('--unit-chunk', type=int, default=UNIT_CHUNK,
                        help='Units read at once per worker in pass 1 (memory vs. speed)')
    parser.add_argument('--recompute', action='store_true',
                        help='Ignore the pass-1 cache and re-read every rawresults file')
    args = parser.parse_args()

    jobs = discover(args.null_dir, args.raw_dir)
    if not jobs:
        raise FileNotFoundError(f'no null__lib_*.h5 under {args.null_dir}')
    families: dict[tuple, list] = {}
    for j in jobs:
        key = j['family'] + ((j['group'],) if args.bh_family == 'group' else ())
        families.setdefault(key, []).append(j)
    print(f'{len(jobs)} null files in {len(families)} BH families (one per '
          f'{"group" if args.bh_family == "group" else "session"}) under {args.null_dir}')
    print(f'{sum(len(j["raw_files"]) for j in jobs)} rawresults files under {args.raw_dir}')
    print(f'{args.n_workers} workers, q = {args.q}, p = {args.p_method}, '
          f'cap = {args.max_maps_per_unit or "none"}')

    args.out_dir.mkdir(parents=True, exist_ok=True)
    unit_tables: dict[str, list] = {}
    with mp.get_context('fork').Pool(args.n_workers) as pool:
        for key in sorted(families, key=lambda k: tuple(str(x) for x in k)):
            fam = families[key]
            units = run_family(fam, pool, args.session, args.out_dir, args.q,
                               args.p_method, args.bh_family, args.max_maps_per_unit,
                               args.check_tol, args.unit_chunk, args.recompute)
            # one table per (trial, phase) whatever the family; rewritten after each
            # family, so with --bh-family group it grows group by group
            name = f'unit_tests__{stem_for(args.session, fam[0]["trial"], fam[0]["phase"])}.csv'
            unit_tables.setdefault(name, []).append(units)
            pd.concat(unit_tables[name], ignore_index=True).to_csv(args.out_dir / name,
                                                                  index=False)


if __name__ == '__main__':
    main()
