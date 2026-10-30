# Author: Marcel C. Raabe
# Date: 2026-10-29
"""Null distribution of the sweep-wide maximum |correlation| for SLAP2 zebra sessions.

The SLAP2 counterpart of `compute_null_distribution_ecephys.py`, which is the reference
for what the statistic is: a single-step maxT null for the maximum a unit attains
over the whole search - every Gabor filter x every (delay, duration) sweep point -
so that thresholding at the (1-alpha) quantile controls the family-wise error rate
within a unit, with FDR across units still to be applied on top. The library
resolution, the normalised stimulus cache, the lag set and the output format are
imported from that script, so only what the modality forces is restated here.

What differs, beyond the ophys changes shared with the mesoscope null
(`null_scan_ophys`):

**The design matrix is the imaged frames only.** SLAP2 samples at ~200 Hz against
a 30 fps movie, so `compute_waven_pipeline_slap2.py` resamples frame-first: one
response per movie frame, averaged over [onset + delay, onset + delay + duration).
Imaging runs in bouts with blanking in between, so most frames of a session are
not sampled at all, and a frame whose response window is not covered densely
enough is dropped from stimulus and response alike rather than filled in. Which
frames survive depends on BOTH delay and duration, so - unlike the mesoscope,
where the selection depends on delay alone - most sweep points get their own row
selection and their own gather.

**Repeats are pooled by default,** as in the pipeline: a single repeat may retain
too few imaged frames to correlate against, so all repeats go into one design
matrix and `frame_index` maps each onset back to its row of the decomposition.
`--per-trial` restores one null per repeat, which is what a repeatability check
needs.

**Rolls are along the retained-frame axis.** `--min-lag-sec` converts with the
movie frame period, which is a LOWER bound on the shift a roll produces: the
retained frames are a subset of a uniform 30 Hz grid, so consecutive retained
frames are at least 1/fps apart and the blanking gaps only stretch that. A roll of
k retained frames is therefore a shift of at least k/fps seconds, which is what
the min-lag guarantee needs. `lag_seconds` in the output is that lower bound.

One caveat of pooling. `zebra_frame_times` restarts `frame` at 0 for each repeat,
so with R repeats the stimulus is periodic in design-matrix position with period
~L = (retained frames)/R. A roll of about L therefore re-pairs each response with
nearly the frame it actually saw, and such a surrogate carries real signal into
the null. It is conservative - it can only raise a p-value - and at 300 evenly
spread rolls only a couple land close enough to L to matter, but it is the one
place the "a roll breaks the pairing with the stimulus" argument does not hold
exactly. `--per-trial` avoids it entirely.

**Each channel has its own grid,** copied from the pipeline: green is iGluSnFR4f
and resolves single movie frames, red is RCaMP3 whose calcium kinetics blur the
response across frames no matter which window is chosen. Both grids are used in
full - nothing is thinned - so the observed maximum needs no restriction beyond
ignoring the grid cells the pipeline itself skipped for lack of coverage.

The stimulus cache is shared with the other modalities - it is keyed on (movie,
library, phase) alone - so nothing has to be prepared before a run: the first job
to find it cold builds it, every later one finds it warm.

Usage
-----
  python compute_null_distribution_slap2.py \
      --nwb-path sub-829704/sub-829704_ses-829704-2025-12-18-10-57-36_image+ophys.nwb \
      --results-dir /path/allen/rf/zebra/nullresults/slap2/<session> \
      --dmd DMD1 --channel green --signal events

Add --local to read --nwb-path from disk instead.

Validation
----------
As for ecephys, run with `--n-surrogates 0` on a SINGLE sweep point:

  --delays 0.0 --durations 0.0333333 --n-surrogates 0 --phases 0

Then `family_max[:, :, 0].max(axis=1)` is what the matching rawresults file holds
in `abs_max_value`, provided the two agree on coverage - so pass the same
--min-coverage as that run. Match the units by
id, since the screen drops some. Agreement is ~1e-4, limited by the float16 cache.
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
from utils import deconvolution
from waven_pipeline import MIN_COVERED_FRAMES
from waven_settings import movpath

MODALITY = 'slap2'

# Allen Open Scope SLAP2. Streaming is the default for the same reason as in the
# ecephys script: `open_session` falls back to disk whenever dandiset_id is None,
# so reading a local copy has to be asked for with --local.
DEFAULT_DANDISET = '001424'

SIGNALS = ('events', 'dff')

# The per-channel grids compute_waven_pipeline_slap2.py uses, imported rather
# than copied, so the null is always taken over the same test family as the
# observed maximum.
from compute_waven_pipeline_slap2 import GRIDS  # noqa: E402


def load_signal(stream, dmd, channel, t_start, t_stop, signal='events', nwb_path=None):
    """(traces_df, unit_names) for one DMD/channel over [t_start, t_stop].

    The same loader compute_waven_pipeline_slap2.py uses, including the ROI naming,
    so the unit ids in the null file are the ones in the result files. Only the
    Zebra block is read: the full-session traces are several hundred MB per
    channel.
    """
    if signal == 'dff':
        traces_df = stream.slap2_dff(dmd, channel, t_start=t_start, t_stop=t_stop)
    elif signal == 'events':
        traces_df = deconvolution.slap2_events_df(nwb_path, dmd, channel,
                                                  t_start=t_start, t_stop=t_stop,
                                                  stream=stream)
    else:
        raise ValueError(f"signal must be one of {SIGNALS}, got {signal!r}")

    roi_ids = stream.slap2_rois(dmd)['roi_id'].to_numpy()
    unit_names = np.array([f'{dmd}_{channel}_roi{roi_id}' for roi_id in roi_ids])
    return traces_df, unit_names


def coverage_masks(times, valid, frame_onset_times, delays, durations, min_coverage):
    """[(delay, duration, covered)] for the sweep, without touching the traces.

    Which frames survive depends only on where the valid samples are, not on
    their values: the coverage is the imaged time of each window, the same for
    every ROI. So the masks can be had from a single dummy row carrying the NaN
    pattern (`valid`), which is what makes it affordable to know the effective grid BEFORE
    deciding whether an existing result file matches this run - a sweep point the
    coverage floor rejects is not part of the null's test family, and the file's
    `sweep_delays` / `sweep_durations` have to say so.
    """
    dummy = np.where(valid, 0.0, np.nan)[None]
    out = []
    for delay in delays:
        for duration in durations:
            _, covered = wp.compute_slap2_response_to_zebra_frames(
                times, dummy, frame_onset_times, delay, duration,
                min_coverage=min_coverage)
            out.append((float(delay), float(duration), covered))
    return out


def response_points(times, signal, frame_onset_times, frame_index, masks,
                    min_coverage):
    """(delay, duration, cols, resp) for every sweep point in `masks`.

    Mirrors the `slap2` branch of `waven_pipeline.full_pipeline`: the same
    windowed means, the same coverage mask, the same `frame_index[covered]`
    stimulus rows - because lag 0 of the resulting scan has to reproduce what that
    branch already wrote to the result files.

    `min_coverage` must be the value `masks` was built with; the masks are
    re-derived here and compared against them, which is how a mismatch shows up
    as an error rather than as a null taken over a different set of frames than
    the grid recorded in the file.
    """
    points = []
    for delay, duration, covered in masks:
        resp, covered_again = wp.compute_slap2_response_to_zebra_frames(
            times, signal, frame_onset_times, delay, duration,
            min_coverage=min_coverage)
        if not np.array_equal(covered, covered_again):
            raise RuntimeError(
                f'coverage at delay {delay}, duration {duration} differs between the '
                f'dummy pass and the real one at min_coverage={min_coverage}; either '
                'the two passes were given different values, or the traces still '
                'hold non-finite samples.')
        points.append((delay, duration, frame_index[covered], resp))
    return points


def main(nwb_path, results_dir, dmd='DMD1', channel='green', signal='events',
         dandiset_id=DEFAULT_DANDISET, phases=('0', '1'), per_trial=False,
         fps=30.0, min_coverage=wp.MIN_COVERAGE,
         n_surrogates=300, min_lag_sec=1.0, delay_stride=1, delays=None,
         durations=None, family_axes=2, feat_block=16384,
         build_frame_block=BUILD_FRAME_BLOCK, lag_batch=8, znorm_dir=None,
         min_active=MIN_ACTIVE_SAMPLES, recompute=False, lib_id=None,
         allow_build=False, decomp_dir=None, build_cache_only=False):

    if signal not in SIGNALS:
        raise ValueError(f'signal must be one of {SIGNALS}, got {signal!r}')
    if channel not in GRIDS:
        raise ValueError(f'channel must be one of {tuple(GRIDS)}, got {channel!r}')

    results_dir = Path(results_dir)
    session_name = Path(nwb_path).stem

    print('Locating wavelet decompositions...')
    movie_path = Path(movpath)
    decomp_dir, lib_id = resolve_decomposition(lib_id, phases, movie_path,
                                               allow_build, decomp_dir)
    print(f'  lib {lib_id} at {decomp_dir}')

    # One cache serves every modality. Its content depends on (movie, library,
    # phase) and nothing else, and all three are in the filename, so this reads
    # whatever copy the ecephys runs already built rather than a SLAP2 one of
    # its own. That is also why there is no prep job here: the first run to find
    # it cold builds it, and every later run of any modality finds it warm.
    znorm_root = Path(znorm_dir) if znorm_dir is not None else decomp_dir

    # The cache depends only on (movie, library, phase) - not on the session, the
    # DMD, the channel or the sweep - and building it is pure numpy and I/O. So it
    # can be built once on a CPU node, before any GPU is allocated and without
    # touching DANDI at all.
    if build_cache_only:
        print(f'Building the normalised cache only, into {znorm_root}')
        for phase in phases:
            build_znorm_stim(decomp_dir / f'dwt_videodata_{phase}.npy', znorm_root,
                             lib_id, movie_path.stem,
                             frame_block=build_frame_block)
        print('Cache ready; the per-channel array jobs can now run together.')
        return

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    if device.type == 'cpu':
        print('WARNING: no CUDA device — this will be far too slow for a full run.')

    if delay_stride < 1:
        raise ValueError(f'delay stride must be at least 1, got {delay_stride}')
    sweep_delays = (np.asarray(delays, dtype=float) if delays is not None
                    else GRIDS[channel]['delays'][::delay_stride])
    sweep_durations = (np.asarray(durations, dtype=float) if durations is not None
                       else GRIDS[channel]['durations'])

    # filt_shape[-0:] is the whole shape, not an empty tuple, so family_axes=0
    # would silently make every filter its own family.
    if family_axes < 1:
        raise ValueError(f'family_axes must be at least 1, got {family_axes}')

    if dandiset_id is None:
        print(f'Reading {nwb_path} FROM DISK (--local).')
    else:
        print(f'Streaming {nwb_path} from dandiset {dandiset_id}...')
    stream = utils.open_session(nwb_path, dandiset_id)
    if dmd not in stream.dmds():
        raise ValueError(f'{dmd!r} not in this session; available: {stream.dmds()}')

    # one row per movie frame per repeat; 'frame' is the row of the decomposition
    zebra_frames = stream.zebra_frame_times(fps=fps)

    # Read only the Zebra block, with room for the longest response window. Sized
    # from the channel's FULL grid, not the possibly-narrowed sweep, because the
    # pipeline sizes its read that way: a one-point validation run must see the
    # same traces the pipeline saw, or its lag 0 drifts from the result file it is
    # being checked against.
    margin = float(
        max(np.max(np.abs(GRIDS[channel]['delays'])), np.max(np.abs(sweep_delays)))
        + max(np.max(np.abs(GRIDS[channel]['durations'])),
              np.max(np.abs(sweep_durations))) + 1.0)
    t_start = zebra_frames['start_time'].min() - margin
    t_stop = zebra_frames['stop_time'].max() + margin
    traces_df, all_unit_names = load_signal(stream, dmd, channel, t_start, t_stop,
                                            signal=signal, nwb_path=nwb_path)

    # NaN samples stay in, as in waven_pipeline: the frame coverage counts them
    # as not imaged, and the screen below only looks at the valid samples
    times = traces_df.columns.to_numpy(dtype=float)
    traces = traces_df.to_numpy(dtype=np.float64)
    valid = np.isfinite(traces).all(axis=0)
    print(f'{traces.shape[0]} ROIs, {traces.shape[1]} samples '
          f'({(~valid).sum()} blanked) over the Zebra block')
    if traces.shape[0] != len(all_unit_names):
        raise ValueError(
            f'{traces.shape[0]} trace rows but {len(all_unit_names)} ROI names; '
            'slap2_rois() and the fluorescence series disagree on the ROI set.')

    # Screened once for the whole sweep, so the kept set is the same at every
    # delay and duration and a maximum over the sweep is well defined per unit.
    keep, n_active = nso.screen_units(traces[:, valid], signal, min_active)
    unit_names = all_unit_names[keep]
    print(f'{keep.sum()} of {len(keep)} ROIs pass the screen '
          f'(>= {min_active} active {signal} samples, finite, non-constant)')
    if keep.sum() == 0:
        print('no ROIs pass the screen — nothing to do')
        return
    traces = traces[keep]

    # pooled (default): one block holding all Zebra repeats; per trial: one block
    # per repeat - the same blocks compute_waven_pipeline_slap2.py runs on
    for block in wp.zebra_blocks(zebra_frames, per_trial):
        trial_part = block.trial_part
        frame_onset_times = block.frame_onset_times
        frame_index = block.frame_index

        # Which frames survive depends on delay and duration, so the effective
        # grid is resolved here - before the staleness check, which has to compare
        # against the grid that will actually be scanned.
        masks = coverage_masks(times, valid, frame_onset_times, sweep_delays,
                               sweep_durations, min_coverage)
        dropped = [(d, u, int(c.sum())) for d, u, c in masks
                   if c.sum() < MIN_COVERED_FRAMES]
        for d, u, n in dropped:
            print(f'  delay {d}, duration {u}: only {n} imaged frames '
                  f'(floor {MIN_COVERED_FRAMES}) — dropped from the sweep, as the '
                  'pipeline drops it from the observed side')
        masks = [m for m in masks if m[2].sum() >= MIN_COVERED_FRAMES]
        if not masks:
            print('no sweep point retains enough imaged frames — skipping')
            continue
        eff_delays = np.unique([d for d, _, _ in masks])
        eff_durations = np.unique([u for _, u, _ in masks])

        for phase in phases:
            decomp_path = decomp_dir / f'dwt_videodata_{phase}.npy'
            # signal / dmd / channel / trial_<i> or pooled_trials / phase / lib_<id> mirrors the
            # rawresults layout compute_waven_pipeline_slap2.py writes, so both
            # trees walk alike; the session belongs in --results-dir.
            out_path = results_dir.joinpath(
                signal, dmd, channel, *trial_part, f'phase_{phase}',
                f'lib_{lib_id}', f'null__lib_{lib_id}.h5')

            # Checked against the decomposition's header before anything is built:
            # normalising is a ~50 GB pass, and a wrong-movie run would otherwise
            # burn all of it before noticing.
            n_frames = int(np.load(decomp_path, mmap_mode='r').shape[0])
            if frame_index.max() >= n_frames:
                raise ValueError(
                    f'frame_index reaches {frame_index.max()} but the decomposition '
                    f'of {movie_path.name} has only {n_frames} frames; the onsets '
                    'must be generated from this movie.')

            if out_path.exists() and not recompute:
                stale = nso.stale_reason_ophys(
                    out_path, eff_delays, eff_durations, n_surrogates,
                    {'signal': signal, 'min_active_samples': min_active,
                     'min_coverage': min_coverage,
                     'fps_assumed': fps, 'pooled_repeats': not per_trial})
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
                                     masks, min_coverage)
            groups = nso.group_sweep_points(points, device)
            del points
            grid = nso.sweep_grid(groups)
            n_used = [len(g.cols) for g in groups]
            frac = [len(g.cols) / len(frame_onset_times) for g in groups]

            # Lags are in RETAINED FRAMES and built from the shortest sweep point,
            # so each stays a proper roll there (see null_max_scan_subset). One lag
            # is then the same number of retained frames everywhere, which is a
            # shift of at least lag/fps seconds at every sweep point.
            lags = build_lags(min(n_used), n_surrogates,
                             int(np.ceil(min_lag_sec * fps)))
            nso.warn_if_lags_collapsed(lags, n_surrogates)
            # One lag set has to serve the whole sweep, so it is sized by the
            # SHORTEST sweep point. When coverage is very uneven, those rolls span
            # only a sliver of the longest sweep points - and those are the ones
            # that usually carry the sweep-wide maximum. Neighbouring surrogates
            # are then near-duplicates of each other, the upper tail of the null is
            # under-explored, and the p-values come out too small.
            span = float(lags.max()) / max(n_used)
            if span < 0.5:
                print(f'  WARNING: rolls span only {100 * span:.0f} % of the longest '
                      f'sweep point ({max(n_used)} frames) because the shortest holds '
                      f'{min(n_used)}. Surrogates on the long sweep points are then '
                      f'near-duplicates and the p-values are biased SMALL. Raise '
                      f'--min-coverage, or drop the starved (delay, duration) with '
                      f'--durations, so the sweep points are comparable in length.')
            print(f'  phase {phase}: {n_filters} filters, {n_families} families, '
                  f'{len(masks)} sweep points in {len(groups)} row selections of '
                  f'{min(n_used)}-{max(n_used)} frames '
                  f'({100 * min(frac):.0f}-{100 * max(frac):.0f} % imaged), '
                  f'{len(lags) - 1} surrogates')
            flops = nso.scan_flops(n_filters, groups, len(unit_names), len(lags))
            print(f'  ~{flops / 1e15:.1f} PFLOP '
                  f'(~{flops / 1e14 / 60:.0f} min at 100 TFLOP/s)')

            maxbuf = nso.null_max_scan_subset(
                znorm_path, groups, lags, n_families, device, feat_block, lag_batch,
                expect_shape=(n_filters, n_frames))
            del groups
            if device.type == 'cuda':
                torch.cuda.empty_cache()

            attributes = {
                'session': session_name,
                'modality': MODALITY,
                'signal': signal,
                'group': f'{dmd}_{channel}',
                'dmd': dmd,
                'channel': channel,
                'library_id': lib_id,
                'phase': phase,
                'movie': movie_path.name,
                'fps_assumed': fps,
                'n_frames': n_frames,
                'frame_period': 1.0 / fps,
                'n_timepoints_min': int(min(n_used)),
                'n_timepoints_max': int(max(n_used)),
                'n_row_selections': len(n_used),
                'frac_frames_covered_min': float(min(frac)),
                'frac_frames_covered_max': float(max(frac)),
                'min_coverage': float(min_coverage),
                'n_sweep_points_dropped': len(dropped),
                'n_surrogates': len(lags) - 1,
                'min_lag_sec': min_lag_sec,
                'min_active_samples': min_active,
                # what the n_spikes dataset actually counts in this file
                'activity_measure': ('nonzero event samples' if signal == 'events'
                                     else 'finite dff samples'),
                'roll_axis': 'retained movie frames',
                # gaps between retained frames only stretch a roll, never shorten it
                'lag_seconds_is_lower_bound': True,
                'date_computed': datetime.today().strftime('%Y-%m-%d'),
                **block.attributes,
            }

            save_null(out_path, unit_names, n_active[keep], lags, lags / fps,
                      maxbuf, grid, filt_shape, family_axes, attributes=attributes)


def _parse_floats(s):
    return None if s is None else np.array([float(v) for v in s.split(',')])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Null distribution of the sweep-wide max |correlation| per ROI, '
                    'SLAP2 sessions.')
    parser.add_argument('--nwb-path', required=True)
    parser.add_argument('--results-dir', required=True)
    parser.add_argument('--dmd', default='DMD1', help='DMD imaging plane, e.g. DMD1 or DMD2')
    parser.add_argument('--channel', default='green', choices=list(GRIDS),
                        help="'green' (iGluSnFR4f, default) or 'red' (RCaMP3); each "
                             'has its own delay/duration grid')
    parser.add_argument('--signal', default='events', choices=SIGNALS,
                        help="Trace to correlate: the deconvolved 'events' (default), "
                             'computed and cached by utils.deconvolution on first use, '
                             "or raw 'dff'.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--dandiset-id', default=DEFAULT_DANDISET,
                        help='Dandiset to stream --nwb-path from as an asset path '
                             f'(default {DEFAULT_DANDISET}).')
    source.add_argument('--local', action='store_true',
                        help='Read --nwb-path from disk instead of streaming.')
    parser.add_argument('--phases', default='0,1',
                        help="Wavelet phases to run, comma separated (default '0,1'). "
                             'The null is phase specific.')
    parser.add_argument('--per-trial', action='store_true',
                        help='One null per Zebra repeat instead of pooling them. '
                             'Needed for repeatability checks; note a single repeat '
                             'may retain few imaged frames.')
    parser.add_argument('--fps', type=float, default=30.0,
                        help='Frame rate assumed when reconstructing frame onsets '
                             'from the per-repeat Zebra intervals. Also the period '
                             '--min-lag-sec converts with.')
    parser.add_argument('--min-coverage', type=float, default=wp.MIN_COVERAGE,
                        help="Fraction of a response window's time that must be imaged for "
                             'the frame to be kept. Must match the run being '
                             'thresholded.')
    parser.add_argument('--n-surrogates', type=int, default=300,
                        help='Roll offsets besides lag 0 (default 300 - about one per '
                             'second of one Zebra repeat; fewer per second once '
                             'repeats are pooled). The per-unit test needs far fewer, '
                             'but the p floor is 1/(1+N), and BH across ROIs cannot '
                             'reject until roughly n/(q*(1+N)) of them sit at that '
                             'floor; at N=100 that left a clearly responsive ecephys '
                             'probe with zero rejections.')
    parser.add_argument('--min-lag-sec', type=float, default=1.0,
                        help='Exclusion zone at both ends of the roll range, in '
                             'seconds, converted with the movie frame period - a lower '
                             'bound on the shift, since the blanking gaps only stretch '
                             'it. Not the spacing between surrogates - that follows '
                             'from --n-surrogates.')
    parser.add_argument('--delay-stride', type=int, default=1,
                        help="Take every Nth delay of the channel's pipeline grid. "
                             'Default 1 - the grids are coarse already.')
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
                             'the sweep point being scanned. Pooled repeats make the '
                             'gathered copy the larger of the two.')
    parser.add_argument('--build-frame-block', type=int, default=BUILD_FRAME_BLOCK,
                        help='Frames per chunk when building the normalised cache. '
                             'A memory knob only.')
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
    parser.add_argument('--lib-id', default=None,
                        help='Use this existing library/decomposition instead of the '
                             'one the current waven_settings hashes to.')
    parser.add_argument('--allow-build', action='store_true',
                        help='Build the filter library and wavelet decomposition if '
                             'absent (~100 GB per phase, hours).')
    parser.add_argument('--build-cache-only', action='store_true',
                        help='Build the normalised stimulus cache for --phases and '
                             'exit. Needs no GPU, no DANDI access and no session.')
    parser.add_argument('--decomp-dir', default=None,
                        help='Directory holding dwt_videodata_{phase}.npy, bypassing '
                             'path derivation.')
    args = parser.parse_args()

    if not args.local and not args.dandiset_id:
        parser.error('--dandiset-id is empty; pass a dandiset or use --local')

    main(nwb_path=args.nwb_path, results_dir=args.results_dir, dmd=args.dmd,
         channel=args.channel, signal=args.signal,
         dandiset_id=None if args.local else args.dandiset_id,
         phases=tuple(args.phases.split(',')), per_trial=args.per_trial,
         fps=args.fps, min_coverage=args.min_coverage,
         n_surrogates=args.n_surrogates,
         min_lag_sec=args.min_lag_sec, delay_stride=args.delay_stride,
         delays=_parse_floats(args.delays), durations=_parse_floats(args.durations),
         family_axes=args.family_axes, feat_block=args.feat_block,
         build_frame_block=args.build_frame_block, lag_batch=args.lag_batch,
         znorm_dir=args.znorm_dir, min_active=args.min_active_samples,
         recompute=args.recompute, lib_id=args.lib_id,
         allow_build=args.allow_build, decomp_dir=args.decomp_dir,
         build_cache_only=args.build_cache_only)
