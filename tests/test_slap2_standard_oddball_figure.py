"""Native optical geometry, per-DMD trial counts and four exact white SVG compositions."""

import json
from collections import Counter
from xml.etree import ElementTree as ET

import numpy as np
import pytest

from openscope_p3_publication import standard_oddball_matched_columns as matched
from openscope_p3_publication.mesoscope_standard_oddball import sha256
from openscope_p3_publication.mesoscope_standard_oddball_figure import cohort_curves
from openscope_p3_publication.slap2_standard_oddball import load_snapshot
from openscope_p3_publication.slap2_standard_oddball_figure import (
    build_slap2_standard_oddball,
    dmd_grouped_order,
)

NS = matched.NS


@pytest.fixture(scope="module")
def columns(tmp_path_factory):
    root = tmp_path_factory.mktemp("slap2-columns")
    return build_slap2_standard_oddball(root / "svg", root / "audit")


@pytest.fixture(scope="module")
def composites(tmp_path_factory):
    root = tmp_path_factory.mktemp("three-modality")
    return matched.build_three_modality_standard_oddball_columns(
        root / "svg", root / "audit", primary_only=True,
    )


def test_slap2_columns_have_native_geometry_two_panels_and_actual_trial_counts(columns):
    payload, _, _ = load_snapshot()
    for path in columns[:2]:
        root = ET.parse(path).getroot()
        has_cohort = root.get("data-signal") == "glutamate"
        assert root.get("width") == "54mm"
        assert root.get("height") == ("174mm" if has_cohort else "135mm")
        labels = root.findall(".//s:g[@id='panel-label-A']/s:text", NS)
        assert len(labels) == 1
        assert root.find(".//s:g[@id='panel-label-B']", NS) is not None
        assert (root.find(".//s:g[@id='panel-label-C']", NS) is not None) == has_cohort
        assert (
            root.find(".//s:g[@id='cohort-responsiveness-proportions']", NS) is not None
        ) == has_cohort
        assert root.get("data-eligible-roi-count") == "119"
        assert root.get("data-rastermap-fit-signal") == "glutamate"
        assert root.get("data-population-ordering") == "dmd-grouped-context-glutamate-rastermap"
        assert root.get("data-dmd-source-counts") == "79,40"
        expected_keys = [payload["roi_keys"][i] for i in dmd_grouped_order(payload)]
        assert root.get("data-population-order").split(",") == expected_keys
        assert root.find(".//s:g[@id='population-dmd-divider']", NS) is not None
        for dmd in ("DMD1", "DMD2"):
            assert root.find(f".//s:g[@id='population-dmd-label-{dmd}']", NS) is not None
        title = root.find(".//s:g[@id='example-trial-heatmap-1']", NS)
        assert "Unresponsive" in "".join(title.itertext())
        assert "Comparison" not in "".join(title.itertext())
        if has_cohort:
            assert root.get("data-cohort-groups") == "DMD1,DMD2"
        for condition in ("context", "control"):
            assert json.loads(root.get(f"data-{condition}-trial-counts-by-dmd")) == {
                d: len(w[condition]) for d, w in payload["trials_by_dmd"].items()
            }
        description = root.find("s:desc", NS).text
        assert "not calcium-specific SNR" in description
        assert "No interpolation across acquisition pauses" in description
        assert ("No SLAP2 cohort" in description) != has_cohort


def test_three_column_geometry_letters_and_opaque_white_canvas(composites):
    assert len(composites) == 2
    for path in composites[:-1]:
        root = ET.parse(path).getroot()
        is_main = root.get("data-mesoscope-signal") == "dff" and (
            root.get("data-slap2-signal") == "glutamate"
        )
        assert root.get("width") == ("174mm" if is_main else "170mm")
        assert root.get("height") == ("184mm" if is_main else "174mm")
        columns = root.findall("s:svg", NS)
        assert [c.get("id") for c in columns] == [
            "column-neuropixels", "column-mesoscope", "column-slap2",
        ]
        background = root.find("s:rect[@id='figure-background']", NS)
        assert background.get("fill") == "#ffffff" and background.get("fill-opacity") == "1"
        assert [float(background.get(k)) for k in ("width", "height")] == (
            list(map(float, root.get("viewBox").split()))[2:]
        )
        assert list(root).index(background) < list(root).index(columns[0])
        has_cohort = root.get("data-slap2-signal") == "glutamate"
        expected = ("ADG", "BEH", "CFI" if has_cohort else "CF")
        for i, (column, letters) in enumerate(zip(columns, expected, strict=True)):
            assert float(column.get("x")) / matched.POINTS_PER_MM == pytest.approx(
                58 * i + (4 if is_main else 0)
            )
            assert float(column.get("width")) / matched.POINTS_PER_MM == pytest.approx(54)
            texts = column.findall(".//s:text[@data-panel-letter]", NS)
            assert "".join(t.text for t in texts) == letters
            scale = 170 / 174 if is_main else 1
            assert all(float(t.get("font-size")) * scale == pytest.approx(9) for t in texts)
        assert root.get("data-slap2-cohort-panel") == ("present" if has_cohort else "absent")
        assert (root.find(".//s:text[@data-panel-letter='I']", NS) is not None) == has_cohort
        assert ("No SLAP2 cohort or panel I" in root.find("s:desc", NS).text) != has_cohort


def test_all_three_source_path_geometry_and_embedded_images_are_preserved(composites):
    for path in composites[:-1]:
        root = ET.parse(path).getroot()
        mesoscope = root.get("data-mesoscope-signal")
        slap2 = root.get("data-slap2-signal")
        sources = [
            matched.NEUROPIXELS,
            matched.OUTPUT_DIR / f"mesoscope-standard-oddball-90-{mesoscope}.svg",
            matched.OUTPUT_DIR / f"slap2-standard-oddball-90-{slap2}.svg",
        ]
        for column, source in zip(root.findall("s:svg", NS), sources, strict=True):
            original = ET.parse(source).getroot()
            for tag, attribute in (
                ("path", "d"), ("image", "{http://www.w3.org/1999/xlink}href"),
            ):
                assert Counter(n.get(attribute) for n in column.findall(f".//s:{tag}", NS)) == (
                    Counter(n.get(attribute) for n in original.findall(f".//s:{tag}", NS))
                )
        nodes = list(root.iter())
        ids = [n.get("id") for n in nodes if n.get("id") is not None]
        assert len(ids) == len(set(ids))
        for node in nodes:
            for value in node.attrib.values():
                assert all(m in ids for m in matched.URL_REFERENCE.findall(value))


def test_main_is_deterministic_and_source_backed(composites, tmp_path):
    again = matched.build_three_modality_standard_oddball_columns(
        tmp_path / "svg", tmp_path / "audit", primary_only=True,
    )
    assert [sha256(p) for p in composites] == [sha256(p) for p in again]
    audit = json.loads(composites[-1].read_text())
    assert len(audit["outputs"]) == 1
    assert audit["slap2_cohort_panel"] == {"glutamate": "present", "calcium": "absent"}
    assert audit["footprint_mm"] == [170, 174]
    assert audit["main_footprint_mm"] == [174, 184]
    for source in audit["sources"]:
        assert sha256(matched.ROOT / source["path"]) == source["sha256"]


def test_main_row_labels_and_shared_gradient_preserve_native_scales(composites):
    main = next(p for p in composites if p.name.endswith("dff-glutamate.svg"))
    root = ET.parse(main).getroot()
    rows = root.findall("s:text[@class='modality-row-label']", NS)
    assert [r.text for r in rows] == ["Single Unit", "All Units"]
    assert all(r.get("transform").startswith("rotate(-90 ") for r in rows)
    assert all(float(r.get("x")) > 0 for r in rows)
    legend = root.find("s:g[@id='shared-population-colorbar']", NS)
    assert legend.get("data-palette") == "RdBu_r"
    scales = legend.findall("s:text[@data-panel-scale]", NS)
    assert [(s.get("data-panel-scale"), float(s.get("data-limit")), s.get("data-unit"))
            for s in scales] == [("D", 44, "spikes/s"), ("E", 0.4, "%"), ("F", 1, "a.u.")]
    stops = legend.findall(".//s:stop", NS)
    assert len(stops) == 256
    assert stops[0].get("stop-color") == "#053061"
    assert stops[-1].get("stop-color") == "#67001f"
    assert float(legend.find("s:rect", NS).get("y")) / matched.POINTS_PER_MM > 174
    for path in composites[:-1]:
        if path != main:
            other = ET.parse(path).getroot()
            assert other.find("s:g[@id='shared-population-colorbar']", NS) is None


def test_population_delta_arrays_are_source_weighted_not_trial_pooled():
    payload, statistics, arrays = load_snapshot()
    assert len(payload["roi_keys_by_dmd"]["1"]) == 79
    assert len(payload["roi_keys_by_dmd"]["2"]) == 40
    for signal in ("glutamate", "calcium"):
        assert arrays[f"delta_{signal}"].shape == (2, 119, 301)
        assert np.isfinite(arrays[f"delta_{signal}"]).all()
        for i, key in enumerate(payload["examples"][signal]):
            index = payload["roi_keys"].index(key)
            for c, condition in enumerate(("context", "control")):
                np.testing.assert_array_equal(
                    arrays[f"delta_{signal}"][c, index],
                    arrays[f"examples_{signal}_{condition}_{i}"].mean(axis=0),
                )
        column = (
            "positive_joint" if payload["positive_examples_only"][signal] else "joint_responsive"
        )
        rows = statistics.loc[
            statistics.signal.eq(signal) & statistics.event_id.eq("orientation_90")
        ].set_index("roi_key").loc[payload["roi_keys"]]
        curves = cohort_curves(
            statistics.loc[statistics.event_id.eq("orientation_90")], arrays, signal,
            payload["roi_keys"], responsive_column=column,
        )
        for group, flag in (("positive", column), ("nonq2", "q2_nonsignificant")):
            selected = arrays[f"delta_{signal}"][:, rows[flag]].astype(np.float64)
            np.testing.assert_array_equal(curves[group]["mean"], selected.mean(axis=1))
            np.testing.assert_array_equal(
                curves[group]["sem"], selected.std(axis=1, ddof=1) / np.sqrt(selected.shape[1]),
            )


def test_dmd_grouping_preserves_relative_frozen_order_and_every_source():
    payload, _, _ = load_snapshot()
    order = dmd_grouped_order(payload)
    assert sorted(order) == list(range(119))
    assert all(payload["roi_keys"][i].startswith("DMD1:") for i in order[:79])
    assert all(payload["roi_keys"][i].startswith("DMD2:") for i in order[79:])
    for dmd, block in (("DMD1:", order[:79]), ("DMD2:", order[79:])):
        assert block == [i for i in payload["order"] if payload["roi_keys"][i].startswith(dmd)]
    with pytest.raises(ValueError, match="complete"):
        dmd_grouped_order({**payload, "order": payload["order"][:-1]})
