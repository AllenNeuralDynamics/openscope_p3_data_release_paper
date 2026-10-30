"""Render the mesoscope column (panels B, F, J) from the 81-session QC-Pass cohort.

Two corrections relative to the 27-session build:

1. Quality class is now fitted ONCE over the whole cohort, not within each
   session. The per-session fit is retained as `amp_threshold_quality_class_session`.
   This mirrors the SLAP2 sibling column (PR #171), whose panels use the
   archive-wide `quality_class` and keep `quality_class_session` alongside it,
   and it makes panel F's "one fit over all sessions" footnote true.

2. Panel B's footprint colours are JOINED from the cohort table on
   (plane, roi_index) instead of being re-derived from a dominant-fraction
   rule, which agrees with the k-means class only ~69% of the time.


Run outside the repo build. Inputs are both committed:

    python scripts/build_mesoscope_unit_extraction_panels.py \\
        --cohort figure_sources/data/mesoscope-unit-extraction-roi-metrics.csv.gz \\
        --payload figure_sources/data/mesoscope-unit-extraction-example-session.json \\
        --out-dir figure_sources/media/mesoscope-unit-extraction

writes panel-b.png, panel-f.png, panel-j.png (plus SVGs) and the stacked
composite figure-06-unit-extraction-mesoscope.png into --out-dir. The cohort
table is the 17-column per-ROI snapshot produced by
scripts/extract_mesoscope_roi_metrics.py; its checksum and the renderer
checksums are recorded in figure_sources/data/
mesoscope-unit-extraction.provenance.json. Needs numpy, pandas, matplotlib
and Pillow (all repo dependencies); nothing here touches the network.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from openscope_p3_publication.mesoscope_unit_extraction import (
    DEPTH_ORDER as DEPTH_ORDER,
)
from openscope_p3_publication.mesoscope_unit_extraction import (
    build_planes,
    decode_plane,
    load_cohort,
    onsets,
    panel_inputs,
    pick_example,
)
from openscope_p3_publication.mesoscope_unit_extraction import (
    shares as shares,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mesoscope_matched_panels as M

SESSION = "839909_2026-02-26"
SESSION_LABEL = "multiplane-ophys_839909_2026-02-26"
FR = ["frac_events_lt2sd", "frac_events_2_4sd", "frac_events_gt4sd"]


# Layout of the committed composite. It is built here rather than in the figure
# build because Pillow's PNG output depends on the local zlib build, so
# re-encoding at build time makes the generated SVG platform-dependent.
PAD, GAP, HEADER = 40, 60, 150


def compose(panel_dir: pathlib.Path) -> pathlib.Path:
    """Stack panels B, F and J into the committed composite PNG."""
    from PIL import Image

    panels = [Image.open(panel_dir / f"panel-{k}.png").convert("RGB") for k in ("b", "f", "j")]
    width = max(p.width for p in panels) + 2 * PAD
    height = HEADER + sum(p.height for p in panels) + GAP * (len(panels) - 1) + PAD
    canvas = Image.new("RGB", (width, height), "#FFFFFF")
    offset = HEADER
    for panel in panels:
        canvas.paste(panel, ((width - panel.width) // 2, offset))
        offset += panel.height + GAP
    out = panel_dir / "figure-06-unit-extraction-mesoscope.png"
    canvas.save(out, format="PNG", optimize=True)
    return out

def render(cohort: pd.DataFrame, payload_path: str, inputs: dict,
           out_dir: pathlib.Path = pathlib.Path(".")) -> dict:
    counts = inputs["counts"]
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ses = cohort[cohort["session"] == SESSION]
    cls_lookup = {(r.plane, int(r.roi_index)): r.amp_threshold_quality_class
                  for r in ses.itertuples()}

    payload = json.loads(pathlib.Path(payload_path).read_bytes())
    planes = build_planes(payload, cls_lookup)
    planes.sort(key=lambda q: (q["plane"].split("_")[0] != "VISp", q["depth"]))

    unresolved = sum(v is None for q in planes for v in q["roi_class"].values())
    if unresolved:
        raise SystemExit(f"{unresolved} payload ROIs have no cohort class — join key mismatch")

    # ---- B -------------------------------------------------------------
    nev, q_ex, i_ex, rr_ex, dtr, dev = pick_example(planes)
    h2, w2 = q_ex["labels"].shape
    ys, xs = np.nonzero(q_ex["labels"] == i_ex)
    pad = 30
    zs = (slice(max(0, ys.min() - pad), min(h2, ys.max() + pad)),
          slice(max(0, xs.min() - pad), min(w2, xs.max() + pad)))
    mem = (q_ex["labels"] == i_ex)[zs]
    same_plane = ses["plane"] == q_ex["plane"]
    ex_row = ses[same_plane & (ses["roi_index"] == int(rr_ex["roi_index"]))].iloc[0]

    example = dict(
        plane=q_ex["plane"], roi=int(rr_ex["roi_index"]), cx=xs.mean(), cy=ys.mean(),
        area=rr_ex["roi_area_pix"], cls=ex_row["amp_threshold_quality_class"],
        t=np.arange(q_ex["raw"]["excerptFrames"]) * q_ex["raw"]["dtSeconds"],
        trace=dtr, events=onsets(dev).astype(float),
        rate_hz=float(ex_row["event_rate_hz"]), n_events=int(ex_row["n_events"]),
        zoom=q_ex["projection"][zs],
        zoom_edge=M.mask_outline(mem),
    )
    cnts_b = {"n_rois": int(len(ses)),
              "per_class": ses["amp_threshold_quality_class"].value_counts().to_dict()}

    plt.close("all")
    fig_b = M.panel_B(planes, example, cnts_b, str(out_dir / "panel-b.png"), SESSION_LABEL)
    fig_b.savefig(out_dir / "panel-b.svg")
    plt.close(fig_b)

    # ---- F -------------------------------------------------------------
    pl = next(q["raw"] for q in planes if q["plane"] == example["plane"])
    idx = next(i for i, r in enumerate(pl["rois"]) if r["roi_index"] == example["roi"])
    dffq, evq = decode_plane(pl)
    noise = pl["rois"][idx]["baseline_noise_sd"]
    t = np.arange(pl["excerptFrames"]) * pl["dtSeconds"]
    ex_label = (f"ROI {example['roi']}, {pl['plane']} ({pl['structure']}, "
                f"{pl['depthUm']:.0f} \u00b5m) \u2014 the ROI of panel B")

    examples = []
    for cls in M.CLASS_ORDER:
        sub = ses[ses["amp_threshold_quality_class"] == cls]
        cen = cohort.loc[cohort["amp_threshold_quality_class"] == cls, FR].mean().values
        examples.append((cls, sub.iloc[int(np.linalg.norm(sub[FR].values - cen, axis=1).argmin())]))

    fig_f = M.panel_F(dffq[idx] / noise, t, evq[idx] / noise, examples, cohort, counts,
                      str(out_dir / "panel-f.png"), ex_label)
    fig_f.savefig(out_dir / "panel-f.svg")
    plt.close(fig_f)

    # ---- J -------------------------------------------------------------
    fig_j = M.panel_J(inputs["by_area"], inputs["by_depth"], inputs["by_session"], counts,
                      str(out_dir / "panel-j.png"), by_mouse=inputs["by_mouse"])
    fig_j.savefig(out_dir / "panel-j.svg")
    plt.close(fig_j)
    return {"example": example, "counts_b": cnts_b, "examples_F": examples}


# ---------------------------------------------------------------------------
# Cohort aggregation for panel J and the caption counts.
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cohort", required=True, type=pathlib.Path,
                    help="per-ROI cohort table (figure_sources/data/*.csv.gz)")
    ap.add_argument("--payload", required=True, type=pathlib.Path,
                    help="example-session viewer payload JSON for panel B")
    ap.add_argument("--out-dir", required=True, type=pathlib.Path)
    ap.add_argument("--no-compose", action="store_true",
                    help="write the three panels only, skip the stacked composite")
    args = ap.parse_args(argv)

    cohort = load_cohort(args.cohort)
    inputs = panel_inputs(cohort)
    c = inputs["counts"]
    print(f"{c['sessions']} sessions, {c['mice']} mice, {c['rois']:,} ROIs; "
          f"classes {c['per_class']}")
    render(cohort, str(args.payload), inputs, out_dir=args.out_dir)
    for k in ("b", "f", "j"):
        print(f"wrote {args.out_dir / f'panel-{k}.png'}")
    if not args.no_compose:
        print(f"wrote {compose(args.out_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
