"""Consecutive-mismatch adjacency in the P3 predictive-processing context blocks.

A mismatch event that immediately follows another mismatch is not equally
surprising: the animal has not re-established the standard context in between.
This module measures how often that happens, per context, from a stimulus table.

The adjacency rule is context-specific because the blocks have different
structure:

- ``standard`` and ``duration`` present one stimulus per table row, so the
  reference is the immediately preceding row.
- ``sequence`` presents five rows per sequence (four gratings then a grey
  inter-sequence interval) with the substitution always at element three, so the
  reference is the previous sequence, five rows back.
- ``sensorimotor`` embeds 350 ms mismatch events in a continuous 30 Hz stream of
  phase updates, so there is no meaningful "previous trial" and the reference is
  elapsed time.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

CONTEXT_MISMATCH_TYPES: dict[str, tuple[str, ...]] = {
    "standard": ("orientation_45", "orientation_90", "halt", "omission"),
    "sequence": ("orientation_45", "orientation_90", "halt", "omission"),
    "duration": ("jitter", "omission"),
    "sensorimotor": (
        "motor_orientation_45",
        "motor_orientation_90",
        "motor_halt",
        "motor_omission",
    ),
}
SEQUENCE_GREY_TRIAL_TYPE = "sequence_omission"
SEQUENCE_PERIOD_ROWS = 5
SEQUENCE_SUBSTITUTION_ELEMENT = 3
SENSORIMOTOR_MIN_INTERVAL_SECONDS = 2.0
ADJACENCY_RULES: dict[str, str] = {
    "standard": "previous presentation row is also a deviant",
    "sequence": f"previous sequence ({SEQUENCE_PERIOD_ROWS} rows back) also substituted",
    "duration": "previous presentation row is also a deviant",
    "sensorimotor": (
        f"previous mismatch onset less than {SENSORIMOTOR_MIN_INTERVAL_SECONDS:g} s earlier"
    ),
}
INTERVAL_UNITS: dict[str, str] = {
    "standard": "presentations",
    "sequence": "sequences",
    "duration": "presentations",
    "sensorimotor": "seconds",
}
TABLE_KEYS = ("trial_type", "orientation", "delay", "start", "stop", "block_number")


def context_mismatch_types(context: str) -> tuple[str, ...]:
    """Return the TrialType values that count as a mismatch in this context."""
    try:
        return CONTEXT_MISMATCH_TYPES[context]
    except KeyError as exc:
        raise ValueError(f"Unknown mismatch-adjacency context: {context}") from exc


def adjacency_rule(context: str) -> str:
    """Return a human-readable statement of the context's adjacency rule."""
    context_mismatch_types(context)
    return ADJACENCY_RULES[context]


def interval_unit(context: str) -> str:
    """Return the unit in which this context's inter-mismatch interval is measured."""
    context_mismatch_types(context)
    return INTERVAL_UNITS[context]


def event_label(trial_type: str, delay: float) -> str:
    """Label a mismatch so that repeats of the *same* deviant can be identified.

    Duration deviants share the ``jitter`` trial type and differ only by delay,
    so the delay is folded into the label.
    """
    if trial_type == "jitter":
        return f"jitter_{round(float(delay) * 1000)}ms"
    return str(trial_type)


def _require_table(table: Mapping[str, Any]) -> dict[str, np.ndarray]:
    missing = [key for key in TABLE_KEYS if key not in table]
    if missing:
        raise ValueError(f"Stimulus table is missing columns: {', '.join(missing)}")
    arrays = {
        "trial_type": np.asarray(table["trial_type"]).astype("U"),
        "orientation": np.asarray(table["orientation"], dtype=float),
        "delay": np.asarray(table["delay"], dtype=float),
        "start": np.asarray(table["start"], dtype=float),
        "stop": np.asarray(table["stop"], dtype=float),
        "block_number": np.asarray(table["block_number"], dtype=float),
    }
    lengths = {len(value) for value in arrays.values()}
    if len(lengths) != 1:
        raise ValueError("Stimulus-table columns must all have the same length.")
    return arrays


def _reference_rows(
    rows: np.ndarray,
    arrays: dict[str, np.ndarray],
    context: str,
) -> list[int | None]:
    """The row each mismatch is compared against, or None when unavailable."""
    if context == "sequence":
        offset = SEQUENCE_PERIOD_ROWS
    elif context == "sensorimotor":
        return [None] * len(rows)
    else:
        offset = 1

    references: list[int | None] = []
    block = arrays["block_number"]
    for row in rows:
        candidate = int(row) - offset
        if candidate < 0 or block[candidate] != block[row]:
            references.append(None)
        else:
            references.append(candidate)
    return references


def _preceding_standard_run(
    row: int,
    is_mismatch: np.ndarray,
    block: np.ndarray,
) -> int:
    """How many consecutive non-mismatch rows precede this row in the same block."""
    count = 0
    index = row - 1
    while index >= 0 and not is_mismatch[index] and block[index] == block[row]:
        count += 1
        index -= 1
    return count


def adjacency_records(
    table: Mapping[str, Any],
    context: str,
) -> list[dict[str, Any]]:
    """Return one record per mismatch event, flagging adjacency to the previous one.

    Each record carries the table ``row``, the ``label`` identifying which deviant
    it was, whether it is ``adjacent`` to the preceding mismatch, whether that
    preceding mismatch was the ``same_type``, the ``interval`` to the previous
    mismatch in this context's natural unit, and how many standard presentations
    preceded it.
    """
    mismatch_types = context_mismatch_types(context)
    arrays = _require_table(table)
    trial_type = arrays["trial_type"]

    is_mismatch = np.isin(trial_type, list(mismatch_types))
    rows = np.flatnonzero(is_mismatch)
    if not len(rows):
        return []

    labels = [
        event_label(trial_type[row], arrays["delay"][row]) for row in rows
    ]
    references = _reference_rows(rows, arrays, context)
    label_by_row = dict(zip(rows.tolist(), labels, strict=True))

    records: list[dict[str, Any]] = []
    for position, row in enumerate(rows.tolist()):
        if context == "sensorimotor":
            if position == 0:
                interval: float | None = None
                adjacent = False
            else:
                interval = float(
                    arrays["start"][row] - arrays["start"][rows[position - 1]]
                )
                adjacent = interval < SENSORIMOTOR_MIN_INTERVAL_SECONDS
            same_type = bool(
                adjacent and labels[position] == labels[position - 1]
            )
        else:
            reference = references[position]
            adjacent = reference is not None and bool(is_mismatch[reference])
            same_type = bool(
                adjacent and label_by_row.get(reference) == labels[position]
            )
            if position == 0:
                interval = None
            else:
                gap_rows = row - rows[position - 1]
                interval = (
                    gap_rows / SEQUENCE_PERIOD_ROWS
                    if context == "sequence"
                    else float(gap_rows)
                )

        records.append(
            {
                "row": int(row),
                "label": labels[position],
                "trial_type": str(trial_type[row]),
                "onset_seconds": float(arrays["start"][row]),
                "adjacent": bool(adjacent),
                "same_type": same_type,
                "interval": interval,
                "interval_seconds": (
                    None
                    if position == 0
                    else float(
                        arrays["start"][row] - arrays["start"][rows[position - 1]]
                    )
                ),
                "preceding_standard_run": _preceding_standard_run(
                    row, is_mismatch, arrays["block_number"]
                ),
            }
        )
    return records


def summarize_adjacency(
    records: Sequence[Mapping[str, Any]],
    context: str,
) -> dict[str, Any]:
    """Aggregate per-event adjacency records into the figure's summary payload."""
    context_mismatch_types(context)
    if not records:
        raise ValueError(f"{context} has no mismatch events to summarize.")

    adjacent = [bool(record["adjacent"]) for record in records]
    same_type = [bool(record["same_type"]) for record in records]
    adjacent_count = int(sum(adjacent))

    per_label: dict[str, dict[str, int]] = {}
    for record in records:
        entry = per_label.setdefault(
            str(record["label"]), {"total": 0, "adjacent": 0, "same_type": 0}
        )
        entry["total"] += 1
        entry["adjacent"] += int(bool(record["adjacent"]))
        entry["same_type"] += int(bool(record["same_type"]))

    intervals = [
        float(record["interval"])
        for record in records
        if record["interval"] is not None
    ]
    seconds = [
        float(record["interval_seconds"])
        for record in records
        if record["interval_seconds"] is not None
    ]

    return {
        "context": context,
        "adjacency_rule": adjacency_rule(context),
        "interval_unit": interval_unit(context),
        "mismatch_trials": len(records),
        "adjacent_count": adjacent_count,
        "adjacent_fraction": adjacent_count / len(records),
        "adjacent_same_type_count": int(sum(same_type)),
        "adjacent_different_type_count": adjacent_count - int(sum(same_type)),
        "per_label": per_label,
        "interval_min": min(intervals) if intervals else None,
        "interval_median": float(np.median(intervals)) if intervals else None,
        "interval_seconds_min": min(seconds) if seconds else None,
        "interval_seconds_median": float(np.median(seconds)) if seconds else None,
        "preceding_standard_run_zero_count": int(
            sum(1 for record in records if record["preceding_standard_run"] == 0)
        ),
    }
