from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")
pytest.importorskip("scipy")

from openscope_p3_publication.optotagging import (  # noqa: E402
    TAGGING_CONDITION,
    optotagging_yield_summary,
    tagged_unit_mask,
)

P_COLUMN = f"{TAGGING_CONDITION}__p_value"
MI_COLUMN = f"{TAGGING_CONDITION}__modulation_index"


def test_tagged_unit_mask_requires_both_thresholds() -> None:
    results = pd.DataFrame(
        {
            P_COLUMN: [0.01, 0.01, 0.2, 0.05, np.nan],
            MI_COLUMN: [0.5, 0.1, 0.5, 0.5, 0.5],
        }
    )

    assert tagged_unit_mask(results).tolist() == [True, False, False, False, False]


def test_yield_summary_excludes_unregistered_units_from_regional_tables() -> None:
    results = pd.DataFrame(
        {
            "session_id": ["a", "a", "a", "b", "b", "c", "c"],
            "unit_id": [1, 2, 3, 1, 2, 1, 2],
            P_COLUMN: [0.01, 0.01, 0.5, 0.01, 0.01, 0.01, 0.01],
            MI_COLUMN: [0.5, 0.5, 0.5, 0.5, 0.0, 0.5, 0.5],
        }
    )
    unit_table = pd.DataFrame(
        {
            "session_id": ["a", "a", "a", "b", "b", "c", "c", "c"],
            "unit_id": ["1", "2", "3", "1", "2", "1", "2", "noise-unit"],
            "brain_division": ["Isocortex", "HPF", "HPF", "Isocortex", "Isocortex"]
            + [None, None, None],
            "brain_area": ["VISp", "CA1", "CA1", "VISp", "VISp", None, None, None],
        }
    )

    summary = optotagging_yield_summary(results, unit_table)

    assert summary["sessions"] == ["a", "b", "c"]
    assert summary["overall"]["counts"] == [2, 1, 2]
    assert summary["unregistered"] == {"sessions": ["c"], "unit_count": 2}
    by_label = {record["label"]: record for record in summary["structures"]}
    assert by_label["VISp"]["counts"] == [1, 1]
    assert by_label["CA1"]["counts"] == [1]
    assert by_label["CA1"]["sampled_session_count"] == 1
    assert {record["label"] for record in summary["major_parent"]} == {"Isocortex", "HPF"}


def test_yield_summary_rejects_units_missing_from_unit_table() -> None:
    results = pd.DataFrame(
        {"session_id": ["a"], "unit_id": [1], P_COLUMN: [0.01], MI_COLUMN: [0.5]}
    )
    unit_table = pd.DataFrame(
        {"session_id": ["a"], "unit_id": ["2"], "brain_division": ["HPF"], "brain_area": ["CA1"]}
    )

    with pytest.raises(ValueError, match="missing from the unit table"):
        optotagging_yield_summary(results, unit_table)
