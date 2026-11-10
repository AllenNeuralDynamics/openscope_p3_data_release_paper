"""Static 90-degree comparison of pooled, pre-context and post-context C1 controls."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .mesoscope_standard_oddball import ROOT, sha256
from .mesoscope_standard_oddball_cohort import COHORT_DIR as MESOSCOPE_DIR
from .mesoscope_standard_oddball_cohort import load_cohort as load_meso
from .mesoscope_standard_oddball_cohort_figure import prepare_cohort_panel as prepare_meso
from .slap2_standard_oddball_cohort import DATA as SLAP2_DIR
from .slap2_standard_oddball_cohort import load_cohort as load_slap2
from .slap2_standard_oddball_cohort import summaries as summarize_slap2
from .standard_oddball_cohort import COHORT_DIR as NEUROPIXELS_DIR
from .standard_oddball_cohort import load_cohort as load_np
from .standard_oddball_cohort_figure import prepare_cohort_panel as prepare_np

OUTPUT = ROOT / "images/figures/generated/standard-oddball-c1-repeat-sensitivity.svg"
PROVENANCE = (
    ROOT / "figure_sources/derived/standard-oddball-c1-repeat-sensitivity/provenance.json"
)
EVENT = "orientation_90"
REPEATS = ("pooled", "pre", "post")
COLORS = {"pooled": "#555555", "pre": "#56B4E9", "post": "#E69F00"}
REPEAT_LABELS = {"pooled": "Pooled C1", "pre": "Pre-context C1", "post": "Post-context C1"}


def _record(
    group: str, values: dict[str, dict], *, modality: str, signal: str = "",
) -> dict:
    return {"group": group, "modality": modality, "signal": signal, "values": values}


def sensitivity_rows() -> list[dict]:
    """Return exact 90-degree Q2 counts and intervals from checked cohort snapshots."""
    load_np()
    np_units = pd.read_csv(
        NEUROPIXELS_DIR / "units.csv.gz", float_precision="round_trip",
        dtype={"subject_id": str},
    )
    np_areas = prepare_np(np_units, event=EVENT)["areas"]
    rows = []
    for row in np_areas.to_dict("records"):
        values = {}
        for repeat in REPEATS:
            suffix = "" if repeat == "pooled" else f"_{repeat}"
            values[repeat] = {
                "count": int(row[f"n_q2_responsive{suffix}"]),
                "denominator": int(row[f"n_joint{suffix}_testable"]),
                "interval": [
                    float(row[f"fraction_q2_responsive{suffix}_ci95_{bound}"])
                    for bound in ("low", "high")
                ] if row.get(f"bootstrap_status{suffix}") == "estimated" else None,
            }
        rows.append(_record(row["brain_area"], values, modality="Neuropixels"))

    meso_units, _, _ = load_meso()
    meso_areas = prepare_meso(meso_units)["areas"]
    for row in meso_areas.loc[meso_areas.event_id.eq(EVENT)].to_dict("records"):
        values = {}
        for repeat in REPEATS:
            suffix = "" if repeat == "pooled" else f"_{repeat}"
            values[repeat] = {
                "count": int(row[f"n_q2_responsive{suffix}"]),
                "denominator": int(row[f"n_joint{suffix}_testable"]),
                "interval": [
                    float(row[f"fraction_q2_responsive{suffix}_ci95_{bound}"])
                    for bound in ("low", "high")
                ] if row.get(f"bootstrap_status{suffix}") == "estimated" else None,
            }
        rows.append(_record(
            f'{row["brain_area"]} {row["signal"]}', values, modality="Mesoscope",
            signal=row["signal"],
        ))

    _, slap_units, _ = load_slap2()
    _, slap_pooled = summarize_slap2(slap_units)
    for row in slap_pooled.loc[
        slap_pooled.event_id.eq(EVENT) & slap_pooled.group.ne("Pooled")
    ].to_dict("records"):
        values = {}
        for repeat in REPEATS:
            suffix = "" if repeat == "pooled" else f"_{repeat}"
            values[repeat] = {
                "count": int(row[f"n_q2_responsive{suffix}"]),
                "denominator": int(row[f"n_joint{suffix}_testable"]),
                "interval": None,
            }
        rows.append(_record(row["group"], values, modality="SLAP2"))
    return rows


def build_c1_sensitivity_figure(
    output: Path = OUTPUT, provenance_path: Path = PROVENANCE,
) -> tuple[Path, Path]:
    """Render a compact, accessible static summary from frozen cohort counts."""
    rows = sensitivity_rows()
    if not rows or any(
        values["denominator"] < 0 or values["count"] < 0
        or values["count"] > values["denominator"]
        for row in rows for values in row["values"].values()
    ):
        raise ValueError("Invalid 90-degree C1 sensitivity counts.")
    figure_height = max(3.2, 0.34 * len(rows) + 1.6)
    with mpl.rc_context({
        "font.family": "DejaVu Sans", "font.size": 6.5,
        "svg.fonttype": "none", "svg.hashsalt": "openscope-standard-oddball-c1",
        "axes.spines.top": False, "axes.spines.right": False,
    }):
        fig, ax = plt.subplots(figsize=(8.8, figure_height), constrained_layout=True)
        y_positions = np.arange(len(rows), dtype=float)
        offsets = {"pooled": -0.21, "pre": 0.0, "post": 0.21}
        for repeat in REPEATS:
            percentages = []
            errors = []
            for row in rows:
                record = row["values"][repeat]
                denominator = record["denominator"]
                fraction = record["count"] / denominator if denominator else np.nan
                percentages.append(100 * fraction)
                interval = record["interval"]
                errors.append(
                    [100 * (fraction - interval[0]), 100 * (interval[1] - fraction)]
                    if interval is not None and denominator else [0.0, 0.0]
                )
            valid = np.isfinite(percentages)
            for i in np.flatnonzero(valid):
                record = rows[i]["values"][repeat]
                error = np.asarray(errors[i], dtype=float)[:, None]
                ax.barh(
                    y_positions[i] + offsets[repeat], percentages[i], height=0.16,
                    color=COLORS[repeat], xerr=error if record["interval"] else None,
                    error_kw={"elinewidth": 0.55, "capsize": 1.5},
                )
                ax.text(
                    min(percentages[i] + 1.2, 103),
                    y_positions[i] + offsets[repeat],
                    f'{record["count"]}/{record["denominator"]}',
                    va="center", ha="left", fontsize=5.5,
                )
        ax.set_yticks(y_positions, [
            f'{row["modality"]}: {row["group"]}' for row in rows
        ])
        ax.invert_yaxis()
        ax.set_xlim(0, 122)
        ax.set_xlabel("Q2-responsive eligible observations (%)")
        ax.set_title("90° Q2 sensitivity to which C1 control repeat is used", loc="left")
        ax.grid(axis="x", color="#dddddd", linewidth=0.45)
        ax.set_axisbelow(True)
        handles = [
            plt.Rectangle((0, 0), 1, 1, color=COLORS[repeat], label=REPEAT_LABELS[repeat])
            for repeat in REPEATS
        ]
        ax.legend(handles=handles, loc="lower right", frameon=False, ncol=1)
        description = (
            "For each modality and cohort group, bars show the fraction of jointly "
            "testable eligible sources passing the baseline-subtracted Q2 screen using "
            "pooled C1 controls, the pre-context C1 repeat, or the post-context C1 repeat. "
            "Labels give responsive/testable counts. Error bars for Neuropixels and "
            "mesoscope are 95% mouse-cluster bootstrap intervals; SLAP2 has two mice and "
            "no bootstrap intervals. Pooled C1 is the primary comparison."
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output, format="svg", metadata={"Date": None, "Description": description})
        plt.close(fig)
    sources = [
        Path(__file__), NEUROPIXELS_DIR / "provenance.json",
        MESOSCOPE_DIR / "provenance.json", SLAP2_DIR / "provenance.json",
    ]
    provenance_path.parent.mkdir(parents=True, exist_ok=True)
    provenance_path.write_text(json.dumps({
        "version": 1, "event": EVENT, "repeats": list(REPEATS),
        "response_rule": "Raw Q2 p<0.05 and abs(MI)>0.1; either sign.",
        "denominator": "Eligible jointly Q1/Q2-testable observations per selected C1 repeat.",
        "uncertainty": (
            "95% mouse-cluster bootstrap intervals for Neuropixels and mesoscope; "
            "no bootstrap intervals for two-mouse SLAP2."
        ),
        "sources": [
            {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path)}
            for path in sources
        ],
        "output": {"path": output.name, "sha256": sha256(output)},
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return output, provenance_path
