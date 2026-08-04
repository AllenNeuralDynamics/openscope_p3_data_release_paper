#!/usr/bin/env python3
"""Extract all public Neuropixels trajectories and a compact CCF brain surface."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from pathlib import Path

try:
    import h5py
    import nrrd
    import numpy as np
    import remfile
    from skimage import measure
except ImportError as exc:  # pragma: no cover - optional extraction environment
    raise SystemExit(
        "Run with: uv run --with h5py --with numpy --with pynrrd --with remfile "
        "--with scikit-image python scripts/extract_neuropixels_trajectories.py"
    ) from exc


REPO_ROOT = Path(__file__).resolve().parents[1]
SESSION_RECORDS_PATH = (
    REPO_ROOT / "figure_sources" / "data" / "neuropixels-unit-yield.csv"
)
SESSION_PROVENANCE_PATH = SESSION_RECORDS_PATH.with_suffix(".provenance.json")
DEFAULT_OUTPUT = (
    REPO_ROOT / "figure_sources" / "data" / "neuropixels-trajectories.json"
)
DEFAULT_PROVENANCE_OUTPUT = DEFAULT_OUTPUT.with_suffix(".provenance.json")
DANDISET_ID = "001637"
DANDI_VERSION = "draft"
DANDI_ASSET_URL = "https://api.dandiarchive.org/api/assets/{asset_id}/download/"
CCF_ANNOTATION_URL = (
    "https://download.alleninstitute.org/informatics-archive/current-release/"
    "mouse_ccf/annotation/ccf_2017/annotation_25.nrrd"
)
CCF_STRUCTURE_GRAPH_URL = (
    "https://api.brain-map.org/api/v2/structure_graph_download/1.json"
)
RETRIEVED_DATE = "2026-08-03"
CCF_VOXEL_SIZE_UM = 25
BRAIN_MESH_RESOLUTION_UM = 100
PROBE_COLORS = {
    "A": "#D1495B",
    "B": "#00798C",
    "C": "#EDAE49",
    "D": "#5C4D9A",
    "E": "#2A9D6F",
    "F": "#E76F51",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--provenance-output", type=Path, default=DEFAULT_PROVENANCE_OUTPUT
    )
    parser.add_argument("--max-workers", type=int, default=8)
    return parser.parse_args()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def fetch_bytes(url: str) -> tuple[bytes, dict[str, str | int | None]]:
    request = urllib.request.Request(url, headers={"User-Agent": "openscope-p3-paper"})
    with urllib.request.urlopen(request, timeout=300) as response:
        content = response.read()
        metadata = {
            "contentLength": len(content),
            "contentType": response.headers.get("Content-Type"),
            "etag": response.headers.get("ETag", "").strip('"'),
            "lastModified": response.headers.get("Last-Modified"),
            "sha256": sha256_bytes(content),
            "url": url,
        }
    return content, metadata


def fetch_json(url: str) -> tuple[dict, dict[str, str | int | None]]:
    content, metadata = fetch_bytes(url)
    return json.loads(content), metadata


def decode_strings(values: np.ndarray) -> np.ndarray:
    return values.astype("U")


def structure_records(node: dict) -> list[dict]:
    records = [
        {
            "acronym": node["acronym"],
            "color": f"#{node['color_hex_triplet']}",
            "id": int(node["id"]),
            "name": node["name"],
        }
    ]
    for child in node.get("children", []):
        records.extend(structure_records(child))
    return records


def area_profile(
    locations: np.ndarray,
    relative_depths: np.ndarray,
    structures: dict[str, dict],
) -> list[dict]:
    ordered_depths = np.unique(relative_depths)[::-1]
    surface_depth = float(ordered_depths[0])
    samples = []
    previous_location = None
    for relative_depth in ordered_depths:
        labels, counts = np.unique(
            locations[relative_depths == relative_depth],
            return_counts=True,
        )
        candidates = labels[counts == counts.max()]
        location = (
            previous_location
            if previous_location in candidates
            else str(candidates[0])
        )
        samples.append((surface_depth - float(relative_depth), location))
        previous_location = location

    segments = []
    for sample_index, (depth, location) in enumerate(samples):
        if segments and segments[-1]["acronym"] == location:
            continue
        start_depth = (
            0.0
            if sample_index == 0
            else (samples[sample_index - 1][0] + depth) / 2
        )
        if segments:
            segments[-1]["endDepthUm"] = round(start_depth, 3)
        structure = structures.get(str(location), {})
        segments.append(
            {
                "acronym": str(location),
                "color": structure.get("color", "#A9B1B3"),
                "endDepthUm": round(start_depth, 3),
                "name": structure.get("name", str(location)),
                "startDepthUm": round(start_depth, 3),
            }
        )
    if segments:
        segments[-1]["endDepthUm"] = round(samples[-1][0], 3)
    return segments


def centerline_points(
    coordinates: np.ndarray,
    relative_depths: np.ndarray,
) -> list[list[int]]:
    points = []
    for relative_depth in np.unique(relative_depths)[::-1]:
        point = np.median(coordinates[relative_depths == relative_depth], axis=0)
        values = np.rint(point).astype(int).tolist()
        if not points or values != points[-1]:
            points.append(values)
    return points


def trim_exterior_void_contacts(
    coordinates: np.ndarray,
    relative_depths: np.ndarray,
    locations: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    non_void = locations != "void"
    if not np.any(non_void):
        raise RuntimeError("Probe trajectory contains no brain-area annotations.")
    minimum_depth = float(relative_depths[non_void].min())
    maximum_depth = float(relative_depths[non_void].max())
    retained = (relative_depths >= minimum_depth) & (relative_depths <= maximum_depth)
    return coordinates[retained], relative_depths[retained], locations[retained]


def extract_session(
    row: dict[str, str],
    structures: dict[str, dict],
) -> tuple[list[dict], dict | None]:
    asset_id = row["asset_id"]
    url = DANDI_ASSET_URL.format(asset_id=asset_id)
    with closing(remfile.File(url)) as remote:
        with h5py.File(remote, mode="r") as nwb:
            electrodes = nwb["general/extracellular_ephys/electrodes"]
            required = {"group_name", "location", "rel_y"}
            missing = sorted(required - set(electrodes))
            if missing:
                raise RuntimeError(
                    f"{row['session_id']} electrode table lacks: {', '.join(missing)}"
                )
            missing_coordinates = sorted({"x", "y", "z"} - set(electrodes))
            if missing_coordinates:
                return [], {
                    "asset_id": asset_id,
                    "path": row["asset_path"],
                    "reason": (
                        "missing-ccf-coordinates:"
                        f"{','.join(missing_coordinates)}"
                    ),
                    "session_id": row["session_id"],
                }
            groups = decode_strings(np.asarray(electrodes["group_name"][:]))
            locations = decode_strings(np.asarray(electrodes["location"][:]))
            relative_depths = np.asarray(electrodes["rel_y"][:], dtype=float)
            coordinates = np.column_stack(
                [
                    np.asarray(electrodes[axis][:], dtype=float)
                    for axis in ("x", "y", "z")
                ]
            )

    insertions = []
    for group_name in sorted(set(groups)):
        probe_id = str(group_name).removeprefix("Probe")
        if probe_id not in PROBE_COLORS:
            continue
        mask = groups == group_name
        probe_coordinates = coordinates[mask]
        finite = np.all(np.isfinite(probe_coordinates), axis=1) & np.isfinite(
            relative_depths[mask]
        )
        if np.count_nonzero(finite) < 2:
            raise RuntimeError(
                f"{row['session_id']} {group_name} lacks a finite CCF trajectory."
            )
        probe_coordinates = probe_coordinates[finite]
        probe_depths = relative_depths[mask][finite]
        probe_locations = locations[mask][finite]
        probe_coordinates, probe_depths, probe_locations = trim_exterior_void_contacts(
            probe_coordinates,
            probe_depths,
            probe_locations,
        )
        points = centerline_points(probe_coordinates, probe_depths)
        insertions.append(
            {
                "areas": area_profile(probe_locations, probe_depths, structures),
                "assetId": asset_id,
                "color": PROBE_COLORS[probe_id],
                "date": row["date"],
                "id": f"{row['session_id']}-probe-{probe_id.lower()}",
                "lengthUm": round(float(np.ptp(probe_depths)), 3),
                "mouseId": row["mouse_id"],
                "points": points,
                "probe": probe_id,
                "sessionId": row["session_id"],
                "sourcePath": row["asset_path"],
            }
        )
    if not insertions:
        raise RuntimeError(f"{row['session_id']} contains no supported probes.")
    return insertions, None


def brain_surface(annotation_bytes: bytes) -> dict:
    with tempfile.NamedTemporaryFile(suffix=".nrrd") as temporary:
        temporary.write(annotation_bytes)
        temporary.flush()
        annotation, header = nrrd.read(temporary.name)
    if annotation.ndim != 3:
        raise RuntimeError(f"Unexpected CCF annotation shape: {annotation.shape}")
    factor = BRAIN_MESH_RESOLUTION_UM // CCF_VOXEL_SIZE_UM
    if any(dimension % factor for dimension in annotation.shape):
        raise RuntimeError(
            f"CCF dimensions are not divisible by mesh factor {factor}: "
            f"{annotation.shape}"
        )
    coarse_shape = tuple(dimension // factor for dimension in annotation.shape)
    mask = annotation > 0
    coarse = mask.reshape(
        coarse_shape[0],
        factor,
        coarse_shape[1],
        factor,
        coarse_shape[2],
        factor,
    ).max(axis=(1, 3, 5))
    vertices, faces, _, _ = measure.marching_cubes(
        coarse.astype(np.uint8),
        level=0.5,
        spacing=(
            BRAIN_MESH_RESOLUTION_UM,
            BRAIN_MESH_RESOLUTION_UM,
            BRAIN_MESH_RESOLUTION_UM,
        ),
        step_size=1,
        allow_degenerate=False,
    )
    return {
        "annotationShape": list(annotation.shape),
        "annotationSpace": header.get("space", "unknown"),
        "faces": faces.astype(int).tolist(),
        "meshResolutionUm": BRAIN_MESH_RESOLUTION_UM,
        "vertices": np.rint(vertices).astype(int).tolist(),
    }


def main() -> None:
    args = parse_args()
    session_bytes = SESSION_RECORDS_PATH.read_bytes()
    session_provenance_bytes = SESSION_PROVENANCE_PATH.read_bytes()
    with SESSION_RECORDS_PATH.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise RuntimeError("Neuropixels session inventory is empty.")

    structure_graph, structure_source = fetch_json(CCF_STRUCTURE_GRAPH_URL)
    roots = structure_graph.get("msg", [])
    if len(roots) != 1:
        raise RuntimeError("Allen CCF structure graph does not contain one root.")
    structure_list = structure_records(roots[0])
    structures = {record["acronym"]: record for record in structure_list}
    annotation_bytes, annotation_source = fetch_bytes(CCF_ANNOTATION_URL)

    exclusions = []
    insertions = []
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {
            executor.submit(extract_session, row, structures): row for row in rows
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            row = futures[future]
            records, exclusion = future.result()
            insertions.extend(records)
            if exclusion:
                exclusions.append(exclusion)
            detail = (
                f"{len(records)} trajectories" if records else exclusion["reason"]
            )
            print(
                f"[{completed}/{len(rows)}] {row['session_id']}: {detail}",
                flush=True,
            )
    exclusions.sort(key=lambda row: row["session_id"])
    insertions.sort(key=lambda row: (row["mouseId"], row["date"], row["probe"]))

    payload = {
        "brainSurface": brain_surface(annotation_bytes),
        "coordinateSystem": {
            "axes": [
                {"field": "x", "label": "Anterior-posterior", "unit": "um"},
                {"field": "y", "label": "Dorsal-ventral", "unit": "um"},
                {"field": "z", "label": "Medial-lateral", "unit": "um"},
            ],
            "name": "Allen Mouse Brain Common Coordinate Framework 2017",
        },
        "insertions": insertions,
        "probeColors": PROBE_COLORS,
        "retrievedDate": RETRIEVED_DATE,
        "summary": {
            "excludedSessions": len(exclusions),
            "insertions": len(insertions),
            "localizedSessions": len(rows) - len(exclusions),
            "sourceSessions": len(rows),
            "subjects": len({row["mouse_id"] for row in rows}),
        },
        "version": 1,
    }
    output_bytes = (
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output_bytes)

    provenance = {
        "ccf_annotation": annotation_source,
        "ccf_structure_graph": structure_source,
        "dandiset_id": DANDISET_ID,
        "dandiset_version": DANDI_VERSION,
        "exclusions": exclusions,
        "notes": (
            "Each trajectory follows finite electrode x/y/z coordinates in the "
            "session NWB CCF frame. Area profiles follow contiguous electrode "
            "location annotations from the dorsal shank end toward the tip."
        ),
        "retrieved_date": RETRIEVED_DATE,
        "session_inventory_sha256": sha256_bytes(session_bytes),
        "session_provenance_sha256": sha256_bytes(session_provenance_bytes),
        "localized_sessions": len(rows) - len(exclusions),
        "source_sessions": len(rows),
        "subjects": payload["summary"]["subjects"],
        "trajectories": len(insertions),
        "vendored_sha256": sha256_bytes(output_bytes),
        "version": 1,
    }
    args.provenance_output.write_text(
        json.dumps(provenance, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {args.output} with {len(insertions)} trajectories and "
        f"{len(payload['brainSurface']['faces'])} brain-surface faces"
    )


if __name__ == "__main__":
    main()