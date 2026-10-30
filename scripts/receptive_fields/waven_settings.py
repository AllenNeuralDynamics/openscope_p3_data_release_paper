# Author: Marcel C. Raabe
# Date: 2026-10-29
"""Analysis parameters for the waven RF mapping of the Zebra noise movie.

Imported by waven_pipeline.py, the compute_waven_pipeline*.py drivers, the
compute_null_distribution*.py scripts and filter_significant_maps.py.

The stimulus movie is cropped to `analysis_coverage` and downsampled to an
nx x ny pixel grid. Every Gabor filter is defined on that grid, so all sizes and
frequencies are in pixels of the downsampled movie, not of the screen.

Attributes:
    movpath (str): Path to the Zebra noise stimulus movie (.mp4), from
        `$OPENSCOPE_P3_ZEBRA_MOVIE` or the ignored `.receptive_fields_work/`
        folder of the repository. The public copy is `MOVIE_URL`.
    nb_frames (int): Number of frames in the Zebra movie (30 Hz, 5 min). Used
        by the null submission scripts to estimate the z-normalised
        stimulus cache size.
    library_path (str): Folder holding the Gabor filter libraries and their
        registry, from `$OPENSCOPE_P3_WAVEN_LIBRARIES` or
        `.receptive_fields_work/filter_libraries/`.
    visual_coverage (list[float]): Visual field covered by the screen, as
        [azimuth left, azimuth right, elevation top, elevation bottom] in
        degrees.
    analysis_coverage (list[float]): Part of the visual field that is analysed,
        in the same format as `visual_coverage`.
    ratio_x (float): Fraction of the screen width that is analysed. Used to crop
        the movie before downsampling.
    ratio_y (float): Fraction of the screen height that is analysed.
    nx (int): Width of the downsampled movie in pixels (azimuth).
    ny (int): Height of the downsampled movie in pixels (elevation).
    deg_per_pix (float): Visual degrees per pixel of the downsampled movie
        (~1.79 deg). The grid is square: 120 deg / 67 px and 95 deg / 53 px
        agree to 0.1 %.
    screen_ratio (float): Degrees per pixel computed from the full screen, as
        Waven's PearsonCorrelationPinkNoise expects it. Equals `deg_per_pix` as
        long as the whole screen is analysed.
    xs (np.ndarray): Filter centre positions along x, one per pixel.
    ys (np.ndarray): Filter centre positions along y, one per pixel.
    n_thetas (int): Number of filter orientations.
    thetas (np.ndarray): Filter orientations, `n_thetas` angles evenly spaced
        over [0, pi), in radians.
    sigmas (np.ndarray): Standard deviation of the Gaussian envelope, in pixels.
    ns (int): Number of envelope sizes.
    sigmas_deg (np.ndarray): Filter size in visual degrees (2 sigma, truncated
        to two decimals), as Waven reports it in `best_gabor_params_degree`.
    offsets (np.ndarray): Filter phases in DEGREES: 0 = even (cosine),
        90 = odd (sine). `create_gabor_library` converts them to radians.
    frequencies (list[float]): Spatial frequencies in CYCLES PER PIXEL of the
        downsampled movie (skimage.filters.gabor_kernel uses
        exp(i * 2 pi * frequency * x)). One cycle spans 1 / frequency pixels;
        divide by `deg_per_pix` for cycles per degree.

Note:
    Nyquist limit: a pixel grid cannot show a pattern finer than 2 pixels per
    cycle, so every frequency must be below 0.5 cycles/pixel (~0.28 cycles/deg
    here). A larger value folds back onto a coarser pattern (aliasing): at 0
    and 90 deg, f becomes f - 1 (1.1 -> 0.1); at every other orientation both
    the frequency and the orientation change (1.1 at 18 deg is really 0.34 at
    82 deg). At exactly 0.5 the odd (sine) filter is zero at every pixel. Near
    the limit filters degrade as well, so stay below ~0.35.

Warning:
    Changing any of xs, ys, thetas, sigmas, offsets or frequencies changes the
    library id (the SHA-1 hash computed by waven_pipeline.create_gabor_library).
    That builds a new filter library and wavelet decomposition, and the results
    land in a new lib_<id> folder. Changing nx/ny or the coverage also changes
    the downsampled movie, whose cached file is NOT keyed on these values:
    delete <movie>_downsampled__<ny>_<nx>.npy and the old decompositions first.
"""

import os
from pathlib import Path

import numpy as np

# Paths
MOVIE_URL = ('https://github.com/AllenNeuralDynamics/openscope-community-predictive-processing/'
             'raw/9f4d70abe948940c1c8f7ad76a41eb33181fc962/code/stimulus-control/src/Mindscope/movies/'
             'zebra_allen_screen_tscale_30_scale_10.mp4')
WORK_DIR = Path(__file__).resolve().parents[2] / '.receptive_fields_work'
movpath = os.environ.get('OPENSCOPE_P3_ZEBRA_MOVIE',
                         str(WORK_DIR / 'zebra_allen_screen_tscale_30_scale_10.mp4'))
nb_frames = 9000
library_path = os.environ.get('OPENSCOPE_P3_WAVEN_LIBRARIES',
                              str(WORK_DIR / 'filter_libraries')) + '/'

# Visual field
visual_coverage = [-60, 60, 47.5, -47.5]
analysis_coverage = [-60, 60, 47.5, -47.5]
ratio_x = ((analysis_coverage[1] - analysis_coverage[0])
           / (visual_coverage[1] - visual_coverage[0]))
ratio_y = ((analysis_coverage[2] - analysis_coverage[3])
           / (visual_coverage[2] - visual_coverage[3]))

# Analysis grid
nx = 67
ny = 53
deg_per_pix = abs(analysis_coverage[1] - analysis_coverage[0]) / nx
screen_ratio = abs(visual_coverage[0] - visual_coverage[1]) / nx
xs = np.arange(nx)
ys = np.arange(ny)

# Gabor filter library
n_thetas = 10
thetas = np.arange(n_thetas) * np.pi / n_thetas
sigmas = np.array([2, 3, 4, 5, 6, 8])
ns = len(sigmas)
sigmas_deg = np.trunc(2 * deg_per_pix * sigmas * 100) / 100
offsets = np.array([0, 90])
frequencies = [0.01, 0.02, 0.04, 0.06, 0.08, 0.1, 0.2,]
