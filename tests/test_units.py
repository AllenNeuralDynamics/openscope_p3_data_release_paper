from __future__ import annotations

import hashlib
import json
from pathlib import Path

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
