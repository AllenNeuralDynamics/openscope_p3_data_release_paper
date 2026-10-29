# Author: Marcel C. Raabe
# Date: 2026-10-29
"""Optimize waven pipeline parameters per unit.

Scans a directory tree of waven result .h5 files and, for each unit,
identifies the (delay, duration, theta, sigma, frequency) combination
that maximises the peak Pearson correlation.

Within each .h5 file the correlation matrix has already been reduced to
  abs_max_value[unit]          — peak |correlation| across x,y,θ,σ,f
  best_gabor_params_idx[:, u]  — argmax indices [xi, yi, θi, σi, fi]
  best_gabor_params_degree[:, u] — best params in visual degrees [x, y, θ, σ]

So optimising over delay × duration amounts to picking the file with
the highest abs_max_value for each unit and reading out its stored best
gabor parameters.

Usage, from the command line or by calling optimize_parameters() directly:

    python optimize_waven_parameters.py <results_dir> [--output path/to/out.csv]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
from tqdm import tqdm

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _parse_lib_id(filepath: Path) -> str:
    """Extract library id from filename (e.g. lib_5d7b94947f__delay…)."""
    stem = filepath.stem
    for part in stem.split("__"):
        if part.startswith("lib_") or part.startswith("lib-"):
            return part.split("_", 1)[1].split("-", 1)[-1]
    return ""


def read_null_sweep(null_path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """The (delays, durations) grid a null-distribution file was built on.

    compute_null_distribution_ecephys.py maximises each surrogate over a sweep that may be
    a subset of this pipeline's own - e.g. every second delay. Its threshold
    is only valid against an observed maximum taken over that same subset, so the
    grid travels with the null file rather than being restated by hand.
    """
    with h5py.File(Path(null_path), "r") as hf:
        return (np.asarray(hf.attrs["sweep_delays"], dtype=float),
                np.asarray(hf.attrs["sweep_durations"], dtype=float))


def _in_grid(value: float, grid: np.ndarray | None) -> bool:
    """Whether `value` is in `grid`, tolerantly. No grid means no restriction."""
    return grid is None or bool(np.any(np.isclose(value, grid)))


def discover_files(results_dir: str | Path) -> list[Path]:
    """Return all .h5 files under results_dir that look like waven outputs."""
    results_dir = Path(results_dir)
    files = sorted(results_dir.rglob("*.h5"))
    valid = []
    for f in files:
        try:
            with h5py.File(f, "r") as hf:
                if (
                    "abs_max_value" in hf
                    and "unit_ids" in hf
                    and "best_gabor_params_idx" in hf
                    and "delay" in hf.attrs
                    and "sigmas" in hf.attrs
                ):
                    valid.append(f)
        except OSError:
            pass
    return valid


# ---------------------------------------------------------------------------
# core optimisation
# ---------------------------------------------------------------------------

def optimize_parameters(
    results_dir: str | Path,
    output_path: str | Path | None = None,
    all_values_path: str | Path | None = None,
    include_negative: bool = False,
    extract_tuning_curves: bool = False,
    sweep_delays: np.ndarray | None = None,
    sweep_durations: np.ndarray | None = None,
) -> pd.DataFrame:
    """Picks, per unit, the best filter over all (delay, duration) result files.

    Scans every waven result file under ``results_dir`` and keeps, for each
    unit, the file with the highest ``abs_max_value`` together with its stored
    best filter.

    Args:
        results_dir: Folder searched recursively for waven ``.h5`` files.
        output_path: CSV to write the result to. An HDF5 file with the same
            stem is written next to it. None writes nothing.
        all_values_path: CSV for every (unit, delay, duration, abs_max_value);
            defaults to ``<output_path stem>_all_values.csv``.
        include_negative: Also use files with a negative delay or duration.
        extract_tuning_curves: Add 1D tuning curves from each unit's best file.
        sweep_delays: Restrict the maximum to these delays (e.g. a null's grid).
            None uses every file found.
        sweep_durations: Same for the durations.

    Returns:
        One row per unit with the columns:

        * ``unit_id``, ``delay``, ``duration``, ``lib_id``, ``abs_max_value``
        * ``x_deg``, ``y_deg``: RF centre in visual degrees
        * ``theta_deg``: orientation in degrees, converted from ``theta_rad``
          (not read from ``best_gabor_params_degree``, which is wrong in files
          written before the Waven fix)
        * ``sigma_deg``: Gabor size in visual degrees (2 * deg/pix * sigma)
        * ``theta_rad``, ``sigma`` (pixels), ``frequency`` (cycles/pixel),
          looked up from the file attributes
        * ``xi``, ``yi``, ``theta_idx``, ``sigma_idx``, ``frequency_idx``: grid
          indices of the best filter
        * ``source_file``: the file that gave the best result

    Raises:
        FileNotFoundError: If no waven result file is found.
    """
    files = discover_files(results_dir)
    if not files:
        raise FileNotFoundError(f"No valid waven .h5 files found under {results_dir}")

    print(f"Found {len(files)} result files — scanning for per-unit optima…")

    best: dict[str, dict] = {}
    all_rows: list[dict] = []
    skipped_off_grid = 0
    used_delays: set[float] = set()
    used_durations: set[float] = set()

    for filepath in tqdm(files):
        lib_id = _parse_lib_id(filepath)
        try:
            with h5py.File(filepath, "r") as hf:
                delay = float(hf.attrs["delay"])
                duration = float(hf.attrs["duration"])
                thetas = hf.attrs["thetas"][:]
                sigmas = hf.attrs["sigmas"][:]
                frequencies = hf.attrs["frequencies"][:]

                unit_ids = hf["unit_ids"][:].astype(str)
                abs_max = hf["abs_max_value"][:].astype(float)
                best_idx = hf["best_gabor_params_idx"][:]    # (5, n_units)
                best_deg = hf["best_gabor_params_degree"][:] # (4, n_units)
        except OSError as e:
            print(f"WARNING: skipping {filepath}: {e}")
            continue

        if not include_negative and (delay < 0 or duration < 0):
            continue

        # Restricting the maximum to the null's grid. Taking it over more sweep
        # points than the surrogates saw inflates it relative to the threshold,
        # which is anti-conservative - so this has to be skipped, not merely
        # flagged.
        if not (_in_grid(delay, sweep_delays) and _in_grid(duration, sweep_durations)):
            skipped_off_grid += 1
            continue
        used_delays.add(delay)
        used_durations.add(duration)

        for i, uid in enumerate(unit_ids):
            val = abs_max[i]
            all_rows.append(
                {"unit_id": uid, "delay": delay, "duration": duration, "abs_max_value": val}
            )
            if uid not in best or val > best[uid]["abs_max_value"]:
                xi, yi, ti, si, fi = best_idx[:, i]
                best[uid] = {
                    "unit_id": uid,
                    "delay": delay,
                    "duration": duration,
                    "lib_id": lib_id,
                    "abs_max_value": val,
                    "x_deg": best_deg[0, i],
                    "y_deg": best_deg[1, i],
                    "theta_deg": float(np.degrees(thetas[ti])),
                    "sigma_deg": best_deg[3, i],
                    "xi": int(xi),
                    "yi": int(yi),
                    "theta_idx": int(ti),
                    "theta_rad": float(thetas[ti]),
                    "sigma_idx": int(si),
                    "sigma": float(sigmas[si]),
                    "frequency_idx": int(fi),
                    "frequency": float(frequencies[fi]),
                    "source_file": str(filepath),
                }

    if sweep_delays is not None or sweep_durations is not None:
        print(f"Restricted to the null's sweep: {len(used_delays)} delays x "
              f"{len(used_durations)} durations, {skipped_off_grid} files skipped")
        # A grid point with no result file means the observed maximum is over a
        # SMALLER family than the surrogates were - conservative rather than
        # wrong, but it silently costs power and usually means the two runs were
        # pointed at different sweeps.
        for name, want, got in (("delays", sweep_delays, used_delays),
                                ("durations", sweep_durations, used_durations)):
            if want is None:
                continue
            missing = [float(v) for v in want
                       if not (got and any(np.isclose(v, list(got))))]
            if missing:
                print(f"WARNING: no result files for {name} {missing}; the observed "
                      "maximum spans fewer sweep points than the null does.")

    df = pd.DataFrame(list(best.values()))
    df = df.sort_values("unit_id").reset_index(drop=True)

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False)
        print(f"Saved {len(df)} units → {output_path}")

    # resolve all_values_path: explicit > sibling of output_path > skip
    if all_values_path is None and output_path is not None:
        all_values_path = output_path.parent / (output_path.stem + "_all_values.csv")
    if all_values_path is not None:
        all_values_path = Path(all_values_path)
    df_all = (
        pd.DataFrame(all_rows)
        .sort_values(["unit_id", "delay", "duration"])
        .reset_index(drop=True)
    )
    if all_values_path is not None:
        all_values_path.parent.mkdir(parents=True, exist_ok=True)
        df_all.to_csv(all_values_path, index=False)
        print(f"Saved {len(df_all)} (unit, delay, duration) rows → {all_values_path}")

    if extract_tuning_curves:
        print("Extracting tuning curves from best delay/duration files…")
        df = _extract_tuning_curves(df)

    if output_path is not None:
        h5_path = Path(output_path).with_suffix(".h5")
        save_rf_results(df, h5_path)

    return df


# ---------------------------------------------------------------------------
# RF map loader
# ---------------------------------------------------------------------------

def load_rf_maps(
    best_params: str | Path | pd.DataFrame
) -> pd.DataFrame:
    """Attaches the 2D RF map at the best filter to each unit.

    For every unit, reads
    ``correlation_matrix[unit_row, :, :, theta_idx, sigma_idx, frequency_idx]``
    from its source file: the spatial map (nx x ny) at the orientation, size
    and frequency found by ``optimize_parameters``.

    Args:
        best_params: Output of ``optimize_parameters``, as a DataFrame or the
            path of its CSV.

    Returns:
        The input with one extra column ``rf_map``: an (nx, ny) array per unit.
    """
    if isinstance(best_params, pd.DataFrame):
        df = best_params
    else:
        df = pd.read_csv(best_params)

    rf_maps = [None] * len(df)

    # with h5py.File(f'{best_params.parent/best_params.stem}.h5', "r") as hf:
    #     rf_maps = hf['rf_maps'][:]
    #     df["rf_map"] = list(rf_maps)

    # group by source file so each file is opened exactly once
    for source_file, grp in tqdm(df.groupby("source_file"), desc="Loading RF maps"):
        try:
            with h5py.File(source_file, "r") as hf:
                # build uid → row-index map for this file
                file_unit_ids = hf["unit_ids"][:].astype(str)
                uid_to_row = {uid: row for row, uid in enumerate(file_unit_ids)}
                cm = hf["correlation_matrix"]   # (n_units, nx, ny, n_theta, n_sigma, n_freq)

                for df_row, unit in grp.iterrows():
                    row_idx = uid_to_row.get(unit["unit_id"])
                    if row_idx is None:
                        continue
                    ti = int(unit["theta_idx"])
                    si = int(unit["sigma_idx"])
                    fi = int(unit["frequency_idx"])
                    rf_maps[df_row] = cm[row_idx, :, :, ti, si, fi]   # (nx, ny) float32

        except OSError as e:
            print(f"WARNING: could not open {source_file}: {e}")

    df["rf_map"] = rf_maps
    return df


# ---------------------------------------------------------------------------
# Save / load
# ---------------------------------------------------------------------------

_SCALAR_COLS = [
    "delay", "duration", "abs_max_value",
    "x_deg", "y_deg", "theta_deg", "sigma_deg",
    "theta_rad", "sigma", "frequency",
    "xi", "yi", "theta_idx", "sigma_idx", "frequency_idx",
]
_STRING_COLS = ["lib_id", "source_file"]
_TUNING_CURVE_NAMES = [
    "tuning_azimuth",      # correlation vs x position  (nx,)
    "tuning_elevation",    # correlation vs y position  (ny,)
    "tuning_orientation",  # correlation vs theta       (n_thetas,)
    "tuning_size",         # correlation vs sigma       (ns,)
    "tuning_frequency",    # correlation vs frequency   (n_freq,)
]


def _extract_tuning_curves(df: pd.DataFrame) -> pd.DataFrame:
    """Add 1D tuning curve columns to df from each unit's best source file.

    For each unit the correlation_matrix in its best source file is sliced at
    the stored best parameter indices, varying one parameter at a time while
    holding the others fixed.  The five new columns each contain a 1D float32
    array per unit.
    """
    curves: dict[str, list] = {name: [None] * len(df) for name in _TUNING_CURVE_NAMES}

    for source_file, grp in tqdm(df.groupby("source_file"), desc="Extracting tuning curves"):
        try:
            with h5py.File(source_file, "r") as hf:
                file_unit_ids = hf["unit_ids"][:].astype(str)
                uid_to_row = {uid: r for r, uid in enumerate(file_unit_ids)}
                cm = hf["correlation_matrix"]  # lazy (n_units, nx, ny, n_thetas, ns, n_freq)

                for df_idx, unit in grp.iterrows():
                    row = uid_to_row.get(str(unit["unit_id"]))
                    if row is None:
                        continue
                    xi = int(unit["xi"])
                    yi = int(unit["yi"])
                    ti = int(unit["theta_idx"])
                    si = int(unit["sigma_idx"])
                    fi = int(unit["frequency_idx"])

                    # load one unit's slice; cast from stored float16 to float32
                    block = cm[row].astype(np.float32)  # (nx, ny, n_thetas, ns, n_freq)
                    curves["tuning_azimuth"][df_idx]     = block[:, yi, ti, si, fi]
                    curves["tuning_elevation"][df_idx]   = block[xi, :, ti, si, fi]
                    curves["tuning_orientation"][df_idx] = block[xi, yi, :, si, fi]
                    curves["tuning_size"][df_idx]        = block[xi, yi, ti, :, fi]
                    curves["tuning_frequency"][df_idx]   = block[xi, yi, ti, si, :]
        except OSError as e:
            print(f"WARNING: could not open {source_file}: {e}")

    for name, vals in curves.items():
        df[name] = vals
    return df


def save_rf_results(df: pd.DataFrame, output_path: str | Path) -> Path:
    """Saves the optimized results to one HDF5 file, atomically.

    The file holds ``/unit_ids``, one dataset per scalar or string column, and,
    when present, ``/rf_maps`` (n_units, nx, ny) and the tuning curves
    ``/tuning_azimuth`` (n_units, nx), ``/tuning_elevation`` (n_units, ny),
    ``/tuning_orientation`` (n_units, n_thetas), ``/tuning_size``
    (n_units, ns) and ``/tuning_frequency`` (n_units, n_freq), all gzip-
    compressed.

    Args:
        df: Output of ``optimize_parameters``, optionally with ``rf_map`` and
            tuning-curve columns.
        output_path: HDF5 file to write.

    Returns:
        The path written.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = output_path.with_suffix(".h5.tmp")
    try:
        with h5py.File(tmp_path, "w") as hf:
            dt = h5py.string_dtype()
            hf.create_dataset("unit_ids", data=df["unit_id"].tolist(), dtype=dt)

            if "rf_map" in df.columns and df["rf_map"].notna().any():
                maps = np.stack(df["rf_map"].values)   # (n_units, nx, ny)
                hf.create_dataset("rf_maps", data=maps, compression="gzip", compression_opts=4)

            for col in _SCALAR_COLS:
                if col in df.columns:
                    hf.create_dataset(col, data=df[col].values)

            for col in _STRING_COLS:
                if col in df.columns:
                    hf.create_dataset(col, data=df[col].tolist(), dtype=dt)

            for name in _TUNING_CURVE_NAMES:
                if name in df.columns and df[name].notna().any():
                    hf.create_dataset(
                        name,
                        data=np.stack(df[name].values),
                        compression="gzip",
                        compression_opts=4,
                    )
        tmp_path.rename(output_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    print(f"Saved {len(df)} units → {output_path}")
    return output_path


def load_rf_results(path: str | Path) -> pd.DataFrame:
    """Loads a file written by ``save_rf_results``.

    Args:
        path: The HDF5 file.

    Returns:
        One row per unit with the scalar and string columns and, when present,
        ``rf_map`` (an (nx, ny) array per unit) and the tuning curves
        ``tuning_azimuth``, ``tuning_elevation``, ``tuning_orientation``,
        ``tuning_size`` and ``tuning_frequency``.
    """
    path = Path(path)
    with h5py.File(path, "r") as hf:
        unit_ids = hf["unit_ids"][:].astype(str)

        data: dict = {"unit_id": unit_ids}
        for col in _SCALAR_COLS:
            if col in hf:
                data[col] = hf[col][:]
        for col in _STRING_COLS:
            if col in hf:
                data[col] = hf[col][:].astype(str)

        rf_maps = hf["rf_maps"][:] if "rf_maps" in hf else None

        tc_arrays = {}
        for name in _TUNING_CURVE_NAMES:
            if name in hf:
                tc_arrays[name] = hf[name][:]

    df = pd.DataFrame(data)

    if rf_maps is not None:
        df["rf_map"] = [rf_maps[i] for i in range(len(df))]

    for name, arr in tc_arrays.items():
        df[name] = [arr[i] for i in range(len(df))]

    return df


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Optimise waven RF parameters per unit across delay × duration sweeps."
    )
    parser.add_argument(
        "results_dir",
        help="Root directory containing waven .h5 result files (searched recursively).",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Base output path (e.g. best_params.csv). HDF5 saved at same stem with .h5. "
             "Defaults to <results_dir>/best_params.csv.",
    )
    parser.add_argument(
        "--include-negative",
        action="store_true",
        default=False,
        help="Include files with negative delay or duration in the optimisation. "
             "Excluded by default.",
    )
    parser.add_argument(
        "--tuning-curves",
        action="store_true",
        default=False,
        help="Extract 1D tuning curves (azimuth, elevation, orientation, size, frequency) "
             "and store them in the output HDF5. Skipped by default.",
    )
    parser.add_argument(
        "--sweep-from-null",
        default=None,
        help="Path to a null__lib_*.h5 from compute_null_distribution_ecephys.py. The "
             "per-unit maximum is then taken only over that file's (delay, duration) "
             "grid, so it spans the same test family the surrogates did. Without "
             "this the maximum covers every result file present, which against a "
             "thinned null is anti-conservative.",
    )
    args = parser.parse_args()

    sweep_delays = sweep_durations = None
    if args.sweep_from_null:
        sweep_delays, sweep_durations = read_null_sweep(args.sweep_from_null)
        print(f"Matching the null's sweep from {args.sweep_from_null}:")
        print(f"  delays    {sweep_delays}")
        print(f"  durations {sweep_durations}")

    csv_out = args.output or str(Path(args.results_dir) / "best_params.csv")
    h5_out = str(Path(csv_out).with_suffix(".h5"))

    # optimize_parameters scans files, saves CSV + HDF5 (tuning curves optional)
    df = optimize_parameters(args.results_dir, csv_out, include_negative=args.include_negative,
                             extract_tuning_curves=args.tuning_curves,
                             sweep_delays=sweep_delays, sweep_durations=sweep_durations)
    # load_rf_maps adds 2D spatial RF maps; save_rf_results writes the final HDF5
    df = load_rf_maps(df)
    save_rf_results(df, h5_out)

    print(f"\nSummary ({len(df)} units):")
    print(df[["unit_id", "delay", "duration", "abs_max_value",
              "theta_rad", "sigma", "frequency"]].describe())


if __name__ == "__main__":
    main()
