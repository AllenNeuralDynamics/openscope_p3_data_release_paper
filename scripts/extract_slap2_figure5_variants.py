#!/usr/bin/env python3
"""Extract the committed inputs of the two candidate SLAP2 Figure 5 layouts.

Reads versioned DANDI 001424 NWBs of the 12 glutamate-only sessions and writes compact tables to
`figure_sources/data/slap2-figure5-variants/`:

* `noise_only_amplitude_histogram.csv`: pooled amplitudes of detections on spectrum-matched
  surrogates. The surrogate is not valid for the 8 dual-channel sessions, whose traces are
  denoised and non-negative.
* `noise_only_source_rates.csv`: the noise-only event rate of each source.
* `example_source_amplitudes.csv`: event amplitudes of the sources at the 10th, 50th and 90th
  percentiles of median event amplitude in the example session.
* `provenance.json`: assets, parameters, exclusions and checksums.

Usage:
    uv run --with pynwb python scripts/extract_slap2_figure5_variants.py --cache /tmp/slap2_cache
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import urllib.request
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from openscope_p3_publication.slap2_glutamate_qc_events import (
    TAU_IGLUSNFR4F_S,
    baseline_noise,
    detect_events,
    drop_untimed_events,
    event_amplitudes_raw,
    resolve_layout,
    sampling_interval,
)
from openscope_p3_publication.slap2_noise_surrogate import (
    EVENT_SAMPLES_AFTER,
    EVENT_SAMPLES_BEFORE,
    surrogate_events,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = REPO_ROOT / "figure_sources/data/slap2-figure5-variants"
METRICS = REPO_ROOT / "figure_sources/data/slap2-glutamate-qc/slap2_metrics_all_sessions.csv"
ASSETS = REPO_ROOT / "figure_sources/media/slap2-glutamate-qc/example.provenance.json"
EXAMPLE_SESSION = "sub-794237_ses-20250508T145040"
CLASSES = ("Low SNR", "Intermediate", "High SNR")
AMPLITUDE = "median_event_raw_sd"
PERCENTILES = (10, 50, 90)
EDGES = np.round(np.arange(-5.0, 50.05, 0.1), 1)
SEED = 0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 24):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(asset: dict, cache: Path) -> Path:
    """Return a verified local copy of one DANDI asset, downloading it when absent."""
    path = cache / Path(asset["path"]).name
    if not path.exists():
        cache.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(path.suffix + ".part")
        request = urllib.request.Request(
            asset["content_url"][0], headers={"User-Agent": "openscope-p3-publication"},
        )
        with urllib.request.urlopen(request, timeout=300) as response, partial.open("wb") as out:
            shutil.copyfileobj(response, out, length=1 << 23)
        partial.rename(path)
    if sha256(path) != asset["digest"]["dandi:sha2-256"]:
        raise ValueError(f"{path.name}: checksum differs from the published DANDI digest.")
    return path


def select_examples(metrics: pd.DataFrame) -> list[tuple[int, int, int, float]]:
    """Return (percentile, dmd, roi, median) for the sources nearest each session percentile."""
    usable = metrics.loc[
        metrics.session.eq(EXAMPLE_SESSION) & metrics.quality_class.isin(CLASSES)
    ]
    picks = []
    for percentile in PERCENTILES:
        target = np.percentile(usable[AMPLITUDE], percentile)
        row = usable.loc[(usable[AMPLITUDE] - target).abs().idxmin()]
        picks.append((percentile, int(row.dmd), int(row.roi), float(row[AMPLITUDE])))
    return picks


def process_session(path: Path) -> tuple[list[dict], np.ndarray]:
    """Run one independently seeded surrogate per source of one session."""
    from pynwb import NWBHDF5IO

    session = path.name.replace("_image+ophys.nwb", "")
    rng = np.random.default_rng(SEED)
    rows, counts = [], np.zeros(EDGES.size - 1, dtype=np.int64)
    with NWBHDF5IO(str(path), "r", load_namespaces=True) as io:
        layout = resolve_layout(io.read())
        for dmd in layout["dmds"]:
            series = layout["dff_series"][dmd]
            dt = sampling_interval(np.asarray(series.timestamps))
            data = np.asarray(series.data, dtype=np.float32)
            for roi in range(data.shape[1]):
                rate, amplitudes = surrogate_events(data[:, roi], dt, rng)
                clipped = np.clip(amplitudes, EDGES[0], EDGES[-1] - 1e-6)
                counts += np.histogram(clipped, bins=EDGES)[0]
                rows.append({
                    "session": session, "dmd": dmd, "roi": roi,
                    "surrogate_event_rate_hz": rate, "surrogate_events": amplitudes.size,
                })
    return rows, counts


def example_amplitudes(path: Path, picks: list[tuple[int, int, int, float]]) -> pd.DataFrame:
    """Measure event amplitudes as the archive analysis does, and check them against its table."""
    from pynwb import NWBHDF5IO

    frames = []
    with NWBHDF5IO(str(path), "r", load_namespaces=True) as io:
        layout = resolve_layout(io.read())
        for percentile, dmd, roi, median in picks:
            series = layout["dff_series"][dmd]
            timestamps = np.asarray(series.timestamps)
            dt = sampling_interval(timestamps)
            trace = np.asarray(series.data[:, roi], dtype=np.float32)
            detected = detect_events(trace, dt)
            indices, _ = drop_untimed_events(detected["idx"], detected["amp_sd"], timestamps)
            noise, _ = baseline_noise(trace[np.isfinite(trace)])
            amplitudes = event_amplitudes_raw(trace, indices, dt, noise)
            amplitudes = amplitudes[np.isfinite(amplitudes)]
            if not np.isclose(np.median(amplitudes), median, atol=1e-3):
                raise ValueError(f"DMD{dmd} ROI {roi}: median differs from the archive table.")
            frames.append(pd.DataFrame({
                "percentile": percentile, "dmd": dmd, "roi": roi, "amplitude_sd": amplitudes,
            }))
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("/tmp/slap2_cache"))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--jobs", type=int, default=6)
    args = parser.parse_args()

    metrics = pd.read_csv(METRICS)
    sessions = sorted(metrics.loc[~metrics.has_calcium.astype(bool), "session"].unique())
    assets = {
        asset["session_id"]: asset
        for asset in json.loads(ASSETS.read_text(encoding="utf-8"))["source_assets"]
    }
    paths = [fetch(assets[session], args.cache) for session in sessions]
    with ProcessPoolExecutor(args.jobs) as executor:
        results = list(executor.map(process_session, paths))
    rows = pd.DataFrame([row for session_rows, _ in results for row in session_rows])
    counts = sum(session_counts for _, session_counts in results)
    picks = select_examples(metrics)
    amplitudes = example_amplitudes(paths[sessions.index(EXAMPLE_SESSION)], picks)

    args.output.mkdir(parents=True, exist_ok=True)
    occupied = counts > 0
    pd.DataFrame({
        "bin_left_sd": EDGES[:-1][occupied], "bin_right_sd": EDGES[1:][occupied],
        "events": counts[occupied],
    }).to_csv(args.output / "noise_only_amplitude_histogram.csv", index=False,
              lineterminator="\n", float_format="%.1f")
    rows.to_csv(args.output / "noise_only_source_rates.csv", index=False, lineterminator="\n",
                float_format="%.6f")
    amplitudes.to_csv(args.output / "example_source_amplitudes.csv", index=False,
                      lineterminator="\n", float_format="%.6f")

    outputs = (
        "noise_only_amplitude_histogram.csv", "noise_only_source_rates.csv",
        "example_source_amplitudes.csv",
    )
    provenance = {
        "version": 1,
        "dandiset_id": "001424",
        "dandiset_version": "draft",
        "processed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_assets": [assets[session] for session in sessions],
        "source_hash_verification": "SHA-256 of each NWB matched its published DANDI digest.",
        "inputs": {path.name: sha256(path) for path in (METRICS,)},
        "parameters": {
            "null_model": "phase-randomized surrogate of the event-free trace, one per source",
            "event_samples_removed_before": EVENT_SAMPLES_BEFORE,
            "event_samples_removed_after": EVENT_SAMPLES_AFTER,
            "tau_seconds": TAU_IGLUSNFR4F_S,
            "seed_per_session": SEED,
            "histogram_bin_sd": 0.1,
            "example_session": EXAMPLE_SESSION,
            "example_percentiles": list(PERCENTILES),
            "example_metric": AMPLITUDE,
        },
        "exclusions": "The 8 dual-channel sessions: their traces are denoised and non-negative.",
        "example_sources": [
            {"percentile": p, "dmd": d, "roi": r, "median_event_raw_sd": m} for p, d, r, m in picks
        ],
        "outputs": {name: sha256(args.output / name) for name in outputs},
    }
    (args.output / "provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n",
    )
    print(f"{len(rows)} sources, {int(counts.sum())} noise-only events, examples {picks}")


if __name__ == "__main__":
    main()
