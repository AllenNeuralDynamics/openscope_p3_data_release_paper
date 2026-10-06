"""Platform-stable encodings for publication raster images."""

from __future__ import annotations

import base64
import hashlib
import zlib
from io import BytesIO
from xml.dom import minidom

from PIL.PngImagePlugin import PngStream, putchunk


def canonical_png(data: bytes) -> bytes:
    """Normalize lossless compression without changing PNG scanlines or metadata."""
    source = BytesIO(data)
    signature = source.read(8)
    if signature != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Expected a PNG image.")
    output = BytesIO()
    output.write(signature)
    chunks = PngStream(source)
    compressed = bytearray()
    while True:
        chunk_type, _position, length = chunks.read()
        payload = source.read(length)
        chunks.crc(chunk_type, payload)
        if chunk_type == b"IDAT":
            compressed.extend(payload)
        else:
            if compressed:
                putchunk(output, b"IDAT", zlib.compress(zlib.decompress(compressed)))
                compressed.clear()
            putchunk(output, chunk_type, payload)
        if chunk_type == b"IEND":
            return output.getvalue()


def canonical_svg_images(svg: str) -> str:
    """Normalize embedded PNG compression and image IDs derived from those bytes."""
    document = minidom.parseString(svg)
    replacements = {}
    images = document.getElementsByTagNameNS("http://www.w3.org/2000/svg", "image")
    for image_index, image in enumerate(images):
        attribute = "xlink:href" if image.hasAttribute("xlink:href") else "href"
        value = image.getAttribute(attribute)
        prefix = "data:image/png;base64,"
        if not value.startswith(prefix):
            continue
        png = canonical_png(base64.b64decode(value[len(prefix):]))
        image.setAttribute(attribute, prefix + base64.b64encode(png).decode("ascii"))
        if image.hasAttribute("id"):
            identifier = f"image{image_index}_{hashlib.sha256(png).hexdigest()[:12]}"
            replacements[image.getAttribute("id")] = identifier
            image.setAttribute("id", identifier)
    for element in document.getElementsByTagName("*"):
        for attribute in list(element.attributes.values()):
            value = attribute.value
            for old, new in replacements.items():
                if value == f"#{old}":
                    value = f"#{new}"
                value = value.replace(f"url(#{old})", f"url(#{new})")
            if value != attribute.value:
                element.setAttribute(attribute.name, value)
    return document.toxml()