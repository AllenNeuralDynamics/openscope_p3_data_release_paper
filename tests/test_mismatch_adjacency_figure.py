"""Tests for the consecutive-mismatch adjacency supplementary figure."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from openscope_p3_publication.figures import FIGURE_SANS_FONT
from openscope_p3_publication.mismatch_adjacency_figure import (
    ADJACENT_COLOR,
    DATA_PATH,
    DIFFERENT_TYPE_COLOR,
    load_adjacency_data,
    write_mismatch_adjacency_svg,
)


def synthetic_payload() -> dict:
    def events(n: int, adjacent: int, same: int, unit_step: float):
        out = []
        for index in range(n):
            is_adjacent = index < adjacent
            out.append(
                {
                    "row": index * 3,
                    "label": "halt" if index % 2 else "omission",
                    "adjacent": is_adjacent,
                    "same_type": is_adjacent and index < same,
                    "interval": None if index == 0 else float(index % 7 + 1),
                    "onset_offset_seconds": round(index * unit_step, 4),
                }
            )
        return out

    def context(name: str, unit: str, n: int, adjacent: int, same: int) -> dict:
        return {
            "sessions": 15,
            "subjects": ["830794"],
            "schedule_identical_across_sessions": True,
            "schedule_sha256": "0" * 64,
            "rows": 2274,
            "block_duration_seconds_min": 1592.0,
            "block_duration_seconds_max": 1592.1,
            "block_duration_seconds": 1592.0,
            "events": events(n, adjacent, same, 11.0),
            "summary": {
                "context": name,
                "adjacency_rule": "previous presentation row is also a deviant",
                "interval_unit": unit,
                "mismatch_trials": n,
                "adjacent_count": adjacent,
                "adjacent_fraction": adjacent / n,
                "adjacent_same_type_count": same,
                "adjacent_different_type_count": adjacent - same,
                "per_label": {"halt": {"total": n // 2, "adjacent": 1, "same_type": 0}},
                "interval_min": 1.0,
                "interval_median": 4.0,
                "interval_seconds_min": 0.45,
                "interval_seconds_median": 7.7,
                "preceding_standard_run_zero_count": adjacent,
            },
        }

    return {
        "version": 1,
        "context_order": ["standard", "sequence", "duration", "sensorimotor"],
        "contexts": {
            "standard": context("standard", "presentations", 140, 13, 1),
            "sequence": context("sequence", "sequences", 140, 20, 4),
            "duration": context("duration", "presentations", 140, 13, 6),
            "sensorimotor": context("sensorimotor", "seconds", 140, 19, 4),
        },
    }


@pytest.fixture
def synthetic_data(tmp_path: Path) -> Path:
    path = tmp_path / "mismatch-adjacency.json"
    path.write_text(json.dumps(synthetic_payload()), encoding="utf-8")
    return path


class TestRenderFromSynthetic:
    def test_writes_a_well_formed_svg(self, synthetic_data: Path, tmp_path: Path):
        output = write_mismatch_adjacency_svg(
            output=tmp_path / "out.svg",
            data_path=synthetic_data,
            provenance_path=tmp_path / "absent.provenance.json",
        )
        content = output.read_text(encoding="utf-8")
        assert content.startswith("<svg")
        assert content.rstrip().endswith("</svg>")
        assert content.count("<svg") == 1

    def test_declares_accessible_title_and_description(
        self, synthetic_data: Path, tmp_path: Path
    ):
        content = write_mismatch_adjacency_svg(
            output=tmp_path / "out.svg",
            data_path=synthetic_data,
            provenance_path=tmp_path / "absent.json",
        ).read_text(encoding="utf-8")
        assert 'role="img"' in content
        assert 'aria-labelledby="title description"' in content
        assert '<title id="title">' in content
        assert '<desc id="description">' in content

    def test_uses_the_publication_font(self, synthetic_data: Path, tmp_path: Path):
        content = write_mismatch_adjacency_svg(
            output=tmp_path / "out.svg",
            data_path=synthetic_data,
            provenance_path=tmp_path / "absent.json",
        ).read_text(encoding="utf-8")
        assert FIGURE_SANS_FONT in content
        assert "Source Sans 3" not in content

    def test_labels_every_context(self, synthetic_data: Path, tmp_path: Path):
        content = write_mismatch_adjacency_svg(
            output=tmp_path / "out.svg",
            data_path=synthetic_data,
            provenance_path=tmp_path / "absent.json",
        ).read_text(encoding="utf-8")
        for label in ("Standard oddball", "Sequence", "Duration", "Sensorimotor"):
            assert label in content

    def test_reports_the_adjacent_percentages(self, synthetic_data: Path, tmp_path: Path):
        content = write_mismatch_adjacency_svg(
            output=tmp_path / "out.svg",
            data_path=synthetic_data,
            provenance_path=tmp_path / "absent.json",
        ).read_text(encoding="utf-8")
        # 13/140 = 9.3%, 20/140 = 14.3%
        assert "9.3%" in content
        assert "14.3%" in content

    def test_uses_the_validated_adjacency_colors(
        self, synthetic_data: Path, tmp_path: Path
    ):
        content = write_mismatch_adjacency_svg(
            output=tmp_path / "out.svg",
            data_path=synthetic_data,
            provenance_path=tmp_path / "absent.json",
        ).read_text(encoding="utf-8")
        assert ADJACENT_COLOR in content
        assert DIFFERENT_TYPE_COLOR in content

    def test_carries_a_legend_for_multiple_series(
        self, synthetic_data: Path, tmp_path: Path
    ):
        content = write_mismatch_adjacency_svg(
            output=tmp_path / "out.svg",
            data_path=synthetic_data,
            provenance_path=tmp_path / "absent.json",
        ).read_text(encoding="utf-8")
        assert "same deviant type" in content
        assert "different deviant type" in content

    def test_canvas_is_the_reference_width(self, synthetic_data: Path, tmp_path: Path):
        content = write_mismatch_adjacency_svg(
            output=tmp_path / "out.svg",
            data_path=synthetic_data,
            provenance_path=tmp_path / "absent.json",
        ).read_text(encoding="utf-8")
        width = float(re.search(r'<svg[^>]+width="([^"]+)"', content).group(1))
        assert width == 1200

    def test_empty_contexts_raise(self, tmp_path: Path):
        path = tmp_path / "empty.json"
        path.write_text(json.dumps({"version": 1, "contexts": {}}), encoding="utf-8")
        with pytest.raises(RuntimeError, match="no context records"):
            load_adjacency_data(path, tmp_path / "absent.json")


@pytest.mark.skipif(
    not DATA_PATH.exists(), reason="committed adjacency intermediate is absent"
)
class TestCommittedData:
    def test_measured_counts_match_the_verified_values(self):
        payload = load_adjacency_data()
        expected = {
            "standard": (140, 13),
            "sequence": (140, 20),
            "duration": (140, 13),
            "sensorimotor": (140, 19),
        }
        for context, (trials, adjacent) in expected.items():
            summary = payload["contexts"][context]["summary"]
            assert summary["mismatch_trials"] == trials, context
            assert summary["adjacent_count"] == adjacent, context

    def test_schedules_are_identical_across_sessions(self):
        payload = load_adjacency_data()
        for entry in payload["contexts"].values():
            assert entry["schedule_identical_across_sessions"] is True

    def test_sequence_structure_is_five_rows(self):
        payload = load_adjacency_data()
        structure = payload["contexts"]["sequence"]["structure"]
        assert structure["sequences"] * 5 == payload["contexts"]["sequence"]["rows"]
