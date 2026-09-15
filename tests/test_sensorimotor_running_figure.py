"""Tests for the sensorimotor locomotion supplementary figure."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from openscope_p3_publication.figures import FIGURE_SANS_FONT, FIGURE_TYPE_SCALE
from openscope_p3_publication.sensorimotor_running import (
    DEFAULT_RUNNING_THRESHOLD_CM_S,
    MINIMUM_QUALIFYING_TRIALS,
    RUNNING_THRESHOLDS_CM_S,
)
from openscope_p3_publication.sensorimotor_running_figure import (
    AVAILABLE_COLOR,
    DATA_PATH,
    SEQUENTIAL_RAMP,
    UNAVAILABLE_COLOR,
    load_running_data,
    write_sensorimotor_running_svg,
)

LABELS = ("motor_halt", "motor_omission", "motor_orientation_45", "motor_orientation_90")


def session(subject: str, mean_speed: float, qualifying: dict[str, int]) -> dict:
    thresholds = {}
    for key, count in qualifying.items():
        per_label = {label: count // 4 for label in LABELS}
        minimum = min(per_label.values())
        thresholds[key] = {
            "threshold_cm_s": float(key),
            "qualifying_trials": count,
            "qualifying_fraction": count / 140,
            "per_label": per_label,
            "minimum_per_label": minimum,
            "available": minimum >= MINIMUM_QUALIFYING_TRIALS,
        }
    return {
        "asset_id": "a" * 36,
        "asset_path": f"sub-{subject}/sub-{subject}_ses.nwb",
        "session_id": f"{subject}_2026-01-26",
        "subject": subject,
        "running_unit": "cm/s",
        "running_sample_rate_hz": 60.0,
        "context": {
            "mismatch_trials": 140,
            "labels": list(LABELS),
            "minimum_window_samples": 20,
            "block": {
                "samples": 93000,
                "mean_cm_s": mean_speed,
                "median_cm_s": mean_speed * 0.9,
                "p90_cm_s": mean_speed * 1.5,
                "running_fraction": 0.5,
            },
            "thresholds": thresholds,
        },
    }


def synthetic_payload() -> dict:
    keys = [f"{value:g}" for value in RUNNING_THRESHOLDS_CM_S]
    fast = session("848387", 70.63, dict(zip(keys, [138, 138, 137, 136], strict=True)))
    good = session("830794", 23.42, dict(zip(keys, [134, 132, 124, 109], strict=True)))
    poor = session("830846", 1.12, dict(zip(keys, [21, 19, 14, 0], strict=True)))
    dead = session("830848", 0.09, dict(zip(keys, [0, 0, 0, 0], strict=True)))
    return {
        "version": 1,
        "analysis": {
            "baseline_seconds": 0.343,
            "default_threshold_cm_s": DEFAULT_RUNNING_THRESHOLD_CM_S,
            "minimum_qualifying_trials": MINIMUM_QUALIFYING_TRIALS,
            "thresholds_cm_s": list(RUNNING_THRESHOLDS_CM_S),
        },
        "cohort": {
            "sessions": 4,
            "sessions_with_running": 4,
            "block_mean_cm_s_median": 12.27,
            "stationary_median_sessions": 2,
            "by_threshold": {
                key: {
                    "threshold_cm_s": float(key),
                    "sessions_available": 2,
                    "available_subjects": ["830794", "848387"],
                }
                for key in keys
            },
        },
        "sessions": [fast, good, poor, dead],
    }


@pytest.fixture
def synthetic_data(tmp_path: Path) -> Path:
    path = tmp_path / "sensorimotor-running.json"
    path.write_text(json.dumps(synthetic_payload()), encoding="utf-8")
    return path


def render(data: Path, tmp_path: Path) -> str:
    return write_sensorimotor_running_svg(
        output=tmp_path / "out.svg",
        data_path=data,
        provenance_path=tmp_path / "absent.json",
    ).read_text(encoding="utf-8")


class TestRender:
    def test_writes_a_well_formed_svg(self, synthetic_data: Path, tmp_path: Path):
        content = render(synthetic_data, tmp_path)
        assert content.startswith("<svg")
        assert content.rstrip().endswith("</svg>")
        assert content.count("<svg") == 1

    def test_declares_accessible_title_and_description(
        self, synthetic_data: Path, tmp_path: Path
    ):
        content = render(synthetic_data, tmp_path)
        assert 'role="img"' in content
        assert 'aria-labelledby="title description"' in content
        assert '<title id="title">' in content
        assert '<desc id="description">' in content

    def test_uses_the_publication_font(self, synthetic_data: Path, tmp_path: Path):
        content = render(synthetic_data, tmp_path)
        assert FIGURE_SANS_FONT in content
        assert "Source Sans 3" not in content

    def test_respects_the_minimum_font_size(self, synthetic_data: Path, tmp_path: Path):
        content = render(synthetic_data, tmp_path)
        width = float(re.search(r'<svg[^>]+width="([0-9.]+)"', content).group(1))
        sizes = [float(size) for size in re.findall(r'font-size="([0-9.]+)"', content)]
        scaled = min(sizes) * 1200 / width
        assert scaled >= FIGURE_TYPE_SCALE["small"]

    def test_lists_every_session(self, synthetic_data: Path, tmp_path: Path):
        content = render(synthetic_data, tmp_path)
        for subject in ("848387", "830794", "830846", "830848"):
            assert subject in content

    def test_orders_sessions_by_descending_speed(
        self, synthetic_data: Path, tmp_path: Path
    ):
        content = render(synthetic_data, tmp_path)
        positions = [content.index(s) for s in ("848387", "830794", "830846", "830848")]
        assert positions == sorted(positions)

    def test_marks_unavailable_sessions_distinctly(
        self, synthetic_data: Path, tmp_path: Path
    ):
        content = render(synthetic_data, tmp_path)
        assert AVAILABLE_COLOR in content
        assert UNAVAILABLE_COLOR in content

    def test_uses_a_sequential_ramp_for_the_threshold_grid(
        self, synthetic_data: Path, tmp_path: Path
    ):
        content = render(synthetic_data, tmp_path)
        used = [step for step in SEQUENTIAL_RAMP if step in content]
        assert len(used) >= 3, used

    def test_shows_every_threshold_column(self, synthetic_data: Path, tmp_path: Path):
        content = render(synthetic_data, tmp_path)
        for value in RUNNING_THRESHOLDS_CM_S:
            assert f"≥{value:g}" in content

    def test_labels_every_mismatch_event_type(
        self, synthetic_data: Path, tmp_path: Path
    ):
        content = render(synthetic_data, tmp_path)
        for header in ("halt", "omission", "45°", "90°"):
            assert f">{header}</text>" in content, header

    def test_reports_per_event_type_counts(self, synthetic_data: Path, tmp_path: Path):
        content = render(synthetic_data, tmp_path)
        # 848387 qualifies 137 of 140 at 5 cm/s, so 34 in each of four types.
        assert ">34</text>" in content

    def test_event_types_below_the_minimum_are_marked(
        self, synthetic_data: Path, tmp_path: Path
    ):
        content = render(synthetic_data, tmp_path)
        # The stationary session has zero qualifying trials in every type.
        assert UNAVAILABLE_COLOR in content
        assert MINIMUM_QUALIFYING_TRIALS == 8

    def test_carries_a_legend(self, synthetic_data: Path, tmp_path: Path):
        content = render(synthetic_data, tmp_path)
        assert "minimum" in content.lower()
        assert "not analysable" in content

    def test_canvas_is_the_reference_width(self, synthetic_data: Path, tmp_path: Path):
        content = render(synthetic_data, tmp_path)
        width = float(re.search(r'<svg[^>]+width="([0-9.]+)"', content).group(1))
        assert width == 1200

    def test_empty_sessions_raise(self, tmp_path: Path):
        path = tmp_path / "empty.json"
        path.write_text(json.dumps({"version": 1, "sessions": []}), encoding="utf-8")
        with pytest.raises(RuntimeError, match="no session records"):
            load_running_data(path, tmp_path / "absent.json")

    def test_sessions_without_running_are_skipped(self, tmp_path: Path):
        payload = synthetic_payload()
        payload["sessions"].append(
            {"subject": "999999", "error": "NWB processed running series unavailable"}
        )
        path = tmp_path / "with-error.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        content = render(path, tmp_path)
        assert "999999" not in content


@pytest.mark.skipif(
    not DATA_PATH.exists(), reason="committed locomotion intermediate is absent"
)
class TestCommittedData:
    def test_covers_the_sixteen_sensorimotor_sessions(self):
        payload = load_running_data()
        with_context = [s for s in payload["sessions"] if "context" in s]
        assert len(with_context) == 16

    def test_every_session_has_the_full_trial_count(self):
        payload = load_running_data()
        for record in payload["sessions"]:
            if "context" in record:
                assert record["context"]["mismatch_trials"] == 140, record["subject"]

    def test_the_selected_mouse_clears_the_minimum(self):
        payload = load_running_data()
        key = f"{DEFAULT_RUNNING_THRESHOLD_CM_S:g}"
        selected = next(s for s in payload["sessions"] if s["subject"] == "830794")
        entry = selected["context"]["thresholds"][key]
        assert entry["available"] is True
        assert entry["minimum_per_label"] >= MINIMUM_QUALIFYING_TRIALS

    def test_the_previous_mouse_does_not_clear_the_minimum(self):
        payload = load_running_data()
        key = f"{DEFAULT_RUNNING_THRESHOLD_CM_S:g}"
        previous = next(s for s in payload["sessions"] if s["subject"] == "830846")
        assert previous["context"]["thresholds"][key]["available"] is False

    def test_most_sessions_have_a_stationary_median(self):
        payload = load_running_data()
        assert payload["cohort"]["stationary_median_sessions"] >= 8
