import base64
import hashlib
import io
import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from openscope_p3_publication.image_encoding import canonical_png, canonical_svg_images
from openscope_p3_publication.slap2_glutamate_figure7_panels import (
    CLASS_COLORS,
    CLASS_ORDER,
    EXAMPLE_PATH,
    class_composition_summary,
    class_examples,
    combined_quality_ecdf,
    coverage_bbox,
    event_table,
    load_example_snapshot,
    low_snr_group_summary,
    quality_group_ecdfs,
    quality_groups,
    raw_event_peak_indices,
    render_panel_c,
    render_panel_g,
    render_panel_k,
    render_publication_distribution,
    render_publication_prevalence,
    render_publication_sources,
    source_trace,
    write_slap2_glutamate_figure,
)
from openscope_p3_publication.slap2_glutamate_qc_events import (
    assign_classes,
    detect_events,
    event_amplitudes_raw,
    sampling_interval,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "figure_sources/data/slap2-glutamate-qc"


def test_compact_traces_preserve_original_roi_identity() -> None:
    full = np.arange(60).reshape(10, 6)
    compact = {"data": full[:, [1, 4]], "roi_ids": np.array([1, 4])}

    np.testing.assert_array_equal(source_trace(compact, 4), full[:, 4])
    np.testing.assert_array_equal(source_trace({"data": full}, 4), full[:, 4])
    with pytest.raises(KeyError, match="ROI 3"):
        source_trace(compact, 3)


def test_image_encoding_preserves_pixels_and_normalizes_svg_ids() -> None:
    pixels = np.arange(400, dtype=np.uint8).reshape(10, 10, 4)
    original = io.BytesIO()
    Image.fromarray(pixels).save(original, format="PNG")
    normalized = canonical_png(original.getvalue())
    np.testing.assert_array_equal(np.asarray(Image.open(io.BytesIO(normalized))), pixels)
    assert canonical_png(normalized) == normalized
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
        '<image id="{identifier}" xlink:href="data:image/png;base64,{encoded}"/>'
        '<use xlink:href="#{identifier}"/></svg>'
    )
    first = svg.format(identifier="first", encoded=base64.b64encode(original.getvalue()).decode())
    second = svg.format(identifier="second", encoded=base64.b64encode(normalized).decode())
    assert canonical_svg_images(first) == canonical_svg_images(second)


def test_example_snapshot_checks_checksum_and_numeric_arrays(tmp_path: Path) -> None:
    output = tmp_path / "example.npz"
    traces = np.arange(20, dtype=np.float32).reshape(10, 2)
    np.savez_compressed(
        output, schema_version=np.array(1), session_id=np.array("example-session"),
        trace_dmds=np.array([2]), plane_dmds=np.array([1]),
        data2=traces, ts2=np.arange(10) * 0.005, dt2=np.array(0.005),
        roi_ids2=np.array([1, 4]), activity1=np.ones((4, 5)), mean1=np.ones((4, 5)),
        outlines1=np.ones((2, 4, 5), dtype=bool),
    )
    output.with_suffix(".provenance.json").write_text(
        json.dumps({"output_sha256": hashlib.sha256(output.read_bytes()).hexdigest()}),
        encoding="utf-8",
    )

    session = load_example_snapshot(output)
    assert session["session_id"] == "example-session"
    np.testing.assert_array_equal(source_trace(session["traces"][2], 4), traces[:, 1])
    assert len(session["planes"][1][2]) == 2
    output.write_bytes(b"changed snapshot")
    with pytest.raises(ValueError, match="checksum"):
        load_example_snapshot(output)


def test_archived_classes_reproduce_without_nwb() -> None:
    metrics = pd.read_csv(DATA_DIR / "slap2_metrics_all_sessions.csv")
    reproduced = assign_classes(metrics)

    assert len(metrics) == 2540
    assert metrics.session.nunique() == 20
    assert metrics.subject.nunique() == 8
    pd.testing.assert_series_equal(reproduced.quality_class, metrics.quality_class)
    assert metrics.quality_class.value_counts().to_dict() == {
        "Intermediate": 1026,
        "High SNR": 830,
        "Low SNR": 665,
        "Excluded (no baseline noise)": 19,
    }


def test_context_records_preserve_source_counts_and_rate_definition() -> None:
    metrics = pd.read_csv(DATA_DIR / "slap2_metrics_all_sessions.csv")
    contexts = pd.read_csv(DATA_DIR / "slap2_context_rates_all_sessions.csv")
    keys = ["subject", "session", "dmd", "roi"]

    assert not contexts.duplicated(keys + ["context"]).any()
    assert contexts.n_events.gt(0).all()
    assert contexts.seconds.gt(0).all()
    np.testing.assert_allclose(contexts.rate_hz, contexts.n_events / contexts.seconds)
    joined = contexts.merge(metrics[keys + ["quality_class"]], on=keys, validate="many_to_one")
    assert (joined.quality_class_x == joined.quality_class_y).all()
    expected = metrics.loc[metrics.n_events.gt(0)].set_index(keys).n_events.sort_index()
    observed = contexts.groupby(keys).n_events.sum().sort_index()
    pd.testing.assert_series_equal(observed, expected)


def test_two_quality_groups_preserve_the_archived_low_snr_boundary() -> None:
    metrics = pd.read_csv(DATA_DIR / "slap2_metrics_all_sessions.csv")
    original = metrics.copy(deep=True)
    groups = quality_groups(metrics)
    assert groups.value_counts().to_dict() == {"Non-low SNR": 1856, "Low SNR": 665}
    assert groups.isna().sum() == 19
    pd.testing.assert_series_equal(groups.eq("Low SNR"), metrics.quality_class.eq("Low SNR"))
    pd.testing.assert_frame_equal(metrics, original)


def test_quality_ecdfs_and_prevalence_use_sources_not_group_means() -> None:
    metrics = pd.read_csv(DATA_DIR / "slap2_metrics_all_sessions.csv")
    groups = quality_groups(metrics)
    for group, (horizontal, vertical) in quality_group_ecdfs(metrics).items():
        expected = np.sort(metrics.loc[groups == group, "frac_events_gt4sd"].to_numpy() * 100)
        np.testing.assert_array_equal(horizontal, expected)
        np.testing.assert_allclose(vertical, np.arange(1, len(expected) + 1) / len(expected) * 100)
    combined, cumulative = combined_quality_ecdf(metrics)
    expected = np.sort(metrics.loc[groups.notna(), "frac_events_gt4sd"].to_numpy() * 100)
    np.testing.assert_array_equal(combined, expected)
    np.testing.assert_allclose(cumulative, np.arange(1, 2522) / 2521 * 100)
    summary = low_snr_group_summary(metrics)
    overall = summary.loc[summary.group == "Overall"].iloc[0]
    assert (overall.n, overall.low) == (2521, 665)
    assert overall.percent_low == pytest.approx(100 * 665 / 2521)
    for group in ("Compartment", "Processing cohort", "Mouse"):
        subset = summary.loc[summary.group == group]
        assert subset.n.sum() == overall.n
        assert subset.low.sum() == overall.low


def test_quality_panels_pool_sources_and_put_group_labels_below_ticks(
    tmp_path, monkeypatch,
) -> None:
    import matplotlib.pyplot as plt

    metrics = pd.read_csv(DATA_DIR / "slap2_metrics_all_sessions.csv")
    example = metrics.loc[metrics.session == "sub-794237_ses-20250508T145040"]
    captured = {}

    def capture(figure, output, name, **kwargs):
        captured[name] = figure

    monkeypatch.setattr(
        "openscope_p3_publication.slap2_glutamate_figure7_panels.save_panel", capture
    )
    try:
        render_publication_distribution(metrics, tmp_path)
        figure = captured["figure7_panelG_slap2_glutamate"]
        axis = figure.axes[0]
        assert len(axis.lines) == 21
        pooled = next(line for line in axis.lines if line.get_gid() == "session-ecdf-combined")
        horizontal, cumulative = combined_quality_ecdf(metrics)
        np.testing.assert_array_equal(pooled.get_xdata(), horizontal)
        np.testing.assert_array_equal(pooled.get_ydata(), cumulative)
        assert len(horizontal) == 2521
        counts = sorted(len(collection.get_offsets()) for collection in axis.collections)
        assert counts == [665, 1856]
        overlap = next(patch for patch in axis.patches
                   if patch.get_gid() == "quality-group-overlap")
        figure.canvas.draw()
        bounds = axis.transData.inverted().transform_bbox(overlap.get_window_extent())
        grouped = quality_group_ecdfs(metrics)
        assert bounds.x0 == pytest.approx(max(values.min() for values, _ in grouped.values()))
        assert bounds.x1 == pytest.approx(min(values.max() for values, _ in grouped.values()))

        render_publication_prevalence(metrics, tmp_path)
        figure = captured["figure7_panelK_slap2_glutamate"]
        axis = figure.axes[0]
        summary = low_snr_group_summary(metrics)
        assert len(axis.patches) == len(summary)
        np.testing.assert_allclose([bar.get_height() for bar in axis.patches], summary.percent_low)
        assert all(line.get_gid().startswith("prevalence-group-divider-") for line in axis.lines)
        for collection, row in zip(axis.collections, summary.itertuples(), strict=True):
            np.testing.assert_allclose(collection.get_offsets()[:, 1], row.session_percent_low)
        figure.canvas.draw()
        renderer = figure.canvas.get_renderer()
        tick_bottom = min(label.get_window_extent(renderer).y0 for label in axis.get_xticklabels())
        group_labels = [label for label in axis.texts
                        if (label.get_gid() or "").startswith("prevalence-group-label-")]
        assert len(group_labels) == 4
        assert all(label.get_window_extent(renderer).y1 < tick_bottom for label in group_labels)
        assert all(label.get_window_extent(renderer).y0 >= 0 for label in group_labels)

        session = load_example_snapshot(EXAMPLE_PATH)
        render_publication_sources(session, example, tmp_path)
        figure = captured["figure7_panelC_slap2_glutamate"]
        axes = {axis.get_gid(): axis for axis in figure.axes if axis.get_gid()}
        traces = [axes[f"raw-source-DMD2-{roi}"] for roi in (26, 1)]
        assert traces[0].get_ylim() == traces[1].get_ylim()
        assert all(axis.get_xlim() == (0, 10) for axis in traces)
        trace_data = session["traces"][2]
        times = trace_data["ts"]
        start = times[0] + 920
        for roi in (26, 1):
            trace = source_trace(trace_data, roi)
            events = event_table(trace, times, trace_data["dt"])
            peaks = events["peak_idx"]
            selected = (times[peaks] >= start) & (times[peaks] < start + 10)
            points = axes[f"raw-source-DMD2-{roi}"].collections[0].get_offsets()
            np.testing.assert_allclose(points[:, 0], times[peaks[selected]] - start)
            np.testing.assert_allclose(
                points[:, 1], (trace[peaks[selected]] - events["raw_med"]) / events["raw_sd"]
            )
        assert axes["event-amplitudes-DMD2-1"].get_xlabel() == "Time (s)"
    finally:
        for figure in captured.values():
            plt.close(figure)


def test_selected_example_reproduces_original_source_measurements() -> None:
    provenance = json.loads(EXAMPLE_PATH.with_suffix(".provenance.json").read_text())
    session = load_example_snapshot(EXAMPLE_PATH)
    metrics = pd.read_csv(DATA_DIR / "slap2_metrics_all_sessions.csv")
    example = metrics.loc[metrics.session == session["session_id"]].set_index(["dmd", "roi"])

    assert provenance["large_snapshot_approved"] is True
    assert EXAMPLE_PATH.stat().st_size == provenance["output_bytes"]
    assert EXAMPLE_PATH.stat().st_size < 100 * 1024 * 1024
    assert len(provenance["source_assets"]) == 20
    assert all(asset["digest"] for asset in provenance["source_assets"])
    assert {record["dmd"] for record in provenance["selected_sources"]} == {1, 2}
    assert len(provenance["selected_sources"]) == 4
    assert [len(session["planes"][dmd][2]) for dmd in (1, 2)] == [120, 59]
    for record in provenance["selected_sources"]:
        trace_data = session["traces"][record["dmd"]]
        events = event_table(
            source_trace(trace_data, record["roi"]), trace_data["ts"], trace_data["dt"]
        )
        assert events["z"].dtype == np.float64
        original_events = detect_events(source_trace(trace_data, record["roi"]), trace_data["dt"])
        np.testing.assert_array_equal(events["idx"], original_events["idx"])
        expected = example.loc[record["dmd"], record["roi"]]
        assert len(events["idx"]) == expected.n_events
        assert events["raw_sd"] == pytest.approx(expected.noise_dff, rel=1e-6)
        assert np.nanmedian(events["amp_raw"]) == pytest.approx(
            expected.median_event_raw_sd, rel=1e-6
        )


def test_class_compositions_preserve_all_three_archived_classes() -> None:
    metrics = pd.read_csv(DATA_DIR / "slap2_metrics_all_sessions.csv")
    original = metrics.copy(deep=True)
    classified = metrics.loc[metrics.quality_class.isin(CLASS_ORDER)]
    table = class_composition_summary(metrics)
    assert len(table) == 24
    assert table.group.value_counts().to_dict() == {"Session": 20, "Compartment": 4}
    np.testing.assert_allclose(table[CLASS_ORDER].sum(axis=1), 100)
    for group in ("Compartment", "Session"):
        subset = table.loc[table.group == group]
        assert subset.n.sum() == 2521
        np.testing.assert_allclose(
            subset[CLASS_ORDER].mul(subset.n, axis=0).sum() / 100, [665, 1026, 830]
        )
    for row in table.loc[table.group == "Session"].itertuples():
        sources = classified.loc[classified.session == row.session]
        assert row.n == len(sources)
        expected = sources.quality_class.value_counts().reindex(CLASS_ORDER, fill_value=0)
        observed = table.loc[table.session == row.session, CLASS_ORDER].iloc[0]
        np.testing.assert_allclose(observed, expected * 100 / len(sources))
    pd.testing.assert_frame_equal(metrics, original)
    with pytest.raises(ValueError, match="No classified sources"):
        class_composition_summary(metrics.loc[~metrics.has_calcium])


def test_compact_panels_put_dmd2_beside_full_archive_below_histograms(
    tmp_path: Path, monkeypatch,
) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.colors import to_rgba

    metrics = pd.read_csv(DATA_DIR / "slap2_metrics_all_sessions.csv")
    summary = pd.read_csv(DATA_DIR / "slap2_session_summary.csv")
    session = load_example_snapshot(EXAMPLE_PATH)
    example = metrics.loc[metrics.session == session["session_id"]]
    captured = {}

    def capture(figure, output, name, **kwargs):
        captured[name] = figure

    monkeypatch.setattr(
        "openscope_p3_publication.slap2_glutamate_figure7_panels.save_panel", capture
    )
    try:
        render_panel_c(session, example, tmp_path)
        figure = captured["figure7_panelC_slap2_glutamate"]
        assert len(figure.axes) == 2
        trace_axis = next(axis for axis in figure.axes
                          if axis.get_gid() == "example-trace-DMD1-9")
        trace_data = session["traces"][1]
        times = trace_data["ts"]
        window = (times >= times[0] + 900) & (times < times[0] + 920)
        np.testing.assert_array_equal(
            trace_axis.lines[0].get_ydata(), source_trace(trace_data, 9)[window]
        )
        assert trace_axis.get_title() == ""
        assert trace_axis.get_legend() is None
        footprint = next(axis for axis in figure.axes
                         if axis.get_gid() == "single-synapse-footprint-DMD1-9")
        figure.canvas.draw()
        image_bounds = figure.transFigure.inverted().transform_bbox(
            footprint.images[0].get_window_extent()
        )
        assert image_bounds.x0 > trace_axis.get_position().x1
        assert (image_bounds.x0 + image_bounds.x1) / 2 == (
            pytest.approx((trace_axis.get_position().x1 + 0.985) / 2)
        )
        assert footprint.get_title() == ""
        assert [text.get_text() for text in figure.texts] == ["A", "B"]
        events = event_table(source_trace(trace_data, 9), times, trace_data["dt"])
        band = next(patch for patch in trace_axis.patches
                    if patch.get_gid() == "raw-noise-reference-band")
        bounds = trace_axis.transData.inverted().transform_bbox(band.get_window_extent())
        assert bounds.y0 == pytest.approx(events["raw_med"] - 3 * events["raw_sd"])
        assert bounds.y1 == pytest.approx(events["raw_med"] + 3 * events["raw_sd"])
        annotations = {text.get_gid(): text for text in trace_axis.texts if text.get_gid()}
        assert set(annotations) == {
            "detected-event-label", "example-event-amplitude",
            "event-amplitude-label", "raw-noise-reference-label",
        }
        label = annotations["detected-event-label"]
        assert label.get_text() == "detected event"
        assert label.get_color() == "#eb6834"
        points = trace_axis.collections[0].get_offsets()
        assert any(np.allclose(label.xy, point) for point in points)
        detected = (events["t"] >= times[0] + 900) & (events["t"] < times[0] + 920)
        np.testing.assert_array_equal(points[:, 0], events["t"][detected] - (times[0] + 900))
        selected = np.flatnonzero(detected & np.isfinite(events["amp_raw"]))
        selected = int(selected[np.argmax(events["amp_raw"][selected])])
        arrow = annotations["example-event-amplitude"]
        raw = source_trace(trace_data, 9)
        peak = raw[events["peak_idx"][selected]]
        detection = events["idx"][selected]
        pre_a = int(round(0.06 / trace_data["dt"]))
        pre_b = int(round(0.02 / trace_data["dt"]))
        baseline = np.nanmedian(raw[max(0, detection - pre_a):max(1, detection - pre_b)])
        assert arrow.xy[1] == pytest.approx(peak)
        assert arrow.xyann[1] == pytest.approx(baseline, abs=1e-6)
        assert (arrow.xy[1] - arrow.xyann[1]) / events["raw_sd"] == pytest.approx(
            events["amp_raw"][selected]
        )
        renderer = figure.canvas.get_renderer()
        amplitude_bounds = annotations["event-amplitude-label"].get_window_extent(renderer)
        peak_y = trace_axis.transData.transform(arrow.xy)[1]
        pixels_per_point = figure.dpi / 72
        assert 0 < amplitude_bounds.y1 - peak_y < 4 * pixels_per_point
        assert amplitude_bounds.y1 < trace_axis.transData.transform(points[0])[1]
        noise_bounds = annotations["raw-noise-reference-label"].get_window_extent(renderer)
        assert 6 * pixels_per_point < noise_bounds.y0 - band.get_window_extent().y1 < (
            9 * pixels_per_point
        )
        trace_pixels = trace_axis.transData.transform(
            np.column_stack((trace_axis.lines[0].get_xdata(), trace_axis.lines[0].get_ydata()))
        )
        for bounds in (amplitude_bounds, noise_bounds):
            beneath = (trace_pixels[:, 0] >= bounds.x0) & (trace_pixels[:, 0] <= bounds.x1)
            assert np.nanmax(trace_pixels[beneath, 1]) + 2 < bounds.y0

        render_panel_g(session, example, metrics, summary, tmp_path)
        figure = captured["figure7_panelG_slap2_glutamate"]
        assert len(figure.axes) == 5
        axes = {axis.get_gid(): axis for axis in figure.axes if axis.get_gid()}
        assert "class-footprints-DMD1" not in axes
        footprints = [axes["class-footprints-DMD2"]]
        archive = axes["archive-class-feature-space"]
        figure.canvas.draw()
        histogram_axes = [axis for name, axis in axes.items()
                          if name.startswith("class-amplitudes-")]
        assert len(histogram_axes) == 3
        for cls, (dmd, roi) in class_examples(example).items():
            axis = axes[f"class-amplitudes-{cls.lower().replace(' ', '-')}"]
            trace_data = session["traces"][dmd]
            events = event_table(source_trace(trace_data, roi),
                                 trace_data["ts"], trace_data["dt"])
            amplitudes = events["amp_raw"][np.isfinite(events["amp_raw"])]
            expected, _ = np.histogram(
                np.clip(amplitudes, -2, 14 - 1e-6), bins=np.arange(-2, 14.01, 0.25),
            )
            assert len(axis.patches) == 66
            assert axis.patches[0].get_x() == -2
            assert axis.patches[0].get_width() == 4
            assert axis.patches[1].get_x() == 4
            assert axis.patches[1].get_width() == 10
            np.testing.assert_array_equal(
                [bar.get_height() for bar in axis.patches[2:]], expected,
            )
            assert len(axis.texts) == 2
            percentages = [
                f"{100 * (amplitudes < 2).mean():.0f} %",
                f"{100 * (amplitudes >= 4).mean():.0f} %",
            ]
            assert all(text.get_text().endswith(value)
                       for text, value in zip(axis.texts, percentages, strict=True))
            assert all("2–4" not in text.get_text() for text in axis.texts)
        assert all(axis.get_position().y0 > footprint.get_position().y1
                   for axis in histogram_axes for footprint in footprints)
        assert footprints[0].get_position().x1 < archive.get_position().x0
        assert footprints[0].get_position().y0 < archive.get_position().y1
        assert footprints[0].get_position().y1 > archive.get_position().y0
        assert all(axis.get_position().y0 > archive.get_position().y1
                   for axis in histogram_axes)
        assert sorted(len(collection.get_offsets()) for collection in archive.collections) == [
            665, 830, 1026,
        ]
        assert archive.get_title() == ""
        panel_labels = {
            text.get_text(): text for text in figure.texts
            if (text.get_gid() or "").startswith("panel-label-")
        }
        assert list(panel_labels) == list("CDEFG")
        original_bounds = archive.get_subplotspec().get_position(figure)
        assert archive.get_position().bounds == pytest.approx(original_bounds.bounds)
        assert panel_labels["F"].get_position()[1] == pytest.approx(
            panel_labels["G"].get_position()[1]
        )
        assert archive.get_legend() is not None
        figure.canvas.draw()
        renderer = figure.canvas.get_renderer()
        histogram_label_bottom = min(
            axis.xaxis.label.get_window_extent(renderer).y0 for axis in histogram_axes
        )
        for text in figure.texts:
            if text.get_text() in {"F", "G"}:
                assert text.get_window_extent(renderer).y1 < histogram_label_bottom
        for field in footprints:
            assert field.get_position().height * figure.get_figheight() <= 1.45
            assert field.get_tightbbox(renderer).y1 < histogram_label_bottom
        titles = [text for text in figure.texts
                  if (text.get_gid() or "").startswith("compartment-title-")]
        assert len(titles) == 1
        assert titles[0].get_gid() == "compartment-title-DMD2"
        for field, letter, title in zip(footprints, "F", titles, strict=True):
            image_top = field.get_window_extent(renderer).y1
            assert image_top < panel_labels[letter].get_window_extent(renderer).y0
            assert image_top < title.get_window_extent(renderer).y0
        assert len(archive.lines) == 3
        assert len(footprints[0].lines) == 3
        for dmd, roi in ((2, 1), (2, 21), (2, 26)):
            suffix = f"source-DMD{dmd}-{roi}"
            point = next(line for line in archive.lines if line.get_gid().endswith(suffix))
            field = axes[f"class-footprints-DMD{dmd}"]
            spatial = next(line for line in field.lines if line.get_gid().endswith(suffix))
            for getter in ("get_marker", "get_markersize", "get_markerfacecolor",
                           "get_markeredgecolor", "get_markeredgewidth"):
                assert getattr(point, getter)() == getattr(spatial, getter)()
            assert point.get_markeredgecolor() == "white"
            assert len(point.get_path_effects()) == len(spatial.get_path_effects()) == 2
            row = example.loc[example.dmd.eq(dmd) & example.roi.eq(roi)].iloc[0]
            np.testing.assert_allclose(point.get_xdata(), [100 * row.frac_events_lt2sd])
            np.testing.assert_allclose(point.get_ydata(), [100 * row.frac_events_gt4sd])
        assert {text.get_text() for text in archive.texts} == {"1", "21", "26"}
        assert not any(line.get_visible()
                       for line in archive.get_xgridlines() + archive.get_ygridlines())
        for dmd, footprint in zip((2,), footprints, strict=True):
            y0, y1, x0, x1 = coverage_bbox(session["planes"][dmd][2])
            overlays = {image.get_gid(): image for image in footprint.images if image.get_gid()}
            assert len(overlays) == 3
            for cls in CLASS_ORDER:
                name = f"filled-rois-DMD{dmd}-{cls.lower().replace(' ', '-')}"
                image = overlays[name]
                assert image.get_interpolation() == "nearest"
                actual = np.asarray(image.get_array())
                expected_mask = np.logical_or.reduce([
                    session["planes"][dmd][2][int(roi)][y0:y1, x0:x1]
                    for roi in example.loc[
                        example.dmd.eq(dmd) & example.quality_class.eq(cls), "roi"
                    ]
                ])
                np.testing.assert_array_equal(actual[:, :, 3] > 0, expected_mask)
                np.testing.assert_allclose(actual[expected_mask], np.tile(
                    to_rgba(CLASS_COLORS[cls], 0.55), (int(expected_mask.sum()), 1)
                ))
        assert class_examples(example) == {
            "Low SNR": (2, 26), "Intermediate": (2, 21), "High SNR": (2, 1),
        }

        render_panel_k(metrics, pd.DataFrame(), tmp_path)
        figure = captured["figure7_panelK_slap2_glutamate"]
        assert len(figure.axes) == 1
        axis = figure.axes[0]
        assert [text.get_text() for text in figure.texts] == ["H"]
        assert axis.get_gid() == "three-class-composition"
        assert not figure.legends
        assert axis.get_legend() is None
        assert axis.get_ylim() == (0, 100)
        assert [text.get_text() for text in axis.get_xticklabels()] == list(
            class_composition_summary(metrics).label
        )
        assert len(axis.containers) == 3
        table = class_composition_summary(metrics)
        for cls, container in zip(CLASS_ORDER, axis.containers, strict=True):
            assert len(container) == 24
            np.testing.assert_allclose([bar.get_height() for bar in container], table[cls])
        np.testing.assert_allclose(
            np.sum([[bar.get_height() for bar in bars] for bars in axis.containers], axis=0),
            100,
        )
        mouse_ids = [text for text in axis.texts
                     if (text.get_gid() or "").startswith("mouse-id-")]
        assert len(mouse_ids) == 8
        assert {text.get_position()[1] for text in mouse_ids} == {-0.57}
        assert {text.get_text() for text in axis.texts
                if (text.get_gid() or "").startswith("session-")} == {"Date", "Mouse ID"}
        groups = {line.get_gid(): line for line in axis.lines}
        assert len(groups) == 8
        positions = np.array([bar.get_x() + bar.get_width() / 2 for bar in axis.containers[0]])
        for text in mouse_ids:
            subject = text.get_gid().removeprefix("mouse-id-")
            rows = table.index[table.group.eq("Session") & table.subject.astype(str).eq(subject)]
            expected = positions[rows]
            assert text.get_position()[0] == pytest.approx(expected.mean())
            np.testing.assert_allclose(
                groups[f"mouse-group-{subject}"].get_xdata(),
                [expected.min() - 0.4, expected.min() - 0.4,
                 expected.max() + 0.4, expected.max() + 0.4],
            )
        figure.canvas.draw()
        renderer = figure.canvas.get_renderer()
        headers = sorted(
            (text.get_window_extent(renderer) for text in axis.texts
             if text.get_position()[1] == 1.18),
            key=lambda bounds: bounds.x0,
        )
        assert len(headers) == 4
        assert all(left.x1 < right.x0 for left, right in zip(headers, headers[1:], strict=False))
        mouse_bounds = sorted((text.get_window_extent(renderer) for text in mouse_ids),
                              key=lambda bounds: bounds.x0)
        assert all(left.x1 < right.x0 for left, right in
                   zip(mouse_bounds, mouse_bounds[1:], strict=False))
        date_bottom = min(text.get_window_extent(renderer).y0
                          for text in axis.get_xticklabels()[4:])
        assert all(line.get_window_extent(renderer).y1 < date_bottom for line in axis.lines)
        assert not any("stimulus context" in text.get_text().lower() for text in figure.texts)
    finally:
        for figure in captured.values():
            plt.close(figure)


def test_raw_event_markers_use_raw_peaks_not_filtered_detection_times() -> None:
    trace = np.array([0, 0, 1, 4, 2, 0, 0, np.nan, 3, 5, 1, 0], dtype=float)
    detected = np.array([2, 8, 11])
    peaks = raw_event_peak_indices(trace, detected, 0.02)
    np.testing.assert_array_equal(peaks, [3, 9, 11])
    for detected_index, peak_index in zip(detected, peaks, strict=True):
        assert trace[peak_index] == np.nanmax(trace[detected_index:detected_index + 3])


def test_missing_samples_do_not_create_amplitudes() -> None:
    assert sampling_interval(np.array([0.0, 0.005, np.nan, 0.015, 0.020])) == pytest.approx(0.005)
    amplitudes = event_amplitudes_raw(np.full(100, np.nan), np.array([50]), 0.005, 1.0)
    assert np.isnan(amplitudes).all()
    with pytest.raises(ValueError, match="sampling interval"):
        sampling_interval(np.array([1.0, 0.0]))


def test_notebook_is_thin_offline_and_has_no_saved_outputs() -> None:
    notebook_path = REPO_ROOT / "figure_sources/python/slap2_glutamate_figure7_panels.ipynb"
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    code = "\n".join(
        "".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code"
    )
    assert notebook_path.stat().st_size < 100_000
    assert "load_example_snapshot" in code
    assert "download.download" not in code
    assert "qc.compute(" not in code
    for cell in notebook["cells"]:
        assert not cell.get("outputs")
        assert cell.get("execution_count") is None


def test_publication_figure_builds_without_network(tmp_path: Path, monkeypatch, capsys) -> None:
    import socket

    def reject_network(*args, **kwargs):
        raise AssertionError("The figure build must not open network connections.")

    monkeypatch.setattr(socket, "socket", reject_network)
    output = write_slap2_glutamate_figure(tmp_path / "figure-07.svg")
    text = output.read_text(encoding="utf-8")
    assert "SLAP2 glutamate signal-quality analysis" in text
    root = ET.fromstring(text)
    namespace = "{http://www.w3.org/2000/svg}"
    assert len(root.findall(f"{namespace}svg")) == 3
    assert "data:image/svg+xml;base64," not in text
    identifiers = [node.get("id") for node in root.iter() if node.get("id")]
    assert len(identifiers) == len(set(identifiers))
    assert {node.get("data-panel-letter") for node in root.iter()
            if node.get("data-panel-letter")} == set("ABCDEFGH")
    visible = " ".join("".join(node.itertext()) for node in root.iter()
                       if node.tag == f"{namespace}text")
    assert not re.search(r"\bn\s*=|\b[\d,]+\s+events\b", visible)
    assert "Single-synapse" not in visible
    assert not list(tmp_path.glob("figure7_panel*.png"))
    assert len(list(tmp_path.glob("figure7_panel*.svg"))) == 5
    source_panel = (tmp_path / "figure7_panelC_slap2_glutamate.svg").read_text(encoding="utf-8")
    assert 'id="example-trace-DMD1-9"' in source_panel
    assert 'id="single-synapse-footprint-DMD1-9"' in source_panel
    assert 'id="example-event-amplitude"' in source_panel
    assert 'id="raw-noise-reference-band"' in source_panel
    assert "detected event" in source_panel
    assert "events in 20 s" not in source_panel
    assert "class-footprints-DMD" not in source_panel
    distribution_panel = (tmp_path / "figure7_panelG_slap2_glutamate.svg").read_text()
    assert 'id="archive-class-feature-space"' in distribution_panel
    assert 'id="class-footprints-DMD2"' in distribution_panel
    assert 'id="class-footprints-DMD1"' not in distribution_panel
    gradient_panel = (tmp_path / "figure7_panelG_slap2_glutamate_gradient.svg").read_text()
    assert 'id="class-footprints-DMD2"' in gradient_panel
    assert 'id="class-footprints-DMD1"' not in gradient_panel
    assert "1. Detect" not in distribution_panel and "2. Measure" not in distribution_panel
    assert "Intermediate" in distribution_panel
    assert "k-means" not in distribution_panel
    assert "All sessions" not in distribution_panel
    assert "\u2460" not in distribution_panel and "\u2461" not in distribution_panel
    prevalence_panel = (tmp_path / "figure7_panelK_slap2_glutamate.svg").read_text()
    assert 'id="three-class-composition"' in prevalence_panel
    assert 'id="composition-0-intermediate"' in prevalence_panel
    assert 'id="legend_' not in prevalence_panel
    assert "stimulus context" not in prevalence_panel
    assert "different extraction pipelines" not in prevalence_panel
    first_build = {asset.name: asset.read_bytes() for asset in tmp_path.iterdir()}
    write_slap2_glutamate_figure(output)
    assert {asset.name: asset.read_bytes() for asset in tmp_path.iterdir()} == first_build
    assert capsys.readouterr().out.isascii()