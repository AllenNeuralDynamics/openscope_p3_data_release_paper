# Author: Marcel C. Raabe
# Date: 2026-10-29
"""Shared machinery for the ophys null distributions (mesoscope and SLAP2).

`compute_null_distribution_ecephys.py` is the ecephys version and the reference for what
the null means; this module holds only what the two ophys modalities need on top
of it, and the two driver scripts
(`compute_null_distribution_mesoscope.py`, `compute_null_distribution_slap2.py`)
import the rest straight from it so the file layout, the lag construction and the
cache cannot drift between modalities.

One structural difference drives everything here. For spike times, every movie
frame is one row of the design matrix: the stimulus matrix is the whole
decomposition, it is the same for every sweep point, and so a single
row-normalised copy can be streamed once and multiplied against every response.
For both ophys modalities the rows are a SELECTION of frames that changes with
the sweep point - with delay on the mesoscope (the imaging samples are looked up
against shifted frame onsets), with delay and duration on SLAP2 (which frames
were imaged densely enough depends on the window). A Pearson correlation
normalises over the rows that are actually used, so the normalisation moves
inside the sweep.

That does not invalidate the cached stimulus, because the cache's normalisation
is a per-row affine map: `(x - mean_all) / norm_all`. Re-centring and
re-normalising a subset of those columns gives exactly
`(x_sub - mean_sub) / ||x_sub - mean_sub||`, the quantity Waven's
`_row_normalize` produces from the raw decomposition - the cache's own mean and
norm cancel. So one cache serves all three modalities - it is keyed on
(movie, library, phase) and nothing else, so the ecephys runs' copy is the one
these read - and the extra work per sweep point is one gather plus one row
normalisation of the filter block, on the GPU.

The other half of the module is the grouping that keeps that work down: sweep
points sharing a row selection share the gather. On the mesoscope the lookup
depends on delay alone, so every duration at one delay falls in one group, and a
6 x 3 sweep costs 6 gathers rather than 18.
"""

from __future__ import annotations

from dataclasses import dataclass

import h5py
import numpy as np
import torch

# Imported rather than restated: the responses must be normalised by exactly the
# same code as the cached stimulus was, or lag 0 stops reproducing the existing
# result files and the validation gate loses its meaning.
from compute_null_distribution_ecephys import _stale_reason, _znorm_rows
from tqdm import tqdm

# Fewest samples a unit must be active in before it is worth testing. The ophys
# counterpart of the ecephys script's MIN_SPIKES, and there for the same reason:
# `_row_normalize` clamps a vanishing norm instead of raising, so a dead ROI
# produces garbage correlations rather than an error - and costs the full
# surrogate budget to do it. What counts as "active" is per signal; see
# `activity_counts`.
MIN_ACTIVE_SAMPLES = 20


def activity_counts(signal: np.ndarray, kind: str) -> np.ndarray:
    """Per-unit activity count used to screen units, by signal type.

    events : samples holding a nonzero event. OASIS output is sparse and a
             fraction of ROIs never fire inside the Zebra block at all; those
             have a constant (zero) trace, which is the degenerate case the
             screen exists for.
    dff    : finite samples. dF/F is continuous, so counting "active" samples
             says nothing - the screen reduces to requiring a trace that is
             present at all, and degeneracy is caught by the variance test in
             `screen_units` instead.
    """
    if kind == 'events':
        return (np.nan_to_num(signal, nan=0.0) > 0).sum(axis=1)
    if kind == 'dff':
        return np.isfinite(signal).sum(axis=1)
    raise ValueError(f"signal must be 'events' or 'dff', got {kind!r}")


def screen_units(signal: np.ndarray, kind: str, min_active: int = MIN_ACTIVE_SAMPLES):
    """(keep, n_active) for a (n_units, n_times) block-restricted signal.

    Three things disqualify a unit: too little activity, a constant trace (zero
    norm, which `_row_normalize` would clamp rather than reject), and any
    non-finite sample - the windowed means run off cumulative sums, so one NaN
    poisons every window after it.

    Screening once per (plane, trial) rather than per sweep point keeps the unit
    set identical across the sweep, which is what makes a maximum over the sweep
    well defined per unit.
    """
    n_active = activity_counts(signal, kind)
    finite = np.isfinite(signal).all(axis=1)
    varies = np.nanstd(signal, axis=1) > 0
    return (n_active >= min_active) & finite & varies, n_active


def stale_reason_ophys(out_path, sweep_delays, durations, n_surrogates, must_match):
    """`_stale_reason`, plus the run parameters that change the design matrix.

    The base check covers the sweep grid and the surrogate count, which is all an
    ecephys run can disagree on without changing the path. The ophys runs have
    more: SLAP2's `--min-coverage` decides which movie frames survive,
    `--fps` moves the frame onsets, and
    `--signal` replaces the traces outright. None of those appears in the
    filename, so without this a second run with a different value prints
    "results exist - skipping" and hands back a null built from different data
    than the observed side it will be compared against - which is the failure the
    whole grid-matching discipline exists to prevent.

    `must_match` maps attribute name to the value this run would write; every one
    of them is already recorded by `save_null`.
    """
    base = _stale_reason(out_path, sweep_delays, durations, n_surrogates)
    if base is not None:
        return base
    try:
        with h5py.File(out_path, 'r') as hf:
            attrs = dict(hf.attrs)
    except OSError as e:
        return f'unreadable: {e}'
    for key, want in must_match.items():
        if key not in attrs:
            return f'{key} not recorded (written before this check existed)'
        got = attrs[key]
        if isinstance(want, (bool, int, float, np.bool_, np.integer, np.floating)):
            same = np.isclose(float(got), float(want))
        else:
            same = str(got) == str(want)
        if not same:
            return f'{key} {got!r} != {want!r}'
    return None


def scan_flops(n_filters, groups, n_units, n_lags):
    """Multiply-adds `null_max_scan_subset` will do.

    One GEMM per (filter block, group, response, lag), so the sweep enters as
    `len(cols) * len(responses)` summed over groups - NOT as the sum of the group
    lengths. Grouping collapses sweep points that share a row selection into one
    gather but still scans each of their responses, so summing lengths alone
    undercounts by the number of responses per group: threefold on the mesoscope,
    where all durations at one delay share a group.
    """
    per_sweep = sum(len(g.cols) * len(g.responses) for g in groups)
    return 2 * n_filters * n_units * n_lags * per_sweep


def warn_if_lags_collapsed(lags, n_surrogates):
    """Say so when fewer distinct rolls fit than were asked for.

    `build_lags` spreads its offsets evenly over the usable range and then drops
    duplicates, so a short design matrix yields fewer surrogates than requested:
    what fits is `min(n_surrogates, n_used - 2 * min_lag + 1)`, so the collapse
    starts once `n_used - 2 * min_lag` drops below `n_surrogates`.
    The test stays valid with whatever distinct rolls exist, but the file records
    the number it actually got, and `_stale_reason` treats a file holding fewer
    surrogates than the run asks for as stale. Left unsaid, that file would be
    recomputed on every re-submit.
    """
    got = len(lags) - 1
    if got < n_surrogates:
        print(f'  WARNING: only {got} distinct rolls fit, not the {n_surrogates} '
              f'requested - the design matrix is too short for that many. Pass '
              f'--n-surrogates {got} (or less) to stop this file being treated as '
              'stale and recomputed on every re-run.')
    return got


@dataclass
class SweepGroup:
    """Sweep points that share one selection of stimulus rows.

    cols      : (n_used,) rows of the wavelet decomposition, in design-matrix
                order. Repeats are allowed and expected - SLAP2 pools movie
                repeats, so the same stimulus row recurs.
    cols_t    : the same indices, resident on the scan's device.
    responses : row-normalised (n_units, n_used) response tensors on the device.
    points    : the (delay, duration) each response belongs to.
    """
    cols: np.ndarray
    cols_t: torch.Tensor
    responses: list
    points: list


def group_sweep_points(points, device) -> list[SweepGroup]:
    """Group (delay, duration, cols, resp) tuples by their row selection.

    `resp` is normalised here rather than by the caller because a circular roll
    changes neither a row's mean nor its norm: normalising once per sweep point
    is exact for every surrogate drawn from it.

    Grouping is by the exact bytes of `cols`. Two sweep points either use the
    same rows or they do not, and any near-miss simply costs one more gather -
    so there is no tolerance to choose here.
    """
    groups: dict[bytes, SweepGroup] = {}
    order: list[bytes] = []
    n_units = None
    for delay, duration, cols, resp in points:
        cols = np.ascontiguousarray(cols, dtype=np.int64)
        resp = np.asarray(resp)
        if resp.shape[1] != len(cols):
            raise ValueError(
                f'delay {delay}, duration {duration}: {resp.shape[1]} response '
                f'timepoints but {len(cols)} stimulus rows. The two must be the '
                'same samples in the same order.')
        if n_units is None:
            n_units = resp.shape[0]
        elif resp.shape[0] != n_units:
            raise ValueError(
                f'delay {delay}, duration {duration}: {resp.shape[0]} units but '
                f'{n_units} at the first sweep point; the unit set must be screened '
                'once for the whole sweep.')
        key = cols.tobytes()
        group = groups.get(key)
        if group is None:
            group = SweepGroup(cols, torch.as_tensor(cols, device=device), [], [])
            groups[key] = group
            order.append(key)
        group.responses.append(torch.as_tensor(_znorm_rows(resp), device=device))
        group.points.append((float(delay), float(duration)))
    if not order:
        raise ValueError('no sweep points to scan')
    return [groups[k] for k in order]


def sweep_grid(groups) -> list[tuple[float, float]]:
    """The (delay, duration) of every sweep point, in accumulation order.

    Grouping reorders the sweep relative to the nested delay/duration loops, so
    this - not the loops - is what the result file's `grid_delays` /
    `grid_durations` must record.
    """
    return [p for g in groups for p in g.points]


@torch.no_grad()
def null_max_scan_subset(znorm_path, groups, lags, n_families, device,
                         feat_block: int = 16384, lag_batch: int = 8,
                         expect_shape: tuple | None = None) -> np.ndarray:
    """Running maximum of |correlation| per (lag, unit, filter family).

    Returns (n_lags, n_units, n_families) float32, with column 0 of the lag axis
    the observed value and the rest the null - the same layout
    `compute_null_distribution_ecephys.null_max_scan` returns, so `save_null` writes both
    identically.

    The subset counterpart of that function: the filter axis is still the outer
    loop, so the ~50 GB cache streams exactly once, but each block is gathered
    and re-normalised per group before the GEMM. The reduction order is
    unchanged - a maximum over (filters x sweep points) is the maximum over sweep
    points of the maximum over filters - so one running buffer still suffices.

    `lags` must be valid for every group, i.e. strictly below the smallest
    `len(cols)`: a roll equal to a group's length is the identity and would
    inject the observed statistic into its own null. The caller builds the lags
    from that minimum; this only checks it.
    """
    stim = np.load(znorm_path, mmap_mode='r')
    if expect_shape is not None and stim.shape != tuple(expect_shape):
        raise ValueError(
            f'{znorm_path} is {stim.shape} but this run needs {tuple(expect_shape)}; '
            'the cache does not belong to the decomposition being read.')
    n_filters, n_frames = stim.shape
    n_units = groups[0].responses[0].shape[0]
    n_lags = len(lags)

    min_used = min(len(g.cols) for g in groups)
    max_row = max(int(g.cols.max()) for g in groups)
    if max_row >= n_frames:
        raise ValueError(
            f'a sweep point indexes stimulus row {max_row} but the cached '
            f'decomposition has {n_frames} frames; the frame onsets must come from '
            'the movie that was decomposed.')
    if n_lags > 1 and int(np.max(lags)) >= min_used:
        raise ValueError(
            f'lag {int(np.max(lags))} is not below the shortest sweep point '
            f'({min_used} timepoints); such a roll wraps to the identity for it and '
            'would put the observed statistic into its own null.')

    if n_filters % n_families:
        raise ValueError(
            f'{n_filters} filters is not a whole number of {n_families}-filter '
            'families; family_axes does not describe this filter grid.')
    if feat_block % n_families:
        feat_block -= feat_block % n_families
    if feat_block <= 0:
        raise ValueError(f'feat_block must be at least n_families={n_families}')

    maxbuf = torch.zeros(n_lags, n_units, n_families, device=device)
    full = np.arange(n_frames)

    for f0 in tqdm(range(0, n_filters, feat_block), desc='filter blocks'):
        f1 = min(f0 + feat_block, n_filters)
        n_block = f1 - f0
        # float16 on disk, float32 on device: the half precision is what makes the
        # cache fit and the upload cheap, while a float32 GEMM keeps the output off
        # the float16 grid so lag 0 can still be compared against the pipeline's
        # own result files.
        block = torch.as_tensor(np.array(stim[f0:f1]), device=device).float()

        for group in groups:
            # a fully covered SLAP2 session with one repeat uses every row in
            # order; clone rather than gather, to skip building the index tensor
            # and to keep the in-place normalisation below off `block` itself
            if len(group.cols) == n_frames and np.array_equal(group.cols, full):
                sub = block.clone()
            else:
                sub = block.index_select(1, group.cols_t)
            # the Pearson normalisation of the rows actually used; the cache's own
            # mean and norm cancel, see the module docstring
            sub -= sub.mean(dim=1, keepdim=True)
            sub /= sub.norm(dim=1, keepdim=True).clamp_(min=1e-8)

            for resp in group.responses:
                for l0 in range(0, n_lags, lag_batch):
                    sel = lags[l0:l0 + lag_batch]
                    rolled = torch.cat(
                        [torch.roll(resp, int(lag), dims=1) for lag in sel], dim=0)
                    corr = rolled @ sub.T                     # (B*n_units, n_block)
                    fam = (corr.abs()
                               .reshape(len(sel) * n_units,
                                        n_block // n_families, n_families)
                               .amax(dim=1)
                               .reshape(len(sel), n_units, n_families))
                    maxbuf[l0:l0 + len(sel)] = torch.maximum(
                        maxbuf[l0:l0 + len(sel)], fam)
                    del rolled, corr, fam
            del sub
        del block

    return maxbuf.cpu().numpy()
