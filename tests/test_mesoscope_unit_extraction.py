"""Scientific and layout regressions for the editable mesoscope quality figure."""

import json
import re
import socket
from xml.etree import ElementTree as ET

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pytest

from openscope_p3_publication.mesoscope_unit_extraction import (
    CLASS_COLORS,
    CLASS_ORDER,
    FRACTIONS,
    PLANE,
    PROVENANCE,
    SESSION,
    TRACE_ROI,
    build_planes,
    class_examples,
    decode_plane,
    load_publication_inputs,
    make_mesoscope_figure,
    onsets,
    panel_inputs,
    pick_example,
    write_mesoscope_unit_extraction_svg,
)


@pytest.fixture(scope="module")
def inputs():
    return load_publication_inputs()


@pytest.fixture(scope="module")
def figure(inputs):
    with mpl.rc_context({
        "font.size": 7.5, "axes.labelsize": 7.5,
        "xtick.labelsize": 6.5, "ytick.labelsize": 6.5,
    }):
        result = make_mesoscope_figure(*inputs)
        result.canvas.draw()
        yield result
        plt.close(result)


def test_archived_cohort_and_classifications_are_unchanged(inputs):
    cohort, _ = inputs
    counts = panel_inputs(cohort)["counts"]
    assert counts == {
        "sessions": 81, "mice": 10, "rois": 175508,
        "per_class": {"Low SNR": 51694, "Intermediate": 85860, "High SNR": 37954},
    }
    examples = class_examples(cohort)
    assert {cls: int(row.roi_index) for cls, row in examples.items()} == {
        "Low SNR": 272, "Intermediate": 81, "High SNR": 103,
    }
    assert all(row.session == SESSION and row.plane == PLANE for row in examples.values())
    for cls, row in examples.items():
        candidates = cohort.loc[
            cohort.session.eq(SESSION) & cohort.plane.eq(PLANE)
            & cohort.amp_threshold_quality_class.eq(cls)
        ]
        centroid = cohort.loc[cohort.amp_threshold_quality_class.eq(cls), FRACTIONS].mean()
        assert np.linalg.norm(row[FRACTIONS].to_numpy(dtype=float) - centroid.values) == (
            pytest.approx(np.linalg.norm(candidates[FRACTIONS].values - centroid.values,
                                        axis=1).min())
        )


def test_selected_trace_and_single_footprint_use_unchanged_saved_data(inputs, figure):
    cohort, payload = inputs
    session = cohort.loc[cohort.session.eq(SESSION)]
    lookup = {(r.plane, int(r.roi_index)): r.amp_threshold_quality_class
              for r in session.itertuples()}
    # The original selection over all eight FOVs must still select this trace.
    planes = build_planes(payload, lookup)
    _, plane, _, legacy_roi, _, legacy_events = pick_example(planes)
    assert plane["plane"] == PLANE and legacy_roi["roi_index"] == 154
    assert TRACE_ROI == 84
    index = next(i for i, roi in enumerate(plane["raw"]["rois"])
                 if roi["roi_index"] == TRACE_ROI)
    roi = plane["raw"]["rois"][index]
    dff, saved_events = decode_plane(plane["raw"])
    trace, events = dff[index], saved_events[index]
    assert roi["n_events"] == 3954
    assert onsets(events).sum() == 56 < onsets(legacy_events).sum()
    axes = {axis.get_gid(): axis for axis in figure.axes}
    axis = axes["mesoscope-example-trace"]
    np.testing.assert_array_equal(axis.lines[0].get_ydata(), trace)
    times = np.arange(len(trace)) * plane["raw"]["dtSeconds"]
    np.testing.assert_array_equal(axis.lines[0].get_xdata(), times)
    np.testing.assert_array_equal(axis.collections[0].get_offsets()[:, 0], times[onsets(events)])
    figure.canvas.draw()
    noise = axis.transData.inverted().transform_bbox(axis.patches[0].get_window_extent())
    assert noise.y0 == pytest.approx(-3 * roi["baseline_noise_sd"])
    assert noise.y1 == pytest.approx(3 * roi["baseline_noise_sd"])
    footprint = axes["mesoscope-single-roi-footprint"]
    ys, xs = np.nonzero(plane["labels"] == index)
    crop = (slice(max(0, ys.min() - 30), min(plane["labels"].shape[0], ys.max() + 30)),
            slice(max(0, xs.min() - 30), min(plane["labels"].shape[1], xs.max() + 30)))
    np.testing.assert_array_equal(footprint.images[0].get_array(), plane["projection"][crop])
    image = footprint.images[0].get_window_extent()
    assert image.x0 > axis.get_window_extent().x1
    assert (image.x0 + image.x1) / 2 == pytest.approx(
        (axis.get_window_extent().x1 + figure.bbox.width * 0.975) / 2
    )
    dff, _ = decode_plane(plane["raw"])
    np.testing.assert_array_equal(dff[index], trace)


def test_single_fov_and_scatter_highlight_only_the_three_fraction_examples(inputs, figure):
    cohort, payload = inputs
    axes = {axis.get_gid(): axis for axis in figure.axes}
    assert len(axes) == 9
    field = axes["mesoscope-single-fov"]
    scatter = axes["mesoscope-cohort-feature-space"]
    assert len(field.images) == 4
    plane = next(p for p in payload["planes"] if p["plane"] == PLANE)
    assert plane["nRois"] == 277
    rows = cohort.loc[cohort.session.eq(SESSION) & cohort.plane.eq(PLANE)]
    lookup = {(row.plane, int(row.roi_index)): row.amp_threshold_quality_class
              for row in rows.itertuples()}
    decoded, = build_planes({"planes": [plane]}, lookup)
    np.testing.assert_array_equal(field.images[0].get_array(), decoded["projection"])
    assert rows.amp_threshold_quality_class.value_counts().to_dict() == {
        "Low SNR": 181, "Intermediate": 85, "High SNR": 11,
    }
    for cls, image, points in zip(
        CLASS_ORDER, field.images[1:], scatter.collections, strict=True,
    ):
        members = [index for index, value in decoded["roi_class"].items() if value == cls]
        mask = np.isin(decoded["labels"], members)
        expected = np.zeros((*mask.shape, 4))
        expected[mask] = mpl.colors.to_rgba(CLASS_COLORS[cls], 0.5)
        np.testing.assert_array_equal(image.get_array(), expected)
        original = cohort.loc[cohort.amp_threshold_quality_class.eq(cls)]
        np.testing.assert_allclose(points.get_offsets(), np.column_stack((
            original.frac_events_lt2sd * 100, original.frac_events_gt4sd * 100,
        )))
    assert all(image.get_interpolation() == "nearest" for image in field.images)
    assert sum(len(points.get_offsets()) for points in scatter.collections) == 175508
    assert len(field.lines) == len(scatter.lines) == 3
    for cls, row in class_examples(cohort).items():
        roi = int(row.roi_index)
        point = next(line for line in scatter.lines if line.get_gid().endswith(f"-{roi}"))
        spatial = next(line for line in field.lines if line.get_gid().endswith(f"-{roi}"))
        np.testing.assert_allclose(point.get_xdata(), [row.frac_events_lt2sd * 100])
        np.testing.assert_allclose(point.get_ydata(), [row.frac_events_gt4sd * 100])
        index = next(i for i, saved in enumerate(plane["rois"]) if saved["roi_index"] == roi)
        y, x = np.argwhere(decoded["labels"] == index).mean(axis=0)
        np.testing.assert_allclose(spatial.get_xdata(), [x])
        np.testing.assert_allclose(spatial.get_ydata(), [y])
        assert point.get_markeredgecolor() == spatial.get_markeredgecolor() == "white"
        assert point.get_markersize() == spatial.get_markersize()
        assert len(point.get_path_effects()) == len(spatial.get_path_effects()) == 2
        axis = axes[f"mesoscope-fractions-{cls.lower().replace(' ', '-')}"]
        np.testing.assert_allclose(
            [bar.get_height() for bar in axis.patches],
            row[["frac_events_lt2sd", "frac_events_gt4sd"]].to_numpy(dtype=float) * 100,
        )
        assert [tick.get_text() for tick in axis.get_xticklabels()] == ["<2", ">4"]
    assert {text.get_text() for text in scatter.texts} == {"272", "81", "103"}
    assert [axis for axis in figure.axes if axis.get_legend()] == [scatter]
    assert not figure.legends
    assert not any(line.get_visible() for axis in figure.axes
                   for line in axis.get_xgridlines() + axis.get_ygridlines())


def test_composition_and_all_session_points_preserve_original_summaries(inputs, figure):
    cohort, _ = inputs
    data = panel_inputs(cohort)
    composition = next(axis for axis in figure.axes
                       if axis.get_gid() == "mesoscope-shared-composition")
    assert len(composition.patches) == 16 * 3
    assert composition.get_ylim() == (0, 100)
    offset = 0
    for table in (data["by_area"], data["by_depth"], data["by_mouse"]):
        heights = []
        for cls, bars in zip(CLASS_ORDER, composition.containers[offset:offset + 3], strict=True):
            np.testing.assert_allclose([bar.get_height() for bar in bars], table[cls])
            heights.append([bar.get_height() for bar in bars])
        np.testing.assert_allclose(np.sum(heights, axis=0), 100)
        offset += 3
    spread = next(axis for axis in figure.axes if axis.get_gid() == "mesoscope-session-spread")
    assert len(spread.collections) == len(spread.lines) == 10
    assert sum(len(points.get_offsets()) for points in spread.collections) == 81
    for mouse, points, median in zip(
        data["by_mouse"].index, spread.collections, spread.lines, strict=True,
    ):
        rows = data["by_session"].loc[data["by_session"].subject.eq(mouse)]
        np.testing.assert_allclose(points.get_offsets()[:, 1], rows["High SNR"])
        np.testing.assert_array_equal(points.get_facecolors(), [[0, 0, 0, 1]])
        np.testing.assert_allclose(median.get_ydata(), [rows["High SNR"].median()] * 2)
    assert spread.get_xlabel() == "Mouse ID"


def test_letter_order_and_plot_text_have_no_sample_counts(figure):
    letters = [text.get_text() for text in figure.texts
               if (text.get_gid() or "").startswith("panel-label-")]
    assert letters == list("ABCDEFGHI")
    text = " ".join(
        [t.get_text() for t in figure.texts]
        + [t.get_text() for axis in figure.axes for t in axis.texts]
        + [axis.get_title() for axis in figure.axes]
    )
    assert not re.search(r"\bn\s*=|\b[\d,]+\s+(?:events|ROIs|sessions)\b", text)
    assert "k-means" not in text and "All sessions" not in text
    assert "footprint" not in text


def test_editable_svg_build_is_offline_and_byte_deterministic(tmp_path, monkeypatch):
    def reject_network(*args, **kwargs):
        raise AssertionError("Mesoscope figure generation must remain offline.")

    monkeypatch.setattr(socket, "socket", reject_network)
    output = write_mesoscope_unit_extraction_svg(tmp_path / "figure.svg")
    first = output.read_bytes()
    write_mesoscope_unit_extraction_svg(output)
    assert output.read_bytes() == first
    root = ET.fromstring(first)
    assert root.get("data-publication-font") == "Arial"
    assert root.get("data-panel-letter-points") == "9"
    assert root.get("aria-labelledby") == "mesoscope-title mesoscope-description"
    identifiers = [node.get("id") for node in root.iter() if node.get("id")]
    assert len(identifiers) == len(set(identifiers))
    assert {node.get("data-panel-letter") for node in root.iter()
            if node.get("data-panel-letter")} == set("ABCDEFGHI")
    assert len(root.findall(".//{http://www.w3.org/2000/svg}text")) > 75


def test_input_checksum_mismatch_is_explicit(tmp_path):
    record = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    record["source_table"]["sha256"] = "0" * 64
    path = tmp_path / "provenance.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="source_table.*checksum"):
        load_publication_inputs(path)
