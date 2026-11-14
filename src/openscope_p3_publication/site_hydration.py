"""Bound MyST hydration startup and defer off-screen publication figures."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from html import escape
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[2]
SUPPORTED_MYST = "1.10.1"
HYDRATION_CALL = re.compile(r"(window\.requestIdleCallback\()([A-Za-z_$][\w$]*)(\))")
FIGURE_STARTUP = """(() => {
    const frames = document.querySelectorAll("iframe[data-publication-src]");
    const load = frame => {
        frame.src = frame.dataset.publicationSrc;
        frame.removeAttribute("data-publication-src");
    };
    if (!window.IntersectionObserver) {
        frames.forEach(load);
        return;
    }
    const observer = new window.IntersectionObserver(entries => {
        for (const entry of entries) {
            if (entry.isIntersecting) {
                load(entry.target);
                observer.unobserve(entry.target);
            }
        }
    }, {rootMargin: "1200px 0px"});
    frames.forEach(frame => observer.observe(frame));
})();
"""


class _LazyIframeParser(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=False)
        self.line_offsets = [0]
        for line in source.splitlines(keepends=True):
            self.line_offsets.append(self.line_offsets[-1] + len(line))
        self.replacements: list[tuple[int, int, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag != "iframe" or not attributes.get("src") or attributes.get("loading") == "eager":
            return
        updated = [
            ("data-publication-src" if name == "src" else name, value)
            for name, value in attrs
        ]
        if "loading" not in attributes:
            updated.append(("loading", "lazy"))
        rendered = "<iframe" + "".join(
            f' {name}="{escape(value, quote=True)}"' if value is not None else f" {name}"
            for name, value in updated
        ) + ">"
        line, column = self.getpos()
        start = self.line_offsets[line - 1] + column
        self.replacements.append((start, start + len(self.get_starttag_text()), rendered))


def _lazy_figure_frames(source: str) -> str:
    parser = _LazyIframeParser(source)
    parser.feed(source)
    for start, end, rendered in reversed(parser.replacements):
        source = source[:start] + rendered + source[end:]
    return source


def bound_site_hydration(html_dir: Path, myst_version: str = SUPPORTED_MYST) -> dict:
    """Write a cache-distinct bounded bootstrap, preserving the original build asset."""
    if myst_version.removeprefix("v") != SUPPORTED_MYST:
        raise ValueError(f"Unsupported MyST version: {myst_version}; review its bootstrap first.")
    entries = sorted((html_dir / "build").glob("entry.client-*.js"))
    if len(entries) != 1:
        raise ValueError("Expected exactly one MyST entry.client asset.")
    entry = entries[0]
    source = entry.read_text(encoding="utf-8")
    if len(HYDRATION_CALL.findall(source)) != 1:
        raise ValueError("Unrecognized MyST hydration bootstrap; refusing to patch it.")
    patched = FIGURE_STARTUP + HYDRATION_CALL.sub(r"\1\2,{timeout:1500}\3", source)
    digest = hashlib.sha256(patched.encode("utf-8")).hexdigest()
    name = f"hydration-entry-{digest[:20]}.js"
    manifests = sorted((html_dir / "build").glob("manifest-*.js"))
    if len(manifests) != 1:
        raise ValueError("Expected exactly one MyST runtime manifest.")
    manifest = manifests[0]
    manifest_source = manifest.read_text(encoding="utf-8").strip()
    prefix = "window.__remixManifest="
    if not manifest_source.startswith(prefix):
        raise ValueError("Unrecognized MyST runtime manifest.")
    data = json.loads(manifest_source[len(prefix):].removesuffix(";"))
    module = data.get("entry", {}).get("module", "")
    url = data.get("url", "")
    if PurePosixPath(module).name != entry.name or PurePosixPath(url).name != manifest.name:
        raise ValueError("MyST runtime manifest does not match its bootstrap assets.")
    data["entry"]["module"] = str(PurePosixPath(module).with_name(name))
    manifest_digest = hashlib.sha256(
        json.dumps(data, sort_keys=True).encode("utf-8")
    ).hexdigest()
    manifest_name = f"hydration-manifest-{manifest_digest[:20]}.js"
    data["url"] = str(PurePosixPath(url).with_name(manifest_name))
    manifest_patched = prefix + json.dumps(data, separators=(",", ":")) + ";\n"
    pages = sorted(html_dir.rglob("*.html"))
    changes = []
    existing_references = 0
    for page in pages:
        text = page.read_text(encoding="utf-8")
        existing_references += text.count(manifest_name)
        if any(reference in text for reference in (entry.name, manifest.name, manifest_name)):
            updated = _lazy_figure_frames(text).replace(entry.name, name).replace(
                manifest.name, manifest_name
            )
            if updated != text:
                changes.append((page, updated))
    if not changes:
        asset = html_dir / "build" / name
        if (
            not existing_references or not asset.exists()
            or asset.read_text(encoding="utf-8") != patched
            or not (html_dir / "build" / manifest_name).exists()
            or (html_dir / "build" / manifest_name).read_text(encoding="utf-8") != manifest_patched
        ):
            raise ValueError("No HTML references to the supported bootstrap were found.")
        return {"status": "already bounded", "asset": name, "pages_updated": 0}
    asset = html_dir / "build" / name
    asset.write_text(patched, encoding="utf-8", newline="\n")
    (html_dir / "build" / manifest_name).write_text(
        manifest_patched, encoding="utf-8", newline="\n"
    )
    for page, text in changes:
        page.write_text(text, encoding="utf-8", newline="\n")
    return {
        "status": "bounded", "myst_version": SUPPORTED_MYST, "timeout_ms": 1500,
        "original_asset": entry.name, "asset": name, "sha256": digest,
        "manifest": manifest_name, "pages_updated": len(changes),
    }


def main() -> None:
    """Apply the bounded hydration bootstrap after a static MyST HTML build."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html-dir", type=Path, default=REPO_ROOT / "_build" / "html")
    parser.add_argument("--myst-version", default=SUPPORTED_MYST)
    args = parser.parse_args()
    print(json.dumps(bound_site_hydration(args.html_dir, args.myst_version), indent=2))


if __name__ == "__main__":
    main()