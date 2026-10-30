# Author: Marcel C. Raabe
# Date: 2026-10-29
"""OASIS deconvolution of SLAP2 ΔF/F traces.

The mesoscope NWB files ship the deconvolved event series alongside ΔF/F
(`event_timeseries`, written by aind-ophys-oasis-event-detection). The SLAP2
release does not: dandiset 001424 carries only `F0` and `dFF` per DMD and
channel, so the events have to be computed here. This module runs the same
algorithm (`oasis.functions.deconvolve`, AR(1), parameters estimated from the
data) and caches the result next to the raw data, one file per
(session, DMD, channel).

Two things differ from the mesoscope capsule, both forced by how SLAP2 records:

* **Segments, not one trace.** SLAP2 images in ~30 s bouts with blanking in
  between, and blanks further short stretches of samples to NaN. OASIS assumes
  a continuously sampled AR process, so a trace is cut into maximal runs of
  finite samples with no acquisition gap inside, and each run is deconvolved on
  its own. Deconvolving across a gap would let the model explain a step between
  bouts as a burst of events.
* **Kinetics estimated per ROI, not per segment.** A single 30 s bout may hold
  too few transients to pin down the decay time, and a time constant that
  jumped from bout to bout would make the event amplitudes incomparable across
  a session. The AR coefficient and the noise level are therefore the medians
  over that ROI's segments, and only the baseline and the sparsity penalty are
  re-fitted per segment - which is what the per-bout baseline steps need.

Usage from a script:

    from utils.deconvolution import slap2_events_df
    events = slap2_events_df(nwb_path, 'DMD1', 'green', t_start=..., t_stop=...)

which returns the same layout as `NWBStream.slap2_dff()` and computes the cache
on first use. Or precompute from the command line:

    python -m utils.deconvolution --nwb-path <session.nwb> --dmd DMD1 --channel green
"""

from __future__ import annotations

import multiprocessing
import os
from datetime import datetime
from functools import partial
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
from oasis.functions import GetSn, ar1_to_tau, deconvolve, estimate_time_constant

# rawdata/allen_open_scope/derivatives/ already holds derived per-session data
# (the probe pickles, the extracted spike times), so the events go beside them.
EVENTS_DIR = (Path(__file__).resolve().parents[3]
              / 'rawdata' / 'allen_open_scope' / 'derivatives' / 'slap2_events')

# A gap this much longer than the median sampling interval ends a segment. The
# same rule as NWBStream.slap2_segments(), so segments line up with the bouts.
GAP_FACTOR = 5.0

# Shortest segment worth deconvolving, in samples. GetSn estimates the noise
# from a Welch periodogram whose default window is 256 samples, so anything
# shorter gets a noise level fitted to a truncated window. At ~215 Hz this is
# 1.2 s and costs <0.1 % of a SLAP2 session; those samples are left NaN and drop
# out downstream with the other blanked ones.
MIN_SEGMENT_SAMPLES = 256


def contiguous_segments(times, valid, gap_factor=GAP_FACTOR,
                        min_samples=MIN_SEGMENT_SAMPLES):
    """Index ranges of `valid` samples that hold no acquisition gap.

    times: (n_t,) sorted sample times; valid: (n_t,) bool, e.g. np.isfinite of a
    trace. Returns a list of (start, stop) index pairs, half-open, each at least
    `min_samples` long.
    """
    dt = np.median(np.diff(times))
    gap = np.zeros(len(times), dtype=bool)
    gap[1:] = np.diff(times) > gap_factor * dt

    prev_valid = np.concatenate([[False], valid[:-1]])
    next_valid = np.concatenate([valid[1:], [False]])
    gap_next = np.concatenate([gap[1:], [False]])

    starts = np.flatnonzero(valid & (~prev_valid | gap))
    stops = np.flatnonzero(valid & (~next_valid | gap_next)) + 1

    long_enough = (stops - starts) >= min_samples
    return list(zip(starts[long_enough], stops[long_enough], strict=False))


def _deconvolve_roi(args, gap_factor=GAP_FACTOR, min_samples=MIN_SEGMENT_SAMPLES):
    """Deconvolve one ROI segment by segment. `args` is (trace, times).

    Returns (events, params): events is the full-length event series, NaN
    wherever the input was NaN or the segment was too short; params holds the
    per-ROI AR coefficient, decay time and noise level, and the median baseline
    and sparsity penalty over the segments.
    """
    y, times = args
    events = np.full(len(y), np.nan)
    params = {k: np.nan for k in ('g_hat', 'tau_hat', 'sn_hat', 'b_hat', 'lam_hat')}

    segments = contiguous_segments(times, np.isfinite(y), gap_factor, min_samples)
    if not segments:
        return events, params

    # One set of kinetics per ROI: the median over its segments is robust to the
    # occasional bout that holds no transient to fit.
    sns, gs = [], []
    for i0, i1 in segments:
        seg = y[i0:i1]
        sn = GetSn(seg)
        g = np.atleast_1d(estimate_time_constant(seg, p=1, sn=sn))[0]
        sns.append(sn)
        if 0 < g < 1:            # an AR(1) coefficient outside (0, 1) is not a decay
            gs.append(g)

    sn_hat = float(np.median(sns))
    g_hat = float(np.median(gs)) if gs else None

    framerate = 1.0 / np.median(np.diff(times))
    tau_hat = ar1_to_tau(g_hat, framerate) if g_hat else None

    bs, lams = [], []
    for i0, i1 in segments:
        # an ROI whose decay could not be estimated anywhere falls back to
        # OASIS estimating it per segment
        res = (deconvolve(y[i0:i1], tau_d=tau_hat, framerate=framerate,
                          sn=sn_hat, b_nonneg=True, penalty=1) if tau_hat
               else deconvolve(y[i0:i1], sn=sn_hat, b_nonneg=True, penalty=1))
        events[i0:i1] = res.s
        bs.append(res.b)
        lams.append(res.lam)

    params.update(g_hat=g_hat if g_hat else np.nan,
                  tau_hat=tau_hat if tau_hat else np.nan,
                  sn_hat=sn_hat,
                  b_hat=float(np.median(bs)),
                  lam_hat=float(np.median(lams)))
    return events, params


def deconvolve_traces(traces, times, gap_factor=GAP_FACTOR,
                      min_samples=MIN_SEGMENT_SAMPLES, n_procs=None):
    """Deconvolve every row of `traces` (n_rois, n_t) sampled at `times`.

    Returns (events, params): events has the shape of `traces`, params is a
    DataFrame with one row per ROI.
    """
    if traces.shape[1] != len(times):
        raise ValueError(f'{traces.shape[1]} samples but {len(times)} timestamps')

    # Pool sizes itself from os.cpu_count(), which reports the whole node rather
    # than this job's cgroup, so on a shared cluster node it would oversubscribe.
    if n_procs is None and os.environ.get('SLURM_CPUS_PER_TASK'):
        n_procs = int(os.environ['SLURM_CPUS_PER_TASK'])

    worker = partial(_deconvolve_roi, gap_factor=gap_factor, min_samples=min_samples)
    tasks = ((traces[i], times) for i in range(traces.shape[0]))
    with multiprocessing.Pool(processes=n_procs) as pool:
        results = pool.map(worker, tasks)

    events = np.stack([r[0] for r in results]).astype(np.float32)
    params = pd.DataFrame([r[1] for r in results])
    return events, params


def events_path(nwb_path, dmd, channel, events_dir=EVENTS_DIR):
    """Cache file for one (session, DMD, channel)."""
    session = Path(nwb_path).stem
    return Path(events_dir) / session / f'{session}__{dmd}__{channel}__events.h5'


def deconvolve_session(nwb_path, dmd='DMD1', channel='green', events_dir=EVENTS_DIR,
                       stream=None, n_procs=None, gap_factor=GAP_FACTOR,
                       min_samples=MIN_SEGMENT_SAMPLES):
    """Deconvolve one DMD/channel of a SLAP2 session and write the cache file.

    The whole session is deconvolved at once, not just a stimulus block: the
    result is reused by every analysis of that session, and the AR parameters
    should not depend on which block happens to be under study.
    """
    import utils

    out = events_path(nwb_path, dmd, channel, events_dir)
    out.parent.mkdir(parents=True, exist_ok=True)

    stream = stream if stream is not None else utils.open_local(str(nwb_path))
    dff = stream.slap2_dff(dmd, channel)
    times = dff.columns.to_numpy(dtype=float)
    traces = dff.to_numpy(dtype=np.float64)
    roi_ids = stream.slap2_rois(dmd)['roi_id'].to_numpy()

    print(f'Deconvolving {dmd}/{channel}: {traces.shape[0]} ROIs x {traces.shape[1]} samples '
          f'at {1 / np.median(np.diff(times)):.0f} Hz...')
    events, params = deconvolve_traces(traces, times, gap_factor, min_samples, n_procs)

    n_segments = len(contiguous_segments(times, np.isfinite(traces).all(axis=0),
                                         gap_factor, min_samples))
    print(f'{n_segments} segments, median tau {params["tau_hat"].median():.3f} s, '
          f'{100 * np.mean(np.nan_to_num(events) > 0):.1f} % of samples carry an event')

    # write to a temp file and rename, so a run killed midway never leaves a
    # half-written cache behind, and two jobs computing the same file are safe
    tmp = out.with_suffix(f'.tmp{os.getpid()}.h5')
    try:
        with h5py.File(tmp, 'w') as hf:
            hf.attrs['session'] = Path(nwb_path).stem
            hf.attrs['dmd'] = dmd
            hf.attrs['channel'] = channel
            hf.attrs['n_segments'] = n_segments
            hf.attrs['gap_factor'] = gap_factor
            hf.attrs['min_segment_samples'] = min_samples
            hf.attrs['oasis'] = 'AR(1), penalty=1, b_nonneg=True; g and sn per ROI'
            hf.attrs['date_computed'] = datetime.today().strftime('%Y-%m-%d')
            hf.create_dataset('events', data=events, compression='gzip', compression_opts=4)
            hf.create_dataset('timestamps', data=times)
            hf.create_dataset('roi_ids', data=roi_ids)
            for name in params:
                hf.create_dataset(name, data=params[name].to_numpy())
        tmp.replace(out)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

    print(f'Wrote {out}')
    return out


def slap2_events_df(nwb_path, dmd='DMD1', channel='green', t_start=None, t_stop=None,
                    events_dir=EVENTS_DIR, stream=None, recompute=False, n_procs=None):
    """Deconvolved events for one DMD/channel, as NWBStream.slap2_dff() returns ΔF/F.

    Shape (n_rois, n_timepoints) with timestamps as columns and the ROI order of
    slap2_rois(dmd). The cache is computed on first use; `t_start` / `t_stop`
    restrict what is read back, as in slap2_dff().
    """
    path = events_path(nwb_path, dmd, channel, events_dir)
    if recompute or not path.exists():
        deconvolve_session(nwb_path, dmd, channel, events_dir=events_dir,
                           stream=stream, n_procs=n_procs)

    with h5py.File(path, 'r') as hf:
        times = hf['timestamps'][:]
        i0 = 0 if t_start is None else int(np.searchsorted(times, t_start))
        i1 = len(times) if t_stop is None else int(np.searchsorted(times, t_stop))
        events = hf['events'][:, i0:i1]

    return pd.DataFrame(events, columns=times[i0:i1])


if __name__ == '__main__':
    import argparse
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[1]))

    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--nwb-path', required=True, help='Path to the SLAP2 NWB file')
    parser.add_argument('--dmd', default='DMD1',
                        help="DMD imaging plane, or 'all' for every DMD in the session")
    parser.add_argument('--channel', default='green', choices=['green', 'red', 'all'],
                        help="'green' (iGluSnFR4f), 'red' (RCaMP3), or 'all'")
    parser.add_argument('--events-dir', default=str(EVENTS_DIR),
                        help=f'Where the cache files go. Default: {EVENTS_DIR}')
    parser.add_argument('--n-procs', type=int, default=None,
                        help='Worker processes; default is one per core')
    parser.add_argument('--recompute', action='store_true',
                        help='Overwrite cache files that already exist')
    args = parser.parse_args()

    import utils

    stream = utils.open_local(args.nwb_path)
    dmds = stream.dmds() if args.dmd == 'all' else [args.dmd]
    channels = ['green', 'red'] if args.channel == 'all' else [args.channel]

    for dmd in dmds:
        for channel in channels:
            out = events_path(args.nwb_path, dmd, channel, args.events_dir)
            if out.exists() and not args.recompute:
                print(f'{out} exists, skipping')
                continue
            deconvolve_session(args.nwb_path, dmd, channel, events_dir=args.events_dir,
                               stream=stream, n_procs=args.n_procs)
