# JavaScript figure sources

This folder contains the reviewable source for interactive publication figures. The Python publication package injects structured protocol data and inlines these files into the generated artifact under `interactive/`.

`figure_sources/data/stimulus-viewer-sources.json` pins the upstream stimulus repository revision, canonical example CSVs, generator, Bonsai workflow, movie, checksums, and DANDI locations. Generated examples define the protocol and schema; recorded synchronized tables remain inside each public NWB file.

The stimulus viewer is split into:

- `stimulus-viewer.html`: semantic screen, session tabs, and playback controls.
- `stimulus-viewer.css`: responsive, screen-focused layout.
- `stimulus-viewer.js`: deterministic stimulus rendering and playback state.

Build the committed HTML and static SVG fallback with:

```bash
uv run build-publication-figures
```

Do not edit `interactive/experimental-design.html` directly; it is generated and checked for drift in CI.