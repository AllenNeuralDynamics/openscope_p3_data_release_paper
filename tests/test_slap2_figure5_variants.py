"""Regression checks for the two candidate SLAP2 Figure 5 layouts."""

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from openscope_p3_publication.slap2_figure5_variants import (
    AMPLITUDE,
    DATA_DIR,
    VARIANT_A_OUTPUT,
    VARIANT_B_OUTPUT,
    load_inputs,
    noise_median,
    percentile_examples,
    write_figure5_variants,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _visible_text(path: Path) -> str:
    return " ".join(re.findall(r"<text[^>]*>(.*?)</text>", path.read_text(encoding="utf-8"), re.S))


@pytest.fixture(scope="module")
def inputs():
    return load_inputs()


def test_changed_input_is_rejected(tmp_path: Path) -> None:
    for source in DATA_DIR.iterdir():
        (tmp_path / source.name).write_bytes(source.read_bytes())
    with (tmp_path / "example_source_amplitudes.csv").open("a", encoding="utf-8") as handle:
        handle.write("10,1,35,1.000000\n")
    with pytest.raises(ValueError, match="input changed"):
        load_inputs(tmp_path)


def test_noise_reference_covers_every_glutamate_only_source() -> None:
    metrics = pd.read_csv(
        REPO_ROOT / "figure_sources/data/slap2-glutamate-qc/slap2_metrics_all_sessions.csv"
    )
    rates = pd.read_csv(DATA_DIR / "noise_only_source_rates.csv")
    expected = metrics.loc[~metrics.has_calcium.astype(bool)]
    assert len(rates) == len(expected) == 1744
    assert set(rates.session) == set(expected.session)
    assert rates.surrogate_event_rate_hz.median() == pytest.approx(0.065, abs=0.001)
    histogram = pd.read_csv(DATA_DIR / "noise_only_amplitude_histogram.csv")
    assert histogram.events.sum() == rates.surrogate_events.sum()


def test_noise_reference_values_used_in_the_review_text(inputs) -> None:
    assert noise_median(inputs) == pytest.approx(2.5, abs=0.05)
    centers, counts = inputs.noise_centers, inputs.noise_counts
    assert counts[centers >= 4].sum() / counts.sum() == pytest.approx(0.065, abs=0.001)
    assert counts[centers < 2].sum() / counts.sum() == pytest.approx(0.29, abs=0.005)


def test_example_sources_are_the_session_percentiles_and_match_the_archive(inputs) -> None:
    usable = inputs.example.loc[inputs.example.quality_class.ne("Excluded (no baseline noise)")]
    examples = percentile_examples(inputs)
    assert examples == {10: (1, 35), 50: (1, 87), 90: (1, 110)}
    for percentile, (dmd, roi) in examples.items():
        row = usable.loc[(usable.dmd == dmd) & (usable.roi == roi)].iloc[0]
        target = np.percentile(usable[AMPLITUDE], percentile)
        assert abs(row[AMPLITUDE] - target) == (usable[AMPLITUDE] - target).abs().min()
        amplitudes = inputs.amplitudes.loc[inputs.amplitudes.percentile == percentile]
        assert amplitudes.amplitude_sd.median() == pytest.approx(row[AMPLITUDE], abs=1e-3)
    assert (inputs.trace_dmd, inputs.trace_roi) == (1, 9)


def test_provenance_records_assets_and_the_excluded_cohort() -> None:
    provenance = json.loads((DATA_DIR / "provenance.json").read_text(encoding="utf-8"))
    assert len(provenance["source_assets"]) == 12
    assert all(a["digest"]["dandi:sha2-256"] for a in provenance["source_assets"])
    assert "dual-channel" in provenance["exclusions"]


def test_committed_variants_regenerate_identically(tmp_path: Path) -> None:
    first, second = write_figure5_variants(tmp_path / "a.svg", tmp_path / "b.svg")
    assert first.read_bytes() == VARIANT_A_OUTPUT.read_bytes()
    assert second.read_bytes() == VARIANT_B_OUTPUT.read_bytes()


def test_only_variant_b_presents_the_kmeans_classes() -> None:
    variant_a, variant_b = _visible_text(VARIANT_A_OUTPUT), _visible_text(VARIANT_B_OUTPUT)
    for name in ("High", "Intermediate", "Low"):
        assert name not in variant_a
        assert name in variant_b
    assert "Median event amplitude" in variant_a
    assert "Noise only" in variant_a
    assert "Noise only" not in variant_b


def test_variants_have_scale_bars_and_accessible_text() -> None:
    for path in (VARIANT_A_OUTPUT, VARIANT_B_OUTPUT):
        text = _visible_text(path)
        assert "2 µm" in text
        assert text.count("25 µm") == 2
        svg = path.read_text(encoding="utf-8")
        assert '<title id="title">' in svg
        assert '<desc id="description">' in svg


def test_manuscript_still_uses_the_current_figure() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    assert "figure-07-unit-extraction-plan.svg" in manuscript
    assert "figure-07-unit-extraction-plan-variant" not in manuscript
