"""Glutamate subset proportions with individual mouse points, not bootstrap intervals."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from matplotlib.axes import Axes

from .mesoscope_standard_oddball import ROOT, sha256
from .slap2_standard_oddball_cohort import DATA, DERIVED, GROUPS, load_cohort, summaries
from .standard_oddball_cohort_figure import SCREENS

PANEL_GROUPS = GROUPS[:2]


def cohort_plot_data() -> dict:
    """Return validated all-event summaries and the 90-degree plotting subset."""
    inventory, units, provenance = load_cohort()
    sessions, pooled = summaries(units)
    return {
        "inventory": inventory, "units": units, "sessions": sessions, "pooled": pooled,
        "provenance": provenance,
        "panel_sessions": sessions.loc[
            sessions.event_id.eq("orientation_90") & sessions.contributing
            & sessions.group.isin(PANEL_GROUPS)
        ],
        "panel_pooled": pooled.loc[pooled.event_id.eq("orientation_90")].set_index("group").loc[
            list(PANEL_GROUPS)
        ].reset_index(),
    }


def draw_panel(ax: Axes, cohort: dict, color: str) -> None:
    """Plot pooled source counts and each of the two independent mouse/session proportions."""
    pooled = cohort["panel_pooled"]
    sessions = cohort["panel_sessions"]
    if set(pooled.group) != set(PANEL_GROUPS) or not pooled.n_mice.eq(2).all():
        raise ValueError("Glutamate subset panel needs both DMD groups with exactly two mice.")
    colors = ("#56B4E9", "#E69F00", color)
    x = np.arange(len(PANEL_GROUPS))
    subjects = sorted(sessions.subject_id.unique())
    for j, (screen, label) in enumerate(SCREENS):
        centers = x + (j - 1) * 0.24
        bars = ax.bar(
            centers, 100 * pooled[f"{screen}_fraction"], width=0.22,
            color=colors[j], alpha=0.65, linewidth=0, label=label,
        )
        for bar, group in zip(bars, PANEL_GROUPS, strict=True):
            bar.set_gid(f"cohort-pooled-{screen}-{group}")
        for i, subject in enumerate(subjects):
            mouse = sessions.loc[sessions.subject_id.eq(subject)].set_index("group").loc[
                list(PANEL_GROUPS)
            ]
            points = ax.scatter(
                centers + (i - 0.5) * 0.08, 100 * mouse[f"{screen}_fraction"],
                s=7, marker="o" if i == 0 else "s", facecolor="white",
                edgecolor="#333333", linewidth=0.4, zorder=3,
            )
            points.set_gid(f"cohort-mouse-{subject}-{screen}")
    ax.legend(
        loc="lower center", bbox_to_anchor=(0.5, 1.02), ncol=3, frameon=False,
        fontsize=5.5, handlelength=0.9, handletextpad=0.3, columnspacing=0.7, borderaxespad=0,
    ).set_gid("cohort-screen-legend")
    ax.set_gid("cohort-responsiveness-proportions")
    ax.set_xlim(-0.6, len(PANEL_GROUPS) - 0.4)
    ax.set_ylim(0, 100)
    ax.set_yticks([0, 50, 100])
    ax.set_xticks(x, [
        f"{group}\nn={int(n):,}"
        for group, n in zip(PANEL_GROUPS, pooled.n_joint_testable, strict=True)
    ])
    ax.set_ylabel("Responsive (%)", fontsize=6)
    ax.tick_params(labelsize=5.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def write_audits(cohort: dict, directory: Path = DERIVED) -> list[Path]:
    """Write all-event reusable counts with unambiguous grouping and denominator definitions."""
    directory.mkdir(parents=True, exist_ok=True)
    outputs = []
    for name, frame in (
        ("session-dmd-statistics.csv", cohort["sessions"]),
        ("group-statistics.csv", cohort["pooled"]),
    ):
        path = directory / name
        frame.to_csv(path, index=False, float_format="%.17g", lineterminator="\n")
        outputs.append(path)
    sources = [
        Path(__file__), ROOT / "src/openscope_p3_publication/slap2_standard_oddball_cohort.py",
        *[DATA / name for name in (
            "sessions.csv", "units.csv.gz", "stimulus-audit.json", "provenance.json",
        )],
    ]
    provenance = directory / "provenance.json"
    provenance.write_text(json.dumps({
        "version": 1, "groups": list(GROUPS), "minimum_eligible_sources": 20,
        "displayed_groups": list(PANEL_GROUPS),
        "response_rule": "Both Q1/Q2 raw p<0.05, abs(MI)>0.1; either sign.",
        "denominator": "Eligible jointly Q1/Q2-testable source/session observations.",
        "uncertainty": "Pooled bars + individual mouse/session proportions; no bootstrap.",
        "sources": [{"path": p.relative_to(ROOT).as_posix(), "sha256": sha256(p)} for p in sources],
        "outputs": [{"path": p.name, "sha256": sha256(p)} for p in outputs],
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return [*outputs, provenance]
