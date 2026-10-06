import base64
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from openscope_p3_publication.image_encoding import canonical_png, canonical_svg_images
from openscope_p3_publication.slap2_glutamate_figure7_panels import (
    EXAMPLE_PATH,
    event_table,
    load_example_snapshot,
    source_trace,
    write_slap2_glutamate_figure,
)
from openscope_p3_publication.slap2_glutamate_qc_events import (
    assign_classes,
    event_amplitudes_raw,
    sampling_interval,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "figure_sources/data/slap2-glutamate-qc"


def test_compact_traces_preserve_original_roi_identity() -> None:
    full = np.arange(60).reshape(10, 6)
    compact = {"data": full[:, [1, 4]], "roi_ids": np.array([1, 4])}

    np.testing.assert_array_equal(source_trace(compact, 4), full[:, 4])
    np.testing.assert_array_equal(source_trace({"data": full}, 4), full[:, 4])
    with pytest.raises(KeyError, match="ROI 3"):
        source_trace(compact, 3)


def test_image_encoding_preserves_pixels_and_normalizes_svg_ids() -> None:
    pixels = np.arange(400, dtype=np.uint8).reshape(10, 10, 4)
    original = io.BytesIO()
    Image.fromarray(pixels).save(original, format="PNG")
    normalized = canonical_png(original.getvalue())
    np.testing.assert_array_equal(np.asarray(Image.open(io.BytesIO(normalized))), pixels)
    assert canonical_png(normalized) == normalized
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
        '<image id="{identifier}" xlink:href="data:image/png;base64,{encoded}"/>'
        '<use xlink:href="#{identifier}"/></svg>'
    )
    first = svg.format(identifier="first", encoded=base64.b64encode(original.getvalue()).decode())
    second = svg.format(identifier="second", encoded=base64.b64encode(normalized).decode())
    assert canonical_svg_images(first) == canonical_svg_images(second)


def test_example_snapshot_checks_checksum_and_numeric_arrays(tmp_path: Path) -> None:
    output = tmp_path / "example.npz"
    traces = np.arange(20, dtype=np.float32).reshape(10, 2)
    np.savez_compressed(
        output, schema_version=np.array(1), session_id=np.array("example-session"),
        trace_dmds=np.array([2]), plane_dmds=np.array([1]),
        data2=traces, ts2=np.arange(10) * 0.005, dt2=np.array(0.005),
        roi_ids2=np.array([1, 4]), activity1=np.ones((4, 5)), mean1=np.ones((4, 5)),
        outlines1=np.ones((2, 4, 5), dtype=bool),
    )
    output.with_suffix(".provenance.json").write_text(
        json.dumps({"output_sha256": hashlib.sha256(output.read_bytes()).hexdigest()}),
        encoding="utf-8",
    )

    session = load_example_snapshot(output)
    assert session["session_id"] == "example-session"
    np.testing.assert_array_equal(source_trace(session["traces"][2], 4), traces[:, 1])
    assert len(session["planes"][1][2]) == 2
    output.write_bytes(b"changed snapshot")
    with pytest.raises(ValueError, match="checksum"):
        load_example_snapshot(output)


def test_archived_classes_reproduce_without_nwb() -> None:
    metrics = pd.read_csv(DATA_DIR / "slap2_metrics_all_sessions.csv")
    reproduced = assign_classes(metrics)

    assert len(metrics) == 2540
    assert metrics.session.nunique() == 20
    assert metrics.subject.nunique() == 8
    pd.testing.assert_series_equal(reproduced.quality_class, metrics.quality_class)
    assert metrics.quality_class.value_counts().to_dict() == {
        "Intermediate": 1026,
        "High SNR": 830,
        "Low SNR": 665,
        "Excluded (no baseline noise)": 19,
    }


def test_context_records_preserve_source_counts_and_rate_definition() -> None:
    metrics = pd.read_csv(DATA_DIR / "slap2_metrics_all_sessions.csv")
    contexts = pd.read_csv(DATA_DIR / "slap2_context_rates_all_sessions.csv")
    keys = ["subject", "session", "dmd", "roi"]

    assert not contexts.duplicated(keys + ["context"]).any()
    assert contexts.n_events.gt(0).all()
    assert contexts.seconds.gt(0).all()
    np.testing.assert_allclose(contexts.rate_hz, contexts.n_events / contexts.seconds)
    joined = contexts.merge(metrics[keys + ["quality_class"]], on=keys, validate="many_to_one")
    assert (joined.quality_class_x == joined.quality_class_y).all()
    expected = metrics.loc[metrics.n_events.gt(0)].set_index(keys).n_events.sort_index()
    observed = contexts.groupby(keys).n_events.sum().sort_index()
    pd.testing.assert_series_equal(observed, expected)


def test_selected_example_reproduces_original_source_measurements() -> None:
    provenance = json.loads(EXAMPLE_PATH.with_suffix(".provenance.json").read_text())
    session = load_example_snapshot(EXAMPLE_PATH)
    metrics = pd.read_csv(DATA_DIR / "slap2_metrics_all_sessions.csv")
    example = metrics.loc[metrics.session == session["session_id"]].set_index(["dmd", "roi"])

    assert provenance["large_snapshot_approved"] is True
    assert EXAMPLE_PATH.stat().st_size == provenance["output_bytes"]
    assert EXAMPLE_PATH.stat().st_size < 100 * 1024 * 1024
    assert len(provenance["source_assets"]) == 20
    assert all(asset["digest"] for asset in provenance["source_assets"])
    assert {record["dmd"] for record in provenance["selected_sources"]} == {1, 2}
    assert len(provenance["selected_sources"]) == 4
    assert [len(session["planes"][dmd][2]) for dmd in (1, 2)] == [120, 59]
    for record in provenance["selected_sources"]:
        trace_data = session["traces"][record["dmd"]]
        events = event_table(
            source_trace(trace_data, record["roi"]), trace_data["ts"], trace_data["dt"]
        )
        expected = example.loc[record["dmd"], record["roi"]]
        assert len(events["idx"]) == expected.n_events
        assert events["raw_sd"] == pytest.approx(expected.noise_dff, rel=1e-6)
        assert np.nanmedian(events["amp_raw"]) == pytest.approx(
            expected.median_event_raw_sd, rel=1e-6
        )


def test_missing_samples_do_not_create_amplitudes() -> None:
    assert sampling_interval(np.array([0.0, 0.005, np.nan, 0.015, 0.020])) == pytest.approx(0.005)
    amplitudes = event_amplitudes_raw(np.full(100, np.nan), np.array([50]), 0.005, 1.0)
    assert np.isnan(amplitudes).all()
    with pytest.raises(ValueError, match="sampling interval"):
        sampling_interval(np.array([1.0, 0.0]))


def test_notebook_is_thin_offline_and_has_no_saved_outputs() -> None:
    notebook_path = REPO_ROOT / "figure_sources/python/slap2_glutamate_figure7_panels.ipynb"
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    code = "\n".join(
        "".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code"
    )
    assert notebook_path.stat().st_size < 100_000
    assert "load_example_snapshot" in code
    assert "download.download" not in code
    assert "qc.compute(" not in code
    for cell in notebook["cells"]:
        assert not cell.get("outputs")
        assert cell.get("execution_count") is None


def test_publication_figure_builds_without_network(tmp_path: Path, monkeypatch, capsys) -> None:
    import socket

    def reject_network(*args, **kwargs):
        raise AssertionError("The figure build must not open network connections.")

    monkeypatch.setattr(socket, "socket", reject_network)
    output = write_slap2_glutamate_figure(tmp_path / "figure-07.svg")
    text = output.read_text(encoding="utf-8")
    assert "SLAP2 glutamate signal-quality analysis" in text
    assert text.count("data:image/svg+xml;base64,") == 3
    assert len(list(tmp_path.glob("figure7_panel*.png"))) == 5
    assert len(list(tmp_path.glob("figure7_panel*.svg"))) == 5
    first_build = {asset.name: asset.read_bytes() for asset in tmp_path.iterdir()}
    write_slap2_glutamate_figure(output)
    assert {asset.name: asset.read_bytes() for asset in tmp_path.iterdir()} == first_build
    assert capsys.readouterr().out.isascii()