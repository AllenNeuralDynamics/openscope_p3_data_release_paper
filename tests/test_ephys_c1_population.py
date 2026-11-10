import copy
import json
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
import pytest

from openscope_p3_publication import ephys_c1_pseudocontext_figure
from openscope_p3_publication.ephys_c1_population import (
    DIRECTORY,
    load_c1_population,
    validate_c1_population,
)
from openscope_p3_publication.ephys_c1_pseudocontext import load_pseudo
from openscope_p3_publication.ephys_c1_pseudocontext_figure import (
    build_ephys_c1_pseudocontext,
    prepare_pseudo_cohort,
)
from openscope_p3_publication.standard_oddball_cohort import ROOT
from openscope_p3_publication.standard_oddball_cohort_figure import REGION_ORDER
from openscope_p3_publication.standard_oddball_examples import load_example_spikes
from openscope_p3_publication.standard_oddball_neuropixels import load_diagnostic
from openscope_p3_publication.standard_oddball_ordering import load_context_order
from openscope_p3_publication.standard_oddball_population import load_population


@pytest.fixture(scope="module")
def display():
    return load_c1_population()


@pytest.fixture(scope="module")
def original():
    data = load_diagnostic()
    return load_population(data, load_example_spikes(data)["events"][1])


def test_frozen_c1_maps_share_original_units_order_and_trial_identity(display, original):
    _, _, provenance = load_pseudo()
    session = next(
        s for s in provenance["sessions"] if s["session_id"] == original["session_id"]
    )
    assert display["heatmaps"].shape == (3, 203, 300)
    assert display["payload"]["unit_ids"] == [u["id"] for u in original["units"]]
    np.testing.assert_array_equal(display["order"], load_context_order(original))
    for condition in ("pre", "post"):
        trials = display["trials"][condition]
        assert len(trials) == 34
        assert [t["row_index"] for t in trials] == session["trials"][f"{condition}_indices"]
    pre, post = (display["trials"][c] for c in ("pre", "post"))
    assert max(t["onset_seconds"] for t in pre) < min(t["onset_seconds"] for t in post)
    assert display["time"][0] == pytest.approx(-0.7475)
    assert display["time"][-1] == pytest.approx(0.7475)
    assert np.diff(display["time"]) == pytest.approx(np.full(299, 0.005))


def test_c1_heatmaps_subtract_separate_baselines_before_post_minus_pre(display):
    delta = display["rates"] - display["baselines"][..., None]
    order = display["order"]
    np.testing.assert_array_equal(display["heatmaps"][0], delta[0, order])
    np.testing.assert_array_equal(display["heatmaps"][1], delta[1, order])
    np.testing.assert_array_equal(display["heatmaps"][2], (delta[1] - delta[0])[order])
    np.testing.assert_array_equal(
        display["heatmaps"][2], display["heatmaps"][1] - display["heatmaps"][0],
    )
    assert not np.array_equal(display["baselines"][0], display["baselines"][1])


@pytest.mark.parametrize("change", ["order", "trials", "unit_ids", "parameters", "rates"])
def test_c1_population_rejects_changed_identity_or_pooled_replay(display, original, change):
    payload = copy.deepcopy(display["payload"])
    if change == "order":
        payload["order"] = payload["order"][::-1]
    elif change == "trials":
        payload["trials"]["pre"].pop()
    elif change == "unit_ids":
        payload["unit_ids"][0] = -1
    elif change == "parameters":
        payload["parameters"]["tau_seconds"] = 0.01
    else:
        payload["mean_hz"][0][0][0] += 1
    with pytest.raises((ValueError, AssertionError)):
        validate_c1_population(payload, original, display["order"])


def test_c1_population_checksum_is_verified(tmp_path):
    for name in ("population.json", "provenance.json"):
        (tmp_path / name).write_bytes((DIRECTORY / name).read_bytes())
    with (tmp_path / "population.json").open("a") as stream:
        stream.write(" ")
    with pytest.raises(ValueError, match="checksum"):
        load_c1_population(tmp_path)


def test_pseudo_mouse_bootstrap_uses_included_sessions_and_shared_denominators():
    units, expected, _ = load_pseudo()
    cohort = prepare_pseudo_cohort(units)
    areas, mice = cohort["areas"], cohort["mice"]
    assert areas.brain_area.tolist() == list(REGION_ORDER)
    assert areas.bootstrap_status.eq("estimated").all()
    assert areas.n_joint_testable.sum() == 6642
    assert areas.n_q1_responsive.sum() == 619
    assert areas.n_q2_responsive.sum() == 693
    assert areas.n_joint_responsive.sum() == 140
    for screen in ("q1", "q2", "joint"):
        np.testing.assert_array_equal(
            areas[f"n_{screen}_responsive"], expected[f"n_{screen}_responsive"],
        )
        np.testing.assert_array_equal(
            areas[f"fraction_{screen}_responsive"],
            areas[f"n_{screen}_responsive"] / areas.n_joint_testable,
        )
        for area in areas.itertuples():
            mouse = mice.loc[mice.brain_area.eq(area.brain_area)]
            assert mouse.n_joint_testable.sum() == area.n_joint_testable
            assert mouse[f"n_{screen}_responsive"].sum() == getattr(
                area, f"n_{screen}_responsive",
            )
        lower = areas[f"fraction_{screen}_responsive_ci95_low"]
        upper = areas[f"fraction_{screen}_responsive_ci95_high"]
        assert ((lower >= 0) & (upper <= 1) & (lower <= upper)).all()
    pd.testing.assert_frame_equal(areas, prepare_pseudo_cohort(units)["areas"])


def test_supplement_is_deterministic_accessible_and_has_shared_scale(
    tmp_path, display, monkeypatch,
):
    observed = []
    save = ephys_c1_pseudocontext_figure.save_diagnostic_svg

    def observe_layout(fig, *args, **kwargs):
        fig.canvas.draw()
        objects = {ax.get_gid(): ax for ax in fig.axes if ax.get_gid()}
        reference_size = objects["population-heatmap-pre"].xaxis.label.get_fontsize()
        for key in ("panel-D-pre-post-Q1-positive-means", "cohort-responsiveness-proportions"):
            axis = objects[key]
            assert axis.xaxis.label.get_fontsize() == reference_size
            assert axis.yaxis.label.get_fontsize() == reference_size
            assert all(
                text.get_fontsize() == reference_size
                for text in (
                    *axis.get_xticklabels(), *axis.get_yticklabels(),
                    *axis.get_legend().get_texts(),
                )
            )
        axes = {ax.get_gid(): ax.get_position() for ax in fig.axes if ax.get_gid()}
        label_left = objects["cohort-responsiveness-proportions"].yaxis.label.get_window_extent().x0
        mean_right = objects["panel-D-pre-post-Q1-positive-means"].get_window_extent().x1
        observed.append((
            axes, [(text.get_position(), text.get_text()) for text in fig.texts],
            label_left - mean_right,
        ))
        save(fig, *args, **kwargs)

    monkeypatch.setattr(ephys_c1_pseudocontext_figure, "save_diagnostic_svg", observe_layout)
    output = tmp_path / "supplement.svg"
    audit = tmp_path / "audit"
    paths = build_ephys_c1_pseudocontext(output, audit)
    before = [p.read_bytes() for p in paths]
    build_ephys_c1_pseudocontext(output, audit)
    assert [p.read_bytes() for p in paths] == before
    root = ET.parse(output).getroot()
    assert root.get("role") == "img"
    assert root.get("data-population-units") == "203"
    assert root.get("data-joint-testable") == "6642"
    assert root.get("data-shared-color-limit-hz") == "31"
    assert root.get("data-mean-units") == "51"
    assert root.get("data-mean-selection") == "actual-context-positive-Q1-only"
    ids = {e.get("id") for e in root.iter()}
    for condition in ("pre", "post", "post-minus-pre"):
        assert f"population-heatmap-{condition}" in ids
    for letter in "ABCDE":
        assert f"panel-label-{letter}" in ids
    for condition in ("pre", "post"):
        assert f"mean-Q1-positive-{condition}" in ids
        assert f"mean-sem-{condition}" in ids
    texts = [e.text for e in root.iter() if e.tag.rsplit("}", 1)[-1] == "text"]
    assert "Rastermap rank" in texts
    assert "\u0394 Firing rate (spikes/s)" in texts
    assert "Figure 9 Rastermap rank" not in texts
    assert "C1 repeat negative control | Neuropixels" not in texts
    assert not any(text and text.startswith("Figure 9 example population") for text in texts)
    assert not any(text and text.startswith("Positive context Q1") for text in texts)
    for axes, labels, label_gap in observed:
        pre = axes["population-heatmap-pre"]
        post = axes["population-heatmap-post"]
        difference = axes["population-heatmap-post-minus-pre"]
        means = axes["panel-D-pre-post-Q1-positive-means"]
        bars = axes["cohort-responsiveness-proportions"]
        centers = [(box.x0 + box.x1) / 2 for box in (pre, post, difference)]
        assert (means.x0 + means.x1) / 2 == pytest.approx((centers[0] + centers[1]) / 2)
        assert (bars.x0 + bars.x1) / 2 == pytest.approx((centers[1] + centers[2]) / 2)
        assert means.x1 < bars.x0
        assert label_gap > 0
        assert post.y0 - means.y1 >= 0.17
        assert difference.y0 - bars.y1 >= 0.17
        assert bars.width < 0.3
        assert {text for position, text in labels if position[1] < pre.y0} == {
            "D", "E", "Regional pseudo-Q1 / Q2 / Both",
        }
    for screen in ("q1", "q2", "joint"):
        assert f"cohort-mouse-bootstrap-ci95-{screen}" in ids
        for area in REGION_ORDER:
            assert f"cohort-pooled-{screen}-{area}" in ids
    provenance = json.loads((audit / "provenance.json").read_text())
    assert provenance["heatmap_shape"] == [3, 203, 300]
    assert provenance["bootstrap"]["replicates"] == 10000
    assert provenance["display"]["finite_samples"] == 3 * 203 * 300
    assert provenance["display"]["unavailable_samples"] == 0
    assert float(root.get("data-shared-color-limit-hz")) == provenance["display"]["limit"]
    units = pd.read_csv(audit / "display-units.csv")
    np.testing.assert_array_equal(
        units.nwb_unit_id,
        np.asarray(display["payload"]["unit_ids"])[display["order"]],
    )
    assert units.mean_selected.sum() == 51
    alternate_audit = ROOT / "figure_sources/derived/ephys-c1-context-comparison"
    assert (audit / "mean-traces.csv").read_bytes() == (
        alternate_audit / "mean-traces.csv"
    ).read_bytes()
    alternate = json.loads((alternate_audit / "provenance.json").read_text())
    assert provenance["mean_unit_count"] == 51
    assert provenance["selected_unit_ids"] == alternate["selected_unit_ids"]


def test_supplement_is_wired_into_manuscript_and_default_build():
    text = (ROOT / "index.md").read_text()
    assert text.count(":label: fig-ephys-c1-pseudocontext") == 1
    assert "**Supplementary Figure 7.** Ephys C1 repeat negative control" in text
    assert (
        text.index("# Supplementary Figure 6:")
        < text.index("# Supplementary Figure 7:")
        < text.index("# Supplementary Text 1:")
    )
    figure = text.split(
        ":::{figure} ./images/figures/generated/ephys-c1-pseudocontext.svg", 1,
    )[1].split(":::", 1)[0]
    assert ":enumerated: false" in figure and ":alt:" in figure
    assert "619/6,642" in figure and "693/6,642" in figure and "140/6,642" in figure
    assert "not assumed to be expected standards" in figure
    assert "10,000 resamples" in figure
    assert "**D,** Pre-C1" in figure and "**E,** Regional pseudo-Q1" in figure
    assert "**B, bottom,**" not in figure and "**D, below C,**" not in figure
    assert "same 51 visual units" in figure and "no Q2 restriction" in figure
    assert "c1_pseudocontext_paths = build_ephys_c1_pseudocontext()" in (
        ROOT / "src/openscope_p3_publication/figures.py"
    ).read_text()
