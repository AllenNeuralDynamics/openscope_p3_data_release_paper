# Figure data

Small structured inputs used by publication figures and tables live here.

`mesoscope-laser-power.csv` transcribes the lookup values embedded in the Google Doc image exported as `images/figures/imported/mesoscope-laser-power-table.png`. The PNG remains as source provenance; Methods links to a MyST hover preview of the accessible table without reserving permanent page space.

`experimental-animals.csv` is a dated 39-row snapshot of the linked public experiment worksheet, with source URL and source/vendored checksums recorded in `experimental-animals.provenance.json`. It supplies individual mouse metadata to the interactive explorer. Hidden imported source tables retain the grouped manuscript data needed for deterministic generation but are not shown beside the record-level explorer. Individual session rows (164 unique sessions) are expanded from the grouped session IDs in that source.

`other-oddball-studies.csv` is the complete 17-row by 6-column source for Supplementary Table 1. Its Google Sheets URL, retrieval date, dimensions, and checksums are recorded in `other-oddball-studies.provenance.json`.

`stimulus-table-excerpts/` contains compact, checksum-verified excerpts from all four pinned example tables. Context excerpts span approximately 24 seconds around the first true mismatch; shared-block excerpts preserve the first approximately 24 seconds of each generated control block. Source row and trial numbers are retained.