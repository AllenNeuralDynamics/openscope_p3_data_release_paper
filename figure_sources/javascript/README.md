# JavaScript figure sources

This folder contains the reviewable source for interactive publication figures. The Python publication package injects structured protocol data and inlines these files into the generated artifact under `interactive/`.

`embed-auto-height.js` is shared by every generated embed. On the same-origin published site, it keeps each MyST iframe wrapper equal to the interactive root's responsive content height and updates that height when controls or tables change.

`figure-typography.css` defines the shared panel-title, section-title, body, control, metadata, and axis roles. Every generated interactive stylesheet is composed with this file, and visible text must remain at least 12 px at publication width. Static SVG generators use the matching scale in `openscope_p3_publication.figures.FIGURE_TYPE_SCALE`.

`figure_sources/data/stimulus-viewer-sources.json` pins the upstream stimulus repository revision, canonical example CSVs, generator, Bonsai workflow, movie, checksums, and DANDI locations. Compact excerpts under `figure_sources/data/stimulus-table-excerpts/` preserve contiguous source rows and their generated pseudo-random order for every displayed context and control block. The viewer renders those rows directly; recorded synchronized tables remain inside each public NWB file.

The Movie block uses the real pinned zebra stimulus excerpt and poster under `figure_sources/media/`, with source and conversion checksums recorded in `zebra-stimulus-excerpt.provenance.json`.

The stimulus viewer is split into:

- `stimulus-viewer.html`: semantic screen, Interactive/Static toggle, session tabs, and playback controls.
- `stimulus-viewer.css`: responsive, screen-focused layout.
- `stimulus-viewer.js`: source-row playback, spherical stimulus rendering, and playback state.

The data explorer follows the same generated-asset pattern:

- `data-explorer.html`: accessible Interactive/Static toggle and Animals/Sessions explorer structure.
- `data-explorer.css`: compact filters, sticky headers, and responsive table styling.
- `data-explorer.js`: tabs, search, filters, ID disclosure, and CSV export.

The explorer normalizes grouped manuscript rows into individual records: mouse metadata comes from the versioned worksheet snapshot in `figure_sources/data/experimental-animals.csv`, while individual session rows are expanded from the grouped session IDs in the manuscript.

The synchronized behavior viewer is split into:

- `behavior-viewer.html`: modality, camera, video, stimulus, and wheel-trace structure.
- `behavior-viewer.css`: publication-width and mobile layouts.
- `behavior-viewer.js`: S3 video seeking, shared playback state, stimulus reconstruction, and trace rendering.

`figure_sources/data/behavior-excerpts.json` contains compact event-centered traces and stimulus rows for one real Neuropixels, mesoscope, and SLAP2 session. Camera MP4 files are not copied into the repository; the viewer range-streams them from the public `aind-open-data` bucket. Neuropixels and mesoscope use 100-kHz camera exposure/readout edges from each raw sync file; reported dropped frame IDs are removed before hardware frame indices are mapped to the MP4 60-fps presentation timeline. SLAP2 uses the per-frame `CameraFrameTime` Harp timestamps and maps those frame indices to the MP4 30-fps timeline. Its raw example trace is calibrated at build time with the same pinned conversion used by `running-statistics.json`, so all displayed traces use cm/s. Source URLs, NWB SHA-256 values, camera ETags, and small-source SHA-256 values are included in the payload.

Figure 9's Static view embeds 10 ETag-pinned camera stills beside complete, block-annotated protocol running profiles from the same mice and sessions. It then compares mouse-level mean speed for all eight blocks and all three modalities on one shared cm/s axis. Neuropixels and mesoscope stills retain local excerpt time 8 s; matching SLAP2 stills use profile-session video time 600 s. The Interactive view retains the synchronized 16-second example and its paired control/context summary. Refresh all committed stills with `uv run --with av --with pillow python scripts/extract_behavior_static_frames.py`, or only the matching SLAP2 set with `--modality slap2`.

Regenerate the behavior payload from its public sources with:

```bash
uv run --no-project --with h5py --with harp-python==0.4.1 --with numpy --with remfile \
	python scripts/extract_behavior_excerpts.py
```

The raw neural-data viewer is split into:

- `neural-viewer.html`: Interactive/Static toggle plus modality, source, contrast, canvas, and timeline controls.
- `neural-viewer.css`: responsive publication-width raw-data viewer styling.
- `neural-viewer.js`: raw AP shaft heatmap, spritesheet movie, tooltip, and playback rendering.

Its vendored `figure_sources/data/raw-neural-excerpts.json` snapshot and WebP sheets use the same source sessions as the behavior viewer. Source windows retain synchronized event metadata for reproducibility, but the neural viewer presents only elapsed excerpt time and does not mark stimulus onset. The Static view stacks six source-derived AP heatmaps and twelve checksum-tracked microscopy stills without movie controls. Builds do not contact DANDI or S3; the networked extraction script is run only when refreshing the committed snapshot.

Build the committed HTML and static SVG fallback with:

```bash
uv run build-publication-figures
```

The optotagging Static view is rendered by
`openscope_p3_publication.figures.write_optotagging_static_source` from the
committed numeric atlas and `figure_sources/data/optotagging-static-summary.json`.
That summary exposes the values recovered from the original PR's archived
Matplotlib SVG; regenerate it with
`python scripts/extract_optotagging_static_summary.py`.

Do not edit files under `interactive/` directly; they are generated and checked for drift in CI.