"""Generate collapsible PyNWB HTML snapshots from pinned public NWB assets."""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

import h5py
import remfile
from hdmf import __version__ as hdmf_version
from pynwb import NWBHDF5IO
from pynwb import __version__ as pynwb_version

REPO_ROOT = Path(__file__).resolve().parents[1]
ASSET_PROVENANCE = REPO_ROOT / "figure_sources" / "data" / "segmentation-viewers.provenance.json"
DEFAULT_OUTPUT = REPO_ROOT / "figure_sources" / "data" / "nwb-file-contents"
MODALITY_LABELS = {
    "neuropixels": "Neuropixels",
    "mesoscope": "Mesoscope",
    "slap2": "SLAP2",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--modality",
        action="append",
        choices=tuple(MODALITY_LABELS),
        help="Generate only the selected modality; may be repeated.",
    )
    return parser.parse_args()


def wrap_snapshot(modality: str, asset: dict[str, object], representation: str) -> str:
    label = MODALITY_LABELS[modality]
    path = html.escape(str(asset["path"]))
    dandiset_id = html.escape(str(asset["dandiset_id"]))
    dandiset_url = html.escape(str(asset["dandiset_url"]), quote=True)
    asset_id = html.escape(str(asset["asset_id"]))
    representation = re.sub(r"<style>.*?</style>", "", representation, flags=re.DOTALL)
    representation = re.sub(r"<script>.*?</script>", "", representation, flags=re.DOTALL)
    return f"""<div class="nwb-file-resource">
  <header class="nwb-resource-header">
    <strong>
      {label} representative file ·
      <a href="{dandiset_url}" target="_blank" rel="noreferrer">DANDI:{dandiset_id}</a>
    </strong>
    <p class="nwb-resource-source">
      {path}<br>Asset {asset_id} · PyNWB {pynwb_version} · HDMF {hdmf_version}
    </p>
  </header>
  {representation}
</div>
"""


def generate_snapshot(modality: str, asset: dict[str, object], output: Path) -> None:
    remote_file = remfile.File(str(asset["url"]))
    h5_file = h5py.File(remote_file, mode="r")
    io = NWBHDF5IO(file=h5_file, mode="r", load_namespaces=True)
    try:
        nwbfile = io.read()
        representation = nwbfile._repr_html_()
        page = wrap_snapshot(modality, asset, representation)
        output.write_text(page, encoding="utf-8", newline="\n")
    finally:
        io.close()
        remote_file.close()


def main() -> None:
    args = parse_args()
    provenance = json.loads(ASSET_PROVENANCE.read_text(encoding="utf-8"))
    modalities = args.modality or list(MODALITY_LABELS)
    args.output.mkdir(parents=True, exist_ok=True)
    for modality in modalities:
        output = args.output / f"{modality}.html"
        generate_snapshot(modality, provenance["assets"][modality], output)
        print(f"Wrote {output.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
