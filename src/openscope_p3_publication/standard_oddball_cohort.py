"""Counts-based standard-oddball statistics and reproducible cohort summaries."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .mismatch_responsiveness import (
    benjamini_hochberg,
    clean_trial_mask,
    comparison_windows,
    modulation_index,
    paired_p_values,
    unpaired_p_values,
)
from .neural_responses import (
    NEURAL_SESSIONS,
    QC_THRESHOLDS,
    context_event_definitions,
    event_indices,
    neural_baseline_windows,
    neural_response_windows,
)

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "figure_sources/data"
COHORT_DIR = DATA / "neuropixels-standard-oddball-cohort"
LEDGER = DATA / "experimental-sessions.csv"
MANIFEST = DATA / "neuropixels-units.provenance.json"
METADATA = DATA / "neuropixels-units.parquet"
CONFIG = next(s for s in NEURAL_SESSIONS if s.context == "standard")
EVENTS = tuple(d.id for d in context_event_definitions("standard"))
KEYS = ["asset_id", "nwb_unit_id", "event_id"]
FLAGS = (
    "eligible", "q1_testable", "q2_testable", "joint_testable",
    "q1_responsive", "q2_responsive", "joint_responsive", "positive_joint",
    "negative_joint", "mixed_joint", "q2_nonsignificant",
    *[
        name
        for repeat in ("pre", "post")
        for name in (
            f"q2_{repeat}_testable", f"q2_{repeat}_responsive",
            f"joint_{repeat}_testable", f"joint_{repeat}_responsive",
            f"positive_joint_{repeat}", f"negative_joint_{repeat}",
            f"mixed_joint_{repeat}", f"q2_{repeat}_nonsignificant",
        )
    ],
)
PROBE_EXCLUSIONS = {"ecephys_820454_2025-11-05_15-21-15": ("ProbeC",)}


def sha256(path: Path) -> str:
    """Return a file's SHA256 digest."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cohort_inventory(
    ledger: Path = LEDGER, manifest: Path = MANIFEST,
) -> pd.DataFrame:
    """Freeze standard sessions against the committed asset manifest, including QC exclusions."""
    sessions = pd.read_csv(ledger, dtype=str, keep_default_na=False)
    sessions = sessions.loc[
        sessions.modality.str.lower().eq("neuropixels")
        & sessions.session_stimulus.str.endswith("_STANDARD")
    ].copy()
    if sessions.empty or not sessions.qc.isin(["PASS", "FAIL"]).all():
        raise ValueError("Standard cohort is empty or contains unreviewed session QC.")
    assets = json.loads(manifest.read_text())["asset_manifest"]
    records = []
    for row in sessions.to_dict("records"):
        session_id = row["source_session_id"]
        record = {
            "session_id": session_id, "subject_id": row["mouse_id"], "date": row["date"],
            "protocol": row["session_stimulus"], "session_qc": row["qc"],
            "qc_tags": row["qc_tags"], "ledger_source_row": row["source_row"],
            "included": row["qc"] == "PASS",
            "exclusion_reason": "" if row["qc"] == "PASS" else "session_qc_fail",
            "excluded_probes": ";".join(PROBE_EXCLUSIONS.get(session_id, ())),
        }
        if record["included"]:
            matches = [
                a for a in assets
                if f"_ses-{session_id.replace('_', '-')}_ecephys.nwb" in a["asset_path"]
            ]
            if not session_id or len(matches) != 1:
                raise ValueError(f"{session_id!r}: expected exactly one pinned asset.")
            asset = matches[0]
            record.update(
                asset_id=asset["asset_id"], asset_path=asset["asset_path"],
                asset_size=asset["size"], asset_modified=asset["modified"],
                asset_sha256=asset["digest"]["dandi:sha2-256"],
                asset_etag=asset["digest"]["dandi:dandi-etag"],
            )
        records.append(record)
    result = pd.DataFrame(records).fillna("")
    selected = result.loc[result.included]
    if selected.session_id.duplicated().any() or selected.asset_id.duplicated().any():
        raise ValueError("Selected session or pinned asset keys are duplicated.")
    return result.sort_values(["subject_id", "date"], kind="stable").reset_index(drop=True)


def rates_in_windows(
    spikes: np.ndarray, windows: list[tuple[float, float] | None],
) -> np.ndarray:
    """Count rates with Figure 9's inclusive-stop statistical window convention."""
    result = np.full(len(windows), np.nan)
    valid = [i for i, window in enumerate(windows) if window is not None]
    if valid:
        bounds = np.asarray([windows[i] for i in valid], dtype=float)
        if not np.isfinite(bounds).all() or np.any(bounds[:, 1] <= bounds[:, 0]):
            raise ValueError("Statistical windows must be finite and positive.")
        result[valid] = (
            np.searchsorted(spikes, bounds[:, 1], side="right")
            - np.searchsorted(spikes, bounds[:, 0], side="left")
        ) / (bounds[:, 1] - bounds[:, 0])
    return result


def split_control_repeats(
    context_start: np.ndarray,
    context_stop: np.ndarray,
    control_start: np.ndarray,
    control_stop: np.ndarray,
) -> dict[str, np.ndarray]:
    """Classify every control row as the repeat before or after the context block."""
    context_start = np.asarray(context_start, dtype=float)
    context_stop = np.asarray(context_stop, dtype=float)
    control_start = np.asarray(control_start, dtype=float)
    control_stop = np.asarray(control_stop, dtype=float)
    if (
        context_start.ndim != 1 or context_stop.shape != context_start.shape
        or control_start.ndim != 1 or control_stop.shape != control_start.shape
        or not len(context_start) or not len(control_start)
        or not np.isfinite(context_start).all() or not np.isfinite(context_stop).all()
        or not np.isfinite(control_start).all() or not np.isfinite(control_stop).all()
        or np.any(context_stop <= context_start) or np.any(control_stop <= control_start)
    ):
        raise ValueError("C1 repeat splitting requires aligned finite positive stimulus intervals.")
    context_first = float(context_start.min())
    context_last = float(context_stop.max())
    repeats = {
        "pre": control_stop <= context_first,
        "post": control_start >= context_last,
    }
    assigned = repeats["pre"] | repeats["post"]
    if not repeats["pre"].any() or not repeats["post"].any() or not assigned.all():
        raise ValueError("Control rows must belong to both flanking C1 repeats, with no overlap.")
    return repeats


def event_windows(tables: dict[str, dict[str, np.ndarray]]) -> dict[str, dict]:
    """Build the established standard/control windows and clean-trial identities."""
    context, control = tables["context"], tables["control"]
    control_repeats = split_control_repeats(
        context["start"], context["stop"], control["start"], control["stop"],
    )
    events = {}
    for definition in context_event_definitions("standard"):
        windows: dict = {}
        for condition, table in tables.items():
            lengths = {len(a) for a in table.values()}
            if len(lengths) != 1 or not np.isfinite(table["start"]).all():
                raise ValueError(f"{condition}: invalid stimulus table arrays.")
            indices = event_indices(
                table["trial_type"], table["orientation"], table["delay"],
                definition, control=condition == "control",
            )
            if not indices:
                raise ValueError(f"{definition.id}: no {condition} trials.")
            windows[f"{condition}_indices"] = indices
            windows[f"{condition}_test"] = neural_response_windows(
                table["start"], table["stop"], indices,
            )
            windows[f"{condition}_baseline"] = neural_baseline_windows(
                table["start"], table["stop"], indices, "standard", table["block_number"],
            )
            if condition == "control":
                for repeat, repeat_mask in control_repeats.items():
                    repeat_indices = [index for index in indices if repeat_mask[index]]
                    if not repeat_indices:
                        raise ValueError(
                            f"{definition.id}: no control trials in the {repeat} C1 repeat."
                        )
                    windows[f"control_{repeat}_indices"] = repeat_indices
                    windows[f"control_{repeat}_test"] = neural_response_windows(
                        table["start"], table["stop"], repeat_indices,
                    )
                    windows[f"control_{repeat}_baseline"] = neural_baseline_windows(
                        table["start"], table["stop"], repeat_indices, "standard",
                        table["block_number"],
                    )
            if condition == "context":
                windows["context_comparison"] = comparison_windows(
                    table["start"], table["stop"], indices, "standard", table["block_number"],
                )
                windows["clean"] = clean_trial_mask(
                    table["trial_type"], indices, "standard", table["block_number"],
                )
        events[definition.id] = windows
    return events


def response_statistics(collected: dict[str, np.ndarray], clean: list[bool]) -> pd.DataFrame:
    """Compute pooled Q2 statistics and repeat-specific sensitivity tests when available."""
    keep = np.asarray(clean, dtype=bool)
    test = collected["context_test"][:, keep]
    comparison = collected["context_comparison"][:, keep]
    baseline = collected["context_baseline"][:, keep]
    control = collected["control_test"]
    control_baseline = collected["control_baseline"]
    delta, control_delta = test - baseline, control - control_baseline
    n = len(test)

    def mean_mi(left: np.ndarray, right: np.ndarray) -> np.ndarray:
        values = np.full(n, np.nan)
        for i in range(n):
            a, b = left[i][np.isfinite(left[i])], right[i][np.isfinite(right[i])]
            if len(a) and len(b):
                values[i] = modulation_index([a.mean()], [b.mean()])
        return values

    result = pd.DataFrame({
        "q1_p": paired_p_values(test, comparison),
        "q1_mi": [modulation_index(a, b) for a, b in zip(test, comparison, strict=True)],
        "q1_baseline_mi": [
            modulation_index(a, b) for a, b in zip(delta, comparison - baseline, strict=True)
        ],
        "q1_trials": np.sum(np.isfinite(test) & np.isfinite(comparison), axis=1),
        "q2_raw_p": unpaired_p_values(test, control),
        "q2_raw_mi": mean_mi(test, control),
        "q2_p": unpaired_p_values(delta, control_delta),
        "q2_mi": mean_mi(delta, control_delta),
        "q2_context_trials": np.sum(np.isfinite(delta), axis=1),
        "q2_control_trials": np.sum(np.isfinite(control_delta), axis=1),
        "context_raw_trials": np.sum(np.isfinite(test), axis=1),
        "control_raw_trials": np.sum(np.isfinite(control), axis=1),
    })
    available_repeats = [
        repeat for repeat in ("pre", "post")
        if f"control_{repeat}_test" in collected and f"control_{repeat}_baseline" in collected
    ]
    if any(
        (f"control_{repeat}_test" in collected) != (f"control_{repeat}_baseline" in collected)
        for repeat in ("pre", "post")
    ):
        raise ValueError("Each C1 repeat requires both response and baseline windows.")
    for repeat in available_repeats:
        repeat_control = collected[f"control_{repeat}_test"]
        repeat_baseline = collected[f"control_{repeat}_baseline"]
        repeat_delta = repeat_control - repeat_baseline
        result[f"q2_{repeat}_raw_p"] = unpaired_p_values(test, repeat_control)
        result[f"q2_{repeat}_raw_mi"] = mean_mi(test, repeat_control)
        result[f"q2_{repeat}_p"] = unpaired_p_values(delta, repeat_delta)
        result[f"q2_{repeat}_mi"] = mean_mi(delta, repeat_delta)
        result[f"q2_{repeat}_context_trials"] = np.sum(np.isfinite(delta), axis=1)
        result[f"q2_{repeat}_control_trials"] = np.sum(np.isfinite(repeat_delta), axis=1)
    prefixes = ["q1", "q2", "q2_raw"]
    prefixes.extend(
        prefix
        for repeat in available_repeats
        for prefix in (f"q2_{repeat}", f"q2_{repeat}_raw")
    )
    for prefix in prefixes:
        result[f"{prefix}_q"] = benjamini_hochberg(result[f"{prefix}_p"])
    return result


def classify_units(frame: pd.DataFrame) -> pd.DataFrame:
    """Add eligibility and exploratory response flags without treating missing tests as nulls."""
    result = frame.copy()
    finite = np.isfinite
    result["qc_pass"] = (
        finite(result.amplitude_cutoff) & finite(result.isi_violations_ratio)
        & finite(result.presence_ratio)
        & (result.amplitude_cutoff < QC_THRESHOLDS["amplitude_cutoff_max"])
        & (result.isi_violations_ratio < QC_THRESHOLDS["isi_violations_ratio_max"])
        & (result.presence_ratio > QC_THRESHOLDS["presence_ratio_min"])
    )
    result["eligible"] = (
        result.qc_pass & result.decoder_label.eq("sua")
        & finite(result.firing_rate) & result.firing_rate.gt(1)
    )
    result["probe_excluded"] = [
        probe in PROBE_EXCLUSIONS.get(session, ())
        for session, probe in zip(result.session_id, result.probe, strict=True)
    ]
    result["eligible"] &= ~result.probe_excluded
    result["eligibility_reason"] = [
        ";".join(filter(None, (
            "probe_excluded_saturation" if excluded else "",
            "" if qc else "unit_qc_fail_or_missing",
            "" if label == "sua" else "not_sua",
            "" if np.isfinite(rate) and rate > 1 else "fr_not_above_1_or_missing",
        )))
        for excluded, qc, label, rate in zip(
            result.probe_excluded, result.qc_pass, result.decoder_label,
            result.firing_rate, strict=True,
        )
    ]
    for prefix in ("q1", "q2"):
        p, mi = result[f"{prefix}_p"], result[f"{prefix}_mi"]
        if (
            np.any(np.isinf(mi)) or np.any(np.isinf(p))
            or np.any(p.dropna().lt(0) | p.dropna().gt(1))
        ):
            raise ValueError(f"Invalid {prefix} statistic.")
        available = finite(p) & finite(mi)
        result[f"{prefix}_testable"] = available
        result[f"{prefix}_responsive"] = available & p.lt(0.05) & mi.abs().gt(0.1)
        result[f"{prefix}_status"] = np.where(
            ~finite(p), "insufficient_valid_trials",
            np.where(~finite(mi), "undefined_mi", "testable"),
        )
    for repeat in ("pre", "post"):
        if f"q2_{repeat}_p" not in result:
            continue
        p, mi = result[f"q2_{repeat}_p"], result[f"q2_{repeat}_mi"]
        if (
            np.any(np.isinf(mi)) or np.any(np.isinf(p))
            or np.any(p.dropna().lt(0) | p.dropna().gt(1))
        ):
            raise ValueError(f"q2_{repeat} statistic is invalid.")
        available = finite(p) & finite(mi)
        responsive = available & p.lt(0.05) & mi.abs().gt(0.1)
        result[f"q2_{repeat}_testable"] = available
        result[f"q2_{repeat}_responsive"] = responsive
        result[f"q2_{repeat}_status"] = np.where(
            ~finite(p), "insufficient_valid_trials",
            np.where(~finite(mi), "undefined_mi", "testable"),
        )
        joint = result.q1_responsive & responsive
        result[f"joint_{repeat}_testable"] = result.q1_testable & available
        result[f"joint_{repeat}_responsive"] = joint
        result[f"positive_joint_{repeat}"] = (
            joint & result.q1_mi.gt(0.1) & mi.gt(0.1)
        )
        result[f"negative_joint_{repeat}"] = (
            joint & result.q1_mi.lt(-0.1) & mi.lt(-0.1)
        )
        result[f"mixed_joint_{repeat}"] = (
            joint & ~result[f"positive_joint_{repeat}"] & ~result[f"negative_joint_{repeat}"]
        )
        result[f"q2_{repeat}_nonsignificant"] = available & p.ge(0.05)
    result["joint_testable"] = result.q1_testable & result.q2_testable
    result["joint_responsive"] = result.q1_responsive & result.q2_responsive
    joint = result.joint_responsive
    result["positive_joint"] = joint & result.q1_mi.gt(0.1) & result.q2_mi.gt(0.1)
    result["negative_joint"] = joint & result.q1_mi.lt(-0.1) & result.q2_mi.lt(-0.1)
    result["mixed_joint"] = joint & ~result.positive_joint & ~result.negative_joint
    result["q2_nonsignificant"] = result.q2_testable & result.q2_p.ge(0.05)
    return result


def summarize_units(frame: pd.DataFrame, level: str) -> pd.DataFrame:
    """Pool counts, never averages of fractions; eligibility gates every response count."""
    keys = {
        "session": ["session_id", "subject_id", "event_id", "brain_division", "brain_area"],
        "mouse": ["subject_id", "event_id", "brain_division", "brain_area"],
        "area": ["event_id", "brain_division", "brain_area"],
    }[level]
    work = frame.copy()
    work[["brain_division", "brain_area"]] = work[["brain_division", "brain_area"]].fillna(
        "unresolved"
    )
    work["n_recorded"] = 1
    for flag in FLAGS:
        work[f"n_{flag}"] = (work[flag] & work.eligible).astype(int)
    counts = ["n_recorded", *[f"n_{flag}" for flag in FLAGS]]
    result = work.groupby(keys, observed=True, dropna=False, sort=True).agg(
        **{c: (c, "sum") for c in counts},
        n_sessions=("session_id", "nunique"), n_mice=("subject_id", "nunique"),
    ).reset_index()
    result["n_excluded"] = result.n_recorded - result.n_eligible
    for test in ("q1", "q2", "joint", "q2_pre", "joint_pre", "q2_post", "joint_post"):
        denominator = result[f"n_{test}_testable"]
        result[f"n_{test}_untestable"] = result.n_eligible - denominator
    for flag, denominator in (
        ("q1_responsive", "q1"), ("q2_responsive", "q2"),
        ("joint_responsive", "joint"), ("positive_joint", "joint"),
        ("negative_joint", "joint"), ("mixed_joint", "joint"),
        ("q2_nonsignificant", "q2"),
        *[
            (flag, denominator)
            for repeat in ("pre", "post")
            for flag, denominator in (
                (f"q2_{repeat}_responsive", f"q2_{repeat}"),
                (f"joint_{repeat}_responsive", f"joint_{repeat}"),
                (f"positive_joint_{repeat}", f"joint_{repeat}"),
                (f"negative_joint_{repeat}", f"joint_{repeat}"),
                (f"mixed_joint_{repeat}", f"joint_{repeat}"),
                (f"q2_{repeat}_nonsignificant", f"q2_{repeat}"),
            )
        ],
    ):
        result[f"fraction_{flag}"] = result[f"n_{flag}"].div(
            result[f"n_{denominator}_testable"].replace(0, np.nan)
        )
    result["joint_status"] = np.where(
        result.n_joint_testable.gt(0), "testable",
        np.where(result.n_eligible.gt(0), "no_testable_units", "no_eligible_units"),
    )
    return result


def visual_rows(frame: pd.DataFrame) -> pd.Series:
    """Apply the existing Figure 9 visual cortex/thalamus anatomical group definitions."""
    return (
        frame.brain_division.eq("Isocortex") & frame.brain_area.str.startswith("VIS")
    ) | (
        frame.brain_division.eq("TH")
        & frame.brain_area.str.startswith(("LGd", "LGv", "LP"))
    )


def load_cohort(directory: Path = COHORT_DIR) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Load checksummed offline area/mouse summaries and verify selected-session coverage."""
    provenance = json.loads((directory / "provenance.json").read_text())
    for entry in provenance["outputs"]:
        if sha256(directory / entry["name"]) != entry["sha256"]:
            raise ValueError(f"Cohort output checksum mismatch: {entry['name']}")
    sessions = pd.read_csv(directory / "sessions.csv", dtype={"subject_id": str})
    expected = set(cohort_inventory().query("included").session_id)
    if set(sessions.loc[sessions.included, "session_id"]) != expected:
        raise ValueError("Published cohort no longer matches the QC-pass standard inventory.")
    for source in provenance["sources"]:
        if sha256(ROOT / source["path"]) != source["sha256"]:
            raise ValueError(f"Cohort source changed; deliberately refresh: {source['path']}")
    area = pd.read_csv(directory / "area.csv")
    mouse = pd.read_csv(directory / "mouse-area.csv", dtype={"subject_id": str})
    return area, mouse, provenance
