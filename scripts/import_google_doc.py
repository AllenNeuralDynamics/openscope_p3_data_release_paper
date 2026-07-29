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
        "source-only",
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

Playable stimulus viewer for the four predictive-processing recording contexts.
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

Filterable explorer for experimental animals, recording modalities, contexts,
and session identifiers.
:::"""

SUPPLEMENTARY_DEPTH_FIGURE_BLOCK = "\n".join(
    [
        ":::{figure} "
        "./images/figures/generated/supplementary-mesoscope-depth-power.svg",
        ":label: fig-supp-mesoscope-depth-power",
        (
            ":alt: Minimum and maximum mesoscope laser power ranges for imaging "
            "depths from the cortical surface to 600 micrometers."
        ),
        ":width: 82%",
        "",
        (
            "Mesoscope laser-power lookup ranges used to guide imaging settings "
            "across cortical depth. Values are generated from the structured CSV "
            "used by the Methods table."
        ),
        ":::",
    ]
)

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
    if source_name == "image9.png":
        return render_mesoscope_laser_power_table()

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


def render_mesoscope_laser_power_table() -> str:
    with MESOSCOPE_LASER_POWER_PATH.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))

    lines = [
        ":::{table} Mesoscope laser power lookup ranges by imaging depth.",
        ":label: table-mesoscope-laser-power",
        ":enumerated: false",
        ":class: table-accent table-compact table-laser-power",
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


def replace_incomplete_supplementary_table(markdown: str) -> str:
    pattern = re.compile(r"^\| Publication \|\n(?:^\|.*\|\n?)+", re.MULTILINE)
    match = pattern.search(markdown)
    if match is None:
        raise RuntimeError("Expected incomplete Supplementary Table 1 was not found.")

    fields = []
    for line in match.group().splitlines():
        value = line.removeprefix("|").removesuffix("|").strip()
        if value == "----" or value.startswith("**Supplementary Table 1."):
            continue
        fields.append(value)

    warning = "\n".join(
        [
            ":::{warning} Supplementary table needs a source export",
            "The DOCX export retained the row labels but not the study columns for ",
            "Supplementary Table 1. Replace this shell with a CSV or another structured ",
            "source before submission.",
            "",
            f"Recovered row labels: {'; '.join(fields)}.",
            ":::",
        ]
    )
    markdown = f"{markdown[: match.start()]}{markdown[match.end() :]}"
    interrupted_sentence = re.compile(
        r"(The resulting curve revealed diminishing returns in detection rates beyond)"
        r"\s*\n+\s*(a certain number of trials)"
    )
    markdown, count = interrupted_sentence.subn(r"\1 \2", markdown, count=1)
    if count != 1:
        raise RuntimeError("Expected interrupted supplementary paragraph was not found.")

    warning_anchor = "required more repeats."
    if markdown.count(warning_anchor) != 1:
        raise RuntimeError("Expected Supplementary Table 1 warning anchor was not found.")
    return markdown.replace(warning_anchor, f"{warning_anchor}\n\n{warning}", 1)


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

    markdown = normalize_text_export_artifacts(markdown)
    markdown = move_interrupted_analysis_figure(markdown)
    markdown = RAW_HTML_TABLE_PATTERN.sub(
        lambda match: normalize_imported_html_table(match.group()),
        markdown,
    )
    markdown = wrap_publication_data_tables(markdown)
    markdown = replace_incomplete_supplementary_table(markdown)
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
            '<details class="static-table-fallback">',
            "<summary>View grouped static summary tables</summary>",
            "",
            static_tables,
            "",
            "</details>",
        ]
    )
    return f"{markdown[:start]}{replacement}{markdown[end:]}"


def add_supplementary_depth_figure(markdown: str) -> str:
    heading = "## Supplementary figures"
    if markdown.count(heading) != 1:
        raise RuntimeError("Expected one Supplementary figures heading.")
    return markdown.replace(
        heading,
        f"{heading}\n\n{SUPPLEMENTARY_DEPTH_FIGURE_BLOCK}",
        1,
    )


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


def build_index(markdown: str) -> str:
    markdown = replace_images(markdown)
    markdown = normalize_known_export_artifacts(markdown)
    markdown = add_supplementary_depth_figure(markdown)
    markdown = move_glossary_to_end(markdown)
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