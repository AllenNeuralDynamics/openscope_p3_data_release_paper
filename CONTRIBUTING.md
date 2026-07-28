# Contributing

## Manuscript changes

Edit `index.md` using MyST Markdown and submit changes through a pull request. Keep scientific edits separate from generated-asset updates when practical so reviewers can distinguish prose changes from rendering changes.

During the Google Doc cutover, `scripts/import_google_doc.py` is destructive: it replaces `index.md`, imported PNGs, and their manifest. Do not run it over repository-only edits that have not been reconciled with the source document.

## Authorship metadata

Add each contributor once in `authors.yml` with a stable lowercase ID. Include an ORCID when available, affiliation IDs, CRediT roles, contribution levels, section-level contributions, and a concise contribution statement. Do not infer or assign contributions on another person's behalf; authors should review their own record.

Use the structure established in the [AuthorshipExtractor](https://github.com/AllenNeuralDynamics/AuthorshipExtractor) plugin and the `openscope_perspective` publication. Affiliation records belong in the shared `project.affiliations` list rather than being duplicated for each contributor.

## Figures

Every figure needs:

1. An editable source or a stable source URL under `figure_sources/`.
2. Any small tabular input under `figure_sources/data/`, or a versioned external-data manifest for large inputs.
3. Reproducible generation code in `src/openscope_p3_publication/`, `figure_sources/python/`, or a committed notebook.
4. A rendered web asset in `images/figures/`.
5. A static fallback for interactive figures.
6. A stable MyST label, descriptive alternative text, and a manuscript caption.

Do not commit NWB files or other large primary datasets. Cite a versioned DANDI asset and record its URL or DOI plus any required checksum.

## Interactive figures

Generated HTML belongs in `interactive/` and must be listed through `project.static_files` in `myst.yml`. Embed it with the MyST `iframe` directive using a page-relative URL and provide a placeholder image for PDF and other static exports.

## Checks

Run these before opening a pull request:

```bash
uv run --extra dev ruff check .
uv run --extra dev pytest
uv run build-publication-figures
git diff --exit-code -- interactive images/figures/generated
myst build --html
```