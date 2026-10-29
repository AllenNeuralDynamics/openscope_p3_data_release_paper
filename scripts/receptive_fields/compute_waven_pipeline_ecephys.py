# Author: Marcel C. Raabe
# Date: 2026-10-29
"""Waven RF mapping of the Zebra noise movie, ecephys sessions.

For one probe of a session, the spike rate of every unit in a window after each
movie frame is correlated with the Gabor wavelet decomposition of the movie
(`waven_pipeline.full_pipeline`), once per (delay, duration) of the grid below
and per wavelet phase. Each grid is then reduced to one row per unit
(`optimize_waven_parameters`).

What delay and duration mean here: the response to a frame is the firing rate in
the window [onset + delay, onset + delay + duration), with the onset taken from
the session's Zebra frame table.

Zebra repeats are pooled by default: the rate is averaged over repeats per movie
frame and the correlation rescaled, which equals the correlation on the stacked
repeats (`waven_pipeline.pool_repeats`). `--per-trial` gives one result set per
repeat instead.

The bulky per-(delay, duration) files go to
<results-dir>/<session>/spikes/<probe>/<pooled_trials|trial_<i>>/phase_<p>/lib_<id>/,
the reduced files to <optimized-dir>/<session>/spikes/ - the same layout as the
mesoscope and SLAP2 drivers, with 'spikes' as the signal.

The session is streamed from DANDI (dandiset 001637) by default, so --nwb-path is
the asset path inside the dandiset. Add --local to read --nwb-path from disk.

    python compute_waven_pipeline_ecephys.py \\
        --nwb-path sub-830794/sub-830794_ses-ecephys-830794-2026-01-26-12-02-05_ecephys.nwb \\
        --results-dir /path/to/rawresults/ecephys --probe-idx 0
"""

import argparse
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import numpy as np
import optimize_waven_parameters as owp
import utils
from waven_pipeline import full_pipeline, zebra_blocks

OPTIMIZED_DIR = Path('/mnt/ceph-hdd/projects/cidbn_wibral_neuro_nonhuman/'
                     'SPP2205_mraabe/results/allen_open_scope/rf/waven/zebra/optimized')

# Allen Open Scope ecephys. Streaming is the default, as in the other drivers:
# `open_session` falls back to disk whenever dandiset_id is None, so reading a
# local copy has to be asked for with --local.
DEFAULT_DANDISET = '001637'

# Spikes are the only signal of this modality; it is still a folder level and an
# attribute, so that all three modalities share one layout.
SIGNAL = 'spikes'

# Delay x duration grid in seconds. Defined only here: compute_null_distribution_ecephys.py
# imports it, so the null is always taken over the same test family.
DELAYS = np.arange(0.0, 0.13, 0.01)
DURATIONS = np.arange(0.05, 0.3, 0.05)


def main(nwb_path: str,
         results_dir: str | Path,
         probe_idx: int = 0,
         phases: Sequence[str] = ('0', '1'),
         per_trial: bool = False,
         recompute: bool = False,
         optimize: bool = True,
         optimized_dir: str | Path = OPTIMIZED_DIR,
         dandiset_id: str | None = DEFAULT_DANDISET
         ) -> None:
    """Run the waven RF mapping on one probe of an ecephys session.

    Args:
        nwb_path: Asset path inside the dandiset, or a disk path if
            `dandiset_id` is None.
        results_dir: Root for the bulky per-(delay, duration) result files; the
            session name and 'spikes' are appended.
        probe_idx: Index into the session's probes, in the order of
            `units_df()['probe'].unique()`.
        phases: Wavelet phases to run ('0', '1', 'complex').
        per_trial: One result set per Zebra repeat instead of pooling them.
        recompute: Recompute grid cells whose result file already exists.
        optimize: Reduce each result set over delay x duration to one row per
            unit and save it under `optimized_dir`.
        optimized_dir: Root for the reduced one-row-per-unit results; the
            session name and 'spikes' are appended.
        dandiset_id: Dandiset to stream from, or None to read `nwb_path` from disk.
    """
    session_name = Path(nwb_path).stem
    results_dir = Path(results_dir) / session_name / SIGNAL
    optimized_dir = Path(optimized_dir) / session_name / SIGNAL

    if dandiset_id is None:
        print(f'Reading {nwb_path} FROM DISK (--local).')
    else:
        print(f'Streaming {nwb_path} from dandiset {dandiset_id}...')
    stream = utils.open_session(nwb_path, dandiset_id)

    units_df = stream.units_df()
    probe = units_df['probe'].unique()[probe_idx]
    unit_ids = units_df.loc[units_df['probe'] == probe, 'unit_name'].values
    spike_times = units_df.loc[units_df['probe'] == probe, 'spike_times'].values

    # pooled (default): one block holding all Zebra repeats; per trial: one block per repeat
    for block in zebra_blocks(stream.zebra_df(), per_trial):
        for phase in phases:
            attributes = {
                'session': session_name,
                'modality': 'ecephys',
                'signal': SIGNAL,
                'group': probe,
                'probe': probe,
                'phase': phase,
                'date_computed': datetime.today().strftime('%Y-%m-%d'),
                **block.attributes,
            }

            lib_dir = full_pipeline(
                block.frame_onset_times,
                spike_times,
                DELAYS,
                DURATIONS,
                unit_ids,
                results_path=results_dir.joinpath(probe, *block.trial_part, f'phase_{phase}'),
                attributes=attributes,
                recompute=recompute,
                phase=phase,
                input_type='ecephys',
                frame_index=block.frame_index,
            )

            if optimize:
                print(f'Optimizing parameters over {lib_dir}...')
                stem = '__'.join(['optimized', session_name, probe,
                                  *block.trial_part, f'phase_{phase}'])
                df = owp.optimize_parameters(results_dir=lib_dir,
                                             output_path=optimized_dir / (stem + '.csv'))
                df = owp.load_rf_maps(df)
                owp.save_rf_results(df, optimized_dir / (stem + '.h5'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--nwb-path', required=True, help='Path to the ecephys NWB file')
    parser.add_argument('--results-dir', required=True,
                        help='Root directory for the per-(delay, duration) result files; '
                             '<session>/spikes/ is appended.')
    parser.add_argument('--optimized-dir', default=str(OPTIMIZED_DIR),
                        help='Root directory for the reduced one-row-per-unit results; '
                             f'<session>/spikes/ is appended. Default: {OPTIMIZED_DIR}')
    parser.add_argument('--probe-idx', required=True, type=int,
                        help='Index of the probe to process (0-based)')
    parser.add_argument('--phases', nargs='+', default=['0', '1'],
                        choices=['0', '1', 'complex'], help='Wavelet phases to run')
    parser.add_argument('--per-trial', action='store_true',
                        help='One result set per Zebra repeat instead of pooling them. '
                             'Needed for repeatability checks.')
    parser.add_argument('--recompute', action='store_true',
                        help='Recompute grid cells whose result file already exists')
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
    main(args.nwb_path, args.results_dir, args.probe_idx, tuple(args.phases),
         per_trial=args.per_trial, recompute=args.recompute,
         optimize=not args.no_optimize, optimized_dir=args.optimized_dir,
         dandiset_id=None if args.local else args.dandiset_id)
