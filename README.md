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
- `scripts/sync_authors.py`: refreshes `authors.yml` from the versioned `p3_data_release` contribution record.
- `tests/`: publication and figure regression checks.

## Manuscript source policy

The repository should become the canonical manuscript after the transition is accepted. Until that cutover, importing the Google Doc overwrites `index.md`; reconcile repository-only edits first. See `docs/MIGRATION.md` for unresolved source and editorial work.

## Contributing to the manuscript

We welcome contributions from OpenScope Predictive Processing Community members. Coordinate substantial scientific or structural changes in an issue or discussion before starting so parallel edits do not conflict.

1. Create a focused branch from the latest `main` and edit `index.md` using MyST Markdown.
2. Preserve the manuscript's existing section structure, MyST labels, citations, terminology, and figure numbering unless the pull request explicitly proposes a coordinated change.
3. Support scientific claims with a citation or a source-backed project record. Do not commit unpublished primary data, NWB files, credentials, or personally identifying information.
4. Keep prose, figure, and data-snapshot changes narrowly scoped. Separate unrelated scientific revisions into different pull requests when practical.
5. For figures, commit the editable or versioned source, provenance or checksums, reproducible generation code, rendered web asset, static fallback for interactive views, alternative text, and caption.
6. Update generated files in the same pull request as their source. Do not edit files in `interactive/` or `images/figures/generated/` without updating the owning source or generator.
7. Manage authorship through the [P3 data-release contribution form](https://data.allenneuraldynamics.org/contributions/add?project=p3_data_release), not by editing generated author records directly.
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

## Publish

Pushes to `main` deploy to [AllenNeuralDynamics GitHub Pages](https://allenneuraldynamics.github.io/openscope_p3_data_release_paper/). In the repository settings, configure **Pages > Source** as **GitHub Actions** before the first deployment.