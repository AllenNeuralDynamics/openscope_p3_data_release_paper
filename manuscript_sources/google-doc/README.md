# Google Doc source

The collaborative manuscript currently lives in the shared [Google Doc](https://docs.google.com/document/d/1A4aj5E1jsv-XihPt2_6K0TKMnwvtiMAFau3qJUcOV-I/edit).

`manuscript.docx` is the preserved source export used for the current migration. Refresh it and the MyST manuscript with:

```bash
python scripts/import_google_doc.py
```

The importer overwrites `index.md`, the rendered files in `images/figures/imported/`, and the generated provenance manifest. Do not run it after making repository-only manuscript edits unless those edits have first been reconciled with the Google Doc.

Known export limitations:

- Google Docs exports embedded Slides as rendered PNG files, without the source presentation or slide IDs.
- Supplementary Table 1 loses its study columns in the DOCX export and must be migrated from a spreadsheet or CSV.
- Some source paragraphs use heading styles even though they are body text. The importer corrects only the known cases.