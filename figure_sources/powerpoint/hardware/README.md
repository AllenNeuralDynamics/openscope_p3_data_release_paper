# Hardware PowerPoint sources

`Presentation_ALL_HARDWARE.pptx` is the editable one-slide source supplied for Figure 3. Its cohort column is intentionally excluded from the rebuilt publication figure because cohort allocation is already presented in Figure 1C.

The nine PNG files under `images/` are copied byte-for-byte from the PowerPoint OOXML package and retain their native dimensions and alpha channels. `provenance.json` records the source deck checksum, original `ppt/media` filename, semantic role, checksum, dimensions, slide placement, and PowerPoint crop fractions for every asset.

Refresh the source snapshot with:

```bash
uv run python scripts/extract_hardware_powerpoint.py \
  /path/to/Presentation_ALL_HARDWARE.pptx
```

Build the generated `images/figures/generated/multimodal-hardware.svg` with `uv run build-publication-figures`.