"""Offline adapters for the primary-signal standard-oddball explorer."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .figures import JAVASCRIPT_DIR, load_figure_controls, load_figure_stylesheet
from .mesoscope_standard_oddball import ROOT, sha256
from .mesoscope_standard_oddball import load_snapshot as load_mesoscope
from .mesoscope_standard_oddball_cohort_figure import (
    cohort_plot_data as mesoscope_cohort,
)
from .mesoscope_standard_oddball_figure import load_display_snapshot
from .slap2_standard_oddball import load_snapshot as load_slap2
from .slap2_standard_oddball_cohort_figure import cohort_plot_data as slap2_cohort
from .slap2_standard_oddball_figure import dmd_grouped_order
from .standard_oddball_cohort import EVENTS
from .standard_oddball_examples import load_example_spikes
from .standard_oddball_explorer_events import load_population_events
from .standard_oddball_explorer_window import WINDOW
from .standard_oddball_neuropixels import load_diagnostic
from .standard_oddball_ordering import load_context_order
from .standard_oddball_population import BIN_SECONDS, load_population, population_arrays
from .standard_oddball_publication_data import (
    DIRECTORY as PUBLICATION_DIRECTORY,
)
from .standard_oddball_publication_data import (
    STATISTICS,
    load_example_statistics,
    load_neuropixels_cohort,
)

OUTPUT = ROOT / "interactive/standard-oddball-explorer.html"
STATIC = ROOT / "images/figures/generated/standard-oddball-three-modality-dff-glutamate.svg"
EVENT_LABELS = {
    "orientation_45": "45° orientation", "orientation_90": "90° orientation",
    "halt": "Motion halt", "omission": "Omission",
}
SCREENS = ("q1", "q2", "joint")


def records(frame: pd.DataFrame) -> list[dict]:
    """Serialize finite values without JavaScript-invalid NaN literals."""
    return json.loads(frame.to_json(orient="records", double_precision=15))


def population_view(
    time: np.ndarray, delta: np.ndarray, order: list[int],
    units: list[dict], spans: list[list[float]], *, event: str = "orientation_90",
) -> dict:
    """Encode unchanged float64 population samples with an explicit event identity."""
    if (
        delta.shape != (2, len(units), len(time))
        or not np.isfinite(delta).all() or not np.isfinite(time).all()
        or not np.all(np.diff(time) > 0)
        or sorted(order) != list(range(len(units)))
        or len({u["id"] for u in units}) != len(units)
    ):
        raise ValueError("Invalid explorer population shape, ordering, identity or samples.")
    return {
        "event": event, "time": time.tolist(), "units": units, "order": order,
        "spans": spans, "encoding": "base64-little-endian-float64", "shape": list(delta.shape),
        "values": base64.b64encode(np.asarray(delta, dtype="<f8").tobytes()).decode("ascii"),
    }


def cohort_rows(
    prepared: dict, event: str, *, grouping: str = "brain_area",
) -> list[dict]:
    """Normalize existing pooled counts, mouse points and bootstrap endpoints."""
    result = []
    for row in prepared["areas"].to_dict("records"):
        group = row[grouping]
        mice = prepared["mice"].loc[prepared["mice"][grouping].eq(group)]
        result.append({
            "event": event, "group": group, "n": int(row["n_joint_testable"]),
            "n_eligible": int(row["n_eligible"]),
            "n_sessions": int(row["n_sessions"]), "n_mice": int(row["n_mice"]),
            "counts": {s: int(row[f"n_{s}_responsive"]) for s in SCREENS},
            "intervals": {
                s: [
                    float(row[f"fraction_{s}_responsive_ci95_{b}"]) for b in ("low", "high")
                ] if row.get("bootstrap_status") == "estimated" else None
                for s in SCREENS
            },
            "points": [
                {"mouse": str(m["subject_id"]), "n": int(m["n_joint_testable"]),
                 "counts": {s: int(m[f"n_{s}_responsive"]) for s in SCREENS}}
                for m in mice.to_dict("records") if m["n_joint_testable"] > 0
            ],
        })
    return result


def load_explorer_data() -> dict:
    """Load validated frozen snapshots; no remote reads, statistical tests or refits."""
    np_units = load_example_statistics("neuropixels")
    diagnostic = load_diagnostic()
    examples = load_example_spikes(diagnostic)
    population = load_population(diagnostic, examples["events"][1])
    rates, baselines = population_arrays(population)
    np_rows = np_units.loc[
        np_units.event_id.eq("orientation_90")
    ].set_index("id")
    source_units = []
    for unit in diagnostic.units:
        row = np_rows.loc[str(unit["id"])]
        if not row.eligible:
            raise ValueError("Explorer population source is ineligible in its frozen cohort.")
        source_units.append({
            "id": str(unit["id"]), "label": f'{unit["location"]} unit {unit["id"]}',
            "group": unit["parentArea"],
            **records(row[STATISTICS].to_frame().T)[0],
        })
    np_cohort = [
        row for event in EVENTS
        for row in cohort_rows(load_neuropixels_cohort(event), event)
    ]
    spans = [
        np.median([t[field] for t in population["event"]["conditions"]["context"]["trials"]],
                  axis=0).tolist()
        for field in ("previous_window", "event_window")
    ]
    neuropixels = {
        "id": "neuropixels", "label": "Neuropixels", "unit": "Hz", "kind": "units",
        "session": population["session_id"], "mouse": "830794",
        "notes": "QC-passing SUA >1 Hz; population is visual cortex/thalamus only. "
                 "Cohort areas also include other regions. Causal 25-ms SDF, 5-ms bins.",
        "cohort_rule": "At least 20 QC-passing SUA per session/region before firing-rate "
                       "and testability filtering; pooled jointly testable eligible units.",
        "population": population_view(
            -0.75 + (np.arange(rates.shape[-1]) + 0.5) * BIN_SECONDS,
            rates - baselines[..., None], load_context_order(population).tolist(),
            source_units, spans,
        ), "cohort": np_cohort,
    }
    meso_payload, meso_stats, meso_arrays = load_mesoscope()
    meso_payload, _ = load_display_snapshot(meso_payload, meso_stats, meso_arrays)
    meso_prepared = mesoscope_cohort()
    meso_rows = meso_stats.loc[meso_stats.signal.eq("dff")].set_index("roi_key").loc[
        meso_payload["roi_keys"]
    ]
    meso_sources = [
        {"id": row["roi_key"], "label": row["roi_key"], "group": row["area"],
         **{k: row[k] for k in STATISTICS}}
        for row in records(meso_rows.reset_index())
    ]
    meso_cohort = []
    for event in EVENTS:
        prepared = {
            k: meso_prepared[k].loc[
                meso_prepared[k].event_id.eq(event) & meso_prepared[k].signal.eq("dff")
            ] for k in ("areas", "mice")
        }
        meso_cohort.extend(cohort_rows(prepared, event))
    meso_spans = [meso_payload["stimulus_spans"][k] for k in ("comparison", "response")]
    mesoscope = {
        "id": "mesoscope", "label": "Mesoscope ΔF/F", "unit": "%", "kind": "ROIs",
        "session": meso_payload["session_id"], "mouse": "832700",
        "notes": "Somatic High/Intermediate-SNR ROIs; native stored percent ΔF/F. "
                 "Native ~9.48-Hz samples linearly aligned for display, not smoothed SDFs.",
        "cohort_rule": "At least 20 eligible ROIs per session/area after pooling planes; "
                       "signal-specific jointly testable ROI/session observations, not "
                       "unique longitudinal neurons.",
        "population": population_view(
            meso_arrays["time"], meso_arrays["delta_dff"], meso_payload["order"],
            meso_sources, meso_spans,
        ), "cohort": meso_cohort,
    }
    slap_payload, slap_stats, slap_arrays = load_slap2()
    slap_prepared = slap2_cohort()
    slap_rows = slap_stats.loc[
        slap_stats.signal.eq("glutamate") & slap_stats.event_id.eq("orientation_90")
    ].set_index("roi_key").loc[slap_payload["roi_keys"]]
    slap_sources = [
        {"id": row["roi_key"], "label": row["roi_key"], "group": f'DMD{row["dmd"]}',
         **{k: row[k] for k in STATISTICS}}
        for row in records(slap_rows.reset_index())
    ]
    slap_cohort = []
    for row in slap_prepared["pooled"].to_dict("records"):
        if row["group"] == "Pooled":
            continue
        points = slap_prepared["sessions"].loc[
            slap_prepared["sessions"].event_id.eq(row["event_id"])
            & slap_prepared["sessions"].group.eq(row["group"])
            & slap_prepared["sessions"].contributing
        ]
        slap_cohort.append({
            "event": row["event_id"], "group": row["group"], "n": int(row["n_joint_testable"]),
            "n_eligible": int(row["n_eligible"]), "n_sessions": int(row["n_sessions"]),
            "n_mice": int(row["n_mice"]),
            "counts": {s: int(row[f"n_{s}_responsive"]) for s in SCREENS},
            "intervals": {s: None for s in SCREENS},
            "points": [
                {"mouse": str(m["subject_id"]), "n": int(m["n_joint_testable"]),
                 "counts": {s: int(m[f"n_{s}_responsive"]) for s in SCREENS}}
                for m in points.to_dict("records")
            ],
        })
    slap2 = {
        "id": "slap2", "label": "SLAP2 glutamate", "unit": "a.u.", "kind": "sources",
        "session": slap_payload["session_id"], "mouse": "828408",
        "notes": "Frozen glutamate High/Intermediate-SNR optical sources in VISp; not "
                 "independent neurons. DMD-specific complete trials; 200-Hz linear display "
                 "alignment, no acquisition-gap bridging or SDF kernel.",
        "cohort_rule": "Two verified standard sessions/two mice; at least 20 eligible sources "
                       "per session/DMD, jointly testable source/session denominator. "
                       "Mouse points only, no bootstrap intervals. Twelve legacy sessions "
                       "have unresolved standard-block mapping.",
        "population": population_view(
            slap_arrays["time"], slap_arrays["delta_glutamate"],
            dmd_grouped_order(slap_payload), slap_sources,
            [slap_payload["stimulus_spans"][k] for k in ("comparison", "response")],
        ), "cohort": slap_cohort,
    }
    datasets = [neuropixels, mesoscope, slap2]
    event_statistics = {
        "neuropixels": np_units,
        "mesoscope": load_example_statistics("mesoscope"),
        "slap2": slap_stats.loc[slap_stats.signal.eq("glutamate")],
    }
    color_labels = {
        "neuropixels": "Δ Firing rate (spikes/s)",
        "mesoscope": "Δ F/F", "slap2": "Δ Glu change",
    }
    for dataset in datasets:
        previous = dataset.pop("population")
        view, arrays = load_population_events(
            dataset["id"], [u["id"] for u in previous["units"]],
        )
        dataset["populations"], dataset["color_label"] = {}, color_labels[dataset["id"]]
        statistics = event_statistics[dataset["id"]]
        for e, event in enumerate(EVENTS):
            rows = statistics.loc[statistics.event_id.eq(event)].set_index(
                "roi_key" if dataset["id"] == "slap2" else "id"
            )
            units = []
            for i, unit in enumerate(previous["units"]):
                key = unit["id"]
                row = rows.loc[key]
                if not row.eligible:
                    raise ValueError(f"{dataset['id']}/{event}/{key}: source eligibility changed.")
                units.append({
                    **unit, **records(row[STATISTICS].to_frame().T)[0],
                    "display_trial_counts": [
                        [int(arrays["counts"][e, c, i].min()), int(arrays["counts"][e, c, i].max())]
                        for c in (0, 1)
                    ],
                })
            event_view = view["events"][event]
            dataset["populations"][event] = {
                **population_view(
                    arrays["time"], arrays["delta"][e], previous["order"], units,
                    previous["spans"] if event == "orientation_90" else [],
                    event=event,
                ),
                "window": list(WINDOW), "presentations": event_view["presentations"],
                "recorded_trial_count_ranges": event_view["count_ranges"],
            }
    return {
        "version": 2, "events": [{"id": e, "label": EVENT_LABELS[e]} for e in EVENTS],
        "datasets": datasets,
        "screen_rule": "Exploratory raw p<0.05 and |MI|>0.1, either sign; Both is the "
                       "intersection. Signed baseline-subtracted MIs are not clipped. "
                       "All bars use eligible jointly Q1/Q2-testable denominators. "
                       "Population filters do not recompute tests or change cohort bars.",
    }


def build_standard_oddball_explorer(output: Path = OUTPUT) -> Path:
    """Generate a self-contained explorer with the complete static print counterpart."""
    if not STATIC.is_file():
        raise ValueError("Build the three-modality static counterpart before the explorer.")
    payload = load_explorer_data()
    template = (JAVASCRIPT_DIR / "standard-oddball-explorer.html").read_text()
    replacements = {
        "__DATA__": json.dumps(payload, allow_nan=False, separators=(",", ":")).replace(
            "<", "\\u003c"
        ),
        "__CSS__": load_figure_stylesheet("standard-oddball-explorer.css"),
        "__JS__": (JAVASCRIPT_DIR / "standard-oddball-explorer.js").read_text(),
        "__CONTROLS__": load_figure_controls(),
        "__STATIC__": "data:image/svg+xml;base64," + base64.b64encode(
            STATIC.read_bytes()
        ).decode("ascii"),
    }
    for token, value in replacements.items():
        template = template.replace(token, value)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(template, encoding="utf-8", newline="\n")
    sources = [
        Path(__file__), Path(__file__).with_name("standard_oddball_cohort_figure.py"), STATIC,
        *[JAVASCRIPT_DIR / f"standard-oddball-explorer.{ext}" for ext in ("html", "css", "js")],
        ROOT / "figure_sources/data/neuropixels-standard-oddball-90-population.provenance.json",
        ROOT / "figure_sources/data/neuropixels-standard-oddball-90-rastermap.json",
        ROOT / "figure_sources/data/standard-oddball-explorer-window/provenance.json",
        ROOT / "figure_sources/data/standard-oddball-explorer-events/provenance.json",
        Path(__file__).with_name("standard_oddball_explorer_events.py"),
        PUBLICATION_DIRECTORY / "provenance.json", PUBLICATION_DIRECTORY / "cohorts.json",
        Path(__file__).with_name("standard_oddball_publication_data.py"),
        ROOT / (
            "figure_sources/data/mesoscope-standard-oddball-832700-2026-01-30/"
            "display-provenance.json"
        ),
        *[ROOT / "figure_sources/data" / d / "provenance.json" for d in (
            "slap2-standard-oddball-cohort", "mesoscope-standard-oddball-832700-2026-01-30",
            "slap2-standard-oddball-828408-2025-11-18",
        )],
    ]
    output.with_suffix(".provenance.json").write_text(json.dumps({
        "version": 2, "population_events": list(EVENTS), "statistics_events": list(EVENTS),
        "sources": [{"path": str(p.relative_to(ROOT)), "sha256": sha256(p)} for p in sources],
        "output_sha256": sha256(output),
    }, indent=2, sort_keys=True) + "\n")
    return output
