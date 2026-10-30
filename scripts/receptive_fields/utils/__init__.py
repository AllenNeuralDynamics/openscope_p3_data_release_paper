# Author: Marcel C. Raabe
# Contributors: Lucas Rudelt
# Date: 2026-10-29
from .ccf import (
    decode_ccf,
    decode_many,
    enrich_unit_locations,
    parse_mesoscope_location,
    structure_label,
)
from .streaming import DandiSession, NWBStream, open_local, open_nwb, open_session

__all__ = [
    "DandiSession",
    "NWBStream",
    "open_nwb",
    "open_local",
    "open_session",
    "decode_ccf",
    "decode_many",
    "enrich_unit_locations",
    "parse_mesoscope_location",
    "structure_label",
    "load_unit_areas",
]


def load_unit_areas(stream: NWBStream, probe: str | None = None):
    """Per-unit CCF area / layer from a streamed or local ecephys NWB.

    Reads electrode ``location`` acronyms (already in the NWB) and decodes them
    the same way as ``ai_oscp_neuro/openscope_ccf``. Does not load spike times.

    Returns a DataFrame with at least ``probe``, ``location``, ``area``,
    ``layer``, ``group``, ``tissue``, and ``structure`` (area+layer label).
    """
    df = stream.units_df(probe=probe, include_spikes=False)
    if "area" not in df.columns:
        if "location" not in df.columns:
            raise ValueError(
                "No electrodes.location in this NWB — CCF acronyms are absent."
            )
        df = enrich_unit_locations(df)
    df = df.copy()
    df["structure"] = [
        structure_label(a, L) for a, L in zip(df["area"], df["layer"], strict=False)
    ]
    return df
