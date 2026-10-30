# Authors: Lucas Rudelt, Marcel C. Raabe
# Date: 2026-10-29
"""Ecephys NWB helpers (aligned with ai_oscp_neuro/openscope_ccf/nwbio.py).

Maps each unit to the correct row in the stacked ``electrodes`` table using
``device_name`` + ``extremum_channel_index`` (per-probe channel index), not the
unit's ``electrodes`` DynamicTableRegion — that region lists many channels and
taking the first row often picks a deep/tip channel instead of the peak channel.
"""

from __future__ import annotations

import numpy as np


def _decode_str(arr) -> np.ndarray:
    return np.array([x.decode() if isinstance(x, bytes) else x for x in arr])


def unit_electrode_rows(h5) -> np.ndarray:
    """For each unit, row index into ``general/extracellular_ephys/electrodes``."""
    u = h5["units"]
    el = h5["general/extracellular_ephys/electrodes"]
    egrp = _decode_str(el["group_name"][:])
    dev = _decode_str(u["device_name"][:])
    eci = u["extremum_channel_index"][:]
    offset = {p: int(np.where(egrp == p)[0][0]) for p in sorted(set(egrp))}
    blocklen = {p: int((egrp == p).sum()) for p in offset}
    for p in offset:
        rows = np.where(egrp == p)[0]
        if rows[-1] - rows[0] + 1 != len(rows):
            raise ValueError(
                f"electrode rows for probe {p!r} are not contiguous "
                f"(rows {rows[0]}..{rows[-1]}, n={len(rows)})"
            )
    out = np.empty(len(dev), dtype=np.int64)
    for i, (d, c) in enumerate(zip(dev, eci, strict=False)):
        if d not in offset:
            raise KeyError(
                f"unit {i} device_name {d!r} has no matching electrode group_name"
            )
        c = int(c)
        if not (0 <= c < blocklen[d]):
            raise IndexError(
                f"unit {i} extremum_channel_index {c} out of range for probe "
                f"{d!r} (0..{blocklen[d] - 1})"
            )
        out[i] = offset[d] + c
    return out