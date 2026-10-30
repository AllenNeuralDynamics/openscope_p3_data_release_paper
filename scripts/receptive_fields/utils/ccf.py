# Authors: Lucas Rudelt, Marcel C. Raabe
# Date: 2026-10-29
"""CCF acronym decoding for OpenScope ecephys (and mesoscope plane location strings).

Mirrors ``alexmaier_code/ai_oscp_neuro/openscope_ccf/ccf.py``: the alignment team
writes CCF acronyms into NWB ``electrodes.location`` (e.g. ``VISp5``); this module
parses them into ``area`` / ``layer`` / ``group`` / ``tissue``. No atlas volume
lookup.

Mesoscope planes store a free-text ``optophysiology/<plane>/location`` string
(``Structure: VISp Depth: 167``); :func:`parse_mesoscope_location` extracts that.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

FIBER_TRACTS = {
    "alv", "ccb", "ccg", "ccs", "cing", "dhc", "fa", "fi", "fp", "or",
    "scwm", "int", "ee", "st", "ar", "SH", "fx", "opt", "em", "cc",
}
UNASSIGNED = {"root", "void", "unknown", ""}

_LAYER_RE = re.compile(r"^(?P<area>[A-Za-z][A-Za-z\-]*?)(?P<layer>1|2/3|4|5|6a|6b)$")
_MESO_LOC_RE = re.compile(r"Structure:\s*(\S+)\s*Depth:\s*(\d+)", re.IGNORECASE)

_THALAMUS = {
    "LGd", "LGd-sh", "LGd-co", "LGd-ip", "LGv", "LP", "LD", "AV", "AD",
    "AMd", "AMv", "AM", "MGd", "MGv", "MGm", "PO", "VPM", "VPL", "VL",
    "VAL", "CL", "RT", "TH", "MD", "IntG", "IGL", "IAD", "PIL", "PF",
    "PoT", "SGN", "Eth", "REth",
}
_STRIATUM = {"CP", "STR", "LSr", "LSc", "ACB", "LSv", "SF"}


def decode_ccf(acronym: str | None) -> dict:
    """Decode one CCF acronym into ``{area, layer, tissue, group}``."""
    if acronym is None or (isinstance(acronym, float) and acronym != acronym):
        return dict(area=None, layer=None, tissue="unassigned", group="unassigned")
    if not isinstance(acronym, str):
        raise TypeError(
            f"decode_ccf expects a str acronym, got {type(acronym).__name__}: {acronym!r}"
        )
    if acronym in FIBER_TRACTS:
        return dict(area=acronym, layer=None, tissue="fiber_tract", group="white_matter")
    if acronym in UNASSIGNED:
        return dict(area=acronym, layer=None, tissue="unassigned", group="unassigned")
    if acronym in {"CA1", "CA2", "CA3"}:
        return dict(area=acronym, layer=None, tissue="grey", group="hippocampus")
    if acronym in {"DG-mo", "DG-po", "DG-sg"}:
        return dict(area="DG", layer=acronym.split("-")[1], tissue="grey", group="hippocampus")
    if acronym in {"SUB", "ProS", "PRE", "POST", "PAR"}:
        return dict(area=acronym, layer=None, tissue="grey", group="hippocampus")

    m = _LAYER_RE.match(acronym)
    area, layer = (m.group("area"), m.group("layer")) if m else (acronym, None)

    if area.startswith("VIS"):
        group = "visual_ctx"
    elif area.startswith(("MOp", "MOs")):
        group = "motor_ctx"
    elif area.startswith(("ACA", "PL", "ILA", "DP", "RSP", "ORB")):
        group = "cingulate/PFC"
    elif area.startswith(("SSp", "SS")):
        group = "somatosensory_ctx"
    elif area in _THALAMUS:
        group = "thalamus"
    elif area in _STRIATUM:
        group = "striatum"
    else:
        group = "other_grey"
    return dict(area=area, layer=layer, tissue="grey", group=group)


def decode_many(acronyms) -> list[dict]:
    """Vectorised convenience wrapper over :func:`decode_ccf`."""
    return [decode_ccf(a) for a in acronyms]


def enrich_unit_locations(df: pd.DataFrame, location_col: str = "location") -> pd.DataFrame:
    """Add ``area``, ``layer``, ``group``, ``tissue`` by decoding ``location``."""
    if location_col not in df.columns:
        raise KeyError(
            f"DataFrame has no {location_col!r} column; load electrode CCF "
            "acronyms first (NWBStream.units_df)."
        )
    out = df.copy()
    decoded = decode_many(out[location_col].tolist())
    for key in ("area", "layer", "group", "tissue"):
        out[key] = [d[key] for d in decoded]
    return out


def structure_label(area, layer) -> str:
    """Human-readable structure name: ``VISp5`` or area alone when layer is absent."""
    if area is None or (isinstance(area, float) and np.isnan(area)):
        return "unknown"
    try:
        if pd.isna(area):
            return "unknown"
    except (TypeError, ValueError):
        pass
    if layer is None or layer == "":
        return str(area)
    try:
        if pd.isna(layer):
            return str(area)
    except (TypeError, ValueError):
        pass
    if isinstance(layer, float) and np.isnan(layer):
        return str(area)
    return f"{area}{layer}"


def parse_mesoscope_location(location: str | bytes, plane_fallback: str | None = None) -> dict:
    """Parse ``Structure: VISp Depth: 167`` from mesoscope optophysiology location."""
    if isinstance(location, bytes):
        location = location.decode()
    m = _MESO_LOC_RE.search(location or "")
    if m:
        return dict(area=m.group(1), depth_um=int(m.group(2)))
    area = None
    if plane_fallback:
        area = re.sub(r"_?\d.*$", "", plane_fallback)
    return dict(area=area, depth_um=None)