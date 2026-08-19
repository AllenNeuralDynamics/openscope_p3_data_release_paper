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

### Example workflow for analyses across many NWB files

Figure 8 demonstrates the intended pattern for an analysis that must read many large NWB files. Opening and processing every NWB during each test, figure build, or MyST preview would be slow and would make routine builds depend on network availability. Instead, separate the workflow into an expensive **extraction stage** and a fast **presentation stage**:

1. **Define the intermediate.** Store only the scientifically necessary derived values in a compact, deterministic CSV or JSON file under `figure_sources/data/`. Include stable session/asset identifiers so every row can be traced back to its source NWB.
2. **Write a cloud-backed extractor.** Commit a script under `scripts/` that discovers or opens the versioned DANDI/NWB or S3 assets, performs the analysis, validates coverage and exclusions, and writes the intermediate plus source URLs, asset IDs/paths, retrieval date, parameters, and checksums.
3. **Commit the result.** Commit the intermediate and provenance with the extractor. This is an intentional derived publication snapshot, not an untracked cache. Reviewers should be able to inspect its values without rerunning a multi-hour cloud analysis.
4. **Build figures from the intermediate.** Static and interactive figure generators must read the committed snapshot rather than reopening all NWBs. Tests and `uv run build-publication-figures` must therefore work offline after a fresh clone and dependency installation.
5. **Refresh deliberately.** Rerun the expensive extractor only when source assets, inclusion rules, or analysis logic change. Commit the refreshed intermediate, provenance/checksums, generated static and interactive outputs, and updated tests in the same pull request. Optional download caches may speed up this refresh but are never committed or treated as the source of truth.

For the behavior figure, the stages map to repository files as follows:

- `scripts/extract_running_statistics.py` streams running-speed series and named interval tables from the public Neuropixels and mesoscope NWBs, and reads the corresponding SLAP2 Harp encoder/stimulus files from project S3. It computes common 50 ms running summaries across the available P3 sessions and writes the committed `figure_sources/data/running-statistics.json` intermediate. The JSON retains session-level block summaries, downsampled example profiles, coverage, exclusions, source asset manifests, calibration, and checksums.
- Refreshing that many-session intermediate is an explicit maintenance operation:

	```bash
	uv run --with h5py --with harp-python --with numpy --with remfile \
		python scripts/extract_running_statistics.py \
		--cache-dir /tmp/openscope-p3-running-cache
	```

	The cache is optional. Removing it increases download time but must not change the JSON values.
- `scripts/extract_behavior_excerpts.py` separately writes `figure_sources/data/behavior-excerpts.json`, a compact synchronized excerpt for representative Neuropixels, mesoscope, and SLAP2 sessions.
- `scripts/extract_behavior_static_frames.py` extracts representative public S3 camera frames into `figure_sources/media/behavior-viewer-static/` and records source URLs, ETags, target/decoded times, display transforms, and output checksums in `behavior-static-frames.provenance.json`.
- `scripts/extract_pupil_event_responses.py` streams the released P3 NWBs, aligns pupil area to context and matched-control stimulus-table `start_time` values, applies documented pupil-fit quality control, and writes the committed `figure_sources/data/pupil-event-responses.json` intermediate plus provenance.
- `scripts/extract_neuropixels_event_responses.py` streams four versioned Neuropixels NWBs from one mouse, computes context and matched-control unit PSTHs plus baseline and response summaries, reads Units-table firing rates and sorter labels, maps exact areas through the Allen ontology, computes event-specific Rastermap 1.0 ranks, and writes committed metadata plus compressed count and squared-count atlases for the interactive unit-response explorer.
- The routine command `uv run build-publication-figures` reads these committed intermediates and media files to produce both `interactive/behavior-viewer.html` and `images/figures/generated/synchronized-behavior.svg`. It does not recompute the many-NWB running analysis.

Use the same architecture for future figures that aggregate units, receptive fields, anatomical coverage, response metrics, or other values across many NWB files: cloud extractor → committed checksummed intermediate → deterministic static and interactive renderers.

## Using AI assistants effectively

This repository is structured to support agentic AI workflows: the manuscript, source data snapshots, provenance, figure generators, generated outputs, tests, and build commands are all available in one clone. We currently recommend using **5.6 SOL**.

1. Clone the repository locally, open the repository root in an agentic coding environment, and give the assistant access to the complete clone.
2. Ask the assistant to read `README.md`, `CONTRIBUTING.md`, and any repository or directory-specific instruction files before planning or editing.
3. Create a focused branch from the latest `main`.
4. Describe the requested manuscript, analysis, or figure change and point to the relevant issue, file, figure label, source data, or expected behavior.
5. Ask the assistant to trace the owning source or generator before editing and to preserve unrelated changes.
6. Ask it to implement the change end to end: update source data or code, regenerate static and interactive outputs, update captions and provenance, and add or update tests.
7. Have the assistant run the repository checks and report the changed files, validation results, and any assumptions or exclusions.
8. Review the manuscript text, scientific values, figures, captions, source links, and final diff. Correct any mistakes.
9. Ask the assistant to open a focused pull request containing only the related source, generated outputs, provenance, and tests. The pull request description should summarize the scientific change and validation results.

For example:

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