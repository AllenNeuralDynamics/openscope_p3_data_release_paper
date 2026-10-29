"""Tests for the receptive-field figure and its committed intermediate."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import numpy as np
import pytest

from openscope_p3_publication.receptive_field_figure import (
    DATA_PATH,
    MODALITIES,
    PROVENANCE_PATH,
    SELECTIONS,
    load_receptive_fields,
    overlap_counts,
    write_receptive_fields_svg,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def data() -> dict:
    return load_receptive_fields()


@pytest.fixture(scope="module")
def provenance() -> dict:
    return json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))


def test_intermediate_is_small_and_matches_provenance(provenance: dict) -> None:
    assert DATA_PATH.stat().st_size < 10 * 2**20
    assert provenance["output"]["bytes"] == DATA_PATH.stat().st_size
    assert provenance["output"]["path"] == DATA_PATH.relative_to(REPO_ROOT).as_posix()
    assert provenance["stimulus"]["movie_sha256"] == (
        "3ee4d88356dba7220eb67e53f7d117400932f3adf95132d6301fe212ff7cf899"
    )
    assert provenance["parameters"]["q_level"] == 0.05


def test_checksum_mismatch_is_rejected(tmp_path: Path, provenance: dict) -> None:
    record = dict(provenance, output=dict(provenance["output"], sha256="0" * 64))
    wrong = tmp_path / "receptive-fields.provenance.json"
    wrong.write_text(json.dumps(record), encoding="utf-8")
    copy = tmp_path / "receptive-fields.h5"
    shutil.copyfile(DATA_PATH, copy)
    with pytest.raises(ValueError, match="does not match"):
        load_receptive_fields(copy, wrong)


def test_examples_have_one_map_pair_per_selection(data: dict) -> None:
    for modality, _ in MODALITIES:
        ex = data[modality]["examples"]
        assert tuple(ex["selection"]) == SELECTIONS
        assert ex["gabor_map"].shape == (3, 9, 9)
        assert ex["zebra_map"].shape == (3, 67, 53)
        for col, present in enumerate(ex["present"]):
            assert present == bool(ex["unit_id"][col])
            assert np.isfinite(ex["zebra_map"][col]).any() == present
            # a fit is stored only for a map that passed its test
            for kind in ("gabor", "zebra"):
                if np.isfinite(ex[f"{kind}_fit"][col]).any():
                    assert ex[f"pass_{kind}"][col]
        # each example belongs to the selection it is shown under
        passes = {
            "both": (True, True), "gabor-only": (True, False), "zebra-only": (False, True),
        }
        for col, selection in enumerate(ex["selection"]):
            if ex["present"][col]:
                assert (ex["pass_gabor"][col], ex["pass_zebra"][col]) == passes[selection]
    assert not data["slap2"]["examples"]["present"][1]


def test_overlap_counts_match_provenance(data: dict, provenance: dict) -> None:
    for modality, _ in MODALITIES:
        units = data[modality]["units"]
        for structure, recorded in provenance["counts"][modality]["structures"].items():
            counts = overlap_counts(units, structure)
            assert counts == {
                "neither": recorded["neither"],
                "Zebra only": recorded["zebra_only"],
                "Gabor only": recorded["gabor_only"],
                "both": recorded["both"],
            }
            assert sum(counts.values()) == recorded["units"]
            for kind in ("gabor", "zebra"):
                fits = data[modality][f"{kind}_fits"]
                assert int((fits["structure"] == structure).sum()) == recorded[f"{kind}_fits"]


def test_fits_are_the_significant_units(data: dict) -> None:
    for modality, _ in MODALITIES:
        units = data[modality]["units"]
        for kind in ("gabor", "zebra"):
            fits = data[modality][f"{kind}_fits"]
            significant = set(
                zip(units["group"][units[f"pass_{kind}"]],
                    units["unit_id"][units[f"pass_{kind}"]], strict=True)
            )
            fitted = set(zip(fits["group"], fits["unit_id"], strict=True))
            assert fitted <= significant
            assert np.isfinite(fits["area"]).all() and (fits["area"] > 0).all()
    # Gabor fits whose centre lies beyond the limit were excluded
    limit = float(data["attrs"]["gabor_centre_limit_deg"])
    for modality, _ in MODALITIES:
        fits = data[modality]["gabor_fits"]
        assert (np.abs(fits["x0"]) <= limit).all() and (np.abs(fits["y0"]) <= limit).all()


def test_provenance_records_the_exclusions(provenance: dict) -> None:
    excluded = {
        modality: provenance["counts"][modality]["excluded_gabor_fit_or_centre"]
        for modality, _ in MODALITIES
    }
    assert excluded == {
        "ecephys": {"VISl": 5, "VISp": 10},
        "mesoscope": {"VISl": 68, "VISp": 14},
        "slap2": {"DMD1\n(apical)": 1, "DMD2\n(basal)": 1},
    }


def test_svg_is_deterministic_and_labelled(tmp_path: Path) -> None:
    first = write_receptive_fields_svg(tmp_path / "a.svg").read_bytes()
    second = write_receptive_fields_svg(tmp_path / "b.svg").read_bytes()
    assert first == second
    svg = first.decode("utf-8")
    assert "<dc:date>" not in svg
    for text in ("Neuropixels", "Mesoscope", "SLAP2 glutamate", "No significant result",
                 "V1 (n=163)", "LM (n=94)", "DMD1 (n=23)", "DMD2 (n=30)"):
        assert text in svg
    assert len(re.findall(r"data:image/png;base64,", svg)) >= 20


def test_committed_svg_is_current(tmp_path: Path) -> None:
    committed = REPO_ROOT / "images" / "figures" / "generated" / "receptive-fields.svg"
    fresh = write_receptive_fields_svg(tmp_path / "receptive-fields.svg")
    assert committed.read_bytes() == fresh.read_bytes()
