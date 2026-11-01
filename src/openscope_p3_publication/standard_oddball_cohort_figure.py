"""Offline area proportions for the cohort panel of the standard-oddball column."""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
from matplotlib.axes import Axes

from .standard_oddball_publication_data import load_neuropixels_cohort

REGION_ORDER = ("LGd", "VISp", "VISl", "VISa", "Frontal", "Hippocampus", "SSp", "STR")
REGION_LABELS = {"Hippocampus": "HIP"}
MINIMUM_QC_SUA = 20
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 0
BOOTSTRAP_RULE = (
    "95% percentile mouse-cluster bootstrap; resample contributing mice with replacement "
    "within each region and recompute summed responsive / summed joint-testable counts; "
    "fixed session/group inclusion and shared resamples for Q1, Q2 and Both"
)
SCREENS = (("q1", "Q1"), ("q2", "Q2"), ("joint", "Both"))
RESPONSE_RULE = (
    "90-degree exploratory Q1 and baseline-subtracted Q2: p <0.05 and abs(MI) >0.1; "
    "Both is their intersection, including opposite-sign responses"
)
# Match Figure 9's pinned extractor without importing its cloud/atlas dependencies.
FRONTAL_PREFIXES = ("ACA", "ILA", "PL", "ORB", "MOp", "MOs")
STR_AREAS = ("LSr", "LSc", "STR", "CP", "SH")
PANEL_COLUMNS = (
    "session_id", "subject_id", "asset_id", "nwb_unit_id", "event_id",
    "brain_division", "brain_area", "qc_pass", "decoder_label", "probe_excluded",
    "eligible", "joint_testable", "q1_responsive", "q2_responsive", "joint_responsive",
)


def _response_fractions(frame: pd.DataFrame) -> None:
    for screen, _ in SCREENS:
        frame[f"fraction_{screen}_responsive"] = frame[f"n_{screen}_responsive"].div(
            frame.n_joint_testable.replace(0, np.nan)
        )


def _mouse_bootstrap_intervals(areas: pd.DataFrame, mice: pd.DataFrame) -> None:
    for screen, _ in SCREENS:
        for bound in ("low", "high"):
            areas[f"fraction_{screen}_responsive_ci95_{bound}"] = np.nan
    areas["bootstrap_status"] = "insufficient_mice"
    for index, row in areas.iterrows():
        group = mice.loc[mice.brain_area.eq(row.brain_area)].sort_values("subject_id")
        if len(group) < 2:
            continue
        seed_key = f"{BOOTSTRAP_SEED}:{row.brain_area}"
        seed = int.from_bytes(hashlib.sha256(seed_key.encode()).digest()[:8], "big")
        rng = np.random.default_rng(seed)
        draws = rng.integers(len(group), size=(BOOTSTRAP_REPLICATES, len(group)))
        denominator = group.n_joint_testable.to_numpy(dtype=np.int64)
        numerator = group[
            [f"n_{screen}_responsive" for screen, _ in SCREENS]
        ].to_numpy(dtype=np.int64)
        estimates = numerator[draws].sum(axis=1) / denominator[draws].sum(axis=1)[:, None]
        bounds = np.quantile(estimates, [0.025, 0.975], axis=0, method="linear")
        for j, (screen, _) in enumerate(SCREENS):
            areas.loc[index, f"fraction_{screen}_responsive_ci95_low"] = bounds[0, j]
            areas.loc[index, f"fraction_{screen}_responsive_ci95_high"] = bounds[1, j]
        areas.loc[index, "bootstrap_status"] = "estimated"


def prepare_cohort_panel(
    units: pd.DataFrame, *, event: str = "orientation_90",
) -> dict:
    """Pool regions before applying a test-independent session/group QC-SUA cutoff."""
    missing = set(PANEL_COLUMNS) - set(units)
    if missing:
        raise ValueError(f"Panel C unit columns missing: {sorted(missing)}")
    work = units.loc[units.event_id.eq(event)].copy()
    if work.duplicated(["asset_id", "nwb_unit_id"]).any():
        raise ValueError(f"Duplicate {event} cohort source units.")
    region = pd.Series(pd.NA, index=work.index, dtype="string")
    for area in ("LGd", "VISp", "VISl", "VISa", "SSp"):
        division = "TH" if area == "LGd" else "Isocortex"
        region.loc[work.brain_division.eq(division) & work.brain_area.eq(area)] = area
    frontal = (
        work.brain_division.eq("Isocortex")
        & work.brain_area.str.startswith(FRONTAL_PREFIXES, na=False)
    )
    region.loc[frontal] = "Frontal"
    region.loc[work.brain_division.eq("HPF")] = "Hippocampus"
    region.loc[work.brain_division.eq("STR") & work.brain_area.isin(STR_AREAS)] = "STR"
    work["region"] = region
    work = work.loc[work.region.notna()].copy()
    work["qc_sua"] = (
        work.qc_pass & work.decoder_label.eq("sua") & ~work.probe_excluded
    )
    work["testable"] = work.eligible & work.joint_testable
    if not work.joint_responsive.eq(work.q1_responsive & work.q2_responsive).all():
        raise ValueError("Joint response flags do not equal the Q1/Q2 intersection.")
    for screen, _ in SCREENS:
        work[f"responsive_{screen}"] = work.testable & work[f"{screen}_responsive"]
    session_keys = ["session_id", "subject_id", "region"]
    sessions = work.groupby(session_keys, observed=True, sort=True).agg(
        n_recorded=("qc_sua", "size"), n_qc_sua=("qc_sua", "sum"),
        n_eligible=("eligible", "sum"), n_joint_testable=("testable", "sum"),
        **{
            f"n_{screen}_responsive": (f"responsive_{screen}", "sum")
            for screen, _ in SCREENS
        },
    ).reset_index()
    sessions["included"] = sessions.n_qc_sua.ge(MINIMUM_QC_SUA)
    sessions["status"] = np.where(
        ~sessions.included, "below_minimum_qc_sua",
        np.where(sessions.n_joint_testable.gt(0), "included", "no_testable_eligible_units"),
    )
    included = sessions.loc[sessions.included]
    if included.empty:
        raise ValueError("No session/group meets the panel C QC-SUA minimum.")

    def pool(keys: list[str]) -> pd.DataFrame:
        counts = [
            "n_recorded", "n_qc_sua", "n_eligible", "n_joint_testable",
            *[f"n_{screen}_responsive" for screen, _ in SCREENS],
        ]
        result = included.groupby(keys, observed=True, sort=True).agg(
            **{name: (name, "sum") for name in counts},
            n_sessions=("session_id", "nunique"), n_mice=("subject_id", "nunique"),
        ).reset_index()
        _response_fractions(result)
        result["division_order"] = result.region.map(
            {name: i for i, name in enumerate(REGION_ORDER)}
        ).astype(int)
        return result.sort_values(
            ["division_order", *[k for k in keys if k != "region"]], kind="stable",
        ).rename(columns={"region": "brain_area"}).reset_index(drop=True)

    areas = pool(["region"])
    mice = pool(["region", "subject_id"])
    areas = areas.loc[areas.n_joint_testable.gt(0)].reset_index(drop=True)
    mice = mice.loc[mice.n_joint_testable.gt(0)].reset_index(drop=True)
    if areas.empty:
        raise ValueError("No testable units remain after the panel C QC-SUA cutoff.")
    _mouse_bootstrap_intervals(areas, mice)
    _response_fractions(sessions)
    sessions["minimum_qc_sua"] = MINIMUM_QC_SUA
    sessions = sessions.rename(columns={"region": "brain_area"})
    return {"areas": areas, "mice": mice, "sessions": sessions}


def cohort_plot_data() -> dict:
    """Load exact compact regional counts and validate their pooled mouse fractions."""
    prepared = load_neuropixels_cohort()
    for row in prepared["areas"].to_dict("records"):
        points = prepared["mice"].loc[prepared["mice"].brain_area.eq(row["brain_area"])]
        for column in ("n_joint_testable", *[f"n_{s}_responsive" for s, _ in SCREENS]):
            if points[column].sum() != row[column]:
                raise ValueError(f"{row['brain_area']}: mouse counts differ at {column}.")
    for table in (prepared["areas"], prepared["mice"]):
        keys = ["brain_area"] + (["subject_id"] if table is prepared["mice"] else [])
        if table.duplicated(keys).any():
            raise ValueError("Duplicate plotted cohort identities.")
        for screen, _ in SCREENS:
            count = table[f"n_{screen}_responsive"]
            expected = count / table.n_joint_testable
            if (
                np.any(count.lt(0) | count.gt(table.n_joint_testable))
                or not np.allclose(
                    table[f"fraction_{screen}_responsive"], expected, rtol=1e-14, atol=1e-16,
                )
            ):
                raise ValueError(f"Invalid cohort fractions for {screen}.")
    return prepared


def draw_cohort_panel(ax: Axes, prepared: dict, color: str) -> None:
    """Draw pooled Q1, Q2 and joint bars with 95% mouse-bootstrap intervals."""
    areas = prepared["areas"]
    if not areas.bootstrap_status.eq("estimated").all():
        raise ValueError("Panel C bootstrap intervals require at least two mice per region.")
    x = np.arange(len(areas))
    colors = ("#56B4E9", "#E69F00", color)
    for j, (screen, label) in enumerate(SCREENS):
        centers = x + (j - 1) * 0.24
        bars = ax.bar(
            centers, 100 * areas[f"fraction_{screen}_responsive"], width=0.22,
            color=colors[j], alpha=0.65, linewidth=0, label=label,
        )
        for bar, area in zip(bars, areas.brain_area, strict=True):
            bar.set_gid(f"cohort-pooled-{screen}-{area}")
        lower = areas[f"fraction_{screen}_responsive_ci95_low"].to_numpy()
        upper = areas[f"fraction_{screen}_responsive_ci95_high"].to_numpy()
        # Preserve exact CI endpoints even if a percentile interval excludes the estimate.
        interval = ax.errorbar(
            centers, 50 * (lower + upper), yerr=50 * (upper - lower),
            fmt="none", ecolor="#333333", elinewidth=0.6,
            capsize=0, zorder=3,
        )
        interval.lines[2][0].set_gid(f"cohort-mouse-bootstrap-ci95-{screen}")
    legend = ax.legend(
        loc="lower center", bbox_to_anchor=(0.5, 1.02), ncol=3, frameon=False,
        fontsize=5.5, handlelength=0.9, handletextpad=0.3, columnspacing=0.7,
        borderaxespad=0,
    )
    legend.set_gid("cohort-screen-legend")
    ax.set_gid("cohort-responsiveness-proportions")
    ax.set_xlim(-0.6, len(areas) - 0.4)
    ax.set_ylim(0, 100)
    ax.set_yticks([0, 50, 100])
    ax.set_xticks(
        x, areas.brain_area.replace(REGION_LABELS),
        rotation=45, ha="right", rotation_mode="anchor",
    )
    ax.tick_params(labelsize=5.5, length=1.5, pad=1)
    ax.set_ylabel("Responsive (%)", fontsize=6)
