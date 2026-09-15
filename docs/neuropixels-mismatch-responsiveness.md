# Neuropixels mismatch responsiveness — analysis plan

Design document for adding per-unit, per-event responsiveness to Figure 10
(`fig-neuropixels-event-responses`).

Status: **draft for review.** Nothing in this plan has been implemented.
Branch: `edit/neuropixel-mismatch-responsiveness`.

---

## 1. Outcome

When this is done, the following should be true:

1. Figure 10 is built from mouse **830794** rather than 830846, because 830846's sensorimotor
   block cannot support a running-gated analysis (§3.2).
2. Every sorted unit in each of the four Neuropixels sessions has, for every mismatch event, a
   **within-block responsiveness** result (Q1) and a **mismatch-versus-control** result (Q2),
   each computed with a window rule appropriate to that context's stimulus structure.
3. Those results are committed as a reviewable tabular data product that can be inspected
   without rerunning the cloud extraction.
4. The interactive figure can restrict its unit set to responsive units.
5. The static figure shows example responsive neurons per mismatch condition and an
   area-level quantification comparing mismatch to control.
6. The interactive figure renders on an opaque white background in MyST.
7. The manuscript explains the method in prose so the caption does not have to.

Non-goals are listed in §11.

---

## 2. What the pipeline does today

Verified against the committed intermediate and the extractor on
`ce79fe5`.

| Stage | File |
|---|---|
| Cloud extractor | `scripts/extract_neuropixels_event_responses.py` (1237 lines) |
| Analysis helpers | `src/openscope_p3_publication/neural_responses.py` (290 lines) |
| Response metrics | `src/openscope_p3_publication/optotagging.py:253` |
| Intermediate | `figure_sources/data/neuropixels-event-responses.json` (15.7 MB) |
| SDF atlases | `figure_sources/media/neuropixels-event-responses/*.u16.gz` (~32 MB) |
| Interactive source | `figure_sources/javascript/neuropixels-event-responses.{html,css,js}` |
| Static generator | `src/openscope_p3_publication/neural_response_figure.py` |
| Figure directive / caption | `index.md:966` / `index.md:972` |

Four sessions, all from mouse **830846**, one per context.

### 2.1 The blocking constraint: no per-trial data survives

`histogram_trial_counts` sums spike counts across trials immediately
(`counts += trial_counts`), and `mean_rate_in_windows` returns a single averaged rate. Per
(event, condition, unit) the intermediate therefore holds only a trial-mean SDF, one scalar
response rate, and a baseline mean/std computed **across 20 ms bins, not across trials**.

No responsiveness test with a real error bar can be computed from the committed data. This
requires a re-extraction.

### 2.2 Machinery that already exists and should be reused

- **Neighbouring-row windows.** `extract_neuropixels_event_responses.py:374` already scans
  `range(-64, 65)` row offsets, enforces `same_block`, and averages the offset window across
  trials. It discards offsets falling outside the display window — that filter is the only
  reason the windows this plan needs are not already present.
- **Duration pre-delay window.** The extractor already emits
  `previousPresentationStartSeconds` / `previousPresentationStopSeconds` for the duration
  context — exactly the pre-delay stimulus window §4.4 requires.
- **Paired response metrics.** `compute_response_metrics` computes per-trial pre/post rates, a
  paired Wilcoxon signed-rank, and a modulation index
  `MI = mean_trials((post − pre) / (post + pre))`. The SST classification in this same figure
  already gates on `p < 0.05 AND MI > 0.1`. This is the house convention and should be the
  basis of the Q1 test.
- **Running data.** `figure_sources/data/running-statistics.json` holds 20 Hz forward-speed
  summaries with an established `threshold_cm_s = 1.0`.

---

## 3. Four problems found while verifying

### 3.1 The sequence baseline is wrong

`neural_responses.py:182-190` defines the sequence baseline as
`start_times[index - 1] → event_start` — the **immediately preceding sequence element**, which
for a substitution at element 3 is element 2, a 45° drifting grating.

It should be the grey inter-sequence interval.

**Verified directly against the NWB stimulus table** (`Sequence mismatch block_presentations`,
6240 rows, asset `03973a42`). The grey interval is a stimulus-table row with
`TrialType == "sequence_omission"`, appearing 1248 times — exactly 6240/5. Each sequence is
five rows. Offsets relative to the substituted element 3:

| Offset | Element | Verification |
|---|---|---|
| `−5` | element 3 of the **previous** sequence — the Q1 comparison | standard 0° in 120/140 |
| `−4` | element 4 of the previous sequence (45°) | |
| `−3` | **grey inter-sequence interval** — the correct baseline | `sequence_omission` in **140/140** |
| `−2` | element 1 (90°) | |
| `−1` | element 2 (45°) | |
| `0` | element 3, substituted | 35 each of halt, omission, orientation_45, orientation_90 |
| `+1` | element 4 (45°) | |
| `+2` | grey | `sequence_omission` in **140/140** |

Measured timing differs from the nominal design: rows are **266.9 ms**, not 250 ms, so the
sequence period is **1.3345 s**, not 1.25 s. The manuscript should quote measured values.
Rows are perfectly contiguous — inter-row gap is 0.0 ms at min, median, and max.

Offset `−5` therefore sits at exactly **−1.3345 s**, **outside the current `[−0.75, 0.75]`
window**.

**Consequence:** the sequence display window must widen for the Q1 comparison to be both
computable and visible. See §13.2 for the two candidate widths and their storage cost.

**Contamination is real, not hypothetical.** 20 of 140 mismatch trials have another
substitution within the previous five rows, which is exactly why only 120/140 have a clean
standard 0° at offset `−5`. Excluding them costs ~14% of trials, reducing each event from 35
to roughly 30.

An `orientation_45` substitution also produces three consecutive 45° elements (e2, e3, e4),
matching the "repeated element where a change was expected" description — confirmed in the
table.

### 3.2 Mouse 830846 cannot support a running-gated sensorimotor analysis — switch to 830794

In a closed-loop visuomotor block, optic flow is *generated by* locomotion. If the animal is
not running there is no flow, so "freezing the grating" is physically a no-op — the mismatch
event does not exist as a stimulus. Stationary trials are not noisy measurements of a mismatch
response; they are measurements of nothing. Running gating is therefore a validity requirement,
not statistical hygiene.

Measured per-trial running for all 16 sensorimotor sessions, requiring mean forward speed to
clear threshold in **both** the 343 ms pre-event window and the 350 ms mismatch window
(`processing/running/running_speed`, 60 Hz, cm/s, ~20 samples per window):

| Mouse | Block mean | Median | Running % | Trials ≥1 cm/s (min/type) | ≥5 cm/s (min/type) |
|---|---|---|---|---|---|
| 848387 | 70.63 | 78.24 | 97.5% | 138 (34/35) | 137 (33) |
| **830794** | **23.42** | **24.56** | **94.5%** | **134 (31/35)** | **124 (29)** |
| 832691 | 4.27 | 2.79 | 69.3% | 88 (19) | 37 (6) |
| 830849 | 3.43 | 0.76 | 49.1% | 66 (14) | 32 (6) |
| 830847 | 2.67 | 0.76 | 49.7% | 57 (11) | 15 (1) |
| 834686 | 1.67 | 0.38 | 39.9% | 34 (5) | 5 (0) |
| **830846** | **1.12** | **0.00** | **19.1%** | **21 (4/35)** | 14 (2) |
| 9 others | ≤ 1.10 | 0.00 | ≤ 20% | ≤ 26 | ≤ 7 |

Median block speed is **0.00 cm/s in 11 of 16 sessions** — most animals are stationary for more
than half the block. 830846 ranks 7th of 16 and retains only **4 trials in its worst event
type**, below any usable minimum.

**Decision: switch all four sessions to mouse 830794.** It runs in every context, has the
highest QC unit count in the dataset, and retains 29/35 trials per type even at a 5 cm/s
threshold. The one-mouse framing is preserved.

| | 830846 (was) | **830794 (now)** |
|---|---|---|
| Total sorted units | 13,682 | 12,060 |
| QC-passing units | 7,266 | **8,118** |
| Context speeds (std/seq/dur/sm) | 11.1 / 31.8 / **none** / 1.1 | 6.6 / 19.4 / 18.7 / **23.4** |
| Sensorimotor trials ≥5 cm/s | 14 (min 2) | **124 (min 29)** |

830846's duration NWB has **no processed running series at all**, which Supplementary Figure 6
already discloses; 830794 has running in all four.

New session identifiers for `NEURAL_SESSIONS` in `neural_responses.py:52`:

| Context | Date | `session_id` | `asset_id` | Probes | QC units |
|---|---|---|---|---|---|
| sensorimotor | 2026-01-26 | `830794_2026-01-26_12-02-05` | `0c67a84f-7da3-44b2-b707-72ab376a9034` | 6 | 2,725 |
| standard | 2026-01-27 | `830794_2026-01-27_11-25-31` | `a23eba88-5d08-4e4b-89e1-a2a10fd143b5` | 5 | 1,799 |
| sequence | 2026-01-28 | `830794_2026-01-28_11-01-44` | `6068eec9-d614-471c-aa33-0ab27dc66475` | 5 | 1,833 |
| duration | 2026-01-29 | `830794_2026-01-29_11-12-57` | `b383b4ff-a2b9-4497-8c8f-9f77de89e1b0` | 6 | 1,761 |

All four `asset_path` values follow `sub-830794/sub-830794_ses-ecephys-830794-<date-time>_ecephys.nwb`.

**Consequences:** every figure value, unit count, and caption number changes, so this is a full
re-extraction of all four sessions rather than an incremental edit. 848387 was rejected despite
better running because at 70–77 cm/s it is a ~70× outlier against the cohort median and would
be fairly criticised as unrepresentative.

### 3.3 The sensorimotor 2 s minimum inter-mismatch interval is not honoured

The protocol specifies a minimum 2 s separation between consecutive sensorimotor mismatch
events. Verified against the released NWBs for subjects 820454 and 830846:

| Measure | Value |
|---|---|
| Mismatch events per session | 140 (35 × 4 types) |
| Pairs with onset-to-onset gap < 2.0 s | **19** |
| Pairs < 1.0 s | 7 |
| Pairs < 0.5 s | 2 |
| Minimum onset-to-onset gap | **0.450 s** |
| Minimum offset-to-onset gap | **0.100 s** |

The tightest pair is a `motor_omission` followed 100 ms later by a `motor_halt`. Mismatch rows
are 350.3 ms; the surrounding `standard` rows are 33.4 ms phase updates at 30 Hz.

**The mismatch *schedule* is pre-generated and identical across sessions — but the sensorimotor
*stimulus* is not.** Verified across all 60 Neuropixels NWBs by hashing each interval table's
full row-by-row `TrialType` sequence, mismatch row indices, and orientation/delay columns:

| Block | Rows | TrialType | Ori + Delay | Relative timing |
|---|---|---|---|---|
| Standard context | 2274 | identical | identical | 15 distinct |
| Sequence context | 6240 | identical | identical | 15 distinct |
| Duration context | 2274 | identical | identical | 14 distinct |
| Sensorimotor context | 45461 | identical | identical | 16 distinct |
| Controls 1–4 | 1088 / 1120 / 368 / 11520 | identical | identical | 60 distinct each |

Timing differences are display-refresh jitter — about 1 ms over a 26-minute block for most
tables.

The distinction matters for the sensorimotor block specifically: the table records *when*
visual flow was decoupled, which is pre-scheduled, but not the grating *phase*, which is driven
by locomotion. Each animal therefore saw a different stimulus despite an identical schedule.
An earlier draft of this section wrongly described the sensorimotor stimulus itself as
identical across sessions.

Consequences:

1. Sensorimotor needs the same adjacency exclusion as the other contexts.
2. The adjacency statistic is a fixed property of the protocol, so the supplemental figure
   (§14) should characterise the protocol once rather than plot a per-session distribution.
3. Which scheduled sensorimotor events are actually analysable still varies per animal,
   because that depends on running (§3.2).

**Two anomalies found in passing**, neither affecting this figure but both worth reporting:
Control block 1 varies by **101.9 s** in duration across sessions (2322.2–2424.2 s) despite
identical trial types and row count, and **RF mapping exists in two stimulus versions**
(1214 vs 1215 rows, with genuinely different trial-type and orientation content).

### 3.4 Regenerating the atlases triggers CONTRIBUTING's binary-review rule

Re-extraction rewrites all four `.u16.gz` atlases (~32 MB), and widening the sequence window
grows that file from 7.6 MB to roughly 12 MB. Every rewritten file is a new blob in git
history. CONTRIBUTING requires maintainer review for any pull request adding more than 25 MiB
of binary content in total, so **this PR needs maintainer approval by policy**, independent of
whether the science is right. Worth raising before the work starts, not at review time.

---

## 4. Q1 — Within-block responsiveness

The organizing principle, taken from your framing: responsiveness is **local and
stimulus-structure-aware**. The comparison is the mismatch event against the most recent
instance of what the animal expected, in the same block, rather than against a generic
pre-stimulus baseline.

For every context the per-trial quantities are spike *rates* in spikes/s, so unequal window
durations normalize out.

### 4.1 Standard oddball

Deviants (45°, 90°, halt, omission) occur at 1.35/min each against a high-probability 0°
standard.

- **Test window:** the deviant presentation, offset `0` — `(0.000, 0.367)`.
- **Comparison window:** the preceding presentation, offset `−1` — `(−0.701, −0.334)`. This is
  the expected standard stimulus.
- **Pairing:** within trial. `n` = number of deviant trials (35).
- **Baseline subtraction:** optional and configurable. Both windows are stimulus presentations
  of equal duration in the same block seconds apart, so subtraction is not required to control
  for drift. Default **off**; store the values needed to turn it on.

**Hygiene:** exclude any deviant whose offset `−1` row is itself a deviant. At a combined
5.4/min this is rare but must be enforced rather than assumed, and the excluded count
reported.

### 4.2 Sensorimotor

Closed-loop optic flow, transiently decoupled for 343 ms. Mismatch types: motor halt, motor
omission, motor orientation 45°/90°, each 1.35/min.

There is no discrete preceding trial — flow is continuous — so this context alone uses a
baseline comparison, consistent with the existing rule.

- **Test window:** the mismatch presentation, offset `0` — `(0.000, 0.350)`.
- **Comparison window:** the 343 ms immediately preceding `start_time`.
- **Pairing:** within trial.
- **Running gate (new):** a trial is included only if mean forward speed clears threshold in
  **both** the comparison window and the test window. Requiring both matters — gating on the
  event window alone would admit trials where the animal only started moving in response to
  the mismatch.
- **Threshold:** **5.0 cm/s**, not the 1.0 cm/s in `extract_running_statistics.py:39`. That
  value was chosen to describe whether an animal was locomoting at all; here the premise is
  self-generated optic flow, and at 1 cm/s there is barely any flow to freeze. With 830794 the
  stricter threshold is affordable: 124/140 trials survive, 29/35 in the worst event type
  (versus 134 and 31/35 at 1.0 cm/s). Report the 1/2/5/10 cm/s ladder in provenance so the
  choice is auditable.
- **Availability rule:** if fewer than **8** trials survive for an event, that event is
  recorded as unavailable rather than estimated. With 830794 this no longer binds — the worst
  case is 29 — but it stays in place as a guard.
- **Adjacency hygiene (see §3.3):** the design's 2 s minimum inter-mismatch interval is **not
  honoured in the released data**. Exclude mismatches whose preceding mismatch onset is less
  than 2 s earlier: 19 of 140 events. This overlaps with the running exclusion, so the
  combined surviving count must be reported rather than inferred from either rule alone.

This requires the extractor to read the processed running-speed series from the sensorimotor
NWB, which it does not currently do. `extract_pupil_event_responses.py` already does exactly
this and is the pattern to copy.

### 4.3 Sequence

Five-element sequences (90°–45°–0°–45°–grey), with element 3 substituted.

- **Test window:** substituted element 3, offset `0` — `(0.000, 0.267)`.
- **Comparison window:** element 3 of the **previous** sequence, offset `−5`, at
  **−1.3345 s** — the same physical position in the sequence, normally 0°.
- **Pairing:** within trial.
- **Baseline:** offset `−3`, the grey inter-sequence interval. **This is a correction to the
  existing analysis** (§3.1) and changes the published baseline z-scores, so it must be
  disclosed in the caption and the changelog.
- **Window:** must widen to reach −1.3345 s; see §13.2.
- **Display:** draw vertical guides at every element boundary, not only at the mismatch onset.

**Hygiene:** exclude mismatch sequences whose previous sequence also contained a substitution
— **20 of 140 trials, verified**, leaving ~30 per event rather than 35.

### 4.4 Duration

The stimulus is invariant; the inter-stimulus interval is manipulated (150, 500, 1000 ms
deviants, plus omission) against a standard 343 ms stimulus / 343 ms delay structure.

Because the manipulation is temporal, the response of interest is to the stimulus that
*follows* the violated delay.

- **Test window:** the post-delay stimulus, offset `0` — `(0.000, 0.367)`.
- **Comparison window:** the pre-delay stimulus, offset `−1`. Already computed as
  `previousPresentationStartSeconds` / `previousPresentationStopSeconds`.
- **Pairing:** within trial.
- **Baseline:** unchanged — offset `−2` stop through offset `−1` start, the standard
  unmanipulated interval, deliberately excluding the manipulated delay.

**Open caveat.** This measures the response to the post-delay stimulus, not a sustained
response *during* the delay. If units ramp during an extended delay, this window misses it.
A delay-window statistic is not proposed here to avoid a fifth window definition, but the
per-trial storage in §6 makes it addable later without re-extraction. Flagged in §13.

### 4.5 Summary

| Context | Test window | Comparison window | Baseline | Gate |
|---|---|---|---|---|
| Standard | offset `0` | offset `−1` (expected standard) | offset `−1` stop → event start | prev row not a deviant |
| Sensorimotor | offset `0` | 343 ms pre-event | same as comparison | **running ≥ 1.0 cm/s** |
| Sequence | offset `0` (element 3) | offset `−5` (prev element 3) | offset `−3` (**grey**, corrected) | prev sequence clean |
| Duration | offset `0` (post-delay) | offset `−1` (pre-delay) | offset `−2` stop → `−1` start | — |

---

## 5. Q2 — Mismatch versus control

Same windows as §4, applied across blocks. Trial counts are unequal and the blocks are
recorded at different times, so these tests are **unpaired** (Mann-Whitney U).

| Context | Quantity compared | Baseline-subtracted? |
|---|---|---|
| Standard | deviant response vs. same stimulus in control block C1 | **Yes** |
| Sensorimotor | running-gated mismatch vs. same event in open-loop C4 | Yes |
| Sequence | substituted element 3 vs. same event type in C2 | **No** — C2 has no sequence structure or grey interval, so no comparable baseline exists |
| Duration | (post-delay − pre-delay) in mismatch vs. the same difference in C3 | Implicit in the difference |

Duration is a difference-of-differences: the per-trial quantity is already
`response(offset 0) − response(offset −1)` in both blocks, so the test asks whether the delay
violation changes that difference.

**Trial counts available for Q2:** standard 35 vs 68, sequence 35 vs 70, duration 35 vs 46,
sensorimotor **35 vs 8** — and the sensorimotor mismatch side shrinks further under the
running gate. Sensorimotor Q2 is the weakest comparison in the figure and should be labelled
as such.

**Sequence transition matching — resolved: not feasible.** You asked whether the 45°→90°
transition could be matched between blocks. Verified against `Control block 2_presentations`
(1120 rows): it contains 980 `single` rows spread over **14 orientations** (0° through 292.5°
in 22.5° steps), plus 70 `halt` and 70 `omission`, and **no `sequence_omission` rows at all**.
A specific ordered orientation transition would occur roughly 4–5 times by chance. Drop this
comparison.

The same inspection confirms the decision not to baseline-subtract the sequence Q2 contrast:
C2 has no grey inter-sequence interval, so no comparable baseline exists.

---

## 6. Statistics

### 6.1 Tests

| Question | Test | Effect size |
|---|---|---|
| Q1 within-block | paired Wilcoxon signed-rank on per-trial (test − comparison) | `MI = mean_trials((test − comp) / (test + comp))` |
| Q2 mismatch vs control | Mann-Whitney U on per-trial values | difference of medians, and MI on block means |

Q1 reuses `compute_response_metrics`, generalized to accept explicit per-trial window arrays
instead of its current fixed-width pre-window. Keep the existing signature as a thin wrapper
so the optotagging path and `tests/test_figures.py:398` are untouched.

### 6.2 Power is genuinely limited — disclose it

The median QC-passing unit fires ~2 spikes per trial in a ~0.37 s window; the 10th-percentile
unit fires ~0.5. Per-trial rates are highly discrete, ties and zero-differences are common
(`zero_method="zsplit"` handles them), and a unit firing zero spikes on most trials cannot
reach significance at any effect size. This is a property of the data, not a defect in the
method, and belongs in the caption.

### 6.3 Multiple comparisons — the discussion you asked for

**The arithmetic.** Roughly 1,500 QC-passing units per session × 4 events × 2 tests. At an
uncorrected α = 0.05, about **75 units per event per test** are expected to be called
responsive by chance alone.

Whether that matters depends entirely on the true effect size:

| True responsive fraction | True positives | Chance positives | Resulting FDR |
|---|---|---|---|
| 5% (75 units) | ~75 | ~75 | **~50%** — half your "responsive" units are noise |
| 20% (300 units) | ~300 | ~75 | ~20% |
| 40% (600 units) | ~600 | ~75 | ~11% |

So the answer is not knowable in advance. If mismatch responses are sparse — which is the
interesting scientific possibility — an uncorrected analysis is actively misleading.

**But correction is not automatically right either.** Benjamini–Hochberg costs power, and §6.2
establishes that power is already marginal. In a low-power regime, aggressive correction can
eliminate most true positives and produce a misleadingly sparse result.

**The resolution is that you are asking two different questions, which need two different
treatments.**

1. *"Is this particular unit responsive?"* — needed when selecting example neurons for the
   static figure, or when a reader filters the interactive figure down to one unit. This is a
   per-unit claim and **does** need correction. Use Benjamini–Hochberg within each
   (session, event, test) family and gate on `q < 0.05`.

2. *"Is this area responsive?"* — needed for the per-area quantification. This is a population
   claim, and per-unit correction is the wrong tool. Instead ask whether the *count* of
   significant units in an area exceeds chance, with a binomial test against the expected
   α × n. This is more powerful, more directly answers the question, and sidesteps the
   correction debate entirely.

**Recommendation:** store raw `p` and BH `q` for every test so either can be used. Gate the
interactive filter and example-neuron selection on `q < 0.05` plus an MI floor. Quantify areas
with the binomial count test, and plot the chance-level expectation as a reference line so the
reader can see it directly.

**One caveat to state plainly:** example neurons chosen as the strongest responders are
selected on the same statistic used to test them. They are illustrative, not inferential, and
the caption should say so.

### 6.4 Thresholds

| Parameter | Proposed | Basis |
|---|---|---|
| Significance | `q < 0.05` (BH within session × event × test) | §6.3 |
| Effect-size floor | `MI > 0.1` | matches existing SST classification |
| Running gate | `≥ 1.0 cm/s` | matches `running-statistics.json` |
| Minimum trials | 8 after gating | judgement — needs sign-off (§13) |

---

## 7. Data product

A standalone, reviewable table of responsiveness for every unit in every session.

**Format: CSV**, at `figure_sources/data/neuropixels-mismatch-responsiveness.csv`.

Rationale: CONTRIBUTING directs small tabular inputs to `figure_sources/data/`, the repository
already has `neuropixels-unit-yield.csv` as precedent, CSV is diffable and reviewable in a
pull request, and it adds no dependency. Parquet would be more compact but is binary,
undiffable, and would add `pyarrow` to a dev-dependency list currently limited to numpy,
pytest, and ruff. JSON is the house format for nested payloads, but this data is flatly
rectangular.

Estimated size: ~55,000 rows (all sorted units × 4 events × 4 sessions) at ~12 columns ≈ 4–5
MB. Under the 10 MiB threshold, to be confirmed on generation.

Proposed columns:

```
session_id, context, event_id, unit_id, probe, location, parent_area,
neuron_type, qc_pass, firing_rate_hz,
q1_n_trials, q1_test_hz, q1_comparison_hz, q1_modulation_index, q1_p, q1_q, q1_responsive,
q2_n_mismatch, q2_n_control, q2_mismatch_hz, q2_control_hz, q2_modulation_index, q2_p, q2_q, q2_selective,
running_gated, available
```

The interactive figure does not read the CSV directly. Per CONTRIBUTING's deployment-copy
pattern, `build-publication-figures` folds a compact per-unit payload into the existing
`neuropixels-event-responses.json` and generates the ignored copy under `interactive/`.

**Per-trial scalars.** The extractor additionally retains, per (event, condition, unit), the
per-trial test-window and comparison-window rates. This is what makes every threshold, test,
and baseline-subtraction choice in this document revisable **without rerunning the cloud
extraction** — the expensive stage is paid once. Cost is roughly 5 MB uncompressed per
session as quantized integers. Per-trial *time series* are explicitly not retained; they would
multiply the 32 MB of atlases by 35–68.

---

## 8. Interactive figure changes

1. **Opaque white background.** The figure currently renders transparent in MyST. Set an
   explicit background on the page root in
   `figure_sources/javascript/neuropixels-event-responses.css` rather than relying on the
   host. Verify in both MyST light and dark themes.
2. **Responsiveness filter.** A select control, not a checkbox, because "responsive" is
   ambiguous:
   - All units *(current behaviour, default)*
   - Responsive to the selected event (Q1, `q < 0.05` & MI > 0.1)
   - Responsive to any event in this context
   - Mismatch-selective for the selected event (Q2)
   The selected-unit count must update visibly so a reader can see how many units a filter
   removes.
3. **Sequence element guides.** Vertical lines at all five element boundaries, with the
   substituted element distinguished.
4. **Sensorimotor running disclosure.** Show surviving trial count per event and mark events
   falling below the minimum as unavailable rather than plotting an unreliable estimate.

## 9. Static figure changes

Load the `dataviz` skill before implementing; no panel design is committed here.

- **Panel A — example responsive neurons per mismatch condition.** Per context, a small number
  of units passing Q1, showing the test and comparison windows explicitly.
- **Panel B — per-area quantification.** Responsive fraction by area and event, with the
  binomial chance level drawn as a reference (§6.3).
- **Panel C — mismatch versus control.** The Q2 contrast per area.

Existing panels are not preserved by default; what they become is a design question for the
next round.

## 10. Manuscript text

You asked to carry the explanation in prose and keep the caption shorter. The current caption
(`index.md:972`) is already 740 words and cannot absorb four window definitions and two
statistical tests.

Proposal: add a short methods subsection to the existing
"Neuropixels mismatch responses across predictive contexts" section defining the per-context
windows (the §4.5 table renders well as prose or a manuscript table), the two tests, the
thresholds, and the running gate. The caption then names the panels, states that
responsiveness is defined per context in the text, and retains only what a reader needs at the
figure: sample sizes, exclusions, and the selection-bias note from §6.3.

The sequence baseline correction (§3.1) must be stated explicitly as a change from the
previously published version.

---

## 11. Scope

**In scope:** switching the four sessions from mouse 830846 to mouse 830794 (§3.2);
responsiveness computation;
per-trial scalar retention; the running gate for sensorimotor; the sequence baseline fix and
window widening; the CSV data product; the interactive background fix and filter; the static
panels; caption and manuscript text; tests.

**Out of scope:** more than one mouse in the main figure; changes to alignment, bin size, or
the SDF kernel; the other nine figures; the `ruff format` question; `notebooks/`. The
`compute_response_metrics` refactor must leave the existing signature and the optotagging path
behaviourally unchanged.

**Note on the mouse switch:** because every figure value, unit count, area list, Rastermap
ordering, and caption number derives from the source sessions, this is a full re-extraction and
a full caption rewrite, not an incremental edit. Nothing from the current Figure 10 numbers
survives. That argues for landing §14 (adjacency) and §15 (running) as their own pull requests
first, so the large re-extraction PR carries only the responsiveness change.

---

## 12. Verification

Per CONTRIBUTING and `prompting-conventions`, evidence rather than assertion:

```bash
uv run --extra dev ruff check .
uv run --extra dev pytest
uv run build-publication-figures
git diff --exit-code -- interactive images/figures/generated
myst build --html
```

Plus, specific to this change:

1. Unit tests for each context's window selection against a synthetic stimulus table with
   known row structure — in particular that sequence resolves offset `−5` and `−3` correctly.
2. A test that a synthetic unit with a known injected response is called responsive, and a
   Poisson unit with no response is not, at the stated thresholds.
3. A test that `compute_response_metrics` returns identical values for the optotagging path
   before and after the refactor.
4. Reported counts of responsive units per context, per event, and per area, with chance
   levels — for scientific sanity-checking, not just green tests.
5. Reported surviving trial counts for the sensorimotor running gate.
6. Confirmation that the regenerated CSV is under 10 MiB and the total binary delta is
   declared for maintainer review (§3.4).
7. Visual check of the interactive figure in MyST light and dark themes at desktop and mobile
   widths.

---

## 13. Decisions needed before implementation

1. ~~**Minimum trial count** for the sensorimotor running gate.~~ **Resolved by the switch to
   830794** (§3.2). The rule stays at 8 as a guard but no longer binds: the worst event type
   retains 29 trials at a 5 cm/s threshold. Confirm 5.0 cm/s is the threshold you want.
2. **Sequence window width.** Must reach at least −1.3345 s (offset `−5` start) and ideally
   −1.0676 s (its stop). Two candidates, at 2.5 ms bins:

   | Window | Span | Bins | Atlas est. | Shows |
   |---|---|---|---|---|
   | `[−1.6, 0.8]` *(recommended)* | 2.4 s | 960 | ~12 MB | full current sequence, plus back through e3 of the previous sequence |
   | `[−2.0, 0.8]` | 2.8 s | 1120 | ~14 MB | both sequences complete, e1 of the previous sequence onward |

   Current is `[−0.75, 0.75]`, 600 bins, 7.6 MB. The wider option is the only one that shows
   two complete sequences, but costs ~2 MB more and widens every heatmap. Recommend
   `[−1.6, 0.8]` unless you want the full previous sequence plotted.
3. **Baseline subtraction default for Q1 standard.** Proposed off.
4. **Delay-window statistic for duration** (§4.4) — add now, or defer given per-trial storage
   makes it cheap later? Recommend defer.
5. ~~**Whether the sensorimotor context should use a different mouse.**~~ **Resolved: switch
   all four sessions to 830794** (§3.2). Note the reasoning that made this cheap — the caption
   already states units are not longitudinally matched across sessions, so the one-mouse
   framing buys consistency of animal, not unit identity.
6. ~~**Confirmation of the 5-row sequence structure** against the NWB stimulus table.~~
   **Resolved.** Verified directly against the NWB: grey is a `sequence_omission` row at
   offset `−3` and `+2` in 140/140 mismatch trials, 1248 grey rows = 6240/5. The assertion
   should still be encoded in the extractor so it fails loudly if upstream data changes.
7. **Supplemental adjacency figure** (§14) — confirm the panel design and whether it ships in
   this pull request or its own.

---

## 14. Supplemental figure: consecutive-mismatch adjacency

### 14.1 Why it matters

A mismatch that immediately follows another mismatch is not equally surprising: the animal has
not re-established the standard context in between. Every downstream analysis of these blocks
inherits this, so the fraction is worth publishing as a characterisation of the released data
rather than buried in an exclusion rule.

### 14.2 Verified numbers

Measured across all 60 Neuropixels NWBs. Because each block uses one pre-generated schedule
(§3.3), these counts are **identical in every session** — there is no across-session variance
to plot.

| Context | Adjacency rule | Mismatch events | Adjacent | Fraction | Of those, same type |
|---|---|---|---|---|---|
| Standard oddball | previous presentation is also a deviant | 140 | 13 | **9.3%** | **1** |
| Sequence | previous sequence also contained a substitution | 140 | 20 | **14.3%** | **4** |
| Duration | previous presentation is also a deviant | 140 | 13 | **9.3%** | **6** |
| Sensorimotor | previous mismatch onset < 2 s earlier | 140 | 19 | **13.6%** | 4 |

Sessions per context: standard 15, sequence 15, duration 14, sensorimotor 16.

Notes:

- **Duration is the worst case for same-type repeats** — 6 of 13 adjacent pairs repeat the same
  deviant delay, so the second event is both un-reset and identical.
- **Standard is the mildest** — only 1 of 13 adjacent pairs repeats the same deviant type.
- **Sensorimotor violates its own design minimum** (§3.3): 19 pairs under 2 s, 7 under 1 s, 2
  under 0.5 s, floor 0.450 s onset-to-onset and 0.100 s offset-to-onset.
- Excluding adjacent mismatches costs **9–14%** of trials, leaving roughly 30–32 of 35 per
  event type.

### 14.3 Proposed panels

Load the `dataviz` skill before implementing. Because the schedule is fixed, this is a
protocol characterisation, so the figure should be compact.

- **A — Realised mismatch schedule.** One horizontal timeline per context showing every
  mismatch event, coloured by type, with adjacent pairs marked. Makes the clustering visible
  rather than merely tabulated.
- **B — Inter-mismatch interval distribution.** Per context, a histogram of the interval to the
  previous mismatch, in the natural unit (presentations, sequences, or seconds), with the
  design-intended minimum drawn as a reference line — which shows the sensorimotor violation
  directly.
- **C — Adjacency summary.** The §14.2 table as a grouped bar chart: fraction adjacent per
  context, split into same-type and different-type.

### 14.4 Implementation

Follows the standard architecture. The extractor reads only interval tables, so it is cheap
compared with the other extractors in this repository — no spike data, no per-probe work.

| Stage | Path |
|---|---|
| Extractor | `scripts/extract_mismatch_adjacency.py` |
| Intermediate | `figure_sources/data/mismatch-adjacency.json` + `.provenance.json` |
| Static generator | `src/openscope_p3_publication/` (new module or an existing figure module) |
| Output | `images/figures/generated/supplementary-mismatch-adjacency.svg` |
| Tests | `tests/` — assert the per-context counts above against a synthetic table |

The extractor must assert the schedule-identity property it relies on, so the figure fails
loudly rather than silently averaging if a future data release randomises the schedules.

**Recommendation on sequencing:** ship this as its **own pull request, before** the
responsiveness work. It is small, independently useful, has no binary-size implications, and
its numbers justify the exclusion rules that the responsiveness analysis depends on.

Working scripts already exist in the session scratchpad
(`mismatch_adjacency.py`, `schedule_identity.py`, `schedule_identity2.py`) and can be promoted
into `scripts/` rather than rewritten.

---

## 15. Supplemental figure: locomotion during the sensorimotor block

### 15.1 Why it matters

The sensorimotor block is a closed-loop visuomotor paradigm: optic flow is generated by the
animal's own locomotion. A mismatch event decouples flow from locomotion — but if the animal is
stationary there is no flow to decouple, so the event is not a stimulus at all. How much each
animal ran therefore determines whether its sensorimotor data is interpretable, and that is not
currently documented anywhere in the publication.

It is also the evidence base for the session switch in §3.2, so publishing it makes that
choice reviewable rather than asserted.

### 15.2 Verified numbers

Measured across all 16 Neuropixels sessions containing a sensorimotor block. Source:
`processing/running/running_speed` (60 Hz, cm/s); forward speed is `max(velocity, 0)` per the
convention in `extract_running_statistics.py:390`. A trial qualifies when mean forward speed
clears threshold in **both** the 343 ms pre-event baseline window and the 350 ms mismatch
window (~20 samples each).

The full ranked table is in §3.2. Headline findings:

- **Median block speed is 0.00 cm/s in 11 of 16 sessions.** Most animals are stationary for
  more than half the block.
- **Only 2 of 16 sessions run substantially**: 848387 (70.6 cm/s, 97.5% running) and 830794
  (23.4 cm/s, 94.5%).
- **Cohort median block speed is ~1.0 cm/s**, which is also the repository's existing running
  threshold — meaning the median session sits exactly at the detection floor.
- Surviving trials at 5 cm/s range from **137 of 140** (848387) down to **0** (several
  sessions), with the worst-event-type count ranging 33 to 0.
- Control block 4 (open-loop) contains only **8 mismatch trials per type, 32 total**, versus
  140 in the context block — so the Q2 sensorimotor comparison is trial-limited on the control
  side regardless of running.

### 15.3 Proposed panels

Load the `dataviz` skill before implementing.

- **A — Session ranking.** One row per session: block mean forward speed with median and p90,
  ordered by mean. Mark the cohort median and the running threshold. Makes the bimodality
  obvious — two runners, fourteen largely stationary animals.
- **B — Surviving trials versus threshold.** For each session, trials qualifying at 1, 2, 5,
  and 10 cm/s, so a reader can see how threshold choice interacts with session choice.
- **C — Worst-event-type count.** The number that actually limits a per-event analysis, with
  the minimum-trial rule drawn as a reference line. This is the panel that justifies §3.2.

Optionally a speed distribution for the selected session, showing where the gated trials fall.

### 15.4 Implementation

| Stage | Path |
|---|---|
| Extractor | `scripts/extract_sensorimotor_running.py` |
| Intermediate | `figure_sources/data/sensorimotor-running.json` + `.provenance.json` |
| Static generator | `src/openscope_p3_publication/` |
| Output | `images/figures/generated/supplementary-sensorimotor-running.svg` |
| Tests | `tests/` — window-mean gating against a synthetic running series |

Reads only the running series and interval tables, so it is inexpensive. A working script
exists at `sensorimotor_running.py` in the session scratchpad and can be promoted into
`scripts/`.

**Recommendation on sequencing:** ship alongside or just after §14, and before the
responsiveness re-extraction. Both supplementals are small, carry no binary-size burden, and
together they document the two data-quality constraints (adjacency and locomotion) that shape
the main analysis.

---

## 16. Recommended pull-request sequence

| # | Pull request | Contents | Size |
|---|---|---|---|
| 1 | Adjacency supplemental (§14) | extractor, JSON intermediate, static SVG, tests, caption | small |
| 2 | Locomotion supplemental (§15) | extractor, JSON intermediate, static SVG, tests, caption | small |
| 3 | Responsiveness (§4–§10) | mouse switch to 830794, per-trial extraction, responsiveness CSV, regenerated atlases, interactive filter and white background, static panels, caption and manuscript text, tests | **large — needs maintainer binary review (§3.4)** |

PR 3 is large and unavoidably so, because the mouse switch invalidates every current Figure 10
value. Splitting the supplementals out keeps its diff limited to the responsiveness change plus
the re-extraction, rather than mixing in two independent analyses.
