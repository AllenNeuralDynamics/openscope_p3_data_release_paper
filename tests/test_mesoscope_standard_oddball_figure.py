"""Matched optical columns: identities, native statistics, actual artists and offline products."""

import hashlib
import json
import shutil
from copy import deepcopy
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd
import pytest
from matplotlib.text import Text

from openscope_p3_publication import mesoscope_standard_oddball as meso
from openscope_p3_publication import mesoscope_standard_oddball_figure as column
from openscope_p3_publication.mesoscope_standard_oddball_display import (
    context_dff_peaks,
    select_display_examples,
)
from openscope_p3_publication.mismatch_responsiveness import benjamini_hochberg


@pytest.fixture(scope="module")
def snapshot():
    return meso.load_snapshot()


@pytest.fixture(scope="module")
def display_snapshot(snapshot):
    payload, statistics, arrays = snapshot
    prepared, arrays = column.load_display_snapshot(payload, statistics, arrays)
    return prepared, statistics, arrays


@pytest.fixture(scope="module")
def rendered(tmp_path_factory, snapshot):
    directory = tmp_path_factory.mktemp("mesoscope-columns")
    paths = column.build_mesoscope_standard_oddball(directory / "svg", directory / "audit")
    return directory, paths


def test_snapshot_contains_original_and_eligible_roi_identities(snapshot):
    payload, stats, arrays = snapshot
    assert payload["session_id"] == meso.SESSION_ID
    assert payload["original_roi_count"] == 2371
    assert len(payload["roi_keys"]) == 1475
    assert len(stats) == 4742
    assert stats.groupby("signal").size().to_dict() == {"dff": 2371, "oasis": 2371}
    for signal in meso.SIGNALS:
        rows = stats.loc[stats.signal.eq(signal)]
        expected = rows.is_soma & rows.quality_class.isin(["High SNR", "Intermediate"])
        np.testing.assert_array_equal(rows.eligible, expected)
        assert rows.loc[expected, "roi_key"].tolist() == payload["roi_keys"]
        assert arrays[f"delta_{signal}"].shape == (2, 1475, len(arrays["time"]))
    assert sorted(payload["order"]) == list(range(1475))
    assert payload["rastermap"]["parameters"]["n_PCs"] == len(arrays["time"]) - 1
    assert payload["rastermap"]["parameters"]["random_state"] == 0
    assert payload["rastermap"]["version"] == "1.0"


def test_native_trial_windows_and_recorded_calibration(snapshot):
    payload, _, arrays = snapshot
    assert len(payload["trials"]["context"]) == 34
    assert len(payload["trials"]["control"]) == 68
    assert len(payload["trials"]["excluded"]["context"]) == 1
    assert payload["response_seconds"] == 0.5
    for plane in payload["planes"]:
        assert plane["signals"]["dff"]["unit"] == "%"
        assert plane["signals"]["oasis"]["unit"] == "a.u."
        assert 0.1054 < plane["dt_seconds"] < 0.1055
        for signal in meso.SIGNALS:
            ranges = plane["signals"][signal]["native_frame_count_range"]
            assert ranges["context_test"][0] >= 4
            assert ranges["context_comparison"][0] >= 4
    assert len(arrays["time"]) == 15
    np.testing.assert_allclose(np.diff(arrays["time"]), payload["planes"][0]["dt_seconds"])


def test_classification_is_strict_signed_and_bh_uses_all_original_rois(snapshot):
    _, stats, _ = snapshot
    for signal in meso.SIGNALS:
        rows = stats.loc[stats.signal.eq(signal)]
        for screen in ("q1", "q2"):
            p, mi = rows[f"{screen}_p"], rows[f"{screen}_mi"]
            valid = np.isfinite(p) & np.isfinite(mi)
            np.testing.assert_array_equal(rows[f"{screen}_testable"], valid)
            np.testing.assert_array_equal(
                rows[f"{screen}_responsive"], valid & (p < 0.05) & (mi.abs() > 0.1),
            )
            np.testing.assert_allclose(
                rows[f"{screen}_q"], benjamini_hochberg(p), rtol=0, atol=1e-15, equal_nan=True,
            )
        np.testing.assert_array_equal(
            rows.positive_joint,
            rows.q1_responsive & rows.q2_responsive & rows.q1_mi.gt(0.1) & rows.q2_mi.gt(0.1),
        )
        assert rows.q1_trials.eq(34).all()
        assert rows.q2_context_trials.eq(34).all()
        assert rows.q2_control_trials.eq(68).all()


def test_examples_pass_their_rules_in_both_signals(snapshot):
    payload, stats, _ = snapshot
    assert payload["example_roi_keys"] == meso.matched_examples(stats, payload["roi_keys"])
    positive = stats.loc[stats.roi_key.eq(payload["example_roi_keys"][0])]
    comparison = stats.loc[stats.roi_key.eq(payload["example_roi_keys"][1])]
    assert len(positive) == len(comparison) == 2
    assert positive.positive_joint.all()
    assert comparison.q2_nonsignificant.all()
    assert comparison.q2_mi.abs().lt(0.25).all()


def test_population_curves_have_exact_signal_specific_membership_and_neuron_sem(snapshot):
    payload, stats, arrays = snapshot
    for signal in meso.SIGNALS:
        result = column.cohort_curves(stats, arrays, signal, payload["roi_keys"])
        rows = stats.loc[stats.signal.eq(signal)].set_index("roi_key").loc[payload["roi_keys"]]
        for group, field in (("positive", "positive_joint"), ("nonq2", "q2_nonsignificant")):
            mask = rows[field].to_numpy()
            values = arrays[f"delta_{signal}"][:, mask].astype(np.float64)
            np.testing.assert_array_equal(result[group]["mask"], mask)
            np.testing.assert_array_equal(result[group]["mean"], values.mean(axis=1))
            np.testing.assert_array_equal(
                result[group]["sem"], values.std(axis=1, ddof=1) / np.sqrt(mask.sum()),
            )
        assert result["positive"]["count"] == (225 if signal == "dff" else 145)
        assert result["nonq2"]["count"] == (1002 if signal == "dff" else 1180)


def test_missing_population_is_explicit_error(snapshot):
    payload, stats, arrays = snapshot
    changed = stats.copy()
    changed["positive_joint"] = False
    with pytest.raises(ValueError, match="at least two eligible ROIs"):
        column.cohort_curves(changed, arrays, "dff", payload["roi_keys"])


def test_actual_artists_use_display_order_matching_trials_and_uncertainty(
    tmp_path, display_snapshot, monkeypatch,
):
    payload, stats, arrays = display_snapshot
    cohort = column.cohort_plot_data()
    original = column.save_diagnostic_svg
    seen = []

    def capture(fig, *args, **kwargs):
        axes = {a.get_gid(): a for a in fig.axes}
        signal = args[3]["data-signal"]
        image = axes["population-heatmap-context"].images[0]
        np.testing.assert_array_equal(
            image.get_array(),
            arrays[f"delta_{signal}"][0, column.population_order(payload, signal)],
        )
        np.testing.assert_array_equal(
            axes["example-trial-heatmap-0"].images[0].get_array(),
            arrays[f"examples_{signal}_context"][0],
        )
        np.testing.assert_array_equal(
            axes["example-trial-mean-0"].lines[-2].get_ydata(),
            arrays[f"examples_{signal}_context"][0].astype(np.float64).mean(axis=0),
        )
        curves = column.cohort_curves(stats, arrays, signal, payload["roi_keys"])
        lines = {line.get_gid(): line for line in axes["population-mean-overlay"].lines}
        bands = {band.get_gid(): band for band in axes["population-mean-overlay"].collections}
        for group, style in (("positive", "-"), ("nonq2", ":")):
            for c, condition in enumerate(("context", "control")):
                line = lines[f"population-{group}-{condition}"]
                np.testing.assert_array_equal(line.get_ydata(), curves[group]["mean"][c])
                assert line.get_linestyle() == style
                vertices = bands[f"population-sem-{group}-{condition}"].get_paths()[0].vertices
                for j, t in enumerate(arrays["time"]):
                    at_time = vertices[vertices[:, 0] == t, 1]
                    mean, sem = curves[group]["mean"][c, j], curves[group]["sem"][c, j]
                    np.testing.assert_allclose(
                        [at_time.min(), at_time.max()], [mean - sem, mean + sem],
                    )
        assert len(fig.axes) == 8  # platform icon, four example axes, B heatmap/mean, cohort C
        for gid, top, height_mm in (
            ("example-trial-heatmap-0", 10.8, 18),
            ("example-trial-mean-0", 30.96, 18),
            ("population-heatmap-context", 58.5, 38.7),
            ("population-mean-overlay", 99.36, 25.2),
        ):
            bounds = axes[gid].get_position()
            assert (1 - bounds.y1) * column.HEIGHT_MM == pytest.approx(top)
            assert bounds.height * column.HEIGHT_MM == pytest.approx(height_mm)
        expected_areas = column.signal_panel(cohort, signal)["areas"]
        bars = {bar.get_gid(): bar for bar in axes["cohort-responsiveness-proportions"].patches}
        for row in expected_areas.itertuples():
            for screen in ("q1", "q2", "joint"):
                assert bars[f"cohort-pooled-{screen}-{row.brain_area}"].get_height() == (
                    100 * getattr(row, f"fraction_{screen}_responsive")
                )
        assert axes["example-trial-mean-0"].get_ylim() == (
            axes["example-trial-mean-1"].get_ylim()
        )
        for gid in ("example-trial-mean-0", "example-trial-mean-1", "population-mean-overlay"):
            ax = axes[gid]
            assert ax.get_xlim() == meso.WINDOW
            patches = {patch.get_gid(): patch for patch in ax.patches}
            for name, window in (
                ("preceding", "comparison"), ("oddball", "response"),
            ):
                patch = patches[f"{gid}-{name}-stimulus-shading"]
                actual = [patch.get_x(), patch.get_x() + patch.get_width()]
                np.testing.assert_array_equal(actual, payload["stimulus_spans"][window])
                assert 0.366 < patch.get_width() < 0.368
        assert axes["population-heatmap-context"].get_ylabel() == "Rastermap rank"
        assert not any(
            (line.get_gid() or "").startswith("population-plane-boundary-")
            for line in axes["population-heatmap-context"].lines
        )
        response = (arrays["time"] >= 0) & (arrays["time"] < 0.5)
        plotted = axes["example-trial-mean-0"].lines[-2].get_ydata()
        if signal == "dff":
            assert plotted[response].max() > 0.5
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        width, height = fig.bbox.width, fig.bbox.height
        for text in fig.findobj(Text):
            if not text.get_visible() or not text.get_text():
                continue
            bbox = text.get_window_extent(renderer)
            assert bbox.x0 >= 0 and bbox.x1 <= width, text.get_text()
            assert bbox.y0 >= 0 and bbox.y1 <= height, text.get_text()
        seen.append(signal)
        return original(fig, *args, **kwargs)

    monkeypatch.setattr(column, "save_diagnostic_svg", capture)
    column.build_mesoscope_standard_oddball(tmp_path / "svg", tmp_path / "audit")
    assert seen == ["dff", "oasis"]


def test_frozen_hashes_and_identity_tampering_are_rejected(tmp_path, snapshot):
    payload = deepcopy(snapshot[0])
    for path in meso.SNAPSHOT.iterdir():
        shutil.copyfile(path, tmp_path / path.name)
    payload["session_id"] = "wrong_session"
    provenance = tmp_path / "provenance.json"
    provenance.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="Unsupported mesoscope"):
        meso.load_snapshot(tmp_path)
    payload["session_id"] = meso.SESSION_ID
    payload["sources"][0]["sha256"] = "changed"
    provenance.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="source changed"):
        meso.load_snapshot(tmp_path)
    payload = deepcopy(snapshot[0])
    payload["outputs"][0]["sha256"] = "changed"
    provenance.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="snapshot checksum"):
        meso.load_snapshot(tmp_path)


def test_products_are_deterministic_editable_and_scientifically_labelled(rendered, tmp_path):
    _, paths = rendered
    repeated = column.build_mesoscope_standard_oddball(tmp_path / "svg", tmp_path / "audit")
    assert [p.read_bytes() for p in paths] == [p.read_bytes() for p in repeated]
    ns = {"s": "http://www.w3.org/2000/svg"}
    for path in paths[:2]:
        root = ET.parse(path).getroot()
        assert float(root.attrib["width"].removesuffix("pt")) * 25.4 / 72 == pytest.approx(54)
        assert float(root.attrib["height"].removesuffix("pt")) * 25.4 / 72 == pytest.approx(174)
        assert root.attrib["data-session-count"] == "1"
        assert root.attrib["data-cohort-session-count"] == "20"
        assert root.attrib["data-cohort-mouse-count"] == "10"
        assert root.attrib["data-cohort-denominator"] == "signal-specific-eligible-joint-testable"
        assert root.attrib["data-eligible-roi-count"] == "1475"
        assert root.attrib["data-population-ordering"] == "context-dff-rastermap"
        assert root.attrib["data-rastermap-fit-signal"] == "dff"
        assert 0.366 < float(root.attrib["data-stimulus-window-seconds"]) < 0.368
        assert root.attrib["data-response-window-seconds"] == "0.5"
        assert root.attrib["data-example-roi-keys"] == "VISl_6:64,VISp_1:52"
        assert float(root.attrib["data-panel-a-dff-peak-threshold"]) == 0.5
        assert float(root.attrib["data-panel-a-responsive-dff-peak"]) > 0.5
        assert root.attrib["data-native-unit"] == ("%" if "dff" in path.stem else "a.u.")
        assert root.findall(".//s:text", ns)
        description = root.find("s:desc", ns).text
        assert "display-only" in description and "descriptive" in description
        assert "C: 90-degree cohort across 20 sessions" in description
        assert "resample whole mice" in description
        assert len(root.findall(".//s:g[@id='cohort-responsiveness-proportions']", ns)) == 1
        for text in root.findall(".//s:text", ns):
            assert "Arial" in text.attrib.get("style", "")
        assert len(root.findall(".//s:g[@id='platform-logo-mesoscope']", ns)) == 1
    audit = pd.read_csv(paths[2])
    assert len(audit) == 4742
    assert audit.rastermap_rank.notna().sum() == 2950
    assert audit.dff_display_rank.notna().sum() == 2950
    assert audit.oasis_display_rank.notna().sum() == 2950
    assert audit.depth_um.notna().all()
    np.testing.assert_equal(audit.dff_display_rank.to_numpy(), audit.rastermap_rank.to_numpy())
    np.testing.assert_equal(audit.oasis_display_rank.to_numpy(), audit.rastermap_rank.to_numpy())
    assert audit.panel_a_dff_peak.notna().sum() == 2950
    assert audit.example.sum() == 4
    provenance = json.loads(paths[3].read_text())
    for source in provenance["sources"]:
        assert meso.sha256(meso.ROOT / source["path"]) == source["sha256"]
    for output, path in zip(provenance["outputs"], paths[:3], strict=True):
        assert hashlib.sha256(path.read_bytes()).hexdigest() == output["sha256"]


def test_build_and_static_packaging_are_wired():
    source = (meso.ROOT / "src/openscope_p3_publication/figures.py").read_text(encoding="utf-8")
    assert "mesoscope_oddball_paths = build_mesoscope_standard_oddball(primary_only=True)" in source
    assert meso.SNAPSHOT.relative_to(meso.ROOT).as_posix() in (
        meso.ROOT / "myst.yml"
    ).read_text(encoding="utf-8")
    assert "figure_sources/data/standard-oddball-publication" in (
        meso.ROOT / "myst.yml"
    ).read_text()


def test_replacement_is_shared_and_original_arrays_are_untouched(snapshot, display_snapshot):
    original, stats, arrays = snapshot
    prepared, _, displayed = display_snapshot
    assert original["example_roi_keys"] == ["VISp_1:319", "VISp_1:52"]
    assert prepared["example_roi_keys"] == ["VISl_6:64", "VISp_1:52"]
    expected = select_display_examples(original, stats, arrays)
    assert prepared["example_roi_keys"] == expected
    for signal in meso.SIGNALS:
        rows = stats.loc[stats.signal.eq(signal)].set_index("roi_key")
        assert rows.loc[prepared["example_roi_keys"][0], "positive_joint"]
        np.testing.assert_array_equal(displayed[f"delta_{signal}"], arrays[f"delta_{signal}"])
        for condition in ("context", "control"):
            key = f"examples_{signal}_{condition}"
            np.testing.assert_array_equal(displayed[key][1], arrays[key][1])
            assert not np.array_equal(displayed[key][0], arrays[key][0])


def test_identical_frozen_rastermap_order_in_both_variants(display_snapshot):
    payload, _, _ = display_snapshot
    assert column.population_order(payload, "dff") == payload["order"]
    assert column.population_order(payload, "oasis") == payload["order"]
    assert sorted(column.population_order(payload, "dff")) == list(range(1475))
    with pytest.raises(ValueError, match="Unknown mesoscope signal"):
        column.population_order(payload, "unknown")


def test_panel_a_gate_has_twenty_shared_candidates_and_the_plotted_peak_passes(display_snapshot):
    payload, stats, arrays = display_snapshot
    rows = [
        stats.loc[stats.signal.eq(s)].set_index("roi_key").loc[payload["roi_keys"]]
        for s in ("dff", "oasis")
    ]
    candidates = rows[0].positive_joint & rows[1].positive_joint & (context_dff_peaks(arrays) > 0.5)
    assert candidates.sum() == 20
    trace = arrays["examples_dff_context"][0].mean(axis=0)
    response = (arrays["time"] >= 0) & (arrays["time"] < 0.5)
    assert trace[response].max() > 0.5
    assert trace[response].max() == pytest.approx(0.91555202, abs=1e-7)
    assert payload["panel_a_dff_peak_threshold"] == 0.5


@pytest.mark.parametrize(
    "mutation,error", [
        ("session", "Unsupported"), ("source", "source changed"), ("output", "checksum"),
        ("example", "example selection"), ("duration", "actual duration"),
        ("depth", "area/depth"), ("comparison", "Preceding stimulus"),
    ],
)
def test_display_supplement_rejects_stale_or_inconsistent_inputs(
    tmp_path, snapshot, mutation, error,
):
    payload, stats, arrays = snapshot
    path = meso.SNAPSHOT / "display-provenance.json"
    data = json.loads(path.read_text())
    shutil.copyfile(meso.SNAPSHOT / data["output"]["path"], tmp_path / data["output"]["path"])
    if mutation == "session":
        data["session_id"] = "wrong_session"
    elif mutation == "source":
        data["sources"][0]["sha256"] = "changed"
    elif mutation == "output":
        data["output"]["sha256"] = "changed"
    elif mutation == "example":
        data["example_roi_keys"] = payload["example_roi_keys"]
    elif mutation == "duration":
        row = data["trials"]["context"][0]
        row["stop_time"] = row["start_time"] + 0.5
    elif mutation == "depth":
        data["planes"][0]["depth_um"] += 1
    else:
        row = data["trials"]["context"][0]
        row["comparison_stop_time"] = row["comparison_start_time"]
    (tmp_path / path.name).write_text(json.dumps(data))
    with pytest.raises(ValueError, match=error):
        column.load_display_snapshot(payload, stats, arrays, tmp_path)


@pytest.mark.parametrize("mutation", ["replacement_mean", "comparison", "missing_array"])
def test_replacement_arrays_must_match_frozen_means_and_comparison(tmp_path, snapshot, mutation):
    payload, stats, arrays = snapshot
    data = json.loads((meso.SNAPSHOT / "display-provenance.json").read_text())
    with np.load(meso.SNAPSHOT / data["output"]["path"], allow_pickle=False) as archive:
        replacement = {key: archive[key] for key in archive.files}
    if mutation == "missing_array":
        replacement.pop("examples_dff_context")
    else:
        replacement["examples_dff_context"][0 if mutation == "replacement_mean" else 1, 0, 0] += 1
    path = tmp_path / data["output"]["path"]
    np.savez_compressed(path, **replacement)
    data["output"]["sha256"] = meso.sha256(path)
    (tmp_path / "display-provenance.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Replacement"):
        column.load_display_snapshot(payload, stats, arrays, tmp_path)
