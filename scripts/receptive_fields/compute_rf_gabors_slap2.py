# Author: Marcel C. Raabe
# Contributors: Lucas Rudelt
# Date: 2026-10-29
"""Receptive field mapping of the local Gabor patches, SLAP2 sessions.

The SLAP2 counterpart of `compute_rf_gabors_ecephys.py`: instead of a spike rate
per presentation it uses the mean ΔF/F (or deconvolved event amplitude) of each
ROI over the response window [onset + delay, onset + delay + duration), on the
delay x duration grid of the SLAP2 Zebra analysis for that channel (`GRIDS` of
`compute_waven_pipeline_slap2.py`). One HDF5
file is written per (DMD, channel, delay, duration) into
<results-path>/<session>/<signal>/, then the grid is reduced to one optimized
file per DMD and channel, exactly as for the probes (`rf_gabors`). <results-path>
is the modality root, by default <gabors>/slap2, as for the Zebra results.

SLAP2 does not image continuously — it records in ~30 s bouts and blanks short
stretches of samples to NaN — so presentations whose response window is less
than 95 % imaged are dropped from the test rather than averaged over a hole
(the same rule as the waven maps, `waven_pipeline.imaged_window_means`).

The test runs on the deconvolved events by default; `--signal dff` restores the
raw ΔF/F. Unlike the mesoscope release, the SLAP2 NWB files carry no events, so
`utils.deconvolution` computes and caches them per session, DMD and channel on
first use.

The whole RF block is pooled by default. `--per-trial` splits it into its
earlier and later half (trial_0, trial_1) and scores each half at the windows
the pooled run chose, so run the pooled job first. Existing sweep files are
skipped unless `--recompute`.

The session is streamed from DANDI (dandiset 001424) by default, so --nwb-path is
the asset path inside the dandiset. Add --local to read --nwb-path from disk.

    python compute_rf_gabors_slap2.py \\
        --nwb-path sub-829704/sub-829704_ses-829704-2025-12-18-10-57-36_image+ophys.nwb \\
        --dmd DMD1 --channel green
"""

import argparse
import os
from pathlib import Path

import compute_waven_pipeline_slap2 as zebra
import numpy as np
import rf_gabors
import utils
from utils import deconvolution

RESULTS_DIR = os.path.abspath('../../../results/allen_open_scope/rf/gabors/slap2')
STIM_TABLE = 'rf_mapping'
DEFAULT_DANDISET = '001424'

# Window rule of the SLAP2 Zebra analysis: a window counts if ≥ 95 % of it was imaged.
WINDOW_MEANS = rf_gabors.imaged_means


def grid(channel):
    """(delays, durations) in seconds for one channel: those of the Zebra analysis.

    Green (iGluSnFR4f) resolves single frames, red (RCaMP3) needs a later, wider
    window; see `GRIDS` in compute_waven_pipeline_slap2.py. Rounded to drop the
    float noise of np.arange.
    """
    return (np.round(zebra.GRIDS[channel]['delays'], 6),
            np.round(zebra.GRIDS[channel]['durations'], 6))


def load_traces(stream, dmd, channel, t_start, t_stop, signal='dff', nwb_path=None):
    """(traces, times, unit_names) for one DMD, restricted to [t_start, t_stop].

    signal: 'dff' for ΔF/F, 'events' for the deconvolved series — the latter is
    non-negative and so the closer analogue of a spike rate.
    """
    if signal == 'dff':
        df = stream.slap2_dff(dmd, channel, t_start=t_start, t_stop=t_stop)
    elif signal == 'events':
        df = deconvolution.slap2_events_df(nwb_path, dmd, channel, t_start=t_start,
                                           t_stop=t_stop, stream=stream)
    else:
        raise ValueError(f"signal must be 'dff' or 'events', got {signal!r}")

    traces = df.to_numpy(dtype=np.float64)
    times = df.columns.to_numpy(dtype=float)
    roi_ids = stream.slap2_rois(dmd)['roi_id'].to_numpy()
    unit_names = [f'{dmd}_{channel}_roi{roi_id}' for roi_id in roi_ids]
    return traces, times, unit_names


def main(nwb_path, dmd, results_dir=RESULTS_DIR, channel='green', signal='events',
         baseline=0.0, n_shuffle=rf_gabors.N_SHUFFLE, optimize=True, per_trial=False,
         recompute=False, dandiset_id=DEFAULT_DANDISET):
    session_name = Path(nwb_path).stem
    # One tree per signal: readers key the optimized files on the DMD alone,
    # so ΔF/F and events must not share a directory.
    results_dir = Path(results_dir) / session_name / signal
    delays, durations = grid(channel)

    if dandiset_id is None:
        print(f'Reading {nwb_path} FROM DISK (--local).')
    else:
        print(f'Streaming {nwb_path} from dandiset {dandiset_id}...')
    with utils.open_session(nwb_path, dandiset_id) as stream:
        if dmd not in stream.dmds():
            raise ValueError(f'{dmd!r} not in this session; available: {stream.dmds()}')
        df_rf = stream.stim_df(STIM_TABLE)
        # only the RF block is read - the full traces are several hundred MB
        margin = baseline + delays.max() + durations.max() + 1.0
        traces, times, unit_names = load_traces(
            stream, dmd, channel,
            t_start=df_rf['start_time'].min() - margin,
            t_stop=df_rf['stop_time'].max() + margin,
            signal=signal, nwb_path=nwb_path,
        )

    x_pos, y_pos, orientations = rf_gabors.rf_grid(df_rf)
    # NaN samples stay in: the response windows count them as not imaged
    n_blanked = (~np.isfinite(traces).all(axis=0)).sum()
    print(f'{dmd}/{channel} ({signal}): {traces.shape[0]} ROIs, {traces.shape[1]} samples over the '
          f'RF block ({n_blanked} blanked), {len(df_rf)} presentations, '
          f'{len(x_pos)}x{len(y_pos)} grid, {len(orientations)} orientations')

    attributes = {
        'session': session_name,
        'modality': 'slap2',
        'signal': signal,
        'group': f'{dmd}/{channel}',
        'dmd': dmd,
        'probe': dmd,            # keeps the ecephys reducer's naming happy
        'channel': channel,
        'baseline_s': baseline,
        'n_shuffle': n_shuffle,
    }

    def compute(df_block, delay, duration, path, attrs):
        rf_gabors.compute_gabor_ophys(
            traces, times, unit_names, df_block, x_pos, y_pos, orientations,
            delay=delay, duration=duration, results_path=path, attributes=attrs,
            baseline=baseline, n_shuffle=n_shuffle, window_means=WINDOW_MEANS,
        )

    rf_gabors.run_sweep(compute, df_rf, delays, durations, results_dir, session_name,
                        f'rf-{signal}-{channel}', dmd, unit_names, attributes,
                        per_trial=per_trial, recompute=recompute, optimize=optimize)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--nwb-path', required=True, help='Path to the SLAP2 NWB file')
    parser.add_argument('--dmd', default='DMD1', help='DMD imaging plane, e.g. DMD1 or DMD2')
    parser.add_argument('--results-path', default=RESULTS_DIR,
                        help='Modality root for results; <session>/<signal>/ is appended. '
                             f'Default: {RESULTS_DIR}')
    parser.add_argument('--channel', default='green', choices=['green', 'red'],
                        help="'green' (iGluSnFR4f, default) or 'red' (RCaMP3)")
    parser.add_argument('--signal', default='events', choices=['dff', 'events'],
                        help="Trace to analyse: the deconvolved 'events' (default), "
                             'computed and cached by utils.deconvolution on first use, '
                             "or raw 'dff'. Results go to <results-path>/<session>/<signal>/")
    parser.add_argument('--baseline', type=float, default=0.0,
                        help='Seconds of pre-stimulus signal to subtract per trial. '
                             'Default 0 (no subtraction), matching the spike-rate version; '
                             'note the 0.267 s ISI leaves no truly blank baseline.')
    parser.add_argument('--n-shuffle', type=int, default=rf_gabors.N_SHUFFLE,
                        help='Permutations used for the p-value')
    parser.add_argument('--per-trial', action='store_true',
                        help='Score the two halves of the RF block separately, at the '
                             'windows of the pooled run')
    parser.add_argument('--recompute', action='store_true',
                        help='Recompute sweep points whose result file already exists')
    parser.add_argument('--no-optimize', action='store_true',
                        help='Skip the delay x duration reduction step')
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--dandiset-id', default=DEFAULT_DANDISET,
                        help='Dandiset to stream --nwb-path from as an asset path '
                             f'(default {DEFAULT_DANDISET}).')
    source.add_argument('--local', action='store_true',
                        help='Read --nwb-path from disk instead of streaming.')

    args = parser.parse_args()
    if not args.local and not args.dandiset_id:
        parser.error('--dandiset-id is empty; pass a dandiset or use --local')
    main(args.nwb_path, args.dmd, args.results_path, args.channel, args.signal,
         args.baseline, args.n_shuffle, optimize=not args.no_optimize,
         per_trial=args.per_trial, recompute=args.recompute,
         dandiset_id=None if args.local else args.dandiset_id)
