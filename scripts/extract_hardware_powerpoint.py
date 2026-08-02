#!/usr/bin/env python3
"""Extract source images and placement metadata from the hardware PowerPoint."""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import shutil
import struct
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "figure_sources" / "powerpoint" / "hardware"
EMU_PER_INCH = 914_400
PRESENTATION_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NAMESPACES = {"a": DRAWING_NS, "p": PRESENTATION_NS}
SHAPE_TAGS = {
    f"{{{PRESENTATION_NS}}}{name}"
    for name in ("sp", "pic", "graphicFrame", "grpSp", "cxnSp", "contentPart")
}
PICTURE_TAG = f"{{{PRESENTATION_NS}}}pic"
RELATIONSHIP_ID = f"{{{OFFICE_REL_NS}}}id"
RELATIONSHIP_EMBED = f"{{{OFFICE_REL_NS}}}embed"

MEDIA_ASSETS = {
    "image5.png": (
        "neuropixels_rig_geometry",
        "neuropixels-rig-geometry.png",
        "Neuropixels rig geometry",
    ),
    "image1.png": (
        "mesoscope_rig_geometry",
        "mesoscope-rig-geometry.png",
        "Mesoscope rig geometry",
    ),
    "image6.png": (
        "slap2_rig_geometry",
        "slap2-rig-geometry.png",
        "SLAP2 rig geometry",
    ),
    "image7.png": (
        "neuropixels_mouse_platform",
        "neuropixels-mouse-platform.png",
        "Neuropixels mouse platform",
    ),
    "image8.png": (
        "mesoscope_mouse_platform",
        "mesoscope-mouse-platform.png",
        "Mesoscope mouse platform",
    ),
    "image9.png": (
        "slap2_mouse_platform",
        "slap2-mouse-platform.png",
        "SLAP2 mouse platform",
    ),
    "image4.png": (
        "neuropixels_brain_targeting",
        "neuropixels-brain-targeting.png",
        "Neuropixels probe trajectories and brain targets",
    ),
    "image3.png": (
        "mesoscope_brain_targeting",
        "mesoscope-brain-targeting.png",
        "Mesoscope cortical targets",
    ),
    "image2.png": (
        "slap2_brain_targeting",
        "slap2-brain-targeting.png",
        "SLAP2 proximal and apical dendritic planes",
    ),
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def relative_path(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def relationships(archive: ZipFile, member: str) -> dict[str, str]:
    root = ET.fromstring(archive.read(member))
    return {
        relationship.attrib["Id"]: relationship.attrib["Target"]
        for relationship in root
    }


def slide_member(archive: ZipFile) -> tuple[str, ET.Element, int, int, int]:
    presentation = ET.fromstring(archive.read("ppt/presentation.xml"))
    slide_ids = presentation.findall("p:sldIdLst/p:sldId", NAMESPACES)
    if len(slide_ids) != 1:
        raise RuntimeError(f"Expected one hardware slide, found {len(slide_ids)}")
    slide_size = presentation.find("p:sldSz", NAMESPACES)
    if slide_size is None:
        raise RuntimeError("PowerPoint slide size is missing.")
    presentation_rels = relationships(archive, "ppt/_rels/presentation.xml.rels")
    relationship_id = slide_ids[0].attrib[RELATIONSHIP_ID]
    member = posixpath.normpath(
        posixpath.join("ppt", presentation_rels[relationship_id])
    )
    return (
        member,
        ET.fromstring(archive.read(member)),
        len(slide_ids),
        int(slide_size.attrib["cx"]),
        int(slide_size.attrib["cy"]),
    )


def picture_placements(
    archive: ZipFile, slide_path: str, slide: ET.Element
) -> tuple[dict[str, dict], dict[str, str]]:
    relationship_path = posixpath.join(
        posixpath.dirname(slide_path),
        "_rels",
        f"{posixpath.basename(slide_path)}.rels",
    )
    slide_rels = relationships(archive, relationship_path)
    shape_tree = slide.find("p:cSld/p:spTree", NAMESPACES)
    if shape_tree is None:
        raise RuntimeError("PowerPoint slide shape tree is missing.")
    placements = {}
    media_members = {}
    shape_index = -1
    for shape in shape_tree:
        if shape.tag not in SHAPE_TAGS:
            continue
        shape_index += 1
        if shape.tag != PICTURE_TAG:
            continue
        blip = shape.find("p:blipFill/a:blip", NAMESPACES)
        transform = shape.find("p:spPr/a:xfrm", NAMESPACES)
        if blip is None or transform is None:
            raise RuntimeError(f"PowerPoint picture {shape_index} is incomplete.")
        offset = transform.find("a:off", NAMESPACES)
        extent = transform.find("a:ext", NAMESPACES)
        if offset is None or extent is None:
            raise RuntimeError(f"PowerPoint picture {shape_index} has no geometry.")
        relationship_id = blip.attrib[RELATIONSHIP_EMBED]
        target = slide_rels[relationship_id]
        media_name = posixpath.basename(target)
        if media_name in placements:
            raise RuntimeError(f"PowerPoint media is placed more than once: {media_name}")
        source_rectangle = shape.find("p:blipFill/a:srcRect", NAMESPACES)
        crop_fractions = [
            round(
                int(source_rectangle.attrib.get(side, 0)) / 100_000
                if source_rectangle is not None
                else 0,
                6,
            )
            for side in ("l", "t", "r", "b")
        ]
        placements[media_name] = {
            "shape_index": shape_index,
            "slide_box_inches": [
                round(int(value) / EMU_PER_INCH, 6)
                for value in (
                    offset.attrib["x"],
                    offset.attrib["y"],
                    extent.attrib["cx"],
                    extent.attrib["cy"],
                )
            ],
            "crop_fractions": crop_fractions,
        }
        media_members[media_name] = posixpath.normpath(
            posixpath.join(posixpath.dirname(slide_path), target)
        )
    return placements, media_members


def png_metadata(data: bytes) -> tuple[int, int, str]:
    if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) < 26:
        raise RuntimeError("PowerPoint media is not a valid PNG.")
    width, height = struct.unpack(">II", data[16:24])
    mode = {6: "RGBA"}.get(data[25], f"PNG color type {data[25]}")
    return width, height, mode


def extract(source: Path, output_dir: Path) -> Path:
    source = source.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)

    with ZipFile(source) as archive:
        slide_path, slide, slide_count, slide_width, slide_height = slide_member(archive)
        placements, media_members = picture_placements(archive, slide_path, slide)
        if set(placements) != set(MEDIA_ASSETS):
            raise RuntimeError(
                "PowerPoint media set changed: "
                f"expected {sorted(MEDIA_ASSETS)}, found {sorted(placements)}"
            )
        media_data = {
            media_name: archive.read(member)
            for media_name, member in media_members.items()
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    image_dir = output_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    source_output = output_dir / source.name
    shutil.copyfile(source, source_output)

    assets = {}
    for media_name, (asset_id, filename, role) in MEDIA_ASSETS.items():
        data = media_data[media_name]
        output_path = image_dir / filename
        output_path.write_bytes(data)
        width, height, image_mode = png_metadata(data)
        assets[asset_id] = {
            "role": role,
            "source_media": media_name,
            "output_path": relative_path(output_path),
            "sha256": sha256(data),
            "width": width,
            "height": height,
            "mode": image_mode,
            **placements[media_name],
        }

    provenance = {
        "version": 1,
        "source_path": relative_path(source_output),
        "source_filename": source.name,
        "source_sha256": sha256(source.read_bytes()),
        "slide_count": slide_count,
        "slide_width_inches": round(slide_width / EMU_PER_INCH, 6),
        "slide_height_inches": round(slide_height / EMU_PER_INCH, 6),
        "extraction_method": "Direct OOXML media extraction with Python standard library",
        "assets": assets,
    }
    provenance_path = output_dir / "provenance.json"
    provenance_path.write_text(
        json.dumps(provenance, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return provenance_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Path to Presentation_ALL_HARDWARE.pptx")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Extraction directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    provenance_path = extract(args.source, args.output_dir.expanduser().resolve())
    print(f"Wrote {provenance_path}")


if __name__ == "__main__":
    main()