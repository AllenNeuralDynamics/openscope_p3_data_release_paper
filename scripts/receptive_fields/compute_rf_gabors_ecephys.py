# Author: Marcel C. Raabe
# Contributors: Lucas Rudelt
# Date: 2026-10-29
"""Receptive field mapping of the local Gabor patches, ecephys sessions.

For one probe of a session, the spike rate of every unit after each Gabor
presentation is placed on the (orientation, x, y) stimulus grid and tested for
spatial structure with a permutation test (`rf_gabors`), once per
(delay, duration) of the Zebra grid of this modality (`DELAYS` and `DURATIONS`
of `compute_waven_pipeline_ecephys.py`). The grid is then reduced to one
optimized file per probe: per unit and orientation, the sweep point with the
lowest p.

What delay and duration mean here: the response to a presentation is the number
of spikes in [onset + delay, onset + delay + duration), divided by the
presentation's stimulus duration.

The whole RF block is pooled by default. `--per-trial` splits it into its
earlier and later half (trial_0, trial_1) and scores each half at the windows
the pooled run chose, so run the pooled job first.

Files go to <results-path>/<session>/spikes/, named as described in `rf_gabors`
with tag `rf-spike-count` and the probe as the group - the layout of the
mesoscope and SLAP2 drivers, with 'spikes' as the signal. <results-path> is the
modality root, by default <gabors>/ecephys, as for the Zebra results. Existing sweep files on the
same unit list are skipped; a file computed on another unit list (an older
release of the NWB file) makes the run stop, and `--recompute` replaces it.

The session is streamed from DANDI (dandiset 001637) by default, so --nwb-path is
the asset path inside the dandiset. Add --local to read --nwb-path from disk.

    python compute_rf_gabors_ecephys.py \\
        --nwb-path sub-830794/sub-830794_ses-ecephys-830794-2026-01-26-12-02-05_ecephys.nwb \\
        --probe-idx 2
"""

import argparse
import os
from pathlib import Path

import compute_waven_pipeline_ecephys as zebra
import numpy as np
import rf_gabors
import utils

RESULTS_DIR = os.path.abspath('../../../results/allen_open_scope/rf/gabors/ecephys')
DEFAULT_DANDISET = '001637'
TAG = 'rf-spike-count'

# Spikes are the only signal of this modality; it is still a folder level, so
# that all three modalities share one layout.
SIGNAL = 'spikes'

# Delay x duration grid in seconds: the one of the Zebra analysis, so both stimuli
# are tested over the same windows. Rounded to drop the float noise of np.arange.
DELAYS = np.round(zebra.DELAYS, 6)
DURATIONS = np.round(zebra.DURATIONS, 6)


def presentation_rates(spike_times, onsets, offsets, delay, duration):
    """Spike count in [onset + delay, onset + delay + duration), per stimulus duration.

    spike_times must be sorted. Returns one rate per presentation.
    """
    onsets = np.asarray(onsets, dtype=float)
    stimulus = np.maximum(np.asarray(offsets, dtype=float) - onsets, 1e-9)
    spikes = np.asarray(spike_times, dtype=float)
    if spikes.size == 0:
        return np.zeros(len(onsets))
    starts = onsets + delay
    i0 = np.searchsorted(spikes, starts, side='left')
    i1 = np.searchsorted(spikes, starts + duration, side='left')
    return (i1 - i0) / stimulus


def spike_rates(spikes, df_rf, delay, duration):
    """(n_units, n_presentations) rates of every unit for one window."""
    onsets = df_rf['start_time'].to_numpy(float)
    offsets = df_rf['stop_time'].to_numpy(float)
    return np.stack([presentation_rates(st, onsets, offsets, delay, duration) for st in spikes])


def compute_spike_rf(spikes, unit_names, df_rf, x_pos, y_pos, orientations, delay, duration,
                     results_path, attributes, n_shuffle=rf_gabors.N_SHUFFLE, seed=0, n_procs=None):
    """Run the Gabor RF test on every unit and write one HDF5 result file."""
    rates = spike_rates(spikes, df_rf, delay, duration)
    R, n_valid = rf_gabors.fill_grids(rates, df_rf, x_pos, y_pos, orientations)
    stats = rf_gabors.gabor_test(R, n_shuffle, seed, n_procs)
    return rf_gabors.write_result(results_path, attributes, unit_names, orientations,
                                  x_pos, y_pos, stats, n_valid)


def load_probe(stream, probe_idx):
    """(probe, unit_names, spike_times) for one probe, in units_df() order."""
    units = stream.units_df(include_spikes=True)
    probe = units['probe'].unique()[probe_idx]
    on_probe = units.loc[units['probe'] == probe].drop_duplicates('unit_name')
    unit_names = [rf_gabors._text(name) for name in on_probe['unit_name']]
    spikes = [np.sort(np.asarray(st, dtype=float)) for st in on_probe['spike_times']]
    return rf_gabors._text(probe), unit_names, spikes


def main(nwb_path, probe_idx, results_dir=RESULTS_DIR, per_trial=False, recompute=False,
         optimize=True, n_shuffle=rf_gabors.N_SHUFFLE, dandiset_id=DEFAULT_DANDISET):
    session_name = Path(nwb_path).stem
    results_dir = Path(results_dir) / session_name / SIGNAL

    if dandiset_id is None:
        print(f'Reading {nwb_path} FROM DISK (--local).')
    else:
        print(f'Streaming {nwb_path} from dandiset {dandiset_id}...')
    with utils.open_session(nwb_path, dandiset_id) as stream:
        probe, unit_names, spikes = load_probe(stream, probe_idx)
        df_rf = stream.gabor_rf_df()

    x_pos, y_pos, orientations = rf_gabors.rf_grid(df_rf)
    counts = df_rf.groupby(['X', 'Y', 'Orientation'], observed=True).size()
    print(f'{probe}: {len(unit_names)} units, {len(df_rf)} presentations, '
          f'{len(x_pos)}x{len(y_pos)} grid, {len(orientations)} orientations, '
          f'{int(counts.min())}-{int(counts.max())} repeats per cell')

    attributes = {
        'session': session_name,
        'modality': 'ecephys',
        'signal': SIGNAL,
        'group': probe,
        'probe': probe,
        'n_shuffle': int(n_shuffle),
        'source_asset': str(nwb_path),
    }

    def compute(df_block, delay, duration, path, attrs):
        compute_spike_rf(spikes, unit_names, df_block, x_pos, y_pos, orientations,
                         delay, duration, path, attrs, n_shuffle)

    rf_gabors.run_sweep(compute, df_rf, DELAYS, DURATIONS, results_dir, session_name, TAG, probe,
                        unit_names, attributes, per_trial=per_trial, recompute=recompute,
                        optimize=optimize)


# ---------------------------------------------------------------------------
# Legacy helpers, still imported by utils/utils.py and older notebooks
# ---------------------------------------------------------------------------

def get_stim_onsets_offsets(df_rf, combination_xy, orientation='0'):
    import quantities as pq

    x, y = combination_xy
    df_sub = df_rf[
        (df_rf['X'] == str(float(x))) &
        (df_rf['Y'] == str(float(y))) &
        (df_rf['Orientation'] == str(float(orientation)))
    ]
    return (df_sub['start_time'].values * pq.s, df_sub['stop_time'].values * pq.s)


def time_slice_spike_train(spike_train, start, stop):
    if (stop < spike_train.t_start) or (start > spike_train.t_stop):
        return []
    start = max(start, spike_train.t_start)
    stop = min(stop, spike_train.t_stop)
    return spike_train.time_slice(start, stop)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--nwb-path', required=True, help='Path to the ecephys NWB file')
    parser.add_argument('--probe-idx', required=True, type=int,
                        help='Index of the probe to process (0-based)')
    parser.add_argument('--results-path', default=RESULTS_DIR,
                        help='Modality root for results; <session>/spikes/ is appended. '
                             f'Default: {RESULTS_DIR}')
    parser.add_argument('--per-trial', action='store_true',
                        help='Score the two halves of the RF block separately, at the '
                             'windows of the pooled run')
    parser.add_argument('--recompute', action='store_true',
                        help='Recompute sweep points whose result file already exists')
    parser.add_argument('--no-optimize', action='store_true',
                        help='Skip the delay x duration reduction step')
    parser.add_argument('--n-shuffle', type=int, default=rf_gabors.N_SHUFFLE,
                        help='Permutations used for the p-value')
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--dandiset-id', default=DEFAULT_DANDISET,
                        help='Dandiset to stream --nwb-path from as an asset path '
                             f'(default {DEFAULT_DANDISET}).')
    source.add_argument('--local', action='store_true',
                        help='Read --nwb-path from disk instead of streaming.')

    args = parser.parse_args()
    if not args.local and not args.dandiset_id:
        parser.error('--dandiset-id is empty; pass a dandiset or use --local')
    main(args.nwb_path, args.probe_idx, args.results_path, per_trial=args.per_trial,
         recompute=args.recompute, optimize=not args.no_optimize, n_shuffle=args.n_shuffle,
         dandiset_id=None if args.local else args.dandiset_id)
