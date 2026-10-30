# Google Slides figure sources

`slide-15-neuropixels-implant.png` is the source-quality PNG export of slide 15 from the linked analysis-map deck. It replaces the former Figure 11 analysis-map image and is rendered as Supplementary Figure 1. The slide URL, export URL, slide identifier, retrieval date, dimensions, and checksum are recorded in `slide-15-neuropixels-implant.provenance.json`.

Supplementary Figure 1 now embeds `slide-15-neuropixels-implant-native.png`,
the original 2048 x 1408 PNG stored inside that slide's SVG export. The
2500 x 1250 full-slide PNG above remains the Methods coordinate-table reference.
The native image avoids the slide export's downsampling, providing approximately
18% more linear detail in panels A-C; it is still raster, not vector artwork.
Panel layout and crops are unchanged, and panel D remains independently generated
from recorded trajectories.

To reproduce the native extraction, download `native_image.export_url` from the
provenance, verify its `svg_sha256`, and base64-decode the sole SVG `image`
element's data URI directly to the native PNG. Do not re-encode or resize it.
Verify the PNG dimensions and `native_image.sha256`. The original SVG view box
and image transform are recorded alongside the native-to-slide transform:
scale the SVG coordinates by 2500 / view-box width and 1250 / view-box height.
The renderer applies this transform to the native pixels, preserving the existing
slide-coordinate crops without creating an intermediate resized image. Panel B
retains its grayscale body and colored header; the old 100-pixel slide-coordinate
header boundary maps to native row 79. Normal figure builds use only these
committed sources and do not download the slide.
