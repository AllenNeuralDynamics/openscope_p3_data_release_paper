"""Tests for the standard-oddball LFP power-change supplementary figure."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from openscope_p3_publication.lfp_spectral_mi_figure import (
    DATA_PATH,
    OUTPUT_PATH,
    PROVENANCE_PATH,
    REPO_ROOT,
    load_lfp_spectral_mi,
    write_lfp_spectral_mi_svg,
)


@pytest.fixture(scope="module")
def data() -> dict:
    return load_lfp_spectral_mi()


def test_intermediate_matches_provenance_checksum(tmp_path: Path) -> None:
    copy = tmp_path / DATA_PATH.name
    shutil.copy(DATA_PATH, copy)
    copy.write_bytes(copy.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="SHA-256"):
        load_lfp_spectral_mi(copy)


def test_provenance_pins_every_source_asset() -> None:
    provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    assert provenance["dandiset_id"] == "001637"
    assert provenance["output"]["path"] == DATA_PATH.name
    assets = provenance["assets"]
    assert assets and all(path.endswith(".nwb") for path in assets)
    assert all(record and record["asset_id"] for record in assets.values())


def test_plotted_data_is_consistent(data: dict) -> None:
    n_freqs = len(data["freqs_hz"])
    assert len(data["freq_edges_hz"]) == n_freqs + 1
    assert set(data["heatmaps"]) == {"std", "ctrl"}
    for block in data["heatmaps"].values():
        dpow, q = np.array(block["dpow_db"], float), np.array(block["q_fdr"], float)
        assert dpow.shape == q.shape == (len(block["events"]), len(block["areas"]), n_freqs)
        assert np.nanmin(q) >= 0 and np.nanmax(q) <= 1
        assert len(block["n_animals"]) == len(block["areas"])
    assert data["heatmaps"]["ctrl"]["events"][-1] == "standard"
    spectra = data["v1"]["spectra_db"]
    n_mice = len(data["v1"]["subjects"])
    assert all(len(rows) == n_mice for rows in spectra.values())
    event = data["example"]["event"]
    for key in ("standard", event, "control_standard", f"control_{event}"):
        assert any(row is not None for row in spectra[key]), key
    example = data["example"]
    assert len(example["t_s"]) == len(example["lfp_uv"])
    assert np.array(example["spectrogram_db_vs_median"], float).shape == (
        len(example["spectrogram_freqs_hz"]), len(example["spectrogram_t_s"]))


def test_svg_is_deterministic_and_committed(tmp_path: Path) -> None:
    first = write_lfp_spectral_mi_svg(tmp_path / "a.svg").read_bytes()
    second = write_lfp_spectral_mi_svg(tmp_path / "b.svg").read_bytes()
    assert first == second
    assert OUTPUT_PATH.read_bytes() == first
    svg = first.decode("utf-8")
    for letter in "ABCDE":
        assert f'id="panel-label-{letter}"' in svg
    assert 'data-publication-font="Arial"' in svg


def test_manuscript_cites_the_figure() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    block = manuscript.split(
        ":::{figure} ./images/figures/generated/supplementary-lfp-spectral-mi.svg", 1
    )[1].split("\n:::", 1)[0]
    assert ":label: fig-supp-lfp-spectral-mi\n:enumerated: false" in block
    assert "**Supplementary Figure 7.**" in block and "001637" in block
    assert "[Supplementary Figure 7](#fig-supp-lfp-spectral-mi)" in manuscript
    assert "__" not in block, "caption placeholders left unfilled"
