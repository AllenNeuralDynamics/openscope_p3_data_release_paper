# JavaScript figure sources

This folder contains the reviewable source for interactive publication figures. The Python publication package injects structured protocol data and inlines these files into the generated artifact under `interactive/`.

`figure_sources/data/stimulus-viewer-sources.json` pins the upstream stimulus repository revision, canonical example CSVs, generator, Bonsai workflow, movie, checksums, and DANDI locations. Compact excerpts under `figure_sources/data/stimulus-table-excerpts/` preserve contiguous source rows and their generated pseudo-random order for every displayed context and control block. The viewer renders those rows directly; recorded synchronized tables remain inside each public NWB file.

The Movie block uses the real pinned zebra stimulus excerpt and poster under `figure_sources/media/`, with source and conversion checksums recorded in `zebra-stimulus-excerpt.provenance.json`.

The stimulus viewer is split into:

- `stimulus-viewer.html`: semantic screen, session tabs, and playback controls.
- `stimulus-viewer.css`: responsive, screen-focused layout.
- `stimulus-viewer.js`: source-row playback, spherical stimulus rendering, and playback state.

The data explorer follows the same generated-asset pattern:

- `data-explorer.html`: accessible Animals/Sessions explorer structure.
- `data-explorer.css`: compact filters, sticky headers, and responsive table styling.
- `data-explorer.js`: tabs, search, filters, ID disclosure, and CSV export.

The explorer normalizes grouped manuscript rows into individual records: mouse metadata comes from the versioned worksheet snapshot in `figure_sources/data/experimental-animals.csv`, while individual session rows are expanded from the grouped session IDs in the manuscript.

Build the committed HTML and static SVG fallback with:

```bash
uv run build-publication-figures
```

Do not edit `interactive/experimental-design.html` directly; it is generated and checked for drift in CI.