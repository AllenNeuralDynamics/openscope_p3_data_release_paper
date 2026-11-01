"""Offline, signal-specific mesoscope cohort counts and mouse-cluster uncertainty."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.axes import Axes

from .mesoscope_standard_oddball import ROOT, sha256
from .standard_oddball_cohort_figure import (
    BOOTSTRAP_REPLICATES,
    BOOTSTRAP_RULE,
    BOOTSTRAP_SEED,
    SCREENS,
    _mouse_bootstrap_intervals,
    _response_fractions,
    draw_cohort_panel,
)
from .standard_oddball_publication_data import DIRECTORY, load_mesoscope_cohort

MINIMUM_ELIGIBLE_ROIS = 20
REGIONS = ("VISp", "VISl")
COUNT_COLUMNS = [
    "n_recorded", "n_soma", "n_eligible", "n_q1_testable", "n_q2_testable",
    "n_joint_testable", "n_untestable",
    *[f"n_{screen}_responsive" for screen, _ in SCREENS],
]


def prepare_cohort_panel(units: pd.DataFrame) -> dict:
    """Pool planes before eligibility cutoffs, using each signal's own joint denominator."""
    required = {
        "session_id", "subject_id", "asset_id", "plane", "roi_id", "area", "event_id",
        "signal", "is_soma", "eligible", "q1_testable", "q2_testable", "joint_testable",
        *[f"{s}_responsive" for s, _ in SCREENS],
    }
    if not required.issubset(units):
        raise ValueError(f"Missing mesoscope cohort columns: {sorted(required - set(units))}")
    if units.duplicated(["asset_id", "plane", "roi_id", "event_id", "signal"]).any():
        raise ValueError("Duplicate mesoscope cohort source ROI/signal/event.")
    if not units.area.isin(REGIONS).all():
        raise ValueError("Unexpected mesoscope cohort area.")
    if (
        not units.joint_testable.eq(units.q1_testable & units.q2_testable).all()
        or not units.joint_responsive.eq(units.q1_responsive & units.q2_responsive).all()
    ):
        raise ValueError("Inconsistent mesoscope joint testability/response flags.")
    work = units.copy()
    work["testable"] = work.eligible & work.joint_testable
    for screen in ("q1", "q2"):
        work[f"testable_{screen}"] = work.eligible & work[f"{screen}_testable"]
    for screen, _ in SCREENS:
        work[f"responsive_{screen}"] = work.testable & work[f"{screen}_responsive"]
    keys = ["event_id", "signal", "session_id", "subject_id", "asset_id", "area"]
    sessions = work.groupby(keys, observed=True, sort=True).agg(
        n_recorded=("eligible", "size"), n_soma=("is_soma", "sum"),
        n_eligible=("eligible", "sum"), n_joint_testable=("testable", "sum"),
        **{f"n_{s}_testable": (f"testable_{s}", "sum") for s in ("q1", "q2")},
        **{f"n_{s}_responsive": (f"responsive_{s}", "sum") for s, _ in SCREENS},
    ).reset_index().rename(columns={"area": "brain_area"})
    sessions["n_untestable"] = sessions.n_eligible - sessions.n_joint_testable
    sessions["minimum_eligible_rois"] = MINIMUM_ELIGIBLE_ROIS
    sessions["included"] = sessions.n_eligible.ge(MINIMUM_ELIGIBLE_ROIS)
    sessions["contributing"] = sessions.included & sessions.n_joint_testable.gt(0)
    sessions["status"] = np.where(
        ~sessions.included, "below_minimum_eligible_rois",
        np.where(sessions.contributing, "included", "no_jointly_testable_eligible_rois"),
    )
    _response_fractions(sessions)
    included = sessions.loc[sessions.included]
    if included.empty:
        raise ValueError("No mesoscope session/area meets the eligible-ROI minimum.")

    def pool(grouping: list[str]) -> pd.DataFrame:
        groups = included.groupby(grouping, observed=True, sort=True)
        frame = groups.agg(
            **{name: (name, "sum") for name in COUNT_COLUMNS},
            n_sessions=("session_id", "nunique"), n_included_mice=("subject_id", "nunique"),
            n_contributing_sessions=("contributing", "sum"),
        ).reset_index()
        mice = included.loc[included.contributing].groupby(
            grouping, observed=True, sort=True,
        ).subject_id.nunique()
        frame["n_mice"] = (
            frame.set_index(grouping).index.map(mice).fillna(0).to_numpy(dtype=int)
        )
        _response_fractions(frame)
        return frame

    groups = ["event_id", "signal", "brain_area"]
    areas, mice = pool(groups), pool([*groups, "subject_id"])
    bootstrapped = []
    for (event, signal), frame in areas.groupby(["event_id", "signal"], sort=True):
        frame = frame.copy().reset_index(drop=True)
        contributing = mice.loc[
            mice.event_id.eq(event) & mice.signal.eq(signal) & mice.n_joint_testable.gt(0)
        ]
        _mouse_bootstrap_intervals(frame, contributing)
        bootstrapped.append(frame)
    areas = pd.concat(bootstrapped, ignore_index=True)
    for frame in (areas, mice, sessions):
        frame["area_order"] = frame.brain_area.map({r: i for i, r in enumerate(REGIONS)})
        frame.sort_values(
            ["event_id", "signal", "area_order", *(
                ["subject_id", "session_id"] if frame is sessions
                else ["subject_id"] if frame is mice else []
            )],
            kind="stable", inplace=True,
        )
        frame.reset_index(drop=True, inplace=True)
    return {"areas": areas, "mice": mice, "sessions": sessions}


def cohort_plot_data() -> dict:
    """Load frozen counts/intervals without the analysis-scale ROI table."""
    return load_mesoscope_cohort()


def signal_panel(prepared: dict, signal: str, event: str = "orientation_90") -> dict:
    """Select a figure view without changing source classifications or denominators."""
    result = {
        key: frame.loc[frame.signal.eq(signal) & frame.event_id.eq(event)].copy()
        for key, frame in prepared.items() if isinstance(frame, pd.DataFrame) and "signal" in frame
    }
    if (
        "areas" not in result or tuple(result["areas"].brain_area) != REGIONS
        or not result["areas"].bootstrap_status.eq("estimated").all()
    ):
        raise ValueError(f"{signal}/{event}: both areas need estimable mouse-cluster intervals.")
    return result


def draw_panel(ax: Axes, prepared: dict, color: str) -> None:
    """Match the Neuropixels screen colors and exact uncapped interval endpoints."""
    draw_cohort_panel(ax, prepared, color)
    areas = prepared["areas"]
    ax.set_xticks(
        np.arange(len(areas)),
        [f"{r.brain_area}\nn={r.n_joint_testable:,}" for r in areas.itertuples()],
        rotation=0, ha="center",
    )
    ax.tick_params(axis="x", labelsize=5)


def write_cohort_audits(prepared: dict, directory: Path) -> list[Path]:
    """Persist all-event counts, exact intervals and their deterministic derivation."""
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for key, name in (
        ("sessions", "session-area-statistics.csv"), ("mice", "mouse-area-statistics.csv"),
        ("areas", "area-statistics.csv"),
    ):
        path = directory / name
        prepared[key].to_csv(path, index=False, float_format="%.17g", lineterminator="\n")
        paths.append(path)
    sources = [
        Path(__file__), ROOT / "src/openscope_p3_publication/standard_oddball_cohort_figure.py",
        DIRECTORY / "provenance.json", DIRECTORY / "cohorts.json",
    ]
    provenance = {
        "version": 1, "events": prepared["source_provenance"]["events"],
        "included_session_count": int(prepared["inventory"].included.sum()),
        "included_mouse_count": int(
            prepared["inventory"].loc[prepared["inventory"].included, "subject_id"].nunique()
        ),
        "source_asset_urls": [{
            "asset_id": record["asset_id"],
            "metadata_url": f"https://api.dandiarchive.org/api/assets/{record['asset_id']}/",
            "download_url": (
                f"https://api.dandiarchive.org/api/assets/{record['asset_id']}/download/"
            ),
        } for record in prepared["source_provenance"]["asset_manifest"]],
        "signals": ["dff", "oasis"], "minimum_eligible_rois": MINIMUM_ELIGIBLE_ROIS,
        "minimum_rule": (
            "Pool planes per session/area before applying the eligible soma/SNR cutoff."
        ),
        "denominator": (
            "Each signal's own eligible, jointly Q1/Q2-testable ROI/session observations."
        ),
        "response_rule": "Raw p<0.05 and abs(MI)>0.1, either sign; Both is the intersection.",
        "amplitude_gate": "None; dF/F>0.5 applies only to panel A example selection.",
        "bootstrap_rule": BOOTSTRAP_RULE, "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "sources": [{"path": p.relative_to(ROOT).as_posix(), "sha256": sha256(p)} for p in sources],
        "outputs": [{"path": p.name, "sha256": sha256(p)} for p in paths],
    }
    path = directory / "provenance.json"
    path.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n",
    )
    return [*paths, path]
