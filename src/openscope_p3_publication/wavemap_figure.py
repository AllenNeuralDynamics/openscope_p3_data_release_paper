"""Load the committed WaveMAP snapshot and render its offline explorers."""

from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import runpy
import shutil
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

import matplotlib as mpl
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from IPython.display import display
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_PATH = REPO_ROOT / "figure_sources" / "data" / "wavemap" / "wavemap-analysis.json.gz"
RENDERING_SOURCE = REPO_ROOT / "figure_sources/python/wavemap_rendering.py"
EXPLORER_NAMES = (
    "wavemap-area-explorer.html",
    "fs-sst-wavemap-explorer.html",
    "wavemap-context-explorer.html",
)


def _decode_publication(value):
    if isinstance(value, list):
        return [_decode_publication(v) for v in value]
    if not isinstance(value, dict) or "__type__" not in value:
        return value
    kind = value["__type__"]
    if kind == "dataframe":
        return pd.DataFrame(
            [{k: _decode_publication(v) for k, v in row.items()} for row in value["records"]],
            columns=value["columns"],
        )
    if kind == "series":
        return pd.Series([_decode_publication(v) for v in value["values"]], name=value.get("name"))
    if kind == "ndarray":
        data = _decode_publication(value["data"])
        arr = np.asarray(data)
        return arr.reshape(value["shape"])
    if kind == "tuple":
        return tuple(_decode_publication(v) for v in value["items"])
    if kind == "mapping":
        return {_decode_publication(k): _decode_publication(v) for k, v in value["items"]}
    raise RuntimeError(f"Unsupported WaveMAP snapshot object type: {kind}")


def load_wavemap_snapshot(path: Path = SNAPSHOT_PATH) -> dict:
    """Decode the unchanged snapshot after checking its provenance checksum."""
    if not path.exists():
        raise FileNotFoundError(
            f"WaveMAP publication snapshot not found: {path}. "
            "Refresh it with scripts/extract_wavemap_analysis.py."
        )
    provenance_path = path.with_suffix("").with_suffix(".provenance.json")
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != provenance["snapshot_sha256"]:
        raise RuntimeError("WaveMAP snapshot checksum does not match its provenance.")
    payload = json.loads(gzip.decompress(raw))
    if payload.get("format") != "openscope-p3-wavemap-publication-snapshot-v1":
        raise RuntimeError("Unsupported WaveMAP publication snapshot format.")
    snapshot = {name: _decode_publication(value) for name, value in payload["objects"].items()}
    units = snapshot["units_df"]
    if len(units) != len(snapshot["normWFs"]):
        raise RuntimeError("WaveMAP waveforms and unit metadata are not row-aligned.")
    if not units["unit_uid"].is_unique:
        raise RuntimeError("WaveMAP snapshot contains duplicate unit identifiers.")
    if not units["unit_uid"].equals(snapshot["map_df"]["unit_uid"]):
        raise RuntimeError("WaveMAP classification rows do not match the unit metadata.")
    return snapshot


def build_wavemap_figures(
    snapshot_path: Path = SNAPSHOT_PATH,
    *,
    output_root: Path = REPO_ROOT,
    snapshot: dict | None = None,
) -> tuple[Path, ...]:
    """Build the explorers without NWB access or notebook display requirements."""
    from plotly.offline import get_plotlyjs

    from openscope_p3_publication.figures import load_figure_stylesheet

    snapshot = load_wavemap_snapshot(snapshot_path) if snapshot is None else snapshot
    required = {
        "units_df",
        "normWFs",
        "group_embeddings",
        "CLASS_COLORS",
        "AREA_CLUSTER_COLORS",
        "map_df",
        "sst_opto_df",
        "region_context_summary",
        "enrich_df",
    }
    missing = sorted(required - set(snapshot))
    if missing:
        raise RuntimeError("WaveMAP snapshot is missing: " + ", ".join(missing))

    output_root = output_root.resolve()
    interactive_dir = output_root / "interactive"
    interactive_dir.mkdir(parents=True, exist_ok=True)
    vendor = interactive_dir / "vendor"
    vendor.mkdir(exist_ok=True)
    (vendor / "plotly.min.js").write_text(get_plotlyjs(), encoding="utf-8", newline="\n")
    plt.switch_backend("Agg")

    with tempfile.TemporaryDirectory(prefix="openscope_p3_wavemap_figures_") as tmp:
        static_dir = Path(tmp) / "static"
        static_dir.mkdir()
        ns = dict(snapshot)
        ns.update(
            {
                "__name__": "openscope_p3_publication.wavemap_figure.render",
                "np": np,
                "pd": pd,
                "plt": plt,
                "mcolors": mcolors,
                "sns": sns,
                "Patch": Patch,
                "Line2D": Line2D,
                "display": display,
                "shutil": shutil,
                "REPO_ROOT": output_root,
                "STATIC_DIR": static_dir,
                "FINAL_INTERACTIVE_DIR": interactive_dir,
                "OUT_DIR": Path(tmp),
                "_BUILD_TMP": type("_Tmp", (), {"name": tmp, "cleanup": lambda self: None})(),
                "WF_SAMPLING_RATE": verified_waveform_sampling_rate(snapshot),
                "WAVEFORM_SAMPLING_RATE": None,
            }
        )
        with mpl.rc_context(), redirect_stdout(io.StringIO()):
            runpy.run_path(str(RENDERING_SOURCE), init_globals=ns)
        plt.close("all")

    outputs = tuple(interactive_dir / name for name in EXPLORER_NAMES)
    missing_outputs = [str(p) for p in outputs if not p.exists()]
    if missing_outputs:
        raise RuntimeError("WaveMAP build did not produce: " + ", ".join(missing_outputs))
    for output in outputs:
        html = output.read_text(encoding="utf-8").replace(
            "https://cdn.plot.ly/plotly-2.35.2.min.js", "./vendor/plotly.min.js"
        )
        typography = load_figure_stylesheet("figure-typography.css")
        html = html.replace("</head>", f"<style>{typography}</style>\n</head>", 1)
        output.write_text(html, encoding="utf-8", newline="\n")
    return outputs


def verified_waveform_sampling_rate(snapshot: dict) -> float | None:
    """Return a common recorded rate, never the notebook's unverified fallback."""
    rates = pd.to_numeric(snapshot["units_df"]["waveform_sampling_rate_hz"], errors="coerce")
    if rates.isna().any() or not np.isfinite(rates).all() or (rates <= 0).any():
        return None
    unique = rates.unique()
    return float(unique[0]) if len(unique) == 1 else None


def build_wavemap_publication(output_root: Path = REPO_ROOT) -> tuple[Path, ...]:
    """Build Supplementary Figure 9 and stage its local runtime assets."""
    from openscope_p3_publication.figures import (
        load_embed_auto_height,
        load_figure_stylesheet,
    )
    from openscope_p3_publication.wavemap_publication_figures import (
        build_wavemap_static_figures,
    )

    snapshot = load_wavemap_snapshot()
    with mpl.rc_context():
        static = build_wavemap_static_figures(snapshot, output_root / "images/figures/generated")
        explorers = build_wavemap_figures(output_root=output_root, snapshot=snapshot)
    interactive_dir = output_root / "interactive"
    media_dir = interactive_dir / "media/wavemap"
    media_dir.mkdir(parents=True, exist_ok=True)
    pdf = next(path for path in static if path.name == "supplementary-wavemap.pdf")
    shutil.copyfile(pdf, media_dir / pdf.name)
    svg = next(path for path in static if path.suffix == ".svg")
    sources = REPO_ROOT / "figure_sources/javascript"
    html = (sources / "wavemap-supplement.html").read_text(encoding="utf-8")
    html = (
        html.replace("__WAVEMAP_STYLE__", load_figure_stylesheet("wavemap-supplement.css"))
        .replace(
            "__WAVEMAP_SCRIPT__",
            (sources / "wavemap-supplement.js").read_text(encoding="utf-8"),
        )
        .replace(
            "__WAVEMAP_STATIC__",
            "data:image/svg+xml;base64," + base64.b64encode(svg.read_bytes()).decode("ascii"),
        )
        .replace("__EMBED_AUTO_HEIGHT_JS__", load_embed_auto_height())
    )
    wrapper = interactive_dir / "wavemap-supplement.html"
    wrapper.write_text(html, encoding="utf-8", newline="\n")
    return (*static, *explorers, wrapper)


def main() -> None:
    """Regenerate the complete WaveMAP supplementary figure."""
    for output in build_wavemap_publication():
        print(f"Wrote {output.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
