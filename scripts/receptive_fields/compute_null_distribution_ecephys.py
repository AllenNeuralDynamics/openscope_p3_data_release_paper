# Author: Marcel C. Raabe
# Date: 2026-10-29
"""
Null distribution of the sweep-wide maximum |correlation| for ecephys zebra sessions.

The statistic that `optimize_waven_parameters` reports per unit is a maximum over
the whole search: every Gabor filter x every (delay, duration) sweep point. A
p-value for it therefore needs the null distribution of *that same maximum*, so
each surrogate is itself maximised over the identical search space. This is the
single-step maxT construction: thresholding at the (1-alpha) quantile of the
surrogate maxima controls the family-wise error rate over every filter and sweep
point *within a unit*, so one critical value per unit is all that has to be
stored.

That is per-unit control only. Surrogates are never maximised over units, so at
alpha=0.05 roughly one unit in twenty passes by chance; correcting across the
~10^3 units on a probe needs FDR over the per-unit p-values on top.

The sweep grid here must be the SAME grid the observed correlations were computed
on, or the comparison is meaningless. By default it is compute_waven_pipeline_ecephys.py's
whole grid: all 13 delays (0, 0.01 ... 0.12) and all 5 durations, 65 sweep points,
so every rawresults file has a null. --delay-stride N thins it to a strict SUBSET
(every Nth delay; 2 gives 7 x 5 = 35 points, which is what the first nulls were
run on). A maximum over 65 points exceeds one over 35, so against a thinned null
the observed maximum must be restricted to the same points - which for a subset
means nothing more than ignoring the result files whose delay is not in the grid.
`optimize_waven_parameters.optimize_parameters` does that when given
--sweep-from-null pointing at the file written here.

Extending an existing file
--------------------------
The statistic is a maximum over sweep points, kept per (lag, unit, family). So a
file that holds only some of the sweep points asked for is not stale but partial:
the missing points are scanned WITH THE SAME ROLLS and the elementwise maximum of
old and new is exactly what one scan over all of them would have given. A 7 x 5
file is brought to 13 x 5 by scanning the 30 points in between, not all 65. This
needs the same units, library, movie, trial and surrogate rolls as the file, and a
file whose points are not all wanted cannot be reduced - either is recomputed.

The grid in force is written to the output as the `sweep_delays` and
`sweep_durations` attributes, and a consumer should read them rather than assume.
Choosing delays outside the waven grid (via --delays) is allowed but then there
are no matching result files and the observed side has to be recomputed.

Note that lag 0 rides along in the same pass, so `family_max[..., 0]` is the
observed maximum on *this* grid and is always self-consistent with the null
beside it. The mismatch only bites when thresholding correlations computed
elsewhere.

Surrogates come from circularly rolling each unit's per-frame rate vector. A roll
preserves the rate autocorrelation, the ISI structure, the burstiness and any
slow drift exactly, and breaks only the pairing with the stimulus - which is what
the null requires. Rolls are taken at least `--min-lag-sec` from either wrap so
that no residual alignment survives; the zebra movie's temporal autocorrelation
falls to ~0 within 3 frames, and the widest response window is 0.25 s, so the 1 s
default leaves a comfortable margin.

Repeats of the Zebra movie are pooled by default, as in compute_waven_pipeline_ecephys.py
(--per-trial gives one null per repeat). The rate is averaged over repeats per
movie frame and rescaled per unit (`waven_pipeline.pool_repeats`), which gives
exactly the correlation on the stacked repeats; a roll of that average is the same
roll applied to every repeat.

Lag 0 is carried through the same pass as element 0 of the lag set, so the
observed statistic and its null are produced by identical code on an identical
grid and cannot drift apart.

Efficiency
----------
The row-normalised stimulus matrix is (n_filters, n_frames) - tens of GB - and it
does not depend on delay, duration, or lag. So the filter axis is the outer loop
and it streams exactly once per (movie, library, phase); everything else stays
resident on the GPU. Calling Waven's `PearsonCorrelationPinkNoise` once per
surrogate would instead re-normalise and re-stream that matrix
n_sweep_points * n_lags times.

Only the per-family maxima are kept: a (n_units, n_families, n_lags) array of a
few tens of MB, against terabytes for per-filter surrogates.

Validation
----------
Run with `--n-surrogates 0` on a SINGLE sweep point:

  --delays 0.0 --durations 0.1 --n-surrogates 0 --phases 0

Then `family_max[:, :, 0].max(axis=1)` is exactly what one existing result file
holds in `abs_max_value`: the maximum over filters at that (delay, duration).
Match the units by id, since near-silent ones are screened out here.

The single sweep point is what makes a single-file comparison valid. Over the
full 13 x 5 grid, lag 0 would be the maximum over all 65 files and would have to
be compared against `optimize_waven_parameters`' output instead.

Agreement is limited to ~1e-4 absolute because the stimulus is cached as float16;
a difference of that order is expected, not a failure. Note also that
`PearsonCorrelationPinkNoise` applies `rfs -= (rfs >= 0.99)` and `nan_to_num`,
which this script does not replicate - irrelevant for spike data, but it would
show up here if a correlation ever reached 0.99.

Usage
-----
The session is streamed from DANDI by default, so --nwb-path is an asset path
inside the dandiset rather than a file on disk:

  python compute_null_distribution_ecephys.py \
      --nwb-path sub-830794/sub-830794_ses-ecephys-830794-2026-01-26-12-02-05_ecephys.nwb \
      --results-dir /path/allen/rf/zebra/nullresults/ecephys/<session> \
      --probe-idx 0

Add --local to read --nwb-path from disk instead.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

import h5py
import numpy as np
import torch
import utils
import waven_pipeline as wp
from tqdm import tqdm
from waven_settings import frequencies, movpath, offsets, sigmas, thetas, xs, ys

# Fewest spikes a unit must fire inside the zebra block to be worth testing.
# `_row_normalize` clamps the norm rather than raising, so a near-silent unit
# silently produces garbage correlations instead of an error - and would cost the
# full surrogate budget to do so.
MIN_SPIKES = 100

# Allen Open Scope ecephys. Streaming is the default rather than an opt-in:
# `open_session` falls back to reading from disk whenever dandiset_id is None, and
# a local copy is easy to have lying around at a stale revision. Reading from
# disk therefore has to be asked for explicitly, with --local.
DEFAULT_DANDISET = '001637'

# Spikes are the only signal of this modality; still a folder level and an
# attribute, as in compute_waven_pipeline_ecephys.py, so all modalities share a layout.
SIGNAL = 'spikes'

# The sweep compute_waven_pipeline_ecephys.py uses, imported rather than copied so the
# two cannot drift apart; the null's grid can still be a strict subset of it
# (--delay-stride).
from compute_waven_pipeline_ecephys import DELAYS as WAVEN_DELAYS  # noqa: E402
from compute_waven_pipeline_ecephys import DURATIONS as WAVEN_DURATIONS  # noqa: E402

# Frames per chunk when building the normalised cache. Only sets how much of the
# input is held at once (frame_block * n_filters * 4 B, ~3.3 GB at 300) and how
# large each RAM scatter is. The I/O is sequential regardless, so this is a
# memory knob, not a throughput one - unlike the filter-block it replaced, where
# the value decided whether the build finished at all.
BUILD_FRAME_BLOCK = 300


# ---------------------------------------------------------------------------
# locating the decomposition
# ---------------------------------------------------------------------------

def settings_lib_id() -> str:
    """Library id the current waven_settings would produce, without building it.

    Mirrors the serialisation in `create_gabor_library`. Computing the hash
    directly matters because calling that function would write a multi-GB filter
    library as a side effect when the settings have moved on from whatever the
    existing results were computed with.
    """
    props = {
        'xs': list(map(int, xs)),
        'ys': list(map(int, ys)),
        'thetas': list(map(float, thetas)),
        'sigmas': list(map(float, sigmas)),
        'offsets': list(map(float, offsets)),
        'frequencies': list(map(float, frequencies)),
    }
    serialized = json.dumps(props, sort_keys=True, separators=(',', ':'),
                            ensure_ascii=False)
    return hashlib.sha1(serialized.encode('utf-8')).hexdigest()[:10]


def resolve_decomposition(lib_id, phases, movie_path, allow_build=False,
                          decomp_dir=None):
    """Directory holding dwt_videodata_{phase}.npy, and the library id used.

    Only the decomposition is needed here, never the filter library itself, so
    this resolves the path and checks it rather than invoking Waven's builders.
    A missing decomposition is an error by default: building one is a ~100 GB,
    many-hour job that should be a deliberate act, not a side effect of asking
    for a null distribution.

    `decomp_dir` overrides the derived path. Decompositions written before the
    movie stem was added to the layout sit one level up from where
    `get_path_wavelet_decomposition` now looks, so an explicit path is the only
    way to reach them.
    """
    if lib_id is None:
        lib_id = settings_lib_id()
    if decomp_dir is not None:
        decomp_dir = Path(decomp_dir)
        missing = [p for p in phases
                   if not (decomp_dir / f'dwt_videodata_{p}.npy').exists()]
        if missing:
            raise FileNotFoundError(
                f'No dwt_videodata_{{{",".join(missing)}}}.npy under {decomp_dir}')
        # The directory is named lib-<id> by convention, so it can say which
        # library it holds. Without this the id recorded in the output - and used
        # to key the normalised cache - would be whatever the settings hash to,
        # which need not be the library the decomposition was built from.
        dir_lib = decomp_dir.name[4:] if decomp_dir.name.startswith('lib-') else None
        if dir_lib and dir_lib != lib_id:
            raise ValueError(
                f'--decomp-dir names library {dir_lib} but the library id in use is '
                f'{lib_id}. Pass --lib-id {dir_lib} so the output and the '
                'normalised cache are labelled with the library actually read.')
        return decomp_dir, lib_id
    decomp_dir = (movie_path.parent / 'wavelet_decompositions'
                  / movie_path.stem / f'lib-{lib_id}')

    missing = [p for p in phases
               if not (decomp_dir / f'dwt_videodata_{p}.npy').exists()]
    if missing and not allow_build:
        available = sorted(
            d.name for d in (movie_path.parent / 'wavelet_decompositions'
                             / movie_path.stem).glob('lib-*')) \
            if (movie_path.parent / 'wavelet_decompositions' / movie_path.stem).exists() \
            else []
        raise FileNotFoundError(
            f'No decomposition for phase(s) {missing} of lib {lib_id} under '
            f'{decomp_dir}.\nAvailable: {available or "none"}.\n'
            'Pass --lib-id to use an existing decomposition, or --allow-build to '
            'compute one (expect ~100 GB per phase and several hours).')

    if missing:
        print(f'Building filter library and decomposition for lib {lib_id}...')
        lib_path = wp.create_gabor_library(xs, ys, thetas, sigmas, offsets, frequencies)
        built = Path(wp.get_path_wavelet_decomposition(
            library_path=lib_path, movpath=movie_path))
        if built != decomp_dir:
            raise RuntimeError(
                f'built decomposition at {built} but expected {decomp_dir}')

    if lib_id != settings_lib_id():
        print(f'NOTE: using lib {lib_id}, which does not match the current '
              f'waven_settings ({settings_lib_id()}). Filter axis sizes are taken '
              'from the decomposition, so family grouping stays correct, but the '
              'sigma/frequency values in waven_settings do not describe this '
              'library.')
    return decomp_dir, lib_id


# ---------------------------------------------------------------------------
# normalisation helpers
# ---------------------------------------------------------------------------

def _znorm_rows(x: np.ndarray) -> np.ndarray:
    """Mean-centre and L2-normalise each row, matching Waven's _row_normalize."""
    x = np.asarray(x, dtype=np.float32)
    x = x - x.mean(axis=1, keepdims=True)
    n = np.linalg.norm(x, axis=1, keepdims=True)
    np.maximum(n, 1e-8, out=n)
    return x / n


def znorm_name(movie_stem: str, lib_id: str, phase: str) -> str:
    """Filename of the cached normalised stimulus.

    The movie stem is part of the key, not just the library id. Several stimulus
    movies (the zebra scale variants) share a filter library, so a key of
    (library, phase) alone would let the second movie silently reuse the first
    one's bytes and every variant would yield identical results. This is the same
    trap `get_path_wavelet_decomposition` was fixed for; the cache sits in one
    flat directory shared by every probe, so it is even easier to hit here.
    """
    return f'znorm__{movie_stem}__lib-{lib_id}__phase-{phase}.npy'


def build_znorm_stim(decomp_path: Path, znorm_dir: Path, lib_id: str, movie_stem: str,
                     frame_block: int = BUILD_FRAME_BLOCK) -> tuple[Path, int, tuple]:
    """Write the row-normalised, transposed decomposition as a float16 memmap.

    The decomposition is stored (n_frames, *filter_dims); the correlation needs
    (n_filters, n_frames). Every read here is SEQUENTIAL, which is the whole point
    of the structure below.

    The obvious implementation loops over filter blocks - normalising needs a
    filter's whole time series, and the write is then contiguous. But the read
    `dec2[:, f0:f1]` takes one run per frame and skips n_filters * 4 B (~11 MB) to
    the next, so it walks the entire 100 GB file in strides. On ceph that is
    hopeless at any block size: the object store fetches whole multi-MB objects to
    deliver part of each, and the pass effectively never completes. Enlarging the
    run only reduces the amplification factor, it does not remove the seeking.

    So the transpose happens in RAM instead, which works because the float16
    OUTPUT is half the size of the float32 input and fits:

      pass 1  stream frame blocks in order, accumulating per-filter sum and sum of
              squares (n_filters float64 each, ~44 MB) -> mean and norm
      pass 2  stream frame blocks in order again, normalise with those, and
              scatter the transposed float16 into a RAM-resident output
      write   one sequential pass of the finished array to disk

    Cost: two sequential reads of the input and one sequential write, against a
    RAM residency of n_filters * n_frames * 2 B (49.9 GB at current settings) plus
    a frame block. Strided access is confined to RAM, where it is ~100x cheaper
    than on ceph.

    `frame_block` trades memory for the size of those RAM scatters; it has almost
    no effect on the I/O, which is sequential regardless.

    float16 is safe here: the z-scored entries are O(1/sqrt(n_frames)), the
    per-element rounding error is independent across the sum, and the GEMM
    accumulates in float32. The residual error on a correlation is ~1e-5.
    """
    dec = np.load(decomp_path, mmap_mode='r')
    n_frames = dec.shape[0]
    filt_shape = tuple(dec.shape[1:])
    n_filters = int(np.prod(filt_shape))

    phase = decomp_path.stem.rsplit('_', 1)[-1]
    out_path = Path(znorm_dir) / znorm_name(movie_stem, lib_id, phase)

    if out_path.exists():
        # The name cannot express every way a cache could be stale - --decomp-dir
        # accepts a directory whose library is not `lib_id` - so the shape is
        # checked against the decomposition this run actually reads.
        cached_shape = np.load(out_path, mmap_mode='r').shape
        if cached_shape != (n_filters, n_frames):
            print(f'Cached {out_path.name} is {cached_shape} but this '
                  f'decomposition needs {(n_filters, n_frames)} — rebuilding')
            out_path.unlink()
        else:
            print(f'Reusing normalised stimulus at {out_path}')
            return out_path, n_frames, filt_shape

    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Unique per process: the cache key has no probe in it, so every probe's job
    # wants the same file. A shared tmp name would let two of them write the same
    # bytes at once and corrupt both. Identical content means whichever rename
    # lands last is still correct.
    tmp_path = out_path.with_suffix(f'.npy.tmp{os.getpid()}')
    ram_gb = n_filters * n_frames * 2 / 1e9
    chunk_gb = frame_block * n_filters * 4 / 1e9
    print(f'Normalising {decomp_path.name} -> {out_path.name}\n'
          f'  {n_filters} filters x {n_frames} frames, '
          f'{ram_gb:.1f} GB float16 out, '
          f'{n_filters * n_frames * 4 / 1e9:.1f} GB in\n'
          f'  sequential: 2 read passes + 1 write; '
          f'{-(-n_frames // frame_block)} frame blocks of {frame_block}\n'
          f'  RAM needed: {ram_gb:.1f} GB output + {chunk_gb:.1f} GB per chunk '
          f'= {ram_gb + 2 * chunk_gb:.1f} GB')

    dec2 = dec.reshape(n_frames, n_filters)
    starts = range(0, n_frames, frame_block)
    try:
        # Pass 1: per-filter mean and L2 norm of the centred series, from sums.
        # Accumulating in float64 keeps sumsq - n*mean**2 well conditioned; the
        # wavelet responses are near zero-mean, so there is no cancellation risk
        # at this precision.
        total = np.zeros(n_filters, dtype=np.float64)
        sqtotal = np.zeros(n_filters, dtype=np.float64)
        for t0 in tqdm(starts, desc='pass 1/2 stats', unit='blk'):
            chunk = np.asarray(dec2[t0:min(t0 + frame_block, n_frames)])
            total += chunk.sum(axis=0, dtype=np.float64)
            sqtotal += np.einsum('ij,ij->j', chunk, chunk, dtype=np.float64)
            del chunk

        mean = (total / n_frames).astype(np.float32)
        nrm = np.sqrt(np.maximum(sqtotal - n_frames * (total / n_frames) ** 2, 0.0))
        np.maximum(nrm, 1e-8, out=nrm)
        nrm = nrm.astype(np.float32)

        # Pass 2: normalise each frame block and scatter it into the RAM-resident
        # transpose. Writing a column slice of a C-contiguous array is strided, but
        # in RAM rather than on the filesystem.
        try:
            ram = np.empty((n_filters, n_frames), dtype=np.float16)
        except MemoryError:
            raise MemoryError(
                f'need {ram_gb:.0f} GB of RAM for the transposed cache plus '
                f'{2 * chunk_gb:.0f} GB of chunk buffers. Raise the job\'s --mem, or '
                'lower --build-frame-block to shrink the chunks (the output array '
                'is fixed by the filter count and frame count).') from None
        for t0 in tqdm(starts, desc='pass 2/2 write', unit='blk'):
            t1 = min(t0 + frame_block, n_frames)
            # np.array, not np.asarray: the decomposition is already float32, so
            # asarray would hand back a read-only view of the memmap and the
            # in-place normalisation below would fail.
            chunk = np.array(dec2[t0:t1], dtype=np.float32)
            chunk -= mean
            chunk /= nrm
            ram[:, t0:t1] = chunk.T.astype(np.float16)
            del chunk

        out = np.lib.format.open_memmap(
            tmp_path, mode='w+', dtype=np.float16, shape=(n_filters, n_frames))
        row_block = max(1, 1_000_000_000 // (n_frames * 2))
        for f0 in tqdm(range(0, n_filters, row_block), desc='flush', unit='blk'):
            f1 = min(f0 + row_block, n_filters)
            out[f0:f1] = ram[f0:f1]
        out.flush()
        del out, ram
        tmp_path.rename(out_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise

    return out_path, n_frames, filt_shape


# ---------------------------------------------------------------------------
# sweep grid and surrogate lags
# ---------------------------------------------------------------------------

def default_delays(stride: int) -> np.ndarray:
    """Every `stride`-th delay of the waven pipeline's own grid (1: all of them).

    Deliberately compute_waven_pipeline_ecephys.py's delays, or a SUBSET of them, rather
    than an independently chosen grid. The null must be maximised over the same
    test family as the observed maximum it is compared against, and a subset can
    be matched by simply restricting which existing per-(delay, duration) result
    files the observed maximum is taken over - no recomputation. A grid at
    whole-frame steps would share only delay 0.0 with those files and would force
    the observed side to be recomputed from scratch.

    Thinning costs almost no power for the per-unit test - at a ~33.4 ms frame
    period a stride of 2 is a 0.6-frame step - but it leaves the rawresults files
    in between without a null, so their maps cannot be tested.
    """
    if stride < 1:
        raise ValueError(f'delay stride must be at least 1, got {stride}')
    return WAVEN_DELAYS[::stride]


def build_lags(n_frames: int, n_surrogates: int, min_lag: int) -> np.ndarray:
    """Lag 0 followed by `n_surrogates` roll offsets, evenly spread.

    Even spacing rather than random sampling: it maximises the spread for a
    given count and makes the run reproducible without a seed. Offsets stay
    `min_lag` away from both 0 and n_frames so neither the lag itself nor its
    wrap re-aligns the response with the stimulus.
    """
    if n_surrogates <= 0:
        return np.zeros(1, dtype=np.int64)
    if min_lag < 1:
        # A roll of 0 - and equally of n_frames, which linspace would then reach -
        # is the identity, so the observed statistic would be injected into its own
        # null and the p-value floored by however many such lags were drawn.
        raise ValueError(
            f'min_lag must be at least 1 frame, got {min_lag}; a zero or '
            'whole-length roll leaves the response aligned with the stimulus.')
    if 2 * min_lag >= n_frames:
        raise ValueError(f'min_lag {min_lag} too large for {n_frames} frames')
    lags = np.linspace(min_lag, n_frames - min_lag, n_surrogates)
    lags = np.unique(np.round(lags).astype(np.int64))
    return np.concatenate([[0], lags])


# ---------------------------------------------------------------------------
# responses
# ---------------------------------------------------------------------------

def response_matrices(frame_onset_times, frame_index, spiketimes, grid, n_frames, device):
    """Row-normalised rate matrices for the (delay, duration) of `grid`, on `device`.

    Delay is not an integer roll - the grid steps are a fraction of a frame - so
    each (delay, duration) needs its own pass over the spike times. Normalising
    here rather than per surrogate is safe because a circular roll changes
    neither the mean nor the norm, so rolls of a normalised row stay normalised.

    Repeats are averaged per movie frame and the normalised row is multiplied by
    `scale`, exactly as in `full_pipeline` (see `waven_pipeline.pool_repeats`):
    a correlation with it is the correlation on the stacked repeats, and rolling
    the average is the same roll of every repeat, which leaves `scale` unchanged.
    With a single repeat `scale` is 1.
    """
    mats = []
    for delay, duration in grid:
        rate = wp.compute_neuron_rate_to_zebra_frames(
            frame_onset_times, spiketimes, delay, duration)
        mean_rate, scale = wp.pool_repeats(rate, frame_index, n_frames)
        mats.append(torch.as_tensor((_znorm_rows(mean_rate) * scale[:, None]).astype(np.float32),
                                    device=device))
    return mats


# ---------------------------------------------------------------------------
# the scan
# ---------------------------------------------------------------------------

@torch.no_grad()
def null_max_scan(znorm_path: Path, responses: list, lags: np.ndarray, n_families: int,
                  device, feat_block: int = 16384, lag_batch: int = 8,
                  expect_shape: tuple | None = None) -> np.ndarray:
    """Running maximum of |correlation| per (lag, unit, filter family).

    Returns (n_lags, n_units, n_families) float32. Column 0 of the lag axis is
    the observed value; the rest are the null.

    The maximum over (filters x sweep points) equals the maximum over sweep
    points of the maximum over filters, so one running buffer carried across the
    whole sweep needs no further bookkeeping.

    Families are the trailing axes of the filter grid, which vary fastest in the
    flat index. That makes the per-family reduction a reshape plus an amax,
    provided each block starts on a family boundary.
    """
    stim = np.load(znorm_path, mmap_mode='r')
    if expect_shape is not None and stim.shape != tuple(expect_shape):
        raise ValueError(
            f'{znorm_path} is {stim.shape} but this run needs {tuple(expect_shape)}; '
            'the cache does not belong to the decomposition being read.')
    n_filters, n_frames = stim.shape
    n_units = responses[0].shape[0]
    n_lags = len(lags)

    if n_filters % n_families:
        raise ValueError(
            f'{n_filters} filters is not a whole number of {n_families}-filter '
            'families; family_axes does not describe this filter grid.')
    if feat_block % n_families:
        feat_block -= feat_block % n_families
    if feat_block <= 0:
        raise ValueError(f'feat_block must be at least n_families={n_families}')

    maxbuf = torch.zeros(n_lags, n_units, n_families, device=device)

    for f0 in tqdm(range(0, n_filters, feat_block), desc='filter blocks'):
        f1 = min(f0 + feat_block, n_filters)
        n_block = f1 - f0
        if n_block % n_families:
            raise ValueError(
                f'filter block [{f0}, {f1}) is not a whole number of families; '
                f'n_filters={n_filters} must be divisible by n_families={n_families}')
        # float16 on disk, float32 on device: the upload is what the float16
        # storage buys, while a float32 GEMM keeps the output off the float16
        # grid so lag 0 can be compared against the existing results.
        block = torch.as_tensor(np.array(stim[f0:f1]), device=device).float()

        for resp in responses:
            for l0 in range(0, n_lags, lag_batch):
                sel = lags[l0:l0 + lag_batch]
                rolled = torch.cat(
                    [torch.roll(resp, int(lag), dims=1) for lag in sel], dim=0)
                corr = rolled @ block.T                       # (B*n_units, n_block)
                fam = (corr.abs()
                           .reshape(len(sel) * n_units, n_block // n_families, n_families)
                           .amax(dim=1)
                           .reshape(len(sel), n_units, n_families))
                maxbuf[l0:l0 + len(sel)] = torch.maximum(maxbuf[l0:l0 + len(sel)], fam)
                del rolled, corr, fam
        del block

    return maxbuf.cpu().numpy()


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------

def _stale_reason(out_path: Path, sweep_delays, durations, n_surrogates):
    """Why an existing file does not match this run, or None if it does.

    The filename carries only the library id, so a file written with a different
    sweep or surrogate count sits at the same path. Skipping on existence alone
    would silently hand back the validation gate's 13-delay, zero-surrogate file
    to a later production run - and a null taken over a different sweep than the
    observed maximum is not a valid null for it.
    """
    def _same(a, b):
        # Shapes first: np.allclose raises rather than returning False when the
        # operands cannot broadcast, which is exactly the mismatch being tested.
        a = np.unique(np.asarray(a, dtype=float))
        b = np.unique(np.asarray(b, dtype=float))
        return a.shape == b.shape and np.allclose(a, b)

    try:
        with h5py.File(out_path, 'r') as hf:
            got_d = np.unique(np.asarray(hf.attrs['sweep_delays'], dtype=float))
            got_u = np.unique(np.asarray(hf.attrs['sweep_durations'], dtype=float))
            got_n = int(hf.attrs['n_surrogates'])
    except (OSError, KeyError) as e:
        return f'unreadable: {e}'
    if not _same(got_d, sweep_delays):
        return f'delays {got_d} != {np.unique(np.asarray(sweep_delays, dtype=float))}'
    if not _same(got_u, durations):
        return f'durations {got_u} != {np.unique(np.asarray(durations, dtype=float))}'
    # Fewer surrogates than asked for is stale; more is not, since np.unique may
    # legitimately collapse requested lags.
    if got_n < n_surrogates:
        return f'{got_n} surrogates < {n_surrogates} requested'
    return None


def _grid_key(delay, duration) -> tuple:
    return (round(float(delay), 6), round(float(duration), 6))


def load_partial(out_path: Path, grid, n_surrogates, unit_names, n_families, expect):
    """What an existing file already holds of this run, or why it cannot be built on.

    Returns (prev, None) or (None, reason). prev carries the file's running maxima
    as (n_lags, n_units, n_families) - the layout `null_max_scan` returns - with
    the lags and the sweep points they were taken over.

    A file is built on when every sweep point in it is wanted, and everything that
    decides what its numbers mean is the same as in this run: the units and their
    order, the rolls, and `expect` (library, movie, trial, frame count, screen).
    Then max(file, scan of the missing points with the file's lags) is the maximum
    over all the points. Anything else makes the two halves maxima of different
    things, and the file is recomputed instead.
    """
    try:
        with h5py.File(out_path, 'r') as hf:
            attrs = dict(hf.attrs)
            ids = np.array([u.decode() if isinstance(u, bytes) else str(u)
                            for u in hf['unit_ids'][:]])
            lags = hf['lags'][:].astype(np.int64)
            family_max = hf['family_max'][:]
    except (OSError, KeyError) as e:
        return None, f'unreadable: {e}'

    for key, want in expect.items():
        got = attrs.get(key)
        if got is None or not np.array_equal(np.asarray(got), np.asarray(want)):
            return None, f'{key} {got} != {want}'
    if not np.array_equal(ids, np.asarray(unit_names, dtype=str)):
        return None, 'different units'
    # Fewer surrogates than asked for is stale; more is not, since np.unique may
    # legitimately collapse requested lags.
    if len(lags) - 1 < n_surrogates:
        return None, f'{len(lags) - 1} surrogates < {n_surrogates} requested'
    if lags[0] != 0 or family_max.shape != (len(ids), n_families, len(lags)):
        return None, f'family_max {family_max.shape} does not fit its units and lags'

    have = list(zip(np.asarray(attrs['grid_delays'], dtype=float).tolist(),
                    np.asarray(attrs['grid_durations'], dtype=float).tolist(), strict=False))
    extra = {_grid_key(*g) for g in have} - {_grid_key(*g) for g in grid}
    if extra:
        return None, (f'holds {len(extra)} sweep points this run does not ask for, '
                      f'e.g. {sorted(extra)[:3]}; a maximum cannot be reduced')
    return {'maxbuf': np.ascontiguousarray(family_max.transpose(2, 0, 1)),
            'lags': lags, 'grid': have}, None


def save_null(out_path: Path, unit_ids, n_spikes, lags, lag_seconds, maxbuf,
              grid, filt_shape, family_axes, attributes):
    """Write one null-distribution file, atomically.

    `family_max` is (n_units, n_families, n_lags); [..., 0] is the observed
    maximum per family and the remaining columns are the surrogate draws. The
    sweep-wide statistic is the maximum over the family axis, taken after
    studentising by each family's own null scale.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix('.h5.tmp')
    try:
        with h5py.File(tmp_path, 'w') as hf:
            for k, v in attributes.items():
                hf.attrs[k] = v
            hf.attrs['filter_shape'] = np.asarray(filt_shape, dtype=np.int64)
            hf.attrs['family_axes'] = family_axes
            # One entry per sweep point, in the order the maxima were accumulated:
            # delays repeat across durations, so these are NOT the unique grid
            # values. `delays`/`durations` below are, and are what a consumer must
            # match against the grid the observed correlations were computed on.
            hf.attrs['grid_delays'] = np.array([g[0] for g in grid])
            hf.attrs['grid_durations'] = np.array([g[1] for g in grid])
            hf.attrs['sweep_delays'] = np.unique([g[0] for g in grid])
            hf.attrs['sweep_durations'] = np.unique([g[1] for g in grid])

            hf.create_dataset('unit_ids', data=list(unit_ids),
                              dtype=h5py.string_dtype())
            hf.create_dataset('n_spikes', data=np.asarray(n_spikes))
            hf.create_dataset('lags', data=np.asarray(lags, dtype=np.int64))
            hf.create_dataset('lag_seconds', data=np.asarray(lag_seconds))
            hf.create_dataset('family_max',
                              data=np.ascontiguousarray(maxbuf.transpose(1, 2, 0)),
                              compression='gzip', compression_opts=4)
        if out_path.exists():
            out_path.unlink()
        tmp_path.rename(out_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    print(f'Saved {out_path}')
    return out_path


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------

def main(nwb_path, results_dir, probe_idx, dandiset_id=DEFAULT_DANDISET, phases=('0', '1'),
         n_surrogates=300, min_lag_sec=1.0, delay_stride=1, delays=None, durations=None,
         family_axes=2, feat_block=16384, build_frame_block=BUILD_FRAME_BLOCK, lag_batch=8,
         znorm_dir=None,
         min_spikes=MIN_SPIKES, recompute=False, lib_id=None, allow_build=False,
         decomp_dir=None, build_cache_only=False, per_trial=False):

    results_dir = Path(results_dir)
    session_name = Path(nwb_path).stem

    print('Locating wavelet decompositions...')
    movie_path = Path(movpath)
    decomp_dir, lib_id = resolve_decomposition(lib_id, phases, movie_path,
                                               allow_build, decomp_dir)
    print(f'  lib {lib_id} at {decomp_dir}')

    znorm_root = Path(znorm_dir) if znorm_dir is not None else decomp_dir

    # The cache depends only on (movie, library, phase) - not on the session, the
    # probe or the trial - and building it is pure numpy and I/O. So it can be
    # built once on a CPU node, before any GPU is allocated and without touching
    # DANDI at all. Every probe's job then finds it warm. Returning here keeps the
    # session open, the units table and the GPU entirely out of the prep step.
    if build_cache_only:
        print(f'Building the normalised cache only, into {znorm_root}')
        for phase in phases:
            build_znorm_stim(decomp_dir / f'dwt_videodata_{phase}.npy', znorm_root,
                             lib_id, movie_path.stem,
                             frame_block=build_frame_block)
        print('Cache ready; the per-probe array jobs can now run together.')
        return

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    if device.type == 'cpu':
        print('WARNING: no CUDA device — this will be far too slow for a full run.')

    if dandiset_id is None:
        print(f'Reading {nwb_path} FROM DISK (--local).')
    else:
        print(f'Streaming {nwb_path} from dandiset {dandiset_id}...')
    stream = utils.open_session(nwb_path, dandiset_id)
    units_df = stream.units_df()
    probe = units_df['probe'].unique()[probe_idx]
    all_unit_names = units_df.loc[units_df['probe'] == probe, 'unit_name'].values
    all_spiketimes = units_df.loc[units_df['probe'] == probe, 'spike_times'].values
    zebra_df = stream.zebra_df()

    durations = (np.asarray(durations, dtype=float) if durations is not None
                 else WAVEN_DURATIONS)

    # filt_shape[-0:] is the whole shape, not an empty tuple, so family_axes=0
    # would silently make every filter its own family.
    if family_axes < 1:
        raise ValueError(f'family_axes must be at least 1, got {family_axes}')

    # pooled (default): one block holding all Zebra repeats; per trial: one block
    # per repeat - the same blocks compute_waven_pipeline_ecephys.py runs on
    for block in wp.zebra_blocks(zebra_df, per_trial):
        trial_part = block.trial_part
        frame_onset_times = block.frame_onset_times
        frame_index = block.frame_index
        i_trial, trialnumber = block.attributes['trial'], block.attributes['nwb_trialnumber']
        frame_period = float(np.median(np.diff(frame_onset_times)))

        sweep_delays = (np.asarray(delays, dtype=float) if delays is not None
                        else default_delays(delay_stride))

        # Units are screened once per block on the whole block rather than per
        # sweep point, so the kept set is the same for every delay and duration.
        window_end = frame_onset_times[-1] + float(np.max(durations))
        n_spikes = np.array([
            np.searchsorted(s, window_end) - np.searchsorted(s, frame_onset_times[0])
            for s in all_spiketimes])
        keep = n_spikes >= min_spikes
        unit_names = all_unit_names[keep]
        spiketimes = all_spiketimes[keep]
        print(f'\ntrial {i_trial} (TrialNumber {trialnumber}): '
              f'{len(frame_onset_times)} frames, {frame_period * 1000:.2f} ms/frame, '
              f'{keep.sum()} of {len(keep)} units with >= {min_spikes} spikes')
        if keep.sum() == 0:
            print('  no units pass the spike-count screen — skipping trial')
            continue

        for phase in phases:
            decomp_path = decomp_dir / f'dwt_videodata_{phase}.npy'
            # lib_<id> as a directory level and in the filename mirrors the raw
            # results layout that full_pipeline writes, so both trees walk alike.
            out_path = (results_dir.joinpath(SIGNAL, probe, *trial_part, f'phase_{phase}')
                        / f'lib_{lib_id}' / f'null__lib_{lib_id}.h5')

            # Checked against the decomposition's header before anything is built:
            # normalising is a ~50 GB pass, and a wrong-movie run would otherwise
            # burn all of it before noticing.
            dec_shape = np.load(decomp_path, mmap_mode='r').shape
            n_frames = int(dec_shape[0])
            counts = np.bincount(frame_index, minlength=n_frames)
            # a frame may be missing from some repeats (the Allen tables sometimes
            # lack the last frame), but each must occur at least once
            if len(counts) != n_frames or counts.min() == 0:
                raise ValueError(
                    f'{int((counts[:n_frames] == 0).sum())} of the {n_frames} frames of '
                    f'{movie_path.name} never occur in the frame onsets, or they point '
                    'past its end; the onsets must come from this movie.')

            # A file holding some of the sweep points is extended by the missing
            # ones rather than redone (see load_partial). It is not unlinked here:
            # save_null replaces it atomically, so a run that dies keeps it.
            grid = [(float(d), float(u)) for d in sweep_delays for u in durations]
            prev, todo = None, grid
            if out_path.exists() and not recompute:
                prev, why = load_partial(
                    out_path, grid, n_surrogates, unit_names,
                    int(np.prod(dec_shape[1:][-family_axes:])),
                    expect={'library_id': lib_id, 'movie': movie_path.name,
                            'nwb_trialnumber': trialnumber, 'n_frames': n_frames,
                            'filter_shape': dec_shape[1:], 'family_axes': family_axes,
                            'min_lag_sec': min_lag_sec, 'min_spikes': min_spikes})
                if prev is None:
                    print(f'  phase {phase}: existing file at {out_path} cannot be '
                          f'built on ({why}) — recomputing')
                else:
                    have = {_grid_key(*g) for g in prev['grid']}
                    todo = [g for g in grid if _grid_key(*g) not in have]
                    if not todo:
                        print(f'  phase {phase}: results exist at {out_path} — skipping')
                        continue
                    print(f'  phase {phase}: {out_path} holds {len(have)} of the '
                          f'{len(grid)} sweep points — scanning the other {len(todo)} '
                          'with its rolls')

            znorm_path, n_frames, filt_shape = build_znorm_stim(
                decomp_path, znorm_root, lib_id, movie_path.stem,
                frame_block=build_frame_block)

            # Families are the trailing `family_axes` of the filter grid. Filters
            # differing only in position share a null scale because the stimulus
            # is spatially homogeneous; sigma and frequency do not, because they
            # set the temporal autocorrelation and so the effective sample size.
            n_families = int(np.prod(filt_shape[-family_axes:]))
            n_filters = int(np.prod(filt_shape))

            lags = (prev['lags'] if prev is not None else
                    build_lags(n_frames, n_surrogates,
                               int(np.ceil(min_lag_sec / frame_period))))
            print(f'  phase {phase}: {n_filters} filters, {n_families} families, '
                  f'{len(todo)} of {len(sweep_delays)}x{len(durations)} sweep points, '
                  f'{len(lags) - 1} surrogates')
            flops = 2 * n_filters * n_frames * len(spiketimes) * len(lags) * len(todo)
            print(f'  ~{flops / 1e15:.1f} PFLOP '
                  f'(~{flops / 1e14 / 60:.0f} min at 100 TFLOP/s)')

            responses = response_matrices(frame_onset_times, frame_index, spiketimes,
                                          todo, n_frames, device)
            maxbuf = null_max_scan(znorm_path, responses, lags, n_families,
                                   device, feat_block, lag_batch,
                                   expect_shape=(n_filters, n_frames))
            del responses
            if device.type == 'cuda':
                torch.cuda.empty_cache()
            if prev is not None:
                # same rolls, so the maximum over all sweep points is the larger of
                # the maximum over the old ones and over the new ones
                np.maximum(maxbuf, prev['maxbuf'], out=maxbuf)
                grid = prev['grid'] + todo

            save_null(
                out_path, unit_names, n_spikes[keep], lags, lags * frame_period,
                maxbuf, grid, filt_shape, family_axes,
                attributes={
                    'session': session_name,
                    'modality': 'ecephys',
                    'signal': SIGNAL,
                    'group': probe,
                    'probe': probe,
                    'library_id': lib_id,
                    'phase': phase,
                    'movie': movie_path.name,
                    'nwb_trialnumber': trialnumber,
                    'trial': i_trial,
                    'pooled_repeats': block.attributes['pooled_repeats'],
                    'n_repeats': block.attributes['n_repeats'],
                    'n_frames': n_frames,
                    'frame_period': frame_period,
                    'n_surrogates': len(lags) - 1,
                    'min_lag_sec': min_lag_sec,
                    'min_spikes': min_spikes,
                    'n_sweep_points_reused': len(grid) - len(todo),
                    'date_computed': datetime.today().strftime('%Y-%m-%d'),
                })


def _parse_floats(s):
    return None if s is None else np.array([float(v) for v in s.split(',')])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Null distribution of the sweep-wide max |correlation| per unit.')
    parser.add_argument('--nwb-path', required=True)
    parser.add_argument('--results-dir', required=True)
    parser.add_argument('--probe-idx', required=True, type=int)
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
                        help='Roll offsets besides lag 0 (default 300 - one per second '
                             'of the Zebra block). The per-unit test needs far fewer, '
                             'but the p floor is 1/(1+N), and BH across units cannot '
                             'reject until roughly n/(q*(1+N)) of them sit at that '
                             'floor; at N=100 that left a clearly responsive probe '
                             'with zero rejections.')
    parser.add_argument('--min-lag-sec', type=float, default=1.0,
                        help='Exclusion zone at BOTH ends of the roll range: no '
                             'surrogate lands within this many seconds of 0 or of the '
                             'full block length. This is not the spacing between '
                             'surrogates - that follows from --n-surrogates, which '
                             'spreads its rolls evenly over what is left.')
    parser.add_argument('--delay-stride', type=int, default=1,
                        help='Take every Nth delay of the waven pipeline grid '
                             '(default 1 -> all 13: 0, 0.01 ... 0.12; 2 -> 7). An '
                             'existing file on a coarser stride is extended by the '
                             'missing delays, not recomputed.')
    parser.add_argument('--delays', default=None,
                        help='Explicit delays in seconds, comma separated; '
                             'overrides --delay-stride.')
    parser.add_argument('--durations', default=None,
                        help='Explicit durations in seconds, comma separated.')
    parser.add_argument('--family-axes', type=int, default=2,
                        help='How many trailing filter axes define a family '
                             '(2 = sigma x frequency).')
    parser.add_argument('--feat-block', type=int, default=16384,
                        help='Filters per block in the scan. Reads the cached file, '
                             'which is filter-major and so contiguous; this is a GPU '
                             'memory knob, not an I/O one.')
    parser.add_argument('--build-frame-block', type=int, default=BUILD_FRAME_BLOCK,
                        help='Frames per chunk when building the normalised cache. '
                             'A memory knob only - the build reads sequentially '
                             'either way. The build needs n_filters * n_frames * 2 B '
                             'of RAM for the transposed output (~50 GB here) plus '
                             'frame_block * n_filters * 4 B per chunk.')
    parser.add_argument('--lag-batch', type=int, default=8)
    parser.add_argument('--znorm-dir', default=None,
                        help='Where to cache the normalised stimulus; defaults to '
                             'the decomposition directory.')
    parser.add_argument('--min-spikes', type=int, default=MIN_SPIKES)
    parser.add_argument('--per-trial', action='store_true',
                        help='One null per Zebra repeat instead of pooling them. Must '
                             'match the waven run being thresholded.')
    parser.add_argument('--recompute', action='store_true',
                        help='Scan every sweep point again, even those an existing '
                             'file already holds.')
    parser.add_argument('--lib-id', default=None,
                        help='Use this existing library/decomposition instead of the '
                             'one the current waven_settings hashes to. Required when '
                             'settings have changed since the results being validated '
                             'against were computed.')
    parser.add_argument('--allow-build', action='store_true',
                        help='Build the filter library and wavelet decomposition if '
                             'absent (~100 GB per phase, hours). Off by default so a '
                             'settings mismatch fails fast instead of starting one.')
    parser.add_argument('--build-cache-only', action='store_true',
                        help='Build the normalised stimulus cache for --phases and '
                             'exit. Needs no GPU, no DANDI access and no session: the '
                             'cache is keyed on (movie, library, phase) alone. Run '
                             'this once on a CPU node so the per-probe array jobs all '
                             'find it warm and can run together.')
    parser.add_argument('--decomp-dir', default=None,
                        help='Directory holding dwt_videodata_{phase}.npy, bypassing '
                             'path derivation. Needed for decompositions written '
                             'before the movie stem entered the layout.')
    args = parser.parse_args()

    # An empty --dandiset-id would otherwise reach DandiSession('') and fail deep
    # in the DANDI client; the shell wrapper can produce one from DANDISET="".
    if not args.local and not args.dandiset_id:
        parser.error('--dandiset-id is empty; pass a dandiset or use --local')

    main(nwb_path=args.nwb_path, results_dir=args.results_dir,
         probe_idx=args.probe_idx,
         dandiset_id=None if args.local else args.dandiset_id,
         phases=tuple(args.phases.split(',')), n_surrogates=args.n_surrogates,
         min_lag_sec=args.min_lag_sec, delay_stride=args.delay_stride,
         delays=_parse_floats(args.delays), durations=_parse_floats(args.durations),
         family_axes=args.family_axes, feat_block=args.feat_block,
         build_frame_block=args.build_frame_block,
         lag_batch=args.lag_batch, znorm_dir=args.znorm_dir,
         min_spikes=args.min_spikes, recompute=args.recompute,
         lib_id=args.lib_id, allow_build=args.allow_build,
         decomp_dir=args.decomp_dir, build_cache_only=args.build_cache_only,
         per_trial=args.per_trial)
