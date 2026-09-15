"""Tests for consecutive-mismatch adjacency analysis."""

from __future__ import annotations

import numpy as np
import pytest

from openscope_p3_publication.mismatch_adjacency import (
    SENSORIMOTOR_MIN_INTERVAL_SECONDS,
    SEQUENCE_PERIOD_ROWS,
    adjacency_records,
    context_mismatch_types,
    event_label,
    summarize_adjacency,
)


def standard_table(deviant_rows: dict[int, str], n_rows: int = 40):
    """A standard-oddball table: contiguous 0.343 s presentations, 0.343 s gaps."""
    trial_types = np.array(["standard"] * n_rows, dtype="U24")
    orientation = np.zeros(n_rows)
    for row, kind in deviant_rows.items():
        trial_types[row] = kind
        if kind == "orientation_45":
            orientation[row] = np.pi / 4
        elif kind == "orientation_90":
            orientation[row] = np.pi / 2
    start = np.arange(n_rows, dtype=float) * 0.686
    stop = start + 0.343
    return {
        "trial_type": trial_types,
        "orientation": orientation,
        "delay": np.zeros(n_rows),
        "start": start,
        "stop": stop,
        "block_number": np.full(n_rows, 2.0),
    }


def sequence_table(mismatch_sequences: dict[int, str], n_sequences: int = 12):
    """A sequence table: five 0.2669 s rows per sequence, grey last."""
    pattern = ["standard", "standard", "standard", "standard", "sequence_omission"]
    orientations = [np.pi / 2, np.pi / 4, 0.0, np.pi / 4, 0.0]
    trial_types: list[str] = []
    orientation: list[float] = []
    for seq in range(n_sequences):
        rows = list(pattern)
        oris = list(orientations)
        if seq in mismatch_sequences:
            rows[2] = mismatch_sequences[seq]
            if rows[2] == "orientation_45":
                oris[2] = np.pi / 4
            elif rows[2] == "orientation_90":
                oris[2] = np.pi / 2
        trial_types.extend(rows)
        orientation.extend(oris)
    n_rows = len(trial_types)
    start = np.arange(n_rows, dtype=float) * 0.2669
    return {
        "trial_type": np.array(trial_types, dtype="U24"),
        "orientation": np.array(orientation),
        "delay": np.zeros(n_rows),
        "start": start,
        "stop": start + 0.2669,
        "block_number": np.full(n_rows, 2.0),
    }


class TestEventLabel:
    def test_jitter_labels_include_the_delay(self):
        assert event_label("jitter", 0.15) == "jitter_150ms"
        assert event_label("jitter", 1.0) == "jitter_1000ms"

    def test_other_types_use_the_trial_type(self):
        assert event_label("halt", 0.0) == "halt"
        assert event_label("motor_omission", 0.0) == "motor_omission"


class TestContextMismatchTypes:
    def test_every_context_is_defined(self):
        for context in ("standard", "sequence", "duration", "sensorimotor"):
            assert context_mismatch_types(context)

    def test_grey_is_not_a_sequence_mismatch(self):
        assert "sequence_omission" not in context_mismatch_types("sequence")

    def test_unknown_context_raises(self):
        with pytest.raises(ValueError, match="Unknown"):
            context_mismatch_types("nonsense")


class TestStandardAdjacency:
    def test_isolated_deviants_are_not_adjacent(self):
        table = standard_table({5: "halt", 15: "omission", 25: "orientation_45"})
        records = adjacency_records(table, "standard")
        assert len(records) == 3
        assert [r["adjacent"] for r in records] == [False, False, False]

    def test_consecutive_rows_are_adjacent(self):
        table = standard_table({10: "halt", 11: "omission"})
        records = adjacency_records(table, "standard")
        assert [r["row"] for r in records] == [10, 11]
        assert [r["adjacent"] for r in records] == [False, True]
        assert records[1]["same_type"] is False

    def test_consecutive_same_type_is_flagged(self):
        table = standard_table({10: "halt", 11: "halt"})
        records = adjacency_records(table, "standard")
        assert records[1]["adjacent"] is True
        assert records[1]["same_type"] is True

    def test_block_boundary_breaks_adjacency(self):
        table = standard_table({10: "halt", 11: "omission"})
        table["block_number"][11:] = 3.0
        records = adjacency_records(table, "standard")
        assert records[1]["adjacent"] is False

    def test_preceding_standard_run_is_counted(self):
        table = standard_table({10: "halt", 11: "omission"})
        records = adjacency_records(table, "standard")
        assert records[0]["preceding_standard_run"] == 10
        assert records[1]["preceding_standard_run"] == 0


class TestSequenceAdjacency:
    def test_period_is_five_rows(self):
        assert SEQUENCE_PERIOD_ROWS == 5

    def test_mismatch_sits_at_element_three(self):
        table = sequence_table({3: "halt"})
        records = adjacency_records(table, "sequence")
        assert len(records) == 1
        assert records[0]["row"] == 3 * 5 + 2

    def test_consecutive_sequences_are_adjacent(self):
        table = sequence_table({3: "halt", 4: "omission"})
        records = adjacency_records(table, "sequence")
        assert [r["adjacent"] for r in records] == [False, True]
        assert records[1]["same_type"] is False

    def test_consecutive_same_substitution_is_flagged(self):
        table = sequence_table({3: "orientation_90", 4: "orientation_90"})
        records = adjacency_records(table, "sequence")
        assert records[1]["adjacent"] is True
        assert records[1]["same_type"] is True

    def test_sequences_two_apart_are_not_adjacent(self):
        table = sequence_table({3: "halt", 5: "omission"})
        records = adjacency_records(table, "sequence")
        assert [r["adjacent"] for r in records] == [False, False]

    def test_grey_row_sits_three_before_the_substitution(self):
        table = sequence_table({3: "halt"})
        records = adjacency_records(table, "sequence")
        row = records[0]["row"]
        assert table["trial_type"][row - 3] == "sequence_omission"
        assert table["trial_type"][row + 2] == "sequence_omission"


class TestSensorimotorAdjacency:
    def test_minimum_interval_is_two_seconds(self):
        assert SENSORIMOTOR_MIN_INTERVAL_SECONDS == 2.0

    def test_events_closer_than_the_minimum_are_adjacent(self):
        n = 200
        trial_types = np.array(["standard"] * n, dtype="U24")
        start = np.arange(n, dtype=float) * 0.0334
        # Two mismatches 0.45 s apart, one far away.
        trial_types[10] = "motor_omission"
        trial_types[23] = "motor_halt"
        trial_types[150] = "motor_halt"
        table = {
            "trial_type": trial_types,
            "orientation": np.zeros(n),
            "delay": np.zeros(n),
            "start": start,
            "stop": start + 0.0334,
            "block_number": np.full(n, 2.0),
        }
        records = adjacency_records(table, "sensorimotor")
        assert [r["adjacent"] for r in records] == [False, True, False]
        assert records[1]["interval_seconds"] == pytest.approx(13 * 0.0334, abs=1e-6)


class TestSummary:
    def test_counts_and_fractions(self):
        table = standard_table({10: "halt", 11: "halt", 20: "omission"})
        summary = summarize_adjacency(adjacency_records(table, "standard"), "standard")
        assert summary["mismatch_trials"] == 3
        assert summary["adjacent_count"] == 1
        assert summary["adjacent_same_type_count"] == 1
        assert summary["adjacent_fraction"] == pytest.approx(1 / 3)

    def test_per_label_breakdown_sums_to_total(self):
        table = standard_table({10: "halt", 11: "omission", 20: "omission"})
        summary = summarize_adjacency(adjacency_records(table, "standard"), "standard")
        assert sum(summary["per_label"][k]["total"] for k in summary["per_label"]) == 3

    def test_empty_records_raise(self):
        with pytest.raises(ValueError, match="no mismatch"):
            summarize_adjacency([], "standard")
