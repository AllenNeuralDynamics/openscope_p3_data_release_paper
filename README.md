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

We welcome contributions from OpenScope Predictive Processing Community members. Start from the latest `main`, keep each pull request focused, and coordinate substantial scientific or structural changes before editing. Manuscript text belongs in `index.md`; generated assets must be updated through their owning source or generator.

All analyses must be reproducible from versioned public P3 DANDI/NWB or project S3 data. Every figure needs a caption, and every interactive figure needs a scientifically complete static counterpart for noninteractive exports. Manage authorship through the [P3 data-release contribution form](https://data.allenneuraldynamics.org/contributions/add?project=p3_data_release); authorship synchronization is maintainer-only.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the complete manuscript workflow, MyST patterns, figure and provenance requirements, cloud-data/intermediate policy, AI-assisted contribution practices, and validation commands.

## Publish

Pushes to `main` deploy to [AllenNeuralDynamics GitHub Pages](https://allenneuraldynamics.github.io/openscope_p3_data_release_paper/). In the repository settings, configure **Pages > Source** as **GitHub Actions** before the first deployment.