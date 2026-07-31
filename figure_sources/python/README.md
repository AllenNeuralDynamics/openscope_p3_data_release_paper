# Python figure sources

The installable package in `src/openscope_p3_publication/` owns figures generated from Python. Build all current generated assets with:

```bash
uv run build-publication-figures
```

The experimental-design generator writes:

- `interactive/experimental-design.html`: self-contained JavaScript stimulus viewer for the MyST site.
- `images/figures/generated/experimental-design-panel-d.png`: static panel shown by the viewer toggle and used for PDF exports.
- `images/figures/generated/experimental-design.svg`: accessible generated timeline summary.

Its structured inputs are `figure_sources/data/experimental-design-sessions.csv` and `figure_sources/data/experimental-design-blocks.csv`.
Its HTML, CSS, and JavaScript sources are under `figure_sources/javascript/`.
Pinned upstream stimulus provenance is recorded in `figure_sources/data/stimulus-viewer-sources.json`.

The record-level explorer uses `images/figures/generated/session-inventory.svg` as its static HTML view and PDF placeholder. The SVG is generated from the checksum-verified complete worksheet snapshot in `figure_sources/data/experimental-sessions.csv`; the interactive table remains the separate 164-session manuscript inventory.

The raw-data viewer uses `images/figures/generated/raw-neural-recordings.svg` as its static HTML view and PDF placeholder. It stacks six standard-library-rendered Neuropixels heatmaps with twelve checksum-verified microscopy stills from `figure_sources/media/neural-viewer-static/`.

Keep data-loading, transformation, and rendering logic in the package. Store small figure inputs under `figure_sources/data/`; large or externally archived inputs should be represented by a manifest containing their URL, version, and checksum.