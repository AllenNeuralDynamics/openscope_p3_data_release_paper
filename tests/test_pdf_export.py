import csv
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from openscope_p3_publication.pdf_export import REPO_ROOT, prepare_pdf_assets, verify_pdf


def test_pdf_manifest_preserves_literature_without_processing_figures(tmp_path: Path) -> None:
    data = tmp_path / "figure_sources" / "data"
    data.mkdir(parents=True)
    rows = [
        ["Publication", "First study", "Second study"],
        ["Stimulus", "Quoted, multiline\nvalue", "Other value"],
        ["Sampling", "0.05", "140"],
    ]
    source = data / "other-oddball-studies.csv"
    with source.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream).writerows(rows)
    manifest_path = prepare_pdf_assets(tmp_path)
    first = manifest_path.read_bytes()
    manifest = json.loads(first)
    assert manifest["literature"]["rows"] == rows
    assert manifest["literature"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert "figures" not in manifest
    assert list(manifest_path.parent.iterdir()) == [manifest_path]
    assert prepare_pdf_assets(tmp_path).read_bytes() == first


def run_node_check(code: str) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the MyST print plugin checks.")
    result = subprocess.run(
        [node, "--input-type=module", "-e", code],
        cwd=REPO_ROOT, check=True, capture_output=True, text=True, encoding="utf-8",
    )
    return json.loads(result.stdout)


def test_print_transform_restores_authors_dropdowns_and_fallbacks() -> None:
    result = run_node_check("""
import {preparePrintTree} from './pdf/print.mjs';
const tree = {children: [
  {type: 'anywidget', model: {authors: JSON.stringify({primary: [
    {name: 'First Author', orcid: '0000-0000-0000-0001', affiliations: [{name: 'Institute'}]},
    {name: 'Second Author', affiliations: [{name: 'Institute'}]},
  ]})}},
  {type: 'details', children: [
    {type: 'summary', children: [{type: 'text', value: 'Show Methods'}]},
    {type: 'paragraph', children: [{type: 'text', value: 'Methods retained'}]},
  ]},
  {type: 'iframe', src: './interactive/unit-yield.html', children: []},
  {type: 'iframe', src: './interactive/eye-tracking-viewer.html', children: []},
]};
preparePrintTree(tree);
const content = JSON.stringify(tree);
console.log(JSON.stringify({
  methods: content.includes('Methods retained'),
  dropdown: content.includes('"type":"details"'),
  widget: content.includes('"type":"anywidget"'),
  authors: content.includes('First Author') && content.includes('Second Author'),
  affiliationCount: (content.match(/Institute/g) ?? []).length,
  fallbacks: tree.children.filter(node => node.type === 'iframe')
    .map(node => node.children[0].url),
}));
""")
    assert result["methods"] and result["authors"]
    assert not result["dropdown"] and not result["widget"]
    assert result["affiliationCount"] == 1
    assert len(result["fallbacks"]) == 2
    assert all((REPO_ROOT / path).is_file() for path in result["fallbacks"])


@pytest.mark.parametrize("interactive", [False, True])
@pytest.mark.parametrize("enumerated", [False, True, None])
def test_figures_use_native_myst_nodes_and_original_assets(
    interactive: bool, enumerated: bool | None,
) -> None:
    result = run_node_check("""
import {preparePrintTree} from './pdf/print.mjs';
const image = {type: 'image', url: './images/original.svg', width: '640px',
  height: '900px', alt: 'Original alt text'};
const caption = {type: 'caption', children: [{type: 'text', value: 'Full caption'}]};
const picture = INTERACTIVE ? {type: 'iframe', children: [image]} : image;
const tree = {children: [{type: 'container', kind: 'figure', identifier: 'fig-original',
  enumerated: ENUMERATED, children: [picture, caption]}]};
preparePrintTree(tree, {figures: {'original.svg': {
  panels: [{url: './unwanted-cropped-panel.svg'}],
}}});
console.log(JSON.stringify(tree.children[0]));
""".replace("INTERACTIVE", json.dumps(interactive)).replace("ENUMERATED", json.dumps(enumerated)))
    if enumerated is False:
        assert result["type"] == "div"
        assert result["children"][0] == {
            "type": "raw", "typst": "#[\n#set figure(numbering: none)\n",
        }
        assert result["children"][-1] == {"type": "raw", "typst": "\n]\n"}
        result = result["children"][1]
    assert result["type"] == "container" and result["kind"] == "figure"
    assert result["identifier"] == "fig-original" and result["enumerated"] is enumerated
    assert result["children"] == [
        {"type": "image", "url": "./images/original.svg", "width": "100%",
         "alt": "Original alt text"},
        {"type": "caption", "children": [{"type": "text", "value": "Full caption"}]},
    ]


@pytest.mark.parametrize("caption", [
    "Figure 11: Supplementary Figure 1. Caption.",
    "Figure 7: Figure 7. Caption.",
])
def test_pdf_validation_rejects_duplicate_caption_labels(tmp_path: Path, caption: str) -> None:
    pymupdf = pytest.importorskip("pymupdf")
    output = tmp_path / "duplicate.pdf"
    with pymupdf.open() as document:
        document.new_page().insert_text((70, 70), caption)
        document.save(output)
    with pytest.raises(ValueError, match="Duplicate figure caption labels"):
        verify_pdf(output)


def test_native_supplement_caption_has_one_label_without_affecting_main_figures(
    tmp_path: Path,
) -> None:
    pymupdf = pytest.importorskip("pymupdf")
    compiler = shutil.which("typst")
    if not compiler:
        pytest.skip("Typst is required for compiled caption checks.")
    wrapper = run_node_check("""
import {preparePrintTree} from './pdf/print.mjs';
const tree = {children: [{type: 'container', kind: 'figure', enumerated: false,
  identifier: 'fig-supplement', children: [{type: 'image', url: './original.svg'}]}]};
preparePrintTree(tree);
const wrappers = tree.children[0].children.filter(node => node.type === 'raw');
console.log(JSON.stringify({prefix: wrappers[0].typst, suffix: wrappers[1].typst}));
""")
    source = tmp_path / "captions.typ"
    source.write_text(
        '#set page(paper: "a4", margin: 20mm)\n'
        '#figure(rect(width: 20pt, height: 20pt), caption: [Main caption.]) <fig-main>\n'
        + wrapper["prefix"]
        + '#figure(rect(width: 20pt, height: 20pt), '
        'caption: [#strong[Supplementary Figure 1.] Supplemental caption.]) <fig-supplement>\n'
        + wrapper["suffix"]
        + '#figure(rect(width: 20pt, height: 20pt), '
        'caption: [Second main caption.]) <fig-second>\n',
        encoding="utf-8",
    )
    output = tmp_path / "captions.pdf"
    subprocess.run([compiler, "compile", str(source), str(output)], check=True,
                   capture_output=True, text=True, encoding="utf-8")
    with pymupdf.open(output) as document:
        text = " ".join(page.get_text() for page in document)
    normalized = " ".join(text.split())
    assert "Figure 1: Main caption." in normalized
    assert re.search(r"Figure \d+: Second main caption\.", normalized)
    assert normalized.count("Supplementary Figure 1.") == 1
    assert not re.search(r"Figure \d+:\s+Supplementary Figure", normalized)


def test_print_table_retains_its_methods_reference_target() -> None:
    result = run_node_check("""
import {preparePrintTree} from './pdf/print.mjs';
const tree = {children: [{type: 'table', identifier: 'neuropixels-implant-coordinates',
    children: [{type: 'tableRow', children: [
        {type: 'tableCell', header: true, children: [{type: 'text', value: 'Probe port'}]},
        {type: 'tableCell', header: true, children: [{type: 'text', value: 'AP (mm)'}]},
    ]}]}]};
preparePrintTree(tree);
console.log(JSON.stringify({identifier: tree.children[0].identifier,
    label: tree.children[0].children.some(node =>
        node.typst?.includes('#label("neuropixels-implant-coordinates")'))}));
""")
    assert result == {"identifier": "neuropixels-implant-coordinates", "label": True}


def test_print_literature_preserves_every_csv_cell() -> None:
    result = run_node_check("""
import {preparePrintTree} from './pdf/print.mjs';
const tree = {children: [{type: 'container', kind: 'figure', enumerated: false,
  identifier: 'table-supplementary-oddball-studies', children: []}]};
const rows = [['Publication', 'Study A', 'Study B'], ['Units', '17', '28'],
  ['Description', 'First, with comma', 'Second with\\nline break']];
preparePrintTree(tree, {literature: {rows}});
const values = [];
function visit(node) {
  if (node.type === 'text') values.push(node.value);
  (node.children ?? []).forEach(visit);
}
visit(tree);
console.log(JSON.stringify({values, serialized: JSON.stringify(tree)}));
""")
    for value in ["Study A", "Study B", "17", "28", "First, with comma", "Second with\nline break"]:
        assert value in result["values"]
    assert "table.header" in result["serialized"]
    assert "tablex" not in result["serialized"]


def test_pdf_profile_is_separate_from_the_website() -> None:
    web = (REPO_ROOT / "myst.yml").read_text(encoding="utf-8")
    profile = (REPO_ROOT / "pdf" / "myst.yml").read_text(encoding="utf-8")
    assert "print.mjs" not in web
    assert "../index.md" in profile
    assert "./print.mjs" in profile
    assert "format: typst" in profile
    assert "../_build/exports/openscope-p3.pdf" in profile


@pytest.mark.parametrize(("width", "height"), [(2400, 160), (160, 2400), (450, 300)])
def test_native_figures_fill_width_unless_limited_by_page_height(
    tmp_path: Path, width: int, height: int,
) -> None:
    pymupdf = pytest.importorskip("pymupdf")
    compiler = shutil.which("typst")
    if not compiler:
        pytest.skip("Typst is required for compiled figure-bounds checks.")
    shutil.copyfile(REPO_ROOT / "pdf" / "template" / "print.typ", tmp_path / "print.typ")
    (tmp_path / "source.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<rect width="{width}" height="{height}" fill="red"/></svg>', encoding="utf-8",
    )
    source = tmp_path / "fixture.typ"
    source.write_text(
        '#import "print.typ": fitPrintImage\n'
        '#set page(paper: "a4", margin: (x: 20mm, top: 20mm, bottom: 18mm))\n'
        '#show image.where(height: auto): fitPrintImage\n'
        '#show figure: set block(breakable: true)\n'
        '#figure(image("source.svg", width: 100%), caption: [Short caption.])'
        '<fig-test>\n', encoding="utf-8",
    )
    output = tmp_path / "fixture.pdf"
    subprocess.run([compiler, "compile", str(source), str(output)], check=True,
                   capture_output=True, text=True, encoding="utf-8")
    with pymupdf.open(output) as document:
        assert all(page.rect.height > page.rect.width for page in document)
        drawings = [(page, drawing["rect"]) for page in document for drawing in page.get_drawings()
                    if drawing.get("fill") == (1, 0, 0)]
        assert len(drawings) == 1
        page, bounds = drawings[0]
        margin = 20 * 72 / 25.4
        text_width = page.rect.width - 2 * margin
        maximum_height = 205 * 72 / 25.4
        expected_width = min(text_width, maximum_height * width / height)
        assert bounds.width == pytest.approx(expected_width, abs=0.1)
        assert bounds.height <= maximum_height + 0.1
        assert bounds.x0 >= margin - 0.1
        assert bounds.x1 <= page.rect.width - margin + 0.1
        assert bounds.y0 >= margin - 0.1
        assert bounds.y1 <= page.rect.height - 18 * 72 / 25.4 + 0.1
        assert bounds.width / bounds.height == pytest.approx(width / height, rel=0.005)


def test_pdf_validation_rejects_a_contentless_pdf(tmp_path: Path) -> None:
    pymupdf = pytest.importorskip("pymupdf")
    path = tmp_path / "empty.pdf"
    with pymupdf.open() as document:
        document.new_page()
        document.save(path)
    with pytest.raises(ValueError, match="Missing PDF content"):
        verify_pdf(path)


def test_pdf_validation_rejects_landscape_pages(tmp_path: Path) -> None:
    pymupdf = pytest.importorskip("pymupdf")
    path = tmp_path / "landscape.pdf"
    with pymupdf.open() as document:
        document.new_page(width=842, height=595)
        document.save(path)
    with pytest.raises(ValueError, match="portrait-only profile"):
        verify_pdf(path)
