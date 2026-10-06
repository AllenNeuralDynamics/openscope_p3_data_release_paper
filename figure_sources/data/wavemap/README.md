# WaveMAP supplementary figure

This directory contains the original contributed, gzip-compressed analysis
snapshot and its source provenance. The 50.9 MiB snapshot is retained unchanged;
its SHA-256 is checked before the publication renderer decodes it.

The snapshot contains 22,878 units from 59 sessions and 16 mice. The six displayed
anatomical groups contain 15,155 units, all with available optotagging results.
Units outside those groups are retained in the snapshot but not silently included
in displayed denominators. The omitted March 25 session for mouse 832691 is
marked `FAIL: mouse stress` in the committed session inventory.

## Rebuild

```bash
uv sync --locked --extra dev
uv run build-publication-figures
```

Routine rendering is offline and does not open NWBs, recompute embeddings,
recluster units, or rerun statistical classification. Editable rendering source
is in `figure_sources/python/wavemap_rendering.py`; the static renderer and
snapshot loader are in `src/openscope_p3_publication/wavemap_*`. The generated
four-panel SVG and four-page PDF are the complete static counterpart to
Supplementary Figure 9's interactive explorers. Plotly and the downloadable PDF
are copied to ignored deployment paths during the build, not duplicated in Git.

PNG compression, including raster images embedded in PDFs, is normalized with
Python's standard zlib encoder. This preserves image pixels, metadata, and PDF
content while avoiding platform-dependent Pillow compression choices in the
byte-for-byte generated-asset checks.

The legacy serialized 30 kHz waveform-rate fallback is not treated as measured
metadata: every recorded per-unit rate is missing in this snapshot. Static and
interactive waveform plots therefore use sample indices. The putative FS
classification still uses the contributor's source waveform-duration metric;
it is not recomputed from the displayed sample axis.

## Provenance and refresh

`wavemap-analysis.provenance.json` pins asset IDs, paths, sizes, archive digests,
and URLs. The metadata verification checks that source blobs predate the
snapshot and records when their metadata were retrieved. This is not a new
scientific extraction. The original extraction software versions were not
recorded by the contribution and are explicitly marked unavailable; `uv.lock`
pins the publication renderer's environment, not an invented historical one.

To reverify the existing asset metadata without downloading NWBs:

```bash
uv run python scripts/update_wavemap_provenance.py
```

The expensive extraction remains a separate, deliberate maintenance operation
in `scripts/extract_wavemap_analysis.py`. Do not run it as part of routine
builds or tests. Its analysis-specific QC, UMAP, Louvain, and optotagging
settings must be reviewed before a refresh. Any refreshed snapshot requires
updated provenance, tests, and both static and interactive outputs together.

WaveMAP communities are waveform clusters, not verified molecular cell types.
The putative FS/SST overlay uses criteria documented in the supplementary caption
and must not be equated with the different tagging rule in Supplementary Figure 5.