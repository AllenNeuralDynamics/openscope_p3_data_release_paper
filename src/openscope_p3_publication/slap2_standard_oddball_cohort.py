"""Source-verified glutamate cohort, explicit legacy exclusions and DMD-specific denominators."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .mesoscope_standard_oddball import ROOT, sha256, signal_statistics
from .slap2_standard_oddball import ASSETS, QUALITY, load_snapshot

DATA = ROOT / "figure_sources/data/slap2-standard-oddball-cohort"
DERIVED = ROOT / "figure_sources/derived/slap2-standard-oddball-cohort"
EVENTS = ("orientation_45", "orientation_90", "halt", "omission")
GROUPS = ("DMD1", "DMD2", "Pooled")
MINIMUM_ELIGIBLE = 20
VERIFIED_SESSIONS = (
    "sub-828408_ses-828408-2025-11-18-14-44-48",
    "sub-829704_ses-829704-2025-12-11-12-57-26",
)


def freeze_inventory(audit_dir: Path, directory: Path = DATA) -> None:
    """Generate a frozen inventory from the completed 20-asset native metadata audit."""
    if directory.exists():
        raise FileExistsError(f"Refusing to overwrite cohort inventory: {directory}")
    assets = json.loads(ASSETS.read_text())["source_assets"]
    records, audits = [], []
    quality = pd.read_csv(QUALITY)
    for asset in assets:
        audit = json.loads((audit_dir / f"{asset['asset_id']}.json").read_text())
        if audit["asset"] != asset:
            raise ValueError(f"Native audit pin differs: {asset['session_id']}")
        session = asset["session_id"]
        labels = quality.loc[quality.session.eq(session)]
        tables = audit["tables"]
        explicit = "standard_oddball" in tables and "standard_control" in tables
        legacy = any(k in tables for k in ("gratings", "stimulus_presentations"))
        if explicit != (session in VERIFIED_SESSIONS):
            raise ValueError("Audited standard membership differs from approved verified subset.")
        record = {
            "session_id": session, "subject_id": str(labels.subject.iloc[0]),
            "asset_id": asset["asset_id"], "asset_path": asset["path"],
            "layout": labels.layout.iloc[0], "original_sources": len(labels),
            "eligible_sources": int(labels.quality_class.isin(["High SNR", "Intermediate"]).sum()),
            "included": explicit,
            "status": "verified_standard" if explicit else (
                "legacy_mapping_unresolved" if legacy else "other_oddball_protocol"
            ),
            "exclusion_reason": "" if explicit else (
                "no_source_backed_legacy_block_event_mapping" if legacy
                else "no_explicit_standard_oddball_table"
            ),
            "native_interval_tables": ";".join(tables),
        }
        records.append(record)
        audits.append({
            "asset": asset, "checked_at": audit["checked_at"], "tables": tables,
            "signals": audit["signals"], "initial_compatibility": audit["initial_compatibility"],
        })
    ledger = pd.read_csv(ROOT / "figure_sources/data/experimental-sessions.csv", dtype=str)
    for row in ledger.loc[
        ledger.modality.str.lower().eq("slap2")
        & ledger.session_stimulus.str.endswith("_STANDARD")
    ].itertuples():
        session = f"sub-{row.mouse_id}_ses-{row.source_session_id.replace('_', '-')}"
        if session in set(quality.session):
            continue
        records.append({
            "session_id": session, "subject_id": row.mouse_id, "included": False,
            "status": "missing_frozen_quality_labels",
            "exclusion_reason": "not_in_frozen_figure5h_qc_archive",
            "native_interval_tables": "",
        })
    directory.mkdir(parents=True)
    frame = pd.DataFrame(records).fillna("")
    frame.to_csv(directory / "sessions.csv", index=False)
    (directory / "stimulus-audit.json").write_text(
        json.dumps({"version": 1, "sessions": audits}, indent=2, sort_keys=True) + "\n",
    )


def quality_rows(session: str, dmd: int, ids: np.ndarray) -> pd.DataFrame:
    """Match all original source columns to unchanged archive-wide labels."""
    rows = pd.read_csv(QUALITY)
    rows = rows.loc[rows.session.eq(session) & rows.dmd.eq(dmd)]
    if (
        rows.roi.duplicated().any() or set(rows.roi) != set(ids)
        or not np.array_equal(ids, np.arange(len(ids)))
        or not rows.layout.eq("dual").all() or not rows.has_calcium.eq(True).all()
    ):
        raise ValueError(f"{session}/DMD{dmd}: original source identity/layout mismatch.")
    rows = rows.set_index("roi").loc[ids].reset_index()
    rows["roi_key"] = [f"DMD{dmd}:{i}" for i in ids]
    rows["eligible"] = rows.quality_class.isin(["High SNR", "Intermediate"])
    return rows


def november_reference() -> tuple[pd.DataFrame, dict]:
    """Replay and reuse the approved November native results without a remote reanalysis."""
    payload, table, arrays = load_snapshot()
    selected = table.loc[table.signal.eq("glutamate")].copy()
    for dmd in (1, 2):
        for event in EVENTS:
            native = {
                key: arrays[f"native:DMD{dmd}:glutamate:{event}:{key}"]
                for key in ("context_test", "context_baseline", "context_comparison",
                            "control_test", "control_baseline")
            }
            replay = signal_statistics(native)
            rows = selected.loc[selected.dmd.eq(dmd) & selected.event_id.eq(event)]
            for column in ("q1_p", "q1_mi", "q2_p", "q2_mi"):
                np.testing.assert_allclose(
                    rows[column], replay[column], rtol=2e-12, atol=2e-12, equal_nan=True,
                )
    selected["session_id"] = payload["session_id"]
    selected["subject_id"] = "828408"
    selected["asset_id"] = payload["asset"]["asset_id"]
    return selected, payload


def summaries(units: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Pool counts once per grouping; do not count the pooled and DMD summaries together."""
    if (
        units.duplicated(["asset_id", "dmd", "roi_id", "event_id"]).any()
        or not units.signal.eq("glutamate").all()
        or not units.event_id.isin(EVENTS).all() or not units.dmd.isin([1, 2]).all()
        or not units.joint_testable.eq(units.q1_testable & units.q2_testable).all()
        or not units.joint_responsive.eq(units.q1_responsive & units.q2_responsive).all()
    ):
        raise ValueError("Invalid or duplicate glutamate cohort statistics/identities.")
    frames = []
    for group in GROUPS:
        frame = units.copy() if group == "Pooled" else units.loc[
            units.dmd.eq(int(group[-1]))
        ].copy()
        frame["testable"] = frame.eligible & frame.joint_testable
        for screen in ("q1", "q2", "joint"):
            frame[f"testable_{screen}"] = frame.eligible & frame[f"{screen}_testable"]
            frame[f"responsive_{screen}"] = frame.testable & frame[f"{screen}_responsive"]
        by = ["session_id", "subject_id", "asset_id", "event_id"]
        sessions = frame.groupby(by, sort=True).agg(
            n_original=("eligible", "size"), n_eligible=("eligible", "sum"),
            n_joint_testable=("testable", "sum"),
            **{f"n_{s}_testable": (f"testable_{s}", "sum") for s in ("q1", "q2")},
            **{f"n_{s}_responsive": (f"responsive_{s}", "sum") for s in ("q1", "q2", "joint")},
        ).reset_index()
        sessions["group"] = group
        sessions["included"] = sessions.n_eligible.ge(MINIMUM_ELIGIBLE)
        sessions["contributing"] = sessions.included & sessions.n_joint_testable.gt(0)
        sessions["n_untestable"] = sessions.n_eligible - sessions.n_joint_testable
        frames.append(sessions)
    sessions = pd.concat(frames, ignore_index=True)
    count_columns = [c for c in sessions if c.startswith("n_")]
    pooled = sessions.loc[sessions.included].groupby(["event_id", "group"], sort=True).agg(
        **{c: (c, "sum") for c in count_columns},
        n_sessions=("session_id", "nunique"), n_mice=("subject_id", "nunique"),
        n_contributing_sessions=("contributing", "sum"),
    ).reset_index()
    for frame in (sessions, pooled):
        for screen in ("q1", "q2", "joint"):
            frame[f"{screen}_fraction"] = np.divide(
                frame[f"n_{screen}_responsive"], frame.n_joint_testable,
                out=np.full(len(frame), np.nan), where=frame.n_joint_testable.gt(0),
            )
        frame["minimum_eligible_sources"] = MINIMUM_ELIGIBLE
    return sessions, pooled


def load_cohort(directory: Path = DATA) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Validate compact frozen cohort inputs without network access."""
    provenance = json.loads((directory / "provenance.json").read_text())
    for record in provenance["inputs"]:
        if sha256(ROOT / record["path"]) != record["sha256"]:
            raise ValueError(f"Glutamate cohort source changed: {record['path']}")
    for record in provenance["outputs"]:
        if sha256(directory / record["path"]) != record["sha256"]:
            raise ValueError(f"Glutamate cohort payload changed: {record['path']}")
    inventory = pd.read_csv(directory / "sessions.csv", keep_default_na=False)
    units = pd.read_csv(directory / "units.csv.gz")
    included = inventory.loc[inventory.included]
    if (
        set(included.session_id) != set(VERIFIED_SESSIONS)
        or set(units.session_id) != set(VERIFIED_SESSIONS)
        or len(units) != (134 + 76) * 4
    ):
        raise ValueError("Verified glutamate cohort membership/family differs.")
    for session in VERIFIED_SESSIONS:
        rows = units.loc[units.session_id.eq(session)]
        ids = rows[["dmd", "roi_id"]].drop_duplicates()
        if len(rows) != len(ids) * len(EVENTS):
            raise ValueError("Incomplete source/event family in glutamate cohort.")
        for dmd in (1, 2):
            native_ids = ids.loc[ids.dmd.eq(dmd), "roi_id"].to_numpy()
            quality = quality_rows(session, dmd, native_ids).set_index("roi")
            observed = rows.loc[rows.dmd.eq(dmd)]
            if not observed.quality_class.eq(observed.roi_id.map(quality.quality_class)).all():
                raise ValueError("Frozen glutamate quality classes differ.")
    summaries(units)
    return inventory, units, provenance
