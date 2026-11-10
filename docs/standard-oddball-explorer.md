# Figure 9: standard-oddball explorer

The manuscript uses the existing
[Delta F/F + glutamate composite](../images/figures/generated/standard-oddball-three-modality-dff-glutamate.svg)
as its complete static counterpart. The original four-context Neuropixels
explorer and its discussion are preserved as Supplementary Figure 6, with the
stable `fig-neuropixels-event-responses` anchor. Main Figure 9 now uses
`fig-standard-oddball-responses`; Figure 10 remains the behavior figure.

The new [explorer](../interactive/standard-oddball-explorer.html) is generated
offline by [standard_oddball_explorer.py](../src/openscope_p3_publication/standard_oddball_explorer.py).
Editable HTML/CSS/JavaScript sources live in
[figure_sources/javascript](../figure_sources/javascript/).
The normal figure build generates the static composite first, then embeds it
and a compact, float64 population payload in the explorer. Its adjacent
provenance records input and output checksums. No NWB reads or SNR refits
occur during publication builds.

## Minimal publication dependencies

The default build produces the three primary 90-degree source columns, the main
Delta F/F + glutamate composite, its explorer and their provenance/audit outputs.
Candidate and regional galleries, normalization comparisons, two-column figures
and alternate-signal composites are not default publication outputs.

The compact [publication snapshot](../figure_sources/data/standard-oddball-publication/)
contains exact regional/session/mouse counts and bootstrap endpoints, plus all
four events' statistics for the displayed Neuropixels and mesoscope sources.
SLAP2's small verified-subset tables remain separate. Full Neuropixels/mesoscope
cohort unit tables and the large mesoscope extraction manifest are upstream
analysis products, not rendering or test dependencies.

[The freezing tool](../scripts/freeze_standard_oddball_publication.py) reads
validated full analyses and exports the exact required values without rerunning
tests or rounding bootstrap intervals. The compact provenance records upstream
file checksums, pinned source identities and owning-code hashes. Its upstream
hash records do not imply those full files must be present in a fresh clone.

The remaining inputs are the original example-session activity/trial snapshots,
frozen ordering and the four-event explorer arrays. Extractors and helper modules
named in their provenance remain necessary for integrity checks even when they
are not executed. No NWBs, checkpoint directories, browser screenshots or local
extraction caches belong in the publication commit.

Replaying the frozen Neuropixels spikes checks exact trial identities, source
spike digests, baselines, array shapes and finite values. Only the causal
50-term float64 SDF convolution permits relative roundoff of
`64 * float64 epsilon` (approximately `1.42e-14`), with **zero absolute tolerance**.
Zero SDF bins therefore remain exact. The frozen scientific values are not
rounded or regenerated to accommodate numerical-library differences.
Publication-renderer metadata uses slash-separated repository-relative paths on
both Windows and Linux; filesystem access continues to use native paths.
SVGs, interactive sources and audit sidecars use explicit UTF-8 and LF output.
Custom SLAP2 build directories keep their cohort audits alongside the requested
audit directory instead of overwriting the committed default audits.

After changing only the comparison replay validator, refresh its provenance
offline using the owning extractor:

```bash
uv run python scripts/extract_neuropixels_standard_oddball_comparison.py --refresh-validation-provenance
```

This verifies the existing spike checksum and replay before updating provenance,
retains the original extraction-code hashes as `extraction_sha256`, and records
the validation refresh date separately from retrieval. Other extraction-source
changes are rejected; the spike payload and population snapshot remain unchanged.

For a serialization-only change to the mesoscope cohort audit writer, use
`uv run python scripts/freeze_standard_oddball_publication.py --refresh-renderer-provenance`.
This retains original code hashes as `frozen_source_sha256`, verifies the
unchanged frozen cohort checksum, and rejects changes to other owning code.
It does not require the full upstream analyses or rerun statistical tests.

After deliberately refreshing the full analyses, freeze a new publication
snapshot with:

```bash
uv run python scripts/freeze_standard_oddball_publication.py --output /path/to/new-snapshot
```

## Available controls and data

### Separate ephys C1 pseudo-context analysis

The [focused extractor](../scripts/extract_ephys_c1_pseudocontext.py) tests a
different comparison from the explorer's actual-context sensitivity analyses:
post-context C1 is the pseudo-context and pre-context C1 is its control.
This initial analysis covers matched 90-degree single presentations in the
13 selected ephys sessions, without changing Figure 9 or its frozen statistics.

- Pseudo-Q1 compares each post-C1 90-degree response with the immediately preceding
  within-block stimulus response, using the existing paired Wilcoxon and MI rules.
  The predecessor can have any recorded C1 orientation/type, including another
  90-degree single, a halt, or an omission. These are not assumed to be expected
  standards. The provenance records each predecessor and excluded trial.
- Pseudo-Q2 compares post-C1 versus pre-C1 90-degree responses after subtracting
  each presentation's preceding-grey baseline, using the existing Mann-Whitney
  and condition-mean MI rules. Native spike-count windows are unchanged.
- Raw p < 0.05 and absolute MI > 0.1 define responsiveness; Both is their
  intersection. Regional Q1/Q2/Both counts share the jointly testable eligible
  denominator. Separate Q1 and Q2 testability counts are also saved.
- Original unit eligibility, probe exclusions, anatomical groups, and the
  minimum 20 QC-passing SUA per session/region remain unchanged. Missing or
  cross-block post-C1 predecessors are excluded; the matched pre-C1 pool remains
  intact. No additional predecessor-orientation restriction is applied.

This comparison measures control stimulus-history and pre/post differences;
it is neither an oddball-selectivity test nor a pure estimate of temporal drift.

Run the example first with a fresh output directory:

```bash
uv run --extra dev --with remfile python scripts/extract_ephys_c1_pseudocontext.py \
  --work-dir /tmp/ephys-c1-pseudo-checkpoints \
  --output-dir /tmp/ephys-c1-pseudo-example \
  --session-id ecephys_830794_2026-01-27_11-25-31
```

Omit `--session-id` and choose a fresh `--output-dir` to run the full cohort;
completed checkpoints are reused only when source signatures and checksums match.
The [result snapshot](../figure_sources/data/ephys-c1-pseudocontext/) contains
per-unit statistics, session/region counts, and pinned-source/trial provenance.
Every session's native spike digest is checked against the original extraction.
The loader `load_pseudo` in
[ephys_c1_pseudocontext.py](../src/openscope_p3_publication/ephys_c1_pseudocontext.py)
verifies checksums and recomputes count summaries offline.

For the 13-session snapshot, the included regions contain 6,670 eligible units,
of which 6,642 are jointly testable. On that shared denominator, pseudo-Q1
identifies 619 units (9.3%), pseudo-Q2 identifies 693 (10.4%), and Both identifies
140 (2.1%). All sessions retain 34 pre-C1 and 34 post-C1 90-degree presentations.
Across the 442 post-C1 presentations, the predecessors are 403 single gratings,
13 halts, and 26 omissions; single-grating orientations vary. These predecessor
types are retained, not reclassified as standards.

| Region | Jointly testable | Pseudo-Q1 | Pseudo-Q2 | Both |
| --- | ---: | ---: | ---: | ---: |
| LGd | 480 | 116 | 135 | 42 |
| VISp | 499 | 170 | 133 | 51 |
| VISl | 289 | 73 | 63 | 12 |
| VISa | 186 | 18 | 32 | 6 |
| Frontal | 3,055 | 123 | 188 | 13 |
| Hippocampus | 1,306 | 43 | 87 | 4 |
| SSp | 436 | 59 | 36 | 10 |
| STR | 391 | 17 | 19 | 2 |

#### Supplemental population figure

[Supplementary Figure 7](../index.md#fig-ephys-c1-pseudocontext) shows pre-C1,
post-C1, and post-minus-pre heatmaps for the same 203 visual units as Figure 9 D,
with regional pseudo-Q1/Q2/Both bars for the full cohort in panel E, centered
beneath B and C. Panel D, centered beneath A and B, shows pre/post-C1 mean SDFs
and across-neuron SEM using the same 51 positive
actual-context Q1 visual units as the alternative layout (raw p <0.05, signed
MI >0.1, no Q2 restriction). Selection details appear in the caption rather
than a mean-panel title. All three maps
retain Figure 9's frozen context-only Rastermap order, with no response-based
selection. Each condition subtracts its own per-unit preceding-grey display
baseline. The difference is between the baseline-subtracted means, not paired
pre/post trials. The shared symmetric color limit is the ceiling of the pooled
absolute 99th percentile of all three maps, with saturation beyond that limit.
SDFs retain the existing 5 ms bins and causal 25 ms kernel; the display baseline
pools complete half-open 20 ms bins and is not the native Q2 statistical rate.

The separate [display extractor](../scripts/extract_ephys_c1_population.py)
streams only the pinned example session. It verifies all 203 full-unit spike
digests against Figure 9, rechecks original and pseudo-context trial identities,
and verifies that the split raw means and bin-weighted display baselines
reconstruct the original pooled control. The compact
[display snapshot](../figure_sources/data/ephys-c1-population/) and its provenance
are committed inputs, not a build-time download. To refresh deliberately, choose
a fresh output directory and review before replacing the published snapshot:

```bash
uv run --extra dev --with remfile python scripts/extract_ephys_c1_population.py \
  --output-dir /tmp/ephys-c1-population-refresh
```

The [renderer](../src/openscope_p3_publication/ephys_c1_pseudocontext_figure.py)
runs offline as part of `uv run build-publication-figures`. Regional bars reuse
Figure 9's 10,000-replicate mouse-cluster bootstrap, pooling included sessions
within mouse before resampling. Both layouts use the same
[mean-trace helper](../src/openscope_p3_publication/ephys_c1_mean_traces.py), avoiding
separate selection or SEM calculations. Derived area/mouse tables, ordered unit
baselines and Q1 selection, time-by-condition mean/SEM traces,
clipping statistics, and output/source checksums are saved in
[the figure audit directory](../figure_sources/derived/ephys-c1-pseudocontext/).
Figure 9 and its primary statistics are not changed.

#### Alternative pre/context/post layout

A separate [alternative SVG](../images/figures/generated/ephys-c1-context-comparison.svg)
keeps the existing supplement and manuscript entry intact. Its top row shows
**A**, pre-C1; **B**, the exact actual-context heatmap from Figure 9 D; and **C**,
post-C1. All maps retain the same 203 units and original context-only Rastermap
order. The common color limits are Figure 9 D's original +/-44 Hz, not a new
limit estimated from the controls. There is no difference heatmap in this version.

Below B, pre/post-C1 baseline-subtracted mean SDFs use one fixed pool of **51
actual-context Q1-positive visual units** (finite raw p <0.05 and signed MI >0.1).
There is **no Q2 restriction**: this is not Figure 9's joint-positive mean pool,
nor a selection on post-C1 pseudo-Q1. Both curves equally weight the same cells;
shading is sample SD across neurons (ddof=1) divided by sqrt(51), not across-trial
or across-mouse uncertainty. The conditions retain their separate per-unit
display baselines. Below C, the same regional pseudo-Q1/Q2/Both bars and
mouse-bootstrap intervals are compressed into one column; their cohort and
denominators are unchanged.

The [alternative renderer](../src/openscope_p3_publication/ephys_c1_context_figure.py)
reuses the committed context and split-control snapshots offline; no NWB
re-extraction is needed. It runs in `uv run build-publication-figures`, writing
separate [audit outputs](../figure_sources/derived/ephys-c1-context-comparison/):
the full 203-unit selection table, time-by-condition mean/SEM traces, regional
counts and intervals, clipping statistics, and source/output checksums. The
current supplement remains the manuscript version while this alternative is
available for comparison.

#### Four-event post-minus-pre experiment

The separate [four-event figure](../images/figures/generated/ephys-c1-event-differences.svg)
compares post-C1 minus pre-C1 for 90-degree singles, 45-degree singles, halt, and
omission. It is an exploratory display for the same example session, not a
replacement for S7 or a new cohort Q1/Q2 analysis. These are matched event types
inside C1 controls, not oddball-context deviants.

All four heatmaps retain the same 203 eligible visual units and original
context-only Rastermap order, without event-specific responsiveness selection.
For each unit, the difference is
`(post SDF - post grey baseline) - (pre SDF - pre grey baseline)`.
SDFs use 5 ms bins, a causal 25 ms exponential kernel and the existing
[-0.75, +0.75] s display window. Display baselines pool complete half-open
20 ms bins within each trial's preceding grey. The plotted means equally weight
all 203 unitwise differences, and SEM is their sample SD (ddof=1) divided by
sqrt(203). It is **not** the independent sum of pre/post SEMs or trial/mouse
uncertainty. Heatmaps share a symmetric pooled absolute 99th-percentile ceiling
color scale, with saturation beyond the limits; mean traces also share one
symmetric Hz axis.

Each condition contributes 34 presentations for 90 degrees, halt and omission.
The first 45-degree presentation in **each** C1 repeat (control rows 0 and 544)
has no preceding-grey baseline. Those two trials are explicitly excluded from
both the SDF and its baseline, leaving **33 pre and 33 post** for 45 degrees.
Baselines are not borrowed or imputed. Exclusions and exact retained trial
identities are recorded in the source snapshot.

The original 90-degree split snapshot is reused unchanged. The additional
[three-event snapshot](../figure_sources/data/ephys-c1-event-populations/) stores
compact pre/post means and baselines, not NWB files. Its
[extractor](../scripts/extract_ephys_c1_event_populations.py) checks all 203
full-unit spike digests against Figure 9, verifies exact four-event stimulus
tables/trial identities, reproduces the saved 90-degree split exactly, and
replays the six existing native trial-spike examples in every event.
To refresh deliberately, use a fresh output directory:

```bash
uv run --extra dev --with remfile python scripts/extract_ephys_c1_event_populations.py \
  --output-dir /tmp/ephys-c1-event-populations-refresh
```

The [renderer](../src/openscope_p3_publication/ephys_c1_event_differences.py)
runs offline in the normal figure build. Its
[audit directory](../figure_sources/derived/ephys-c1-event-differences/) contains
trial/exclusion/clipping counts, mean/SEM traces, unit identities/order and
source/output checksums. No significance screen or drift-specific interpretation
is implied; the current manuscript and both previous C1 figures are unchanged.

### Explorer controls

- Primary signals only: Neuropixels SDF, mesoscope stored Delta F/F percent,
  and SLAP2 glutamate in arbitrary units.
- Event selection: 45-degree orientation, 90-degree orientation, motion halt,
  and omission. All three modalities have validated four-event cohort statistics.
- Population heatmaps/time courses: **all four events in all three modalities**.
  Each event uses its own retained trials, native activity and frozen source
  responsiveness statistics; switching events never substitutes 90-degree data.
- Interactive displays align activity directly to native stimulus-table
  `start_time`, using **[-1.5, 1.5] seconds** and the same retained trials.
  Neighbor guides at offsets -2/-1/0/+1/+2 use actual native presentation
  medians, not assumed periods. The last following presentation can be
  truncated by the requested +1.5-second limit. No extra standard-neighbor
  trial filter is applied. Static figures retain their original windows.
  The original [90-degree wide display](../figure_sources/data/standard-oddball-explorer-window/)
  remains a validated reference. The
  [four-event snapshot](../figure_sources/data/standard-oddball-explorer-events/)
  is frozen by [its extractor](../scripts/extract_standard_oddball_explorer_events.py)
  and checked against that reference.
- Available area/DMD selection is modality-specific. Neuropixels cohort regions
  include nonvisual regions absent from the visual example population; those
  selections explicitly lack a population view. Mesoscope offers VISp/VISl.
  SLAP2 offers DMD1/DMD2, both in VISp; no displayed Pooled category.
- Population filters: all eligible, Q1, Q2, Both, positive Both, and
  Q2-nonsignificant. They do not modify cohort statistics or denominators.
- Heatmap values: baseline-subtracted context, control, or their difference.
  Color saturation uses the selected view's 99th absolute percentile times
  the color-limit control. Values themselves are not normalized.
  A numeric gradient above the heatmap uses the selected modality's label:
  Delta Firing rate (spikes/s), Delta F/F, or Delta Glu change. Percent and
  arbitrary-unit tick suffixes retain the optical signals' stored units.
- Row order: frozen context Rastermap, area, response-window magnitude, or
  time to positive peak. SLAP2 always retains separate DMD groups; filtering
  never refits Rastermap. Sources without a positive post-onset peak sort last.
  Population traces weight selected sources equally.
- Trace: selected-source mean with across-source SEM, or individual-source
  context/control means without a trial SEM band. Select a source directly,
  click its heatmap row, or use the focused canvas's arrow/Enter keys.
- Event-specific cohort counts and denominators are retained in the embedded
  data and the barplot's accessible summary, without visible tables or prose
  beneath the bars. Bars pool counts and mouse points show each contributing mouse.
  Neuropixels/mesoscope use the existing exact 95% mouse-cluster bootstrap
  bounds; SLAP2's two-mouse subset has no bootstrap intervals.
  SLAP2 circles/squares identify mice 828408/829704, respectively.
  The optional question-mark legend contains scientific interpretation; normal
  view omits session/selection paragraphs, the textual color key, click hint,
  cohort inclusion paragraph and post-barplot details.

The main static composite adds vertical Single Unit/All Units row labels.
Its one RdBu_r population gradient has separate native-unit limits for D/E/F:
44 spikes/s, 0.4% Delta F/F and 1 a.u. glutamate change. The shared legend
denotes fractions of those existing limits, not normalized scientific values.
A 4-mm left gutter and 10-mm footer prevent label/legend clipping; native source
column geometry is unchanged. Panel lettering remains 9 pt at publication
width. Alternative signal composites are unchanged.

## Scientific invariants

Q1 is the paired two-sided Wilcoxon deviant/preceding-standard comparison;
Q2 is the unpaired two-sided Mann-Whitney context/control comparison after
each trial's preceding-grey subtraction. The exploratory screen uses
raw p < 0.05 and |MI| > 0.1, either sign. Both is their intersection.
Do not clip signed MIs or call undefined tests nonresponses.

Cohort denominators are eligible jointly Q1/Q2-testable observations.
Region/DMD inclusion retains the established minimum of 20 QC-passing SUA
(Neuropixels, before firing-rate/testability filtering) or 20 eligible optical
sources (mesoscope/SLAP2, before testability). Neuropixels's existing regional
renderer now accepts an event argument, retaining 90 degrees as its default.

The original scientific snapshots, optical alignment and saved 90-degree
Rastermap orders are unchanged. All events reuse that order without refitting.
The four-event explorer snapshot preserves the existing 90-degree retained rows
and wide activity. Neuropixels display subtraction retains the released
complete half-open 20-ms preceding-grey bins, independently of native statistical
windows. A control trial without a preceding-grey baseline is excluded from
the baseline-subtracted display and recorded explicitly in provenance; its
undefined baseline was already unavailable to Q2. Native optical samples unavailable during
acquisition pauses remain missing; each time bin averages only recorded
trials, with count ranges in accessible source readouts and full source/time counts in NPZ.
Actual stimulus spans come from validated display
metadata, not approximated durations. SLAP2 uses each DMD's fully recorded
trials and frozen glutamate High/Intermediate labels. Sources may share a
dendrite/cell; optical ROI/session observations are not independent
longitudinal neurons. Cohorts are not matched animals across modalities.
Twelve legacy SLAP2 sessions remain unresolved and excluded from the verified
standard subset; do not infer compatible blocks from orientation frequencies.

To deliberately reproduce the four-event display from the same pinned public assets:

```bash
uv run --with remfile python scripts/extract_standard_oddball_explorer_events.py \
  --stage /path/to/private-checkpoints --output /path/to/new-event-snapshot
```

Completed unit/plane/DMD checkpoints are reusable. The extractor refuses to
overwrite an existing output and never changes original scientific snapshots
or any static SVG.
