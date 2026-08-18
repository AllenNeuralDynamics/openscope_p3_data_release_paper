import base64
import csv
import hashlib
import json
import math
import re
import statistics
import struct
from io import BytesIO
from pathlib import Path

import pytest

from openscope_p3_publication.figures import (
    ANIMAL_RECORDS_PATH,
    ANIMAL_RECORDS_PROVENANCE_PATH,
    BEHAVIOR_EXCERPTS_PATH,
    BEHAVIOR_STATIC_FRAME_DIR,
    BEHAVIOR_STATIC_FRAME_PROVENANCE_PATH,
    BLOCKS,
    DATA_ACCESS_PATH,
    DATA_ACCESS_PROVENANCE_PATH,
    EYE_TRACKING_EXCERPTS_PATH,
    FIGURE_MONO_FONT,
    FIGURE_REFERENCE_WIDTH,
    FIGURE_SANS_FONT,
    FIGURE_TEXT_MARGIN,
    FIGURE_TYPE_SCALE,
    HARDWARE_DESCRIPTION_FONT_SIZE,
    NEURAL_EXCERPTS_PATH,
    NEURAL_MEDIA_DIR,
    NEURAL_STATIC_FRAME_DIR,
    NEURAL_STATIC_FRAME_PROVENANCE_PATH,
    NEUROPIXELS_TRAJECTORY_DATA_PATH,
    NEUROPIXELS_TRAJECTORY_PROVENANCE_PATH,
    OPTOTAGGING_HEATMAP_DATA_PATH,
    OPTOTAGGING_HEATMAP_PROVENANCE_PATH,
    OPTOTAGGING_HEATMAP_SOURCE_DIR,
    OPTOTAGGING_STATIC_LEGACY_SOURCE,
    OPTOTAGGING_STATIC_SOURCE,
    OPTOTAGGING_STATIC_SUMMARY_PATH,
    REPO_ROOT,
    RUNNING_STATISTICS_PATH,
    SEGMENTATION_VIEWER_DATA_PATH,
    SEGMENTATION_VIEWER_OUTPUT,
    SEGMENTATION_VIEWER_PROVENANCE_PATH,
    SEGMENTATION_VIEWER_STATIC_OUTPUT,
    SEGMENTATION_VIEWER_STATIC_OUTPUTS,
    SESSION_RECORDS_PATH,
    SESSION_RECORDS_PROVENANCE_PATH,
    SESSION_TYPE_COLORS,
    SESSIONS,
    STIMULUS_EXCERPT_PROVENANCE_PATH,
    STIMULUS_SOURCES_PATH,
    UNIT_YIELD_DATA_PATH,
    UNIT_YIELD_PROVENANCE_PATH,
    ZEBRA_MOVIE_SOURCE,
    ZEBRA_POSTER_SOURCE,
    common_median_corrected_rgb,
    load_behavior_excerpts,
    load_data_access_table,
    load_experimental_design_sources,
    load_experimental_session_records,
    load_eye_tracking_excerpts,
    load_hardware_sources,
    load_neural_excerpts,
    load_neuropixels_trajectory_data,
    load_optotagging_heatmap_data,
    load_optotagging_static_summary,
    load_publication_table_data,
    load_running_statistics,
    load_segmentation_viewers,
    load_shared_stimulus_table_excerpts,
    load_stimulus_table_excerpts,
    load_unit_yield_data,
    modality_session_records,
    session_panel_rows,
    text_sha256_matches,
    total_duration_minutes,
    write_basic_stimuli_plan_svg,
    write_behavior_static_svg,
    write_behavior_viewer_html,
    write_context_controls_svg,
    write_data_explorer_html,
    write_eye_tracking_static_svg,
    write_eye_tracking_viewer_html,
    write_figure_1_panel_c_svg,
    write_hardware_figure_svg,
    write_interactive_html,
    write_literature_comparison_html,
    write_merged_figure_1_svg,
    write_neural_static_svg,
    write_neural_viewer_html,
    write_neuropixels_trajectory_html,
    write_neuropixels_trajectory_svg,
    write_optotagging_heatmap_html,
    write_optotagging_heatmap_svg,
    write_optotagging_static_source,
    write_segmentation_viewer_html,
    write_segmentation_viewer_static_svg,
    write_segmentation_viewer_svg,
    write_segmentation_viewers,
    write_session_inventory_svg,
    write_standard_oddball_plan_svg,
    write_static_svg,
    write_svg_output,
    write_unit_extraction_plan_svg,
    write_unit_yield_html,
    write_unit_yield_svg,
)

try:
    import numpy as np
    import pandas as pd
    from PIL import Image

    from openscope_p3_publication.optotagging import (
        CONDITIONS,
        SessionAnalysis,
        SessionSkipped,
        _unit_anatomy_acronyms,
        allen_major_parent_acronyms,
        baseline_zscore,
        build_session_numeric_atlas,
        compute_psth,
        compute_response_metrics,
        expand_pulse_times,
        heatmap_response_scores,
        mean_firing_rate_during_pulses,
        order_heatmap_rows,
        quantize_zscores,
        strongest_first_indices,
        validate_nwb,
        write_results,
    )
except ModuleNotFoundError:
    HAS_OPTOTAGGING_ANALYSIS_DEPS = False
else:
    HAS_OPTOTAGGING_ANALYSIS_DEPS = True

requires_optotagging_analysis_deps = pytest.mark.skipif(
    not HAS_OPTOTAGGING_ANALYSIS_DEPS,
    reason="Optotagging analysis dependencies are installed ad hoc by the extractor.",
)


def assert_modality_title_scale(svg: str, expected_count: int = 3) -> None:
    canvas_width = float(re.search(r'<svg[^>]+width="([^"]+)"', svg).group(1))
    font_sizes = [
        float(size)
        for size in re.findall(
            r'<text class="[^"]*modality-title[^"]*"[^>]*font-size="([^"]+)"',
            svg,
        )
    ]
    expected_size = canvas_width / FIGURE_REFERENCE_WIDTH * FIGURE_TYPE_SCALE["modality"]
    assert len(font_sizes) == expected_count
    assert font_sizes == pytest.approx([expected_size] * expected_count, abs=0.01)


def test_svg_output_uses_lf_line_endings(tmp_path: Path) -> None:
    output = tmp_path / "output.svg"
    write_svg_output(
        output,
        [
            '<svg xmlns="http://www.w3.org/2000/svg" width="1200">',
            f'<text font-family="{FIGURE_SANS_FONT}" font-size="12">Test</text>',
            "</svg>",
        ],
    )

    assert output.read_bytes().endswith(b"</svg>\n")
    assert b"\r\n" not in output.read_bytes()


def test_experimental_design_data() -> None:
    assert FIGURE_SANS_FONT == "Myriad Pro, Arial, sans-serif"
    assert FIGURE_MONO_FONT == "IBM Plex Mono, monospace"
    assert FIGURE_REFERENCE_WIDTH == 1200
    assert FIGURE_TEXT_MARGIN == 8
    assert HARDWARE_DESCRIPTION_FONT_SIZE == 12
    assert FIGURE_TYPE_SCALE == {
        "panel": 34,
        "title": 28,
        "heading": 24,
        "modality": 20,
        "label": 15,
        "small": 12,
    }
    assert len(SESSIONS) == 4
    assert len(BLOCKS) == 8
    assert total_duration_minutes() == pytest.approx(71.3)
    assert SESSION_TYPE_COLORS == {
        "sensorimotor": "#283185",
        "standard": "#22BCAD",
        "sequence": "#B16027",
        "duration": "#CCAF2D",
    }
    assert {session.name: session.color for session in SESSIONS} == {
        "Standard oddball": "#22BCAD",
        "Sensorimotor mismatch": "#283185",
        "Sequence mismatch": "#B16027",
        "Duration mismatch": "#CCAF2D",
    }


def test_interactive_figures_share_readable_typography() -> None:
    source_dir = REPO_ROOT / "figure_sources" / "javascript"
    typography = (source_dir / "figure-typography.css").read_text(encoding="utf-8")
    assert "--figure-type-panel-title: 1.25rem" in typography
    assert "--figure-type-section-title: 1rem" in typography
    assert "--figure-type-body: 0.875rem" in typography
    assert "--figure-type-control: 0.8125rem" in typography
    assert "--figure-type-metadata: 0.75rem" in typography
    assert "--figure-type-axis: 0.75rem" in typography

    stylesheets = sorted(source_dir.glob("*.css"))
    panel_stylesheets = [
        path for path in stylesheets if path.name != "figure-typography.css"
    ]
    for path in panel_stylesheets:
        content = path.read_text(encoding="utf-8")
        for value, unit in re.findall(r"font-size:\s*([0-9.]+)(px|rem)", content):
            pixels = float(value) * (16 if unit == "rem" else 1)
            assert pixels >= 12, (path.name, pixels)

    for name in ("neural-viewer.js", "segmentation-viewer.js"):
        javascript = (source_dir / name).read_text(encoding="utf-8")
        assert all(int(size) >= 12 for size in re.findall(r"\bsize:\s*(\d+)", javascript))

    for path in sorted((REPO_ROOT / "interactive").glob("*.html")):
        assert "--figure-type-metadata: 0.75rem" in path.read_text(encoding="utf-8")

    for path in sorted((REPO_ROOT / "images" / "figures" / "generated").glob("*.svg")):
        svg = path.read_text(encoding="utf-8")
        width_match = re.search(r'<svg[^>]+width="([0-9.]+)"', svg)
        sizes = [float(size) for size in re.findall(r'font-size="([0-9.]+)"', svg)]
        if width_match is None or not sizes:
            continue
        if path.name in {"figure-01-overview.svg", "raw-neural-recordings.svg"}:
            minimum = min(sizes)
        else:
            minimum = (
                min(sizes)
                * FIGURE_REFERENCE_WIDTH
                / float(width_match.group(1))
            )
        assert minimum >= FIGURE_TYPE_SCALE["small"], (path.name, minimum)


def test_session_type_colors_are_consistent_across_figure_surfaces() -> None:
    context_surfaces = (
        REPO_ROOT / "figure_sources/data/experimental-design-sessions.csv",
        REPO_ROOT / "figure_sources/javascript/behavior-viewer.css",
        REPO_ROOT / "figure_sources/javascript/behavior-viewer.js",
        REPO_ROOT / "interactive/behavior-viewer.html",
        REPO_ROOT / "interactive/experimental-design.html",
        REPO_ROOT / "images/figures/generated/experimental-design.svg",
        REPO_ROOT / "images/figures/generated/figure-01-panel-c-cohorts.svg",
        REPO_ROOT / "images/figures/generated/session-inventory.svg",
        REPO_ROOT / "images/figures/generated/synchronized-behavior.svg",
    )
    legacy_colors = ("#008F80", "#3157B7", "#C65D13", "#A47C00")
    combined = "\n".join(path.read_text(encoding="utf-8") for path in context_surfaces)
    assert not any(color.lower() in combined.lower() for color in legacy_colors)
    assert all(color.lower() in combined.lower() for color in SESSION_TYPE_COLORS.values())


def test_unit_yield_calculation_uses_calendar_days_and_day_one_baseline(
    tmp_path: Path,
) -> None:
    data_path = tmp_path / "unit-yield.csv"
    data_path.write_text(
        "dandiset_id,asset_id,asset_path,session_id,mouse_id,date,total_unit_count,"
        "qc_unit_count,probe_count,probe_names\n"
        "001637,a,path-a,101_2026-01-01_10-00-00,101,2026-01-01,120,100,2,ProbeA;ProbeB\n"
        "001637,b,path-b,101_2026-01-03_10-00-00,101,2026-01-03,96,80,2,ProbeA;ProbeB\n"
        "001637,c,path-c,202_2026-02-01_10-00-00,202,2026-02-01,180,150,3,ProbeA;ProbeB;ProbeC\n",
        encoding="utf-8",
    )
    provenance_path = data_path.with_suffix(".provenance.json")
    provenance_path.write_text(
        json.dumps(
            {
                "dandiset_id": "001637",
                "rows": 3,
                "source_url": "https://dandiarchive.org/dandiset/001637/draft",
                "vendored_sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )

    payload = load_unit_yield_data(data_path, provenance_path)

    assert [record["day"] for record in payload["records"]] == [1, 3, 1]
    assert [record["percentOfDay1"] for record in payload["records"]] == [100, 80, 100]
    assert payload["summary"] == [
        {
            "day": 1,
            "meanPercent": 100,
            "meanUnitsPerProbe": 50,
            "sessionCount": 2,
        },
        {
            "day": 3,
            "meanPercent": 80,
            "meanUnitsPerProbe": 40,
            "sessionCount": 1,
        },
    ]


def test_unit_yield_snapshot_is_source_backed() -> None:
    payload = load_unit_yield_data()
    provenance = json.loads(UNIT_YIELD_PROVENANCE_PATH.read_text(encoding="utf-8"))

    assert hashlib.sha256(UNIT_YIELD_DATA_PATH.read_bytes()).hexdigest() == (
        provenance["vendored_sha256"]
    )
    assert provenance["rows"] == 60
    assert provenance["subjects"] == 16
    assert len(provenance["skipped_assets"]) == 2
    assert {row["reason"] for row in provenance["skipped_assets"]} == {
        "missing-units-table"
    }
    assert len(payload["records"]) == 60
    assert {record["probeCount"] for record in payload["records"]} == {5, 6}
    assert [row["sessionCount"] for row in payload["summary"]] == [16, 15, 15, 14]
    assert payload["summary"][-1]["meanPercent"] == pytest.approx(80.9230526465)


def test_unit_yield_outputs_are_deterministic_and_inspectable(tmp_path: Path) -> None:
    html_path = write_unit_yield_html(tmp_path / "unit-yield.html")
    svg_path = write_unit_yield_svg(tmp_path / "unit-yield.svg")
    html = html_path.read_text(encoding="utf-8")
    svg = svg_path.read_text(encoding="utf-8")

    assert 'id="unit-yield-chart" viewBox="0 0 960 410"' in html
    assert "const mouseNeutral = \"#9AA29F\"" in html
    assert "const selectedMouse = \"#087F8C\"" in html
    assert 'state.metric === "percent" ? 140' in html
    assert "min-width: 620px;" in html
    assert "@media (max-width: 560px)" in html
    assert 'id="mouse-select"' in html
    assert '<details class="data-disclosure" id="session-data">' in html
    assert '<details class="data-disclosure" id="session-data" open>' not in html
    assert 'id="session-table-body"' in html
    assert 'id="session-row-count">60 rows' in html
    assert "QC units / probe" in html
    assert "Download visible session data as CSV" in html
    assert 'class="viewer-header"' not in html
    assert "DANDI source" not in html
    assert '"sessionCount":14' in html
    assert 'document.querySelector("body > main")' in html
    assert "__UNIT_YIELD_" not in html
    assert "__EMBED_AUTO_HEIGHT_JS__" not in html
    assert 'role="img"' in svg
    assert "QC-passing Neuropixels unit yield" in svg
    assert "Day 4" in svg
    assert ">140</text>" in svg
    assert 'stroke="#9AA29F"' in svg
    assert 'stroke="#E2E5E4"' not in svg

    write_unit_yield_html(html_path)
    write_unit_yield_svg(svg_path)
    assert html_path.read_text(encoding="utf-8") == html
    assert svg_path.read_text(encoding="utf-8") == svg


@requires_optotagging_analysis_deps
def test_expand_optotagging_pulse_times_uses_duration_and_frequency() -> None:
    pulses = expand_pulse_times(
        np.array([1.0, 3.0]),
        np.array([1.0, 0.5]),
        frequency_hz=5.0,
    )

    assert pulses == pytest.approx([1.0, 1.2, 1.4, 1.6, 1.8, 3.0, 3.2])


@requires_optotagging_analysis_deps
def test_optotagging_psth_returns_event_averaged_rate() -> None:
    centers, rates = compute_psth(
        np.array([0.001, 1.001]),
        np.array([0.0, 1.0]),
        window=(0.0, 0.004),
        bin_seconds=0.001,
    )

    assert centers == pytest.approx([0.0005, 0.0015, 0.0025, 0.0035])
    assert rates == pytest.approx([0.0, 1000.0, 0.0, 0.0])


@requires_optotagging_analysis_deps
def test_optotagging_response_metrics_match_paired_pre_post_counts() -> None:
    condition = CONDITIONS[1]
    metrics = compute_response_metrics(
        np.array([-0.005, 0.004, 0.006, 0.995, 1.004, 1.006]),
        np.array([0.0, 1.0]),
        condition,
    )

    assert metrics["pre_mean"] == pytest.approx(100.0)
    assert metrics["post_mean"] == pytest.approx(200.0)
    assert metrics["modulation_index"] == pytest.approx(1 / 3)
    assert 0.0 <= metrics["p_value"] <= 1.0


@requires_optotagging_analysis_deps
def test_optotagging_response_metrics_can_skip_unused_wilcoxon() -> None:
    metrics = compute_response_metrics(
        np.array([-0.005, 0.004, 0.006]),
        np.array([0.0]),
        CONDITIONS[1],
        compute_p_value=False,
    )

    assert metrics["pre_mean"] == pytest.approx(100.0)
    assert metrics["post_mean"] == pytest.approx(200.0)
    assert metrics["modulation_index"] == pytest.approx(1 / 3)
    assert np.isnan(metrics["p_value"])


@requires_optotagging_analysis_deps
def test_optotagging_heatmap_normalization_and_modulation_ordering() -> None:
    time_seconds = np.array([-0.002, -0.001, 0.001, 0.002])
    psths = np.array(
        [
            [0.0, 2.0, 5.0, 5.0],
            [0.0, 2.0, 2.0, 2.0],
        ]
    )

    zscored = baseline_zscore(psths, time_seconds)
    order = order_heatmap_rows(np.array([0.8, -0.2, np.nan, 0.8]))

    assert zscored[0] == pytest.approx([-1.0, 1.0, 4.0, 4.0])
    assert order.tolist() == [2, 1, 0, 3]


@requires_optotagging_analysis_deps
def test_optotagging_mean_firing_rate_during_exact_laser_pulses() -> None:
    rate = mean_firing_rate_during_pulses(
        spike_times=np.array(
            [
                0.001,
                0.009,
                0.015,
                0.201,
                0.209,
                0.215,
                0.401,
                0.409,
                0.415,
            ]
        ),
        pulse_times=np.array([0.0, 0.2, 0.4]),
        pulse_width_seconds=0.010,
    )

    assert rate == pytest.approx(200.0)


@requires_optotagging_analysis_deps
def test_optotagging_heatmap_ordering_uses_exact_laser_rate() -> None:
    analysis = type(
        "Analysis",
        (),
        {
            "metrics": pd.DataFrame(
                {"raised_cosine_presentations__modulation_index": [0.2, 0.8]}
            ),
            "pulse_firing_rates": {
                "raised_cosine_presentations": np.array([7.0, 3.0]),
                "5 hz pulse train_presentations": np.array([40.0, 10.0]),
                "40 hz pulse train_presentations": np.array([5.0, 25.0]),
            },
        },
    )()

    raised_scores, raised_label = heatmap_response_scores(analysis, CONDITIONS[0])
    five_hz_scores, five_hz_label = heatmap_response_scores(analysis, CONDITIONS[1])
    forty_hz_scores, forty_hz_label = heatmap_response_scores(analysis, CONDITIONS[2])

    assert raised_scores.tolist() == [7.0, 3.0]
    assert raised_label == "mean firing during 1000 ms pulses"
    assert five_hz_scores.tolist() == [40.0, 10.0]
    assert five_hz_label == "mean firing during 10 ms pulses"
    assert forty_hz_scores.tolist() == [5.0, 25.0]
    assert forty_hz_label == "mean firing during 6 ms pulses"


@requires_optotagging_analysis_deps
def test_optotagging_strongest_first_order_is_stable_and_puts_nan_last() -> None:
    order = strongest_first_indices(np.array([2.0, np.nan, 4.0, 4.0, -1.0]))

    assert order.tolist() == [2, 3, 0, 4, 1]


@requires_optotagging_analysis_deps
def test_optotagging_allen_major_parent_mapping_uses_hierarchy() -> None:
    class Regions:
        def acronym2id(self, acronym):
            return {"VISp": np.array([1]), "CP": np.array([2]), "unknown": np.array([])}[
                acronym
            ]

        def ancestors(self, region_id):
            values = {
                1: np.array(["root", "CH", "CTX", "Isocortex", "VISp"]),
                2: np.array(["root", "CH", "CNU", "STR", "STRd", "CP"]),
            }
            return type("Ancestors", (), {"acronym": values[region_id]})()

    parents = allen_major_parent_acronyms(
        ["VISp", "CP", "unknown"],
        brain_regions=Regions(),
    )

    assert parents.tolist() == ["Isocortex", "STR", "Other"]


@requires_optotagging_analysis_deps
def test_optotagging_unit_anatomy_uses_ragged_electrode_references() -> None:
    nwb = {
        "units": {
            "id": np.array([1, 2]),
            "electrodes": np.array([4, 2, 3]),
            "electrodes_index": np.array([2, 3]),
            "extremum_channel_index": np.array([1, 0]),
        },
        "general/extracellular_ephys/electrodes": {
            "location": np.array(["A", "B", "VISp", "CP", "TH"]),
        },
    }

    assert _unit_anatomy_acronyms(nwb).tolist() == ["VISp", "CP"]


@requires_optotagging_analysis_deps
def test_optotagging_unit_anatomy_uses_probe_local_extremum_indices() -> None:
    nwb = {
        "units": {
            "id": np.array([1, 2]),
            "device_name": np.array(["ProbeA", "ProbeB"]),
            "extremum_channel_index": np.array([1, 0]),
        },
        "general/extracellular_ephys/electrodes": {
            "group_name": np.array(["ProbeA", "ProbeB", "ProbeA"]),
            "location": np.array(["VISp", "TH", "CP"]),
        },
    }

    assert _unit_anatomy_acronyms(nwb).tolist() == ["CP", "TH"]


@requires_optotagging_analysis_deps
def test_optotagging_unit_anatomy_is_optional_for_legacy_nwbs() -> None:
    nwb = {"units": {"id": np.array([1, 2])}}

    assert _unit_anatomy_acronyms(nwb).tolist() == ["Other", "Other"]


@requires_optotagging_analysis_deps
def test_optotagging_numeric_atlas_retains_rows_and_laser_orders() -> None:
    time_seconds = np.linspace(-0.5, 1.2, 10, endpoint=False)
    psths = np.array(
        [
            np.linspace(0, 9, 10),
            np.linspace(9, 0, 10),
            np.ones(10),
        ]
    )
    analysis = SessionAnalysis(
        session_id="ecephys_test",
        asset_id="asset",
        asset_path="session.nwb",
        metrics=pd.DataFrame({"unit_id": ["a", "b", "c"]}),
        psths={condition.table_name: psths for condition in CONDITIONS},
        pulse_firing_rates={
            condition.table_name: np.array([2.0, 5.0, np.nan])
            for condition in CONDITIONS
        },
        time_seconds=time_seconds,
        trial_counts={condition.table_name: 1 for condition in CONDITIONS},
        pulse_counts={condition.table_name: 1 for condition in CONDITIONS},
        unit_count=3,
        major_parent_acronyms=np.array(["TH", "Isocortex", "TH"]),
    )

    metadata, image = build_session_numeric_atlas(analysis)

    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(BytesIO(image)) as atlas_image:
        assert atlas_image.mode == "L"
        assert atlas_image.size == (10, 9)
    assert metadata["parent_areas"] == ["Isocortex", "TH"]
    assert metadata["parent_codes"] == [1, 0, 1]
    assert metadata["strongest_first_unit_indices"][
        "raised_cosine_presentations"
    ] == [1, 0, 2]
    assert metadata["time_bin_count"] == 10
    assert metadata["quantization"]["dtype"] == "int8"
    assert metadata["quantization"]["scale"] == pytest.approx(127 / 8)


@requires_optotagging_analysis_deps
def test_optotagging_atlas_quantization_reserves_nan_sentinel() -> None:
    quantized = quantize_zscores(
        np.array([-9.0, -8.0, -4.0, 0.0, 4.0, 8.0, 9.0, np.nan])
    )

    assert quantized.dtype == np.int8
    assert quantized.tolist() == [-127, -127, -64, 0, 64, 127, 127, -128]


@requires_optotagging_analysis_deps
def test_optotagging_validate_nwb_reports_missing_conditions() -> None:
    with pytest.raises(SessionSkipped, match="missing optotagging tables"):
        validate_nwb({"intervals": {}, "units": {}})


@requires_optotagging_analysis_deps
def test_optotagging_write_results_round_trips_parquet(tmp_path: Path) -> None:
    metric_columns = {
        "asset_id": ["asset-1"],
        "asset_path": ["sub-1/session.nwb"],
        "session_id": ["ecephys_1"],
        "unit_id": ["unit-1"],
    }
    for condition in CONDITIONS:
        for metric in ("pre_mean", "post_mean", "modulation_index", "p_value"):
            metric_columns[f"{condition.table_name}__{metric}"] = [0.25]
    metrics = pd.DataFrame(metric_columns)
    assets = [
        {
            "asset_id": "asset-1",
            "asset_path": "sub-1/session.nwb",
            "modified": "2026-01-01T00:00:00+00:00",
            "size": 123,
        }
    ]

    parquet_path, provenance_path = write_results(
        metrics,
        assets=assets,
        skipped=[],
        failed=[],
        output_dir=tmp_path,
    )

    pd.testing.assert_frame_equal(pd.read_parquet(parquet_path), metrics)
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    assert provenance["rows"] == 1
    assert provenance["sessions"] == 1
    assert len(provenance["output_sha256"]) == 64


def test_optotagging_snapshot_is_source_backed(tmp_path: Path) -> None:
    payload = load_optotagging_heatmap_data()
    provenance = json.loads(
        OPTOTAGGING_HEATMAP_PROVENANCE_PATH.read_text(encoding="utf-8")
    )

    assert text_sha256_matches(
        OPTOTAGGING_HEATMAP_DATA_PATH,
        provenance["manifest_sha256"],
    )
    assert payload["session_count"] == 3
    assert payload["version"] == 2
    assert payload["total_unit_count"] == sum(
        session["unit_count"] for session in payload["sessions"]
    )
    assert payload["default_session_id"] == "ecephys_830851_2026-03-19_10-49-11"
    assert (
        payload["static_example_session_id"]
        == "ecephys_830851_2026-03-19_10-49-11"
    )
    assert len(payload["sessions"]) == 3
    assert payload["selection"] == {
        "strategy": "nearest_all_session_optotagged_cell_yield_percentiles",
        "source_session_count": 60,
        "sessions": {
            "ecephys_830851_2026-03-19_10-49-11": {
                "optotagged_cell_count": 39,
                "target_yield_percentile": 0.5,
            },
            "ecephys_832691_2026-03-24_10-04-30": {
                "optotagged_cell_count": 84,
                "target_yield_percentile": 0.95,
            },
            "ecephys_848390_2026-05-06_09-54-56": {
                "optotagged_cell_count": 68,
                "target_yield_percentile": 0.8,
            },
        },
    }
    assert provenance["failed_assets"] == []
    assert provenance["skipped_assets"] == []
    assert provenance["source_session_count"] == 60
    assert len(provenance["asset_manifest"]) == 60
    assert all(
        asset["digest"]["dandi:sha2-256"]
        for asset in provenance["asset_manifest"]
    )
    assert {
        path.name for path in OPTOTAGGING_HEATMAP_SOURCE_DIR.glob("*.atlas.json")
    } == {session["atlas_file"] for session in payload["sessions"]}
    assert {
        path.name for path in OPTOTAGGING_HEATMAP_SOURCE_DIR.glob("*.atlas.png")
    } == {session["numeric_png_file"] for session in payload["sessions"]}
    assert {path.name for path in OPTOTAGGING_HEATMAP_SOURCE_DIR.glob("*.webp")} == {
        session["image_file"]
        for session in payload["sessions"]
        if "image_file" in session
    }
    interactive_html = (
        REPO_ROOT / "interactive" / "optotagging-heatmaps.html"
    ).read_text(encoding="utf-8")
    assert "globalThis.OPTOTAGGING_ATLASES" in interactive_html
    assert interactive_html.count("data:image/png;base64,") == 3
    assert {
        path.name
        for path in (REPO_ROOT / "interactive" / "media" / "optotagging").iterdir()
    } == {"optotagging-heatmaps.svg"}
    summary = load_optotagging_static_summary()
    assert summary["source"] == OPTOTAGGING_STATIC_LEGACY_SOURCE.relative_to(
        REPO_ROOT
    ).as_posix()
    assert summary["source_sha256"] == hashlib.sha256(
        OPTOTAGGING_STATIC_LEGACY_SOURCE.read_bytes()
    ).hexdigest()
    assert summary["source_session_count"] == 60
    assert summary["overall"]["sampled_session_count"] == 60
    assert summary["overall"]["mean"] == pytest.approx(46.316667)
    assert len(summary["major_parent"]) == 10
    assert len(summary["structures"]) == 48
    assert [record["sampled_session_count"] for record in summary["major_parent"]] == [
        58,
        58,
        60,
        58,
        54,
        28,
        12,
        6,
        4,
        23,
    ]
    assert OPTOTAGGING_STATIC_SUMMARY_PATH.is_file()
    static_svg = OPTOTAGGING_STATIC_SOURCE.read_text(encoding="utf-8")
    assert 'width="1200" height="960"' in static_svg
    assert 'role="img" aria-labelledby="title description"' in static_svg
    assert "Optotagging response and yield summary" in static_svg
    assert "Laser-aligned 5 Hz response" not in static_svg
    assert "Overall yield" not in static_svg
    assert "Major parent area" in static_svg
    assert "Structure acronym" in static_svg
    expected_structures = sorted(
        summary["structures"],
        key=lambda record: (-record["mean"], record["label"]),
    )[:18]
    assert all(f'>{record["label"]}</text>' in static_svg for record in expected_structures)
    assert static_svg.count('height="8"') == 18
    assert 'stroke="#DDE1DF"' not in static_svg
    assert ">Session</text>" not in static_svg
    assert all(f">{label}</text>" in static_svg for label in "ABCD")
    assert FIGURE_SANS_FONT in static_svg
    assert FIGURE_MONO_FONT in static_svg
    assert "DejaVuSans" not in static_svg
    assert "#315F73" in static_svg
    assert "#3B4CC0" in static_svg
    assert "#B40426" in static_svg
    assert not any(color in static_svg for color in ("#82ed83", "#ed828e", "#a4d3ed"))
    regenerated = write_optotagging_static_source(tmp_path / "optotagging-static.svg")
    assert regenerated.read_bytes() == OPTOTAGGING_STATIC_SOURCE.read_bytes()


def test_optotagging_outputs_are_deterministic_and_accessible(tmp_path: Path) -> None:
    media_dir = tmp_path / "source-media"
    media_dir.mkdir()
    static_source = media_dir / "optotagging-static-composite.svg"
    image = b"RIFF\x04\x00\x00\x00WEBP"
    image_file = "ecephys_test.webp"
    image_sha256 = hashlib.sha256(image).hexdigest()
    (media_dir / image_file).write_bytes(image)
    session = {
        "asset_id": "asset-1",
        "asset_path": "sub-1/session.nwb",
        "image_file": image_file,
        "image_height": 1,
        "image_sha256": image_sha256,
        "image_width": 1,
        "session_id": "ecephys_test",
        "unit_count": 12,
        "condition_counts": {},
    }
    payload = {
        "version": 1,
        "default_session_id": "ecephys_test",
        "session_count": 1,
        "total_unit_count": 12,
        "conditions": [],
        "psth": {},
        "sessions": [session],
    }
    data_path = tmp_path / "optotagging-heatmaps.json"
    data_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    image_manifest = [{"image_file": image_file, "image_sha256": image_sha256}]
    asset_manifest = [
        {
            "asset_id": "asset-1",
            "asset_path": "sub-1/session.nwb",
            "digest": {"dandi:sha2-256": "source-checksum"},
        }
    ]
    provenance = {
        "version": 1,
        "asset_manifest": asset_manifest,
        "asset_manifest_sha256": hashlib.sha256(
            json.dumps(asset_manifest, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest(),
        "failed_assets": [],
        "manifest_sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
        "media_manifest_sha256": hashlib.sha256(
            json.dumps(image_manifest, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest(),
        "session_count": 1,
        "skipped_assets": [],
        "total_unit_count": 12,
    }
    provenance_path = tmp_path / "optotagging-heatmaps.provenance.json"
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    static_source.write_text(
        '<svg role="img"><text>Optotagging response and yield summary</text>'
        "<text>Major parent area</text><text>Structure acronym</text></svg>",
        encoding="utf-8",
    )

    html_path = write_optotagging_heatmap_html(
        tmp_path / "interactive" / "optotagging.html",
        data_path,
        provenance_path,
        media_dir,
        static_output=tmp_path / "optotagging.svg",
    )
    svg_path = write_optotagging_heatmap_svg(
        tmp_path / "optotagging.svg",
        data_path,
        provenance_path,
        media_dir,
    )
    html = html_path.read_text(encoding="utf-8")
    svg = svg_path.read_text(encoding="utf-8")

    assert 'label for="session-select"' in html
    assert 'label for="parent-area"' in html
    assert 'label for="color-limit"' in html
    assert '<select id="session-select"></select>' in html
    assert '<select id="parent-area" disabled>' in html
    assert 'id="session-search"' not in html
    assert "<datalist" not in html
    assert 'type="search"' not in html
    assert 'type="range" min="0.5" max="8" step="0.5" value="3"' in html
    assert 'data-view="interactive"' in html
    assert 'data-view="static"' in html
    assert 'id="interactive-view"' in html
    assert 'id="static-view"' in html
    assert "Four-panel optotagging figure" in html
    assert "optotagging.svg" in html
    assert "selectView" in html
    assert 'parentSelect.addEventListener("change", scheduleRedraw)' in html
    assert "normalizeParentArea" not in html
    assert "globalThis.OPTOTAGGING_ATLASES" in html
    assert "<canvas" not in html  # Panels are created without duplicating markup.
    assert "createElement(\"canvas\")" in html
    assert 'aria-live="polite"' in html
    assert '"default_session_id":"ecephys_test"' in html
    assert "__OPTOTAGGING_" not in html
    assert "__EMBED_AUTO_HEIGHT_JS__" not in html
    assert (html_path.parent / "media" / "optotagging" / image_file).read_bytes() == image
    assert (
        html_path.parent / "media" / "optotagging" / "optotagging.svg"
    ).read_bytes() == svg_path.read_bytes()
    assert not list(
        (html_path.parent / "media" / "optotagging").glob("*.atlas.js")
    )
    assert 'role="img"' in svg
    assert "Optotagging response and yield summary" in svg
    assert "Major parent area" in svg
    assert "Structure acronym" in svg

    write_optotagging_heatmap_html(
        html_path,
        data_path,
        provenance_path,
        media_dir,
        static_output=svg_path,
    )
    write_optotagging_heatmap_svg(
        svg_path,
        data_path,
        provenance_path,
        media_dir,
    )
    assert html_path.read_text(encoding="utf-8") == html
    assert svg_path.read_text(encoding="utf-8") == svg

    (media_dir / image_file).write_bytes(image + b"changed")
    with pytest.raises(RuntimeError, match="image is invalid"):
        load_optotagging_heatmap_data(data_path, provenance_path, media_dir)


def test_optotagging_version_2_numeric_atlas_validation(tmp_path: Path) -> None:
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    atlas_file = "ecephys_test.atlas.json"
    png_file = "ecephys_test.atlas.png"
    image_file = "ecephys_test.webp"
    atlas = {
        "version": 2,
        "unit_count": 2,
        "time_bin_count": 2,
        "time_seconds": [-0.5, 1.2],
        "numeric_png_file": png_file,
        "parent_areas": ["TH"],
        "parent_codes": [0, 0],
        "strongest_first_unit_indices": {"raised": [1, 0]},
        "condition_row_offsets": {"raised": 0},
        "quantization": {
            "dtype": "int8",
            "scale": 15.875,
            "range": [-8.0, 8.0],
            "nan_sentinel": -128,
            "png_channels": "single-channel uint8 viewed as signed int8",
        },
    }
    assets = {
        atlas_file: (json.dumps(atlas) + "\n").encode(),
        png_file: (
            b"\x89PNG\r\n\x1a\n"
            + b"\x00" * 8
            + struct.pack(">II", 2, 2)
            + b"\x08\x00"
        ),
        image_file: b"RIFF\x04\x00\x00\x00WEBP",
    }
    for filename, content in assets.items():
        (media_dir / filename).write_bytes(content)
    session = {
        "asset_id": "asset-1",
        "asset_path": "session.nwb",
        "session_id": "ecephys_test",
        "unit_count": 2,
        "condition_counts": {"raised": {"presentations": 1, "pulses": 1}},
        "atlas_file": atlas_file,
        "atlas_sha256": hashlib.sha256(assets[atlas_file]).hexdigest(),
        "numeric_png_file": png_file,
        "numeric_png_sha256": hashlib.sha256(assets[png_file]).hexdigest(),
        "image_file": image_file,
        "image_sha256": hashlib.sha256(assets[image_file]).hexdigest(),
        "image_width": 1,
        "image_height": 1,
    }
    payload = {
        "version": 2,
        "default_session_id": "ecephys_test",
        "session_count": 1,
        "total_unit_count": 2,
        "conditions": [{"table_name": "raised", "display_name": "Raised"}],
        "psth": {},
        "sessions": [session],
    }
    data_path = tmp_path / "snapshot.json"
    data_path.write_text(json.dumps(payload), encoding="utf-8")
    asset_manifest = [
        {
            "asset_id": "asset-1",
            "asset_path": "session.nwb",
            "digest": {"dandi:sha2-256": "source"},
        }
    ]
    media_manifest = [
        {"file": atlas_file, "sha256": session["atlas_sha256"]},
        {"file": png_file, "sha256": session["numeric_png_sha256"]},
        {"file": image_file, "sha256": session["image_sha256"]},
    ]
    provenance = {
        "version": 2,
        "manifest_sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
        "session_count": 1,
        "total_unit_count": 2,
        "asset_manifest": asset_manifest,
        "asset_manifest_sha256": hashlib.sha256(
            json.dumps(asset_manifest, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest(),
        "media_manifest_sha256": hashlib.sha256(
            json.dumps(media_manifest, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest(),
        "skipped_assets": [],
        "failed_assets": [],
    }
    provenance_path = tmp_path / "snapshot.provenance.json"
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")

    assert load_optotagging_heatmap_data(
        data_path,
        provenance_path,
        media_dir,
    ) == payload


def test_neuropixels_trajectory_snapshot_is_source_backed() -> None:
    payload = load_neuropixels_trajectory_data()
    provenance = json.loads(
        NEUROPIXELS_TRAJECTORY_PROVENANCE_PATH.read_text(encoding="utf-8")
    )

    assert hashlib.sha256(NEUROPIXELS_TRAJECTORY_DATA_PATH.read_bytes()).hexdigest() == (
        provenance["vendored_sha256"]
    )
    assert payload["summary"] == {
        "excludedSessions": 3,
        "insertions": 332,
        "localizedSessions": 57,
        "sourceSessions": 60,
        "subjects": 16,
    }
    assert [len(payload["brainSurface"][field]) for field in ("vertices", "faces")] == [
        60_687,
        121_248,
    ]
    assert {record["probe"] for record in payload["insertions"]} == set("ABCDEF")
    assert payload["probeColors"] == {
        "A": "#8CC63F",
        "B": "#C5E9FA",
        "C": "#25AAE1",
        "D": "#283892",
        "E": "#39B54A",
        "F": "#156C49",
    }
    assert all(
        record["areas"][0]["acronym"] != "void"
        and record["areas"][-1]["acronym"] != "void"
        and all(
            current["endDepthUm"] == following["startDepthUm"]
            for current, following in zip(
                record["areas"][:-1],
                record["areas"][1:],
                strict=True,
            )
        )
        for record in payload["insertions"]
    )
    assert {record["mouseId"] for record in payload["insertions"]} == {
        "820454",
        "820459",
        "830794",
        "830795",
        "830846",
        "830847",
        "830848",
        "830849",
        "830851",
        "830852",
        "832691",
        "834686",
        "834687",
        "834691",
        "848387",
        "848390",
    }
    assert {row["reason"] for row in provenance["exclusions"]} == {
        "missing-ccf-coordinates:x,y,z"
    }
    atlas_midline_um = payload["brainSurface"]["annotationShape"][2] * 12.5
    planned_entry_lateral_um = {
        "A": 800,
        "B": 2_000,
        "C": 2_300,
        "D": 4_200,
        "E": 2_600,
        "F": 1_500,
    }
    observed_entry_lateral_um = {
        probe: statistics.median(
            atlas_midline_um - record["points"][0][2]
            for record in payload["insertions"]
            if record["probe"] == probe
        )
        for probe in planned_entry_lateral_um
    }
    source_sign_error_um = statistics.mean(
        abs(observed_entry_lateral_um[probe] - planned_lateral)
        for probe, planned_lateral in planned_entry_lateral_um.items()
    )
    reflected_sign_error_um = statistics.mean(
        abs(-observed_entry_lateral_um[probe] - planned_lateral)
        for probe, planned_lateral in planned_entry_lateral_um.items()
    )
    assert source_sign_error_um < 500
    assert reflected_sign_error_um > 4_000


def test_neuropixels_trajectory_outputs_are_deterministic(tmp_path: Path) -> None:
    html_path = write_neuropixels_trajectory_html(
        tmp_path / "neuropixels-trajectories.html",
        tmp_path / "supplementary-neuropixels-trajectories.svg",
    )
    svg_path = tmp_path / "supplementary-neuropixels-trajectories.svg"
    html = html_path.read_text(encoding="utf-8")
    svg = svg_path.read_text(encoding="utf-8")

    assert 'id="brain-canvas"' in html
    assert 'id="orientation-canvas"' in html
    assert 'id="area-list"' in html
    assert 'id="brain-opacity"' in html
    assert 'data-probe="A"' in html
    assert "three@0.179.1" in html
    assert "OrbitControls" in html
    assert "preserveDrawingBuffer: true" in html
    assert "camera.position.clone().sub(controls.target).normalize()" in html
    assert "orientationRenderer.render(orientationScene, orientationCamera)" in html
    assert "atlasCenter.x - point[2]" in html
    assert "point[2] - atlasCenter.x" not in html
    assert "camera.fov = fittedVerticalFov(camera.aspect)" in html
    assert "dorsal: { position: [0, 17500, 0.01], up: [0, 0, 1] }" in html
    assert '<div class="orientation"' not in html
    assert '"insertions":332' in html
    assert 'role="img"' in svg
    assert ">A</text>" in svg
    assert ">B</text>" in svg
    assert "Oblique CCF surface</text>" not in svg
    assert "Dorsal CCF surface</text>" not in svg
    assert svg.count('fill="#F7F9F8"') == 0
    assert svg.count('class="ccf-brain-render"') == 2
    assert svg.count('data-surface-opacity="0.12"') == 2
    assert svg.count("data:image/png;base64,") == 2
    brain_images = re.findall(
        r'<image class="ccf-brain-render"[^>]+href="data:image/png;base64,([^"]+)"',
        svg,
    )
    assert len(brain_images) == 2
    assert all(
        image.startswith(b"\x89PNG\r\n\x1a\n")
        and image[25] == 6
        and len(image) > 50_000
        for image in map(base64.b64decode, brain_images)
    )
    assert svg.count('class="ccf-scale-bar"') == 2
    assert svg.count(">2 mm</text>") == 2
    assert svg.count('class="ccf-orientation-axis"') == 5
    assert svg.count('class="probe-legend-title"') == 1
    assert ">Probe:</text>" in svg
    assert svg.count('class="probe-legend-label"') == 6
    assert "100 µm surface mesh" not in svg
    assert "probe-port colors" not in svg
    assert "localized insertions ·" not in svg
    assert ".viewer.static-active .source-strip" in html
    assert svg.count("<polyline ") == 664
    payload = load_neuropixels_trajectory_data()
    insertion_count = len(payload["insertions"])
    trajectory_polylines = re.findall(r'<polyline points="([^"]+)"', svg)
    dorsal_polylines = trajectory_polylines[insertion_count:]
    assert len(dorsal_polylines) == insertion_count
    shape = payload["brainSurface"]["annotationShape"]
    center = tuple(dimension * 12.5 for dimension in shape)
    static_screen_x = []
    static_screen_y = []
    interactive_screen_x = []
    interactive_screen_y = []
    for record, polyline in zip(
        payload["insertions"], dorsal_polylines, strict=True
    ):
        screen_x, screen_y = map(
            float, polyline.split(maxsplit=1)[0].split(",", maxsplit=1)
        )
        anterior_posterior, dorsal_ventral, medial_lateral = record["points"][0]
        world_x = center[2] - medial_lateral
        world_y = center[1] - dorsal_ventral
        world_z = center[0] - anterior_posterior
        camera_depth = 17_500 - world_y
        static_screen_x.append(screen_x)
        static_screen_y.append(screen_y)
        interactive_screen_x.append(-world_x / camera_depth)
        interactive_screen_y.append(-world_z / camera_depth)
    assert statistics.correlation(static_screen_x, interactive_screen_x) > 0.99
    assert statistics.correlation(static_screen_y, interactive_screen_y) > 0.99
    assert "__NEUROPIXELS_TRAJECTORY_" not in html
    assert "__EMBED_AUTO_HEIGHT_JS__" not in html
    copied_static = (
        tmp_path
        / "media"
        / "neuropixels-trajectories"
        / "supplementary-neuropixels-trajectories.svg"
    )
    assert copied_static.read_bytes() == svg_path.read_bytes()

    write_neuropixels_trajectory_html(html_path, svg_path)
    write_neuropixels_trajectory_svg(svg_path)
    assert html_path.read_text(encoding="utf-8") == html
    assert svg_path.read_text(encoding="utf-8") == svg


def test_segmentation_viewer_snapshot_is_source_backed() -> None:
    payload = load_segmentation_viewers()
    provenance = json.loads(
        SEGMENTATION_VIEWER_PROVENANCE_PATH.read_text(encoding="utf-8")
    )

    assert hashlib.sha256(SEGMENTATION_VIEWER_DATA_PATH.read_bytes()).hexdigest() == (
        provenance["vendored_sha256"]
    )
    assert payload["version"] == 4
    viewers = {viewer["id"]: viewer for viewer in payload["viewers"]}
    expected_counts = {
        "neuropixels": [569, 502, 534, 799, 542, 604],
        "mesoscope": [399, 463, 70, 277, 374, 356, 124, 321],
        "slap2": [45, 74],
    }
    assert {
        modality: [source["filterCount"] for source in viewer["sources"]]
        for modality, viewer in viewers.items()
    } == expected_counts
    assert {
        modality: viewer["asset"]["dandiset_id"]
        for modality, viewer in viewers.items()
    } == {
        "neuropixels": "001637",
        "mesoscope": "001768",
        "slap2": "001424",
    }
    assert viewers["slap2"]["asset"]["asset_id"] == (
        "1b6509ef-70d7-46e4-9c8e-587bb6ace95f"
    )
    assert [source["sourceId"] for source in viewers["neuropixels"]["sources"]] == [
        "probe-a", "probe-b", "probe-c", "probe-d", "probe-e", "probe-f"
    ]
    assert [source["sourceId"] for source in viewers["mesoscope"]["sources"]] == [
        "visp_0", "visp_1", "visp_2", "visp_3",
        "visl_4", "visl_5", "visl_6", "visl_7",
    ]
    assert [source["sourceId"] for source in viewers["slap2"]["sources"]] == [
        "dmd1", "dmd2"
    ]
    for source in viewers["neuropixels"]["sources"]:
        assert source["waveformColumns"] == 210
        assert source["viewType"] == "spike-map"
        assert (source["rawRows"], source["rawColumns"]) == (96, 3000)
        assert len(base64.b64decode(source["rawDataBase64"])) == 288_000
        assert source["spikeEvents"]
        assert source["traceColumns"] == 600
        assert source["traceTimesSeconds"][-1] == pytest.approx(11.99)
        assert all(
            "isQcPassing" not in row
            and "snr" not in row
            and "firingRateHz" not in row
            for row in source["filters"]
        )
    for source in (*viewers["mesoscope"]["sources"], *viewers["slap2"]["sources"]):
        assert source["traceTimesSeconds"][-1] > 29.8
        assert "activityImage" not in source
        assert source["traceLabel"] == "ΔF/F (%)"
        assert source["traceScale"] == 100
        assert source["traceUnit"] == "%"
    assert {
        source["fastScanAxis"] for source in viewers["mesoscope"]["sources"]
    } == {"horizontal"}
    assert {
        source["fastScanAxis"] for source in viewers["slap2"]["sources"]
    } == {"vertical"}
    assert {
        source["displayTransform"] for source in viewers["mesoscope"]["sources"]
    } == {"stored-yx"}
    assert {
        source["displayTransform"] for source in viewers["slap2"]["sources"]
    } == {"transpose-for-publication"}
    assert (
        viewers["slap2"]["sources"][0]["baseImage"]["width"],
        viewers["slap2"]["sources"][0]["baseImage"]["height"],
    ) == (408, 427)
    assert (
        viewers["slap2"]["sources"][1]["baseImage"]["width"],
        viewers["slap2"]["sources"][1]["baseImage"]["height"],
    ) == (587, 429)
    referenced_media = {
        Path(source[field]["assetPath"]).name
        for viewer in viewers.values()
        for source in viewer["sources"]
        for field in ("baseImage", "labelImage", "filterOverlay")
        if field in source
    }
    assert set(provenance["vendored_media_sha256"]) == referenced_media
    assert len(referenced_media) == 30
    assert not any("activity" in name for name in referenced_media)


def test_common_median_correction_removes_time_column_offsets() -> None:
    corrected = common_median_corrected_rgb(
        bytes((10, 20, 30, 110, 120, 130)),
        rows=2,
        columns=3,
        contrast=1,
    )

    assert corrected == bytes((78, 78, 78) * 3 + (178, 178, 178) * 3)


def test_segmentation_viewer_outputs_are_deterministic(tmp_path: Path) -> None:
    html_path = write_segmentation_viewer_html(tmp_path / "segmentation-viewer.html")
    html = html_path.read_text(encoding="utf-8")
    assert 'id="modality-selector"' in html
    assert 'role="tablist"' in html
    assert 'id="source-select"' in html
    assert 'id="source-label"' in html
    assert 'id="source-canvas"' in html
    assert 'id="filter-select"' in html
    assert 'id="activity-chart"' in html
    assert 'id="background-intensity"' in html
    assert 'id="common-mode-toggle"' in html
    assert 'id="common-mode-control"' in html
    assert 'class="view-button active" data-view="interactive"' in html
    assert 'data-view="static"' in html
    assert 'id="interactive-view"' in html
    assert 'id="static-view"' in html
    assert "twenty vertically stacked activity traces per modality" in html
    assert 'id="panel-label"' not in html
    assert 'id="session-line"' not in html
    assert 'id="viewer-title"' in html
    assert 'const colors = ["#25aae1", "#8cc63f", "#ccaf2d"' in html
    assert 'context.filter = "grayscale(1)"' not in html
    assert "filterColor(event.filterIndex)" in html
    assert 'id="overlay-opacity"' not in html
    for source_id in (
        "probe-a", "probe-b", "probe-c", "probe-d", "probe-e", "probe-f",
        "visp_0", "visp_1", "visp_2", "visp_3",
        "visl_4", "visl_5", "visl_6", "visl_7", "dmd1", "dmd2",
    ):
        assert f'"sourceId":"{source_id}"' in html
    assert "protocol.viewers.map" in html
    assert "activateModality" in html
    assert "activateSource" in html
    assert "populateSourceSelect" in html
    assert 'class="modality-logo"' in html
    assert html.count("data:image/png;base64,") == 3
    assert "tab-count" not in html
    assert 'id="filter-count"' not in html
    assert 'id="qc-toggle"' not in html
    assert 'id="qc-key"' not in html
    assert 'id="activity-toggle"' not in html
    assert 'id="activity-key"' not in html
    assert "isQcPassing" not in html
    assert "activityImage" not in html
    assert "firingRateHz" not in html
    assert '"snr"' not in html
    assert "Firing rate" not in html
    assert '["SNR"' not in html
    assert 'document.querySelector("body > main")' in html
    assert "[hidden] { display: none !important; }" in html
    assert "filterAt(event)" in html
    assert "chart-event" not in html
    assert "Sequence omission" not in html
    assert "Motor orientation 90" not in html
    assert "Common-mode-corrected AP voltage" in html
    assert "Raw AP voltage" in html
    assert "Detected sorted spikes" not in html
    assert "Extraction filters" not in html
    assert "Fast scan" not in html
    assert 'id="trace-window"' not in html
    assert "0.0–30.0 s" not in html
    assert "Peak channel</span>" not in html
    assert '["Peak channel", String(filter.peakChannel)]' in html
    assert '["Source", String(filter.id + 1)]' in html
    assert r"\u0394F/F (%)" in html
    assert '"traceScale":100' in html
    assert "value * scale" in html
    assert 'options.yUnit === "%"' in html
    assert "const margin = { left: 96, right: 40" in html
    assert "Source Delta F/F" not in html
    assert 'context.fillStyle = "#ffffff"' in html
    assert "context.filter = \"grayscale(1)\"" not in html
    assert "const colors = [" in html
    assert 'class="chart-tick"' in html
    assert "Raw AP contrast" in html
    assert "Background intensity" in html
    assert "state.overlayOpacity" not in html
    assert "dandiset/001637/draft/files" in html
    assert "dandiset/001768/draft/files" in html
    assert "dandiset/001424/draft/files" in html
    assert "__SEGMENTATION_" not in html
    assert "__EMBED_AUTO_HEIGHT_JS__" not in html

    static_paths = {
        modality: tmp_path / SEGMENTATION_VIEWER_STATIC_OUTPUTS[modality].name
        for modality in SEGMENTATION_VIEWER_STATIC_OUTPUTS
    }
    first_static_renders = {}
    for modality, panel_labels, removed_heading in (
        ("neuropixels", ("A", "B"), "Neuropixels unit-template viewer"),
        ("mesoscope", ("C", "D"), "Mesoscope ROI segmentation viewer"),
        ("slap2", ("E", "F"), "SLAP2 source-segmentation viewer"),
    ):
        svg_path = write_segmentation_viewer_svg(modality, static_paths[modality])
        svg = svg_path.read_text(encoding="utf-8")
        first_static_renders[modality] = svg
        assert 'role="img"' in svg
        assert 'filter id="neutral-overlay"' not in svg
        assert "Mouse " not in svg
        for panel_label in panel_labels:
            assert f">{panel_label}</text>" in svg
        assert "Selected filter" not in svg
        assert " filters</text>" not in svg
        assert "Activity traces ·" not in svg
        assert svg.count('class="static-modality-logo"') == 1
        assert removed_heading not in svg.split("</title>", maxsplit=1)[1]
        assert '<rect x="748" y="100"' not in svg
        assert svg.count('class="static-activity-trace"') == 20
        assert svg.count('class="trace-scale-bar"') == 2
        assert 'class="trace-scale-tick"' not in svg
        assert svg.count('stroke="#000000" stroke-width="4"') == 2
        assert 'stroke="#E2E6E4"' not in svg
        assert "Fast scan" not in svg
        if modality == "neuropixels":
            assert "Probe length from tip (µm)" in svg
            assert 'transform="rotate(-90' not in svg
            assert svg.count('data-vertical-gain="1"') == 20
            assert "310 detected spikes" not in svg
            assert "common-mode-corrected AP voltage" not in svg
            assert "Sequence omission" not in svg
            assert 'fill="#25AAE1"' in svg
            assert "Binned spike rate" not in svg
        else:
            expected_gain = "3" if modality == "mesoscope" else "2"
            assert svg.count(f'data-vertical-gain="{expected_gain}"') == 20
            assert svg.count("<clipPath") == 20
            assert svg.count("data:image/png;base64,") >= 3
            assert 'filter="url(#neutral-overlay)"' not in svg
            assert svg.count('class="represented-filter-fills"') == 1
            assert 'class="represented-filter"' not in svg
            assert "<circle" not in svg
            assert "ΔF/F (%)" not in svg
            assert "%</text>" in svg

    combined_path = write_segmentation_viewer_static_svg(
        tmp_path / "figure-06-segmentation-viewers.svg",
        static_paths,
    )
    combined_svg = combined_path.read_text(encoding="utf-8")
    assert 'width="1400" height="2280"' in combined_svg
    assert 'role="img"' in combined_svg
    assert combined_svg.count("data:image/svg+xml;base64,") == 3

    copied_media = tmp_path / "media" / "segmentation-viewers"
    assert {path.name for path in copied_media.glob("*.png")} == set(
        json.loads(
            SEGMENTATION_VIEWER_PROVENANCE_PATH.read_text(encoding="utf-8")
        )["vendored_media_sha256"]
    )
    assert (copied_media / SEGMENTATION_VIEWER_STATIC_OUTPUT.name).read_bytes() == (
        SEGMENTATION_VIEWER_STATIC_OUTPUT.read_bytes()
    )
    assert write_segmentation_viewer_html(html_path).read_text(encoding="utf-8") == html
    assert write_segmentation_viewer_static_svg(
        combined_path,
        static_paths,
    ).read_text(encoding="utf-8") == combined_svg
    for modality, svg in first_static_renders.items():
        assert write_segmentation_viewer_svg(
            modality,
            static_paths[modality],
        ).read_text(encoding="utf-8") == svg


def test_segmentation_viewer_orchestrator_writes_all_modalities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / SEGMENTATION_VIEWER_OUTPUT.name
    combined_static_path = tmp_path / SEGMENTATION_VIEWER_STATIC_OUTPUT.name
    static_paths = {
        modality: tmp_path / f"segmentation-{modality}.svg"
        for modality in ("neuropixels", "mesoscope", "slap2")
    }
    monkeypatch.setattr(
        "openscope_p3_publication.figures.SEGMENTATION_VIEWER_OUTPUT",
        output_path,
    )
    monkeypatch.setattr(
        "openscope_p3_publication.figures.SEGMENTATION_VIEWER_STATIC_OUTPUT",
        combined_static_path,
    )
    monkeypatch.setattr(
        "openscope_p3_publication.figures.SEGMENTATION_VIEWER_STATIC_OUTPUTS",
        static_paths,
    )

    assert write_segmentation_viewers() == output_path
    assert output_path.is_file()
    assert combined_static_path.is_file()
    assert all(path.is_file() for path in static_paths.values())


def test_stimulus_sources_are_pinned() -> None:
    sources = json.loads(STIMULUS_SOURCES_PATH.read_text(encoding="utf-8"))

    assert sources["upstream_revision"] == "0365ae32f0f0473320ed202b7c5d2bce6cf5df6b"
    assert sources["zebra_movie_sha256"] == (
        "3ee4d88356dba7220eb67e53f7d117400932f3adf95132d6301fe212ff7cf899"
    )
    assert len(sources["sessions"]) == 4
    for source in sources["sessions"]:
        assert source["example_table_url"].endswith("_example.csv")
        assert len(source["sha256"]) == 64


def test_stimulus_excerpts_preserve_pinned_source_order() -> None:
    sources = json.loads(STIMULUS_SOURCES_PATH.read_text(encoding="utf-8"))
    provenance = json.loads(
        STIMULUS_EXCERPT_PROVENANCE_PATH.read_text(encoding="utf-8")
    )
    contexts = load_stimulus_table_excerpts(sources)
    shared = load_shared_stimulus_table_excerpts(sources)

    assert provenance["upstream_revision"] == sources["upstream_revision"]
    assert set(contexts) == {"1", "2", "3", "4"}
    assert set(shared) == {"0", "2", "3", "4", "5", "7"}
    assert contexts["1"]["firstMismatchTrial"] == 572
    assert contexts["2"]["firstMismatchTrial"] == 1070
    assert contexts["1"]["rows"][0]["trialNumber"] == 560
    assert contexts["1"]["rows"][0]["sourceRow"] == 561
    assert contexts["1"]["rows"][12]["trialNumber"] == 572
    assert [row["orientation"] for row in shared["0"]["rows"][:4]] == [
        45.0,
        45.0,
        247.5,
        90.0,
    ]
    assert shared["7"]["rows"][0]["diameterX"] == 20.0
    assert shared["0"]["rows"][0]["sourceRow"] == 2
    c4_phases = [row["phaseCycles"] for row in shared["5"]["rows"]]
    assert all(phase is not None for phase in c4_phases)
    assert max(
        abs(current - previous)
        for previous, current in zip(c4_phases[:-1], c4_phases[1:], strict=True)
    ) < 0.17


def test_figure_outputs_are_accessible_and_interactive(tmp_path: Path) -> None:
    html_path = write_interactive_html(tmp_path / "experimental-design.html")
    svg_path = write_static_svg(tmp_path / "experimental-design.svg")

    html = html_path.read_text(encoding="utf-8")
    svg = svg_path.read_text(encoding="utf-8")

    assert 'id="stimulus-viewer"' in html
    assert 'data-view="playback"' in html
    assert 'data-view="static"' in html
    assert ">Interactive</button>" in html
    assert ">Static</button>" in html
    assert 'class="view-button active" data-view="playback" aria-pressed="true"' in html
    assert '<div id="playback-view">' in html
    assert 'selectView("playback")' in html
    assert 'id="static-panel"' in html
    assert "data:image/svg+xml;base64," in html
    assert "detailed context, control, receptive-field, and zebra-movie blocks" in html
    assert "selectView" in html
    assert 'id="stimulus-canvas"' in html
    assert 'id="session-selector"' in html
    assert 'id="play-toggle"' in html
    assert 'id="block-track"' in html
    assert html.index('id="session-selector"') < html.index('id="block-track"')
    assert html.index('id="block-track"') < html.index('id="stimulus-canvas"')
    assert 'id="context-selector"' in html
    assert "--context-start" in html
    assert 'contextButton.textContent = "Context"' in html
    assert 'elements.sessionTitle.textContent = "Context block"' in html
    assert "contextButton.textContent = sessionLabels[index]" not in html
    assert "grid-template-columns: minmax(0, 1fr);" in html
    assert 'id="stimulus-video"' in html
    assert 'class="source-links"' not in html
    assert "updateSourceLinks" not in html
    assert "0365ae32f0f0473320ed202b7c5d2bce6cf5df6b" in html
    assert "setInterval" in html
    assert "Standard oddball" in html
    assert "Duration mismatch" in html
    assert (
        'const sessionLabels = ["Standard oddball", "Sensorimotor", "Sequence", "Duration"]'
        in html
    )
    assert "background: var(--tab-color);" in html
    assert "max-width: 760px;" in html
    assert "width: min(100%, 380px);" in html
    assert "--tab-text-color" in html
    assert "white-space: nowrap;" in html
    for context_color in ("#283185", "#22BCAD", "#B16027", "#CCAF2D"):
        assert context_color in html
    assert 'width="480" height="380"' in html
    assert "stimulusTableExcerpts" in html
    assert "sharedTableExcerpts" in html
    assert '"trialNumber":572' in html
    assert "angularDistanceDegrees" in html
    assert "normalizedX * 120 / 2" in html
    assert "normalizedY * 95 / 2" in html
    assert "zebra-stimulus-excerpt.m4v" in html
    assert "zebra-stimulus-poster.png" in html
    assert "#stimulus-video[hidden]" in html
    assert "display: none !important" in html
    assert "Open-loop playback" in html
    assert "nextRow.phaseCycles" in html
    assert ".block-tab.context {" in html
    assert "background: var(--accent);" in html
    assert 'id="sync-square"' not in html
    assert "drawZebraFallback" not in html
    for removed_function in (
        "oddballSpec",
        "sensorimotorSpec",
        "sequenceSpec",
        "durationSpec",
        "standardControlSpec",
        "receptiveFieldSpec",
    ):
        assert removed_function not in html
    assert 'id="mock-mouse"' not in html
    assert 'id="event-log"' not in html
    assert 'id="trigger-mismatch"' not in html
    assert 'document.querySelector("body > main")' in html
    assert 'classList.add("is-embedded")' in html
    assert "__EMBED_AUTO_HEIGHT_JS__" not in html
    assert "__SIMULATOR_" not in html
    assert 'role="img"' in svg
    assert "Session 4" in svg
    assert "Source Sans 3" not in html
    assert 'font-family: "Myriad Pro", Arial, sans-serif;' in html
    assert "IBM Plex Sans" not in svg
    assert "Source Sans 3" not in svg
    assert 'font-family="Myriad Pro, Arial, sans-serif"' in svg

    assert hashlib.sha256(
        (tmp_path / ZEBRA_MOVIE_SOURCE.name).read_bytes()
    ).hexdigest() == hashlib.sha256(ZEBRA_MOVIE_SOURCE.read_bytes()).hexdigest()
    assert hashlib.sha256(
        (tmp_path / ZEBRA_POSTER_SOURCE.name).read_bytes()
    ).hexdigest() == hashlib.sha256(ZEBRA_POSTER_SOURCE.read_bytes()).hexdigest()

    first_render = html
    write_interactive_html(html_path)
    assert html_path.read_text(encoding="utf-8") == first_render


def test_opening_figures_are_source_backed(tmp_path: Path) -> None:
    assets = load_experimental_design_sources()
    assert set(assets) == {
        "figure_2_detailed_blocks",
        "figure_2_stimulus_timeline",
    }

    figure_1 = write_merged_figure_1_svg(tmp_path / "figure-01-overview.svg").read_text(
        encoding="utf-8"
    )
    assert 'width="2000" height="1620"' in figure_1
    assert figure_1.count("data:image/png;base64,") == 2
    assert figure_1.count("data:image/svg+xml;base64,") == 1
    assert 'viewBox="0 60 580 460"' in figure_1
    assert figure_1.count('class="panel-label"') == 3
    assert figure_1.count('class="workflow-label-mask"') == 1
    assert figure_1.count('class="workflow-modality-label"') == 1
    assert 'class="workflow-modality-label" x="526" y="203"' in figure_1
    assert '>Mesoscope</text>' in figure_1
    assert "Predictive-processing framework and experimental workflow" in figure_1

    panel_c = write_figure_1_panel_c_svg(
        tmp_path / "figure-01-panel-c-cohorts.svg"
    ).read_text(encoding="utf-8")
    assert 'width="1600" height="640"' in panel_c
    assert panel_c.count('class="modality-cohort" data-modality=') == 3
    assert panel_c.count('class="modality-title"') == 3
    assert_modality_title_scale(panel_c)
    assert panel_c.count('class="platform-logo"') == 3
    assert panel_c.count('class="cohort-line"') == 5
    assert panel_c.count('class="habituation-session"') == 40
    assert panel_c.count('class="cohort-session"') == 28
    session_dimensions = re.findall(
        r'class="(?:habituation|cohort)-session"[^>]+width="([^"]+)" '
        r'height="([^"]+)"',
        panel_c,
    )
    assert session_dimensions == [("38", "38")] * 68
    assert len(re.findall(r'class="cohort-session" data-cohort="1"', panel_c)) == 16
    assert len(re.findall(r'class="cohort-session" data-cohort="2"', panel_c)) == 12
    for context in ("sensorimotor", "standard oddball", "sequence", "duration"):
        assert panel_c.count(f'data-context="{context}"') == 7
    assert "Habituation / training" in panel_c
    assert "Habituation without mismatch" in panel_c
    assert panel_c.count('font-size="26.67"') == 3
    assert panel_c.count('font-size="32"') == 2
    assert panel_c.count('font-size="20"') == 13
    assert panel_c.count('width="110" height="110"') == 3
    assert "#F6F8F7" not in panel_c

    figure_3 = write_context_controls_svg(
        tmp_path / "figure-02-context-controls.svg"
    ).read_text(encoding="utf-8")
    assert 'width="1600" height="1600"' in figure_3
    assert figure_3.count("data:image/png;base64,") == 2
    assert figure_3.count('class="panel-label"') == 2
    assert "Shared session architecture" in figure_3
    assert "Context, control, and system-identification blocks" in figure_3


def test_hardware_figure_is_powerpoint_source_backed(tmp_path: Path) -> None:
    assets = load_hardware_sources()
    assert len(assets) == 9
    assert {
        asset_id.rsplit("_", maxsplit=2)[0]
        for asset_id in assets
    } == {"neuropixels", "mesoscope", "slap2"}
    assert {asset["mode"] for asset in assets.values()} == {"RGBA"}
    assert sum(asset["width"] == 2048 for asset in assets.values()) == 7
    assert assets["slap2_brain_targeting"]["width"] == 448
    assert assets["neuropixels_brain_targeting"]["width"] == 1172
    assert all(len(asset["slide_box_inches"]) == 4 for asset in assets.values())

    svg = write_hardware_figure_svg(tmp_path / "multimodal-hardware.svg").read_text(
        encoding="utf-8"
    )
    assert 'width="1800" height="1310"' in svg
    assert svg.count('class="hardware-image"') == 9
    assert svg.count('class="hardware-modality" data-modality=') == 3
    assert svg.count('class="modality-title"') == 3
    assert_modality_title_scale(svg)
    assert svg.count('class="platform-logo"') == 3
    assert svg.count('width="190" height="190"') == 3
    assert svg.count("data:image/png;base64,") == 12
    assert svg.count('viewBox="') == 4
    assert "Rig geometry" in svg
    assert "Mouse platform" in svg
    assert "Brain targeting" in svg
    assert 'class="hardware-caption"' not in svg
    assert "6 probes spanning cortical" not in svg
    assert "8 imaging planes across" not in svg
    assert "Dual-plane dendritic imaging" not in svg
    assert "pan-neuronal calcium imaging" not in svg
    assert "Behavior cohorts" not in svg
    assert "motor cohort" not in svg.lower()
    assert svg.count('class="zoom-focus-box"') == 2
    assert 'data-modality="mesoscope"' in svg
    focus_angle = float(
        re.search(
            r'data-modality="mesoscope"[^>]+transform="rotate\(([-0-9.]+)',
            svg,
        ).group(1)
    )
    layer_segment = re.search(
        r'class="mesoscope-layer-plane"[^>]+x1="([^"]+)" y1="([^"]+)" '
        r'x2="([^"]+)" y2="([^"]+)"',
        svg,
    )
    layer_x1, layer_y1, layer_x2, layer_y2 = map(float, layer_segment.groups())
    layer_angle = math.degrees(
        math.atan2(layer_y1 - layer_y2, layer_x1 - layer_x2)
    )
    assert focus_angle == pytest.approx(layer_angle, abs=0.02)
    assert svg.count('class="mesoscope-target-border"') == 1
    assert svg.count('class="zoom-connector"') == 6
    assert svg.count('data-stage="neuropixels-to-mesoscope"') == 2
    assert svg.count('data-stage="mesoscope-internal"') == 2
    assert svg.count('data-stage="mesoscope-to-slap2"') == 2
    assert svg.count('stroke-dasharray="2 10"') == 6
    assert svg.count('class="mesoscope-layer-plane"') == 8
    assert svg.count('data-layer="I"') == 2
    assert svg.count('data-layer="II/III"') == 2
    assert svg.count('data-layer="IV"') == 2
    assert svg.count('data-layer="V"') == 2
    assert svg.count('class="slap2-plane-label"') == 2
    hardware_description_sizes = re.findall(
        r'class="slap2-plane-label"[^>]+font-size="([^"]+)"',
        svg,
    )
    assert hardware_description_sizes == ["18"] * 2
    plane_label_positions = re.findall(
        r'class="slap2-plane-label" x="([^"]+)" y="([^"]+)"', svg
    )
    assert len(plane_label_positions) == 2
    assert len({position[0] for position in plane_label_positions}) == 1
    assert 'class="slap2-plane-label" x="1680" y="1009" text-anchor=' not in svg
    for label in (
        "Layer I",
        "Layer II/III",
        "Layer IV",
        "Layer V",
        "VISlm",
        "VISp",
        "Apical plane",
        "Proximal plane",
    ):
        assert label in svg
    assert '<text x="1318" y="746"' in svg
    assert '<text x="1460" y="716"' in svg
    assert 'class="mesoscope-target-legend"' in svg
    assert svg.count('paint-order="stroke"') == 4
    for asset_id in assets:
        assert f'data-asset="{asset_id}"' in svg


def test_placeholder_plans_mask_obsolete_figure_numbers(tmp_path: Path) -> None:
    cases = (
        (
            write_unit_extraction_plan_svg,
            "figure-07-unit-extraction-plan.svg",
            "Unit extraction → signal and noise amplitude",
            "Figure 4",
            2,
        ),
        (
            write_basic_stimuli_plan_svg,
            "figure-08-basic-stimuli-plan.svg",
            "Basic stimuli → unit/system identification",
            "Figure 5",
            1,
        ),
        (
            write_standard_oddball_plan_svg,
            "figure-10-standard-oddball-plan.svg",
            "Responses to standard oddball stimuli",
            "Figure 7",
            2,
        ),
    )
    for writer, filename, expected_title, obsolete_title, title_lines in cases:
        svg = writer(tmp_path / filename).read_text(encoding="utf-8")
        assert 'width="2048" height="1024"' in svg
        assert svg.count("data:image/png;base64,") == 1
        assert svg.count('class="stale-title-mask"') == 1
        assert svg.count('class="placeholder-title"') == title_lines
        assert expected_title in svg
        assert obsolete_title not in svg


def test_data_explorer_is_deterministic(tmp_path: Path) -> None:
    static_path = tmp_path / "session-inventory.svg"
    explorer_path = write_data_explorer_html(
        tmp_path / "data-explorer.html",
        static_output=static_path,
    )
    html = explorer_path.read_text(encoding="utf-8")

    assert 'id="data-explorer"' in html
    assert "Download visible rows as CSV" in html
    assert "Two-photon mesoscope" in html
    assert "832700_2026-01-30" in html
    assert "841193" in html
    assert 'data-view="interactive"' in html
    assert 'data-view="static"' in html
    assert 'id="static-view"' in html
    assert 'class="view-button active" data-view="interactive" aria-pressed="true"' in html
    assert '<div id="interactive-view">' in html
    assert 'selectView("interactive")' in html
    assert "data:image/svg+xml;base64," in html
    assert "selectView" in html
    assert 'document.querySelector("body > main")' in html
    assert 'classList.add("is-embedded")' in html
    assert "__EMBED_AUTO_HEIGHT_JS__" not in html

    write_data_explorer_html(explorer_path, static_output=static_path)
    assert explorer_path.read_text(encoding="utf-8") == html


def test_data_access_table_uses_modality_specific_columns(tmp_path: Path) -> None:
    headers = (
        "Session ID,Mouse ID,Date,Modality,Context,Dandiset ID,DANDI path,"
        "DANDI link,Source session S3 asset,Spike-sorted S3 asset,CCF S3 asset,"
        "Behavior S3 asset,Behavior videos S3 asset,Motion-corrected S3 asset,"
        "Annotated S3 asset,Processed S3 asset,NWB S3 asset\n"
    )
    rows = (
        "ecephys_1_2026-01-01_00-00-00,1,2026-01-01,Neuropixels,Sequence,"
        "001637,path-a,https://dandi/a,https://s3/source,https://s3/sorted,"
        "INTERNAL,,,,,,https://s3/nwb\n"
        "multiplane-ophys_2_2026-01-02_00-00-00,2,2026-01-02,Mesoscope,Duration,"
        "001768,path-b,https://dandi/b,https://s3/source,,,https://s3/behavior,"
        "https://s3/videos,,,https://s3/processed,https://s3/nwb\n"
        "SLAP2_3_2026-01-03_00-00-00,3,2026-01-03,SLAP2,Sensorimotor,001424,"
        "path-c,https://dandi/c,https://s3/source,,,,,https://s3/motion,"
        "https://s3/annotated,https://s3/processed,https://s3/nwb\n"
    )
    source = tmp_path / "data-access.csv"
    source.write_text(headers + rows, encoding="utf-8")
    provenance = tmp_path / "data-access.provenance.json"
    provenance.write_text(
        json.dumps(
            {
                "rows": 3,
                "source_url": "https://example.org/data-access.csv",
                "vendored_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    table = load_data_access_table(source, provenance)

    assert len(table["rows"]) == 3
    assert {row["modality"] for row in table["rows"]} == {
        "neuropixels", "mesoscope", "slap2"
    }
    assert "CCF S3 asset" in table["columnViews"]["neuropixels"]
    assert "Annotated S3 asset" not in table["columnViews"]["mesoscope"]
    assert table["columnViews"]["slap2"][-5:] == [
        "Source session S3 asset",
        "Motion-corrected S3 asset",
        "Annotated S3 asset",
        "Processed S3 asset",
        "NWB S3 asset",
    ]


def test_data_access_snapshot_is_source_backed() -> None:
    provenance = json.loads(DATA_ACCESS_PROVENANCE_PATH.read_text(encoding="utf-8"))
    assert hashlib.sha256(DATA_ACCESS_PATH.read_bytes()).hexdigest() == (
        provenance["vendored_sha256"]
    )
    with DATA_ACCESS_PATH.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == provenance["rows"]
    assert all(len(row["Dandiset ID"]) == 6 for row in rows)


def test_data_access_explorer_source_has_required_controls() -> None:
    javascript = (
        Path(__file__).parents[1] / "figure_sources" / "javascript" / "data-explorer.js"
    ).read_text(encoding="utf-8")

    assert '["animals", "sessions", "dataAccess"]' in javascript
    assert 'dataAccess: "Data Access"' in javascript
    assert 'table.columnViews[elements.modality.value]' in javascript
    assert 'state.kind === "sessions" || state.kind === "dataAccess"' in javascript
    assert 'appendLinks(cell, value, header)' in javascript


def test_experimental_session_snapshot_and_static_figure(tmp_path: Path) -> None:
    provenance = json.loads(
        SESSION_RECORDS_PROVENANCE_PATH.read_text(encoding="utf-8")
    )
    assert hashlib.sha256(SESSION_RECORDS_PATH.read_bytes()).hexdigest() == (
        provenance["vendored_sha256"]
    )
    assert provenance["worksheet_rows"] == 198
    assert provenance["rows"] == 198
    assert provenance["source_rows"] == 198
    assert provenance["modality_rows"] == {
        "mesoscope": 91,
        "neuropixels": 64,
        "slap2": 43,
    }

    payload = load_experimental_session_records()
    records = payload["records"]
    assert len(records) == 198
    assert [int(record["source_row"]) for record in records] == list(range(3, 201))
    assert {
        modality: len(modality_session_records(records, modality))
        for modality in ("neuropixels", "mesoscope", "slap2")
    } == {"neuropixels": 64, "mesoscope": 91, "slap2": 29}

    mesoscope_rows = session_panel_rows(records, "mesoscope")
    assert [row["mouseId"] for row in mesoscope_rows] == [
        "832700",
        "839909",
        "843001",
        "845342",
        "846289",
        "837568",
        "842971",
        "843000",
        "850399",
        "853137",
    ]
    assert [len(row["sessions"]) for row in mesoscope_rows] == [
        8,
        8,
        12,
        8,
        8,
        11,
        8,
        8,
        8,
        12,
    ]
    slap2_rows = session_panel_rows(records, "slap2")
    assert [row["mouseId"] for row in slap2_rows] == [
        "851453",
        "845207",
        "841191",
        "829704",
        "828409",
        "828408",
    ]
    assert [len(row["sessions"]) for row in slap2_rows] == [3, 5, 4, 4, 4, 6]

    svg_path = write_session_inventory_svg(tmp_path / "session-inventory.svg")
    svg = svg_path.read_text(encoding="utf-8")
    assert 'width="1150" height="680"' in svg
    assert svg.count('class="platform-heading" data-modality=') == 3
    assert_modality_title_scale(svg)
    assert svg.count('class="platform-logo"') == 3
    assert svg.count('y="1" width="54" height="54"') == 3
    assert svg.count('class="panel-title"') == 3
    assert svg.count('y="34"') == 3
    assert svg.count("data:image/png;base64,") == 3
    assert '>A</text>' in svg and '>Neuropixels</text>' in svg
    assert '>B</text>' in svg and '>Mesoscope</text>' in svg
    assert '>C</text>' in svg and '>SLAP2</text>' in svg
    assert "SLAP2 P3" not in svg
    assert svg.count('id="mouse-id-axis-label"') == 1
    assert ">Mouse ID</text>" in svg
    assert 'id="session-inventory-legend"' in svg
    assert "Session type" in svg
    assert "Quality control" in svg
    assert (
        '<rect x="120" y="42" width="24" height="16" fill="none" '
        'stroke="#69716F" stroke-width="2"/>'
    ) in svg
    assert "Failed session (type-colored border)" in svg
    assert "Missing expected session" not in svg
    assert "QC tags" in svg
    assert "<circle" not in svg
    assert 'font-family="IBM Plex Mono, monospace" font-size="11.5"' in svg
    assert ">Pilot session</text>" not in svg
    assert ">One probe excluded for saturation events</text>" in svg
    assert ">10</text>" in svg
    assert svg.index(">Blood at insertion site</text>") < svg.index(">Mouse stress</text>")
    assert svg.index(">Mouse stress</text>") < svg.index(">Mouse suspected asleep</text>")
    assert "Poor opto response" not in svg
    assert "Sync problems" not in svg
    assert "Poor brain health" not in svg
    assert svg.count(">Motion correction problems</text>") == 1
    assert "Motion correction issue" not in svg
    assert "SLAP2 stopped early" in svg
    assert svg.count(">Cell matching problems</text>") == 1
    assert svg.count('class="session-qc-outline"') == 18
    assert svg.count('class="session-qc-outline" data-qc-kind="session-fail"') == 18
    failed_blocks = re.findall(
        r'<rect class="session-block"[^>]+fill="none" '
        r'stroke="(#[0-9A-F]{6})" stroke-width="2"/>',
        svg,
    )
    assert len(failed_blocks) == 18
    assert set(failed_blocks) == {
        SESSION_TYPE_COLORS["sensorimotor"],
        SESSION_TYPE_COLORS["standard"],
        SESSION_TYPE_COLORS["sequence"],
        SESSION_TYPE_COLORS["duration"],
    }
    filled_blocks = re.findall(
        r'<rect class="session-block"[^>]+fill="(#[0-9A-F]{6})" '
        r'stroke="(#[0-9A-F]{6})" stroke-width="2"/>',
        svg,
    )
    assert filled_blocks
    assert all(fill == stroke for fill, stroke in filled_blocks)
    assert "<pattern" not in svg
    assert svg.count('class="session-qc-tags"') == 47
    assert svg.count('class="session-qc-tags" data-qc-tags=') == 47
    assert all(
        numbers == sorted(numbers)
        for label in re.findall(r'data-qc-tags="([0-9,]+)"', svg)
        for numbers in [[int(number) for number in label.split(",")]]
    )
    assert '<tspan ' not in svg
    white_qc_numbers = re.findall(
        r'class="session-qc-tags"[^>]+fill="#FFFFFF" stroke="#000000" '
        r'stroke-width="1"',
        svg,
    )
    black_qc_numbers = re.findall(
        r'class="session-qc-tags"[^>]+fill="#000000" stroke="#FFFFFF" '
        r'stroke-width="1"',
        svg,
    )
    assert len(white_qc_numbers) + len(black_qc_numbers) == 47
    assert len(black_qc_numbers) == 17
    assert len(white_qc_numbers) == 30
    assert "Recording sessions per mouse</text>" not in svg
    assert "worksheet rows ·" not in svg
    assert "Static panels follow" not in svg
    assert 'stroke-dasharray="3 2"' not in svg
    assert ">C1</text>" not in svg
    assert ">C2</text>" not in svg
    assert svg.count(">Session number</text>") == 1
    session_widths = {
        float(width)
        for width in re.findall(
            r'<rect class="session-block"[^>]* width="([^"]+)"',
            svg,
        )
    }
    assert session_widths == {29.8}
    panel_title_positions = [
        float(position)
        for position in re.findall(
            r'<text class="panel-title" x="([^"]+)"',
            svg,
        )
    ]
    assert len(panel_title_positions) == 3
    panel_chunks = re.split(r'<text class="panel-title"', svg)[1:]
    first_session_positions = [
        float(re.search(r'<rect class="session-block" x="([^"]+)"', chunk).group(1))
        for chunk in panel_chunks
    ]
    assert [
        session_position - title_position
        for title_position, session_position in zip(
            panel_title_positions,
            first_session_positions,
            strict=True,
        )
    ] == [67.5, 67.5, 67.5]
    assert max(
        following - current
        for current, following in zip(
            panel_title_positions[:-1],
            panel_title_positions[1:],
            strict=True,
        )
    ) < 500
    assert svg.count('class="session-axis"') == 1
    mouse_y_positions = {
        modality: [
            float(position)
            for position in re.findall(
                rf'<text class="mouse-id" data-modality="{modality}" '
                rf'x="[^"]+" y="([^"]+)"',
                svg,
            )
        ]
        for modality in ("neuropixels", "mesoscope", "slap2")
    }
    mouse_y_steps = {
        modality: [
            following - current
            for current, following in zip(positions[:-1], positions[1:], strict=True)
        ]
        for modality, positions in mouse_y_positions.items()
    }
    assert set(mouse_y_steps["neuropixels"]) == {28, 56}
    assert set(mouse_y_steps["mesoscope"]) == {28, 56}
    assert set(mouse_y_steps["slap2"]) == {28}
    legend_position = re.search(
        r'id="session-inventory-legend" transform="translate\(([^ ]+) ([^)]+)\)"',
        svg,
    )
    assert legend_position is not None
    assert float(legend_position.group(1)) == 310
    legend_y = float(legend_position.group(2))
    assert legend_y == 421
    assert legend_y - (mouse_y_positions["mesoscope"][-1] - 4) == 56


def test_literature_comparison_is_deterministic(tmp_path: Path) -> None:
    comparison_path = write_literature_comparison_html(
        tmp_path / "literature-comparison.html"
    )
    html = comparison_path.read_text(encoding="utf-8")

    assert 'id="literature-comparison"' in html
    assert "Compare parameter" in html
    assert "Study profile" in html
    assert "Attinger et al 2017" in html
    assert "Westerberg et al 2025" in html
    assert "Download visible rows as CSV" in html
    assert 'document.querySelector("body > main")' in html
    assert 'classList.add("is-embedded")' in html
    assert "__EMBED_AUTO_HEIGHT_JS__" not in html
    assert "__LITERATURE_" not in html

    write_literature_comparison_html(comparison_path)
    assert comparison_path.read_text(encoding="utf-8") == html


def test_behavior_excerpts_are_source_backed_and_synchronized() -> None:
    payload = load_behavior_excerpts(BEHAVIOR_EXCERPTS_PATH)
    expected_video_times = {
        "neuropixels": {
            "behavior": (443.49, 448.49),
            "face": (442.953, 447.953),
            "eye": (443.18, 448.18),
        },
        "mesoscope": {
            "behavior": (429.922, 434.922),
            "face": (429.185, 434.185),
            "eye": (429.521, 434.521),
            "nose": (428.857, 433.857),
        },
        "slap2": {
            "body": (841.285, 846.812),
            "face": (833.228, 838.703),
            "eye": (828.016, 833.456),
        },
    }

    def video_time_at(time_map: list[list[float]], local_time: float) -> float:
        for first, second in zip(time_map[:-1], time_map[1:], strict=True):
            if first[0] <= local_time <= second[0]:
                fraction = (local_time - first[0]) / (second[0] - first[0])
                return first[1] + fraction * (second[1] - first[1])
        raise AssertionError(f"No frame-map interval covers {local_time}")

    assert [session["id"] for session in payload["sessions"]] == [
        "neuropixels",
        "mesoscope",
        "slap2",
    ]
    assert [session["event"]["trialNumber"] for session in payload["sessions"]] == [
        1070,
        1070,
        112,
    ]
    assert {session["traceUnit"] for session in payload["sessions"]} == {"cm/s"}
    assert {session["traceLabel"] for session in payload["sessions"]} == {
        "Running speed"
    }
    for session in payload["sessions"]:
        assert len(session["trace"]) == 321
        assert session["trace"][0][0] == 0.0
        assert session["trace"][-1][0] == payload["durationSeconds"]
        assert session["event"]["time"] == 5.0
        assert any(
            row["start"] <= session["event"]["time"] <= row["end"]
            for row in session["stimulus"]
        )
        assert all(
            camera["url"].startswith(
                "https://aind-open-data.s3.us-west-2.amazonaws.com/"
            )
            for camera in session["cameras"]
        )
        for camera in session["cameras"]:
            if session["id"] in {"neuropixels", "mesoscope"}:
                assert camera["timing"]["clock"] == "NI-DAQ sync"
                assert camera["timing"]["clockRateHz"] == 100_000.0
                assert camera["timing"]["encodedRateHz"] == 60.0
                assert camera["timing"]["leadingMetadataFrames"] == 1
                assert "syncLine" in camera["timing"]
            else:
                assert camera["timing"] == {
                    "clock": "Harp CameraFrameTime",
                    "encodedRateHz": 30.0,
                    "leadingMetadataFrames": 0,
                    "reportedDroppedFrames": 0,
                }
            expected_start, expected_event = expected_video_times[session["id"]][
                camera["id"]
            ]
            assert video_time_at(camera["timeMap"], 0.0) == pytest.approx(
                expected_start, abs=0.002
            )
            assert video_time_at(camera["timeMap"], 5.0) == pytest.approx(
                expected_event, abs=0.002
            )
        assert all(
            camera["timeMap"][0][0] <= 0
            and camera["timeMap"][-1][0] >= payload["durationSeconds"]
            and all(
                current[0] > previous[0] and current[1] > previous[1]
                for previous, current in zip(
                    camera["timeMap"][:-1], camera["timeMap"][1:], strict=True
                )
            )
            for camera in session["cameras"]
        )
        assert all(
            source.get("sha256") or source.get("etag")
            for source in session["sources"]
        )


def test_behavior_viewer_is_deterministic(tmp_path: Path) -> None:
    static_path = tmp_path / "synchronized-behavior.svg"
    viewer_path = write_behavior_viewer_html(
        tmp_path / "behavior-viewer.html",
        static_output=static_path,
    )
    html = viewer_path.read_text(encoding="utf-8")

    assert 'id="behavior-viewer"' in html
    assert "Neuropixels" in html
    assert "Mesoscope" in html
    assert "SLAP2" in html
    assert html.count('"logo":"data:image/png;base64,') == 3
    assert 'className = "modality-logo"' in html
    assert 'button.append(logo, session.label)' in html
    assert "820459" in html
    assert "832700" in html
    assert "796630" in html
    assert "aind-open-data.s3.us-west-2.amazonaws.com" in html
    assert 'data-view="interactive"' in html
    assert 'data-view="static"' in html
    assert 'id="static-view"' in html
    assert "media/behavior-viewer/synchronized-behavior.svg" in html
    assert "selectView" in html
    assert "Wheel recording trace with synchronized playback cursor" in html
    assert 'id="running-summary-canvas"' not in html
    assert "runningStatistics" not in html
    assert "drawRunningSummary" not in html
    assert "Control versus context-block running" not in html
    assert "videoTimeAt" in html
    assert "localTimeAt" in html
    assert html.count('id="play-toggle"') == 1
    assert 'id="stage-play"' not in html
    assert "stagePlay" not in html
    assert 'document.querySelector("body > main")' in html
    assert 'classList.add("is-embedded")' in html
    assert 'document.documentElement.style.overflow = "hidden"' in html
    assert 'addEventListener("resize", syncHeight)' in html
    assert "@media (max-width: 560px)" in html
    assert 'id="alignment-label"' not in html
    assert "offsetSeconds" not in html
    for label, color in {
        "Sensorimotor mismatch": "#283185",
        "Standard oddball": "#22bcad",
        "Sequence mismatch": "#b16027",
        "Duration mismatch": "#ccaf2d",
    }.items():
        assert f'"{label}": "{color}"' in html
    assert "#3157b7" not in html
    assert "#008f80" not in html
    assert "__EMBED_AUTO_HEIGHT_JS__" not in html
    assert "__BEHAVIOR_" not in html
    copied_static = tmp_path / "media" / "behavior-viewer" / static_path.name
    assert copied_static.read_bytes() == static_path.read_bytes()

    write_behavior_viewer_html(viewer_path, static_output=static_path)
    assert viewer_path.read_text(encoding="utf-8") == html


def test_eye_tracking_snapshot_is_source_backed() -> None:
    payload = load_eye_tracking_excerpts()

    assert payload["version"] == 2
    assert payload["durationSeconds"] == 16.0
    assert [session["id"] for session in payload["sessions"]] == [
        "neuropixels",
        "mesoscope",
        "slap2",
    ]
    assert [session["event"]["trialNumber"] for session in payload["sessions"]] == [
        863,
        1535,
        1354,
    ]
    assert payload["sessions"][2]["subject"] == "829704"
    for session in payload["sessions"]:
        assert set(session["fits"]) == {"pupil", "corneal_reflection", "ellipse"}
        assert [session["fits"][fit_id]["label"] for fit_id in (
            "pupil",
            "corneal_reflection",
            "ellipse",
        )] == ["Pupil", "Corneal reflection", "Eye ellipse"]
        for fit in session["fits"].values():
            assert len(fit["samples"]) >= 450
            assert fit["samples"][0][0] <= 0.04
            assert fit["samples"][-1][0] >= 15.95
            assert any(sample[-1] for sample in fit["samples"])
            reference = fit["fieldReference"]
            assert 0 <= reference["medianX"] < reference["frameWidth"]
            assert 0 <= reference["medianY"] < reference["frameHeight"]
            assert reference["areaLow"] < reference["areaHigh"]
            assert reference["validNonblinkSamples"] > 100_000
        assert session["camera"]["id"] == "eye"
        assert session["camera"]["timeMap"][0][0] <= 0
        assert session["camera"]["timeMap"][-1][0] >= payload["durationSeconds"]
        assert all(
            source.get("sha256") or source.get("etag") or source.get("asset_id")
            for source in session["sources"]
        )
    assert EYE_TRACKING_EXCERPTS_PATH.stat().st_size < 4_000_000


def test_eye_tracking_viewer_is_deterministic(tmp_path: Path) -> None:
    static_path = tmp_path / "synchronized-eye-tracking.svg"
    viewer_path = write_eye_tracking_viewer_html(
        tmp_path / "eye-tracking-viewer.html",
        static_output=static_path,
    )
    html = viewer_path.read_text(encoding="utf-8")

    assert 'id="eye-tracking-viewer"' in html
    assert 'id="eye-video"' in html
    assert 'id="stimulus-canvas"' in html
    assert 'id="pupil-field"' in html
    assert 'id="pupil-trace"' in html
    assert 'id="fit-selector"' in html
    assert "SLAP2" in html
    assert "Corneal reflection" in html
    assert "Eye ellipse" in html
    assert "Full-session median" in html
    assert "fieldReference" in html
    assert "sampleBounds" not in html
    assert "Pupil area trace with blink intervals" in html
    assert "Likely blink" in html
    assert "drawField" in html
    assert "currentFit" in html
    assert "selectFit" in html
    assert "blinkIntervals" in html
    assert 'data-view="static"' in html
    assert 'id="static-view"' in html
    assert "synchronized-eye-tracking.svg" in html
    assert "videoTimeAt" in html
    assert "localTimeAt" in html
    assert html.count('id="play-toggle"') == 1
    assert 'id="stage-play"' not in html
    assert "stagePlay" not in html
    assert '<details class="session-metadata">' in html
    assert '<details class="session-metadata" open>' not in html
    assert html.index('id="pupil-trace"') < html.index('class="session-metadata"')
    assert html.index('class="session-metadata"') < html.index('id="source-links"')
    assert "aind-open-data.s3.us-west-2.amazonaws.com" in html
    assert 'document.querySelector("body > main")' in html
    assert "@media (max-width: 760px)" in html
    assert "__EYE_TRACKING_" not in html
    assert "__EMBED_AUTO_HEIGHT_JS__" not in html
    copied_static = tmp_path / "media" / "eye-tracking-viewer" / static_path.name
    assert copied_static.read_bytes() == static_path.read_bytes()

    write_eye_tracking_viewer_html(viewer_path, static_output=static_path)
    assert viewer_path.read_text(encoding="utf-8") == html


def test_eye_tracking_static_figure_is_source_backed(tmp_path: Path) -> None:
    output = write_eye_tracking_static_svg(tmp_path / "synchronized-eye-tracking.svg")
    svg = output.read_text(encoding="utf-8")

    assert "Synchronized eye-tracking signals across recording modalities" in svg
    assert svg.count('class="oddball-period"') == 9
    assert svg.count('class="blink-period"') >= 3
    assert svg.count("X position") == 3
    assert svg.count("Y position") == 3
    assert svg.count("Pupil area") == 3
    for label, subject, trial in (
        ("Neuropixels", "820454", "863"),
        ("Mesoscope", "832700", "1535"),
        ("SLAP2", "829704", "1354"),
    ):
        assert label in svg
        assert f"mouse {subject} · trial {trial}" in svg

    write_eye_tracking_static_svg(output)
    assert output.read_text(encoding="utf-8") == svg


def test_behavior_static_figure_is_source_backed(tmp_path: Path) -> None:
    provenance = json.loads(
        BEHAVIOR_STATIC_FRAME_PROVENANCE_PATH.read_text(encoding="utf-8")
    )
    assert provenance["version"] == 2
    assert provenance["behavior_excerpts_sha256"] == hashlib.sha256(
        BEHAVIOR_EXCERPTS_PATH.read_bytes()
    ).hexdigest()
    assert provenance["running_statistics_sha256"] == hashlib.sha256(
        RUNNING_STATISTICS_PATH.read_bytes()
    ).hexdigest()
    assert provenance["local_time_seconds"] == 8.0
    assert len(provenance["frames"]) == 10
    assert {
        modality: sum(record["modality"] == modality for record in provenance["frames"])
        for modality in ("neuropixels", "mesoscope", "slap2")
    } == {"neuropixels": 3, "mesoscope": 4, "slap2": 3}
    for record in provenance["frames"]:
        frame_path = BEHAVIOR_STATIC_FRAME_DIR / record["asset_path"]
        assert hashlib.sha256(frame_path.read_bytes()).hexdigest() == record[
            "output_sha256"
        ]
        assert record["source_etag"]
        assert record["source_content_length"] > 0
        assert record["mouse_id"]
        assert record["source_session_id"]
        assert record["decoded_video_time_seconds"] >= record[
            "target_video_time_seconds"
        ]
        contrast = record["display_contrast"]
        assert contrast["method"] == "luminance percentile stretch with adaptive gamma"
        assert contrast["low_percentile"] == 1.0
        assert contrast["high_percentile"] == 99.0
        assert contrast["target_median"] == 0.35
        assert 0 <= contrast["low_value"] < contrast["high_value"] <= 255
        assert 0.35 <= contrast["gamma"] <= 1.0

    svg_path = write_behavior_static_svg(tmp_path / "synchronized-behavior.svg")
    svg = svg_path.read_text(encoding="utf-8")
    statistics_payload = load_running_statistics()
    assert 'width="1800" height="1080"' in svg
    assert svg.count("data:image/jpeg;base64,") == 10
    assert svg.count("data:image/png;base64,") == 3
    assert svg.count('class="platform-heading" data-modality=') == 3
    assert_modality_title_scale(svg)
    assert svg.count('class="platform-logo"') == 3
    assert svg.count('width="54" height="54"') == 3
    assert svg.count('class="behavior-camera-card" data-modality="neuropixels"') == 3
    assert svg.count('class="behavior-camera-card" data-modality="mesoscope"') == 4
    assert svg.count('class="behavior-camera-card" data-modality="slap2"') == 3
    assert "camera stills: 8 s in synchronized excerpts" not in svg
    assert "Full-session running profile" not in svg
    assert "camera streams" not in svg
    assert svg.count('class="running-profile"') == 3
    assert svg.count('class="running-profile-block"') == 24
    assert svg.count(">0m</text>") == 1
    assert svg.count(">20m</text>") == 1
    assert svg.count(">40m</text>") == 1
    assert svg.count(">60m</text>") == 1
    for block, color in {
        "standard": "#D9DFE3",
        "context": "#283185",
        "standard_repeat": "#C7D0D6",
        "sequence": "#B5C1C8",
        "jitter": "#A4B2BA",
        "open_loop": "#92A3AC",
        "movie": "#80949E",
        "rf": "#6F858F",
    }.items():
        assert re.search(
            rf'class="running-profile-block" data-block="{block}"[^>]+fill="{color}"',
            svg,
        )
    assert re.search(
        r'class="running-block-region" data-block="context"[^>]+fill="#68706E"',
        svg,
    )
    assert "Wheel encoder velocity (counts/s)" not in svg
    assert "Average running speed across blocks" not in svg
    assert svg.count('class="running-summary-plot" data-shared-y-axis="true"') == 1
    assert '<g class="running-summary" transform="translate(0 30)">' in svg
    assert 'class="running-panel-label"' in svg
    assert svg.count('class="running-block-header"') == 0
    assert svg.count('class="running-block-region"') == 8
    assert svg.count("Mean forward speed (cm/s)") == 1
    axis_title = re.search(r'<text class="running-y-axis-title"[^>]*>', svg)
    assert axis_title is not None
    assert "transform=" not in axis_title.group()
    assert svg.count('class="running-block-mean"') == 24
    assert svg.count('class="running-block-point"') == len(
        statistics_payload["mouse_block"]
    )
    for modality, color in {
        "neuropixels": "#4B79C6",
        "mesoscope": "#14866C",
        "slap2": "#168EA0",
    }.items():
        assert len(
            re.findall(
                rf'class="running-block-mean" data-block="[^"]+" '
                rf'data-modality="{modality}"[^>]+fill="{color}"',
                svg,
            )
        ) == 8
    profiles = {
        profile["modality"]: profile
        for profile in statistics_payload["example_profiles"]
    }
    for record in provenance["frames"]:
        assert record["mouse_id"] == profiles[record["modality"]]["mouse_id"]
        assert record["source_session_id"] == profiles[record["modality"]][
            "source_session_id"
        ]


def test_running_statistics_are_source_backed_and_mouse_aggregated() -> None:
    payload = load_running_statistics()

    assert payload["version"] == 2
    assert payload["sample_rate_hz"] == 20
    assert payload["threshold_cm_s"] == 1.0
    assert payload["source_session_records"]["sha256"] == hashlib.sha256(
        SESSION_RECORDS_PATH.read_bytes()
    ).hexdigest()
    assert [context["id"] for context in payload["contexts"]] == [
        "sensorimotor",
        "standard",
        "sequence",
        "duration",
    ]
    calibration = payload["calibration"]["slap2"]
    assert calibration["counts_per_revolution"] == 8192
    assert calibration["wheel_radius_cm"] == 8.255
    assert calibration["subject_position"] == pytest.approx(2 / 3)
    assert "37ce6471824c5f76b18820e429c7d8fd69352f0a" in calibration["source_url"]

    sessions = payload["sessions"]
    summaries = payload["mouse_context"]
    mouse_blocks = payload["mouse_block"]
    coverage = payload["coverage"]
    profiles = payload["example_profiles"]
    expected_blocks = [
        "standard",
        "context",
        "standard_repeat",
        "sequence",
        "jitter",
        "open_loop",
        "movie",
        "rf",
    ]
    assert {record["modality"] for record in sessions} == {
        "neuropixels",
        "mesoscope",
        "slap2",
    }
    assert len(coverage) == 12
    assert sum(record["included_sessions"] for record in coverage) == len(sessions)
    assert sum(record["included_mice"] for record in coverage) == len(summaries)
    assert len(mouse_blocks) % 8 == 0
    assert {(record["modality"], record["block"]) for record in mouse_blocks} == {
        (modality, block)
        for modality in ("neuropixels", "mesoscope", "slap2")
        for block in expected_blocks
    }
    assert [record["modality"] for record in profiles] == [
        "neuropixels",
        "mesoscope",
        "slap2",
    ]
    assert all(profile["bin_seconds"] == 5 for profile in profiles)
    assert all(4200 < profile["duration_seconds"] < 4400 for profile in profiles)
    assert all(len(profile["points"]) > 800 for profile in profiles)
    assert all(
        [block["id"] for block in profile["blocks"]] == expected_blocks
        for profile in profiles
    )
    assert all(record["duration_seconds"] > 60 * 60 for record in sessions)
    assert all(0 <= record["running_fraction"] <= 1 for record in sessions)
    assert all(0 <= record["mean_forward_speed_cm_s"] < 100 for record in sessions)
    assert all(
        [block["id"] for block in record["blocks"]] == expected_blocks
        for record in sessions
    )
    assert all(
        0 <= record["control_mean_forward_speed_cm_s"] < 100
        and 0 <= record["context_mean_forward_speed_cm_s"] < 100
        for record in sessions
    )

    for session in sessions:
        source = session["source"]
        if session["modality"] == "slap2":
            assert source["encoder"]["etag"]
            assert len(source["encoder"]["sha256"]) == 64
            assert source["device"]["etag"]
            assert source["pulse_do0"]["etag"]
            assert source["pulse_do2"]["etag"]
            assert source["stimulus"]["etag"]
        else:
            assert source["asset_id"]
            assert source["size"] > 0
            assert source["download_url"].endswith("/download/")

    for summary in summaries:
        matching = [
            session
            for session in sessions
            if session["modality"] == summary["modality"]
            and session["mouse_id"] == summary["mouse_id"]
            and session["context"] == summary["context"]
        ]
        assert len(matching) == summary["session_count"]
        assert sorted(record["source_session_id"] for record in matching) == summary[
            "source_session_ids"
        ]
        assert summary["mean_forward_speed_cm_s"] == pytest.approx(
            sum(record["mean_forward_speed_cm_s"] for record in matching)
            / len(matching),
            abs=1e-4,
        )
        assert summary["running_fraction"] == pytest.approx(
            sum(record["running_fraction"] for record in matching) / len(matching),
            abs=1e-6,
        )
        assert summary["control_mean_forward_speed_cm_s"] == pytest.approx(
            sum(record["control_mean_forward_speed_cm_s"] for record in matching)
            / len(matching),
            abs=1e-4,
        )
        assert summary["context_mean_forward_speed_cm_s"] == pytest.approx(
            sum(record["context_mean_forward_speed_cm_s"] for record in matching)
            / len(matching),
            abs=1e-4,
        )

    for summary in mouse_blocks:
        matching = [
            session
            for session in sessions
            if session["modality"] == summary["modality"]
            and session["mouse_id"] == summary["mouse_id"]
        ]
        assert len(matching) == summary["session_count"]
        assert summary["mean_forward_speed_cm_s"] == pytest.approx(
            sum(
                record["block_mean_forward_speed_cm_s"][summary["block"]]
                for record in matching
            )
            / len(matching),
            abs=1e-4,
        )


def test_neural_excerpts_are_source_backed_and_aligned() -> None:
    assert hashlib.sha256(NEURAL_EXCERPTS_PATH.read_bytes()).hexdigest() == (
        "d9c5e84a3417c44ec6a929763e59bb61db20f2ff7bc3a7a55b3bbaa32b6f99d8"
    )
    payload = load_neural_excerpts(NEURAL_EXCERPTS_PATH)

    assert [session["id"] for session in payload["sessions"]] == [
        "neuropixels",
        "mesoscope",
        "slap2",
    ]
    assert [session["viewType"] for session in payload["sessions"]] == [
        "heatmap",
        "movie",
        "movie",
    ]
    assert [len(session["options"]) for session in payload["sessions"]] == [6, 8, 4]
    assert [session["signalUnit"] for session in payload["sessions"]] == [
        "uV",
        "detector counts",
        "detector counts",
    ]
    assert payload["sessions"][0]["session"] == "ecephys_830846_2026-03-09_10-32-54"
    assert payload["sessions"][0]["subject"] == "830846"
    assert payload["sessions"][0]["context"] == "Sequence mismatch"
    assert payload["sessions"][0]["event"] == {
        "label": "Sequence omission",
        "time": 0.0,
        "trialNumber": 549,
    }
    for session in payload["sessions"]:
        assert session["event"]["time"] == 0.0
        assert any(row["start"] <= 0 <= row["end"] for row in session["stimulus"])
    for option in payload["sessions"][0]["options"]:
        assert (option["rows"], option["columns"]) == (96, 3000)
        assert len(base64.b64decode(option["dataBase64"])) == 288_000
        assert (option["depthMinUm"], option["depthMaxUm"]) == (0.0, 3800.0)
        assert option["nativeSampleRateHz"] == 30_000.0
        assert option["sourceChannels"] == list(range(380, -1, -4))
        assert option["timeStartSeconds"] <= -0.0499
        assert option["timeEndSeconds"] >= 0.0498
        assert "apDataBase64" not in option
        assert option["anatomySegments"][0]["startRow"] == 0
        assert option["anatomySegments"][-1]["endRow"] == 96
        assert all(
            current["endRow"] == following["startRow"]
            for current, following in zip(
                option["anatomySegments"][:-1],
                option["anatomySegments"][1:],
                strict=True,
            )
        )
    assert [
        len(option["anatomySegments"])
        for option in payload["sessions"][0]["options"]
    ] == [17, 18, 21, 19, 13, 13]
    assert [
        segment["label"]
        for segment in payload["sessions"][0]["options"][0]["anatomySegments"]
    ] == [
        "void",
        "MOs1",
        "MOs2/3",
        "MOs5",
        "ACAd5",
        "ACAd6a",
        "ACAv6a",
        "ACAv5",
        "ACAv6a",
        "cing",
        "ccb",
        "LSc",
        "fi",
        "V3",
        "sm",
        "TH",
        "IAD",
    ]
    assert payload["sessions"][0]["options"][2]["anatomyLabel"] == (
        "VISp L1–L6a · CA1–CA3 / DG · LGd / VPM"
    )
    movie_options = [
        option for session in payload["sessions"][1:] for option in session["options"]
    ]
    assert [
        (option["id"], option["imagingDepthUm"], option["channel"])
        for option in payload["sessions"][1]["options"]
    ] == [
        ("visp_0", 152, 2),
        ("visp_1", 300, 1),
        ("visp_2", 49, 2),
        ("visp_3", 402, 1),
        ("visl_4", 149, 2),
        ("visl_5", 300, 1),
        ("visl_6", 50, 2),
        ("visl_7", 404, 1),
    ]
    assert [option["targetLayer"] for option in payload["sessions"][1]["options"]] == [
        "L2/3",
        "L4",
        "L1",
        "L5",
        "L2/3",
        "L4",
        "L1",
        "L5",
    ]
    assert {
        option["micronsPerPixel"] for option in payload["sessions"][1]["options"]
    } == {0.78}
    assert [option["measurement"] for option in payload["sessions"][2]["options"]] == [
        "iGluSnFR4f",
        "RCaMP3",
        "iGluSnFR4f",
        "RCaMP3",
    ]
    assert [
        option["remoteFocusDepthBelowPiaUm"]
        for option in payload["sessions"][2]["options"]
    ] == [91.0, 91.0, 123.75, 123.75]
    assert {
        option["micronsPerPixel"] for option in payload["sessions"][2]["options"]
    } == {0.25}
    slap2_options = payload["sessions"][2]["options"]
    assert {
        (
            option["frameWidth"],
            option["frameHeight"],
            option["spatialDownsampleFactor"],
            option["spriteEncoding"],
        )
        for option in slap2_options
    } == {(400, 640, 2, "lossless WebP")}
    assert {
        (
            option["nativeWidth"],
            option["nativeHeight"],
            option["displayWidth"],
            option["displayHeight"],
            option["storedWidth"],
            option["storedHeight"],
            option["displayTransform"],
        )
        for option in slap2_options
    } == {(1280, 800, 800, 1280, 1280, 800, "transpose-for-publication")}
    assert {option["fastScanAxis"] for option in slap2_options} == {"vertical"}
    for green_option, red_option in zip(
        slap2_options[0::2], slap2_options[1::2], strict=True
    ):
        assert green_option["frameTimes"] == red_option["frameTimes"]
        assert green_option["compositeAssetPath"] == red_option["compositeAssetPath"]
        assert (
            green_option["compositeSheetSha256"]
            == red_option["compositeSheetSha256"]
        )
        composite_asset = NEURAL_MEDIA_DIR / Path(
            green_option["compositeAssetPath"]
        ).name
        assert hashlib.sha256(composite_asset.read_bytes()).hexdigest() == (
            green_option["compositeSheetSha256"]
        )
    assert len(movie_options) == 12
    for option in movie_options:
        assert option["frameTimes"][0] <= -0.9
        assert option["frameTimes"][-1] >= 2.89
        assert len(option["frameTimes"]) == option["frameCount"]
        asset = NEURAL_MEDIA_DIR / Path(option["assetPath"]).name
        assert hashlib.sha256(asset.read_bytes()).hexdigest() == option["sheetSha256"]
    slap2_ranges = [
        source
        for source in payload["sessions"][2]["sources"]
        if "rangeSha256" in source
    ]
    assert [source["trialNumber"] for source in slap2_ranges] == [26, 26]
    assert [source["rangeStop"] - source["rangeStart"] for source in slap2_ranges] == [
        40_649_112,
        46_698_496,
    ]


def test_neural_excerpts_require_anatomical_context(tmp_path: Path) -> None:
    payload = json.loads(NEURAL_EXCERPTS_PATH.read_text(encoding="utf-8"))
    payload["sessions"][0]["options"][0]["anatomyLabel"] = " "
    snapshot_path = tmp_path / "raw-neural-excerpts.json"
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match="lacks anatomical context"):
        load_neural_excerpts(snapshot_path)


def test_neural_viewer_is_deterministic(tmp_path: Path) -> None:
    static_path = tmp_path / "raw-neural-recordings.svg"
    viewer_path = write_neural_viewer_html(
        tmp_path / "neural-viewer.html",
        static_output=static_path,
    )
    html = viewer_path.read_text(encoding="utf-8")

    assert 'id="neural-viewer"' in html
    assert 'id="raw-canvas"' in html
    assert 'id="option-select"' in html
    assert 'id="contrast"' in html
    assert 'id="playhead"' in html
    assert 'data-view="interactive"' in html
    assert 'data-view="static"' in html
    assert 'id="static-view"' in html
    assert "media/neural-viewer/raw-neural-recordings.svg" in html
    assert "max-width: 900px" not in html
    assert "max-width: 1200px" not in html
    assert 'classList.toggle("static-active", view === "static")' in html
    assert "function microscopyFrame(option, record, frameIndex)" in html
    assert "movieFrameContext.getImageData" in html
    assert "movieFrameContext.putImageData" in html
    assert "context.filter" not in html
    assert "selectView" in html
    assert "Excerpt time (s)" in html
    assert "Excerpt time (ms)" in html
    assert "Time from event onset" not in html
    assert "aligned to event onset" not in html
    assert "event-tick" not in html
    assert "xForExcerptTime" not in html
    assert '"event":' not in html
    assert '"stimulus":' not in html
    assert '"alignment":' not in html
    assert "Neuropixels" in html
    assert "Mesoscope" in html
    assert "SLAP2" in html
    assert html.count('"logo":"data:image/png;base64,') == 3
    assert 'className = "modality-logo"' in html
    assert 'button.append(logo, session.label)' in html
    assert "Raw AP acquisition voltage" in html
    assert "Raw AP acquisition" in html
    assert "colorbarX" not in html
    assert "Raw 30 kHz AP acquisition voltage with CCF boundaries" in html
    assert "drawAnatomySegments" in html
    assert "anatomySegments" in html
    assert "Raw imaging frames with a 50 micrometer scale bar" in html
    assert "scaleBarMicrons = 50" in html
    assert "LFP" not in html
    assert "apDataBase64" not in html
    assert "Raw two-photon frames" in html
    assert "Sparse raw detector frames" in html
    assert "storedWidth || option.nativeWidth" in html
    assert "storedHeight || option.nativeHeight" in html
    assert "option.displayWidth || option.nativeWidth" in html
    assert "dataBase64" in html
    assert "mesoscope-visp-0.webp" in html
    assert "rangeSha256" in html
    assert 'document.querySelector("body > main")' in html
    assert 'id="signal-summary"' not in html
    assert "event-key" not in html
    assert "drawStimulusTrack" not in html
    assert 'elements.transport.hidden = session.viewType === "heatmap"' in html
    assert "__NEURAL_" not in html
    assert "__EMBED_AUTO_HEIGHT_JS__" not in html
    copied_media = tmp_path / "media" / "neural-viewer"
    assert len(list(copied_media.glob("*.webp"))) == 14
    assert (copied_media / "slap2-dmd1-composite.webp").is_file()
    assert (copied_media / "slap2-dmd2-composite.webp").is_file()
    assert (copied_media / static_path.name).read_bytes() == static_path.read_bytes()

    write_neural_viewer_html(viewer_path, static_output=static_path)
    assert viewer_path.read_text(encoding="utf-8") == html


def test_neural_static_figure_is_source_backed(tmp_path: Path) -> None:
    provenance = json.loads(
        NEURAL_STATIC_FRAME_PROVENANCE_PATH.read_text(encoding="utf-8")
    )
    assert provenance["version"] == 2
    assert provenance["raw_neural_excerpts_sha256"] == hashlib.sha256(
        NEURAL_EXCERPTS_PATH.read_bytes()
    ).hexdigest()
    assert len(provenance["frames"]) == 10
    assert {
        (record["modality"], record["option_id"])
        for record in provenance["frames"]
    } == {
        ("mesoscope", "visp_0"),
        ("mesoscope", "visp_1"),
        ("mesoscope", "visp_2"),
        ("mesoscope", "visp_3"),
        ("mesoscope", "visl_4"),
        ("mesoscope", "visl_5"),
        ("mesoscope", "visl_6"),
        ("mesoscope", "visl_7"),
        ("slap2", "dmd1-composite"),
        ("slap2", "dmd2-composite"),
    }
    for record in provenance["frames"]:
        frame_path = NEURAL_STATIC_FRAME_DIR / record["asset_path"]
        assert hashlib.sha256(frame_path.read_bytes()).hexdigest() == record[
            "output_sha256"
        ]
        if record["modality"] == "mesoscope":
            contrast = record["display_contrast"]
            assert contrast["method"] == "max-channel hue-preserving linear stretch"
            assert contrast["low_percentile"] == 1.0
            assert contrast["high_percentile"] == 99.5
            assert 0 <= contrast["low_value"] < contrast["high_value"] <= 255
        else:
            assert record["frame_size"] == [400, 640]
            assert record["spatial_downsample_factor"] == 2
            assert record["temporal_averaging_frames"] == 1
            assert record["display_contrast"] == {
                "gamma": 0.55,
                "method": "max-channel hue-preserving gamma",
            }
            assert record["channel_composite"] == {
                "green": "iGluSnFR4f",
                "red": "RCaMP3",
                "source_high_percentile": 99.5,
                "source_low_percentile": 1.0,
            }

    svg_path = write_neural_static_svg(tmp_path / "raw-neural-recordings.svg")
    svg = svg_path.read_text(encoding="utf-8")
    assert 'width="1800" height="700"' in svg
    assert svg.count("data:image/png;base64,") == 19
    assert svg.count('class="platform-heading" data-modality=') == 3
    assert_modality_title_scale(svg)
    assert svg.count('class="platform-logo"') == 3
    assert svg.count('y="1" width="96" height="96"') == 3
    assert svg.count('class="raw-image-card" data-modality="neuropixels"') == 6
    assert svg.count('class="raw-image-card" data-modality="mesoscope"') == 8
    assert svg.count('class="raw-image-card" data-modality="slap2"') == 2
    assert svg.count('data-modality="slap2" data-option-id=') == 2
    assert svg.count('data-card-width="265"') == 2
    assert svg.count('class="raw-card-image"') == 16
    assert svg.count('data-modality="mesoscope" data-option-id=') == 8
    assert svg.count('data-card-width="255"') == 8
    assert "Probe A" in svg
    assert "Probe F" in svg
    assert "VISp · 4 planes" in svg
    assert "VISl · 4 planes" in svg
    assert "DMD1 · 91 µm" in svg
    assert "DMD2 · 123.75 µm" in svg
    assert "green + red composite" not in svg
    assert svg.count(">50 µm</text>") == 1
    assert svg.count(">25 µm</text>") == 1
    assert "6 probe recordings · all raw excerpts stacked" in svg
    assert "8 planes · 4 VISp + 4 VISl · all raw frames stacked" in svg
    assert "2 VISp planes · merged green + red channels" in svg
    assert "±" not in svg
    assert "µV" not in svg
    assert 'font-size="12" font-weight="600" text-anchor="middle"' in svg
    assert svg.count('class="neural-detail-label"') == 3
    assert re.findall(
        r'class="neural-detail-label"[^>]+\sy="([^"]+)"[^>]+font-size="([^"]+)"',
        svg,
    ) == [("122", "18")] * 3
    assert '<rect x="650.00" y="135.00" width="255"' in svg
    assert '<rect x="1240.00" y="135.00" width="265"' in svg
    assert '<rect x="1510.00" y="135.00" width="265"' in svg
    assert "#D9DEDC" not in svg
    assert "scale-card" not in svg
    assert "playback" not in svg.lower()
    assert "event onset" not in svg.lower()


def test_publication_table_data() -> None:
    data = load_publication_table_data()

    animals = data["tables"]["animals"]
    sessions = data["tables"]["sessions"]
    with SESSION_RECORDS_PATH.open(newline="", encoding="utf-8") as stream:
        source_sessions = list(csv.DictReader(stream))
    expected_session_ids = {
        row["source_session_id"]
        for row in source_sessions
        if row["qc"].strip().casefold() == "pass"
        and row["source_session_id"].strip() not in {"", "aborted"}
    }
    assert len(animals["rows"]) == 39
    assert len({row["values"][0] for row in animals["rows"]}) == 39
    assert {row["values"][0] for row in sessions["rows"]} == expected_session_ids
    assert {row["qc"] for row in sessions["rows"]} == {"pass"}
    assert sessions["headers"] == ["Session ID", "Mouse ID", "Date", "Modality", "Context"]
    failed_mouse = next(row for row in animals["rows"] if row["values"][0] == "841193")
    assert failed_mouse["values"][3] == "FAILED"
    assert failed_mouse["qc"] == "failed"


def test_animal_record_provenance() -> None:
    provenance = json.loads(
        ANIMAL_RECORDS_PROVENANCE_PATH.read_text(encoding="utf-8")
    )

    assert len(provenance["source_sha256"]) == 64
    assert provenance["vendored_sha256"] == hashlib.sha256(
        ANIMAL_RECORDS_PATH.read_bytes()
    ).hexdigest()