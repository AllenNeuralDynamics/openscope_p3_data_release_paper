import copy
import json
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
import pytest

from openscope_p3_publication.ephys_c1_context_figure import (
    build_ephys_c1_context_comparison,
    prepare_context_comparison,
)
from openscope_p3_publication.ephys_c1_population import load_c1_population
from openscope_p3_publication.ephys_c1_pseudocontext_figure import (
    AUDIT_DIRECTORY as ORIGINAL_AUDIT,
)
from openscope_p3_publication.ephys_c1_pseudocontext_figure import OUTPUT as ORIGINAL_OUTPUT
from openscope_p3_publication.standard_oddball_cohort import ROOT
from openscope_p3_publication.standard_oddball_column import column_data
from openscope_p3_publication.standard_oddball_examples import load_example_spikes
from openscope_p3_publication.standard_oddball_neuropixels import load_diagnostic
from openscope_p3_publication.standard_oddball_population import load_population


@pytest.fixture(scope="module")
def inputs():
    data = load_diagnostic()
    examples = load_example_spikes(data)
    original = load_population(data, examples["events"][1])
    return data, original, load_c1_population(), examples


def test_context_variant_reuses_exact_figure9_map_order_and_scale(inputs):
    data, original, split, examples = inputs
    prepared = prepare_context_comparison(data, original, split)
    figure9 = column_data(data, original, examples)
    assert prepared["heatmaps"].shape == (3, 203, 300)
    np.testing.assert_array_equal(prepared["heatmaps"][0], split["heatmaps"][0])
    np.testing.assert_array_equal(
        prepared["heatmaps"][1], figure9["ordered_heatmaps"][0],
    )
    np.testing.assert_array_equal(prepared["heatmaps"][2], split["heatmaps"][1])
    np.testing.assert_array_equal(prepared["order"], figure9["order"])
    assert prepared["display"]["limit"] == figure9["heatmap"]["limit"] == 44
    assert prepared["display"]["clipped_samples_by_condition"] == (
        np.abs(prepared["heatmaps"]) > 44
    ).sum(axis=(1, 2)).tolist()
    assert [len(trials) for trials in prepared["trials"]] == [34, 34, 34]
    pre, context, post = prepared["trials"]
    assert max(t["onset_seconds"] for t in pre) < min(t["onset_seconds"] for t in context)
    assert max(t["onset_seconds"] for t in context) < min(t["onset_seconds"] for t in post)


def test_variant_means_use_same_q1_only_pool_and_separate_display_baselines(inputs):
    data, original, split, _ = inputs
    prepared = prepare_context_comparison(data, original, split)
    expected = (
        np.isfinite(data.statistics["q1_p"][1])
        & np.isfinite(data.statistics["q1_modulation"][1])
        & (data.statistics["q1_p"][1] < 0.05)
        & (data.statistics["q1_modulation"][1] > 0.1)
    )
    np.testing.assert_array_equal(prepared["positive"], expected)
    assert expected.sum() == 51
    selected = (split["rates"] - split["baselines"][..., None])[:, expected]
    np.testing.assert_array_equal(prepared["mean"], selected.mean(axis=1))
    np.testing.assert_array_equal(
        prepared["sem"], selected.std(axis=1, ddof=1) / np.sqrt(51),
    )
    assert prepared["mean"].shape == prepared["sem"].shape == (2, 300)
    assert not np.array_equal(prepared["mean"], split["rates"][:, expected].mean(axis=1))
    changed = copy.deepcopy(data)
    changed.statistics["q2_delta_p"][:] = np.nan
    changed.statistics["q2_delta_modulation"][:] = np.nan
    np.testing.assert_array_equal(
        prepare_context_comparison(changed, original, split)["positive"], expected,
    )


def test_variant_q1_selection_uses_strict_positive_finite_thresholds(inputs):
    data, original, split, _ = inputs
    changed = copy.deepcopy(data)
    changed.statistics["q1_p"][1, :6] = [0.049, 0.05, 0.01, np.nan, 0.01, 0.01]
    changed.statistics["q1_modulation"][1, :6] = [0.101, 0.5, 0.1, 0.5, np.nan, -0.5]
    prepared = prepare_context_comparison(changed, original, split)
    assert prepared["positive"][:6].tolist() == [True, False, False, False, False, False]
    changed.statistics["q1_p"][1, :] = 1
    with pytest.raises(ValueError, match="At least two"):
        prepare_context_comparison(changed, original, split)


@pytest.mark.parametrize("change", ["units", "session", "asset", "parameters", "order"])
def test_variant_rejects_misaligned_sources(inputs, change):
    data, original, split, _ = inputs
    split = copy.deepcopy(split)
    if change == "units":
        split["payload"]["unit_ids"] = split["payload"]["unit_ids"][::-1]
    elif change == "session":
        split["payload"]["session_id"] = "other"
    elif change == "asset":
        split["payload"]["asset"] = {}
    elif change == "parameters":
        split["payload"]["parameters"]["bin_seconds"] = 0.01
    else:
        split["order"] = split["order"][::-1]
    with pytest.raises(ValueError, match="disagree"):
        prepare_context_comparison(data, original, split)


def test_variant_preserves_original_is_deterministic_and_saves_exact_audits(tmp_path, inputs):
    preserved = [
        ORIGINAL_OUTPUT, ROOT / "index.md",
        *sorted(ORIGINAL_AUDIT.glob("*")),
    ]
    before = [path.read_bytes() for path in preserved]
    output, audit = tmp_path / "variant.svg", tmp_path / "audit"
    paths = build_ephys_c1_context_comparison(output, audit)
    first = [path.read_bytes() for path in paths]
    build_ephys_c1_context_comparison(output, audit)
    assert [path.read_bytes() for path in paths] == first
    assert [path.read_bytes() for path in preserved] == before
    root = ET.parse(output).getroot()
    assert root.get("data-conditions") == "pre,context,post"
    assert root.get("data-shared-color-limit-hz") == "44"
    assert root.get("data-mean-units") == "51"
    assert root.get("data-mean-selection") == "actual-context-positive-Q1-only"
    ids = {e.get("id") for e in root.iter()}
    for condition in ("pre", "context", "post"):
        assert f"population-heatmap-{condition}" in ids
    assert "population-heatmap-post-minus-pre" not in ids
    assert "panel-B-pre-post-Q1-positive-means" in ids
    assert "panel-C-regional-pseudo-responsiveness" in ids
    assert {letter for letter in "ABCD" if f"panel-label-{letter}" in ids} == set("ABC")
    for condition in ("pre", "post"):
        assert f"mean-Q1-positive-{condition}" in ids
        assert f"mean-sem-{condition}" in ids
    selection = pd.read_csv(audit / "unit-selection.csv", float_precision="round_trip")
    prepared = prepare_context_comparison(*inputs[:3])
    np.testing.assert_array_equal(
        selection.nwb_unit_id,
        np.asarray(prepared["unit_ids"])[prepared["order"]],
    )
    np.testing.assert_array_equal(
        selection.mean_selected, prepared["positive"][prepared["order"]],
    )
    traces = pd.read_csv(audit / "mean-traces.csv", float_precision="round_trip")
    for i, condition in enumerate(("pre", "post")):
        np.testing.assert_array_equal(traces[f"{condition}_mean_hz"], prepared["mean"][i])
        np.testing.assert_array_equal(traces[f"{condition}_sem_hz"], prepared["sem"][i])
    regions = pd.read_csv(audit / "regions.csv", float_precision="round_trip")
    pd.testing.assert_frame_equal(
        regions, pd.read_csv(ORIGINAL_AUDIT / "areas.csv", float_precision="round_trip"),
    )
    provenance = json.loads((audit / "provenance.json").read_text())
    assert provenance["mean_unit_count"] == 51
    assert provenance["selected_unit_ids"] == np.asarray(prepared["unit_ids"])[
        prepared["positive"]
    ].tolist()


def test_alternative_is_registered_separately_without_replacing_manuscript_figure():
    manuscript = (ROOT / "index.md").read_text()
    assert "ephys-c1-pseudocontext.svg" in manuscript
    assert "ephys-c1-context-comparison.svg" not in manuscript
    build = (ROOT / "src/openscope_p3_publication/figures.py").read_text()
    assert "c1_pseudocontext_paths = build_ephys_c1_pseudocontext()" in build
    assert "c1_context_comparison_paths = build_ephys_c1_context_comparison()" in build
