"""Tests for the receptive-field figure and its committed intermediate."""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Iterator
from pathlib import Path
from xml.etree import ElementTree

import matplotlib as mpl
import numpy as np
import pytest
from matplotlib import pyplot as plt
from matplotlib.text import Text
from matplotlib.transforms import Bbox

from openscope_p3_publication.receptive_field_figure import (
    DATA_PATH,
    MODALITIES,
    PIE_COLORS,
    PIE_ORDER,
    PROVENANCE_PATH,
    RC_PARAMS,
    SELECTIONS,
    build_figure,
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


@pytest.fixture(scope="module")
def rendered_figure(data: dict) -> Iterator[plt.Figure]:
    with mpl.rc_context(RC_PARAMS):
        figure = build_figure(data)
        figure.canvas.draw()
        yield figure
        plt.close(figure)


def test_example_scales_are_shared_without_changing_values(
    data: dict, rendered_figure: plt.Figure,
) -> None:
    axes = {axis.get_gid(): axis for axis in rendered_figure.axes if axis.get_gid()}
    colorbars = {gid: axis for gid, axis in axes.items() if "colorbar" in gid}
    assert set(colorbars) == {"shared-colorbar-gabor", "shared-colorbar-zebra"}
    for kind, label in (("gabor", "z score"), ("zebra", "Correlation")):
        bar = colorbars[f"shared-colorbar-{kind}"]
        norm = bar.collections[-1].norm
        expected = max(
            np.nanmax(np.abs(data[modality]["examples"][f"{kind}_map"][
                data[modality]["examples"]["present"]
            ])) for modality, _ in MODALITIES
        )
        assert norm.vmax == expected
        assert norm.vmin == -expected
        assert bar.get_ylabel() == label
        assert bar.get_position().x0 > max(
            axis.get_position().x1 for gid, axis in axes.items() if gid.startswith("example-")
        )
        for modality, _ in MODALITIES:
            examples = data[modality]["examples"]
            for index, selection in enumerate(SELECTIONS):
                axis = axes[f"example-{modality}-{kind}-{selection}"]
                if not examples["present"][index]:
                    assert not axis.images
                    continue
                image = axis.images[0]
                assert image.norm is norm
                np.testing.assert_array_equal(image.get_array(), examples[f"{kind}_map"][index].T)
                assert np.ma.min(image.get_array()) >= norm.vmin
                assert np.ma.max(image.get_array()) <= norm.vmax
                assert image.get_interpolation() == "nearest"


def test_shared_overlap_legend_and_lighter_strokes(
    data: dict, rendered_figure: plt.Figure,
) -> None:
    assert len(rendered_figure.legends) == 1
    legend = rendered_figure.legends[0]
    assert legend.get_gid() == "overlap-shared-legend"
    assert [text.get_text() for text in legend.get_texts()] == list(PIE_ORDER)
    for handle, name in zip(legend.legend_handles, PIE_ORDER, strict=True):
        assert handle.get_facecolor() == mpl.colors.to_rgba(PIE_COLORS[name])
    for axis in rendered_figure.axes:
        gid = axis.get_gid() or ""
        if gid.startswith("overlap-"):
            assert axis.get_legend() is None
            modality = gid.split("-")[1]
            structure = axis.get_title().rsplit(" (", 1)[0].strip()
            n = int((data[modality]["units"]["structure"] == structure).sum())
            assert n > 0 and axis.get_title().endswith(f" ({n})")
            assert all(patch.get_linewidth() <= 0.35 for patch in axis.patches)
        if gid.startswith("example-") and axis.images:
            assert all(spine.get_linewidth() == 0.8 for spine in axis.spines.values())
            assert all(patch.get_linewidth() <= 1.0 for patch in axis.patches)
            assert all(line.get_linewidth() <= 0.35 for line in axis.lines[:2])
            assert all(line.get_markersize() <= 2.5 for line in axis.lines[2:])
        if gid.startswith("summary-"):
            assert all(line.get_linewidth() <= 0.6 for line in axis.lines
                       if line.get_linestyle() != "None")


def test_shared_labels_and_larger_icons_do_not_overlap(rendered_figure: plt.Figure) -> None:
    renderer = rendered_figure.canvas.get_renderer()
    axes = {axis.get_gid(): axis for axis in rendered_figure.axes if axis.get_gid()}
    for modality in ("neuropixels", "mesoscope", "slap2"):
        logo = axes[f"platform-logo-{modality}"]
        assert logo.get_window_extent(renderer).width / rendered_figure.dpi >= 0.70
    shared = [text for text in rendered_figure.texts if "-shared-" in (text.get_gid() or "")]
    assert len(shared) == 4
    for text in shared:
        box = text.get_window_extent(renderer)
        assert all(not box.overlaps(axis.get_tightbbox(renderer))
                   for axis in rendered_figure.axes if axis.axison)
    for modality, _ in MODALITIES:
        for kind in ("gabor", "zebra"):
            position = axes[f"summary-{modality}-{kind}-position"]
            area = axes[f"summary-{modality}-{kind}-area"]
            strength = axes[f"summary-{modality}-{kind}-strength"]
            assert not position.get_xlabel() and not position.get_ylabel()
            assert not area.get_ylabel() and not strength.get_ylabel()
            assert area.get_title() == ("RF area (deg²)" if kind == "gabor" else "")
            assert strength.get_title() == ("Peak |z|" if kind == "gabor" else "Peak |r|")
            for following in (area, strength):
                assert not following.title.get_window_extent(renderer).overlaps(
                    position.get_legend().get_window_extent(renderer)
                )
            labels = [text for text in strength.get_xticklabels() if text.get_visible()]
            assert all(not left.get_window_extent(renderer).overlaps(
                right.get_window_extent(renderer)
            ) for left, right in zip(labels[:-1], labels[1:], strict=True))


def test_elevation_clearance_and_slightly_raised_row_b(rendered_figure: plt.Figure) -> None:
    renderer = rendered_figure.canvas.get_renderer()
    axes = {axis.get_gid(): axis for axis in rendered_figure.axes if axis.get_gid()}
    texts = {text.get_gid(): text for text in rendered_figure.texts if text.get_gid()}
    elevation = texts["examples-shared-elevation"]
    assert elevation.get_position()[0] == texts["summary-shared-elevation"].get_position()[0]
    stimulus_right = max(
        axis.get_window_extent(renderer).x1 for axis in rendered_figure.axes
        if axis.images and not axis.get_gid()
    )
    assert elevation.get_window_extent(renderer).x0 - stimulus_right >= rendered_figure.dpi * 0.20
    height = rendered_figure.get_figheight()
    assert height == pytest.approx(11.33)
    for modality, _ in MODALITIES:
        for gid, top in (
            (f"example-{modality}-gabor-both", 1.40),
            (f"example-{modality}-zebra-both", 2.592),
            (f"overlap-{modality}-0", 4.63),
            (f"overlap-{modality}-1", 4.63),
            (f"summary-{modality}-gabor-position", 7.56),
            (f"summary-{modality}-zebra-position", 9.44),
        ):
            assert (1 - axes[gid].get_position().y1) * height == pytest.approx(top)
    legend = rendered_figure.legends[0].get_window_extent(renderer)
    assert height - (legend.y0 + legend.y1) / (2 * rendered_figure.dpi) == pytest.approx(6.61)


def test_plot_groups_share_the_modality_heading_centres(rendered_figure: plt.Figure) -> None:
    renderer = rendered_figure.canvas.get_renderer()
    axes = {axis.get_gid(): axis for axis in rendered_figure.axes if axis.get_gid()}
    headings = {text.get_gid(): text for text in rendered_figure.texts}
    centres = []
    for modality, _ in MODALITIES:
        heading = headings[f"modality-heading-{modality}"].get_window_extent(renderer)
        centre = (heading.x0 + heading.x1) / 2
        centres.append(centre)
        for prefix in ("example", "overlap", "summary"):
            group = Bbox.union([
                axis.get_window_extent(renderer) for gid, axis in axes.items()
                if gid.startswith(f"{prefix}-{modality}-")
            ])
            assert (group.x0 + group.x1) / 2 == pytest.approx(centre, abs=1e-6)
        pies = [axes[f"overlap-{modality}-{index}"] for index in range(2)]
        circle_centres = [
            axis.transData.transform(axis.patches[0].center)[0] for axis in pies
        ]
        assert np.mean(circle_centres) == pytest.approx(centre, abs=1e-6)
        for pie in pies:
            diameter = pie.get_window_extent(renderer).width / rendered_figure.dpi
            assert diameter == pytest.approx(1.65)
        logo_key = "neuropixels" if modality == "ecephys" else modality
        assert axes[f"platform-logo-{logo_key}"].get_window_extent(renderer).x1 < heading.x0
    np.testing.assert_allclose(np.diff(centres), np.diff(centres)[0], atol=1e-6)


def test_tentative_caption_reports_saved_populations_and_parameters(provenance: dict) -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    caption = manuscript.split(":label: fig-basic-stimuli-plan", 1)[1].split(":::", 1)[0]
    caption = " ".join(caption.split())
    assert "tentative caption" in caption
    assert "Draft panel plan" not in caption
    assert all(f"**{letter},**" in caption for letter in "ABC")
    for modality, label, structures in (
        ("ecephys", "Neuropixels V1/LM", ("V1", "LM")),
        ("mesoscope", "mesoscope V1/LM", ("V1", "LM")),
        ("slap2", "SLAP2 DMD1 apical/DMD2 basal", ("DMD1\n(apical)", "DMD2\n(basal)")),
    ):
        counts = provenance["counts"][modality]["structures"]
        ns = "/".join(f"{counts[structure]['units']:,}" for structure in structures)
        assert f"{label} (n = {ns})" in caption
    parameters = provenance["parameters"]
    assert f"q ≤ {parameters['q_level']}" in caption
    assert f"{parameters['bootstrap_resamples']:,} resamples" in caption
    assert f"{parameters['permutations']:,} permutations" in caption
    assert f"beyond ±{parameters['gabor_centre_limit_deg']:g}°" in caption
    assert "one session" in caption
    assert "source snapshot and provenance" in caption


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
    root = ElementTree.fromstring(svg)
    namespace = "{http://www.w3.org/2000/svg}"
    for modality in ("neuropixels", "mesoscope", "slap2"):
        assert root.find(f".//{namespace}g[@id='platform-logo-{modality}']") is not None
    labels = list(root.iter(f"{namespace}text"))
    assert labels
    assert all("Arial" in label.get("style", "") for label in labels)
    assert "DejaVu Sans" not in svg


def test_larger_panels_and_text_fit_the_original_full_width(data: dict) -> None:
    with mpl.rc_context(RC_PARAMS):
        figure = build_figure(data)
        try:
            figure.canvas.draw()
            renderer = figure.canvas.get_renderer()
            assert figure.get_figwidth() == 15
            assert figure.get_figheight() / figure.get_figwidth() * 170 < 205
            labels = [text for text in figure.findobj(Text) if text.get_visible()
                      and text.get_text() and (text.axes is None or text.axes.axison)]
            assert min(text.get_fontsize() for text in labels) >= 9
            for label in labels:
                box = label.get_window_extent(renderer)
                assert box.x0 >= 0 and box.y0 >= 0
                assert box.x1 <= figure.bbox.width and box.y1 <= figure.bbox.height
            axes = {axis.get_gid(): axis for axis in figure.axes if axis.get_gid()}
            for modality, _ in MODALITIES:
                example = axes[f"example-{modality}-zebra-both"]
                assert example.get_window_extent(renderer).width / figure.dpi >= 0.96 * 1.10 - 1e-8
                pie = axes[f"overlap-{modality}-0"]
                assert pie.get_window_extent(renderer).width / figure.dpi >= 1.425 * 1.15
                summary = axes[f"summary-{modality}-gabor-position"]
                assert summary.get_window_extent(renderer).height / figure.dpi >= 0.8 * 1.10 - 1e-8
                for kind in ("gabor", "zebra"):
                    for left_role, right_role in (("position", "area"), ("area", "strength")):
                        previous = axes[f"summary-{modality}-{kind}-{left_role}"]
                        following = axes[f"summary-{modality}-{kind}-{right_role}"]
                        label_left = following.get_tightbbox(renderer).x0
                        assert label_left - previous.get_window_extent(renderer).x1 >= (
                            figure.dpi * 0.05
                        )
            for row in ("example", "overlap", "summary"):
                boxes = [
                    Bbox.union([axis.get_tightbbox(renderer) for gid, axis in axes.items()
                                if gid.startswith(f"{row}-{modality}-")])
                    for modality, _ in MODALITIES
                ]
                assert all(left.x1 < right.x0
                           for left, right in zip(boxes[:-1], boxes[1:], strict=True))
        finally:
            plt.close(figure)


def test_committed_svg_is_current(tmp_path: Path) -> None:
    committed = REPO_ROOT / "images" / "figures" / "generated" / "receptive-fields.svg"
    fresh = write_receptive_fields_svg(tmp_path / "receptive-fields.svg")
    assert committed.read_bytes() == fresh.read_bytes()
