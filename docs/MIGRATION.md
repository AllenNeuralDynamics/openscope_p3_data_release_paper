# Google Doc to MyST migration

## Completed on 2026-07-28

- Created the MyST publication and GitHub Pages build.
- Preserved the public Google Doc as a DOCX source snapshot.
- Imported the full manuscript and all 14 embedded media files.
- Assigned semantic asset names, stable MyST labels, alt text, and SHA-256 checksums.
- Added the AuthorshipExtractor plugin and an initial contributor record.
- Added an installable Python package, tests, and the first playable JavaScript figure with an SVG fallback.
- Added source, generated-asset, and contribution conventions.
- Replaced the mesoscope laser-power screenshot with a structured, CSV-backed table.

## Inputs still needed from the team

- **Editable Google Slides:** The public Docs/DOCX/HTML exports contain only PNG renderings, not presentation IDs. Add each deck or source URL under `figure_sources/google-slides/` and fill `editable_source_url` in `figure_sources/google-doc/manifest.json`.
- **Complete author roster:** `authors.yml` currently contains only the initial seed record. Each contributor must review their own CRediT roles, effort levels, affiliations, and section contributions.
- **Bibliography:** Convert Paperpile links into stable BibTeX keys in `references.bib`, then replace inline author-year links with MyST citations.
- **Supplementary Table 1:** The DOCX export retained row labels but dropped the study columns. Export the original table as CSV or obtain its linked spreadsheet source.
- **Figure placeholders:** Figures 4-7 are visibly unfinished slide canvases and should be replaced by generated analyses or final artwork.
- **Data and code versions:** Pin DANDI dataset versions and the exact analysis repositories or releases used for each result.
- **Publication metadata:** Confirm the final title, abstract, author order or consortium policy, corresponding authors, keywords, license, funding, acknowledgements, and journal export target.

## Cutover decision

Choose and announce one canonical editing surface to avoid divergent manuscripts:

1. Freeze the Google Doc at a named revision.
2. Run one final import and commit the resulting source snapshot and manifest.
3. Reconcile any repository-only edits.
4. Move all new manuscript, authorship, citation, and figure work to pull requests.
5. Keep the frozen DOCX only as provenance; do not use it as a second live manuscript.

## Recommended next milestone

Complete one figure end to end: obtain its Slides source, move numerical inputs into a structured file, recreate the analytical panels in Python, generate static and interactive outputs, and replace the imported PNG. That establishes the pattern the remaining figure owners can follow.