"""Offline cortical example galleries and Q2-nonsignificant cohort definitions."""

from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import MaxNLocator

from .standard_oddball_examples import (
    EXAMPLES_PATH,
    EXAMPLES_PROVENANCE,
    WINDOW,
    _trial_windows,
    load_example_spikes,
)
from .standard_oddball_neuropixels import (
    CONTEXT_COLOR,
    DATA_PATH,
    PROVENANCE_PATH,
    REPO_ROOT,
    Diagnostic,
    _sha256,
    _write_csv,
    load_diagnostic,
    save_diagnostic_svg,
    visual_group,
)
from .standard_oddball_population import (
    BIN_SECONDS,
    EVENT_ID,
    POPULATION_PATH,
    POPULATION_PROVENANCE,
    TAU_SECONDS,
    load_population,
    population_arrays,
)

CONTROL_LINE_COLOR = "#777777"
CONTROL_LINE_ALPHA = 0.5
RESPONSIVE_EXAMPLE_RULE = (
    "visual cortex; finite Q1 and baseline-subtracted Q2 p <0.05 and BOTH signed MI >0.25"
)
COMPARISON_EXAMPLE_RULE = (
    "visual cortex; finite baseline-subtracted Q2 p >=0.05 and abs(MI) <0.25; "
    "finite session firingRateHz >3; no Q1 restriction"
)
NONQ2_CORTEX_RULE = (
    "visual cortex; finite baseline-subtracted Q2 p and MI, p >=0.05; "
    "no example-only MI or firing-rate threshold; inherited QC-passing SUA firingRateHz >1"
)
CANDIDATE_DIR = (
    REPO_ROOT / "images/figures/generated/neuropixels-standard-oddball-90-candidates"
)
CANDIDATE_AUDIT_DIR = (
    REPO_ROOT / "figure_sources/derived/neuropixels-standard-oddball-90-candidates"
)


def nonq2_cortex_mask(data: Diagnostic) -> np.ndarray:
    """Select testable, Q2-nonsignificant cortical units, regardless of Q1."""
    p = data.statistics["q2_delta_p"][1]
    mi = data.statistics["q2_delta_modulation"][1]
    cortex = np.array([visual_group(unit) == 0 for unit in data.units])
    return cortex & np.isfinite(p) & np.isfinite(mi) & (p >= 0.05)


def candidate_masks(data: Diagnostic) -> dict[str, np.ndarray]:
    """Apply the stricter example-only effect-size and firing-rate thresholds."""
    p1, p2, m1, m2 = (
        data.statistics[key][1]
        for key in ("q1_p", "q2_delta_p", "q1_modulation", "q2_delta_modulation")
    )
    cortex = np.array([visual_group(unit) == 0 for unit in data.units])
    fr = np.array([unit["firingRateHz"] for unit in data.units])
    return {
        "responsive": (
            cortex & np.isfinite(p1) & np.isfinite(p2) & np.isfinite(m1) & np.isfinite(m2)
            & (p1 < 0.05) & (p2 < 0.05) & (m1 > 0.25) & (m2 > 0.25)
        ),
        "comparison": (
            nonq2_cortex_mask(data) & (np.abs(m2) < 0.25) & np.isfinite(fr) & (fr > 3)
        ),
    }


def _render_gallery(
    data: Diagnostic, population: dict, kind: str, indices: list[int], output: Path,
) -> None:
    rates, _ = population_arrays(population)
    times = WINDOW[0] + (np.arange(rates.shape[-1]) + 0.5) * BIN_SECONDS
    columns = 4
    rows = math.ceil(len(indices) / columns)
    rc = {
        "font.size": 6, "axes.spines.top": False, "axes.spines.right": False,
        "axes.linewidth": 0.5, "xtick.labelsize": 6, "ytick.labelsize": 6,
        "xtick.major.size": 2, "ytick.major.size": 2,
    }
    with mpl.rc_context(rc):
        fig, axes = plt.subplots(rows, columns, figsize=(170 / 25.4, 220 / 25.4), squeeze=False)
        fig.subplots_adjust(left=0.075, right=0.98, bottom=0.06, top=0.86, wspace=0.55, hspace=1)
        handles = []
        for number, (ax, i) in enumerate(zip(axes.flat, indices, strict=False)):
            unit = data.units[i]
            ax.set_gid(f"candidate-{kind}-{unit['id']}")
            _trial_windows(ax, population["event"]["conditions"]["context"]["trials"], raster=False)
            for c, (label, color, alpha) in enumerate((
                ("Context", CONTEXT_COLOR, 1.0),
                ("Control", CONTROL_LINE_COLOR, CONTROL_LINE_ALPHA),
            )):
                line, = ax.plot(
                    times, rates[c, i], color=color, alpha=alpha, linewidth=0.7,
                    label=label, zorder=4 - c,
                )
                if number == 0:
                    handles.append(line)
            stats = data.statistics
            ax.set_title(
                f"{unit['id']}  {unit['location']}  {unit['firingRateHz']:.2f} Hz\n"
                f"Q1 p={stats['q1_p'][1, i]:.2g}  MI={stats['q1_modulation'][1, i]:+.3f}\n"
                f"Q2 p={stats['q2_delta_p'][1, i]:.2g}  "
                f"MI={stats['q2_delta_modulation'][1, i]:+.3f}",
                fontsize=6, pad=3,
            )
            ax.set_xlim(WINDOW)
            ax.set_ylim(bottom=0)
            ax.set_xticks([-0.5, 0, 0.5])
            ax.yaxis.set_major_locator(MaxNLocator(3, integer=True))
            ax.tick_params(pad=1)
        for ax in list(axes.flat)[len(indices):]:
            ax.set_visible(False)
        responsive = kind == "responsive"
        fig.suptitle(
            f"90-degree oddball: {kind} cortical candidates (n={len(indices)})",
            fontsize=9, y=0.985,
        )
        fig.text(
            0.5, 0.95,
            "Q1 and Q2: p <0.05; both signed MI >0.25" if responsive else
            "Q2: p >=0.05; |MI| <0.25; session FR >3 Hz; no Q1 restriction",
            ha="center", fontsize=6.5,
        )
        fig.legend(handles=handles, loc="center", bbox_to_anchor=(0.5, 0.92),
                   ncol=2, frameon=False, fontsize=6.5)
        fig.supxlabel("Time from deviant (s)", fontsize=7, y=0.012)
        fig.supylabel("Raw firing rate (Hz); independent unit scales", fontsize=7, x=0.008)
        save_diagnostic_svg(
            fig, output, f"90-degree standard oddball: {kind} cortical candidates",
            f"{len(indices)} cortical candidates from mouse 830794. "
            f"{RESPONSIVE_EXAMPLE_RULE if responsive else COMPARISON_EXAMPLE_RULE}. "
            "Exploratory original tests, without BH correction. Native unit IDs and areas "
            "label each plot; Hz beside the ID is session-wide firing rate. "
            "Raw-Hz clean context and matched-control means use 34 and 68 trials, "
            "5 ms bins, causal exponential smoothing tau 25 ms and 250 ms support. "
            "Control is grey at 50 percent opacity; unit y scales are independent. "
            "Tan/grey mark preceding presentation/deviant windows. No uncertainty bands: "
            "the committed intermediate contains trial means, not trial variability. "
            "Q2 nonsignificance does not establish equivalence or absent visual responses.",
            {
                "data-candidate-kind": kind,
                "data-unit-ids": ",".join(str(data.units[i]["id"]) for i in indices),
                "data-candidate-count": str(len(indices)), "data-event-id": EVENT_ID,
                "data-sdf-bin-seconds": str(BIN_SECONDS),
                "data-sdf-tau-seconds": str(TAU_SECONDS),
            },
            target_width_mm=170, target_height_mm=220,
        )


def build_candidate_galleries(
    output_dir: Path = CANDIDATE_DIR, audit_dir: Path = CANDIDATE_AUDIT_DIR,
) -> list[Path]:
    """Render every eligible cortical example's paired means entirely offline."""
    data = load_diagnostic()
    examples = load_example_spikes(data)
    population = load_population(data, examples["events"][1])
    masks = candidate_masks(data)
    paths, selection = [], {}
    for kind, mask in masks.items():
        indices = sorted(np.flatnonzero(mask).tolist(), key=lambda i: (
            data.units[i]["parentArea"], data.units[i]["location"], data.units[i]["id"],
        ))
        if not indices:
            raise ValueError(f"No cortical {kind} candidates meet the example criteria.")
        selection[kind] = [data.units[i]["id"] for i in indices]
        path = output_dir / f"{kind}.svg"
        _render_gallery(data, population, kind, indices, path)
        paths.append(path)
    audit_dir.mkdir(parents=True, exist_ok=True)
    nonq2 = nonq2_cortex_mask(data)
    audit = audit_dir / "unit-statistics.csv"
    _write_csv(audit, [{
        "unit_id": unit["id"], "recorded_area": unit["location"],
        "parent_area": unit["parentArea"], "session_firing_rate_hz": unit["firingRateHz"],
        "responsive_candidate": bool(masks["responsive"][i]),
        "comparison_candidate": bool(masks["comparison"][i]),
        "cortical_q2_nonsignificant": bool(nonq2[i]),
        **{
            key: float(values[1, i]) if math.isfinite(values[1, i]) else None
            for key, values in data.statistics.items()
        },
    } for i, unit in enumerate(data.units)])
    sources = [
        Path(__file__), Path(__file__).with_name("standard_oddball_neuropixels.py"),
        Path(__file__).with_name("standard_oddball_examples.py"),
        Path(__file__).with_name("standard_oddball_population.py"),
        Path(__file__).with_name("figure_typography.py"),
        Path(__file__).with_name("image_encoding.py"),
        DATA_PATH, PROVENANCE_PATH, POPULATION_PATH, POPULATION_PROVENANCE,
        EXAMPLES_PATH, EXAMPLES_PROVENANCE,
    ]
    provenance = {
        "version": 1, "session_id": data.session["sessionId"], "asset": data.session["asset"],
        "rules": {"responsive": RESPONSIVE_EXAMPLE_RULE, "comparison": COMPARISON_EXAMPLE_RULE},
        "selection": selection, "order": "parent area, recorded area, unit ID",
        "counts": {kind: int(mask.sum()) for kind, mask in masks.items()},
        "population_nonq2": {"rule": NONQ2_CORTEX_RULE, "count": int(nonq2.sum())},
        "parameters": population["parameters"],
        "trial_counts": {
            condition: len(record["trials"])
            for condition, record in population["event"]["conditions"].items()
        },
        "sources": [
            {"path": str(path.relative_to(REPO_ROOT)), "sha256": _sha256(path)}
            for path in sources
        ],
        "outputs": [
            {"name": path.name, "sha256": _sha256(path)} for path in [*paths, audit]
        ],
    }
    provenance_path = audit_dir / "provenance.json"
    provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    return [*paths, audit, provenance_path]


if __name__ == "__main__":
    for path in build_candidate_galleries():
        print(f"Wrote {path}")
