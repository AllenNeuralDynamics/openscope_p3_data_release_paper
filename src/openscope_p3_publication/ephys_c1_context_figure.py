"""Alternative pre/context/post layout; preserves the original C1 supplement."""

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
from .ephys_c1_population import DIRECTORY as SPLIT_DIRECTORY
from .ephys_c1_population import load_c1_population
from .ephys_c1_pseudocontext import DIRECTORY as STATISTICS_DIRECTORY
from .ephys_c1_pseudocontext import load_pseudo
from .ephys_c1_pseudocontext_figure import prepare_pseudo_cohort
from .standard_oddball_cohort import ROOT, sha256
from .standard_oddball_cohort_figure import BOOTSTRAP_RULE, draw_cohort_panel
from .standard_oddball_examples import WINDOW, load_example_spikes
from .standard_oddball_neuropixels import (
    CONTEXT_COLOR,
    DATA_PATH,
    PROVENANCE_PATH,
    Diagnostic,
    _heatmap_display,
    load_diagnostic,
    save_diagnostic_svg,
)
from .standard_oddball_ordering import ORDER_PATH, load_context_order
from .standard_oddball_population import (
    POPULATION_PATH,
    POPULATION_PROVENANCE,
    load_population,
    population_arrays,
)

OUTPUT = ROOT / "images/figures/generated/ephys-c1-context-comparison.svg"
AUDIT_DIRECTORY = ROOT / "figure_sources/derived/ephys-c1-context-comparison"
CONDITIONS = ("pre", "context", "post")
LABELS = ("Pre-context C1", "Standard-oddball context", "Post-context C1")
WIDTH_MM, HEIGHT_MM = 170.0, 125.0


def prepare_context_comparison(data: Diagnostic, population: dict, split: dict) -> dict:
    """Combine aligned maps and one Q1-positive population without changing Figure 9."""
    ids = [unit["id"] for unit in data.units]
    if (
        ids != [unit["id"] for unit in population["units"]]
        or ids != split["payload"]["unit_ids"]
        or data.session["sessionId"] != population["session_id"]
        or population["session_id"] != split["payload"]["session_id"]
        or population["asset"] != split["payload"]["asset"]
        or population["parameters"] != split["payload"]["parameters"]
    ):
        raise ValueError("Context and split-C1 population identities or parameters disagree.")
    order = load_context_order(population)
    if not np.array_equal(order, split["order"]):
        raise ValueError("Context and split-C1 Rastermap row orders disagree.")
    rates, baselines = population_arrays(population)
    context = (rates - baselines[..., None])[0, order]
    heatmaps = np.stack([split["heatmaps"][0], context, split["heatmaps"][1]])
    limit = _heatmap_display(context[None, None], "hz")["limit"]
    return {
        "heatmaps": heatmaps, "order": order, "unit_ids": ids,
        **prepare_positive_q1_means(data, split),
        "trials": (
            split["trials"]["pre"], population["event"]["conditions"]["context"]["trials"],
            split["trials"]["post"],
        ),
        "display": {
            "limit": limit,
            "limit_rule": "Exact Figure 9 D context-only pooled absolute 99th-percentile ceiling.",
            "finite_samples": int(heatmaps.size),
            "clipped_samples_by_condition": (np.abs(heatmaps) > limit).sum(axis=(1, 2)).tolist(),
        },
    }


def build_ephys_c1_context_comparison(
    output: Path = OUTPUT, audit_directory: Path = AUDIT_DIRECTORY,
) -> tuple[Path, ...]:
    """Write a separate alternative SVG with source-backed mean and selection audits."""
    data = load_diagnostic()
    original = load_population(data, load_example_spikes(data)["events"][1])
    split = load_c1_population()
    prepared = prepare_context_comparison(data, original, split)
    cohort = prepare_pseudo_cohort(load_pseudo()[0])
    heatmaps, limit = prepared["heatmaps"], prepared["display"]["limit"]
    count = int(prepared["positive"].sum())
    denominator = int(cohort["areas"].n_joint_testable.sum())
    description = (
        "Alternative layout, not a replacement for Supplementary Figure 7. "
        "A: pre-context C1 heatmap. B, top: the exact actual-context heatmap from "
        "Figure 9 D. C, top: post-context C1 heatmap. All three show the same "
        f"{len(data.units)} eligible visual SUA, without a responsiveness filter, "
        f"in the original context-only Rastermap order on Figure 9 D's +/-{limit:g} Hz "
        "scale; values beyond the limits saturate. Each condition subtracts its own "
        "per-unit preceding-grey display baseline pooled over complete half-open 20-ms "
        "bins. SDFs use 5-ms bins, a causal 25-ms exponential kernel, and the window "
        "-0.75 to +0.75 seconds. Each block contributes 34 presentations, including "
        "zero-spike trials; context trials retain Figure 9's clean-predecessor rule. "
        "Dashed lines mark onset; black bars mark each condition's median presentation "
        "duration. The same 203 units from mouse 830794's January 27, 2026 session are "
        "displayed. B, bottom: pre-C1 (dashed grey) and post-C1 (solid purple) "
        f"baseline-subtracted mean SDFs across the same {count} units. {SELECTION_RULE} "
        "Shading is sample SD (ddof=1) across these neurons divided by sqrt(neuron count), "
        "not trial or across-mouse uncertainty. This population differs from Figure 9's "
        "positive Q1 AND Q2 mean-trace population. C, bottom: unchanged regional "
        f"pseudo-Q1, pseudo-Q2, and Both fractions from 13 sessions, sharing {denominator} "
        "jointly testable eligible units across included regions; intervals are the "
        f"Figure 9 10,000-resample 95% mouse-cluster bootstrap. {BOOTSTRAP_RULE}. "
        "Pseudo-Q1 tests post-C1 versus its preceding within-block stimulus, whose "
        "orientation/type varies, not an expected standard. Pseudo-Q2 compares "
        "post-C1 with pre-C1 after each trial's grey-baseline subtraction. Both screens "
        "require raw p <0.05 and absolute MI >0.1, either sign; Both is their intersection. "
        "Cohort eligibility, region inclusion, counts, and exclusions are unchanged. "
        "This exploratory repeat comparison does not isolate prediction error or drift."
    )
    with mpl.rc_context({
        "font.family": "DejaVu Sans", "font.size": 7,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.linewidth": 0.5,
    }):
        fig = plt.figure(figsize=(WIDTH_MM / 25.4, HEIGHT_MM / 25.4))
        fig.text(
            0.5, 0.975, "C1 repeats around the standard-oddball context | Neuropixels",
            ha="center", va="top", fontsize=8.5, fontweight="bold",
        )
        fig.text(
            0.5, 0.935, "Same 203 Figure 9 units and row order | 34 presentations per block",
            ha="center", fontsize=7,
        )
        for i, x in enumerate((0.09, 0.36, 0.63)):
            ax = fig.add_axes([x, 0.52, 0.235, 0.35])
            ax.set_gid(f"population-heatmap-{CONDITIONS[i]}")
            image = ax.imshow(
                heatmaps[i], cmap="RdBu_r", vmin=-limit, vmax=limit,
                aspect="auto", interpolation="none", origin="upper",
                extent=[*WINDOW, len(data.units) - 0.5, -0.5],
            )
            ax.axvline(0, color="black", linewidth=0.4, linestyle="--")
            for spine in ax.spines.values():
                spine.set_visible(False)
            ax.set_title(LABELS[i], fontsize=7, pad=9)
            ax.set_xticks([-0.5, 0, 0.5])
            ax.tick_params(labelsize=7, length=2, pad=1.5)
            ax.set_xlabel("Time from 90-degree onset (s)", fontsize=7)
            if i == 0:
                ax.set_yticks([0, len(data.units) - 1], ["1", str(len(data.units))])
                ax.set_ylabel("Figure 9 Rastermap rank", fontsize=7)
            else:
                ax.set_yticks([])
            duration = np.median([trial["event_window"][1] for trial in prepared["trials"][i]])
            ax.plot(
                [0, duration], [1.01, 1.01], transform=ax.get_xaxis_transform(),
                color="black", linewidth=2, clip_on=False,
            )
            fig.text(
                x - 0.037, 0.895, "ABC"[i], fontweight="bold", fontsize=9,
                gid=f"panel-label-{'ABC'[i]}",
            )
        cax = fig.add_axes([0.89, 0.56, 0.013, 0.25])
        bar = fig.colorbar(image, cax=cax, ticks=[-limit, 0, limit], extend="both")
        bar.set_label("Change from baseline (Hz)", fontsize=7, labelpad=3)
        bar.ax.tick_params(labelsize=7, length=2)
        ax = fig.add_axes([0.36, 0.15, 0.235, 0.21])
        ax.set_gid("panel-B-pre-post-Q1-positive-means")
        draw_positive_q1_means(ax, prepared)
        fig.text(
            0.4775, 0.425, f"Positive context Q1 (n={count})", ha="center", fontsize=7,
        )
        ax = fig.add_axes([0.66, 0.15, 0.265, 0.21])
        draw_cohort_panel(ax, cohort, CONTEXT_COLOR)
        ax.set_gid("panel-C-regional-pseudo-responsiveness")
        fig.text(
            0.7925, 0.425, "Regional pseudo-Q1 / Q2 / Both", ha="center", fontsize=7,
        )
        fig.text(
            0.09, 0.33,
            "Mean-trace selection:\nActual-context Q1\np < 0.05, MI > 0.1\n"
            "No Q2 restriction\nSame cells in both curves\n\nShading: across-neuron SEM",
            va="top", fontsize=7, linespacing=1.5,
        )
        fig.text(
            0.5, 0.025,
            f"Regional bars: 13 sessions | {denominator:,} jointly testable units | "
            "Q1 / Q2 / Both are exploratory pseudo-context screens",
            ha="center", fontsize=6,
        )
        save_diagnostic_svg(
            fig, output, "Alternative C1 layout: pre-C1, actual context, post-C1",
            description, {
                "data-conditions": "pre,context,post",
                "data-shared-color-limit-hz": str(limit),
                "data-mean-selection": "actual-context-positive-Q1-only",
                "data-mean-units": str(count),
                "data-joint-testable": str(denominator),
            }, target_width_mm=WIDTH_MM, target_height_mm=HEIGHT_MM,
        )
    audit_directory.mkdir(parents=True, exist_ok=True)
    path = audit_directory / "mean-traces.csv"
    pd.DataFrame({
        "time_seconds": prepared["time"],
        "pre_mean_hz": prepared["mean"][0], "pre_sem_hz": prepared["sem"][0],
        "post_mean_hz": prepared["mean"][1], "post_sem_hz": prepared["sem"][1],
    }).to_csv(path, index=False, lineterminator="\n")
    outputs = [output, path]
    path = audit_directory / "unit-selection.csv"
    order = prepared["order"]
    pd.DataFrame({
        "rastermap_rank": np.arange(1, len(data.units) + 1),
        "nwb_unit_id": np.asarray(prepared["unit_ids"])[order],
        "actual_context_q1_p": prepared["q1_p"][order],
        "actual_context_q1_mi": prepared["q1_mi"][order],
        "mean_selected": prepared["positive"][order],
    }).to_csv(path, index=False, lineterminator="\n")
    outputs.append(path)
    path = audit_directory / "regions.csv"
    cohort["areas"].to_csv(path, index=False, lineterminator="\n")
    outputs.append(path)
    sources = [
        Path(__file__), DATA_PATH, PROVENANCE_PATH, POPULATION_PATH, POPULATION_PROVENANCE,
        ORDER_PATH, SPLIT_DIRECTORY / "provenance.json", STATISTICS_DIRECTORY / "provenance.json",
        *[
            ROOT / f"src/openscope_p3_publication/{name}.py"
            for name in (
                "ephys_c1_population", "ephys_c1_pseudocontext_figure", "ephys_c1_mean_traces",
                "standard_oddball_cohort_figure", "standard_oddball_neuropixels",
                "figure_typography",
            )
        ],
    ]
    path = audit_directory / "provenance.json"
    path.write_text(json.dumps({
        "version": 1, "description": description, "conditions": list(CONDITIONS),
        "display": prepared["display"], "selection_rule": SELECTION_RULE,
        "mean_unit_count": count,
        "selected_unit_ids": np.asarray(prepared["unit_ids"])[prepared["positive"]].tolist(),
        "sem_rule": SEM_RULE,
        "bootstrap_rule": BOOTSTRAP_RULE,
        "sources": [
            {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)} for path in sources
        ],
        "outputs": [{"name": path.name, "sha256": sha256(path)} for path in outputs],
    }, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    return (*outputs, path)
