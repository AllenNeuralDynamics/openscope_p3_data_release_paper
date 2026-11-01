"""Validated offline four-event displays for the standard-oddball explorer."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .mesoscope_standard_oddball import ROOT, sha256
from .standard_oddball_cohort import EVENTS
from .standard_oddball_explorer_window import WINDOW

DIRECTORY = ROOT / "figure_sources/data/standard-oddball-explorer-events"


def load_population_events(
    modality: str, keys: list[str], directory: Path = DIRECTORY,
) -> tuple[dict, dict[str, np.ndarray]]:
    """Validate checksums, identities, event axes and recorded-sample coverage."""
    metadata = json.loads((directory / "provenance.json").read_text())
    if (
        metadata.get("version") != 1 or metadata.get("events") != list(EVENTS)
        or metadata.get("window") != list(WINDOW)
    ):
        raise ValueError("Unsupported four-event explorer snapshot.")
    for record in metadata["inputs"]:
        if sha256(ROOT / record["path"]) != record["sha256"]:
            raise ValueError(f"Four-event explorer source changed: {record['path']}")
    path = directory / f"{modality}.npz"
    if sha256(path) != metadata["outputs"][modality]:
        raise ValueError(f"Four-event {modality} checksum changed.")
    view = metadata["modalities"][modality]
    with np.load(path, allow_pickle=False) as archive:
        arrays = {k: archive[k] for k in archive.files}
    time, delta, counts = (arrays[k] for k in ("time", "delta", "counts"))
    if (
        view["source_ids"] != keys or set(view["events"]) != set(EVENTS)
        or time.ndim != 1 or len(time) < 2
        or delta.shape != (len(EVENTS), 2, len(keys), len(time))
        or counts.shape != delta.shape or not np.isfinite(delta).all()
        or not np.isfinite(time).all() or not np.all(np.diff(time) > 0)
        or time[0] < WINDOW[0] or time[-1] > WINDOW[1]
        or not np.issubdtype(counts.dtype, np.integer) or np.any(counts <= 0)
    ):
        raise ValueError("Four-event explorer identity, shape, samples or coverage changed.")
    for e, event in enumerate(EVENTS):
        expected = {
            c: [int(counts[e, i].min()), int(counts[e, i].max())]
            for i, c in enumerate(("context", "control"))
        }
        if view["events"][event]["count_ranges"] != expected:
            raise ValueError(f"{modality}/{event}: recorded-count metadata changed.")
    return view, arrays
