"""Post-C1 pseudo-context versus pre-C1 control, separate from the oddball analysis."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from .mesoscope_standard_oddball import signal_statistics
from .mismatch_responsiveness import comparison_windows
from .neural_responses import neural_response_windows
from .standard_oddball_cohort import ROOT, event_windows, sha256
from .standard_oddball_cohort_figure import (
    FRONTAL_PREFIXES,
    MINIMUM_QC_SUA,
    REGION_ORDER,
    STR_AREAS,
)

EVENT = "orientation_90"
DIRECTORY = ROOT / "figure_sources/data/ephys-c1-pseudocontext"


def pseudo_windows(tables: dict) -> tuple[dict, dict]:
    """Build post-C1 event/predecessor windows and matched pre-C1 control windows."""
    spec = event_windows(tables)[EVENT]
    control = tables["control"]
    post_indices = spec["control_post_indices"]
    comparisons = comparison_windows(
        control["start"], control["stop"], post_indices, "standard", control["block_number"],
    )
    kept, excluded = [], []
    for position, (index, comparison) in enumerate(zip(post_indices, comparisons, strict=True)):
        if comparison is None:
            excluded.append({"index": int(index), "reason": "missing_or_cross_block_predecessor"})
        elif index - 1 not in range(len(control["start"])) or (
            control["start"][index - 1] < np.max(tables["context"]["stop"])
        ):
            raise ValueError("Pseudo-Q1 predecessor does not belong to post-C1.")
        elif spec["control_post_baseline"][position] is None:
            excluded.append({"index": int(index), "reason": "missing_preceding_grey"})
        else:
            kept.append(position)
    if len(kept) < 2:
        raise ValueError("Pseudo-context needs at least two valid post-C1 trials.")
    pre_indices = spec["control_pre_indices"]
    if any(bound is None for bound in spec["control_pre_baseline"]):
        raise ValueError("Pre-C1 matched controls lack a preceding-grey baseline.")
    selected = [post_indices[position] for position in kept]
    windows = {
        "context_test": neural_response_windows(control["start"], control["stop"], selected),
        "context_comparison": [comparisons[position] for position in kept],
        "context_baseline": [spec["control_post_baseline"][position] for position in kept],
        "control_test": spec["control_pre_test"],
        "control_baseline": spec["control_pre_baseline"],
    }
    predecessors = [
        {
            "event_index": int(index), "predecessor_index": int(index - 1),
            "trial_type": str(control["trial_type"][index - 1]),
            "orientation_radians": float(control["orientation"][index - 1]),
        }
        for index in selected
    ]
    return windows, {
        "event_id": EVENT, "post_indices": [int(index) for index in selected],
        "pre_indices": [int(index) for index in pre_indices], "excluded_post": excluded,
        "post_selected_before_exclusions": len(post_indices),
        "predecessors": predecessors,
        "predecessor_trial_types": dict(Counter(row["trial_type"] for row in predecessors)),
        "windows": windows,
    }


def pseudo_statistics(collected: dict[str, np.ndarray]) -> pd.DataFrame:
    """Apply the existing paired Q1 and baseline-subtracted unpaired Q2 screens."""
    required = {
        "context_test", "context_comparison", "context_baseline",
        "control_test", "control_baseline",
    }
    if set(collected) != required:
        raise ValueError("Pseudo-context arrays must contain exactly the five analysis windows.")
    return signal_statistics(collected)


def assign_regions(units: pd.DataFrame) -> pd.Series:
    """Use Figure 9's cortical, thalamic and pooled anatomical definitions."""
    region = pd.Series(pd.NA, index=units.index, dtype="string")
    for area in ("LGd", "VISp", "VISl", "VISa", "SSp"):
        division = "TH" if area == "LGd" else "Isocortex"
        region.loc[units.brain_division.eq(division) & units.brain_area.eq(area)] = area
    region.loc[
        units.brain_division.eq("Isocortex")
        & units.brain_area.str.startswith(FRONTAL_PREFIXES, na=False)
    ] = "Frontal"
    region.loc[units.brain_division.eq("HPF")] = "Hippocampus"
    region.loc[
        units.brain_division.eq("STR") & units.brain_area.isin(STR_AREAS)
    ] = "STR"
    return region


def summarize_pseudo(units: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Count eligible responders using the unchanged Figure 9 session/region gate."""
    if units.duplicated(["asset_id", "nwb_unit_id"]).any():
        raise ValueError("Duplicate pseudo-context unit identities.")
    work = units.copy()
    work["region"] = assign_regions(work)
    work = work.loc[work.region.notna()].copy()
    work["qc_sua"] = work.qc_pass & work.decoder_label.eq("sua") & ~work.probe_excluded
    for screen in ("q1", "q2", "joint"):
        work[f"eligible_{screen}_testable"] = work.eligible & work[f"{screen}_testable"]
        work[f"eligible_{screen}_responsive"] = (
            work.eligible & work.joint_testable & work[f"{screen}_responsive"]
        )
    if not work.joint_responsive.eq(work.q1_responsive & work.q2_responsive).all():
        raise ValueError("Pseudo-context Both flags must be the Q1/Q2 intersection.")
    counts = {
        "n_recorded": ("eligible", "size"), "n_qc_sua": ("qc_sua", "sum"),
        "n_eligible": ("eligible", "sum"),
        **{
            f"n_{screen}_{kind}": (f"eligible_{screen}_{kind}", "sum")
            for screen in ("q1", "q2", "joint") for kind in ("testable", "responsive")
        },
    }
    sessions = work.groupby(["session_id", "subject_id", "region"], sort=True).agg(
        **counts,
    ).reset_index()
    sessions["included"] = sessions.n_qc_sua.ge(MINIMUM_QC_SUA)
    included = sessions.loc[sessions.included]
    if included.empty:
        raise ValueError("No pseudo-context session/region meets the Figure 9 inclusion gate.")
    areas = included.groupby("region", sort=True).agg(
        **{name: (name, "sum") for name in counts},
        n_sessions=("session_id", "nunique"), n_mice=("subject_id", "nunique"),
    ).reset_index()
    areas["region_order"] = areas.region.map(
        {name: index for index, name in enumerate(REGION_ORDER)},
    )
    areas = areas.sort_values("region_order").drop(columns="region_order").reset_index(drop=True)
    for frame in (sessions, areas):
        for screen in ("q1", "q2", "joint"):
            frame[f"fraction_{screen}_responsive"] = frame[f"n_{screen}_responsive"].div(
                frame.n_joint_testable.replace(0, np.nan),
            )
    return sessions, areas


def load_pseudo(directory: Path = DIRECTORY) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Verify offline pseudo-context inputs and reproduce the saved count summaries."""
    provenance = json.loads((directory / "provenance.json").read_text())
    if provenance["version"] != 1 or provenance["event"] != EVENT:
        raise ValueError("Unsupported ephys pseudo-context snapshot.")
    for source in provenance["sources"]:
        if sha256(ROOT / source["path"]) != source["sha256"]:
            raise ValueError(f"Pseudo-context source changed: {source['path']}")
    for output in provenance["outputs"]:
        if sha256(directory / output["path"]) != output["sha256"]:
            raise ValueError(f"Pseudo-context output changed: {output['path']}")
    units = pd.read_csv(
        directory / "units.csv.gz", float_precision="round_trip", dtype={"subject_id": str},
    )
    if (
        len(units) != provenance["unit_count"]
        or units.session_id.nunique() != provenance["session_count"]
        or not units.event_id.eq(EVENT).all()
    ):
        raise ValueError("Pseudo-context unit/session/event coverage changed.")
    sessions, areas = summarize_pseudo(units)
    for name, expected in (("session-regions.csv", sessions), ("regions.csv", areas)):
        observed = pd.read_csv(
            directory / name, float_precision="round_trip", dtype={"subject_id": str},
        )
        pd.testing.assert_frame_equal(observed, expected, check_dtype=False)
    return units, areas, provenance
