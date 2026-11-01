"""Offline, native-size two-channel SLAP2 columns using the shared optical panel geometry."""

from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree as ET

from .figures import PLATFORM_LOGO_PROVENANCE_PATH, load_platform_logos
from .mesoscope_standard_oddball import ROOT, sha256
from .mesoscope_standard_oddball_figure import render_column
from .slap2_standard_oddball import SIGNALS, SNAPSHOT, load_snapshot
from .slap2_standard_oddball_cohort_figure import cohort_plot_data, write_audits

OUTPUT_DIR = ROOT / "images/figures/generated"
AUDIT_DIR = ROOT / "figure_sources/derived/slap2-standard-oddball-90"


def dmd_grouped_order(payload: dict) -> list[int]:
    """Retain the frozen Rastermap relative order within DMD1, then DMD2."""
    original = payload["order"]
    keys = payload["roi_keys"]
    order = [
        i for dmd in (1, 2) for i in original if keys[i].startswith(f"DMD{dmd}:")
    ]
    if sorted(order) != list(range(len(keys))):
        raise ValueError("DMD-grouped display requires a complete, unique source permutation.")
    return order


def build_slap2_standard_oddball(
    output_dir: Path = OUTPUT_DIR, audit_dir: Path = AUDIT_DIR,
    *, primary_only: bool = False,
) -> list[Path]:
    """Render DMD-separated heatmaps and the glutamate-only cohort without scientific refits."""
    payload, statistics, arrays = load_snapshot()
    cohort = cohort_plot_data()
    cohort_outputs = write_audits(cohort, audit_dir.parent / "slap2-standard-oddball-cohort")
    logo = load_platform_logos()["slap2"]
    outputs, records = [], []
    output_dir.mkdir(parents=True, exist_ok=True)
    for signal in (("glutamate",) if primary_only else SIGNALS):
        units = {r["unit"] for r in payload["sources"] if r["signal"] == signal}
        if len(units) != 1:
            raise ValueError(f"{signal}: DMD units differ; explicit calibration is required.")
        unit = units.pop()
        example_keys = payload["examples"][signal]
        channel_label = "green iGluSnFR4f" if signal == "glutamate" else "red RCaMP3"
        response_rule = (
            "positive-joint (both MI>0.1)"
            if payload["positive_examples_only"][signal] else "joint-responsive (either MI sign)"
        )
        trial_summary = "; ".join(
            f"DMD{d} {len(w['context'])} context/{len(w['control'])} control"
            for d, w in payload["trials_by_dmd"].items()
        )
        description = (
            f"SLAP2 {signal}: stored {channel_label} "
            f"dFF series, native {unit}, without additional scaling. "
            "A/B: mouse 828408, November 18 2025, one standard-oddball session. "
            "134 original sources; 119 eligible (DMD1 79, DMD2 40), pooled across DMDs. "
            "Both signals use the identical frozen archive-wide glutamate High/Intermediate-SNR "
            "selection, not calcium-specific SNR. Fifteen no-baseline-noise sources excluded. "
            "Protocol-clean 90-degree trials: 30 context/68 control. Each DMD uses its own "
            f"fully recorded trials: {trial_summary}. "
            "Acquisition segments split at gaps >3 median native frame intervals; each "
            "statistical window and the full displayed window must fit recorded segments. "
            "Finite eligible-source native coverage is required in both channels, including "
            "interpolation bracketing frames. Stored NaN warm-up frames are not filled. "
            "No interpolation across acquisition pauses. Trial exposure differs across DMDs, "
            "but matches between signals within each DMD. "
            f"A: separately selected {response_rule} and active Q2-nonsignificant examples: "
            f"{', '.join(example_keys)}. No amplitude gate. Unresponsive means Q2-nonsignificant, "
            "not necessarily visually "
            "unresponsive. Context trial heatmaps; context green/control grey means ± trial SEM. "
            "B: all eligible context sources grouped by DMD1 then DMD2, with labels and a divider. "
            "Within each DMD retain the relative order from the frozen context-glutamate "
            "Rastermap fit, shared with calcium; no refitting or trace normalization. "
            f"Context/control curves: solid {response_rule} sources, dotted "
            "Q2-nonsignificant sources, each classified independently per channel. "
            "Means equally weight sources; SEM is across sources, not mice or independent neurons. "
            "Sources may belong to the same dendrite/cell. All displays subtract each trial's "
            "full native preceding-grey mean. Paired two-sided Wilcoxon Q1 compares native "
            "500-ms oddball and preceding-standard means; unpaired two-sided Mann-Whitney Q2 "
            "compares context/control response minus preceding grey. Exploratory raw p<0.05 and "
            f"|MI|>0.1; solid/example responsive rule: {response_rule}. "
            "Signed MIs are not clipped. "
            "BH alternatives use all 134 original sources per event/channel. "
            "No glutamate event detection, spike conversion or smoothing kernel. "
            "Linear 200-Hz alignment is display-only; tests use original native frames. "
            "Tan/grey shading shows actual median preceding-standard/oddball presentation "
            f"bounds {payload['stimulus_spans']}, not the 500-ms test windows. "
            "X-limits -0.75 to +0.75 s. "
            + ("No SLAP2 cohort analysis or cohort panel." if signal == "calcium" else (
                "C: verified standard glutamate subset, 2 sessions/2 mice, November 18 828408 "
                "and December 11 829704. DMD1 and DMD2 Q1/Q2/Both proportions include "
                "either MI sign; no amplitude gate. Include session/groups with >=20 eligible "
                "sources before testability. Denominator: eligible jointly Q1/Q2-testable "
                "source/session observations, not unique independent neurons. Heights pool "
                "counts, not session percentage means. Circle/square points show mice "
                "828408/829704, respectively. No bootstrap confidence intervals for two mice. "
                "Six frozen-QC sessions contain other protocols, twelve legacy sessions have "
                "unresolved standard block/event mapping, and four newer standard sessions "
                "lack frozen labels; none are silently called nonresponsive. "
                "Native trial coverage matches the existing dual-channel reference definition; "
                "red frames are consulted for completeness only, not glutamate statistics. "
                + " ".join(
                    f"{r.group}: {r.n_joint_testable} jointly testable/{r.n_eligible} eligible; "
                    f"Q1 {r.n_q1_responsive}, Q2 {r.n_q2_responsive}, Both {r.n_joint_responsive}."
                    for r in cohort["panel_pooled"].itertuples()
                )
            ))
        )
        view = {
            **payload, "example_roi_keys": example_keys, "order": dmd_grouped_order(payload),
            "dmd_groups": [
                {"label": f"DMD{d}", "count": len(payload["roi_keys_by_dmd"][str(d)])}
                for d in (1, 2)
            ],
        }
        rows = statistics.loc[statistics.event_id.eq("orientation_90")]
        path = output_dir / f"slap2-standard-oddball-90-{signal}.svg"
        record = render_column(
            view, rows, arrays, signal, logo, path,
            cohort=cohort if signal == "glutamate" else None, platform="slap2",
            native_label=f"{'Glu' if signal == 'glutamate' else 'Ca'} change ({unit})",
            description=description,
        )
        root = ET.parse(path).getroot()
        box = root.attrib["viewBox"].split()
        height = 174 if signal == "glutamate" else 135
        box[3] = f"{height * 72 / 25.4:.8f}"
        root.set("viewBox", " ".join(box))
        root.set("width", "54mm")
        root.set("height", f"{height}mm")
        path.write_text(ET.tostring(root, encoding="unicode"), encoding="utf-8", newline="\n")
        outputs.append(path)
        records.append({
            **record, "example_roi_keys": example_keys, "native_unit": unit,
            "footprint_mm": [54, height],
        })
    sources = [
        Path(__file__), ROOT / "src/openscope_p3_publication/mesoscope_standard_oddball_figure.py",
        ROOT / "src/openscope_p3_publication/slap2_standard_oddball_cohort_figure.py",
        *cohort_outputs,
        ROOT / "src/openscope_p3_publication/figure_typography.py",
        PLATFORM_LOGO_PROVENANCE_PATH, logo,
        *[SNAPSHOT / name for name in ("statistics.csv.gz", "responses.npz", "provenance.json")],
    ]
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit = audit_dir / "provenance.json"
    audit.write_text(json.dumps({
        "version": 2, "records": records,
        "sources": [
            {"path": p.relative_to(ROOT).as_posix() if p.is_relative_to(ROOT) else p.as_posix(),
             "sha256": sha256(p)}
            for p in sources
        ],
        "outputs": [{"path": p.name, "sha256": sha256(p)} for p in outputs],
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return [*outputs, audit, *cohort_outputs]


if __name__ == "__main__":
    for output in build_slap2_standard_oddball():
        print(f"Wrote {output}")
