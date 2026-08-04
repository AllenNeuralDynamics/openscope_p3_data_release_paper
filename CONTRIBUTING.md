# Contributing

## Manuscript changes

We welcome contributions from OpenScope Predictive Processing Community members. Coordinate substantial scientific or structural changes in an issue or discussion before starting so parallel edits do not conflict.

1. Create a focused branch from the latest `main` and edit `index.md` using MyST Markdown.
2. Preserve the manuscript's section structure, MyST labels, citations, terminology, and figure numbering unless the pull request explicitly proposes a coordinated change.
3. Support scientific claims with a citation or source-backed project record. Do not infer results or provenance.
4. Keep prose, figure, and data-snapshot changes narrowly scoped. Separate unrelated scientific revisions when practical.
5. Update generated files in the same pull request as their source; never edit generated outputs without updating their owner.
6. In the pull request, summarize the scientific change, identify source data or references, list regenerated assets, report validation, and request review from the relevant section or data owner.

During the Google Doc cutover, `scripts/import_google_doc.py` is destructive: it replaces `index.md`, imported PNGs, and their manifest. Do not run it over repository-only edits that have not been reconciled with the source document.

## Authorship metadata

Add or update your contribution through the [P3 data-release contribution form](https://data.allenneuraldynamics.org/contributions/add?project=p3_data_release). Do not edit contributor records directly in `authors.yml`; it is a generated snapshot of the contribution portal.

After changing your portal record, notify the repository maintainer and request an authorship snapshot refresh. Do not run `scripts/sync_authors.py`; authorship synchronization and the resulting commit are maintainer-only operations.

The maintainer-run sync pins the newest portal commit and maps its ORCID, affiliation, CRediT-level, and section-level records into the structure consumed by [AuthorshipExtractor](https://github.com/AllenNeuralDynamics/AuthorshipExtractor). Do not infer or assign contributions on another person's behalf; authors should review their own portal record.

## Figures

Every figure needs:

1. An editable source or a stable source URL under `figure_sources/`.
2. Any small tabular input under `figure_sources/data/`, or a versioned external-data manifest for large inputs.
3. Reproducible generation code in `src/openscope_p3_publication/`, `figure_sources/python/`, or a committed notebook.
4. A rendered web asset in `images/figures/`.
5. A stable MyST label, descriptive alternative text, and a manuscript caption that defines panels, encodings, units, sample sizes, exclusions, and source data.
6. For every interactive figure, a scientifically complete static counterpart generated from the same validated inputs for PDF, print, and other noninteractive exports.

Do not commit NWB files or other large primary datasets. Cite a versioned DANDI asset or project S3 asset and record its URL, path, version or DOI, retrieval date, and any required checksum.

## Static and interactive figures with MyST

Choose the simplest format that communicates the scientific result clearly. Use a static figure for a fixed result, comparison, schematic, or composition that must read completely in HTML, PDF, print, and archival exports. Use an interactive figure when selection, filtering, synchronized playback, 3D rotation, or access to many records materially improves interpretation. Interactivity should expose additional detail, not hide the primary conclusion.

Every interactive figure must have a static counterpart generated from the same validated inputs. The static view must communicate the primary result independently, not show controls or instruct readers to visit the website.

For a static asset, use MyST's `figure` directive:

```markdown
:::{figure} ./images/figures/generated/example.svg
:label: fig-example
:alt: Concise description of the plotted data and visual encoding.
:width: 100%

Caption describing the result, panels, units, sample sizes, and provenance.
:::
```

For an interactive figure, keep generated HTML under `interactive/` and provide a static placeholder:

```markdown
:::{iframe} ./interactive/example.html
:label: fig-example
:width: 100%
:title: Short accessible title for the interactive figure
:placeholder: ./images/figures/generated/example.svg

One caption shared by the interactive and static views.
:::
```

Generated HTML belongs in `interactive/` and must be listed through `project.static_files` in `myst.yml`. Embed it with the MyST `iframe` directive using a page-relative URL and provide a meaningful `:placeholder:` image for PDF and other static exports. The placeholder must communicate the primary scientific result without requiring interaction.

- Use stable, unique labels and page-relative paths so cross-references survive reordering.
- Put explanatory science in the manuscript caption, not only in the HTML application.
- Give interactive controls semantic markup, keyboard access, accessible names, responsive layout, and a useful initial state.
- Generate both outputs deterministically and verify interactive plus static rendering at desktop and mobile sizes.
- Preview with `myst start`; use `myst build --html` to catch path and static-asset errors.

## Reproducible analysis and data sources

All analysis code and derived manuscript outputs must be reproducible from public P3 cloud data. Use versioned DANDI/NWB assets or project S3 files as the primary source of truth.

- Commit analysis and extraction code, declared dependencies, tests, small derived snapshots, generated outputs, and provenance/checksum records.
- Do not depend on untracked desktop files, private paths, mounted drives, hidden notebook state, or manual image edits. Builds must work from a fresh clone after installing declared dependencies.
- Keep primary NWB, imaging, video, and other large acquisition files in DANDI or S3. Stream them or generate a documented, checksum-verified subset when a compact input is needed.
- If cloud extraction is too expensive for every build, commit the smallest scientifically sufficient intermediate under `figure_sources/data/` or `figure_sources/media/`. The same pull request must include extraction code and provenance recording source asset IDs/paths, Dandiset or S3 URLs, versions, retrieval dates, checksums, analysis parameters, exclusions, and the intermediate checksum.
- Figure generators should consume committed intermediates by default. Do not make ordinary tests, MyST builds, or figure generation depend on downloading full NWBs, videos, or imaging stores. Provide a separate documented refresh command for maintainers.
- Local caches are permitted only as optional accelerators; cache presence must not affect results.
- When an upstream cloud asset changes, refresh all dependent snapshots, provenance hashes, static figures, interactive outputs, and tests in the same pull request.

### Behavior-figure example

Figure 8 uses committed intermediates so routine builds remain fast and deterministic:

- `scripts/extract_behavior_excerpts.py` reads synchronized behavior/running/stimulus data from public DANDI NWBs and project S3/Harp sources, producing `figure_sources/data/behavior-excerpts.json`.
- `scripts/extract_running_statistics.py` reads full-session NWB running series and named interval tables, plus SLAP2 Harp encoder and stimulus files, producing `figure_sources/data/running-statistics.json`. Its cache directory is optional and is never the source of truth.
- `scripts/extract_behavior_static_frames.py` extracts representative public camera frames into `figure_sources/media/behavior-viewer-static/` and records source URLs, ETags, target/decoded times, display transforms, and output checksums in `behavior-static-frames.provenance.json`.
- `uv run build-publication-figures` consumes these committed intermediates to produce the interactive behavior viewer and its static SVG counterpart. Contributors should rerun the extraction scripts only when changing source data or analysis logic, then commit the refreshed intermediates, provenance, generated outputs, and tests together.

## Using AI assistants effectively

AI assistants can help navigate the repository, draft focused edits, trace generation paths, update tests, and run validation. They accelerate reviewable work but do not replace scientific judgment or provenance checks.

- Start with a concrete task, file, figure label, failing test, or expected behavior. Ask the assistant to inspect the owning source before editing.
- State the scientific source of truth and constraints explicitly. Do not ask an assistant to infer results, citations, authorship, or provenance.
- Ask for the smallest source-level change. Regenerate outputs through their owning script rather than editing them by hand.
- Keep source data, generators, static counterparts, interactive outputs, captions, and tests synchronized.
- Require preservation of unrelated changes and a final report of the diff, validation, assumptions, and exclusions.
- Verify every scientific statement, citation, numerical value, image interpretation, and authorship change yourself.
- Never provide credentials, private data, unpublished participant information, or restricted material to an external AI service. Follow Allen Institute policies for approved tools and data handling.

A useful request names the target, source of truth, required outputs, and checks. For example:

> Update Figure 4's session colors to the supplied RGB values. Trace the palette to its source, update static and interactive outputs without changing unrelated figures, add a regression test, run the publication checks, and summarize the diff for review.

## Checks

Run these before opening a pull request:

```bash
uv run --extra dev ruff check .
uv run --extra dev pytest
uv run build-publication-figures
git diff --exit-code -- interactive images/figures/generated
myst build --html
```