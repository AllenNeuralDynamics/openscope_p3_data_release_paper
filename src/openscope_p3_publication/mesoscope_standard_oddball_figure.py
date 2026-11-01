"""Matched, final-width mesoscope oddball columns rendered from frozen inputs only."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .figures import PLATFORM_LOGO_PROVENANCE_PATH, load_platform_logos
from .mesoscope_standard_oddball import (
    ASSET_ID,
    ASSET_SHA256,
    ROOT,
    SIGNALS,
    SNAPSHOT,
    WINDOW,
    load_snapshot,
    sha256,
)
from .mesoscope_standard_oddball_cohort_figure import (
    cohort_plot_data,
    draw_panel,
    signal_panel,
    write_cohort_audits,
)
from .mesoscope_standard_oddball_display import (
    PANEL_A_DFF_PEAK_THRESHOLD,
    context_dff_peaks,
    select_display_examples,
)
from .standard_oddball_candidates import CONTROL_LINE_ALPHA, CONTROL_LINE_COLOR
from .standard_oddball_neuropixels import CONTEXT_COLOR, save_diagnostic_svg
from .standard_oddball_publication_data import DIRECTORY as PUBLICATION_DIRECTORY

WIDTH_MM, HEIGHT_MM = 54.0, 174.0
OUTPUT_DIR = ROOT / "images/figures/generated"
AUDIT_DIR = ROOT / "figure_sources/derived/mesoscope-standard-oddball-90"
LABELS = {"dff": "ΔF/F change (%)", "oasis": "OASIS change (a.u.)"}


def load_display_snapshot(
    payload: dict, statistics: pd.DataFrame, arrays: dict, directory: Path = SNAPSHOT,
) -> tuple[dict, dict]:
    """Validate display-only replacement trials, stimulus bounds and anatomical metadata."""
    display = json.loads((directory / "display-provenance.json").read_text())
    if (
        display.get("version") != 2 or display.get("session_id") != payload["session_id"]
        or display.get("asset_id") != ASSET_ID or display.get("asset_sha256") != ASSET_SHA256
    ):
        raise ValueError("Unsupported mesoscope display supplement.")
    for source in display["sources"]:
        if sha256(ROOT / source["path"]) != source["sha256"]:
            raise ValueError(f"Mesoscope display source changed: {source['path']}")
    output = display["output"]
    if sha256(directory / output["path"]) != output["sha256"]:
        raise ValueError("Mesoscope display snapshot checksum changed.")
    previous = payload["example_roi_keys"][0]
    expected = select_display_examples(payload, statistics, arrays)
    if (
        display["excluded_responsive_roi"] != previous
        or display["example_roi_keys"] != expected
        or expected[1] != payload["example_roi_keys"][1]
        or display.get("panel_a_dff_peak_threshold") != PANEL_A_DFF_PEAK_THRESHOLD
        or display.get("responsive_dff_peak") != float(
            context_dff_peaks(arrays)[payload["roi_keys"].index(expected[0])]
        )
    ):
        raise ValueError("Replacement example selection changed.")
    if not all(display["native_sources"][s]["native_statistics_verified"] for s in SIGNALS):
        raise ValueError("Replacement native statistics must match the frozen analysis.")
    prepared = deepcopy(payload)
    prepared["example_roi_keys"] = expected
    prepared["panel_a_dff_peak_threshold"] = PANEL_A_DFF_PEAK_THRESHOLD
    prepared["panel_a_responsive_dff_peak"] = display["responsive_dff_peak"]
    prepared["stimulus_spans"] = {}
    for condition in ("context", "control"):
        rows = display["trials"][condition]
        original = payload["trials"][condition]
        if len(rows) != len(original):
            raise ValueError("Display stimulus trial count changed.")
        for row, frozen in zip(rows, original, strict=True):
            if (
                row["index"] != frozen["index"] or row["start_time"] != frozen["onset"]
                or not 0 < row["stop_time"] - row["start_time"] < 0.5
            ):
                raise ValueError("Display stimulus identity or actual duration changed.")
            if condition == "context" and (
                row["comparison_start_time"] != frozen["comparison"][0]
                or not (
                    row["comparison_start_time"] < row["comparison_stop_time"] < row["start_time"]
                )
            ):
                raise ValueError("Preceding stimulus bounds changed.")
    context = display["trials"]["context"]
    prepared["stimulus_spans"]["response"] = [
        0.0, float(np.median([r["stop_time"] - r["start_time"] for r in context])),
    ]
    prepared["stimulus_spans"]["comparison"] = np.median([
        [r["comparison_start_time"] - r["start_time"],
         r["comparison_stop_time"] - r["start_time"]] for r in context
    ], axis=0).tolist()
    planes = {p["plane"]: p for p in display["planes"]}
    if len(planes) != len(payload["planes"]):
        raise ValueError("Display anatomical plane identities changed.")
    for original in payload["planes"]:
        plane = planes[original["plane"]]
        if (
            plane["area"] not in ("VISp", "VISl") or not np.isfinite(plane["depth_um"])
            or plane["depth_um"] < 0
            or original["location"] != f"Structure: {plane['area']} Depth: {plane['depth_um']:g}"
        ):
            raise ValueError("Display anatomical area/depth differs from the frozen source.")
    prepared["plane_metadata"] = planes
    result = dict(arrays)
    with np.load(directory / output["path"], allow_pickle=False) as archive:
        replacement = {key: archive[key] for key in archive.files}
    expected_keys = {f"examples_{s}_{c}" for s in SIGNALS for c in ("context", "control")}
    if set(replacement) != expected_keys:
        raise ValueError("Replacement example arrays are incomplete.")
    roi_index = payload["roi_keys"].index(expected[0])
    for signal in SIGNALS:
        for c, condition in enumerate(("context", "control")):
            key = f"examples_{signal}_{condition}"
            values = replacement[key]
            if (
                values.shape != arrays[key].shape or not np.isfinite(values).all()
                or not np.array_equal(values[1], arrays[key][1])
                or not np.array_equal(
                    values[0].mean(axis=0).astype(np.float32),
                    arrays[f"delta_{signal}"][c, roi_index],
                )
            ):
                raise ValueError("Replacement trials differ from frozen population/comparison.")
    result.update(replacement)
    return prepared, result


def population_order(payload: dict, signal: str) -> list[int]:
    """Use the same saved context-ΔF/F Rastermap order in both signal variants."""
    if signal not in SIGNALS:
        raise ValueError(f"Unknown mesoscope signal: {signal}")
    return payload["order"]


def cohort_curves(
    statistics, arrays: dict, signal: str, roi_keys: list[str],
    *, responsive_column: str = "positive_joint",
) -> dict:
    """Compute descriptive, equally weighted ROI/source means and across-source SEM."""
    rows = statistics.loc[statistics.signal.eq(signal)].set_index("roi_key").loc[roi_keys]
    result = {}
    for group, mask in (
        ("positive", rows[responsive_column].to_numpy()),
        ("nonq2", rows.q2_nonsignificant.to_numpy()),
    ):
        if mask.sum() < 2:
            raise ValueError(f"{signal}/{group}: at least two eligible ROIs required for SEM.")
        values = arrays[f"delta_{signal}"][:, mask].astype(np.float64)
        result[group] = {
            "count": int(mask.sum()), "mask": mask,
            "mean": values.mean(axis=1),
            "sem": values.std(axis=1, ddof=1) / math.sqrt(mask.sum()),
        }
    return result


def color_limit(values: np.ndarray) -> float:
    """Use a symmetric rounded 99th absolute percentile without changing scientific values."""
    q = float(np.quantile(np.abs(values), 0.99))
    if not np.isfinite(q) or q <= 0:
        raise ValueError("A nonzero finite heatmap scale is required.")
    step = 10 ** math.floor(math.log10(q))
    return float(math.ceil(q / step) * step)


def render_column(
    payload: dict, statistics, arrays: dict, signal: str, logo: Path, output: Path,
    *, cohort: dict | None, platform: str = "mesoscope", native_label: str | None = None,
    description: str | None = None,
) -> dict:
    """Draw native optical panels; preserve the mesoscope cohort or an explicit SLAP2 scope."""
    if (
        platform not in ("mesoscope", "slap2")
        or (platform == "mesoscope" and cohort is None)
        or (platform == "slap2" and (
            not native_label or not description or (cohort is not None and signal != "glutamate")
        ))
    ):
        raise ValueError("Optical columns require an explicit platform, scope and native units.")
    label = LABELS[signal] if platform == "mesoscope" else native_label
    responsive_column = "positive_joint" if platform == "mesoscope" else (
        "positive_joint" if payload["positive_examples_only"][signal] else "joint_responsive"
    )
    curves = cohort_curves(
        statistics, arrays, signal, payload["roi_keys"], responsive_column=responsive_column,
    )
    time = arrays["time"]
    dt = float(np.median(np.diff(time)))
    extent = [time[0] - dt / 2, time[-1] + dt / 2]
    trials = arrays[f"examples_{signal}_context"] if platform == "mesoscope" else [
        arrays[f"examples_{signal}_context_{i}"] for i in range(2)
    ]
    trial_limit = color_limit(
        trials if platform == "mesoscope" else np.concatenate(trials),
    )
    order = population_order(payload, signal) if platform == "mesoscope" else payload["order"]
    population = arrays[f"delta_{signal}"][0, order]
    population_limit = color_limit(population)
    if platform == "mesoscope":
        examples = {
            c: arrays[f"examples_{signal}_{c}"].astype(np.float64)
            for c in ("context", "control")
        }
        centers = {c: v.mean(axis=1) for c, v in examples.items()}
        errors = {c: v.std(axis=1, ddof=1) / np.sqrt(v.shape[1]) for c, v in examples.items()}
    else:
        examples = {
            c: [arrays[f"examples_{signal}_{c}_{i}"].astype(np.float64) for i in range(2)]
            for c in ("context", "control")
        }
        centers = {c: np.stack([v.mean(axis=0) for v in rows]) for c, rows in examples.items()}
        errors = {
            c: np.stack([v.std(axis=0, ddof=1) / math.sqrt(len(v)) for v in rows])
            for c, rows in examples.items()
        }
    lower = min(float((centers[c] - errors[c]).min()) for c in centers)
    upper = max(float((centers[c] + errors[c]).max()) for c in centers)
    padding = (upper - lower) * 0.05
    with mpl.rc_context({
        "font.family": "DejaVu Sans", "font.size": 6,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.linewidth": 0.45, "axes.labelpad": 2,
        "xtick.labelsize": 5.5, "ytick.labelsize": 5.5,
        "xtick.major.size": 1.5, "ytick.major.size": 1.5,
        "xtick.major.pad": 1, "ytick.major.pad": 1,
    }):
        fig = plt.figure(figsize=(WIDTH_MM / 25.4, HEIGHT_MM / 25.4))

        def axis(left: float, top: float, width: float, height: float, gid: str):
            ax = fig.add_axes([
                left / WIDTH_MM, 1 - (top + height) / HEIGHT_MM,
                width / WIDTH_MM, height / HEIGHT_MM,
            ])
            ax.set_gid(gid)
            return ax

        icon = axis(17.28, 2, 5, 5, f"platform-logo-{platform}")
        icon.imshow(plt.imread(logo), interpolation="none")
        icon.set_xticks([])
        icon.set_yticks([])
        icon.set_axis_off()
        fig.text(
            0.435, 1 - 4.5 / HEIGHT_MM, "Mesoscope" if platform == "mesoscope" else "SLAP2",
            fontsize=7.5, fontweight="bold", va="center", gid=f"platform-label-{platform}",
        )
        def guides(ax):
            ax.axvspan(
                *payload["stimulus_spans"]["comparison"], color="#CFAF6E",
                alpha=0.16, linewidth=0, gid=f"{ax.get_gid()}-preceding-stimulus-shading",
            )
            ax.axvspan(
                *payload["stimulus_spans"]["response"], color="#777777",
                alpha=0.15, linewidth=0, gid=f"{ax.get_gid()}-oddball-stimulus-shading",
            )
            ax.axvline(0, color="black", linewidth=0.35, linestyle="--")
            ax.axhline(0, color="#777777", linewidth=0.35)
            ax.set_xlim(WINDOW)
            ax.set_xticks([-0.5, 0, 0.5], ["-0.5", "0", "0.5"])
            ax.yaxis.set_major_locator(mpl.ticker.MaxNLocator(3, prune="both"))

        for i, left in enumerate((10.8, 32.4)):
            ax = axis(left, 10.8, 15.66, 18, f"example-trial-heatmap-{i}")
            ax.imshow(
                trials[i], cmap="RdBu_r", vmin=-trial_limit, vmax=trial_limit,
                aspect="auto", interpolation="none", origin="upper",
                extent=[*extent, len(trials[i]) + 0.5, 0.5],
            )
            ax.axvline(0, color="black", linewidth=0.35, linestyle="--")
            ax.set_xlim(WINDOW)
            ax.set_xticks([])
            ax.set_yticks([1, len(trials[i])])
            ax.set_title("Responsive" if i == 0 else "Unresponsive", fontsize=6.5, pad=2)
            if i == 0:
                ax.set_ylabel("Trial", fontsize=6)
            ax = axis(left, 30.96, 15.66, 18, f"example-trial-mean-{i}")
            guides(ax)
            for c, condition in enumerate(("context", "control")):
                color = CONTEXT_COLOR if c == 0 else CONTROL_LINE_COLOR
                alpha = 1 if c == 0 else CONTROL_LINE_ALPHA
                ax.fill_between(
                    time, centers[condition][i] - errors[condition][i],
                    centers[condition][i] + errors[condition][i],
                    color=color, alpha=0.15 if c == 0 else 0.1, linewidth=0,
                )
                ax.plot(
                    time, centers[condition][i], color=color, alpha=alpha, linewidth=0.75,
                    gid=f"example-{condition}-{i}",
                )
            ax.set_ylim(lower - padding, upper + padding)
            if i == 0:
                ax.set_ylabel(label, fontsize=5.5)
        fig.text(
            0.545, 1 - 54.54 / HEIGHT_MM, "Time from deviant (s)",
            fontsize=6, ha="center",
        )
        ax = axis(10.8, 58.5, 35.1, 38.7, "population-heatmap-context")
        ax.imshow(
            population, cmap="RdBu_r", vmin=-population_limit, vmax=population_limit,
            aspect="auto", interpolation="none", origin="upper",
            extent=[*extent, len(population) + 0.5, 0.5],
        )
        ax.axvline(0, color="black", linewidth=0.35, linestyle="--")
        ax.set_xlim(WINDOW)
        ax.set_xticks([])
        ax.set_yticks([1, len(population)])
        ax.set_ylabel("Rastermap rank" if platform == "mesoscope" else "Source rank", fontsize=6)
        if platform == "slap2":
            groups = payload["dmd_groups"]
            if sum(g["count"] for g in groups) != len(population) or len(groups) != 2:
                raise ValueError("SLAP2 heatmap DMD labels must cover the full population.")
            boundary = groups[0]["count"]
            ax.set_yticks([1, boundary, len(population)])
            ax.axhline(
                boundary + 0.5, color="black", linewidth=0.6, gid="population-dmd-divider",
            )
            offset = 0
            for group in groups:
                ax.text(
                    1.02, offset + (group["count"] + 1) / 2,
                    f"{group['label']}\nn={group['count']}",
                    transform=ax.get_yaxis_transform(), va="center", fontsize=5,
                    gid=f"population-dmd-label-{group['label']}",
                )
                offset += group["count"]
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax = axis(10.8, 99.36, 35.1, 25.2, "population-mean-overlay")
        guides(ax)
        for group, style in (("positive", "-"), ("nonq2", ":")):
            for c, condition in enumerate(("context", "control")):
                mean, sem = curves[group]["mean"][c], curves[group]["sem"][c]
                color = CONTEXT_COLOR if c == 0 else CONTROL_LINE_COLOR
                ax.fill_between(
                    time, mean - sem, mean + sem,
                    color=color, alpha=0.18 if c == 0 else 0.12, linewidth=0,
                    gid=f"population-sem-{group}-{condition}",
                )
                ax.plot(
                    time, mean, color=color, alpha=1 if c == 0 else CONTROL_LINE_ALPHA,
                    linestyle=style, linewidth=0.85, gid=f"population-{group}-{condition}",
                )
        ax.set_ylabel(label, fontsize=6)
        ax.set_xlabel("Time from deviant (s)", fontsize=6)
        if platform == "slap2":
            responsive_name = (
                "positive-joint" if responsive_column == "positive_joint" else "joint-responsive"
            )
            for letter, top in (("A", 10.8), ("B", 58.5)):
                fig.text(
                    0.015, 1 - top / HEIGHT_MM, letter,
                    fontsize=9, fontweight="bold", gid=f"panel-label-{letter}",
                )
            if cohort is not None:
                from .slap2_standard_oddball_cohort_figure import draw_panel as draw_slap2_panel

                cohort_axis = axis(10.8, 143, 35.1, 22, "cohort-responsiveness-proportions")
                draw_slap2_panel(cohort_axis, cohort, CONTEXT_COLOR)
                fig.text(
                    10.8 / WIDTH_MM, 1 - 136 / HEIGHT_MM, "2 sessions, 2 mice",
                    fontsize=5.5, va="baseline", gid="cohort-sample-size",
                )
                fig.text(
                    0.015, 1 - 136 / HEIGHT_MM, "C", fontsize=9,
                    fontweight="bold", gid="panel-label-C",
                )
            description += (
                f" Heatmap limits: A ±{trial_limit:g}, B ±{population_limit:g}; "
                "rounded 99th absolute percentiles, blue-negative/red-positive, no colorbar. "
                f"Population curves include {curves['positive']['count']} "
                f"{responsive_name} "
                "and "
                f"{curves['nonq2']['count']} Q2-nonsignificant sources."
            )
            save_diagnostic_svg(
                fig, output, f"SLAP2 90-degree standard oddball: {signal}", description,
                {
                    "data-signal": signal, "data-session-id": payload["session_id"],
                    "data-event-id": "orientation_90", "data-session-count": "1",
                    "data-eligible-roi-count": str(len(payload["roi_keys"])),
                    **{
                        f"data-{condition}-trial-counts-by-dmd": json.dumps({
                            d: len(w[condition]) for d, w in payload["trials_by_dmd"].items()
                        }, sort_keys=True)
                        for condition in ("context", "control")
                    },
                    "data-example-roi-keys": ",".join(payload["example_roi_keys"]),
                    "data-rastermap-fit-signal": "glutamate",
                    "data-population-ordering": "dmd-grouped-context-glutamate-rastermap",
                    "data-dmd-source-counts": ",".join(
                        str(g["count"]) for g in payload["dmd_groups"]
                    ),
                    "data-population-order": ",".join(payload["roi_keys"][i] for i in order),
                    "data-response-window-seconds": "0.5",
                    "data-stimulus-window-seconds": str(payload["stimulus_spans"]["response"][1]),
                    "data-cohort-panel": "present" if cohort is not None else "absent",
                    **({
                        "data-cohort-session-count": "2", "data-cohort-mouse-count": "2",
                        "data-cohort-uncertainty": "individual-mouse-points-no-bootstrap",
                        "data-cohort-groups": "DMD1,DMD2",
                    } if cohort is not None else {}),
                    "data-population-responsive-count": str(curves["positive"]["count"]),
                    "data-population-responsive-rule": responsive_column,
                    "data-population-nonq2-count": str(curves["nonq2"]["count"]),
                    "data-trial-heatmap-limit": str(trial_limit),
                    "data-population-heatmap-limit": str(population_limit),
                },
                target_width_mm=WIDTH_MM, target_height_mm=HEIGHT_MM,
            )
            return {
                "signal": signal, "trial_heatmap_limit": trial_limit,
                "population_heatmap_limit": population_limit,
                "responsive_count": curves["positive"]["count"],
                "responsive_rule": responsive_column,
                "nonq2_count": curves["nonq2"]["count"],
                "display_order": [payload["roi_keys"][i] for i in order],
            }
        panel = signal_panel(cohort, signal)
        cohort_axis = axis(10.8, 143, 35.1, 22, "cohort-responsiveness-proportions")
        draw_panel(cohort_axis, panel, CONTEXT_COLOR)
        inventory = cohort["inventory"].loc[cohort["inventory"].included]
        fig.text(
            10.8 / WIDTH_MM, 1 - 136 / HEIGHT_MM,
            f"{len(inventory)} sessions, {inventory.subject_id.nunique()} mice",
            fontsize=5.5, va="baseline", gid="cohort-sample-size",
        )
        for label, top in (("A", 10.8), ("B", 58.5), ("C", 136)):
            fig.text(
                0.015, 1 - top / HEIGHT_MM, label,
                fontsize=9, fontweight="bold", gid=f"panel-label-{label}",
            )
        n_context = len(payload["trials"]["context"])
        n_control = len(payload["trials"]["control"])
        description = (
            f"Mesoscope {signal} comparison. A/B: mouse 832700, January 30 2026, one session. "
            f"{len(payload['roi_keys'])} High/Intermediate-SNR soma-labelled ROIs in VISp/VISl. "
            f"{n_context} clean 90-degree context and {n_control} matched control trials. "
            "A: identical positive-joint and Q2-nonsignificant example ROIs across both versions, "
            f"{', '.join(payload['example_roi_keys'])}; context trial heatmaps and "
            "context (green)/control (grey, 50% opacity) means with across-trial SEM. "
            "The responsive example additionally requires a peak trial-averaged "
            "baseline-subtracted context dF/F >0.5 during [0,0.5) s in native stored units. "
            f"Its peak is {payload['panel_a_responsive_dff_peak']:.6g}. "
            "This amplitude gate applies only to panel A, not population classifications. "
            "Unresponsive means Q2-nonsignificant, not absence of visual responsiveness. "
            "B: context population heatmap in the same frozen context-dF/F Rastermap order "
            "for both signals. Population means and across-neuron SEM: solid positive Q1/Q2 "
            f"responders ({curves['positive']['count']} ROIs), dotted Q2-nonsignificant "
            f"({curves['nonq2']['count']} ROIs), classified separately per signal. "
            "All displayed values subtract each trial's native preceding-grey baseline. "
            "Statistical windows use native-frame means, not display interpolation: paired "
            "Q1 oddball versus preceding standard over equal 500-ms windows; Q2 Mann-Whitney "
            "on context/control response minus full preceding-grey baseline. Exploratory "
            "p<0.05 and abs(MI)>0.1; solid means additionally require both MI>0.1. "
            "Signed MIs are not clipped. No firing-rate eligibility gate, spike conversion, "
            "or Neuropixels smoothing kernel. Linear alignment at approximately 9.48 Hz "
            "is display-only. Tan/grey shading shows actual preceding-standard/oddball "
            "presentation windows (median trial-aligned bounds, approximately 367 ms), "
            "not the 500-ms statistical windows. X-limits remain -0.75 to +0.75 s. "
            f"Units: {LABELS[signal]}; native stored values without additional scaling. "
            "Heatmaps blue-negative/red-positive, no colorbar; rounded 99th absolute percentile "
            f"limits: A ±{trial_limit:g}, B ±{population_limit:g}; larger values saturate. "
            "These response-selected curves are descriptive; SEM is not across mice. "
            f"C: 90-degree cohort across {len(inventory)} sessions in "
            f"{inventory.subject_id.nunique()} mice. Pool planes within session/area; "
            "include groups with at least 20 eligible somatic High/Intermediate-SNR ROIs, "
            "before checking testability. Q1/Q2/Both bars include either MI sign and use "
            "this signal's own eligible jointly Q1/Q2-testable denominator; n labels are "
            "ROI/session observations, not unique longitudinal neurons. Heights are pooled "
            "counts, not means of session/mouse percentages. Uncapped lines show exact "
            "95% percentile mouse-cluster bootstrap bounds (10,000 resamples, seed 0): "
            "resample whole mice carrying every retained session, then recompute pooled ratios. "
            "C has no amplitude gate. "
            + " ".join(
                f"{r.brain_area}: {r.n_joint_testable} jointly testable / "
                f"{r.n_eligible} eligible ROI/session observations, "
                f"{r.n_contributing_sessions} contributing sessions, {r.n_mice} mice; "
                f"Q1 {r.n_q1_responsive}, Q2 {r.n_q2_responsive}, Both {r.n_joint_responsive}."
                for r in panel["areas"].itertuples()
            )
        )
        save_diagnostic_svg(
            fig, output, f"Mesoscope 90-degree standard oddball: {signal}", description,
            {
                "data-signal": signal, "data-session-id": payload["session_id"],
                "data-session-count": "1", "data-event-id": "orientation_90",
                "data-cohort-session-count": str(len(inventory)),
                "data-cohort-mouse-count": str(inventory.subject_id.nunique()),
                "data-cohort-minimum-eligible-rois": "20",
                "data-cohort-denominator": "signal-specific-eligible-joint-testable",
                "data-example-roi-keys": ",".join(payload["example_roi_keys"]),
                "data-panel-a-dff-peak-threshold": str(PANEL_A_DFF_PEAK_THRESHOLD),
                "data-panel-a-responsive-dff-peak": str(payload["panel_a_responsive_dff_peak"]),
                "data-eligible-roi-count": str(len(payload["roi_keys"])),
                "data-context-trial-count": str(n_context),
                "data-control-trial-count": str(n_control),
                "data-population-ordering": "context-dff-rastermap",
                "data-rastermap-fit-signal": "dff", "data-rastermap-fit-condition": "context",
                "data-response-window-seconds": "0.5",
                "data-stimulus-window-seconds": str(payload["stimulus_spans"]["response"][1]),
                "data-population-positive-count": str(curves["positive"]["count"]),
                "data-population-nonq2-count": str(curves["nonq2"]["count"]),
                "data-population-order": ",".join(payload["roi_keys"][i] for i in order),
                "data-trial-heatmap-limit": str(trial_limit),
                "data-population-heatmap-limit": str(population_limit),
                "data-native-unit": "%" if signal == "dff" else "a.u.",
            },
            target_width_mm=WIDTH_MM, target_height_mm=HEIGHT_MM,
        )
    return {
        "signal": signal, "trial_heatmap_limit": trial_limit,
        "population_heatmap_limit": population_limit,
        "positive_count": curves["positive"]["count"], "nonq2_count": curves["nonq2"]["count"],
        "display_order": [payload["roi_keys"][i] for i in order],
    }


def build_mesoscope_standard_oddball(
    output_dir: Path = OUTPUT_DIR, audit_dir: Path = AUDIT_DIR, snapshot: Path = SNAPSHOT,
    *, primary_only: bool = False,
) -> list[Path]:
    """Build both matched columns and a full ROI audit from committed data."""
    payload, statistics, arrays = load_snapshot(snapshot)
    payload, arrays = load_display_snapshot(payload, statistics, arrays, snapshot)
    logo = load_platform_logos()["mesoscope"]
    cohort = cohort_plot_data()
    cohort_paths = write_cohort_audits(
        cohort, audit_dir.parent / "mesoscope-standard-oddball-cohort",
    )
    paths, summaries = [], []
    for signal in (("dff",) if primary_only else SIGNALS):
        output = output_dir / f"mesoscope-standard-oddball-90-{signal}.svg"
        summaries.append(render_column(
            payload, statistics, arrays, signal, logo, output, cohort=cohort,
        ))
        paths.append(output)
    audit_dir.mkdir(parents=True, exist_ok=True)
    table_path = audit_dir / "roi-statistics.csv"
    audited = statistics.copy()
    ranks = {payload["roi_keys"][i]: rank + 1 for rank, i in enumerate(payload["order"])}
    audited["rastermap_rank"] = audited.roi_key.map(ranks)
    audited["depth_um"] = audited.plane.map({
        plane: record["depth_um"] for plane, record in payload["plane_metadata"].items()
    })
    for signal in SIGNALS:
        order = population_order(payload, signal)
        ranks = {payload["roi_keys"][i]: rank + 1 for rank, i in enumerate(order)}
        audited[f"{signal}_display_rank"] = audited.roi_key.map(ranks)
    audited["example"] = audited.roi_key.isin(payload["example_roi_keys"])
    peaks = dict(zip(payload["roi_keys"], context_dff_peaks(arrays), strict=True))
    audited["panel_a_dff_peak"] = audited.roi_key.map(peaks)
    audited.to_csv(table_path, index=False, float_format="%.17g", lineterminator="\n")
    provenance_path = audit_dir / "provenance.json"
    sources = [
        Path(__file__), ROOT / "src/openscope_p3_publication/figure_typography.py",
        ROOT / "src/openscope_p3_publication/figures.py",
        logo, PLATFORM_LOGO_PROVENANCE_PATH, snapshot / "provenance.json",
        snapshot / "display-provenance.json",
        ROOT / "src/openscope_p3_publication/mesoscope_standard_oddball_cohort_figure.py",
        PUBLICATION_DIRECTORY / "provenance.json", PUBLICATION_DIRECTORY / "cohorts.json",
    ]
    provenance = {
        "version": 4, "session_id": payload["session_id"], "footprint_mm": [WIDTH_MM, HEIGHT_MM],
        "example_roi_keys": payload["example_roi_keys"], "variants": summaries,
        "panel_a_dff_peak_threshold": PANEL_A_DFF_PEAK_THRESHOLD,
        "panel_a_responsive_dff_peak": payload["panel_a_responsive_dff_peak"],
        "cohort_analysis": {
            "directory": "../mesoscope-standard-oddball-cohort",
            "provenance_sha256": sha256(cohort_paths[-1]),
        },
        "stimulus_spans": payload["stimulus_spans"],
        "sources": [{"path": str(p.relative_to(ROOT)), "sha256": sha256(p)} for p in sources],
        "outputs": [{"path": p.name, "sha256": sha256(p)} for p in [*paths, table_path]],
    }
    provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    return [*paths, table_path, provenance_path, *cohort_paths]


if __name__ == "__main__":
    for written in build_mesoscope_standard_oddball():
        print(f"Wrote {written}")
