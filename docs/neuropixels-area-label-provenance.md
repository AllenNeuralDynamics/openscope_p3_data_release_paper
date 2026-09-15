# Neuropixels area labels: provenance and coordinate cross-check

What we found while auditing the anatomical labels in the released P3 Neuropixels NWBs,
written up for anyone else working with this data.

Audited 2026-09-15 against the draft of
[Dandiset 001637](https://dandiarchive.org/dandiset/001637/draft/files) with `iblatlas` 1.2.0.

---

## Summary

1. **The draft Dandiset is mutable, and 48 of its 60 Neuropixels assets were replaced in
   August 2026.** Anything pinned before then reads superseded data. This repository's
   committed Neuropixels snapshots pin the June 2026 versions.
2. **The August update was primarily an annotation fix.** 43 of 60 sessions kept identical
   unit counts; 17 changed by between −93 and +64 units, for −106 across the release (−0.05%).
3. **On the current assets, the NWB `location` strings agree well with the electrode CCF
   coordinates**: 95.9% exact and 96.9% at area level across 178,447 units, with residual
   disagreement concentrated at anatomical boundaries and ontology hierarchy levels rather
   than being systematic.
4. **An earlier annotation problem is already fixed upstream.** The June assets labelled a
   complete six-layer visual area `VISlm`, which is absent from the Allen ontology. The August
   assets label it `VISl`.
5. **The units table's `estimated_x/y/z` are not CCF coordinates** and must not be used for
   anatomy. They are probe-relative localisation from spike sorting.

---

## 1. The draft Dandiset is mutable

`001637` is published as a **draft**, and draft dandisets can be modified in place. Assets are
addressed by an `asset_id` that changes when the file is replaced, while the `path` stays the
same.

Comparing the asset IDs pinned in this repository's `neuropixels-unit-yield.csv`
(retrieved 2026-07-30, which pins files last modified 2026-06-30) against the current draft:

| | Assets |
|---|---|
| Unchanged `asset_id` | 12 |
| **Replaced `asset_id`** | **48** |
| Paths added or removed | 0 |

All 48 replacements are dated 2026-08, and they affect 15 of the 16 mice.

Superseded assets remain fetchable by their old `asset_id`, so pinned analyses keep working and
keep returning the old data. That is good for reproducibility and bad for staying current: an
extractor that pins IDs is stable, and an extractor that enumerates the API follows the draft.
**Both behaviours exist in this repository right now**, which is worth knowing when comparing
figures:

- `scripts/extract_neuropixels_event_responses.py` and the trajectory and unit-yield extractors
  pin asset IDs through `neural_responses.py` or their committed snapshots, so they read the
  June versions.
- `scripts/extract_mismatch_adjacency.py` and `scripts/extract_sensorimotor_running.py`
  enumerate the API, so they read the August versions.

### What changed in the update

Total unit counts, June snapshot versus current:

| | Sessions |
|---|---|
| Identical total unit count | 43 |
| Changed total unit count | 17 |

Changes range from −93 to +64 units, mean −6.2, and the release total moves from 195,553 to
195,447 units (−106, −0.05%). The largest single change is
`sub-848390_ses-ecephys-848390-2026-05-04-10-22-33` at −93 units.

So the update looks like a re-annotation plus limited re-sorting, not a wholesale reprocessing.
It is nonetheless enough to change every per-unit figure value derived from the affected
sessions.

---

## 2. How to resolve electrode coordinates to Allen structures

The electrode table carries `x`, `y`, `z` alongside the `location` string. Resolving those
coordinates requires knowing their axis order, and **guessing it wrong produces
plausible-looking but completely wrong anatomy**, so it is worth stating explicitly.

The columns are CCF micrometres in **`apdvml`** order — `x` is anterior-posterior, `y` is
dorsal-ventral, `z` is medial-lateral — measured from the anterior-left-dorsal corner of the
CCF volume, not from bregma.

```python
from iblatlas.atlas import AllenAtlas

ba = AllenAtlas(25)
xyz = ba.ccf2xyz(ccf, ccf_order="apdvml")   # ccf is an N x 3 array of (AP, DV, ML) micrometres
ids = ba.get_labels(xyz, mode="clip")
```

`ccf2xyz` defaults to `ccf_order="mlapdv"`, which is the IBL convention and **wrong for this
data**. Testing all twelve permutations of column order against the 1,833 channels whose
`location` string already resolves in the ontology:

| Convention | Exact-label agreement |
|---|---|
| `apdvml` (columns as given) | **95.5%** |
| `mlapdv` (the function default) | 0.3% |
| Every other permutation | ≤ 20% |

The separation is decisive, which is why it is worth calibrating rather than assuming. Any
pipeline reading these coordinates should assert an agreement rate against the `location`
strings and fail loudly if it drops, so a future change in column order cannot silently corrupt
the anatomy.

The observed coordinate ranges corroborate the convention against the CCF volume, which is
13200 × 11400 × 8000 micrometres at 25 micrometre voxels:

| Column | Axis | Observed range | Reading |
|---|---|---|---|
| `x` | AP | 2950 to 9500 | 2.95 to 9.5 mm posterior of the anterior pole |
| `y` | DV | −250 to 4400 | 0 is the dorsal surface, so **negative means above the brain** |
| `z` | ML | 1875 to 5725 | midline is 5700, so every probe is in the left hemisphere |

The negative `y` values are not an error. They are channels above the brain surface, and they
correspond exactly to the `void` labels at the dorsal end of each shank.

### `estimated_x/y/z` in the units table are not CCF coordinates

The units table has its own `estimated_x`, `estimated_y`, and `estimated_z` columns. These are
**probe-relative unit localisation from spike sorting**, not atlas coordinates:

| Source | x | y | z |
|---|---|---|---|
| `estimated_*` (units table) | −838 to 898 | −236 to 4607 | 1 to 960 |
| electrode table, peak channel | 2950 to 9500 | −250 to 4400 | 1875 to 5725 |

Median displacement between the two is **7.9 mm**, and nothing agrees within 200 micrometres.
Fed to the atlas, `estimated_*` gives 4.9% label agreement and places every unit of one cortical
area outside the brain. Use the electrode table's coordinates via
`extremum_channel_index` instead.

---

## 3. Agreement between labels and coordinates on the current assets

Across all 60 current Neuropixels sessions, 178,447 units with a resolvable `location`.
Medians are over sessions and average the two middle values, since there are 60:

| Measure | Min | Median | Max | Unit-weighted |
|---|---|---|---|---|
| Exact label agreement | 92.3% | 96.20% | 98.5% | **95.9%** |
| Area agreement, layer ignored | 92.5% | 97.47% | 99.1% | **96.9%** |

Units whose Allen **major parent** (Isocortex, TH, HPF, STR) would change: **1,036, or 0.58%**.

**No acronym in any current session is absent from the `iblatlas` 1.2.0 ontology.**

### The residual disagreement is boundaries, not errors

The ~4% that disagrees falls into recognisable categories rather than being scattered:

| Example | Count | What it is |
|---|---|---|
| `ar -> int` | 62 | adjacent white-matter tracts |
| `TTd -> OLF` | 23 | hierarchy depth — `TTd` is inside `OLF` |
| `alv -> CA1` | 20 | white matter against grey matter |
| `ACAd6a -> ACAd6b` | 17 | adjacent cortical layers |
| `MOs5 -> MOp5` | 12 | adjacent cortical areas |
| `LGd-co -> LGd-ip` | 12 | subdivisions of the same nucleus |
| `SSp-bfd6b -> or` | 10 | layer 6b against optic radiation |

This is what you expect from comparing a per-channel registration with spatial regularisation
against a bare nearest-voxel lookup in a 25 micrometre atlas. At boundaries the NWB label is
plausibly the better estimate, so **the `location` strings should stay authoritative** and the
coordinate lookup is best used as a cross-check rather than a replacement.

---

## 4. The `VISlm` labels in the superseded June assets

Recorded because anyone pinned to the June versions will hit it.

In all four sessions of mouse 830794 as of 2026-06-30, the electrode `location` column contained
a complete six-layer visual area labelled `VISlm1`, `VISlm2/3`, `VISlm4`, `VISlm5`, `VISlm6a`,
and `VISlm6b`. That acronym does not exist in the Allen ontology, which has `VISl`, `VISli`, and
`VISlla` but no `VISlm`. Any pipeline resolving acronyms against the ontology fails on it.

| Session | Units | On `VISlm` channels | Share |
|---|---|---|---|
| sensorimotor | 3,966 | 156 | 3.93% |
| standard | 3,018 | 158 | 5.24% |
| sequence | 2,951 | 168 | 5.69% |
| duration | 3,125 | 132 | 4.22% |

614 units in total. Mouse 830846 had no unmatched acronyms in any session, which is why this
surfaced only when the figure's source mouse changed.

The coordinates placed those channels across the VISp/VISl border: weighted by units, roughly
60% resolved to `VISl` and 34% to `VISp`, with the deep layers 5 and 6a resolving to `VISl` and
the thinner superficial layers to `VISp`. The affected shank was ProbeD, whose trajectory runs

```
void -> VISlm1..6b -> or -> fp -> alv -> CA1 -> DG -> CA3 -> bsc -> LGd -> IGL -> LGv
```

which is a textbook lateral-visual insertion through cortex, white matter, hippocampus, and
LGN.

**In the current August assets these channels are labelled `VISl` and resolve normally**, so no
alias table or special case is needed. `VISlm` is presumably the lateromedial naming used by
some mouse visual-cortex parcellations for the area Allen calls `VISl`.

---

## 5. Implications for this repository

- **Committed Neuropixels snapshots pin June 2026 assets.** The unit-yield CSV records
  `retrieved_date: 2026-07-30`, and the event-response, trajectory, and optotagging snapshots
  pin asset IDs from around then. Their values remain reproducible but no longer match the
  current draft.
- **The two locomotion and adjacency supplementals read the August assets**, because their
  extractors enumerate the API. Figures derived from pinned snapshots and figures derived from
  enumerated assets are therefore not currently based on the same source data.
- **Refreshing is a deliberate act with wide reach.** Re-extracting against the August assets
  would change per-unit values in 48 of 60 sessions and total unit counts in 17 of them. Every
  dependent snapshot, provenance hash, static figure, interactive output, and caption number
  would need regenerating together, as CONTRIBUTING requires.
- **Pinning versus enumerating should be a conscious choice per extractor**, and the choice
  should be visible in provenance. An extractor that enumerates the API cannot be reproduced
  later unless its asset manifest hash is recorded, which
  `extract_mismatch_adjacency.py` and `extract_sensorimotor_running.py` both do.

## 6. Suggestions for the data release

- Consider publishing a **versioned** Dandiset release rather than relying on the draft, so
  downstream analyses can pin a version rather than individual asset IDs.
- `estimated_x/y/z` in the units table invite misuse, since the names suggest coordinates
  comparable to the electrode table's. A units-table column description, or names indicating the
  probe-relative frame, would prevent that.
- The June `VISlm` labels are fixed, but the episode shows the value of validating acronyms
  against the reference ontology during packaging, so an unrecognised label is caught before
  release.

---

## Reproducing this audit

The scripts used are exploratory and were not promoted into `scripts/`, since the repository's
extractors now carry the parts that matter. The method is:

1. Enumerate assets from
   `https://api.dandiarchive.org/api/dandisets/001637/versions/draft/assets/`.
2. For each NWB, read `general/extracellular_ephys/electrodes` (`location`, `x`, `y`, `z`) and
   the `units` table (`electrodes`, `electrodes_index`, `extremum_channel_index`).
3. Map each unit to its peak channel, then that channel's coordinates.
4. Resolve with `AllenAtlas(25).get_labels(ba.ccf2xyz(ccf, ccf_order="apdvml"), mode="clip")`.
5. Compare against the `location` string exactly and with the trailing layer suffix removed.
6. Calibrate the column order by maximising agreement before trusting any result.
