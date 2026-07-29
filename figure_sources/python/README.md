# Python figure sources

The installable package in `src/openscope_p3_publication/` owns figures generated from Python. Build all current generated assets with:

```bash
uv run build-publication-figures
```

The experimental-design generator writes:

- `interactive/experimental-design.html`: self-contained JavaScript stimulus viewer for the MyST site.
- `images/figures/generated/experimental-design.svg`: accessible fallback for static exports.

Its structured inputs are `figure_sources/data/experimental-design-sessions.csv` and `figure_sources/data/experimental-design-blocks.csv`.
Its HTML, CSS, and JavaScript sources are under `figure_sources/javascript/`.
Pinned upstream stimulus provenance is recorded in `figure_sources/data/stimulus-viewer-sources.json`.

Keep data-loading, transformation, and rendering logic in the package. Store small figure inputs under `figure_sources/data/`; large or externally archived inputs should be represented by a manifest containing their URL, version, and checksum.