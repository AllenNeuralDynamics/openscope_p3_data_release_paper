# Author: Marcel C. Raabe
# Date: 2026-10-29
"""Null distribution of the sweep-wide maximum |correlation| for mesoscope zebra sessions.

The mesoscope counterpart of `compute_null_distribution_ecephys.py`, which is the
reference for what the statistic is and why it is built this way: a single-step
maxT null for the maximum a unit attains over the whole search - every Gabor
filter x every (delay, duration) sweep point - so that thresholding at the
(1-alpha) quantile controls the family-wise error rate within a unit, with FDR
across units still to be applied on top. Everything structural is imported from
that script (library resolution, the normalised stimulus cache, the lag set, the
output format), so only what the modality forces is restated here.

Four things differ.

**Resampling.** The mesoscope samples at ~10 Hz against a 30 fps movie, so the
design matrix has one row per imaging sample, not one per movie frame:
`compute_waven_pipeline_mesoscope.py` looks up, for each sample, the frame shown
`delay` seconds earlier and averages dF/F (or events) over `duration` from that
sample. The stimulus rows are therefore a SELECTION of the decomposition, and
the selection moves with delay. That is what `null_scan_ophys` exists for - it
gathers and re-normalises the filter block per distinct selection, which is exact
against the same cached stimulus the ecephys scan uses (see its module
docstring). Durations at one delay share a selection, so a 6 x 3 sweep costs 6
gathers.

**Surrogates.** Rolling is along the imaging-sample axis, at ~10 Hz, so
`--min-lag-sec` converts with the imaging period rather than the movie's frame
period. A roll still preserves each trace's autocorrelation, its event
statistics and any slow drift exactly, and breaks only the pairing with the
stimulus.

**The screen.** There is no spike count to screen on, so units are screened on
activity: for `events`, samples holding a nonzero event; for `dff`, only
presence. A constant or non-finite trace is rejected either way - the first
because `_row_normalize` clamps a zero norm instead of raising, the second
because the windowed means run off cumulative sums and one NaN poisons every
window after it. The count that decided it is written to `n_spikes` (the dataset
name is shared with the ecephys file so both read alike; `activity_measure` in
the attributes says what it holds).

**Pooled repeats.** As in `compute_waven_pipeline_mesoscope.py`, the Zebra
repeats are pooled by default: their samples are stacked into one design matrix,
each matched to its movie frame through `TrialInSequence`; `--per-trial` gives
one null per repeat. Rolls run along the stacked samples.

**The stimulus cache is shared.** It is keyed on (movie, library, phase) alone,
so this reads the same `<znorm-dir>` copy the ecephys nulls built. Nothing has to
be prepared before a run: the first job to find it cold builds it (~50 GB per
phase, hours, no GPU needed), every later one finds it warm.

The sweep grid is `compute_waven_pipeline_mesoscope.py`'s own grid in full, not a
thinned version of it. At 0.03 s the delay step is already ~1 movie frame, so
there is nothing to thin, and the observed maximum then needs no restriction at
all: it is the maximum over every result file for that (plane, signal, trial,
phase). `optimize_waven_parameters.optimize_parameters` takes the grid from the
`sweep_delays` / `sweep_durations` attributes via `--sweep-from-null`.

Usage
-----
The session is streamed from DANDI by default, so --nwb-path is an asset path
inside the dandiset rather than a file on disk:

  python compute_null_distribution_mesoscope.py \
      --nwb-path sub-832700/sub-832700_ses-multiplane-ophys-832700-2026-01-24-12-06-12_ophys.nwb \
      --results-dir /path/allen/rf/zebra/nullresults/mesoscope/<session> \
      --plane-idx 0 --signal events

Add --local to read --nwb-path from disk instead.

Validation
----------
As for ecephys, run with `--n-surrogates 0` on a SINGLE sweep point:

  --delays 0.0 --durations 0.1 --n-surrogates 0 --phases 0

Then `family_max[:, :, 0].max(axis=1)` is what the matching rawresults file holds
in `abs_max_value`. Match the units by id, since the screen drops some - and note
the mesoscope rawresults write `unit_ids` as integers where the null writes
strings, so compare `raw['unit_ids'][:].astype(str)`. Agreement is ~1e-4, limited
by the float16 cache.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import null_scan_ophys as nso
import numpy as np
import torch
import utils
import waven_pipeline as wp
from compute_null_distribution_ecephys import (
    BUILD_FRAME_BLOCK,
    build_lags,
    build_znorm_stim,
    resolve_decomposition,
    save_null,
)
from null_scan_ophys import MIN_ACTIVE_SAMPLES
from waven_settings import movpath

MODALITY = 'mesoscope'

# Allen Open Scope multiplane ophys. Streaming is the default for the same reason
# as in the ecephys script: `open_session` falls back to disk whenever
# dandiset_id is None, and a local copy is easy to have lying around at a stale
# revision, so reading from disk has to be asked for with --local.
DEFAULT_DANDISET = '001768'

SIGNALS = ('events', 'dff')

# The sweep compute_waven_pipeline_mesoscope.py uses, imported rather than
# copied, so the null is always taken over the same test family as the observed
# maximum. Unlike the ecephys grid there is nothing to thin here - 0.03 s is
# about one movie frame - so the default stride is 1.
from compute_waven_pipeline_mesoscope import DELAYS as MESO_DELAYS  # noqa: E402
from compute_waven_pipeline_mesoscope import DURATIONS as MESO_DURATIONS  # noqa: E402

# Fewest imaging samples the Zebra block must contain before correlating is
# meaningful. A block is ~300 s and the mesoscope runs at ~10 Hz, so ~3000 is
# expected; anything near this floor means the imaging barely overlaps the block
# and the run is a mistake rather than a weak result.
MIN_SAMPLES = 300


def default_delays(stride: int) -> np.ndarray:
    """Every `stride`-th delay of the mesoscope pipeline's grid (all of them by default)."""
    if stride < 1:
        raise ValueError(f'delay stride must be at least 1, got {stride}')
    return MESO_DELAYS[::stride]


def response_points(times, signal, frame_onset_times, frame_index, delays, durations):
    """(delay, duration, cols, resp) for every sweep point.

    Mirrors the `mesoscope` branch of `waven_pipeline.full_pipeline` exactly -
    the same lookup, the same `keep` mask, the same windowed mean - because lag 0
    of the resulting scan has to reproduce what that branch already wrote to the
    result files.

    cols is the row of the decomposition each retained imaging sample looks up:
    the movie frame (`frame_index`) of the last onset strictly before
    `sample_time - delay`. It depends on delay only, so `group_sweep_points` will
    collapse the durations at one delay into a single gather.
    """
    frame_period = float(np.median(np.diff(frame_onset_times)))
    points = []
    for delay in delays:
        # the response at time t is attributed to the frame shown `delay` earlier
        t_lookup = times - delay
        idxs = np.searchsorted(frame_onset_times, t_lookup, side='left') - 1
        # the frame must still be on screen, as in full_pipeline
        keep = (idxs >= 0) & (
            t_lookup - frame_onset_times[np.maximum(idxs, 0)] < 1.5 * frame_period)
        n_kept = int(keep.sum())
        if n_kept < MIN_SAMPLES:
            raise ValueError(
                f'only {n_kept} imaging samples fall inside the Zebra block at delay '
                f'{delay} s (floor {MIN_SAMPLES}). The traces and the stimulus table '
                'do not describe the same stretch of the session.')
        cols = frame_index[idxs[keep]]
        for duration in durations:
            # average over `duration` from each retained sample; windows shorter
            # than the ~0.1 s imaging interval reduce to that single sample
            resp = wp.average_signal_over_window(times, signal, times[keep], duration)
            points.append((float(delay), float(duration), cols, resp))
    return points


def main(nwb_path, results_dir, plane_idx, signal='events',
         dandiset_id=DEFAULT_DANDISET, phases=('0', '1'), n_surrogates=300,
         min_lag_sec=1.0, delay_stride=1, delays=None, durations=None,
         family_axes=2, feat_block=16384, build_frame_block=BUILD_FRAME_BLOCK,
         lag_batch=8, znorm_dir=None, min_active=MIN_ACTIVE_SAMPLES,
         recompute=False, lib_id=None, allow_build=False, decomp_dir=None,
         build_cache_only=False, per_trial=False):

    if signal not in SIGNALS:
        raise ValueError(f'signal must be one of {SIGNALS}, got {signal!r}')

    results_dir = Path(results_dir)
    session_name = Path(nwb_path).stem

    print('Locating wavelet decompositions...')
    movie_path = Path(movpath)
    decomp_dir, lib_id = resolve_decomposition(lib_id, phases, movie_path,
                                               allow_build, decomp_dir)
    print(f'  lib {lib_id} at {decomp_dir}')

    # One cache serves every modality. Its content depends on (movie, library,
    # phase) and nothing else, and all three are in the filename, so this reads
    # whatever copy the ecephys runs already built rather than a mesoscope one of
    # its own. That is also why there is no prep job here: the first run to find
    # it cold builds it, and every later run of any modality finds it warm.
    znorm_root = Path(znorm_dir) if znorm_dir is not None else decomp_dir

    # The cache depends only on (movie, library, phase) - not on the session, the
    # plane, the signal or the sweep - and building it is pure numpy and I/O. So
    # it can be built once on a CPU node, before any GPU is allocated and without
    # touching DANDI at all. Returning here keeps the session, the traces and the
    # GPU entirely out of the prep step.
    if build_cache_only:
        print(f'Building the normalised cache only, into {znorm_root}')
        for phase in phases:
            build_znorm_stim(decomp_dir / f'dwt_videodata_{phase}.npy', znorm_root,
                             lib_id, movie_path.stem,
                             frame_block=build_frame_block)
        print('Cache ready; the per-plane array jobs can now run together.')
        return

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    if device.type == 'cpu':
        print('WARNING: no CUDA device — this will be far too slow for a full run.')

    if dandiset_id is None:
        print(f'Reading {nwb_path} FROM DISK (--local).')
    else:
        print(f'Streaming {nwb_path} from dandiset {dandiset_id}...')
    stream = utils.open_session(nwb_path, dandiset_id)

    planes = stream.imaging_planes()
    if plane_idx >= len(planes):
        raise IndexError(f'plane index {plane_idx} but this session has '
                         f'{len(planes)} planes: {planes}')
    plane = planes[plane_idx]
    traces_df = stream.dff_df(plane) if signal == 'dff' else stream.events_df(plane)
    all_unit_names = np.asarray(traces_df.index.to_numpy()).astype(str)
    all_times = traces_df.columns.to_numpy(dtype=float)
    all_traces = traces_df.to_numpy(dtype=np.float64)
    print(f'plane {plane}: {all_traces.shape[0]} ROIs, {all_traces.shape[1]} '
          f'{signal} samples')

    durations = (np.asarray(durations, dtype=float) if durations is not None
                 else MESO_DURATIONS)
    sweep_delays = (np.asarray(delays, dtype=float) if delays is not None
                    else default_delays(delay_stride))

    # filt_shape[-0:] is the whole shape, not an empty tuple, so family_axes=0
    # would silently make every filter its own family.
    if family_axes < 1:
        raise ValueError(f'family_axes must be at least 1, got {family_axes}')

    zebra_df = stream.zebra_df()
    # pooled (default): one block holding all Zebra repeats; per trial: one block
    # per repeat - the same blocks compute_waven_pipeline_mesoscope.py runs on
    for block in wp.zebra_blocks(zebra_df, per_trial):
        trial_part = block.trial_part
        frame_onset_times = block.frame_onset_times
        frame_index = block.frame_index
        i_trial, trialnumber = block.attributes['trial'], block.attributes['nwb_trialnumber']
        # zebra_blocks sorts by onset and keeps each row paired with its frame;
        # the lookup needs the onsets not to go BACKWARDS - np.searchsorted is
        # valid on a non-decreasing array, ties included.
        dt = np.diff(frame_onset_times)
        if np.any(dt < 0):
            raise ValueError(
                f'trial {i_trial}: the Zebra frame onsets go backwards at '
                f'{int((dt < 0).sum())} place(s), so they cannot be matched to the '
                'decomposition by position. Note compute_waven_pipeline_mesoscope.py '
                'looks them up with np.searchsorted, which needs a non-decreasing '
                'array too - the rawresults for this session would be wrong as well.')
        n_tied = int((dt == 0).sum())
        if n_tied:
            # Seen on sub-832700 trial 0, where the first two frames share an onset.
            # A tie makes that frame a zero-width interval, so the lookup never
            # returns it - one movie frame dropped out of 9000, which is why this
            # is a note rather than an error.
            print(f'  NOTE: {n_tied} pair(s) of Zebra frames share an onset time; '
                  f'{n_tied} frame(s) are unreachable by the lookup and contribute '
                  'to no response.')
        # positive diffs only, so a tie cannot drag the period down
        frame_period = float(np.median(dt[dt > 0]))

        # Restrict the traces to the block plus the widest window. The windowed
        # means are differences of cumulative sums over whatever is passed in, so
        # this changes no value - but it keeps a NaN elsewhere in the session from
        # reaching them, and it is what the screen below is applied to.
        margin = float(np.max(np.abs(sweep_delays)) + np.max(np.abs(durations)) + 1.0)
        win = ((all_times >= frame_onset_times[0] - margin)
               & (all_times <= frame_onset_times[-1] + margin))
        times = all_times[win]
        traces = all_traces[:, win]
        if times.size < MIN_SAMPLES:
            print(f'\ntrial {i_trial} (TrialNumber {trialnumber}): only {times.size} '
                  f'imaging samples in the block — skipping trial')
            continue
        sample_period = float(np.median(np.diff(times)))

        # Screened once per block on the whole block rather than per sweep point,
        # so the kept set is the same for every delay and duration and a maximum
        # over the sweep is well defined per unit.
        keep, n_active = nso.screen_units(traces, signal, min_active)
        unit_names = all_unit_names[keep]
        print(f'\ntrial {i_trial} (TrialNumber {trialnumber}): '
              f'{len(frame_onset_times)} movie frames, {frame_period * 1000:.2f} '
              f'ms/frame, {times.size} imaging samples, '
              f'{sample_period * 1000:.1f} ms/sample, '
              f'{keep.sum()} of {len(keep)} ROIs pass the screen '
              f'(>= {min_active} active {signal} samples, finite, non-constant)')
        if keep.sum() == 0:
            print('  no ROIs pass the screen — skipping trial')
            continue
        traces = traces[keep]

        for phase in phases:
            decomp_path = decomp_dir / f'dwt_videodata_{phase}.npy'
            # signal / plane / trial / phase / lib_<id> mirrors the rawresults
            # layout compute_waven_pipeline_mesoscope.py writes, so both trees
            # walk alike; the session belongs in --results-dir.
            out_path = (results_dir.joinpath(signal, plane, *trial_part, f'phase_{phase}')
                        / f'lib_{lib_id}' / f'null__lib_{lib_id}.h5')

            # Checked against the decomposition's header before anything is built:
            # normalising is a ~50 GB pass, and a wrong-movie run would otherwise
            # burn all of it before noticing.
            n_frames = int(np.load(decomp_path, mmap_mode='r').shape[0])
            if frame_index.max() >= n_frames:
                raise ValueError(
                    f'frame_index reaches {frame_index.max()} but the decomposition of '
                    f'{movie_path.name} has only {n_frames} frames; the onsets must '
                    'come from this movie.')

            if out_path.exists() and not recompute:
                stale = nso.stale_reason_ophys(
                    out_path, sweep_delays, durations, n_surrogates,
                    {'signal': signal, 'min_active_samples': min_active})
                if stale is None:
                    print(f'  phase {phase}: results exist at {out_path} — skipping')
                    continue
                # not unlinked here: save_null replaces it atomically, so an
                # interrupted recompute leaves the old file rather than nothing
                print(f'  phase {phase}: existing file at {out_path} does not match '
                      f'this run ({stale}) — recomputing')

            znorm_path, n_frames, filt_shape = build_znorm_stim(
                decomp_path, znorm_root, lib_id, movie_path.stem,
                frame_block=build_frame_block)

            # Families are the trailing `family_axes` of the filter grid. Filters
            # differing only in position share a null scale because the stimulus
            # is spatially homogeneous; sigma and frequency do not, because they
            # set the temporal autocorrelation and so the effective sample size.
            n_families = int(np.prod(filt_shape[-family_axes:]))
            n_filters = int(np.prod(filt_shape))

            points = response_points(times, traces, frame_onset_times, frame_index,
                                     sweep_delays, durations)
            groups = nso.group_sweep_points(points, device)
            del points
            grid = nso.sweep_grid(groups)
            n_used = [len(g.cols) for g in groups]

            # Lags are in imaging samples, not movie frames, and are built from
            # the SHORTEST sweep point so that every one of them stays a proper
            # roll there (see null_max_scan_subset). The lengths differ by only a
            # sample or two - `keep` moves with delay - so one lag is the same
            # physical shift at every sweep point.
            lags = build_lags(min(n_used), n_surrogates,
                              int(np.ceil(min_lag_sec / sample_period)))
            nso.warn_if_lags_collapsed(lags, n_surrogates)
            print(f'  phase {phase}: {n_filters} filters, {n_families} families, '
                  f'{len(sweep_delays)}x{len(durations)} sweep points in '
                  f'{len(groups)} row selections of {min(n_used)}-{max(n_used)} '
                  f'samples, {len(lags) - 1} surrogates')
            flops = nso.scan_flops(n_filters, groups, len(unit_names), len(lags))
            print(f'  ~{flops / 1e15:.1f} PFLOP '
                  f'(~{flops / 1e14 / 60:.0f} min at 100 TFLOP/s)')

            maxbuf = nso.null_max_scan_subset(
                znorm_path, groups, lags, n_families, device, feat_block, lag_batch,
                expect_shape=(n_filters, n_frames))
            del groups
            if device.type == 'cuda':
                torch.cuda.empty_cache()

            save_null(
                out_path, unit_names, n_active[keep], lags, lags * sample_period,
                maxbuf, grid, filt_shape, family_axes,
                attributes={
                    'session': session_name,
                    'modality': MODALITY,
                    'signal': signal,
                    'group': plane,
                    'plane': plane,
                    'library_id': lib_id,
                    'phase': phase,
                    'movie': movie_path.name,
                    'nwb_trialnumber': trialnumber,
                    'trial': i_trial,
                    'pooled_repeats': block.attributes['pooled_repeats'],
                    'n_repeats': block.attributes['n_repeats'],
                    'n_frames': n_frames,
                    'frame_period': frame_period,
                    'sample_period': sample_period,
                    'n_timepoints_min': int(min(n_used)),
                    'n_timepoints_max': int(max(n_used)),
                    'n_row_selections': len(n_used),
                    'n_surrogates': len(lags) - 1,
                    'min_lag_sec': min_lag_sec,
                    'min_active_samples': min_active,
                    # what the n_spikes dataset actually counts in this file
                    'activity_measure': ('nonzero event samples' if signal == 'events'
                                         else 'finite dff samples'),
                    'roll_axis': 'imaging samples',
                    'date_computed': datetime.today().strftime('%Y-%m-%d'),
                })


def _parse_floats(s):
    return None if s is None else np.array([float(v) for v in s.split(',')])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Null distribution of the sweep-wide max |correlation| per ROI, '
                    'mesoscope sessions.')
    parser.add_argument('--nwb-path', required=True)
    parser.add_argument('--results-dir', required=True)
    parser.add_argument('--plane-idx', required=True, type=int,
                        help='Index into NWBStream.imaging_planes()')
    parser.add_argument('--signal', default='events', choices=SIGNALS,
                        help="Trace to correlate: the OASIS-deconvolved 'events' "
                             "(default) or raw 'dff'. Each signal gets its own "
                             'subtree, as in the waven pipeline.')
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--dandiset-id', default=DEFAULT_DANDISET,
                        help='Dandiset to stream --nwb-path from as an asset path '
                             f'(default {DEFAULT_DANDISET}). Streaming is the '
                             'default so a stale local copy cannot be picked up by '
                             'accident.')
    source.add_argument('--local', action='store_true',
                        help='Read --nwb-path from disk instead of streaming.')
    parser.add_argument('--phases', default='0,1',
                        help="Wavelet phases to run, comma separated (default '0,1'). "
                             'The null is phase specific: a threshold from one phase '
                             'does not transfer to the other.')
    parser.add_argument('--n-surrogates', type=int, default=300,
                        help='Roll offsets besides lag 0 (default 300 - about one per '
                             'second of the Zebra block). The per-unit test needs far '
                             'fewer, but the p floor is 1/(1+N), and BH across ROIs '
                             'cannot reject until roughly n/(q*(1+N)) of them sit at '
                             'that floor; at N=100 that left a clearly responsive '
                             'ecephys probe with zero rejections.')
    parser.add_argument('--min-lag-sec', type=float, default=1.0,
                        help='Exclusion zone at both ends of the roll range, converted '
                             'with the IMAGING period (~0.1 s) rather than the movie '
                             'frame period. Not the spacing between surrogates - that '
                             'follows from --n-surrogates.')
    parser.add_argument('--delay-stride', type=int, default=1,
                        help='Take every Nth delay of the mesoscope pipeline grid. '
                             'Default 1 - the grid is already at ~1 movie frame per '
                             'step, so there is nothing to thin.')
    parser.add_argument('--delays', default=None,
                        help='Explicit delays in seconds, comma separated; '
                             'overrides --delay-stride.')
    parser.add_argument('--durations', default=None,
                        help='Explicit durations in seconds, comma separated.')
    parser.add_argument('--family-axes', type=int, default=2,
                        help='How many trailing filter axes define a family '
                             '(2 = sigma x frequency).')
    parser.add_argument('--feat-block', type=int, default=16384,
                        help='Filters per block in the scan. A GPU memory knob: each '
                             'block is held twice, once whole and once gathered to '
                             'the sweep point being scanned.')
    parser.add_argument('--build-frame-block', type=int, default=BUILD_FRAME_BLOCK,
                        help='Frames per chunk when building the normalised cache. '
                             'A memory knob only - the build reads sequentially '
                             'either way.')
    parser.add_argument('--lag-batch', type=int, default=8)
    parser.add_argument('--znorm-dir', default=None,
                        help='Where to cache the normalised stimulus. Shared with '
                             'every other modality - the cache is keyed on (movie, '
                             'library, phase) alone. Defaults to the decomposition '
                             'directory.')
    parser.add_argument('--min-active-samples', type=int, default=MIN_ACTIVE_SAMPLES,
                        help='Fewest active samples an ROI needs inside the Zebra '
                             "block: nonzero events for --signal events, finite "
                             'samples for --signal dff.')
    parser.add_argument('--recompute', action='store_true')
    parser.add_argument('--per-trial', action='store_true',
                        help='One null per Zebra repeat instead of pooling them. Must '
                             'match the waven run being thresholded.')
    parser.add_argument('--lib-id', default=None,
                        help='Use this existing library/decomposition instead of the '
                             'one the current waven_settings hashes to.')
    parser.add_argument('--allow-build', action='store_true',
                        help='Build the filter library and wavelet decomposition if '
                             'absent (~100 GB per phase, hours). Off by default so a '
                             'settings mismatch fails fast instead of starting one.')
    parser.add_argument('--build-cache-only', action='store_true',
                        help='Build the normalised stimulus cache for --phases and '
                             'exit. Needs no GPU, no DANDI access and no session.')
    parser.add_argument('--decomp-dir', default=None,
                        help='Directory holding dwt_videodata_{phase}.npy, bypassing '
                             'path derivation.')
    args = parser.parse_args()

    # An empty --dandiset-id would otherwise reach DandiSession('') and fail deep
    # in the DANDI client; the shell wrapper can produce one from DANDISET="".
    if not args.local and not args.dandiset_id:
        parser.error('--dandiset-id is empty; pass a dandiset or use --local')

    main(nwb_path=args.nwb_path, results_dir=args.results_dir,
         plane_idx=args.plane_idx, signal=args.signal,
         dandiset_id=None if args.local else args.dandiset_id,
         phases=tuple(args.phases.split(',')), n_surrogates=args.n_surrogates,
         min_lag_sec=args.min_lag_sec, delay_stride=args.delay_stride,
         delays=_parse_floats(args.delays), durations=_parse_floats(args.durations),
         family_axes=args.family_axes, feat_block=args.feat_block,
         build_frame_block=args.build_frame_block, lag_batch=args.lag_batch,
         znorm_dir=args.znorm_dir, min_active=args.min_active_samples,
         recompute=args.recompute, lib_id=args.lib_id,
         allow_build=args.allow_build, decomp_dir=args.decomp_dir,
         build_cache_only=args.build_cache_only, per_trial=args.per_trial)
