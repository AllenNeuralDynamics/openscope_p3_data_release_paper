# Contributing

## Manuscript changes

Edit `index.md` using MyST Markdown and submit changes through a pull request. Keep scientific edits separate from generated-asset updates when practical so reviewers can distinguish prose changes from rendering changes.

During the Google Doc cutover, `scripts/import_google_doc.py` is destructive: it replaces `index.md`, imported PNGs, and their manifest. Do not run it over repository-only edits that have not been reconciled with the source document.

## Authorship metadata

Add or update your contribution through the [P3 data-release contribution form](https://data.allenneuraldynamics.org/contributions/add?project=p3_data_release). Do not edit contributor records directly in `authors.yml`; it is a generated snapshot of the contribution portal.

Refresh the repository snapshot after portal changes:

```bash
uv run python scripts/sync_authors.py
```

The sync pins the newest portal commit and maps its ORCID, affiliation, CRediT-level, and section-level records into the structure consumed by [AuthorshipExtractor](https://github.com/AllenNeuralDynamics/AuthorshipExtractor). Do not infer or assign contributions on another person's behalf; authors should review their own portal record.

## Figures

Every figure needs:

1. An editable source or a stable source URL under `figure_sources/`.
2. Any small tabular input under `figure_sources/data/`, or a versioned external-data manifest for large inputs.
3. Reproducible generation code in `src/openscope_p3_publication/`, `figure_sources/python/`, or a committed notebook.
4. A rendered web asset in `images/figures/`.
5. A stable MyST label, descriptive alternative text, and a manuscript caption that defines panels, encodings, units, sample sizes, exclusions, and source data.
6. For every interactive figure, a scientifically complete static counterpart generated from the same validated inputs for PDF, print, and other noninteractive exports.

Do not commit NWB files or other large primary datasets. Cite a versioned DANDI asset or project S3 asset and record its URL, path, version or DOI, retrieval date, and any required checksum.

## Interactive figures

Generated HTML belongs in `interactive/` and must be listed through `project.static_files` in `myst.yml`. Embed it with the MyST `iframe` directive using a page-relative URL and provide a meaningful `:placeholder:` image for PDF and other static exports. The placeholder must communicate the primary scientific result without requiring interaction.

## Reproducible analysis and data sources

All analysis code and derived manuscript outputs must be reproducible from public P3 cloud data. Use versioned DANDI/NWB assets or project S3 files as the primary source of truth.

- Commit analysis and extraction code, declared dependencies, tests, small derived snapshots, generated outputs, and provenance/checksum records.
- Do not depend on untracked desktop files, private paths, mounted drives, hidden notebook state, or manual image edits. Builds must work from a fresh clone after installing declared dependencies.
- Keep primary NWB, imaging, video, and other large acquisition files in DANDI or S3. Stream them or generate a documented, checksum-verified subset when a compact input is needed.
- Local caches are permitted only as optional accelerators; cache presence must not affect results.
- When an upstream cloud asset changes, refresh all dependent snapshots, provenance hashes, static figures, interactive outputs, and tests in the same pull request.

## Checks

Run these before opening a pull request:

```bash
uv run --extra dev ruff check .
uv run --extra dev pytest
uv run build-publication-figures
git diff --exit-code -- interactive images/figures/generated
myst build --html
```