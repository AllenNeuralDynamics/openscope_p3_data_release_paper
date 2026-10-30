# Author: Marcel C. Raabe
# Contributors: Lucas Rudelt
# Date: 2026-10-29
"""
Gaussian-envelope fits to Gabor-patch receptive fields, and the conversion
needed to compare their width against the Zebra (waven) pipeline's Gabor sigma.

Why this module exists
----------------------
The two pipelines report receptive-field *size* in incompatible ways:

* **Gabor patches** report no size at all — only a 9 x 9 map of z-scored
  responses on a 10-degree grid. A width has to be *fitted*.
* **Zebra (waven)** reports the sigma of whichever filter in the Gabor library
  correlated best. That is a real Gaussian sigma, but it is stored in a
  doubled convention (see `waven_sigma_deg` below).

`fit_gaussian_envelope` supplies the first, `waven_sigma_deg` fixes the second,
so that both sides end up as a plain Gaussian standard deviation in visual
degrees.

Resolution limit
----------------
The patch grid steps in 10 degrees and spans only +-40 degrees. A sigma much
below ~5 degrees is not resolvable — the fit is then interpolating between
grid points rather than measuring anything — and a unit whose centre lands on
the edge of the grid has a half-truncated map. Both are reported as flags, but
only the first disqualifies a fit; see `FitResult.usable`.
"""

import numpy as np
from scipy.optimize import curve_fit

# The stimulus table of the RF-mapping block records DiameterX = DiameterY =
# 20 deg for every patch. PsychoPy's 'gauss' mask puts the envelope sigma at
# size / (2 * sd) with its default sd = 3, i.e. 20 / 6. That mask parameter is
# NOT recorded in the NWB, so this is the documented PsychoPy default and not a
# value read from the data — which is why deconvolution is opt-in.
PATCH_DIAMETER_DEG = 20.0
PATCH_SIGMA_DEG = PATCH_DIAMETER_DEG / 6.0


def waven_sigma_deg(sigma_deg):
    """Convert waven's stored `sigma_deg` into a plain Gaussian sigma in degrees.

    waven builds its filters with `skimage.filters.gabor_kernel(sigma_x=sigma,
    sigma_y=sigma)`, where sigma is a true Gaussian standard deviation in
    pixels. But the value written to the result files as `sigma_deg` is

        sigma_deg = 2 * deg_per_pix * sigma_pix

    (see `sigmas_deg` in waven's `example.py` / `zebraGUI.py`) — twice the
    degree-converted sigma. Halving it recovers the standard deviation, which
    is what a fitted Gaussian envelope returns.
    """
    return np.asarray(sigma_deg, dtype=float) / 2.0


def gaussian2d(xy, amp, x0, y0, sigma_x, sigma_y, theta, offset):
    """Rotated 2D Gaussian, evaluated on the flattened coordinates `xy`.

    `amp` is deliberately unbounded in sign: an OFF-dominated unit has a
    negative peak in the z-score map and must fit as a negative Gaussian, not
    as a positive one somewhere else.
    """
    x, y = xy
    ct, st = np.cos(theta), np.sin(theta)
    xr = (x - x0) * ct + (y - y0) * st
    yr = -(x - x0) * st + (y - y0) * ct
    return offset + amp * np.exp(-0.5 * ((xr / sigma_x) ** 2 + (yr / sigma_y) ** 2))


def gaussian2d_iso(xy, amp, x0, y0, sigma, offset):
    """Isotropic 2D Gaussian — the robust fallback on a coarse grid.

    With 81 samples on a 9 x 9 grid, the elliptical model's `sigma_x`,
    `sigma_y` and `theta` are only weakly constrained, and an elongation of
    one grid step can swing them a long way. The isotropic fit has four fewer
    degrees of freedom and is the one to trust when the two disagree.
    """
    x, y = xy
    r2 = (x - x0) ** 2 + (y - y0) ** 2
    return offset + amp * np.exp(-0.5 * r2 / sigma ** 2)


class FitResult(dict):
    """A fit, as a dict, with the quality question answered in one place."""

    @property
    def usable(self):
        """True when the fitted sigma is something the grid could actually measure.

        Three ways a fit is not usable, all of which occur in this data:
          - it did not converge at all;
          - the model explains little of the map (`r2` below `min_r2`);
          - sigma sits on a bound, meaning the optimiser ran out of room rather
            than finding a minimum.

        `edge` — the fitted centre landing outside the sampled window — is
        deliberately *not* one of them. Those maps are truncated and their width
        is extrapolated from a partial peak, which biases sigma upward, but the
        flag is kept on every row so the effect can be measured rather than
        assumed. On this data it is small: most edge units fail `railed` or
        `min_r2` anyway, so keeping the rest moves the median sigma by ~0.1
        degrees. Filter on `~df['edge']` to get the interior-only subset back.
        """
        return bool(self['success'] and not self['railed']
                    and self['r2'] >= self['min_r2']
                    and self['sigma'] >= self['sigma_resolution'])


def fit_gaussian_envelope(z_map, x_pos, y_pos, min_r2=0.5, isotropic=False,
                          sigma_bounds=None, nonnegative=False):
    """Fit a Gaussian envelope to one RF map.

    Parameters
    ----------
    z_map : (nx, ny) array
        Map indexed `[x_i, y_i]`, matching `x_positions` and `y_positions`.
        Non-finite pixels are left out of the fit. A signed z-score map is
        fit as-is, so an OFF peak is a negative amplitude. Pass
        ``np.abs(z_map)`` with ``nonnegative=True`` to fit an envelope.
    x_pos, y_pos : 1D arrays
        Pixel centres in visual degrees.
    min_r2 : float
        Variance-explained floor below which the fit is not `usable`.
    isotropic : bool
        Fit the 4-parameter circular model instead of the elliptical one.
    sigma_bounds : (lo, hi) or None
        Defaults to half the grid step up to the full grid span.
    nonnegative : bool
        Keep the amplitude at or above zero. Used for an absolute-value map.

    Returns
    -------
    FitResult with keys: sigma, sigma_x, sigma_y, aspect, x0, y0, theta, amp,
    offset, r2, peak_z, success, edge, railed, sigma_resolution, min_r2.
    `sigma` is the equivalent circular sigma, sqrt(sigma_x * sigma_y), which
    preserves the area of the elliptical fit.
    """
    z = np.asarray(z_map, dtype=float)
    x_pos = np.asarray(x_pos, dtype=float)
    y_pos = np.asarray(y_pos, dtype=float)

    # 'ij' so that X[i, j] pairs with z[i, j] = z at (x_pos[i], y_pos[j]);
    # the default 'xy' indexing would silently transpose the map.
    X, Y = np.meshgrid(x_pos, y_pos, indexing='ij')
    finite = np.isfinite(z)
    n_params = 5 if isotropic else 7
    step = float(np.median(np.diff(np.sort(x_pos))))
    span = float(max(x_pos.max() - x_pos.min(), y_pos.max() - y_pos.min()))
    lo, hi = sigma_bounds if sigma_bounds is not None else (step / 2, span)

    # A sigma below half the grid step cannot be distinguished from a single
    # hot grid point, so it is reported but marked unusable.
    out = FitResult(sigma=np.nan, sigma_x=np.nan, sigma_y=np.nan, aspect=np.nan,
                    x0=np.nan, y0=np.nan, theta=np.nan, amp=np.nan, offset=np.nan,
                    r2=np.nan, peak_z=np.nan, success=False, edge=False,
                    railed=False, sigma_resolution=step / 2, min_r2=min_r2)

    if int(finite.sum()) < n_params:
        return out
    xy = (X[finite], Y[finite])
    zf = z[finite]
    if np.allclose(zf, zf[0]):
        return out

    # Seed from the map itself: the extreme pixel relative to the background.
    offset0 = float(np.median(zf))
    k = int(np.argmax(np.abs(zf - offset0)))
    amp0 = float(zf[k] - offset0)
    if nonnegative:
        amp0 = abs(amp0)
    x00, y00 = float(xy[0][k]), float(xy[1][k])
    out['peak_z'] = float(zf[k])

    # Centres are allowed one grid step outside the window so that a unit
    # sitting on the border can still converge; `edge` then flags it.
    xlo, xhi = x_pos.min() - step, x_pos.max() + step
    ylo, yhi = y_pos.min() - step, y_pos.max() + step
    amp_lim = 10 * max(abs(amp0), 1e-6)
    amp_lo = 0.0 if nonnegative else -amp_lim

    if isotropic:
        f = gaussian2d_iso
        p0 = [amp0, x00, y00, step, offset0]
        bounds = ([amp_lo, xlo, ylo, lo, zf.min() - 10],
                  [amp_lim, xhi, yhi, hi, zf.max() + 10])
    else:
        f = gaussian2d
        p0 = [amp0, x00, y00, step, step, 0.0, offset0]
        bounds = ([amp_lo, xlo, ylo, lo, lo, -np.pi / 2, zf.min() - 10],
                  [amp_lim, xhi, yhi, hi, hi, np.pi / 2, zf.max() + 10])

    try:
        popt, _ = curve_fit(f, xy, zf, p0=p0, bounds=bounds, maxfev=20000)
    except (RuntimeError, ValueError):
        return out

    if isotropic:
        amp, x0, y0, sigma, offset = popt
        sx = sy = sigma
        theta = 0.0
    else:
        amp, x0, y0, sx, sy, theta, offset = popt
        sigma = float(np.sqrt(sx * sy))

    resid = zf - f(xy, *popt)
    ss_tot = float(((zf - zf.mean()) ** 2).sum())
    r2 = 1.0 - float((resid ** 2).sum()) / ss_tot if ss_tot > 0 else np.nan

    tol = 1e-3 * (hi - lo)
    out.update(sigma=float(sigma), sigma_x=float(sx), sigma_y=float(sy),
               aspect=float(max(sx, sy) / min(sx, sy)),
               x0=float(x0), y0=float(y0), theta=float(theta), amp=float(amp),
               offset=float(offset), r2=float(r2), success=True,
               edge=bool(x0 < x_pos.min() or x0 > x_pos.max()
                         or y0 < y_pos.min() or y0 > y_pos.max()),
               railed=bool(sx <= lo + tol or sx >= hi - tol
                           or sy <= lo + tol or sy >= hi - tol))
    return out


def envelope_area(sigma_x, sigma_y=None, n_sigma=1.0):
    """Area of the `n_sigma` ellipse of a Gaussian envelope, in square degrees.

        A = pi * (n * sigma_x) * (n * sigma_y)

    `sigma_y=None` means circular, which is what waven reports — its filters are
    built with `sigma_x == sigma_y`, so its receptive fields have no elongation
    to preserve.

    Note that this is a monotone function of sigma, so it cannot change any rank
    correlation: `spearmanr(area_fit, area_waven)` is identical to
    `spearmanr(sigma_fit, sigma_waven)` by construction. Area changes the *size*
    statements — a 22% difference in sigma is a 49% difference in area — and
    puts them in the deg^2 unit receptive fields are usually quoted in. It is
    not independent evidence about whether the two pipelines agree per unit.
    """
    sx = np.asarray(sigma_x, dtype=float)
    sy = sx if sigma_y is None else np.asarray(sigma_y, dtype=float)
    return np.pi * (n_sigma ** 2) * sx * sy


def deconvolve_patch(sigma_fit, patch_sigma=PATCH_SIGMA_DEG):
    """Remove the stimulus patch's own width from a fitted sigma.

    A patch map is the true receptive field convolved with the patch envelope,
    so widths add in quadrature: sigma_fit^2 = sigma_rf^2 + patch_sigma^2.
    Returns NaN where the fit is narrower than the patch itself, which is not a
    physically meaningful receptive field but does happen on noisy maps.

    `patch_sigma` rests on the PsychoPy default mask parameter (see
    `PATCH_SIGMA_DEG`), not on a value recorded in the NWB — treat the result
    as a correction of known form but uncertain magnitude.
    """
    s2 = np.asarray(sigma_fit, dtype=float) ** 2 - float(patch_sigma) ** 2
    return np.sqrt(np.where(s2 > 0, s2, np.nan))


def patch_centres(extent, n):
    """Patch centres in degrees, recovered from the imshow extent.

    `load_gabor` stores an extent covering the pixel *edges*, so the centres
    are half a step inside it. Reconstructing them here avoids having to carry
    `x_positions` / `y_positions` separately through the merge.
    """
    lo, hi = float(extent[0]), float(extent[1])
    step = (hi - lo) / n
    return lo + step / 2 + step * np.arange(n)


def fit_dataframe(df, extent, map_col='rf_map_gabor', n_top=None,
                  rank_by=('p_value', 'z_max'), ascending=(True, False),
                  isotropic=False, min_r2=0.5, **kwargs):
    """Fit every unit's Gabor-patch map and return the fits joined to `df`.

    `n_top` restricts the fit to the most significant units, ranked the way the
    rest of this notebook ranks them: p-value first, peak |z| breaking the ties
    at the permutation floor. Leave it None to fit everything.

    The returned frame carries `sigma_fit` (equivalent circular sigma of the
    fitted envelope, in degrees), `sigma_waven` (waven's sigma converted to the
    same units by `waven_sigma_deg`), `sigma_rf` (patch-deconvolved), the fit
    diagnostics, and `usable` — the flag that says whether the grid could
    resolve this width at all.
    """
    import pandas as pd

    sub = df.dropna(subset=[c for c in rank_by if c in df.columns])
    sub = sub[sub[map_col].map(lambda m: isinstance(m, np.ndarray))]
    if not len(sub):
        return pd.DataFrame()
    sub = sub.sort_values(list(rank_by), ascending=list(ascending))
    if n_top is not None:
        sub = sub.head(n_top)

    nx, ny = sub[map_col].iloc[0].shape
    x = patch_centres(extent[:2], nx)
    y = patch_centres(extent[2:], ny)

    rows = []
    for idx, r in sub.iterrows():
        fit = fit_gaussian_envelope(r[map_col], x, y, min_r2=min_r2,
                                    isotropic=isotropic, **kwargs)
        rows.append({'_idx': idx, 'sigma_fit': fit['sigma'],
                     'sigma_x_fit': fit['sigma_x'], 'sigma_y_fit': fit['sigma_y'],
                     'aspect_fit': fit['aspect'], 'x0_fit': fit['x0'],
                     'y0_fit': fit['y0'], 'theta_fit': fit['theta'],
                     'amp_fit': fit['amp'], 'r2_fit': fit['r2'],
                     'usable': fit.usable, 'edge': fit['edge'],
                     'railed': fit['railed']})

    out = pd.DataFrame(rows).set_index('_idx')
    out = sub.join(out)
    out['sigma_rf'] = deconvolve_patch(out['sigma_fit'])

    # Areas of the 1-sigma ellipse. `sigma_fit` is already sqrt(sigma_x *
    # sigma_y), so pi * sigma_fit^2 *is* the ellipse area — the equivalent
    # circular sigma was defined to preserve it.
    out['area_fit'] = envelope_area(out['sigma_x_fit'], out['sigma_y_fit'])
    out['area_rf'] = envelope_area(out['sigma_rf'])
    if 'sigma_deg' in out.columns:
        out['sigma_waven'] = waven_sigma_deg(out['sigma_deg'])
        out['sigma_ratio'] = out['sigma_fit'] / out['sigma_waven']
        out['area_waven'] = envelope_area(out['sigma_waven'])
        out['area_ratio'] = out['area_fit'] / out['area_waven']
    return out
