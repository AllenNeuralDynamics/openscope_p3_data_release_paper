# Receptive-field pipeline

Analysis behind the receptive-field figure: receptive fields from the Zebra noise movie (waven
wavelet correlation) and from the local Gabor patches of the receptive-field
mapping block, for Neuropixels, mesoscope and SLAP2 sessions streamed from DANDI.
Authors: Marcel C. Raabe, Lucas Rudelt.

This is the expensive stage. It needs a cluster (one phase of the wavelet
decomposition is about 54 GB in memory, and the correlation needs about as
much again, so plan for 300–350 GB of RAM), and it is never run by
`build-publication-figures`, `pytest` or `myst build`. Its reduced results
are hosted outside this repository. `scripts/extract_receptive_fields.py`
reduces them to the committed figure intermediate
(`figure_sources/data/receptive-fields/`).

## Dependencies

The dependencies are listed in [`requirements.txt`](requirements.txt). They are
not dependencies of the publication build, so they are not in `pyproject.toml`.
Use them with:

```bash
uv run --with-requirements scripts/receptive_fields/requirements.txt \
  python scripts/receptive_fields/<script>.py --help
```

waven comes from the `allen_open_scope` branch of
[RaabeM/waven](https://github.com/RaabeM/waven/tree/allen_open_scope). The
branch is the waven version for this analysis and must be used for it. It
includes the corrected orientation in degrees (`omax * 180 / n_thetas`) and the
GPU tiling of the Pearson correlation.
The distribution is named `waven0.1`; it is imported as `Waven`.

Besides waven (which brings `opencv-python`, `scikit-image` and `torch`), the
pipeline needs `numpy`, `scipy`, `pandas`, `h5py`, `pynwb`, `remfile`, `dandi`,
`requests`, `tqdm` and `quantities`, plus `oasis-deconv` for the SLAP2 events.

Inputs:

- the Zebra movie, from `$OPENSCOPE_P3_ZEBRA_MOVIE` or `.receptive_fields_work/`
  (`MOVIE_URL` in `waven_settings.py`; SHA-256 `3ee4d883…f899`)
- the filter libraries, from `$OPENSCOPE_P3_WAVEN_LIBRARIES` or
  `.receptive_fields_work/filter_libraries/`

Run the scripts from this folder, so that `waven_settings`, `utils` and
`analysis` are importable.

## Order

1. `compute_waven_pipeline_{ecephys,mesoscope,slap2}.py`: Zebra correlation maps
   over the delay × duration grid of each modality, reduced to the best filter
   per unit (`optimize_waven_parameters.py`).
2. `compute_null_distribution_{ecephys,mesoscope,slap2}.py`: null of the
   sweep-wide maximum |r| from circularly shifted responses (shared ophys code
   in `null_scan_ophys.py`).
3. `filter_significant_maps.py`: Gumbel p-values and Benjamini–Hochberg q.
4. `compute_rf_gabors_{ecephys,mesoscope,slap2}.py`: Gabor-patch maps and their
   shuffle test (`rf_gabors.py`), on the same windows as the Zebra analysis.
5. `compute_gabor_unit_significance.py`: unit-level Gabor p-values after the
   search over windows and orientations (`gabor_significance.py`), then BH.
6. `export_ephys_unit_areas.py`: CCF area and layer per Neuropixels unit.

Each script documents its arguments, layout and design choices in its
docstring and `--help`. All parameters are in `waven_settings.py`. Changing the
filter bank changes the library id, and with it every downstream result.

These files are copied from the analysis repository with only these
changes:

- import paths
- explicit imports
- lint fixes
- `None` instead of mutable default arguments
- the movie and library paths
