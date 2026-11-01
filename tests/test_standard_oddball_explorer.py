"""Regression checks for exact, source-backed explorer views."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np
import pytest

from openscope_p3_publication import standard_oddball_explorer as explorer
from openscope_p3_publication.mesoscope_standard_oddball import load_snapshot as load_mesoscope
from openscope_p3_publication.slap2_standard_oddball import load_snapshot as load_slap2
from openscope_p3_publication.standard_oddball_cohort_figure import cohort_plot_data
from openscope_p3_publication.standard_oddball_explorer_window import verify_central


@pytest.fixture(scope="module")
def payload() -> dict:
    return explorer.load_explorer_data()


def test_primary_signals_and_event_coverage(payload: dict) -> None:
    assert [d["id"] for d in payload["datasets"]] == ["neuropixels", "mesoscope", "slap2"]
    assert [d["unit"] for d in payload["datasets"]] == ["Hz", "%", "a.u."]
    assert [len(d["populations"]["orientation_90"]["time"]) for d in payload["datasets"]] == [
        600, 29, 601,
    ]
    for dataset, count in zip(payload["datasets"], (203, 1475, 119), strict=True):
        assert set(dataset["populations"]) == set(explorer.EVENTS)
        for event, p in dataset["populations"].items():
            assert p["event"] == event
            assert p["shape"] == [2, count, len(p["time"])]
            assert sorted(p["order"]) == list(range(count))
            assert len({u["id"] for u in p["units"]}) == count
            assert p["window"] == [-1.5, 1.5]
        population = dataset["populations"]["orientation_90"]
        assert population["event"] == "orientation_90"
        assert population["window"] == [-1.5, 1.5]
        assert population["time"][0] < -1.45 and population["time"][-1] > 1.45
        assert [p["offset"] for p in population["presentations"]] == [-2, -1, 0, 1, 2]
        assert population["shape"] == [2, count, len(population["time"])]
        assert sorted(population["order"]) == list(range(count))
        assert len({u["id"] for u in population["units"]}) == count
        assert {r["event"] for r in dataset["cohort"]} == set(explorer.EVENTS)
        for r in dataset["cohort"]:
            assert 0 < r["n"] <= r["n_eligible"]
            assert 0 <= r["counts"]["joint"] <= min(r["counts"]["q1"], r["counts"]["q2"])
            assert all(0 <= n <= r["n"] for n in r["counts"].values())
    assert {r["group"] for r in payload["datasets"][2]["cohort"]} == {"DMD1", "DMD2"}
    json.dumps(payload, allow_nan=False)


def test_unchanged_optical_samples_and_actual_stimulus_spans(payload: dict) -> None:
    for dataset, loader, key in (
        (payload["datasets"][1], load_mesoscope, "delta_dff"),
        (payload["datasets"][2], load_slap2, "delta_glutamate"),
    ):
        source, _, arrays = loader()
        population = dataset["populations"]["orientation_90"]
        decoded = np.frombuffer(base64.b64decode(population["values"]), dtype="<f8").reshape(
            population["shape"]
        )
        verify_central(np.asarray(population["time"]), decoded, arrays["time"], arrays[key])
        if dataset["id"] == "slap2":
            groups = [population["units"][i]["group"] for i in population["order"]]
            assert groups == ["DMD1"] * 79 + ["DMD2"] * 40
            assert population["spans"] == [
                source["stimulus_spans"][k] for k in ("comparison", "response")
            ]
            assert population["recorded_trial_count_ranges"]["context"] == [24, 28]
    meso_span = payload["datasets"][1]["populations"]["orientation_90"]["spans"][1]
    assert 0.36 < meso_span[1] < 0.38
    assert meso_span[1] != 0.367


def test_exact_published_cohort_counts_and_uncertainty(payload: dict) -> None:
    published = cohort_plot_data()["areas"].set_index("brain_area")
    for row in payload["datasets"][0]["cohort"]:
        if row["event"] != "orientation_90":
            continue
        reference = published.loc[row["group"]]
        assert row["n"] == reference.n_joint_testable
        for screen in explorer.SCREENS:
            assert row["counts"][screen] == reference[f"n_{screen}_responsive"]
            assert row["intervals"][screen] == [
                reference[f"fraction_{screen}_responsive_ci95_{b}"] for b in ("low", "high")
            ]
    slap_rows = {
        r["group"]: r for r in payload["datasets"][2]["cohort"] if r["event"] == "orientation_90"
    }
    assert slap_rows["DMD1"]["n"] == 110
    assert slap_rows["DMD1"]["counts"] == {"q1": 29, "q2": 19, "joint": 10}
    assert slap_rows["DMD2"]["n"] == 85
    assert slap_rows["DMD2"]["counts"] == {"q1": 18, "q2": 10, "joint": 4}
    for row in slap_rows.values():
        assert row["n_sessions"] == row["n_mice"] == len(row["points"]) == 2
        assert all(interval is None for interval in row["intervals"].values())


def test_deterministic_self_contained_output(
    payload: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(explorer, "load_explorer_data", lambda: payload)
    path = explorer.build_standard_oddball_explorer(tmp_path / "explorer.html")
    before = path.read_bytes(), path.with_suffix(".provenance.json").read_bytes()
    explorer.build_standard_oddball_explorer(path)
    assert before == (path.read_bytes(), path.with_suffix(".provenance.json").read_bytes())
    html = path.read_text(encoding="utf-8")
    for control in (
        "modality-tabs", "event-select", "area-select", "responsiveness-select",
        "metric-select", "sort-select", "source-select", "colorbar-canvas",
    ):
        assert f'id="{control}"' in html
    assert "data:image/svg+xml;base64," in html
    assert "data-simple-view" in html and "legend-toggle" in html
    for removed in (
        "selection-status", "dataset-notes", "color-key", "cohort-table",
        "cohort-caption", "cohort-notes", "mouse-points", "screen-rule", "trace-note",
    ):
        assert f'id="{removed}"' not in html
    assert "Click a heatmap row to inspect its source." not in html
    assert "table below" not in html
    for label in ("Δ Firing rate (spikes/s)", "Δ F/F", "Δ Glu change"):
        assert json.dumps(label) in html
    assert "ArrowUp" in html and "aria-live" in html
    assert "fetch(" not in html
    assert "__DATA__" not in html and "__STATIC__" not in html
    provenance = json.loads(path.with_suffix(".provenance.json").read_text())
    assert provenance["population_events"] == list(explorer.EVENTS)
    assert provenance["output_sha256"] == explorer.sha256(path)


def test_manuscript_figure9_and_supplement6_are_distinct() -> None:
    manuscript = (explorer.ROOT / "index.md").read_text(encoding="utf-8")
    assert manuscript.count(":label: fig-standard-oddball-responses") == 1
    assert manuscript.count(":label: fig-neuropixels-event-responses") == 1
    assert (
        manuscript.index(":label: fig-standard-oddball-responses")
        < manuscript.index(":label: fig-behavior-tracking")
        < manuscript.index("# Supplementary Figure 6:")
        < manuscript.index(":label: fig-neuropixels-event-responses")
    )
    assert "[Figure 9](#fig-standard-oddball-responses)" in manuscript
    assert "[Supplementary Figure 6](#fig-neuropixels-event-responses)" in manuscript


def test_event_specific_source_statistics_and_fixed_orders(payload: dict) -> None:
    import pandas as pd

    frames = {
        "neuropixels": explorer.load_example_statistics("neuropixels"),
        "mesoscope": explorer.load_example_statistics("mesoscope"),
        "slap2": load_slap2()[1],
    }
    for dataset in payload["datasets"]:
        frame = frames[dataset["id"]]
        if "session_id" in frame:
            frame = frame.loc[frame.session_id.eq(dataset["session"])]
        if "signal" in frame:
            signal = "dff" if dataset["id"] == "mesoscope" else "glutamate"
            frame = frame.loc[frame.signal.eq(signal)]
        reference_order = dataset["populations"]["orientation_90"]["order"]
        for event, population in dataset["populations"].items():
            rows = frame.loc[frame.event_id.eq(event)].set_index(
                "roi_key" if dataset["id"] == "slap2" else "id"
            )
            assert population["order"] == reference_order
            for unit in population["units"]:
                key = unit["id"]
                row = rows.loc[key]
                for flag in ("q1_responsive", "q2_responsive", "joint_responsive",
                             "positive_joint", "q2_nonsignificant"):
                    assert unit[flag] == bool(row[flag])
                for stat in ("q1_p", "q1_mi", "q2_p", "q2_mi"):
                    if pd.isna(row[stat]):
                        assert unit[stat] is None
                    else:
                        assert unit[stat] == pytest.approx(row[stat], rel=2e-15, abs=1e-14)
