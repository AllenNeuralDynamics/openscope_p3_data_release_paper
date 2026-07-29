from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

GOOGLE_DOC_ID = "1A4aj5E1jsv-XihPt2_6K0TKMnwvtiMAFau3qJUcOV-I"
GOOGLE_DOC_URL = f"https://docs.google.com/document/d/{GOOGLE_DOC_ID}/edit"
GOOGLE_DOC_EXPORT_URL = (
    f"https://docs.google.com/document/d/{GOOGLE_DOC_ID}/export?format=docx"
)
REPO_ROOT = Path(__file__).resolve().parents[1]
MESOSCOPE_LASER_POWER_PATH = (
    REPO_ROOT / "figure_sources" / "data" / "mesoscope-laser-power.csv"
)
OTHER_STUDIES_PATH = REPO_ROOT / "figure_sources" / "data" / "other-oddball-studies.csv"
OTHER_STUDIES_PROVENANCE_PATH = OTHER_STUDIES_PATH.with_suffix(".provenance.json")
SLIDE_15_SOURCE_PATH = (
    REPO_ROOT
    / "figure_sources"
    / "google-slides"
    / "slide-15-neuropixels-implant.png"
)
SLIDE_15_PROVENANCE_PATH = SLIDE_15_SOURCE_PATH.with_suffix(".provenance.json")
DERIVED_FIGURE_PROVENANCE_PATH = (
    REPO_ROOT / "figure_sources" / "derived" / "cropped-figures.provenance.json"
)
FIGURE_1_PROVENANCE_PATH = (
    REPO_ROOT
    / "figure_sources"
    / "illustrator"
    / "figure-01-predictive-processing.provenance.json"
)


@dataclass(frozen=True)
class FigureAsset:
    source_name: str
    filename: str
    label: str
    alt: str
    caption: str
    status: str = "draft"
    supplementary_number: int | None = None


FIGURE_ASSETS = (
    FigureAsset(
        "image12.png",
        "figure-01-graphical-abstract.png",
        "fig-graphical-abstract",
        "Predictive processing across brain-wide, local-circuit, and single-cell scales.",
        (
            "Predictive processing across spatial scales. A visual sequence "
            "establishes an expectation (blue), whereas an unexpected oddball "
            "produces a prediction-error signal (red). Predictions and errors may "
            "be expressed through reciprocal brain-wide pathways, within local "
            "cortical populations, and across the dendritic and somatic compartments "
            "of individual neurons. The multimodal dataset samples these nested "
            "scales to test whether mismatch responses reflect a shared computation "
            "or scale- and circuit-specific mechanisms."
        ),
    ),
    FigureAsset(
        "image10.png",
        "figure-02-experimental-design.png",
        "fig-experimental-design",
        (
            "Experimental workflow, recording cohorts, four mismatch contexts, "
            "and shared control blocks."
        ),
        (
            "Experimental design and shared stimulus architecture. **A,** Animals "
            "progressed from surgery through intrinsic-signal-imaging mapping and "
            "habituation before recording with mesoscope two-photon imaging, "
            "Neuropixels, or SLAP2. **B,** Motor- and sequence-habituated cohorts "
            "experienced the same four recording contexts in cohort-specific orders; "
            "open squares denote training without mismatches and colored squares "
            "denote recording sessions with mismatches. **C,** Every recording used "
            "the same block order: standard control, context-specific mismatch, "
            "repeat standard control, sequential control, duration-jitter control, "
            "open-loop playback, receptive-field mapping, and zebra movie. **D,** "
            "Context panels summarize standard oddball, sensorimotor, sequence, and "
            "duration violations; control panels show the matched stimulus sets used "
            "for tuning, normalization, and cross-context comparison."
        ),
    ),
    FigureAsset(
        "image8.png",
        "figure-03-multimodal-pipelines.png",
        "fig-multimodal-pipelines",
        (
            "Neuropixels, mesoscope, and SLAP2 pipelines from behavioral cohort "
            "through rig geometry, mouse platform, and brain targeting."
        ),
        (
            "Multimodal experimental pipelines. Rows summarize Neuropixels, "
            "mesoscope two-photon calcium imaging, and SLAP2 dendritic imaging. "
            "Colored blocks indicate the cohort-specific order of predictive "
            "contexts across recording days. The central columns show each rig and "
            "head-fixed mouse platform. Brain-targeting schematics show six acute "
            "Neuropixels trajectories spanning cortical and subcortical structures, "
            "eight chronic mesoscope planes across VISp and VISlm, and dual-plane "
            "SLAP2 sampling of proximal and apical dendritic compartments in a "
            "layer II/III pyramidal neuron."
        ),
    ),
    FigureAsset(
        "image5.png",
        "figure-04-unit-extraction-plan.png",
        "fig-unit-extraction-plan",
        "Draft panel plan for unit extraction and signal-to-noise analysis across modalities.",
        "Draft plan for unit extraction and signal-to-noise analysis across recording modalities.",
        "placeholder",
    ),
    FigureAsset(
        "image3.png",
        "figure-05-basic-stimuli-plan.png",
        "fig-basic-stimuli-plan",
        "Draft panel plan for basic stimulus responses across recording modalities.",
        "Draft plan for basic stimulus characterization across recording modalities.",
        "placeholder",
    ),
    FigureAsset(
        "image6.png",
        "figure-06-behavior-tracking-plan.png",
        "fig-behavior-tracking-plan",
        "Placeholder slide titled Behavior tracking across all modalities.",
        "Placeholder for behavior tracking across recording modalities.",
        "source-only",
    ),
    FigureAsset(
        "image4.png",
        "figure-07-standard-oddball-plan.png",
        "fig-standard-oddball-plan",
        "Placeholder slide for standard oddball responses and stimulus alignment.",
        "Placeholder for standard oddball responses across recording modalities.",
        "placeholder",
    ),
    FigureAsset(
        "image14.png",
        "supplementary-neuropixels-implant-trajectories.png",
        "fig-supp-neuropixels-implant-trajectories",
        (
            "Four-panel Neuropixels implant figure showing six planned probe "
            "trajectories, atlas structures along each trajectory, stereotaxic "
            "coordinates, and implant-hole geometry."
        ),
        (
            "Neuropixels implant geometry and planned probe trajectories. "
            "**A,** Six trajectories (A-F) through the Allen Mouse Brain Common "
            "Coordinate Framework. **B,** Atlas structures intersected by each "
            "trajectory. **C,** Anteroposterior and mediolateral coordinates "
            "relative to bregma with implant-hole diameters D1 and D2. **D,** Top "
            "view of the implant with labeled probe-access holes."
        ),
        "supplementary",
        1,
    ),
    FigureAsset(
        "image9.png",
        "mesoscope-laser-power-table.png",
        "fig-mesoscope-laser-power",
        "Mesoscope laser power ranges by imaging depth from the cortical surface.",
        "Mesoscope laser power lookup table by imaging depth.",
        "source-only",
    ),
    FigureAsset(
        "image11.png",
        "supplementary-neuropixels-targeting.png",
        "fig-supp-neuropixels-targeting",
        "Neuropixels implant hole positions, stereotaxic coordinates, diameters, and targets.",
        "Neuropixels implant geometry and intended anatomical targets.",
        "removed",
    ),
    FigureAsset(
        "image13.png",
        "supplementary-neuropixels-unit-yield.png",
        "fig-supp-neuropixels-unit-yield",
        "Unit yield over four recording days for three Neuropixels probes in six mice.",
        "Example Neuropixels unit yield across recording days.",
        "supplementary",
        2,
    ),
    FigureAsset(
        "image7.png",
        "supplementary-neuropixels-visual-responses.png",
        "fig-supp-neuropixels-visual-responses",
        (
            "Visually responsive fractions, firing-rate traces, and receptive fields "
            "across Neuropixels probes."
        ),
        "Example visually evoked Neuropixels responses and receptive fields.",
        "removed",
    ),
    FigureAsset(
        "image2.png",
        "supplementary-figure-02-power-simulation-trials.png",
        "fig-supp-power-simulation-trials",
        "Measured and simulated response distributions and detection power across trial counts.",
        "Simulation of responsive-neuron detection rate across trials.",
        "removed",
    ),
    FigureAsset(
        "image1.png",
        "supplementary-figure-03-power-simulation-sessions.png",
        "fig-supp-power-simulation-sessions",
        "Responsive-neuron detection rate by trial count for one to twenty simulated sessions.",
        "Simulation of responsive-neuron detection rate across sessions.",
        "removed",
    ),
)
ASSET_BY_SOURCE = {asset.source_name: asset for asset in FIGURE_ASSETS}

IMAGE_PATTERN = re.compile(
    r'<img\s+src="[^"]*/(?P<name>image\d+\.png)"[^>]*/?>', re.IGNORECASE
)
HEADING_IMAGE_PATTERN = re.compile(
    r'^(?P<hashes>#{1,6})\s*'
    r'<img\s+src="[^"]*/(?P<name>image\d+\.png)"[^>]*/?>'
    r'(?P<title>.*)$',
    re.IGNORECASE,
)
RAW_HTML_TABLE_PATTERN = re.compile(r"<table>.*?</table>", re.DOTALL)

AUTHORSHIP_BLOCK = """:::{authorship-explorer}
:authors: ./authors.yml
:height: 800px
:::"""

INTERACTIVE_DESIGN_BLOCK = """:::{iframe} ./interactive/experimental-design.html
:label: fig-interactive-experimental-design
:width: 100%
:title: Predictive-processing stimulus viewer
:placeholder: ./images/figures/generated/experimental-design.svg

Interactive reconstruction of the four recording contexts and shared control
blocks. Context playback follows contiguous rows from the pinned generated
stimulus tables in their source (pseudo-randomized) order, with the source trial
number shown for each frame. The Movie block plays an excerpt of the canonical
zebra stimulus, and receptive-field mapping uses the stated 120° × 95° angular
projection. Source links resolve to the pinned generator, Bonsai workflow,
example tables, and public NWB intervals.
:::"""

STIMULUS_REVISION = "0365ae32f0f0473320ed202b7c5d2bce6cf5df6b"
STIMULUS_BLOB_ROOT = (
    "https://github.com/AllenNeuralDynamics/openscope-community-predictive-processing/"
    f"blob/{STIMULUS_REVISION}/code/stimulus-control/src/Mindscope"
)
STIMULUS_EXAMPLE_ROOT = f"{STIMULUS_BLOB_ROOT}/examples"
STIMULUS_PROVENANCE_BLOCK = "\n".join(
    [
        ":::{note} Stimulus table and presentation sources",
        "Pinned generated example tables are available for",
        f"[standard oddball]({STIMULUS_EXAMPLE_ROOT}/visual_mismatch_example.csv),",
        f"[sensorimotor mismatch]({STIMULUS_EXAMPLE_ROOT}/sensorimotor_mismatch_example.csv),",
        f"[sequence mismatch]({STIMULUS_EXAMPLE_ROOT}/sequence_mismatch_example.csv), and",
        f"[duration mismatch]({STIMULUS_EXAMPLE_ROOT}/duration_mismatch_example.csv),",
        f"together with the [table generator]({STIMULUS_BLOB_ROOT}/generate_experiment_csv.py)",
        f" and [Bonsai presentation workflow]({STIMULUS_BLOB_ROOT}/generic_oddball.bonsai).",
        "Exact synchronized tables for recorded sessions are stored as NWB `TimeIntervals`",
        "in the public [electrophysiology](https://dandiarchive.org/dandiset/001637/draft/files)",
        "and [mesoscope](https://dandiarchive.org/dandiset/001768/draft/files) Dandisets.",
        "The example CSVs define the protocol and schema; they are not a replay of a",
        "particular recorded session.",
        ":::"
    ]
)

DATA_EXPLORER_BLOCK = """:::{iframe} ./interactive/data-explorer.html
:label: table-data-explorer
:width: 100%
:title: Interactive explorer for experimental animals and recording sessions

Interactive record-level inventory of 39 mice and 164 recording sessions. The
Animals tab reports one row per mouse with modality, sex, quality-control status,
and expandable genotype, viral, surgical, and study-inclusion metadata. The
Sessions tab reports one row per session with its mouse, acquisition date,
recording modality, and predictive context. Search and filters update both the
visible-row count and downloadable CSV, allowing the displayed subset to be
exported without collapsing individual records into manuscript summary groups.
:::"""

OTHER_STUDIES_BLOCK = """:::{iframe} ./interactive/literature-comparison.html
:label: table-supplementary-oddball-studies
:width: 100%
:title: Supplementary Table 1. Published oddball paradigms and sampling parameters.

Compare one paradigm parameter across all studies or inspect the complete
profile of one study. Search filters the visible records in either view, and
CSV export contains exactly the displayed subset.
:::"""

BEHAVIOR_VIEWER_BLOCK = """:::{iframe} ./interactive/behavior-viewer.html
:label: fig-behavior-tracking
:width: 100%
:title: Synchronized behavior, locomotion, and visual stimuli across recording modalities

Event-centered excerpts from real Neuropixels, mesoscope, and SLAP2 recording
sessions. Behavior-camera video is range-streamed from the public
`aind-open-data` S3 bucket. The wheel trace and visual-stimulus state use the
same session clock. Neuropixels and mesoscope camera frames are mapped from
100-kHz exposure/readout edges in each sync file, including reported dropped
frames; SLAP2 uses per-frame Harp timestamps. Camera and source selectors expose
the underlying public data without bundling multi-gigabyte videos into the
publication.
:::"""

BEHAVIOR_ANALYSIS_DESCRIPTION = """## Behavioral data analysis across modalities

For sessions with camera acquisition, the release includes continuous raw
behavioral videos together with synchronized running-wheel signals, processed
eye-tracking outputs, and stimulus-presentation intervals. Depending on the
recording platform, the available views include body or behavior, face, eye,
and nose cameras. The synchronized multimodal examples in
[](#fig-behavior-tracking) show these streams alongside the wheel signal and
current stimulus state. Existing NWB products provide wheel rotation and
running speed, plus pupil, corneal-reflection, and eye-ellipse fits with
likely-blink flags. The underlying videos remain available so investigators can
derive additional behavioral measurements while preserving alignment to the
stimulus and neural or imaging data.

These synchronized videos are therefore open to more sophisticated reanalysis,
including markerless pose and keypoint tracking with
[DeepLabCut](https://github.com/DeepLabCut/DeepLabCut),
[SLEAP](https://sleap.ai/), [Lightning Pose](https://lightning-pose.readthedocs.io/),
or other computer-vision methods. Potential derived features include facial and
body motion energy, posture, grooming, locomotor state, pupil dynamics, and
trial-resolved behavioral responses. Camera frames are tied to the acquisition
clock through 100-kHz exposure or readout edges for Neuropixels and mesoscope
sessions and per-frame Harp timestamps for SLAP2, allowing newly derived
features to be registered to wheel, stimulus, electrophysiology, and imaging
signals."""

FRONTMATTER = """---
title: OpenScope Predictive Processing Community Project - Data Release
---"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export the collaborative Google Doc into the MyST publication."
    )
    parser.add_argument(
        "--docx",
        type=Path,
        help="Use an existing DOCX export instead of downloading the shared document.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "index.md",
        help="Markdown output path (default: repository index.md).",
    )
    parser.add_argument(
        "--export-date",
        default=date.today().isoformat(),
        help="Date recorded in the provenance manifest (YYYY-MM-DD).",
    )
    return parser.parse_args()


def acquire_docx(source: Path | None) -> Path:
    destination = REPO_ROOT / "manuscript_sources" / "google-doc" / "manuscript.docx"
    destination.parent.mkdir(parents=True, exist_ok=True)

    if source is None:
        urllib.request.urlretrieve(GOOGLE_DOC_EXPORT_URL, destination)
    else:
        source = source.expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"DOCX export not found: {source}")
        if source != destination.resolve():
            shutil.copy2(source, destination)

    return destination


def run_pandoc(docx_path: Path, work_dir: Path) -> tuple[str, Path]:
    markdown_path = work_dir / "manuscript.md"
    media_root = work_dir / "extracted"
    subprocess.run(
        [
            "pandoc",
            str(docx_path),
            "--from=docx",
            "--to=gfm",
            "--wrap=none",
            f"--extract-media={media_root}",
            "--output",
            str(markdown_path),
        ],
        check=True,
    )
    return markdown_path.read_text(encoding="utf-8"), media_root


def find_extracted_assets(media_root: Path) -> dict[str, Path]:
    extracted = {path.name: path for path in media_root.rglob("image*.png")}
    expected = set(ASSET_BY_SOURCE)
    missing = expected - set(extracted)
    unexpected = set(extracted) - expected
    if missing or unexpected:
        raise RuntimeError(
            "Google Doc media set changed; update FIGURE_ASSETS before importing. "
            f"Missing: {sorted(missing)}; unexpected: {sorted(unexpected)}"
        )
    return extracted


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_other_studies_rows() -> list[list[str]]:
    provenance = json.loads(
        OTHER_STUDIES_PROVENANCE_PATH.read_text(encoding="utf-8")
    )
    if sha256(OTHER_STUDIES_PATH) != provenance["vendored_sha256"]:
        raise RuntimeError("Other-studies table checksum does not match its provenance.")
    with OTHER_STUDIES_PATH.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.reader(stream))
    if len(rows) != provenance["rows"]:
        raise RuntimeError("Other-studies table row count does not match its provenance.")
    if not rows or any(len(row) != provenance["columns"] for row in rows):
        raise RuntimeError("Other-studies table column count does not match its provenance.")
    if rows[0][0] != "Publication":
        raise RuntimeError("Other-studies table must begin with a Publication header.")
    return rows


def copy_assets(extracted: dict[str, Path], export_date: str) -> None:
    output_dir = REPO_ROOT / "images" / "figures" / "imported"
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_assets = []
    derived = json.loads(
        DERIVED_FIGURE_PROVENANCE_PATH.read_text(encoding="utf-8")
    )["assets"]

    for asset in FIGURE_ASSETS:
        destination = output_dir / asset.filename
        source = extracted[asset.source_name]
        source_kind = "google-doc-rendered-png"
        editable_source_url = None
        source_metadata = {}
        if asset.source_name == "image12.png":
            provenance = json.loads(
                FIGURE_1_PROVENANCE_PATH.read_text(encoding="utf-8")
            )
            illustrator_source = REPO_ROOT / provenance["source_path"]
            source = REPO_ROOT / provenance["rendered_path"]
            if sha256(illustrator_source) != provenance["source_sha256"]:
                raise RuntimeError("Figure 1 Illustrator checksum mismatch.")
            if sha256(source) != provenance["rendered_sha256"]:
                raise RuntimeError("Figure 1 rendered checksum mismatch.")
            source_kind = "illustrator-rendered-png"
            editable_source_url = provenance["source_url"]
            source_metadata = {
                "replacement_source_path": provenance["rendered_path"],
                "source_asset_path": provenance["source_path"],
                "source_asset_sha256": provenance["source_sha256"],
                "replaces_google_doc_source": asset.source_name,
            }
        elif asset.source_name in derived:
            crop = derived[asset.source_name]
            if sha256(source) != crop["source_sha256"]:
                raise RuntimeError(
                    f"{asset.source_name} checksum changed; regenerate its approved crop."
                )
            source = REPO_ROOT / crop["output_path"]
            if sha256(source) != crop["sha256"]:
                raise RuntimeError(
                    f"Derived crop checksum mismatch for {asset.source_name}."
                )
            source_kind = "google-doc-derived-crop"
            source_metadata = {
                "replacement_source_path": crop["output_path"],
                "crop_box_px": crop["crop_box_px"],
                "replaces_google_doc_source": asset.source_name,
            }
        if asset.source_name == "image14.png":
            provenance = json.loads(SLIDE_15_PROVENANCE_PATH.read_text(encoding="utf-8"))
            if sha256(SLIDE_15_SOURCE_PATH) != provenance["sha256"]:
                raise RuntimeError("Slide 15 checksum does not match its provenance record.")
            source = SLIDE_15_SOURCE_PATH
            source_kind = "google-slides-rendered-png"
            editable_source_url = provenance["source_url"]
            source_metadata = {
                "replacement_source_path": source.relative_to(REPO_ROOT).as_posix(),
                "replacement_export_url": provenance["export_url"],
                "replaces_google_doc_source": asset.source_name,
            }
        shutil.copy2(source, destination)
        manifest_assets.append(
            {
                **asdict(asset),
                "path": destination.relative_to(REPO_ROOT).as_posix(),
                "sha256": sha256(destination),
                "source_kind": source_kind,
                "editable_source_url": editable_source_url,
                **source_metadata,
            }
        )

    manifest = {
        "version": 1,
        "source_document": GOOGLE_DOC_URL,
        "source_export": GOOGLE_DOC_EXPORT_URL,
        "export_date": export_date,
        "assets": manifest_assets,
    }
    manifest_path = REPO_ROOT / "figure_sources" / "google-doc" / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def render_figure(source_name: str) -> str:
    if source_name == "image9.png":
        return render_mesoscope_laser_power_table()
    if source_name == "image6.png":
        return BEHAVIOR_VIEWER_BLOCK

    asset = ASSET_BY_SOURCE[source_name]
    if asset.status == "removed":
        return ""
    path = f"./images/figures/imported/{asset.filename}"
    supplementary_option = ""
    caption = asset.caption
    if asset.supplementary_number is not None:
        supplementary_option = ":enumerated: false\n"
        caption = (
            f"**Supplementary Figure {asset.supplementary_number}.** {asset.caption}"
        )
    figure = (
        f":::{'{'}figure{'}'} {path}\n"
        f":label: {asset.label}\n"
        f":alt: {asset.alt}\n"
        f"{supplementary_option}"
        ":width: 100%\n\n"
        f"{caption}\n"
        ":::"
    )
    return figure


def render_mesoscope_laser_power_table() -> str:
    with MESOSCOPE_LASER_POWER_PATH.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))

    lines = [
        (
            "Laser power was selected from the "
            "[depth-dependent lookup ranges](#table-mesoscope-laser-power)."
        ),
        "",
        ":::{table} Mesoscope laser power lookup ranges by imaging depth.",
        ":label: table-mesoscope-laser-power",
        ":enumerated: false",
        ":class: table-accent table-compact table-laser-power table-hover-source",
        "",
        "| Depth from surface (µm) | Minimum power (mW) | Maximum power (mW) |",
        "| ---: | ---: | ---: |",
    ]
    for row in rows:
        depth = f"{row['depth_min_um']}-{row['depth_max_um']}"
        lines.append(
            f"| {depth} | {row['laser_power_min_mw']} | {row['laser_power_max_mw']} |"
        )
    lines.append(":::")
    return "\n".join(lines)


def normalize_imported_html_table(table_html: str) -> str:
    table = ET.fromstring(table_html)
    table_text = " ".join("".join(table.itertext()).split())
    if "Predictive processing experiment tables" not in table_text:
        return table_html

    table_kind = "sessions" if "List of sessions" in table_text else "animals"
    table.set("class", f"publication-data-table table-{table_kind}")
    table.set("data-table-kind", table_kind)
    head = table.find("thead")
    body = table.find("tbody")
    if head is None:
        return table_html
    if body is None:
        body = ET.SubElement(table, "tbody")

    rows = list(head.findall("tr"))
    for row in rows[2:]:
        head.remove(row)
        first_cell_text = " ".join("".join(row[0].itertext()).lower().split())
        modality = "other"
        if "two-photon" in first_cell_text or "mesoscope" in first_cell_text:
            modality = "mesoscope"
            row.set("class", "modality-mesoscope")
        elif "neuropixels" in first_cell_text:
            modality = "neuropixels"
            row.set("class", "modality-neuropixels")
        elif "slap2" in first_cell_text:
            modality = "slap2"
            row.set("class", "modality-slap2")
        row.set("data-modality", modality)
        if table_kind == "sessions":
            context = " ".join("".join(row[1].itertext()).lower().split())
            row.set("data-context", context)
        for cell in row:
            if cell.tag == "th":
                cell.tag = "td"
            cell.set("style", "text-align: left;")
        collapse_identifier_cell(row[-1], table_kind)
        body.append(row)

    ET.indent(table, space="  ")
    return ET.tostring(table, encoding="unicode", method="xml")


def collapse_identifier_cell(cell: ET.Element, table_kind: str) -> None:
    full_value = " ".join("".join(cell.itertext()).split())
    identifiers = [value.strip() for value in full_value.split(",") if value.strip()]
    label = "mouse IDs" if table_kind == "animals" else "sessions"
    cell.set("data-full-value", full_value)
    cell.text = None
    for child in list(cell):
        cell.remove(child)

    details = ET.SubElement(cell, "details", {"class": "id-disclosure"})
    summary = ET.SubElement(details, "summary")
    summary.text = f"{len(identifiers)} {label}"
    identifier_list = ET.SubElement(details, "div", {"class": "id-list"})
    identifier_list.text = full_value


def replace_images(markdown: str) -> str:
    lines: list[str] = []
    for line in markdown.splitlines():
        heading_match = HEADING_IMAGE_PATTERN.match(line)
        if heading_match:
            lines.extend(
                [
                    render_figure(heading_match.group("name")),
                    "",
                    f"{heading_match.group('hashes')} {heading_match.group('title').strip()}",
                ]
            )
            continue

        line = IMAGE_PATTERN.sub(
            lambda match: f"\n\n{render_figure(match.group('name'))}\n\n", line
        )
        lines.append(line)

    return "\n".join(lines)


def normalize_text_export_artifacts(markdown: str) -> str:
    replacements = {
        (
            "[<u>(de Vries et al. 2020; Groblewski et al. 2020; "
            "Durand et al. 2023; Bennett et al. 2024; Siegle et al. 2021</u>]"
            "(https://paperpile.com/c/tTM80k/1eyg+Yunn+PAsB+xhvZ+yxs4).."
        ): (
            "[(de Vries et al. 2020; Groblewski et al. 2020; "
            "Durand et al. 2023; Bennett et al. 2024; Siegle et al. 2021)]"
            "(https://paperpile.com/c/tTM80k/1eyg+Yunn+PAsB+xhvZ+yxs4)."
        ),
        (
            "<u>[(](https://paperpile.com/c/tTM80k/ZAyJ)"
            "[Madisen et al. 2012](https://paperpile.com/c/tTM80k/2W65)</u>, "
            "<u>[Taniguchi et al. 2011](https://paperpile.com/c/tTM80k/ZAyJ)"
            "[)](https://paperpile.com/c/tTM80k/2W65)</u>"
        ): (
            "([Madisen et al. 2012](https://paperpile.com/c/tTM80k/2W65); "
            "[Taniguchi et al. 2011](https://paperpile.com/c/tTM80k/ZAyJ))"
        ),
        (
            "[<u>(Siegle et al. 2021; Durand et al. 2023)</u>.]"
            "(https://paperpile.com/c/tTM80k/yxs4+PAsB)"
        ): (
            "[(Siegle et al. 2021; Durand et al. 2023)]"
            "(https://paperpile.com/c/tTM80k/yxs4+PAsB)."
        ),
        (
            "[L](https://www.sciencedirect.com/topics/neuroscience/"
            "local-field-potential)ocal Field Potential"
        ): (
            "[Local Field Potential](https://www.sciencedirect.com/topics/"
            "neuroscience/local-field-potential)"
        ),
        (
            "[<u>(aind-ephys-pipeline: AIND pipeline fo...)</u>]"
            "(https://paperpile.com/c/tTM80k/hLaJ)"
        ): "[AIND ephys pipeline](https://paperpile.com/c/tTM80k/hLaJ)",
        r"\autocite{noauthor_allenneuraldynamicsgiant-matlab_2026}": (
            "[AllenNeuralDynamics/GIAnT-MATLAB (2026)]"
            "(https://github.com/AllenNeuralDynamics/GIAnT-MATLAB)"
        ),
        r"~\autocite{pnevmatikakis_normcorre_2017}": " (Pnevmatikakis & Giovannucci, 2017)",
        r"~\autocite{lelek_single-molecule_2021, chen_imaging_2025}": (
            " (Lelek et al., 2021; Chen et al., 2025)"
        ),
        r"\$1.33\$~pixels": r"$1.33$ pixels",
        r"\$\tau = 20\$ms": r"$\tau = 20$ ms",
        r"\textit{activity image}": "*activity image*",
        "with with": "with",
        "Neuropixels node**s**": "Neuropixels nodes",
        "**Supplementary** **Fig. X**": "**Supplementary Fig. X**",
        "**Supplementary** **Table 1**": "**Supplementary Table 1**",
        "**Supplementary Fig. X)**": "**Supplementary Fig. X**",
        "quality_control.json ,rig.json": "quality_control.json, rig.json",
        "rig.json,session.json": "rig.json, session.json",
        "ITI<sub>min</sub> , ITI<sub>max</sub>": "ITI<sub>min</sub>, ITI<sub>max</sub>",
        "pipeline\n\n(aind-pophys-pipeline v11 and v13;\n\n": (
            "pipeline (aind-pophys-pipeline v11 and v13; "
        ),
        ")\n\nand the same two input files": ") and the same two input files",
        (
            r"> i\. R(downward, 90° shift) \> R(45° shift),"
            "\\\n"
            "> because this is a bigger change in orientation\n"
            ">\n"
            r"> ii\. R(halt) \< R(90°) and R(45°), because the halt involves "
            "a smaller change in velocity"
        ): (
            "  1. R(downward, 90° shift) > R(45° shift), because this is a "
            "bigger change in orientation\n\n"
            "  2. R(halt) < R(90°) and R(45°), because the halt involves a "
            "smaller change in velocity"
        ),
    }
    for old, new in replacements.items():
        markdown = markdown.replace(old, new)

    markdown = re.sub(
        r"\[<u>([^\n]*?)</u>\]\(([^\n]+?)\)",
        r"[\1](\2)",
        markdown,
    )
    markdown = re.sub(
        r"<u>(https?://[^<\s]+)</u>",
        r"[\1](\1)",
        markdown,
    )
    markdown = markdown.replace(
        "\n> The default configuration used Suite2p",
        "\n  The default configuration used Suite2p",
    )
    markdown = re.sub(
        r"\n\n> (\(\[[^\n]+\]\(https?://[^\n]+\)\))",
        r" \1",
        markdown,
    )
    markdown = re.sub(r"\n\n(?=\(\[[^\n]+\]\(https?://)", " ", markdown)
    markdown = re.sub(r"\\\n  (?=\(\[)", " ", markdown)
    markdown = re.sub(r"\\(?=\n+:::\{figure\})", "", markdown)
    markdown = re.sub(r"(?m)^-\s*$\n?", "", markdown)
    markdown = re.sub(r"(?<!\.)\.\.(?!\.)", ".", markdown)
    return markdown.replace("\u200b", "").replace("\ufeff", "")


def move_interrupted_analysis_figure(markdown: str) -> str:
    pattern = re.compile(
        r"(?P<before>Simulated models will vary in complexity to evaluate our ability)"
        r"[ \t]*\n{2,}(?P<figure>:::\{figure\} .*?\n:::)\n{2,}"
        r"(?P<after>to disentangle mechanisms such as adaptation, E/I balance, "
        r"and other underlying processes\.)",
        re.DOTALL,
    )
    markdown, count = pattern.subn(
        r"\g<before> \g<after>\n\n\g<figure>",
        markdown,
        count=1,
    )
    if count != 1:
        raise RuntimeError("Expected interrupted Figure 11 paragraph was not found.")
    return markdown


def replace_supplementary_text(markdown: str) -> str:
    pattern = re.compile(r"# Supplementary Text 1:.*\Z", re.DOTALL)
    if pattern.search(markdown) is None:
        raise RuntimeError("Expected Supplementary Text 1 was not found.")
    load_other_studies_rows()
    replacement = "\n\n".join(
        [
            "# Supplementary Text 1: Published oddball paradigms and sampling ranges",
            (
                "[Supplementary Table 1](#table-supplementary-oddball-studies) "
                "compares five published visual oddball paradigms with respect to "
                "stimulus design, timing, sample size, recording method, statistical "
                "test, habituation, and sampling."
            ),
            OTHER_STUDIES_BLOCK,
            (
                "The paradigms span visuomotor decoupling and local or global "
                "deviations in visual sequences. Three studies used two-photon "
                "calcium imaging, one used local field potentials, and one used "
                "Neuropixels recordings."
            ),
            (
                "Reported oddball probabilities ranged from 0.07 to 0.20, the "
                "reported number of oddball repeats required ranged from 10 to 144, "
                "and session durations ranged from 6 minutes to 2 hours. These values "
                "provide literature context for trial-count and session-duration "
                "choices in the present dataset; differences in stimuli, response "
                "definitions, and significance tests should be considered when "
                "comparing responsive-neuron fractions across studies."
            ),
        ]
    )
    return pattern.sub(replacement, markdown, count=1)


def normalize_known_export_artifacts(markdown: str) -> str:
    replacements = {
        "# Background & Rationale ": "# Background & Rationale",
        "### Surgery & cranial window procedure2-photon calcium imaging experiments": (
            "### Surgery & cranial window procedure: two-photon calcium imaging experiments"
        ),
        "## For experiments involving simultaneous glutamate and calcium imaging": (
            "For experiments involving simultaneous glutamate and calcium imaging"
        ),
        "#### The 3D-printed protective cone was then lowered": (
            "The 3D-printed protective cone was then lowered"
        ),
        "## All data from this project are packaged as Neurodata Without Borders": (
            "All data from this project are packaged as Neurodata Without Borders"
        ),
        "SUPP figures": "## Supplementary figures",
        "shared below.Four predictive contexts": "shared below.\n\n**Four predictive contexts**",
        " (see **Figure 11**)": "",
        "\nDescription of the multi-modal animal experimentation pipelines\n": "\n",
        "\n## \n": "\n",
        "\n\\\n=\n": "\n",
    }
    for old, new in replacements.items():
        markdown = markdown.replace(old, new)

    markdown = normalize_text_export_artifacts(markdown)
    markdown = move_interrupted_analysis_figure(markdown)
    markdown = RAW_HTML_TABLE_PATTERN.sub(
        lambda match: normalize_imported_html_table(match.group()),
        markdown,
    )
    markdown = wrap_publication_data_tables(markdown)
    markdown = replace_supplementary_text(markdown)
    markdown = "\n".join(line.rstrip() for line in markdown.splitlines())
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    return markdown.strip() + "\n"


def wrap_publication_data_tables(markdown: str) -> str:
    pattern = re.compile(
        r'<table class="publication-data-table table-[^"]+".*?</table>',
        re.DOTALL,
    )
    matches = list(pattern.finditer(markdown))
    if len(matches) != 2:
        raise RuntimeError(f"Expected two publication data tables, found {len(matches)}.")
    start = matches[0].start()
    end = matches[-1].end()
    static_tables = markdown[start:end]
    replacement = "\n".join(
        [
            DATA_EXPLORER_BLOCK,
            "",
            '<div class="publication-data-source" hidden aria-hidden="true">',
            "",
            static_tables,
            "",
            "</div>",
        ]
    )
    return f"{markdown[:start]}{replacement}{markdown[end:]}"


def relocate_supplementary_implant_figure(markdown: str) -> str:
    pattern = re.compile(
        r"\n(?P<figure>:::\{figure\} [^\n]+\n"
        r":label: fig-supp-neuropixels-implant-trajectories\n.*?\n:::)\n",
        re.DOTALL,
    )
    match = pattern.search(markdown)
    if match is None:
        raise RuntimeError("Expected slide 15 implant figure was not found.")
    markdown = f"{markdown[: match.start()]}\n{markdown[match.end() :]}"
    heading = "## Supplementary figures"
    if markdown.count(heading) != 1:
        raise RuntimeError("Expected one Supplementary figures heading.")
    return markdown.replace(heading, f"{heading}\n\n{match.group('figure')}", 1)


def move_glossary_to_end(markdown: str) -> str:
    pattern = re.compile(
        r"\n## Glossary\n(?P<body>.*?)\n# Data validation\n",
        re.DOTALL,
    )
    match = pattern.search(markdown)
    if match is None:
        raise RuntimeError("Expected Glossary section before Data validation.")

    body = match.group("body").strip()
    records_heading = "#### NWB Files"
    if body.count(records_heading) != 1:
        raise RuntimeError("Expected one NWB Files subsection in the Glossary export.")
    terms, records = body.split(records_heading, maxsplit=1)
    without_glossary = "\n".join(
        [
            markdown[: match.start()].rstrip(),
            "",
            "## NWB file contents",
            "",
            records.strip(),
            "",
            "# Data validation",
            "",
            markdown[match.end() :].lstrip(),
        ]
    )
    glossary = "\n".join(
        [
            "# Glossary",
            "",
            ":::{dropdown} Terms and abbreviations",
            "",
            terms.strip(),
            ":::",
        ]
    )
    return f"{without_glossary.rstrip()}\n\n{glossary}\n"


def replace_behavior_analysis_text(markdown: str) -> str:
    draft = """## Behavioral data analysis across modalities

- Running

- Pupil

- Motion energy of the face?"""
    if markdown.count(draft) != 1:
        raise RuntimeError("Expected one draft behavioral-analysis section.")
    return markdown.replace(draft, BEHAVIOR_ANALYSIS_DESCRIPTION, 1)


def build_index(markdown: str) -> str:
    markdown = replace_images(markdown)
    markdown = normalize_known_export_artifacts(markdown)
    markdown = replace_behavior_analysis_text(markdown)
    markdown = relocate_supplementary_implant_figure(markdown)
    markdown = move_glossary_to_end(markdown)
    interactive_anchor = (
        "The order of stimuli blocks (deviant vs control blocks) were maintained "
        "across all sessions."
    )
    if markdown.count(interactive_anchor) != 1:
        raise RuntimeError("Expected interactive viewer placement anchor was not found.")
    markdown = markdown.replace(
        interactive_anchor,
        f"{interactive_anchor}\n\n{INTERACTIVE_DESIGN_BLOCK}",
        1,
    )
    background_heading = "# Background & Rationale"
    if background_heading not in markdown:
        raise RuntimeError("Expected Background & Rationale heading was not found.")
    markdown = markdown.replace(
        background_heading,
        f"{AUTHORSHIP_BLOCK}\n\n{background_heading}",
        1,
    )
    stimulus_paragraph_end = (
        "was read by the Bonsai workflow (generic_oddball.bonsai) to drive stimulus "
        "presentation in sequence."
    )
    if stimulus_paragraph_end not in markdown:
        raise RuntimeError("Expected stimulus table paragraph was not found.")
    markdown = markdown.replace(
        stimulus_paragraph_end,
        f"{stimulus_paragraph_end}\n\n{STIMULUS_PROVENANCE_BLOCK}",
        1,
    )
    return f"{FRONTMATTER}\n\n{markdown}"


def main() -> None:
    args = parse_args()
    docx_path = acquire_docx(args.docx)
    with tempfile.TemporaryDirectory(prefix="openscope-p3-import-") as temp_dir:
        markdown, media_root = run_pandoc(docx_path, Path(temp_dir))
        extracted = find_extracted_assets(media_root)
        copy_assets(extracted, args.export_date)
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(build_index(markdown), encoding="utf-8")

    print(f"Imported manuscript to {output}")
    print(f"Preserved source export at {docx_path}")


if __name__ == "__main__":
    main()