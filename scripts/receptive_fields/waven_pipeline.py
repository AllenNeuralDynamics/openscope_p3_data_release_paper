# Author: Marcel C. Raabe
# Date: 2026-10-29
"""Core of the waven RF mapping of the Zebra noise movie, shared by all modalities.

Builds (or reuses) the Gabor filter library, the downsampled movie and its
wavelet decomposition, resamples the neural activity onto the movie frames and
correlates the two (`full_pipeline`). The compute_waven_pipeline_*.py drivers and
the null-distribution scripts build on the functions here.

Every response window in this module is half-open, [start, stop).
"""

import hashlib
import json
import os
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import (
    Any,
    Literal,
    NamedTuple,
    NoReturn,
)

import h5py
import numpy as np
import pandas as pd
import waven_settings as settings
from tqdm import tqdm
from Waven import Analysis_Utils as au
from Waven import WaveletGenerator as wg

# Fewest imaged movie frames a SLAP2 (delay, duration) cell must retain before
# the correlation is worth running at all. A Zebra repeat is 9000 frames, of
# which ~97 % are imaged, so this floor only catches a broken session.
MIN_COVERED_FRAMES = 300

# Fraction of a SLAP2 response window that must be imaged for its movie frame to
# be kept.
MIN_COVERAGE = 0.95

# SLAP2 pauses ~0.59 s between imaging bouts. That pause lies between two valid
# samples, so without this cap it would count as imaged. Normal steps are
# ~5 ms; an interval longer than GAP_FACTOR x the median step is a pause and
# does not count. Same rule as NWBStream.slap2_segments() and the deconvolution.
GAP_FACTOR = 5


def create_gabor_library(xs: Sequence[int], 
                         ys: Sequence[int], 
                         thetas: Sequence[float], 
                         sigmas: Sequence[float], 
                         offsets: Sequence[float], 
                         frequencies: Sequence[float],
                         library_dir: str = settings.library_path,
                         registry_name: str = "filter_registry.json",
                         overwrite: bool = False
                        ) -> Path:
    """Creates a Gabor filter library, or reuses an existing one.

    The filter parameters are serialized to JSON and hashed (SHA-1, first 10
    hex characters). The hash is the library id and is part of the file name
    (``gabor_filter_library_{hash}.npy``). Libraries and their parameters are
    tracked in a JSON registry inside ``library_dir``. If the registry already
    holds an entry with identical parameters and its file exists, that file is
    returned without recomputing.

    Args:
        xs: Filter center positions along x, in stimulus pixels.
        ys: Filter center positions along y, in stimulus pixels.
        thetas: Filter orientations.
        sigmas: Gaussian envelope widths, in pixels.
        offsets: Filter phase offsets, in degrees. Converted to radians
            before the library is built.
        frequencies: Spatial frequencies, in cycles per pixel.
        library_dir: Directory in which the library and the registry are
            stored. Created if missing.
        registry_name: File name of the JSON registry inside ``library_dir``.
        overwrite: If True, recompute and overwrite the library file even if
            a matching one exists.

    Returns:
        Path to the ``.npy`` library file. For an existing library this is
        the path stored in the registry, resolved against the registry
        directory if relative.
    """
    lib_dir = Path(library_dir)
    lib_dir.mkdir(parents=True, exist_ok=True)
    registry_path = lib_dir / registry_name

    props = {
        "xs": list(map(int, xs)),  # Ensure all elements are Python int
        "ys": list(map(int, ys)),  # Ensure all elements are Python int
        "thetas": list(map(float, thetas)),
        "sigmas": list(map(float, sigmas)),
        "offsets": list(map(float, offsets)),
        "frequencies": list(map(float, frequencies)),
    }

    serialized = json.dumps(props, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha1(serialized.encode("utf-8")).hexdigest()[:10]
    filename = f"gabor_filter_library_{digest}.npy"
    file_path = lib_dir / filename

    # load or init registry (list of entries)
    if registry_path.exists():
        with open(registry_path, encoding="utf-8") as f:
            try:
                registry = json.load(f)
            except Exception:
                registry = []
    else:
        registry = []

    # search for exact serialized match
    for entry in registry:
        if entry.get("serialized") == serialized:
            entry_path = Path(entry.get("filename"))
            # if stored path is relative to other dir, resolve relative to registry location
            if not entry_path.is_absolute():
                entry_path = (registry_path.parent / entry_path).resolve()
            if entry_path.exists() and not overwrite:
                print(f"Library already exists at {entry_path}")
                return entry_path
            # else: file missing or overwrite requested -> break and recreate below
            break

    # offsets are given in degrees (see waven_settings) but Waven needs radians;
    # converting here keeps the degree values, and so the library id, unchanged
    lib = wg.makeFilterLibrary2(xs, ys, thetas, sigmas, np.deg2rad(offsets), frequencies)
    if not isinstance(lib, np.ndarray):
        lib = np.asarray(lib)

    # save compressed
    np.save(file_path, lib)

    # add/update registry entry
    new_entry = {
        "serialized": serialized,
        "filename": str(file_path.name),  # store relative filename for portability
        "hash": digest,
        "props": props,
    }
    # remove previous entries with same serialized if present
    registry = [e for e in registry if e.get("serialized") != serialized]
    registry.append(new_entry)

    with open(registry_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)

    return file_path


def get_downsampled_video_path(movie_path: str | Path = settings.movpath) -> Path:
    """Returns the path of the downsampled stimulus file for a movie.

    The file lives next to the movie and is named
    ``{movie_stem}_downsampled__{ny}_{nx}.npy``, with ``ny`` and ``nx`` taken
    from ``waven_settings``. This function only builds the path; it does not
    check whether the file exists.

    Args:
        movie_path: Path to the stimulus video (.mp4). Defaults to the
            ``movpath`` from ``waven_settings``.

    Returns:
        Path to the downsampled ``.npy`` file.
    """
    movie_path = Path(movie_path)
    return movie_path.parent / f'{movie_path.stem}_downsampled__{settings.ny}_{settings.nx}.npy'


def downsample_video(movie_path: str | Path = settings.movpath, 
                     chunk_size: int = 500
                     ) -> NoReturn:
    """Downsamples the stimulus video to the analysis grid, unless already done.

    The video is cropped to ``analysis_coverage`` (given the full screen extent
    in ``visual_coverage``) and resized to ``(ny, nx)`` by
    ``wg.downsample_video_binary``, which saves the result as a boolean array
    at the path given by ``get_downsampled_video_path``. If that file already
    exists, nothing is done.

    Args:
        movie_path: Path to the stimulus video (.mp4). Defaults to the
            ``movpath`` from ``waven_settings``.
    """
    movie_path = Path(movie_path)
    downsampled_path = get_downsampled_video_path(movie_path)
    if not os.path.exists(downsampled_path):
        wg.downsample_video_binary(os.path.abspath(movie_path),
                                np.array(settings.visual_coverage),
                                np.array(settings.analysis_coverage),
                                shape=(settings.ny, settings.nx),
                                chunk_size=chunk_size,
                                ratios=(settings.ratio_x, settings.ratio_y)
                                )


def get_path_wavelet_decomposition(library_path: str | Path = settings.library_path,
                                   movpath: str | Path = settings.movpath
                                   )->Path:
    """Returns the folder of the wavelet decomposition, computing it if missing.

    The folder is ``{movie_dir}/wavelet_decompositions/{movie_stem}/lib-{lib_id}``,
    so a decomposition is specific to both the stimulus movie and the filter
    library. ``lib_id`` is parsed from the library file name
    (``gabor_filter_library_{lib_id}.npy``). The folder is created if needed.

    For each phase (0 and 1), ``dwt_videodata_{phase}.npy`` is computed with
    ``wg.waveletDecomposition`` unless it already exists. If the downsampled
    movie is missing it is created first via ``downsample_video``.

    Args:
        library_path: Path to the Gabor library ``.npy`` file, as returned by
            ``create_gabor_library``. Defaults to ``library_path`` from
            ``waven_settings``.
        movpath: Path to the stimulus video (.mp4). Defaults to ``movpath``
            from ``waven_settings``.

    Returns:
        Path to the folder containing ``dwt_videodata_0.npy`` and
        ``dwt_videodata_1.npy``.
    """
    lib_name = os.path.basename(library_path)
    lib_id = lib_name.split('_')[-1].split('.')[0]

    movpath = Path(movpath)
    print(movpath)
    # The movie stem has to be part of the path: several stimulus movies live in
    # the same folder (the zebra scale variants), and a decomposition is specific
    # to the movie *and* the filter library. Keyed on lib_id alone, the second
    # movie would silently reuse the first one's dwt_videodata_*.npy via the
    # skip-if-exists branch below and every variant would yield identical RFs.
    path_decompositions = movpath.parent / 'wavelet_decompositions' / movpath.stem / f'lib-{lib_id}'
    Path(path_decompositions).mkdir(exist_ok=True, parents=True)

    for phase in [0, 1]:
        filename = f'dwt_videodata_{phase}.npy'
        file_path = os.path.join(path_decompositions, filename)

        if os.path.exists(file_path):
            print(f"Wavelet decomposition for lib {lib_id} and phase {phase} already exists "
                  f"at {file_path}. Skipping decomposition.")
        else:
            video_path = get_downsampled_video_path(movpath)
            if not os.path.exists(video_path):
                print(f"Downsampled video not found at {video_path}. Running downsampling...")
                downsample_video(movpath)
            videodata=np.load(video_path)

            wg.waveletDecomposition(videodata=videodata, phase=phase, sigmas=settings.sigmas,
                                    folder_path=path_decompositions,
                                    library_path=library_path)

    return path_decompositions


def compute_neuron_rate_to_zebra_frames(frame_onset_times: np.ndarray,
                                        spike_times_list: Sequence[np.ndarray],
                                        delay: float = 0.0,
                                        duration: float = 1/30
                                        ) -> np.ndarray:
    """Computes the firing rate of each unit in a window after each frame onset.

    The window is half-open, ``[onset + delay, onset + delay + duration)``, the
    convention of every window in this module. The continuous-signal
    counterpart is ``average_signal_over_window``.

    Args:
        frame_onset_times: Frame onset times in seconds, shape (n_frames,).
        spike_times_list: One sorted array of spike times in seconds per unit, len (n_units).
        delay: Offset of the window start from the frame onset, in seconds.
        duration: Window length in seconds.

    Returns:
        Firing rates in Hz, shape (n_units, n_frames).
    """
    starts = frame_onset_times + delay     
    stops  = starts + duration
    num_units = len(spike_times_list)
    out = np.zeros((num_units, len(frame_onset_times)), dtype=np.float64)

    for u in range(num_units):
        spk = spike_times_list[u]
        out[u] = (np.searchsorted(spk, stops) - np.searchsorted(spk, starts)) / duration
    return out


def pool_repeats(responses: np.ndarray,
                 frame_index: np.ndarray,
                 n_frames: int
                 ) -> tuple[np.ndarray, np.ndarray]:
    """Averages the responses over repeats of the movie, one value per frame.

    When every movie frame occurs equally often (once per repeat), the Pearson
    correlation of a stimulus with the responses of all repeats stacked equals
    its correlation with this average times ``scale``:

        r_stacked = r_average * std(average) / std(all responses)

    ``scale`` is one positive number per unit, so the best filter and the shape
    of the map are those of the stacked repeats, while only one copy of the
    stimulus is needed. With a single repeat in movie order, the average is the
    response itself and ``scale`` is 1.

    A frame missing from some repeats is averaged over the repeats it occurs
    in. The Allen frame tables sometimes lack the last frame of a repeat (8999
    instead of 9000 rows); the result then differs from exact stacking only by
    the weight of that one frame.

    Args:
        responses: One response per frame onset, shape (n_units, n_onsets).
        frame_index: Movie frame of each onset, shape (n_onsets,).
        n_frames: Number of frames in the movie.

    Returns:
        mean_response: Average over repeats, shape (n_units, n_frames).
        scale: Factor turning a correlation with ``mean_response`` into the
            correlation on the stacked repeats, shape (n_units,). 0 for units
            whose response never changes.

    Raises:
        ValueError: If a movie frame occurs in no repeat at all, or frame_index
            points past the end of the movie.
    """
    frame_index = np.asarray(frame_index, dtype=int)
    counts = np.bincount(frame_index, minlength=n_frames)
    if len(counts) != n_frames or counts.min() == 0:
        raise ValueError(
            f'frame_index covers frames 0-{frame_index.max()}, and '
            f'{int((counts[:n_frames] == 0).sum())} of the {n_frames} movie frames '
            'never occur; every frame must occur in at least one repeat. The onsets '
            'must be generated from this movie.')

    # sort the onsets by frame, sum the repeats of each frame and divide by their number
    order = np.argsort(frame_index, kind='stable')
    first_of_frame = np.concatenate([[0], np.cumsum(counts)[:-1]])
    sums = np.add.reduceat(responses[:, order], first_of_frame, axis=1)
    mean_response = np.ascontiguousarray(sums / counts)

    std_all = responses.std(axis=1)
    scale = np.divide(mean_response.std(axis=1), std_all,
                      out=np.zeros(len(responses)), where=std_all > 0)
    return mean_response, scale


class ZebraBlock(NamedTuple):
    """The onsets of one ``full_pipeline`` call: one Zebra repeat or all of them.

    Attributes:
        trial_part: ``['trial_<i>']`` for a single repeat, ``['pooled_trials']`` when
            pooled; the folder level and file-name part of its results.
        frame_onset_times: Frame onset times in seconds, shape (n_onsets,).
        frame_index: Movie frame of each onset, shape (n_onsets,).
        attributes: ``pooled_repeats``, ``n_repeats``, ``trial`` and
            ``nwb_trialnumber`` (both ``'pooled_trials'`` when pooled), for the
            result files.
    """
    trial_part: list
    frame_onset_times: np.ndarray
    frame_index: np.ndarray
    attributes: dict


def zebra_blocks(zebra_frames: pd.DataFrame, per_trial: bool = False) -> list:
    """Splits the Zebra frame table into the blocks ``full_pipeline`` is run on.

    This is where pooled versus per trial is decided. ``full_pipeline`` pools
    whatever repeats it is given, so pooling (the default) is one block holding
    all repeats, and per trial is one block per repeat.

    Args:
        zebra_frames: One row per movie frame shown, with ``start_time``,
            ``TrialNumber`` and the frame of the movie: ``frame`` (counted from
            0, SLAP2's ``NWBStream.zebra_frame_times()``) or ``TrialInSequence``
            (counted from 1, the ecephys and mesoscope ``zebra_df()``).
        per_trial: One block per repeat instead of one pooled block.

    Returns:
        A list of ``ZebraBlock``, in the order the repeats were shown.
    """
    zebra_frames = zebra_frames.sort_values('start_time', kind='stable')
    if 'frame' in zebra_frames:
        frames = zebra_frames['frame'].to_numpy(dtype=int)
    else:
        frames = pd.to_numeric(zebra_frames['TrialInSequence']).to_numpy().astype(int) - 1
    onsets = zebra_frames['start_time'].to_numpy(dtype=float)
    trial_numbers = zebra_frames['TrialNumber'].to_numpy()
    repeats = pd.unique(trial_numbers)

    if not per_trial:
        return [ZebraBlock(['pooled_trials'], onsets, frames,
                           {'pooled_repeats': True, 'n_repeats': len(repeats),
                            'trial': 'pooled_trials', 'nwb_trialnumber': 'pooled_trials'})]
    blocks = []
    for i_trial, trial_number in enumerate(repeats):
        rows = trial_numbers == trial_number
        blocks.append(ZebraBlock([f'trial_{i_trial}'], onsets[rows], frames[rows],
                                 {'pooled_repeats': False, 'n_repeats': 1,
                                  'trial': i_trial, 'nwb_trialnumber': str(trial_number)}))
    return blocks


def average_signal_over_window(times: np.ndarray,
                               signal: np.ndarray,
                               window_onset_times: np.ndarray,
                               duration: float
                               ) -> np.ndarray:
    """Averages a continuously sampled signal over a window at each onset time.

    This is the continuous-signal counterpart of the spike-rate window in
    ``compute_neuron_rate_to_zebra_frames``. For an onset ``t`` the window spans
    ``t`` to ``t + duration``; a negative ``duration`` makes it extend backwards
    from ``t``. The mean (rather than a sum over ``duration``) keeps the sign of
    the response independent of the sign of the window, which matters because
    Pearson correlation is sign-sensitive.

    Windows are half-open, ``[min(t, t + duration), max(t, t + duration))``, the
    convention of every window in this module (see also
    ``compute_neuron_rate_to_zebra_frames`` and ``imaged_window_means``). Every
    window averages at least one sample, so the output has no NaNs from empty
    windows:

    * A window that contains no sample (``duration`` 0, a window between two
      samples, or one entirely before the first or after the last sample) takes
      the value of the first sample at or after its lower edge, or the last
      sample if there is none. With ``duration`` 0 that is the sample at ``t``.
    * A window that only partly overlaps the recording averages the samples
      that exist.

    Because the means are computed from a cumulative sum along time, a single NaN
    would turn every window ending after it into NaN. ``signal`` must therefore
    be NaN-free; this is asserted.

    Args:
        times: Acquisition times of ``signal`` in seconds, sorted ascending,
            shape (n_times,).
        signal: Continuous signal, e.g. dF/F, shape (n_units, n_times). Must not
            contain NaNs.
        window_onset_times: Window onset times in seconds, shape (n_windows,).
        duration: Window length in seconds. The sign sets the direction.

    Returns:
        Window means, shape (n_units, n_windows).

    Raises:
        AssertionError: If ``signal`` contains NaNs.
    """
    assert not np.isnan(signal).any(), "signal must not contain NaNs"

    lo = np.minimum(window_onset_times, window_onset_times + duration)  # duration can be negative
    hi = np.maximum(window_onset_times, window_onset_times + duration)

    # [i_lo, i_hi) is the slice of samples with lo <= time < hi
    i_lo = np.searchsorted(times, lo, side='left')    # first sample with time >= lo
    i_hi = np.searchsorted(times, hi, side='left')    # first sample with time >= hi
    # An empty window has i_hi == i_lo. Widen it to one sample, the one at i_lo
    # (the first sample at or after the window start), so the mean is defined.
    i_hi = np.maximum(i_hi, i_lo + 1)
    # Windows starting after the last sample have i_lo == n_times; clamp both
    # indices so they select the last sample.
    i_lo = np.minimum(i_lo, signal.shape[1] - 1)
    i_hi = np.minimum(i_hi, signal.shape[1])

    # csum[:, k] is the sum of the first k samples (csum[:, 0] == 0), so the sum
    # over samples [i_lo, i_hi) is csum[:, i_hi] - csum[:, i_lo]. This turns
    # every window mean into two column gathers instead of a loop over windows.
    csum = np.zeros((signal.shape[0], signal.shape[1] + 1), dtype=np.float64)
    np.cumsum(signal, axis=1, dtype=np.float64, out=csum[:, 1:])

    counts = (i_hi - i_lo).astype(np.float64)
    return (csum[:, i_hi] - csum[:, i_lo]) / counts


def imaged_time(times: np.ndarray,
                valid: np.ndarray,
                starts: np.ndarray,
                stops: np.ndarray
                ) -> np.ndarray:
    """Time that was actually imaged inside each window [start, stop).
    Relevant for SLAP2; also used by the two-photon Gabor maps (rf_gabors).

    The imaged time is the sum of the intervals between consecutive samples
    that are both valid (non-NaN). An interval only counts with the part that
    lies inside the window, and an interval longer than GAP_FACTOR x the median
    step is a pause between imaging bouts and does not count at all.

    Args:
        times: Sample times in seconds, sorted ascending, shape (n_times,).
        valid: True where the sample holds data, shape (n_times,).
        starts: Window starts in seconds, shape (n_windows,).
        stops: Window stops in seconds, shape (n_windows,).

    Returns:
        Imaged time in seconds per window, shape (n_windows,).
    """
    step = np.diff(times)
    counts = valid[:-1] & valid[1:] & (step <= GAP_FACTOR * np.median(step))
    # imaged time from the first sample up to each sample; np.interp places the
    # window edges inside their intervals, which clips the intervals to the window
    imaged_before = np.concatenate([[0.0], np.cumsum(np.where(counts, step, 0.0))])
    return np.interp(stops, times, imaged_before) - np.interp(starts, times, imaged_before)


def imaged_window_means(times: np.ndarray,
                        signal: np.ndarray,
                        starts: np.ndarray,
                        stops: np.ndarray,
                        min_coverage: float = MIN_COVERAGE
                        ) -> tuple[np.ndarray, np.ndarray]:
    """Mean of each trace over each window [start, stop), if the window was imaged.

    A window counts as imaged if at least ``min_coverage`` of its time was
    imaged (see ``imaged_time``) and it holds at least one valid sample. NaN
    samples inside an imaged window are left out of its mean.

    Args:
        times: Sample times in seconds, sorted ascending, shape (n_times,).
        signal: Traces, e.g. dF/F or events, shape (n_units, n_times). May
            contain NaN; a sample counts as valid only if no unit is NaN.
        starts: Window starts in seconds, shape (n_windows,).
        stops: Window stops in seconds, shape (n_windows,).
        min_coverage: Fraction of the window's time that must be imaged.

    Returns:
        mean_responses: Mean per window, NaN where the window was not imaged,
            shape (n_units, n_windows).
        covered: True for the imaged windows, shape (n_windows,).
    """
    valid = np.isfinite(signal).all(axis=0)

    # number of valid samples and their sum in [start, stop), from cumulative sums
    i_lo = np.searchsorted(times, starts, side='left')
    i_hi = np.searchsorted(times, stops, side='left')
    n_valid = np.concatenate([[0], np.cumsum(valid)])
    n_window = n_valid[i_hi] - n_valid[i_lo]
    csum = np.zeros((signal.shape[0], signal.shape[1] + 1))
    np.cumsum(np.where(valid, signal, 0.0), axis=1, out=csum[:, 1:])

    covered = (
        (imaged_time(times, valid, starts, stops) >= min_coverage * (stops - starts))
        & (n_window > 0)
    )

    mean_responses = np.full((signal.shape[0], len(starts)), np.nan)
    mean_responses[:, covered] = ((csum[:, i_hi[covered]] - csum[:, i_lo[covered]])
                                  / n_window[covered])
    return mean_responses, covered


def compute_slap2_response_to_zebra_frames(times: np.ndarray,
                                           signal: np.ndarray,
                                           frame_onset_times: np.ndarray,
                                           delay: float = 0.0,
                                           duration: float = 1/30,
                                           min_coverage: float = MIN_COVERAGE
                                           ) -> tuple[np.ndarray, np.ndarray]:
    """Mean response per movie frame, keeping only frames that were imaged.

    The counterpart of ``compute_neuron_rate_to_zebra_frames`` for SLAP2. SLAP2
    samples at ~200 Hz against a 30 Hz movie, so there are several samples per
    frame and the response of a frame is the mean over its window
    ``[onset + delay, onset + delay + duration)``.

    Imaging is not continuous: it pauses between bouts and some stretches are
    NaN. A frame is kept only if at least ``min_coverage`` of its window was
    imaged (see ``imaged_window_means``); the other frames are dropped from
    stimulus and response alike rather than filled in. NaN samples within a kept
    window are left out of its mean.

    Args:
        times: Sample times in seconds, sorted ascending, shape (n_times,).
        signal: Traces, e.g. dF/F or events, shape (n_units, n_times). May
            contain NaN; a sample counts as imaged only if no unit is NaN.
        frame_onset_times: Movie frame onsets in seconds, shape (n_frames,).
        delay: Offset of the window start from the frame onset, in seconds.
        duration: Window length in seconds. The sign sets the direction.
        min_coverage: Fraction of the window's time that must be imaged.

    Returns:
        mean_responses: Mean response per kept frame, shape (n_units, n_kept).
        covered: True for the kept frames, shape (n_frames,), to select the
            matching stimulus rows.
    """
    starts = np.asarray(frame_onset_times, dtype=float) + delay
    lo = np.minimum(starts, starts + duration) # relevant, because duration can be negative
    hi = np.maximum(starts, starts + duration)

    mean_responses, covered = imaged_window_means(times, signal, lo, hi, min_coverage)
    return mean_responses[:, covered], covered


def save_results(rfs: Sequence[np.ndarray],
                 unit_ids: Iterable[int | str],
                 results_path: str | Path = './',
                 results_filename: str = '',
                 attributes: dict[str, Any] | None = None
                 ) -> Path:
    """Saves the receptive-field results of one run to an HDF5 file.

    The file contains:
    * root attributes: all entries of ``attributes``
    * ``unit_ids``: shape (n_units,)
    * ``correlation_matrix``: ``rfs[0]`` as float16, shape
      (n_units, nx, ny, n_thetas, n_sigmas, n_frequencies)
    * ``best_gabor_params_idx``: ``rfs[1]``, best [x, y, theta, sigma, frequency]
      indices, shape (5, n_units)
    * ``best_gabor_params_degree``: ``rfs[2]``, best parameters in visual degrees,
      shape (4, n_units)
    * ``abs_max_value``: ``rfs[3]``, peak correlation per unit, shape (n_units,)

    Args:
        rfs: Four arrays in the order (correlation matrix, best Gabor parameter
            indices, best Gabor parameters in degrees, absolute maximum
            values), as returned by the waven analysis.
        unit_ids: Unit identifiers, one per unit, in the same order as
            the first axis of ``rfs[0]``.
        results_path: Directory to save into. Created, including parents, if
            missing.
        results_filename: File name inside ``results_path``. ``.h5`` is
            appended if missing.
        attributes: Metadata stored as HDF5 root attributes, e.g. delay,
            duration, sigmas, thetas and frequencies. Values must be types
            h5py can store as attributes.

    Returns:
        Path to the saved ``.h5`` file.

    Raises:
        Exception: Any error while writing is printed and re-raised after the
            temporary file is removed.
    """
    if attributes is None:
        attributes = {}
    import tempfile

    results_path = Path(results_path)
    results_path.mkdir(parents=True, exist_ok=True)

    if not results_filename.endswith('.h5'):
        results_filename += '.h5'

    outpath = results_path / results_filename
    print(f"Saving results to {outpath}...")

    # Write to a temp file first; rename atomically on success so that any
    # interruption (OOM kill, wall-time exceeded) never leaves a corrupt file.
    tmp_fd, tmp_name = tempfile.mkstemp(suffix='.h5', dir=results_path)
    os.close(tmp_fd)
    tmp_path = Path(tmp_name)

    try:
        with h5py.File(tmp_path, 'w') as hf:
            for k, v in attributes.items():
                hf.attrs[k] = v

            hf.create_dataset('unit_ids', data=list(unit_ids))
            hf.create_dataset('correlation_matrix', data=rfs[0].astype(np.float16),
                              compression='gzip', compression_opts=4, dtype=np.float16)
            hf.create_dataset('best_gabor_params_idx', data=rfs[1])
            hf.create_dataset('best_gabor_params_degree', data=rfs[2])
            hf.create_dataset('abs_max_value', data=rfs[3])

        if outpath.exists():
            outpath.unlink()
        tmp_path.rename(outpath)
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        print(f"Error saving results: {e}")
        raise

    return outpath


def subsample_wavelet_responses(wavelets_complex: np.ndarray,
                                xis: Sequence[int],
                                yis: Sequence[int]) -> np.ndarray:
    """Selects a sub-grid of filter positions from a wavelet decomposition.

    The output keeps every position ``(x, y)`` with ``x`` in ``xis`` and ``y`` in
    ``yis``. The new axes 1 and 2 follow the order of ``xis`` and ``yis``.

    Args:
        wavelets_complex: Decomposition with shape (n_frames, nx, ny, n_thetas,
            n_sigmas, n_frequencies).
        xis: Indices along axis 1 (x) to keep. Converted with ``int``.
        yis: Indices along axis 2 (y) to keep. Converted with ``int``.

    Returns:
        Array of shape (n_frames, len(xis), len(yis), n_thetas, n_sigmas,
        n_frequencies).
    """

    wavelets_complex_subsampled = np.zeros((wavelets_complex.shape[0], len(xis), len(yis),
                                            wavelets_complex.shape[3],
                                            wavelets_complex.shape[4],
                                            wavelets_complex.shape[5]))
    for i, x_i in enumerate(tqdm(xis)):
        for j, y_i in enumerate(yis):
            wavelets_complex_subsampled[:, i, j, :, :, :] = wavelets_complex[:, int(x_i), int(y_i)]
    
    return wavelets_complex_subsampled


def load_phase_dependent_wavelet_decompositions(path_decompositions: str | Path,
                                                phase: int | str,
                                                xis: Sequence[int] = (),
                                                yis: Sequence[int] = ()) -> np.ndarray:
    """Loads the wavelet decomposition of one filter phase.

    Reads ``dwt_videodata_{phase}.npy`` from ``path_decompositions`` fully into
    memory. The file is not created here; it comes from
    ``get_path_wavelet_decomposition``. If both ``xis`` and ``yis`` are
    non-empty, the result is reduced with ``subsample_wavelet_responses``.

    Args:
        path_decompositions: Folder containing the decomposition files, as
            returned by ``get_path_wavelet_decomposition``.
        phase: Filter phase, ``0`` or ``1``. Only used in the file name.
        xis: Indices along the x axis to keep. If empty, nothing is subsampled.
        yis: Indices along the y axis to keep. If empty, nothing is subsampled.

    Returns:
        Decomposition with shape (n_frames, nx, ny, n_thetas, n_sigmas,
        n_frequencies), or (n_frames, len(xis), len(yis), n_thetas, n_sigmas,
        n_frequencies) if subsampled.

    Raises:
        FileNotFoundError: If ``dwt_videodata_{phase}.npy`` does not exist.
    """

    file_path = os.path.join(path_decompositions, f'dwt_videodata_{phase}.npy')

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Wavelet decomposition files not found at {file_path}. "
                                "Please run wavelet_decomposition() first.")
    
    wavelet = np.load(file_path)

    if len(xis) > 0 and len(yis) > 0:
        wavelet = subsample_wavelet_responses(wavelet, xis, yis)

    return wavelet


def load_complex_wavelet_decomposition(path_decompositions: str | Path,
                                       xis: Sequence[int] = (),
                                       yis: Sequence[int] = ()) -> np.ndarray:
    """Loads the phase-invariant wavelet energy, computing it on first use.

    The "complex" response is the sum of the squared phase-0 and phase-1
    responses, ``a0**2 + a1**2``, which does not depend on the filter phase. It
    is a real float32 array, not complex-valued. It is cached as
    ``dwt_videodata_c.npy`` in ``path_decompositions``.

    If the cache is missing, it is computed from ``dwt_videodata_0.npy`` and
    ``dwt_videodata_1.npy`` in chunks of 512 frames via memory maps, so the full
    arrays are never held in memory at once. An existing cache is reused as is
    and is not checked against the two phase files. After that the cache is
    loaded fully into memory and, if both ``xis`` and ``yis`` are non-empty,
    reduced with ``subsample_wavelet_responses``.

    Args:
        path_decompositions: Folder containing the phase decompositions, as
            returned by ``get_path_wavelet_decomposition``.
        xis: Indices along the x axis to keep. If empty, nothing is subsampled.
        yis: Indices along the y axis to keep. If empty, nothing is subsampled.

    Returns:
        Wavelet energy with shape (n_frames, nx, ny, n_thetas, n_sigmas,
        n_frequencies), or (n_frames, len(xis), len(yis), n_thetas, n_sigmas,
        n_frequencies) if subsampled. The subsampled array is float64.
    """

    path_complex = os.path.join(path_decompositions, 'dwt_videodata_c.npy')
    if not os.path.exists(path_complex):
        # Compute wavelet_c in chunks and avoid loading full arrays into RAM.
        path_0 = os.path.join(path_decompositions, 'dwt_videodata_0.npy')
        path_1 = os.path.join(path_decompositions, 'dwt_videodata_1.npy')

        # open memmaps to read shapes (these do not load the whole file)
        wavelet_0_mm = np.load(path_0, mmap_mode='r')
        wavelet_1_mm = np.load(path_1, mmap_mode='r')

        n_frames = wavelet_0_mm.shape[0]
        frame_shape = wavelet_0_mm.shape[1:]  # (Nx, Ny, Ntheta, Nsigma, Nfreq, Noffset) or similar
        dtype = np.float32

        # prepare an on-disk memmap for the computed magnitude (wavelet_c)
        wavelet_c_mm = np.lib.format.open_memmap(path_complex, mode='w+', dtype=dtype,
                                                 shape=(n_frames, *frame_shape))

        chunk_frames = 512  # adjust if you want larger/smaller chunks

        for start in tqdm(range(0, n_frames, chunk_frames), desc="Computing wavelet_c chunks"):
            end = min(start + chunk_frames, n_frames)
            # read just the slice from the memmaps (this loads only the chunk into RAM)
            a0 = wavelet_0_mm[start:end].astype(dtype)
            a1 = wavelet_1_mm[start:end].astype(dtype)

            # magnitude / power: a0**2 + a1**2
            c_chunk = a0 * a0 + a1 * a1

            # write chunk directly to the output memmap
            wavelet_c_mm[start:end] = c_chunk

            # free local refs for this iteration
            del a0, a1, c_chunk

        # close/delete temporary memmap references to free resources
        del wavelet_0_mm, wavelet_1_mm, wavelet_c_mm

    print(f"Loading precomputed wavelet_c from {path_complex}")
    wavelet_c = np.load(path_complex)

    if len(xis) > 0 and len(yis) > 0:
        wavelet_c = subsample_wavelet_responses(wavelet_c, xis, yis)

    return wavelet_c


def full_pipeline(frame_onset_times: np.ndarray,
                  activity: Sequence[np.ndarray] | pd.DataFrame,
                  delays: float | Sequence[float] | np.ndarray,
                  durations: float | Sequence[float] | np.ndarray,
                  unit_ids: Iterable[int | str],
                  xis: Sequence[int] = (),
                  yis: Sequence[int] = (),
                  results_path: str | Path = './',
                  results_filename: str = '',
                  attributes: dict[str, Any] | None = None,
                  recompute: bool = False,
                  phase: Literal['complex', '0', '1'] = 'complex',
                  input_type: Literal['ecephys', 'mesoscope', 'slap2'] = 'ecephys',
                  movie_path: str | Path | None = None,
                  frame_index: Sequence[int] | np.ndarray | None = None,
                  min_coverage: float = MIN_COVERAGE
                  ) -> Path:
    """Maps receptive fields by correlating neural responses with Gabor wavelet energy.

    Runs the full waven analysis for one recording. The setup steps are
    cached on disk and shared across calls: load or create the Gabor library,
    downsample the stimulus movie, and wavelet-decompose it (see
    ``create_gabor_library``, ``downsample_video`` and
    ``get_path_wavelet_decomposition``). The decomposition is then loaded and
    optionally subsampled in space. For every combination of ``delays`` and
    ``durations``, the neural responses are resampled onto the movie frames
    and correlated with the decomposition by ``au.PearsonCorrelationPinkNoise``.
    The result of each (delay, duration) combination is saved with
    ``save_results`` to its own HDF5 file.

    Pooled or per trial: ``full_pipeline`` pools whatever repeats of the movie
    it is given. To get one result set per repeat, call it once per repeat;
    ``zebra_blocks`` builds the onsets for either case and is what the
    compute_waven_pipeline*.py drivers use (pooled by default, ``--per-trial``).

    The three ``input_type`` values differ in how responses are matched to
    movie frames:

    * ``'ecephys'``: ``activity`` holds sorted spike times per unit.
      The response is the firing rate in the window after each onset (see
      ``compute_neuron_rate_to_zebra_frames``). Repeats of the movie are
      averaged per frame and the correlation is rescaled, which gives exactly
      the correlation on the stacked repeats (see ``pool_repeats``).
    * ``'mesoscope'``: ``activity`` is a DataFrame of dF/F with ROIs
      in rows and sample times in columns. The ~10 Hz samples are slower than
      the movie, so each sample is attributed to the last frame whose onset lies
      before ``sample time - delay``. Samples that do not fall on a frame (before
      the first onset, after the last frame, or in a pause between repeats) are
      dropped from stimulus and response alike. The response is the dF/F
      averaged over ``duration`` from the sample (see
      ``average_signal_over_window``). Repeats are stacked.
    * ``'slap2'``: ``activity`` is a DataFrame of dF/F with ROIs in rows
      and sample times in columns. SLAP2 samples faster than the movie, so there is
      one response per movie frame
      (``compute_slap2_response_to_zebra_frames``). Frames that are not
      sufficiently imaged are dropped from stimulus and response alike, and
      repeats are stacked. A
      (delay, duration) combination with fewer than ``MIN_COVERED_FRAMES``
      frames left is skipped without writing a file.

    Results are written to ``{results_path}/lib_{lib_id}/``, with the file name
    ``{stem}__lib_{lib_id}__delay_{delay:.4f}__dur_{duration:.4f}.h5``, where ``stem`` is
    ``results_filename`` without its extension. If ``results_filename`` is empty,
    the file name starts at ``lib_{lib_id}``. An existing file for a combination
    is skipped unless ``recompute`` is True. A file that cannot be opened, e.g.
    left behind by a killed run, is deleted and recomputed.

    The following attributes are added to the HDF5 attributes: library_id,
    delay, duration, sigmas, thetas, frequencies, phase, num_units, num_frames
    and movie. For ``'slap2'`` also: n_frames_covered, n_frames_total,
    frac_frames_covered and min_coverage.

    Args:
        frame_onset_times: Onset time of each stimulus frame in seconds, sorted
            ascending, shape (n_onsets,). Either one repeat of the movie or
            several repeats pooled, matched to movie frames through
            ``frame_index``.
        activity: Neural activity of each unit. For ``'ecephys'``, one
            sorted array of spike times in seconds per unit. For
            ``'mesoscope'`` and ``'slap2'``, a DataFrame with ROIs in rows and
            sample times in seconds as columns (dF/F or events).
        delays: Delay(s) between frame onset and start of the response window,
            in seconds. A scalar is treated as a single value.
        durations: Length(s) of the response window in seconds. A scalar is
            treated as a single value. Every delay is combined with every
            duration.
        unit_ids: Unit identifiers, one per unit, saved as ``unit_ids``.
        xis: Indices along the x axis of the decomposition to keep. If either
            ``xis`` or ``yis`` is empty, all positions are used. See
            ``subsample_wavelet_responses``.
        yis: Indices along the y axis to keep.
        results_path: Base directory for the results. The ``lib_{lib_id}``
            subdirectory is created inside it.
        results_filename: Prefix for the result file names; an extension is
            ignored.
        attributes: Metadata stored as HDF5 attributes in every result file.
            Updated in place with the attributes listed above, so it is
            modified for the caller.
        recompute: If True, recompute and overwrite existing result files.
        phase: Which decomposition to use. ``'complex'`` is the phase-invariant
            energy; ``'0'`` and ``'1'`` are the individual filter phases. See
            ``load_complex_wavelet_decomposition``.
        input_type: How ``activity`` is interpreted, see above.
        movie_path: Stimulus movie to correlate against. Defaults to the
            ``movpath`` from ``waven_settings``; pass it explicitly when a
            session shows more than one movie (e.g. the zebra scale variants),
            so that each gets its own downsampling and wavelet decomposition.
        frame_index: Movie frame (row of the decomposition) of each entry of
            ``frame_onset_times``, shape (n_onsets,). Needed when the onsets
            pool several repeats, because the same frame recurs on every
            repeat. None means one repeat in movie order (0, 1, 2, ...).
        min_coverage: Fraction of a response window's time that must be imaged
            for the corresponding movie frame to be kept (``'slap2'`` only).

    Returns:
        The directory containing the result files, ``{results_path}/lib_{lib_id}``.

    Raises:
        AssertionError: If ``phase`` is not ``'complex'``, ``'0'`` or ``'1'``.
        ValueError: If ``input_type`` is unknown, or if ``frame_index`` has a
            different length than ``frame_onset_times`` or points past the end
            of the decomposition. For ``'ecephys'``, if a movie frame occurs
            in no repeat (see ``pool_repeats``).
    """

    if attributes is None:
        attributes = {}
    # ensure delays and durations are numpy 1D arrays of floats (support scalar input)
    delays = np.atleast_1d(np.asarray(delays, dtype=float))
    durations = np.atleast_1d(np.asarray(durations, dtype=float))

    movie_path = Path(movie_path) if movie_path is not None else Path(settings.movpath)

    # create_gabor_library()
    print('Creating/Loading Gabor Filter Library...')
    library_path = create_gabor_library(settings.xs, settings.ys, settings.thetas,
                                        settings.sigmas, settings.offsets,
                                        settings.frequencies)
    lib_id = os.path.basename(library_path).split('_')[-1].split('.')[0]

    print('Downsampling Video...')
    downsample_video(movie_path)

    print('Wavelet Decomposition...')
    path_decompositions =  get_path_wavelet_decomposition(library_path=library_path,
                                                          movpath=movie_path)

    print('Loading and Subsampling Wavelet Decompositions...')
    assert phase in ['complex', '0', '1'], "phase parameter must be 'complex', '0', or '1'"
    if phase in ['0', '1']:
        wavelet_decomposition = load_phase_dependent_wavelet_decompositions(
            path_decompositions, phase, xis, yis)
    else:
        wavelet_decomposition = load_complex_wavelet_decomposition(path_decompositions, xis, yis)

    # Checking the frame index and reading the traces does not depend on delay
    # or duration, so it is done once rather than per grid cell. A frame index
    # past the end of the decomposition means the onsets were built for another
    # movie - silent garbage rather than an error further down.
    frame_onset_times = np.asarray(frame_onset_times, dtype=float)
    if frame_index is None:
        frame_index = np.arange(len(frame_onset_times))
    frame_index = np.asarray(frame_index, dtype=int)
    if len(frame_index) != len(frame_onset_times):
        raise ValueError(
            f'{len(frame_index)} frame indices but {len(frame_onset_times)} '
            'frame onset times; they must describe the same rows.'
        )
    if frame_index.max() >= wavelet_decomposition.shape[0]:
        raise ValueError(
            f'frame_index reaches {frame_index.max()} but the decomposition of '
            f'{movie_path.name} has only {wavelet_decomposition.shape[0]} frames. '
            'The onsets must be generated from this movie.'
        )

    if input_type == 'mesoscope':
        frame_period = float(np.median(np.diff(frame_onset_times)))

    if input_type == 'slap2':
        # NaN samples stay in: compute_slap2_response_to_zebra_frames counts
        # them as not imaged and leaves them out of the means
        slap2_times = np.asarray(activity.columns.to_numpy(), dtype=float)
        slap2_dff = activity.to_numpy(dtype=np.float64)
        n_blanked = (~np.isfinite(slap2_dff).all(axis=0)).sum()
        print(f'{slap2_dff.shape[0]} ROIs, {slap2_dff.shape[1]} samples '
              f'({n_blanked} blanked), {len(frame_onset_times)} movie frames')

    lib_dir = Path(results_path) / f'lib_{lib_id}'

    for delay in delays:
        for duration in durations:

            # Skip a grid cell whose result file exists, unless recompute is True.
            # Delay and duration go into the name with four decimals, so float noise
            # (0.15000000000000002) does not end up in the file name.
            stem = Path(results_filename).stem if results_filename else ''
            name = f'lib_{lib_id}__delay_{delay:.4f}__dur_{duration:.4f}.h5'
            filename = f'{stem}__{name}' if stem else name
            filepath = lib_dir / filename

            # Runs killed by the wall time or memory limit can leave a corrupt file
            # behind, so an existing file is only skipped if it can be opened.
            if filepath.exists() and not recompute:
                try:
                    with h5py.File(filepath, 'r'):
                        pass
                    print(f"Results for lib {lib_id}, delay {delay}, duration {duration} "
                          f"already exist at {filepath}. Skipping computation.")
                    continue
                except OSError:
                    print(f"WARNING: corrupt results file at {filepath} — recomputing.")    
                    filepath.unlink()

            print(f'Computing responses to the Zebra frames for delay {delay:.4f}, '
                  f'duration {duration:.4f} and phase {phase}...')
            if input_type == 'ecephys':
                stim = wavelet_decomposition
                rates = compute_neuron_rate_to_zebra_frames(frame_onset_times, activity,
                                                            delay, duration)
                # one value per movie frame, averaged over repeats; `scale` is
                # applied to the correlations below (see pool_repeats)
                responses, scale = pool_repeats(
                    rates, frame_index, wavelet_decomposition.shape[0])
            elif input_type == 'mesoscope':
                # mesoscope data is a DataFrame with time in columns and ROIs in rows
                times = activity.columns.to_numpy()
                dff = activity.to_numpy()  # (n_rois, n_times)
                # The mesoscope samples at ~10 Hz, slower than the 30 Hz movie, so
                # each sample takes the frame shown `delay` seconds before it and the
                # frames in between are not used.
                t_lookup = times - delay
                # index of the last onset strictly before t_lookup
                idxs = np.searchsorted(frame_onset_times, t_lookup, side='left') - 1
                # keep a sample only if that frame was still on screen: after the
                # first onset and less than 1.5 frames after the matched onset, which
                # drops samples after the last frame and in pauses between repeats
                keep = (idxs >= 0) & (
                    t_lookup - frame_onset_times[np.maximum(idxs, 0)] < 1.5 * frame_period)
                # stimulus and response must be restricted to the *same* samples,
                # otherwise the two matrices have different numbers of timepoints
                stim = wavelet_decomposition[frame_index[idxs[keep]]]
                # average dF/F over `duration` from each retained sample; windows
                # shorter than the ~0.1 s mesoscope interval reduce to that sample
                responses = average_signal_over_window(times, dff, times[keep], duration)
            elif input_type == 'slap2':
                # SLAP2 samples ~6x faster than the movie, so the resampling runs
                # the other way round from the mesoscope: one response per movie
                # frame, with the frames that fall in a blanking gap dropped from
                # stimulus and response alike.
                responses, covered = compute_slap2_response_to_zebra_frames(
                    slap2_times, slap2_dff, frame_onset_times, delay, duration,
                    min_coverage=min_coverage)
                # The decomposition is ~100 GB at the current settings and the
                # fancy index below copies most of it. Drop the previous cell's
                # copy first, or the assignment holds two at once and the peak
                # doubles for no reason.
                stim = None
                rows = frame_index[covered]
                # a fully covered session indexes every frame in order, where the
                # copy buys nothing over a view of the decomposition itself
                if len(rows) == wavelet_decomposition.shape[0] and np.array_equal(
                        rows, np.arange(wavelet_decomposition.shape[0])):
                    stim = wavelet_decomposition
                else:
                    stim = wavelet_decomposition[rows]
                print(f'{covered.sum()} of {len(covered)} movie frames imaged '
                      f'({100 * covered.mean():.0f} %)')
                if covered.sum() < MIN_COVERED_FRAMES:
                    print(f'WARNING: only {covered.sum()} covered frames for delay {delay}, '
                          f'duration {duration} — skipping, the correlation would be noise.')
                    continue
            else:
                raise ValueError(
                    f'unknown input_type {input_type!r}; expected one of '
                    "'ecephys', 'mesoscope', 'slap2'"
                )


            print('Running Correlation Analysis...')
            rfs = au.PearsonCorrelationPinkNoise(stim=stim,
                                                    resp=responses.T,
                                                    # dummy value for neuron_pos
                                                    neuron_pos=np.zeros((1,2)),
                                                    nx=stim.shape[1],
                                                    ny=stim.shape[2],
                                                    ns=settings.ns,
                                                    n_frequencies=len(settings.frequencies),
                                                    # actual number of phases from the
                                                    # loaded decomposition
                                                    n_phases=stim.shape[-1],
                                                    visual_coverage=settings.analysis_coverage, 
                                                    screen_ratio=settings.screen_ratio, 
                                                    sigmas=settings.sigmas_deg,
                                                    plotting=False,
                                                    n_thetas=settings.n_thetas
                                                    )
            if input_type == 'ecephys':
                # correlation with the average -> correlation on the stacked repeats;
                # PearsonCorrelationPinkNoise returns a tuple, which cannot be assigned to
                rfs = list(rfs)
                rfs[0] *= scale.reshape(-1, *[1] * (rfs[0].ndim - 1))
                rfs[3] *= scale
            
            # Add additional attributes
            add_to_attributes = {
                "library_id": lib_id,
                "delay": delay,
                "duration": duration,
                "sigmas": list(settings.sigmas),
                "thetas": list(settings.thetas),
                "frequencies": list(settings.frequencies),
                "phase": phase,
                "num_units": len(activity),
                "num_frames": stim.shape[0],
                "movie": movie_path.name,
            }
            if input_type == 'slap2':
                # without these, a weak map cannot be told apart from one
                # estimated off a handful of frames that happened to be imaged
                add_to_attributes.update({
                    "n_frames_covered": int(covered.sum()),
                    "n_frames_total": int(covered.size),
                    "frac_frames_covered": float(covered.mean()),
                    "min_coverage": float(min_coverage),
                })
            attributes.update(add_to_attributes)

            print('Saving Results...')
            save_results(rfs,
                                    unit_ids,
                                    results_path=lib_dir,
                                    results_filename=filename,
                                    attributes=attributes
                                    )
    return lib_dir
    