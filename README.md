# OpenScope predictive processing data release

This repository is the reproducible MyST publication for the OpenScope Predictive Processing Community Project data release. It keeps the manuscript, authorship metadata, editable figure sources, generated assets, interactive JavaScript figures, and build code under version control.

## Quick start

Requirements: Python 3.11 or newer, [uv](https://docs.astral.sh/uv/), Node.js, and [MyST](https://mystmd.org/).

```bash
uv sync --extra dev
uv run build-publication-figures
myst start
```

MyST prints the local preview URL, normally `http://localhost:3000`.

## Validate

```bash
uv run --extra dev ruff check .
uv run --extra dev pytest
uv run build-publication-figures
myst build --html
```

The GitHub Actions workflow runs the same checks and deploys the static site from `main`.

## Repository map

- `index.md`: canonical MyST manuscript.
- `authors.yml`: generated snapshot of portal-managed contributor, affiliation, CRediT, and section-level authorship metadata.
- `author_avatars.json`: verified remote portrait URLs and source-page provenance; images remain hosted by the Allen Institute and are not bundled with the publication.
- `myst.yml`: publication, plugin, navigation, and static-asset configuration.
- `src/openscope_p3_publication/`: installable Python package for publication figures and data transforms.
- `interactive/`: generated JavaScript/HTML figures copied into the site at stable URLs.
- `images/figures/`: rendered assets consumed by MyST.
- `figure_sources/`: editable sources, input data, and provenance manifests.
- `manuscript_sources/google-doc/`: preserved Google Doc export and import notes.
- `scripts/import_google_doc.py`: deterministic but destructive Google Doc importer.
- `scripts/sync_authors.py`: maintainer-only tool that refreshes `authors.yml` from the versioned `p3_data_release` contribution record.
- `tests/`: publication and figure regression checks.

## Manuscript source policy

The repository should become the canonical manuscript after the transition is accepted. Until that cutover, importing the Google Doc overwrites `index.md`; reconcile repository-only edits first. See `docs/MIGRATION.md` for unresolved source and editorial work.

## Contributing to the manuscript

We welcome contributions from OpenScope Predictive Processing Community members. Coordinate substantial scientific or structural changes in an issue or discussion before starting so parallel edits do not conflict.

1. Create a focused branch from the latest `main` and edit `index.md` using MyST Markdown.
2. Preserve the manuscript's existing section structure, MyST labels, citations, terminology, and figure numbering unless the pull request explicitly proposes a coordinated change.
3. Support scientific claims with a citation or a source-backed project record. Analyses must derive from versioned P3 data available through DANDI/NWB or public project S3 assets, with source URLs and checksums recorded in the repository. Do not commit unpublished primary data, NWB files, credentials, or personally identifying information.
4. Keep prose, figure, and data-snapshot changes narrowly scoped. Separate unrelated scientific revisions into different pull requests when practical.
5. Every figure needs a manuscript caption. For generated figures, commit the editable or versioned source, provenance or checksums, reproducible generation code, rendered web asset, alternative text, and caption. Every interactive figure also requires a scientifically complete static counterpart for PDF and other noninteractive exports.
6. Update generated files in the same pull request as their source. Do not edit files in `interactive/` or `images/figures/generated/` without updating the owning source or generator.
7. Manage authorship through the [P3 data-release contribution form](https://data.allenneuraldynamics.org/contributions/add?project=p3_data_release), not by editing generated author records directly. After updating the form, notify the repository maintainer; only the maintainer should run `scripts/sync_authors.py` and commit the refreshed snapshot.
8. In the pull request, summarize the scientific change, identify source data or references, list regenerated assets, and report validation commands. Request review from the relevant section or data owner.

Before opening a pull request, run:

```bash
uv run --extra dev ruff check .
uv run --extra dev pytest
uv run build-publication-figures
git diff --exit-code -- interactive images/figures/generated
myst build --html
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for authorship, figure provenance, interactive-figure, and data-size requirements.

### Static and interactive figures with MyST

Choose the simplest format that communicates the scientific result clearly:

- Use a **static figure** for a fixed result, comparison, schematic, or composition that should read completely in HTML, PDF, print, and archival exports.
- Use an **interactive figure** when selection, filtering, synchronized playback, 3D rotation, or access to many records materially improves interpretation. Interactivity should expose additional detail, not hide the primary conclusion.
- Every interactive figure must have a static counterpart. Build both from the same validated data and generator. The static view must communicate the primary result as a meaningful standalone figure, not a screenshot of controls or an instruction to open the website.

For a static asset, use MyST's `figure` directive with a stable label, descriptive alternative text, width, and caption:

```markdown
:::{figure} ./images/figures/generated/example.svg
:label: fig-example
:alt: Concise description of the plotted data and visual encoding.
:width: 100%

Caption describing the result, panels, units, sample sizes, and provenance.
:::
```

For an interactive figure, keep generated HTML under `interactive/` and embed it with an `iframe`. Always provide a static `:placeholder:` for PDF, print, failed JavaScript, and other noninteractive exports:

```markdown
:::{iframe} ./interactive/example.html
:label: fig-example
:width: 100%
:title: Short accessible title for the interactive figure
:placeholder: ./images/figures/generated/example.svg

One caption shared by the interactive and static views.
:::
```

MyST guidance for this repository:

- Use page-relative paths and stable, unique labels so references such as `[Figure 2](#fig-example)` survive reordering.
- Keep `interactive/` listed under `project.static_files` in `myst.yml`; add another static directory only when the site must copy it verbatim.
- Put explanatory science in the manuscript caption, not only inside the HTML application. Captions must define panels, colors, symbols, units, sample sizes, exclusions, and source data.
- Give the interactive HTML semantic controls, keyboard access, accessible names, responsive layout, and a useful initial state. Avoid duplicating usage instructions as visible figure content.
- Generate both outputs deterministically, commit them with their source, and verify HTML plus static rendering at desktop and mobile sizes.
- Preview interactively with `myst start`; use `myst build --html` to catch path and static-asset errors. The committed placeholder is what noninteractive exports and many reviewers will see.

### Reproducible and self-contained analyses

The repository must contain everything needed to understand and rebuild the manuscript except the versioned primary data themselves:

- Commit manuscript text, bibliography, figure/data transforms, configuration, tests, small derived snapshots, generated assets, and provenance records.
- Derive analyses from public P3 cloud sources: DANDI/NWB assets or versioned project S3 files. Record stable asset paths, URLs or Dandiset versions, retrieval dates, and checksums where practical.
- Do not depend on files that exist only on a contributor's desktop, Downloads folder, private network drive, interactive notebook state, or uncommitted environment. A fresh clone must be able to run the documented build after installing declared dependencies.
- Keep large primary files in DANDI or S3 rather than Git. If a build streams or extracts a subset, commit the extraction code and enough provenance to reproduce that subset.
- When reading the primary NWB/S3 sources is too slow for routine builds, commit a compact intermediate under `figure_sources/data/` or `figure_sources/media/`. Commit the extraction script beside it, plus source asset identifiers, URLs, versions, retrieval dates, checksums, parameters, exclusions, and the intermediate's checksum. Normal figure builds should read the committed intermediate; maintainers can rerun the extractor when the source or analysis changes.
- Pin software dependencies and external source revisions. Avoid manual post-processing of generated figures; encode display transformations in scripts and record relevant parameters.
- Treat local caches as optional performance aids. Deleting a cache may make a build slower, but must not change scientific values or rendered outputs.

The behavior figure demonstrates this pattern:

1. `scripts/extract_behavior_excerpts.py` streams representative Neuropixels and mesoscope NWB data from DANDI and SLAP2 behavior/Harp data from project S3, then writes the compact synchronized `figure_sources/data/behavior-excerpts.json` snapshot.
2. `scripts/extract_running_statistics.py` streams NWB running-speed series and interval tables, plus SLAP2 Harp encoder/stimulus files, and writes `figure_sources/data/running-statistics.json`. The committed JSON contains block-aware session summaries and downsampled example profiles; the optional cache only avoids repeated downloads.
3. `scripts/extract_behavior_static_frames.py` reads the verified public camera streams and committed snapshots, then writes the static JPEGs under `figure_sources/media/behavior-viewer-static/` and their checksum-bearing provenance record.
4. `uv run build-publication-figures` reads those committed intermediates to deterministically generate both `interactive/behavior-viewer.html` and `images/figures/generated/synchronized-behavior.svg`. A normal manuscript build therefore does not need to stream multi-gigabyte NWBs or videos, while every intermediate remains traceable to cloud data and reproducible from committed code.

### Using AI assistants effectively

AI assistants can help navigate the repository, draft focused edits, trace figure-generation paths, update tests, and run validation. They should accelerate reviewable work, not replace scientific judgment or provenance checks.

- Start with a concrete task, file, figure label, failing test, or expected behavior. Ask the assistant to inspect the owning source before editing.
- State the scientific source of truth and any constraints explicitly. Do not ask an assistant to infer results, citations, authorship, or data provenance.
- Ask for the smallest source-level change. Generated files should be rebuilt through their owning script or `uv run build-publication-figures`, not edited by hand.
- Keep source data, generators, static fallbacks, interactive outputs, captions, and regression tests synchronized in one pull request.
- Require the assistant to preserve unrelated local changes and to show the final diff, validation results, and any assumptions or exclusions.
- Verify every scientific statement, citation, numerical value, image interpretation, and authorship change yourself. AI-generated text may be fluent but unsupported.
- Never provide credentials, private data, unpublished participant information, or other restricted material to an external AI service. Follow Allen Institute policies for approved tools and data handling.

A useful request includes the target, source of truth, required outputs, and checks. For example:

> Update Figure 4's session colors to the supplied RGB values. Trace the palette to its source, update static and interactive outputs without changing unrelated figures, add a regression test, run the publication checks, and summarize the diff for review.

## Publish

Pushes to `main` deploy to [AllenNeuralDynamics GitHub Pages](https://allenneuraldynamics.github.io/openscope_p3_data_release_paper/). In the repository settings, configure **Pages > Source** as **GitHub Actions** before the first deployment.