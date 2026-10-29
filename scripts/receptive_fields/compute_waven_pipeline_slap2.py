# Author: Marcel C. Raabe
# Date: 2026-10-29
"""Waven RF mapping of the Zebra noise movie, SLAP2 sessions.

The SLAP2 counterpart of `compute_waven_pipeline_mesoscope.py`. Three things
differ from the mesoscope version, all forced by how SLAP2 records:

* **Resampling direction.** SLAP2 samples at ~200 Hz against a 30 fps movie, so
  there are ~6 imaging samples per frame instead of the mesoscope's one sample
  per three frames. The pipeline's `slap2` input type therefore averages dF/F
  per movie frame rather than looking up a frame per imaging sample, which
  keeps the design matrix at one row per frame instead of six near-duplicates.

* **Gaps.** Imaging runs in bouts with blanking in between, and short stretches
  of samples are NaN. Frames whose response window is less than `MIN_COVERAGE`
  (95 %) imaged are dropped from stimulus and response alike rather than filled
  in. Bouts are not mean-centred: on sub-829704 (both DMDs, whole recording) the
  dF/F step across a gap is no larger than the step between neighbouring windows
  inside a bout (explore_slap2.ipynb), so there is no baseline offset to remove.
  How much the gaps cost depends on the session: on sub-829704 ~97 % of frames
  are kept, but nothing guarantees that elsewhere, and the fraction retained is
  written to every result file (`frac_frames_covered`).

* **Repeats are pooled.** A single Zebra repeat may retain too few imaged frames
  to correlate against, so by default all repeats go into one design matrix,
  with `frame_index` mapping each onset back to its row of the decomposition.
  `--per-trial` restores the mesoscope behaviour of one result set per repeat,
  which is what the repeatability checks need. (sub-829704 has only one repeat,
  so the two are equivalent there.)

Two DMDs x two colour channels means four runs per session. Green is
iGluSnFR4f, fast enough to resolve single movie frames; red is RCaMP3, whose
calcium kinetics blur the response across frames no matter which window is
chosen - so each channel gets its own delay/duration grid.

The correlation runs against the deconvolved events by default; `--signal dff`
restores the raw ΔF/F. The SLAP2 release carries no events (unlike the mesoscope
one), so `utils.deconvolution` computes and caches them per session, DMD and
channel on first use.

The two outputs go to different places: the per-(delay, duration) files are
bulky and land in the HDD workspace, while the reduced one-row-per-unit results
go to the project results tree. Each signal gets its own subtree in both.

The session is streamed from DANDI (dandiset 001424) by default, so --nwb-path is
the asset path inside the dandiset. Add --local to read --nwb-path from disk.

    python compute_waven_pipeline_slap2.py \
        --nwb-path sub-829704/sub-829704_ses-829704-2025-12-18-10-57-36_image+ophys.nwb \
        --results-dir /mnt/ceph-hdd/workspaces/ws/cidbn_wibral_neuro_nonhuman/u19361-allen-hdd \
        --dmd DMD1 --channel green
"""

import argparse
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import numpy as np
import optimize_waven_parameters as owp
import pandas as pd
import utils
from utils import NWBStream, deconvolution
from waven_pipeline import MIN_COVERAGE, full_pipeline, zebra_blocks

OPTIMIZED_DIR = Path('/mnt/ceph-hdd/projects/cidbn_wibral_neuro_nonhuman/'
                     'SPP2205_mraabe/results/allen_open_scope/rf/waven/zebra/optimized')

# Allen Open Scope SLAP2. Streaming is the default, as in the null scripts:
# `open_session` falls back to disk whenever dandiset_id is None, so reading a
# local copy has to be asked for with --local.
DEFAULT_DANDISET = '001424'

# One Zebra frame is 1/30 s. Green (iGluSnFR4f) decays in tens of milliseconds,
# so it is the one signal in this dataset that can be integrated over a single
# frame; durations beyond ~0.1 s only smear it across neighbours. Red (RCaMP3)
# is a calcium sensor - its rise alone outlasts a frame, so the grid is shifted
# later and wider and the maps it yields are a lower-resolution cross-check
# rather than a second independent estimate.
# Defined only here: compute_null_distribution_slap2.py imports it, so the null
# is always taken over the same test family.
GRIDS = {
    'green': {
        'delays':    np.arange(0.0, 0.15, 0.025),
        'durations': np.array([1 / 30, 1 / 15, 0.1]),
    },
    'red': {
        'delays':    np.arange(0.0, 0.4, 0.05),
        'durations': np.array([0.1, 0.25, 0.5]),
    },
}


def load_signal(stream: NWBStream, 
                dmd: str, 
                channel: str, 
                t_start: float, 
                t_stop: float,
                signal: str = 'dff',
                nwb_path: str | None = None
                ) -> tuple[pd.DataFrame, list[str]]:
    """Load the traces of one DMD/channel over [t_start, t_stop].

    Only the Zebra block is read: the full-session traces are several hundred MB
    per channel, and everything outside the block is dead weight in the cumulative
    sums downstream.

    Args:
        stream: Open session returned by `utils.open_session`.
        dmd: DMD imaging plane, e.g. 'DMD1' or 'DMD2'.
        channel: Colour channel, 'green' or 'red'.
        t_start: Start of the window to read, in session seconds.
        t_stop: End of the window to read, in session seconds.
        signal: 'dff' for ΔF/F, 'events' for the deconvolved series.
        nwb_path: Session path; only used by the 'events' signal, to locate the
            cached deconvolution.

    Returns:
        traces_df: Traces over the window, one row per ROI, sample times as columns.
        unit_ids: One name per ROI, formatted '{dmd}_{channel}_roi{roi_id}'.

    Raises:
        ValueError: If `signal` is neither 'dff' nor 'events'.
    """
    if signal == 'dff':
        traces_df = stream.slap2_dff(dmd, channel, t_start=t_start, t_stop=t_stop)
    elif signal == 'events':
        traces_df = deconvolution.slap2_events_df(nwb_path, dmd, channel, t_start=t_start,
                                                  t_stop=t_stop, stream=stream)
    else:
        raise ValueError(f"signal must be 'dff' or 'events', got {signal!r}")

    roi_ids = stream.slap2_rois(dmd)['roi_id'].to_numpy()
    unit_ids = [f'{dmd}_{channel}_roi{roi_id}' for roi_id in roi_ids]
    return traces_df, unit_ids


def main(nwb_path: str,
         results_dir: str | Path,
         dmd: str = 'DMD1',
         channel: str = 'green',
         phases: Sequence[str] = ('0', '1'),
         signal: str = 'events',
         per_trial: bool = False,
         fps: float = 30.0,
         min_coverage: float = MIN_COVERAGE,
         recompute: bool = False,
         optimize: bool = True,
         optimized_dir: str | Path = OPTIMIZED_DIR,
         dandiset_id: str | None = DEFAULT_DANDISET
         ) -> None:
    """Run the Waven RF mapping on one SLAP2 session, DMD and channel.

    For each trial (or all repeats pooled) and each wavelet phase, runs
    `full_pipeline` over the channel's delay x duration grid and, if requested,
    reduces the resulting files to one row per unit.

    Args:
        nwb_path: Asset path inside the dandiset, or a disk path if
            `dandiset_id` is None.
        results_dir: Root for the bulky per-(delay, duration) result files; the
            session name and signal are appended.
        dmd: DMD imaging plane, e.g. 'DMD1' or 'DMD2'.
        channel: Colour channel, 'green' (iGluSnFR4f) or 'red' (RCaMP3); selects
            the delay/duration grid from `GRIDS`.
        phases: Wavelet phases to run ('0', '1', 'complex').
        signal: Trace to correlate, 'events' (deconvolved) or 'dff'.
        per_trial: One result set per Zebra repeat instead of pooling them.
        fps: Frame rate assumed when reconstructing frame onsets.
        min_coverage: Fraction of a response window's time that must be imaged
            for the frame to be kept.
        recompute: Recompute grid cells whose result file already exists.
        optimize: Reduce each result set over delay x duration to one row per
            unit and save it under `optimized_dir`.
        optimized_dir: Root for the reduced one-row-per-unit results.
        dandiset_id: Dandiset to stream from, or None to read `nwb_path` from disk.

    Raises:
        ValueError: If `dmd` is not present in the session.
    """

    session_name = Path(nwb_path).stem
    # full_pipeline skips grid cells whose file exists and the optimized stems
    # carry no signal, so each signal needs its own subtree in both places
    results_dir = Path(results_dir) / session_name / signal
    optimized_dir = Path(optimized_dir)

    delays = GRIDS[channel]['delays']
    durations = GRIDS[channel]['durations']

    if dandiset_id is None:
        print(f'Reading {nwb_path} FROM DISK (--local).')
    else:
        print(f'Streaming {nwb_path} from dandiset {dandiset_id}...')
    stream = utils.open_session(nwb_path, dandiset_id)
    if dmd not in stream.dmds():
        raise ValueError(f'{dmd!r} not in this session; available: {stream.dmds()}')

    # one row per movie frame per repeat; 'frame' is the row of the decomposition
    zebra_frames = stream.zebra_frame_times(fps=fps)

    # read only the Zebra block, with room for the longest response window
    margin = float(delays.max() + np.abs(durations).max() + 1.0)
    t_start = zebra_frames['start_time'].min() - margin
    t_stop = zebra_frames['stop_time'].max() + margin
    traces_df, unit_ids = load_signal(stream, dmd, channel, t_start, t_stop,
                                        signal=signal, nwb_path=nwb_path)

    # pooled (default): one block holding all Zebra repeats; per trial: one block per repeat
    for block in zebra_blocks(zebra_frames, per_trial):
        trial_part = block.trial_part
        frame_onset_times = block.frame_onset_times
        frame_index = block.frame_index

        for phase in phases:
            attributes = {
                'session': session_name,
                'modality': 'slap2',
                'signal': signal,
                'group': f'{dmd}_{channel}',
                'dmd': dmd,
                'channel': channel,
                'phase': phase,
                'fps_assumed': fps,
                'date_computed': datetime.today().strftime('%Y-%m-%d'),
                **block.attributes,
            }

            lib_dir = full_pipeline(
                frame_onset_times,
                traces_df,
                delays,
                durations,
                unit_ids,
                results_path=results_dir.joinpath(dmd, channel, *trial_part, f'phase_{phase}'),
                attributes=attributes,
                recompute=recompute,
                phase=phase,
                input_type='slap2',
                frame_index=frame_index,
                min_coverage=min_coverage,
            )

            if optimize:
                print(f'Optimizing parameters over {lib_dir}...')
                stem = '__'.join(['optimized', session_name, dmd, channel,
                                  *trial_part, f'phase_{phase}'])
                outdir = optimized_dir / session_name / signal
                df = owp.optimize_parameters(results_dir=lib_dir,
                                             output_path=outdir / (stem + '.csv'))
                df = owp.load_rf_maps(df)
                owp.save_rf_results(df, outdir / (stem + '.h5'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nwb-path', required=True, help='Path to the SLAP2 NWB file')
    parser.add_argument('--results-dir', required=True,
                        help='Root directory for the per-(delay, duration) result files. '
                             'These are the bulky ones - the correlation matrix dominates - '
                             'so this normally points at the HDD workspace.')
    parser.add_argument('--optimized-dir', default=str(OPTIMIZED_DIR),
                        help='Root directory for the reduced one-row-per-unit results. '
                             f'Default: {OPTIMIZED_DIR}')
    parser.add_argument('--dmd', default='DMD1', help='DMD imaging plane, e.g. DMD1 or DMD2')
    parser.add_argument('--channel', default='green', choices=['green', 'red'],
                        help="'green' (iGluSnFR4f, default) or 'red' (RCaMP3)")
    parser.add_argument('--phases', nargs='+', default=['0', '1'],
                        choices=['0', '1', 'complex'], help='Wavelet phases to run')
    parser.add_argument('--signal', default='events', choices=['dff', 'events'],
                        help="Trace to correlate: the deconvolved 'events' (default), "
                             'computed and cached by utils.deconvolution on first use, '
                             "or raw 'dff'. Each signal gets its own results subtree.")
    parser.add_argument('--per-trial', action='store_true',
                        help='One result set per Zebra repeat instead of pooling them. '
                             'Needed for repeatability checks; note a single repeat may '
                             'retain few imaged frames.')
    parser.add_argument('--fps', type=float, default=30.0,
                        help='Frame rate assumed when reconstructing frame onsets from '
                             'the per-repeat Zebra intervals')
    parser.add_argument('--min-coverage', type=float, default=MIN_COVERAGE,
                        help="Fraction of a response window's time that must be imaged "
                             'for the frame to be kept')
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
    main(args.nwb_path, args.results_dir, args.dmd, args.channel, tuple(args.phases),
         signal=args.signal,
         per_trial=args.per_trial, fps=args.fps, min_coverage=args.min_coverage,
         recompute=args.recompute,
         optimize=not args.no_optimize, optimized_dir=args.optimized_dir,
         dandiset_id=None if args.local else args.dandiset_id)
