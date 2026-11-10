"""Regression checks for exact, source-backed explorer views."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from openscope_p3_publication import standard_oddball_c1_sensitivity as sensitivity
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
            assert set(r["repeats"]) == {"pooled", "pre", "post"}
            assert r["repeats"]["pooled"]["n"] == r["n"]
            for repeat in r["repeats"].values():
                assert 0 <= repeat["n"] <= repeat["n_eligible"]
                assert all(0 <= n <= repeat["n"] for n in repeat["counts"].values())
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
        assert row["repeats"]["pre"]["n"] > 0
        assert row["repeats"]["post"]["n"] > 0


def test_cohort_rows_keep_repeat_denominators_separate() -> None:
    areas = pd.DataFrame([{
        "brain_area": "VISp", "n_joint_testable": 10, "n_eligible": 12,
        "n_sessions": 2, "n_mice": 2,
        "n_q1_responsive": 5, "n_q2_responsive": 4, "n_joint_responsive": 3,
        "n_joint_pre_testable": 6, "n_q1_responsive_pre": 3,
        "n_q2_responsive_pre": 2, "n_joint_responsive_pre": 2,
        "n_joint_post_testable": 8, "n_q1_responsive_post": 4,
        "n_q2_responsive_post": 3, "n_joint_responsive_post": 2,
        "bootstrap_status": "estimated", "bootstrap_status_pre": "estimated",
        "bootstrap_status_post": "estimated",
        **{
            f"fraction_{screen}_responsive{suffix}_ci95_{bound}": value
            for suffix in ("", "_pre", "_post")
            for screen, value in (("q1", 0.1), ("q2", 0.2), ("joint", 0.3))
            for bound in ("low", "high")
        },
    }])
    mice = pd.DataFrame([{
        "brain_area": "VISp", "subject_id": "mouse-a", "n_joint_testable": 10,
        "n_joint_pre_testable": 6, "n_joint_post_testable": 8,
        "n_q1_responsive": 5, "n_q2_responsive": 4, "n_joint_responsive": 3,
        "n_q1_responsive_pre": 3, "n_q2_responsive_pre": 2,
        "n_joint_responsive_pre": 2, "n_q1_responsive_post": 4,
        "n_q2_responsive_post": 3, "n_joint_responsive_post": 2,
    }])

    row, = explorer.cohort_rows({"areas": areas, "mice": mice}, "orientation_90")

    assert row["n"] == 10 and row["repeats"]["pre"]["n"] == 6
    assert row["repeats"]["post"]["n"] == 8
    assert row["repeats"]["pre"]["counts"] == {"q1": 3, "q2": 2, "joint": 2}
    assert row["repeats"]["pre"]["intervals"]["q2"] == [0.2, 0.2]
    assert row["repeats"]["pre"]["points"][0]["n"] == 6


def test_static_sensitivity_summary_renders_counts_and_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        repeat: {"count": count, "denominator": 10, "interval": interval}
        for repeat, count, interval in (
            ("pooled", 4, [0.2, 0.6]), ("pre", 3, [0.1, 0.5]), ("post", 5, None),
        )
    }
    monkeypatch.setattr(sensitivity, "sensitivity_rows", lambda: [
        sensitivity._record("VISp", values, modality="Neuropixels"),
    ])
    source_dirs = [tmp_path / name for name in ("neuropixels", "mesoscope", "slap2")]
    source_file = tmp_path / "standard_oddball_c1_sensitivity.py"
    source_file.write_text("", encoding="utf-8")
    for source_dir in source_dirs:
        source_dir.mkdir()
        (source_dir / "provenance.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sensitivity, "ROOT", tmp_path)
    monkeypatch.setattr(sensitivity, "__file__", str(source_file))
    monkeypatch.setattr(sensitivity, "NEUROPIXELS_DIR", source_dirs[0])
    monkeypatch.setattr(sensitivity, "MESOSCOPE_DIR", source_dirs[1])
    monkeypatch.setattr(sensitivity, "SLAP2_DIR", source_dirs[2])

    image, provenance = sensitivity.build_c1_sensitivity_figure(
        tmp_path / "sensitivity.svg", tmp_path / "provenance.json",
    )

    assert image.is_file()
    svg = image.read_text(encoding="utf-8")
    assert "90° Q2 sensitivity" in svg
    assert "3/10" in svg and "5/10" in svg
    assert json.loads(provenance.read_text(encoding="utf-8"))["event"] == "orientation_90"
    first_image, first_provenance = image.read_bytes(), provenance.read_bytes()
    sensitivity.build_c1_sensitivity_figure(image, provenance)
    assert first_image == image.read_bytes()
    assert first_provenance == provenance.read_bytes()


def test_deterministic_self_contained_output(
    payload: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(explorer, "load_explorer_data", lambda: payload)
    sensitivity_svg = tmp_path / "sensitivity.svg"
    sensitivity_svg.write_text("<svg/>", encoding="utf-8")
    sensitivity_provenance = tmp_path / "sensitivity.provenance.json"
    sensitivity_provenance.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(explorer, "STATIC_SENSITIVITY", sensitivity_svg)
    monkeypatch.setattr(explorer, "STATIC_SENSITIVITY_PROVENANCE", sensitivity_provenance)
    path = explorer.build_standard_oddball_explorer(tmp_path / "explorer.html")
    before = path.read_bytes(), path.with_suffix(".provenance.json").read_bytes()
    explorer.build_standard_oddball_explorer(path)
    assert before == (path.read_bytes(), path.with_suffix(".provenance.json").read_bytes())
    html = path.read_text(encoding="utf-8")
    for control in (
        "modality-tabs", "event-select", "area-select", "responsiveness-select",
        "metric-select", "sort-select", "source-select", "colorbar-canvas",
        "cohort-control-repeat",
    ):
        assert f'id="{control}"' in html
    assert "data:image/svg+xml;base64," in html
    assert "pooled C1 controls" in html and "pre-context C1 repeat" in html
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
    assert manuscript.count(":name: fig-standard-oddball-c1-sensitivity") == 1
    assert manuscript.count(":label: fig-neuropixels-event-responses") == 1
    assert (
        manuscript.index(":label: fig-standard-oddball-responses")
        < manuscript.index(":name: fig-standard-oddball-c1-sensitivity")
        < manuscript.index(":label: fig-behavior-tracking")
        < manuscript.index("# Supplementary Figure 6:")
        < manuscript.index(":label: fig-neuropixels-event-responses")
    )
    assert "[Figure 9](#fig-standard-oddball-responses)" in manuscript
    assert "standard-oddball-c1-repeat-sensitivity.svg" in manuscript
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
