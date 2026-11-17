# SLAP2 Figure 5 Noise-Only Reference

These tables give the noise-only reference line of SLAP2 Figure 5 (`fig-unit-extraction-plan`).

| File | Use |
|---|---|
| `figure-07-unit-extraction-plan.svg` | Manuscript Figure 5: all sessions pooled |
| `figure-07-unit-extraction-plan-by-cohort.svg` | Variant with E–G split into the glutamate-only and glutamate-plus-calcium cohorts; not in the manuscript |

Rendering: `write_figure5` in `slap2_figure5.py`, offline, as part of
`uv run build-publication-figures`. The figure also reads the issue-59 archive tables in
`../slap2-glutamate-qc-v2/` and the pinned example snapshot in
`../../media/slap2-glutamate-qc/`.

Extraction: `scripts/extract_slap2_figure5_noise.py` reads the 12 glutamate-only DANDI 001424
NWBs listed in `../slap2-glutamate-qc-v2/provenance.json` and checks each SHA-256 against the
published digest. Run it only when the assets or the analysis change.

## Contents

- `noise_only_amplitude_histogram.csv`: pooled event amplitudes from surrogates, in 0.1 SD bins
  (367,111 detections from 1,744 sources in 12 glutamate-only sessions).
- `noise_only_source_rates.csv`: the noise-only event rate and event count of each source.
- `provenance.json`: asset IDs, paths and digests, input checksums, parameters, exclusions and
  output checksums.

## Noise-only reference

Event-free SLAP2 noise is strongly autocorrelated, so a white-noise null is not valid. For each
source, the extractor removes the detection windows (20 samples before and 40 after each
detection) from the trace, randomizes the Fourier phases of the remainder, and runs the unchanged
detector at the nominal 5 ms sample interval. The result has a median of 2.53 SD, 6.5% of
detections at or above 4 SD, 28% below 2 SD, and a median rate of 0.065 Hz per source.

The 8 dual-channel sessions are excluded: their traces are denoised and non-negative, so their
"noise" is a denoiser residual.

## Open items

- Scale bars use 0.25 µm/pixel, the value in the raw-neural and segmentation extractors. NWB
  `grid_spacing` is empty, so the value needs confirmation for sub-794237.
- The "proximal" and "apical" labels of DMD1 and DMD2 come from the NWB imaging-plane location,
  which is recorded only for the three sub-794237 sessions. Other sessions record "unknown" or
  "VISp".
