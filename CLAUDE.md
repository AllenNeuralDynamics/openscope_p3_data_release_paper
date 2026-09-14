# CLAUDE.md

Guidance for Claude Code (and humans) working in this repository.

> **`README.md` and `CONTRIBUTING.md` are authoritative.** This file summarizes them for
> agents and points at the details. If anything here disagrees with them, they win — and the
> disagreement is a bug in this file worth fixing.

## Project overview

This repository is the reproducible [MyST](https://mystmd.org/) publication for the OpenScope
Predictive Processing Community Project data release. Manuscript, authorship metadata,
editable figure sources, committed data snapshots, generated assets, interactive JavaScript
figures, and build code all live here so a result can be traced end to end.

It is a **publication**, not an application. The primary outputs are `index.md`, the rendered
static figures under `images/figures/generated/`, and the interactive figures under
`interactive/`. Pushes to `main` deploy to GitHub Pages.

## Setup

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js, and MyST.

```bash
uv sync --extra dev
uv run build-publication-figures
myst start                      # local preview, normally http://localhost:3000
```

## Checks

Run all five before opening a pull request (from `CONTRIBUTING.md`):

```bash
uv run --extra dev ruff check .
uv run --extra dev pytest
uv run build-publication-figures
git diff --exit-code -- interactive images/figures/generated
myst build --html
```

The fourth command is the important one: `build-publication-figures` must be deterministic, so
regenerating must not dirty the tree unless you intended to change an asset. CI runs the same
checks.

There is **no `ruff format` step.** The repo is linted, not formatted — `ruff format --check .`
would currently rewrite most files. Do not introduce it as part of an unrelated change.

## Repository map

| Path | What it holds |
|---|---|
| `index.md` | Canonical MyST manuscript (large — read the section you need) |
| `src/openscope_p3_publication/` | Installable package: figure builders and data transforms |
| `scripts/` | Cloud extractors and maintainer tools |
| `figure_sources/` | Editable figure sources, committed input data, provenance manifests |
| `images/figures/generated/` | **Generated** static assets — never hand-edit |
| `interactive/` | **Generated** JS/HTML figures — never hand-edit |
| `tests/` | Publication and figure regression checks |
| `authors.yml`, `author_avatars.json` | **Generated** authorship snapshots — never hand-edit |
| `myst.yml` | Publication, plugin, navigation, static-asset config |
| `docs/` | Longer-form references (migration notes, agent guidance) |

## The core architecture: extractor → committed intermediate → renderers

This is the pattern to follow for any analysis that reads many large NWB files. Do not
reinvent it; see the worked example in `CONTRIBUTING.md`.

1. **Cloud extractor** (`scripts/extract_*.py`) streams versioned DANDI/NWB or project-S3
   assets, does the expensive analysis, and writes a compact intermediate plus provenance
   recording asset IDs, URLs, versions, retrieval dates, parameters, exclusions, and
   checksums.
2. **Committed intermediate** under `figure_sources/data/` (JSON/CSV) or
   `figure_sources/media/<figure-name>/` (binary payloads). This is an intentional derived
   publication snapshot, **not** a cache — it is committed on purpose so reviewers can inspect
   values without a multi-hour rerun.
3. **Renderers** read only the committed intermediate. `uv run build-publication-figures`,
   `pytest`, and `myst build` must all work **offline from a fresh clone** after
   `uv sync --extra dev`. Never make them depend on downloading NWBs.
4. **Refresh deliberately.** Rerun an extractor only when source assets, inclusion rules, or
   analysis logic change — then commit the refreshed intermediate, provenance, regenerated
   static and interactive outputs, and updated tests in the same pull request.

There are fifteen extractors — see `scripts/extract_*.py`. Read the one nearest your figure
before writing a new one; `extract_neuropixels_event_responses.py` and
`extract_running_statistics.py` are the fullest worked examples.

## Hard rules

- **Never hand-edit a generated file.** Change its owning source or generator and regenerate.
  This covers `images/figures/generated/`, `interactive/`, `authors.yml`, and
  `author_avatars.json`.
- **Never edit `authors.yml` directly, and never run `scripts/sync_authors.py`.** Authorship
  sync is maintainer-only; contributors use the P3 contribution portal.
- **`scripts/import_google_doc.py` is destructive** — it overwrites `index.md`, imported PNGs,
  and their manifest. Do not run it over unreconciled repository edits.
- **Do not commit NWB files or other large primary datasets.** Cite a versioned DANDI or S3
  asset and record URL, path, version/DOI, retrieval date, and checksum.
- **Binary size tiers:** <10 MiB fine if required; 10–100 MiB needs maintainer approval;
  >100 MiB never. A PR adding >25 MiB of binary content total needs maintainer review.
- **Every figure needs** an editable source, reproducible generation code, a rendered asset, a
  stable MyST label, alt text, and a caption defining panels, encodings, units, sample sizes,
  exclusions, and source data. **Every interactive figure needs a scientifically complete
  static counterpart** that stands alone in PDF and print.
- **Support scientific claims with a citation or source-backed record.** Do not infer results
  or provenance.

## Working style

- **Plan before non-trivial work.** Propose 2–3 approaches with trade-offs and a
  recommendation before implementing. See the `prompting-conventions` skill.
- **Keep pull requests focused.** Separate unrelated scientific revisions; don't mix repo
  governance with a figure change. Update generated files in the same PR as their source.
- **Evidence over assertions.** Run the checks and paste the output; don't claim a build or
  test passes without showing it.
- **Preview destructive shell commands.** Extractors overwrite multi-MB committed snapshots in
  place — commit first, preview, then run. See the `bash-safety` skill.
- **Trace the owning source before editing**, and preserve unrelated changes.

## Python conventions

- Package code in `src/openscope_p3_publication/`, imported absolutely
  (`from openscope_p3_publication.neural_responses import ...`). Analysis and figure-generation
  code belongs here when it is reusable and tested — that is the established pattern
  (`neural_responses.py`, `pupil_responses.py`, `optotagging.py`).
- One-off extractors and maintainer CLIs go in `scripts/` and should import logic from the
  package rather than reimplementing it.
- Tests in `tests/`, named `test_*.py`, tracking the module they cover
  (`neural_responses.py` → `test_neural_responses.py`).
- ruff: line length 100, target py311, rules `E, F, I, UP, B` (see `pyproject.toml`).
  Type-hint public signatures; short docstrings on public functions.
- Prefer small, single-purpose functions. Prefer vectorized NumPy over Python-level loops on
  numerical data, and watch for precision loss, silent dtype casts, and off-by-one errors in
  math-heavy code — but don't add caching or low-level tricks without a measured bottleneck.
- Notebooks stay thin and are not required by the build. Clear outputs before committing, and
  confirm `uv run --extra dev ruff check .` passes with them present.

## Available project skills (`.claude/skills/`)

Load the relevant one before doing that kind of work:

- **bash-safety** — bash footguns (`rm`, globs, redirection, git force operations) and how to
  avoid them; load before destructive commands. Full reference: `docs/bash-safety.md`.
- **prompting-conventions** — how to frame a task for a coding agent: plan first, clear
  outcome, acceptance criteria, bounded scope, verification. Full reference:
  `docs/prompting-conventions.md`.
- **authoring-skills** — how to write a new project-local skill here.

## Optional: superpowers plugin

This repo is self-contained and requires no plugins. If the **superpowers** Claude Code plugin
is installed, its global skills (brainstorming, writing-plans, test-driven-development,
systematic-debugging, verification-before-completion) complement the local skills above.
