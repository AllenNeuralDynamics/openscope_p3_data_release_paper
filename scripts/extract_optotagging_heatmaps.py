#!/usr/bin/env python3
"""Extract all-session optotagging heatmaps from public DANDI NWBs."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    from openscope_p3_publication.optotagging import (
        ATLAS_DISPLAY_BINS,
        ATLAS_NAN_SENTINEL,
        ATLAS_QUANTIZATION_SCALE,
        CONDITION_DISPLAY_NAMES,
        CONDITIONS,
        DANDISET_ID,
        DANDISET_VERSION,
        PSTH_BIN_SECONDS,
        PSTH_WINDOW,
        SessionSkipped,
        analyze_asset,
        build_session_numeric_atlas,
        discover_session_assets,
    )
except ImportError as exc:  # pragma: no cover - optional extraction environment
    raise SystemExit(
        "Run with: uv run --with dandi --with h5py --with iblatlas "
        "--with iblutil --with matplotlib --with numpy --with pandas "
        "--with pillow --with remfile --with scipy "
        "python scripts/extract_optotagging_heatmaps.py"
    ) from exc


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MEDIA_DIR = REPO_ROOT / "figure_sources" / "media" / "optotagging"
DEFAULT_MANIFEST = REPO_ROOT / "figure_sources" / "data" / "optotagging-heatmaps.json"
DEFAULT_PROVENANCE = DEFAULT_MANIFEST.with_suffix(".provenance.json")
REPRESENTATIVE_SESSIONS = {
    "ecephys_830851_2026-03-19_10-49-11": {
        "target_yield_percentile": 0.50,
        "optotagged_cell_count": 39,
    },
    "ecephys_848390_2026-05-06_09-54-56": {
        "target_yield_percentile": 0.80,
        "optotagged_cell_count": 68,
    },
    "ecephys_832691_2026-03-24_10-04-30": {
        "target_yield_percentile": 0.95,
        "optotagged_cell_count": 84,
    },
}
DEFAULT_SESSION_ID = "ecephys_830851_2026-03-19_10-49-11"
SESSION_FILENAME_PATTERN = re.compile(r"[^a-zA-Z0-9_.-]+")


def atlas_filename(session_id: str, suffix: str) -> str:
    """Return a portable filename for one numeric session atlas asset."""

    safe_session_id = SESSION_FILENAME_PATTERN.sub("-", session_id).strip("-")
    if not safe_session_id:
        raise ValueError("Session ID cannot be converted to a safe filename.")
    return f"{safe_session_id}.atlas.{suffix}"


def extract_asset(asset: dict) -> tuple[dict, dict[str, bytes]]:
    """Analyze one DANDI session into a numeric atlas."""

    analysis = analyze_asset(asset, compute_p_values=False)
    atlas_metadata, atlas_png = build_session_numeric_atlas(analysis)
    atlas_png_file = atlas_filename(analysis.session_id, "png")
    atlas_metadata["numeric_png_file"] = atlas_png_file
    atlas_json = (
        json.dumps(atlas_metadata, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()
    condition_counts = {
        condition.table_name: {
            "presentations": analysis.trial_counts[condition.table_name],
            "pulses": analysis.pulse_counts[condition.table_name],
        }
        for condition in CONDITIONS
    }
    record = {
        "asset_id": analysis.asset_id,
        "asset_path": analysis.asset_path,
        "atlas_file": atlas_filename(analysis.session_id, "json"),
        "atlas_sha256": hashlib.sha256(atlas_json).hexdigest(),
        "numeric_png_file": atlas_png_file,
        "numeric_png_sha256": hashlib.sha256(atlas_png).hexdigest(),
        "session_id": analysis.session_id,
        "unit_count": analysis.unit_count,
        "condition_counts": condition_counts,
    }
    return record, {
        record["atlas_file"]: atlas_json,
        atlas_png_file: atlas_png,
    }


def extract_assets(
    assets: list[dict],
    *,
    max_workers: int,
) -> tuple[list[tuple[dict, dict[str, bytes]]], list[dict], list[dict]]:
    """Extract selected assets while preserving explicit skip and failure records."""

    extracted = []
    skipped = []
    failed = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(extract_asset, asset): asset for asset in assets
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            asset = futures[future]
            try:
                record, files = future.result()
            except SessionSkipped as exc:
                skipped.append(
                    {
                        "asset_id": asset["asset_id"],
                        "asset_path": asset["asset_path"],
                        "reason": str(exc),
                    }
                )
                detail = f"skipped: {exc}"
            except Exception as exc:  # noqa: BLE001 - surfaced in the publication provenance
                failed.append(
                    {
                        "asset_id": asset["asset_id"],
                        "asset_path": asset["asset_path"],
                        "error_type": type(exc).__name__,
                        "reason": str(exc),
                    }
                )
                detail = f"failed: {type(exc).__name__}: {exc}"
            else:
                extracted.append((record, files))
                detail = f"{record['unit_count']} units"
            print(f"[{completed}/{len(assets)}] {asset['asset_path']}: {detail}")

    extracted.sort(key=lambda item: item[0]["session_id"])
    skipped.sort(key=lambda item: item["asset_path"])
    failed.sort(key=lambda item: item["asset_path"])
    return extracted, skipped, failed


def write_snapshot(
    extracted: list[tuple[dict, dict[str, bytes]]],
    *,
    assets: list[dict],
    skipped: list[dict],
    failed: list[dict],
    media_dir: Path,
    manifest_path: Path,
    provenance_path: Path,
    source_session_count: int | None = None,
    default_session_id: str | None = DEFAULT_SESSION_ID,
) -> tuple[Path, Path]:
    """Write per-session numeric atlases, compact manifest, and provenance."""

    if not extracted:
        raise ValueError("No optotagging sessions were extracted.")
    session_ids = {record["session_id"] for record, _ in extracted}
    if default_session_id is None:
        default_session_id = min(session_ids)
    elif default_session_id not in session_ids:
        raise ValueError(f"Default session is missing from extraction: {default_session_id}")

    media_dir.mkdir(parents=True, exist_ok=True)
    expected_filenames = set()
    sessions = []
    for record, files in extracted:
        for filename in (record["atlas_file"], record["numeric_png_file"]):
            (media_dir / filename).write_bytes(files[filename])
            expected_filenames.add(filename)
        sessions.append(record)
    for suffix in ("*.png", "*.webp", "*.json"):
        for stale_asset in media_dir.glob(suffix):
            if stale_asset.name not in expected_filenames:
                stale_asset.unlink()

    manifest = {
        "version": 2,
        "default_session_id": default_session_id,
        "static_example_session_id": DEFAULT_SESSION_ID,
        "session_count": len(sessions),
        "total_unit_count": sum(record["unit_count"] for record in sessions),
        "selection": {
            "strategy": "nearest_all_session_optotagged_cell_yield_percentiles",
            "source_session_count": source_session_count or len(assets),
            "sessions": {
                session_id: REPRESENTATIVE_SESSIONS[session_id]
                for session_id in sorted(session_ids)
                if session_id in REPRESENTATIVE_SESSIONS
            },
        },
        "conditions": [
            {
                "table_name": condition.table_name,
                "display_name": CONDITION_DISPLAY_NAMES[condition.table_name],
                "pulse_frequency_hz": condition.pulse_frequency_hz,
                "pulse_width_seconds": condition.pulse_width_seconds,
                "count_window_seconds": condition.count_window_seconds,
                "post_delay_seconds": condition.post_delay_seconds,
                "ordering": "mean_firing_rate_during_exact_pulses",
            }
            for condition in CONDITIONS
        ],
        "psth": {
            "alignment": "presentation laser onset",
            "baseline": "time < 0 seconds",
            "bin_seconds": PSTH_BIN_SECONDS,
            "display_bin_count": ATLAS_DISPLAY_BINS,
            "color_limits_zscore": [-3, 3],
            "interactive_color_limit_range": [0.5, 8],
            "interactive_color_limit_step": 0.5,
            "window_seconds": list(PSTH_WINDOW),
            "storage": (
                "baseline-zscored contiguous-bin means, clipped to [-8, 8], "
                f"quantized to signed int8 at 1/{ATLAS_QUANTIZATION_SCALE:g} "
                f"z-score per step, with NaN sentinel {ATLAS_NAN_SENTINEL}, "
                "in a lossless single-channel PNG"
            ),
        },
        "sessions": sessions,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    asset_manifest = [
        {
            key: asset.get(key)
            for key in ("asset_id", "asset_path", "modified", "size", "digest")
        }
        for asset in sorted(assets, key=lambda item: item["asset_path"])
    ]
    media_manifest = []
    for record in sessions:
        media_manifest.extend(
            [
                {"file": record["atlas_file"], "sha256": record["atlas_sha256"]},
                {
                    "file": record["numeric_png_file"],
                    "sha256": record["numeric_png_sha256"],
                },
            ]
        )
        if "image_file" in record:
            media_manifest.append(
                {"file": record["image_file"], "sha256": record["image_sha256"]}
            )
    try:
        manifest_display_path = manifest_path.relative_to(REPO_ROOT).as_posix()
        media_display_path = media_dir.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        manifest_display_path = str(manifest_path)
        media_display_path = str(media_dir)

    provenance = {
        "version": 2,
        "dandiset_id": DANDISET_ID,
        "dandiset_version": DANDISET_VERSION,
        "source_url": (
            f"https://dandiarchive.org/dandiset/{DANDISET_ID}/"
            f"{DANDISET_VERSION}/files"
        ),
        "retrieved_date": dt.date.today().isoformat(),
        "asset_manifest": asset_manifest,
        "asset_manifest_sha256": hashlib.sha256(
            json.dumps(asset_manifest, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest(),
        "manifest_path": manifest_display_path,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "media_path": media_display_path,
        "media_manifest_sha256": hashlib.sha256(
            json.dumps(media_manifest, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest(),
        "source_session_count": source_session_count or len(assets),
        "session_count": len(sessions),
        "total_unit_count": manifest["total_unit_count"],
        "skipped_assets": skipped,
        "failed_assets": failed,
        "unit_filter": "decoder_label != 'noise'",
        "notes": (
            "The three interactive sessions are nearest the 50th, 80th, and 95th "
            "percentiles of all-session optotagged-cell yield. Session NWBs are streamed "
            "from DANDI. Heatmaps show 1 ms presentation-aligned PSTHs baseline z-scored "
            "per unit and deterministically reduced to display resolution. Every "
            "condition is ordered by mean firing rate inside its exact laser pulses. "
            "Allen acronyms are mapped to major parent divisions through the iblatlas "
            "Allen hierarchy. The static yield summary covers all source sessions."
        ),
    }
    provenance_path.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path, provenance_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media-dir", type=Path, default=DEFAULT_MEDIA_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--provenance", type=Path, default=DEFAULT_PROVENANCE)
    parser.add_argument("--max-workers", type=int, default=2)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--session-id",
        help="Extract one session whose asset path contains this identifier.",
    )
    args = parser.parse_args()

    partial_extraction = args.limit is not None or args.session_id is not None
    uses_publication_paths = (
        args.media_dir.resolve() == DEFAULT_MEDIA_DIR.resolve()
        or args.manifest.resolve() == DEFAULT_MANIFEST.resolve()
        or args.provenance.resolve() == DEFAULT_PROVENANCE.resolve()
    )
    if partial_extraction and uses_publication_paths:
        raise SystemExit(
            "Partial extraction requires custom --media-dir, --manifest, and "
            "--provenance paths so it cannot overwrite the publication snapshot."
        )

    assets = discover_session_assets()
    if args.session_id:
        selected_assets = [
            asset for asset in assets if args.session_id in asset["asset_path"]
        ]
        if len(selected_assets) != 1:
            raise SystemExit(
                f"Expected one asset matching {args.session_id!r}; "
                f"found {len(selected_assets)}."
            )
    else:
        if args.limit:
            selected_assets = assets[: args.limit]
        else:
            selected_assets = [
                asset
                for asset in assets
                if any(
                    session_id in asset["asset_path"]
                    for session_id in REPRESENTATIVE_SESSIONS
                )
            ]
            if len(selected_assets) != len(REPRESENTATIVE_SESSIONS):
                raise SystemExit(
                    "Could not find every representative optotagging session in DANDI."
                )
    print(
        f"Dandiset {DANDISET_ID}: extracting "
        f"{len(selected_assets)} of {len(assets)} session assets"
    )
    extracted, skipped, failed = extract_assets(
        selected_assets,
        max_workers=args.max_workers,
    )
    manifest, provenance = write_snapshot(
        extracted,
        assets=selected_assets if partial_extraction else assets,
        skipped=skipped,
        failed=failed,
        media_dir=args.media_dir,
        manifest_path=args.manifest,
        provenance_path=args.provenance,
        source_session_count=len(selected_assets) if partial_extraction else len(assets),
        default_session_id=None if partial_extraction else DEFAULT_SESSION_ID,
    )
    print(f"Wrote {len(extracted)} session heatmaps to {args.media_dir}")
    print(f"Wrote manifest to {manifest}")
    print(f"Wrote provenance to {provenance}")
    if failed:
        raise SystemExit(
            f"Extraction completed with {len(failed)} failed assets; "
            "inspect the provenance before using this snapshot."
        )


if __name__ == "__main__":
    main()
