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


Run outside the repo build: needs scipy (not a repo dependency) and the
per-ROI cohort table, which is too large to commit and is pinned by
checksum in figure_sources/data/mesoscope-unit-extraction.provenance.json.
"""
from __future__ import annotations

import base64
import io
import json
import pathlib
import sys
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.ndimage import binary_erosion

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

def decode_plane(p):
    raw_dff = np.frombuffer(base64.b64decode(p["dffBase64"]), dtype="<i2")
    raw_ev = np.frombuffer(base64.b64decode(p["eventsBase64"]), dtype="<i2")
    dff = raw_dff.astype(np.float32) * p["dffScale"]
    ev = raw_ev.astype(np.float32) * p["eventsScale"]
    n, f = p["nRois"], p["excerptFrames"]
    return dff.reshape(n, f), ev.reshape(n, f)


def build_planes(payload, cls_lookup):
    out = []
    for p in payload["planes"]:
        h, w = p["imageHeight"], p["imageWidth"]
        runs = np.frombuffer(base64.b64decode(p["maskRunsBase64"]), dtype="<u2")
        offs = p["maskRunOffsets"]
        lab = np.full((h, w), -1, dtype=np.int32)
        rc = {}
        for i, rr in enumerate(p["rois"]):
            for k in range(offs[i], offs[i + 1], 3):
                row, col, ln = int(runs[k]), int(runs[k + 1]), int(runs[k + 2])
                lab[row, col:col + ln] = i
            rc[i] = cls_lookup.get((p["plane"], rr["roi_index"]))
        out.append(dict(plane=p["plane"], depth=p["depthUm"], n=p["nRois"],
                        projection=mpl.image.imread(io.BytesIO(base64.b64decode(p["projectionPng"]))),
                        labels=lab, roi_class=rc, raw=p))
    return out


def onsets(e):
    o = np.zeros(e.shape, bool)
    o[1:] = (e[1:] > 0) & (e[:-1] <= 0)
    o[0] = e[0] > 0
    return o


def pick_example(planes_):
    """Brightest-firing mid-sized High SNR ROI, as in the 27-session build."""
    best = None
    for q in planes_:
        dffq, evq = decode_plane(q["raw"])
        for i, rr in enumerate(q["raw"]["rois"]):
            if q["roi_class"][i] != "High SNR":
                continue
            nev = int((evq[i] > 0).sum())
            if 150 <= rr["roi_area_pix"] <= 450 and (best is None or nev > best[0]):
                best = (nev, q, i, rr, dffq[i], evq[i])
    return best


def render(cohort: pd.DataFrame, payload_path: str, inputs: dict) -> dict:
    counts = inputs["counts"]
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
        zoom_edge=mem & ~binary_erosion(mem, np.ones((3, 3), bool)),
    )
    cnts_b = {"n_rois": int(len(ses)),
              "per_class": ses["amp_threshold_quality_class"].value_counts().to_dict()}

    plt.close("all")
    fig_b = M.panel_B(planes, example, cnts_b, "figure6_panelB_mesoscope.png", SESSION_LABEL)
    fig_b.savefig("figure6_panelB_mesoscope.svg")
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
                      "figure6_panelF_mesoscope.png", ex_label)
    fig_f.savefig("figure6_panelF_mesoscope.svg")
    plt.close(fig_f)

    # ---- J -------------------------------------------------------------
    fig_j = M.panel_J(inputs["by_area"], inputs["by_depth"], inputs["by_session"], counts,
                      "figure6_panelJ_mesoscope.png", by_mouse=inputs["by_mouse"])
    fig_j.savefig("figure6_panelJ_mesoscope.svg")
    plt.close(fig_j)
    return {"example": example, "counts_b": cnts_b, "examples_F": examples}
