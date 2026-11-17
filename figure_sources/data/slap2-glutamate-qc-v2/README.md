# SLAP2 Glutamate Quality Control, Issue-59 Refresh

These tables repeat the archive-wide SLAP2 glutamate QC of `../slap2-glutamate-qc/` with one
change: every session uses the nominal 200 Hz sample interval
([issue #59](https://github.com/AllenNeuralDynamics/openscope_p3_data_release_paper/issues/59)).
Figure 5 reads these tables. Figure 9 and the legacy three-class panels keep the frozen tables in
`../slap2-glutamate-qc/`, which stay byte-identical.

## Why the refresh

`sampling_interval()` used the median timestamp step as dt. That value is wrong in two ways:

- In the dual-channel sessions, DMD1 samples are interpolated between cycle starts, so the median
  step is 4.5–4.9 ms while the mean step within a trial is 5.0 ms. This shortened the recorded
  duration and changed the kernel length.
- The kernel length is `ceil(5 tau / dt)`. Median steps a few microseconds on each side of 5 ms
  gave some glutamate-only sessions 21-sample kernels and others 20-sample kernels. With
  `np.convolve(..., mode="same")`, this moved each detection by one sample relative to the raw
  trace, so more raw peaks fell after the 40 ms peak window.

The function now returns 5 ms after it checks that the median step is within 15% of it.

## Contents

- `slap2_metrics_all_sessions.csv`, `slap2_context_rates_all_sessions.csv`,
  `slap2_session_summary.csv`: the same columns and the same 2,540 sources from 20 sessions and
  8 mice as the frozen tables.
- `provenance.json`: the 20 DANDI 001424 assets with their verified SHA-256 digests, the
  parameters, the frozen table used to select the sessions, and output checksums.

## Changes from the frozen tables

- 235 of 2,540 sources change their archive-wide k-means class: 888 High SNR (was 830),
  957 Intermediate (was 1,026), 676 Low SNR (was 665), 19 excluded (unchanged). 76 of the 235
  are in `sub-794237_ses-20250403T103830`, which changed from a 21-sample to a 20-sample kernel.
  Some glutamate-only sources change class only because the archive-wide fit moves.
- Median event amplitude rises by 0.30 SD (session median) in `sub-794237_ses-20250403T103830`.
  It changes by 0.12 SD or less in every other session, and not at all in sessions that already
  used 20-sample kernels.
- In the Figure 9 sessions (`sub-828408` 2025-11-18 and the four `sub-829704` sessions), the set
  of High SNR plus Intermediate sources does not change. Only labels between those two classes
  change.

The class labels remain in the tables, but Figure 5 no longer uses them.

## Refresh

```bash
uv run --extra nwb-view python scripts/extract_slap2_glutamate_qc.py \
  --output figure_sources/data/slap2-glutamate-qc-v2 --cache /tmp/slap2_cache --keep-downloads \
  --sessions-from figure_sources/data/slap2-glutamate-qc/slap2_metrics_all_sessions.csv
```

`--sessions-from` keeps exactly the 20 tabled sessions. The DANDI draft also holds
`sub-828408` 2025-11-19, which is not in the frozen tables; adding it is a separate change.
The run needs the 20 NWBs (about 40 GB) and takes about 10 minutes from a local cache.

## Open item

The detector convolves the trace with the kernel itself, not with its reflection, in
`mode="same"`. A matched filter with the reflected kernel, as in SILo, would place detections at
the event onset, but it changes event counts by +2% to +29% per session in a four-session test.
That is a change of method and is not part of this refresh.
