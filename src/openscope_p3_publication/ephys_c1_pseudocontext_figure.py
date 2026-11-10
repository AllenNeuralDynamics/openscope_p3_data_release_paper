"""Static supplemental ephys C1 repeat negative control, rendered entirely offline."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .ephys_c1_mean_traces import (
    SELECTION_RULE,
    SEM_RULE,
    draw_positive_q1_means,
    prepare_positive_q1_means,
)
from .ephys_c1_population import DIRECTORY as POPULATION_DIRECTORY
from .ephys_c1_population import load_c1_population
from .ephys_c1_pseudocontext import DIRECTORY as STATISTICS_DIRECTORY
from .ephys_c1_pseudocontext import load_pseudo, summarize_pseudo
from .standard_oddball_cohort import ROOT, sha256
from .standard_oddball_cohort_figure import (
    BOOTSTRAP_REPLICATES,
    BOOTSTRAP_RULE,
    BOOTSTRAP_SEED,
    SCREENS,
    _mouse_bootstrap_intervals,
    draw_cohort_panel,
)
from .standard_oddball_examples import WINDOW
from .standard_oddball_neuropixels import (
    CONTEXT_COLOR,
    DATA_PATH,
    PROVENANCE_PATH,
    _heatmap_display,
    load_diagnostic,
    save_diagnostic_svg,
)

OUTPUT = ROOT / "images/figures/generated/ephys-c1-pseudocontext.svg"
AUDIT_DIRECTORY = ROOT / "figure_sources/derived/ephys-c1-pseudocontext"
WIDTH_MM, HEIGHT_MM = 170.0, 125.0
MAP_LABELS = ("Pre-context C1", "Post-context C1", "Post - pre")


def prepare_pseudo_cohort(units: pd.DataFrame) -> dict:
    """Pool included sessions by mouse before using Figure 9's cluster bootstrap."""
    sessions, areas = summarize_pseudo(units)
    areas = areas.rename(columns={"region": "brain_area"})
    counts = [
        "n_joint_testable", *[f"n_{screen}_responsive" for screen, _ in SCREENS],
    ]
    mice = sessions.loc[sessions.included].groupby(
        ["region", "subject_id"], sort=True,
    )[counts].sum().reset_index().rename(columns={"region": "brain_area"})
    mice = mice.loc[mice.n_joint_testable.gt(0)].reset_index(drop=True)
    for row in areas.itertuples():
        group = mice.loc[mice.brain_area.eq(row.brain_area)]
        if not np.array_equal(group[counts].sum().to_numpy(), [getattr(row, c) for c in counts]):
            raise ValueError(f"Pseudo-context mouse totals disagree for {row.brain_area}.")
    _mouse_bootstrap_intervals(areas, mice)
    return {"areas": areas, "mice": mice, "sessions": sessions}


def build_ephys_c1_pseudocontext(
    output: Path = OUTPUT, audit_directory: Path = AUDIT_DIRECTORY,
) -> tuple[Path, ...]:
    """Write three matched heatmaps, Q1-positive means, regional bars, and audits."""
    population = load_c1_population()
    means = prepare_positive_q1_means(load_diagnostic(), population)
    count = int(means["positive"].sum())
    units, _, _ = load_pseudo()
    cohort = prepare_pseudo_cohort(units)
    heatmaps = population["heatmaps"]
    display = _heatmap_display(heatmaps, "delta")
    limit = display["limit"]
    totals = cohort["areas"][
        ["n_joint_testable", *[f"n_{screen}_responsive" for screen, _ in SCREENS]]
    ].sum()
    description = (
        "Supplementary Figure 7. Ephys C1 repeat negative control. "
        "A-C: pre-context C1, post-context C1, and post-minus-pre trial-mean SDFs "
        "for the same 203 eligible visual SUA from mouse 830794 used in Figure 9 D. "
        "All maps share the original context-only Rastermap row order, without "
        "a responsiveness filter, 34 presentations of a 90-degree grating per repeat, "
        "5-ms bins, and a 25-ms causal exponential kernel. Each condition subtracts "
        "its own unit-specific preceding-grey display baseline, pooled over complete "
        "half-open 20-ms bins; the difference is post minus pre after subtraction. "
        f"Shared color limits are +/-{limit:g} Hz, the ceiling of the pooled absolute "
        "99th percentile across all three maps, with saturation beyond the limits. "
        "Dashed lines mark onset; black bars mark the median presentation duration. "
        "D, centered beneath A and B: pre-C1 (dashed grey) and post-C1 (solid purple) "
        "baseline-subtracted "
        f"mean SDFs across the same {count} actual-context Q1-positive visual units. "
        f"{SELECTION_RULE} Shading is across-neuron sample SD (ddof=1) divided by "
        "sqrt(neuron count), not trial or across-mouse uncertainty. This is the same "
        "mean-trace population as the alternative layout, not Figure 9's joint-positive "
        "pool and not a selection on post-C1 pseudo-Q1. "
        "E, centered beneath B and C: regional pseudo-Q1, pseudo-Q2, and Both percentages "
        "from 13 sessions, "
        "using the Figure 9 regional inclusion criteria and jointly testable denominator. "
        f"Counts are {int(totals.n_q1_responsive)}/{int(totals.n_joint_testable)} pseudo-Q1, "
        f"{int(totals.n_q2_responsive)}/{int(totals.n_joint_testable)} pseudo-Q2, and "
        f"{int(totals.n_joint_responsive)}/{int(totals.n_joint_testable)} Both. "
        "Intervals are 95% mouse-cluster bootstrap intervals (10,000 resamples). "
        "Pseudo-Q1 compares post-C1 responses with the preceding within-block stimulus, "
        "whose orientation/type varies; it does not test an expected standard. "
        "Pseudo-Q2 compares post-C1 with pre-C1 after each trial's grey-baseline subtraction. "
        "Both screens use raw p < 0.05 and absolute MI > 0.1, either sign; "
        "this exploratory repeat comparison does not isolate prediction error."
    )
    with mpl.rc_context({
        "font.family": "DejaVu Sans", "font.size": 7,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.linewidth": 0.5,
    }):
        fig = plt.figure(figsize=(WIDTH_MM / 25.4, HEIGHT_MM / 25.4))
        for i, (label, x) in enumerate(zip(MAP_LABELS, (0.09, 0.36, 0.63), strict=True)):
            ax = fig.add_axes([x, 0.51, 0.235, 0.42])
            ax.set_gid(f"population-heatmap-{('pre', 'post', 'post-minus-pre')[i]}")
            image = ax.imshow(
                heatmaps[i], cmap="RdBu_r", vmin=-limit, vmax=limit,
                aspect="auto", interpolation="none", origin="upper",
                extent=[*WINDOW, heatmaps.shape[1] - 0.5, -0.5],
            )
            ax.axvline(0, color="black", linewidth=0.4, linestyle="--")
            for spine in ax.spines.values():
                spine.set_visible(False)
            ax.set_title(label, fontsize=8, pad=9)
            ax.set_xticks([-0.5, 0, 0.5])
            ax.tick_params(labelsize=7, length=2, pad=1.5)
            ax.set_xlabel("Time from 90-degree onset (s)", fontsize=7)
            if i == 0:
                ax.set_yticks([0, heatmaps.shape[1] - 1], ["1", str(heatmaps.shape[1])])
                ax.set_ylabel("Rastermap rank", fontsize=7)
            else:
                ax.set_yticks([])
            durations = [
                trial["event_window"][1]
                for condition in ("pre", "post") for trial in population["trials"][condition]
            ]
            ax.plot(
                [0, float(np.median(durations))], [1.01, 1.01],
                transform=ax.get_xaxis_transform(), color="black", linewidth=2, clip_on=False,
            )
            fig.text(
                x - 0.037, 0.955, "ABC"[i], fontweight="bold", fontsize=9,
                gid=f"panel-label-{'ABC'[i]}",
            )
        cax = fig.add_axes([0.89, 0.59, 0.013, 0.25])
        bar = fig.colorbar(image, cax=cax, ticks=[-limit, 0, limit], extend="both")
        bar.set_label("Change from baseline (Hz)", fontsize=7, labelpad=3)
        bar.ax.tick_params(labelsize=7, length=2)
        mean_ax = fig.add_axes([0.24, 0.10, 0.205, 0.235])
        mean_ax.set_gid("panel-D-pre-post-Q1-positive-means")
        draw_positive_q1_means(mean_ax, means)
        mean_ax.set_ylabel("\u0394 Firing rate (spikes/s)", fontsize=7)
        fig.text(
            0.203, 0.39, "D", fontweight="bold", fontsize=9, gid="panel-label-D",
        )
        cohort_ax = fig.add_axes([0.495, 0.10, 0.235, 0.235])
        draw_cohort_panel(cohort_ax, cohort, CONTEXT_COLOR)
        cohort_ax.set_ylabel("Responsive (%)", fontsize=7, labelpad=0)
        cohort_ax.tick_params(axis="x", labelrotation=60)
        for ax in (mean_ax, cohort_ax):
            ax.tick_params(labelsize=7)
            ax.xaxis.label.set_fontsize(7)
            for text in ax.get_legend().get_texts():
                text.set_fontsize(7)
        fig.text(
            0.458, 0.39, "E", fontweight="bold", fontsize=9, gid="panel-label-E",
        )
        fig.text(
            0.6125, 0.39, "Regional pseudo-Q1 / Q2 / Both",
            ha="center", fontsize=8,
        )
        save_diagnostic_svg(
            fig, output, "Supplementary Figure 7. Ephys C1 pseudo-context",
            description, {
                "data-comparison": "post-C1-pseudo-context-versus-pre-C1",
                "data-population-units": str(heatmaps.shape[1]),
                "data-shared-color-limit-hz": str(limit),
                "data-joint-testable": str(int(totals.n_joint_testable)),
                "data-mean-selection": "actual-context-positive-Q1-only",
                "data-mean-units": str(count),
            },
            target_width_mm=WIDTH_MM, target_height_mm=HEIGHT_MM,
        )
    audit_directory.mkdir(parents=True, exist_ok=True)
    outputs = [output]
    for name in ("areas", "mice"):
        path = audit_directory / f"{name}.csv"
        cohort[name].to_csv(path, index=False, lineterminator="\n")
        outputs.append(path)
    path = audit_directory / "display-units.csv"
    pd.DataFrame({
        "rastermap_rank": np.arange(1, heatmaps.shape[1] + 1),
        "nwb_unit_id": np.asarray(population["payload"]["unit_ids"])[population["order"]],
        "pre_baseline_hz": population["baselines"][0, population["order"]],
        "post_baseline_hz": population["baselines"][1, population["order"]],
        "actual_context_q1_p": means["q1_p"][population["order"]],
        "actual_context_q1_mi": means["q1_mi"][population["order"]],
        "mean_selected": means["positive"][population["order"]],
    }).to_csv(path, index=False, lineterminator="\n")
    outputs.append(path)
    path = audit_directory / "mean-traces.csv"
    pd.DataFrame({
        "time_seconds": means["time"],
        "pre_mean_hz": means["mean"][0], "pre_sem_hz": means["sem"][0],
        "post_mean_hz": means["mean"][1], "post_sem_hz": means["sem"][1],
    }).to_csv(path, index=False, lineterminator="\n")
    outputs.append(path)
    sources = [
        Path(__file__), DATA_PATH, PROVENANCE_PATH, POPULATION_DIRECTORY / "provenance.json",
        STATISTICS_DIRECTORY / "provenance.json",
        *[
            ROOT / f"src/openscope_p3_publication/{name}.py"
            for name in (
                "ephys_c1_pseudocontext", "ephys_c1_mean_traces", "standard_oddball_cohort_figure",
                "standard_oddball_neuropixels", "figure_typography",
            )
        ],
    ]
    provenance = {
        "version": 1, "description": description,
        "sources": [
            {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)} for path in sources
        ],
        "outputs": [{"name": path.name, "sha256": sha256(path)} for path in outputs],
        "display": display, "heatmap_shape": list(heatmaps.shape),
        "selection_rule": SELECTION_RULE, "mean_unit_count": count, "sem_rule": SEM_RULE,
        "selected_unit_ids": np.asarray(population["payload"]["unit_ids"])[
            means["positive"]
        ].tolist(),
        "bootstrap": {
            "rule": BOOTSTRAP_RULE, "replicates": BOOTSTRAP_REPLICATES, "seed": BOOTSTRAP_SEED,
        },
        "region_order": cohort["areas"].brain_area.tolist(),
    }
    path = audit_directory / "provenance.json"
    path.write_text(
        json.dumps(provenance, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8", newline="\n",
    )
    return (*outputs, path)
