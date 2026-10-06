# SLAP2 Glutamate Quality Control

This is the migrated contribution by Ido Aizenbud from
[community PR #171](https://github.com/AllenNeuralDynamics/openscope-community-predictive-processing/pull/171),
pinned to commit `a0f6af8a05f296d1c376bd10e1edd70766699c25`. His three original
commits are retained in the migration history. The CSV values are unchanged.

## Contents

- `slap2_metrics_all_sessions.csv`: 2,540 source records from 20 sessions and 8 mice.
- `slap2_context_rates_all_sessions.csv`: event-bearing source/context records,
  including event counts, valid recording seconds, rates, and archive-wide classes.
- `slap2_session_summary.csv`: one row per session.
- `slap2_event_metrics.csv` and `stimulus_contexts.csv`: original example-session tables.
- `../../media/slap2-glutamate-qc/example.npz`: lossless, numeric-only example input.
- `../../media/slap2-glutamate-qc/example.provenance.json`: source asset IDs, observed
  DANDI metadata/digests, original commit, table hashes, example selections and checksum.

The example contains the original full-resolution activity/mean images and all source
masks for both imaging planes, but only four full-session source traces and their exact
timestamps: DMD1 source 9 and DMD2 sources 1, 21, and 26. It is not a primary NWB.
Its 13.05 MiB size was explicitly approved by the maintainer. LZMA compression is
lossless, and NumPy loads the archive with `allow_pickle=False`.

The example source is asset `1fccbd05-7ba2-4e40-9cb8-e8814119f756`,
`sub-794237/sub-794237_ses-20250508T145040_image+ophys.nwb`, with published SHA-256
`375a7ed7c5793cba2aaa24834db5849a71901d36d772a9b94e80df01a619c801`.
Extraction verifies event counts, noise estimates, and median raw event amplitudes
against the original table for all four selected sources.

The upstream extraction did not record its original NWB asset digests. The migration
manifest therefore distinguishes the preserved upstream table hashes from the source
asset metadata observed during migration. The example was checked against the pinned
asset, but the other 19 NWBs were not re-analyzed during migration. DANDI's draft can
change; a full rerun is a deliberate refresh, not a promise of byte-identical historical
reconstruction.

## Interpretation

The final upstream commit uses **one archive-wide k-means fit**, not the per-cohort
fits described in the older PR body. All 2,540 saved labels reproduce from the tables:
665 Low SNR, 1,026 Intermediate, 830 High SNR, and 19 excluded. The
`quality_class_session` column retains the separate within-session classifications.

Detection uses a 20 ms exponential kernel and a 3 SD threshold. Event amplitudes are
measured on the raw trace relative to a local baseline, in raw-trace noise SD. The
fraction bins are `<2`, `2 <= amplitude <4`, and `>=4` SD; the legacy `gt4sd` column
name and panel labels refer to this inclusive upper bin. The classifier standardizes
these three fractions and uses `scipy.cluster.vq.kmeans2`, three clusters, and seed 0.

The 12 glutamate-only sessions contain two-sided traces; the 8 dual-channel sessions
contain non-negative, denoised traces and have a different noise scale. Class
differences across these cohorts are not evidence of preparation-quality differences.
Context labels are inferred from orientation statistics in the older sessions and
read from named interval tables in the dual-channel sessions.

The original context table omits zero-event source/context pairs. Panel K therefore
shows means and SEM over retained event-bearing records with at least 5 valid seconds,
not an unconditional mean over every source. Classes with fewer than 10 sources in
a cohort and named contexts with fewer than 100 retained records are not drawn.

## Rebuild Offline

From the repository root:

```bash
uv sync --extra dev
uv run build-publication-figures
uv run pytest tests/test_slap2_glutamate_qc.py
```

The build generates C/G/K, the continuous-color C/G variants, and the Figure 7
composition from the committed inputs. It does not download or open a primary NWB.
The notebook at `../../python/slap2_glutamate_figure7_panels.ipynb` uses the same
package functions and writes previews only into the ignored build directory.

To render panels separately:

```bash
uv run python -m openscope_p3_publication.slap2_glutamate_figure7_panels \
  --output /tmp/slap2-qc-preview
```

## Refresh Deliberately

These commands access public cloud data and may overwrite the specified outputs.
Use a staging directory, review changes, and retain the provenance with each refresh.

```bash
uv run --extra nwb-view python scripts/extract_slap2_glutamate_qc.py \
  --output figure_sources/data/slap2-glutamate-qc --example-only \
  --example-output /tmp/slap2-example-review/example.npz --allow-large-example

uv run --extra nwb-view python scripts/extract_slap2_glutamate_qc.py \
  --output /tmp/slap2-qc-refresh --cache /tmp/slap2-nwb-cache
```

The first refreshes the four-source example and its provenance. The second is the
expensive archive-wide analysis; it downloads one NWB at a time and removes its own
download after processing unless `--keep-downloads` is passed. Do not run it over
unreviewed committed snapshots. Refit-only classification is available via
`--refit-only`, but also rewrites the supplied tables and should be run in staging.