# SLAP2 Figure 5 candidate layouts

These tables support two candidate layouts for SLAP2 Figure 5. The manuscript still uses
`figure-07-unit-extraction-plan.svg`. A later pull request should switch it to the chosen
candidate, and then remove the other one.

| Candidate | File | Presentation of quality |
|---|---|---|
| A | `figure-07-unit-extraction-plan-variant-a.svg` | Median event amplitude, no k-means classes |
| B | `figure-07-unit-extraction-plan-variant-b.svg` | Archive-wide k-means classes |

Rendering: `write_figure5_variants` in `slap2_figure5_variants.py`. It runs offline as part of
`uv run build-publication-figures`.

Extraction: `scripts/extract_slap2_figure5_variants.py` reads the DANDI 001424 NWBs. Run it only
when the assets or the analysis change.

## Contents

- `noise_only_amplitude_histogram.csv`: pooled event amplitudes from surrogates, in 0.1 SD bins
  (366,674 detections from 1,744 sources in 12 glutamate-only sessions).
- `noise_only_source_rates.csv`: the noise-only event rate and event count of each source.
- `example_source_amplitudes.csv`: all event amplitudes of DMD1 sources 35, 87 and 110, at the
  10th, 50th and 90th percentiles of median event amplitude in the example session. The example
  snapshot does not store their traces.
- `provenance.json`: asset IDs, URLs and digests, parameters, exclusions and checksums.

## Noise-only reference

Event-free SLAP2 noise is strongly autocorrelated, so a white-noise null is not valid. For each
source, the extractor removes the detection windows from the trace, randomizes the Fourier phases
of the remainder, and runs the unchanged detector. The result has a median of about 2.5 SD, 6.5%
of detections at or above 4 SD, 29% below 2 SD, and a median rate of about 0.065 Hz.

The 8 dual-channel sessions are excluded: their traces are denoised and non-negative, so their
"noise" is a denoiser residual.

## Open items

- Scale bars use 0.25 µm/pixel, the value in the raw-neural and segmentation extractors. NWB
  `grid_spacing` is empty, so the value needs confirmation for sub-794237.
- Curve colors in candidate A panel E show the order of the sources only. They do not follow the
  map scale, because the three medians are too close on that scale.

## Draft captions

**Shared panels.** **A,** One glutamate-only example trace (session sub-794237, 2025-05-08, DMD1
source 9) in ΔF/F, with detections from an exponential matched filter (20 ms decay, 3 SD level)
and one amplitude measurement. The gray band is plus/minus three raw-noise SD: a noise reference,
not the detection threshold. **B,** Footprint of that source. **C, D,** DMD1 and DMD2 maps of the
same session.

**Candidate A.** **C, D,** Sources colored by median event amplitude in raw-noise SD, with the
trace source and the sources in E circled. **E,** Event-amplitude density of the sources at the
10th, 50th and 90th percentiles of that session (n = 2,058, 2,410 and 2,828 events), with the
median marked, and the noise-only reference. Curve color shows order only. **F,** Median event
amplitude of 2,521 classified sources (1,744 glutamate-only, 777 glutamate + calcium; 19 excluded
for undefined noise), with values above 10 SD in the last bin. **G,** The same metric per
compartment pool and session: dots are sources, bars are median and interquartile range. Values
across the two cohorts are not comparable, because the dual-channel traces are denoised.

**Candidate B.** **C, D,** Sources colored by archive-wide k-means class. **E,** Event-amplitude
density of the source nearest each class median, with the percentages below 2 SD and at or above
4 SD. **F,** 2,521 classified sources in the below-2 versus at-least-4-SD event-fraction plane.
**G,** Class composition per compartment pool and session.
