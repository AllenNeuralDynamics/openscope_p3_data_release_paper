#!/usr/bin/env python3
# Author: Marcel C. Raabe
# Contributors: Lucas Rudelt
# Date: 2026-10-29
"""Receptive-field figure intermediate from the reduced Zebra and Gabor results.

Reads the reduced receptive-field results (optimized Zebra maps, Zebra null
distributions, pooled Gabor maps with their unit-level significance, and the
ecephys unit areas) and writes the compact intermediate that
``openscope_p3_publication.receptive_field_figure`` draws:

* ``figure_sources/data/receptive-fields/receptive-fields.h5``
* ``figure_sources/data/receptive-fields/receptive-fields.provenance.json``

The reduced results are produced by the pipeline in ``scripts/receptive_fields/``
(``compute_waven_pipeline_*``, ``compute_null_distribution_*``,
``compute_rf_gabors_*``, ``compute_gabor_unit_significance.py``,
``export_ephys_unit_areas.py``) and hosted outside this repository; their layout
is described in ``figure_sources/data/receptive-fields/README.md``.

Selection, significance, Gaussian fits, bootstrap intervals and permutation tests
follow ``plot_data_release_panels.py`` of the analysis repository unchanged. Only
the plotting is left to the renderer:

* Row A, example maps: one unit per selection (both significant, only Gabor, only
  Zebra) from primary visual cortex (ecephys VISp layer 2/3, mesoscope plane
  VISp_0, SLAP2 green channel).
* Row B, significance overlap: every unit of the two compared structures (ecephys
  VISp and VISl, all layers; mesoscope VISp and VISl, all planes; SLAP2 DMD1 and
  DMD2, green channel) counted by which test it passes.
* Row C, RF summary: Gaussian centre, one-sigma area and peak strength of every
  significant map whose fit converged.

Refresh with::

    uv run --with tqdm --with opencv-python-headless \\
        python scripts/extract_receptive_fields.py --results-root <reduced results>

``--movie`` defaults to ``waven_settings.movpath``; the movie is checked against
the SHA-256 of the public copy (``waven_settings.MOVIE_URL``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import date
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "receptive_fields"))

from analysis.gaussian_envelope import fit_gaussian_envelope, patch_centres  # noqa: E402
from filter_significant_maps import bh_fdr as _bh_fdr  # noqa: E402
from filter_significant_maps import gumbel_mom, load_null  # noqa: E402
from optimize_waven_parameters import load_rf_results  # noqa: E402
from waven_settings import MOVIE_URL, analysis_coverage, movpath, visual_coverage  # noqa: E402

OUTPUT_DIR = REPO_ROOT / "figure_sources" / "data" / "receptive-fields"
OUTPUT_PATH = OUTPUT_DIR / "receptive-fields.h5"
PROVENANCE_PATH = OUTPUT_DIR / "receptive-fields.provenance.json"
SCHEMA_VERSION = 1

MOVIE_SHA256 = "3ee4d88356dba7220eb67e53f7d117400932f3adf95132d6301fe212ff7cf899"
# waven version the reduced results were computed with (scripts/receptive_fields/README.md)
WAVEN = {
    "repository": "https://github.com/RaabeM/waven",
    "branch": "allen_open_scope",
}
ZEBRA_FRAME = 1000
# The stored frame is block-averaged by this factor in both axes.
ZEBRA_FRAME_DOWNSAMPLE = 4
# Example Gabor patch of the RF mapping stimulus table, drawn by the renderer.
GABOR_PATCH = {
    "x_deg": -20.0,
    "y_deg": -20.0,
    "orientation_rad": float(np.pi / 4),
    "spatial_frequency_cpd": 0.08,
    "diameter_deg": 20.0,
    "contrast": 0.8,
}

# Set by main(): the reduced results, laid out as in the analysis repository.
RESULTS = Path()
PHASE = 0
# Zebra maps and their nulls: the pooled block of both repeats.
ZEBRA_BLOCK = "pooled_trials"
GABOR_SIGNAL = "events"
# Signal of the Zebra maps and nulls per modality.
ZEBRA_SIGNAL = {"ecephys": "spikes", "mesoscope": "events", "slap2": "dff"}
# The lag-0 maximum of a null file and the map's abs_max_value must agree to
# this, or the two were not computed on the same data (float16 maps).
CHECK_TOL = 1e-3
Q_LEVEL = 0.05

xM, xm, yM, ym = analysis_coverage
WAVEN_EXTENT = (xM, xm, ym, yM)

# modality -> (session, channel kept or None, dandiset, population of row A)
SESSIONS = {
    "ecephys": (
        "sub-830794_ses-ecephys-830794-2026-01-26-12-02-05_ecephys", None, "001637",
        "VISp layer 2/3",
    ),
    "mesoscope": (
        "sub-832700_ses-multiplane-ophys-832700-2026-01-24-12-06-12_ophys", None, "001768",
        "VISp_0",
    ),
    "slap2": (
        "sub-829704_ses-829704-2025-12-18-10-57-36_image+ophys", "green", "001424",
        "V1 layer 2/3, green channel",
    ),
}
EPHYS_SESSION = SESSIONS["ecephys"][0]
# Row A uses the second-ranked ecephys example and the first of the others.
EXAMPLE_INDEX = {"ecephys": 1, "mesoscope": 0, "slap2": 0}

DMD1_LABEL = "DMD1\n(apical)"
DMD2_LABEL = "DMD2\n(basal)"
STRUCTURE_ORDER = (
    "VISp", "VISl", "V1", "LM",
    DMD1_LABEL, DMD2_LABEL, "DMD1", "DMD2", "apical", "basal",
)
# Summary figures name the same comparison on both rows.
_SUMMARY_RENAME = {"VISp": "V1", "VISl": "LM"}
# A Gabor-significant unit whose fitted centre lies beyond this many degrees in
# azimuth or elevation, or whose fit fails, is left out of the corpus.
GABOR_CENTRE_LIMIT = 40.0
N_BOOT = 2000
N_PERM = 10000

WAVEN_COLS = [
    "unit_id", "abs_max_value", "rf_map", "delay", "duration",
    "x_deg", "y_deg", "theta_rad", "theta_deg", "sigma_deg", "frequency", "lib_id",
]
GABOR_COLS = [
    "unit_id", "p_value", "p_value_gumbel", "p_value_bh", "z_max", "ori_idx", "ori_rad", "delay",
    "duration", "rf_map", "rf_maps_all", "p_all", "rate_map",
]
FIT_KEYS = ("x0", "y0", "sigma_x", "sigma_y", "theta", "r2")

# Every results file read, for the provenance.
READ_FILES: set[Path] = set()


def _read(path: Path) -> Path:
    READ_FILES.add(Path(path).resolve())
    return path


# ---------------------------------------------------------------------------
# Loading, as plot_data_release_panels.py
# ---------------------------------------------------------------------------


def _text(value) -> str:
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


def in_filter(group: str, keep: str | None) -> bool:
    return keep is None or group.split("__")[-1] == keep


def canonical_unit_id(uid) -> str:
    m = re.match(r"^.*_roi(\d+)$", str(uid))
    return m.group(1) if m else str(uid)


def _gabor_dir(modality: str, session: str) -> Path:
    """``gabors/<modality>/<session>/<signal>``: ``spikes`` for ecephys, else ``GABOR_SIGNAL``."""
    signal = "spikes" if modality == "ecephys" else GABOR_SIGNAL
    return RESULTS / "gabors" / modality / session / signal


def _zebra_dir(kind: str, session: str, signal: str) -> Path | None:
    """``zebra/<kind>/<modality>/<session>/<signal>``, or None if absent."""
    hits = sorted(
        p / signal for p in (RESULTS / "zebra" / kind).glob(f"*/{session}")
        if (p / signal).is_dir()
    )
    if len(hits) > 1:
        raise ValueError(f"{session}/{signal} is under several modality folders of {kind}: {hits}")
    return hits[0] if hits else None


def discover_waven(session: str, signal: str) -> dict[str, Path]:
    """Pooled, phase-``PHASE`` optimized Zebra files of one session and signal, by group."""
    out = {}
    d = _zebra_dir("optimized", session, signal)
    if d is None:
        return out
    prefix = f"optimized__{session}__"
    suffix = f"__{ZEBRA_BLOCK}__phase_{PHASE}"
    for f in sorted(d.glob(f"{prefix}*{suffix}.h5")):
        out[f.stem[len(prefix):-len(suffix)]] = f
    return out


def discover_gabor(modality: str, session: str) -> dict[str, Path]:
    """Pooled Gabor ``*__optimized.h5`` of one session, by group."""
    out = {}
    d = _gabor_dir(modality, session)
    if not d.is_dir():
        print(f"  no Gabor results at {d}")
        return out
    for f in sorted(d.glob(f"{session}__rf-spike-count__*__optimized.h5")):
        if "__trial_" in f.stem:
            continue
        out[f.stem.split("__")[-2]] = f

    channel_prefix = f"rf-{GABOR_SIGNAL}-"
    for f in sorted(d.glob(f"{session}__*__optimized.h5")):
        if "__trial_" in f.stem:
            continue
        parts = f.stem.split("__")
        if len(parts) < 4:
            continue
        tag, group = parts[-3], parts[-2]
        if tag.startswith(channel_prefix):
            group = f"{group}__{tag[len(channel_prefix):]}"
        out[group] = f
    return out


def load_waven(path) -> pd.DataFrame:
    if path is None or not Path(path).exists():
        return pd.DataFrame(columns=WAVEN_COLS)
    df = load_rf_results(_read(path))
    if "rf_map" not in df.columns:
        print(f"  {Path(path).name}: no rf_maps stored — skipping")
        return pd.DataFrame(columns=WAVEN_COLS)
    df = df[[c for c in WAVEN_COLS if c in df.columns]].copy()
    df["unit_id"] = df["unit_id"].map(canonical_unit_id)
    return df


def _extent_from_centres(x_pos, y_pos):
    dx = np.median(np.diff(x_pos)) if len(x_pos) > 1 else 1.0
    dy = np.median(np.diff(y_pos)) if len(y_pos) > 1 else 1.0
    return (
        x_pos[0] - dx / 2, x_pos[-1] + dx / 2,
        y_pos[0] - dy / 2, y_pos[-1] + dy / 2,
    )


def load_gabor(path) -> pd.DataFrame:
    """Best orientation per unit: lowest p, then largest peak |z| on a tie."""
    if path is None or not Path(path).exists():
        empty = pd.DataFrame(columns=GABOR_COLS)
        empty.attrs["extent"] = (-45, 45, -45, 45)
        return empty

    with h5py.File(_read(path), "r") as hf:
        unit_names = hf["unit_names"][:].astype(str)
        p_values = hf["p_value"][:]
        z_scores = hf["z_score_response"][:]
        mean_response = hf["mean_response"][:]
        orientations = hf["orientations"][:]
        x_pos, y_pos = hf["x_positions"][:], hf["y_positions"][:]
        if "p_value_bh" in hf and hf["p_value_bh"].shape == (len(unit_names),):
            p_value_bh = np.asarray(hf["p_value_bh"][:], dtype=float)
        else:
            p_value_bh = np.full(len(unit_names), np.nan)
        if "p_value_gumbel" in hf and hf["p_value_gumbel"].shape == (len(unit_names),):
            p_value_gumbel = np.asarray(hf["p_value_gumbel"][:], dtype=float)
        else:
            p_value_gumbel = np.full(len(unit_names), np.nan)

    z_peak = np.nanmax(np.abs(z_scores), axis=(2, 3))
    with np.errstate(invalid="ignore"):
        at_min = p_values <= np.nanmin(p_values, axis=1, keepdims=True) + 1e-12
    best_ori = np.argmax(np.where(at_min, z_peak, -np.inf), axis=1)
    u = np.arange(len(unit_names))

    df = pd.DataFrame({
        "unit_id": [canonical_unit_id(x) for x in unit_names],
        "p_value": p_values[u, best_ori],
        "p_value_gumbel": p_value_gumbel,
        "p_value_bh": p_value_bh,
        "ori_idx": best_ori,
        "ori_rad": orientations[best_ori],
    })
    df["rf_map"] = [z_scores[i, best_ori[i]] for i in u]
    df["rate_map"] = [np.asarray(mean_response[i, best_ori[i]], dtype=float) for i in u]
    df["z_max"] = z_peak[u, best_ori]
    with np.errstate(invalid="ignore"):
        df["z_max_all"] = np.nanmax(z_peak, axis=1)
    df.attrs["extent"] = _extent_from_centres(x_pos, y_pos)
    df.attrs["x_positions"] = np.asarray(x_pos, dtype=float)
    df.attrs["y_positions"] = np.asarray(y_pos, dtype=float)
    df.attrs["orientations"] = tuple(float(o) for o in orientations)
    return df


def load_session(modality: str, session: str, keep: str | None) -> pd.DataFrame:
    """Pooled Zebra maps (``ZEBRA_SIGNAL``) and Gabor maps of one session, merged per unit."""
    signal = ZEBRA_SIGNAL[modality]
    waven_files, gabor_files = discover_waven(session, signal), discover_gabor(modality, session)
    if not waven_files:
        print(f"  no {ZEBRA_BLOCK} phase-{PHASE} Zebra maps for {session}/{signal}")
    frames, extent, orientations = [], None, ()
    x_positions = y_positions = None
    for group in sorted(
        g for g in set(waven_files) | set(gabor_files) if in_filter(g, keep)
    ):
        w = load_waven(waven_files.get(group))
        s = load_gabor(gabor_files.get(group))
        if extent is None and len(s):
            extent = s.attrs["extent"]
            orientations = s.attrs.get("orientations", ())
            x_positions = s.attrs.get("x_positions")
            y_positions = s.attrs.get("y_positions")
        merged = w.merge(s, on="unit_id", how="outer", suffixes=("_zebra", "_gabor"))
        merged.insert(0, "group", group)
        if len(merged):
            frames.append(merged)
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["group", "unit_id", "abs_max_value", "rf_map_zebra", "p_value", "rf_map_gabor"]
    )
    duplicated = df.duplicated(["group", "unit_id"])
    if duplicated.any():
        raise ValueError(
            f"{session}: {int(duplicated.sum())} (group, unit) pairs occur twice, "
            f"e.g. {df.loc[duplicated, ['group', 'unit_id']].head(3).values.tolist()}"
        )
    df.attrs["extent"] = extent or (-45, 45, -45, 45)
    df.attrs["orientations"] = tuple(float(o) for o in orientations)
    if x_positions is not None:
        df.attrs["x_positions"] = np.asarray(x_positions, dtype=float)
        df.attrs["y_positions"] = np.asarray(y_positions, dtype=float)
    return df


def unit_areas_csv() -> Path:
    return RESULTS / "ecephys" / EPHYS_SESSION / "unit_areas.csv"


def load_ephys_unit_areas() -> pd.DataFrame:
    """Unit id, probe, area, and layer from the saved table."""
    path = unit_areas_csv()
    if not path.is_file():
        raise FileNotFoundError(
            f"No unit-area table at {path}. Run export_ephys_unit_areas.py once to build it."
        )
    anatomy = pd.read_csv(_read(path), dtype=str, keep_default_na=False)
    anatomy["unit_id"] = anatomy["unit_id"].map(_text)
    anatomy["probe"] = anatomy["probe"].map(_text)
    return anatomy


def label_summary_groups(modality: str, df: pd.DataFrame) -> pd.DataFrame:
    """VISp vs VISl, or SLAP2 apical (DMD1 green) vs basal (DMD2 green)."""
    if modality == "ecephys":
        anatomy = load_ephys_unit_areas()
        n_match = int(df["unit_id"].isin(set(anatomy["unit_id"])).sum())
        print(f"  unit-id overlap with saved areas: {n_match} / {len(df)}")
        if n_match == 0:
            raise ValueError("no ecephys unit id matches the saved unit areas")
        # Summaries have no area. Walk every probe, match that probe's unit
        # ids, and keep VISp / VISl from the extremum-channel labels.
        pieces = []
        for probe in sorted(set(anatomy["probe"]) | set(df["group"])):
            summary = df[df["group"] == probe]
            labeled = anatomy[anatomy["probe"] == probe]
            vis = labeled[labeled["area"].isin(["VISp", "VISl"])]
            matched = summary.merge(vis[["unit_id", "area"]], on="unit_id", how="inner")
            if len(matched):
                pieces.append(matched)
        if not pieces:
            raise ValueError("no ecephys unit lies in VISp or VISl")
        out = pd.concat(pieces, ignore_index=True)
        out["structure"] = out["area"]
        return out

    if modality == "mesoscope":
        out = df[df["group"].str.match(r"VIS[pl]")].copy()
        out["structure"] = np.where(out["group"].str.startswith("VISp"), "VISp", "VISl")
        return out

    out = df[df["group"].isin(["DMD1__green", "DMD2__green"])].copy()
    out["structure"] = np.where(out["group"] == "DMD1__green", DMD1_LABEL, DMD2_LABEL)
    return out


def primary_visual(modality: str, df: pd.DataFrame) -> pd.DataFrame:
    """Primary visual cortex for the example maps: VISp layer 2/3, or VISp_0."""
    if modality == "ecephys":
        anatomy = load_ephys_unit_areas()
        visp = anatomy[(anatomy["area"] == "VISp") & (anatomy["layer"] == "2/3")]
        out = df.merge(
            visp[["unit_id", "area", "layer", "structure"]], on="unit_id", how="inner",
        )
    elif modality == "mesoscope":
        out = df[df["group"] == "VISp_0"].copy()
    else:
        out = df
    for key in ("extent", "orientations", "x_positions", "y_positions"):
        if key in df.attrs:
            out.attrs[key] = df.attrs[key]
    if "extent" not in out.attrs:
        out.attrs["extent"] = (-45, 45, -45, 45)
    return out


# ---------------------------------------------------------------------------
# Significance, as plot_data_release_panels.py
# ---------------------------------------------------------------------------


def _null_files(modality: str, session: str, lib_ids) -> list[tuple[str, Path]]:
    """Null files of the maps as ``(group, path)``: same signal, block, phase and library."""
    signal = ZEBRA_SIGNAL[modality]
    base = _zebra_dir("nullresults", session, signal)
    if base is None:
        raise FileNotFoundError(f"No null results for {session}/{signal}")
    found = []
    for path in sorted(base.rglob("null__lib_*.h5")):
        rel = path.relative_to(base).parts      # (*group, block, phase, lib_<id>, file)
        if len(rel) < 5 or rel[-4] != ZEBRA_BLOCK or rel[-3] != f"phase_{PHASE}":
            continue
        if rel[-2].removeprefix("lib_") not in lib_ids:
            continue
        found.append(("__".join(rel[:-4]), path))
    return found


def _unit_null_rows(group: str, path: Path) -> pd.DataFrame:
    """Gumbel p-value of every tested unit of one null file, as filter_significant_maps.py."""
    null = load_null(_read(path))
    mu, beta = gumbel_mom(null["M_sur"])
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        p_values = -np.expm1(-np.exp(-(null["max_obs_null"] - mu) / beta))
    p_values = np.where(np.isfinite(p_values), p_values, 1.0)
    return pd.DataFrame({
        "group": group,
        "unit_id": [canonical_unit_id(unit_id) for unit_id in null["unit_ids"]],
        "max_obs_null": null["max_obs_null"],
        "p_null": p_values,
    })


_Q_CACHE: dict[tuple[str, str], pd.DataFrame] = {}
LIBRARIES: dict[str, list[str]] = {}


def zebra_q_table(modality: str, session: str) -> pd.DataFrame:
    """Every tested unit, with its Gumbel p-value and BH q-value.

    The nulls must reproduce the maps' abs_max_value at lag 0. BH families as in
    filter_significant_maps.py: the session for ecephys and mesoscope, each group
    (DMD x channel) for SLAP2.
    """
    key = (modality, session)
    if key in _Q_CACHE:
        return _Q_CACHE[key]
    signal = ZEBRA_SIGNAL[modality]
    maps = discover_waven(session, signal)
    if not maps:
        raise FileNotFoundError(f"No {ZEBRA_BLOCK} phase-{PHASE} Zebra maps for {session}/{signal}")
    libraries, observed = set(), {}
    for group, path in maps.items():
        with h5py.File(_read(path), "r") as hf:
            libraries.update(_text(value) for value in hf["lib_id"][:])
            ids = [canonical_unit_id(_text(value)) for value in hf["unit_ids"][:]]
            observed.update(
                ((group, uid), float(v))
                for uid, v in zip(ids, hf["abs_max_value"][:], strict=True)
            )
    LIBRARIES[modality] = sorted(libraries)
    files = _null_files(modality, session, libraries)
    if not files:
        raise FileNotFoundError(
            f"No {ZEBRA_BLOCK} phase-{PHASE} null files of library {sorted(libraries)} "
            f"for {session}/{signal}"
        )
    table = pd.concat([_unit_null_rows(group, path) for group, path in files], ignore_index=True)
    if table.duplicated(["group", "unit_id"]).any():
        raise ValueError(f"{session}: some units have more than one null file")

    mapped = np.array([
        observed.get(k, np.nan) for k in zip(table["group"], table["unit_id"], strict=True)
    ])
    diff = np.abs(mapped - table["max_obs_null"].to_numpy())
    wrong = np.isfinite(mapped) & (diff > CHECK_TOL)
    if wrong.any():
        raise ValueError(
            f"{session}/{signal}: the null lag-0 maximum disagrees with the maps' abs_max_value "
            f"for {int(wrong.sum())} units (up to {diff[wrong].max():.2e})."
        )

    p_values = table["p_null"].to_numpy()
    if modality == "slap2":
        table["q"] = np.nan
        for _, rows in table.groupby("group").groups.items():
            table.loc[rows, "q"] = _bh_fdr(p_values[table.index.get_indexer(rows)])
    else:
        table["q"] = _bh_fdr(p_values)
    table["significant"] = table["q"] <= Q_LEVEL
    print(
        f"  Zebra null test ({signal}), q ≤ {Q_LEVEL}: "
        f"{int(table['significant'].sum())} / {len(table)} tested units"
    )
    _Q_CACHE[key] = table
    return table


def attach_tests(df: pd.DataFrame, modality: str, session: str) -> pd.DataFrame:
    """Add the Zebra q and the Gabor BH q; an untested unit gets p = q = 1."""
    if "p_value_bh" not in df.columns or df["p_value_bh"].isna().all():
        raise FileNotFoundError(
            f"{session}: the Gabor files carry no p_value_bh. "
            "Run compute_gabor_unit_significance.py first."
        )
    q_table = zebra_q_table(modality, session)
    q_table = q_table[["group", "unit_id", "p_null", "q"]].rename(
        columns={"q": "q_zebra", "p_null": "p_zebra"}
    )
    out = df.merge(q_table, on=["group", "unit_id"], how="left").reset_index(drop=True)
    cols = ["p_value_bh", "p_zebra", "q_zebra"]
    out[cols] = out[cols].fillna(1.0)
    out["pass_zebra"] = out["q_zebra"] <= Q_LEVEL
    out["pass_gabor"] = out["p_value_bh"] <= Q_LEVEL
    out.attrs = dict(df.attrs)
    return out


# ---------------------------------------------------------------------------
# Gaussian fits and summaries, as plot_data_release_panels.py
# ---------------------------------------------------------------------------


def _fit_map(image, x_pos, y_pos, mode):
    """``mode`` is ``signed`` for a Gabor z-map, or ``abs`` for a Zebra envelope."""
    values = np.abs(image) if mode == "abs" else image
    return fit_gaussian_envelope(values, x_pos, y_pos, nonnegative=mode == "abs")


def _zebra_centres(shape):
    """Pixel centres of a Zebra map, drawn with ``origin='upper'`` over ``WAVEN_EXTENT``."""
    nx, ny = shape
    left, right, bottom, top = (float(v) for v in WAVEN_EXTENT)
    x = left + (np.arange(nx) + 0.5) * (right - left) / nx
    y = top - (np.arange(ny) + 0.5) * (top - bottom) / ny
    return x, y


def _gabor_centres(frame, extent, shape):
    x_pos = frame.attrs.get("x_positions")
    y_pos = frame.attrs.get("y_positions")
    if x_pos is None or len(x_pos) != shape[0] or len(y_pos) != shape[1]:
        x_pos = patch_centres(extent[:2], shape[0])
        y_pos = patch_centres(extent[2:], shape[1])
    return np.asarray(x_pos, dtype=float), np.asarray(y_pos, dtype=float)


def _valid_fit(fit) -> bool:
    if not fit.get("success"):
        return False
    values = (fit["sigma_x"], fit["sigma_y"], fit["x0"], fit["y0"], fit["theta"])
    return bool(np.isfinite(values).all() and min(fit["sigma_x"], fit["sigma_y"]) > 0)


def _fit_columns(df: pd.DataFrame, map_col: str, mode: str, centres) -> pd.DataFrame:
    """Gaussian centre, one-sigma ellipse area and fit r2 of each map; NaN where the fit fails."""
    rows = []
    for image in df[map_col]:
        fit = None
        if isinstance(image, np.ndarray):
            x_pos, y_pos = centres(image.shape)
            fit = _fit_map(image, x_pos, y_pos, mode)
            values = (fit["sigma_x"], fit["sigma_y"], fit["x0"], fit["y0"])
            if (
                not fit["success"] or not np.isfinite(values).all()
                or min(fit["sigma_x"], fit["sigma_y"]) <= 0
            ):
                fit = None
        rows.append((np.nan,) * 4 if fit is None else (
            float(fit["x0"]), float(fit["y0"]),
            float(np.pi * fit["sigma_x"] * fit["sigma_y"]), float(fit["r2"]),
        ))
    return pd.DataFrame(rows, columns=["x0", "y0", "area", "fit_r2"], index=df.index)


def rf_corpus(modality: str) -> pd.DataFrame:
    """Units of the RF summaries and the overlap pies, with both tests and fits.

    Every unit of the compared structures. Significant maps carry their Gaussian
    fit in ``gabor_*`` / ``zebra_*`` columns. Gabor-significant units whose fit
    fails or whose centre lies beyond ``GABOR_CENTRE_LIMIT`` are dropped.
    """
    session, keep, _, _ = SESSIONS[modality]
    loaded = load_session(modality, session, keep)
    labeled = label_summary_groups(modality, loaded)
    labeled.attrs = dict(loaded.attrs)
    tested = attach_tests(labeled, modality, session)
    extent = loaded.attrs.get("extent", (-45.0, 45.0, -45.0, 45.0))
    gabor = _fit_columns(
        tested.loc[tested["pass_gabor"]], "rf_map_gabor", "signed",
        lambda shape: _gabor_centres(loaded, extent, shape),
    )
    zebra = _fit_columns(
        tested.loc[tested["pass_zebra"]], "rf_map_zebra", "abs", _zebra_centres,
    )
    tested = tested.join(gabor.add_prefix("gabor_")).join(zebra.add_prefix("zebra_"))
    inside = tested[["gabor_x0", "gabor_y0"]].abs().le(GABOR_CENTRE_LIMIT).all(axis=1)
    dropped = tested["pass_gabor"] & ~inside
    excluded = tested.loc[dropped].groupby("structure").size().to_dict()
    print(f"  Gabor significant, fit failed or centre beyond ±{GABOR_CENTRE_LIMIT:g}°: {excluded}")
    out = tested.loc[~dropped].reset_index(drop=True)
    out.attrs = dict(loaded.attrs)
    out.attrs["excluded_gabor"] = {str(k): int(v) for k, v in excluded.items()}
    return out


def _fit_table(df: pd.DataFrame, kind: str, strength_col: str) -> pd.DataFrame:
    """One row per fitted map of ``kind`` (``gabor`` or ``zebra``) for the summary panels."""
    fitted = pd.DataFrame({
        "group": df["group"].astype(str),
        "unit_id": df["unit_id"].astype(str),
        "structure": df["structure"],
        "x0": df[f"{kind}_x0"],
        "y0": df[f"{kind}_y0"],
        "area": df[f"{kind}_area"],
        "strength": df[strength_col].astype(float),
        "fit_r2": df[f"{kind}_fit_r2"],
    })
    failed = fitted["x0"].isna()
    if failed.any():
        print(f"  {kind}: {int(failed.sum())} of {len(fitted)} fits failed, not drawn")
    return fitted.loc[~failed].reset_index(drop=True)


def _fit_window(x_pos, y_pos) -> tuple[float, float, float, float]:
    """Bounds of a fitted centre: the grid plus one step, as in `fit_gaussian_envelope`."""
    x_pos, y_pos = np.asarray(x_pos, dtype=float), np.asarray(y_pos, dtype=float)
    step = float(np.median(np.diff(np.sort(x_pos))))
    return (x_pos.min() - step, x_pos.max() + step, y_pos.min() - step, y_pos.max() + step)


def _structure_order(structures) -> list[str]:
    present = set(structures)
    return [name for name in STRUCTURE_ORDER if name in present]


def _summary_ci(values: np.ndarray, n_boot: int = N_BOOT) -> tuple[float, float, float]:
    """Median and its bootstrap 95% CI."""
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return np.nan, np.nan, np.nan
    center = float(np.median(values))
    if len(values) == 1:
        return center, center, center
    rng = np.random.default_rng(0)
    draws = rng.choice(values, size=(n_boot, len(values)), replace=True)
    lo, hi = np.percentile(np.median(draws, axis=1), [2.5, 97.5])
    return center, float(lo), float(hi)


def _median_permutation_p(a: np.ndarray, b: np.ndarray, n_perm: int = N_PERM) -> float:
    """Two-sided permutation p-value for a difference of medians."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    observed = abs(float(np.median(a) - np.median(b)))
    pooled = np.concatenate([a, b])
    n_a = len(a)
    rng = np.random.default_rng(0)
    count = 0
    for _ in range(n_perm):
        rng.shuffle(pooled)
        diff = abs(float(np.median(pooled[:n_a]) - np.median(pooled[n_a:])))
        count += diff >= observed - 1e-15
    return (count + 1) / (n_perm + 1)


SUMMARY_COLUMNS = ["column", "structure", "n", "median", "ci_low", "ci_high"]
TEST_COLUMNS = ["column", "structure_a", "structure_b", "p_value"]


def summary_statistics(fitted: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Median and CI per structure and column, and the permutation test between structures."""
    structures = _structure_order(fitted["structure"])
    rows, tests = [], []
    for column in ("area", "strength"):
        grouped = []
        for structure in structures:
            values = fitted.loc[fitted["structure"] == structure, column].to_numpy(dtype=float)
            values = values[np.isfinite(values)]
            grouped.append(values)
            center, lo, hi = _summary_ci(values)
            rows.append({
                "column": column, "structure": structure, "n": len(values),
                "median": center, "ci_low": lo, "ci_high": hi,
            })
        if len(grouped) == 2 and all(len(values) for values in grouped):
            tests.append({
                "column": column, "structure_a": structures[0], "structure_b": structures[1],
                "p_value": _median_permutation_p(grouped[0], grouped[1]),
            })
    return (
        pd.DataFrame(rows, columns=SUMMARY_COLUMNS),
        pd.DataFrame(tests, columns=TEST_COLUMNS),
    )


# ---------------------------------------------------------------------------
# Example selection, as plot_data_release_panels.py
# ---------------------------------------------------------------------------


def _both_maps(df: pd.DataFrame) -> pd.DataFrame:
    if "rf_map_gabor" not in df.columns or "rf_map_zebra" not in df.columns:
        return df.iloc[0:0]
    keep = df["rf_map_gabor"].map(lambda m: isinstance(m, np.ndarray)) & df["rf_map_zebra"].map(
        lambda m: isinstance(m, np.ndarray)
    )
    out = df.loc[keep].copy()
    out.attrs = dict(df.attrs)
    return out


def _top_zebra(pool: pd.DataFrame) -> pd.DataFrame:
    """Lowest Zebra p-value first, then largest peak |r|."""
    return pool.dropna(subset=["p_zebra"]).sort_values(
        ["p_zebra", "abs_max_value"], ascending=[True, False],
    )


def _top_gabor(pool: pd.DataFrame) -> pd.DataFrame:
    """Lowest unit-level Gabor p-value first, then largest peak |z|."""
    return pool.dropna(subset=["p_value_gumbel"]).sort_values(
        ["p_value_gumbel", "z_max"], ascending=[True, False],
    )


def _top_both(pool: pd.DataFrame) -> pd.DataFrame:
    """Smallest sum of the Zebra rank and the Gabor rank; ties share the better rank."""
    work = pool.dropna(subset=["p_zebra", "p_value_gumbel"]).copy()
    if not len(work):
        return work
    work["zebra_rank"] = work["p_zebra"].rank(ascending=True, method="min")
    work["gabor_rank"] = work["p_value_gumbel"].rank(ascending=True, method="min")
    work["combined_rank"] = work["zebra_rank"] + work["gabor_rank"]
    return work.sort_values(
        ["combined_rank", "zebra_rank", "p_zebra"], ascending=[True, True, True],
    )


# (selection, pie category, selection rule, ranking), in column order
OVERLAP_COLUMNS = (
    ("both", "both", lambda df: df["pass_zebra"] & df["pass_gabor"], _top_both),
    ("gabor-only", "Gabor only", lambda df: df["pass_gabor"] & ~df["pass_zebra"], _top_gabor),
    ("zebra-only", "Zebra only", lambda df: df["pass_zebra"] & ~df["pass_gabor"], _top_zebra),
)
FIT_NAN = dict.fromkeys(FIT_KEYS, np.nan)


def example_maps(modality: str) -> dict:
    """One example per selection of row A, with maps and the fits of passing maps."""
    session, keep, _, _ = SESSIONS[modality]
    loaded = load_session(modality, session, keep)
    tested = attach_tests(primary_visual(modality, loaded), modality, session)
    paired = _both_maps(tested)
    extent = tuple(float(v) for v in (paired.attrs.get("extent") or (-45, 45, -45, 45)))
    index = EXAMPLE_INDEX[modality]
    gabor_shape = next(m.shape for m in paired["rf_map_gabor"])
    zebra_shape = next(m.shape for m in paired["rf_map_zebra"])
    out = {
        "selection": [], "present": [], "group": [], "unit_id": [], "n_eligible": [],
        "pass_gabor": [], "pass_zebra": [], "gabor_map": [], "zebra_map": [],
        "gabor_fit": [], "zebra_fit": [],
    }
    for stem, _, choose, ranker in OVERLAP_COLUMNS:
        pool = paired.loc[choose(paired)]
        ranked = ranker(pool) if len(pool) else pool
        out["selection"].append(stem)
        out["n_eligible"].append(len(pool))
        if len(ranked) <= index:
            print(f"  {stem}: no example at position {index + 1}")
            out["present"].append(False)
            out["group"].append("")
            out["unit_id"].append("")
            out["pass_gabor"].append(False)
            out["pass_zebra"].append(False)
            out["gabor_map"].append(np.full(gabor_shape, np.nan))
            out["zebra_map"].append(np.full(zebra_shape, np.nan))
            out["gabor_fit"].append(FIT_NAN)
            out["zebra_fit"].append(FIT_NAN)
            continue
        row = ranked.iloc[index]
        print(f"  {stem}: example {index + 1} of {len(pool)}  {row.group} / {row.unit_id}")
        gabor_map = np.asarray(row["rf_map_gabor"], dtype=float)
        zebra_map = np.asarray(row["rf_map_zebra"], dtype=float)
        fits = {}
        for kind, image, mode, passed, centres in (
            ("gabor", gabor_map, "signed", bool(row["pass_gabor"]),
             _gabor_centres(paired, extent, gabor_map.shape)),
            ("zebra", zebra_map, "abs", bool(row["pass_zebra"]),
             _zebra_centres(zebra_map.shape)),
        ):
            # A fit is a position and a size only when that stimulus's RF passed.
            fit = _fit_map(image, *centres, mode) if passed else {"success": False}
            fits[kind] = {k: float(fit[k]) for k in FIT_KEYS} if _valid_fit(fit) else FIT_NAN
        out["present"].append(True)
        out["group"].append(str(row["group"]))
        out["unit_id"].append(str(row["unit_id"]))
        out["pass_gabor"].append(bool(row["pass_gabor"]))
        out["pass_zebra"].append(bool(row["pass_zebra"]))
        out["gabor_map"].append(gabor_map)
        out["zebra_map"].append(zebra_map)
        out["gabor_fit"].append(fits["gabor"])
        out["zebra_fit"].append(fits["zebra"])
    out["gabor_extent"] = extent
    out["gabor_x_positions"], out["gabor_y_positions"] = _gabor_centres(
        paired, extent, gabor_shape,
    )
    out["n_units"] = len(tested)
    out["n_paired"] = len(paired)
    return out


def modality_summary(modality: str) -> dict:
    """Rows B and C of one modality."""
    corpus = rf_corpus(modality)
    corpus = corpus.assign(structure=corpus["structure"].replace(_SUMMARY_RENAME))
    gabor = corpus.loc[corpus["pass_gabor"]]
    zebra = corpus.loc[corpus["pass_zebra"]]
    gabor_fit = _fit_table(gabor, "gabor", "z_max_all")
    zebra_fit = _fit_table(zebra, "zebra", "abs_max_value")
    extent = corpus.attrs.get("extent", (-45.0, 45.0, -45.0, 45.0))
    gabor_sample = next(m for m in gabor["rf_map_gabor"] if isinstance(m, np.ndarray))
    zebra_sample = next(m for m in zebra["rf_map_zebra"] if isinstance(m, np.ndarray))
    return {
        "units": corpus,
        "gabor_fit": gabor_fit,
        "zebra_fit": zebra_fit,
        "gabor_stats": summary_statistics(gabor_fit),
        "zebra_stats": summary_statistics(zebra_fit),
        "gabor_window": _fit_window(*_gabor_centres(corpus, extent, gabor_sample.shape)),
        "zebra_window": _fit_window(*_zebra_centres(zebra_sample.shape)),
        "excluded_gabor": corpus.attrs["excluded_gabor"],
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def zebra_frame(movie: Path, index: int = ZEBRA_FRAME) -> np.ndarray:
    """Grey levels (uint8) of one movie frame, block-averaged by ``ZEBRA_FRAME_DOWNSAMPLE``."""
    import cv2

    capture = cv2.VideoCapture(str(movie))
    capture.set(cv2.CAP_PROP_POS_FRAMES, index)
    ok, frame = capture.read()
    capture.release()
    if not ok:
        raise OSError(f"cannot read frame {index} of {movie}")
    grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(float)
    k = ZEBRA_FRAME_DOWNSAMPLE
    h, w = (grey.shape[0] // k) * k, (grey.shape[1] // k) * k
    blocks = grey[:h, :w].reshape(h // k, k, w // k, k).mean(axis=(1, 3))
    return np.round(blocks).astype(np.uint8)


STRING = h5py.string_dtype("utf-8")


def _dataset(group: h5py.Group, name: str, values) -> None:
    values = np.asarray(values)
    if values.dtype.kind in "OUS":
        group.create_dataset(name, data=values.astype(object), dtype=STRING, track_times=False)
    elif values.ndim >= 2:
        group.create_dataset(
            name, data=values, compression="gzip", compression_opts=4, shuffle=True,
            track_times=False,
        )
    else:
        group.create_dataset(name, data=values, track_times=False)


def _table(parent: h5py.Group, name: str, frame: pd.DataFrame, columns) -> None:
    group = parent.create_group(name, track_order=True)
    for column, dtype in columns:
        values = frame[column].to_numpy()
        _dataset(group, column, values.astype(str) if dtype is str else values.astype(dtype))


def write_h5(path: Path, frame: np.ndarray, results: dict) -> None:
    with h5py.File(path, "w", libver=("earliest", "v110"), track_order=True) as hf:
        hf.attrs["schema_version"] = SCHEMA_VERSION
        hf.attrs["q_level"] = Q_LEVEL
        hf.attrs["gabor_centre_limit_deg"] = GABOR_CENTRE_LIMIT
        hf.attrs["zebra_block"] = ZEBRA_BLOCK
        hf.attrs["phase"] = PHASE
        hf.attrs["visual_coverage_deg"] = np.asarray(visual_coverage, dtype=float)
        hf.attrs["zebra_extent_deg"] = np.asarray(WAVEN_EXTENT, dtype=float)

        stimulus = hf.create_group("stimulus", track_order=True)
        _dataset(stimulus, "zebra_frame", frame)
        stimulus["zebra_frame"].attrs["frame_index"] = ZEBRA_FRAME
        stimulus["zebra_frame"].attrs["downsample"] = ZEBRA_FRAME_DOWNSAMPLE
        for key, value in GABOR_PATCH.items():
            stimulus.attrs[f"gabor_{key}"] = value

        for modality, packed in results.items():
            session, keep, dandiset, population = SESSIONS[modality]
            group = hf.create_group(modality, track_order=True)
            group.attrs["session"] = session
            group.attrs["dandiset"] = dandiset
            group.attrs["zebra_signal"] = ZEBRA_SIGNAL[modality]
            group.attrs["gabor_signal"] = "spikes" if modality == "ecephys" else GABOR_SIGNAL
            group.attrs["example_population"] = population
            group.attrs["library_id"] = ",".join(LIBRARIES[modality])

            ex = packed["examples"]
            examples = group.create_group("examples", track_order=True)
            for key in ("selection", "group", "unit_id"):
                _dataset(examples, key, np.asarray(ex[key], dtype=str))
            for key in ("present", "pass_gabor", "pass_zebra"):
                _dataset(examples, key, np.asarray(ex[key], dtype=bool))
            _dataset(examples, "n_eligible", np.asarray(ex["n_eligible"], dtype=np.int64))
            _dataset(examples, "gabor_map", np.stack(ex["gabor_map"]).astype(np.float32))
            _dataset(examples, "zebra_map", np.stack(ex["zebra_map"]).astype(np.float32))
            for kind in ("gabor", "zebra"):
                fits = np.array([[fit[k] for k in FIT_KEYS] for fit in ex[f"{kind}_fit"]])
                _dataset(examples, f"{kind}_fit", fits.astype(np.float64))
                examples[f"{kind}_fit"].attrs["columns"] = ",".join(FIT_KEYS)
            examples.attrs["gabor_extent_deg"] = np.asarray(ex["gabor_extent"], dtype=float)
            examples.attrs["gabor_x_positions_deg"] = ex["gabor_x_positions"]
            examples.attrs["gabor_y_positions_deg"] = ex["gabor_y_positions"]
            examples.attrs["n_units"] = ex["n_units"]
            examples.attrs["n_paired"] = ex["n_paired"]

            units = packed["units"]
            _table(group, "units", units, (
                ("group", str), ("unit_id", str), ("structure", str),
                ("pass_gabor", bool), ("pass_zebra", bool),
                ("p_value_bh", np.float64), ("q_zebra", np.float64),
            ))
            for kind in ("gabor", "zebra"):
                _table(group, f"{kind}_fits", packed[f"{kind}_fit"], (
                    ("group", str), ("unit_id", str), ("structure", str),
                    ("x0", np.float64), ("y0", np.float64), ("area", np.float64),
                    ("strength", np.float64), ("fit_r2", np.float64),
                ))
                group[f"{kind}_fits"].attrs["window_deg"] = np.asarray(
                    packed[f"{kind}_window"], dtype=float,
                )
                summary, tests = packed[f"{kind}_stats"]
                _table(group, f"{kind}_summary", summary, (
                    ("column", str), ("structure", str), ("n", np.int64),
                    ("median", np.float64), ("ci_low", np.float64), ("ci_high", np.float64),
                ))
                _table(group, f"{kind}_tests", tests, (
                    ("column", str), ("structure_a", str), ("structure_b", str),
                    ("p_value", np.float64),
                ))


def write_deterministic(frame: np.ndarray, results: dict) -> str:
    """Write twice, check both copies are identical, then move one into place."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    digests, paths = [], []
    try:
        for _ in range(2):
            handle, name = tempfile.mkstemp(suffix=".h5", dir=OUTPUT_DIR)
            os.close(handle)
            paths.append(Path(name))
            write_h5(paths[-1], frame, results)
            digests.append(sha256(paths[-1]))
        if digests[0] != digests[1]:
            raise RuntimeError("two writes of the same data differ; the HDF5 is not deterministic")
        os.replace(paths[0], OUTPUT_PATH)
        OUTPUT_PATH.chmod(0o644)
    finally:
        for path in paths:
            path.unlink(missing_ok=True)
    return digests[0]


def environment() -> dict:
    from importlib.metadata import version
    from platform import python_version

    packages = ("numpy", "scipy", "pandas", "h5py", "opencv-python-headless")
    return {"python": python_version(), **{name: version(name) for name in packages}}


def provenance(results: dict, h5_digest: str, movie: Path, results_url: str | None) -> dict:
    inputs = []
    for path in sorted(READ_FILES):
        inputs.append({
            "path": path.relative_to(RESULTS.resolve()).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        })
    counts = {}
    for modality, packed in results.items():
        units = packed["units"]
        counts[modality] = {
            "structures": {
                str(structure): {
                    "units": int(len(sub)),
                    "neither": int((~sub["pass_zebra"] & ~sub["pass_gabor"]).sum()),
                    "zebra_only": int((sub["pass_zebra"] & ~sub["pass_gabor"]).sum()),
                    "gabor_only": int((sub["pass_gabor"] & ~sub["pass_zebra"]).sum()),
                    "both": int((sub["pass_zebra"] & sub["pass_gabor"]).sum()),
                    "gabor_fits": int((packed["gabor_fit"]["structure"] == structure).sum()),
                    "zebra_fits": int((packed["zebra_fit"]["structure"] == structure).sum()),
                }
                for structure, sub in units.groupby("structure", sort=False)
            },
            "excluded_gabor_fit_or_centre": packed["excluded_gabor"],
            "example_units": [
                {"selection": s, "group": g, "unit_id": u, "eligible": int(n)}
                for s, g, u, n in zip(
                    packed["examples"]["selection"], packed["examples"]["group"],
                    packed["examples"]["unit_id"], packed["examples"]["n_eligible"],
                    strict=True,
                )
            ],
        }
    sessions = {
        modality: {
            "session": session,
            "dandiset": dandiset,
            "asset_path": f"{session.split('_')[0]}/{session}.nwb",
            "zebra_signal": ZEBRA_SIGNAL[modality],
            "gabor_signal": "spikes" if modality == "ecephys" else GABOR_SIGNAL,
            "channel": keep,
            "zebra_library_ids": LIBRARIES[modality],
        }
        for modality, (session, keep, dandiset, _) in SESSIONS.items()
    }
    return {
        "description": (
            "Receptive-field figure intermediate: example Zebra and Gabor maps, significance "
            "overlap and Gaussian-fit summaries for one session per modality."
        ),
        "generator": "scripts/extract_receptive_fields.py",
        "retrieved": date.today().isoformat(),
        "pipeline": {
            "code": "scripts/receptive_fields/",
            "requirements": "scripts/receptive_fields/requirements.txt",
            "waven": WAVEN,
        },
        "results": {
            "url": results_url,
            "layout": "figure_sources/data/receptive-fields/README.md",
            "inputs": inputs,
        },
        "sessions": sessions,
        "stimulus": {
            "movie_url": MOVIE_URL,
            "movie_sha256": sha256(movie),
            "zebra_frame_index": ZEBRA_FRAME,
            "zebra_frame_downsample": ZEBRA_FRAME_DOWNSAMPLE,
            "gabor_patch": GABOR_PATCH,
        },
        "parameters": {
            "q_level": Q_LEVEL,
            "zebra_test": (
                "Gumbel fit (method of moments) to the surrogate maxima of the sweep-wide maximum "
                "|r|; Benjamini-Hochberg over the session (ecephys, mesoscope) or per DMD x "
                "channel (SLAP2)"
            ),
            "gabor_test": (
                "unit-level Gumbel p-value after the search over windows and orientations "
                "(compute_gabor_unit_significance.py), Benjamini-Hochberg q in p_value_bh"
            ),
            "untested_units": "p = q = 1 on the untested stimulus",
            "zebra_block": ZEBRA_BLOCK,
            "phase": PHASE,
            "gabor_centre_limit_deg": GABOR_CENTRE_LIMIT,
            "bootstrap_resamples": N_BOOT,
            "permutations": N_PERM,
            "random_seed": 0,
            "example_rank": {m: i + 1 for m, i in EXAMPLE_INDEX.items()},
        },
        # The Gaussian fits (scipy.optimize.curve_fit) shift slightly between
        # library versions, most for the 9 x 9 Gabor maps.
        "environment": environment(),
        "counts": counts,
        "output": {
            "path": OUTPUT_PATH.relative_to(REPO_ROOT).as_posix(),
            "bytes": OUTPUT_PATH.stat().st_size,
            "sha256": h5_digest,
        },
    }


def main() -> None:
    global RESULTS
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results-root", type=Path, required=True,
                        help="folder holding the reduced results (gabors/, zebra/, ecephys/)")
    parser.add_argument("--results-url", default=None,
                        help="public location of that folder, recorded in the provenance")
    parser.add_argument("--movie", type=Path, default=Path(movpath),
                        help="Zebra stimulus movie (default: waven_settings.movpath)")
    args = parser.parse_args()
    RESULTS = args.results_root
    if not args.movie.is_file():
        raise FileNotFoundError(f"no Zebra movie at {args.movie}; download {MOVIE_URL}")
    if sha256(args.movie) != MOVIE_SHA256:
        raise ValueError(f"{args.movie} is not the published Zebra movie ({MOVIE_URL})")

    results = {}
    for modality in SESSIONS:
        print(f"\n=== {modality} ===")
        results[modality] = modality_summary(modality)
        results[modality]["examples"] = example_maps(modality)
    frame = zebra_frame(args.movie)
    digest = write_deterministic(frame, results)
    record = provenance(results, digest, args.movie, args.results_url)
    PROVENANCE_PATH.write_text(
        json.dumps(record, indent=2, sort_keys=False, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n",
    )
    print(f"\nWrote {OUTPUT_PATH.relative_to(REPO_ROOT)} ({OUTPUT_PATH.stat().st_size} bytes)")
    print(f"Wrote {PROVENANCE_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
