"""All joint-responsive orientation examples in five non-visual parent regions."""

from __future__ import annotations

import json
import math
from pathlib import Path

from .standard_oddball_examples import load_example_spikes, render_example_gallery
from .standard_oddball_neuropixels import (
    DATA_PATH,
    REPO_ROOT,
    Diagnostic,
    _sha256,
    _write_csv,
    joint_example_mask,
    load_diagnostic,
)

REGIONS = ("ACAd", "CA1", "MOs", "PL", "SSp")
ORIENTATIONS = ("orientation_45", "orientation_90")
REGIONAL_PATH = DATA_PATH.with_name("neuropixels-standard-oddball-regional-examples.json")
REGIONAL_PROVENANCE = REGIONAL_PATH.with_suffix(".provenance.json")
REGIONAL_OUTPUT_DIR = (
    REPO_ROOT / "images/figures/generated/neuropixels-standard-oddball-regional-examples"
)
REGIONAL_AUDIT_DIR = REPO_ROOT / "figure_sources/derived/neuropixels-standard-oddball-regional"
REGIONAL_SELECTION_RULE = (
    "all QC-passing SUA with firingRateHz > 1 in ACAd, CA1, MOs, PL, SSp; "
    "BOTH Q1 and baseline-subtracted Q2, each p < 0.05 and abs(MI) > 0.1, "
    "for the SAME 45- or 90-degree event; union across orientations; "
    "region then unit ID order; exploratory, not BH-selected"
)


def regional_selections(data: Diagnostic) -> list[dict]:
    """Select every eligible joint responder once, retaining both orientations."""
    joint = joint_example_mask(data)
    records = []
    for region in REGIONS:
        indices = sorted(
            (i for i, unit in enumerate(data.units) if unit["parentArea"] == region),
            key=lambda i: data.units[i]["id"],
        )
        if not indices:
            raise ValueError(f"No eligible units for requested region {region}.")
        for i in indices:
            passing = [event for e, event in enumerate(ORIENTATIONS) if joint[e, i]]
            if passing:
                unit = data.units[i]
                records.append({
                    "index": i, "unit_id": unit["id"], "label": unit["location"],
                    "parent_area": region, "passing_events": passing,
                })
    return records


def load_regional_spikes(data: Diagnostic) -> dict:
    """Load and validate the committed all-responder orientation spike snapshot."""
    return load_example_spikes(
        data, REGIONAL_PATH, REGIONAL_PROVENANCE, selection=regional_selections(data),
        selection_rule=REGIONAL_SELECTION_RULE, event_ids=ORIENTATIONS,
    )


def build_regional_gallery(
    output_dir: Path = REGIONAL_OUTPUT_DIR, audit_dir: Path = REGIONAL_AUDIT_DIR,
) -> list[Path]:
    """Build every responder's two-orientation raster/mean page entirely offline."""
    data = load_diagnostic(visual_only=False)
    payload = load_regional_spikes(data)
    paths = []
    for region in REGIONS:
        pairs = [
            (selection, unit)
            for selection, unit in zip(payload["selection"], payload["units"], strict=True)
            if selection["parent_area"] == region
        ]
        region_payload = {
            **payload, "selection": [s for s, _ in pairs], "units": [u for _, u in pairs],
        }
        paths.extend(render_example_gallery(
            data, region_payload, output_dir / region, bin_seconds=0.005, tau_seconds=0.025,
        ))
    joint = joint_example_mask(data)
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_path = audit_dir / "unit-statistics.csv"
    rows = []
    for selection in payload["selection"]:
        i = selection["index"]
        for e, event in enumerate(ORIENTATIONS):
            rows.append({
                "session_id": data.session["sessionId"], "unit_id": selection["unit_id"],
                "parent_area": selection["parent_area"], "recorded_area": selection["label"],
                "event_id": event, "passes_both": bool(joint[e, i]),
                **{
                    key: float(values[e, i]) if math.isfinite(values[e, i]) else None
                    for key, values in data.statistics.items()
                },
            })
    _write_csv(audit_path, rows)
    sources = [
        Path(__file__), Path(__file__).with_name("standard_oddball_examples.py"),
        Path(__file__).with_name("standard_oddball_neuropixels.py"),
        Path(__file__).with_name("figure_typography.py"),
        Path(__file__).with_name("image_encoding.py"),
        REGIONAL_PATH, REGIONAL_PROVENANCE,
    ]
    provenance = {
        "version": 1, "session_id": data.session["sessionId"], "asset": data.session["asset"],
        "selection_rule": REGIONAL_SELECTION_RULE, "selection": payload["selection"],
        "counts": {
            region: sum(s["parent_area"] == region for s in payload["selection"])
            for region in REGIONS
        },
        "sdf": {"bin_seconds": 0.005, "tau_seconds": 0.025, "support_tau": 10},
        "trials": "clean context and all matched control; rasters and means use identical trials",
        "sources": [
            {"path": str(path.relative_to(REPO_ROOT)), "sha256": _sha256(path)}
            for path in sources
        ],
        "outputs": [
            {"path": str(path.relative_to(output_dir)), "sha256": _sha256(path)}
            for path in paths
        ],
        "audit": {"name": audit_path.name, "sha256": _sha256(audit_path)},
    }
    provenance_path = audit_dir / "provenance.json"
    provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    return [*paths, audit_path, provenance_path]


if __name__ == "__main__":
    for output in build_regional_gallery():
        print(f"Wrote {output}")
