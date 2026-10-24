import argparse
import base64
import gc
import gzip
import hashlib
import json
import os
import pickle
import re
from collections import defaultdict
from datetime import UTC, datetime

import numpy as np
import pandas as pd

try:
    import h5py
    import remfile
    from dandi.dandiapi import DandiAPIClient
    from pynwb import NWBHDF5IO
    from scipy.ndimage import gaussian_filter1d
    from scipy.signal import welch
except ImportError:
    h5py = None
    remfile = None
    DandiAPIClient = None
    NWBHDF5IO = None
    gaussian_filter1d = None
    welch = None

# ==========================================
# CONFIGURATION & CONSTANTS
# ==========================================
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "figure_sources", "data")
OUTPUT_JSON = os.path.join(DATA_DIR, "ecephys-qc-dashboard.json.gz")
PROV_JSON = os.path.join(DATA_DIR, "ecephys-qc-dashboard.provenance.json")

UNIT_META_COLS = [
    "session_key",
    "mouse_id",
    "cohort",
    "context",
    "session_stage",
    "probe",
    "area",
    "major_division",
    "region_group",
    "area_family",
    "subarea",
    "layer",
    "layer_or_compartment",
    "anatomy_class",
]

UNIT_METRIC_ROUND_SPECS = {
    "amplitude_cutoff": 5,
    "isi_violations_ratio": 5,
    "presence_ratio": 4,
    "snr": 3,
    "firing_rate": 3,
    "isolation_distance": 2,
    "d_prime": 3,
    "silhouette": 4,
    "l_ratio": 5,
    "amplitude": 2,
    "half_width": 5,
    "peak_to_valley": 5,
    "repolarization_slope": 2,
    "drift_ptp": 3,
    "drift_std": 3,
    "amplitude_cv_median": 4,
    "depth_from_cortex_um": 2,
    "depth_from_l1_l23_um": 2,
    "estimated_y": 2,
}

VALID_PROBES = ["ProbeA", "ProbeB", "ProbeC", "ProbeD", "ProbeE", "ProbeF"]
NON_ANATOMICAL_LABELS = {
    "",
    "void",
    "root",
    "none",
    "nan",
    "unknown",
    "unlabeled",
    "unlabelled",
    "n/a",
    "na",
    "null",
}
_HIPPO_COMPARTMENTS = {"so": "SO", "sp": "SP", "sr": "SR", "slm": "SLM"}

STATIC_CSD_PRE_MS = 100
STATIC_CSD_POST_MS = 300
STATIC_CSD_BASELINE_MS = 100
STATIC_CSD_MAX_TRIALS_PER_CONDITION = 100
STATIC_CSD_RANDOM_SEED = 20260911
STATIC_CSD_SPATIAL_SIGMA_UM = 40.0
STATIC_CSD_TEMPORAL_SIGMA_MS = 2.0
STATIC_CSD_DISPLAY_DT_MS = 5.0
STATIC_CSD_MAX_DEPTH_ROWS = 64
STATIC_CSD_TARGET_TABLE = "Standard mismatch block_presentations"
STATIC_CSD_TARGET_GROUP = "TrialType"
STATIC_CSD_TARGET_CONDITION = "standard"
STATIC_CSD_TARGET_CONTEXT = "STANDARD"

STATIC_PSD_N_WINDOWS = 8
STATIC_PSD_WINDOW_SECONDS = 8.0
STATIC_PSD_WELCH_SECONDS = 2.0
STATIC_PSD_WELCH_OVERLAP = 0.50
STATIC_PSD_FMIN = 1.0
STATIC_PSD_FMAX = 200.0
STATIC_PSD_FREQ_STEP = 1.0
STATIC_PSD_MAX_DEPTH_ROWS = 64

STATIC_PSD_BANDS = {
    "Delta 1–4 Hz": (1.0, 4.0),
    "Theta 4–12 Hz": (4.0, 12.0),
    "Hipp theta 6–10 Hz": (6.0, 10.0),
    "Beta 12–30 Hz": (12.0, 30.0),
    "Low gamma 30–55 Hz": (30.0, 55.0),
    "High-frequency activity 65–100 Hz": (65.0, 100.0),
    "Ripple 120–200 Hz": (120.0, 200.0),
}

SESSION_DESIGN = {
    "Motor": {
        "SENSORYMOTOR": [
            "820454_2025-11-04",
            "820459_2025-11-10",
            "830794_2026-01-26",
            "830795_2026-02-23",
            "830851_2026-03-16",
            "830852_2026-02-23",
            "834691_2026-02-16",
            "848387_2026-05-04",
            "848390_2026-05-04",
        ],
        "STANDARD": [
            "820454_2025-11-05",
            "830794_2026-01-27",
            "830795_2026-02-24",
            "830852_2026-02-24",
            "834691_2026-02-17",
            "830851_2026-03-17",
            "848387_2026-05-05",
            "848390_2026-05-05",
        ],
        "SEQUENCE": [
            "820454_2025-11-06",
            "820459_2025-11-12",
            "830794_2026-01-28",
            "830795_2026-02-25",
            "830851_2026-03-18",
            "830852_2026-02-25",
            "848387_2026-05-06",
            "848390_2026-05-06",
        ],
        "DURATION": [
            "820454_2025-11-07",
            "830794_2026-01-29",
            "830795_2026-02-26",
            "830851_2026-03-19",
            "830852_2026-02-26",
            "848387_2026-05-07",
            "848390_2026-05-07",
        ],
    },
    "Sequence": {
        "SEQUENCE": [
            "830846_2026-03-09",
            "830847_2026-03-09",
            "830848_2026-03-02",
            "830849_2026-03-04",
            "832691_2026-03-23",
            "834686_2026-03-23",
            "834687_2026-03-16",
        ],
        "DURATION": [
            "830846_2026-03-10",
            "830847_2026-03-10",
            "830848_2026-03-03",
            "830849_2026-03-05",
            "832691_2026-03-24",
            "834686_2026-03-24",
            "834687_2026-03-17",
        ],
        "STANDARD": [
            "830846_2026-03-11",
            "830847_2026-03-11",
            "830848_2026-03-04",
            "830849_2026-03-06",
            "834686_2026-03-25",
            "834687_2026-03-18",
        ],
        "SENSORYMOTOR": [
            "830846_2026-03-12",
            "830847_2026-03-12",
            "830848_2026-03-05",
            "830849_2026-03-07",
            "832691_2026-03-26",
            "834686_2026-03-26",
            "834687_2026-03-19",
        ],
    },
}


# ==========================================
# HELPER FUNCTIONS
# ==========================================
def sanitize_for_json(obj):
    if isinstance(obj, (float, np.floating)):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return float(obj)
    elif isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple, np.ndarray)):
        return [sanitize_for_json(v) for v in obj]
    return obj


def _decode_text(x):
    if x is None:
        return None
    if isinstance(x, bytes):
        return x.decode("utf-8", errors="replace")
    if isinstance(x, np.bytes_):
        return bytes(x).decode("utf-8", errors="replace")
    return str(x)


def _normalize_probe(raw_probe):
    text = _decode_text(raw_probe)
    if text is None:
        return None
    match = re.search(r"[Pp]robe[ _]?([A-Fa-f])", text)
    return f"Probe{match.group(1).upper()}" if match else text.strip()


def _clean_area_label(x):
    if x is None:
        return None
    text = _decode_text(x).strip()
    if text.lower() in NON_ANATOMICAL_LABELS:
        return None
    return text


def _anatomy_path(parts):
    clean = []
    for p in parts:
        if p is None:
            continue
        p = str(p).strip()
        if not p:
            continue
        if not clean or clean[-1] != p:
            clean.append(p)
    return " → ".join(clean)


def _parse_ccf_hierarchy(label):
    acronym = _clean_area_label(label)
    empty = {
        "ccf_acronym": None,
        "major_division": None,
        "region_group": None,
        "area_family": None,
        "subarea": None,
        "layer": None,
        "compartment": None,
        "layer_or_compartment": None,
        "anatomy_class": None,
        "anatomy_path": None,
        "hierarchy_label": None,
        "region_family": None,
        "subregion": None,
    }
    if acronym is None:
        return empty

    for field in ("CA1", "CA2", "CA3"):
        if acronym.startswith(field):
            suffix = acronym[len(field) :].strip().lower()
            compartment = _HIPPO_COMPARTMENTS.get(suffix)
            path = _anatomy_path(
                ["Hippocampal formation", "Hippocampus", "Hippocampus", field, compartment]
            )
            return {
                **empty,
                "ccf_acronym": acronym,
                "major_division": "Hippocampal formation",
                "region_group": "Hippocampus",
                "area_family": "Hippocampus",
                "subarea": field,
                "compartment": compartment,
                "layer_or_compartment": compartment,
                "anatomy_class": "hippocampal_subfield",
                "anatomy_path": path,
                "hierarchy_label": path,
                "region_family": "Hippocampus",
                "subregion": field,
            }

    if acronym.startswith("DG"):
        path = _anatomy_path(["Hippocampal formation", "Dentate gyrus", "DG", acronym])
        return {
            **empty,
            "ccf_acronym": acronym,
            "major_division": "Hippocampal formation",
            "region_group": "Dentate gyrus",
            "area_family": "DG",
            "subarea": acronym,
            "anatomy_class": "hippocampal_formation",
            "anatomy_path": path,
            "hierarchy_label": path,
            "region_family": "DG",
            "subregion": acronym,
        }

    if acronym.startswith(("SUB", "POST", "PRE", "ProS")):
        stem0 = re.sub(r"(2/3|6a|6b|1|2|3|4|5)$", "", acronym, flags=re.IGNORECASE)
        path = _anatomy_path(["Hippocampal formation", "Subicular complex", stem0, acronym])
        return {
            **empty,
            "ccf_acronym": acronym,
            "major_division": "Hippocampal formation",
            "region_group": "Subicular complex",
            "area_family": stem0,
            "subarea": stem0,
            "anatomy_class": "hippocampal_formation",
            "anatomy_path": path,
            "hierarchy_label": path,
            "region_family": stem0,
            "subregion": stem0,
        }

    m = re.search(r"(2/3|6a|6b|1|2|3|4|5)$", acronym, flags=re.IGNORECASE)
    layer = None
    stem = acronym
    if m is not None:
        layer = m.group(1)
        if layer.lower() in {"6a", "6b"}:
            layer = layer.lower()
        stem = acronym[: m.start()]

    major_division = "Other / unclassified"
    region_group = "Other / unclassified"
    area_family = subarea = stem
    anatomy_class = "region"

    if stem.startswith("VIS"):
        major_division, region_group, anatomy_class = "Isocortex", "Visual cortex", "cortical"
    elif stem.startswith("MOp"):
        major_division, region_group, anatomy_class = "Isocortex", "Motor cortex", "cortical"
    elif stem.startswith("MOs"):
        major_division, region_group, anatomy_class = "Isocortex", "Motor cortex", "cortical"
    elif stem.startswith("ACA"):
        major_division, region_group, anatomy_class = (
            "Isocortex",
            "Medial frontal cortex",
            "cortical",
        )
    elif stem.startswith("PL"):
        major_division, region_group, anatomy_class = (
            "Isocortex",
            "Medial frontal cortex",
            "cortical",
        )
    elif stem.startswith("ILA"):
        major_division, region_group, anatomy_class = (
            "Isocortex",
            "Medial frontal cortex",
            "cortical",
        )
    elif stem.startswith("RSP"):
        major_division, region_group, anatomy_class = (
            "Isocortex",
            "Retrosplenial cortex",
            "cortical",
        )
    elif stem.startswith("SS"):
        major_division, region_group, anatomy_class = (
            "Isocortex",
            "Somatosensory cortex",
            "cortical",
        )
    elif stem.startswith("AUD"):
        major_division, region_group, anatomy_class = "Isocortex", "Auditory cortex", "cortical"
    elif stem.startswith(
        ("LGd", "LP", "PO", "VAL", "RT", "AM", "AV", "AD", "MD", "LD", "CL", "VM", "VL", "TH")
    ) or stem in {
        "SMT",
        "PR",
        "RE",
        "RH",
        "CM",
        "PVT",
        "PT",
        "PCN",
        "PF",
        "PIL",
        "PP",
        "MG",
        "SPA",
        "SPF",
        "POL",
        "Eth",
        "LH",
        "MH",
    }:
        major_division, region_group, anatomy_class, layer = (
            "Thalamus",
            "Thalamus",
            "thalamic",
            None,
        )
    elif stem.startswith("LS"):
        major_division, region_group, anatomy_class, layer = (
            "Cerebral nuclei",
            "Septum",
            "septal",
            None,
        )
    elif stem == "CP" or stem.startswith("CP"):
        major_division, region_group, anatomy_class, layer = (
            "Basal ganglia",
            "Striatum",
            "striatal",
            None,
        )

    layer_or_compartment = layer if anatomy_class == "cortical" else None
    layer_text = f"L{layer}" if layer is not None else None
    path = _anatomy_path([major_division, region_group, area_family, subarea, layer_text])

    return {
        "ccf_acronym": acronym,
        "major_division": major_division,
        "region_group": region_group,
        "area_family": area_family,
        "subarea": subarea,
        "layer": layer,
        "compartment": None,
        "layer_or_compartment": layer_or_compartment,
        "anatomy_class": anatomy_class,
        "anatomy_path": path,
        "hierarchy_label": path,
        "region_family": area_family,
        "subregion": subarea,
    }


def _annotate_anatomy_columns(df):
    if len(df) == 0:
        return df.copy()
    out = df.copy()
    parsed_by_area = {
        area: _parse_ccf_hierarchy(area) for area in out["area"].dropna().astype(str).unique()
    }
    hierarchy_cols = [
        "ccf_acronym",
        "major_division",
        "region_group",
        "area_family",
        "subarea",
        "layer",
        "compartment",
        "layer_or_compartment",
        "anatomy_class",
        "anatomy_path",
        "hierarchy_label",
        "region_family",
        "subregion",
    ]
    for col in hierarchy_cols:
        out[col] = out["area"].map(
            lambda x, target_col=col: parsed_by_area.get(str(x), _parse_ccf_hierarchy(x)).get(
                target_col
            )
        )
    return out


# ==========================================
# DATA EXTRACTION LOGIC
# ==========================================
class _StaticRemoteNWB:
    def __init__(self):
        self.rf = self.h5 = self.io = self.nwb = None
        self.info = None

    def close(self):
        for obj in [self.io, self.h5, self.rf]:
            try:
                if obj is not None:
                    obj.close()
            except Exception:
                pass
        self.rf = self.h5 = self.io = self.nwb = None
        self.info = None
        gc.collect()

    def open(self, session_info):
        self.close()
        self.rf = remfile.File(session_info["url"])
        self.h5 = h5py.File(self.rf, "r")
        self.io = NWBHDF5IO(file=self.h5, mode="r", load_namespaces=True)
        self.nwb = self.io.read()
        self.info = dict(session_info)
        return self.nwb


_STATIC_REMOTE = _StaticRemoteNWB()


def _extract_units_from_nwb(nwb, session_info):
    if nwb.units is None:
        return pd.DataFrame()
    units_df = nwb.units.to_dataframe().reset_index()

    # Bin spike times into 90 1-minute bins for active units (>=0.05 Hz)
    minute_bins = np.arange(0, 90 * 60 + 1, 60.0)
    time_series_list = []
    has_spikes = "spike_times" in units_df.columns
    for _, row in units_df.iterrows():
        st = row.get("spike_times") if has_spikes else None
        fr = row.get("firing_rate", 1.0)
        if st is not None and len(st) > 0 and (fr is None or fr >= 0.05):
            counts, _ = np.histogram(st, bins=minute_bins)
            time_series_list.append(np.round(counts / 60.0, 2).tolist())
        else:
            time_series_list.append(None)
    units_df["fr_time_series"] = time_series_list

    # --- CRITICAL FIX: Drop live file pointers before saving to cache ---
    cols_to_drop = [
        "electrode_group",
        "electrodes",
        "spike_times",
        "waveform_mean",
        "waveform_sd",
        "waveforms",
    ]
    for col in cols_to_drop:
        if col in units_df.columns:
            units_df.drop(columns=[col], inplace=True)
    # --------------------------------------------------------------------

    elec_df = nwb.electrodes.to_dataframe().reset_index()

    probe_list, area_list, depth_list = [], [], []
    for _, row in units_df.iterrows():
        dev_name = row.get("device_name", "")
        if pd.isna(dev_name):
            dev_name = ""
        probe = _normalize_probe(dev_name)
        probe_list.append(probe)

        ch_idx = row.get("extremum_channel_index", -1)
        if not pd.isna(ch_idx) and ch_idx >= 0 and ch_idx < len(elec_df):
            loc = elec_df["location"].iloc[int(ch_idx)]
            ry = elec_df.get(
                "rel_y", elec_df.get("probe_vertical_position", pd.Series([np.nan] * len(elec_df)))
            ).iloc[int(ch_idx)]
            area_list.append(_clean_area_label(loc))
            depth_list.append(float(ry))
        else:
            area_list.append(None)
            depth_list.append(np.nan)

    units_df["probe"] = probe_list
    units_df["area"] = area_list
    units_df["depth"] = depth_list
    for k in ["session_key", "mouse_id", "cohort", "context", "session_stage"]:
        units_df[k] = session_info[k]

    return units_df


def _stream_probe_anatomy_metadata(nwb):
    et = nwb.electrodes
    if et is None:
        return {}, []
    channel_names = np.asarray(et["channel_name"][:], dtype=object)
    group_names = np.asarray(et["group_name"][:], dtype=object)
    locations = np.asarray(et["location"][:], dtype=object)

    if "rel_y" in et.colnames:
        local_depths = np.asarray(et["rel_y"][:], dtype=float)
    else:
        local_depths = np.full(len(channel_names), np.nan, dtype=float)
        for i, ch in enumerate(channel_names):
            text = str(ch)
            m = re.search(r"AP(\d+)", text)
            if m:
                local_depths[i] = (int(m.group(1)) // 2) * 20.0

    rows = []
    by_probe = defaultdict(list)
    for group, location, depth_um in zip(group_names, locations, local_depths, strict=False):
        probe = _normalize_probe(group)
        area = _clean_area_label(location)
        if probe not in VALID_PROBES or area is None or not np.isfinite(depth_um):
            continue
        rows.append({"probe": probe, "depth_um": float(depth_um), "area": area})
        by_probe[probe].append(float(depth_um))

    surface_lookup = {
        probe: float(np.max(depths)) for probe, depths in by_probe.items() if len(depths)
    }
    boundary_records = []

    if rows:
        e_df = pd.DataFrame(rows)
        for probe, p_df in e_df.groupby("probe", sort=True):
            collapsed = []
            for depth_um, d_df in p_df.groupby("depth_um", sort=True):
                labels = d_df["area"].dropna().astype(str)
                if len(labels) == 0:
                    continue
                modes = labels.mode()
                area = sorted(modes.astype(str).tolist())[0] if len(modes) else labels.iloc[0]
                parsed = _parse_ccf_hierarchy(area)
                collapsed.append({"depth_um": float(depth_um), "area": area, **parsed})

            if not collapsed:
                continue
            collapsed = sorted(collapsed, key=lambda r: r["depth_um"])

            def boundary_key(r):
                if r.get("layer") is not None:
                    return (r.get("region_family"), r.get("subregion"), r.get("layer"))
                if r.get("region_family") == "Hippocampus":
                    return ("Hippocampus", r.get("subregion"))
                return (r.get("region_family"), r.get("subregion"))

            prev = collapsed[0]
            prev_key = boundary_key(prev)
            for curr in collapsed[1:]:
                curr_key = boundary_key(curr)
                if curr_key != prev_key:
                    depth_mid = (float(prev["depth_um"]) + float(curr["depth_um"])) / 2.0
                    if (
                        prev.get("subregion") == curr.get("subregion")
                        and prev.get("layer") is not None
                        and curr.get("layer") is not None
                    ):
                        boundary_type = "layer"
                        label = f"L{prev['layer']} / L{curr['layer']}"
                    elif (
                        prev.get("region_family") == "Hippocampus"
                        and curr.get("region_family") == "Hippocampus"
                        and prev.get("subregion") != curr.get("subregion")
                    ):
                        boundary_type = "hippocampal_subfield"
                        label = f"{prev['subregion']} / {curr['subregion']}"
                    else:
                        boundary_type = "region"
                        label = f"{prev.get('hierarchy_label')} / {curr.get('hierarchy_label')}"

                    boundary_records.append(
                        {
                            "probe": probe,
                            "depth_um": depth_mid,
                            "boundary_type": boundary_type,
                            "boundary_label": label,
                            "from_area": prev.get("area"),
                            "to_area": curr.get("area"),
                            "from_major_division": prev.get("major_division"),
                            "to_major_division": curr.get("major_division"),
                            "from_region_group": prev.get("region_group"),
                            "to_region_group": curr.get("region_group"),
                            "from_area_family": prev.get("area_family"),
                            "to_area_family": curr.get("area_family"),
                            "from_subarea": prev.get("subarea"),
                            "to_subarea": curr.get("subarea"),
                            "from_compartment": prev.get("compartment"),
                            "to_compartment": curr.get("compartment"),
                            "from_region_family": prev.get("region_family"),
                            "to_region_family": curr.get("region_family"),
                            "from_subregion": prev.get("subregion"),
                            "to_subregion": curr.get("subregion"),
                            "from_layer": prev.get("layer"),
                            "to_layer": curr.get("layer"),
                        }
                    )
                    prev = curr
                    prev_key = curr_key
                else:
                    prev = curr
    return surface_lookup, boundary_records


def _norm_layer_label(x):
    if pd.isna(x):
        return ""
    x = str(x).lower().strip().replace("layer ", "").replace("layer", "").strip()
    if x.startswith("l"):
        x = x[1:]
    return x.replace("2-3", "2/3").replace("2_3", "2/3")


def _superficial_cortical_area_from_units(u, max_search_depth_um=700.0):
    if u is None or len(u) == 0:
        return None
    cortical = u["anatomy_class"].fillna("").astype(str).str.lower().eq("cortical")
    u = u.loc[
        cortical & u["depth_from_cortex_um"].notna() & (u["depth_from_cortex_um"] >= 0)
    ].copy()
    if len(u) == 0:
        return None
    u = u.loc[u["depth_from_cortex_um"] <= float(max_search_depth_um)].copy()
    if len(u) == 0:
        return None
    u = u.loc[
        u["area_family"].notna() & (u["area_family"].astype(str).str.strip() != "")
    ].sort_values("depth_from_cortex_um")
    if len(u) == 0:
        return None
    counts = u.head(20)["area_family"].astype(str).value_counts()
    return str(counts.index[0]) if len(counts) > 0 else None


def _estimate_l1_l23_reference(ug, max_search_depth_um=700.0):
    superficial_area = _superficial_cortical_area_from_units(ug, max_search_depth_um)
    if superficial_area is None:
        return np.nan
    u = ug.loc[
        ug["area_family"].astype(str).eq(str(superficial_area))
        & ug["anatomy_class"].fillna("").astype(str).str.lower().eq("cortical")
    ].copy()
    u = u.loc[
        u["depth_from_cortex_um"].notna()
        & (u["depth_from_cortex_um"] >= 0)
        & (u["depth_from_cortex_um"] <= float(max_search_depth_um))
    ].copy()
    if "layer" not in u.columns:
        return np.nan
    layer = u["layer"].map(_norm_layer_label)
    l1 = u.loc[layer.eq("1"), "depth_from_cortex_um"].astype(float).sort_values()
    l23 = u.loc[layer.eq("2/3"), "depth_from_cortex_um"].astype(float).sort_values()
    if len(l1) >= 1 and len(l23) >= 2:
        l1_edge = float(l1.quantile(0.90)) if len(l1) >= 4 else float(l1.max())
        l23_edge = float(l23.quantile(0.10)) if len(l23) >= 4 else float(l23.min())
        if -100.0 <= (l23_edge - l1_edge) <= 300.0:
            ref = 0.5 * (l1_edge + l23_edge)
            if 0.0 <= ref <= float(max_search_depth_um):
                return float(ref)
    return np.nan


def _build_l1_l23_reference_table(unit_df, boundary_df, ref_keys, max_search_depth_um=700.0):
    if unit_df is None or len(unit_df) == 0:
        return pd.DataFrame(columns=list(ref_keys) + ["l1_l23_boundary_depth_um"])
    rows = []
    for key_values, ug in unit_df.groupby(ref_keys, dropna=False):
        if not isinstance(key_values, tuple):
            key_values = (key_values,)
        key_dict = dict(zip(ref_keys, key_values, strict=False))
        ref = _estimate_l1_l23_reference(ug, max_search_depth_um)
        rows.append({**key_dict, "l1_l23_boundary_depth_um": ref})
    return pd.DataFrame(rows)


def _static_prepare_alignment_tables(master_df, ccf_boundary_df):
    target = str(STATIC_CSD_TARGET_CONTEXT).strip().upper()
    u = master_df.loc[master_df["context"].astype(str).str.strip().str.upper().eq(target)].copy()
    b = ccf_boundary_df.loc[
        ccf_boundary_df["context"].astype(str).str.strip().str.upper().eq(target)
    ].copy()
    candidate = ["mouse_id", "cohort", "context", "session_stage", "session_key", "probe"]
    ref_keys = [c for c in candidate if c in u.columns]
    refs = _build_l1_l23_reference_table(u, b, ref_keys, max_search_depth_um=700.0)
    return u, refs


def _static_alignment(session_info, probe, align_units, l1_refs):
    u = align_units.loc[
        (align_units["session_key"] == session_info["session_key"])
        & (align_units["probe"] == probe)
    ]
    r = l1_refs.loc[
        (l1_refs["session_key"] == session_info["session_key"]) & (l1_refs["probe"] == probe)
    ]
    surface = l1ref = np.nan
    ref_source = None
    if len(u) and "ccf_surface_depth_um" in u.columns:
        vals = pd.to_numeric(u["ccf_surface_depth_um"], errors="coerce").dropna()
        if len(vals):
            surface = float(vals.median())
    if len(r) and "l1_l23_boundary_depth_um" in r.columns:
        vals = pd.to_numeric(r["l1_l23_boundary_depth_um"], errors="coerce").dropna()
        if len(vals):
            l1ref = float(vals.iloc[0])
    return surface, l1ref, ref_source


def _static_lfp_series_by_probe(nwb):
    if "ecephys" not in nwb.processing:
        return {}
    e = nwb.processing["ecephys"]
    if "LFP" not in e.data_interfaces:
        return {}
    out = {}
    for key in e["LFP"].electrical_series.keys():
        m = re.search(r"Probe[ _]?([A-Fa-f])", str(key))
        if m:
            p = f"Probe{m.group(1).upper()}"
            if p in VALID_PROBES:
                out[p] = e["LFP"].electrical_series[key]
    return out


def _static_safe_col(table, names, n, default=None):
    for name in names:
        if name in table.colnames:
            return np.asarray(table[name][:])
    return np.full(n, default, dtype=object)


def _static_electrode_meta(nwb, es, session_info, probe, align_units, l1_refs):
    n_ch = int(es.data.shape[1])
    et = nwb.electrodes
    try:
        rows = np.asarray(es.electrodes.data[:], dtype=int)
    except Exception:
        rows = np.array([], dtype=int)
    if len(rows) != n_ch:
        groups = _static_safe_col(et, ["group_name", "probe_name", "device_name"], len(et), "")
        rows = np.flatnonzero(np.array([_normalize_probe(x) == probe for x in groups]))
    if len(rows) != n_ch:
        raise ValueError(f"{probe}: LFP columns={n_ch}, electrode rows={len(rows)}")

    ry = pd.to_numeric(
        pd.Series(
            _static_safe_col(
                et, ["rel_y", "probe_vertical_position", "vertical_position"], len(et), np.nan
            )[rows]
        ),
        errors="coerce",
    ).to_numpy(float)
    rx = pd.to_numeric(
        pd.Series(
            _static_safe_col(
                et, ["rel_x", "probe_horizontal_position", "horizontal_position"], len(et), np.nan
            )[rows]
        ),
        errors="coerce",
    ).to_numpy(float)
    loc = [
        _clean_area_label(x)
        for x in _static_safe_col(
            et, ["location", "structure_acronym", "brain_region"], len(et), None
        )[rows]
    ]
    ch = [_decode_text(x) for x in _static_safe_col(et, ["channel_name"], len(et), None)[rows]]
    for i in range(n_ch):
        if not np.isfinite(ry[i]):
            m = re.fullmatch(r"AP(\d+)", str(ch[i]).strip())
            if m:
                ry[i] = (int(m.group(1)) // 2) * 20.0

    parsed = [_parse_ccf_hierarchy(x) for x in loc]
    m = pd.DataFrame(
        {
            "lfp_col": np.arange(n_ch, dtype=int),
            "rel_x_um": rx,
            "rel_y_um": ry,
            "ccf_acronym": loc,
            "major_division": [p.get("major_division") for p in parsed],
            "region_group": [p.get("region_group") for p in parsed],
            "area_family": [p.get("area_family") for p in parsed],
            "subarea": [p.get("subarea") for p in parsed],
            "layer": [p.get("layer") for p in parsed],
            "anatomy_class": [p.get("anatomy_class") for p in parsed],
        }
    )
    finite = m["rel_y_um"].to_numpy(float)
    if not np.isfinite(finite).any():
        raise ValueError(f"{probe}: no usable electrode depth coordinate")
    top_y = float(np.nanmax(finite))
    m["probe_depth_from_surface_um"] = top_y - m["rel_y_um"]

    surface, l1ref, ref_source = _static_alignment(session_info, probe, align_units, l1_refs)
    cortex_probe_depth = (top_y - surface) if np.isfinite(surface) else np.nan
    l1_probe_depth = (
        (cortex_probe_depth + l1ref)
        if np.isfinite(cortex_probe_depth) and np.isfinite(l1ref)
        else np.nan
    )
    return m, cortex_probe_depth, l1_probe_depth, ref_source


def _static_timebase(es):
    n = int(es.data.shape[0])
    rate = getattr(es, "rate", None)
    st = getattr(es, "starting_time", None)
    if rate is not None and np.isfinite(rate) and float(rate) > 0:
        return {"mode": "rate", "rate": float(rate), "t0": float(st or 0.0), "ts": None, "n": n}
    ts = es.timestamps
    if ts is None:
        raise ValueError("LFP has neither rate nor timestamps")
    sample = np.asarray(ts[: min(2000, n)], float)
    d = np.diff(sample)
    d = d[np.isfinite(d) & (d > 0)]
    if not len(d):
        raise ValueError("Cannot estimate LFP sampling rate")
    return {
        "mode": "timestamps",
        "rate": 1 / float(np.median(d)),
        "t0": float(sample[0]),
        "ts": ts,
        "n": n,
    }


def _static_nearest(tb, t):
    j = int(round((float(t) - tb["t0"]) * tb["rate"]))
    j = max(0, min(tb["n"] - 1, j))
    if tb["mode"] == "rate":
        return j
    lo = max(0, j - 8)
    hi = min(tb["n"], j + 9)
    a = np.asarray(tb["ts"][lo:hi], float)
    return j if not len(a) else lo + int(np.argmin(np.abs(a - float(t))))


def _static_to_mV(es, raw):
    x = np.asarray(raw, np.float64)
    conv = getattr(es, "conversion", 1.0)
    off = getattr(es, "offset", 0.0)
    x *= 1.0 if conv is None else float(conv)
    cc = getattr(es, "channel_conversion", None)
    if cc is not None:
        cc = np.asarray(cc[:], float).reshape(1, -1)
        if cc.shape[1] == x.shape[1]:
            x *= cc
    x += 0.0 if off is None else float(off)
    unit = str(getattr(es, "unit", "") or "").strip().lower()
    if unit in {"v", "volt", "volts"}:
        x *= 1000.0
    elif unit in {"uv", "µv", "microvolt", "microvolts"}:
        x /= 1000.0
    return x


def _static_condition_specs(df):
    if STATIC_CSD_TARGET_GROUP not in df.columns:
        return None, []
    vals = df[STATIC_CSD_TARGET_GROUP].map(
        lambda x: str(x).strip().lower() if not pd.isna(x) else ""
    )
    target = str(STATIC_CSD_TARGET_CONDITION).strip().lower()
    if not (vals == target).any():
        return STATIC_CSD_TARGET_GROUP, []
    return STATIC_CSD_TARGET_GROUP, [(STATIC_CSD_TARGET_CONDITION, STATIC_CSD_TARGET_CONDITION)]


def _static_selected_indices(df, group_col, specs, random_key=""):
    starts = pd.to_numeric(df["start_time"], errors="coerce")
    valid = np.flatnonzero(starts.notna().to_numpy())
    selections = {}
    for value, label in specs:
        idx = valid.copy()
        if value != "__ALL__" and group_col:
            vals = (
                df.iloc[idx][group_col]
                .map(lambda x: str(x).strip().lower() if not pd.isna(x) else "<missing>")
                .to_numpy()
            )
            idx = idx[vals == str(value).strip().lower()]
        if len(idx) > STATIC_CSD_MAX_TRIALS_PER_CONDITION:
            seed_text = f"{STATIC_CSD_RANDOM_SEED}|{random_key}|{label}"
            seed = int.from_bytes(hashlib.sha256(seed_text.encode("utf-8")).digest()[:8], "little")
            rng = np.random.default_rng(seed)
            idx = np.sort(rng.choice(idx, size=STATIC_CSD_MAX_TRIALS_PER_CONDITION, replace=False))
        selections[label] = np.asarray(idx, dtype=int)
    return starts.to_numpy(float), selections


def _static_trial_averages(es, stim_df, group_col, specs, random_key=""):
    starts, selections = _static_selected_indices(stim_df, group_col, specs, random_key=random_key)
    tb = _static_timebase(es)
    rate = tb["rate"]
    npre = int(round(STATIC_CSD_PRE_MS * rate / 1000))
    npost = int(round(STATIC_CSD_POST_MS * rate / 1000))
    ns = npre + npost + 1
    nch = int(es.data.shape[1])
    bn = min(max(int(round(STATIC_CSD_BASELINE_MS * rate / 1000)), 0), npre)
    acc = {lab: np.zeros((ns, nch), np.float64) for _, lab in specs}
    counts = {lab: 0 for _, lab in specs}
    used_rows = {lab: [] for _, lab in specs}
    row_to_labels = {}
    for lab, idxs in selections.items():
        for ix in idxs:
            row_to_labels.setdefault(int(ix), []).append(lab)
    for ix, labels in row_to_labels.items():
        t = starts[ix]
        if not np.isfinite(t):
            continue
        c = _static_nearest(tb, t)
        lo = c - npre
        hi = c + npost + 1
        if lo < 0 or hi > tb["n"]:
            continue
        tr = _static_to_mV(es, es.data[lo:hi, :])
        if tr.shape != (ns, nch):
            continue
        if bn > 0:
            tr = tr - np.nanmean(tr[npre - bn : npre, :], axis=0, keepdims=True)
        for lab in labels:
            acc[lab] += tr
            counts[lab] += 1
            used_rows[lab].append(int(ix))
    time = (np.arange(ns) - npre) * 1000.0 / rate
    out = {}
    for _, lab in specs:
        if counts[lab] > 0:
            out[lab] = (acc[lab] / counts[lab], time, rate, counts[lab], used_rows[lab])
    return out


def _static_collapse(avg, meta, depth_col):
    m = meta[["lfp_col", depth_col]].copy()
    m[depth_col] = pd.to_numeric(m[depth_col], errors="coerce")
    m = m.dropna()
    z = []
    rows = []
    for zz, g in m.groupby(depth_col, sort=True):
        cols = g["lfp_col"].astype(int).to_numpy()
        z.append(float(zz))
        rows.append(np.nanmean(avg[:, cols], axis=1))
    if len(z) < 3:
        raise ValueError("fewer than 3 unique depths")
    return np.asarray(z), np.stack(rows, axis=0)


def _static_regularize(z, v, time_ms):
    o = np.argsort(z)
    z = np.asarray(z, float)[o]
    v = np.asarray(v, float)[o, :]
    dd = np.diff(z)
    dd = dd[np.isfinite(dd) & (dd > 0)]
    if not len(dd):
        raise ValueError("invalid depth geometry")
    dz = float(np.median(dd))
    zg = np.arange(z.min(), z.max() + 0.5 * dz, dz)
    if len(zg) < 3:
        raise ValueError("fewer than 3 regularized depths")
    vg = np.empty((len(zg), v.shape[1]), float)
    for ti in range(v.shape[1]):
        vg[:, ti] = np.interp(zg, z, v[:, ti])
    if STATIC_CSD_SPATIAL_SIGMA_UM > 0:
        vg = gaussian_filter1d(vg, STATIC_CSD_SPATIAL_SIGMA_UM / dz, axis=0, mode="nearest")
    if STATIC_CSD_TEMPORAL_SIGMA_MS > 0 and len(time_ms) > 1:
        dt = float(np.median(np.diff(time_ms)))
        if dt > 0:
            vg = gaussian_filter1d(vg, STATIC_CSD_TEMPORAL_SIGMA_MS / dt, axis=1, mode="nearest")
    zmm = zg / 1000.0
    csd = -np.gradient(np.gradient(vg, zmm, axis=0, edge_order=2), zmm, axis=0, edge_order=2)
    return zg, vg, csd, dz


def _static_segment_key(row):
    ac = row.get("ccf_acronym")
    ac = None if pd.isna(ac) else str(ac)
    if row.get("anatomy_class") == "cortical":
        return f"CTX:{row.get('subarea') or row.get('area_family') or ac}"
    if row.get("major_division") == "Hippocampal formation":
        return f"HPF:{row.get('subarea') or row.get('area_family') or ac}"
    if ac and ac.upper().startswith("SC"):
        return "SC"
    return str(row.get("subarea") or row.get("area_family") or ac or "unannotated")


def _static_segments(meta, depth_col="probe_depth_from_surface_um"):
    m = meta.copy()
    m[depth_col] = pd.to_numeric(m[depth_col], errors="coerce")
    m = m.loc[m[depth_col].notna()].sort_values(depth_col)
    if not len(m):
        return []
    ud = np.sort(m[depth_col].unique())
    dd = np.diff(ud)
    dd = dd[dd > 0]
    typical = float(np.median(dd)) if len(dd) else 40.0
    gap = max(100.0, 2.75 * typical)
    out = []
    idx = []
    key = None
    prev = None
    for i, row in m.iterrows():
        k = _static_segment_key(row)
        z = float(row[depth_col])
        if idx and (k != key or (prev is not None and abs(z - prev) > gap)):
            g = m.loc[idx].copy()
            if g[depth_col].nunique() >= 3:
                out.append(g)
            idx = []
        idx.append(i)
        key = k
        prev = z
    if idx:
        g = m.loc[idx].copy()
        if g[depth_col].nunique() >= 3:
            out.append(g)
    return out


def _static_anatomy_spans(meta, depth_col="probe_depth_from_surface_um"):
    m = meta.copy()
    m[depth_col] = pd.to_numeric(m[depth_col], errors="coerce")
    m = m.loc[m[depth_col].notna()].sort_values(depth_col)
    if not len(m):
        return []
    zs = np.sort(m[depth_col].unique())
    dd = np.diff(zs)
    dd = dd[dd > 0]
    half = (float(np.median(dd)) if len(dd) else 40.0) / 2
    rows = []
    for z, g in m.groupby(depth_col, sort=True):
        labels = g["ccf_acronym"].dropna().astype(str)
        lab = labels.mode().iloc[0] if len(labels) else "unannotated"
        gp = g.iloc[0]
        rows.append(
            (
                float(z),
                lab,
                gp.get("region_group"),
                gp.get("major_division"),
                gp.get("anatomy_class"),
            )
        )
    spans = []
    start, lab, rg, md, ac = rows[0]
    prev = start
    for z, nlab, nrg, nmd, nac in rows[1:]:
        if nlab != lab:
            spans.append(
                {
                    "z0": float(start - half),
                    "z1": float(prev + half),
                    "label": lab,
                    "region_group": None if pd.isna(rg) else str(rg),
                    "major_division": None if pd.isna(md) else str(md),
                    "anatomy_class": None if pd.isna(ac) else str(ac),
                }
            )
            start, lab, rg, md, ac = z, nlab, nrg, nmd, nac
        prev = z
    spans.append(
        {
            "z0": float(start - half),
            "z1": float(prev + half),
            "label": lab,
            "region_group": None if pd.isna(rg) else str(rg),
            "major_division": None if pd.isna(md) else str(md),
            "anatomy_class": None if pd.isna(ac) else str(ac),
        }
    )
    return spans


def _static_full_probe_csd(avg, meta, time_ms):
    z, v = _static_collapse(avg, meta, "probe_depth_from_surface_um")
    zg, vg, global_csd, dz = _static_regularize(z, v, time_ms)
    csd = np.full_like(vg, np.nan)
    seginfo = []
    for seg in _static_segments(meta):
        try:
            z0, v0 = _static_collapse(avg, seg, "probe_depth_from_surface_um")
            zs, _, cs, _ = _static_regularize(z0, v0, time_ms)
        except Exception:
            continue
        inside = (zg >= zs.min()) & (zg <= zs.max())
        if not inside.any():
            continue
        for ti in range(len(time_ms)):
            csd[inside, ti] = np.interp(zg[inside], zs, cs[:, ti])
        labs = seg["ccf_acronym"].dropna().astype(str)
        seginfo.append(
            {
                "z0": float(zs.min()),
                "z1": float(zs.max()),
                "labels": "/".join(pd.unique(labs)) if len(labs) else "unannotated",
            }
        )
    frac = float(np.isfinite(csd).mean()) if csd.size else 0.0
    mode = "anatomy-segmented"
    if frac == 0.0:
        csd = global_csd.copy()
        spans = _static_anatomy_spans(meta)
        mask = max(1.5 * dz, 2.0 * STATIC_CSD_SPATIAL_SIGMA_UM)
        for sp in spans[:-1]:
            csd[np.abs(zg - float(sp["z1"])) <= mask, :] = np.nan
        frac = float(np.isfinite(csd).mean()) if csd.size else 0.0
        mode = "continuous-probe fallback; boundary-masked; exploratory"
    return zg, vg, csd, dz, seginfo, mode, frac


def _static_display_downsample(z, t, lfp, csd):
    dt = float(np.median(np.diff(t))) if len(t) > 1 else STATIC_CSD_DISPLAY_DT_MS
    step = max(1, int(round(STATIC_CSD_DISPLAY_DT_MS / max(dt, 1e-9))))
    ti = np.arange(0, len(t), step, dtype=int)
    zero = int(np.argmin(np.abs(t))) if len(t) else 0
    ti = np.unique(np.r_[ti, zero, len(t) - 1])
    if len(z) > STATIC_CSD_MAX_DEPTH_ROWS:
        zi = np.unique(np.linspace(0, len(z) - 1, STATIC_CSD_MAX_DEPTH_ROWS).round().astype(int))
    else:
        zi = np.arange(len(z), dtype=int)
    return z[zi], t[ti], lfp[np.ix_(zi, ti)], csd[np.ix_(zi, ti)]


def _static_encode_matrix(x):
    x = np.asarray(x, float)
    finite = np.isfinite(x)
    lim = float(np.nanmax(np.abs(x[finite]))) if finite.any() else 0.0
    scale = (lim / 32767.0) if lim > 0 else 1.0
    q = np.full(x.shape, -32768, dtype="<i2")
    if finite.any():
        q[finite] = np.clip(np.rint(x[finite] / scale), -32767, 32767).astype(np.int16)
    return base64.b64encode(q.tobytes(order="C")).decode("ascii"), float(scale)


def build_static_csd_payload(manifest, align_units, l1_refs, cache_dir):
    all_records = []
    print(
        f"\nStatic LFP/CSD: processing ONLY context={STATIC_CSD_TARGET_CONTEXT!r}: "
        f"{len(manifest)} session(s)."
    )

    for i, s in enumerate(manifest, 1):
        cache_path = os.path.join(cache_dir, f"{s['session_key']}_v5_csd.pkl.gz")
        print(f"[{i}/{len(manifest)}] {s['session_key']} | {s['cohort']} | {s['context']}")

        if os.path.exists(cache_path):
            with gzip.open(cache_path, "rb") as f:
                recs = pickle.load(f)
            all_records.extend(recs)
            print(f"  cache hit: {len(recs)} records")
            continue

        try:
            nwb = _STATIC_REMOTE.open(s)
            series = _static_lfp_series_by_probe(nwb)
            if not series:
                raise ValueError("No LFP ElectricalSeries in session")

            interval_names = list(nwb.intervals.keys())
            table_name = None
            target_low = STATIC_CSD_TARGET_TABLE.lower().replace("_presentations", "")
            matches = [n for n in interval_names if target_low in str(n).lower()]
            if matches:
                table_name = matches[0]
            if table_name is None:
                candidates = [
                    n
                    for n in interval_names
                    if "standard" in str(n).lower() and "mismatch" in str(n).lower()
                ]
                if len(candidates) >= 1:
                    table_name = candidates[0]
            if table_name is None:
                raise ValueError("Standard oddball table not found")

            tab = nwb.intervals[table_name]
            df = tab.to_dataframe().reset_index(drop=True)
            group_col, specs = _static_condition_specs(df)

            recs = []
            for probe, es in sorted(series.items()):
                try:
                    meta, cortex_depth, l1_depth, ref_source = _static_electrode_meta(
                        nwb, es, s, probe, align_units, l1_refs
                    )
                    avgs = _static_trial_averages(
                        es, df, group_col, specs, random_key=f"{s['session_key']}|{table_name}"
                    )
                    spans = _static_anatomy_spans(meta)
                    for _, label in specs:
                        if label not in avgs:
                            continue
                        avg, time_ms, rate, ntr, trial_rows = avgs[label]
                        z, lfp, csd, dz, segs, mode, frac = _static_full_probe_csd(
                            avg, meta, time_ms
                        )
                        z, t, lfp, csd = _static_display_downsample(z, time_ms, lfp, csd)
                        lb64, lscale = _static_encode_matrix(lfp)
                        cb64, cscale = _static_encode_matrix(csd)
                        recs.append(
                            {
                                "session_key": s["session_key"],
                                "mouse_id": s["mouse_id"],
                                "cohort": s["cohort"],
                                "context": s["context"],
                                "session_stage": s["session_stage"],
                                "session_label": f"{s['session_key']} | "
                                f"{s['cohort']} | {s['context']} | "
                                f"{s['session_stage']}",
                                "probe": probe,
                                "stim_table": str(table_name),
                                "group_by": group_col or "",
                                "condition": str(label),
                                "time_ms": np.round(t, 3).tolist(),
                                "depth_probe_um": np.round(z, 3).tolist(),
                                "shape": [int(lfp.shape[0]), int(lfp.shape[1])],
                                "lfp_b64": lb64,
                                "lfp_scale": lscale,
                                "csd_b64": cb64,
                                "csd_scale": cscale,
                                "n_trials": int(ntr),
                                "sampling_rate_hz": float(rate),
                                "native_depth_step_um": float(dz),
                                "csd_mode": mode,
                                "csd_finite_fraction": float(frac),
                                "cortex_entry_probe_depth_um": None
                                if not np.isfinite(cortex_depth)
                                else float(cortex_depth),
                                "l1_l23_probe_depth_um": None
                                if not np.isfinite(l1_depth)
                                else float(l1_depth),
                                "l1_l23_reference_source": ref_source,
                                "anatomy_spans": spans,
                                "csd_segments": segs,
                            }
                        )
                except Exception as exc:
                    print(f"      {probe}: skipped ({exc})")

            with gzip.open(cache_path, "wb", compresslevel=6) as f:
                pickle.dump(recs, f, pickle.HIGHEST_PROTOCOL)
            all_records.extend(recs)
            print(f"  cached: {len(recs)} records")
        except Exception as exc:
            print(f"  SESSION FAILED: {exc}")
        finally:
            _STATIC_REMOTE.close()
    return all_records


# PSD Functions
def _spectral_candidate_windows(nwb, tb, window_seconds, n_windows):
    win = float(window_seconds)
    candidates = []
    try:
        names = list(nwb.intervals.keys())
        spont_name = "spontaneous_presentations" if "spontaneous_presentations" in names else None
        if not spont_name:
            matches = [n for n in names if "spontaneous" in str(n).lower()]
            if matches:
                spont_name = matches[0]

        if spont_name is not None:
            df = nwb.intervals[spont_name].to_dataframe().reset_index(drop=True)
            if "start_time" in df.columns and "stop_time" in df.columns:
                for _, row in df.iterrows():
                    a = pd.to_numeric(pd.Series([row["start_time"]]), errors="coerce").iloc[0]
                    b = pd.to_numeric(pd.Series([row["stop_time"]]), errors="coerce").iloc[0]
                    if not (np.isfinite(a) and np.isfinite(b)):
                        continue
                    usable = float(b) - float(a) - win
                    if usable <= 0:
                        candidates.append(float(a))
                    else:
                        for frac in (0.05, 0.50, 0.95):
                            candidates.append(float(a) + frac * usable)
            if candidates:
                candidates = sorted(set(candidates))
                if len(candidates) > int(n_windows):
                    pick = np.linspace(0, len(candidates) - 1, int(n_windows)).round().astype(int)
                    candidates = [candidates[i] for i in pick]
                return candidates, f"{spont_name} (distributed)"
    except Exception:
        pass

    rate, t0 = float(tb["rate"]), float(tb["t0"])
    duration = float(tb["n"]) / rate
    end = t0 + duration
    if duration < win:
        return [], "recording too short"
    margin = min(5.0, max(0.0, 0.05 * duration))
    first, last = t0 + margin, end - win - margin
    if last < first:
        first, last = t0, end - win
    if last < first:
        return [], "recording too short"
    return np.linspace(
        first, last, int(max(1, n_windows))
    ).tolist(), "distributed recording windows"


def _spectral_read_psd_for_series(es, starts_seconds):
    tb = _static_timebase(es)
    rate = float(tb["rate"])
    nwin = max(8, int(round(STATIC_PSD_WINDOW_SECONDS * rate)))
    nperseg = min(nwin, max(16, int(round(STATIC_PSD_WELCH_SECONDS * rate))))
    noverlap = min(nperseg - 1, int(round(STATIC_PSD_WELCH_OVERLAP * nperseg)))

    psd_sum, freq_ref, used = None, None, 0
    for t0 in starts_seconds:
        lo = _static_nearest(tb, float(t0))
        hi = lo + nwin
        if lo < 0 or hi > tb["n"]:
            continue
        x = _static_to_mV(es, es.data[lo:hi, :])
        if x.ndim != 2 or x.shape[0] < nperseg:
            continue

        f, p = welch(
            x,
            fs=rate,
            axis=0,
            nperseg=nperseg,
            noverlap=noverlap,
            detrend="constant",
            scaling="density",
        )
        keep = np.isfinite(f) & (f >= STATIC_PSD_FMIN) & (f <= STATIC_PSD_FMAX)
        f, p = np.asarray(f[keep], dtype=float), np.asarray(p[keep, :], dtype=np.float64)
        if not len(f):
            continue

        if psd_sum is None:
            freq_ref, psd_sum = f, np.zeros_like(p, dtype=np.float64)
        if len(f) != len(freq_ref) or not np.allclose(f, freq_ref):
            p2 = np.empty((len(freq_ref), p.shape[1]), dtype=np.float64)
            for ch in range(p.shape[1]):
                p2[:, ch] = np.interp(freq_ref, f, p[:, ch])
            p = p2
        psd_sum += p
        used += 1

    if used == 0:
        raise ValueError("No usable long LFP windows for PSD")
    return freq_ref, psd_sum / float(used), used, rate


def _spectral_collapse_by_depth(meta, psd_freq_by_channel):
    m = meta[["lfp_col", "probe_depth_from_surface_um"]].copy()
    m["probe_depth_from_surface_um"] = pd.to_numeric(
        m["probe_depth_from_surface_um"], errors="coerce"
    )
    m = m.dropna()
    depths, rows = [], []
    for z, g in m.groupby("probe_depth_from_surface_um", sort=True):
        cols = g["lfp_col"].astype(int).to_numpy()
        cols = cols[(cols >= 0) & (cols < psd_freq_by_channel.shape[1])]
        if not len(cols):
            continue
        depths.append(float(z))
        rows.append(np.nanmean(psd_freq_by_channel[:, cols], axis=1))
    return np.asarray(depths, dtype=float), np.stack(rows, axis=0)


def _spectral_resample_and_summarize(depths, freqs, psd_depth_by_freq):
    target_f = np.arange(
        STATIC_PSD_FMIN,
        STATIC_PSD_FMAX + 0.5 * STATIC_PSD_FREQ_STEP,
        STATIC_PSD_FREQ_STEP,
        dtype=float,
    )
    linear = np.empty((len(depths), len(target_f)), dtype=np.float64)
    for i in range(len(depths)):
        row = np.asarray(psd_depth_by_freq[i], dtype=float)
        good = np.isfinite(row) & (row >= 0) & np.isfinite(freqs)
        if good.sum() < 2:
            linear[i, :] = np.nan
        else:
            linear[i, :] = np.interp(target_f, np.asarray(freqs)[good], row[good])

    tiny = np.finfo(np.float64).tiny
    psd_db = 10.0 * np.log10(np.maximum(linear, tiny))
    total_mask = (target_f >= STATIC_PSD_FMIN) & (target_f <= STATIC_PSD_FMAX)
    total = np.trapezoid(linear[:, total_mask], target_f[total_mask], axis=1)

    band_profiles, linear_band = {}, {}
    for name, (f0, f1) in STATIC_PSD_BANDS.items():
        mask = (target_f >= float(f0)) & (target_f <= float(f1))
        bp = np.trapezoid(linear[:, mask], target_f[mask], axis=1)
        linear_band[name] = bp
        with np.errstate(divide="ignore", invalid="ignore"):
            rel = 100.0 * bp / total
            abs_db = 10.0 * np.log10(np.maximum(bp, tiny))
        band_profiles[name] = {
            "kind": "band_power",
            "unit": "%",
            "absolute_unit": "dB mV²",
            "f0": float(f0),
            "f1": float(f1),
            "values": np.round(rel, 4).tolist(),
            "values_absolute_db": np.round(abs_db, 4).tolist(),
        }

    with np.errstate(divide="ignore", invalid="ignore"):
        td = linear_band["Theta 4–12 Hz"] / linear_band["Delta 1–4 Hz"]
        htd = linear_band["Hipp theta 6–10 Hz"] / linear_band["Delta 1–4 Hz"]
    band_profiles["Theta / delta ratio"] = {
        "kind": "ratio",
        "unit": "ratio",
        "f0": 4.0,
        "f1": 12.0,
        "values": np.round(td, 4).tolist(),
    }
    band_profiles["Hipp theta / delta ratio"] = {
        "kind": "ratio",
        "unit": "ratio",
        "f0": 6.0,
        "f1": 10.0,
        "values": np.round(htd, 4).tolist(),
    }
    return target_f, psd_db, band_profiles


def _spectral_downsample_depth(depths, psd_db, band_profiles):
    if len(depths) <= STATIC_PSD_MAX_DEPTH_ROWS:
        idx = np.arange(len(depths), dtype=int)
    else:
        idx = np.unique(
            np.linspace(0, len(depths) - 1, STATIC_PSD_MAX_DEPTH_ROWS).round().astype(int)
        )

    out_bands = {}
    for name, spec in band_profiles.items():
        out_spec = {k: v for k, v in spec.items() if not k.startswith("values")}
        for value_key in ("values", "values_absolute_db"):
            if value_key in spec:
                vals = np.asarray(spec[value_key], dtype=float)
                out_spec[value_key] = np.round(vals[idx], 4).tolist()
        out_bands[name] = out_spec
    return np.asarray(depths, dtype=float)[idx], np.asarray(psd_db, dtype=float)[idx, :], out_bands


def build_static_spectral_payload(manifest, csd_records, align_units, l1_refs, cache_dir):
    template_by_key = {(str(r.get("session_key")), str(r.get("probe"))): r for r in csd_records}
    wanted = defaultdict(set)
    for s, p in template_by_key.keys():
        wanted[s].add(p)
    all_records = []
    print(f"\nStatic PSD: processing {len(wanted)} STANDARD session(s).")

    for i, s in enumerate(manifest, 1):
        if s["session_key"] not in wanted:
            continue
        cache_path = os.path.join(cache_dir, f"{s['session_key']}_v4_psd_200hz.pkl.gz")
        print(f"[PSD {i}/{len(manifest)}] {s['session_key']} | {s['cohort']} | {s['context']}")

        if os.path.exists(cache_path):
            with gzip.open(cache_path, "rb") as f:
                recs = pickle.load(f)
            cached_probes = {str(r.get("probe")) for r in recs}
            if set(wanted[s["session_key"]]).issubset(cached_probes):
                all_records.extend(
                    [r for r in recs if str(r.get("probe")) in wanted[s["session_key"]]]
                )
                print(f"  cache hit: {len(recs)} records")
                continue

        try:
            nwb = _STATIC_REMOTE.open(s)
            series = _static_lfp_series_by_probe(nwb)
            recs = []
            for probe in sorted(wanted[s["session_key"]]):
                if probe not in series:
                    continue
                es = series[probe]
                try:
                    meta, cortex_depth, l1_depth, ref_source = _static_electrode_meta(
                        nwb, es, s, probe, align_units, l1_refs
                    )
                    tb = _static_timebase(es)
                    starts, source_mode = _spectral_candidate_windows(
                        nwb, tb, STATIC_PSD_WINDOW_SECONDS, STATIC_PSD_N_WINDOWS
                    )
                    if not starts:
                        raise ValueError("No suitable long windows")
                    freqs, p_freq_ch, n_used, rate = _spectral_read_psd_for_series(es, starts)
                    depths, p_depth_freq = _spectral_collapse_by_depth(meta, p_freq_ch)
                    target_f, psd_db, band_profiles = _spectral_resample_and_summarize(
                        depths, freqs, p_depth_freq
                    )
                    depths, psd_db, band_profiles = _spectral_downsample_depth(
                        depths, psd_db, band_profiles
                    )

                    template = template_by_key.get((str(s["session_key"]), str(probe)), {})
                    anatomy_spans = template.get("anatomy_spans", _static_anatomy_spans(meta))

                    recs.append(
                        {
                            "session_key": s["session_key"],
                            "mouse_id": s["mouse_id"],
                            "cohort": s["cohort"],
                            "context": s["context"],
                            "session_stage": s["session_stage"],
                            "session_label": template.get(
                                "session_label",
                                f"{s['session_key']} | "
                                f"{s['cohort']} | {s['context']} | "
                                f"{s['session_stage']}",
                            ),
                            "probe": probe,
                            "freq_hz": np.round(target_f, 3).tolist(),
                            "depth_probe_um": np.round(depths, 3).tolist(),
                            "psd_db": np.round(psd_db, 3).tolist(),
                            "band_profiles": band_profiles,
                            "n_windows": int(n_used),
                            "window_seconds": float(STATIC_PSD_WINDOW_SECONDS),
                            "source_mode": str(source_mode),
                            "sampling_rate_hz": float(rate),
                            "cortex_entry_probe_depth_um": template.get(
                                "cortex_entry_probe_depth_um",
                                None if not np.isfinite(cortex_depth) else float(cortex_depth),
                            ),
                            "l1_l23_probe_depth_um": template.get(
                                "l1_l23_probe_depth_um",
                                None if not np.isfinite(l1_depth) else float(l1_depth),
                            ),
                            "l1_l23_reference_source": template.get(
                                "l1_l23_reference_source", ref_source
                            ),
                            "anatomy_spans": anatomy_spans,
                        }
                    )
                except Exception as exc:
                    print(f"      PSD {probe}: skipped ({exc})")

            with gzip.open(cache_path, "wb", compresslevel=6) as f:
                pickle.dump(recs, f, pickle.HIGHEST_PROTOCOL)
            all_records.extend(recs)
            print(f"  cached: {len(recs)} records")
        except Exception as exc:
            print(f"  SESSION FAILED: {exc}")
        finally:
            _STATIC_REMOTE.close()
    return all_records


def _compact_fr_series(ts):
    if ts is None:
        return None
    out = []
    for v in ts:
        if v is None:
            out.append(None)
        else:
            rv = round(float(v), 1)
            out.append(0 if rv == 0 else rv)
    return out


def compact_dashboard_payload(raw_payload):
    raw_units = raw_payload.get("units", [])
    if isinstance(raw_units, dict):
        keys = list(raw_units.keys())
        n_units = len(raw_units[keys[0]]) if keys else 0
        raw_units = [{k: raw_units[k][i] for k in keys} for i in range(n_units)]

    parsed_cache = {}

    def get_parsed(area):
        if area not in parsed_cache:
            parsed_cache[area] = _parse_ccf_hierarchy(area)
        return parsed_cache[area]

    col_keys = UNIT_META_COLS + list(UNIT_METRIC_ROUND_SPECS.keys()) + ["fr_time_series"]
    col_units = {k: [] for k in col_keys}
    hierarchy_override_cols = {
        "major_division",
        "region_group",
        "area_family",
        "subarea",
        "layer",
        "layer_or_compartment",
        "anatomy_class",
    }

    for u in raw_units:
        area = _clean_area_label(u.get("area") or u.get("ccf_acronym"))
        parsed = get_parsed(area)
        for k in UNIT_META_COLS:
            if k == "area":
                col_units[k].append(area)
            elif k in hierarchy_override_cols:
                col_units[k].append(parsed.get(k))
            else:
                col_units[k].append(sanitize_for_json(u.get(k)))
        for k, ndigits in UNIT_METRIC_ROUND_SPECS.items():
            val = sanitize_for_json(u.get(k))
            col_units[k].append(round(float(val), ndigits) if val is not None else None)
        col_units["fr_time_series"].append(_compact_fr_series(u.get("fr_time_series")))

    boundaries = []
    for b in sanitize_for_json(raw_payload.get("boundaries", [])):
        b_copy = dict(b)
        p_from = get_parsed(b_copy.get("from_area"))
        p_to = get_parsed(b_copy.get("to_area"))
        b_copy.update(
            {
                "from_major_division": p_from.get("major_division"),
                "to_major_division": p_to.get("major_division"),
                "from_region_group": p_from.get("region_group"),
                "to_region_group": p_to.get("region_group"),
                "from_area_family": p_from.get("area_family"),
                "to_area_family": p_to.get("area_family"),
                "from_subarea": p_from.get("subarea"),
                "to_subarea": p_to.get("subarea"),
                "from_compartment": p_from.get("compartment"),
                "to_compartment": p_to.get("compartment"),
                "from_region_family": p_from.get("region_family"),
                "to_region_family": p_to.get("region_family"),
                "from_subregion": p_from.get("subregion"),
                "to_subregion": p_to.get("subregion"),
                "from_layer": p_from.get("layer"),
                "to_layer": p_to.get("layer"),
            }
        )
        if b_copy.get("boundary_type") == "region":
            b_copy["boundary_label"] = (
                f"{p_from.get('hierarchy_label')} / {p_to.get('hierarchy_label')}"
            )
        boundaries.append(b_copy)

    def refresh_spans(records):
        out_recs = []
        for rec in sanitize_for_json(records):
            rec_copy = dict(rec)
            if "anatomy_spans" in rec_copy and isinstance(rec_copy["anatomy_spans"], list):
                new_spans = []
                for sp in rec_copy["anatomy_spans"]:
                    sp_copy = dict(sp)
                    lab = _clean_area_label(sp_copy.get("label"))
                    if lab is not None:
                        p_sp = get_parsed(lab)
                        sp_copy["region_group"] = p_sp.get("region_group")
                        sp_copy["major_division"] = p_sp.get("major_division")
                        sp_copy["anatomy_class"] = p_sp.get("anatomy_class")
                    new_spans.append(sp_copy)
                rec_copy["anatomy_spans"] = new_spans
            if "band_profiles" in rec_copy and isinstance(rec_copy["band_profiles"], dict):
                new_bp = {}
                for bname, bspec in rec_copy["band_profiles"].items():
                    bspec_copy = dict(bspec)
                    bspec_copy.pop("values_relative", None)
                    new_bp[bname] = bspec_copy
                rec_copy["band_profiles"] = new_bp
            out_recs.append(rec_copy)
        return out_recs

    return {
        "units": col_units,
        "boundaries": boundaries,
        "csd": refresh_spans(raw_payload.get("csd", [])),
        "psd": refresh_spans(raw_payload.get("psd", [])),
    }


def write_compressed_dashboard_snapshot(payload, output_path, prov_path, manifest=None):
    compact = compact_dashboard_payload(payload)
    json_bytes = json.dumps(
        compact, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")
    with open(output_path, "wb") as raw_f:
        with gzip.GzipFile(fileobj=raw_f, mode="wb", compresslevel=6, mtime=0) as gz_f:
            gz_f.write(json_bytes)

    with open(output_path, "rb") as raw_f:
        snapshot_sha256 = hashlib.sha256(raw_f.read()).hexdigest()

    existing_prov = {}
    if os.path.exists(prov_path):
        try:
            with open(prov_path, encoding="utf-8") as f:
                existing_prov = json.load(f)
        except Exception:
            existing_prov = {}

    if manifest is not None:
        source_assets = [
            {
                "session_key": s["session_key"],
                "asset_id": s["asset_id"],
                "path": s["path"],
                "modified": s["date_modified"],
            }
            for s in manifest
        ]
        timestamp_utc = datetime.now(UTC).isoformat()
    else:
        source_assets = existing_prov.get("source_assets", [])
        timestamp_utc = existing_prov.get("timestamp_utc", datetime.now(UTC).isoformat())

    prov_payload = {
        "description": "OpenScope Ecephys QC Dashboard Data",
        "snapshot": os.path.basename(output_path),
        "snapshot_sha256": snapshot_sha256,
        "timestamp_utc": timestamp_utc,
        "dandiset": "001637",
        "version": "draft",
        "source_assets": source_assets,
    }
    with open(prov_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(prov_payload, f, indent=2)
        f.write("\n")

    return snapshot_sha256


# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract Ecephys QC Dashboard Data")
    parser.add_argument(
        "--cache-dir", type=str, default=".cache", help="Directory for intermediate caching"
    )
    parser.add_argument(
        "--from-json",
        type=str,
        default=None,
        help="Compact and compress an existing uncompressed JSON snapshot without streaming DANDI",
    )
    args = parser.parse_args()
    os.makedirs(DATA_DIR, exist_ok=True)

    if args.from_json:
        print(f"Loading existing snapshot from {args.from_json}...")
        with open(args.from_json, encoding="utf-8") as f:
            existing_payload = json.load(f)
        print(f"Compacting and compressing snapshot to {OUTPUT_JSON}...")
        sha256 = write_compressed_dashboard_snapshot(existing_payload, OUTPUT_JSON, PROV_JSON)
        print(f"Saved {OUTPUT_JSON} (SHA256: {sha256})")
        raise SystemExit(0)

    os.makedirs(args.cache_dir, exist_ok=True)

    print("Fetching manifest...")
    manifest = []
    with DandiAPIClient() as client:
        dandiset = client.get_dandiset("001637", "draft")
        for cohort, contexts in SESSION_DESIGN.items():
            for context, keys in contexts.items():
                for key in keys:
                    mouse_id, date = key.split("_")
                    pattern = (
                        f"sub-{mouse_id}/sub-{mouse_id}_ses-ecephys-{mouse_id}-{date}-*_ecephys.nwb"
                    )
                    matches = list(dandiset.get_assets_by_glob(pattern))
                    if matches:
                        stage = "Middle"
                        if cohort == "Motor":
                            if context == "SENSORYMOTOR":
                                stage = "First"
                            elif context == "DURATION":
                                stage = "Last"
                        elif cohort == "Sequence":
                            if context == "SEQUENCE":
                                stage = "First"
                            elif context == "SENSORYMOTOR":
                                stage = "Last"

                        asset = matches[0]
                        url = asset.get_content_url(follow_redirects=1, strip_query=True)
                        manifest.append(
                            {
                                "cohort": cohort,
                                "context": context,
                                "session_stage": stage,
                                "mouse_id": mouse_id,
                                "session_key": key,
                                "path": asset.path,
                                "url": url,
                                "asset_id": asset.identifier,
                                "date_modified": str(asset.modified),
                            }
                        )

    print(f"Resolved {len(manifest)} valid sessions. Extracting units and CCF boundaries...")
    payloads = []
    for i, s_info in enumerate(manifest, 1):
        cache_path = os.path.join(args.cache_dir, f"{s_info['session_key']}_v12_base.pkl")
        if os.path.exists(cache_path):
            with open(cache_path, "rb") as f:
                payloads.append(pickle.load(f))
            continue

        print(f"[{i}/{len(manifest)}] Extracting NWB directly from DANDI: {s_info['session_key']}")
        nwb = _STATIC_REMOTE.open(s_info)
        units_df = _extract_units_from_nwb(nwb, s_info)
        surface_lookup, boundaries = _stream_probe_anatomy_metadata(nwb)
        _STATIC_REMOTE.close()

        units_df = _annotate_anatomy_columns(units_df)
        units_df["ccf_surface_depth_um"] = units_df["probe"].map(surface_lookup)
        units_df["probe_depth_from_tip_um"] = pd.to_numeric(units_df["depth"], errors="coerce")
        units_df["depth_from_cortex_um"] = (
            units_df["ccf_surface_depth_um"] - units_df["probe_depth_from_tip_um"]
        )
        units_df.loc[units_df["depth_from_cortex_um"].abs() < 1e-9, "depth_from_cortex_um"] = 0.0

        units_df["l1_l23_boundary_depth_um"] = np.nan
        for probe in units_df["probe"].unique():
            ug = units_df[units_df["probe"] == probe]
            ref_val = _estimate_l1_l23_reference(ug)
            units_df.loc[units_df["probe"] == probe, "l1_l23_boundary_depth_um"] = ref_val

        units_df["depth_from_l1_l23_um"] = (
            units_df["depth_from_cortex_um"] - units_df["l1_l23_boundary_depth_um"]
        )

        for b in boundaries:
            b.update(
                {
                    "mouse_id": s_info["mouse_id"],
                    "cohort": s_info["cohort"],
                    "context": s_info["context"],
                    "session_stage": s_info["session_stage"],
                    "session_key": s_info["session_key"],
                }
            )

        payload = {"metrics_df": units_df, "ccf_boundaries": boundaries}
        with open(cache_path, "wb") as f:
            pickle.dump(payload, f)
        payloads.append(payload)

    master_df = pd.concat([p["metrics_df"] for p in payloads], ignore_index=True)
    ccf_boundary_df = pd.DataFrame([b for p in payloads for b in p.get("ccf_boundaries", [])])

    if len(ccf_boundary_df):
        surface_map = (
            master_df.drop_duplicates(["session_key", "probe"])
            .set_index(["session_key", "probe"])["ccf_surface_depth_um"]
            .to_dict()
        )
        l1_map = (
            master_df.drop_duplicates(["session_key", "probe"])
            .set_index(["session_key", "probe"])["l1_l23_boundary_depth_um"]
            .to_dict()
        )
        ccf_boundary_df["ccf_surface_depth_um"] = ccf_boundary_df.apply(
            lambda r: surface_map.get((r["session_key"], r["probe"]), np.nan), axis=1
        )
        ccf_boundary_df["raw_boundary_depth_from_tip_um"] = ccf_boundary_df["depth_um"]
        ccf_boundary_df["depth_from_cortex_um"] = (
            ccf_boundary_df["ccf_surface_depth_um"]
            - ccf_boundary_df["raw_boundary_depth_from_tip_um"]
        )
        ccf_boundary_df.loc[
            ccf_boundary_df["depth_from_cortex_um"].abs() < 1e-9, "depth_from_cortex_um"
        ] = 0.0
        ccf_boundary_df["l1_l23_boundary_depth_um"] = ccf_boundary_df.apply(
            lambda r: l1_map.get((r["session_key"], r["probe"]), np.nan), axis=1
        )
        ccf_boundary_df["depth_from_l1_l23_um"] = (
            ccf_boundary_df["depth_from_cortex_um"] - ccf_boundary_df["l1_l23_boundary_depth_um"]
        )

    print(
        f"\nAssembly Complete! master_df ready: {master_df.shape[0]} units. "
        f"CCF Boundaries: {ccf_boundary_df.shape[0]}"
    )

    # Pass 2: Extract LFP, CSD, and PSD
    standard_manifest = [s for s in manifest if s["context"].upper() == STATIC_CSD_TARGET_CONTEXT]
    align_units, l1_refs = _static_prepare_alignment_tables(master_df, ccf_boundary_df)

    csd_records = build_static_csd_payload(standard_manifest, align_units, l1_refs, args.cache_dir)
    psd_records = build_static_spectral_payload(
        standard_manifest, csd_records, align_units, l1_refs, args.cache_dir
    )

    # Save to compressed JSON
    print(f"\nSanitizing and saving compressed payload to {OUTPUT_JSON}...")
    final_payload = {
        "units": master_df.to_dict(orient="records"),
        "boundaries": ccf_boundary_df.to_dict(orient="records"),
        "csd": csd_records,
        "psd": psd_records,
    }
    sha256 = write_compressed_dashboard_snapshot(
        final_payload, OUTPUT_JSON, PROV_JSON, manifest=manifest
    )
    print(f"Data extraction complete! SHA256: {sha256}")
