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

After deliberately refreshing the full analyses, freeze a new publication
snapshot with:

```bash
uv run python scripts/freeze_standard_oddball_publication.py --output /path/to/new-snapshot
```

## Available controls and data

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
