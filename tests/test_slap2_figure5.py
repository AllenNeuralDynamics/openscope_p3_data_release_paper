"""Regression checks for SLAP2 Figure 5 and its issue-59 input refresh."""

import json
import re
from pathlib import Path

import pandas as pd
import pytest

from openscope_p3_publication.slap2_figure5 import (
    AMPLITUDE,
    BY_COHORT_OUTPUT,
    NOISE_DIR,
    POOLED_OUTPUT,
    TABLE_DIR,
    load_inputs,
    noise_median,
    write_figure5,
)
from openscope_p3_publication.slap2_glutamate_qc_events import NOMINAL_SAMPLING_INTERVAL_S

REPO_ROOT = Path(__file__).resolve().parents[1]
FROZEN_DIR = REPO_ROOT / "figure_sources/data/slap2-glutamate-qc"
KEYS = ["session", "dmd", "roi"]


def _visible_text(path: Path) -> str:
    return " ".join(re.findall(r"<text[^>]*>(.*?)</text>", path.read_text(encoding="utf-8"), re.S))


@pytest.fixture(scope="module")
def inputs():
    return load_inputs()


def test_changed_inputs_are_rejected(tmp_path: Path) -> None:
    for name, directory in (("tables", TABLE_DIR), ("noise", NOISE_DIR)):
        copy = tmp_path / name
        copy.mkdir()
        for source in directory.iterdir():
            (copy / source.name).write_bytes(source.read_bytes())
    with (tmp_path / "noise/noise_only_source_rates.csv").open("a", encoding="utf-8") as handle:
        handle.write("x,1,0,0.0,0\n")
    with pytest.raises(ValueError, match="input changed"):
        load_inputs(tmp_path / "tables", tmp_path / "noise")


def test_refreshed_tables_cover_the_frozen_archive_with_the_nominal_interval() -> None:
    provenance = json.loads((TABLE_DIR / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["parameters"]["sampling_interval_seconds"] == NOMINAL_SAMPLING_INTERVAL_S
    assert provenance["sessions_from"]["path"] == (
        "figure_sources/data/slap2-glutamate-qc/slap2_metrics_all_sessions.csv"
    )
    assert len(provenance["source_assets"]) == 20
    frozen = pd.read_csv(FROZEN_DIR / "slap2_metrics_all_sessions.csv")
    refreshed = pd.read_csv(TABLE_DIR / "slap2_metrics_all_sessions.csv")
    assert frozen[KEYS].sort_values(KEYS).values.tolist() == (
        refreshed[KEYS].sort_values(KEYS).values.tolist()
    )
    assert refreshed.quality_class.value_counts().to_dict() == {
        "Intermediate": 957, "High SNR": 888, "Low SNR": 676, "Excluded (no baseline noise)": 19,
    }
    merged = frozen.merge(refreshed, on=KEYS, suffixes=("_frozen", "_refreshed"))
    changed = merged.quality_class_frozen.ne(merged.quality_class_refreshed)
    assert changed.sum() == 235
    # Sessions that already ran with 20-sample kernels keep their amplitudes.
    same = merged.loc[merged.session.eq("sub-794237_ses-20250424T142019")]
    assert (same[f"{AMPLITUDE}_refreshed"] - same[f"{AMPLITUDE}_frozen"]).abs().max() < 0.01


def test_figure9_keeps_the_frozen_archive_and_its_eligible_sources() -> None:
    frozen = pd.read_csv(FROZEN_DIR / "slap2_metrics_all_sessions.csv")
    refreshed = pd.read_csv(TABLE_DIR / "slap2_metrics_all_sessions.csv")
    merged = frozen.merge(refreshed, on=KEYS, suffixes=("_frozen", "_refreshed"))
    eligible = ["High SNR", "Intermediate"]
    for session in ("sub-828408_ses-828408-2025-11-18-14-44-48",) + tuple(
        merged.loc[merged.session.str.startswith("sub-829704"), "session"].unique()
    ):
        rows = merged.loc[merged.session.eq(session)]
        assert rows.quality_class_frozen.isin(eligible).equals(
            rows.quality_class_refreshed.isin(eligible)
        )


def test_noise_reference_covers_every_glutamate_only_source(inputs) -> None:
    rates = pd.read_csv(NOISE_DIR / "noise_only_source_rates.csv")
    expected = inputs.metrics.loc[~inputs.metrics.has_calcium.astype(bool)]
    assert len(rates) == len(expected) == 1744
    assert set(rates.session) == set(expected.session)
    histogram = pd.read_csv(NOISE_DIR / "noise_only_amplitude_histogram.csv")
    assert histogram.events.sum() == rates.surrogate_events.sum()
    provenance = json.loads((NOISE_DIR / "provenance.json").read_text(encoding="utf-8"))
    assert len(provenance["source_assets"]) == 12
    assert all(len(asset["sha256"]) == 64 for asset in provenance["source_assets"])
    assert "dual-channel" in provenance["exclusions"]


def test_noise_reference_values_used_in_the_caption(inputs) -> None:
    assert noise_median(inputs) == pytest.approx(2.5, abs=0.05)


def test_trace_example_is_unchanged(inputs) -> None:
    assert (inputs.trace_dmd, inputs.trace_roi) == (1, 9)


def test_committed_figures_regenerate_identically(tmp_path: Path) -> None:
    pooled, by_cohort = write_figure5(tmp_path / "pooled.svg", tmp_path / "by-cohort.svg")
    assert pooled.read_bytes() == POOLED_OUTPUT.read_bytes()
    assert by_cohort.read_bytes() == BY_COHORT_OUTPUT.read_bytes()


def test_svg_ids_do_not_depend_on_float_hashes() -> None:
    for path in (POOLED_OUTPUT, BY_COHORT_OUTPUT):
        svg = path.read_text(encoding="utf-8")
        assert not re.search(r'id="(?:p|m|image)[0-9a-f]{10}"', svg)
        assert 'clip-path="url(#slap2-figure5' in svg


def test_only_the_variant_separates_the_cohorts() -> None:
    pooled, by_cohort = _visible_text(POOLED_OUTPUT), _visible_text(BY_COHORT_OUTPUT)
    assert "Glu only" not in pooled and "Glu + Ca" not in pooled
    assert "Glu only" in by_cohort and "Glu + Ca" in by_cohort
    for text in (pooled, by_cohort):
        for name in ("High SNR", "Intermediate", "Low SNR"):
            assert name not in text
        assert "Median event amplitude" in text
        assert "Noise-only median" in text
        assert "proximal" in text and "apical" in text


def test_figures_have_scale_bars_and_accessible_text() -> None:
    for path in (POOLED_OUTPUT, BY_COHORT_OUTPUT):
        text = _visible_text(path)
        assert "2 µm" in text
        assert text.count("25 µm") == 2
        assert "Time (s)" in text
        svg = path.read_text(encoding="utf-8")
        assert '<title id="title">' in svg
        assert '<desc id="description">' in svg


def test_manuscript_uses_the_pooled_figure_only() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    assert "./images/figures/generated/figure-05-unit-extraction-plan.svg" in manuscript
    assert "figure-05-unit-extraction-plan-by-cohort" not in manuscript
