#!/usr/bin/env python3
"""Merge per-plane-group extractor outputs into one committed intermediate.

The extraction reads a multi-gigabyte NWB from object storage, so it is often
convenient to run it as several smaller scheduler jobs -- one per visual area,
say -- rather than one long job that loses everything if it is pre-empted.
Each part is a complete document covering a subset of planes; this merges them
back into the single file the renderer consumes.

Parts must agree on session and schema. Planes are re-sorted into depth order
within area, so the merged file does not depend on the order the parts were
produced or listed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_mesoscope_plane_snr import order_planes  # noqa: E402

SHARED_KEYS = ("schemaVersion", "sessionId", "sessionSource", "excerptSeconds",
               "excerptStartFraction", "metricDefinitions")


def merge(parts: list[Path], out: Path) -> None:
    docs = [json.loads(p.read_text(encoding="utf-8")) for p in parts]
    if not docs:
        raise SystemExit("no parts given")

    head = docs[0]
    for path, doc in zip(parts[1:], docs[1:], strict=True):
        for key in SHARED_KEYS:
            if doc.get(key) != head.get(key):
                raise SystemExit(
                    f"{path.name}: {key} differs from {parts[0].name} "
                    f"({doc.get(key)!r} vs {head.get(key)!r}); parts must come "
                    f"from the same session and extractor version")

    planes: list[dict] = []
    seen: set[str] = set()
    for path, doc in zip(parts, docs, strict=True):
        for plane in doc["planes"]:
            if plane["plane"] in seen:
                raise SystemExit(f"{path.name}: plane {plane['plane']} appears twice")
            seen.add(plane["plane"])
            planes.append(plane)

    merged = {key: head[key] for key in SHARED_KEYS if key in head}
    merged["planes"] = order_planes(planes)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(merged, indent=1, sort_keys=True, allow_nan=False) + "\n",
                   encoding="utf-8")
    total = sum(p["nRois"] for p in merged["planes"])
    print(f"wrote {out} | {len(merged['planes'])} planes | {total} ROIs | "
          f"{out.stat().st_size / 1e6:.1f} MB")
    print("plane order: " + ", ".join(
        f"{p['plane']}({'' if p['depthUm'] is None else round(p['depthUm'])}um)"
        for p in merged["planes"]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("parts", type=Path, nargs="+")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    merge(args.parts, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
