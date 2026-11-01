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

## PDF preprint

The PDF-only project in `pdf/` reads the same `index.md` and author snapshot as the
website. It uses a local, single-column academic Typst template, expands Methods and
glossary dropdowns, and supplies static figures and the complete literature table.
The HTML configuration, interactive figures, scientific data, and manuscript text
are not modified by PDF generation. Draft notices remain visible.

Install Node.js and [Typst 0.15.1 or newer](https://github.com/typst/typst#installation),
then run from the repository root:

```bash
uv sync --extra dev --extra pdf
uv run --extra pdf build-publication-pdf
```

For a portable compiler outside `PATH`, add `--typst /path/to/typst` to the build
command. MyST 1.10.1 is invoked through `npx`; its first run and the authorship
plugin's first load require network access. No primary data are downloaded.

The combined manuscript and supplement PDF is written to
`_build/exports/openscope-p3.pdf`. The wrapper prepares only the literature-table
manifest under `_build/pdf-assets/`, then invokes MyST's Typst exporter
(`npx mystmd@1.10.1 build --typst --strict` from `pdf/`). Neither build directory
is committed. Figures use MyST's native figure rendering and original static
assets: no figure cropping, splitting, or raster preprocessing is performed.
The export template scales images to the text width, preserving aspect ratio;
images too tall for a portrait page are proportionally reduced to 205 mm high.
Manuscript and figure pages use A4 portrait throughout; long legends can flow
onto the next page.
Main figures retain MyST's automatic caption numbers. Figures marked
`enumerated: false`, including the supplements, retain their authored caption
labels without an additional automatic "Figure" prefix; reference targets remain intact.
This is a review/preprint export, not an assertion that the
unfinished scientific sections or provisional authorship are ready for submission.

The build fails on compiler warnings, missing critical content or author metadata,
landscape pages, and text extending outside a page. Focused regression checks are available with:

```bash
uv run --extra dev --extra pdf pytest tests/test_pdf_export.py
```

## Validate

```bash
uv run --extra dev ruff check .
uv run --extra dev pytest
uv run build-publication-figures
myst build --html
```

The GitHub Actions workflow runs the same checks and deploys the static site from `main`.

### Figure 6 recorded diagnostic examples

Panel A reads the compact, checksummed
[`ecephys-unit-trace.json`](figure_sources/data/ecephys-unit-trace.json) snapshot:
200 ms of native AP samples on the peak electrode of NWB unit 201, with ten
assigned spikes, an ordinary ISI zoom, and a genuine refractory-violating pair
from NWB unit 60 on its own peak electrode. This cluster passes the other signal
gates but fails ISI QC. The snapshot also contains unit 201's saved
mean template and noise level (SNR), plus measured 60 s median spike-location
bins reproducing its saved `drift_ptp`. Missing drift bins remain gaps. Its
[provenance](figure_sources/data/ecephys-unit-trace.provenance.json) records the
NWB asset, raw AP store and chunk checksums, electrode mapping, calibration,
sample intervals, selection rules, sorting-run metadata, and SpikeInterface
analyzer version/parameters. Only ADC-to-µV conversion is applied to raw voltage;
it is not interpolated, smoothed, or synthesized. The template/noise are separate
preprocessing-matched analyzer measurements. A separate 500 ms real voltage
excerpt replays the saved phase shift, high-pass filter and median reference.
The noise band uses the saved estimate from twenty random 500 ms chunks
(10 s total), not an estimate fitted to the displayed excerpt.
The band spans plus/minus one saved same-channel noise level, not the full
range of noise excursions.
The original random sample positions were not saved. The figure crops a 20 ms window
centered on the second assigned spike of the top raw trace, retaining all
600 native samples. A baseline-to-trough arrow illustrates this event's
amplitude over a light-gray noise band; the released SNR still uses the
saved mean waveform, not this single event. Noise-sampling details and the
numeric SNR are given only in the caption.
Per-unit location drift is not the
Kilosort 4 motion-correction estimate. Amplitude cutoff and presence ratio
remain QC gates, without cartoons in panel A.

The normal figure build reads this committed snapshot offline. To deliberately
refresh it from the pinned public sources, install the optional readers in an
isolated extraction environment and run:

```bash
uv run --with h5py --with remfile --with s3fs --with "zarr<3" --with wavpack-numcodecs --with "spikeinterface==0.103.0" python scripts/extract_ecephys_unit_trace.py
uv run build-publication-figures
```

Review and commit the snapshot, provenance, and regenerated figures together.
Panel G uses vector heatmap cells, and the compact layout is A / B–C–D / E–F–G.
The measured drift example (E) precedes its population distribution (F).
Its solid black segments preserve missing-bin gaps, and the drift-measurement
label is beside the range arrow. Panel D identifies individual-mouse traces
in its legend and leaves horizontal margins around session counts.
Panels B, C and F omit gridlines.
Vertical spacing is tightened without shrinking the plotting areas; F is wider
than E, using the otherwise empty gap between them.
Unit and recording identifiers belong in the caption, not plot titles.
The consecutive-mismatch analysis remains available in its committed
[snapshot](figure_sources/data/mismatch-adjacency.json) and
[provenance](figure_sources/data/mismatch-adjacency.provenance.json); its
publication summary is now in Limitations rather than a supplementary figure.

### Standard-oddball Figure 9

[Figure 9's build and data reference](docs/standard-oddball-explorer.md) documents
the Neuropixels / mesoscope Delta F/F / SLAP2 glutamate static figure and explorer.
All three modalities have committed time courses and source statistics for
45 degrees, 90 degrees, halt and omission. The explorer selects event, area/DMD,
responsiveness and source over a native-onset-aligned [-1.5, 1.5]-second window.
The original four-context Neuropixels figure remains Supplementary Figure 6.

The normal build generates only the three primary source columns, main composite
and explorer, with their audits. It does not generate candidate/regional galleries,
baseline-normalization comparisons, two-column composites or alternate signals.
Compact [publication cohort inputs](figure_sources/data/standard-oddball-publication/)
retain exact counts, mouse points, bootstrap endpoints and example-session
statistics; full Neuropixels/mesoscope unit tables are not required in Git or for
offline builds/tests.

To deliberately refresh those compact inputs, first reproduce the full analyses
with the extractors, then run `uv run python scripts/freeze_standard_oddball_publication.py`
with `--output` pointing to a new snapshot directory. Its provenance records the
full analyses' hashes and source identities without requiring those large files
during rendering. No tests, classifications or intervals are approximated.

## Repository map

- [index.md](index.md): sole authoritative MyST manuscript.
- `authors.yml`: generated snapshot of portal-managed contributor, affiliation, CRediT, and section-level authorship metadata.
- `author_portrait_sources.json`: editable, source-backed links and image dimensions for verified public portraits.
- `author_avatars.json`: generated portrait URLs and source-page provenance; images remain hosted by their original sources and are not bundled with the publication.
- `myst.yml`: publication, plugin, navigation, and static-asset configuration.
- `src/openscope_p3_publication/`: installable Python package for publication figures and data transforms.
- `interactive/`: generated JavaScript/HTML figures copied into the site at stable URLs.
- `images/figures/`: rendered assets consumed by MyST.
- `figure_sources/`: editable sources, input data, and provenance manifests.
- `scripts/sync_authors.py`: maintainer-only tool that refreshes `authors.yml` from the versioned `p3_data_release` contribution record.
- `tests/`: publication and figure regression checks.

## Manuscript source policy

[index.md](index.md) is the sole authoritative manuscript. Make all manuscript edits here through pull requests.

## Contributing to the manuscript

We welcome contributions from OpenScope Predictive Processing Community members. Start from the latest `main`, keep each pull request focused, and coordinate substantial scientific or structural changes before editing. Manuscript text belongs in `index.md`; generated assets must be updated through their owning source or generator.

All analyses must be reproducible from versioned public P3 DANDI/NWB or project S3 data. Every figure needs a caption, and every interactive figure needs a scientifically complete static counterpart for noninteractive exports. Manage authorship through the [P3 data-release contribution form](https://data.allenneuraldynamics.org/contributions/add?project=p3_data_release); authorship synchronization is maintainer-only.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the complete manuscript workflow, MyST patterns, figure and provenance requirements, cloud-data/intermediate policy, AI-assisted contribution practices, and validation commands.

## Publish

Pushes to `main` deploy to [AllenNeuralDynamics GitHub Pages](https://allenneuraldynamics.github.io/openscope_p3_data_release_paper/). In the repository settings, configure **Pages > Source** as **GitHub Actions** before the first deployment.