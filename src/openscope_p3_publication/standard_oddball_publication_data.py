"""Compact, checksummed cohort summaries and example statistics for Figure 9."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .mesoscope_standard_oddball import ROOT, sha256

DIRECTORY = ROOT / "figure_sources/data/standard-oddball-publication"
STATISTICS = [
    "q1_p", "q1_mi", "q2_p", "q2_mi", "q1_q", "q2_q",
    "q1_trials", "q2_context_trials", "q2_control_trials",
    "q1_responsive", "q2_responsive", "joint_responsive", "positive_joint",
    "q2_nonsignificant",
]


def load_publication_data(directory: Path = DIRECTORY) -> dict:
    """Verify compact outputs and owning code without requiring full analysis tables."""
    provenance = json.loads((directory / "provenance.json").read_text())
    if provenance.get("version") != 1:
        raise ValueError("Unsupported standard-oddball publication snapshot.")
    for source in provenance["inputs"]:
        if sha256(ROOT / source["path"]) != source["sha256"]:
            raise ValueError(f"Publication data source changed: {source['path']}")
    path = directory / "cohorts.json"
    if sha256(path) != provenance["output_sha256"]:
        raise ValueError("Publication cohort snapshot checksum changed.")
    result = json.loads(path.read_text())
    if result.get("version") != 1:
        raise ValueError("Unsupported publication cohort schema.")
    return result


def decode_frame(record: dict) -> pd.DataFrame:
    """Restore full-precision frozen values and original DataFrame dtypes."""
    frame = pd.DataFrame(record["records"], columns=record["columns"])
    return frame.astype(record["dtypes"])


def load_neuropixels_cohort(event: str = "orientation_90") -> dict:
    """Load the existing regional counts, mouse points and exact bootstrap endpoints."""
    source = load_publication_data()["neuropixels"]
    prepared = {k: decode_frame(v) for k, v in source["events"][event].items()}
    for table in (prepared["areas"], prepared["mice"]):
        for screen in ("q1", "q2", "joint"):
            count, n = table[f"n_{screen}_responsive"], table.n_joint_testable
            if (
                np.any(n <= 0) or np.any(count < 0) or np.any(count > n)
                or not np.allclose(
                    table[f"fraction_{screen}_responsive"], count / n, rtol=1e-14, atol=1e-16,
                )
            ):
                raise ValueError(f"Invalid frozen Neuropixels {screen} counts/fractions.")
    return {**prepared, "provenance": source["provenance"]}


def load_mesoscope_cohort() -> dict:
    """Load signal-specific cohort counts, inventory and frozen uncertainty."""
    source = load_publication_data()["mesoscope"]
    return {
        **{k: decode_frame(v) for k, v in source["tables"].items()},
        "source_provenance": source["provenance"],
    }


def load_example_statistics(modality: str) -> pd.DataFrame:
    """Load only the four-event statistics of the displayed example-session sources."""
    frame = pd.DataFrame(load_publication_data()["example_statistics"][modality])
    frame["id"] = frame.id.astype(str)
    if (
        frame.duplicated(["id", "event_id"]).any() or not frame.eligible.all()
        or not frame.joint_responsive.eq(frame.q1_responsive & frame.q2_responsive).all()
    ):
        raise ValueError(f"Invalid {modality} example identities, eligibility or joint flags.")
    return frame
