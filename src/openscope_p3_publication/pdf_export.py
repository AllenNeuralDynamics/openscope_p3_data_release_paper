"""Build and validate the publication with MyST's Typst exporter."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def prepare_pdf_assets(repo_root: Path = REPO_ROOT) -> Path:
    """Prepare the literature table; figures are exported unchanged by MyST."""
    output_dir = repo_root / "_build" / "pdf-assets"
    output_dir.mkdir(parents=True, exist_ok=True)
    table_path = repo_root / "figure_sources" / "data" / "other-oddball-studies.csv"
    with table_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream))
    if len(rows) < 2 or any(len(row) != len(rows[0]) for row in rows):
        raise ValueError("The literature comparison must be a rectangular, nonempty CSV.")
    manifest = {
        "literature": {
            "source": table_path.relative_to(repo_root).as_posix(),
            "sha256": hashlib.sha256(table_path.read_bytes()).hexdigest(),
            "rows": rows,
        },
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def verify_pdf(path: Path) -> dict:
    """Reject missing manuscript sections, unresolved fallbacks, and page overflow."""
    import pymupdf

    with pymupdf.open(path) as document:
        landscape_pages = [page.number + 1 for page in document
                           if page.rect.width > page.rect.height]
        if landscape_pages:
            raise ValueError(
                f"Landscape PDF pages violate the portrait-only profile: {landscape_pages}"
            )
        text = "\n".join(page.get_text() for page in document)
        normalized = " ".join(text.replace("\u200b", "").replace("\xad", "").split())
        duplicate_captions = re.findall(
            r"\bFigure\s+\d+:\s+(?:Supplementary\s+)?Figure\s+\d+\b", normalized
        )
        if duplicate_captions:
            raise ValueError(f"Duplicate figure caption labels: {duplicate_captions}")
        required = [
            "All animal procedures were approved",
            "Neuronal recording modalities",
            "Neuropixels", "mesoscope", "SLAP2",
            "Supplementary Table 1",
            "References",
            *[f"Supplementary Figure {number}" for number in range(1, 6)],
        ]
        missing = [phrase for phrase in required if phrase not in normalized]
        missing.extend(
            f"Figure {number}" for number in range(1, 11)
            if not re.search(rf"\bFigure {number}[.:]", normalized)
        )
        if missing:
            raise ValueError(f"Missing PDF content: {missing}")
        if not document.metadata.get("author"):
            raise ValueError("The PDF must retain its source-backed author metadata.")
        overflow = []
        for page in document:
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        if not span["text"].strip():
                            continue
                        left, top, right, bottom = span["bbox"]
                        if (
                            left < -1 or top < -1
                            or right > page.rect.width + 1 or bottom > page.rect.height + 1
                        ):
                            overflow.append((page.number + 1, span["text"][:50]))
        if overflow:
            raise ValueError(f"Text outside PDF page bounds: {overflow[:10]}")
        return {"pages": len(document), "bytes": path.stat().st_size, "checks": "passed"}


def main() -> None:
    """Build and validate the print-only MyST PDF without changing the HTML project."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets-only", action="store_true")
    parser.add_argument("--typst", help="Path to Typst when it is not on PATH.")
    args = parser.parse_args()
    if args.assets_only:
        print(prepare_pdf_assets())
        return
    compiler = shutil.which(args.typst or "typst")
    launcher = shutil.which("npx")
    if not compiler or not launcher:
        parser.error("Install Node.js and Typst 0.15.1 or newer; use --typst for a local compiler.")
    prepare_pdf_assets()
    environment = dict(os.environ)
    environment["PATH"] = str(Path(compiler).parent) + os.pathsep + environment.get("PATH", "")
    started = time.time_ns()
    result = subprocess.run(
        [launcher, "--yes", "mystmd@1.10.1", "build", "--typst", "--strict"],
        cwd=REPO_ROOT / "pdf", env=environment, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
    )
    print(result.stdout)
    if re.search(r"(?m)^(?:warning|error):|\u26d4", result.stdout):
        raise RuntimeError("The PDF compiler reported warnings or errors; inspect the build log.")
    output = REPO_ROOT / "_build" / "exports" / "openscope-p3.pdf"
    if not output.exists() or output.stat().st_mtime_ns < started:
        raise RuntimeError("MyST did not produce a fresh PDF.")
    print(json.dumps({"output": str(output), **verify_pdf(output)}, indent=2))


if __name__ == "__main__":
    main()
