# Imported figure provenance

This folder contains provenance for retained figure assets, not a manuscript or a manuscript-editing workflow. [index.md](../../index.md) is the sole authoritative manuscript.

The files in `images/figures/imported/` are rendered PNG exports from the original Google Doc. [manifest.json](manifest.json) records each original export name, semantic repository name, SHA-256 checksum, draft status, and stable MyST label. Publication tests continue to validate these records against the retained images.

Google's DOCX and HTML exports do not expose the source Google Slides presentation IDs. Add each editable deck or source URL to this folder and populate the corresponding `editable_source_url` field in `manifest.json` when it becomes available. Rendered PNGs should remain in the repository as immutable snapshots of what appeared in the manuscript at import time.

Future figure sources should use a format-specific subdirectory, for example:

```text
figure_sources/
  data/
  google-slides/
  illustrator/
  notebooks/
  python/
```