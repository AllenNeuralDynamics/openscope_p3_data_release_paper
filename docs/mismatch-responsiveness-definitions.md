# Defining a responsive unit per mismatch context

A short, self-contained statement of how we decide whether a single unit responded to a
mismatch event in the OpenScope Predictive Processing (P3) Neuropixels data. Written to be
shared on its own; it assumes no knowledge of the publication repository.

The long version, including the reasoning behind each choice and what was rejected, is
`docs/neuropixels-mismatch-responsiveness.md`. The shipped manuscript text is the
"Defining responsiveness per mismatch event" subsection of `index.md`.

## The idea

A mismatch is only surprising relative to the expectation it violates, and each of the four
context blocks builds that expectation differently. So there is no single baseline that works
across contexts. Instead, **each deviant is compared with the most recent instance of the
stimulus it replaced, in the same block and the same unit.**

## Windows, per context

Rows refer to the NWB stimulus table for the context block; row *i* is the mismatch.

| Context | Test window | Comparison window | Baseline |
|---|---|---|---|
| **Standard oddball** | deviant presentation, row *i* | preceding expected standard, row *i−1* | preceding inter-stimulus interval |
| **Sequence** | substituted element three, row *i* | element three of the previous sequence, row *i−5* (−1.3345 s) | grey inter-sequence interval, row *i−3* |
| **Duration** | post-delay stimulus, row *i* | pre-delay stimulus, row *i−1* | standard ISI, row *i−2* stop → row *i−1* start |
| **Sensorimotor** | mismatch window | 343 ms immediately before event onset | the same 343 ms window |

Notes on the two irregular cases:

- **Sensorimotor** has no preceding trial. Closed-loop optic flow is continuous, so the
  comparison is simply the flow immediately before the decoupling.
- **Duration** gets a second test, because the manipulation changes the delay itself and the
  post-delay comparison above does not test that. Firing during the violated delay
  (row *i−1* stop → row *i* start) is compared with firing during a standard delay in the same
  trial (row *i−2* stop → row *i−1* start). Deviant delays of 150, 500, and 1000 ms give
  windows of unequal length, so rates are compared rather than counts.

## The two tests

**Q1 — against the unit's own expectation.** Is the unit driven differently by the mismatch
than by the most recent expected instance in the same block? Paired Wilcoxon signed-rank
across trials (`zero_method="zsplit"`).

Both members of a pair subtract the same per-trial baseline, so the paired difference cancels
it: **the Q1 p value is identical with and without baseline subtraction**, and only the
modulation index changes.

**Q2 — against the matched control block.** Is the mismatch response different from the same
physical event in the control block? Mann-Whitney *U*, unpaired — trial counts differ between
blocks and the blocks are recorded at different times.

Both tests are **two-sided**, because a mismatch can reduce firing. Across the four contexts
44% of responsive unit-event pairs are suppressed rather than enhanced (40% in sensorimotor
to 58% in duration), so a one-sided rule would discard nearly half the signal.

## Thresholds

A unit counts as **responsive** at an event when:

- uncorrected **p < 0.05**, and
- **|modulation index| > 0.1**

where the modulation index is the trial-wise mean of
`(test − comparison) / (test + comparison)`, matching the convention used for SST optotagging
elsewhere in the release.

## Trial hygiene

- A mismatch **preceded by another mismatch is excluded**, because its comparison window is
  not an expected stimulus.
- For **sequence**, the whole previous sequence must be free of substitutions.
- **Sensorimotor** trials additionally require mean forward speed ≥ **5 cm/s in both** the
  pre-event and mismatch windows — a stationary animal has no self-generated flow to
  decouple, so the event is not a stimulus — and must fall at least **2 s** after any other
  mismatch. The released data does not honour that 2 s protocol minimum on its own.

## On multiple comparisons

We report the **uncorrected p and display the chance expectation alongside every count**, so
the noise floor is always visible. Benjamini–Hochberg values over each units-by-event family
are computed and released beside every p value for readers who want the stricter screen.

Be aware how weak the uncorrected screen is on this data. Measured over QC-passing units, the
responsive fraction runs **0.6 to 7.1 times the 5% chance level, median 3.1**, implying a
false-discovery proportion of roughly **14 to 38%** across the twelve non-duration events. The
three duration delay events sit **at or below chance** — `delay_500` finds 49 units where
chance alone predicts 85 — and at none of the three does a single unit survive correction. Correction is not cosmetic here: it removes 26 to 58% of
the nominal survivors at the other thirteen events. Use the released q values for any quantitative
claim; the uncorrected fraction is an exploratory screen with its noise floor drawn next to it.

## Two caveats specific to the sequence context

Both are forced by the structure of its control block (control block 2), and neither applies
to the other three contexts.

1. **Its control baseline is borrowed.** Control block 2 is contiguous — the inter-row gap has
   median, minimum, and maximum all 0.0 ms across its entire 298 s — so it contains no blank
   period to use as a baseline, and applying the sequence rule to it lands on an arbitrary
   drifting grating. Sequence control baselines instead come from the 333.6 ms blank ISIs of
   the control block 1 repeat that ends 0.3 s before control block 2 begins.

2. **Its control block has no sequence structure.** Control block 2 presents single gratings
   in random order, so away from the aligned event its average is over an arbitrary draw of
   14 orientations. Measured: the context trace carries 0.249 Hz of power at the 1.3345 s
   sequence period against the control trace's 0.048 Hz, which is no greater than the
   control's own 0.047 Hz at the element period.

   Consequently the **sequence Q2 contrast matches the stimulus but not its history.** Element
   three in the context block follows a fixed 90°–45° transition; the control block's matched
   row follows a random orientation. The contrast therefore conflates violating an
   established expectation with a difference in immediate stimulus history. Matching the
   transition is not possible — control block 2's 980 single-grating rows spread over 14
   orientations, so any specific ordered transition occurs 4–5 times by chance.

## What this yields

Fraction of QC-passing units responsive, pooled over the four events within each context, in
one mouse's four sessions. The chance floor implied by the p < 0.05 gate is **5%**.

| Region | Standard | Sensorimotor | Sequence | Duration |
|---|---|---|---|---|
| Visual thalamus | 46.6% | 49.6% | 44.4% | 20.7% |
| Visual cortex | 36.6% | 46.9% | 38.5% | 14.2% |
| Hippocampal | 5.5% | 14.7% | 7.9% | 5.3% |
| Frontal | 5.2% | 30.6% | 7.6% | 4.2% |

Three things the per-context definitions make visible:

1. **Visual areas respond to all four**, 37–50% in the first three contexts, falling to
   14–21% in duration — consistent with duration being the context where no unit survives
   multiple-comparisons correction.
2. **Frontal cortex is near chance in the passive contexts but not in the closed-loop one**:
   5.2%, 7.6%, and 4.2% against 30.6% in sensorimotor. Per area, MOs5 goes from 2–6% to
   23–32% and ACAd5 from 0–9% to 51–63%.
3. **The exception is the sequence halt.** Frontal areas are near chance for the sequence
   *substitutions* (MOs5 4–5%, ACAd5 2–9%) but respond to a halt in the sequence (MOs5 22%,
   ACAd5 34%). The pattern holds in both areas, so a halt — a temporal or motor violation —
   appears to engage frontal cortex where an identity substitution does not. Treat this as an
   observation from one mouse, not an established result.

## Reproducing this

- Per-unit statistics for every unit and event:
  `figure_sources/data/neuropixels-mismatch-responsiveness.csv` (51,872 rows, 32 columns,
  including `q1_p`, `q1_q`, `q1_modulation_index`, `q2_p`, `q2_delta_p`, and the delay-epoch
  test for duration).
- Windows, masks, modulation index, Benjamini–Hochberg, and classification:
  `src/openscope_p3_publication/mismatch_responsiveness.py`.
- Locomotion gating: `src/openscope_p3_publication/sensorimotor_running.py`.
- Source data: [Dandiset 001637](https://dandiarchive.org/dandiset/001637/draft/files).
  Note this is a **mutable draft** — 48 of 60 Neuropixels assets were replaced upstream in
  August 2026; pinned asset IDs and checksums are in the committed provenance.
