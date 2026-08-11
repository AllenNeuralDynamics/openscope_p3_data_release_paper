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
        "Experimental workflow, recording cohorts, and shared block order.",
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
            "open-loop playback, receptive-field mapping, and zebra movie."
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
FIGURE_PRESENTATION_OVERRIDES = {
    "image12.png": {
        "path": "./images/figures/generated/figure-01-overview.svg",
        "alt": (
            "Predictive-processing computations across spatial scales and the "
            "multimodal experimental workflow and context allocation used to sample them."
        ),
        "caption": (
            "Distributed predictive-processing hypotheses motivate multimodal recordings. "
            "**A,** A visual sequence establishes an expectation (blue), whereas an "
            "unexpected oddball produces a prediction-error signal (red). Predictions and "
            "errors may be expressed through reciprocal brain-wide pathways, within local "
            "cortical populations, and across the dendritic and somatic compartments of "
            "individual neurons. **B,** To sample these nested scales within one standardized "
            "project, animals progressed from surgery through intrinsic-signal-imaging mapping "
            "and habituation before recording with mesoscope two-photon imaging, Neuropixels "
            "electrophysiology, or SLAP2 dendritic imaging. **C,** Five cohort timelines show "
            "eight outlined habituation and training sessions followed by filled neural-recording "
            "sessions. Neuropixels and mesoscope sampled motor- and sequence-habituated cohorts "
            "in opposite context orders. Neuropixels sampled every context once, whereas "
            "mesoscope repeated each context twice; SLAP2 sampled the motor-habituated cohort "
            "only."
        ),
    },
    "image10.png": {
        "merged_into": "image12.png",
    },
    "image8.png": {
        "path": "./images/figures/generated/multimodal-hardware.svg",
        "alt": (
            "Neuropixels, mesoscope, and SLAP2 rig geometry, mouse platforms, "
            "and brain-targeting strategies."
        ),
        "caption": (
            "Multimodal recording hardware. Rows compare Neuropixels electrophysiology, "
            "mesoscope two-photon calcium imaging, and SLAP2 dendritic imaging. Columns show "
            "each rig geometry, the corresponding head-fixed mouse platform, and the "
            "brain-targeting strategy. Neuropixels uses six acute trajectories spanning "
            "cortical and subcortical structures; mesoscope uses eight chronic imaging planes "
            "across VISp and VISlm; and SLAP2 samples proximal and apical dendritic "
            "compartments in a layer II/III pyramidal neuron. The figure is reconstructed "
            "from nine native-resolution images extracted directly from the editable "
            "PowerPoint source."
        ),
    },
    "image5.png": {
        "path": "./images/figures/generated/figure-07-unit-extraction-plan.svg",
    },
    "image3.png": {
        "path": "./images/figures/generated/figure-08-basic-stimuli-plan.svg",
    },
    "image4.png": {
        "path": "./images/figures/generated/figure-10-standard-oddball-plan.svg",
    },
}
FIGURE_REFERENCE_REPLACEMENTS = {
    "brain fixation and brain histology (see **Figure 2**)": (
        "brain fixation and brain histology (see [Figure 1](#fig-graphical-abstract))"
    ),
    "mouse’s right eye (see **Figure 2**)": (
        "mouse’s right eye (see [Figure 1](#fig-graphical-abstract))"
    ),
    "mouse's right eye (see **Figure 2**)": (
        "mouse's right eye (see [Figure 1](#fig-graphical-abstract))"
    ),
    "six Neuropixels probes simultaneously (see **Figure 2**)": (
        "six Neuropixels probes simultaneously (see [Figure 3](#fig-multimodal-pipelines))"
    ),
    "Figure 6 and the modality subsections below remain an analysis outline.": (
        "[Figure 7](#fig-unit-extraction-plan) and the modality subsections below remain "
        "an analysis outline."
    ),
    "This analysis and Figure 7 are planning placeholders.": (
        "This analysis and [Figure 8](#fig-basic-stimuli-plan) are planning placeholders."
    ),
    "This analysis, the questions below, and Figure 9 are planning placeholders.": (
        "This analysis, the questions below, and "
        "[Figure 10](#fig-standard-oddball-plan) are planning placeholders."
    ),
}

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

INTERACTIVE_DESIGN_BLOCK = """The shared within-session architecture and
context-specific stimulus selection are summarized in
[Figure 2](#fig-interactive-experimental-design).

:::{iframe} ./interactive/experimental-design.html
:label: fig-interactive-experimental-design
:width: 100%
:title: Predictive-processing stimulus viewer
:placeholder: ./images/figures/generated/figure-02-context-controls.svg

Within-session architecture for cross-context comparison. In the **Static** view,
**A** shows the common session sequence: a standard control precedes each context
block and is repeated immediately afterward, followed by shared randomized,
duration, open-loop, receptive-field, and zebra-movie blocks. **B** details the
four contexts and the control and system-identification stimuli used to measure
context-induced changes in response properties. The **Interactive** view
mirrors panel A: select one of the four contexts from the vertical selector above
the Context block or select any shared control or system-identification block
directly. It reconstructs
contiguous rows from the pinned generated stimulus tables in their source
pseudo-randomized order, with the source trial number shown for each frame.
The Movie block plays an excerpt of the canonical zebra stimulus, and receptive-field
mapping uses the stated 120° × 95° angular projection. Sources: pinned
[example tables](https://github.com/AllenNeuralDynamics/openscope-community-predictive-processing/tree/0365ae32f0f0473320ed202b7c5d2bce6cf5df6b/code/stimulus-control/src/Mindscope/examples),
[generator](https://github.com/AllenNeuralDynamics/openscope-community-predictive-processing/blob/0365ae32f0f0473320ed202b7c5d2bce6cf5df6b/code/stimulus-control/src/Mindscope/generate_experiment_csv.py),
[Bonsai workflow](https://github.com/AllenNeuralDynamics/openscope-community-predictive-processing/blob/0365ae32f0f0473320ed202b7c5d2bce6cf5df6b/code/stimulus-control/src/Mindscope/generic_oddball.bonsai),
and public NWB intervals for
[electrophysiology](https://dandiarchive.org/dandiset/001637/draft/files) and
[mesoscope](https://dandiarchive.org/dandiset/001768/draft/files).
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

DATA_EXPLORER_BLOCK = """Animal and session coverage, recording context, and
quality-control status are summarized in
[Figure 4](#fig-recording-session-inventory).

:::{iframe} ./interactive/data-explorer.html
:label: fig-recording-session-inventory
:width: 100%
:title: Recording-session inventory and quality control across modalities
:placeholder: ./images/figures/generated/session-inventory.svg

Recording-session inventory and quality-control summary across modalities. The
**Interactive** view provides searchable, filterable tables for 39 mice and 164
manuscript session records, with expandable animal metadata and CSV export. The
**Static** view summarizes the complete worksheet inputs used by the supplied
modality plots. **A,** Neuropixels uses 62 worksheet rows to populate four
canonical context slots for each of 16 mice; red hatching denotes a missing or
failed session, and a star denotes one failed probe. **B,** Mesoscope shows all
92 chronological worksheet rows from 10 mice; red hatching denotes a failed
session. **C,** SLAP2 shows the 28 P3 worksheet rows from 8 mice; colored borders
and hatching denote partially failed motion correction, stress, sleep, or an
acquisition that stopped halfway. Across panels, indigo, teal, brown, and gold
denote sensorimotor, standard oddball, sequence, and duration sessions,
respectively. Mice are ordered by cohort; where both are present, whitespace
separates the motor-first and sequence-first groups defined in
[Figure 1C](#fig-graphical-abstract).
Repeated and aborted worksheet rows are retained in the Static view, so its rows
do not map one-to-one to the 164-record Interactive inventory.
:::"""

NEUROPIXELS_RAW_SOURCE = (
    "[ecephys_830846_2026-03-09_10-32-54]"
    "(https://open.quiltdata.com/b/aind-open-data/tree/"
    "ecephys_830846_2026-03-09_10-32-54/) "
    "([DANDI:001637](https://dandiarchive.org/dandiset/001637/draft/files))"
)
MESOSCOPE_RAW_SOURCE = (
    "[multiplane-ophys_832700_2026-01-29_11-18-09]"
    "(https://open.quiltdata.com/b/aind-open-data/tree/"
    "multiplane-ophys_832700_2026-01-29_11-18-09/) "
    "([DANDI:001768](https://dandiarchive.org/dandiset/001768/draft/files))"
)
SLAP2_RAW_SOURCE = (
    "[796630_2025-08-28_14-25-34]"
    "(https://open.quiltdata.com/b/aind-open-data/tree/"
    "796630_2025-08-28_14-25-34/) "
    "([DANDI:001424](https://dandiarchive.org/dandiset/001424/draft/files))"
)

NEURAL_VIEWER_BLOCK = f"""## Raw data across recording modalities

Representative native acquisition formats and source-backed excerpts are shown
in [Figure 5](#fig-aligned-neural-signals).

:::{{iframe}} ./interactive/neural-viewer.html
:label: fig-aligned-neural-signals
:width: 100%
:title: Raw recording excerpts across modalities
:placeholder: ./images/figures/generated/raw-neural-recordings.svg

Representative raw-data excerpts from one public session per recording modality,
shown to introduce the native acquisition formats. The **Interactive** view
supports source selection, contrast adjustment, and microscopy playback. The
microscopy contrast control applies black-referenced display gain. The
**Static** view arranges all available recordings as overlapping raw-image cards
without playback controls:
**A,** all six Neuropixels probe heatmaps stacked with CCF anatomy; **B,** all
eight mesoscope plane stills in two four-card stacks spanning VISp and VISl; and
**C,** two merged SLAP2 plane previews spanning two VISp depths (one per DMD),
with iGluSnFR4f shown in green and RCaMP3 in red.
Covered cards retain exposed labels and raw-image strips to convey the complete
acquisition scale. Static mesoscope stills are independently stretched to their
1st–99.5th max-channel percentiles. Each SLAP2 preview merges the two channels,
independently scaled to their 1st–99.5th sampled-pixel percentiles, from a
single aligned source frame without temporal averaging, then applies a
hue-preserving gamma of 0.55 for display. Neuropixels views contain
100 ms of calibrated, unaveraged 30-kHz voltage from 96 regularly spaced
contacts in the raw AP acquisition stream supplied to spike sorting; the
adjacent CCF column and horizontal boundaries identify each contact's annotated
structure or cortical layer. The displayed AP samples are not median-corrected,
so common-mode fluctuations across contacts remain visible as vertical stripes.
Mesoscope views are unprocessed 512 × 512 ScanImage channel frames. SLAP2 views
map native sparse detector samples onto acquisition-plan superpixels, reduce the
stored 1280 × 800 acquisition-coordinate raster by 2×, transpose it for
publication display, and encode the resulting 400 × 640 lossless WebP frames,
with the fast-scanning x axis vertical. A dim structural reference is used only outside
sampled dendritic pixels. Microscopy
playback uses elapsed time within each four-second excerpt. Selectors report CCF
structures and layers for each probe; area, layer, and depth for each mesoscope
plane; and indicator plus remote-focus depth below pia (91 µm for DMD1 and
123.75 µm for DMD2) for each SLAP2 field. Microscopy intensity is pseudocolored
and contrast-scaled independently for display. Source sessions are Neuropixels
{NEUROPIXELS_RAW_SOURCE}; mesoscope {MESOSCOPE_RAW_SOURCE};
and SLAP2
{SLAP2_RAW_SOURCE}.
:::"""

OTHER_STUDIES_BLOCK = """:::{iframe} ./interactive/literature-comparison.html
:label: table-supplementary-oddball-studies
:enumerated: false
:width: 100%
:title: Supplementary Table 1. Published oddball paradigms and sampling parameters.

**Supplementary Table 1.** Compare one paradigm parameter across all studies or inspect the complete
profile of one study. Search filters the visible records in either view, and
CSV export contains exactly the displayed subset.
:::"""

NEUROPIXELS_TRAJECTORY_BLOCK = """:::{iframe} ./interactive/neuropixels-trajectories.html
:label: fig-supp-neuropixels-recorded-trajectories
:enumerated: false
:width: 100%
:title: Supplementary Figure 3. Recorded Neuropixels trajectories in the Allen CCF.
:placeholder: ./images/figures/generated/supplementary-neuropixels-trajectories.svg

**Supplementary Figure 3.** Recorded Neuropixels trajectories in the Allen Mouse
Brain Common Coordinate Framework (CCF) 2017. The **Interactive** view renders
all CCF-localized insertions within a semi-transparent whole-brain surface and
supports mouse, probe-port, camera-orientation, and brain-opacity controls.
Selecting a trajectory shows its session, localized shank length, source NWB,
and contiguous CCF area profile from the dorsal shank end to the tip. Line color
denotes the nominal probe port (A-F). In the **Static** view, **A,** an oblique
projection shows the trajectories across the depth-shaded Allen CCF whole-brain
surface; **B,** a dorsal projection shows their anteroposterior and mediolateral
distribution. Both panels use a semi-transparent brain surface, anatomical
direction markers, and calibrated 2 mm scale bars; the trajectories extend
laterally toward the L direction marker, matching the stereotaxic mediolateral
convention. Electrode coordinates and area annotations come from the public draft
of Dandiset 001637; the brain
surface is a 100-micrometer mesh derived from the Allen CCF 2017 25-micrometer
annotation volume. In total, 332 probe
trajectories from 57 sessions and 16 mice had finite CCF coordinates. Three of
the 60 source sessions are excluded because their NWB electrode tables lack
`x`, `y`, and `z` coordinates.
:::"""

SEGMENTATION_VIEWER_BLOCK = """Representative unit-extraction filters and matched
activity traces are shown in [Figure 6](#fig-segmentation-viewers).

:::{iframe} ./interactive/segmentation-viewer.html
:label: fig-segmentation-viewers
:width: 100%
:title: Unit extraction across recording modalities
:placeholder: ./images/figures/generated/figure-06-segmentation-viewers.svg

Unit extraction filters and matched activity across recording modalities.
Modality tabs use the same platform logos as the other multimodal figures, and
the source selector switches among every probe or imaging plane in one
representative session. The tabs use the same representative sessions as the
raw-data view in [Figure 5](#fig-aligned-neural-signals) and derive their
filters and traces from the matched public NWBs. The **Neuropixels** tab
provides all six probes from `ecephys_830846_2026-03-09_10-32-54`. Each source displays
100 ms of unaveraged AP voltage with sorted-spike detections overlaid at their
spike times and nearest displayed peak channels; common-mode correction is
enabled by default and can be toggled to reveal the uncorrected samples.
Selecting a marker or unit highlights its depth and waveform-spread band and
shows a 12 s binned-rate trace plus its peak-channel mean template. The
**Mesoscope** tab provides all eight VISp and VISl planes from
`multiplane-ophys_832700_2026-01-29_11-18-09`,
outlining each plane's complete NWB segmentation over a grayscale average
projection; selection reveals classification probabilities, footprint geometry,
and a 30 s ΔF/F (%) trace. The **SLAP2** tab provides DMD1 and DMD2 from
`SLAP2_796630_2025-08-28-14-25-34`, outlining each plane's complete source
segmentation over a grayscale mean image; its column-major stored (x, y) arrays
and masks receive the same publication-level axis transpose. Mesoscope
projections retain their stored display orientation. The fast-scanning x axis
is horizontal for mesoscope and vertical for SLAP2. SLAP2 selection
reveals a 30 s, approximately 200 Hz ΔF/F (%) trace. Microscopy background controls alter only
grayscale image intensity, while filter colors remain fixed. No tab shows
stimulus annotations. The stacked static fallback preserves one representative
source per modality and shows twenty activity-bearing filters sampled evenly across
filter order as vertically stacked traces with shared within-modality scales.
Data come from the public drafts of
[DANDI:001637](https://dandiarchive.org/dandiset/001637/draft/files),
[DANDI:001768](https://dandiarchive.org/dandiset/001768/draft/files), and
[DANDI:001424](https://dandiarchive.org/dandiset/001424/draft/files).
:::"""

MAIN_FIGURE_PROMOTION_REPLACEMENTS = {
    "./images/figures/generated/figure-06-unit-extraction-plan.svg": (
        "./images/figures/generated/figure-07-unit-extraction-plan.svg"
    ),
    "./images/figures/generated/figure-07-basic-stimuli-plan.svg": (
        "./images/figures/generated/figure-08-basic-stimuli-plan.svg"
    ),
    "./images/figures/generated/figure-09-standard-oddball-plan.svg": (
        "./images/figures/generated/figure-10-standard-oddball-plan.svg"
    ),
    "[Figure 6](#fig-unit-extraction-plan)": "[Figure 7](#fig-unit-extraction-plan)",
    "[Figure 7](#fig-basic-stimuli-plan)": "[Figure 8](#fig-basic-stimuli-plan)",
    "[Figure 8](#fig-behavior-tracking)": "[Figure 9](#fig-behavior-tracking)",
    "[Figure 9](#fig-standard-oddball-plan)": (
        "[Figure 10](#fig-standard-oddball-plan)"
    ),
}

NWB_ACCESS_INTRO = """All data from this project are packaged as Neurodata
Without Borders (NWB) files and deposited on the DANDI Archive. Neuropixels
electrophysiology sessions are available at
[DANDI:001637](https://dandiarchive.org/dandiset/001637), mesoscope two-photon
imaging sessions at [DANDI:001768](https://dandiarchive.org/dandiset/001768),
and SLAP2 dendritic-imaging sessions at
[DANDI:001424](https://dandiarchive.org/dandiset/001424). Use the tabs below"""

SLAP2_NWB_TAB = "\n".join(
    [
        ":::{tab-item} SLAP2",
        "",
        (
            "**SLAP2 NWB files "
            "([DANDI:001424](https://dandiarchive.org/dandiset/001424)):**"
        ),
        "connect source masks, mean and activity images, and fluorescence traces within",
        "each DMD imaging path.",
        "",
        "| Question | NWB contents | Representative PyNWB entry point |",
        "| --- | --- | --- |",
        (
            "| Where and how was each DMD path imaged? | `/general/optophysiology` "
            "describes the DMD1 and DMD2 imaging planes, optical channels, device, "
            "indicator, and field geometry. | `nwbfile.imaging_planes`, "
            "`nwbfile.devices` |"
        ),
        (
            "| Which pixels belong to each extracted source? | `/processing/ophys/"
            "ImageSegmentation/PlaneSegmentation_DMD*` stores one weighted `pixel_mask` "
            "per source. | `nwbfile.processing[\"ophys\"][\"ImageSegmentation\"]` |"
        ),
        (
            "| What source and structural images are available? | `/processing/ophys/"
            "DMD*_mean_image_channel*` stores mean channel images, and "
            "`DMD*_activity_image` stores the source-localization activity projection. | "
            "`nwbfile.processing[\"ophys\"][\"DMD1_activity_image\"]` |"
        ),
        (
            "| How does each source change over time? | `/processing/ophys/"
            "Fluorescence_DMD*/DMD*_dFF` stores source ΔF/F with timestamps; the "
            "corresponding `DMD*_F0` series stores baseline fluorescence. | "
            "`nwbfile.processing[\"ophys\"][\"Fluorescence_DMD1\"]"
            "[\"DMD1_dFF\"]` |"
        ),
        "",
        ":::",
    ]
)

BEHAVIOR_VIEWER_BLOCK = """:::{iframe} ./interactive/behavior-viewer.html
:label: fig-behavior-tracking
:width: 100%
:title: Synchronized behavior, locomotion, and visual stimuli across recording modalities
:placeholder: ./images/figures/generated/synchronized-behavior.svg

Synchronized behavior and running across recording modalities. **A–C,** Camera
views and complete-session running profiles from representative Neuropixels
(**A**), mesoscope (**B**), and SLAP2 (**C**) sessions. Each row pairs all
available camera views with the running profile from the same mouse and source
session. Neuropixels and mesoscope stills retain the common 8-second synchronized
excerpt selection; the SLAP2 stills are sampled at 600 seconds from the
full-session profile source. Five-second profile means share one time axis and
are shown over measured standard, context, standard-repeat, sequence, jitter,
open-loop, natural-movie, and receptive-field block boundaries using the Figure
2 block colors. **D,** Mean forward running speed in each protocol block for
Neuropixels, mesoscope, and SLAP2, compared on one shared cm/s axis. Each point is
one mouse after averaging its available complete sessions, and each bar is the
mean across mice for its modality; legend values report included mice. The
**Interactive** view provides synchronized camera playback, running signals,
and reconstructed stimulus state for the selected modality. Metrics use
50 ms bins, and negative velocity is set to zero before summarization. SLAP2 encoder values
are converted to cm/s using the pinned
acquisition convention of 8192 counts/revolution, an 8.255 cm disc radius, and a
2/3 effective running radius. Each static camera image is
independently illuminated using its 1st–99th luminance percentiles and a bounded
gamma that maps median luminance to 35%, with exact parameters retained in
provenance. Behavior-camera video is
range-streamed from the public
`aind-open-data` S3 bucket. For Neuropixels and mesoscope sessions, NWB running
speed and stimulus rows share the sync-file clock with 100-kHz camera
exposure/readout edges; reported dropped frames are removed before mapping
hardware frame indices to MP4 presentation time. SLAP2 camera frames use
per-frame Harp timestamps on the acquisition clock. Camera and source selectors
expose the underlying public data without bundling multi-gigabyte videos into
the publication.
:::"""

BEHAVIOR_ANALYSIS_DESCRIPTION = """## Behavioral data analysis across modalities

For sessions with camera acquisition, the release includes continuous raw
behavioral videos together with synchronized running-wheel signals, processed
eye-tracking outputs, and stimulus-presentation intervals. Depending on the
recording platform, the available views include body or behavior, face, eye,
and nose cameras. The synchronized multimodal examples in
[Figure 9](#fig-behavior-tracking) show these streams alongside the wheel signal and
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
    presentation = FIGURE_PRESENTATION_OVERRIDES.get(source_name, {})
    if presentation.get("merged_into"):
        return ""
    path = presentation.get("path", f"./images/figures/imported/{asset.filename}")
    supplementary_option = ""
    caption = presentation.get("caption", asset.caption)
    alt = presentation.get("alt", asset.alt)
    if asset.supplementary_number is not None:
        supplementary_option = ":enumerated: false\n"
        caption = (
            f"**Supplementary Figure {asset.supplementary_number}.** {asset.caption}"
        )
    figure = (
        f":::{'{'}figure{'}'} {path}\n"
        f":label: {asset.label}\n"
        f":alt: {alt}\n"
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


def normalize_figure_references(markdown: str) -> str:
    for old, new in FIGURE_REFERENCE_REPLACEMENTS.items():
        markdown = markdown.replace(old, new)
    return markdown


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
        "shared below.Four predictive contexts": (
            "shared below. This cross-modality allocation is summarized in "
            "[Figure 1C](#fig-graphical-abstract).\n\n**Four predictive contexts**"
        ),
        " (see **Figure 11**)": "",
        "\nDescription of the multi-modal animal experimentation pipelines\n": "\n",
        "\n## \n": "\n",
        "\n\\\n=\n": "\n",
    }
    for old, new in replacements.items():
        markdown = markdown.replace(old, new)

    markdown = normalize_figure_references(markdown)
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


def add_neuropixels_trajectory_figure(markdown: str) -> str:
    heading = "# Supplementary Text 1: Published oddball paradigms and sampling ranges"
    if markdown.count(heading) != 1:
        raise RuntimeError("Expected one Supplementary Text 1 heading.")
    if "fig-supp-neuropixels-recorded-trajectories" in markdown:
        return markdown
    return markdown.replace(
        heading,
        f"{NEUROPIXELS_TRAJECTORY_BLOCK}\n\n{heading}",
        1,
    )


def add_segmentation_viewer_figures(markdown: str) -> str:
    heading = "## Units extraction"
    if markdown.count(heading) != 1:
        raise RuntimeError("Expected one Units extraction heading.")
    if ":label: fig-segmentation-viewers\n" in markdown:
        return markdown
    legacy_pattern = re.compile(
        r"\n:::\{iframe\} \./interactive/segmentation-viewer\.html\n"
        r":label: fig-supp-segmentation-viewers\n.*?\n:::\n",
        re.DOTALL,
    )
    markdown, legacy_count = legacy_pattern.subn("\n", markdown)
    if legacy_count > 1:
        raise RuntimeError("Expected at most one legacy segmentation viewer figure.")
    legacy_description_pattern = re.compile(
        r"Representative extraction filters and their matched activity traces can be\s+"
        r"inspected together in\s+"
        r"\[Supplementary Figure 5\]\(#fig-supp-segmentation-viewers\)\. Its "
        r"Neuropixels,\s+Mesoscope, and SLAP2 tabs use the same representative "
        r"sessions as the raw-data\s+view in "
        r"\[Figure 5\]\(#fig-aligned-neural-signals\) and derive their filters and\s+"
        r"traces from the matched public NWBs\."
    )
    markdown, description_count = legacy_description_pattern.subn("", markdown)
    if description_count > 1:
        raise RuntimeError("Expected at most one legacy segmentation viewer link.")
    for old, new in MAIN_FIGURE_PROMOTION_REPLACEMENTS.items():
        markdown = markdown.replace(old, new)
    return markdown.replace(
        heading,
        f"{heading}\n\n{SEGMENTATION_VIEWER_BLOCK}",
        1,
    )


def add_slap2_nwb_contents(markdown: str) -> str:
    heading = "## NWB file contents"
    end_heading = "# Data validation"
    if markdown.count(heading) != 1 or markdown.count(end_heading) != 1:
        raise RuntimeError("Expected one NWB contents and Data validation heading.")
    start = markdown.index(heading)
    stop = markdown.index(end_heading, start)
    section = markdown[start:stop]
    intro_pattern = re.compile(
        r"All data from this project are packaged as Neurodata\s+Without Borders.*?"
        r"Use the tabs below",
        re.DOTALL,
    )
    section, count = intro_pattern.subn(NWB_ACCESS_INTRO, section, count=1)
    if count != 1:
        raise RuntimeError("Expected one NWB access introduction.")
    if ":::{tab-item} SLAP2" not in section:
        closing = section.rfind("\n::::")
        if closing < 0:
            raise RuntimeError("Expected the NWB tab-set closing fence.")
        section = f"{section[:closing]}\n{SLAP2_NWB_TAB}\n{section[closing:]}"
    return f"{markdown[:start]}{section}{markdown[stop:]}"


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


def relocate_multimodal_pipeline_figure(markdown: str) -> str:
    methods_heading = "# Methods"
    figure_label = ":label: fig-multimodal-pipelines"
    section_heading = "## Multimodal recording hardware"
    if markdown.count(methods_heading) != 1 or markdown.count(figure_label) != 1:
        raise RuntimeError("Expected one Methods heading and multimodal pipeline figure.")
    methods_index = markdown.index(methods_heading)
    label_index = markdown.index(figure_label)
    if label_index < methods_index:
        if markdown.count(section_heading) != 1:
            raise RuntimeError("Visible multimodal pipeline figure lacks its heading.")
        return markdown
    figure_start = markdown.rfind(":::{figure}", methods_index, label_index)
    figure_end = markdown.find("\n:::", label_index)
    if figure_start < 0 or figure_end < 0:
        raise RuntimeError("Multimodal pipeline figure block is malformed.")
    figure_end += len("\n:::")
    figure = markdown[figure_start:figure_end]
    without_figure = (
        f"{markdown[:figure_start].rstrip()}\n\n{markdown[figure_end:].lstrip()}"
    )
    visible_section = f"{section_heading}\n\n{figure}\n\n{methods_heading}"
    return without_figure.replace(methods_heading, visible_section, 1)


def wrap_methods_dropdown(markdown: str) -> str:
    methods_heading = "# Methods"
    records_heading = "# Data records"
    if markdown.count(methods_heading) != 1 or markdown.count(records_heading) != 1:
        raise RuntimeError("Expected one Methods and one Data records heading.")
    methods_start = markdown.index(methods_heading) + len(methods_heading)
    records_start = markdown.index(records_heading)
    if methods_start >= records_start:
        raise RuntimeError("Methods must precede Data records.")
    methods_body = markdown[methods_start:records_start].strip()
    if methods_body.startswith("::::{dropdown} Show complete Methods"):
        return markdown
    wrapped = "\n".join(
        [
            methods_heading,
            "",
            "::::{dropdown} Show complete Methods",
            ":class: manuscript-methods-dropdown",
            "",
            methods_body,
            "::::",
            "",
        ]
    )
    return f"{markdown[: markdown.index(methods_heading)]}{wrapped}{markdown[records_start:]}"


def build_index(markdown: str) -> str:
    markdown = replace_images(markdown)
    markdown = normalize_known_export_artifacts(markdown)
    markdown = replace_behavior_analysis_text(markdown)
    markdown = relocate_supplementary_implant_figure(markdown)
    markdown = add_neuropixels_trajectory_figure(markdown)
    markdown = add_segmentation_viewer_figures(markdown)
    markdown = move_glossary_to_end(markdown)
    markdown = add_slap2_nwb_contents(markdown)
    data_validation_heading = "# Data validation"
    if markdown.count(data_validation_heading) != 1:
        raise RuntimeError("Expected one Data validation heading.")
    markdown = markdown.replace(
        data_validation_heading,
        f"{data_validation_heading}\n\n{NEURAL_VIEWER_BLOCK}",
        1,
    )
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
    markdown = relocate_multimodal_pipeline_figure(markdown)
    markdown = wrap_methods_dropdown(markdown)
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