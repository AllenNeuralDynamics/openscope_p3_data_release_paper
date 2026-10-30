# Receptive-field figure data

`receptive-fields.h5` is the compact intermediate of the receptive-field figure
(`images/figures/generated/receptive-fields.svg`): receptive fields mapped with the local Gabor patches
of the receptive-field mapping block and with the Zebra noise movie, in one
session per modality. It holds only what the figure draws. The renderer,
`src/openscope_p3_publication/receptive_field_figure.py`, checks the file against
the SHA-256 in `receptive-fields.provenance.json` and runs offline.

The renderer retains three modality columns and A-C rows, with larger maps,
summary plots, and text within the same full-width output. Headers reuse the
checksummed platform logos and the shared Myriad/Arial font stack. These are
presentation changes only: maps, fits, counts, significance, and axis ranges
are read unchanged from the committed intermediate.
Each modality has one column centre shared by its heading text, example-map
group, pie-chart pair, and summary-plot group. Icons sit beside the centred
headings rather than offsetting the text; centring preserves plot dimensions.
Example maps share a symmetric color scale across modalities within each
stimulus, with two vertical color bars at the right: Gabor responses retain
z-score units and Zebra maps retain correlation units. Each limit is the largest
absolute value in the displayed maps of that stimulus; no displayed value is
clipped or normalized to a different unit. Gaussian outlines, map frames, and
summary strokes are thinner, while rig icons are larger. Spatial axis labels
are shared across each row. RF-area headings apply to both summary rows;
peak-strength headings distinguish Gabor |z| from Zebra |r|.
Elevation labels in A and C share a left alignment with clearance from the
stimulus images. Row B is raised slightly without moving A or C.
Panel B uses one count-free category legend and retains the original percentages.
Per-structure unit totals appear in the pie titles, tentative manuscript caption,
and provenance; the shared legend contains category names only.

| Modality | Session | Dandiset | Zebra signal | Gabor signal |
|---|---|---|---|---|
| `ecephys` | `sub-830794_ses-ecephys-830794-2026-01-26-12-02-05_ecephys` | 001637 | spikes | spikes |
| `mesoscope` | `sub-832700_ses-multiplane-ophys-832700-2026-01-24-12-06-12_ophys` | 001768 | events (NWB, OASIS) | events (NWB, OASIS) |
| `slap2` | `sub-829704_ses-829704-2025-12-18-10-57-36_image+ophys`, green channel | 001424 | ΔF/F | events (OASIS on ΔF/F) |

## Layout

Tables are groups with one dataset per column; strings are UTF-8.

```
/                         attrs: schema_version, q_level, gabor_centre_limit_deg, zebra_block,
                                 phase, visual_coverage_deg, zebra_extent_deg
/stimulus/zebra_frame     uint8 (H, W), frame 1000 of the Zebra movie, 4 x 4 block-averaged
/stimulus                 attrs: gabor_* parameters of the example Gabor patch
/<modality>/              attrs: session, dandiset, zebra_signal, gabor_signal,
                                 example_population, library_id
    examples/             row A, one entry per selection (both, gabor-only, zebra-only):
                          selection, present, group, unit_id, n_eligible, pass_gabor,
                          pass_zebra, gabor_map (3, 9, 9) z, zebra_map (3, 67, 53) r,
                          gabor_fit / zebra_fit (3, 6) x0, y0, sigma_x, sigma_y, theta, r2
                          (NaN unless the map passed); attrs: gabor_extent_deg, positions
    units/                row B: group, unit_id, structure, pass_gabor, pass_zebra,
                          p_value_bh (Gabor q), q_zebra
    gabor_fits/, zebra_fits/       row C points: group, unit_id, structure, x0, y0 (deg),
                          area (deg², one-sigma ellipse), strength (peak |z| or |r|), fit_r2;
                          attrs: window_deg
    gabor_summary/, zebra_summary/ column, structure, n, median, ci_low, ci_high
    gabor_tests/, zebra_tests/     column, structure_a, structure_b, p_value
```

Populations: row A uses primary visual cortex (ecephys VISp layer 2/3, mesoscope
plane `VISp_0`, all SLAP2 sources). Rows B and C use the two compared structures:
ecephys VISp and VISl (all layers, from the extremum-channel CCF label), mesoscope
VISp and VISl planes, SLAP2 DMD1 (apical) and DMD2 (basal). A map is significant
at Benjamini–Hochberg *q* ≤ 0.05; untested units count as not significant.
Gabor-significant units whose Gaussian fit failed or whose centre lies beyond
±40° are left out of rows B and C; their counts are in the provenance.

## Source results

The extractor reads the reduced pipeline results, laid out as

```
gabors/<modality>/<session>/<signal>/<session>__rf-<measure>__<group>__optimized.h5
zebra/optimized/<modality>/<session>/<signal>/optimized__<session>__<group>__pooled_trials__phase_0.h5
zebra/nullresults/<modality>/<session>/<signal>/<group...>/pooled_trials/phase_0/lib_<id>/null__lib_<id>.h5
ecephys/<session>/unit_areas.csv
```

and records the path, size and SHA-256 of every file it reads in the
provenance. Only null files of the maps' filter library (`lib_0c638217c1`) are
used. These results are produced by the pipeline in `scripts/receptive_fields/`
(waven from its `allen_open_scope` branch; see its README)
from the DANDI sessions above; they are too large for this repository and are
hosted externally (`results.url` in the provenance).

## Refresh

```bash
uv run --with tqdm --with opencv-python-headless \
  python scripts/extract_receptive_fields.py \
  --results-root /path/to/results --results-url <public location of those results>
```

The Zebra movie is read from `$OPENSCOPE_P3_ZEBRA_MOVIE` or
`.receptive_fields_work/` (ignored) and must match the SHA-256 of the pinned
public copy (`MOVIE_URL` in `scripts/receptive_fields/waven_settings.py`). The
extractor writes the HDF5 twice and refuses to continue unless both copies are
byte-identical. The Gaussian fits depend slightly on the SciPy version, so refresh
within the locked environment; the versions used are recorded under
`environment` in the provenance. Then rerun `uv run build-publication-figures`.
