import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from openscope_p3_publication.site_hydration import bound_site_hydration

SOURCE = (
    "function hydrate(){};window.requestIdleCallback?"
    "window.requestIdleCallback(hydrate):window.setTimeout(hydrate,1);"
)


def site_fixture(tmp_path: Path) -> tuple[Path, Path]:
    build = tmp_path / "build"
    build.mkdir()
    entry = build / "entry.client-original.js"
    entry.write_text(SOURCE, encoding="utf-8")
    manifest = build / "manifest-original.js"
    manifest.write_text(
        "window.__remixManifest=" + json.dumps({
            "entry": {"module": "/paper/build/entry.client-original.js"},
            "url": "/paper/build/manifest-original.js",
        }) + ";", encoding="utf-8",
    )
    page = tmp_path / "index.html"
    page.write_text(
        '<h1>Manuscript retained</h1><script type="module">'
        'import "/paper/build/manifest-original.js";'
        'import("/paper/build/entry.client-original.js");</script>',
        encoding="utf-8",
    )
    return entry, page


def test_hydration_is_bounded_and_cache_distinct(tmp_path: Path) -> None:
    entry, page = site_fixture(tmp_path)
    original_page = page.read_text(encoding="utf-8")
    result = bound_site_hydration(tmp_path)
    asset = tmp_path / "build" / result["asset"]
    assert entry.read_text(encoding="utf-8") == SOURCE
    assert asset.read_text(encoding="utf-8") == SOURCE.replace(
        "requestIdleCallback(hydrate)", "requestIdleCallback(hydrate,{timeout:1500})"
    )
    assert page.read_text(encoding="utf-8") == original_page.replace(
        entry.name, asset.name
    ).replace("manifest-original.js", result["manifest"])
    manifest = (tmp_path / "build" / result["manifest"]).read_text(encoding="utf-8")
    data = json.loads(manifest.removeprefix("window.__remixManifest=").strip().removesuffix(";"))
    assert data["entry"]["module"] == "/paper/build/" + asset.name
    assert data["url"] == "/paper/build/" + result["manifest"]
    assert result["timeout_ms"] == 1500
    assert result["pages_updated"] == 1
    assert result["sha256"] == hashlib.sha256(asset.read_bytes()).hexdigest()


def test_hydration_patch_is_idempotent(tmp_path: Path) -> None:
    site_fixture(tmp_path)
    bound_site_hydration(tmp_path)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert bound_site_hydration(tmp_path)["pages_updated"] == 0
    assert before == {path: path.read_bytes() for path in before}


def test_hydration_scheduler_receives_a_deadline(tmp_path: Path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the hydration runtime check.")
    site_fixture(tmp_path)
    result = bound_site_hydration(tmp_path)
    source = (tmp_path / "build" / result["asset"]).read_text(encoding="utf-8")
    code = (
        "import {runInNewContext} from 'node:vm'; let deadline; let calls=0;"
        "const window={requestIdleCallback(callback,options){deadline=options.timeout;"
        "callback();calls+=1;},setTimeout(){throw new Error('Unexpected fallback');}};"
        f"runInNewContext({json.dumps(source)},{{window}});"
        "console.log(JSON.stringify({deadline,calls}));"
    )
    completed = subprocess.run(
        [node, "--input-type=module", "-e", code], check=True,
        capture_output=True, text=True, encoding="utf-8",
    )
    assert json.loads(completed.stdout) == {"deadline": 1500, "calls": 1}


@pytest.mark.parametrize("source", ["unknown bootstrap", SOURCE + SOURCE])
def test_unknown_hydration_bootstrap_is_not_modified(tmp_path: Path, source: str) -> None:
    entry, page = site_fixture(tmp_path)
    entry.write_text(source, encoding="utf-8")
    before = page.read_bytes()
    with pytest.raises(ValueError, match="Unrecognized"):
        bound_site_hydration(tmp_path)
    assert entry.read_text(encoding="utf-8") == source
    assert page.read_bytes() == before
    assert not list((tmp_path / "build").glob("hydration-entry-*"))


def test_unsupported_myst_version_is_rejected(tmp_path: Path) -> None:
    site_fixture(tmp_path)
    with pytest.raises(ValueError, match="Unsupported MyST"):
        bound_site_hydration(tmp_path, "1.11.0")


def test_missing_entry_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        bound_site_hydration(tmp_path)


def test_missing_page_reference_is_rejected(tmp_path: Path) -> None:
    entry, page = site_fixture(tmp_path)
    page.write_text("<h1>Unrelated HTML</h1>", encoding="utf-8")
    with pytest.raises(ValueError, match="No HTML references"):
        bound_site_hydration(tmp_path)
    assert entry.read_text(encoding="utf-8") == SOURCE


def test_invalid_runtime_manifest_is_rejected_without_writes(tmp_path: Path) -> None:
    site_fixture(tmp_path)
    manifest = tmp_path / "build" / "manifest-original.js"
    manifest.write_text("unrecognized manifest", encoding="utf-8")
    with pytest.raises(ValueError, match="Unrecognized MyST runtime manifest"):
        bound_site_hydration(tmp_path)
    assert not list((tmp_path / "build").glob("hydration-*"))