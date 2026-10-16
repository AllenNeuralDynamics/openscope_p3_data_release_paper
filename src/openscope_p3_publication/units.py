"""Release-wide Neuropixels unit table with quality metrics and Allen brain areas.

One row per unit (including noise) for every session NWB in DANDI:001637. Each unit is
placed at its extremum (peak) channel. Three anatomy levels are recorded:
``brain_division`` (Allen major division, e.g. Isocortex, TH), ``brain_area`` (layers and
sub-parcels collapsed, e.g. VISp), and ``brain_structure`` (the electrode table's fully
detailed ``location``, e.g. VISp2/3), plus the CCF coordinates of that channel.
Figures can then filter by
``decoder_label`` / ``qc_pass`` and group by area without re-reading NWBs.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

DANDISET_ID = "001637"
DANDISET_VERSION = "draft"
UNIT_TABLE_VERSION = 1
UNIT_TABLE_NAME = "neuropixels-units.parquet"
UNIT_TABLE_PROVENANCE_NAME = "neuropixels-units.provenance.json"
ELECTRODES_PATH = "general/extracellular_ephys/electrodes"

# Manuscript QC thresholds, shared with scripts/extract_neuropixels_unit_yield.py.
QC_THRESHOLDS = {
    "amplitude_cutoff_max": 0.1,
    "isi_violations_ratio_max": 0.5,
    "presence_ratio_min": 0.8,
}
ALLEN_MAJOR_DIVISIONS = (
    "Isocortex",
    "OLF",
    "HPF",
    "CTXsp",
    "STR",
    "PAL",
    "TH",
    "HY",
    "MB",
    "P",
    "MY",
    "CB",
)
# Scalar NWB unit columns copied as float32; absent columns are stored as NaN so every
# session shares one schema.
FLOAT_METRICS = (
    "firing_rate",
    "amplitude_cutoff",
    "isi_violations_ratio",
    "presence_ratio",
    "snr",
    "amplitude_median",
    "d_prime",
    "isolation_distance",
    "l_ratio",
    "nn_hit_rate",
    "drift_ptp",
    "peak_to_valley",
    "half_width",
    "depth",
    "decoder_probability",
)
_CORTICAL_LAYER_SUFFIX = re.compile(r"(?:1|2|2/3|3|4|5|6|6a|6b)$")


class SessionSkipped(RuntimeError):
    """Raised when an NWB asset has no usable units table."""


def _text(values: Any) -> np.ndarray:
    return np.asarray(
        [value.decode("utf-8") if isinstance(value, bytes) else str(value) for value in values],
        dtype=object,
    )


def _scalar_text(value: Any) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def peak_electrode_rows(units: Mapping[str, Any], electrodes: Mapping[str, Any]) -> np.ndarray:
    """Return each unit's electrode-table row at its extremum channel, or -1 if unresolved.

    ``extremum_channel_index`` indexes the unit's own ragged ``electrodes`` references when
    present; otherwise it indexes the rows of the unit's probe (``device_name`` matched to
    the electrode ``group_name``).
    """

    unit_count = len(units["id"])
    rows = np.full(unit_count, -1, dtype=np.int64)
    if "extremum_channel_index" not in units:
        return rows
    extrema = np.asarray(units["extremum_channel_index"], dtype=np.int64)
    electrode_count = len(electrodes["id"])

    if "electrodes" in units and "electrodes_index" in units:
        references = np.asarray(units["electrodes"], dtype=np.int64)
        ends = np.asarray(units["electrodes_index"], dtype=np.int64)
        starts = np.concatenate(([0], ends[:-1]))
        valid = (extrema >= 0) & (extrema < ends - starts)
        candidate = np.where(valid, references[np.where(valid, starts + extrema, 0)], -1)
    elif "device_name" in units and "group_name" in electrodes:
        devices = _text(units["device_name"][:])
        groups = _text(electrodes["group_name"][:])
        candidate = np.full(unit_count, -1, dtype=np.int64)
        for probe in np.unique(devices):
            probe_rows = np.flatnonzero(groups == probe)
            selected = np.flatnonzero(devices == probe)
            in_range = (extrema[selected] >= 0) & (extrema[selected] < len(probe_rows))
            candidate[selected[in_range]] = probe_rows[extrema[selected[in_range]]]
    else:
        return rows
    return np.where((candidate >= 0) & (candidate < electrode_count), candidate, -1)


def session_unit_table(nwb: Mapping[str, Any]) -> pd.DataFrame:
    """Return one row per unit of a single NWB, before area annotation."""

    if "units" not in nwb:
        raise SessionSkipped("missing units table")
    units = nwb["units"]
    missing = sorted({"id", "decoder_label"} - set(units))
    if missing:
        raise SessionSkipped("missing unit columns: " + ", ".join(missing))

    unit_count = len(units["id"])
    nwb_ids = np.asarray(units["id"], dtype=np.int64)
    unit_names = _text(units["unit_name"][:]) if "unit_name" in units else nwb_ids.astype(str)
    frame = pd.DataFrame(
        {
            "session_id": _scalar_text(nwb["general/session_id"][()]),
            "subject_id": _scalar_text(nwb["general/subject/subject_id"][()]),
            "unit_id": unit_names,
            "nwb_unit_index": np.arange(unit_count, dtype=np.int32),
            "probe": _text(units["device_name"][:]) if "device_name" in units else None,
            "decoder_label": _text(units["decoder_label"][:]),
            "default_qc": (
                np.asarray(units["default_qc"], dtype=bool)
                if "default_qc" in units
                else pd.array([pd.NA] * unit_count, dtype="boolean")
            ),
            "num_spikes": (
                np.asarray(units["num_spikes"], dtype=np.int64)
                if "num_spikes" in units
                else pd.array([pd.NA] * unit_count, dtype="Int64")
            ),
        }
    )
    for column in FLOAT_METRICS:
        frame[column] = (
            np.asarray(units[column], dtype=np.float32)
            if column in units
            else np.full(unit_count, np.nan, dtype=np.float32)
        )

    location = np.full(unit_count, None, dtype=object)
    coordinates = np.full((unit_count, 3), np.nan, dtype=np.float32)
    try:
        electrodes = nwb[ELECTRODES_PATH]
    except (KeyError, TypeError):
        electrodes = None
    if electrodes is not None:
        rows = peak_electrode_rows(units, electrodes)
        resolved = rows >= 0
        if "location" in electrodes:
            location[resolved] = _text(electrodes["location"][:])[rows[resolved]]
        for axis, column in enumerate(("x", "y", "z")):
            if column in electrodes:
                values = np.asarray(electrodes[column], dtype=np.float32)
                coordinates[resolved, axis] = values[rows[resolved]]
    frame["brain_structure"] = location
    frame["ccf_ap_um"] = coordinates[:, 0]
    frame["ccf_dv_um"] = coordinates[:, 1]
    frame["ccf_ml_um"] = coordinates[:, 2]
    return frame


def stream_session_unit_table(asset: Mapping[str, Any]) -> pd.DataFrame:
    """Stream one DANDI NWB asset and return its unit rows tagged with the asset."""

    import h5py
    import remfile

    remote_file = remfile.File(asset["content_url"])
    try:
        with h5py.File(remote_file, mode="r") as nwb:
            frame = session_unit_table(nwb)
    finally:
        remote_file.close()
    frame.insert(1, "asset_id", asset["asset_id"])
    return frame


def _region_index(regions: Any, acronym: str) -> int | None:
    indices = np.flatnonzero((np.asarray(regions.acronym) == acronym) & (regions.id >= 0))
    return int(indices[0]) if len(indices) == 1 else None


def _parent_area_index(regions: Any, index: int) -> int:
    """Climb layers and sub-parcels (VISp2/3 -> VISp, DG-mo -> DG) to the parent area."""

    current = index
    while True:
        parent_id = regions.parent[current]
        if not math.isfinite(parent_id):
            return current
        parent = _region_index_by_id(regions, int(parent_id))
        if parent is None:
            return current
        acronym = str(regions.acronym[current])
        parent_acronym = str(regions.acronym[parent])
        name = str(regions.name[current]).lower()
        ancestors = set(regions.ancestors(int(regions.id[current])).acronym)
        cortical_layer = (
            "Isocortex" in ancestors and _CORTICAL_LAYER_SUFFIX.search(acronym) is not None
        )
        if not ("layer" in name or acronym.startswith(f"{parent_acronym}-") or cortical_layer):
            return current
        current = parent


def _region_index_by_id(regions: Any, region_id: int) -> int | None:
    indices = np.flatnonzero(regions.id == region_id)
    return int(indices[0]) if len(indices) == 1 else None


def area_annotations(
    locations: Iterable[str],
    *,
    brain_regions: Any | None = None,
) -> pd.DataFrame:
    """Map detailed ``brain_structure`` acronyms to ``brain_area`` and ``brain_division``.

    Acronyms absent from the Allen ontology (``unknown``, empty strings) get null for
    both. Ontology regions outside the twelve major divisions (fiber tracts, ventricles,
    ``root``, ``void``) get ``brain_division == "Other"``.
    """

    if brain_regions is None:
        from iblatlas.regions import BrainRegions

        brain_regions = BrainRegions()
    major_divisions = set(ALLEN_MAJOR_DIVISIONS)
    records = []
    for location in sorted(set(locations)):
        index = _region_index(brain_regions, location)
        if index is None:
            area = division = None
        else:
            ancestors = list(brain_regions.ancestors(int(brain_regions.id[index])).acronym)
            division = next(
                (name for name in reversed(ancestors) if name in major_divisions), "Other"
            )
            area = str(brain_regions.acronym[_parent_area_index(brain_regions, index)])
        records.append(
            {"brain_structure": location, "brain_area": area, "brain_division": division}
        )
    return pd.DataFrame(records, columns=["brain_structure", "brain_area", "brain_division"])


def qc_pass_mask(table: pd.DataFrame) -> pd.Series:
    """Return the manuscript QC rule; units with any missing metric fail."""

    return (
        table["isi_violations_ratio"].lt(QC_THRESHOLDS["isi_violations_ratio_max"])
        & table["presence_ratio"].gt(QC_THRESHOLDS["presence_ratio_min"])
        & table["amplitude_cutoff"].lt(QC_THRESHOLDS["amplitude_cutoff_max"])
    )


def build_unit_table(
    frames: Iterable[pd.DataFrame],
    *,
    brain_regions: Any | None = None,
) -> pd.DataFrame:
    """Combine per-session rows, add areas and ``qc_pass``, and fix order and dtypes."""

    table = pd.concat(list(frames), ignore_index=True)
    known = table["brain_structure"].dropna().unique()
    areas = area_annotations(known, brain_regions=brain_regions)
    table = table.merge(areas, on="brain_structure", how="left", validate="many_to_one")
    table["qc_pass"] = qc_pass_mask(table)
    table = table.sort_values(["session_id", "nwb_unit_index"], kind="stable")
    table = table.reset_index(drop=True)
    for column in (
        "session_id",
        "subject_id",
        "asset_id",
        "probe",
        "decoder_label",
        "brain_division",
        "brain_area",
        "brain_structure",
    ):
        table[column] = table[column].astype("category")
    table["unit_id"] = table["unit_id"].astype("string")
    table["default_qc"] = table["default_qc"].astype("boolean")
    table["num_spikes"] = table["num_spikes"].astype("Int64")
    leading = [
        "session_id",
        "asset_id",
        "subject_id",
        "unit_id",
        "nwb_unit_index",
        "probe",
        "decoder_label",
        "qc_pass",
        "default_qc",
        "brain_division",
        "brain_area",
        "brain_structure",
        "ccf_ap_um",
        "ccf_dv_um",
        "ccf_ml_um",
        "num_spikes",
    ]
    return table[[*leading, *FLOAT_METRICS]]


def write_unit_table(
    table: pd.DataFrame,
    *,
    assets: Iterable[Mapping[str, Any]],
    skipped: list[dict[str, str]],
    output_dir: Path,
    retrieved_date: str | None = None,
) -> tuple[Path, Path]:
    """Write the unit table and its provenance into ``output_dir``."""

    output_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = output_dir / UNIT_TABLE_NAME
    provenance_path = output_dir / UNIT_TABLE_PROVENANCE_NAME
    table.to_parquet(parquet_path, index=False, compression="zstd")

    asset_manifest = [
        {key: asset.get(key) for key in ("asset_id", "asset_path", "modified", "size", "digest")}
        for asset in assets
    ]
    provenance = {
        "version": UNIT_TABLE_VERSION,
        "script": "scripts/extract_neuropixels_units.py",
        "module": "src/openscope_p3_publication/units.py",
        "dandiset_id": DANDISET_ID,
        "dandiset_version": DANDISET_VERSION,
        "source_url": f"https://dandiarchive.org/dandiset/{DANDISET_ID}/{DANDISET_VERSION}/files",
        "retrieved_date": retrieved_date or dt.date.today().isoformat(),
        "output_path": parquet_path.name,
        "output_sha256": hashlib.sha256(parquet_path.read_bytes()).hexdigest(),
        "rows": len(table),
        "sessions": int(table["session_id"].nunique()),
        "decoder_label_counts": {
            str(label): int(count)
            for label, count in table["decoder_label"].value_counts().sort_index().items()
        },
        "qc_pass_units": int(table["qc_pass"].sum()),
        "qc_thresholds": QC_THRESHOLDS,
        "columns": {
            "unit_id": "units/unit_name (falls back to units/id); joins per-unit snapshots",
            "nwb_unit_index": "row position in the NWB units table",
            "probe": "units/device_name",
            "qc_pass": (
                "isi_violations_ratio < 0.5 and presence_ratio > 0.8 and "
                "amplitude_cutoff < 0.1"
            ),
            "brain_division": (
                "Allen major division ancestor of brain_structure (e.g. Isocortex, TH, HPF); "
                "'Other' for ontology regions outside the twelve divisions; null outside "
                "the ontology"
            ),
            "brain_area": (
                "brain_structure with cortical layers and hyphenated sub-parcels collapsed "
                "via the Allen ontology (e.g. VISp2/3 -> VISp, DG-mo -> DG; iblatlas "
                "BrainRegions); null outside the ontology"
            ),
            "brain_structure": (
                "fully detailed electrodes/location at the unit's extremum channel "
                "(e.g. VISp2/3); null when unresolved"
            ),
            "ccf_*_um": (
                "electrodes x/y/z at the extremum channel, Allen CCF micrometres in "
                "AP/DV/ML order (see docs/neuropixels-area-label-provenance.md)"
            ),
            "metrics": "copied from the NWB units table as float32; NaN when absent",
        },
        "asset_manifest": asset_manifest,
        "asset_manifest_sha256": hashlib.sha256(
            json.dumps(asset_manifest, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest(),
        "skipped_sessions": skipped,
    }
    provenance_path.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return parquet_path, provenance_path


def load_unit_table(data_dir: Path) -> pd.DataFrame:
    """Load the committed unit table from ``figure_sources/data``."""

    return pd.read_parquet(data_dir / UNIT_TABLE_NAME)
