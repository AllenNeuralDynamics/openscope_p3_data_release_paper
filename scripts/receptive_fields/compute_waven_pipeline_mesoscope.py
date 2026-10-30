# Author: Marcel C. Raabe
# Date: 2026-10-29
"""Waven RF mapping of the Zebra noise movie, mesoscope sessions.

For one imaging plane of a session, the dF/F or deconvolved events of every ROI
are correlated with the Gabor wavelet decomposition of the movie
(`waven_pipeline.full_pipeline`), once per (delay, duration) of the grid below
and per wavelet phase. Each grid is then reduced to one row per ROI
(`optimize_waven_parameters`).

What delay and duration mean here: the mesoscope samples at ~10 Hz, slower than
the 30 Hz movie, so the design matrix has one row per imaging sample, not per
frame. A sample at time t is paired with the movie frame shown at t - delay, and
its response is the trace averaged over [t, t + duration). Samples that do not
fall on a frame - before the movie, after its last frame or in a pause between
repeats - are dropped.

Zebra repeats are pooled by default: the samples of all repeats are stacked into
one design matrix, each matched to its movie frame. `--per-trial` gives one
result set per repeat instead.

The bulky per-(delay, duration) files go to
<results-dir>/<session>/<signal>/<plane>/<pooled_trials|trial_<i>>/phase_<p>/lib_<id>/,
the reduced files to <optimized-dir>/<session>/<signal>/. Each signal gets its own
tree, because full_pipeline skips grid cells whose file already exists.

The session is streamed from DANDI (dandiset 001768) by default, so --nwb-path is
the asset path inside the dandiset. Add --local to read --nwb-path from disk.

    python compute_waven_pipeline_mesoscope.py \\
        --nwb-path \\
        sub-832700/sub-832700_ses-multiplane-ophys-832700-2026-01-24-12-06-12_ophys.nwb \\
        --results-dir /path/to/rawresults/mesoscope --plane-idx 4
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

# Allen Open Scope multiplane ophys. Streaming is the default, as in the other
# drivers: `open_session` falls back to disk whenever dandiset_id is None, so
# reading a local copy has to be asked for with --local.
DEFAULT_DANDISET = '001768'

SIGNALS = ('events', 'dff')

# Delay x duration grid in seconds. Defined only here:
# compute_null_distribution_mesoscope.py imports it, so the null is always taken
# over the same test family.
DELAYS = np.arange(0.0, 0.18, 0.03)
DURATIONS = np.arange(0.0, 0.3, 0.1)


def main(nwb_path: str,
         results_dir: str | Path,
         plane_idx: int = 0,
         signal: str = 'events',
         phases: Sequence[str] = ('0', '1'),
         per_trial: bool = False,
         recompute: bool = False,
         optimize: bool = True,
         optimized_dir: str | Path = OPTIMIZED_DIR,
         dandiset_id: str | None = DEFAULT_DANDISET
         ) -> None:
    """Run the waven RF mapping on one imaging plane of a mesoscope session.

    Args:
        nwb_path: Asset path inside the dandiset, or a disk path if
            `dandiset_id` is None.
        results_dir: Root for the bulky per-(delay, duration) result files; the
            session name and signal are appended.
        plane_idx: Index into `NWBStream.imaging_planes()`.
        signal: Trace to correlate, 'events' (OASIS-deconvolved, stored in the
            NWB) or 'dff'.
        phases: Wavelet phases to run ('0', '1', 'complex').
        per_trial: One result set per Zebra repeat instead of pooling them.
        recompute: Recompute grid cells whose result file already exists.
        optimize: Reduce each result set over delay x duration to one row per
            ROI and save it under `optimized_dir`.
        optimized_dir: Root for the reduced one-row-per-ROI results; the
            session name and signal are appended.
        dandiset_id: Dandiset to stream from, or None to read `nwb_path` from disk.

    Raises:
        ValueError: If `signal` is neither 'events' nor 'dff'.
    """
    if signal not in SIGNALS:
        raise ValueError(f'signal must be one of {SIGNALS}, got {signal!r}')
    session_name = Path(nwb_path).stem
    results_dir = Path(results_dir) / session_name / signal
    optimized_dir = Path(optimized_dir) / session_name / signal

    if dandiset_id is None:
        print(f'Reading {nwb_path} FROM DISK (--local).')
    else:
        print(f'Streaming {nwb_path} from dandiset {dandiset_id}...')
    stream = utils.open_session(nwb_path, dandiset_id)

    plane = stream.imaging_planes()[plane_idx]
    traces_df = stream.dff_df(plane) if signal == 'dff' else stream.events_df(plane)
    unit_ids = traces_df.index.to_numpy()

    # pooled (default): one block holding all Zebra repeats; per trial: one block per repeat
    for block in zebra_blocks(stream.zebra_df(), per_trial):
        for phase in phases:
            attributes = {
                'session': session_name,
                'modality': 'mesoscope',
                'signal': signal,
                'group': plane,
                'plane': plane,
                'phase': phase,
                'date_computed': datetime.today().strftime('%Y-%m-%d'),
                **block.attributes,
            }

            lib_dir = full_pipeline(
                block.frame_onset_times,
                traces_df,
                DELAYS,
                DURATIONS,
                unit_ids,
                results_path=results_dir.joinpath(plane, *block.trial_part, f'phase_{phase}'),
                attributes=attributes,
                recompute=recompute,
                phase=phase,
                input_type='mesoscope',
                frame_index=block.frame_index,
            )

            if optimize:
                print(f'Optimizing parameters over {lib_dir}...')
                stem = '__'.join(['optimized', session_name, plane,
                                  *block.trial_part, f'phase_{phase}'])
                df = owp.optimize_parameters(results_dir=lib_dir,
                                             output_path=optimized_dir / (stem + '.csv'))
                df = owp.load_rf_maps(df)
                owp.save_rf_results(df, optimized_dir / (stem + '.h5'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--nwb-path', required=True, help='Path to the mesoscope NWB file')
    parser.add_argument('--results-dir', required=True,
                        help='Root directory for the per-(delay, duration) result files; '
                             '<session>/<signal>/ is appended.')
    parser.add_argument('--optimized-dir', default=str(OPTIMIZED_DIR),
                        help='Root directory for the reduced one-row-per-ROI results; '
                             f'<session>/<signal>/ is appended. Default: {OPTIMIZED_DIR}')
    parser.add_argument('--plane-idx', required=True, type=int,
                        help='Index of the imaging plane to process (0-based)')
    parser.add_argument('--signal', default='events', choices=SIGNALS,
                        help="Trace to correlate: the OASIS-deconvolved 'events' (default) "
                             "or raw 'dff'. Each signal gets its own results subtree.")
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
    main(args.nwb_path, args.results_dir, args.plane_idx, args.signal, tuple(args.phases),
         per_trial=args.per_trial, recompute=args.recompute,
         optimize=not args.no_optimize, optimized_dir=args.optimized_dir,
         dandiset_id=None if args.local else args.dandiset_id)
