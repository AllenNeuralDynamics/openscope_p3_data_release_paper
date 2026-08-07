# Python figure sources

The installable package in `src/openscope_p3_publication/` owns figures generated from Python. Build all current generated assets with:

```bash
uv run build-publication-figures
```

The experimental-design generator writes:

- `images/figures/generated/figure-01-overview.svg`: horizontal conceptual-framework and multimodal-workflow composition.
- `images/figures/generated/figure-01-panel-c-cohorts.svg`: context allocation across Neuropixels, mesoscope, and SLAP2 cohorts, embedded as Figure 1C.
- `images/figures/generated/figure-02-context-controls.svg`: static session timeline and detailed control architecture.
- `images/figures/generated/multimodal-hardware.svg`: Figure 3 rig, mouse-platform, and targeting composition built from nine checksum-verified PowerPoint PNG sources.
- `images/figures/generated/figure-07-unit-extraction-plan.svg`, `figure-08-basic-stimuli-plan.svg`, and `figure-10-standard-oddball-plan.svg`: clean wrappers around preserved draft PNGs that mask obsolete embedded figure numbers while retaining their analysis-plan content.
- `interactive/experimental-design.html`: self-contained JavaScript stimulus viewer for the MyST site.
- `images/figures/generated/experimental-design.svg`: accessible generated timeline summary.

Its structured inputs are `figure_sources/data/experimental-design-sessions.csv` and `figure_sources/data/experimental-design-blocks.csv`.
Its HTML, CSS, and JavaScript sources are under `figure_sources/javascript/`.
Pinned upstream stimulus provenance is recorded in `figure_sources/data/stimulus-viewer-sources.json`.

The record-level explorer uses `images/figures/generated/session-inventory.svg` as its static HTML view and PDF placeholder. The SVG is generated from the checksum-verified complete worksheet snapshot in `figure_sources/data/experimental-sessions.csv`; the interactive table remains the separate 164-session manuscript inventory.

The raw-data viewer uses `images/figures/generated/raw-neural-recordings.svg` as its static HTML view and PDF placeholder. It stacks six standard-library-rendered Neuropixels heatmaps with twelve checksum-verified microscopy stills from `figure_sources/media/neural-viewer-static/`.

The Neuropixels trajectory viewer uses `images/figures/generated/supplementary-neuropixels-trajectories.svg` as its static HTML view and PDF placeholder. Its Three.js view renders all CCF-localized session-probe trajectories inside a decimated Allen CCF whole-brain surface and exposes each selected insertion's contiguous area profile. Its source payload and exclusions are recorded in `figure_sources/data/neuropixels-trajectories.json` and `neuropixels-trajectories.provenance.json`.

The behavior viewer uses `images/figures/generated/synchronized-behavior.svg` as its static HTML view and PDF placeholder. It combines 10 ETag-verified camera stills with source-backed, same-session block-annotated running profiles and ordered mouse-level block means from `figure_sources/data/running-statistics.json`. The SLAP2 profile and aggregate are calibrated to cm/s with the pinned public acquisition convention.

Keep data-loading, transformation, and rendering logic in the package. Store small figure inputs under `figure_sources/data/`; large or externally archived inputs should be represented by a manifest containing their URL, version, and checksum.