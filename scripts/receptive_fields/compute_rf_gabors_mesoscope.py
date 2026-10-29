# Author: Marcel C. Raabe
# Contributors: Lucas Rudelt
# Date: 2026-10-29
"""Receptive field mapping of the local Gabor patches, mesoscope sessions.

The mesoscope counterpart of `compute_rf_gabors_ecephys.py`: instead of a spike
rate per presentation it uses the mean ΔF/F (or deconvolved event amplitude) of
each ROI over the response window [onset + delay, onset + delay + duration). The
delay x duration grid and the window rule are those of the mesoscope Zebra
analysis (`compute_waven_pipeline_mesoscope.py`): a window that holds no sample,
such as duration 0, takes the first sample at or after its start. One
HDF5 file is written per (plane, delay, duration) into
<results-path>/<session>/<signal>/, then the grid is reduced to one optimized
file per plane, exactly as for the probes (`rf_gabors`). <results-path> is the
modality root, by default <gabors>/mesoscope, as for the Zebra results.

The whole RF block is pooled by default. `--per-trial` splits it into its
earlier and later half (trial_0, trial_1) and scores each half at the windows
the pooled run chose, so run the pooled job first. Existing sweep files are
skipped unless `--recompute`.

The session is streamed from DANDI (dandiset 001768) by default, so --nwb-path is
the asset path inside the dandiset. Add --local to read --nwb-path from disk.

    python compute_rf_gabors_mesoscope.py \\
        --nwb-path \\
        sub-832700/sub-832700_ses-multiplane-ophys-832700-2026-01-24-12-06-12_ophys.nwb \\
        --plane-idx 0
"""

import argparse
import os
from pathlib import Path

import compute_waven_pipeline_mesoscope as zebra
import numpy as np
import rf_gabors
import utils

RESULTS_DIR = os.path.abspath('../../../results/allen_open_scope/rf/gabors/mesoscope')
STIM_TABLE = 'RF mapping_presentations'
DEFAULT_DANDISET = '001768'

# Delay x duration grid in seconds and window rule: those of the Zebra analysis,
# so both stimuli are tested over the same windows. Rounded to drop the float
# noise of np.arange.
DELAYS = np.round(zebra.DELAYS, 6)
DURATIONS = np.round(zebra.DURATIONS, 6)
WINDOW_MEANS = rf_gabors.sample_means


def load_traces(stream, plane, signal='dff'):
    """(traces, times, unit_names) for one imaging plane.

    signal: 'dff' for ΔF/F, 'events' for the deconvolved event series — the
    latter is non-negative and so is the closer analogue of a spike rate.
    """
    if signal == 'dff':
        df = stream.dff_df(plane)
        traces, times = df.to_numpy(dtype=np.float64), df.columns.to_numpy(dtype=float)
        roi_ids = stream.nwb.processing[plane]['dff_timeseries']['dff_timeseries'].rois.data[:]
    elif signal == 'events':
        ts = stream.nwb.processing[plane]['event_timeseries']
        traces = np.asarray(ts.data[:], dtype=np.float64).T   # stored (n_t, n_rois)
        times = ts.timestamps[:]
        roi_ids = ts.rois.data[:]
    else:
        raise ValueError(f"signal must be 'dff' or 'events', got {signal!r}")

    unit_names = [f'{plane}_roi{roi_id}' for roi_id in roi_ids]
    return traces, times, unit_names


def main(nwb_path, plane_idx, results_dir=RESULTS_DIR, signal='events', baseline=0.0,
         n_shuffle=rf_gabors.N_SHUFFLE, optimize=True, per_trial=False, recompute=False,
         dandiset_id=DEFAULT_DANDISET):
    session_name = Path(nwb_path).stem
    # One tree per signal: readers key the optimized files on the plane alone,
    # so dff and events maps sharing a directory would silently shadow each other
    results_dir = Path(results_dir) / session_name / signal

    if dandiset_id is None:
        print(f'Reading {nwb_path} FROM DISK (--local).')
    else:
        print(f'Streaming {nwb_path} from dandiset {dandiset_id}...')
    with utils.open_session(nwb_path, dandiset_id) as stream:
        plane = stream.imaging_planes()[plane_idx]
        df_rf = stream.stim_df(STIM_TABLE)
        traces, times, unit_names = load_traces(stream, plane, signal)

    x_pos, y_pos, orientations = rf_gabors.rf_grid(df_rf)
    traces, times = rf_gabors.slice_to_stimulus(
        traces, times, df_rf, margin=baseline + DELAYS.max() + DURATIONS.max() + 1.0
    )
    print(f'{plane}: {traces.shape[0]} ROIs, {traces.shape[1]} samples over the RF block, '
          f'{len(df_rf)} presentations, {len(x_pos)}x{len(y_pos)} grid, '
          f'{len(orientations)} orientations')

    attributes = {
        'session': session_name,
        'modality': 'mesoscope',
        'signal': signal,
        'group': plane,
        'plane': plane,
        'probe': plane,          # keeps the ecephys reducer's naming happy
        'baseline_s': baseline,
        'n_shuffle': n_shuffle,
    }

    def compute(df_block, delay, duration, path, attrs):
        rf_gabors.compute_gabor_ophys(
            traces, times, unit_names, df_block, x_pos, y_pos, orientations,
            delay=delay, duration=duration, results_path=path, attributes=attrs,
            baseline=baseline, n_shuffle=n_shuffle, window_means=WINDOW_MEANS,
        )

    rf_gabors.run_sweep(compute, df_rf, DELAYS, DURATIONS, results_dir, session_name,
                        f'rf-{signal}', plane, unit_names, attributes,
                        per_trial=per_trial, recompute=recompute, optimize=optimize)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--nwb-path', required=True, help='Path to the mesoscope NWB file')
    parser.add_argument('--plane-idx', type=int, required=True,
                        help='Index into stream.imaging_planes(), 0-based')
    parser.add_argument('--results-path', default=RESULTS_DIR,
                        help='Modality root for results; <session>/<signal>/ is appended. '
                             f'Default: {RESULTS_DIR}')
    parser.add_argument('--signal', default='events', choices=['dff', 'events'],
                        help="Trace to analyse: the OASIS-deconvolved 'events' (default) "
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
    main(args.nwb_path, args.plane_idx, args.results_path, args.signal,
         args.baseline, args.n_shuffle, optimize=not args.no_optimize,
         per_trial=args.per_trial, recompute=args.recompute,
         dandiset_id=None if args.local else args.dandiset_id)
