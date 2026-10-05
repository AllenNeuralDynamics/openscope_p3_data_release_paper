#!/usr/bin/env python3
"""OpenScope P3 WaveMAP extraction/analysis refresh.

Scientific calculations are copied from the approved notebook unchanged.
Only Google Drive/path infrastructure is replaced and plotting-only code is omitted.
This script writes the compact intermediate consumed by the publication figures.
"""

# ==================== ORIGINAL NOTEBOOK CELL 4 ====================
# Cell 2: Imports, optional GPU acceleration, and local checkpoint storage

import gc
import gzip
import json
import os
import pickle
import random
import re
import shutil
import warnings
from pathlib import Path

# ------------------------------------------------------------
# Optional GPU acceleration
# ------------------------------------------------------------
# Never make the analysis depend on RAPIDS. If this Colab image already
# has cuML, enable its compatibility layer BEFORE importing UMAP.
GPU_ACCELERATION = False
try:
    import cuml

    cuml.accel.install(log_level="warn")
    GPU_ACCELERATION = True
    print(f"Optional GPU acceleration enabled (cuML {cuml.__version__}).")
except Exception:
    print("cuML not available: using standard CPU umap-learn.")

import fsspec
import h5py
import matplotlib as mpl
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd
import seaborn as sns
import sklearn.preprocessing
import umap
from dandi.dandiapi import DandiAPIClient
from fsspec.implementations.cached import CachingFileSystem
from IPython.display import display
from pynwb import NWBHDF5IO

# ------------------------------------------------------------
# Repository-safe local paths (infrastructure only)
# ------------------------------------------------------------
REPO_ROOT = Path(os.environ.get("OPENSCOPE_P3_REPO_ROOT", Path.cwd())).resolve()
WORK_DIR = Path(os.environ.get("OPENSCOPE_P3_WAVEMAP_WORK", REPO_ROOT / ".wavemap_work")).resolve()
OUT_DIR = WORK_DIR / "outputs"
CHECKPOINT_DIR = WORK_DIR / "session_checkpoints"
LOCAL_CACHE_DIR = WORK_DIR / "nwb_cache"
PUBLICATION_DATA_DIR = REPO_ROOT / "figure_sources" / "data" / "wavemap"
for _p in (WORK_DIR, OUT_DIR, CHECKPOINT_DIR, LOCAL_CACHE_DIR, PUBLICATION_DATA_DIR):
    _p.mkdir(parents=True, exist_ok=True)
np.random.seed(42)
random.seed(42)
print("\nEnvironment ready.")
print("Repository root:", REPO_ROOT)
print("Local work folder:", WORK_DIR)
print("Checkpoint folder:", CHECKPOINT_DIR)
print("Output folder:", OUT_DIR)
print("GPU acceleration active:", GPU_ACCELERATION)


# ==================== ORIGINAL NOTEBOOK CELL 6 ====================
# Cell 3: Analysis settings and manuscript session inventory

DANDISET_ID = "001637"

ISI_MAX = 0.01
PRESENCE_MIN = 0.9
SNR_MIN = 3.0
AMP_CUTOFF_MAX = 0.1

# WaveMAP graph parameters.
# Lee et al. (eLife 2021) used n_neighbors=20, min_dist=0.1,
# Euclidean distance, and random_state=42.
# Louvain resolution is selected separately for each anatomical group below.
RAND_STATE = 42
N_NEIGHBORS = 20
UMAP_MIN_DIST = 0.1

# Anatomical-area display rules.
# These affect only which areas are shown in the summary heatmap, not unit inclusion.
MIN_UNITS_PER_AREA = 50
MIN_SESSIONS_PER_AREA = 3
MAX_AREAS = 20


CONTEXT_ORDER = [
    "Standard oddball",
    "Sensorimotor mismatch",
    "Sequence mismatch",
    "Duration mismatch",
]

# Current Neuropixels session inventory from Table 1 of the data-release manuscript.
SESSION_KEYS = {
    "Standard oddball": [
        "820454_2025-11-05",
        "830794_2026-01-27",
        "830795_2026-02-24",
        "830846_2026-03-11",
        "830847_2026-03-11",
        "830848_2026-03-04",
        "830849_2026-03-06",
        "830851_2026-03-17",
        "830852_2026-02-24",
        "834686_2026-03-25",
        "834687_2026-03-18",
        "834691_2026-02-17",
        "848387_2026-05-05",
        "848390_2026-05-05",
    ],
    "Sensorimotor mismatch": [
        "820454_2025-11-04",
        "820459_2025-11-10",
        "830794_2026-01-26",
        "830795_2026-02-23",
        "830846_2026-03-12",
        "830847_2026-03-12",
        "830848_2026-03-05",
        "830849_2026-03-07",
        "830851_2026-03-16",
        "830852_2026-02-23",
        "832691_2026-03-26",
        "834686_2026-03-26",
        "834687_2026-03-19",
        "834691_2026-02-16",
        "848387_2026-05-04",
        "848390_2026-05-04",
    ],
    "Sequence mismatch": [
        "820454_2025-11-06",
        "820459_2025-11-12",
        "830794_2026-01-28",
        "830795_2026-02-25",
        "830846_2026-03-09",
        "830847_2026-03-09",
        "830848_2026-03-02",
        "830849_2026-03-04",
        "830851_2026-03-18",
        "830852_2026-02-25",
        "832691_2026-03-23",
        "834686_2026-03-23",
        "834687_2026-03-16",
        "848387_2026-05-06",
        "848390_2026-05-06",
    ],
    "Duration mismatch": [
        "820454_2025-11-07",
        "830794_2026-01-29",
        "830795_2026-02-26",
        "830846_2026-03-10",
        "830847_2026-03-10",
        "830848_2026-03-03",
        "830849_2026-03-05",
        "830851_2026-03-19",
        "830852_2026-02-26",
        "832691_2026-03-24",
        "834686_2026-03-24",
        "834687_2026-03-17",
        "848387_2026-05-07",
        "848390_2026-05-07",
    ],
}

rows = []
for context, keys in SESSION_KEYS.items():
    for key in keys:
        mouse_id, date = key.split("_", 1)
        rows.append({"mouse_id": mouse_id, "date": date, "context": context, "session_key": key})

session_inventory = pd.DataFrame(rows)
session_inventory["date"] = pd.to_datetime(session_inventory["date"])

first_context = (
    session_inventory.sort_values("date").groupby("mouse_id", as_index=True).first()["context"]
)
cohort_map = {
    mouse: ("motor-first" if context == "Sensorimotor mismatch" else "sequence-first")
    for mouse, context in first_context.items()
}
session_inventory["cohort"] = session_inventory["mouse_id"].map(cohort_map)

print("Sessions in manuscript inventory:", len(session_inventory))
print("Mice:", session_inventory["mouse_id"].nunique())
print("\nSessions per context:")
print(session_inventory["context"].value_counts().reindex(CONTEXT_ORDER))
print("\nCohort counts by mouse:")
print(pd.Series(cohort_map).value_counts())

# ==================== ORIGINAL NOTEBOOK CELL 8 ====================
# Cell 4: Resolve the exact NWB assets from DANDI
# Uses subject + date from the manuscript session inventory.

resolved_paths = []
asset_ids = []
asset_sizes = []
problems = []

with DandiAPIClient() as client:
    dandiset = client.get_dandiset(DANDISET_ID)

    for row in session_inventory.itertuples(index=False):
        date_str = row.date.strftime("%Y-%m-%d")
        pattern = (
            f"sub-{row.mouse_id}/"
            f"sub-{row.mouse_id}_ses-ecephys-{row.mouse_id}-{date_str}-*_ecephys.nwb"
        )
        matches = list(dandiset.get_assets_by_glob(pattern))

        if len(matches) == 1:
            a = matches[0]
            resolved_paths.append(a.path)
            asset_ids.append(a.identifier)
            asset_sizes.append(a.size)
            problems.append("")
        else:
            resolved_paths.append(None)
            asset_ids.append(None)
            asset_sizes.append(np.nan)
            problems.append(f"{len(matches)} matches for {pattern}")

session_inventory["filepath"] = resolved_paths
session_inventory["asset_id"] = asset_ids
session_inventory["asset_size_bytes"] = asset_sizes
session_inventory["resolution_problem"] = problems

bad = session_inventory[session_inventory["filepath"].isna()]
if len(bad):
    display(bad[["session_key", "context", "resolution_problem"]])
    raise RuntimeError("Some manuscript sessions could not be resolved uniquely on DANDI.")

print(f"Resolved {len(session_inventory)}/{len(session_inventory)} manuscript sessions.")
print(
    f"Total NWB asset size represented: {session_inventory['asset_size_bytes'].sum() / 1e9:.1f} GB"
)
display(session_inventory[["session_key", "context", "filepath", "asset_size_bytes"]].head())


# ==================== ORIGINAL NOTEBOOK CELL 10 ====================
# Cell 5: Stable, RAM-bounded, resumable NWB extraction
#
# IMPORTANT: computational engineering only. Scientific inclusion/QC logic is unchanged.
# Each session is opened remotely through the official DANDI asset URL with local fsspec
# caching. Only QC-passing waveforms are retained. A completed session is immediately
# written to local checkpoint storage, then all NWB/cache objects are closed and deleted.

WAVEFORM_READ_CHUNK = 64
CHECKPOINT_VERSION = 2  # v2 stores anatomy + waveform-shape metrics during the initial NWB pass

# Resume-safe QC defaults.
# These are only used if the settings cell has not been executed in the
# current runtime. Explicit values already present in globals() are preserved.
_QC_DEFAULTS = {
    "ISI_MAX": 0.01,
    "PRESENCE_MIN": 0.9,
    "AMP_CUTOFF_MAX": 0.1,
    "SNR_MIN": 3.0,
}
_missing_qc_settings = []
for _qc_name, _qc_default in _QC_DEFAULTS.items():
    if _qc_name not in globals():
        globals()[_qc_name] = _qc_default
        _missing_qc_settings.append(f"{_qc_name}={_qc_default}")

if _missing_qc_settings:
    print("[resume-safe] Restored missing QC settings: " + ", ".join(_missing_qc_settings))


def _decode_text(x):
    if isinstance(x, bytes):
        return x.decode("utf-8", errors="replace")
    return str(x) if x is not None else None


def _find_column(table, candidates):
    for name in candidates:
        if name in table.colnames:
            return name
    return None


def _safe_scalar(x):
    if x is None:
        return np.nan
    if isinstance(x, bytes):
        return _decode_text(x)
    if np.isscalar(x):
        try:
            return x.item()
        except Exception:
            return x
    arr = np.asarray(x)
    if arr.size == 1:
        value = arr.reshape(-1)[0]
        return value.item() if hasattr(value, "item") else value
    return x


def _numeric_or_nan(x):
    try:
        val = float(_safe_scalar(x))
        return val if np.isfinite(val) else np.nan
    except Exception:
        return np.nan


def _numeric_array_or_nan(arr, n):
    if arr is None:
        return np.full(n, np.nan, dtype=np.float64)
    out = np.empty(n, dtype=np.float64)
    for i in range(n):
        out[i] = _numeric_or_nan(arr[i])
    return out


def _select_peak_waveform(wf):
    """Reduce one NWB mean waveform to one 1-D peak-channel waveform."""
    arr = np.asarray(wf, dtype=np.float32).squeeze()

    if arr.ndim == 1:
        if arr.size < 3:
            return None, None
        return arr, 0

    if arr.ndim == 2:
        ptp_by_electrode = np.ptp(arr, axis=0)
        if not np.any(np.isfinite(ptp_by_electrode)):
            return None, None
        local_peak_idx = int(np.nanargmax(ptp_by_electrode))
        return arr[:, local_peak_idx], local_peak_idx

    return None, None


def _get_waveform_sampling_rate(units_table):
    wf_col = units_table["waveform_mean"]
    for obj in (wf_col, getattr(wf_col, "target", None)):
        if obj is not None and hasattr(obj, "sampling_rate"):
            try:
                rate = float(obj.sampling_rate)
                if np.isfinite(rate):
                    return rate
            except Exception:
                pass
    return np.nan


def _clean_area_label(x):
    """Normalize non-anatomical/missing electrode locations to None."""
    text = _decode_text(x)
    if text is None:
        return None
    text = text.strip()
    if text in {"", "None", "nan", "unknown", "Unknown", "NONE", "void"}:
        return None
    return text


def _build_ap_anatomy_lookup(nwb):
    """Map (probe/group name, AP channel index) -> electrode anatomical location."""
    if nwb.electrodes is None:
        raise KeyError("NWB has no electrodes table; cannot assign anatomical areas.")

    et = nwb.electrodes
    channel_col = _find_column(et, ["channel_name"])
    group_col = _find_column(et, ["group_name", "probe_name", "device_name"])
    location_col = _find_column(et, ["location", "structure_acronym", "brain_region"])

    missing = [
        name
        for name, col in {
            "channel_name": channel_col,
            "group_name": group_col,
            "location": location_col,
        }.items()
        if col is None
    ]
    if missing:
        raise KeyError(
            f"Electrode anatomy column(s) missing: {missing}. "
            f"Available electrode columns: {list(et.colnames)}"
        )

    channel_names = np.asarray(et[channel_col][:], dtype=object)
    group_names = np.asarray(et[group_col][:], dtype=object)
    locations = np.asarray(et[location_col][:], dtype=object)

    lookup = {}
    for channel, group, location in zip(channel_names, group_names, locations, strict=False):
        channel = _decode_text(channel)
        group = _decode_text(group)
        if channel is None or group is None:
            continue

        match = re.fullmatch(r"AP(\d+)", channel.strip())
        if match is None:
            continue

        key = (group.strip(), int(match.group(1)))
        location = _clean_area_label(location)

        if key in lookup and lookup[key] != location:
            raise ValueError(
                f"Ambiguous anatomy for probe/channel {key}: {lookup[key]!r} versus {location!r}"
            )
        lookup[key] = location

    if not lookup:
        raise ValueError("No AP electrode channels could be mapped to anatomy.")
    return lookup


def _preload_unit_anatomy(units, nwb):
    """Read device/extremum metadata once and assign anatomy for all units."""
    probe_col = _find_column(units, ["device_name", "probe_name", "group_name"])
    extremum_col = _find_column(units, ["extremum_channel_index"])

    missing = [
        name
        for name, col in {
            "device_name": probe_col,
            "extremum_channel_index": extremum_col,
        }.items()
        if col is None
    ]
    if missing:
        raise KeyError(
            f"Unit anatomy column(s) missing: {missing}. "
            f"Available unit columns: {list(units.colnames)}"
        )

    probes = np.array(
        [
            (_decode_text(x).strip() if _decode_text(x) is not None else None)
            for x in np.asarray(units[probe_col][:], dtype=object)
        ],
        dtype=object,
    )
    extremum = _numeric_array_or_nan(units[extremum_col][:], len(probes))
    lookup = _build_ap_anatomy_lookup(nwb)

    areas = np.empty(len(probes), dtype=object)
    areas[:] = None
    for i, (probe, channel_idx) in enumerate(zip(probes, extremum, strict=False)):
        if probe is not None and np.isfinite(channel_idx):
            areas[i] = lookup.get((probe, int(channel_idx)))

    return probes, extremum, areas


METRIC_ALIASES = {
    "isi_violations_ratio": ["isi_violations_ratio", "isi_violations"],
    "presence_ratio": ["presence_ratio"],
    "amplitude_cutoff": ["amplitude_cutoff"],
    "snr": ["snr"],
    "firing_rate": ["firing_rate"],
    "amplitude": ["amplitude"],
    "d_prime": ["d_prime"],
    "isolation_distance": ["isolation_distance"],
    "silhouette_score": ["silhouette_score"],
    # OpenScope/DANDI names first; older aliases retained as fallbacks.
    "waveform_duration": ["peak_to_valley", "waveform_duration", "duration"],
    "waveform_halfwidth": ["half_width", "waveform_halfwidth", "halfwidth"],
    "PT_ratio": ["peak_trough_ratio", "PT_ratio", "pt_ratio"],
    "depth": ["depth"],
}


def _checkpoint_path(session_key):
    # Versioned path preserves older checkpoints instead of deleting/overwriting them.
    return CHECKPOINT_DIR / f"{session_key}_v{CHECKPOINT_VERSION}.pkl.gz"


def _checkpoint_is_valid(path):
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        with gzip.open(path, "rb") as f:
            payload = pickle.load(f)

        if payload.get("checkpoint_version") != CHECKPOINT_VERSION:
            return False
        if not all(k in payload for k in ("all_df", "qc_df", "waveforms", "summary")):
            return False

        qc_df = payload["qc_df"]
        required_qc_columns = {
            "area",
            "probe",
            "extremum_channel_index",
            "waveform_duration",
            "waveform_halfwidth",
            "PT_ratio",
        }
        if len(qc_df) and not required_qc_columns.issubset(qc_df.columns):
            return False

        return True
    except Exception:
        return False


def _save_checkpoint_atomic(path, payload):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wb", compresslevel=3) as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)


def _open_dandi_nwb_cached(filepath, cache_dir):
    """Open one DANDI NWB with a disposable local HTTP cache."""
    with DandiAPIClient() as client:
        asset = client.get_dandiset(DANDISET_ID).get_asset_by_path(filepath)
        url = asset.get_content_url(follow_redirects=1, strip_query=True)

    http_fs = fsspec.filesystem("http")
    cached_fs = CachingFileSystem(fs=http_fs, cache_storage=str(cache_dir))
    remote_file = cached_fs.open(url, "rb")
    h5_file = h5py.File(remote_file, "r")
    io = NWBHDF5IO(file=h5_file, mode="r", load_namespaces=True)
    return io, h5_file, remote_file


def _process_one_session(s):
    session_cache = LOCAL_CACHE_DIR / s.session_key
    if session_cache.exists():
        shutil.rmtree(session_cache, ignore_errors=True)
    session_cache.mkdir(parents=True, exist_ok=True)

    io = h5_file = remote_file = nwb = units = None

    try:
        print("  -> opening cached remote NWB...")
        io, h5_file, remote_file = _open_dandi_nwb_cached(s.filepath, session_cache)

        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"An attribute 'name' already exists on TimeIntervals.*",
                category=UserWarning,
            )
            nwb = io.read()

        if nwb.units is None:
            return {
                "checkpoint_version": CHECKPOINT_VERSION,
                "all_df": pd.DataFrame(),
                "qc_df": pd.DataFrame(),
                "waveforms": [],
                "summary": {
                    "session_key": s.session_key,
                    "mouse_id": s.mouse_id,
                    "context": s.context,
                    "cohort": s.cohort,
                    "n_total_units": 0,
                    "n_qc_pass": 0,
                    "n_qc_waveform": 0,
                },
            }

        units = nwb.units
        unit_ids = np.asarray(units.id[:])
        n_units = len(unit_ids)

        # Anatomy is resolved now, while the NWB/electrode table is already open.
        # This replaces the former second 59-session anatomy-recovery pass.
        probes, extremum_indices, areas = _preload_unit_anatomy(units, nwb)

        resolved_metric_cols = {
            canonical: _find_column(units, candidates)
            for canonical, candidates in METRIC_ALIASES.items()
        }

        required_names = ["isi_violations_ratio", "presence_ratio", "amplitude_cutoff"]
        missing = [name for name in required_names if resolved_metric_cols[name] is None]
        if missing:
            raise KeyError(
                f"Required manuscript QC column(s) missing: {missing}. "
                f"Available unit columns: {list(units.colnames)}"
            )

        metrics = {}
        for canonical, col in resolved_metric_cols.items():
            if col is None:
                metrics[canonical] = np.full(n_units, np.nan, dtype=np.float64)
            else:
                try:
                    metrics[canonical] = _numeric_array_or_nan(units[col][:], n_units)
                except Exception:
                    metrics[canonical] = np.full(n_units, np.nan, dtype=np.float64)

        isi = metrics["isi_violations_ratio"]
        pr = metrics["presence_ratio"]
        ac = metrics["amplitude_cutoff"]

        qc_mask = (
            np.isfinite(isi)
            & np.isfinite(pr)
            & np.isfinite(ac)
            & (isi < ISI_MAX)
            & (pr > PRESENCE_MIN)
            & (ac < AMP_CUTOFF_MAX)
        )
        qc_indices = np.flatnonzero(qc_mask)

        all_data = {
            "unit_uid": [f"{s.session_key}_unit-{uid}" for uid in unit_ids],
            "unit_id": unit_ids.astype(int),
            "mouse_id": s.mouse_id,
            "session_key": s.session_key,
            "date": s.date,
            "context": s.context,
            "cohort": s.cohort,
            "filepath": s.filepath,
            "probe": probes,
            "extremum_channel_index": extremum_indices,
            "area": areas,
            "qc_pass_manuscript": qc_mask,
        }
        all_data.update(metrics)
        all_df = pd.DataFrame(all_data)

        qc_rows = []
        qc_waveforms = []

        if "waveform_mean" in units.colnames and len(qc_indices):
            wf_col = units["waveform_mean"]
            wf_rate = _get_waveform_sampling_rate(units)
            # Read only bounded ranges containing QC units.
            for start in range(0, n_units, WAVEFORM_READ_CHUNK):
                stop = min(start + WAVEFORM_READ_CHUNK, n_units)
                chunk_qc = qc_indices[(qc_indices >= start) & (qc_indices < stop)]
                if len(chunk_qc) == 0:
                    continue

                try:
                    wf_chunk = wf_col[start:stop]
                except Exception:
                    wf_chunk = None

                for i in chunk_qc:
                    i = int(i)
                    try:
                        wf_raw = wf_chunk[i - start] if wf_chunk is not None else wf_col[i]
                        wf_1d, _local_peak_idx = _select_peak_waveform(wf_raw)
                    except Exception:
                        wf_1d, _local_peak_idx = None, None

                    if wf_1d is None:
                        continue

                    wf_1d = np.asarray(wf_1d, dtype=np.float32)
                    if (
                        wf_1d.ndim != 1
                        or len(wf_1d) < 3
                        or not np.all(np.isfinite(wf_1d))
                        or np.ptp(wf_1d) == 0
                    ):
                        continue

                    row = all_df.iloc[i].to_dict()
                    row.update(
                        {
                            "waveform_sampling_rate_hz": wf_rate,
                            "waveform_n_samples": len(wf_1d),
                        }
                    )
                    qc_rows.append(row)
                    qc_waveforms.append(wf_1d)

                if wf_chunk is not None:
                    del wf_chunk

        qc_df = pd.DataFrame(qc_rows)
        summary = {
            "session_key": s.session_key,
            "mouse_id": s.mouse_id,
            "context": s.context,
            "cohort": s.cohort,
            "n_total_units": int(n_units),
            "n_qc_pass": int(qc_mask.sum()),
            "n_qc_waveform": int(len(qc_waveforms)),
        }

        return {
            "checkpoint_version": CHECKPOINT_VERSION,
            "all_df": all_df,
            "qc_df": qc_df,
            "waveforms": qc_waveforms,
            "summary": summary,
        }

    finally:
        for obj in (io, h5_file, remote_file):
            try:
                if obj is not None:
                    obj.close()
            except Exception:
                pass

        try:
            del units, nwb, io, h5_file, remote_file
        except Exception:
            pass

        gc.collect()
        shutil.rmtree(session_cache, ignore_errors=True)


def extract_wavemap_units_stream(session_table):
    """Process missing sessions, checkpoint to Drive, then assemble compact outputs."""
    n_sessions = len(session_table)

    # Stage 1: session extraction. Nothing from earlier sessions remains in RAM.
    for s_idx, s in enumerate(session_table.itertuples(index=False), start=1):
        ckpt = _checkpoint_path(s.session_key)

        if _checkpoint_is_valid(ckpt):
            print(
                f"[{s_idx:02d}/{n_sessions}] {s.session_key} | {s.context} "
                "-> checkpoint exists, skipping"
            )
            continue

        if ckpt.exists():
            print(f"[{s_idx:02d}/{n_sessions}] {s.session_key} | invalid checkpoint removed")
            ckpt.unlink()

        print(f"[{s_idx:02d}/{n_sessions}] {s.session_key} | {s.context}")
        payload = _process_one_session(s)
        _save_checkpoint_atomic(ckpt, payload)

        sm = payload["summary"]
        print(
            f"  -> total={sm['n_total_units']}, QC pass={sm['n_qc_pass']}, "
            f"QC + usable waveform={sm['n_qc_waveform']} | saved to Drive"
        )
        del payload
        gc.collect()

    # Stage 2: compact assembly after all checkpoints exist.
    print("\nAll session checkpoints present. Assembling final analysis objects...")

    all_parts = []
    qc_parts = []
    waveform_parts = []
    summaries = []

    for s in session_table.itertuples(index=False):
        ckpt = _checkpoint_path(s.session_key)
        if not _checkpoint_is_valid(ckpt):
            raise RuntimeError(f"Missing/invalid checkpoint after extraction: {ckpt}")

        with gzip.open(ckpt, "rb") as f:
            payload = pickle.load(f)

        if len(payload["all_df"]):
            all_parts.append(payload["all_df"])
        if len(payload["qc_df"]):
            qc_parts.append(payload["qc_df"])
        waveform_parts.extend(payload["waveforms"])
        summaries.append(payload["summary"])
        del payload

    all_units_df = pd.concat(all_parts, ignore_index=True) if all_parts else pd.DataFrame()
    units_df = pd.concat(qc_parts, ignore_index=True) if qc_parts else pd.DataFrame()
    session_summary = pd.DataFrame(summaries)

    return all_units_df, units_df, waveform_parts, session_summary


print("Extraction helpers ready.")
print("Persistent checkpoints:", CHECKPOINT_DIR)
print("Disposable NWB cache:", LOCAL_CACHE_DIR)
print("Waveform read chunk:", WAVEFORM_READ_CHUNK)
print("Checkpoint schema version:", CHECKPOINT_VERSION)
print("Anatomy + waveform-shape metrics are captured in this same NWB pass.")


# ==================== ORIGINAL NOTEBOOK CELL 12 ====================
# Cell 6: Execute / resume extraction
# Safe to rerun. Completed sessions on local checkpoint storage are skipped automatically.

# Preflight for resumed/stale Colab kernels.
# This also fixes an already-defined older _process_one_session function,
# because that function resolves QC constants from globals() when it runs.
_QC_DEFAULTS = {
    "ISI_MAX": 0.01,
    "PRESENCE_MIN": 0.9,
    "AMP_CUTOFF_MAX": 0.1,
    "SNR_MIN": 3.0,
}
_missing_qc_settings = []
for _qc_name, _qc_default in _QC_DEFAULTS.items():
    if _qc_name not in globals():
        globals()[_qc_name] = _qc_default
        _missing_qc_settings.append(f"{_qc_name}={_qc_default}")

if _missing_qc_settings:
    print("[Cell 6 preflight] Restored missing QC settings: " + ", ".join(_missing_qc_settings))


all_units_df, units_df, raw_waveform_list, session_summary = extract_wavemap_units_stream(
    session_inventory
)

print("\n=== Extraction complete ===")
print("All units:", len(all_units_df))
print("Manuscript-QC units with usable waveform:", len(units_df))
print("Sessions represented:", units_df["session_key"].nunique())
print("Mice represented:", units_df["mouse_id"].nunique())
print(
    "Valid local checkpoints:",
    sum(_checkpoint_is_valid(_checkpoint_path(k)) for k in session_inventory["session_key"]),
)
print("Anatomical area assigned:", units_df["area"].notna().sum(), "/", len(units_df))
print(
    "Waveform duration available:", units_df["waveform_duration"].notna().sum(), "/", len(units_df)
)
print(
    "Waveform half-width available:",
    units_df["waveform_halfwidth"].notna().sum(),
    "/",
    len(units_df),
)
print("Peak/trough ratio available:", units_df["PT_ratio"].notna().sum(), "/", len(units_df))


# ==================== ORIGINAL NOTEBOOK CELL 14 ====================
# Cell 7: Scientific sanity checks and waveform assembly

display(session_summary.head())

print("\nTotal units by context:")
display(
    session_summary.groupby("context")[["n_total_units", "n_qc_pass", "n_qc_waveform"]]
    .sum()
    .reindex(CONTEXT_ORDER)
)

print("\nWaveform sample-length counts:")
print(units_df["waveform_n_samples"].value_counts().sort_index())

# ------------------------------------------------------------------
# Post-hoc unit gating (applied to the cached table; no re-streaming).
# Reviewer guidance: SNR is paramount — use the highest cutoff the unit
# count allows. Stored 'snr' uses the Jia/Allen convention
# (peak-channel amp / (2*STD noise)); per-spike snippets are not stored,
# so it cannot be recomputed and must be thresholded as-is.
# ------------------------------------------------------------------
SNR_MIN = float(globals().get("SNR_MIN", 3.0))  # ideally define in the settings cell

# 1) common waveform length — do not interpolate silently
modal_n_samples = int(units_df["waveform_n_samples"].mode().iloc[0])
same_length = units_df["waveform_n_samples"].eq(modal_n_samples).to_numpy()

# 2) SNR gate (required column — fail loud if absent rather than skip silently)
if "snr" not in units_df.columns:
    raise KeyError("'snr' column absent from units_df; cannot apply the SNR cutoff.")
snr_vals = pd.to_numeric(units_df["snr"], errors="coerce").to_numpy()
snr_pass = np.isfinite(snr_vals) & (snr_vals >= SNR_MIN)


# 3) re-apply current settings-cell QC thresholds post-hoc, so tightening
#    ISI_MAX / PRESENCE_MIN / AMP_CUTOFF_MAX in settings takes effect from
#    cache. No-op if unchanged since extraction.
def _num(col):
    return (
        pd.to_numeric(units_df[col], errors="coerce").to_numpy()
        if col in units_df.columns
        else np.full(len(units_df), np.nan)
    )


isi_v, pr_v, ac_v = _num("isi_violations_ratio"), _num("presence_ratio"), _num("amplitude_cutoff")
extra_qc = (
    (np.isnan(isi_v) | (isi_v < ISI_MAX))
    & (np.isnan(pr_v) | (pr_v > PRESENCE_MIN))
    & (np.isnan(ac_v) | (ac_v < AMP_CUTOFF_MAX))
)

keep = same_length & snr_pass & extra_qc

# ---- per-criterion accounting (metrics, not silent drops) ----
n0 = len(units_df)
print(f"\nPost-hoc gating on {n0} extraction-QC units:")
print(f"  wrong waveform length : -{int((~same_length).sum())}")
print(
    f"  SNR < {SNR_MIN:g}            : -{int((~snr_pass).sum())} "
    f"(among length-ok: -{int((~snr_pass & same_length).sum())})"
)
print(f"  tightened ISI/PR/AC   : -{int((~extra_qc & same_length & snr_pass).sum())}")
print(
    f"  --> kept              : {int(keep.sum())} ({100 * keep.mean():.1f}% of extraction-QC units)"
)

# ---- reviewer caveat: ISI-violation rate is correlated with firing rate,
#      so any ISI cut preferentially removes high-FR units. Report it. ----
if {"firing_rate", "isi_violations_ratio"}.issubset(units_df.columns):
    from scipy.stats import spearmanr

    _d = (
        units_df[["firing_rate", "isi_violations_ratio"]]
        .apply(pd.to_numeric, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
    )
    if len(_d) > 10:
        _r, _p = spearmanr(_d["firing_rate"], _d["isi_violations_ratio"])
        print(
            f"\nISI-vr vs firing rate: Spearman r={_r:+.2f} (p={_p:.1e}) "
            f"— a flat ISI cut biases against high-FR units; interpret FR maps accordingly."
        )

# ---- apply the combined mask to units_df AND waveforms in lockstep ----
units_df = units_df.loc[keep].reset_index(drop=True)
raw_waveforms = np.vstack([wf for wf, k in zip(raw_waveform_list, keep, strict=False) if k])

assert len(units_df) == raw_waveforms.shape[0]
assert raw_waveforms.shape[1] == modal_n_samples
assert (pd.to_numeric(units_df["snr"], errors="coerce") >= SNR_MIN).all(), (
    "an SNR-failing unit survived the mask"
)

finite_rates = units_df["waveform_sampling_rate_hz"].dropna().astype(float)
WF_SAMPLING_RATE = float(finite_rates.mode().iloc[0]) if len(finite_rates) else 30000.0

print("\nWaveMAP waveform matrix:", raw_waveforms.shape)
print("Waveform sampling rate used:", WF_SAMPLING_RATE, "Hz")

all_units_df.to_pickle(OUT_DIR / "all_units_qc_metrics.pkl")
units_df.to_pickle(OUT_DIR / "qc_units_metadata_pre_wavemap.pkl")
session_summary.to_csv(OUT_DIR / "session_qc_summary.csv", index=False)
np.save(OUT_DIR / "raw_qc_waveforms.npy", raw_waveforms)

print("Cached extraction in:", OUT_DIR)

# Reproducibility / integrity checks
assert session_summary["session_key"].nunique() == len(session_inventory), (
    "Not all manuscript sessions were summarized."
)
assert units_df["unit_uid"].is_unique, "Duplicate unit_uid values detected."
assert set(units_df["session_key"]).issubset(set(session_inventory["session_key"])), (
    "Unexpected session detected."
)
assert units_df["qc_pass_manuscript"].all(), "A non-QC unit entered the WaveMAP table."

missing_context_sessions = set(session_inventory["session_key"]) - set(
    session_summary["session_key"]
)
assert not missing_context_sessions, f"Missing sessions: {sorted(missing_context_sessions)}"

print("\nSanity checks passed:")
print("✓ every intended manuscript session summarized")
print(f"✓ every WaveMAP unit has SNR >= {SNR_MIN:g}")
print("✓ no duplicate unit identifiers")
print("✓ every WaveMAP unit passed manuscript QC")
print("✓ waveform array and unit metadata are aligned")
print(
    f"✓ anatomy populated for {units_df['area'].notna().sum():,}/{len(units_df):,} retained units"
)
for _metric in ["waveform_duration", "waveform_halfwidth", "PT_ratio"]:
    print(f"✓ {_metric}: {units_df[_metric].notna().sum():,}/{len(units_df):,} values available")

# ==================== ORIGINAL NOTEBOOK CELL 19 ====================
# Cell 9: WaveMAP waveform preprocessing
# Official WaveMAP preprocessing retained here:
#   1) subtract each waveform's own mean
#   2) normalize each waveform by its maximum absolute magnitude

meanSubWFs = raw_waveforms - np.mean(raw_waveforms, axis=1, keepdims=True)
normWFs = sklearn.preprocessing.normalize(meanSubWFs, norm="max")

assert np.all(np.isfinite(normWFs))
assert normWFs.shape == raw_waveforms.shape

print("Normalized waveform matrix:", normWFs.shape)
print("Global min/max:", normWFs.min(), normWFs.max())

rng = np.random.default_rng(RAND_STATE)
n_show = min(100, len(normWFs))
show_idx = rng.choice(len(normWFs), size=n_show, replace=False)

fig, ax = plt.subplots(figsize=(6, 3.5), dpi=150)
for i in show_idx:
    ax.plot(normWFs[i], alpha=0.15, linewidth=0.8)

ax.set_xlabel("Waveform sample")
ax.set_ylabel("Normalized amplitude")
ax.set_title(f"Random sample of {n_show} QC-passing normalized waveforms")
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
plt.show()

# ==================== ORIGINAL NOTEBOOK CELL 23 ====================
# ============================================================
# Per-area Louvain resolution selection — conservative
# near-optimal modularity rule
#
# WHY THIS VERSION:
# The current notebook uses `python-louvain`. In this implementation,
# changing the numerical "resolution" parameter does not reproduce the
# same directionality seen in the original WaveMAP `cylouvain` example.
# Therefore the selector should NOT assume that "higher" or "lower"
# resolution is intrinsically coarser.
#
# Instead, selection is made in the biologically relevant space:
#
#       number of clusters  <-->  graph modularity
#
# Procedure:
#   1) Sweep a broad resolution range, including values below 1.0.
#   2) Exclude solutions containing clusters with n <= 20.
#   3) Identify the maximum modularity among feasible solutions.
#   4) Retain all solutions within MODULARITY_TOL of that maximum.
#   5) From these near-optimal solutions, choose the partition with
#      the FEWEST clusters.
#   6) If several solutions have the same number of clusters, choose
#      the one with the highest modularity, then largest minimum cluster.
#
# The Pareto frontier and knee score are retained as diagnostics, but
# they are NOT used for final resolution selection.
#
# This explicitly biases the analysis against oversplitting:
# an additional community is only retained if it provides a meaningful
# improvement in graph modularity.
# ============================================================

from community import community_louvain

# ------------------------------------------------------------
# Resolution sweep
# ------------------------------------------------------------

# Include coarser-than-1 solutions because python-louvain can split more
# strongly as this parameter increases.
RES_GRID = np.round(
    np.arange(0.2, 2.01, 0.1),
    2,
)

# Reject partitions containing very small communities.
MIN_CLUSTER_N = 20

# Absolute modularity tolerance.
# Example: if maximum feasible Q = 0.755, all solutions with Q >= 0.745
# are treated as near-optimal; the least fragmented one is selected.
MODULARITY_TOL = 0.01


def _pareto_frontier_by_cluster_count(feasible):
    """
    Return non-dominated solutions in (n_clusters, modularity) space.

    For a given number of clusters, retain the highest-modularity
    solution. Then keep only points for which allowing more clusters
    produces a genuine modularity increase.

    This is retained for diagnostic plotting only.
    """

    if feasible.empty:
        return feasible.copy()

    best_per_k = (
        feasible.sort_values(
            ["n_clusters", "modularity", "min_size"],
            ascending=[True, False, False],
        )
        .drop_duplicates(
            subset=["n_clusters"],
            keep="first",
        )
        .sort_values("n_clusters")
        .reset_index(drop=True)
    )

    keep = []
    best_q_so_far = -np.inf

    for i, row in best_per_k.iterrows():
        q = float(row["modularity"])

        if q > best_q_so_far + 1e-12:
            keep.append(i)
            best_q_so_far = q

    return best_per_k.loc[keep].reset_index(drop=True)


def _add_knee_score(frontier):
    """
    Add the previous normalized Pareto knee score for diagnostics.

    IMPORTANT:
    This score is no longer used to select the final resolution.
    """

    out = frontier.copy()
    out["knee_score"] = np.nan

    if len(out) < 3:
        return out

    k = out["n_clusters"].to_numpy(dtype=float)
    q = out["modularity"].to_numpy(dtype=float)

    k_span = k.max() - k.min()
    q_span = q.max() - q.min()

    if k_span <= 0 or q_span <= 0:
        return out

    x = (k - k.min()) / k_span
    y = (q - q.min()) / q_span

    out["knee_score"] = y - x

    return out


def _choose_conservative_solution(
    feasible,
    modularity_tol=MODULARITY_TOL,
):
    """
    Choose the least fragmented near-optimal Louvain partition.

    A solution is considered near-optimal when:

        Q >= Q_max - modularity_tol

    Among near-optimal solutions:
        1) prefer fewer clusters
        2) then higher modularity
        3) then larger minimum cluster size

    This deliberately biases selection against oversplitting.
    """

    if feasible.empty:
        raise ValueError("Cannot select from an empty feasible set.")

    q_max = float(feasible["modularity"].max())

    q_threshold = q_max - float(modularity_tol)

    near_optimal = feasible.loc[feasible["modularity"] >= q_threshold].copy()

    pick = near_optimal.sort_values(
        [
            "n_clusters",
            "modularity",
            "min_size",
        ],
        ascending=[
            True,
            False,
            False,
        ],
    ).iloc[0]

    return pick, q_max, q_threshold


def choose_resolution(
    G,
    grid=RES_GRID,
    seed=RAND_STATE,
    min_cluster_n=MIN_CLUSTER_N,
    modularity_tol=MODULARITY_TOL,
):
    """
    Select a Louvain resolution using a conservative near-optimal-Q rule.

    Returns
    -------
    selected_resolution : float
    sweep_df : pandas.DataFrame

    `sweep_df` includes flags/diagnostics for:
        feasible
        pareto
        near_optimal
        selected
        delta_q_from_best
        knee_score

    Final selection does NOT use the Pareto knee score.
    """

    rows = []

    for r in grid:
        part = community_louvain.best_partition(
            G,
            weight="weight",
            resolution=float(r),
            random_state=seed,
        )

        Q = community_louvain.modularity(
            part,
            G,
            weight="weight",
        )

        _, sizes = np.unique(
            list(part.values()),
            return_counts=True,
        )

        rows.append(
            {
                "res": float(r),
                "n_clusters": int(len(sizes)),
                "min_size": int(sizes.min()),
                "median_size": float(np.median(sizes)),
                "modularity": float(Q),
            }
        )

    df = pd.DataFrame(rows).sort_values("res").reset_index(drop=True)

    df["feasible"] = df["min_size"] > min_cluster_n

    df["pareto"] = False
    df["near_optimal"] = False
    df["selected"] = False
    df["knee_score"] = np.nan
    df["delta_q_from_best"] = np.nan

    feasible = df.loc[df["feasible"]].copy()

    if feasible.empty:
        pick = df.sort_values(
            [
                "n_clusters",
                "modularity",
                "min_size",
            ],
            ascending=[
                True,
                False,
                False,
            ],
        ).iloc[0]

        df.loc[
            df["res"].eq(float(pick["res"])),
            "selected",
        ] = True

        print(
            "WARNING: no resolution had all clusters "
            f"> {min_cluster_n} units; using least-fragmented "
            f"solution (res={pick['res']:g}, "
            f"k={int(pick['n_clusters'])}, "
            f"Q={pick['modularity']:.3f})."
        )

        return float(pick["res"]), df

    pick, q_max, q_threshold = _choose_conservative_solution(
        feasible,
        modularity_tol=modularity_tol,
    )

    df.loc[
        df["feasible"],
        "delta_q_from_best",
    ] = (
        q_max
        - df.loc[
            df["feasible"],
            "modularity",
        ]
    )

    df.loc[
        (df["feasible"] & (df["modularity"] >= q_threshold)),
        "near_optimal",
    ] = True

    frontier = _pareto_frontier_by_cluster_count(feasible)

    frontier = _add_knee_score(frontier)

    for _, prow in frontier.iterrows():
        mask = df["res"].eq(float(prow["res"])) & df["n_clusters"].eq(int(prow["n_clusters"]))

        df.loc[
            mask,
            "pareto",
        ] = True

        if pd.notna(
            prow.get(
                "knee_score",
                np.nan,
            )
        ):
            df.loc[
                mask,
                "knee_score",
            ] = float(prow["knee_score"])

    selected_mask = df["res"].eq(float(pick["res"])) & df["n_clusters"].eq(int(pick["n_clusters"]))

    df.loc[
        selected_mask,
        "selected",
    ] = True

    return float(pick["res"]), df


# ==================== ORIGINAL NOTEBOOK CELL 24 ====================
# Cell 10: Run WaveMAP PER FUNCTIONAL AREA-GROUP — separate UMAP + Louvain each
# Reviewer point 2: cluster within functional groups (MO vs CA vs ...), not pooled.


np.random.seed(RAND_STATE)
random.seed(RAND_STATE)
os.environ["PYTHONHASHSEED"] = str(RAND_STATE)

# PREREQUISITE: anatomy is populated during the initial NWB extraction pass.
required_metadata = {"area", "probe", "extremum_channel_index"}
missing_metadata = required_metadata - set(units_df.columns)
if missing_metadata:
    raise RuntimeError(
        f"Missing extraction metadata: {sorted(missing_metadata)}. "
        "Rerun the extraction cells with the v2 single-pass checkpoints."
    )

area_fraction = units_df["area"].notna().mean()
print(
    f"Anatomy available for {units_df['area'].notna().sum()}/{len(units_df)} units "
    f"({100 * area_fraction:.1f}%)."
)
assert area_fraction >= 0.5, (
    "'area' is <50% populated; inspect device_name/extremum_channel_index mapping "
    "in the single-pass extractor."
)

AREA_GROUPS = {
    "MO": ("MOs", "MOp"),
    "HPC": ("CA1", "CA3"),
    "VIS": ("VISp", "VISl"),
    "THAL": ("LGd", "LD"),
    "PFC": ("PL", "ACAd"),
    "STR": ("STR", "LSr"),
}
EXCLUDE_FROM_CLUSTERING = {"or"}
MIN_UNITS_TO_CLUSTER = 40


def _group_of(area):
    if area is None or (isinstance(area, float) and np.isnan(area)):
        return None
    if str(area) in EXCLUDE_FROM_CLUSTERING:
        return None
    for g, prefixes in AREA_GROUPS.items():
        if str(area).startswith(prefixes):
            return g
    return None


units_df["wavemap_group"] = units_df["area"].map(_group_of)
print("Units per functional group:")
print(units_df["wavemap_group"].value_counts(dropna=False), "\n")

assert units_df["wavemap_group"].notna().any(), (
    "No units matched AREA_GROUPS. Unmatched sample: "
    f"{sorted(units_df.loc[units_df['wavemap_group'].isna(), 'area'].dropna().unique())[:15]}"
)

units_df["wavemap_local"] = -1
units_df["umap_x"] = np.nan
units_df["umap_y"] = np.nan
group_cluster_counts = {}
group_embeddings = {}
group_graphs = {}
group_resolutions = {}
group_resolution_sweeps = {}

for g in [x for x in units_df["wavemap_group"].unique() if x is not None]:
    idx = np.where(units_df["wavemap_group"].values == g)[0]
    Wg = normWFs[idx]
    if len(idx) < MIN_UNITS_TO_CLUSTER:
        units_df.iloc[idx, units_df.columns.get_loc("wavemap_local")] = 1
        group_cluster_counts[g] = 1
        print(f"  {g}: n={len(idx)} < {MIN_UNITS_TO_CLUSTER} -> kept as 1 class")
        continue
    reducer = umap.UMAP(
        n_neighbors=N_NEIGHBORS,
        min_dist=UMAP_MIN_DIST,
        n_components=2,
        metric="euclidean",
        random_state=RAND_STATE,
    )
    mapper = reducer.fit(Wg)
    emb = mapper.embedding_
    G = nx.from_scipy_sparse_array(mapper.graph_)
    RES_g, sweep_g = choose_resolution(G, seed=RAND_STATE)
    group_resolutions[g] = RES_g
    group_resolution_sweeps[g] = sweep_g
    part = community_louvain.best_partition(
        G, weight="weight", resolution=RES_g, random_state=RAND_STATE
    )
    group_graphs[g] = G
    local = np.array([part[i] for i in range(len(idx))], dtype=int) + 1
    units_df.iloc[idx, units_df.columns.get_loc("wavemap_local")] = local
    units_df.iloc[idx, units_df.columns.get_loc("umap_x")] = emb[:, 0]
    units_df.iloc[idx, units_df.columns.get_loc("umap_y")] = emb[:, 1]
    group_cluster_counts[g] = len(np.unique(local))
    group_embeddings[g] = (idx, emb)
    chosen_row = sweep_g.loc[sweep_g["res"].eq(RES_g)].iloc[0]
    print(
        f"  {g}: n={len(idx)} -> {group_cluster_counts[g]} clusters "
        f"(res={RES_g:g}, Q={chosen_row['modularity']:.3f}, "
        f"min cluster n={int(chosen_row['min_size'])})"
    )

clustered = units_df["wavemap_group"].notna()
pairs = list(
    units_df.loc[clustered, ["wavemap_group", "wavemap_local"]].itertuples(index=False, name=None)
)
uniq = sorted(set(pairs), key=lambda t: (t[0], t[1]))
gid = {p: i + 1 for i, p in enumerate(uniq)}
units_df["wavemap_class"] = -1
units_df.loc[clustered, "wavemap_class"] = [gid[p] for p in pairs]
units_df["wavemap_label"] = [
    f"{grp}-{int(loc)}" if grp is not None else "unclustered"
    for grp, loc in zip(units_df["wavemap_group"], units_df["wavemap_local"], strict=False)
]
n_unclustered = int((~clustered).sum())
print(f"\nTotal WaveMAP classes across groups: {len(uniq)}")
if n_unclustered:
    print(f"Units left unclustered (excluded/unmatched areas): {n_unclustered}")

assert sorted(units_df.loc[clustered, "wavemap_class"].unique()) == list(range(1, len(uniq) + 1))
assert (units_df.loc[clustered, "wavemap_local"] >= 1).all()

MERGE_WF_CORR = 0.95
MERGE_FEAT_DIST = 0.75
_FEAT_COLS = [
    c
    for c in ["firing_rate", "waveform_duration", "waveform_halfwidth", "snr", "amplitude"]
    if c in units_df.columns
]


def _merge_candidates(g):
    idx = np.where(units_df["wavemap_group"].values == g)[0]
    labs = units_df["wavemap_local"].values[idx]
    cls = sorted(np.unique(labs))
    if len(cls) < 2:
        return []
    wf_mean = {c: normWFs[idx][labs == c].mean(0) for c in cls}
    F = units_df.iloc[idx][_FEAT_COLS].apply(pd.to_numeric, errors="coerce")
    Fz = (F - F.mean()) / F.std(ddof=0).replace(0, np.nan)
    fmean = {c: np.nan_to_num(Fz.values[labs == c].mean(0)) for c in cls}
    out = []
    for i in range(len(cls)):
        for j in range(i + 1, len(cls)):
            a, b = cls[i], cls[j]
            corr = np.corrcoef(wf_mean[a], wf_mean[b])[0, 1]
            dist = np.linalg.norm(fmean[a] - fmean[b])
            if corr >= MERGE_WF_CORR and dist <= MERGE_FEAT_DIST:
                out.append((f"{g}-{a}", f"{g}-{b}", round(float(corr), 3), round(float(dist), 3)))
    return out


merge_rows = [r for g in group_cluster_counts for r in _merge_candidates(g)]
print(
    f"\nOPTIONAL diagnostic only — not used to alter WaveMAP labels. "
    f"Similar cluster pairs (wf_corr>={MERGE_WF_CORR}, "
    f"feat_dist<={MERGE_FEAT_DIST}, features={_FEAT_COLS}):"
)
if merge_rows:
    display(pd.DataFrame(merge_rows, columns=["class_a", "class_b", "wf_corr", "feat_dist"]))
    print(
        "-> inspect these pairs, but do not merge automatically; "
        "use the resolution sweep as the primary control."
    )
else:
    print("  none — clusters are distinct on shape+physiology at these thresholds.")

class_counts = units_df.loc[clustered, "wavemap_class"].value_counts().sort_index()
print("\nUnits per class:")
print(class_counts)


# ==================== ORIGINAL NOTEBOOK CELL 28 ====================
# ============================================================
# FIGURE SETUP — RUN ONCE
#
# CONSISTENT AREA-LOCAL WAVEMAP COLOURS
#
# A given local WaveMAP class keeps the same colour everywhere:
# UMAP, mean waveforms, legends, context plots and interactive figures.
#
# Colours are assigned within anatomical group rather than globally.
# Thus VIS-1 and MO-1 may reuse the same colour, which is appropriate
# because local classes are independently defined within each group.
# ============================================================

# Prerequisite: the WaveMAP clustering cell above must have been run.
_required_wavemap_cols = {
    "wavemap_group",
    "wavemap_local",
    "wavemap_class",
    "wavemap_label",
}
_missing_wavemap_cols = _required_wavemap_cols - set(units_df.columns)

if _missing_wavemap_cols:
    raise RuntimeError(
        "WaveMAP clustering has not been run yet. "
        "Run 'Per-area Louvain resolution selection' and then "
        "'Run WaveMAP PER FUNCTIONAL AREA-GROUP' before Figure Setup. "
        f"Missing columns: {sorted(_missing_wavemap_cols)}"
    )

from matplotlib.patches import Patch

CLASS_ORDER = sorted(units_df.loc[units_df["wavemap_class"] > 0, "wavemap_class"].unique())
N_CLASSES = len(CLASS_ORDER)

# ------------------------------------------------------------
# Qualitative palette
#
# <=10 classes/area: seaborn colourblind palette
# 11-20 classes/area: reordered tab20 for greater adjacent contrast
# >20 classes/area: tab20 + tab20b + tab20c
#
# Cluster colour is keyed by LOCAL class number, not by cluster size
# in an individual figure.
# ------------------------------------------------------------

_COLORBLIND10 = list(sns.color_palette("colorblind", 10))

_TAB20 = [plt.colormaps["tab20"](i) for i in range(20)]
_TAB20_REORDERED = [_TAB20[i] for i in list(range(0, 20, 2)) + list(range(1, 20, 2))]

_BIG_PALETTE = (
    _TAB20_REORDERED
    + [plt.colormaps["tab20b"](i) for i in range(20)]
    + [plt.colormaps["tab20c"](i) for i in range(20)]
)


def _cluster_palette(k):
    """Return k visually distinct categorical colours for one area."""

    if k <= 10:
        return _COLORBLIND10[:k]

    if k <= 20:
        return _TAB20_REORDERED[:k]

    if k <= len(_BIG_PALETTE):
        return _BIG_PALETTE[:k]

    raise ValueError(
        f"{k} clusters exceeds the {len(_BIG_PALETTE)}-colour palette. "
        "This is also a strong sign that the WaveMAP solution is oversplit."
    )


# ------------------------------------------------------------
# Fixed mapping: (functional group, local WaveMAP class) -> colour
# ------------------------------------------------------------

AREA_CLUSTER_COLORS = {}

_GROUP_ORDER_FOR_COLOURS = [
    g
    for g in ["MO", "PFC", "VIS", "STR", "HPC", "THAL"]
    if g in units_df["wavemap_group"].dropna().unique()
]

for g in _GROUP_ORDER_FOR_COLOURS:
    local_clusters = sorted(
        units_df.loc[
            (units_df["wavemap_group"] == g) & (units_df["wavemap_local"] > 0),
            "wavemap_local",
        ]
        .dropna()
        .astype(int)
        .unique()
    )

    palette = _cluster_palette(len(local_clusters))

    for local, colour in zip(local_clusters, palette, strict=False):
        AREA_CLUSTER_COLORS[(g, int(local))] = colour


# ------------------------------------------------------------
# Global class IDs remain useful downstream, but their colours are
# now derived from the fixed area-local mapping above.
# ------------------------------------------------------------

CLASS_LABEL = {}
CLASS_COLORS = {}

for cl in CLASS_ORDER:
    row = units_df.loc[units_df["wavemap_class"] == cl].iloc[0]

    group = row["wavemap_group"]
    local = int(row["wavemap_local"])

    if "wavemap_label" in units_df.columns:
        CLASS_LABEL[cl] = str(row["wavemap_label"])
    else:
        CLASS_LABEL[cl] = f"{group}-{local}"

    CLASS_COLORS[cl] = AREA_CLUSTER_COLORS[(group, local)]

# Backwards-compatible alias used by some downstream cells.
class_colors = CLASS_COLORS

CONTEXT_ORDER = list(CONTEXT_ORDER)

plt.rcParams.update(
    {
        "font.size": 10,
        "axes.titlesize": 12,
        "axes.labelsize": 11,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "legend.fontsize": 8,
        "figure.dpi": 150,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    }
)

CLASS_LEGEND = [
    Patch(
        facecolor=CLASS_COLORS[cl],
        edgecolor="none",
        label=CLASS_LABEL[cl],
    )
    for cl in CLASS_ORDER
]

print(
    f"Fixed area-local colour map created for {N_CLASSES} WaveMAP classes "
    f"across {len(_GROUP_ORDER_FOR_COLOURS)} functional groups."
)


# ==================== ORIGINAL NOTEBOOK CELL 43 ====================
# ============================================================
# FIGURE — Session-normalized WaveMAP composition by context
#            WITHIN each anatomical group
#
# Scientific question:
# Within a given anatomical population, do the four predictive
# contexts sample a comparable mixture of local waveform classes?
#
# Important:
# - WaveMAP classes were discovered independently by region.
# - Therefore context comparisons are performed WITHIN region.
# - Each recording session contributes equally.
# ============================================================

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ------------------------------------------------------------
# Settings
# ------------------------------------------------------------

GROUP_ORDER = ["MO", "PFC", "VIS", "STR", "HPC", "THAL"]
GROUP_ORDER = [g for g in GROUP_ORDER if g in group_embeddings]

GROUP_NAMES = {
    "MO": "Motor cortex",
    "PFC": "Prefrontal cortex",
    "VIS": "Visual cortex",
    "STR": "Striatum",
    "HPC": "Hippocampus",
    "THAL": "Thalamus",
}

# Shorter labels for manuscript figure
CONTEXT_SHORT = {
    "Standard oddball": "Standard",
    "Sensorimotor mismatch": "Sensorimotor",
    "Sequence mismatch": "Sequence",
    "Duration mismatch": "Duration",
}

context_order = [c for c in CONTEXT_ORDER if c in units_df["context"].dropna().unique()]

# ------------------------------------------------------------
# Figure styling
# ------------------------------------------------------------

plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.size": 9,
        "axes.titlesize": 10,
        "axes.labelsize": 9,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "figure.dpi": 150,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    }
)

TEXT_GREY = "#666666"

# Use one perceptually uniform sequential scale for all panels.
# Same limits across regions = values can be compared visually.
CMAP = mpl.colormaps["viridis"]


# ------------------------------------------------------------
# 1. Prepare a clean local-class dataframe
# ------------------------------------------------------------

required = [
    "session_key",
    "mouse_id",
    "context",
    "wavemap_group",
    "wavemap_local",
]

missing = [c for c in required if c not in units_df.columns]

if missing:
    raise KeyError(
        "Missing required columns: "
        + ", ".join(missing)
        + "\nRun Sarah's area-specific WaveMAP clustering cells first."
    )

ctx_df = units_df[required].copy()

ctx_df["wavemap_local"] = pd.to_numeric(ctx_df["wavemap_local"], errors="coerce")

ctx_df = ctx_df[
    ctx_df["wavemap_group"].isin(GROUP_ORDER)
    & ctx_df["wavemap_local"].notna()
    & (ctx_df["wavemap_local"] > 0)
    & ctx_df["context"].isin(context_order)
].copy()

ctx_df["wavemap_local"] = ctx_df["wavemap_local"].astype(int)

ctx_df["wavemap_label"] = ctx_df["wavemap_group"] + "-" + ctx_df["wavemap_local"].astype(str)


# ------------------------------------------------------------
# 2. Compute session-normalized proportions WITHIN region
#
# For a session s, region g and local class k:
#
#        N(s,g,k)
# p =  -----------
#        N(s,g)
#
# Thus every session contributes equally to each context.
# ------------------------------------------------------------

all_session_rows = []
summary_rows = []

for group in GROUP_ORDER:
    gdf = ctx_df[ctx_df["wavemap_group"] == group].copy()

    if len(gdf) == 0:
        continue

    local_classes = sorted(gdf["wavemap_local"].unique())

    # Sessions in which this region actually contributed units
    session_meta = gdf[["session_key", "mouse_id", "context"]].drop_duplicates()

    # observed counts
    counts = (
        gdf.groupby(["session_key", "mouse_id", "context", "wavemap_local"])
        .size()
        .rename("n_units")
        .reset_index()
    )

    # Fill missing local classes with zero inside every observed
    # session × region block.
    for row in session_meta.itertuples(index=False):
        sub = (
            counts[counts["session_key"] == row.session_key]
            .set_index("wavemap_local")["n_units"]
            .reindex(local_classes, fill_value=0)
        )

        total = int(sub.sum())

        if total == 0:
            continue

        tmp = pd.DataFrame(
            {
                "group": group,
                "session_key": row.session_key,
                "mouse_id": row.mouse_id,
                "context": row.context,
                "wavemap_local": local_classes,
                "n_units": sub.to_numpy(),
                "region_total": total,
                "class_proportion": sub.to_numpy() / total,
            }
        )

        tmp["wavemap_label"] = group + "-" + tmp["wavemap_local"].astype(str)

        all_session_rows.append(tmp)


region_session_prop = pd.concat(all_session_rows, ignore_index=True)


# ------------------------------------------------------------
# 3. Mean + SEM across sessions for each context
# ------------------------------------------------------------

region_context_summary = (
    region_session_prop.groupby(["group", "context", "wavemap_local", "wavemap_label"])[
        "class_proportion"
    ]
    .agg(mean="mean", std="std", n_sessions="count")
    .reset_index()
)

region_context_summary["sem"] = region_context_summary["std"] / np.sqrt(
    region_context_summary["n_sessions"]
)

region_context_summary["mean_percent"] = region_context_summary["mean"] * 100

region_context_summary["sem_percent"] = region_context_summary["sem"] * 100


# ------------------------------------------------------------
# 4. Build matrices for plotting
# ------------------------------------------------------------

matrices = {}

for group in GROUP_ORDER:
    sub = region_context_summary[region_context_summary["group"] == group].copy()

    if len(sub) == 0:
        continue

    local_order = sorted(sub["wavemap_local"].unique())

    matrix = sub.pivot(index="wavemap_local", columns="context", values="mean_percent").reindex(
        index=local_order, columns=context_order
    )

    matrix.index = [f"{group}-{int(x)}" for x in matrix.index]

    matrices[group] = matrix


# ------------------------------------------------------------
# 5. One GLOBAL colour scale
#
# Important for visual comparison between anatomical groups.
# Use a robust upper bound so a single dominant class doesn't
# flatten all remaining structure.
# ------------------------------------------------------------

all_vals = np.concatenate([m.to_numpy().ravel() for m in matrices.values()])

all_vals = all_vals[np.isfinite(all_vals)]

vmin = 0

# Robust high limit, while never clipping below the actual
# majority of values.
vmax = float(np.nanpercentile(all_vals, 97.5))

# Round to a clean number
vmax = max(5, np.ceil(vmax / 5) * 5)

print(f"Shared heatmap scale: {vmin:.0f}–{vmax:.0f}%")


# ------------------------------------------------------------
# 6. Plot six compact heatmaps
# ------------------------------------------------------------


# ==================== ORIGINAL NOTEBOOK CELL 45 ====================
# ============================================================
# FIGURE — Context enrichment / depletion of local WaveMAP
#          classes WITHIN anatomical region
#
# Uses:
#   region_session_prop
# generated by the previous figure cell.
#
# For each anatomical group + local WaveMAP class:
#
#   enrichment(context) =
#       mean session-normalized proportion in that context
#       --------------------------------------------------
#       mean session-normalized proportion across ALL contexts
#
# We plot log2 enrichment:
#
#   0   = exactly at regional baseline
#   +1  = 2x enriched
#   -1  = 2x depleted
#
# This is a descriptive sampling-composition analysis.
# ============================================================

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import TwoSlopeNorm

# ------------------------------------------------------------
# Settings
# ------------------------------------------------------------

GROUP_ORDER = ["MO", "PFC", "VIS", "STR", "HPC", "THAL"]
GROUP_ORDER = [g for g in GROUP_ORDER if g in region_session_prop["group"].unique()]

GROUP_NAMES = {
    "MO": "Motor cortex",
    "PFC": "Prefrontal cortex",
    "VIS": "Visual cortex",
    "STR": "Striatum",
    "HPC": "Hippocampus",
    "THAL": "Thalamus",
}

CONTEXT_SHORT = {
    "Standard oddball": "Standard",
    "Sensorimotor mismatch": "Sensorimotor",
    "Sequence mismatch": "Sequence",
    "Duration mismatch": "Duration",
}

context_order = [c for c in CONTEXT_ORDER if c in region_session_prop["context"].unique()]

TEXT_GREY = "#666666"

plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.size": 9,
        "axes.titlesize": 10,
        "axes.labelsize": 9,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "figure.dpi": 150,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    }
)


# ------------------------------------------------------------
# 1. Mean session-normalized proportion within each context
# ------------------------------------------------------------

ctx_mean = (
    region_session_prop.groupby(["group", "context", "wavemap_local", "wavemap_label"])[
        "class_proportion"
    ]
    .agg(mean_context="mean", n_sessions="count")
    .reset_index()
)


# ------------------------------------------------------------
# 2. Regional baseline for each local WaveMAP class
#
# Important:
# Baseline is calculated from SESSION-NORMALIZED proportions,
# not pooled unit counts.
#
# Every contributing session therefore remains one observation.
# ------------------------------------------------------------

baseline = (
    region_session_prop.groupby(["group", "wavemap_local", "wavemap_label"])["class_proportion"]
    .mean()
    .rename("regional_baseline")
    .reset_index()
)

enrich_df = ctx_mean.merge(baseline, on=["group", "wavemap_local", "wavemap_label"], how="left")


# ------------------------------------------------------------
# 3. Calculate relative enrichment
# ------------------------------------------------------------

# ratio >1 = enriched
# ratio <1 = depleted

enrich_df["fold_change"] = enrich_df["mean_context"] / enrich_df["regional_baseline"]

# Protect against exact zero values
EPS = 1e-9

enrich_df["log2_enrichment"] = np.log2(
    np.maximum(enrich_df["mean_context"], EPS) / np.maximum(enrich_df["regional_baseline"], EPS)
)

# Also keep intuitive percentage change for exported table
enrich_df["percent_change_from_baseline"] = (enrich_df["fold_change"] - 1) * 100


# ------------------------------------------------------------
# 4. Build matrices
# ------------------------------------------------------------

matrices = {}

for group in GROUP_ORDER:
    sub = enrich_df[enrich_df["group"] == group].copy()

    if len(sub) == 0:
        continue

    local_order = sorted(sub["wavemap_local"].unique())

    m = sub.pivot(index="wavemap_local", columns="context", values="log2_enrichment").reindex(
        index=local_order, columns=context_order
    )

    m.index = [f"{group}-{int(i)}" for i in m.index]

    matrices[group] = m


# ------------------------------------------------------------
# 5. Choose one symmetric colour range across ALL panels
#
# Robust percentile prevents one extreme sparse class from
# destroying contrast everywhere else.
# ------------------------------------------------------------

all_values = np.concatenate([m.to_numpy().ravel() for m in matrices.values()])

all_values = all_values[np.isfinite(all_values)]

robust_abs = np.nanpercentile(np.abs(all_values), 97.5)

# sensible lower limit so small differences don't look enormous
lim = max(0.5, robust_abs)

# keep visual scale reasonable
lim = min(lim, 2.0)

# round upward to nearest 0.25
lim = np.ceil(lim / 0.25) * 0.25

print(f"Shared log2 enrichment scale: {-lim:.2f} to +{lim:.2f}")


# ------------------------------------------------------------
# 6. Diverging colour map
#
# Blue = depleted
# White = baseline
# Red = enriched
#
# This is appropriate here because zero has a true meaning.
# ------------------------------------------------------------

CMAP = mpl.colormaps["RdBu_r"]

norm = TwoSlopeNorm(vmin=-lim, vcenter=0, vmax=lim)


# ------------------------------------------------------------
# 7. Plot
# ------------------------------------------------------------


# ==================== ORIGINAL NOTEBOOK CELL 48 ====================
# ============================================================
# SST OPTO-TAGGING CLASSIFIER — OpenScope P3
#
# Genotype / preparation:
#   Sst-IRES-Cre/wt;Ai32(RCL-ChR2(H134R)_EYFP)/wt
#
# The P3 optotagging cohort is SST-Ai32. There is NO PV
# optotagging in this dataset. Putative FS/PV-like cells are
# classified separately from extracellular waveform + firing rate.
#
# Protocol per session:
#   raised cosine: 150 x 1-s presentations
#   5-Hz train:    150 x 1-s presentations, 5 pulses/train = 750 pulses
#   40-Hz train:   150 x 1-s presentations, 40 pulses/train = 6000 pulses
#
# Positive SST optotagging call requires BOTH:
#   A) 0-3 ms pulse-locked activation vs matched -3-0 ms baseline
#      using 5-Hz + 40-Hz trains, statistics at PRESENTATION level
#   B) increased firing across full 1-s stimulus vs preceding 1-s baseline
#      using raised-cosine + 5-Hz + 40-Hz presentations
#
# Statistics:
#   one-sided paired Wilcoxon, stimulation > baseline
#   BH-FDR within session, q < 0.05 for BOTH A and B
#
# NOTE ON CACHE:
#   The legacy cache directory name is intentionally retained so
#   previously computed SST checkpoints can be resumed unchanged.
# ============================================================

import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

# ------------------------------------------------------------
# SETTINGS
# ------------------------------------------------------------

SHORT_LATENCY_S = 0.003
LATENCY_SEARCH_S = 0.010
FULL_STIM_S = 1.0
FULL_BASELINE_S = 1.0
FDR_Q = 0.05
ONLY_WAVEMAP_UNITS = True
DELETE_CACHE_AFTER_SUCCESS = True

# KEEP THIS CACHE PATH UNCHANGED.
OPTO_CACHE_DIR = Path(OUT_DIR) / "pv_sst_optotagging_three_stim_v2"
OPTO_CACHE_DIR.mkdir(parents=True, exist_ok=True)

SST_GENOTYPE = "Sst-IRES-Cre/wt;Ai32(RCL-ChR2(H134R)_EYFP)/wt"

# ============================================================
# BASIC HELPERS
# ============================================================


def _count_spikes_windows(spike_times, starts, width):
    """Count spikes in [start, start + width) for every start."""
    spike_times = np.asarray(spike_times, dtype=np.float64)
    starts = np.asarray(starts, dtype=np.float64)
    if len(starts) == 0 or len(spike_times) == 0:
        return np.zeros(len(starts), dtype=np.float64)
    left = np.searchsorted(spike_times, starts, side="left")
    right = np.searchsorted(spike_times, starts + width, side="left")
    return (right - left).astype(np.float64)


def _paired_greater_p(stim, baseline):
    """One-sided paired Wilcoxon: stimulation > baseline."""
    stim = np.asarray(stim, dtype=np.float64)
    baseline = np.asarray(baseline, dtype=np.float64)
    good = np.isfinite(stim) & np.isfinite(baseline)
    stim, baseline = stim[good], baseline[good]
    if len(stim) == 0:
        return 1.0
    diff = stim - baseline
    if not np.any(diff != 0):
        return 1.0
    try:
        return float(
            wilcoxon(
                stim,
                baseline,
                alternative="greater",
                zero_method="wilcox",
                method="auto",
            ).pvalue
        )
    except Exception:
        return np.nan


def _bh_qvalues(p_values):
    """Benjamini-Hochberg FDR q-values."""
    p = np.asarray(p_values, dtype=np.float64)
    q = np.full(p.shape, np.nan, dtype=np.float64)
    valid = np.isfinite(p)
    if not np.any(valid):
        return q
    pv = p[valid]
    order = np.argsort(pv)
    ranked = pv[order]
    m = len(ranked)
    q_sorted = ranked * m / np.arange(1, m + 1, dtype=np.float64)
    q_sorted = np.minimum.accumulate(q_sorted[::-1])[::-1]
    q_sorted = np.clip(q_sorted, 0.0, 1.0)
    q_valid = np.empty(m, dtype=np.float64)
    q_valid[order] = q_sorted
    q[valid] = q_valid
    return q


def _modulation_index(stim_rate, baseline_rate):
    denom = stim_rate + baseline_rate
    return float((stim_rate - baseline_rate) / denom) if denom > 0 else 0.0


def _median_first_spike_latency_ms(spike_times, pulse_starts, search_width=LATENCY_SEARCH_S):
    spike_times = np.asarray(spike_times, dtype=np.float64)
    pulse_starts = np.asarray(pulse_starts, dtype=np.float64)
    if len(spike_times) == 0 or len(pulse_starts) == 0:
        return np.nan, 0
    idx = np.searchsorted(spike_times, pulse_starts, side="left")
    valid = idx < len(spike_times)
    if not np.any(valid):
        return np.nan, 0
    pulse_idx = np.flatnonzero(valid)
    lat = spike_times[idx[pulse_idx]] - pulse_starts[pulse_idx]
    within = (lat >= 0) & (lat < search_width)
    if not np.any(within):
        return np.nan, 0
    vals = lat[within] * 1000.0
    return float(np.median(vals)), int(len(vals))


# ============================================================
# SUBJECT METADATA — retained for provenance only
# ============================================================


def _subject_text(nwb):
    vals = []
    subject = getattr(nwb, "subject", None)
    if subject is not None:
        for attr in [
            "genotype",
            "strain",
            "description",
            "subject_id",
            "species",
            "sex",
        ]:
            try:
                v = getattr(subject, attr, None)
                if v is not None:
                    vals.append(str(v))
            except Exception:
                pass
    for attr in ["experiment_description", "notes", "session_description"]:
        try:
            v = getattr(nwb, attr, None)
            if v is not None:
                vals.append(str(v))
        except Exception:
            pass
    return " | ".join(vals)


# ============================================================
# FIND THE THREE OPTO INTERVAL TABLES ROBUSTLY
# ============================================================


def _norm(s):
    return re.sub(r"[_\-]+", " ", str(s).lower()).strip()


def _kind_regex(kind):
    if kind == "raised":
        return re.compile(r"raised\s*cosine|cosine\s*ramp|raised.*cosine", re.I)
    if kind == "5hz":
        return re.compile(r"(?<!\d)5\s*hz", re.I)
    if kind == "40hz":
        return re.compile(r"(?<!\d)40\s*hz", re.I)
    raise ValueError(kind)


def _get_protocol_df(nwb, kind):
    """
    Return the presentation dataframe for one protocol block.
    First match interval-table names; then fall back to matching string
    values (e.g. a generic table with a condition column).
    """
    rx = _kind_regex(kind)

    # 1) Named interval table
    for name, table in nwb.intervals.items():
        n = _norm(name)
        if rx.search(n):
            if kind in {"5hz", "40hz"} and "pulse" not in n:
                continue
            try:
                df = table.to_dataframe().copy()
                if len(df):
                    return str(name), df
            except Exception:
                pass

    # 2) Generic interval table with condition/type values
    for name, table in nwb.intervals.items():
        try:
            df = table.to_dataframe().copy()
        except Exception:
            continue
        if len(df) == 0:
            continue
        str_cols = [
            c
            for c in df.columns
            if (pd.api.types.is_object_dtype(df[c]) or isinstance(df[c].dtype, pd.CategoricalDtype))
        ]
        if not str_cols:
            continue
        row_text = df[str_cols].astype(str).agg(" | ".join, axis=1)
        m = row_text.str.contains(rx, na=False)
        if m.any():
            return f"{name} [filtered]", df.loc[m].copy()

    return None, None


def _finite_starts(df):
    if df is None or "start_time" not in df.columns:
        return np.array([], dtype=np.float64)
    x = pd.to_numeric(df["start_time"], errors="coerce").to_numpy(dtype=np.float64)
    return x[np.isfinite(x)]


# ============================================================
# PRESENTATION-LEVEL SHORT-LATENCY METRICS
# ============================================================


def _early_rates_by_presentation(spike_times, starts, frequency_hz):
    """
    For each 1-s pulse-train presentation, collapse all 0-3 ms pulse
    windows into one rate. This prevents the 750/6000 individual pulses
    from being treated as independent statistical replicates.
    """
    starts = np.asarray(starts, dtype=np.float64)
    n_pulses = int(round(float(frequency_hz) * FULL_STIM_S))
    offsets = np.arange(n_pulses, dtype=np.float64) / float(frequency_hz)

    if len(starts) == 0:
        return (
            np.array([], dtype=np.float64),
            np.array([], dtype=np.float64),
            np.array([], dtype=np.float64),
            np.array([], dtype=np.float64),
        )

    pulse_matrix = starts[:, None] + offsets[None, :]
    pulse_starts = pulse_matrix.reshape(-1)

    stim_counts = _count_spikes_windows(spike_times, pulse_starts, SHORT_LATENCY_S).reshape(
        len(starts), n_pulses
    )

    baseline_counts = _count_spikes_windows(
        spike_times, pulse_starts - SHORT_LATENCY_S, SHORT_LATENCY_S
    ).reshape(len(starts), n_pulses)

    # Convert summed count per presentation to Hz within the total sampled
    # short-latency window time for that presentation.
    exposure = n_pulses * SHORT_LATENCY_S
    stim_rate = stim_counts.sum(axis=1) / exposure
    baseline_rate = baseline_counts.sum(axis=1) / exposure

    return stim_rate, baseline_rate, pulse_starts, stim_counts.reshape(-1)


# ============================================================
# ONE-UNIT SST OPTO-TAGGING CLASSIFIER
# ============================================================


def _classify_one_unit_opto(spike_times, raised_starts, hz5_starts, hz40_starts):
    # --------------------------------------------------------
    # A. Short-latency pulse response: 5 Hz + 40 Hz
    # --------------------------------------------------------
    r5, b5, pulses5, raw5 = _early_rates_by_presentation(spike_times, hz5_starts, 5.0)
    r40, b40, pulses40, raw40 = _early_rates_by_presentation(spike_times, hz40_starts, 40.0)

    early_rates = np.concatenate([r5, r40])
    early_baselines = np.concatenate([b5, b40])
    all_pulses = np.concatenate([pulses5, pulses40])

    early_p = _paired_greater_p(early_rates, early_baselines)
    early_rate_hz = float(np.mean(early_rates)) if len(early_rates) else np.nan
    early_baseline_rate_hz = float(np.mean(early_baselines)) if len(early_baselines) else np.nan
    early_mi = (
        _modulation_index(early_rate_hz, early_baseline_rate_hz)
        if np.isfinite(early_rate_hz) and np.isfinite(early_baseline_rate_hz)
        else np.nan
    )

    # Pulse-level response probability is descriptive only.
    pulse_counts = _count_spikes_windows(spike_times, all_pulses, SHORT_LATENCY_S)
    pulse_baseline_counts = _count_spikes_windows(
        spike_times, all_pulses - SHORT_LATENCY_S, SHORT_LATENCY_S
    )
    early_response_probability = float(np.mean(pulse_counts > 0)) if len(pulse_counts) else np.nan
    early_baseline_probability = (
        float(np.mean(pulse_baseline_counts > 0)) if len(pulse_baseline_counts) else np.nan
    )

    median_latency_ms, n_latency_pulses = _median_first_spike_latency_ms(
        spike_times, all_pulses, LATENCY_SEARCH_S
    )

    # --------------------------------------------------------
    # B. Full 1-s activation: raised cosine + 5 Hz + 40 Hz
    # --------------------------------------------------------
    full_starts = np.concatenate([raised_starts, hz5_starts, hz40_starts])
    full_counts = _count_spikes_windows(spike_times, full_starts, FULL_STIM_S)
    full_baseline_counts = _count_spikes_windows(
        spike_times, full_starts - FULL_BASELINE_S, FULL_BASELINE_S
    )

    full_p = _paired_greater_p(full_counts, full_baseline_counts)
    full_rate_hz = float(np.mean(full_counts) / FULL_STIM_S) if len(full_counts) else np.nan
    full_baseline_rate_hz = (
        float(np.mean(full_baseline_counts) / FULL_BASELINE_S)
        if len(full_baseline_counts)
        else np.nan
    )
    full_mi = (
        _modulation_index(full_rate_hz, full_baseline_rate_hz)
        if np.isfinite(full_rate_hz) and np.isfinite(full_baseline_rate_hz)
        else np.nan
    )

    # Block-specific full-epoch diagnostics (not part of final Boolean call).
    block_metrics = {}
    for label, starts in [
        ("raised", raised_starts),
        ("hz5", hz5_starts),
        ("hz40", hz40_starts),
    ]:
        c = _count_spikes_windows(spike_times, starts, FULL_STIM_S)
        b = _count_spikes_windows(spike_times, starts - FULL_BASELINE_S, FULL_BASELINE_S)
        block_metrics[f"{label}_full_rate_hz"] = (
            float(np.mean(c) / FULL_STIM_S) if len(c) else np.nan
        )
        block_metrics[f"{label}_baseline_rate_hz"] = (
            float(np.mean(b) / FULL_BASELINE_S) if len(b) else np.nan
        )
        block_metrics[f"{label}_full_p"] = _paired_greater_p(c, b)

    out = {
        "early_p": early_p,
        "early_rate_hz": early_rate_hz,
        "early_baseline_rate_hz": early_baseline_rate_hz,
        "early_modulation_index": early_mi,
        "early_response_probability": early_response_probability,
        "early_baseline_probability": early_baseline_probability,
        "full_p": full_p,
        "full_rate_hz": full_rate_hz,
        "full_baseline_rate_hz": full_baseline_rate_hz,
        "full_modulation_index": full_mi,
        "median_first_spike_latency_ms": median_latency_ms,
        "n_latency_pulses": n_latency_pulses,
        "n_raised_presentations": int(len(raised_starts)),
        "n_5hz_presentations": int(len(hz5_starts)),
        "n_40hz_presentations": int(len(hz40_starts)),
        "n_5hz_pulses": int(len(hz5_starts) * 5),
        "n_40hz_pulses": int(len(hz40_starts) * 40),
    }
    out.update(block_metrics)
    return out


# ============================================================
# SESSION INVENTORY / TARGET UNITS
# ============================================================

if ONLY_WAVEMAP_UNITS and "wavemap_group" in units_df.columns:
    opto_units = units_df.loc[units_df["wavemap_group"].notna()].copy()
else:
    opto_units = units_df.copy()

print(f"SST optotagging restricted to WaveMAP/UMAP units: {len(opto_units):,}/{len(units_df):,}")

if "session_inventory" in globals() and {"session_key", "filepath"}.issubset(
    session_inventory.columns
):
    _session_paths = session_inventory[["session_key", "filepath"]].drop_duplicates("session_key")
elif "all_units_df" in globals() and {"session_key", "filepath"}.issubset(all_units_df.columns):
    _session_paths = all_units_df[["session_key", "filepath"]].drop_duplicates("session_key")
else:
    raise RuntimeError("Need session_inventory or all_units_df with session_key + filepath.")

session_rows = (
    opto_units[["session_key"]]
    .drop_duplicates()
    .merge(_session_paths, on="session_key", how="left", validate="one_to_one")
)

print("Sessions to inspect:", len(session_rows))


# ============================================================
# RUN / RESUME SESSION BY SESSION
# ============================================================

all_session_results = []
skipped_sessions = []

for session_number, s in enumerate(session_rows.itertuples(index=False), start=1):
    session_t0 = time.perf_counter()
    session_key = s.session_key
    filepath = s.filepath

    if pd.isna(filepath):
        skipped_sessions.append({"session_key": session_key, "reason": "filepath_missing"})
        continue

    target_unit_ids = (
        pd.to_numeric(
            opto_units.loc[opto_units["session_key"].eq(session_key), "unit_id"],
            errors="coerce",
        )
        .dropna()
        .astype(np.int64)
        .unique()
    )
    if len(target_unit_ids) == 0:
        continue

    # Keep legacy local cache naming unchanged too.
    cache_dir = Path(LOCAL_CACHE_DIR) / f"pv_sst_opto_{session_key}"
    cache_dir.mkdir(parents=True, exist_ok=True)

    io = h5_file = remote_file = None
    session_success = False

    try:
        print(f"\n[{session_number:02d}/{len(session_rows):02d}] {session_key}")
        io, h5_file, remote_file = _open_dandi_nwb_cached(filepath, cache_dir)
        nwb = io.read()

        # All OpenScope P3 optotagging sessions are treated as SST-Ai32.
        cell_type = "SST"
        subject_meta = _subject_text(nwb)

        if "sst" not in subject_meta.lower() and "somatostatin" not in subject_meta.lower():
            print(
                "  note: NWB metadata does not explicitly contain 'SST'; "
                "session is still analysed as SST because this P3 cohort is SST-Ai32."
            )

        # IMPORTANT: preserve the exact SST checkpoint path used previously.
        type_dir = OPTO_CACHE_DIR / "SST"
        type_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = type_dir / f"{session_key}_sst_three_stim_optotagging.csv"

        if checkpoint.exists() and checkpoint.stat().st_size > 0:
            cached = pd.read_csv(checkpoint)

            # Backward compatibility with already-computed checkpoints.
            cached["cell_type"] = "SST"
            if "is_sst_optotagged" not in cached.columns and "is_optotagged" in cached.columns:
                cached["is_sst_optotagged"] = cached["is_optotagged"].fillna(False).astype(bool)

            all_session_results.append(cached)
            print(f"  [SST] resume: {len(cached)} units")
            session_success = True
            continue

        # ----------------------------------------------------
        # Locate all three protocol blocks
        # ----------------------------------------------------
        raised_name, raised_df = _get_protocol_df(nwb, "raised")
        hz5_name, hz5_df = _get_protocol_df(nwb, "5hz")
        hz40_name, hz40_df = _get_protocol_df(nwb, "40hz")

        missing_blocks = [
            label
            for label, df in [
                ("raised cosine", raised_df),
                ("5 Hz", hz5_df),
                ("40 Hz", hz40_df),
            ]
            if df is None or len(df) == 0
        ]
        if missing_blocks:
            print("  missing protocol block(s):", missing_blocks)
            print("  available interval tables:", list(nwb.intervals.keys()))
            skipped_sessions.append(
                {
                    "session_key": session_key,
                    "cell_type": "SST",
                    "reason": "missing_protocol_blocks: " + ", ".join(missing_blocks),
                }
            )
            session_success = True
            continue

        raised_starts = _finite_starts(raised_df)
        hz5_starts = _finite_starts(hz5_df)
        hz40_starts = _finite_starts(hz40_df)

        print(
            f"  [SST] protocol: "
            f"raised={len(raised_starts)} presentations; "
            f"5Hz={len(hz5_starts)} presentations/{len(hz5_starts) * 5} pulses; "
            f"40Hz={len(hz40_starts)} presentations/{len(hz40_starts) * 40} pulses"
        )
        print("  tables:", raised_name, "|", hz5_name, "|", hz40_name)

        # ----------------------------------------------------
        # Map requested unit IDs to NWB rows
        # ----------------------------------------------------
        nwb_unit_ids = np.asarray(nwb.units.id[:], dtype=np.int64)
        id_to_index = {int(uid): i for i, uid in enumerate(nwb_unit_ids)}
        matched_unit_ids = np.asarray(
            [int(uid) for uid in target_unit_ids if int(uid) in id_to_index],
            dtype=np.int64,
        )
        if len(matched_unit_ids) == 0:
            skipped_sessions.append(
                {
                    "session_key": session_key,
                    "cell_type": "SST",
                    "reason": "no_unit_matches",
                }
            )
            session_success = True
            continue
        matched_indices = np.asarray(
            [id_to_index[int(uid)] for uid in matched_unit_ids],
            dtype=np.int64,
        )

        # ----------------------------------------------------
        # Fast ragged spike-time bulk read (with safe fallback)
        # ----------------------------------------------------
        spike_index = nwb.units["spike_times"]
        spike_getter = None

        if hasattr(spike_index, "target"):
            stops = np.asarray(spike_index.data[:], dtype=np.int64)
            first_row = int(matched_indices.min())
            last_row = int(matched_indices.max())
            block_start = 0 if first_row == 0 else int(stops[first_row - 1])
            block_stop = int(stops[last_row])
            block = np.asarray(
                spike_index.target.data[block_start:block_stop],
                dtype=np.float64,
            )

            def spike_getter(unit_index, stops=stops, block=block, block_start=block_start):
                gs = 0 if unit_index == 0 else int(stops[unit_index - 1])
                ge = int(stops[unit_index])
                return block[(gs - block_start) : (ge - block_start)]
        else:

            def spike_getter(unit_index, nwb=nwb):
                return np.asarray(
                    nwb.units["spike_times"][unit_index],
                    dtype=np.float64,
                )

        # ----------------------------------------------------
        # Analyze units
        # ----------------------------------------------------
        rows = []

        for unit_id, unit_index in zip(matched_unit_ids, matched_indices, strict=False):
            spike_times = spike_getter(int(unit_index))

            result = _classify_one_unit_opto(
                spike_times,
                raised_starts,
                hz5_starts,
                hz40_starts,
            )

            result.update(
                {
                    "session_key": session_key,
                    "unit_id": int(unit_id),
                    "unit_uid": f"{session_key}_unit-{int(unit_id)}",
                    "cell_type": "SST",
                    "genotype": SST_GENOTYPE,
                    "subject_metadata": subject_meta,
                    "opto_tested": True,
                }
            )
            rows.append(result)

        session_df = pd.DataFrame(rows)

        if len(session_df) == 0:
            raise RuntimeError(f"No SST optotagging results generated for {session_key}")

        # ----------------------------------------------------
        # FDR within session
        # ----------------------------------------------------
        session_df["early_q"] = _bh_qvalues(session_df["early_p"].to_numpy())
        session_df["full_q"] = _bh_qvalues(session_df["full_p"].to_numpy())

        positive = (
            session_df["early_q"].lt(FDR_Q)
            & session_df["early_rate_hz"].gt(session_df["early_baseline_rate_hz"])
            & session_df["full_q"].lt(FDR_Q)
            & session_df["full_rate_hz"].gt(session_df["full_baseline_rate_hz"])
        )

        session_df["is_optotagged"] = positive
        session_df["is_sst_optotagged"] = positive

        session_df.to_csv(checkpoint, index=False)
        all_session_results.append(session_df)

        print(
            f"  optotagged SST: {int(positive.sum())}/{len(session_df)} "
            f"({100 * positive.mean():.2f}%)"
        )
        print(f"  total session: {time.perf_counter() - session_t0:.1f} s")
        session_success = True

        # free large arrays if bulk mode was used
        for nm in ["block", "stops"]:
            if nm in locals():
                try:
                    del locals()[nm]
                except Exception:
                    pass

    except Exception as exc:
        print(f"  ERROR {session_key}: {type(exc).__name__}: {exc}")
        skipped_sessions.append(
            {
                "session_key": session_key,
                "reason": f"{type(exc).__name__}: {exc}",
            }
        )

    finally:
        try:
            if io is not None:
                io.close()
        except Exception:
            pass
        try:
            if h5_file is not None:
                h5_file.close()
        except Exception:
            pass
        try:
            if remote_file is not None:
                remote_file.close()
        except Exception:
            pass
        if DELETE_CACHE_AFTER_SUCCESS and session_success:
            shutil.rmtree(cache_dir, ignore_errors=True)
        gc.collect()


# ============================================================
# COMBINE + EXPORT — SST ONLY
# ============================================================

if not all_session_results:
    # Resume entirely from the SAME legacy v2 cache, but only SST checkpoints.
    checkpoint_files = sorted(OPTO_CACHE_DIR.glob("SST/*_sst_three_stim_optotagging.csv"))
    all_session_results = [pd.read_csv(p) for p in checkpoint_files if p.stat().st_size > 0]

if not all_session_results:
    raise RuntimeError(
        "No SST optotagging results were produced. Inspect interval-table names printed above."
    )

sst_opto_df = pd.concat(all_session_results, ignore_index=True).drop_duplicates(
    "unit_uid", keep="last"
)

# Backward compatibility with old cached SST checkpoints.
sst_opto_df["cell_type"] = "SST"

if "is_sst_optotagged" not in sst_opto_df.columns:
    if "is_optotagged" not in sst_opto_df.columns:
        raise RuntimeError(
            "Cached SST results contain neither is_sst_optotagged nor is_optotagged."
        )
    sst_opto_df["is_sst_optotagged"] = sst_opto_df["is_optotagged"].fillna(False).astype(bool)

# Keep opto_all_df as a compatibility alias for downstream code,
# but it now contains SST optotagging results only.
opto_all_df = sst_opto_df.copy()

sst_csv = Path(OUT_DIR) / "SST_optotagging_unit_classification_v2.csv"
sst_opto_df.to_csv(sst_csv, index=False)

if skipped_sessions:
    pd.DataFrame(skipped_sessions).drop_duplicates(
        "session_key",
        keep="last",
    ).to_csv(
        Path(OUT_DIR) / "SST_optotagging_skipped_sessions_v2.csv",
        index=False,
    )

n_tested = len(sst_opto_df)
n_tagged = int(sst_opto_df["is_sst_optotagged"].sum())

print("\n" + "=" * 90)
print("SST OPTO-TAGGING SUMMARY")
print("=" * 90)
print(f"Genotype: {SST_GENOTYPE}")
print(f"Tested: {n_tested:,}")
print(
    f"Optotagged SST: {n_tagged:,} ({100 * n_tagged / n_tested:.2f}%)"
    if n_tested
    else "Optotagged SST: 0"
)
print("Cache retained at:", OPTO_CACHE_DIR)
print("Saved:", sst_csv)

_display_cols = [
    "unit_uid",
    "early_rate_hz",
    "early_baseline_rate_hz",
    "early_q",
    "early_response_probability",
    "median_first_spike_latency_ms",
    "full_rate_hz",
    "full_baseline_rate_hz",
    "full_q",
    "raised_full_rate_hz",
    "hz5_full_rate_hz",
    "hz40_full_rate_hz",
    "is_sst_optotagged",
]
_display_cols = [c for c in _display_cols if c in sst_opto_df.columns]

display(
    sst_opto_df[_display_cols]
    .sort_values(
        ["is_sst_optotagged", "early_q", "full_q"],
        ascending=[False, True, True],
    )
    .head(50)
)


# ==================== ORIGINAL NOTEBOOK CELL 50 ====================
# ============================================================
# PUTATIVE FS/PV-LIKE + OPTO-TAGGED SST IN WAVEMAP SPACE
#
# There is NO PV optotagging in this dataset.
#
# Putative FS/PV-like:
#   trough-to-peak waveform duration < 0.40 ms
#   AND firing rate >= 10 Hz
#
# Optotagged SST:
#   SST-Ai32 light-activated units from the classifier above.
#
# FIGURE:
#   Row 1 = all putative FS/PV-like cells        BLUE
#   Row 2 = all optotagged SST cells            MAGENTA
#   Row 3 = SST cells also meeting FS criterion ORANGE
#
# Rows 1 and 2 intentionally include overlap cells.
# Row 3 isolates the intersection.
# ============================================================

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

FS_T2P_MAX_MS = 0.40
FS_FR_MIN_HZ = 10.0

PV_COLOR = "#377EB8"  # blue
SST_COLOR = "#CC2F8A"  # magenta
OVERLAP_COLOR = "#F28E2B"  # orange
BACKGROUND_COLOR = "0.82"

BACKGROUND_ALPHA = 0.20
PV_ALPHA = 0.68
SST_ALPHA = 0.68
OVERLAP_ALPHA = 0.82

BACKGROUND_SIZE = 3.2
PV_SIZE = 27
SST_SIZE = 29
OVERLAP_SIZE = 34

GROUP_ORDER = [g for g in ["MO", "PFC", "VIS", "STR", "HPC", "THAL"] if g in group_embeddings]

GROUP_NAMES = {
    "MO": "Motor cortex",
    "PFC": "Prefrontal cortex",
    "VIS": "Visual cortex",
    "STR": "Striatum",
    "HPC": "Hippocampus",
    "THAL": "Thalamus",
}

# ============================================================
# 1. CHECK INPUTS
# ============================================================

if "units_df" not in globals():
    raise RuntimeError("units_df is not in memory.")
if "group_embeddings" not in globals():
    raise RuntimeError("group_embeddings is not in memory.")
if "sst_opto_df" not in globals():
    raise RuntimeError("sst_opto_df is not in memory. Run the SST optotagging cell first.")
if "unit_uid" not in sst_opto_df.columns:
    raise RuntimeError("sst_opto_df does not contain unit_uid.")
if "is_sst_optotagged" not in sst_opto_df.columns:
    raise RuntimeError("sst_opto_df does not contain is_sst_optotagged.")

# ============================================================
# 2. MASTER DATAFRAME + PUTATIVE FS CLASSIFICATION
# ============================================================

map_df = units_df.copy()

map_df["t2p_ms"] = pd.to_numeric(map_df["waveform_duration"], errors="coerce") * 1000.0
map_df["firing_rate_hz"] = pd.to_numeric(map_df["firing_rate"], errors="coerce")

map_df["putative_fs"] = map_df["t2p_ms"].lt(FS_T2P_MAX_MS) & map_df["firing_rate_hz"].ge(
    FS_FR_MIN_HZ
)

# ============================================================
# 3. ATTACH SST OPTO-TAGGING
# ============================================================

sst_lookup = sst_opto_df.drop_duplicates("unit_uid").set_index("unit_uid")

map_df["sst_opto_available"] = map_df["unit_uid"].isin(sst_lookup.index)
map_df["sst_optotagged"] = False

m = map_df["sst_opto_available"]

map_df.loc[m, "sst_optotagged"] = (
    map_df.loc[m, "unit_uid"].map(sst_lookup["is_sst_optotagged"]).fillna(False).astype(bool)
)

for c in [
    "early_rate_hz",
    "early_baseline_rate_hz",
    "early_q",
    "early_response_probability",
    "early_baseline_probability",
    "full_rate_hz",
    "full_baseline_rate_hz",
    "full_q",
    "median_first_spike_latency_ms",
    "raised_full_rate_hz",
    "hz5_full_rate_hz",
    "hz40_full_rate_hz",
]:
    if c in sst_lookup.columns:
        map_df[f"sst_{c}"] = map_df["unit_uid"].map(sst_lookup[c])

# ============================================================
# 4. OVERLAP / EXCLUSIVE GROUPS
# ============================================================

map_df["sst_fs_overlap"] = map_df["sst_optotagged"] & map_df["putative_fs"]

# Retained for the waveform-comparison cell below.
map_df["putative_fs_only"] = map_df["putative_fs"] & ~map_df["sst_optotagged"]
map_df["sst_only"] = map_df["sst_optotagged"] & ~map_df["putative_fs"]

# ============================================================
# 5. OVERALL SUMMARY
# ============================================================

n_total = len(map_df)
n_fs = int(map_df["putative_fs"].sum())
n_sst = int(map_df["sst_optotagged"].sum())
n_overlap = int(map_df["sst_fs_overlap"].sum())

print("\n" + "=" * 90)
print("PUTATIVE FS/PV-LIKE + OPTO-TAGGED SST")
print("=" * 90)
print(f"Total units: {n_total:,}")
print(
    f"Putative FS/PV-like "
    f"(t2p < {FS_T2P_MAX_MS:.2f} ms, FR >= {FS_FR_MIN_HZ:.1f} Hz): "
    f"{n_fs:,} ({100 * n_fs / n_total:.2f}%)"
)
print(f"Optotagged SST: {n_sst:,} ({100 * n_sst / n_total:.2f}%)")
if n_sst:
    print(f"SST ∩ FS: {n_overlap:,}/{n_sst:,} optotagged SST ({100 * n_overlap / n_sst:.2f}%)")

# ============================================================
# 6. REGIONAL SUMMARY
# ============================================================

summary_rows = []

for group in GROUP_ORDER:
    sub = map_df.loc[map_df["wavemap_group"].eq(group)]

    n_area = len(sub)
    n_fs_area = int(sub["putative_fs"].sum())
    n_sst_area = int(sub["sst_optotagged"].sum())
    n_overlap_area = int(sub["sst_fs_overlap"].sum())

    summary_rows.append(
        {
            "wavemap_group": group,
            "region": GROUP_NAMES.get(group, group),
            "n_units": n_area,
            "n_putative_fs": n_fs_area,
            "putative_fs_percent_all": (100 * n_fs_area / n_area if n_area else np.nan),
            "n_optotagged_sst": n_sst_area,
            "sst_percent_all": (100 * n_sst_area / n_area if n_area else np.nan),
            "n_sst_meeting_fs_criterion": n_overlap_area,
            "percent_sst_meeting_fs_criterion": (
                100 * n_overlap_area / n_sst_area if n_sst_area else np.nan
            ),
        }
    )

regional_summary = pd.DataFrame(summary_rows)

print("\nRegional summary:")
display(regional_summary.round(2))

# ============================================================
# 7. 3-ROW UMAP FIGURE
# ============================================================

ROW_INFO = [
    {
        "label": "Putative FS/PV-like",
        "mask_col": "putative_fs",
        "color": PV_COLOR,
        "alpha": PV_ALPHA,
        "size": PV_SIZE,
    },
    {
        "label": "Optotagged SST",
        "mask_col": "sst_optotagged",
        "color": SST_COLOR,
        "alpha": SST_ALPHA,
        "size": SST_SIZE,
    },
    {
        "label": "Overlap",
        "mask_col": "sst_fs_overlap",
        "color": OVERLAP_COLOR,
        "alpha": OVERLAP_ALPHA,
        "size": OVERLAP_SIZE,
    },
]

n_groups = len(GROUP_ORDER)


# ============================================================
# PUBLICATION INTERMEDIATE — deterministic JSON + provenance
# ============================================================
import datetime as _dt
import hashlib as _hashlib

PUBLICATION_SNAPSHOT = PUBLICATION_DATA_DIR / "wavemap-analysis.json.gz"
PUBLICATION_PROVENANCE = PUBLICATION_DATA_DIR / "wavemap-analysis.provenance.json"

_snapshot_names = [
    "units_df",
    "normWFs",
    "group_embeddings",
    "CLASS_COLORS",
    "AREA_CLUSTER_COLORS",
    "map_df",
    "sst_opto_df",
    "region_context_summary",
    "enrich_df",
    "WAVEFORM_SAMPLING_RATE",
    "WF_SAMPLING_RATE",
    "CONTEXT_ORDER",
]
_snapshot = {name: globals()[name] for name in _snapshot_names if name in globals()}
_required_snapshot = {
    "units_df",
    "normWFs",
    "group_embeddings",
    "CLASS_COLORS",
    "map_df",
    "region_context_summary",
    "enrich_df",
}
_missing_snapshot = sorted(_required_snapshot - set(_snapshot))
if _missing_snapshot:
    raise RuntimeError(
        "Cannot write publication snapshot; missing required object(s): "
        + ", ".join(_missing_snapshot)
    )


def _json_scalar(value):
    if value is None:
        return None
    if isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return value


def _encode_publication(value):
    if isinstance(value, pd.DataFrame):
        records = []
        for row in value.to_dict(orient="records"):
            records.append({str(k): _encode_publication(v) for k, v in row.items()})
        return {
            "__type__": "dataframe",
            "columns": list(map(str, value.columns)),
            "records": records,
        }
    if isinstance(value, pd.Series):
        return {
            "__type__": "series",
            "name": value.name,
            "values": [_encode_publication(v) for v in value.tolist()],
        }
    if isinstance(value, np.ndarray):
        return {
            "__type__": "ndarray",
            "dtype": str(value.dtype),
            "shape": list(value.shape),
            "data": [_encode_publication(v) for v in value.tolist()],
        }
    if isinstance(value, tuple):
        return {"__type__": "tuple", "items": [_encode_publication(v) for v in value]}
    if isinstance(value, list):
        return [_encode_publication(v) for v in value]
    if isinstance(value, dict):
        # JSON object keys must be strings; preserve arbitrary keys explicitly.
        return {
            "__type__": "mapping",
            "items": [[_encode_publication(k), _encode_publication(v)] for k, v in value.items()],
        }
    scalar = _json_scalar(value)
    if scalar is value and not isinstance(value, (type(None), bool, str, int, float)):
        return str(value)
    return scalar


_payload = {
    "format": "openscope-p3-wavemap-publication-snapshot-v1",
    "objects": {name: _encode_publication(value) for name, value in _snapshot.items()},
}

_json_bytes = json.dumps(
    _payload,
    ensure_ascii=False,
    allow_nan=False,
    separators=(",", ":"),
    sort_keys=True,
).encode("utf-8")

with PUBLICATION_SNAPSHOT.open("wb") as _raw_f:
    with gzip.GzipFile(fileobj=_raw_f, mode="wb", compresslevel=9, mtime=0) as _f:
        _f.write(_json_bytes)

_snapshot_sha256 = _hashlib.sha256(PUBLICATION_SNAPSHOT.read_bytes()).hexdigest()

_asset_records = []
for _row in session_inventory.itertuples(index=False):
    _asset_records.append(
        {
            "session_key": str(_row.session_key),
            "context": str(_row.context),
            "asset_id": str(_row.asset_id),
            "path": str(_row.filepath),
            "size_bytes": int(_row.asset_size_bytes),
        }
    )

_provenance = {
    "snapshot": PUBLICATION_SNAPSHOT.name,
    "snapshot_sha256": _snapshot_sha256,
    "generated_utc": _dt.datetime.now(_dt.UTC).isoformat(),
    "source": {
        "archive": "DANDI",
        "dandiset_id": DANDISET_ID,
        "version": "draft",
        "assets": _asset_records,
    },
    "analysis": {
        "checkpoint_version": CHECKPOINT_VERSION,
        "random_seed": RAND_STATE,
        "qc": {k: globals().get(k) for k in _QC_DEFAULTS},
        "note": (
            "Scientific calculations follow the contributed notebook analysis; "
            "this block serializes its final figure inputs."
        ),
    },
}
PUBLICATION_PROVENANCE.write_text(
    json.dumps(_provenance, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)

print(f"Saved publication intermediate: {PUBLICATION_SNAPSHOT}")
print(f"Saved provenance: {PUBLICATION_PROVENANCE}")
print(f"Snapshot SHA256: {_snapshot_sha256}")
