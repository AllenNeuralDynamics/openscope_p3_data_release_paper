from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest

from openscope_p3_publication.units import UNIT_TABLE_NAME, UNIT_TABLE_PROVENANCE_NAME

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "figure_sources" / "data"


def test_committed_unit_table_matches_provenance() -> None:
    provenance = json.loads((DATA_DIR / UNIT_TABLE_PROVENANCE_NAME).read_text(encoding="utf-8"))
    parquet_path = DATA_DIR / UNIT_TABLE_NAME
    assert hashlib.sha256(parquet_path.read_bytes()).hexdigest() == provenance["output_sha256"]

    pytest.importorskip("pyarrow")
    table = pd.read_parquet(parquet_path)
    assert len(table) == provenance["rows"]
    assert table["session_id"].nunique() == provenance["sessions"] == 60
    assert len(provenance["asset_manifest"]) == 60
    assert provenance["skipped_sessions"] == []
    assert not table.duplicated(["session_id", "unit_id"]).any()
    assert set(table["asset_id"]) == {asset["asset_id"] for asset in provenance["asset_manifest"]}


@pytest.mark.parametrize("valid_session_count", [0, 1])
def test_extraction_preserves_snapshots_when_any_session_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, valid_session_count: int
) -> None:
    namespace = runpy.run_path(str(REPO_ROOT / "scripts" / "extract_neuropixels_units.py"))
    extract = namespace["extract_units"]
    assets = [
        {"asset_path": f"valid-{index}.nwb"} for index in range(valid_session_count)
    ] + [{"asset_path": "missing-units.nwb"}]
    originals = {
        tmp_path / UNIT_TABLE_NAME: b"existing complete unit table",
        tmp_path / UNIT_TABLE_PROVENANCE_NAME: b'{"snapshot": "existing complete provenance"}',
    }
    for path, contents in originals.items():
        path.write_bytes(contents)

    def read_session(asset: dict) -> pd.DataFrame:
        if asset["asset_path"] == "missing-units.nwb":
            raise namespace["SessionSkipped"]("missing units table")
        return pd.DataFrame({"unit_id": [1]})

    builder = Mock(side_effect=AssertionError("Must not assemble an incomplete snapshot"))
    writer = Mock(side_effect=AssertionError("Must not overwrite an existing snapshot"))
    monkeypatch.setitem(extract.__globals__, "discover_session_assets", lambda: assets)
    monkeypatch.setitem(extract.__globals__, "stream_session_unit_table", read_session)
    monkeypatch.setitem(extract.__globals__, "build_unit_table", builder)
    monkeypatch.setitem(extract.__globals__, "write_unit_table", writer)

    with pytest.raises(RuntimeError, match="sessions were skipped; nothing was written"):
        extract(tmp_path, workers=1)

    builder.assert_not_called()
    writer.assert_not_called()
    assert {path: path.read_bytes() for path in originals} == originals


def test_extraction_writes_only_after_every_session_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    namespace = runpy.run_path(str(REPO_ROOT / "scripts" / "extract_neuropixels_units.py"))
    extract = namespace["extract_units"]
    assets = [{"asset_path": "valid.nwb"}]
    frame = pd.DataFrame({"unit_id": [1]})
    outputs = (tmp_path / UNIT_TABLE_NAME, tmp_path / UNIT_TABLE_PROVENANCE_NAME)
    builder = Mock(return_value=frame)
    writer = Mock(return_value=outputs)
    monkeypatch.setitem(extract.__globals__, "discover_session_assets", lambda: assets)
    monkeypatch.setitem(extract.__globals__, "stream_session_unit_table", lambda asset: frame)
    monkeypatch.setitem(extract.__globals__, "build_unit_table", builder)
    monkeypatch.setitem(extract.__globals__, "write_unit_table", writer)

    assert extract(tmp_path, workers=1) == outputs
    builder.assert_called_once_with([frame])
    writer.assert_called_once_with(frame, assets=assets, skipped=[], output_dir=tmp_path)
