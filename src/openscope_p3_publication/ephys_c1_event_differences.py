"""Exploratory post-minus-pre C1 heatmaps and mean differences for four event types."""

from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .ephys_c1_event_populations import DIRECTORY, EVENT_ORDER, load_event_differences
from .ephys_c1_population import DIRECTORY as REFERENCE_DIRECTORY
from .standard_oddball_cohort import ROOT, sha256
from .standard_oddball_examples import WINDOW
from .standard_oddball_neuropixels import _heatmap_display, save_diagnostic_svg

OUTPUT = ROOT / "images/figures/generated/ephys-c1-event-differences.svg"
AUDIT_DIRECTORY = ROOT / "figure_sources/derived/ephys-c1-event-differences"
LABELS = ("90 degrees", "45 degrees", "Halt", "Omission")
WIDTH_MM, HEIGHT_MM = 170.0, 125.0
DIFFERENCE_RULE = (
    "(post-C1 trial-mean SDF - post-C1 per-unit grey display baseline) minus "
    "(pre-C1 trial-mean SDF - pre-C1 per-unit grey display baseline)."
)
SEM_RULE = (
    "Mean and sample SD (ddof=1)/sqrt(n) of unitwise post-minus-pre differences; "
    "same units in every event, not independently combined pre/post SEMs."
)


def build_ephys_c1_event_differences(
    output: Path = OUTPUT, audit_directory: Path = AUDIT_DIRECTORY,
) -> tuple[Path, ...]:
    """Render fixed-population, shared-scale differences from verified offline snapshots."""
    data = load_event_differences()
    display = _heatmap_display(data["heatmaps"], "hz")
    limit = display["limit"]
    trace_limit = max(
        1, math.ceil(float(np.max(np.abs(np.stack([
            data["mean"] - data["sem"], data["mean"] + data["sem"],
        ]))))),
    )
    count = len(data["unit_ids"])
    summaries = []
    for i, event in enumerate(EVENT_ORDER):
        record = data["events"][event]
        exclusions = record["payload"].get("excluded_trials", [])
        summaries.append({
            "event_id": event, "unit_count": count,
            "pre_trials": len(record["trials"]["pre"]),
            "post_trials": len(record["trials"]["post"]),
            "excluded_pre": sum(row["condition"] == "pre" for row in exclusions),
            "excluded_post": sum(row["condition"] == "post" for row in exclusions),
            "clipped_heatmap_samples": int((np.abs(data["heatmaps"][i]) > limit).sum()),
            "heatmap_samples": int(data["heatmaps"][i].size),
        })
    description = (
        "Exploratory example-session C1 repeat comparison, separate from Supplementary "
        "Figure 7. A-D: matched 90-degree single presentations, 45-degree singles, halt, "
        f"and omission, respectively. All panels use the same {count} eligible visual "
        "SUA from mouse 830794's January 27, 2026 session and Figure 9's frozen "
        "context-only Rastermap row order, without Q1/Q2 filtering or event-specific "
        f"cell selection. Difference definition: {DIFFERENCE_RULE} Baselines pool complete "
        "half-open 20-ms preceding-grey bins. Each unit's pre/post SDF uses the same "
        "included trials as its baseline. SDFs use 5-ms bins, a causal 25-ms exponential "
        "kernel, and -0.75 to +0.75 seconds relative to event onset. Each event has "
        "34 pre and 34 post presentations, except 45 degrees: the first presentation "
        "in each C1 repeat lacks a preceding-grey baseline and is explicitly excluded, "
        "leaving 33 pre and 33 post. No baseline is borrowed or imputed. "
        f"Top: post-minus-pre heatmaps with one shared +/-{limit:g} Hz color limit, "
        "the ceiling of the pooled absolute 99th percentile across all four maps; "
        "samples beyond the limit saturate. Dashed lines mark onset; black bars "
        "mark the median nominal event window, capped at the displayed window. "
        "Bottom: mean unitwise difference (purple) and across-neuron SEM (shading), "
        f"all on +/-{trace_limit:g} Hz axes. {SEM_RULE} This is descriptive across-neuron "
        "uncertainty, not trial or mouse uncertainty or a significance test. These are "
        "event types in C1 controls, not actual oddball-context deviants. The comparison "
        "does not isolate temporal drift or prediction error. Existing S7 figures and "
        "Q1/Q2 classifications are unchanged."
    )
    with mpl.rc_context({
        "font.family": "DejaVu Sans", "font.size": 7,
        "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": 0.5,
    }):
        fig = plt.figure(figsize=(WIDTH_MM / 25.4, HEIGHT_MM / 25.4))
        for i, (event, x) in enumerate(zip(EVENT_ORDER, (0.075, 0.28, 0.485, 0.69), strict=True)):
            ax = fig.add_axes([x, 0.435, 0.175, 0.45])
            ax.set_gid(f"population-difference-{event}")
            image = ax.imshow(
                data["heatmaps"][i], cmap="RdBu_r", vmin=-limit, vmax=limit,
                aspect="auto", interpolation="none", origin="upper",
                extent=[*WINDOW, count - 0.5, -0.5],
            )
            ax.axvline(0, color="black", linewidth=0.4, linestyle="--")
            for spine in ax.spines.values():
                spine.set_visible(False)
            row = summaries[i]
            ax.set_title(
                f"{LABELS[i]}\n{row['pre_trials']} pre / {row['post_trials']} post",
                fontsize=7, pad=10,
            )
            ax.set_xticks([])
            if i == 0:
                ax.set_yticks([0, count - 1], ["1", str(count)])
                ax.set_ylabel("Rastermap rank", fontsize=7)
                ax.tick_params(labelsize=7, length=2, pad=1)
            else:
                ax.set_yticks([])
            duration = float(np.median([
                trial["event_window"][1]
                for c in ("pre", "post") for trial in data["events"][event]["trials"][c]
            ]))
            ax.plot(
                [0, min(duration, WINDOW[1])], [1.01, 1.01],
                transform=ax.get_xaxis_transform(), color="black", linewidth=2, clip_on=False,
            )
            fig.text(
                x - 0.03, 0.94, "ABCD"[i], fontweight="bold", fontsize=9,
                gid=f"panel-label-{'ABCD'[i]}",
            )
            ax = fig.add_axes([x, 0.13, 0.175, 0.235])
            ax.set_gid(f"mean-difference-{event}")
            mean, sem = data["mean"][i], data["sem"][i]
            ax.fill_between(
                data["time"], mean - sem, mean + sem,
                color="#635aa5", alpha=0.18, linewidth=0,
            ).set_gid(f"mean-difference-sem-{event}")
            ax.plot(
                data["time"], mean, color="#635aa5", linewidth=0.85,
            )[0].set_gid(f"mean-difference-line-{event}")
            ax.axhline(0, color="#777777", linewidth=0.35)
            ax.axvline(0, color="black", linewidth=0.35, linestyle="--")
            ax.set_xlim(WINDOW)
            ax.set_ylim(-trace_limit, trace_limit)
            ax.set_xticks([-0.5, 0, 0.5])
            ax.set_yticks([-trace_limit, 0, trace_limit])
            ax.tick_params(labelsize=6, length=2, pad=1)
            ax.set_xlabel("Time from event (s)", fontsize=6)
            if i == 0:
                ax.set_ylabel("Mean post - pre (Hz)", fontsize=7)
        cax = fig.add_axes([0.9, 0.53, 0.012, 0.24])
        bar = fig.colorbar(image, cax=cax, ticks=[-limit, 0, limit], extend="both")
        bar.set_label("Post - pre (Hz)", fontsize=7, labelpad=3)
        bar.ax.tick_params(labelsize=7, length=2)
        fig.text(
            0.47, 0.035,
            f"Separate grey-baseline subtraction | Same {count} units | Mean +/- across-neuron SEM",
            ha="center", fontsize=7,
        )
        save_diagnostic_svg(
            fig, output, "Four-event C1 differences: post minus pre", description, {
                "data-event-order": ",".join(EVENT_ORDER),
                "data-common-units": str(count),
                "data-shared-color-limit-hz": str(limit),
                "data-shared-mean-limit-hz": str(trace_limit),
            }, target_width_mm=WIDTH_MM, target_height_mm=HEIGHT_MM,
        )
    audit_directory.mkdir(parents=True, exist_ok=True)
    summary = audit_directory / "events.csv"
    pd.DataFrame(summaries).to_csv(summary, index=False, lineterminator="\n")
    traces = audit_directory / "mean-traces.csv"
    pd.concat([
        pd.DataFrame({
            "event_id": event, "time_seconds": data["time"],
            "mean_difference_hz": data["mean"][i], "sem_difference_hz": data["sem"][i],
        }) for i, event in enumerate(EVENT_ORDER)
    ], ignore_index=True).to_csv(traces, index=False, lineterminator="\n")
    outputs = [output, summary, traces]
    sources = [
        Path(__file__), DIRECTORY / "provenance.json", REFERENCE_DIRECTORY / "provenance.json",
        *[
            ROOT / f"src/openscope_p3_publication/{name}.py"
            for name in (
                "ephys_c1_event_populations", "standard_oddball_neuropixels", "figure_typography",
            )
        ],
    ]
    provenance = {
        "version": 1, "description": description, "difference_rule": DIFFERENCE_RULE,
        "sem_rule": SEM_RULE, "event_order": list(EVENT_ORDER), "unit_ids": data["unit_ids"],
        "row_order": data["order"].tolist(), "heatmap_shape": list(data["heatmaps"].shape),
        "display": display, "mean_limit_hz": trace_limit,
        "sources": [
            {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)} for path in sources
        ],
        "outputs": [{"name": path.name, "sha256": sha256(path)} for path in outputs],
    }
    path = audit_directory / "provenance.json"
    path.write_text(
        json.dumps(provenance, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8", newline="\n",
    )
    return (*outputs, path)
