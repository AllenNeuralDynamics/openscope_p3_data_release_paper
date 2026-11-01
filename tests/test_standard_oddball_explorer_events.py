"""Four-event native-display snapshot integrity and scientific preservation."""

import json

import numpy as np
import pytest

from openscope_p3_publication import standard_oddball_explorer_events as events
from openscope_p3_publication.standard_oddball_explorer_window import load_wide_population


@pytest.mark.parametrize("modality", ("neuropixels", "mesoscope", "slap2"))
def test_real_distinct_events_and_unchanged_90_degree_display(modality):
    metadata = json.loads((events.DIRECTORY / "provenance.json").read_text())
    keys = metadata["modalities"][modality]["source_ids"]
    view, arrays = events.load_population_events(modality, keys)
    previous, wide = load_wide_population(modality, keys)
    assert set(view["events"]) == set(events.EVENTS)
    index = list(events.EVENTS).index("orientation_90")
    np.testing.assert_array_equal(arrays["time"], wide["time"])
    np.testing.assert_allclose(arrays["delta"][index], wide["delta"], atol=2e-6, rtol=2e-7)
    np.testing.assert_array_equal(arrays["counts"][index], wide["counts"])
    for e, event in enumerate(events.EVENTS):
        assert np.isfinite(arrays["delta"][e]).all()
        assert [p["offset"] for p in view["events"][event]["presentations"]] == [-2, -1, 0, 1, 2]
        if e != index:
            assert not np.array_equal(arrays["delta"][e], wide["delta"])
    assert previous["source_ids"] == view["source_ids"]


def test_source_identity_and_checksum_corruption_are_explicit(tmp_path):
    metadata = json.loads((events.DIRECTORY / "provenance.json").read_text())
    with pytest.raises(ValueError, match="identity"):
        events.load_population_events("neuropixels", ["wrong-source"])
    (tmp_path / "provenance.json").write_text(json.dumps(metadata))
    (tmp_path / "neuropixels.npz").write_bytes(b"not-the-frozen-array")
    with pytest.raises(ValueError, match="checksum"):
        events.load_population_events(
            "neuropixels", metadata["modalities"]["neuropixels"]["source_ids"], tmp_path,
        )


def test_missing_neuropixels_grey_is_a_recorded_exclusion_not_a_zero_baseline():
    metadata = json.loads((events.DIRECTORY / "provenance.json").read_text())
    view = metadata["modalities"]["neuropixels"]["events"]["orientation_45"]
    excluded = view["excluded_trials"]["control"]
    assert any(row["reason"] == "missing_preceding_grey" for row in excluded)
    indices = {t["index"] for t in view["trials"]["control"]}
    assert not indices.intersection(row["index"] for row in excluded)
    assert all(t["baseline_window"] is not None for t in view["trials"]["control"])
