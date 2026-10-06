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


def test_wavemap_is_a_supplement_not_a_replacement() -> None:
    manuscript = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    assert manuscript.count(":label: fig-supp-wavemap") == 1
    assert "[Supplementary Figure 9](#fig-supp-wavemap)" in manuscript
    assert ":placeholder: ./images/figures/generated/supplementary-wavemap.svg" in manuscript
    assert ":label: fig-unit-extraction-plan" in manuscript
    assert ":label: fig-supp-optotagging-heatmaps" in manuscript
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
    assert template.count('role="tab"') == 4
    assert "__WAVEMAP_STATIC__" in template


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


def test_wavemap_static_supplement_is_complete_and_deterministic(
    tmp_path: Path, snapshot: dict
) -> None:
    outputs = build_wavemap_static_figures(snapshot, tmp_path)
    assert len(outputs) == 10
    pdf = PdfReader(tmp_path / "supplementary-wavemap.pdf")
    assert len(pdf.pages) == 4
    assert pdf.metadata.creation_date is None
    assert "Waveform sample" in pdf.pages[1].extract_text()
    svg = ET.parse(tmp_path / "supplementary-wavemap.svg")
    images = svg.findall(".//{http://www.w3.org/2000/svg}image")
    assert len(images) == 4
    assert all(image.attrib["href"].startswith("data:image/png;base64,") for image in images)
    first = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in outputs}
    second = build_wavemap_static_figures(snapshot, tmp_path)
    assert first == {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in second}
