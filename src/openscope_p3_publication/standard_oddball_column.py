"""Final-width Neuropixels column for a three-modality standard-oddball figure."""

from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import MaxNLocator

from .figures import PLATFORM_LOGO_PROVENANCE_PATH, load_platform_logos
from .standard_oddball_baselines import (
    BASELINES_PATH,
    BASELINES_PROVENANCE,
    load_baselines,
)
from .standard_oddball_candidates import (
    CONTROL_LINE_ALPHA,
    CONTROL_LINE_COLOR,
    NONQ2_CORTEX_RULE,
    candidate_masks,
    nonq2_cortex_mask,
)
from .standard_oddball_cohort_figure import (
    BOOTSTRAP_REPLICATES,
    BOOTSTRAP_RULE,
    BOOTSTRAP_SEED,
    FRONTAL_PREFIXES,
    MINIMUM_QC_SUA,
    REGION_LABELS,
    REGION_ORDER,
    RESPONSE_RULE,
    SCREENS,
    STR_AREAS,
    cohort_plot_data,
    draw_cohort_panel,
)
from .standard_oddball_comparison import (
    COMPARISON_PATH,
    COMPARISON_PROVENANCE,
    COMPARISON_RULE,
    COMPARISON_UNIT_ID,
    load_comparison_spikes,
)
from .standard_oddball_examples import (
    EXAMPLES_PATH,
    EXAMPLES_PROVENANCE,
    WINDOW,
    _trial_windows,
    load_example_spikes,
    trial_mean_sdf,
)
from .standard_oddball_neuropixels import (
    CONTEXT_COLOR,
    REPO_ROOT,
    Diagnostic,
    _heatmap_display,
    _sha256,
    _write_csv,
    joint_example_mask,
    load_diagnostic,
    save_diagnostic_svg,
    visual_group,
)
from .standard_oddball_ordering import ORDER_PATH, load_context_order
from .standard_oddball_population import (
    BIN_SECONDS,
    POPULATION_PATH,
    POPULATION_PROVENANCE,
    TAU_SECONDS,
    load_population,
    population_arrays,
)
from .standard_oddball_publication_data import DIRECTORY as PUBLICATION_DIRECTORY

COLUMN_WIDTH_MM = 54.0
LAYOUT_HEIGHT_MM = 180.0
COLUMN_HEIGHT_MM = 165.0
EXAMPLE_UNIT_IDS = (964, COMPARISON_UNIT_ID)
POSITIVE_RESPONSE_RULE = "90-degree Q1 AND baseline-subtracted Q2: each p <0.05 and MI >0.1"
HEATMAP_RULE = "context SDF minus unit's own clean-context baseline mean (Hz); no SD normalization"
COLUMN_PATH = REPO_ROOT / "images/figures/generated/neuropixels-standard-oddball-90-column.svg"
COLUMN_AUDIT_DIR = REPO_ROOT / "figure_sources/derived/neuropixels-standard-oddball-90-column"


def column_data(data: Diagnostic, population: dict, examples: dict) -> dict:
    """Prepare positive-responder means and verify example/population trial agreement."""
    rates, baselines = population_arrays(population)
    baseline_record = load_baselines(population)
    baseline_sd = np.asarray([
        [unit["conditions"][condition]["sd_hz"] for unit in baseline_record["units"]]
        for condition in ("context", "control")
    ])
    delta = rates - baselines[..., None]
    groups = np.array([visual_group(unit) for unit in data.units])
    positive = (
        joint_example_mask(data)[1]
        & (data.statistics["q1_modulation"][1] > 0.1)
        & (data.statistics["q2_delta_modulation"][1] > 0.1)
    )
    if not np.any(positive):
        raise ValueError("No visual units pass the positive 90-degree Q1 AND Q2 screens.")
    if positive.sum() < 2:
        raise ValueError("At least two positive responders are required for across-neuron SEM.")
    nonq2 = nonq2_cortex_mask(data)
    if nonq2.sum() < 2:
        raise ValueError("At least two cortical Q2-nonsignificant units are required for SEM.")
    comparison = candidate_masks(data)["comparison"]
    raw_units = [*examples["units"], *load_comparison_spikes(data, population)["units"]]
    example_indices, example_spikes = [], []
    for unit_id in EXAMPLE_UNIT_IDS:
        matching = [i for i, unit in enumerate(data.units) if unit["id"] == unit_id]
        spikes = [unit for unit in raw_units if unit["id"] == unit_id]
        if len(matching) != 1 or len(spikes) != 1:
            raise ValueError(f"The fixed 90-degree example {unit_id} is missing or ambiguous.")
        i = matching[0]
        expected = positive if unit_id == EXAMPLE_UNIT_IDS[0] else comparison
        if not expected[i]:
            raise ValueError(
                f"Example {unit_id} no longer satisfies its 90-degree comparison role."
            )
        for c, condition in enumerate(("context", "control")):
            mean = trial_mean_sdf(
                spikes[0]["spikes"]["orientation_90"][condition],
                bin_seconds=BIN_SECONDS, tau_seconds=TAU_SECONDS,
            )
            if not np.array_equal(mean, rates[c, i]):
                raise ValueError("Example/population SDFs do not use identical trial spikes.")
        example_indices.append(i)
        example_spikes.append(spikes[0])
    order = load_context_order(population)
    heatmaps = delta[:1, order]
    selected = delta[:, positive]
    nonq2_selected = delta[:, nonq2]
    return {
        "time": WINDOW[0] + (np.arange(rates.shape[-1]) + 0.5) * BIN_SECONDS,
        "rates": rates, "baselines": baselines, "delta": delta, "groups": groups,
        "baseline_sd": baseline_sd,
        "positive_mask": positive, "positive_mean": selected.mean(axis=1),
        "positive_sem": selected.std(axis=1, ddof=1) / math.sqrt(selected.shape[1]),
        "nonq2_mask": nonq2, "nonq2_mean": nonq2_selected.mean(axis=1),
        "nonq2_sem": nonq2_selected.std(axis=1, ddof=1) / math.sqrt(nonq2_selected.shape[1]),
        "comparison_mask": comparison,
        "example_indices": example_indices, "example_spikes": example_spikes,
        "order": order, "ordered_heatmaps": heatmaps,
        "heatmap": _heatmap_display(heatmaps[None], "hz"),
    }


def _render_column(
    data: Diagnostic, population: dict, prepared: dict, output: Path, logo_path: Path,
) -> None:
    event = population["event"]
    trials = event["conditions"]["context"]["trials"]
    times = prepared["time"]
    rc = {
        "font.family": "DejaVu Sans", "font.size": 6.5, "svg.fonttype": "none",
        "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": 0.45,
        "axes.labelpad": 2, "xtick.labelsize": 6, "ytick.labelsize": 6,
        "xtick.major.size": 2, "ytick.major.size": 2,
        "xtick.major.pad": 1.5, "ytick.major.pad": 1.5,
    }
    with mpl.rc_context(rc):
        fig = plt.figure(figsize=(COLUMN_WIDTH_MM / 25.4, LAYOUT_HEIGHT_MM / 25.4))
        rate_limit = math.ceil(
            float(prepared["rates"][:, prepared["example_indices"]].max()) / 10
        ) * 10
        for col, left in enumerate((0.20, 0.60)):
            i = prepared["example_indices"][col]
            unit_spikes = prepared["example_spikes"][col]
            raster = fig.add_axes([left, 0.84, 0.29, 0.10])
            raster.set_gid(f"example-context-raster-{data.units[i]['id']}")
            raster.set_title("Responsive" if col == 0 else "Unresponsive", fontsize=6.5, pad=2)
            _trial_windows(raster, trials, raster=True)
            for row, spikes in enumerate(unit_spikes["spikes"]["orientation_90"]["context"]):
                visible = [s for s in spikes if WINDOW[0] <= s < WINDOW[1]]
                raster.vlines(visible, row + 0.65, row + 1.35, color="black", linewidth=0.3)
            raster.set_ylim(len(trials) + 0.5, 0.5)
            raster.set_yticks([1, len(trials)])
            if col == 0:
                raster.set_ylabel("Trial", fontsize=6)
            raster.set_xlim(WINDOW)
            raster.set_xticks([])
            raster.tick_params(labelsize=5.5, pad=0.5, length=1)
            mean = fig.add_axes([left, 0.728, 0.29, 0.10])
            mean.set_gid(f"example-trial-mean-{data.units[i]['id']}")
            _trial_windows(mean, trials, raster=False)
            for c, (condition, color, alpha) in enumerate((
                ("Context", CONTEXT_COLOR, 1.0),
                ("Control", CONTROL_LINE_COLOR, CONTROL_LINE_ALPHA),
            )):
                mean.plot(
                    times, prepared["rates"][c, i], color=color, alpha=alpha,
                    linewidth=0.75, label=condition, zorder=4 - c,
                )
            mean.set_ylim(0, rate_limit)
            mean.set_yticks([0, rate_limit])
            mean.set_xlim(WINDOW)
            mean.set_xticks([-0.5, 0, 0.5], ["-0.5", "0", "0.5"])
            mean.tick_params(labelsize=5.5, length=1, pad=0.5)
            if col == 0:
                mean.set_ylabel("Hz", fontsize=6)
        logo_size_mm = 5.0
        logo_ax = fig.add_axes([
            0.32, 0.975 - logo_size_mm / LAYOUT_HEIGHT_MM / 2,
            logo_size_mm / COLUMN_WIDTH_MM, logo_size_mm / LAYOUT_HEIGHT_MM,
        ])
        logo_ax.set_gid("platform-logo-neuropixels")
        logo_ax.imshow(plt.imread(logo_path), interpolation="none")
        logo_ax.set_xticks([])
        logo_ax.set_yticks([])
        logo_ax.set_axis_off()
        fig.text(
            0.435, 0.975, "Neuropixels", fontsize=7.5, fontweight="bold",
            va="center", gid="platform-label-neuropixels",
        )
        fig.text(0.545, 0.697, "Time from deviant (s)", fontsize=6, ha="center")

        limit = prepared["heatmap"]["limit"]
        ax = fig.add_axes([0.20, 0.46, 0.65, 0.215])
        ax.set_gid("population-heatmap-context")
        ax.imshow(
            prepared["ordered_heatmaps"][0],
            cmap=mpl.colormaps["RdBu_r"].with_extremes(bad="#bdbdbd"),
            vmin=-limit, vmax=limit,
            aspect="auto", interpolation="none", origin="upper",
            extent=[*WINDOW, len(data.units) - 0.5, -0.5],
        )
        ax.axvline(0, color="black", linewidth=0.35, linestyle="--")
        ax.set_xticks([])
        ax.set_yticks([0, len(data.units) - 1], ["1", str(len(data.units))])
        ax.set_ylabel("Rastermap rank", fontsize=6)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax = fig.add_axes([0.20, 0.308, 0.65, 0.14])
        ax.set_gid("population-mean-overlay")
        _trial_windows(ax, trials, raster=False)
        for cohort, linestyle in (("positive", "-"), ("nonq2", ":")):
            for c, (condition, color, alpha, band_alpha) in enumerate((
                ("context", CONTEXT_COLOR, 1.0, 0.18),
                ("control", CONTROL_LINE_COLOR, CONTROL_LINE_ALPHA, 0.12),
            )):
                center, sem = prepared[f"{cohort}_mean"][c], prepared[f"{cohort}_sem"][c]
                band = ax.fill_between(
                    times, center - sem, center + sem,
                    color=color, alpha=band_alpha, linewidth=0,
                )
                band.set_gid(
                    f"population-sem-{condition}" if cohort == "positive" else
                    f"population-nonq2-sem-{condition}"
                )
                line, = ax.plot(
                    times, center, color=color, alpha=alpha,
                    linestyle=linestyle, linewidth=0.85, zorder=4 - c,
                )
                line.set_gid(f"population-{cohort}-{condition}")
        ax.axhline(0, color="#777777", linewidth=0.35)
        ax.set_xlim(WINDOW)
        ax.set_xticks([-0.5, 0, 0.5], ["-0.5", "0", "0.5"])
        ax.yaxis.set_major_locator(MaxNLocator(3, prune="both"))
        ax.tick_params(labelsize=5.5, length=1.5, pad=0.5)
        ax.set_ylabel("Δ Firing Rate (spikes/s)", fontsize=6)
        ax.set_xlabel("Time from deviant (s)", fontsize=6)
        cohort = prepared["cohort"]
        draw_cohort_panel(
            fig.add_axes([0.20, 0.125, 0.65, 0.12]), cohort, CONTEXT_COLOR,
        )
        for letter, y in (("A", 0.94), ("B", 0.675), ("C", 0.27)):
            fig.text(
                0.015, y, letter, fontweight="bold", fontsize=9, gid=f"panel-label-{letter}",
            )
        save_diagnostic_svg(
            fig, output, "Neuropixels: 90-degree standard oddball responses",
            "One 54 mm-wide modality column, headed by the Neuropixels icon reused "
            "from Figure 3 and its modality label, replacing the condition legend. "
            "A: responsive VISp5 unit 964 and "
            "Q2-nonsignificant VISp4 unit 993; context "
            "trial rasters with matching raw context/control mean-rate traces directly "
            "below on identical raw-Hz y-limits. Titles are Responsive and Unresponsive; "
            "the latter means Q2-nonsignificant, not visually inactive. "
            "There are 34 clean context and 68 control trials. Context is green; control is "
            "a grey line at 50 percent opacity. "
            "B: context baseline-subtracted Hz heatmap for all 203 eligible visual SUA, "
            "retaining the frozen context-only Rastermap row order. Below, context/control "
            "mean traces share one baseline-subtracted Hz axis with plus/minus across-neuron SEM. "
            "Solid curves equally weight "
            f"{int(prepared['positive_mask'].sum())} pooled visual units, selected by "
            f"{POSITIVE_RESPONSE_RULE}. Heatmap rows have no responsiveness filter. "
            f"Dotted curves equally weight {int(prepared['nonq2_mask'].sum())} "
            f"cortical Q2-nonsignificant units: {NONQ2_CORTEX_RULE}. "
            "The two populations differ in anatomical scope but share the same Hz scale. "
            "SEM is sample SD (ddof=1) of per-unit SDFs divided by sqrt(neuron count), "
            "not trial or across-mouse uncertainty; response-selected descriptive curves. "
            "All SDFs use 5 ms bins, a "
            "normalized causal 25 ms exponential kernel with 250 ms support, and hidden "
            "pre-event padding. Tan/grey indicate preceding presentation/deviant windows. "
            "Each condition's baseline mean pools full 20 ms bins from its clean trials' "
            "preceding grey intervals. No baseline-SD division or zero-SD masking is used. "
            "The heatmap, population means and SEM use baseline-subtracted Hz. "
            f"No colorbar is shown; heatmap colors span {-limit:g} to {limit:g} spikes/s, "
            "with blue negative and red positive. "
            f"A/B: one session, {data.session['sessionId']}, from mouse 830794; "
            "their means do not pool across sessions. "
            "C: 90-degree either-sign responsiveness in LGd, VISp, VISl, VISa, "
            "pooled frontal, pooled hippocampal (HIP), SSp and pooled STR areas, "
            "in that order, across "
            f"{cohort['provenance']['session_count']} QC-pass standard sessions from "
            f"{cohort['provenance']['mouse_count']} mice. Each region has Q1, Q2 and Both "
            "bars, with blue, orange and green encoding respectively. Passing means "
            "p <0.05 and absolute MI >0.1, including suppression. Both is the intersection, "
            "including opposite-sign responses. All three bars use the same joint-testable "
            "eligible neuron denominator; numerators are restricted to that shared set. "
            "Bars pool neuron counts; error bars show 95% percentile mouse-cluster "
            f"bootstrap intervals ({BOOTSTRAP_REPLICATES} resamples) on all three bars, "
            "on a 0-100 percent axis. Each resample draws contributing mice with replacement "
            "within the region and recomputes summed responsive / summed testable counts, "
            "rather than averaging mouse percentages or resampling individual neurons. "
            "The same mouse draws are used for all three screens. "
            "Each session/group must have at least "
            f"{MINIMUM_QC_SUA} QC-passing SUA, counted before firing-rate or response-test "
            "filtering and excluding curated probes. STR pools LSr, LSc, STR, CP and SH. "
            "Frontal, hippocampal and striatal constituent "
            "areas are pooled before this cutoff; excluded sessions contribute to neither "
            "bars nor bootstrap intervals. The existing >1 Hz and finite-test response denominator "
            "is unchanged. This either-sign cohort differs from B's positive-only solid "
            "curves. Undefined tests are not unresponsive. "
            "ProbeC is excluded for saturation in mouse 820454. Sample sizes and coverage "
            "are published in the linked cohort tables. Intervals are pointwise, "
            "conditional on the fixed inclusion rules, and exploratory with 5-13 mice "
            "per group; they are not simultaneous intervals or tests between bars. "
            "The first example passes positive Q1 AND Q2; "
            "the comparison has Q2 p >=0.05, abs(Q2 MI) <0.25 and session FR >3 Hz, "
            "with no Q1 restriction; this unit has significant negative Q1 modulation. "
            "Nonsignificance is not proof of no effect or absent visual responsiveness.",
            {
                "data-intended-width-mm": str(COLUMN_WIDTH_MM),
                "data-intended-height-mm": str(COLUMN_HEIGHT_MM),
                "data-platform-logo": str(logo_path.relative_to(REPO_ROOT)),
                "data-condition-legend": "none",
                "data-event-id": "orientation_90",
                "data-session-id": data.session["sessionId"],
                "data-session-count": "1",
                "data-cohort-session-count": str(cohort["provenance"]["session_count"]),
                "data-cohort-mouse-count": str(cohort["provenance"]["mouse_count"]),
                "data-cohort-event": "orientation_90",
                "data-cohort-selection": RESPONSE_RULE,
                "data-cohort-screens": ",".join(screen for screen, _ in SCREENS),
                "data-cohort-mouse-points": "none",
                "data-cohort-uncertainty": BOOTSTRAP_RULE,
                "data-cohort-bootstrap-replicates": str(BOOTSTRAP_REPLICATES),
                "data-cohort-bootstrap-seed": str(BOOTSTRAP_SEED),
                "data-cohort-y-limit-percent": "0,100",
                "data-cohort-denominator": "eligible-joint-testable-neurons",
                "data-cohort-aggregation": "pooled-neuron-proportion-with-mouse-bootstrap-ci95",
                "data-cohort-areas": ",".join(cohort["areas"].brain_area),
                "data-cohort-minimum-qc-sua": str(MINIMUM_QC_SUA),
                "data-cohort-minimum-scope": "session-within-plotted-group",
                "data-cohort-minimum-before": "firing-rate-and-response-tests",
                "data-example-unit-ids": ",".join(str(i) for i in EXAMPLE_UNIT_IDS),
                "data-example-roles": "positive-responder,q2-nonsignificant-comparison",
                "data-example-shared-y-limit-hz": str(rate_limit),
                "data-sdf-bin-seconds": str(BIN_SECONDS),
                "data-sdf-tau-seconds": str(TAU_SECONDS),
                "data-context-trial-count": str(len(trials)),
                "data-control-trial-count": str(len(event["conditions"]["control"]["trials"])),
                "data-population-filter": "all-eligible-visual-sua-not-response-filtered",
                "data-population-mean-filter": POSITIVE_RESPONSE_RULE,
                "data-population-mean-count": str(int(prepared["positive_mask"].sum())),
                "data-nonq2-mean-filter": NONQ2_CORTEX_RULE,
                "data-nonq2-mean-count": str(int(prepared["nonq2_mask"].sum())),
                "data-population-mean-layout": "shared-axis-overlay",
                "data-responsive-linestyle": "solid",
                "data-nonq2-linestyle": "dotted",
                "data-unit-order": ",".join(str(data.units[i]["id"]) for i in prepared["order"]),
                "data-rastermap-fit-condition": "context",
                "data-population-sem": "sample-neuron-SD-ddof1-divided-by-sqrt-neuron-count",
                "data-heatmap-conditions": "context",
                "data-control-line-color": CONTROL_LINE_COLOR,
                "data-control-line-alpha": str(CONTROL_LINE_ALPHA),
                "data-heatmap-normalization": HEATMAP_RULE,
                "data-heatmap-limit-hz": str(limit),
                "data-heatmap-colorbar": "none",
                "data-minimum-text-points": "5.5",
            },
            target_width_mm=COLUMN_WIDTH_MM, target_height_mm=LAYOUT_HEIGHT_MM,
        )
        # Crop only the lower viewport; preserve all artwork coordinates and physical sizes.
        root = ET.fromstring(output.read_text(encoding="utf-8"))
        viewport = root.attrib["viewBox"].split()
        viewport[3] = str(float(viewport[3]) * COLUMN_HEIGHT_MM / LAYOUT_HEIGHT_MM)
        root.set("viewBox", " ".join(viewport))
        root.set("height", f"{COLUMN_HEIGHT_MM * 72 / 25.4}pt")
        root.set("overflow", "hidden")
        output.write_text(ET.tostring(root, encoding="unicode") + "\n", encoding="utf-8")


def build_standard_oddball_column(
    output: Path = COLUMN_PATH, audit_dir: Path = COLUMN_AUDIT_DIR,
) -> list[Path]:
    """Render the narrow main-figure column and matching audits entirely offline."""
    data = load_diagnostic()
    examples = load_example_spikes(data)
    population = load_population(data, examples["events"][1])
    prepared = column_data(data, population, examples)
    prepared["cohort"] = cohort_plot_data()
    logo_path = load_platform_logos()["neuropixels"]
    _render_column(data, population, prepared, output, logo_path)
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_path = audit_dir / "unit-statistics.csv"
    rows = []
    ranks = np.argsort(prepared["order"])
    for i, unit in enumerate(data.units):
        rows.append({
            "unit_id": unit["id"], "parent_area": unit["parentArea"],
            "recorded_area": unit["location"], "example": unit["id"] in EXAMPLE_UNIT_IDS,
            "positive_q1_q2": bool(prepared["positive_mask"][i]),
            "cortical_q2_nonsignificant": bool(prepared["nonq2_mask"][i]),
            "comparison_candidate": bool(prepared["comparison_mask"][i]),
            "example_role": (
                "positive-responder" if unit["id"] == EXAMPLE_UNIT_IDS[0] else
                "q2-nonsignificant-comparison" if unit["id"] == COMPARISON_UNIT_ID else ""
            ),
            "context_rastermap_rank": int(ranks[i]) + 1,
            "context_baseline_hz": float(prepared["baselines"][0, i]),
            "control_baseline_hz": float(prepared["baselines"][1, i]),
            "context_baseline_sd_hz": float(prepared["baseline_sd"][0, i]),
            "control_baseline_sd_hz": float(prepared["baseline_sd"][1, i]),
            **{
                key: float(values[1, i]) if math.isfinite(values[1, i]) else None
                for key, values in data.statistics.items()
            },
        })
    _write_csv(audit_path, rows)
    cohort_path = audit_dir / "cohort-sessions.csv"
    prepared["cohort"]["sessions"].to_csv(
        cohort_path, index=False, float_format="%.17g", lineterminator="\n",
    )
    sources = [
        Path(__file__), Path(__file__).with_name("figure_typography.py"),
        Path(__file__).with_name("figures.py"), PLATFORM_LOGO_PROVENANCE_PATH, logo_path,
        Path(__file__).with_name("standard_oddball_cohort.py"),
        Path(__file__).with_name("standard_oddball_cohort_figure.py"),
        PUBLICATION_DIRECTORY / "provenance.json", PUBLICATION_DIRECTORY / "cohorts.json",
        Path(__file__).with_name("image_encoding.py"),
        Path(__file__).with_name("standard_oddball_population.py"),
        Path(__file__).with_name("standard_oddball_neuropixels.py"),
        Path(__file__).with_name("standard_oddball_examples.py"),
        Path(__file__).with_name("standard_oddball_ordering.py"), ORDER_PATH,
        Path(__file__).with_name("standard_oddball_baselines.py"),
        BASELINES_PATH, BASELINES_PROVENANCE,
        Path(__file__).with_name("standard_oddball_comparison.py"),
        Path(__file__).with_name("standard_oddball_candidates.py"),
        COMPARISON_PATH, COMPARISON_PROVENANCE,
        POPULATION_PATH, POPULATION_PROVENANCE, EXAMPLES_PATH, EXAMPLES_PROVENANCE,
    ]
    provenance = {
        "version": 1, "session_id": data.session["sessionId"], "asset": data.session["asset"],
        "session_count": 1,
        "cohort": {
            "session_count": prepared["cohort"]["provenance"]["session_count"],
            "mouse_count": prepared["cohort"]["provenance"]["mouse_count"],
            "event": "orientation_90", "selection": RESPONSE_RULE,
            "denominator": "eligible joint-testable neurons",
            "aggregation": "pooled neuron counts; 95% mouse-cluster bootstrap intervals",
            "screens": [label for _, label in SCREENS],
            "signs": "either; Both includes opposite-sign responses",
            "y_limit_percent": [0, 100],
            "uncertainty": {
                "rule": BOOTSTRAP_RULE, "confidence_level": 0.95,
                "replicates": BOOTSTRAP_REPLICATES, "seed": BOOTSTRAP_SEED,
                "region_seed": "first 8 SHA256 bytes of 'seed:region', big-endian",
                "rng": "numpy default_rng", "mouse_order": "subject_id",
                "quantile_method": "linear", "minimum_mice": 2,
                "insufficient_mice": "undefined interval; plotting raises ValueError",
            },
            "region_order": list(REGION_ORDER),
            "region_display_labels": REGION_LABELS,
            "groups": {
                "Frontal": {"division": "Isocortex", "prefixes": list(FRONTAL_PREFIXES)},
                "Hippocampus": {"division": "HPF"},
                "SSp": {"division": "Isocortex", "area": "SSp"},
                "STR": {"division": "STR", "areas": list(STR_AREAS)},
            },
            "minimum_session_group_qc_sua": MINIMUM_QC_SUA,
            "minimum_count_rule": (
                "qc_pass and decoder_label=sua and not probe_excluded; "
                "no firing-rate or response-test requirement for counting toward minimum"
            ),
            "session_filter_audit": cohort_path.name,
            "areas": prepared["cohort"]["areas"].drop(columns="division_order").to_dict("records"),
            "mouse_counts": prepared["cohort"]["mice"].to_dict("records"),
        },
        "footprint_mm": [COLUMN_WIDTH_MM, COLUMN_HEIGHT_MM],
        "header": {
            "label": "Neuropixels", "logo": str(logo_path.relative_to(REPO_ROOT)),
            "logo_provenance": str(PLATFORM_LOGO_PROVENANCE_PATH.relative_to(REPO_ROOT)),
            "logo_reference": "Figure 3", "condition_legend": "removed",
        },
        "bottom_crop_mm": LAYOUT_HEIGHT_MM - COLUMN_HEIGHT_MM,
        "example_unit_ids": list(EXAMPLE_UNIT_IDS),
        "example_rule": {
            "responsive": POSITIVE_RESPONSE_RULE,
            "comparison": COMPARISON_RULE,
        },
        "example_layout": "two context rasters; paired raw context/control mean traces below",
        "example_titles": ["Responsive", "Unresponsive"],
        "example_y_scale": "shared raw-Hz limits across both units and both conditions",
        "population_mean_layout": {
            "axes": "shared baseline-subtracted Hz",
            "responsive": "solid", "cortical_q2_nonsignificant": "dotted",
        },
        "control_line": {"color": CONTROL_LINE_COLOR, "alpha": CONTROL_LINE_ALPHA},
        "rastermap": {
            "fit_condition": "context", "ordered_unit_ids": [
                data.units[i]["id"] for i in prepared["order"]
            ],
        },
        "normalization": {
            "rule": HEATMAP_RULE, "units": "baseline-subtracted Hz",
            "conditions_shown": ["context"],
            "undefined_context_rows": (
                prepared["heatmap"]["unavailable_rows_by_event_condition"][0][0]
            ),
            "zero_sd_rows": "retained with valid baseline-subtracted values; no SD division",
        },
        "population_units": len(data.units), "group_counts": [145, 58],
        "population_mean": {
            "selection": POSITIVE_RESPONSE_RULE,
            "unit_ids": [
                unit["id"] for i, unit in enumerate(data.units) if prepared["positive_mask"][i]
            ],
            "count": int(prepared["positive_mask"].sum()),
            "group_counts": [
                int(np.sum(prepared["positive_mask"] & (prepared["groups"] == group)))
                for group in (0, 1)
            ],
            "values": "equally weighted condition-baseline-subtracted unit SDFs in Hz",
            "uncertainty": {
                "quantity": "pointwise plus/minus SEM across selected neurons, in Hz",
                "formula": "sample SD (ddof=1) / sqrt(neuron count)",
                "sample_size": int(prepared["positive_mask"].sum()),
                "interpretation": (
                    "response-selected, single-session descriptive variability; "
                    "not trial SEM or uncertainty across independent mice"
                ),
            },
        },
        "trial_counts": {
            condition: len(record["trials"])
            for condition, record in population["event"]["conditions"].items()
        },
        "heatmap": prepared["heatmap"], "parameters": population["parameters"],
        "sources": [
            {"path": str(path.relative_to(REPO_ROOT)), "sha256": _sha256(path)}
            for path in sources
        ],
        "outputs": [
            {"name": path.name, "sha256": _sha256(path)}
            for path in (output, audit_path, cohort_path)
        ],
    }
    count = int(prepared["nonq2_mask"].sum())
    provenance["nonq2_population_mean"] = {
        **provenance["population_mean"],
        "selection": NONQ2_CORTEX_RULE,
        "unit_ids": [
            unit["id"] for i, unit in enumerate(data.units) if prepared["nonq2_mask"][i]
        ],
        "count": count, "group_counts": [count, 0],
        "uncertainty": {
            **provenance["population_mean"]["uncertainty"], "sample_size": count,
            "interpretation": (
                "Q2-selected, single-session descriptive variability; "
                "not evidence of equivalence, trial SEM or uncertainty across independent mice"
            ),
        },
    }
    provenance_path = audit_dir / "provenance.json"
    provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    return [output, audit_path, cohort_path, provenance_path]


if __name__ == "__main__":
    for path in build_standard_oddball_column():
        print(f"Wrote {path}")
