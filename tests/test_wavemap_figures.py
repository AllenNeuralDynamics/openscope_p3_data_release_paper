import hashlib
import json
import runpy
import xml.etree.ElementTree as ET
import zlib
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from matplotlib import pyplot as plt
from matplotlib.backends.backend_pdf import PdfFile
from matplotlib.figure import Figure
from matplotlib.path import Path as PlotPath
from matplotlib.transforms import Affine2D
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from pypdf import PdfReader

from openscope_p3_publication.figures import REPO_ROOT
from openscope_p3_publication.wavemap_figure import (
    EXPLORER_NAMES,
    SNAPSHOT_PATH,
    build_wavemap_figures,
    load_wavemap_snapshot,
    verified_waveform_sampling_rate,
)
from openscope_p3_publication.wavemap_publication_figures import (
    _canonical_png,
    _CanonicalPdfFile,
    _CanonicalPdfPages,
    _plot_region_embedding,
    _plot_region_waveforms,
    build_cell_type_static_figures,
    build_context_figure,
    build_regional_waveform_figure,
    build_wavemap_static_figures,
)


@pytest.fixture(scope="module")
def snapshot() -> dict:
    return load_wavemap_snapshot()


def test_wavemap_snapshot_preserves_contributed_values(snapshot: dict) -> None:
    assert hashlib.sha256(SNAPSHOT_PATH.read_bytes()).hexdigest() == (
        "3ccdf6ddaa3448199f9b2a912368291b73e64aa83fd53f38176c90a91150dcf1"
    )
    units = snapshot["units_df"]
    mapping = snapshot["map_df"]
    assert len(units) == 22878
    assert units["session_key"].nunique() == 59
    assert units["mouse_id"].nunique() == 16
    assert snapshot["normWFs"].shape == (22878, 210)
    assert np.isfinite(snapshot["normWFs"]).all()
    assert units["unit_uid"].equals(mapping["unit_uid"])
    displayed = mapping[mapping["wavemap_group"].isin(["MO", "PFC", "VIS", "STR", "HPC", "THAL"])]
    assert len(displayed) == 15155
    assert displayed["sst_opto_available"].all()
    assert displayed["sst_optotagged"].sum() == 225
    assert displayed["putative_fs"].sum() == 1134
    assert displayed["sst_fs_overlap"].sum() == 35


def test_wavemap_loader_rejects_checksum_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "wavemap-analysis.json.gz"
    path.write_bytes(b"not the source snapshot")
    path.with_suffix("").with_suffix(".provenance.json").write_text(
        json.dumps({"snapshot_sha256": "0" * 64}), encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="checksum"):
        load_wavemap_snapshot(path)


def test_wavemap_source_metadata_rejects_changed_assets() -> None:
    verify = runpy.run_path(str(REPO_ROOT / "scripts/update_wavemap_provenance.py"))[
        "verified_asset"
    ]
    record = {"asset_id": "example", "path": "source.nwb", "size_bytes": 100}
    metadata = {
        "identifier": "example",
        "path": "source.nwb",
        "contentSize": 100,
        "digest": {"dandi:sha2-256": "a" * 64},
        "contentUrl": ["https://example.org/source"],
        "blobDateModified": "2026-09-01T00:00:00+00:00",
    }
    assert verify(record, metadata, "2026-10-03T00:00:00+00:00")["digest"] == metadata["digest"]
    with pytest.raises(RuntimeError, match="identity changed"):
        verify(record, {**metadata, "contentSize": 101}, "2026-10-03T00:00:00+00:00")
    with pytest.raises(RuntimeError, match="postdates"):
        verify(record, metadata, "2026-08-01T00:00:00+00:00")


def test_wavemap_time_axis_requires_recorded_rate(snapshot: dict) -> None:
    assert snapshot["WF_SAMPLING_RATE"] == 30000.0
    assert verified_waveform_sampling_rate(snapshot) is None
    recorded = {"units_df": pd.DataFrame({"waveform_sampling_rate_hz": [30000.0, 30000.0]})}
    assert verified_waveform_sampling_rate(recorded) == 30000.0
    recorded["units_df"].loc[1, "waveform_sampling_rate_hz"] = np.nan
    assert verified_waveform_sampling_rate(recorded) is None


def test_wavemap_complements_optotagging_as_a_main_figure() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    assert manuscript.count(":label: fig-supp-wavemap\n") == 1
    assert "[Figure 8](#fig-supp-wavemap)" in manuscript
    assert ":label: fig-supp-wavemap\n:width: 100%" in manuscript
    assert ":placeholder: ./images/figures/generated/cell-type-characterization.svg" in manuscript
    assert ":label: fig-unit-extraction-plan" in manuscript
    assert "(fig-supp-optotagging-heatmaps)=" in manuscript
    assert "waveform sample index" in manuscript
    assert "22,878 QC-selected units" in manuscript
    assert "15,155 displayed units" in manuscript
    assert "not confirmed" in manuscript


def test_wavemap_viewer_has_no_pdf_download_control() -> None:
    sources = REPO_ROOT / "figure_sources/javascript"
    template = (sources / "wavemap-supplement.html").read_text(encoding="utf-8")
    stylesheet = (sources / "wavemap-supplement.css").read_text(encoding="utf-8")
    assert "pdf-link" not in template
    assert "pdf-link" not in stylesheet
    assert "supplementary-wavemap.pdf" not in template
    assert template.count('role="tab"') == 3
    assert 'class="figure-mode-switch"' in template
    assert template.count('data-view="') == 2
    assert 'data-view="static" aria-pressed="true"' in template
    assert "__WAVEMAP_STATIC__" in template
    assert 'alt="WaveMAP:' in template
    assert "Supplementary Figure 9" not in template


def test_wavemap_explorers_build_offline_deterministically(tmp_path: Path, snapshot: dict) -> None:
    outputs = build_wavemap_figures(output_root=tmp_path, snapshot=snapshot)
    assert {output.name for output in outputs} == set(EXPLORER_NAMES)
    first = {output.name: hashlib.sha256(output.read_bytes()).hexdigest() for output in outputs}
    second = build_wavemap_figures(output_root=tmp_path, snapshot=snapshot)
    assert first == {
        output.name: hashlib.sha256(output.read_bytes()).hexdigest() for output in second
    }
    assert (tmp_path / "interactive/vendor/plotly.min.js").is_file()
    for output in outputs:
        html = output.read_text(encoding="utf-8")
        assert "./vendor/plotly.min.js" in html
        assert "cdn.plot.ly" not in html


def test_wavemap_png_compression_is_canonical_and_lossless() -> None:
    pixels = np.arange(19 * 23 * 4, dtype=np.uint8).reshape(19, 23, 4)
    image = Image.fromarray(pixels)
    metadata = PngInfo()
    metadata.add_text("Source", "WaveMAP encoding regression")
    encoded = []
    for level in (1, 9):
        buffer = BytesIO()
        image.save(buffer, format="PNG", compress_level=level, pnginfo=metadata, dpi=(600, 600))
        encoded.append(buffer.getvalue())
    assert encoded[0] != encoded[1]
    canonical = [_canonical_png(data) for data in encoded]
    assert canonical[0] == canonical[1]
    assert _canonical_png(canonical[0]) == canonical[0]
    with Image.open(BytesIO(canonical[0])) as normalized:
        assert np.array_equal(np.asarray(normalized), pixels)
        with Image.open(BytesIO(encoded[0])) as original:
            assert normalized.info == original.info


@pytest.mark.parametrize("translation", [(-1e-8, 0), (0, -1e-8), (-0.5, -1e-8)])
def test_wavemap_pdf_paths_normalize_negative_zero(translation: tuple[float, float]) -> None:
    path = PlotPath.unit_rectangle()
    transform = Affine2D().translate(*translation)
    original = PdfFile.pathOperations(path, transform)[0].pdfRepr()
    normalized = _CanonicalPdfFile.pathOperations(path, transform)[0].pdfRepr()

    assert b"-0" in original.split()
    assert normalized.split() == [
        b"0" if token == b"-0" else token for token in original.split()
    ]


def test_wavemap_pdf_image_compression_is_canonical_and_lossless(tmp_path: Path) -> None:
    image = Image.fromarray(np.arange(19 * 23 * 3, dtype=np.uint8).reshape(19, 23, 3))
    original_file = PdfFile(BytesIO())
    original_data, original_depth, original_palette = original_file._writePng(image)
    original_file.close()
    output = tmp_path / "canonical.pdf"
    with _CanonicalPdfPages(output, metadata={"CreationDate": None, "ModDate": None}) as pages:
        normalized, bit_depth, palette = pages._ensure_file()._writePng(image)
        assert zlib.decompress(normalized) == zlib.decompress(original_data)
        assert normalized == zlib.compress(zlib.decompress(original_data))
        assert (bit_depth, palette) == (original_depth, original_palette)
        figure = Figure(figsize=(1, 1))
        figure.subplots().imshow(image)
        pages.savefig(figure)
    pdf = PdfReader(output)
    assert len(pdf.pages) == 1
    images = pdf.pages[0]["/Resources"]["/XObject"].values()
    assert images
    for reference in images:
        stream = reference.get_object()
        assert stream._data == zlib.compress(zlib.decompress(stream._data))


def test_visual_cortex_plots_reuse_saved_coordinates_and_waveforms(snapshot: dict) -> None:
    figure, (embedding, waveform) = plt.subplots(1, 2)
    try:
        _plot_region_embedding(embedding, snapshot, "VIS")
        _plot_region_waveforms(waveform, snapshot, "VIS")
        units = snapshot["units_df"]
        selected = (units["wavemap_group"] == "VIS") & (units["wavemap_local"] > 0)
        classes = sorted(units.loc[selected, "wavemap_local"].astype(int).unique())
        assert len(embedding.collections) == len(classes)
        for collection, line, local in zip(
            embedding.collections, waveform.lines, classes, strict=False
        ):
            mask = selected & (units["wavemap_local"] == local)
            np.testing.assert_array_equal(
                collection.get_offsets(), units.loc[mask, ["umap_x", "umap_y"]].to_numpy()
            )
            np.testing.assert_array_equal(line.get_ydata(), snapshot["normWFs"][mask].mean(axis=0))
            np.testing.assert_array_equal(line.get_xdata(), np.arange(210))
        assert waveform.get_xlabel() == "Waveform sample"
    finally:
        plt.close(figure)


def test_main_waveform_legend_clears_the_axis_label(tmp_path, snapshot, monkeypatch) -> None:
    from openscope_p3_publication import wavemap_publication_figures as figures

    def check_layout(figure, name, output_dir):
        figure.canvas.draw()
        renderer = figure.canvas.get_renderer()
        axes = {axis.get_gid(): axis for axis in figure.axes if axis.get_gid()}
        waveform = axes["panel-A-visual-cortex-waveforms"]
        legend = axes["panel-A-waveform-legend"].get_legend()
        label_box = waveform.xaxis.label.get_window_extent(renderer)
        legend_box = legend.get_window_extent(renderer)
        assert label_box.y0 >= legend_box.y1 + 6
        plt.close(figure)
        return output_dir / f"{name}.png", output_dir / f"{name}.pdf"

    monkeypatch.setattr(figures, "_save", check_layout)
    figures.build_unified_cell_type_figure(snapshot, tmp_path)


@pytest.mark.parametrize("standalone", [False, True])
def test_context_panel_letters_match_publication_scale(
    tmp_path, snapshot, monkeypatch, standalone
) -> None:
    from openscope_p3_publication import wavemap_publication_figures as figures

    def check_labels(figure, name, output_dir, pages):
        labels = {text.get_text(): text for text in figure.texts}
        letters = ("A", "B") if standalone else ("D1", "D2")
        expected_size = 16 if standalone else 9
        assert all(labels[letter].get_fontsize() == expected_size for letter in letters)
        assert all(labels[letter].get_fontweight() == "bold" for letter in letters)
        if standalone:
            assert expected_size * 1200 / (figure.get_figwidth() * 72) >= 20
            assert labels["A"].get_position()[0] < labels["B"].get_position()[0]
            figure.canvas.draw()
            renderer = figure.canvas.get_renderer()
            plot_top = max(axis.get_window_extent(renderer).y1 for axis in figure.axes[:12])
            assert min(labels[letter].get_window_extent(renderer).y0 for letter in letters) > (
                plot_top
            )
        plt.close(figure)
        return output_dir / f"{name}.png", output_dir / f"{name}.pdf"

    monkeypatch.setattr(figures, "_save", check_labels)
    build_context_figure(snapshot, tmp_path, standalone=standalone)


def test_cell_type_split_keeps_main_and_supplementary_content_distinct(
    tmp_path: Path, snapshot: dict
) -> None:
    outputs = build_cell_type_static_figures(snapshot, tmp_path)
    assert len(outputs) == 20
    main = ET.parse(tmp_path / "cell-type-characterization.svg").getroot()
    assert main.attrib["data-region"] == "VIS"
    assert main.attrib["data-regions"] == "MO PFC VIS STR HPC THAL"
    assert main.attrib["data-unified-renderer"] == "true"
    assert (tmp_path / "cell-type-characterization.svg").stat().st_size < 8 * 1024 * 1024
    canvas_width = float(main.get("viewBox").split()[2])
    canvas_height = float(main.get("viewBox").split()[3])
    assert canvas_height / canvas_width < 0.6
    text_sizes = [float(element.get("font-size")) * 1200 / canvas_width
                  for element in main.iter("{http://www.w3.org/2000/svg}text")
                  if element.get("font-size")]
    assert min(text_sizes) >= 12
    namespace = "{http://www.w3.org/2000/svg}"
    for group in ("MO", "PFC", "VIS", "STR", "HPC", "THAL"):
        assert main.find(f".//{namespace}g[@id='panel-B-{group}']") is not None
    assert main.find(f".//{namespace}g[@id='panel-A-visual-cortex-waveforms']") is not None
    panel_ids = [element.get("id") for element in main.iter(f"{namespace}g")
                 if element.get("id", "").startswith("panel-")]
    assert panel_ids[0] == "panel-A-visual-cortex-waveforms"
    panel_letters = [main.find(f".//{namespace}g[@id='panel-label-{letter}']/{namespace}text")
                     for letter in "ABCDE"]
    assert float(panel_letters[0].get("x")) < float(panel_letters[1].get("x"))
    assert len({letter.get("font-size") for letter in panel_letters}) == 1
    assert {letter.get("font-family") for letter in panel_letters} == {
        "Arial, sans-serif"
    }
    assert "A shows the enlarged visual-cortex mean waveforms first" in main.findtext(
        "{http://www.w3.org/2000/svg}desc"
    )
    assert "B shows all six independently fitted regional maps" in main.findtext(
        "{http://www.w3.org/2000/svg}desc"
    )
    main_text = PdfReader(tmp_path / "cell-type-characterization.pdf").pages[0].extract_text()
    assert "5 Hz optotagging" not in main_text
    assert "Optotagged-cell yield" not in main_text
    assert "Visual cortex" in main_text
    assert "community mean waveforms" in main_text
    visual = PdfReader(tmp_path / "wavemap-visual-cortex.pdf").pages[0].extract_text()
    for label in ("Visual cortex", "VIS community waveforms", "Putative FS/PV-like",
                  "Optotagged SST", "SST and FS overlap", "Waveform sample"):
        assert label in visual
    regional = PdfReader(tmp_path / "wavemap-regional-waveforms.pdf").pages[0].extract_text()
    for label in ("Motor cortex", "Prefrontal cortex", "Visual cortex", "Striatum",
                  "Hippocampus", "Thalamus"):
        assert label in regional
    embeddings = PdfReader(tmp_path / "wavemap-regional-embeddings.pdf").pages[0].extract_text()
    for label in ("Motor cortex", "Prefrontal cortex", "Visual cortex", "Striatum",
                  "Hippocampus", "Thalamus"):
        assert label in embeddings
    composition = PdfReader(tmp_path / "wavemap-composition.pdf").pages[0].extract_text()
    assert "D1" not in composition and "D2" not in composition
    assert "Mean units per class (%)" in composition
    assert (tmp_path / "supplementary-optotagging-anatomy.svg").is_file()
    assert (tmp_path / "supplementary-wavemap-regions.svg").is_file()
    assert (tmp_path / "supplementary-wavemap-composition.svg").is_file()
    regional_root = ET.parse(tmp_path / "supplementary-wavemap-regions.svg")
    assert len(regional_root.findall(".//{http://www.w3.org/2000/svg}image")) == 6
    assert regional_root.findall(".//{http://www.w3.org/2000/svg}text")
    validation_root = ET.parse(tmp_path / "supplementary-cell-type-validation.svg")
    validation_box = [float(value) for value in validation_root.getroot().get("viewBox").split()]
    assert validation_box[3] / validation_box[2] < 0.72
    assert validation_root.find(
        f".//{namespace}g[@id='panel-D-anatomical-yield-continued']"
    ) is not None
    print_panels = json.loads(validation_root.getroot().get("data-print-panels"))
    assert [title for title, _ in print_panels] == ["A-B", "C-D", "E"]
    panel_c_label = validation_root.find(f".//{namespace}g[@id='panel-label-C']/{namespace}text")
    assert float(panel_c_label.get("y")) - float(panel_c_label.get("font-size")) >= (
        print_panels[1][1][1]
    )
    panel_e_label = validation_root.find(f".//{namespace}g[@id='panel-label-E']/{namespace}text")
    assert float(panel_e_label.get("y")) - float(panel_e_label.get("font-size")) >= (
        print_panels[2][1][1]
    )
    panel_labels = [
        validation_root.find(f".//{namespace}g[@id='panel-label-{letter}']/{namespace}text")
        for letter in "ABCDE"
    ]
    points_per_unit = min(170 / validation_box[2], 205 / validation_box[3]) * 72 / 25.4
    assert [float(label.get("font-size")) * points_per_unit
            for label in panel_labels] == pytest.approx([9] * 5)
    for column in ("putative_fs", "sst_optotagged", "sst_fs_overlap"):
        for group in ("MO", "PFC", "VIS", "STR", "HPC", "THAL"):
            assert validation_root.find(
                f".//{namespace}g[@id='panel-E-{column}-{group}']"
            ) is not None
    validation_pdf = PdfReader(tmp_path / "supplementary-cell-type-validation.pdf")
    validation_text = validation_pdf.pages[0].extract_text()
    assert "Optotagged cells / session" in validation_text
    assert "5 Hz optotagging control" in validation_text
    assert "Overall optotagged-cell yield" in validation_text
    assert "FS/PV-like" in validation_text
    assert "SST" in validation_text
    overlays = PdfReader(tmp_path / "wavemap-regional-overlays.pdf").pages[0].extract_text()
    assert "FS/PV-like" in overlays and "Optotagged" in overlays


@pytest.mark.parametrize(
    ("stem", "publication"),
    [
        ("wavemap-regional-waveforms", "supplementary-wavemap-regions"),
        ("wavemap-composition", "supplementary-wavemap-composition"),
    ],
)
def test_vector_supplement_serialization_is_deterministic(
    tmp_path: Path, stem: str, publication: str,
) -> None:
    import matplotlib.pyplot as plt

    from openscope_p3_publication import wavemap_publication_figures as figures

    def render() -> bytes:
        figure, axis = plt.subplots(figsize=(1.5, 1.2))
        axis.scatter([0, 1], [1, 0], rasterized=True)
        figure.text(0.01, 0.95, "A", gid="panel-label-A")
        figures._save(figure, stem, tmp_path)
        path = tmp_path / f"{publication}.svg"
        figures._image_svg(path, path, "Example", "Two measured points.")
        return path.read_bytes()

    assert render() == render()


def test_supplement_maps_do_not_touch_axis_labels(tmp_path, snapshot, monkeypatch) -> None:
    from openscope_p3_publication import wavemap_publication_figures as figures

    def check_layout(figure, name, output_dir, pages=None):
        figure.canvas.draw()
        renderer = figure.canvas.get_renderer()
        if name == "wavemap-regional-waveforms":
            for index in range(0, len(figure.axes), 3):
                embedding, waveform = figure.axes[index:index + 2]
                label_box = waveform.yaxis.label.get_window_extent(renderer)
                assert label_box.x0 >= embedding.get_window_extent(renderer).x1 + 6
        else:
            heatmaps = [axis for axis in figure.axes if axis.images]
            for index, axis in enumerate(heatmaps):
                labels = [label.get_window_extent(renderer) for label in axis.get_yticklabels()]
                assert all(label.x1 <= axis.get_window_extent(renderer).x0 - 4 for label in labels)
                if index % 3:
                    previous = heatmaps[index - 1].get_window_extent(renderer)
                    assert all(label.x0 >= previous.x1 + 4 for label in labels)
        plt.close(figure)
        return output_dir / f"{name}.png", output_dir / f"{name}.pdf"

    monkeypatch.setattr(figures, "_save", check_layout)
    figures.build_regional_waveform_figure(snapshot, tmp_path)
    figures.build_context_figure(snapshot, tmp_path, standalone=True)


def test_regional_waveforms_are_compact_with_aligned_panel_letters(
    tmp_path: Path, snapshot: dict
) -> None:
    png, pdf = build_regional_waveform_figure(snapshot, tmp_path)
    with Image.open(png) as image:
        assert image.height / image.width < 0.65
    labels = {}
    legend_positions = {}

    def collect(text, current_matrix, text_matrix, font, size):
        position = (current_matrix[4] + text_matrix[4], current_matrix[5] + text_matrix[5])
        if text.strip() in set("ABCDEF"):
            labels[text.strip()] = position
        for group in ("MO", "PFC", "VIS", "STR", "HPC", "THAL"):
            if text.strip().startswith(group + "-"):
                legend_positions.setdefault(group, []).append(position)

    PdfReader(pdf).pages[0].extract_text(visitor_text=collect)
    assert set(labels) == set("ABCDEF")
    for left, right in (("A", "B"), ("C", "D"), ("E", "F")):
        assert labels[left][1] == pytest.approx(labels[right][1], abs=0.1)
    assert len({round(labels[letter][0], 1) for letter in "ACE"}) == 1
    assert len({round(labels[letter][0], 1) for letter in "BDF"}) == 1
    for letter, group in zip("ABCDEF", ("MO", "PFC", "VIS", "STR", "HPC", "THAL"), strict=True):
        assert legend_positions[group]
        assert min(position[0] for position in legend_positions[group]) > labels[letter][0] + 150


def test_composition_panels_are_side_by_side(tmp_path: Path, snapshot: dict) -> None:
    png, pdf = build_context_figure(snapshot, tmp_path, standalone=True)
    with Image.open(png) as image:
        assert image.width > image.height * 1.3
    labels = {}

    def collect(text, current_matrix, text_matrix, font, size):
        if text.strip() in {"A", "B"}:
            labels[text.strip()] = (current_matrix[4] + text_matrix[4],
                                    current_matrix[5] + text_matrix[5])

    page = PdfReader(pdf).pages[0]
    text = page.extract_text(visitor_text=collect)
    assert labels["B"][0] > labels["A"][0] + 250
    assert labels["A"][1] == pytest.approx(labels["B"][1], abs=2)
    assert "Mean units per class (%)" in text
    assert "enrichment" in text


def test_wavemap_static_supplement_is_complete_and_deterministic(
    tmp_path: Path, snapshot: dict
) -> None:
    outputs = build_wavemap_static_figures(snapshot, tmp_path)
    assert len(outputs) == 10
    pdf = PdfReader(tmp_path / "supplementary-wavemap.pdf")
    assert len(pdf.pages) == 4
    assert pdf.metadata.creation_date is None
    assert pdf.metadata.title == "WaveMAP waveform characterization"
    assert "Waveform sample" in pdf.pages[1].extract_text()
    svg = ET.parse(tmp_path / "supplementary-wavemap.svg")
    assert svg.findtext(".//{http://www.w3.org/2000/svg}title") == (
        "WaveMAP waveform characterization"
    )
    images = svg.findall(".//{http://www.w3.org/2000/svg}image")
    assert len(images) == 4
    assert all(image.attrib["href"].startswith("data:image/png;base64,") for image in images)
    first = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in outputs}
    second = build_wavemap_static_figures(snapshot, tmp_path)
    assert first == {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in second}
