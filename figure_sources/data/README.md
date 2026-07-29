# Figure data

Small structured inputs used by publication figures and tables live here.

`mesoscope-laser-power.csv` transcribes the lookup values embedded in the Google Doc image exported as `images/figures/imported/mesoscope-laser-power-table.png`. The PNG remains as source provenance; the manuscript renders the numeric CSV values as an accessible Methods table and cross-references that table from the supplementary figures.

`experimental-animals.csv` is a dated 39-row snapshot of the linked public experiment worksheet, with source URL and source/vendored checksums recorded in `experimental-animals.provenance.json`. It supplies individual mouse metadata to the interactive explorer. The grouped manuscript table remains the static publication summary. Individual session rows (164 unique sessions) are expanded from the grouped session IDs in that summary.

`other-oddball-studies.csv` is the complete 17-row by 6-column source for Supplementary Table 1. Its Google Sheets URL, retrieval date, dimensions, and checksums are recorded in `other-oddball-studies.provenance.json`.