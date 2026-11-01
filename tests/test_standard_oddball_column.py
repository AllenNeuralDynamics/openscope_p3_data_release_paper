"""Clean population reconstruction and the final-size, single-modality column."""

import base64
import csv
import hashlib
import io
import json
import re
from copy import deepcopy
from xml.etree import ElementTree as ET

import numpy as np
import pytest
from matplotlib.collections import LineCollection
from matplotlib.text import Text
from PIL import Image

from openscope_p3_publication import standard_oddball_column as column
from openscope_p3_publication.figure_typography import normalize_figure_svg
from openscope_p3_publication.standard_oddball_cohort_figure import SCREENS, cohort_plot_data
from openscope_p3_publication.standard_oddball_examples import load_example_spikes, trial_mean_sdf
from openscope_p3_publication.standard_oddball_neuropixels import (
    REPO_ROOT,
    joint_example_mask,
    load_diagnostic,
    visual_group,
)
from openscope_p3_publication.standard_oddball_ordering import (
    ORDER_PATH,
    context_matrix,
    load_context_order,
    ordered_heatmaps,
    validate_context_order,
)
from openscope_p3_publication.standard_oddball_population import (
    BIN_SECONDS,
    EVENT_ID,
    POPULATION_PATH,
    POPULATION_PROVENANCE,
    TAU_SECONDS,
    load_population,
    population_arrays,
    summarize_spike_trials,
    validate_population,
)


@pytest.fixture(scope="module")
def data():
    return load_diagnostic()


@pytest.fixture(scope="module")
def examples(data):
    return load_example_spikes(data)


@pytest.fixture(scope="module")
def population(data, examples):
    return load_population(data, examples["events"][1])


def test_summary_uses_full_released_baseline_bins_and_retains_empty_trials():
    result = summarize_spike_trials(
        [[-0.334, -0.32, -0.02, -0.01, 0.001], []],
        [{"baseline_window": [-0.33361, 0]}] * 2,
    )
    assert result["baseline_mean_hz"] == 2 / (2 * 16 * 0.02)
    np.testing.assert_array_equal(
        result["mean_hz"],
        trial_mean_sdf(
            [[-0.334, -0.32, -0.02, -0.01, 0.001], []],
            bin_seconds=BIN_SECONDS, tau_seconds=TAU_SECONDS,
        ),
    )


@pytest.mark.parametrize("window", [None, [0, 0], [-1.1, 0], [0, float("nan")], [-0.01, 0]])
def test_summary_rejects_missing_or_invalid_baselines(window):
    with pytest.raises(ValueError, match="baseline"):
        summarize_spike_trials([[]], [{"baseline_window": window}])
    with pytest.raises(ValueError, match="alignment"):
        summarize_spike_trials([], [{"baseline_window": [-0.2, 0]}])


def test_population_has_every_eligible_visual_unit_and_exact_clean_trials(
    data, examples, population,
):
    assert population["event"] == examples["events"][1]
    assert population["event"]["id"] == EVENT_ID
    records = population["event"]["conditions"]
    assert len(records["context"]["trials"]) == 34
    assert len(records["context"]["excluded_rows"]) == 1
    assert len(records["control"]["trials"]) == 68
    assert [u["id"] for u in population["units"]] == [u["id"] for u in data.units]
    assert len(population["units"]) == 203
    rates, baselines = population_arrays(population)
    assert rates.shape == (2, 203, 300)
    assert baselines.shape == (2, 203)
    np.testing.assert_allclose(baselines[1], data.baseline_mean[1, 1], atol=1e-5, rtol=1e-6)


def test_clean_population_matches_all_six_raw_spike_examples_exactly(data, examples, population):
    by_id = {unit["id"]: unit for unit in population["units"]}
    trials = population["event"]["conditions"]
    for example in examples["units"]:
        unit = by_id[example["id"]]
        assert unit["source_spike_array_sha256"] == example["source_spike_array_sha256"]
        for condition in ("context", "control"):
            expected = summarize_spike_trials(
                example["spikes"][EVENT_ID][condition], trials[condition]["trials"],
            )
            assert unit["conditions"][condition] == expected


@pytest.mark.parametrize("mutation", ["unit", "trials", "tau", "rate", "baseline", "shape"])
def test_population_rejects_incomplete_or_corrupt_data(data, examples, population, mutation):
    changed = deepcopy(population)
    if mutation == "unit":
        changed["units"].pop()
    elif mutation == "trials":
        changed["event"]["conditions"]["context"]["trials"].pop()
    elif mutation == "tau":
        changed["parameters"]["tau_seconds"] = 0.020
    elif mutation == "rate":
        changed["units"][0]["conditions"]["context"]["mean_hz"][0] = float("nan")
    elif mutation == "baseline":
        changed["units"][0]["conditions"]["control"]["baseline_mean_hz"] = -1
    else:
        changed["units"][0]["conditions"]["context"]["mean_hz"].pop()
    with pytest.raises(ValueError):
        validate_population(changed, data, examples["events"][1])


def test_population_checksum_and_changed_sources_are_rejected(tmp_path, data, examples):
    path, provenance = tmp_path / "population.json", tmp_path / "provenance.json"
    path.write_text("{}")
    original = json.loads(POPULATION_PROVENANCE.read_text())
    provenance.write_text(json.dumps(original))
    with pytest.raises(ValueError, match="checksum"):
        load_population(data, examples["events"][1], path, provenance)
    original["output_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    original["sources"][0]["sha256"] = "changed"
    provenance.write_text(json.dumps(original))
    with pytest.raises(ValueError, match="source changed"):
        load_population(data, examples["events"][1], path, provenance)
    assert POPULATION_PATH.stat().st_size < 5_000_000


def test_population_mean_pools_only_positive_joint_responders(
    data, examples, population,
):
    prepared = column.column_data(data, population, examples)
    assert np.sum(prepared["groups"] == 0) == 145
    assert np.sum(prepared["groups"] == 1) == 58
    expected_mask = np.ones(203, dtype=bool)
    for test in ("q1", "q2_delta"):
        p = data.statistics[f"{test}_p"][1]
        mi = data.statistics[f"{test}_modulation"][1]
        expected_mask &= np.isfinite(p) & np.isfinite(mi) & (p < 0.05) & (mi > 0.1)
    np.testing.assert_array_equal(prepared["positive_mask"], expected_mask)
    assert expected_mask.sum() == 37
    assert all(np.any(expected_mask & (prepared["groups"] == group)) for group in (0, 1))
    delta = prepared["delta"]
    selected = delta[:, expected_mask]
    expected = selected.mean(axis=1)
    np.testing.assert_allclose(prepared["positive_mean"], expected, atol=1e-14)
    centered_sum_squares = ((selected - expected[:, None]) ** 2).sum(axis=1)
    n = expected_mask.sum()
    expected_sem = np.sqrt(centered_sum_squares / (n * (n - 1)))
    np.testing.assert_allclose(prepared["positive_sem"], expected_sem, atol=1e-14)
    assert prepared["positive_sem"].shape == (2, 300)
    assert np.all(np.isfinite(prepared["positive_sem"]))
    assert np.all(prepared["positive_sem"] >= 0)
    np.testing.assert_array_equal(
        prepared["delta"], prepared["rates"] - prepared["baselines"][..., None],
    )


@pytest.mark.parametrize(("statistic", "value", "included"), [
    ("q1_modulation", 0.2, True),
    ("q1_modulation", -0.2, False),
    ("q2_delta_modulation", -0.2, False),
    ("q1_modulation", 0.1, False),
    ("q2_delta_modulation", 0.1, False),
    ("q1_p", 0.05, False),
    ("q2_delta_p", 0.05, False),
    ("q1_p", float("nan"), False),
    ("q2_delta_p", float("inf"), False),
    ("q1_modulation", float("inf"), False),
    ("q2_delta_modulation", float("nan"), False),
])
def test_positive_selection_checks_both_signs_thresholds_and_finiteness(
    data, population, examples, statistic, value, included,
):
    changed = deepcopy(data)
    for test in ("q1", "q2_delta"):
        changed.statistics[f"{test}_p"][1, 0] = 0.01
        changed.statistics[f"{test}_modulation"][1, 0] = 0.2
        changed.statistics[f"{test}_q"][1, 0] = float("nan")
    changed.statistics[statistic][1, 0] = value
    prepared = column.column_data(changed, population, examples)
    assert bool(prepared["positive_mask"][0]) is included


def test_positive_mean_rejects_empty_selection(data, population, examples):
    changed = deepcopy(data)
    changed.statistics["q1_modulation"][1] = -0.2
    with pytest.raises(ValueError, match="No visual units pass the positive"):
        column.column_data(changed, population, examples)


def test_across_neuron_sem_rejects_a_single_responder(data, population, examples):
    changed = deepcopy(data)
    changed.statistics["q1_modulation"][1] = -0.2
    i = next(i for i, unit in enumerate(data.units) if unit["id"] == 964)
    changed.statistics["q1_modulation"][1, i] = 0.2
    with pytest.raises(ValueError, match="At least two positive responders"):
        column.column_data(changed, population, examples)


@pytest.mark.parametrize(("q1_sign", "q2_sign", "counts"), [
    (1, 1, [37, 30, 7]),
    (1, -1, [1, 1, 0]),
    (-1, 1, [12, 5, 7]),
    (-1, -1, [5, 2, 3]),
])
def test_joint_responder_modulation_sign_subpopulations(data, q1_sign, q2_sign, counts):
    mask = (
        joint_example_mask(data)[1]
        & (q1_sign * data.statistics["q1_modulation"][1] > 0.1)
        & (q2_sign * data.statistics["q2_delta_modulation"][1] > 0.1)
    )
    groups = np.array([visual_group(unit) for unit in data.units])
    assert [mask.sum(), (mask & (groups == 0)).sum(), (mask & (groups == 1)).sum()] == counts


def test_context_order_is_complete_and_independent_of_control(population):
    order = load_context_order(population)
    assert sorted(order.tolist()) == list(range(203))
    assert not np.array_equal(order, np.arange(203))
    changed = deepcopy(population)
    for unit in changed["units"]:
        unit["conditions"]["control"]["mean_hz"] = [999.0] * 300
        unit["conditions"]["control"]["baseline_mean_hz"] = 100
    np.testing.assert_array_equal(context_matrix(changed), context_matrix(population))
    np.testing.assert_array_equal(load_context_order(changed), order)
    changed["units"][0]["conditions"]["context"]["mean_hz"][0] += 1
    with pytest.raises(ValueError, match="input"):
        load_context_order(changed)


@pytest.mark.parametrize("mutation", [
    "duplicate", "mapping", "control-fit", "parameters", "digest",
])
def test_ordering_rejects_corrupted_or_incompatible_fit(population, mutation):
    payload = json.loads(ORDER_PATH.read_text())
    if mutation == "duplicate":
        payload["isort"][0] = payload["isort"][1]
    elif mutation == "mapping":
        payload["ordered_unit_ids"].reverse()
    elif mutation == "control-fit":
        payload["fit_condition"] = "control"
    elif mutation == "parameters":
        payload["rastermap_parameters"]["random_state"] = 1
    else:
        payload["order_sha256"] = "changed"
    with pytest.raises(ValueError):
        validate_context_order(payload, population)


def test_ordering_rejects_changed_fitting_source(tmp_path, population):
    payload = json.loads(ORDER_PATH.read_text())
    payload["sources"][0]["sha256"] = "changed"
    path = tmp_path / "order.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="fitting source changed"):
        load_context_order(population, path)


@pytest.mark.parametrize("value", [0.0, 1 / 3, float("nan")])
def test_context_fit_rejects_constant_or_unavailable_rows(population, value):
    changed = deepcopy(population)
    changed["units"][0]["conditions"]["context"]["mean_hz"] = [value] * 300
    with pytest.raises(ValueError, match="finite and variable"):
        context_matrix(changed)


def test_context_heatmap_preserves_frozen_order_and_baseline_subtraction(
    data, population, examples,
):
    prepared = column.column_data(data, population, examples)
    order = prepared["order"]
    views = ordered_heatmaps(population, order)
    np.testing.assert_array_equal(views[0], prepared["delta"][0, order])
    np.testing.assert_array_equal(views[1], prepared["delta"][1, order])
    np.testing.assert_array_equal(views[2], (prepared["delta"][0] - prepared["delta"][1])[order])
    expected = prepared["delta"][:1, order]
    np.testing.assert_array_equal(prepared["ordered_heatmaps"], expected)
    assert prepared["heatmap"]["limit"] == max(1, np.ceil(np.percentile(np.abs(expected), 99)))
    assert prepared["heatmap"]["unavailable_rows_by_event_condition"] == [[0]]
    assert np.isfinite(prepared["ordered_heatmaps"]).all()
    assert np.sum(prepared["baseline_sd"][0] == 0) == 5
    assert prepared["example_indices"] == [
        next(i for i, unit in enumerate(data.units) if unit["id"] == unit_id)
        for unit_id in (964, 993)
    ]
    responder, comparison = prepared["example_indices"]
    assert prepared["positive_mask"][responder]
    assert prepared["comparison_mask"][comparison]
    assert not prepared["positive_mask"][comparison]


def test_nonq2_mean_and_sem_use_all_92_cortical_units(data, population, examples):
    prepared = column.column_data(data, population, examples)
    mask = prepared["nonq2_mask"]
    assert mask.sum() == 92
    assert not np.any(mask & prepared["positive_mask"])
    assert np.all(prepared["groups"][mask] == 0)
    selected = prepared["delta"][:, mask]
    np.testing.assert_array_equal(prepared["nonq2_mean"], selected.mean(axis=1))
    np.testing.assert_array_equal(prepared["nonq2_sem"], selected.std(axis=1, ddof=1) / np.sqrt(92))
    assert prepared["positive_mask"].sum() == 37


@pytest.mark.parametrize("count", [0, 1])
def test_nonq2_mean_rejects_insufficient_cortical_units(data, population, examples, count):
    changed = deepcopy(data)
    cortex = np.array([visual_group(unit) == 0 for unit in data.units])
    changed.statistics["q2_delta_p"][1, cortex] = 0.01
    if count:
        changed.statistics["q2_delta_p"][1, np.flatnonzero(cortex)[0]] = 0.5
    with pytest.raises(ValueError, match="At least two cortical Q2-nonsignificant"):
        column.column_data(changed, population, examples)


def test_column_geometry_typography_bounds_accessibility_and_determinism(
    tmp_path, monkeypatch, data, population, examples,
):
    original_save = column.save_diagnostic_svg
    prepared = column.column_data(data, population, examples)

    def checked_save(fig, *args, **kwargs):
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        canvas = fig.bbox
        cropped_bottom = canvas.y0 + (
            (column.LAYOUT_HEIGHT_MM - column.COLUMN_HEIGHT_MM) / 25.4 * fig.dpi
        )
        text_bottoms = []
        for text in fig.findobj(match=Text):
            if text.get_visible() and text.get_text():
                bbox = text.get_window_extent(renderer)
                assert canvas.x0 - 1 <= bbox.x0 <= bbox.x1 <= canvas.x1 + 1, text.get_text()
                assert cropped_bottom - 1 <= bbox.y0 <= bbox.y1 <= canvas.y1 + 1, text.get_text()
                text_bottoms.append(bbox.y0)
        assert 0 <= min(text_bottoms) - cropped_bottom < 3 / 25.4 * fig.dpi
        axes = {ax.get_gid(): ax for ax in fig.axes}
        assert len([gid for gid in axes if gid and gid.startswith("example-")]) == 4
        assert len([gid for gid in axes if gid and gid.startswith("population-heatmap-")]) == 1
        titles = {
            "example-context-raster-964": "Responsive",
            "example-context-raster-993": "Unresponsive",
        }
        assert all(ax.get_title() == titles.get(ax.get_gid(), "") for ax in fig.axes)
        visible_text = {
            text.get_text() for text in fig.findobj(match=Text) if text.get_visible()
        }
        assert not visible_text & {
            "964", "1026", "993", "VISp5", "Cortex", "Thalamus",
            "VISp5 unit", "VISp4 unit",
            "90 deg standard oddball", "All visual units (203 SUA)",
            "Ctx - Ctrl",
        }
        heatmap = axes["population-heatmap-context"]
        logo_ax = axes["platform-logo-neuropixels"]
        np.testing.assert_array_equal(
            np.asarray(logo_ax.images[0].get_array()),
            column.plt.imread(column.load_platform_logos()["neuropixels"]),
        )
        assert logo_ax.get_position().width * column.COLUMN_WIDTH_MM == pytest.approx(5)
        assert logo_ax.get_position().height * column.LAYOUT_HEIGHT_MM == pytest.approx(5)
        heading, = [
            text for text in fig.texts if text.get_gid() == "platform-label-neuropixels"
        ]
        assert heading.get_text() == "Neuropixels"
        assert heading.get_fontsize() == 7.5 and heading.get_fontweight() == "bold"
        assert heading.get_window_extent(renderer).x0 > logo_ax.bbox.x1
        assert logo_ax.bbox.y0 > axes["example-context-raster-964"].title.get_window_extent(
            renderer,
        ).y1
        assert not fig.legends
        assert "Context" not in visible_text and "Control" not in visible_text
        np.testing.assert_array_equal(
            np.asarray(heatmap.images[0].get_array()), prepared["ordered_heatmaps"][0],
        )
        previous_mean = None
        for number, unit_id in enumerate(column.EXAMPLE_UNIT_IDS):
            mean = axes[f"example-trial-mean-{unit_id}"]
            raster = axes[f"example-context-raster-{unit_id}"]
            i = prepared["example_indices"][number]
            for c in range(2):
                np.testing.assert_array_equal(
                    mean.lines[1 + c].get_ydata(), prepared["rates"][c, i],
                )
                np.testing.assert_array_equal(mean.lines[1 + c].get_xdata(), prepared["time"])
            assert mean.lines[2].get_color() == "#777777"
            assert mean.lines[2].get_alpha() == 0.5 < mean.lines[1].get_alpha()
            expected_limit = np.ceil(
                prepared["rates"][:, prepared["example_indices"]].max() / 10
            ) * 10
            assert mean.get_ylim() == (0, expected_limit)
            assert mean.get_ylim() == axes["example-trial-mean-964"].get_ylim()
            assert mean.get_position().x0 == pytest.approx(raster.get_position().x0)
            assert mean.get_position().width == pytest.approx(raster.get_position().width)
            assert mean.get_position().height == pytest.approx(raster.get_position().height)
            assert mean.get_position().y1 < raster.get_position().y0
            assert raster.get_position().y0 - mean.get_position().y1 == pytest.approx(0.012)
            assert (
                raster.get_position().y0
                == axes["example-context-raster-964"].get_position().y0
            )
            if previous_mean is not None:
                for label in mean.get_yticklabels():
                    if label.get_visible():
                        assert label.get_window_extent(renderer).x0 >= previous_mean.bbox.x1
            previous_mean = mean
            boxes = [label.get_window_extent(renderer) for label in mean.get_xticklabels()]
            assert all(
                first.x1 <= second.x0 for first, second in zip(boxes, boxes[1:], strict=False)
            )
            spikes = prepared["example_spikes"][number]["spikes"][EVENT_ID]["context"]
            assert raster.get_ylim() == (len(spikes) + 0.5, 0.5)
            collections = [
                collection for collection in raster.collections
                if isinstance(collection, LineCollection)
            ]
            assert len(collections) == len(spikes)
            for row, (collection, trial) in enumerate(zip(collections, spikes, strict=True)):
                visible = [s for s in trial if -0.75 <= s < 0.75]
                expected = [[[s, row + 0.65], [s, row + 1.35]] for s in visible]
                np.testing.assert_array_equal(
                    np.asarray(collection.get_segments()).reshape(-1, 2, 2),
                    np.asarray(expected).reshape(-1, 2, 2),
                )
        mean = axes["population-mean-overlay"]
        assert len([gid for gid in axes if gid and gid.startswith("population-mean-")]) == 1
        assert mean.get_position().x0 == heatmap.get_position().x0
        assert mean.get_position().width == pytest.approx(heatmap.get_position().width)
        assert mean.get_position().y1 < heatmap.get_position().y0
        assert heatmap.get_position().y0 - mean.get_position().y1 == pytest.approx(0.012)
        assert not mean.texts
        assert mean.get_position().height == pytest.approx(0.14)
        assert mean.get_position().y0 == pytest.approx(0.308)
        assert heatmap.get_position().y0 == pytest.approx(0.46)
        assert heatmap.get_position().height == pytest.approx(0.215)
        cohort_ax = axes["cohort-responsiveness-proportions"]
        cohort_data = cohort_plot_data()
        assert cohort_ax.get_position().y1 < mean.get_position().y0
        assert cohort_ax.get_position().height == pytest.approx(0.12)
        assert cohort_ax.get_position().y0 == pytest.approx(0.125)
        assert cohort_ax.get_ylim() == (0, 100)
        assert cohort_ax.get_ylabel() == "Responsive (%)"
        assert len(cohort_ax.patches) == 24
        assert len(cohort_ax.collections) == 3
        bars = {bar.get_gid(): bar for bar in cohort_ax.patches}
        intervals = {artist.get_gid(): artist for artist in cohort_ax.collections}
        for j, (screen, _) in enumerate(SCREENS):
            artist = intervals[f"cohort-mouse-bootstrap-ci95-{screen}"]
            segments = np.asarray(artist.get_segments())
            assert segments.shape == (8, 2, 2)
            for i, row in enumerate(cohort_data["areas"].to_dict("records")):
                region = row["brain_area"]
                bar = bars[f"cohort-pooled-{screen}-{region}"]
                assert bar.get_height() == 100 * row[f"fraction_{screen}_responsive"]
                center = i + (j - 1) * 0.24
                assert bar.get_x() + bar.get_width() / 2 == pytest.approx(center)
                np.testing.assert_allclose(segments[i, :, 0], center)
                np.testing.assert_allclose(
                    segments[i, :, 1],
                    [100 * row[f"fraction_{screen}_responsive_ci95_{bound}"]
                     for bound in ("low", "high")],
                )
                assert np.all((segments[i, :, 1] >= 0) & (segments[i, :, 1] <= 100))
        assert not cohort_ax.lines
        legend = cohort_ax.get_legend()
        assert [text.get_text() for text in legend.get_texts()] == ["Q1", "Q2", "Both"]
        a_xlabel, = [text for text in fig.texts if text.get_text() == "Time from deviant (s)"]
        a_to_b_gap = a_xlabel.get_window_extent(renderer).y0 - heatmap.bbox.y1
        b_to_c_gap = (
            mean.xaxis.label.get_window_extent(renderer).y0
            - legend.get_window_extent(renderer).y1
        )
        for gap in (a_to_b_gap, b_to_c_gap):
            assert 0 < gap < 4 / 25.4 * fig.dpi
        assert mean.get_xlabel() == "Time from deviant (s)"
        assert mean.get_ylabel() == "Δ Firing Rate (spikes/s)"
        assert "population-colorbar" not in axes
        assert [label.get_text() for label in cohort_ax.get_xticklabels()] == [
            "LGd", "VISp", "VISl", "VISa", "Frontal", "HIP", "SSp", "STR",
        ]
        for cohort, linestyle, prefix in (
            ("positive", "-", "population-sem"),
            ("nonq2", ":", "population-nonq2-sem"),
        ):
            for c, condition in enumerate(("context", "control")):
                line, = [
                    line for line in mean.lines
                    if line.get_gid() == f"population-{cohort}-{condition}"
                ]
                np.testing.assert_array_equal(
                    line.get_ydata(), prepared[f"{cohort}_mean"][c],
                )
                np.testing.assert_array_equal(line.get_xdata(), prepared["time"])
                assert line.get_linestyle() == linestyle
                assert line.get_color() == (column.CONTEXT_COLOR if c == 0 else "#777777")
                assert line.get_alpha() == (1.0 if c == 0 else 0.5)
                band, = [artist for artist in mean.collections
                         if artist.get_gid() == f"{prefix}-{condition}"]
                vertices = band.get_paths()[0].vertices
                np.testing.assert_array_equal(np.unique(vertices[:, 0]), prepared["time"])
                for j, t in enumerate(prepared["time"]):
                    bounds = vertices[vertices[:, 0] == t, 1]
                    center = prepared[f"{cohort}_mean"][c, j]
                    sem = prepared[f"{cohort}_sem"][c, j]
                    assert bounds.min() == pytest.approx(center - sem)
                    assert bounds.max() == pytest.approx(center + sem)
                    assert mean.get_ylim()[0] <= bounds.min() <= bounds.max() <= mean.get_ylim()[1]
        assert mean.lines[2].get_color() == "#777777"
        assert mean.lines[2].get_alpha() == 0.5 < mean.lines[1].get_alpha()
        return original_save(fig, *args, **kwargs)

    monkeypatch.setattr(column, "save_diagnostic_svg", checked_save)
    output = tmp_path / "column.svg"
    audit_dir = tmp_path / "audit"
    paths = column.build_standard_oddball_column(output, audit_dir)
    first = {p.name: p.read_bytes() for p in paths}
    for path in column.build_standard_oddball_column(output, audit_dir):
        assert path.read_bytes() == first[path.name]
    root = ET.fromstring(output.read_text())
    assert float(root.get("width").removesuffix("pt")) * 25.4 / 72 == pytest.approx(54)
    assert float(root.get("height").removesuffix("pt")) * 25.4 / 72 == pytest.approx(165)
    assert float(root.get("viewBox").split()[3]) * 25.4 / 72 == pytest.approx(165)
    assert root.get("data-intended-height-mm") == "165.0"
    assert root.get("overflow") == "hidden"
    assert root.get("data-platform-logo") == "figure_sources/media/platform-logos/neuropixels.png"
    assert root.get("data-condition-legend") == "none"
    assert root.find(".//*[@id='platform-label-neuropixels']") is not None
    logo = root.find(".//*[@id='platform-logo-neuropixels']")
    logo_images = logo.findall(".//{http://www.w3.org/2000/svg}image")
    assert len(logo_images) == 1
    logo_href = logo_images[0].get("{http://www.w3.org/1999/xlink}href")
    with Image.open(io.BytesIO(base64.b64decode(logo_href.split(",", 1)[1]))) as image:
        with Image.open(column.load_platform_logos()["neuropixels"]) as source:
            np.testing.assert_array_equal(np.asarray(image), np.asarray(source))
    assert root.get("data-event-id") == EVENT_ID
    assert root.get("data-example-unit-ids") == "964,993"
    assert root.get("data-session-id") == data.session["sessionId"]
    assert root.get("data-session-count") == "1"
    assert float(root.get("data-example-shared-y-limit-hz")) == np.ceil(
        prepared["rates"][:, prepared["example_indices"]].max() / 10
    ) * 10
    assert root.get("data-example-roles") == (
        "positive-responder,q2-nonsignificant-comparison"
    )
    assert root.get("data-rastermap-fit-condition") == "context"
    assert root.get("data-context-trial-count") == "34"
    assert root.get("data-control-trial-count") == "68"
    assert root.get("data-sdf-bin-seconds") == "0.005"
    assert root.get("data-sdf-tau-seconds") == "0.025"
    assert len(root.get("data-unit-order").split(",")) == 203
    assert root.get("role") == "img"
    assert root.get("data-publication-font") == "Arial"
    for letter in root.findall(".//*[@data-panel-letter]"):
        assert float(letter.get("font-size")) == pytest.approx(9, abs=1e-6)
    assert len(root.findall(".//*[@data-panel-letter]")) == 3
    assert root.get("data-cohort-session-count") == root.get("data-cohort-mouse-count") == "13"
    assert root.get("data-cohort-aggregation") == (
        "pooled-neuron-proportion-with-mouse-bootstrap-ci95"
    )
    assert root.get("data-cohort-denominator") == "eligible-joint-testable-neurons"
    assert root.get("data-cohort-areas") == "LGd,VISp,VISl,VISa,Frontal,Hippocampus,SSp,STR"
    assert root.get("data-heatmap-colorbar") == "none"
    assert root.find(".//*[@id='population-colorbar']") is None
    assert root.get("data-cohort-screens") == "q1,q2,joint"
    assert root.get("data-cohort-mouse-points") == "none"
    assert root.get("data-cohort-uncertainty") == column.BOOTSTRAP_RULE
    assert root.get("data-cohort-bootstrap-replicates") == "10000"
    assert root.get("data-cohort-bootstrap-seed") == "0"
    assert not any(
        node.get("id", "").startswith("cohort-mice-") for node in root.iter()
    )
    for screen, _ in SCREENS:
        assert root.find(f".//*[@id='cohort-mouse-bootstrap-ci95-{screen}']") is not None
    assert root.get("data-cohort-y-limit-percent") == "0,100"
    assert root.get("data-cohort-selection") == column.RESPONSE_RULE
    assert root.get("data-cohort-minimum-qc-sua") == "20"
    assert root.get("data-cohort-minimum-before") == "firing-rate-and-response-tests"
    assert root.find(".//*[@id='cohort-responsiveness-proportions']") is not None
    for unit_id in (964, 993):
        assert root.find(f".//*[@id='example-context-raster-{unit_id}']") is not None
        assert root.find(f".//*[@id='example-trial-mean-{unit_id}']") is not None
        assert root.find(f".//*[@id='example-control-raster-{unit_id}']") is None
    assert root.find(".//*[@id='population-mean-0']") is None
    assert root.find(".//*[@id='population-mean-1']") is None
    assert root.find(".//*[@id='population-mean-positive']") is None
    assert root.find(".//*[@id='population-mean-nonq2']") is None
    assert root.find(".//*[@id='population-mean-overlay']") is not None
    assert root.get("data-population-mean-layout") == "shared-axis-overlay"
    assert root.get("data-responsive-linestyle") == "solid"
    assert root.get("data-nonq2-linestyle") == "dotted"
    assert root.get("data-nonq2-mean-count") == "92"
    assert root.get("data-nonq2-mean-filter") == column.NONQ2_CORTEX_RULE
    for condition in ("control", "difference"):
        assert root.find(f".//*[@id='population-heatmap-{condition}']") is None
    heatmap = root.find(".//*[@id='population-heatmap-context']")
    images = heatmap.findall(".//{http://www.w3.org/2000/svg}image")
    assert len(images) == 1
    href = images[0].get("{http://www.w3.org/1999/xlink}href")
    with Image.open(io.BytesIO(base64.b64decode(href.split(",", 1)[1]))) as image:
        assert image.size == (300, 203)
    sizes = [
        float(value) for node in root.iter()
        for value in re.findall(r"font-size:\s*([0-9.]+)px", node.get("style", ""))
    ]
    assert sizes and min(sizes) >= 5.5
    with paths[1].open() as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 203
    assert sum(r["example"] == "True" for r in rows) == 2
    assert sum(r["comparison_candidate"] == "True" for r in rows) == 20
    assert sum(r["cortical_q2_nonsignificant"] == "True" for r in rows) == 92
    assert {r["unit_id"]: r["example_role"] for r in rows if r["example"] == "True"} == {
        "964": "positive-responder", "993": "q2-nonsignificant-comparison",
    }
    for c, condition in enumerate(("context", "control")):
        np.testing.assert_array_equal(
            [float(r[f"{condition}_baseline_sd_hz"]) for r in rows], prepared["baseline_sd"][c],
        )
    np.testing.assert_array_equal(
        [r["positive_q1_q2"] == "True" for r in rows], prepared["positive_mask"],
    )
    assert sorted(int(r["context_rastermap_rank"]) for r in rows) == list(range(1, 204))
    provenance = json.loads(paths[-1].read_text())
    assert provenance["footprint_mm"] == [54, 165]
    assert provenance["bottom_crop_mm"] == 15
    assert provenance["header"]["label"] == "Neuropixels"
    assert provenance["header"]["logo_reference"] == "Figure 3"
    assert provenance["header"]["condition_legend"] == "removed"
    assert provenance["session_count"] == 1
    assert provenance["cohort"]["session_count"] == provenance["cohort"]["mouse_count"] == 13
    assert provenance["cohort"]["minimum_session_group_qc_sua"] == 20
    assert provenance["cohort"]["screens"] == ["Q1", "Q2", "Both"]
    assert provenance["cohort"]["selection"] == column.RESPONSE_RULE
    assert provenance["cohort"]["y_limit_percent"] == [0, 100]
    assert provenance["cohort"]["region_display_labels"] == {"Hippocampus": "HIP"}
    assert provenance["cohort"]["uncertainty"]["rule"] == column.BOOTSTRAP_RULE
    assert provenance["cohort"]["uncertainty"]["replicates"] == 10000
    assert provenance["cohort"]["uncertainty"]["seed"] == 0
    assert len(provenance["cohort"]["mouse_counts"]) == 78
    assert provenance["cohort"]["groups"]["STR"] == {
        "division": "STR", "areas": ["LSr", "LSc", "STR", "CP", "SH"],
    }
    for row in provenance["cohort"]["areas"]:
        for screen, _ in SCREENS:
            assert 0 <= row[f"fraction_{screen}_responsive_ci95_low"] <= (
                row[f"fraction_{screen}_responsive_ci95_high"]
            ) <= 1
    assert provenance["cohort"]["session_filter_audit"] == "cohort-sessions.csv"
    assert provenance["session_id"] == data.session["sessionId"]
    assert provenance["example_titles"] == ["Responsive", "Unresponsive"]
    assert provenance["population_mean_layout"] == {
        "axes": "shared baseline-subtracted Hz",
        "responsive": "solid", "cortical_q2_nonsignificant": "dotted",
    }
    assert provenance["group_counts"] == [145, 58]
    assert provenance["trial_counts"] == {"context": 34, "control": 68}
    assert provenance["example_unit_ids"] == [964, 993]
    assert provenance["normalization"]["conditions_shown"] == ["context"]
    assert provenance["normalization"]["undefined_context_rows"] == 0
    assert provenance["normalization"]["units"] == "baseline-subtracted Hz"
    assert root.get("data-heatmap-conditions") == "context"
    assert root.get("data-heatmap-limit-sd") is None
    assert float(root.get("data-heatmap-limit-hz")) == prepared["heatmap"]["limit"]
    assert root.get("data-heatmap-normalization") == column.HEATMAP_RULE
    selected_ids = [
        unit["id"] for i, unit in enumerate(data.units) if prepared["positive_mask"][i]
    ]
    assert provenance["population_mean"]["unit_ids"] == selected_ids
    assert provenance["population_mean"]["count"] == len(selected_ids)
    assert provenance["population_mean"]["uncertainty"]["sample_size"] == 37
    assert provenance["nonq2_population_mean"]["count"] == 92
    assert provenance["nonq2_population_mean"]["group_counts"] == [92, 0]
    assert provenance["nonq2_population_mean"]["uncertainty"]["sample_size"] == 92
    assert provenance["nonq2_population_mean"]["unit_ids"] == [
        unit["id"] for i, unit in enumerate(data.units) if prepared["nonq2_mask"][i]
    ]
    assert provenance["population_mean"]["uncertainty"]["formula"] == (
        "sample SD (ddof=1) / sqrt(neuron count)"
    )
    assert provenance["control_line"] == {"color": "#777777", "alpha": 0.5}
    assert root.get("data-population-sem") == (
        "sample-neuron-SD-ddof1-divided-by-sqrt-neuron-count"
    )
    assert int(root.get("data-population-mean-count")) == len(selected_ids)
    assert root.get("data-population-mean-filter") == column.POSITIVE_RESPONSE_RULE
    assert root.get("data-unit-order") == ",".join(
        str(i) for i in provenance["rastermap"]["ordered_unit_ids"]
    )
    for record in provenance["outputs"]:
        assert hashlib.sha256(first[record["name"]]).hexdigest() == record["sha256"]
    for record in provenance["sources"]:
        assert hashlib.sha256((REPO_ROOT / record["path"]).read_bytes()).hexdigest() == (
            record["sha256"]
        )


def test_typography_supports_native_column_size_without_changing_full_width_default():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="54mm" height="180mm" '
        'viewBox="0 0 153.07086614 510.23622047">'
        '<text class="panel-label" x="0" y="12">A</text></svg>'
    )
    root = ET.fromstring(normalize_figure_svg(svg, target_width_mm=54, target_height_mm=180))
    assert float(root.find(".//*[@data-panel-letter]").get("font-size")) == pytest.approx(9)
    with pytest.raises(ValueError, match="Target figure dimensions"):
        normalize_figure_svg(svg, target_width_mm=0)
