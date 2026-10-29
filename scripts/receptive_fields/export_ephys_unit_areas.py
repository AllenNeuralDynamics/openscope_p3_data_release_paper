# Authors: Lucas Rudelt, Marcel C. Raabe
# Date: 2026-10-29
"""Assign CCF area and layer to each ephys unit and save the table.

Streams the example ecephys session once (dandiset 001637, sub-830794) and
writes one row per unit. Later scripts join on ``unit_id`` instead of opening
the NWB again.

Assignment is the extremum channel, not the first electrode in the unit's
region: ``device_name`` + ``extremum_channel_index`` -> electrodes row ->
``electrodes.location``, decoded by ``load_unit_areas``.

    python export_ephys_unit_areas.py

Output, in the repository's results tree (read by plotting/plot_data_release_panels.py):
    results/ecephys/<session>/unit_areas.csv
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from utils import DandiSession, load_unit_areas

SESSION_ID = "001637"
ASSET_PATH = (
    "sub-830794/sub-830794_ses-ecephys-830794-2026-01-26-12-02-05_ecephys.nwb"
)
# the repository root: scripts/ is one level below it
REPO = Path(__file__).resolve().parents[1]

COLUMNS = [
    "unit_id",
    "probe",
    "electrode_row",
    "location",
    "area",
    "layer",
    "group",
    "tissue",
    "structure",
]


def _text(value) -> str:
    if isinstance(value, bytes):
        return value.decode()
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    return str(value)


def _clean_probe(value) -> str:
    text = _text(value).strip()
    if text.startswith("b'") and text.endswith("'"):
        text = text[2:-1]
    return text


def unit_area_table(units: pd.DataFrame) -> pd.DataFrame:
    """One row per unit: id, probe, and the decoded CCF fields."""
    out = units.copy()
    if "unit_name" not in out.columns:
        raise ValueError("units table has no unit_name column")
    out["unit_id"] = out["unit_name"].map(_text)
    out["probe"] = out["probe"].map(_clean_probe)
    if "electrode_row" in out.columns:
        out["electrode_row"] = out["electrode_row"].astype("int64")
    missing = [col for col in COLUMNS if col not in out.columns]
    if missing:
        raise ValueError(f"unit table is missing {missing}")
    out = out.loc[:, COLUMNS].sort_values(
        ["probe", "unit_id"], kind="mergesort"
    ).reset_index(drop=True)
    if out["unit_id"].duplicated().any():
        dup = out.loc[out["unit_id"].duplicated(keep=False), "unit_id"].unique()
        raise ValueError(f"unit_id is not unique: {dup[:5].tolist()}")
    return out


def output_path(asset_path: str = ASSET_PATH) -> Path:
    session = Path(asset_path).stem
    return REPO / "results" / "ecephys" / session / "unit_areas.csv"


def main(session_id: str = SESSION_ID, asset_path: str = ASSET_PATH) -> Path:
    session = DandiSession(session_id)
    assets = session.assets()
    try:
        index = np.where([a.path == asset_path for a in assets])[0][0]
    except IndexError as exc:
        raise ValueError(
            f"Asset path {asset_path!r} not found in dandiset {session_id}"
        ) from exc

    asset = assets[index]
    print(f"Streaming {asset.path}")
    print(f"  asset id: {asset.identifier}")
    with session.open(asset.identifier) as stream:
        if stream.modality != "ecephys":
            raise ValueError(f"expected ecephys NWB, got {stream.modality!r}")
        units = load_unit_areas(stream)

    table = unit_area_table(units)
    path = output_path(asset_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.tmp")
    table.to_csv(tmp, index=False)
    tmp.replace(path)

    n_vis = int(table["area"].astype(str).str.startswith("VIS").sum())
    n_l23 = int(
        (
            table["area"].astype(str).str.startswith("VIS")
            & (table["layer"].astype(str) == "2/3")
        ).sum()
    )
    print(f"Wrote {len(table)} units to {path}")
    print(f"  visual cortex: {n_vis}")
    print(f"  visual cortex layer 2/3: {n_l23}")
    return path


if __name__ == "__main__":
    main()