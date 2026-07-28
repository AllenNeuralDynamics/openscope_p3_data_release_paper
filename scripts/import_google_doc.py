from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

GOOGLE_DOC_ID = "1A4aj5E1jsv-XihPt2_6K0TKMnwvtiMAFau3qJUcOV-I"
GOOGLE_DOC_URL = f"https://docs.google.com/document/d/{GOOGLE_DOC_ID}/edit"
GOOGLE_DOC_EXPORT_URL = (
    f"https://docs.google.com/document/d/{GOOGLE_DOC_ID}/export?format=docx"
)
REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class FigureAsset:
    source_name: str
    filename: str
    label: str
    alt: str
    caption: str
    status: str = "draft"


FIGURE_ASSETS = (
    FigureAsset(
        "image12.png",
        "figure-01-graphical-abstract.png",
        "fig-graphical-abstract",
        "Predictive processing across brain-wide, local-circuit, and single-cell scales.",
        "Graphical overview of predictive processing across spatial scales.",
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
            "Experimental design across cohorts, recording modalities, mismatch "
            "contexts, and control blocks."
        ),
    ),
    FigureAsset(
        "image8.png",
        "figure-03-multimodal-pipelines.png",
        "fig-multimodal-pipelines",
        (
            "Neuropixels, mesoscope, and SLAP2 pipelines from behavioral cohort "
            "through neuronal traces."
        ),
        "Multimodal experimental pipelines for Neuropixels, mesoscope, and SLAP2 recordings.",
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
        "placeholder",
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
        "figure-11-analysis-framework.png",
        "fig-analysis-framework",
        (
            "Analysis framework connecting four mismatch contexts to functional "
            "and structural metrics."
        ),
        "General framework for the cross-context analysis plan.",
    ),
    FigureAsset(
        "image9.png",
        "mesoscope-laser-power-table.png",
        "fig-mesoscope-laser-power",
        "Mesoscope laser power ranges by imaging depth from the cortical surface.",
        "Mesoscope laser power lookup table by imaging depth.",
    ),
    FigureAsset(
        "image11.png",
        "supplementary-neuropixels-targeting.png",
        "fig-supp-neuropixels-targeting",
        "Neuropixels implant hole positions, stereotaxic coordinates, diameters, and targets.",
        "Neuropixels implant geometry and intended anatomical targets.",
    ),
    FigureAsset(
        "image13.png",
        "supplementary-neuropixels-unit-yield.png",
        "fig-supp-neuropixels-unit-yield",
        "Unit yield over four recording days for three Neuropixels probes in six mice.",
        "Example Neuropixels unit yield across recording days.",
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
    ),
    FigureAsset(
        "image2.png",
        "supplementary-figure-02-power-simulation-trials.png",
        "fig-supp-power-simulation-trials",
        "Measured and simulated response distributions and detection power across trial counts.",
        "Simulation of responsive-neuron detection rate across trials.",
    ),
    FigureAsset(
        "image1.png",
        "supplementary-figure-03-power-simulation-sessions.png",
        "fig-supp-power-simulation-sessions",
        "Responsive-neuron detection rate by trial count for one to twenty simulated sessions.",
        "Simulation of responsive-neuron detection rate across sessions.",
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

AUTHORSHIP_BLOCK = """:::{authorship-explorer}
:authors: ./authors.yml
:height: 800px
:::"""

INTERACTIVE_DESIGN_BLOCK = """:::{iframe} ./interactive/experimental-design.html
:label: fig-interactive-experimental-design
:width: 100%
:title: Interactive timeline of the four predictive-processing recording sessions
:placeholder: ./images/figures/generated/experimental-design.svg

Interactive timeline showing the context-specific mismatch block and shared control
blocks in each recording session.
:::"""

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


def copy_assets(extracted: dict[str, Path], export_date: str) -> None:
    output_dir = REPO_ROOT / "images" / "figures" / "imported"
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_assets = []

    for asset in FIGURE_ASSETS:
        destination = output_dir / asset.filename
        shutil.copy2(extracted[asset.source_name], destination)
        manifest_assets.append(
            {
                **asdict(asset),
                "path": destination.relative_to(REPO_ROOT).as_posix(),
                "sha256": sha256(destination),
                "source_kind": "google-doc-rendered-png",
                "editable_source_url": None,
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
    asset = ASSET_BY_SOURCE[source_name]
    path = f"./images/figures/imported/{asset.filename}"
    figure = (
        f":::{'{'}figure{'}'} {path}\n"
        f":label: {asset.label}\n"
        f":alt: {asset.alt}\n"
        ":width: 100%\n\n"
        f"{asset.caption}\n"
        ":::"
    )
    if source_name == "image10.png":
        return f"{figure}\n\n{INTERACTIVE_DESIGN_BLOCK}"
    return figure


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
        "\nDescription of the multi-modal animal experimentation pipelines\n": "\n",
        "\n## \n": "\n",
        "\n\\\n=\n": "\n",
    }
    for old, new in replacements.items():
        markdown = markdown.replace(old, new)

    table_marker = "| Publication |\n|----|"
    table_warning = """:::{warning} Supplementary table needs a source export
The DOCX export retained the row labels but not the study columns for Supplementary
Table 1. Replace this shell with a CSV or another structured source before submission.
:::

| Publication |
|----|"""
    markdown = markdown.replace(table_marker, table_warning, 1)
    markdown = "\n".join(line.rstrip() for line in markdown.splitlines())
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    return markdown.strip() + "\n"


def build_index(markdown: str) -> str:
    markdown = replace_images(markdown)
    markdown = normalize_known_export_artifacts(markdown)
    background_heading = "# Background & Rationale"
    if background_heading not in markdown:
        raise RuntimeError("Expected Background & Rationale heading was not found.")
    markdown = markdown.replace(
        background_heading,
        f"{AUTHORSHIP_BLOCK}\n\n{background_heading}",
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