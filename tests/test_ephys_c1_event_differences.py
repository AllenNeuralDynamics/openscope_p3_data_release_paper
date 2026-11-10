import copy
import json
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
import pytest

from openscope_p3_publication import ephys_c1_event_differences as figure
from openscope_p3_publication.ephys_c1_event_populations import (
    DIRECTORY,
    EVENT_ORDER,
    baseline_bin_counts,
    load_event_differences,
    prepare_event_differences,
    validate_event_population,
)
from openscope_p3_publication.ephys_c1_population import load_c1_population
from openscope_p3_publication.standard_oddball_cohort import ROOT
from openscope_p3_publication.standard_oddball_examples import load_example_spikes
from openscope_p3_publication.standard_oddball_neuropixels import load_diagnostic


@pytest.fixture(scope="module")
def data():
    return load_event_differences()


@pytest.fixture(scope="module")
def examples():
    return load_example_spikes(load_diagnostic())


def test_frozen_four_events_use_same_units_order_and_exact_s7_difference(data):
    original = load_c1_population()
    assert data["heatmaps"].shape == (4, 203, 300)
    assert data["unit_ids"] == original["payload"]["unit_ids"]
    np.testing.assert_array_equal(data["order"], original["order"])
    np.testing.assert_array_equal(data["heatmaps"][0], original["heatmaps"][2])
    for event in EVENT_ORDER:
        record = data["events"][event]
        assert record["payload"]["unit_ids"] == data["unit_ids"]
        counts = {c: len(t) for c, t in record["trials"].items()}
        expected = 33 if event == "orientation_45" else 34
        assert counts == {"pre": expected, "post": expected}
    exclusions = data["events"]["orientation_45"]["payload"]["excluded_trials"]
    assert exclusions == [
        {"condition": "pre", "row_index": 0, "reason": "missing_preceding_grey"},
        {"condition": "post", "row_index": 544, "reason": "missing_preceding_grey"},
    ]


def test_difference_mean_and_sem_are_computed_from_paired_unitwise_differences(data):
    delta = np.stack([
        data["events"][e]["rates"] - data["events"][e]["baselines"][..., None]
        for e in EVENT_ORDER
    ])
    expected = delta[:, 1] - delta[:, 0]
    np.testing.assert_array_equal(data["difference"], expected)
    np.testing.assert_array_equal(data["heatmaps"], expected[:, data["order"]])
    np.testing.assert_array_equal(data["mean"], expected.mean(axis=1))
    np.testing.assert_array_equal(data["sem"], expected.std(axis=1, ddof=1) / np.sqrt(203))
    independent = np.sqrt(
        (delta[:, 1].var(axis=1, ddof=1) + delta[:, 0].var(axis=1, ddof=1)) / 203,
    )
    assert not np.allclose(independent, data["sem"])
    raw = np.stack([
        data["events"][e]["rates"][1] - data["events"][e]["rates"][0] for e in EVENT_ORDER
    ])
    assert not np.array_equal(expected, raw)


@pytest.mark.parametrize(
    "change", ["identity", "order", "trials", "exclusions", "interval", "bins", "rates", "replay"],
)
def test_event_validator_rejects_source_or_replay_changes(data, examples, change):
    payload = copy.deepcopy(data["events"]["orientation_45"]["payload"])
    if change == "identity":
        payload["session_id"] = "other"
    elif change == "order":
        payload["order"].reverse()
    elif change == "trials":
        payload["trials"]["pre"].pop()
    elif change == "exclusions":
        payload["excluded_trials"] = []
    elif change == "interval":
        payload["context_interval_seconds"].reverse()
    elif change == "bins":
        payload["baseline_bin_counts"][0] += 1
    elif change == "rates":
        payload["mean_hz"][0][0][0] = np.nan
    else:
        i = payload["unit_ids"].index(examples["units"][0]["id"])
        payload["mean_hz"][0][i][0] += 1
    with pytest.raises((ValueError, AssertionError)):
        validate_event_population(payload, data["events"]["orientation_90"], examples)


def test_missing_baselines_are_not_silently_counted(data, examples):
    trial = examples["events"][0]["conditions"]["control"]["trials"][0]
    assert trial["row_index"] == 0 and trial["baseline_window"] is None
    with pytest.raises(ValueError, match="no valid preceding-grey"):
        baseline_bin_counts({"pre": [trial], "post": [trial]})
    for event in EVENT_ORDER[1:]:
        record = data["events"][event]
        assert baseline_bin_counts(record["trials"]) == record["payload"]["baseline_bin_counts"]
        assert all(
            trial["baseline_window"] is not None
            for trials in record["trials"].values() for trial in trials
        )


@pytest.mark.parametrize("change", ["events", "units", "order", "time", "values"])
def test_difference_preparation_rejects_inconsistent_axes(data, change):
    events = copy.deepcopy(data["events"])
    if change == "events":
        del events["halt"]
    elif change == "units":
        events["halt"]["payload"]["unit_ids"].reverse()
    elif change == "order":
        events["halt"]["order"] = events["halt"]["order"][::-1]
    elif change == "time":
        events["halt"]["time"] = events["halt"]["time"] + 1
    else:
        events["halt"]["rates"][0, 0, 0] = np.nan
    with pytest.raises(ValueError, match="C1 difference|Four-event differences"):
        prepare_event_differences(events)


@pytest.mark.parametrize("change", ["source", "checksum"])
def test_four_event_loader_verifies_source_and_output_checksums(tmp_path, change):
    manifest = json.loads((DIRECTORY / "provenance.json").read_text())
    if change == "source":
        manifest["sources"][0]["sha256"] = "0" * 64
    else:
        (tmp_path / "orientation_45.json").write_text("{}")
    (tmp_path / "provenance.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="source changed|checksum mismatch"):
        load_event_differences(tmp_path)


def test_four_event_figure_has_exact_arrays_shared_axes_and_preserves_s7(
    data, tmp_path, monkeypatch,
):
    observed = []
    save = figure.save_diagnostic_svg

    def observe(fig, *args, **kwargs):
        axes = {ax.get_gid(): ax for ax in fig.axes if ax.get_gid()}
        observed.append({
            event: (
                axes[f"population-difference-{event}"].images[0].get_array().copy(),
                axes[f"population-difference-{event}"].images[0].get_clim(),
                axes[f"mean-difference-{event}"].get_ylim(),
                axes[f"mean-difference-{event}"].get_xlim(),
            ) for event in EVENT_ORDER
        })
        save(fig, *args, **kwargs)

    monkeypatch.setattr(figure, "save_diagnostic_svg", observe)
    preserved = [
        ROOT / "index.md",
        *[
            ROOT / f"images/figures/generated/{name}.svg"
            for name in ("ephys-c1-pseudocontext", "ephys-c1-context-comparison")
        ],
    ]
    before = [p.read_bytes() for p in preserved]
    output, audit = tmp_path / "four-events.svg", tmp_path / "audit"
    paths = figure.build_ephys_c1_event_differences(output, audit)
    first = [p.read_bytes() for p in paths]
    figure.build_ephys_c1_event_differences(output, audit)
    assert [p.read_bytes() for p in paths] == first
    assert [p.read_bytes() for p in preserved] == before
    root = ET.parse(output).getroot()
    assert root.get("data-event-order") == ",".join(EVENT_ORDER)
    assert root.get("data-common-units") == "203"
    color_limit = float(root.get("data-shared-color-limit-hz"))
    mean_limit = float(root.get("data-shared-mean-limit-hz"))
    for result in observed:
        for i, event in enumerate(EVENT_ORDER):
            image, colors, ylim, xlim = result[event]
            np.testing.assert_array_equal(image, data["heatmaps"][i])
            assert colors == (-color_limit, color_limit)
            assert ylim == (-mean_limit, mean_limit)
            assert xlim == (-0.75, 0.75)
    assert np.abs(data["mean"] - data["sem"]).max() <= mean_limit
    assert np.abs(data["mean"] + data["sem"]).max() <= mean_limit
    rows = pd.read_csv(audit / "events.csv")
    assert rows.event_id.tolist() == list(EVENT_ORDER)
    assert rows.pre_trials.tolist() == rows.post_trials.tolist() == [34, 33, 34, 34]
    assert rows.excluded_pre.tolist() == rows.excluded_post.tolist() == [0, 1, 0, 0]
    traces = pd.read_csv(audit / "mean-traces.csv", float_precision="round_trip")
    for i, event in enumerate(EVENT_ORDER):
        rows = traces.loc[traces.event_id.eq(event)]
        np.testing.assert_array_equal(rows.mean_difference_hz, data["mean"][i])
        np.testing.assert_array_equal(rows.sem_difference_hz, data["sem"][i])


def test_four_event_experiment_is_separate_and_wired_into_default_build():
    manuscript = (ROOT / "index.md").read_text()
    assert "ephys-c1-event-differences.svg" not in manuscript
    assert "c1_event_difference_paths = build_ephys_c1_event_differences()" in (
        ROOT / "src/openscope_p3_publication/figures.py"
    ).read_text()
