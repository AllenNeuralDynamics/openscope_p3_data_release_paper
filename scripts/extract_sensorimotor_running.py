"""Measure locomotion during the sensorimotor mismatch block across the P3 release.

The sensorimotor block couples optic flow to the animal's locomotion, so a
mismatch event only exists as a stimulus when the animal is running. This reads
the processed running series and the sensorimotor interval tables from every
released Neuropixels and mesoscope session containing that block, and records
block-level speed plus the number of mismatch trials that qualify as running at
each threshold in the reported ladder.

Both modalities package the sensorimotor interval table and a 60 Hz cm/s
processed running series identically, so one code path covers them. SLAP2 is
declared unavailable: its running data is packaged as Harp encoder files on
project S3 rather than in the NWB.

Refresh (maintainer operation):

    uv run --with h5py --with numpy --with remfile \
        python scripts/extract_sensorimotor_running.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import statistics
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from openscope_p3_publication.sensorimotor_running import (  # noqa: E402
    BASELINE_SECONDS,
    DEFAULT_RUNNING_THRESHOLD_CM_S,
    MINIMUM_QUALIFYING_TRIALS,
    RUNNING_THRESHOLDS_CM_S,
    forward_speed,
    summarize_session,
)

DEFAULT_OUTPUT = REPO_ROOT / "figure_sources" / "data" / "sensorimotor-running.json"
DEFAULT_PROVENANCE_OUTPUT = DEFAULT_OUTPUT.with_suffix(".provenance.json")
DANDI_API = "https://api.dandiarchive.org/api"
DANDI_VERSION = "draft"
# Neuropixels and mesoscope NWBs share the sensorimotor interval table and the
# processed running series, so one code path covers both. SLAP2 running lives in
# Harp encoder files on project S3 rather than in the NWB, needs wheel
# calibration and stimulus alignment, and is declared unavailable here.
DANDISETS = {
    "neuropixels": "001637",
    "mesoscope": "001768",
}
UNAVAILABLE_MODALITIES = {
    "slap2": {
        "dandiset_id": "001424",
        "reason": (
            "SLAP2 running is packaged as Harp encoder files on project S3 rather "
            "than as an NWB processed running series, and requires wheel "
            "calibration and stimulus alignment"
        ),
    },
}
PAYLOAD_VERSION = 2
CONTEXT_TABLE = "Sensory-motor mismatch block_presentations"
CONTROL_TABLE = "Control block 4_presentations"
MISMATCH_TYPES = (
    "motor_orientation_45",
    "motor_orientation_90",
    "motor_halt",
    "motor_omission",
)
RUNNING_SERIES = "processing/running/running_speed"
ACCEPTED_UNITS = {"cm/s", "cmps"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--provenance-output", type=Path, default=DEFAULT_PROVENANCE_OUTPUT
    )
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--retrieved-date", default=dt.date.today().isoformat())
    return parser.parse_args()


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.load(response)


def list_assets() -> tuple[list[dict], dict[str, str], str]:
    """Every NWB asset across the covered dandisets, tagged with its modality."""
    assets: list[dict] = []
    urls: dict[str, str] = {}
    for modality, dandiset_id in DANDISETS.items():
        url = (
            f"{DANDI_API}/dandisets/{dandiset_id}/versions/{DANDI_VERSION}"
            "/assets/?page_size=100"
        )
        urls[modality] = url
        page_url = url
        while page_url:
            page = fetch_json(page_url)
            for asset in page["results"]:
                if asset["path"].endswith(".nwb"):
                    assets.append(
                        {**asset, "modality": modality, "dandiset_id": dandiset_id}
                    )
            page_url = page["next"]
    assets.sort(key=lambda asset: (asset["modality"], asset["path"]))
    manifest = json.dumps(
        [[a["modality"], a["asset_id"], a["path"]] for a in assets],
        separators=(",", ":"),
    )
    return assets, urls, hashlib.sha256(manifest.encode()).hexdigest()


def decode_attribute(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def mismatch_onsets(
    group,
) -> tuple[np.ndarray, np.ndarray, list[str], tuple[float, float]]:
    """Mismatch onsets, offsets, labels, and the full block span from the table."""
    trial_type = np.asarray(group["TrialType"][:]).astype("U")
    start = np.asarray(group["start_time"][:], dtype=float)
    stop = np.asarray(group["stop_time"][:], dtype=float)
    selected = np.flatnonzero(np.isin(trial_type, list(MISMATCH_TYPES)))
    block = (float(start.min()), float(stop.max()))
    return start[selected], stop[selected], trial_type[selected].tolist(), block


def inspect_asset(asset: dict) -> dict | None:
    import h5py
    import remfile

    url = f"{DANDI_API}/assets/{asset['asset_id']}/download/"
    with closing(remfile.File(url)) as remote, h5py.File(remote, "r") as nwb:
        if "intervals" not in nwb or CONTEXT_TABLE not in set(nwb["intervals"]):
            return None
        record: dict = {
            "asset_id": asset["asset_id"],
            "asset_path": asset["path"],
            "dandiset_id": asset["dandiset_id"],
            "modality": asset["modality"],
            "subject": str(nwb["general/subject/subject_id"][()].decode()),
        }
        try:
            record["session_id"] = str(nwb["general/session_id"][()].decode())
        except KeyError:
            record["session_id"] = asset["path"].rsplit("/", 1)[-1]

        if RUNNING_SERIES not in nwb:
            record["error"] = "NWB processed running series unavailable"
            return record

        series = nwb[RUNNING_SERIES]
        velocity = np.asarray(series["data"][:], dtype=float)
        times = np.asarray(series["timestamps"][:], dtype=float)
        unit = decode_attribute(
            series["data"].attrs.get("unit", series.attrs.get("unit", ""))
        )
        if unit.lower().replace(" ", "") not in ACCEPTED_UNITS:
            raise RuntimeError(f"Unsupported running unit {unit!r} in {asset['path']}")

        finite = np.isfinite(times) & np.isfinite(velocity)
        times, velocity = times[finite], velocity[finite]
        order = np.argsort(times, kind="stable")
        times, velocity = times[order], velocity[order]
        forward = forward_speed(velocity)

        record["running_unit"] = unit
        record["running_sample_rate_hz"] = (
            round(float(1.0 / np.median(np.diff(times))), 3) if len(times) > 1 else None
        )
        onsets, offsets, labels, block = mismatch_onsets(
            nwb[f"intervals/{CONTEXT_TABLE}"]
        )
        record["context"] = summarize_session(
            times, forward, onsets, offsets, labels, block_window=block
        )
        if CONTROL_TABLE in set(nwb["intervals"]):
            c_onsets, c_offsets, c_labels, c_block = mismatch_onsets(
                nwb[f"intervals/{CONTROL_TABLE}"]
            )
            if len(c_onsets):
                record["control"] = summarize_session(
                    times, forward, c_onsets, c_offsets, c_labels, block_window=c_block
                )
        return record


def cohort_statistics(sessions: list[dict]) -> dict:
    usable = [s for s in sessions if "context" in s]
    means = [s["context"]["block"]["mean_cm_s"] for s in usable]
    by_modality: dict[str, dict] = {}
    for modality in DANDISETS:
        rows = [s for s in usable if s.get("modality") == modality]
        if not rows:
            continue
        modality_means = [s["context"]["block"]["mean_cm_s"] for s in rows]
        by_modality[modality] = {
            "sessions": len(rows),
            "subjects": len({s["subject"] for s in rows}),
            "block_mean_cm_s_median": round(statistics.median(modality_means), 4),
            "stationary_median_sessions": sum(
                1 for s in rows if s["context"]["block"]["median_cm_s"] == 0.0
            ),
        }
    stats: dict = {
        "sessions": len(sessions),
        "sessions_with_running": len(usable),
        "by_modality": by_modality,
        "block_mean_cm_s_median": round(statistics.median(means), 4) if means else None,
        "stationary_median_sessions": sum(
            1 for s in usable if s["context"]["block"]["median_cm_s"] == 0.0
        ),
        "by_threshold": {},
    }
    for threshold in RUNNING_THRESHOLDS_CM_S:
        key = f"{threshold:g}"
        available = [
            s for s in usable if s["context"]["thresholds"][key]["available"]
        ]
        stats["by_threshold"][key] = {
            "threshold_cm_s": float(threshold),
            "sessions_available": len(available),
            "available_subjects": sorted(s["subject"] for s in available),
        }
    return stats


def main() -> None:
    args = parse_args()
    assets, asset_api_urls, manifest_sha256 = list_assets()
    print(
        f"Scanning {len(assets)} assets across "
        f"{', '.join(f'{m} ({d})' for m, d in DANDISETS.items())}",
        flush=True,
    )

    sessions: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        futures = {pool.submit(inspect_asset, asset): asset for asset in assets}
        for done, future in enumerate(as_completed(futures), 1):
            record = future.result()
            if record is None:
                continue
            sessions.append(record)
            speed = record.get("context", {}).get("block", {}).get("mean_cm_s")
            shown = f"{speed:.2f} cm/s" if speed is not None else record.get("error", "")
            print(
                f"  [{done}/{len(assets)}] {record['modality']} "
                f"{record['subject']}: {shown}",
                flush=True,
            )

    if not sessions:
        raise RuntimeError("No sensorimotor blocks were found in the released assets.")
    sessions.sort(
        key=lambda record: -record.get("context", {}).get("block", {}).get("mean_cm_s", -1)
    )

    payload = {
        "version": PAYLOAD_VERSION,
        "analysis": {
            "baseline_seconds": BASELINE_SECONDS,
            "default_threshold_cm_s": DEFAULT_RUNNING_THRESHOLD_CM_S,
            "gate": (
                "mean forward speed >= threshold in both the pre-event baseline "
                "window and the mismatch window"
            ),
            "minimum_qualifying_trials": MINIMUM_QUALIFYING_TRIALS,
            "running_series": RUNNING_SERIES,
            "thresholds_cm_s": list(RUNNING_THRESHOLDS_CM_S),
        },
        "modalities": {
            "covered": {m: {"dandiset_id": d} for m, d in DANDISETS.items()},
            "unavailable": UNAVAILABLE_MODALITIES,
        },
        "cohort": cohort_statistics(sessions),
        "sessions": sessions,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )

    provenance = {
        "asset_api_urls": asset_api_urls,
        "asset_count": len(assets),
        "asset_manifest_sha256": manifest_sha256,
        "dandisets": DANDISETS,
        "dandiset_version": DANDI_VERSION,
        "unavailable_modalities": UNAVAILABLE_MODALITIES,
        "notes": (
            "Neuropixels and mesoscope NWBs package the sensorimotor interval table "
            "and the processed running series identically, so one code path covers "
            "both; SLAP2 is declared unavailable because its running data lives in "
            "Harp encoder files on project S3. The running series and interval tables "
            "are streamed with remfile; no spike or imaging data is read. "
            "Forward speed clips negative "
            "velocity to zero. A mismatch trial qualifies as running only when the mean "
            "forward speed reaches the threshold in both the preceding baseline window "
            "and the mismatch window, because a closed-loop mismatch requires flow to "
            "have been present before it was decoupled. Block running fractions use a "
            "strict comparison to stay comparable with running-statistics.json."
        ),
        "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "retrieved_date": args.retrieved_date,
        "sessions": len(sessions),
        "source_module_sha256": hashlib.sha256(
            (REPO_ROOT / "src" / "openscope_p3_publication" / "sensorimotor_running.py")
            .read_bytes()
        ).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    args.provenance_output.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote {args.output.relative_to(REPO_ROOT)}")
    print(f"Wrote provenance to {args.provenance_output.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
