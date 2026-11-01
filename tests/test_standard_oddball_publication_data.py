"""Compact Figure 9 inputs preserve exact floats and avoid analysis-scale tables."""

import json
import runpy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from openscope_p3_publication import standard_oddball_publication_data as publication
from openscope_p3_publication.standard_oddball_explorer import load_explorer_data


def test_exact_float_and_dtype_restoration():
    value = 0.012345678901234567
    encoded = {
        "columns": ["n", "fraction", "subject_id"],
        "dtypes": {"n": "int64", "fraction": "float64", "subject_id": "object"},
        "records": [
            {"n": 7, "fraction": value, "subject_id": "001"},
            {"n": 0, "fraction": None, "subject_id": "002"},
        ],
    }
    frame = publication.decode_frame(json.loads(json.dumps(encoded)))
    assert frame.fraction.iloc[0] == value
    assert np.isnan(frame.fraction.iloc[1])
    assert frame.n.dtype == np.dtype("int64")
    assert frame.subject_id.tolist() == ["001", "002"]


def test_exact_counts_and_no_recomputed_tests():
    data = publication.load_publication_data()
    metadata = json.loads((publication.DIRECTORY / "provenance.json").read_text())
    assert metadata["tests_recomputed"] is False
    assert {r["path"].split("/")[-2] for r in metadata["upstream_analyses"]} == {
        "neuropixels-standard-oddball-cohort", "mesoscope-standard-oddball-cohort",
    }
    assert (publication.DIRECTORY / "cohorts.json").stat().st_size < 4 * 1024**2
    assert set(data["neuropixels"]["events"]) == {
        "orientation_45", "orientation_90", "halt", "omission",
    }
    np_cohort = publication.load_neuropixels_cohort()
    assert np_cohort["provenance"]["session_count"] == 13
    assert np_cohort["provenance"]["mouse_count"] == 13
    meso = publication.load_mesoscope_cohort()
    assert meso["source_provenance"]["session_count"] == 20
    assert meso["source_provenance"]["mouse_count"] == 10
    for modality, count in (("neuropixels", 203), ("mesoscope", 1475)):
        frame = publication.load_example_statistics(modality)
        assert len(frame) == 4 * count
        assert frame.groupby("event_id").id.nunique().eq(count).all()


def test_renderers_never_read_full_cohort_tables(monkeypatch):
    original = pd.read_csv

    def guarded_read_csv(path, *args, **kwargs):
        path = str(path)
        assert "neuropixels-standard-oddball-cohort" not in path
        assert "mesoscope-standard-oddball-cohort" not in path
        return original(path, *args, **kwargs)

    monkeypatch.setattr(pd, "read_csv", guarded_read_csv)
    assert len(load_explorer_data()["datasets"]) == 3


def test_corrupt_compact_output_is_explicit(tmp_path: Path):
    metadata = json.loads((publication.DIRECTORY / "provenance.json").read_text())
    (tmp_path / "provenance.json").write_text(json.dumps(metadata))
    (tmp_path / "cohorts.json").write_text("{}")
    with pytest.raises(ValueError, match="checksum"):
        publication.load_publication_data(tmp_path)


def test_renderer_provenance_refresh_preserves_frozen_values_offline(tmp_path, monkeypatch):
    def reject_csv(*args, **kwargs):
        raise AssertionError("Serialization refresh must not read full analysis tables.")

    monkeypatch.setattr(pd, "read_csv", reject_csv)
    refresh = runpy.run_path(
        str(publication.ROOT / "scripts/freeze_standard_oddball_publication.py"),
    )["refresh_renderer_provenance"]
    frozen = (publication.DIRECTORY / "cohorts.json").read_bytes()
    (tmp_path / "cohorts.json").write_bytes(frozen)
    metadata = json.loads((publication.DIRECTORY / "provenance.json").read_text())
    source = metadata["inputs"][-1]
    historical_hash = source["frozen_source_sha256"]
    source["sha256"] = historical_hash
    provenance_path = tmp_path / "provenance.json"
    provenance_path.write_text(json.dumps(metadata))
    refresh(tmp_path)
    updated = json.loads(provenance_path.read_text())
    assert (tmp_path / "cohorts.json").read_bytes() == frozen
    assert updated["output_sha256"] == metadata["output_sha256"]
    assert updated["tests_recomputed"] is False
    assert updated["inputs"][-1]["frozen_source_sha256"] == historical_hash
    assert b"\r\n" not in provenance_path.read_bytes()
    publication.load_publication_data(tmp_path)


@pytest.mark.parametrize("mutation", ["payload", "analysis_source"])
def test_renderer_provenance_refresh_rejects_other_changes(tmp_path, mutation):
    refresh = runpy.run_path(
        str(publication.ROOT / "scripts/freeze_standard_oddball_publication.py"),
    )["refresh_renderer_provenance"]
    (tmp_path / "cohorts.json").write_bytes(
        (publication.DIRECTORY / "cohorts.json").read_bytes(),
    )
    metadata = json.loads((publication.DIRECTORY / "provenance.json").read_text())
    if mutation == "payload":
        (tmp_path / "cohorts.json").write_text("{}")
    else:
        metadata["inputs"][1]["sha256"] = "0" * 64
    provenance_path = tmp_path / "provenance.json"
    provenance_path.write_text(json.dumps(metadata))
    original = provenance_path.read_bytes()
    with pytest.raises(ValueError, match="checksum|source changed"):
        refresh(tmp_path)
    assert provenance_path.read_bytes() == original
