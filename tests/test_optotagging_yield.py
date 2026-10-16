from __future__ import annotations

from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")
pytest.importorskip("scipy")

from openscope_p3_publication import optotagging  # noqa: E402
from openscope_p3_publication.optotagging import (  # noqa: E402
    TAGGING_CONDITION,
    collapse_cortical_layers,
    optotagging_yield_summary,
    tagged_unit_mask,
)

P_COLUMN = f"{TAGGING_CONDITION}__p_value"
MI_COLUMN = f"{TAGGING_CONDITION}__modulation_index"


class FakeBrainRegions:
    def __init__(self, names: dict[str, str]) -> None:
        self._acronyms = list(names)
        self.name = np.asarray(list(names.values()))

    def acronym2id(self, acronym: str) -> np.ndarray:
        if acronym not in self._acronyms:
            return np.asarray([], dtype=int)
        return np.asarray([self._acronyms.index(acronym) + 1])

    def id2index(self, region_id: int):
        return None, [[np.asarray([region_id - 1])]]


def test_tagged_unit_mask_requires_both_thresholds() -> None:
    results = pd.DataFrame(
        {
            P_COLUMN: [0.01, 0.01, 0.2, 0.05, np.nan],
            MI_COLUMN: [0.5, 0.1, 0.5, 0.5, 0.5],
        }
    )

    assert tagged_unit_mask(results).tolist() == [True, False, False, False, False]


def test_collapse_cortical_layers_only_strips_named_layers() -> None:
    regions = FakeBrainRegions(
        {
            "VISp2/3": "Primary visual area, layer 2/3",
            "MOp5": "Primary motor area Layer 5",
            "CA1": "Field CA1",
            "VISp6a": "Primary visual area, layer 6a",
        }
    )

    collapsed = collapse_cortical_layers(
        ["VISp2/3", "MOp5", "CA1", "VISp6a", "unmapped3"], brain_regions=regions
    )

    assert collapsed.tolist() == ["VISp", "MOp", "CA1", "VISp", "unmapped3"]


def test_yield_summary_excludes_unregistered_units_from_regional_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    structure = {"VISp5": "VISp", "CA1": "CA1"}
    parent = {"VISp5": "Isocortex", "CA1": "HPF"}
    monkeypatch.setattr(
        optotagging,
        "collapse_cortical_layers",
        lambda locations, brain_regions: np.asarray([structure[x] for x in locations]),
    )
    monkeypatch.setattr(
        optotagging,
        "allen_major_parent_acronyms",
        lambda locations, brain_regions: [parent[x] for x in locations],
    )
    results = pd.DataFrame(
        {
            "session_id": ["a", "a", "a", "b", "b", "c", "c"],
            "unit_id": [1, 2, 3, 1, 2, 1, 2],
            P_COLUMN: [0.01, 0.01, 0.5, 0.01, 0.01, 0.01, 0.01],
            MI_COLUMN: [0.5, 0.5, 0.5, 0.5, 0.0, 0.5, 0.5],
        }
    )
    unit_areas = pd.DataFrame(
        {
            "session_id": ["a", "a", "a", "b", "b", "c", "c"],
            "unit_id": ["1", "2", "3", "1", "2", "1", "2"],
            "location": ["VISp5", "CA1", "CA1", "VISp5", "VISp5", "unknown", "unknown"],
        }
    )

    summary = optotagging_yield_summary(results, unit_areas, brain_regions=object())

    assert summary["sessions"] == ["a", "b", "c"]
    assert summary["overall"]["counts"] == [2, 1, 2]
    assert summary["unregistered"] == {"sessions": ["c"], "unit_count": 2}
    by_label = {record["label"]: record for record in summary["structures"]}
    assert by_label["VISp"]["counts"] == [1, 1]
    assert by_label["CA1"]["counts"] == [1]
    assert by_label["CA1"]["sampled_session_count"] == 1
    assert {record["label"] for record in summary["major_parent"]} == {"Isocortex", "HPF"}


def test_yield_summary_rejects_units_without_locations() -> None:
    results = pd.DataFrame(
        {"session_id": ["a"], "unit_id": [1], P_COLUMN: [0.01], MI_COLUMN: [0.5]}
    )
    unit_areas = pd.DataFrame({"session_id": ["a"], "unit_id": ["2"], "location": ["CA1"]})

    with pytest.raises(ValueError, match="no recorded location"):
        optotagging_yield_summary(results, unit_areas, brain_regions=SimpleNamespace())
