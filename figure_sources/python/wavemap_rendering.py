from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import matplotlib as mpl
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from matplotlib.lines import Line2D
from plotly.subplots import make_subplots


def HTML(x):
    return x


def display(*args, **kwargs):
    return None


units_df: pd.DataFrame = globals()["units_df"]
normWFs: np.ndarray = globals()["normWFs"]
group_embeddings: dict = globals()["group_embeddings"]
AREA_CLUSTER_COLORS: dict = globals()["AREA_CLUSTER_COLORS"]
CLASS_COLORS: dict = globals()["CLASS_COLORS"]
CONTEXT_ORDER: list[str] = globals()["CONTEXT_ORDER"]
sst_opto_df: pd.DataFrame = globals()["sst_opto_df"]
enrich_df: pd.DataFrame = globals()["enrich_df"]
OUT_DIR: Path = globals()["OUT_DIR"]
REPO_ROOT: Path = globals()["REPO_ROOT"]
FINAL_INTERACTIVE_DIR: Path = globals()["FINAL_INTERACTIVE_DIR"]

# ============================================================
# MAIN PANEL A — WaveMAP landscape, FACETED BY FUNCTIONAL GROUP
#
# Cluster colours are FIXED by (area, local WaveMAP class) and are
# therefore identical to colours used in all downstream waveform,
# legend and interactive panels.
#
# Large clusters are drawn first only to keep small clusters visible;
# drawing order does NOT determine colour.
# ============================================================

label_col = "wavemap_local" if "wavemap_local" in units_df.columns else "wavemap_class"

groups_present = [g for g in group_embeddings.keys()]

n = len(groups_present)
ncol = min(3, n)
nrow = int(np.ceil(n / ncol))

fig, axes = plt.subplots(
    nrow,
    ncol,
    figsize=(4.6 * ncol, 4.3 * nrow),
    dpi=150,
    squeeze=False,
)

for k, g in enumerate(groups_present):
    ax = axes[k // ncol][k % ncol]

    idx, emb = group_embeddings[g]

    labs = units_df.iloc[idx][label_col].values

    valid = labs > 0

    vals, counts = np.unique(
        labs[valid],
        return_counts=True,
    )

    # Draw biggest first so smaller clusters remain visible on top.
    order = np.argsort(counts)[::-1]

    ranked = vals[order]
    ranked_counts = counts[order]

    colours = {int(c): AREA_CLUSTER_COLORS[(g, int(c))] for c in ranked}

    # Every local cluster within an area must have a distinct colour.
    _seen = {tuple(np.round(mcolors.to_rgba(v), 4)) for v in colours.values()}

    assert len(_seen) == len(colours), (
        f"{g}: {len(colours)} clusters but only {len(_seen)} unique colours."
    )

    tot = valid.sum()

    # Noise / unclustered points.
    if (~valid).any():
        ax.scatter(
            emb[~valid, 0],
            emb[~valid, 1],
            s=3,
            color="0.85",
            alpha=0.35,
            linewidths=0,
            rasterized=True,
        )

    for c, ct in zip(ranked, ranked_counts, strict=False):
        m = labs == c

        ax.scatter(
            emb[m, 0],
            emb[m, 1],
            s=7,
            alpha=0.85,
            color=colours[int(c)],
            linewidths=0,
            rasterized=True,
            label=(f"{g}-{int(c)}: {ct:,} ({100 * ct / tot:.0f}%)"),
        )

    ax.set_title(
        f"{g}  (n={len(idx):,}, {len(ranked)} classes)",
        fontsize=11,
    )

    ax.set_xlabel("UMAP 1")
    ax.set_ylabel("UMAP 2")

    ax.set_xticks([])
    ax.set_yticks([])

    ax.legend(
        frameon=False,
        fontsize=6.5,
        loc="best",
        markerscale=2.2,
        handletextpad=0.2,
        labelspacing=0.25,
    )

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


for k in range(n, nrow * ncol):
    axes[k // ncol][k % ncol].axis("off")


fig.suptitle(
    f"WaveMAP landscapes by functional group "
    f"({int((units_df[label_col] > 0).sum()):,} clustered units)",
    y=1.02,
)

fig.tight_layout()

fig.savefig(
    OUT_DIR / "MAIN_A_WaveMAP_UMAP_byGroup.png",
    bbox_inches="tight",
)

fig.savefig(
    OUT_DIR / "MAIN_A_WaveMAP_UMAP_byGroup.pdf",
    bbox_inches="tight",
)

plt.close(fig)


# ============================================================
# FIGURE — Session-normalized WaveMAP composition by context
#            WITHIN each anatomical group
#
# Scientific question:
# Within a given anatomical population, do the four predictive
# contexts sample a comparable mixture of local waveform classes?
#
# Important:
# - WaveMAP classes were discovered independently by region.
# - Therefore context comparisons are performed WITHIN region.
# - Each recording session contributes equally.
# ============================================================


# ------------------------------------------------------------
# Settings
# ------------------------------------------------------------

GROUP_ORDER = ["MO", "PFC", "VIS", "STR", "HPC", "THAL"]
GROUP_ORDER = [g for g in GROUP_ORDER if g in group_embeddings]

GROUP_NAMES = {
    "MO": "Motor cortex",
    "PFC": "Prefrontal cortex",
    "VIS": "Visual cortex",
    "STR": "Striatum",
    "HPC": "Hippocampus",
    "THAL": "Thalamus",
}

# Shorter labels for manuscript figure
CONTEXT_SHORT = {
    "Standard oddball": "Standard",
    "Sensorimotor mismatch": "Sensorimotor",
    "Sequence mismatch": "Sequence",
    "Duration mismatch": "Duration",
}

context_order = [c for c in CONTEXT_ORDER if c in units_df["context"].dropna().unique()]

# ------------------------------------------------------------
# Figure styling
# ------------------------------------------------------------

plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.size": 9,
        "axes.titlesize": 10,
        "axes.labelsize": 9,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "figure.dpi": 150,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    }
)

TEXT_GREY = "#666666"

# Use one perceptually uniform sequential scale for all panels.
# Same limits across regions = values can be compared visually.
CMAP = mpl.colormaps["viridis"]


# ------------------------------------------------------------
# 1. Prepare a clean local-class dataframe
# ------------------------------------------------------------

required = [
    "session_key",
    "mouse_id",
    "context",
    "wavemap_group",
    "wavemap_local",
]

missing = [c for c in required if c not in units_df.columns]

if missing:
    raise KeyError(
        "Missing required columns: "
        + ", ".join(missing)
        + "\nRun Sarah's area-specific WaveMAP clustering cells first."
    )

ctx_df = units_df[required].copy()

ctx_df["wavemap_local"] = pd.to_numeric(ctx_df["wavemap_local"], errors="coerce")

ctx_df = ctx_df[
    ctx_df["wavemap_group"].isin(GROUP_ORDER)
    & ctx_df["wavemap_local"].notna()
    & (ctx_df["wavemap_local"] > 0)
    & ctx_df["context"].isin(context_order)
].copy()

ctx_df["wavemap_local"] = ctx_df["wavemap_local"].astype(int)

ctx_df["wavemap_label"] = ctx_df["wavemap_group"] + "-" + ctx_df["wavemap_local"].astype(str)


# ------------------------------------------------------------
# 2. Compute session-normalized proportions WITHIN region
#
# For a session s, region g and local class k:
#
#        N(s,g,k)
# p =  -----------
#        N(s,g)
#
# Thus every session contributes equally to each context.
# ------------------------------------------------------------

all_session_rows = []
summary_rows = []

for group in GROUP_ORDER:
    gdf = ctx_df[ctx_df["wavemap_group"] == group].copy()

    if len(gdf) == 0:
        continue

    local_classes = sorted(gdf["wavemap_local"].unique())

    # Sessions in which this region actually contributed units
    session_meta = gdf[["session_key", "mouse_id", "context"]].drop_duplicates()

    # observed counts
    counts = (
        gdf.groupby(["session_key", "mouse_id", "context", "wavemap_local"])
        .size()
        .rename("n_units")
        .reset_index()
    )

    # Fill missing local classes with zero inside every observed
    # session × region block.
    for row in session_meta.itertuples(index=False):
        sub = (
            counts[counts["session_key"] == row.session_key]
            .set_index("wavemap_local")["n_units"]
            .reindex(local_classes, fill_value=0)
        )

        total = int(sub.sum())

        if total == 0:
            continue

        tmp = pd.DataFrame(
            {
                "group": group,
                "session_key": row.session_key,
                "mouse_id": row.mouse_id,
                "context": row.context,
                "wavemap_local": local_classes,
                "n_units": sub.to_numpy(),
                "region_total": total,
                "class_proportion": sub.to_numpy() / total,
            }
        )

        tmp["wavemap_label"] = group + "-" + tmp["wavemap_local"].astype(str)

        all_session_rows.append(tmp)


region_session_prop = pd.concat(all_session_rows, ignore_index=True)


# ------------------------------------------------------------
# 3. Mean + SEM across sessions for each context
# ------------------------------------------------------------

region_context_summary = (
    region_session_prop.groupby(["group", "context", "wavemap_local", "wavemap_label"])[
        "class_proportion"
    ]
    .agg(mean="mean", std="std", n_sessions="count")
    .reset_index()
)

region_context_summary["sem"] = region_context_summary["std"] / np.sqrt(
    region_context_summary["n_sessions"]
)

region_context_summary["mean_percent"] = region_context_summary["mean"] * 100

region_context_summary["sem_percent"] = region_context_summary["sem"] * 100


# ------------------------------------------------------------
# 4. Build matrices for plotting
# ------------------------------------------------------------

matrices = {}

for group in GROUP_ORDER:
    sub = region_context_summary[region_context_summary["group"] == group].copy()

    if len(sub) == 0:
        continue

    local_order = sorted(sub["wavemap_local"].unique())

    matrix = sub.pivot(index="wavemap_local", columns="context", values="mean_percent").reindex(
        index=local_order, columns=context_order
    )

    matrix.index = [f"{group}-{int(x)}" for x in matrix.index]

    matrices[group] = matrix


# ------------------------------------------------------------
# 5. One GLOBAL colour scale
#
# Important for visual comparison between anatomical groups.
# Use a robust upper bound so a single dominant class doesn't
# flatten all remaining structure.
# ------------------------------------------------------------

all_vals = np.concatenate([m.to_numpy().ravel() for m in matrices.values()])

all_vals = all_vals[np.isfinite(all_vals)]

vmin = 0

# Robust high limit, while never clipping below the actual
# majority of values.
vmax = float(np.nanpercentile(all_vals, 97.5))

# Round to a clean number
vmax = max(5, np.ceil(vmax / 5) * 5)

print(f"Shared heatmap scale: {vmin:.0f}–{vmax:.0f}%")


# ------------------------------------------------------------
# 6. Plot six compact heatmaps
# ------------------------------------------------------------

fig, axes = plt.subplots(
    2, 3, figsize=(11.8, 7.6), dpi=160, facecolor="white", constrained_layout=False
)

axes = axes.ravel()

image_for_cbar = None

for ax, group in zip(axes, GROUP_ORDER, strict=False):
    matrix = matrices.get(group)

    if matrix is None:
        ax.axis("off")
        continue

    im = ax.imshow(
        matrix.to_numpy(), cmap=CMAP, vmin=vmin, vmax=vmax, aspect="auto", interpolation="nearest"
    )

    image_for_cbar = im

    # --------------------------------------------------------
    # X labels
    # --------------------------------------------------------

    ax.set_xticks(np.arange(len(context_order)))

    ax.set_xticklabels(
        [CONTEXT_SHORT.get(c, c) for c in context_order],
        rotation=30,
        ha="right",
        rotation_mode="anchor",
    )

    # --------------------------------------------------------
    # Y labels = LOCAL class labels
    # --------------------------------------------------------

    ax.set_yticks(np.arange(len(matrix.index)))

    ax.set_yticklabels(matrix.index)

    # --------------------------------------------------------
    # Region title
    # --------------------------------------------------------

    n_units = int((ctx_df["wavemap_group"] == group).sum())

    n_sessions = int(ctx_df.loc[ctx_df["wavemap_group"] == group, "session_key"].nunique())

    ax.set_title(GROUP_NAMES[group], loc="left", fontsize=10.5, fontweight="bold", pad=8)

    ax.text(
        1.0,
        1.025,
        f"n={n_units:,} units · {n_sessions} sessions",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=7.5,
        color=TEXT_GREY,
    )

    # --------------------------------------------------------
    # Subtle white cell boundaries
    # --------------------------------------------------------

    ax.set_xticks(np.arange(-0.5, matrix.shape[1], 1), minor=True)

    ax.set_yticks(np.arange(-0.5, matrix.shape[0], 1), minor=True)

    ax.grid(which="minor", color="white", linewidth=1.0)

    ax.tick_params(which="minor", bottom=False, left=False)

    ax.tick_params(axis="both", length=0)

    # --------------------------------------------------------
    # Annotate only sufficiently large cells
    #
    # Avoids turning the figure into a table.
    # --------------------------------------------------------

    arr = matrix.to_numpy()

    for r in range(arr.shape[0]):
        for c in range(arr.shape[1]):
            val = arr[r, c]

            if not np.isfinite(val):
                continue

            # annotate only biologically substantial proportions
            if val >= max(5, 0.18 * vmax):
                # choose text contrast based on heatmap intensity
                txt_col = "white" if val > 0.55 * vmax else "black"

                ax.text(
                    c,
                    r,
                    f"{val:.0f}",
                    ha="center",
                    va="center",
                    fontsize=7,
                    fontweight="bold",
                    color=txt_col,
                )

    # clean spines
    for spine in ax.spines.values():
        spine.set_visible(False)


# ------------------------------------------------------------
# 7. Shared colour bar
# ------------------------------------------------------------

fig.subplots_adjust(left=0.08, right=0.91, top=0.87, bottom=0.10, wspace=0.33, hspace=0.48)

cbar_ax = fig.add_axes([0.93, 0.18, 0.015, 0.60])

cbar = fig.colorbar(image_for_cbar, cax=cbar_ax)

cbar.set_label("Mean within-session class proportion (%)", fontsize=8.5)

cbar.outline.set_visible(False)

cbar.ax.tick_params(labelsize=8, length=2)


# ------------------------------------------------------------
# 8. Figure title
# ------------------------------------------------------------

fig.text(
    0.08,
    0.965,
    "Waveform-class composition is compared across predictive contexts within anatomical region",
    ha="left",
    va="top",
    fontsize=14.5,
    fontweight="bold",
)

fig.text(
    0.08,
    0.935,
    (
        "Each heatmap shows local WaveMAP classes discovered independently "
        "within that region. Values are normalized within each recording "
        "session before averaging across sessions."
    ),
    ha="left",
    va="top",
    fontsize=8.8,
    color=TEXT_GREY,
)


# ------------------------------------------------------------
# 9. Save data + figure
# ------------------------------------------------------------

OUT_DIR = Path(OUT_DIR)

region_session_prop.to_csv(
    OUT_DIR / "FIG_context_within_region_session_proportions.csv", index=False
)

region_context_summary.to_csv(OUT_DIR / "FIG_context_within_region_summary.csv", index=False)

fig.savefig(
    OUT_DIR / "FIG_context_within_region_heatmaps.png",
    dpi=300,
    bbox_inches="tight",
    facecolor="white",
)

fig.savefig(
    OUT_DIR / "FIG_context_within_region_heatmaps.pdf", bbox_inches="tight", facecolor="white"
)

plt.close(fig)

# ============================================================
# PUTATIVE FS/PV-LIKE + OPTO-TAGGED SST IN WAVEMAP SPACE
#
# There is NO PV optotagging in this dataset.
#
# Putative FS/PV-like:
#   trough-to-peak waveform duration < 0.40 ms
#   AND firing rate >= 10 Hz
#
# Optotagged SST:
#   SST-Ai32 light-activated units from the classifier above.
#
# FIGURE:
#   Row 1 = all putative FS/PV-like cells        BLUE
#   Row 2 = all optotagged SST cells            MAGENTA
#   Row 3 = SST cells also meeting FS criterion ORANGE
#
# Rows 1 and 2 intentionally include overlap cells.
# Row 3 isolates the intersection.
# ============================================================


FS_T2P_MAX_MS = 0.40
FS_FR_MIN_HZ = 10.0

PV_COLOR = "#377EB8"  # blue
SST_COLOR = "#CC2F8A"  # magenta
OVERLAP_COLOR = "#F28E2B"  # orange
BACKGROUND_COLOR = "0.82"

BACKGROUND_ALPHA = 0.20
PV_ALPHA = 0.68
SST_ALPHA = 0.68
OVERLAP_ALPHA = 0.82

BACKGROUND_SIZE = 3.2
PV_SIZE = 27
SST_SIZE = 29
OVERLAP_SIZE = 34

GROUP_ORDER = [g for g in ["MO", "PFC", "VIS", "STR", "HPC", "THAL"] if g in group_embeddings]

GROUP_NAMES = {
    "MO": "Motor cortex",
    "PFC": "Prefrontal cortex",
    "VIS": "Visual cortex",
    "STR": "Striatum",
    "HPC": "Hippocampus",
    "THAL": "Thalamus",
}

# ============================================================
# 1. CHECK INPUTS
# ============================================================

if "units_df" not in globals():
    raise RuntimeError("units_df is not in memory.")
if "group_embeddings" not in globals():
    raise RuntimeError("group_embeddings is not in memory.")
if "sst_opto_df" not in globals():
    raise RuntimeError("sst_opto_df is not in memory. Run the SST optotagging cell first.")
if "unit_uid" not in sst_opto_df.columns:
    raise RuntimeError("sst_opto_df does not contain unit_uid.")
if "is_sst_optotagged" not in sst_opto_df.columns:
    raise RuntimeError("sst_opto_df does not contain is_sst_optotagged.")

# ============================================================
# 2. MASTER DATAFRAME + PUTATIVE FS CLASSIFICATION
# ============================================================

map_df = units_df.copy()

map_df["t2p_ms"] = pd.to_numeric(map_df["waveform_duration"], errors="coerce") * 1000.0
map_df["firing_rate_hz"] = pd.to_numeric(map_df["firing_rate"], errors="coerce")

map_df["putative_fs"] = map_df["t2p_ms"].lt(FS_T2P_MAX_MS) & map_df["firing_rate_hz"].ge(
    FS_FR_MIN_HZ
)

# ============================================================
# 3. ATTACH SST OPTO-TAGGING
# ============================================================

sst_lookup = sst_opto_df.drop_duplicates("unit_uid").set_index("unit_uid")

map_df["sst_opto_available"] = map_df["unit_uid"].isin(sst_lookup.index)
map_df["sst_optotagged"] = False

m = map_df["sst_opto_available"]

map_df.loc[m, "sst_optotagged"] = (
    map_df.loc[m, "unit_uid"].map(sst_lookup["is_sst_optotagged"]).fillna(False).astype(bool)
)

for c in [
    "early_rate_hz",
    "early_baseline_rate_hz",
    "early_q",
    "early_response_probability",
    "early_baseline_probability",
    "full_rate_hz",
    "full_baseline_rate_hz",
    "full_q",
    "median_first_spike_latency_ms",
    "raised_full_rate_hz",
    "hz5_full_rate_hz",
    "hz40_full_rate_hz",
]:
    if c in sst_lookup.columns:
        map_df[f"sst_{c}"] = map_df["unit_uid"].map(sst_lookup[c])

# ============================================================
# 4. OVERLAP / EXCLUSIVE GROUPS
# ============================================================

map_df["sst_fs_overlap"] = map_df["sst_optotagged"] & map_df["putative_fs"]

# Retained for the waveform-comparison cell below.
map_df["putative_fs_only"] = map_df["putative_fs"] & ~map_df["sst_optotagged"]
map_df["sst_only"] = map_df["sst_optotagged"] & ~map_df["putative_fs"]

# ============================================================
# 5. OVERALL SUMMARY
# ============================================================

n_total = len(map_df)
n_fs = int(map_df["putative_fs"].sum())
n_sst = int(map_df["sst_optotagged"].sum())
n_overlap = int(map_df["sst_fs_overlap"].sum())

print("\n" + "=" * 90)
print("PUTATIVE FS/PV-LIKE + OPTO-TAGGED SST")
print("=" * 90)
print(f"Total units: {n_total:,}")
print(
    f"Putative FS/PV-like "
    f"(t2p < {FS_T2P_MAX_MS:.2f} ms, FR >= {FS_FR_MIN_HZ:.1f} Hz): "
    f"{n_fs:,} ({100 * n_fs / n_total:.2f}%)"
)
print(f"Optotagged SST: {n_sst:,} ({100 * n_sst / n_total:.2f}%)")
if n_sst:
    print(f"SST ∩ FS: {n_overlap:,}/{n_sst:,} optotagged SST ({100 * n_overlap / n_sst:.2f}%)")

# ============================================================
# 6. REGIONAL SUMMARY
# ============================================================

summary_rows = []

for group in GROUP_ORDER:
    sub = map_df.loc[map_df["wavemap_group"].eq(group)]

    n_area = len(sub)
    n_fs_area = int(sub["putative_fs"].sum())
    n_sst_area = int(sub["sst_optotagged"].sum())
    n_overlap_area = int(sub["sst_fs_overlap"].sum())

    summary_rows.append(
        {
            "wavemap_group": group,
            "region": GROUP_NAMES.get(group, group),
            "n_units": n_area,
            "n_putative_fs": n_fs_area,
            "putative_fs_percent_all": (100 * n_fs_area / n_area if n_area else np.nan),
            "n_optotagged_sst": n_sst_area,
            "sst_percent_all": (100 * n_sst_area / n_area if n_area else np.nan),
            "n_sst_meeting_fs_criterion": n_overlap_area,
            "percent_sst_meeting_fs_criterion": (
                100 * n_overlap_area / n_sst_area if n_sst_area else np.nan
            ),
        }
    )

regional_summary = pd.DataFrame(summary_rows)

print("\nRegional summary:")
display(regional_summary.round(2))

# ============================================================
# 7. 3-ROW UMAP FIGURE
# ============================================================

ROW_INFO = [
    {
        "label": "Putative FS/PV-like",
        "mask_col": "putative_fs",
        "color": PV_COLOR,
        "alpha": PV_ALPHA,
        "size": PV_SIZE,
    },
    {
        "label": "Optotagged SST",
        "mask_col": "sst_optotagged",
        "color": SST_COLOR,
        "alpha": SST_ALPHA,
        "size": SST_SIZE,
    },
    {
        "label": "Overlap",
        "mask_col": "sst_fs_overlap",
        "color": OVERLAP_COLOR,
        "alpha": OVERLAP_ALPHA,
        "size": OVERLAP_SIZE,
    },
]

n_groups = len(GROUP_ORDER)

fig, axes = plt.subplots(
    3,
    n_groups,
    figsize=(3.25 * n_groups, 9.0),
    dpi=170,
    squeeze=False,
)

for row_i, row_info in enumerate(ROW_INFO):
    for col_i, group in enumerate(GROUP_ORDER):
        ax = axes[row_i, col_i]

        idx, emb = group_embeddings[group]
        idx = np.asarray(idx)
        emb = np.asarray(emb)
        sub = map_df.iloc[idx]

        assert len(sub) == len(emb), f"{group}: UMAP rows != dataframe rows"

        # All WaveMAP units in translucent grey.
        ax.scatter(
            emb[:, 0],
            emb[:, 1],
            s=BACKGROUND_SIZE,
            color=BACKGROUND_COLOR,
            alpha=BACKGROUND_ALPHA,
            linewidths=0,
            rasterized=True,
            zorder=1,
        )

        mask = sub[row_info["mask_col"]].to_numpy(dtype=bool)

        if mask.any():
            ax.scatter(
                emb[mask, 0],
                emb[mask, 1],
                s=row_info["size"],
                color=row_info["color"],
                alpha=row_info["alpha"],
                edgecolors="white",
                linewidths=0.55,
                rasterized=True,
                zorder=5,
            )

        n_area = len(sub)
        n_pop = int(mask.sum())

        # The biologically relevant denominator for overlap is SST.
        if row_info["mask_col"] == "sst_fs_overlap":
            n_sst_area = int(sub["sst_optotagged"].sum())
            pct = 100 * n_pop / n_sst_area if n_sst_area else np.nan
            txt = f"{n_pop}/{n_sst_area} SST\n({pct:.1f}%)" if n_sst_area else "no SST"
        else:
            pct = 100 * n_pop / n_area if n_area else np.nan
            txt = f"{n_pop}/{n_area}\n({pct:.1f}%)"

        if row_i == 0:
            ax.set_title(
                GROUP_NAMES.get(group, group),
                fontsize=10.5,
                fontweight="bold",
            )

        if col_i == 0:
            ax.set_ylabel(
                row_info["label"],
                fontsize=10,
                fontweight="bold",
                labelpad=10,
            )

        ax.text(
            0.02,
            0.02,
            txt,
            transform=ax.transAxes,
            fontsize=7.4,
            color="0.30",
            ha="left",
            va="bottom",
        )

        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)

fig.suptitle(
    "Putative FS/PV-like and optotagged SST populations in area-specific WaveMAP space",
    fontsize=14,
    fontweight="bold",
    y=0.995,
)

legend_handles = [
    Line2D(
        [0],
        [0],
        marker="o",
        linestyle="",
        markerfacecolor=BACKGROUND_COLOR,
        markeredgecolor="none",
        markersize=5,
        label="Other WaveMAP units",
    ),
    Line2D(
        [0],
        [0],
        marker="o",
        linestyle="",
        markerfacecolor=PV_COLOR,
        markeredgecolor="white",
        markersize=7,
        alpha=PV_ALPHA,
        label="Putative FS/PV-like (t2p < 0.40 ms, FR ≥ 10 Hz)",
    ),
    Line2D(
        [0],
        [0],
        marker="o",
        linestyle="",
        markerfacecolor=SST_COLOR,
        markeredgecolor="white",
        markersize=7,
        alpha=SST_ALPHA,
        label="Optotagged SST",
    ),
    Line2D(
        [0],
        [0],
        marker="o",
        linestyle="",
        markerfacecolor=OVERLAP_COLOR,
        markeredgecolor="white",
        markersize=8,
        alpha=OVERLAP_ALPHA,
        label="Optotagged SST ∩ putative FS",
    ),
]

fig.legend(
    handles=legend_handles,
    loc="upper center",
    bbox_to_anchor=(0.5, 0.965),
    ncol=4,
    frameon=False,
    fontsize=8.3,
)

fig.tight_layout(
    rect=[0, 0, 1, 0.92],
    h_pad=1.1,
    w_pad=0.7,
)

fig_png = Path(OUT_DIR) / "FIG_FS_SST_overlap_WaveMAP_3rows.png"
fig_pdf = Path(OUT_DIR) / "FIG_FS_SST_overlap_WaveMAP_3rows.pdf"

fig.savefig(fig_png, dpi=400, bbox_inches="tight")
fig.savefig(fig_pdf, bbox_inches="tight")
plt.close(fig)

# ============================================================
# 8. SAVE
# ============================================================

regional_csv = Path(OUT_DIR) / "FS_SST_WaveMAP_regional_summary.csv"
merged_pkl = Path(OUT_DIR) / "FS_SST_WaveMAP_merged.pkl"

regional_summary.to_csv(regional_csv, index=False)
map_df.to_pickle(merged_pkl)

print("\nSaved:")
print(fig_png)
print(fig_pdf)
print(regional_csv)
print(merged_pkl)


# ============================================================
# FINAL INTERACTIVE FIGURE 1
# Area-specific WaveMAP explorer
#
# FINAL PUBLICATION VERSION
#
# - No overlapping Plotly legend
# - Area selector outside plotting region
# - Click any UMAP unit -> exact individual waveform
# - Selected cluster mean is the dominant class-coloured trace
# - Selected unit uses the same class colour with translucency
# - Selected class +/- SD shown as translucent class-coloured shading
# - Other waveform communities are de-emphasized in gray
# - Compact waveform legend appears below the waveform after selection
# - Clicked UMAP point marked with black ring
# - Unit metadata shown below
# - Class summary table shown below plots
#
# PRESENTATION ONLY:
# Does not rerun WaveMAP / UMAP / Louvain / QC.
# ============================================================


# ============================================================
# 1. OUTPUT
# ============================================================

INTERACTIVE_DIR = Path(OUT_DIR) / "interactive"
INTERACTIVE_DIR.mkdir(parents=True, exist_ok=True)

FIG1_HTML = INTERACTIVE_DIR / "wavemap-area-explorer.html"

# Remove stale output before regeneration so a failed run cannot leave
# an apparently current HTML from a previous analysis.
if FIG1_HTML.exists():
    FIG1_HTML.unlink()


# ============================================================
# 2. AREA SETTINGS
# ============================================================

GROUP_ORDER = [g for g in ["MO", "PFC", "VIS", "STR", "HPC", "THAL"] if g in group_embeddings]

GROUP_NAMES = {
    "MO": "Motor cortex",
    "PFC": "Prefrontal cortex",
    "VIS": "Visual cortex",
    "STR": "Striatum",
    "HPC": "Hippocampus",
    "THAL": "Thalamus",
}

if not GROUP_ORDER:
    raise RuntimeError("No WaveMAP anatomical groups found.")


# ============================================================
# 3. CHECK REQUIRED OBJECTS
# ============================================================

for obj_name in [
    "units_df",
    "normWFs",
    "group_embeddings",
    "CLASS_COLORS",
]:
    if obj_name not in globals():
        raise RuntimeError(f"Missing required object: {obj_name}")


if len(units_df) != len(normWFs):
    raise RuntimeError("units_df and normWFs are not row-aligned.")


# ============================================================
# 4. COLOUR HELPERS
# ============================================================


def css_rgb(colour):

    r, g, b = mcolors.to_rgb(colour)

    return f"rgb({round(r * 255)},{round(g * 255)},{round(b * 255)})"


def css_rgba(colour, alpha):

    r, g, b = mcolors.to_rgb(colour)

    return f"rgba({round(r * 255)},{round(g * 255)},{round(b * 255)},{alpha})"


# ============================================================
# 5. DISPLAY DATA
# ============================================================

idf = units_df.copy()


# ------------------------------------------------------------
# Cortical layer labels for Figure-8-style class profiles
# ------------------------------------------------------------

_LAYER_ORDER_HTML = ["1", "2/3", "4", "5", "6a", "6b"]


def _html_extract_layer(area):

    if pd.isna(area):
        return np.nan

    match = re.search(
        r"(2/3|6a|6b|1|4|5)$",
        str(area).strip(),
    )

    return match.group(1) if match else np.nan


if "cortical_layer" not in idf.columns:
    idf["cortical_layer"] = idf["area"].map(_html_extract_layer)


# ------------------------------------------------------------
# Waveform duration
# ------------------------------------------------------------

if "waveform_duration" in idf.columns:
    idf["_t2p_ms"] = pd.to_numeric(idf["waveform_duration"], errors="coerce") * 1000

else:
    idf["_t2p_ms"] = np.nan


# ------------------------------------------------------------
# Firing rate
# ------------------------------------------------------------

if "firing_rate" in idf.columns:
    idf["_fr"] = pd.to_numeric(idf["firing_rate"], errors="coerce")

else:
    idf["_fr"] = np.nan


# ------------------------------------------------------------
# SNR
# ------------------------------------------------------------

if "snr" in idf.columns:
    idf["_snr"] = pd.to_numeric(idf["snr"], errors="coerce")

else:
    idf["_snr"] = np.nan


# ============================================================
# 6. FS + PUTATIVE PV-LIKE
# ============================================================

idf["_fs"] = False
idf["_pv"] = False


# Existing classifications in units_df
for col in [
    "putative_fs",
    "is_fs",
    "FS",
]:
    if col in idf.columns:
        idf["_fs"] = idf[col].fillna(False).astype(bool)

        break


for col in [
    "putative_pv_like",
    "pv_like",
    "is_pv_like",
]:
    if col in idf.columns:
        idf["_pv"] = idf[col].fillna(False).astype(bool)

        break


# Prefer map_df when row-aligned
if "map_df" in globals() and isinstance(map_df, pd.DataFrame) and len(map_df) == len(idf):
    for col in [
        "putative_fs",
        "is_fs",
        "FS",
    ]:
        if col in map_df.columns:
            idf["_fs"] = map_df[col].fillna(False).astype(bool).to_numpy()

            break

    for col in [
        "putative_pv_like",
        "pv_like",
        "is_pv_like",
    ]:
        if col in map_df.columns:
            idf["_pv"] = map_df[col].fillna(False).astype(bool).to_numpy()

            break


# ============================================================
# 7. SST STATUS
# ============================================================

idf["_sst"] = "Not tested"

tested_sst = set()
positive_sst = set()


for name in [
    "sst_opto_df",
    "sst_results_df",
    "sst_df",
]:
    if name not in globals():
        continue

    df = globals()[name]

    if not isinstance(df, pd.DataFrame):
        continue

    if "unit_uid" not in df.columns:
        continue

    tested_sst.update(df["unit_uid"].dropna().astype(str).tolist())

    for col in [
        "is_sst",
        "sst_optotagged",
        "is_sst_final",
        "sst_positive",
    ]:
        if col in df.columns:
            mask = df[col].fillna(False).astype(bool)

            positive_sst.update(df.loc[mask, "unit_uid"].dropna().astype(str).tolist())

            break


if "unit_uid" in idf.columns:
    uids = idf["unit_uid"].astype(str)

    idf.loc[uids.isin(tested_sst), "_sst"] = "Tested — SST−"

    idf.loc[uids.isin(positive_sst), "_sst"] = "Optotagged SST+"


# ============================================================
# 8. WAVEFORM X AXIS
# ============================================================

waveform_fs = None


for name in [
    "WF_SAMPLING_RATE",
    "WAVEFORM_SAMPLING_RATE",
    "waveform_sampling_rate",
]:
    if name in globals():
        try:
            candidate = float(globals()[name])

            if np.isfinite(candidate) and candidate > 0:
                waveform_fs = candidate
                break

        except Exception:
            pass


if waveform_fs is not None:
    waveform_x = np.arange(normWFs.shape[1]) / waveform_fs * 1000

    waveform_x_label = "Time (ms)"

else:
    waveform_x = np.arange(normWFs.shape[1])

    waveform_x_label = "Waveform sample"


# ============================================================
# 9. CLASS SUMMARIES
# ============================================================

summaries = {}


for group in GROUP_ORDER:
    idx, emb = group_embeddings[group]

    idx = np.asarray(idx, dtype=int)

    emb = np.asarray(emb, dtype=float)

    sub = idf.iloc[idx]

    local = pd.to_numeric(sub["wavemap_local"], errors="coerce")

    classes = sorted(local[local > 0].dropna().astype(int).unique())

    summaries[group] = {}

    for cls in classes:
        mask = local.to_numpy() == cls

        rows = idx[mask]

        global_classes = (
            pd.to_numeric(idf.iloc[rows]["wavemap_class"], errors="coerce")
            .dropna()
            .astype(int)
            .unique()
        )

        if len(global_classes) != 1:
            raise RuntimeError(f"{group}-{cls}: could not identify unique plotting class.")

        global_cls = int(global_classes[0])

        W = np.asarray(normWFs[rows], dtype=float)

        class_rows = idf.iloc[rows]

        summaries[group][cls] = {
            "global_class": global_cls,
            "rows": rows,
            "n": len(rows),
            "mean": np.nanmean(W, axis=0),
            "sd": np.nanstd(W, axis=0),
            "fr": class_rows["_fr"].median(),
            "t2p": class_rows["_t2p_ms"].median(),
            "snr": class_rows["_snr"].median(),
            "fs_pct": (100 * class_rows["_fs"].mean()),
            "pv_pct": (100 * class_rows["_pv"].mean()),
            "layer_available": bool(
                group in ["MO", "PFC", "VIS"]
                and class_rows["cortical_layer"].isin(_LAYER_ORDER_HTML).any()
            ),
            "layer_n": int(class_rows["cortical_layer"].isin(_LAYER_ORDER_HTML).sum()),
            "layer_percent": (
                (
                    100
                    * class_rows.loc[
                        class_rows["cortical_layer"].isin(_LAYER_ORDER_HTML),
                        "cortical_layer",
                    ]
                    .value_counts()
                    .reindex(
                        _LAYER_ORDER_HTML,
                        fill_value=0,
                    )
                    / max(
                        1,
                        class_rows["cortical_layer"].isin(_LAYER_ORDER_HTML).sum(),
                    )
                )
                .to_numpy(dtype=float)
                .round(3)
                .tolist()
            ),
            "background_layer_percent": (
                (
                    100
                    * sub.loc[
                        sub["cortical_layer"].isin(_LAYER_ORDER_HTML),
                        "cortical_layer",
                    ]
                    .value_counts()
                    .reindex(
                        _LAYER_ORDER_HTML,
                        fill_value=0,
                    )
                    / max(
                        1,
                        sub["cortical_layer"].isin(_LAYER_ORDER_HTML).sum(),
                    )
                )
                .to_numpy(dtype=float)
                .round(3)
                .tolist()
            ),
        }


# ============================================================
# 10. CREATE BASE PLOTLY FIGURES
# ============================================================

figures = {}


for group in GROUP_ORDER:
    idx, emb = group_embeddings[group]

    idx = np.asarray(idx, dtype=int)

    emb = np.asarray(emb, dtype=float)

    sub = idf.iloc[idx].copy()

    local = pd.to_numeric(sub["wavemap_local"], errors="coerce")

    classes = sorted(local[local > 0].dropna().astype(int).unique())

    # ========================================================
    # FIGURE
    # ========================================================

    fig = make_subplots(
        rows=2,
        cols=2,
        specs=[
            [
                {"type": "scatter"},
                {"type": "scatter"},
            ],
            [
                {"type": "table", "colspan": 2},
                None,
            ],
        ],
        column_widths=[0.53, 0.47],
        row_heights=[0.69, 0.31],
        horizontal_spacing=0.11,
        vertical_spacing=0.18,
        subplot_titles=[
            (
                "<b>WaveMAP embedding</b>"
                " "
                "<span style='"
                "font-size:10px;"
                "color:#777777"
                "'>"
                "· colour = local class"
                "</span>"
            ),
            "<b>Waveforms</b>",
            "",
        ],
    )

    # ========================================================
    # A. UMAP
    # ========================================================

    for cls in classes:
        mask = local.to_numpy() == cls

        summary = summaries[group][cls]

        global_cls = summary["global_class"]

        colour = css_rgb(CLASS_COLORS[global_cls])

        custom = []

        for row_index in idx[mask]:
            row = idf.iloc[row_index]

            uid = str(row.get("unit_uid", row_index))

            area = str(row.get("area", "—"))

            fr = row["_fr"]
            t2p = row["_t2p_ms"]
            snr = row["_snr"]

            custom.append(
                [
                    int(row_index),
                    uid,
                    area,
                    (f"{fr:.2f}" if np.isfinite(fr) else "—"),
                    (f"{t2p:.3f}" if np.isfinite(t2p) else "—"),
                    (f"{snr:.2f}" if np.isfinite(snr) else "—"),
                    ("Yes" if bool(row["_fs"]) else "No"),
                    ("Yes" if bool(row["_pv"]) else "No"),
                    str(row["_sst"]),
                    f"{group}-{cls}",
                ]
            )

        fig.add_trace(
            go.Scattergl(
                x=emb[mask, 0],
                y=emb[mask, 1],
                mode="markers",
                name=(f"{group}-{cls}"),
                marker=dict(
                    size=5,
                    color=colour,
                    opacity=0.72,
                    line=dict(width=0),
                ),
                customdata=np.asarray(custom, dtype=object),
                hovertemplate=(
                    "<b>%{customdata[9]}</b>"
                    "<br>"
                    "Unit: "
                    "%{customdata[1]}"
                    "<br>"
                    "CCF area: "
                    "%{customdata[2]}"
                    "<br>"
                    "Firing rate: "
                    "%{customdata[3]} Hz"
                    "<br>"
                    "Trough-to-peak: "
                    "%{customdata[4]} ms"
                    "<br>"
                    "SNR: "
                    "%{customdata[5]}"
                    "<br>"
                    "FS: "
                    "%{customdata[6]}"
                    "<br>"
                    "Putative PV-like: "
                    "%{customdata[7]}"
                    "<br>"
                    "SST: "
                    "%{customdata[8]}"
                    "<extra></extra>"
                ),
                showlegend=False,
            ),
            row=1,
            col=1,
        )

    # ========================================================
    # B. CLASS WAVEFORMS
    # ========================================================

    for cls in classes:
        summary = summaries[group][cls]

        global_cls = summary["global_class"]

        colour = css_rgb(CLASS_COLORS[global_cls])

        fill = css_rgba(CLASS_COLORS[global_cls], 0.08)

        mean = summary["mean"]

        sd = summary["sd"]

        # ----------------------------------------------------
        # Upper SD
        # ----------------------------------------------------

        fig.add_trace(
            go.Scatter(
                x=waveform_x,
                y=mean + sd,
                mode="lines",
                line=dict(width=0),
                showlegend=False,
                hoverinfo="skip",
            ),
            row=1,
            col=2,
        )

        # ----------------------------------------------------
        # Lower SD + fill
        # ----------------------------------------------------

        fig.add_trace(
            go.Scatter(
                x=waveform_x,
                y=mean - sd,
                mode="lines",
                line=dict(width=0),
                fill="tonexty",
                fillcolor=fill,
                showlegend=False,
                hoverinfo="skip",
            ),
            row=1,
            col=2,
        )

        # ----------------------------------------------------
        # Mean waveform
        # ----------------------------------------------------

        fig.add_trace(
            go.Scatter(
                x=waveform_x,
                y=mean,
                mode="lines",
                line=dict(
                    color=colour,
                    width=2,
                ),
                showlegend=False,
                hovertemplate=(
                    f"<b>{group}-{cls}</b><br>Normalized amplitude: %{{y:.3f}}<extra></extra>"
                ),
            ),
            row=1,
            col=2,
        )

    # ========================================================
    # C. CLASS SUMMARY TABLE
    # ========================================================

    table_class = []
    table_n = []
    table_fr = []
    table_t2p = []
    table_snr = []
    table_fs = []
    table_pv = []

    for cls in classes:
        s = summaries[group][cls]

        table_class.append(f"{group}-{cls}")

        table_n.append(f"{s['n']:,}")

        table_fr.append(f"{s['fr']:.1f}" if np.isfinite(s["fr"]) else "—")

        table_t2p.append(f"{s['t2p']:.3f}" if np.isfinite(s["t2p"]) else "—")

        table_snr.append(f"{s['snr']:.2f}" if np.isfinite(s["snr"]) else "—")

        table_fs.append(f"{s['fs_pct']:.1f}%")

        table_pv.append(f"{s['pv_pct']:.1f}%")

    fig.add_trace(
        go.Table(
            columnwidth=[
                1.0,
                0.65,
                1.15,
                1.25,
                1.0,
                0.75,
                1.25,
            ],
            header=dict(
                values=[
                    "<b>Local class</b>",
                    "<b>n</b>",
                    "<b>Median FR (Hz)</b>",
                    "<b>Median T→P (ms)</b>",
                    "<b>Median SNR</b>",
                    "<b>FS</b>",
                    "<b>Putative PV-like</b>",
                ],
                align="center",
                fill_color="#F4F4F4",
                line=dict(color="#FFFFFF", width=1),
                font=dict(size=10, color="#333333"),
                height=28,
            ),
            cells=dict(
                values=[
                    table_class,
                    table_n,
                    table_fr,
                    table_t2p,
                    table_snr,
                    table_fs,
                    table_pv,
                ],
                align="center",
                fill_color="#FFFFFF",
                line=dict(color="#E6E6E6", width=1),
                font=dict(size=10, color="#444444"),
                height=25,
            ),
        ),
        row=2,
        col=1,
    )

    # ========================================================
    # D. AXES
    # ========================================================

    fig.update_xaxes(
        title_text="UMAP 1",
        showgrid=False,
        zeroline=False,
        showticklabels=False,
        ticks="",
        row=1,
        col=1,
    )

    fig.update_yaxes(
        title_text="UMAP 2",
        showgrid=False,
        zeroline=False,
        showticklabels=False,
        ticks="",
        row=1,
        col=1,
    )

    fig.update_xaxes(
        title_text=waveform_x_label,
        # Keep the axis title close to the axis so the legend can
        # occupy a separate line below it without overlap.
        title_standoff=3,
        showgrid=False,
        zeroline=False,
        ticks="outside",
        tickfont=dict(size=10),
        row=1,
        col=2,
    )

    fig.update_yaxes(
        title_text="Normalized amplitude",
        showgrid=False,
        zeroline=True,
        zerolinecolor="#DDDDDD",
        zerolinewidth=1,
        ticks="outside",
        tickfont=dict(size=10),
        row=1,
        col=2,
    )

    # ========================================================
    # E. FINAL CLEAN LAYOUT
    # ========================================================

    fig.update_layout(
        template="plotly_white",
        autosize=True,
        height=790,
        # ----------------------------------------------------
        # Area heading
        # ----------------------------------------------------
        title=dict(
            text=(
                f"<b>"
                f"{GROUP_NAMES[group]}"
                f"</b>"
                "<br>"
                "<sup>"
                f"{len(idx):,} QC-passing units"
                " · "
                f"{len(classes)} local WaveMAP classes"
                "</sup>"
            ),
            x=0.01,
            xanchor="left",
            y=0.985,
            yanchor="top",
            font=dict(size=18, color="#222222"),
        ),
        # ----------------------------------------------------
        # Balanced margins
        # No legend space is required anymore.
        # ----------------------------------------------------
        margin=dict(
            l=72,
            r=45,
            t=88,
            b=30,
        ),
        # ----------------------------------------------------
        # IMPORTANT:
        # Completely remove Plotly legend.
        #
        # Class identity is available from:
        # - point colour
        # - hover
        # - click
        # - summary table
        #
        # This avoids redundant clutter and overlap.
        # ----------------------------------------------------
        showlegend=False,
        hoverlabel=dict(
            bgcolor="white",
            bordercolor="#BBBBBB",
            font_size=11,
            font_family=("Arial, Helvetica, sans-serif"),
        ),
        clickmode="event+select",
        paper_bgcolor="white",
        plot_bgcolor="white",
        font=dict(
            family=("Arial, Helvetica, sans-serif"),
            color="#222222",
        ),
    )

    figures[group] = fig


# ============================================================
# 11. SERIALIZE BASE FIGURES
# ============================================================

figure_json = {group: json.loads(pio.to_json(fig, pretty=False)) for group, fig in figures.items()}


# ============================================================
# 12. INDIVIDUAL UNIT PAYLOAD
# ============================================================

unit_payload = {}


for group in GROUP_ORDER:
    idx, _ = group_embeddings[group]

    idx = np.asarray(idx, dtype=int)

    for row_index in idx:
        row = idf.iloc[row_index]

        cls = pd.to_numeric(pd.Series([row.get("wavemap_local", np.nan)]), errors="coerce").iloc[0]

        if pd.isna(cls) or cls <= 0:
            continue

        cls = int(cls)

        fr = row["_fr"]
        t2p = row["_t2p_ms"]
        snr = row["_snr"]

        unit_payload[str(row_index)] = {
            "row": int(row_index),
            "uid": str(row.get("unit_uid", row_index)),
            "group": group,
            "class": f"{group}-{cls}",
            "local_class": cls,
            "area": str(row.get("area", "—")),
            "fr": (float(fr) if np.isfinite(fr) else None),
            "t2p": (float(t2p) if np.isfinite(t2p) else None),
            "snr": (float(snr) if np.isfinite(snr) else None),
            "fs": bool(row["_fs"]),
            "pv": bool(row["_pv"]),
            "sst": str(row["_sst"]),
            "waveform": (np.asarray(normWFs[row_index], dtype=float).round(6).tolist()),
        }


# ============================================================
# 13. CLASS PAYLOAD
# ============================================================

class_payload = {}


for group in GROUP_ORDER:
    class_payload[group] = {}

    for cls, s in summaries[group].items():
        global_cls = s["global_class"]

        class_payload[group][str(cls)] = {
            "mean": (np.asarray(s["mean"], dtype=float).round(6).tolist()),
            "sd": (np.asarray(s["sd"], dtype=float).round(6).tolist()),
            "color": css_rgb(CLASS_COLORS[global_cls]),
            "layer_available": bool(s["layer_available"]),
            "layer_n": int(s["layer_n"]),
            "layer_labels": [
                "L1",
                "L2/3",
                "L4",
                "L5",
                "L6a",
                "L6b",
            ],
            "layer_percent": s["layer_percent"],
            "background_layer_percent": s["background_layer_percent"],
        }


# ============================================================
# 14. AREA DROPDOWN
# ============================================================

area_options = "".join(
    f'<option value="{group}">{GROUP_NAMES[group]}</option>' for group in GROUP_ORDER
)


# ============================================================
# 15. HTML TEMPLATE
#
# Deliberately NOT an f-string.
# JavaScript/CSS braces are therefore safe.
# ============================================================

HTML_TEMPLATE = r"""
<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="utf-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1"
>

<title>Area-specific WaveMAP explorer</title>

<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>


<style>

* {
    box-sizing: border-box;
}


html,
body {

    margin: 0;
    padding: 0;

    width: 100%;

    background: white;

    color: #222222;

    font-family:
        Arial,
        Helvetica,
        sans-serif;
}


#wavemap-app {

    width: 100%;

    max-width: 1260px;

    margin: 0 auto;

    padding:
        24px
        30px
        28px
        30px;
}


/* ==========================================================
   HEADER
   ========================================================== */

.figure-header {

    width: 100%;

    display: grid;

    grid-template-columns:
        minmax(0, 1fr)
        240px;

    align-items: end;

    gap: 36px;

    padding-bottom: 16px;

    border-bottom:
        1px solid #EEEEEE;
}


.figure-title {

    min-width: 0;
}


.figure-title h2 {

    margin:
        0
        0
        5px
        0;

    font-size: 20px;

    line-height: 1.25;

    font-weight: 600;
}


.figure-title p {

    margin: 0;

    max-width: 720px;

    color: #666666;

    font-size: 12.5px;

    line-height: 1.5;
}


/* ==========================================================
   AREA CONTROL
   ========================================================== */

.control {

    width: 100%;
}


.control label {

    display: block;

    margin-bottom: 6px;

    color: #555555;

    font-size: 10px;

    line-height: 1;

    font-weight: 600;

    letter-spacing: 0.055em;
}


.control select {

    width: 100%;

    height: 40px;

    padding:
        0
        11px;

    background: white;

    color: #222222;

    border:
        1px solid #BDBDBD;

    border-radius: 3px;

    font-family:
        Arial,
        Helvetica,
        sans-serif;

    font-size: 13px;
}


/* ==========================================================
   MAIN FIGURE
   ========================================================== */

#main-figure {

    width: 100%;

    min-width: 0;

    min-height: 790px;
}


/* ==========================================================
   SELECTED UNIT PANEL
   ========================================================== */

#selection-panel {

    display: none;

    width: 100%;

    margin-top: 4px;

    padding-top: 16px;

    border-top:
        1px solid #DDDDDD;
}


.selection-title {

    margin:
        0
        0
        12px
        0;

    color: #333333;

    font-size: 11px;

    font-weight: 600;

    letter-spacing: 0.025em;
}


.selection-grid {

    width: 100%;

    display: grid;

    grid-template-columns:
        repeat(
            9,
            minmax(0, 1fr)
        );

    column-gap: 18px;

    row-gap: 14px;
}


.selection-item {

    min-width: 0;
}


.selection-label {

    display: block;

    margin-bottom: 4px;

    color: #777777;

    font-size: 9px;

    font-weight: 600;

    line-height: 1.2;

    letter-spacing: 0.04em;

    text-transform: uppercase;
}


.selection-value {

    display: block;

    color: #222222;

    font-size: 11.5px;

    line-height: 1.35;

    overflow-wrap: anywhere;
}


/* ==========================================================
   FOOTER
   ========================================================== */

.figure-note {

    width: 100%;

    margin-top: 16px;

    padding-top: 12px;

    border-top:
        1px solid #EEEEEE;

    color: #666666;

    font-size: 10.5px;

    line-height: 1.5;
}


/* ==========================================================
   RESPONSIVE
   ========================================================== */

@media (max-width: 950px) {

    .selection-grid {

        grid-template-columns:
            repeat(
                3,
                minmax(0, 1fr)
            );
    }
}


/* ============================================================
   FIGURE-8-STYLE CORTICAL-LAYER PROFILE
   ============================================================ */

#layer-panel {

    display:
        none;

    margin-top:
        18px;

    padding:
        18px 20px;

    border:
        1px solid #dddddd;

    border-radius:
        6px;

    background:
        #ffffff;
}


.layer-panel-title {

    font-size:
        12px;

    font-weight:
        700;

    letter-spacing:
        0.05em;

    margin-bottom:
        6px;
}


.layer-panel-subtitle {

    font-size:
        12px;

    color:
        #666666;

    margin-bottom:
        14px;
}


.layer-profile-row {

    display:
        grid;

    grid-template-columns:
        48px
        minmax(0, 1fr)
        54px;

    align-items:
        center;

    gap:
        9px;

    margin:
        7px 0;
}


.layer-profile-label {

    font-size:
        11px;

    font-weight:
        600;

    color:
        #333333;
}


.layer-track {

    position:
        relative;

    height:
        14px;

    background:
        #f4f4f4;

    border-radius:
        2px;

    overflow:
        hidden;
}


.layer-background-bar {

    position:
        absolute;

    left:
        0;

    top:
        2px;

    height:
        10px;

    background:
        #cfcfcf;

    opacity:
        0.78;

    border-radius:
        2px;
}


.layer-class-bar {

    position:
        absolute;

    left:
        0;

    top:
        4px;

    height:
        6px;

    border-radius:
        2px;
}


.layer-value {

    font-size:
        10px;

    color:
        #555555;

    text-align:
        right;
}


.layer-legend {

    display:
        flex;

    gap:
        18px;

    margin-top:
        12px;

    font-size:
        10px;

    color:
        #666666;
}


.layer-legend-key {

    display:
        inline-flex;

    align-items:
        center;

    gap:
        5px;
}


.layer-swatch {

    width:
        16px;

    height:
        6px;

    border-radius:
        1px;
}


.layer-message {

    color:
        #777777;

    font-size:
        12px;
}



@media (max-width: 700px) {

    #wavemap-app {

        padding:
            18px
            15px
            22px
            15px;
    }


    .figure-header {

        grid-template-columns:
            1fr;

        gap: 14px;
    }


    #main-figure {

        min-height: 880px;
    }


    .selection-grid {

        grid-template-columns:
            repeat(
                2,
                minmax(0, 1fr)
            );
    }
}

</style>

</head>


<body>


<div id="wavemap-app">


    <!-- =====================================================
         HEADER
         ===================================================== -->

    <div class="figure-header">


        <div class="figure-title">

            <h2>
                Area-specific WaveMAP explorer
            </h2>

            <p>
                Select an anatomical group, hover over units for
                metadata, and click an individual unit to inspect
                its extracellular waveform and, for cortical groups,
                its class-specific cortical-layer profile.
            </p>

        </div>


        <div class="control">

            <label for="area-select">
                ANATOMICAL GROUP
            </label>

            <select id="area-select">

                __AREA_OPTIONS__

            </select>

        </div>


    </div>


    <!-- =====================================================
         PLOT
         ===================================================== -->

    <div id="main-figure"></div>


    <!-- =====================================================
         SELECTED UNIT
         ===================================================== -->

    <div id="selection-panel">


        <div class="selection-title">

            SELECTED UNIT

        </div>


        <div class="selection-grid">


            <div class="selection-item">

                <span class="selection-label">
                    Unit
                </span>

                <span
                    class="selection-value"
                    id="sel-unit"
                >
                    —
                </span>

            </div>


            <div class="selection-item">

                <span class="selection-label">
                    WaveMAP class
                </span>

                <span
                    class="selection-value"
                    id="sel-class"
                >
                    —
                </span>

            </div>


            <div class="selection-item">

                <span class="selection-label">
                    CCF area
                </span>

                <span
                    class="selection-value"
                    id="sel-area"
                >
                    —
                </span>

            </div>


            <div class="selection-item">

                <span class="selection-label">
                    Firing rate
                </span>

                <span
                    class="selection-value"
                    id="sel-fr"
                >
                    —
                </span>

            </div>


            <div class="selection-item">

                <span class="selection-label">
                    Trough-to-peak
                </span>

                <span
                    class="selection-value"
                    id="sel-t2p"
                >
                    —
                </span>

            </div>


            <div class="selection-item">

                <span class="selection-label">
                    SNR
                </span>

                <span
                    class="selection-value"
                    id="sel-snr"
                >
                    —
                </span>

            </div>


            <div class="selection-item">

                <span class="selection-label">
                    FS
                </span>

                <span
                    class="selection-value"
                    id="sel-fs"
                >
                    —
                </span>

            </div>


            <div class="selection-item">

                <span class="selection-label">
                    Putative PV-like
                </span>

                <span
                    class="selection-value"
                    id="sel-pv"
                >
                    —
                </span>

            </div>


            <div class="selection-item">

                <span class="selection-label">
                    SST optotagging
                </span>

                <span
                    class="selection-value"
                    id="sel-sst"
                >
                    —
                </span>

            </div>


        </div>


    </div>


    <!-- =====================================================
         CORTICAL-LAYER PROFILE
         ===================================================== -->

    <div id="layer-panel">

        <div class="layer-panel-title">
            CORTICAL-LAYER PROFILE
        </div>

        <div
            class="layer-panel-subtitle"
            id="layer-panel-subtitle"
        >
        </div>

        <div id="layer-profile-content"></div>

        <div
            class="layer-legend"
            id="layer-legend"
        >

            <span class="layer-legend-key">
                <span
                    class="layer-swatch"
                    style="background:#cfcfcf;"
                ></span>
                All units in cortical group
            </span>

            <span class="layer-legend-key">
                <span
                    class="layer-swatch"
                    id="layer-class-swatch"
                ></span>
                Selected WaveMAP class
            </span>

        </div>

    </div>


    <!-- =====================================================
         FOOTER
         ===================================================== -->

    <div class="figure-note">

        WaveMAP was fitted independently within each anatomical
        group. Colours denote local waveform communities.
        Click a UMAP point to emphasize its local community: the
        cluster mean is shown as a thick class-coloured line, the
        exact selected unit as a thinner translucent line in the
        same colour, and ±1 SD as translucent class-coloured shading.
        Other waveform communities are de-emphasized in gray.
        For MO, PFC and VIS, the selected class's cortical-layer
        distribution is shown relative to the overall layer
        distribution of that cortical group.

    </div>


</div>


<script>


// ============================================================
// DATA
// ============================================================

const FIGURES =
    __FIGURES_JSON__;


const UNITS =
    __UNITS_JSON__;


const CLASSES =
    __CLASSES_JSON__;


const WAVEFORM_X =
    __WAVEFORM_X_JSON__;


const DEFAULT_GROUP =
    __DEFAULT_GROUP_JSON__;


//
// ============================================================
// ELEMENTS
// ============================================================
//

const graph =
    document.getElementById(
        "main-figure"
    );


const areaSelect =
    document.getElementById(
        "area-select"
    );


const selectionPanel =
    document.getElementById(
        "selection-panel"
    );


const layerPanel =
    document.getElementById(
        "layer-panel"
    );


const layerProfileContent =
    document.getElementById(
        "layer-profile-content"
    );


const layerPanelSubtitle =
    document.getElementById(
        "layer-panel-subtitle"
    );


const layerLegend =
    document.getElementById(
        "layer-legend"
    );


const layerClassSwatch =
    document.getElementById(
        "layer-class-swatch"
    );


let currentGroup =
    DEFAULT_GROUP;


// ============================================================
// HELPERS
// ============================================================

function deepCopy(value) {

    return JSON.parse(
        JSON.stringify(value)
    );
}


function formatValue(
    value,
    digits,
    suffix
) {

    if (
        value === null
        ||
        value === undefined
        ||
        Number.isNaN(
            Number(value)
        )
    ) {

        return "—";
    }


    return (
        Number(value)
        .toFixed(digits)
        +
        suffix
    );
}


// ============================================================
// PLOTLY CONFIG
// ============================================================

function plotConfig() {

    return {

        responsive:
            true,

        displaylogo:
            false,

        scrollZoom:
            false,

        modeBarButtonsToRemove: [

            "lasso2d",

            "select2d",
        ],

        toImageButtonOptions: {

            format:
                "svg",

            filename:
                "wavemap_"
                +
                currentGroup
                .toLowerCase(),
        },
    };
}


// ============================================================
// RENDER AREA
// ============================================================

async function renderGroup(group) {

    currentGroup =
        group;


    selectionPanel.style.display =
        "none";


    layerPanel.style.display =
        "none";


    const fig =
        deepCopy(
            FIGURES[group]
        );


    fig.layout.autosize =
        true;


    delete fig.layout.width;


    await Plotly.react(

        graph,

        fig.data,

        fig.layout,

        plotConfig()
    );
}


// ============================================================
// METADATA
// ============================================================

function updateMetadata(info) {

    document.getElementById(
        "sel-unit"
    ).textContent =
        info.uid;


    document.getElementById(
        "sel-class"
    ).textContent =
        info.class;


    document.getElementById(
        "sel-area"
    ).textContent =
        info.area;


    document.getElementById(
        "sel-fr"
    ).textContent =
        formatValue(
            info.fr,
            2,
            " Hz"
        );


    document.getElementById(
        "sel-t2p"
    ).textContent =
        formatValue(
            info.t2p,
            3,
            " ms"
        );


    document.getElementById(
        "sel-snr"
    ).textContent =
        formatValue(
            info.snr,
            2,
            ""
        );


    document.getElementById(
        "sel-fs"
    ).textContent =
        info.fs
        ? "Yes"
        : "No";


    document.getElementById(
        "sel-pv"
    ).textContent =
        info.pv
        ? "Yes"
        : "No";


    document.getElementById(
        "sel-sst"
    ).textContent =
        info.sst;


    selectionPanel.style.display =
        "block";
}


// ============================================================
// FIGURE-8-STYLE CORTICAL-LAYER PROFILE
// ============================================================

function updateLayerProfile(
    info,
    classInfo
) {

    layerProfileContent.innerHTML =
        "";


    if (
        !classInfo
        ||
        !classInfo.layer_available
    ) {

        layerPanelSubtitle.textContent =
            info.group
            +
            " is not displayed as a cortical-layer profile.";

        layerProfileContent.innerHTML =
            '<div class="layer-message">'
            +
            'Layer profiles are shown for MO, PFC and VIS only.'
            +
            '</div>';

        layerLegend.style.display =
            "none";

        layerPanel.style.display =
            "block";

        return;
    }


    layerLegend.style.display =
        "flex";


    layerPanelSubtitle.textContent =
        info.class
        +
        " · "
        +
        classInfo.layer_n
        +
        " units with CCF layer assignment";


    layerClassSwatch.style.background =
        classInfo.color;


    const labels =
        classInfo.layer_labels;


    const clusterValues =
        classInfo.layer_percent;


    const backgroundValues =
        classInfo.background_layer_percent;


    for (
        let i = 0;
        i < labels.length;
        i++
    ) {

        const row =
            document.createElement(
                "div"
            );

        row.className =
            "layer-profile-row";


        const label =
            document.createElement(
                "div"
            );

        label.className =
            "layer-profile-label";

        label.textContent =
            labels[i];


        const track =
            document.createElement(
                "div"
            );

        track.className =
            "layer-track";


        const bg =
            document.createElement(
                "div"
            );

        bg.className =
            "layer-background-bar";

        bg.style.width =
            Math.max(
                0,
                Math.min(
                    100,
                    Number(
                        backgroundValues[i]
                    )
                )
            )
            +
            "%";


        const cls =
            document.createElement(
                "div"
            );

        cls.className =
            "layer-class-bar";

        cls.style.width =
            Math.max(
                0,
                Math.min(
                    100,
                    Number(
                        clusterValues[i]
                    )
                )
            )
            +
            "%";

        cls.style.background =
            classInfo.color;


        track.appendChild(
            bg
        );

        track.appendChild(
            cls
        );


        const value =
            document.createElement(
                "div"
            );

        value.className =
            "layer-value";

        value.textContent =
            Number(
                clusterValues[i]
            ).toFixed(1)
            +
            "%";


        row.appendChild(
            label
        );

        row.appendChild(
            track
        );

        row.appendChild(
            value
        );


        layerProfileContent.appendChild(
            row
        );
    }


    layerPanel.style.display =
        "block";
}


// ============================================================
// SELECTED UNIT WAVEFORM
// ============================================================

async function showSelectedUnit(
    info,
    clickedX,
    clickedY
) {

    const classInfo =
        CLASSES[
            info.group
        ][
            String(
                info.local_class
            )
        ];


    if (!classInfo) {

        return;
    }


    updateLayerProfile(
        info,
        classInfo
    );


    const mean =
        classInfo.mean;


    const sd =
        classInfo.sd;


    const upper =
        mean.map(

            function(value, index) {

                return (
                    value
                    +
                    sd[index]
                );
            }
        );


    const lower =
        mean.map(

            function(value, index) {

                return (
                    value
                    -
                    sd[index]
                );
            }
        );


    // --------------------------------------------------------
    // Start from clean original figure on every click
    // --------------------------------------------------------

    const fig =
        deepCopy(
            FIGURES[
                currentGroup
            ]
        );


    // --------------------------------------------------------
    // De-emphasize all pre-existing waveform communities.
    //
    // Mean traces become thin translucent gray lines.
    // Existing SD bands become very faint gray shading.
    // The selected community is then re-drawn on top below.
    // --------------------------------------------------------

    fig.data.forEach(

        function(trace) {

            if (
                trace.xaxis === "x2"
                &&
                trace.yaxis === "y2"
            ) {

                trace.opacity =
                    1.0;


                if (trace.line) {

                    trace.line.color =
                        "rgba(145,145,145,0.24)";


                    if (
                        trace.line.width
                        &&
                        trace.line.width > 0
                    ) {

                        trace.line.width =
                            1.15;
                    }
                }


                if (trace.fillcolor) {

                    trace.fillcolor =
                        "rgba(155,155,155,0.035)";
                }


                trace.showlegend =
                    false;
            }
        }
    );


    // --------------------------------------------------------
    // Selected UMAP point ring
    // --------------------------------------------------------

    fig.data.push({

        x: [
            clickedX
        ],

        y: [
            clickedY
        ],

        type:
            "scatter",

        mode:
            "markers",

        xaxis:
            "x",

        yaxis:
            "y",

        marker: {

            size:
                13,

            color:
                "rgba(255,255,255,0)",

            line: {

                color:
                    "#111111",

                width:
                    2.2,
            },
        },

        hoverinfo:
            "skip",

        showlegend:
            false,
    });


    // --------------------------------------------------------
    // Selected class upper SD
    // --------------------------------------------------------

    fig.data.push({

        x:
            WAVEFORM_X,

        y:
            upper,

        type:
            "scatter",

        mode:
            "lines",

        xaxis:
            "x2",

        yaxis:
            "y2",

        line: {

            width:
                0,
        },

        hoverinfo:
            "skip",

        showlegend:
            false,
    });


    // --------------------------------------------------------
    // Selected class lower SD + translucent class-colour fill
    // --------------------------------------------------------

    fig.data.push({

        x:
            WAVEFORM_X,

        y:
            lower,

        type:
            "scatter",

        mode:
            "lines",

        xaxis:
            "x2",

        yaxis:
            "y2",

        line: {

            width:
                0,
        },

        fill:
            "tonexty",

        fillcolor:
            classInfo.color
            .replace(
                "rgb(",
                "rgba("
            )
            .replace(
                ")",
                ",0.13)"
            ),

        name:
            "Cluster ±1 SD",

        legendrank:
            3,

        hoverinfo:
            "skip",

        showlegend:
            true,
    });


    // --------------------------------------------------------
    // EXACT CLICKED UNIT WAVEFORM
    //
    // Same class colour as the UMAP cluster, but thinner and
    // translucent so the cluster mean remains visually dominant.
    // --------------------------------------------------------

    fig.data.push({

        x:
            WAVEFORM_X,

        y:
            info.waveform,

        type:
            "scatter",

        mode:
            "lines",

        xaxis:
            "x2",

        yaxis:
            "y2",

        line: {

            color:
                classInfo.color
                .replace(
                    "rgb(",
                    "rgba("
                )
                .replace(
                    ")",
                    ",0.48)"
                ),

            width:
                1.7,
        },

        name:
            "Selected unit",

        legendrank:
            2,

        hovertemplate:

            "<b>"
            +
            "Selected unit"
            +
            "</b>"
            +
            "<br>"
            +
            info.uid
            +
            "<br>"
            +
            "Normalized amplitude: "
            +
            "%{y:.3f}"
            +
            "<extra></extra>",

        showlegend:
            true,
    });


    // --------------------------------------------------------
    // SELECTED CLUSTER MEAN
    //
    // Draw LAST so it sits above the individual waveform and
    // SD shading. This is intentionally the strongest element.
    // --------------------------------------------------------

    fig.data.push({

        x:
            WAVEFORM_X,

        y:
            mean,

        type:
            "scatter",

        mode:
            "lines",

        xaxis:
            "x2",

        yaxis:
            "y2",

        line: {

            color:
                classInfo.color,

            width:
                4.0,
        },

        name:
            "Cluster mean",

        legendrank:
            1,

        hovertemplate:

            "<b>"
            +
            info.class
            +
            " mean"
            +
            "</b>"
            +
            "<br>"
            +
            "Normalized amplitude: "
            +
            "%{y:.3f}"
            +
            "<extra></extra>",

        showlegend:
            true,
    });


    // --------------------------------------------------------
    // Update waveform panel heading
    // --------------------------------------------------------

    if (
        fig.layout.annotations
        &&
        fig.layout.annotations.length
        >= 2
    ) {

        fig.layout.annotations[
            1
        ].text =

            "<b>"
            +
            "Waveform"
            +
            "</b>"
            +
            " · "
            +
            info.class;
    }


    // --------------------------------------------------------
    // Compact legend below the waveform panel only
    //
    // The right subplot spans approximately x = 0.58–1.00.
    // x = 0.79 therefore centres the legend below that panel.
    // y = 0.40 places it in the vertical gap between the
    // waveform axes and the class-summary table.
    // --------------------------------------------------------

    fig.layout.showlegend =
        true;


    fig.layout.legend = {

        orientation:
            "h",

        x:
            0.79,

        xanchor:
            "center",

        // Separate line below the waveform x-axis title.
        // The lower table begins beneath this inter-row gap.
        y:
            0.305,

        yanchor:
            "top",

        font: {

            size:
                10,

            color:
                "#555555",
        },

        bgcolor:
            "rgba(255,255,255,0)",

        borderwidth:
            0,

        // Traces are added as SD, selected unit, then mean.
        // Reverse the legend so the conceptual order reads:
        // Cluster mean | Selected unit | Cluster ±1 SD.
        traceorder:
            "reversed",
    };


    fig.layout.autosize =
        true;


    delete fig.layout.width;


    await Plotly.react(

        graph,

        fig.data,

        fig.layout,

        plotConfig()
    );
}


// ============================================================
// INITIALIZE
// ============================================================

async function initialize() {


    await renderGroup(
        currentGroup
    );


    // --------------------------------------------------------
    // Anatomical group selector
    // --------------------------------------------------------

    areaSelect.addEventListener(

        "change",

        async function() {

            await renderGroup(
                this.value
            );
        }
    );


    // --------------------------------------------------------
    // UMAP click
    // --------------------------------------------------------

    graph.on(

        "plotly_click",

        async function(eventData) {


            if (
                !eventData
                ||
                !eventData.points
                ||
                eventData.points.length
                === 0
            ) {

                return;
            }


            const point =
                eventData.points[0];


            // Only actual UMAP unit points contain customdata
            if (
                !point.customdata
                ||
                point.customdata.length
                < 1
            ) {

                return;
            }


            const rowIndex =
                String(
                    point.customdata[
                        0
                    ]
                );


            const info =
                UNITS[
                    rowIndex
                ];


            if (!info) {

                return;
            }


            updateMetadata(
                info
            );


            await showSelectedUnit(

                info,

                point.x,

                point.y
            );
        }
    );


    // --------------------------------------------------------
    // Responsive resize
    // --------------------------------------------------------

    window.addEventListener(

        "resize",

        function() {

            if (
                graph
                &&
                graph.data
            ) {

                Plotly.Plots.resize(
                    graph
                );
            }
        }
    );
}


initialize();


</script>


</body>

</html>
"""


# ============================================================
# 16. INSERT DATA
#
# NOT an f-string:
# avoids Python/JavaScript brace syntax errors.
# ============================================================

html = HTML_TEMPLATE


html = html.replace("__AREA_OPTIONS__", area_options)


html = html.replace("__FIGURES_JSON__", json.dumps(figure_json, separators=(",", ":")))


html = html.replace("__UNITS_JSON__", json.dumps(unit_payload, separators=(",", ":")))


html = html.replace("__CLASSES_JSON__", json.dumps(class_payload, separators=(",", ":")))


html = html.replace(
    "__WAVEFORM_X_JSON__",
    json.dumps(np.asarray(waveform_x, dtype=float).round(6).tolist(), separators=(",", ":")),
)


html = html.replace("__DEFAULT_GROUP_JSON__", json.dumps(GROUP_ORDER[0]))


# ============================================================
# 17. VALIDATION
# ============================================================

required_tokens = [
    "__AREA_OPTIONS__",
    "__FIGURES_JSON__",
    "__UNITS_JSON__",
    "__CLASSES_JSON__",
    "__WAVEFORM_X_JSON__",
    "__DEFAULT_GROUP_JSON__",
]


remaining = [token for token in required_tokens if token in html]


if remaining:
    raise RuntimeError("Unresolved HTML placeholders: " + str(remaining))


if "plotly_click" not in html:
    raise RuntimeError("UMAP click callback missing.")


if "info.waveform" not in html:
    raise RuntimeError("Individual waveform callback missing.")


# ============================================================
# 18. SAVE
# ============================================================

FIG1_HTML.write_text(html, encoding="utf-8")


print()
print("=" * 72)

print("FINAL PUBLICATION INTERACTIVE FIGURE EXPORTED")

print("=" * 72)

print()

print(FIG1_HTML)

print()

print("Areas: " + ", ".join(GROUP_ORDER))

print()

print(f"Interactive units: {len(unit_payload):,}")

print()

print("Compact waveform legend after selection: YES")

print("UMAP click -> individual waveform: YES")

print("Selected point highlight: YES")

print("Selected cluster mean emphasized: YES")

print("Selected unit uses class colour: YES")

print("Class mean +/- SD: YES")

print("Other waveform communities gray: YES")

print("Responsive layout: YES")

print()


# ============================================================
# 19. CONFIRMATION
# ============================================================

display(
    HTML(
        """
        <div style="
            margin:14px 0;
            padding:14px 16px;
            border:1px solid #dddddd;
            border-radius:4px;
            background:white;
            font-family:Arial,Helvetica,sans-serif;
        ">

            <div style="
                font-size:14px;
                font-weight:600;
                margin-bottom:5px;
            ">
                ✓ Final WaveMAP interactive figure exported
            </div>

            <div style="
                font-size:12px;
                color:#666666;
                line-height:1.5;
            ">
                After selecting a UMAP unit, the waveform panel
                emphasizes the selected cluster mean in its class
                colour, shows the exact selected unit as a thinner
                translucent trace, displays ±1 SD as a translucent
                band, and de-emphasizes other waveform communities
                in gray. A compact waveform legend is shown only
                after selection.
            </div>

        </div>
        """
    )
)

# ============================================================
# FINAL INTERACTIVE FIGURE 2
# Putative FS/PV-like and optotagged SST in WaveMAP space
#
# PUBLICATION VERSION
#
# Uses EXISTING calculations from map_df:
#   putative_fs
#   sst_optotagged
#   sst_fs_overlap
#
# Does NOT recalculate classification thresholds.
#
# Controls:
#   1. Anatomical group
#   2. Population
#
# Population views:
#   - Putative FS/PV-like
#   - Optotagged SST
#   - SST ∩ putative FS
#
# Hover:
#   unit metadata + classification information
#
# Click:
#   highlights selected unit and shows metadata below
#
# IMPORTANT:
# There is NO PV optotagging in this dataset.
# ============================================================


# ============================================================
# 1. OUTPUT
# ============================================================

INTERACTIVE_DIR = Path(OUT_DIR) / "interactive"
INTERACTIVE_DIR.mkdir(parents=True, exist_ok=True)

FIG2_HTML = INTERACTIVE_DIR / "fs-sst-wavemap-explorer.html"


# ============================================================
# 2. REQUIRED INPUTS
# ============================================================

for obj_name in [
    "map_df",
    "group_embeddings",
]:
    if obj_name not in globals():
        raise RuntimeError(f"Missing required object: {obj_name}")


required_columns = [
    "wavemap_group",
    "putative_fs",
    "sst_opto_available",
    "sst_optotagged",
    "sst_fs_overlap",
    "unit_uid",
]


missing_columns = [col for col in required_columns if col not in map_df.columns]


if missing_columns:
    raise RuntimeError("map_df is missing required columns: " + ", ".join(missing_columns))


# ============================================================
# 3. AREA SETTINGS
# ============================================================

GROUP_ORDER_FIG2 = [
    group
    for group in [
        "MO",
        "PFC",
        "VIS",
        "STR",
        "HPC",
        "THAL",
    ]
    if group in group_embeddings
]


GROUP_NAMES_FIG2 = {
    "MO": "Motor cortex",
    "PFC": "Prefrontal cortex",
    "VIS": "Visual cortex",
    "STR": "Striatum",
    "HPC": "Hippocampus",
    "THAL": "Thalamus",
}


if not GROUP_ORDER_FIG2:
    raise RuntimeError("No anatomical groups available.")


# ============================================================
# 4. EXACT DISPLAY DEFINITIONS
#
# These correspond directly to the existing static figure.
# ============================================================

POPULATIONS = {
    "fs": {
        "label": "Putative FS/PV-like",
        "mask_col": "putative_fs",
        "color": "#377EB8",
        "description": "Trough-to-peak < 0.40 ms and firing rate ≥ 10 Hz",
        "denominator": "all",
    },
    "sst": {
        "label": "Optotagged SST",
        "mask_col": "sst_optotagged",
        "color": "#CC2F8A",
        "description": "SST-Ai32 light-activated units",
        "denominator": "all",
    },
    "overlap": {
        "label": "SST ∩ putative FS",
        "mask_col": "sst_fs_overlap",
        "color": "#F28E2B",
        "description": "Optotagged SST units also meeting the FS criterion",
        "denominator": "sst",
    },
}


POPULATION_ORDER = [
    "fs",
    "sst",
    "overlap",
]


# ============================================================
# 5. DISPLAY DATAFRAME
# ============================================================

fig2_df = map_df.copy()


# ------------------------------------------------------------
# Numeric metadata
# ------------------------------------------------------------

if "t2p_ms" in fig2_df.columns:
    fig2_df["_t2p"] = pd.to_numeric(fig2_df["t2p_ms"], errors="coerce")

elif "waveform_duration" in fig2_df.columns:
    fig2_df["_t2p"] = pd.to_numeric(fig2_df["waveform_duration"], errors="coerce") * 1000

else:
    fig2_df["_t2p"] = np.nan


if "firing_rate_hz" in fig2_df.columns:
    fig2_df["_fr"] = pd.to_numeric(fig2_df["firing_rate_hz"], errors="coerce")

elif "firing_rate" in fig2_df.columns:
    fig2_df["_fr"] = pd.to_numeric(fig2_df["firing_rate"], errors="coerce")

else:
    fig2_df["_fr"] = np.nan


if "snr" in fig2_df.columns:
    fig2_df["_snr"] = pd.to_numeric(fig2_df["snr"], errors="coerce")

else:
    fig2_df["_snr"] = np.nan


# ------------------------------------------------------------
# SST status
# ------------------------------------------------------------

fig2_df["_sst_status"] = "Not tested"


fig2_df.loc[fig2_df["sst_opto_available"].fillna(False), "_sst_status"] = "Tested — SST−"


fig2_df.loc[fig2_df["sst_optotagged"].fillna(False), "_sst_status"] = "Optotagged SST+"


# ============================================================
# 6. BUILD AREA PAYLOAD
#
# Store each area's UMAP coordinates + row indices.
# ============================================================

area_payload = {}


for group in GROUP_ORDER_FIG2:
    idx, emb = group_embeddings[group]

    idx = np.asarray(idx, dtype=int)

    emb = np.asarray(emb, dtype=float)

    if len(idx) != len(emb):
        raise RuntimeError(f"{group}: embedding/data length mismatch.")

    sub = fig2_df.iloc[idx]

    # Safety check:
    # all rows in this embedding should belong to this group.
    bad_group = ~sub["wavemap_group"].astype(str).eq(group)

    if bad_group.any():
        raise RuntimeError(f"{group}: group_embeddings rows do not match map_df wavemap_group.")

    area_payload[group] = {
        "indices": idx.astype(int).tolist(),
        "x": emb[:, 0].astype(float).round(6).tolist(),
        "y": emb[:, 1].astype(float).round(6).tolist(),
    }


# ============================================================
# 7. UNIT PAYLOAD
# ============================================================

unit_payload_fig2 = {}


all_embedding_indices = sorted(
    set(row_index for group in GROUP_ORDER_FIG2 for row_index in area_payload[group]["indices"])
)


for row_index in all_embedding_indices:
    row = fig2_df.iloc[row_index]

    fr = row["_fr"]
    t2p = row["_t2p"]
    snr = row["_snr"]

    # Exact CCF area if available
    exact_area = "—"

    for candidate in [
        "area",
        "ccf_area",
        "structure_acronym",
        "location",
    ]:
        if candidate in fig2_df.columns:
            value = row.get(candidate, np.nan)

            if pd.notna(value):
                exact_area = str(value)
                break

    # WaveMAP class
    local_class = row.get("wavemap_local", np.nan)

    try:
        local_class = int(local_class)

        wavemap_label = f"{row['wavemap_group']}-{local_class}"

    except Exception:
        wavemap_label = "—"

    unit_payload_fig2[str(row_index)] = {
        "row": int(row_index),
        "uid": str(row.get("unit_uid", row_index)),
        "group": str(row["wavemap_group"]),
        "wavemap_class": wavemap_label,
        "area": exact_area,
        "fr": (float(fr) if np.isfinite(fr) else None),
        "t2p": (float(t2p) if np.isfinite(t2p) else None),
        "snr": (float(snr) if np.isfinite(snr) else None),
        "fs": bool(row["putative_fs"]),
        "sst_available": bool(row["sst_opto_available"]),
        "sst": bool(row["sst_optotagged"]),
        "overlap": bool(row["sst_fs_overlap"]),
        "sst_status": str(row["_sst_status"]),
    }


# ============================================================
# 8. REGIONAL SUMMARY PAYLOAD
#
# Uses SAME denominators as original static figure:
#
# FS:
#   n FS / all regional WaveMAP units
#
# SST:
#   n optotagged SST / all regional WaveMAP units
#
# Overlap:
#   n SST∩FS / optotagged SST
# ============================================================

summary_payload_fig2 = {}


for group in GROUP_ORDER_FIG2:
    idx = np.asarray(area_payload[group]["indices"], dtype=int)

    sub = fig2_df.iloc[idx]

    n_all = int(len(sub))

    n_fs = int(sub["putative_fs"].sum())

    n_sst = int(sub["sst_optotagged"].sum())

    n_overlap = int(sub["sst_fs_overlap"].sum())

    summary_payload_fig2[group] = {
        "n_all": n_all,
        "fs": {
            "n": n_fs,
            "denominator": n_all,
            "percent": (100 * n_fs / n_all if n_all else None),
        },
        "sst": {
            "n": n_sst,
            "denominator": n_all,
            "percent": (100 * n_sst / n_all if n_all else None),
        },
        "overlap": {
            "n": n_overlap,
            "denominator": n_sst,
            "percent": (100 * n_overlap / n_sst if n_sst else None),
        },
    }


# ============================================================
# 9. AREA DROPDOWN OPTIONS
# ============================================================

area_options_fig2 = "".join(
    f'<option value="{group}">{GROUP_NAMES_FIG2[group]}</option>' for group in GROUP_ORDER_FIG2
)


# ============================================================
# 10. POPULATION DROPDOWN OPTIONS
# ============================================================

population_options_fig2 = "".join(
    '<option value="{}">{}</option>'.format(key, POPULATIONS[key]["label"])
    for key in POPULATION_ORDER
)


# ============================================================
# 11. HTML
#
# IMPORTANT:
# Normal raw string — NOT an f-string.
# JavaScript braces are therefore safe.
# ============================================================

HTML_TEMPLATE_FIG2 = r"""
<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="utf-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1"
>

<title>
FS/PV-like and optotagged SST WaveMAP explorer
</title>

<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>


<style>

* {
    box-sizing: border-box;
}


html,
body {

    margin: 0;
    padding: 0;

    width: 100%;

    background: #FFFFFF;

    color: #222222;

    font-family:
        Arial,
        Helvetica,
        sans-serif;
}


#fig2-app {

    width: 100%;

    max-width: 1180px;

    margin: 0 auto;

    padding:
        24px
        30px
        28px
        30px;
}


/* ==========================================================
   HEADER
   ========================================================== */

.figure-header {

    width: 100%;

    display: grid;

    grid-template-columns:
        minmax(0, 1fr)
        230px
        230px;

    align-items: end;

    gap: 22px;

    padding-bottom: 16px;

    border-bottom:
        1px solid #EEEEEE;
}


.figure-title {

    min-width: 0;
}


.figure-title h2 {

    margin:
        0
        0
        5px
        0;

    font-size: 20px;

    line-height: 1.25;

    font-weight: 600;
}


.figure-title p {

    margin: 0;

    max-width: 620px;

    color: #666666;

    font-size: 12.5px;

    line-height: 1.5;
}


/* ==========================================================
   CONTROLS
   ========================================================== */

.control {

    width: 100%;
}


.control label {

    display: block;

    margin-bottom: 6px;

    color: #555555;

    font-size: 10px;

    line-height: 1;

    font-weight: 600;

    letter-spacing: 0.055em;
}


.control select {

    width: 100%;

    height: 40px;

    padding:
        0
        11px;

    background: #FFFFFF;

    color: #222222;

    border:
        1px solid #BDBDBD;

    border-radius: 3px;

    font-family:
        Arial,
        Helvetica,
        sans-serif;

    font-size: 13px;
}


/* ==========================================================
   POPULATION SUMMARY
   ========================================================== */

.population-summary {

    width: 100%;

    display: grid;

    grid-template-columns:
        minmax(0, 1fr)
        auto;

    align-items: center;

    gap: 24px;

    margin-top: 18px;

    padding:
        14px
        16px;

    background: #FAFAFA;

    border:
        1px solid #EEEEEE;

    border-radius: 4px;
}


.population-summary-left {

    min-width: 0;
}


.population-name {

    display: flex;

    align-items: center;

    gap: 9px;

    margin-bottom: 4px;

    color: #222222;

    font-size: 13px;

    font-weight: 600;
}


.population-dot {

    width: 10px;

    height: 10px;

    flex: 0 0 10px;

    border-radius: 50%;
}


.population-description {

    color: #666666;

    font-size: 11px;

    line-height: 1.45;
}


.population-count {

    text-align: right;

    white-space: nowrap;
}


.population-count-main {

    display: block;

    color: #222222;

    font-size: 18px;

    line-height: 1.1;

    font-weight: 600;
}


.population-count-sub {

    display: block;

    margin-top: 3px;

    color: #777777;

    font-size: 10.5px;
}


/* ==========================================================
   UMAP
   ========================================================== */

#fig2-plot {

    width: 100%;

    min-width: 0;

    height: 620px;
}


/* ==========================================================
   SELECTED UNIT
   ========================================================== */

#fig2-selection {

    display: none;

    width: 100%;

    margin-top: 4px;

    padding-top: 16px;

    border-top:
        1px solid #DDDDDD;
}


.selection-title {

    margin:
        0
        0
        12px
        0;

    color: #333333;

    font-size: 11px;

    font-weight: 600;

    letter-spacing: 0.025em;
}


.selection-grid {

    width: 100%;

    display: grid;

    grid-template-columns:
        repeat(
            8,
            minmax(0, 1fr)
        );

    column-gap: 18px;

    row-gap: 14px;
}


.selection-item {

    min-width: 0;
}


.selection-label {

    display: block;

    margin-bottom: 4px;

    color: #777777;

    font-size: 9px;

    font-weight: 600;

    line-height: 1.2;

    letter-spacing: 0.04em;

    text-transform: uppercase;
}


.selection-value {

    display: block;

    color: #222222;

    font-size: 11.5px;

    line-height: 1.35;

    overflow-wrap: anywhere;
}


/* ==========================================================
   NOTE
   ========================================================== */

.figure-note {

    width: 100%;

    margin-top: 16px;

    padding-top: 12px;

    border-top:
        1px solid #EEEEEE;

    color: #666666;

    font-size: 10.5px;

    line-height: 1.5;
}


/* ==========================================================
   RESPONSIVE
   ========================================================== */

@media (max-width: 900px) {

    .figure-header {

        grid-template-columns:
            1fr
            1fr;
    }


    .figure-title {

        grid-column:
            1 / -1;
    }


    .selection-grid {

        grid-template-columns:
            repeat(
                4,
                minmax(0, 1fr)
            );
    }
}


@media (max-width: 650px) {

    #fig2-app {

        padding:
            18px
            15px
            22px
            15px;
    }


    .figure-header {

        grid-template-columns:
            1fr;

        gap: 14px;
    }


    .figure-title {

        grid-column:
            auto;
    }


    .population-summary {

        grid-template-columns:
            1fr;
    }


    .population-count {

        text-align: left;
    }


    #fig2-plot {

        height: 570px;
    }


    .selection-grid {

        grid-template-columns:
            repeat(
                2,
                minmax(0, 1fr)
            );
    }
}

</style>

</head>


<body>


<div id="fig2-app">


    <!-- =====================================================
         HEADER
         ===================================================== -->

    <div class="figure-header">


        <div class="figure-title">

            <h2>
                FS/PV-like and optotagged SST populations
            </h2>

            <p>
                Explore the anatomical distribution of
                extracellularly defined putative FS/PV-like
                units and biologically identified SST units
                within area-specific WaveMAP embeddings.
            </p>

        </div>


        <div class="control">

            <label for="fig2-area">
                ANATOMICAL GROUP
            </label>

            <select id="fig2-area">
                __AREA_OPTIONS__
            </select>

        </div>


        <div class="control">

            <label for="fig2-population">
                POPULATION
            </label>

            <select id="fig2-population">
                __POPULATION_OPTIONS__
            </select>

        </div>


    </div>


    <!-- =====================================================
         SUMMARY
         ===================================================== -->

    <div class="population-summary">


        <div class="population-summary-left">


            <div class="population-name">

                <span
                    class="population-dot"
                    id="population-dot"
                ></span>

                <span id="population-name">
                    —
                </span>

            </div>


            <div
                class="population-description"
                id="population-description"
            >
                —
            </div>


        </div>


        <div class="population-count">

            <span
                class="population-count-main"
                id="population-count-main"
            >
                —
            </span>

            <span
                class="population-count-sub"
                id="population-count-sub"
            >
                —
            </span>

        </div>


    </div>


    <!-- =====================================================
         PLOT
         ===================================================== -->

    <div id="fig2-plot"></div>


    <!-- =====================================================
         SELECTED UNIT
         ===================================================== -->

    <div id="fig2-selection">


        <div class="selection-title">
            SELECTED UNIT
        </div>


        <div class="selection-grid">


            <div class="selection-item">

                <span class="selection-label">
                    Unit
                </span>

                <span
                    class="selection-value"
                    id="f2-unit"
                >
                    —
                </span>

            </div>


            <div class="selection-item">

                <span class="selection-label">
                    WaveMAP class
                </span>

                <span
                    class="selection-value"
                    id="f2-class"
                >
                    —
                </span>

            </div>


            <div class="selection-item">

                <span class="selection-label">
                    CCF area
                </span>

                <span
                    class="selection-value"
                    id="f2-ccf"
                >
                    —
                </span>

            </div>


            <div class="selection-item">

                <span class="selection-label">
                    Firing rate
                </span>

                <span
                    class="selection-value"
                    id="f2-fr"
                >
                    —
                </span>

            </div>


            <div class="selection-item">

                <span class="selection-label">
                    Trough-to-peak
                </span>

                <span
                    class="selection-value"
                    id="f2-t2p"
                >
                    —
                </span>

            </div>


            <div class="selection-item">

                <span class="selection-label">
                    SNR
                </span>

                <span
                    class="selection-value"
                    id="f2-snr"
                >
                    —
                </span>

            </div>


            <div class="selection-item">

                <span class="selection-label">
                    Putative FS/PV-like
                </span>

                <span
                    class="selection-value"
                    id="f2-fs"
                >
                    —
                </span>

            </div>


            <div class="selection-item">

                <span class="selection-label">
                    SST optotagging
                </span>

                <span
                    class="selection-value"
                    id="f2-sst"
                >
                    —
                </span>

            </div>


        </div>


    </div>


    <!-- =====================================================
         NOTE
         ===================================================== -->

    <div class="figure-note">

        Putative FS/PV-like units are defined by
        trough-to-peak duration &lt; 0.40 ms and firing rate
        ≥ 10 Hz. SST identity is based on SST-Ai32
        optotagging. The overlap view shows optotagged SST
        units that also meet the putative FS criterion.

    </div>


</div>


<script>


// ============================================================
// DATA
// ============================================================

const AREAS =
    __AREA_JSON__;


const UNITS =
    __UNIT_JSON__;


const SUMMARY =
    __SUMMARY_JSON__;


const POPULATIONS =
    __POPULATION_JSON__;


const GROUP_NAMES =
    __GROUP_NAMES_JSON__;


const DEFAULT_GROUP =
    __DEFAULT_GROUP_JSON__;


const DEFAULT_POPULATION =
    "fs";


// ============================================================
// ELEMENTS
// ============================================================

const graph =
    document.getElementById(
        "fig2-plot"
    );


const areaSelect =
    document.getElementById(
        "fig2-area"
    );


const populationSelect =
    document.getElementById(
        "fig2-population"
    );


const selectionPanel =
    document.getElementById(
        "fig2-selection"
    );


let currentGroup =
    DEFAULT_GROUP;


let currentPopulation =
    DEFAULT_POPULATION;


// ============================================================
// HELPERS
// ============================================================

function formatNumber(
    value,
    digits
) {

    if (
        value === null
        ||
        value === undefined
        ||
        Number.isNaN(
            Number(value)
        )
    ) {

        return "—";
    }


    return Number(
        value
    ).toFixed(
        digits
    );
}


function plotConfig() {

    return {

        responsive:
            true,

        displaylogo:
            false,

        scrollZoom:
            false,

        modeBarButtonsToRemove: [
            "lasso2d",
            "select2d"
        ],

        toImageButtonOptions: {

            format:
                "svg",

            filename:
                (
                    "fs_sst_"
                    +
                    currentGroup
                    .toLowerCase()
                    +
                    "_"
                    +
                    currentPopulation
                ),
        },
    };
}


// ============================================================
// POPULATION TEST
// ============================================================

function belongsToPopulation(
    unit,
    population
) {

    if (population === "fs") {

        return unit.fs;
    }


    if (population === "sst") {

        return unit.sst;
    }


    if (population === "overlap") {

        return unit.overlap;
    }


    return false;
}


// ============================================================
// SUMMARY CARD
// ============================================================

function updateSummary() {

    const pop =
        POPULATIONS[
            currentPopulation
        ];


    const stats =
        SUMMARY[
            currentGroup
        ][
            currentPopulation
        ];


    document.getElementById(
        "population-dot"
    ).style.backgroundColor =
        pop.color;


    document.getElementById(
        "population-name"
    ).textContent =
        pop.label;


    document.getElementById(
        "population-description"
    ).textContent =
        pop.description;


    if (
        stats.percent === null
        ||
        stats.denominator === 0
    ) {

        document.getElementById(
            "population-count-main"
        ).textContent =
            "No units";


        document.getElementById(
            "population-count-sub"
        ).textContent =
            "";
    }

    else {

        document.getElementById(
            "population-count-main"
        ).textContent =
            (
                stats.n
                .toLocaleString()
                +
                " / "
                +
                stats.denominator
                .toLocaleString()
            );


        let denominatorText;


        if (
            currentPopulation
            === "overlap"
        ) {

            denominatorText =
                (
                    formatNumber(
                        stats.percent,
                        1
                    )
                    +
                    "% of optotagged SST"
                );
        }

        else {

            denominatorText =
                (
                    formatNumber(
                        stats.percent,
                        1
                    )
                    +
                    "% of regional units"
                );
        }


        document.getElementById(
            "population-count-sub"
        ).textContent =
            denominatorText;
    }
}


// ============================================================
// BUILD PLOT
// ============================================================

async function renderPlot() {

    selectionPanel.style.display =
        "none";


    const area =
        AREAS[
            currentGroup
        ];


    const pop =
        POPULATIONS[
            currentPopulation
        ];


    const backgroundX = [];
    const backgroundY = [];
    const backgroundCustom = [];


    const selectedX = [];
    const selectedY = [];
    const selectedCustom = [];


    for (
        let i = 0;
        i < area.indices.length;
        i++
    ) {

        const rowIndex =
            area.indices[i];


        const unit =
            UNITS[
                String(rowIndex)
            ];


        if (!unit) {

            continue;
        }


        const custom = [

            rowIndex,

            unit.uid,

            unit.wavemap_class,

            unit.area,

            (
                unit.fr === null
                ? "—"
                : unit.fr.toFixed(2)
            ),

            (
                unit.t2p === null
                ? "—"
                : unit.t2p.toFixed(3)
            ),

            (
                unit.snr === null
                ? "—"
                : unit.snr.toFixed(2)
            ),

            (
                unit.fs
                ? "Yes"
                : "No"
            ),

            unit.sst_status,
        ];


        backgroundX.push(
            area.x[i]
        );

        backgroundY.push(
            area.y[i]
        );

        backgroundCustom.push(
            custom
        );


        if (
            belongsToPopulation(
                unit,
                currentPopulation
            )
        ) {

            selectedX.push(
                area.x[i]
            );

            selectedY.push(
                area.y[i]
            );

            selectedCustom.push(
                custom
            );
        }
    }


    // --------------------------------------------------------
    // Background
    // --------------------------------------------------------

    const backgroundTrace = {

        x:
            backgroundX,

        y:
            backgroundY,

        type:
            "scattergl",

        mode:
            "markers",

        marker: {

            size:
                4,

            color:
                "#CFCFCF",

            opacity:
                0.28,

            line: {

                width:
                    0,
            },
        },

        customdata:
            backgroundCustom,

        hovertemplate:

            "<b>%{customdata[2]}</b>"
            +
            "<br>"
            +
            "Unit: %{customdata[1]}"
            +
            "<br>"
            +
            "CCF area: %{customdata[3]}"
            +
            "<br>"
            +
            "Firing rate: %{customdata[4]} Hz"
            +
            "<br>"
            +
            "Trough-to-peak: %{customdata[5]} ms"
            +
            "<br>"
            +
            "SNR: %{customdata[6]}"
            +
            "<br>"
            +
            "Putative FS/PV-like: %{customdata[7]}"
            +
            "<br>"
            +
            "SST: %{customdata[8]}"
            +
            "<extra></extra>",

        showlegend:
            false,
    };


    // --------------------------------------------------------
    // Selected population
    // --------------------------------------------------------

    const selectedTrace = {

        x:
            selectedX,

        y:
            selectedY,

        type:
            "scattergl",

        mode:
            "markers",

        marker: {

            size:
                (
                    currentPopulation
                    === "overlap"
                    ? 9
                    : 8
                ),

            color:
                pop.color,

            opacity:
                (
                    currentPopulation
                    === "overlap"
                    ? 0.88
                    : 0.76
                ),

            line: {

                color:
                    "#FFFFFF",

                width:
                    0.8,
            },
        },

        customdata:
            selectedCustom,

        hovertemplate:

            "<b>%{customdata[2]}</b>"
            +
            "<br>"
            +
            "Unit: %{customdata[1]}"
            +
            "<br>"
            +
            "CCF area: %{customdata[3]}"
            +
            "<br>"
            +
            "Firing rate: %{customdata[4]} Hz"
            +
            "<br>"
            +
            "Trough-to-peak: %{customdata[5]} ms"
            +
            "<br>"
            +
            "SNR: %{customdata[6]}"
            +
            "<br>"
            +
            "Putative FS/PV-like: %{customdata[7]}"
            +
            "<br>"
            +
            "SST: %{customdata[8]}"
            +
            "<extra></extra>",

        showlegend:
            false,
    };


    // --------------------------------------------------------
    // Layout
    // --------------------------------------------------------

    const layout = {

        template:
            "plotly_white",

        autosize:
            true,

        height:
            620,


        margin: {

            l:
                72,

            r:
                45,

            t:
                82,

            b:
                58,
        },


        title: {

            text:

                "<b>"
                +
                GROUP_NAMES[
                    currentGroup
                ]
                +
                "</b>"
                +
                "<br>"
                +
                "<sup>"
                +
                SUMMARY[
                    currentGroup
                ].n_all
                .toLocaleString()
                +
                " WaveMAP units"
                +
                "</sup>",

            x:
                0.01,

            xanchor:
                "left",

            y:
                0.975,

            yanchor:
                "top",

            font: {

                size:
                    18,

                color:
                    "#222222",
            },
        },


        xaxis: {

            title: {

                text:
                    "UMAP 1",

                font: {

                    size:
                        11,
                },

                standoff:
                    12,
            },

            showgrid:
                false,

            zeroline:
                false,

            showticklabels:
                false,

            ticks:
                "",

            fixedrange:
                false,
        },


        yaxis: {

            title: {

                text:
                    "UMAP 2",

                font: {

                    size:
                        11,
                },

                standoff:
                    12,
            },

            showgrid:
                false,

            zeroline:
                false,

            showticklabels:
                false,

            ticks:
                "",

            fixedrange:
                false,

            scaleanchor:
                "x",

            scaleratio:
                1,
        },


        showlegend:
            false,


        hoverlabel: {

            bgcolor:
                "#FFFFFF",

            bordercolor:
                "#BBBBBB",

            font: {

                size:
                    11,

                family:
                    "Arial, Helvetica, sans-serif",
            },
        },


        clickmode:
            "event+select",


        paper_bgcolor:
            "#FFFFFF",

        plot_bgcolor:
            "#FFFFFF",


        font: {

            family:
                "Arial, Helvetica, sans-serif",

            color:
                "#222222",
        },
    };


    await Plotly.react(

        graph,

        [
            backgroundTrace,
            selectedTrace,
        ],

        layout,

        plotConfig()
    );


    updateSummary();
}


// ============================================================
// SELECTED UNIT METADATA
// ============================================================

function updateSelectedUnit(
    unit
) {

    document.getElementById(
        "f2-unit"
    ).textContent =
        unit.uid;


    document.getElementById(
        "f2-class"
    ).textContent =
        unit.wavemap_class;


    document.getElementById(
        "f2-ccf"
    ).textContent =
        unit.area;


    document.getElementById(
        "f2-fr"
    ).textContent =

        unit.fr === null

        ? "—"

        : (
            unit.fr.toFixed(2)
            +
            " Hz"
        );


    document.getElementById(
        "f2-t2p"
    ).textContent =

        unit.t2p === null

        ? "—"

        : (
            unit.t2p.toFixed(3)
            +
            " ms"
        );


    document.getElementById(
        "f2-snr"
    ).textContent =

        unit.snr === null

        ? "—"

        : unit.snr.toFixed(2);


    document.getElementById(
        "f2-fs"
    ).textContent =

        unit.fs

        ? "Yes"

        : "No";


    document.getElementById(
        "f2-sst"
    ).textContent =
        unit.sst_status;


    selectionPanel.style.display =
        "block";
}


// ============================================================
// HIGHLIGHT CLICKED UNIT
// ============================================================

async function highlightUnit(
    point,
    unit
) {

    const ringTrace = {

        x: [
            point.x
        ],

        y: [
            point.y
        ],

        type:
            "scatter",

        mode:
            "markers",

        marker: {

            size:
                14,

            color:
                "rgba(255,255,255,0)",

            line: {

                color:
                    "#111111",

                width:
                    2.2,
            },
        },

        hoverinfo:
            "skip",

        showlegend:
            false,
    };


    /*
     * Keep only the two original traces:
     * background + selected population.
     *
     * This prevents repeated clicks from
     * accumulating selection rings.
     */

    while (
        graph.data.length > 2
    ) {

        await Plotly.deleteTraces(
            graph,
            graph.data.length - 1
        );
    }


    await Plotly.addTraces(
        graph,
        ringTrace
    );


    updateSelectedUnit(
        unit
    );
}


// ============================================================
// INITIALIZE
// ============================================================

async function initializeFigure2() {


    await renderPlot();


    // --------------------------------------------------------
    // Area selector
    // --------------------------------------------------------

    areaSelect.addEventListener(

        "change",

        async function() {

            currentGroup =
                this.value;


            await renderPlot();
        }
    );


    // --------------------------------------------------------
    // Population selector
    // --------------------------------------------------------

    populationSelect.addEventListener(

        "change",

        async function() {

            currentPopulation =
                this.value;


            await renderPlot();
        }
    );


    // --------------------------------------------------------
    // Unit click
    // --------------------------------------------------------

    graph.on(

        "plotly_click",

        async function(eventData) {


            if (
                !eventData
                ||
                !eventData.points
                ||
                eventData.points.length
                === 0
            ) {

                return;
            }


            const point =
                eventData.points[0];


            if (
                !point.customdata
                ||
                point.customdata.length
                < 1
            ) {

                return;
            }


            const rowIndex =
                String(
                    point.customdata[
                        0
                    ]
                );


            const unit =
                UNITS[
                    rowIndex
                ];


            if (!unit) {

                return;
            }


            await highlightUnit(
                point,
                unit
            );
        }
    );


    // --------------------------------------------------------
    // Responsive resize
    // --------------------------------------------------------

    window.addEventListener(

        "resize",

        function() {

            if (
                graph
                &&
                graph.data
            ) {

                Plotly.Plots.resize(
                    graph
                );
            }
        }
    );
}


initializeFigure2();


</script>


</body>

</html>
"""


# ============================================================
# 12. INSERT DATA
#
# No f-string parsing.
# ============================================================

html_fig2 = HTML_TEMPLATE_FIG2


html_fig2 = html_fig2.replace("__AREA_OPTIONS__", area_options_fig2)


html_fig2 = html_fig2.replace("__POPULATION_OPTIONS__", population_options_fig2)


html_fig2 = html_fig2.replace("__AREA_JSON__", json.dumps(area_payload, separators=(",", ":")))


html_fig2 = html_fig2.replace("__UNIT_JSON__", json.dumps(unit_payload_fig2, separators=(",", ":")))


html_fig2 = html_fig2.replace(
    "__SUMMARY_JSON__", json.dumps(summary_payload_fig2, separators=(",", ":"))
)


html_fig2 = html_fig2.replace("__POPULATION_JSON__", json.dumps(POPULATIONS, separators=(",", ":")))


html_fig2 = html_fig2.replace(
    "__GROUP_NAMES_JSON__", json.dumps(GROUP_NAMES_FIG2, separators=(",", ":"))
)


html_fig2 = html_fig2.replace("__DEFAULT_GROUP_JSON__", json.dumps(GROUP_ORDER_FIG2[0]))


# ============================================================
# 13. VALIDATION
# ============================================================

required_placeholders_fig2 = [
    "__AREA_OPTIONS__",
    "__POPULATION_OPTIONS__",
    "__AREA_JSON__",
    "__UNIT_JSON__",
    "__SUMMARY_JSON__",
    "__POPULATION_JSON__",
    "__GROUP_NAMES_JSON__",
    "__DEFAULT_GROUP_JSON__",
]


remaining_fig2 = [token for token in required_placeholders_fig2 if token in html_fig2]


if remaining_fig2:
    raise RuntimeError("Unresolved Figure 2 placeholders: " + str(remaining_fig2))


if "plotly_click" not in html_fig2:
    raise RuntimeError("Figure 2 click callback missing.")


if "sst_fs_overlap" not in map_df.columns:
    raise RuntimeError("Overlap classification missing.")


# ============================================================
# 14. SAVE
# ============================================================

FIG2_HTML.write_text(html_fig2, encoding="utf-8")


# ============================================================
# 15. SUMMARY CHECK
# ============================================================

print()
print("=" * 72)

print("FINAL PUBLICATION INTERACTIVE FIGURE 2 EXPORTED")

print("=" * 72)

print()

print(FIG2_HTML)

print()

print("Areas: " + ", ".join(GROUP_ORDER_FIG2))

print()

print("Population views:")

print("  • Putative FS/PV-like")

print("  • Optotagged SST")

print("  • SST ∩ putative FS")

print()

print("FS criterion: T→P < 0.40 ms AND FR ≥ 10 Hz")

print("PV optotagging: NONE")

print("SST status distinguishes tested negative from not tested: YES")

print("Overlap denominator = optotagged SST: YES")

print("Plotly legend removed: YES")

print("Responsive layout: YES")

print()


# ============================================================
# 16. NOTEBOOK CONFIRMATION
# ============================================================

display(
    HTML(
        """
        <div style="
            margin:14px 0;
            padding:14px 16px;
            border:1px solid #dddddd;
            border-radius:4px;
            background:white;
            font-family:Arial,Helvetica,sans-serif;
        ">

            <div style="
                font-size:14px;
                font-weight:600;
                margin-bottom:5px;
            ">
                ✓ Final FS/SST interactive figure exported
            </div>

            <div style="
                font-size:12px;
                color:#666666;
                line-height:1.5;
            ">
                Select an anatomical group and population.
                Highlighted units use the same blue, magenta
                and orange encoding as the original static
                analysis. Hover or click individual units for
                classification and electrophysiological metadata.
            </div>

        </div>
        """
    )
)

# ============================================================
# FINAL INTERACTIVE FIGURE 3 — PUBLICATION VERSION
#
# WaveMAP population composition across predictive contexts
#
# EXACT existing notebook objects used:
#   region_context_summary["mean_percent"]
#   enrich_df["log2_enrichment"]
#
# NO WaveMAP, context, normalization, or enrichment calculations
# are recomputed here.
#
# Interactive controls:
#   • anatomical group
#   • absolute composition / enrichment-depletion
#   • hover for exact values
#   • click a cell for a clean numerical summary
#
# Publication layout:
#   • controls outside plotting area
#   • no legend
#   • no internal Plotly title
#   • dedicated colour-bar space
#   • fixed shared colour scales across anatomical groups
#   • responsive sizing
# ============================================================


# ============================================================
# 1. REQUIRED OBJECTS
# ============================================================

REQUIRED_OBJECTS = [
    "region_context_summary",
    "enrich_df",
]

missing_objects = [name for name in REQUIRED_OBJECTS if name not in globals()]

if missing_objects:
    raise RuntimeError(
        "Missing required object(s): "
        + ", ".join(missing_objects)
        + "\nRun the existing Section 4 context-analysis cells first."
    )


# Make display-only copies.
absolute_df = region_context_summary.copy()
enrichment_df = enrich_df.copy()


# ============================================================
# 2. VERIFY EXACT EXPECTED COLUMNS
# ============================================================

ABS_REQUIRED_COLUMNS = [
    "group",
    "context",
    "wavemap_local",
    "wavemap_label",
    "mean_percent",
]

ENR_REQUIRED_COLUMNS = [
    "group",
    "context",
    "wavemap_local",
    "wavemap_label",
    "log2_enrichment",
]

missing_abs_cols = [col for col in ABS_REQUIRED_COLUMNS if col not in absolute_df.columns]

missing_enr_cols = [col for col in ENR_REQUIRED_COLUMNS if col not in enrichment_df.columns]

if missing_abs_cols:
    raise RuntimeError("region_context_summary is missing: " + ", ".join(missing_abs_cols))

if missing_enr_cols:
    raise RuntimeError("enrich_df is missing: " + ", ".join(missing_enr_cols))


# ============================================================
# 3. OUTPUT LOCATION
# ============================================================

if "OUT_DIR" not in globals():
    OUT_DIR = Path.cwd()

OUT_DIR = Path(OUT_DIR)

INTERACTIVE_DIR = OUT_DIR / "interactive"
INTERACTIVE_DIR.mkdir(parents=True, exist_ok=True)

FIG3_HTML = INTERACTIVE_DIR / "wavemap-context-explorer.html"


# ============================================================
# 4. DISPLAY ORDER
# ============================================================

GROUP_NAMES_FIG3 = {
    "MO": "Motor cortex",
    "PFC": "Prefrontal cortex",
    "VIS": "Visual cortex",
    "STR": "Striatum",
    "HPC": "Hippocampus",
    "THAL": "Thalamus",
}

preferred_group_order = [
    "MO",
    "PFC",
    "VIS",
    "STR",
    "HPC",
    "THAL",
]

groups_present = set(absolute_df["group"].dropna().astype(str))

GROUP_ORDER_FIG3 = [g for g in preferred_group_order if g in groups_present]

# Preserve any unexpected group rather than silently removing it.
for g in absolute_df["group"].dropna().astype(str).unique():
    if g not in GROUP_ORDER_FIG3:
        GROUP_ORDER_FIG3.append(g)

if not GROUP_ORDER_FIG3:
    raise RuntimeError("No anatomical groups found in region_context_summary.")


# ------------------------------------------------------------
# Context order
# ------------------------------------------------------------

preferred_context_order = [
    "Standard oddball",
    "Sensorimotor mismatch",
    "Sequence mismatch",
    "Duration mismatch",
]

contexts_present = set(absolute_df["context"].dropna().astype(str))

CONTEXT_ORDER_FIG3 = [c for c in preferred_context_order if c in contexts_present]

# Preserve unexpected contexts.
for c in absolute_df["context"].dropna().astype(str).unique():
    if c not in CONTEXT_ORDER_FIG3:
        CONTEXT_ORDER_FIG3.append(c)


# Short labels used only on the x axis.
CONTEXT_SHORT_FIG3 = {
    "Standard oddball": "Standard",
    "Sensorimotor mismatch": "Sensorimotor",
    "Sequence mismatch": "Sequence",
    "Duration mismatch": "Duration",
}


# ============================================================
# 5. VERIFY UNIQUE DISPLAY VALUES
#
# We DO NOT average duplicate rows here because that could
# silently change the existing scientific calculation.
# ============================================================

abs_dupes = absolute_df.groupby(["group", "context", "wavemap_local"], dropna=False).size()

abs_dupes = abs_dupes[abs_dupes > 1]

if len(abs_dupes):
    raise RuntimeError(
        "Unexpected duplicate rows in region_context_summary.\n"
        "The interactive figure will not average them automatically.\n\n" + str(abs_dupes.head(20))
    )


enr_dupes = enrichment_df.groupby(["group", "context", "wavemap_local"], dropna=False).size()

enr_dupes = enr_dupes[enr_dupes > 1]

if len(enr_dupes):
    raise RuntimeError(
        "Unexpected duplicate rows in enrich_df.\n"
        "The interactive figure will not average them automatically.\n\n" + str(enr_dupes.head(20))
    )


# ============================================================
# 6. SHARED PUBLICATION COLOUR SCALES
#
# Reproduce the logic used in the existing notebook figures.
#
# ABSOLUTE:
#   97.5th percentile
#   rounded upward to nearest 5
#   minimum 5 %
#
# ENRICHMENT:
#   symmetric 97.5th percentile of |log2 enrichment|
#   minimum 0.5
#   maximum 2.0
#   rounded upward to nearest 0.25
# ============================================================

# ------------------------------------------------------------
# Absolute composition
# ------------------------------------------------------------

absolute_values = pd.to_numeric(absolute_df["mean_percent"], errors="coerce").to_numpy()

absolute_values = absolute_values[np.isfinite(absolute_values)]

if len(absolute_values) == 0:
    raise RuntimeError("No finite mean_percent values found.")

ABS_ZMIN = 0.0

ABS_ZMAX = float(np.nanpercentile(absolute_values, 97.5))

ABS_ZMAX = max(5.0, np.ceil(ABS_ZMAX / 5.0) * 5.0)


# ------------------------------------------------------------
# Enrichment
# ------------------------------------------------------------

enrichment_values = pd.to_numeric(enrichment_df["log2_enrichment"], errors="coerce").to_numpy()

enrichment_values = enrichment_values[np.isfinite(enrichment_values)]

if len(enrichment_values) == 0:
    raise RuntimeError("No finite log2_enrichment values found.")

ENR_LIM = float(np.nanpercentile(np.abs(enrichment_values), 97.5))

ENR_LIM = max(0.5, ENR_LIM)

ENR_LIM = min(ENR_LIM, 2.0)

ENR_LIM = np.ceil(ENR_LIM / 0.25) * 0.25


# ============================================================
# 7. BUILD DISPLAY PAYLOAD
#
# Pivoting is only for presentation.
# Values come directly from the existing summary tables.
# ============================================================

FIGURE_PAYLOAD = {}


def clean_local_class(value):
    """
    Convert WaveMAP local class to an integer where possible.
    """
    try:
        number = float(value)

        if np.isfinite(number) and number.is_integer():
            return int(number)

    except Exception:
        pass

    return str(value)


def class_sort_key(value):
    """
    Numeric WaveMAP classes first, then any unexpected labels.
    """
    try:
        return (0, int(value))
    except Exception:
        return (1, str(value))


for group in GROUP_ORDER_FIG3:
    abs_sub = absolute_df[absolute_df["group"].astype(str) == group].copy()

    enr_sub = enrichment_df[enrichment_df["group"].astype(str) == group].copy()

    if len(abs_sub) == 0:
        continue

    # --------------------------------------------------------
    # Local class order
    # --------------------------------------------------------

    local_classes = [clean_local_class(x) for x in abs_sub["wavemap_local"].dropna().unique()]

    local_classes = sorted(list(dict.fromkeys(local_classes)), key=class_sort_key)

    if not local_classes:
        continue

    class_labels = [f"{group}-{x}" for x in local_classes]

    # --------------------------------------------------------
    # Lookups
    # --------------------------------------------------------

    abs_lookup = {}

    for _, row in abs_sub.iterrows():
        local_class = clean_local_class(row["wavemap_local"])

        context = str(row["context"])

        value = pd.to_numeric(pd.Series([row["mean_percent"]]), errors="coerce").iloc[0]

        abs_lookup[(local_class, context)] = float(value) if pd.notna(value) else None

    enr_lookup = {}

    for _, row in enr_sub.iterrows():
        local_class = clean_local_class(row["wavemap_local"])

        context = str(row["context"])

        value = pd.to_numeric(pd.Series([row["log2_enrichment"]]), errors="coerce").iloc[0]

        enr_lookup[(local_class, context)] = float(value) if pd.notna(value) else None

    # --------------------------------------------------------
    # Matrices
    # --------------------------------------------------------

    absolute_matrix = []

    enrichment_matrix = []

    for local_class in local_classes:
        abs_row = []
        enr_row = []

        for context in CONTEXT_ORDER_FIG3:
            abs_row.append(abs_lookup.get((local_class, context), None))

            enr_row.append(enr_lookup.get((local_class, context), None))

        absolute_matrix.append(abs_row)

        enrichment_matrix.append(enr_row)

    # --------------------------------------------------------
    # Region metadata
    # --------------------------------------------------------

    if (
        "region_session_prop" in globals()
        and isinstance(region_session_prop, pd.DataFrame)
        and "group" in region_session_prop.columns
    ):
        rsp = region_session_prop[region_session_prop["group"].astype(str) == group]

        if "session_key" in rsp.columns:
            n_sessions = int(rsp["session_key"].nunique())
        else:
            n_sessions = None

    else:
        if "n_sessions" in abs_sub.columns:
            n_sessions = int(pd.to_numeric(abs_sub["n_sessions"], errors="coerce").max())
        else:
            n_sessions = None

    FIGURE_PAYLOAD[group] = {
        "name": GROUP_NAMES_FIG3.get(group, group),
        "classes": class_labels,
        "contexts": CONTEXT_ORDER_FIG3,
        "contextShort": [CONTEXT_SHORT_FIG3.get(c, c) for c in CONTEXT_ORDER_FIG3],
        "absolute": absolute_matrix,
        "enrichment": enrichment_matrix,
        "nClasses": len(class_labels),
        "nSessions": n_sessions,
    }


GROUP_ORDER_FIG3 = [g for g in GROUP_ORDER_FIG3 if g in FIGURE_PAYLOAD]

if not GROUP_ORDER_FIG3:
    raise RuntimeError("No displayable anatomical groups were constructed.")


# ============================================================
# 8. HTML AREA OPTIONS
# ============================================================

AREA_OPTIONS = "".join(
    f'<option value="{group}">{GROUP_NAMES_FIG3.get(group, group)}</option>'
    for group in GROUP_ORDER_FIG3
)


# ============================================================
# 9. PUBLICATION HTML
#
# IMPORTANT:
# Plain raw triple-quoted string — NOT an f-string.
# Therefore JavaScript/CSS braces do not need escaping.
# ============================================================

HTML_TEMPLATE = r"""
<!doctype html>

<html lang="en">

<head>

<meta charset="utf-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1"
>

<title>
WaveMAP populations across predictive contexts
</title>

<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>


<style>

* {
    box-sizing: border-box;
}

html,
body {
    margin: 0;
    padding: 0;
    width: 100%;
    background: #ffffff;
    color: #222222;
    font-family: Arial, Helvetica, sans-serif;
}

body {
    overflow-x: hidden;
}

#app {
    width: 100%;
    max-width: 1180px;
    margin: 0 auto;
    padding: 26px 32px 30px 32px;
}


/* ==========================================================
   HEADER
   ========================================================== */

.header {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 215px;
    gap: 32px;
    align-items: end;

    width: 100%;

    padding-bottom: 17px;

    border-bottom: 1px solid #e8e8e8;
}

.header-copy {
    min-width: 0;
}

.header h1 {
    margin: 0 0 6px 0;

    font-size: 20px;
    font-weight: 600;
    line-height: 1.25;

    color: #222222;
}

.header p {
    margin: 0;

    max-width: 760px;

    font-size: 12.5px;
    line-height: 1.5;

    color: #666666;
}


/* ==========================================================
   AREA SELECTOR
   ========================================================== */

.control {
    width: 100%;
}

.control-label {
    display: block;

    margin: 0 0 7px 0;

    font-size: 9.5px;
    font-weight: 600;

    letter-spacing: 0.065em;

    color: #666666;
}

select {
    display: block;

    width: 100%;
    height: 39px;

    margin: 0;

    padding: 0 34px 0 11px;

    border: 1px solid #bdbdbd;
    border-radius: 3px;

    background: #ffffff;

    color: #222222;

    font-family: Arial, Helvetica, sans-serif;
    font-size: 12.5px;

    cursor: pointer;
}


/* ==========================================================
   VIEW CONTROLS
   ========================================================== */

.toolbar {
    display: grid;

    grid-template-columns: auto minmax(0, 1fr);

    align-items: center;

    gap: 26px;

    width: 100%;

    min-height: 62px;

    padding: 13px 0;

    border-bottom: 1px solid #eeeeee;
}

.segmented {
    display: inline-flex;

    align-items: center;

    padding: 3px;

    background: #f3f3f3;

    border-radius: 4px;
}

.segment-button {
    display: block;

    height: 34px;

    padding: 0 15px;

    border: 0;
    border-radius: 3px;

    background: transparent;

    color: #666666;

    font-family: Arial, Helvetica, sans-serif;
    font-size: 11.5px;
    font-weight: 400;

    white-space: nowrap;

    cursor: pointer;
}

.segment-button.active {
    background: #ffffff;

    color: #222222;

    font-weight: 600;

    box-shadow:
        0 1px 3px rgba(0, 0, 0, 0.13);
}

.toolbar-description {
    min-width: 0;

    margin: 0;

    text-align: right;

    font-size: 11px;
    line-height: 1.45;

    color: #666666;
}


/* ==========================================================
   REGION INFORMATION
   ========================================================== */

.region-line {
    display: flex;

    align-items: baseline;

    justify-content: space-between;

    gap: 20px;

    width: 100%;

    padding: 19px 0 4px 0;
}

#region-name {
    margin: 0;

    font-size: 15px;
    font-weight: 600;

    color: #222222;
}

#region-meta {
    margin: 0;

    font-size: 10.5px;

    color: #777777;

    white-space: nowrap;
}


/* ==========================================================
   PLOT
   ========================================================== */

.plot-wrap {
    position: relative;

    width: 100%;

    min-width: 0;

    margin: 0;

    overflow: visible;
}

#plot {
    width: 100%;

    min-width: 0;

    height: 590px;
}


/* ==========================================================
   CLICKED CELL PANEL
   ========================================================== */

#selection {
    display: none;

    width: 100%;

    margin: 10px 0 0 0;

    padding: 14px 17px;

    background: #fafafa;

    border: 1px solid #e8e8e8;
    border-radius: 3px;
}

.selection-grid {
    display: grid;

    grid-template-columns:
        0.85fr
        1.45fr
        0.85fr
        2.25fr;

    gap: 25px;

    align-items: start;
}

.selection-block {
    min-width: 0;
}

.selection-label {
    display: block;

    margin: 0 0 5px 0;

    font-size: 8.5px;
    font-weight: 600;

    letter-spacing: 0.06em;

    color: #777777;
}

.selection-value {
    display: block;

    margin: 0;

    font-size: 11.5px;
    line-height: 1.4;

    color: #222222;

    overflow-wrap: anywhere;
}

.selection-value.main {
    font-size: 16px;
    font-weight: 600;
}


/* ==========================================================
   FOOTNOTE
   ========================================================== */

.note {
    width: 100%;

    margin: 17px 0 0 0;

    padding: 12px 0 0 0;

    border-top: 1px solid #eeeeee;

    font-size: 10px;
    line-height: 1.55;

    color: #707070;
}


/* ==========================================================
   MOBILE
   ========================================================== */

@media (max-width: 760px) {

    #app {
        padding: 20px 16px 24px 16px;
    }

    .header {
        grid-template-columns: 1fr;

        gap: 18px;
    }

    .toolbar {
        grid-template-columns: 1fr;

        gap: 10px;
    }

    .toolbar-description {
        text-align: left;
    }

    .region-line {
        align-items: flex-start;

        flex-direction: column;

        gap: 4px;
    }

    .selection-grid {
        grid-template-columns: 1fr 1fr;

        gap: 16px;
    }

    #plot {
        height: 560px;
    }
}

</style>

</head>


<body>


<div id="app">


    <!-- =====================================================
         HEADER
         ===================================================== -->

    <div class="header">


        <div class="header-copy">

            <h1>
                WaveMAP populations across predictive contexts
            </h1>

            <p>
                Session-normalized composition of local waveform
                populations across predictive-processing contexts.
            </p>

        </div>


        <div class="control">

            <label
                class="control-label"
                for="area-select"
            >
                ANATOMICAL GROUP
            </label>

            <select id="area-select">
                @@AREA_OPTIONS@@
            </select>

        </div>


    </div>


    <!-- =====================================================
         VIEW SWITCH
         ===================================================== -->

    <div class="toolbar">


        <div class="segmented">

            <button
                id="absolute-button"
                class="segment-button active"
                type="button"
            >
                Absolute composition
            </button>

            <button
                id="enrichment-button"
                class="segment-button"
                type="button"
            >
                Enrichment / depletion
            </button>

        </div>


        <p
            class="toolbar-description"
            id="toolbar-description"
        >
            Mean within-session class proportion, averaged across sessions.
        </p>


    </div>


    <!-- =====================================================
         REGION LABEL
         ===================================================== -->

    <div class="region-line">

        <p id="region-name">
            —
        </p>

        <p id="region-meta">
            —
        </p>

    </div>


    <!-- =====================================================
         HEATMAP
         ===================================================== -->

    <div class="plot-wrap">

        <div id="plot"></div>

    </div>


    <!-- =====================================================
         CLICKED CELL INFORMATION
         ===================================================== -->

    <div id="selection">

        <div class="selection-grid">


            <div class="selection-block">

                <span class="selection-label">
                    WAVEMAP CLASS
                </span>

                <span
                    class="selection-value"
                    id="selected-class"
                >
                    —
                </span>

            </div>


            <div class="selection-block">

                <span class="selection-label">
                    PREDICTIVE CONTEXT
                </span>

                <span
                    class="selection-value"
                    id="selected-context"
                >
                    —
                </span>

            </div>


            <div class="selection-block">

                <span class="selection-label">
                    VALUE
                </span>

                <span
                    class="selection-value main"
                    id="selected-value"
                >
                    —
                </span>

            </div>


            <div class="selection-block">

                <span class="selection-label">
                    INTERPRETATION
                </span>

                <span
                    class="selection-value"
                    id="selected-interpretation"
                >
                    —
                </span>

            </div>


        </div>

    </div>


    <!-- =====================================================
         NOTE
         ===================================================== -->

    <div class="note">

        Values are normalized within recording session before
        averaging across sessions. WaveMAP was fitted independently
        within each anatomical group; class labels therefore denote
        local waveform populations within the selected region.

    </div>


</div>


<script>

// ============================================================
// DATA
// ============================================================

const DATA =
    @@DATA_JSON@@;

const GROUP_ORDER =
    @@GROUP_ORDER_JSON@@;

const ABS_ZMIN =
    @@ABS_ZMIN_JSON@@;

const ABS_ZMAX =
    @@ABS_ZMAX_JSON@@;

const ENR_LIM =
    @@ENR_LIM_JSON@@;


// ============================================================
// DOM
// ============================================================

const graph =
    document.getElementById("plot");

const areaSelect =
    document.getElementById("area-select");

const absoluteButton =
    document.getElementById("absolute-button");

const enrichmentButton =
    document.getElementById("enrichment-button");

const toolbarDescription =
    document.getElementById("toolbar-description");

const regionName =
    document.getElementById("region-name");

const regionMeta =
    document.getElementById("region-meta");

const selection =
    document.getElementById("selection");


// ============================================================
// STATE
// ============================================================

let currentGroup =
    GROUP_ORDER[0];

let currentView =
    "absolute";


// ============================================================
// FORMATTERS
// ============================================================

function formatAbsolute(value) {

    if (
        value === null ||
        value === undefined ||
        !Number.isFinite(Number(value))
    ) {
        return "—";
    }

    return Number(value).toFixed(2) + "%";
}


function formatEnrichment(value) {

    if (
        value === null ||
        value === undefined ||
        !Number.isFinite(Number(value))
    ) {
        return "—";
    }

    const number =
        Number(value);

    const sign =
        number > 0
        ? "+"
        : "";

    return sign + number.toFixed(2);
}


// ============================================================
// CONTROLS
// ============================================================

function updateControls() {

    if (currentView === "absolute") {

        absoluteButton.classList.add(
            "active"
        );

        enrichmentButton.classList.remove(
            "active"
        );

        toolbarDescription.textContent =
            "Mean within-session class proportion, averaged across sessions.";

    } else {

        enrichmentButton.classList.add(
            "active"
        );

        absoluteButton.classList.remove(
            "active"
        );

        toolbarDescription.textContent =
            "log₂ enrichment relative to each class's regional baseline abundance.";
    }
}


// ============================================================
// REGION HEADER
// ============================================================

function updateRegionHeader() {

    const area =
        DATA[currentGroup];

    regionName.textContent =
        area.name;

    let meta =
        area.nClasses
        + (
            area.nClasses === 1
            ? " local class"
            : " local classes"
        );

    if (
        area.nSessions !== null &&
        area.nSessions !== undefined
    ) {

        meta +=
            " · "
            + area.nSessions
            + (
                area.nSessions === 1
                ? " session"
                : " sessions"
            );
    }

    regionMeta.textContent =
        meta;
}


// ============================================================
// BUILD CUSTOM DATA
// ============================================================

function buildCustomData(
    area,
    z
) {

    const output = [];

    for (
        let r = 0;
        r < area.classes.length;
        r++
    ) {

        const row = [];

        for (
            let c = 0;
            c < area.contexts.length;
            c++
        ) {

            row.push([
                area.classes[r],
                area.contexts[c],
                z[r][c]
            ]);
        }

        output.push(row);
    }

    return output;
}


// ============================================================
// DYNAMIC HEIGHT
//
// Enough vertical room for every class while preventing the
// plot from becoming unnecessarily tall.
// ============================================================

function calculateHeight(
    nClasses
) {

    return Math.max(
        500,
        Math.min(
            790,
            235 + nClasses * 32
        )
    );
}


// ============================================================
// RENDER
// ============================================================

async function renderFigure() {

    updateControls();
    updateRegionHeader();

    selection.style.display =
        "none";

    const area =
        DATA[currentGroup];

    const isAbsolute =
        currentView === "absolute";

    const z =
        isAbsolute
        ? area.absolute
        : area.enrichment;

    const customdata =
        buildCustomData(
            area,
            z
        );

    const dynamicHeight =
        calculateHeight(
            area.classes.length
        );

    graph.style.height =
        dynamicHeight + "px";


    // --------------------------------------------------------
    // Heatmap trace
    // --------------------------------------------------------

    const trace = {

        type:
            "heatmap",

        x:
            area.contextShort,

        y:
            area.classes,

        z:
            z,

        customdata:
            customdata,

        xgap:
            1,

        ygap:
            1,

        hoverongaps:
            false,

        showscale:
            true,


        colorbar: {

            x:
                1.025,

            xanchor:
                "left",

            y:
                0.50,

            yanchor:
                "middle",

            len:
                0.76,

            thickness:
                14,

            outlinewidth:
                0,

            tickfont: {
                size: 10,
                color: "#555555"
            },

            title: {

                text:
                    isAbsolute
                    ? "Mean proportion (%)"
                    : "log₂ enrichment",

                side:
                    "right",

                font: {
                    size: 10.5,
                    color: "#444444"
                }
            }
        }
    };


    // --------------------------------------------------------
    // Absolute appearance
    // --------------------------------------------------------

    if (isAbsolute) {

        trace.colorscale =
            "Viridis";

        trace.zmin =
            ABS_ZMIN;

        trace.zmax =
            ABS_ZMAX;

        trace.hovertemplate =
            "<b>%{customdata[0]}</b>"
            + "<br>%{customdata[1]}"
            + "<br>Mean proportion: %{z:.2f}%"
            + "<extra></extra>";

    }

    // --------------------------------------------------------
    // Enrichment appearance
    // --------------------------------------------------------

    else {

        // Plotly RdBu is reversed relative to the notebook's
        // matplotlib RdBu_r, so reversescale = true reproduces
        // blue depletion / white baseline / red enrichment.
        trace.colorscale =
            "RdBu";

        trace.reversescale =
            true;

        trace.zmin =
            -ENR_LIM;

        trace.zmax =
            ENR_LIM;

        trace.zmid =
            0;

        trace.hovertemplate =
            "<b>%{customdata[0]}</b>"
            + "<br>%{customdata[1]}"
            + "<br>log₂ enrichment: %{z:+.2f}"
            + "<extra></extra>";
    }


    // --------------------------------------------------------
    // Layout
    //
    // There is deliberately NO Plotly title.
    // All title/header elements are outside the graph so they
    // cannot overlap the axes or colour bar.
    // --------------------------------------------------------

    const layout = {

        template:
            "plotly_white",

        autosize:
            true,

        height:
            dynamicHeight,

        margin: {
            l: 118,
            r: 145,
            t: 26,
            b: 105
        },

        paper_bgcolor:
            "#ffffff",

        plot_bgcolor:
            "#ffffff",

        font: {
            family:
                "Arial, Helvetica, sans-serif",
            size: 11,
            color: "#222222"
        },


        // ----------------------------------------------------
        // X axis
        // ----------------------------------------------------

        xaxis: {

            title: {
                text:
                    "Predictive context",
                font: {
                    size: 11,
                    color: "#333333"
                },
                standoff: 22
            },

            tickfont: {
                size: 10.5,
                color: "#333333"
            },

            tickangle:
                -24,

            side:
                "bottom",

            showgrid:
                false,

            zeroline:
                false,

            showline:
                false,

            ticks:
                "",

            automargin:
                true,

            fixedrange:
                true
        },


        // ----------------------------------------------------
        // Y axis
        // ----------------------------------------------------

        yaxis: {

            title: {
                text:
                    "Local WaveMAP class",
                font: {
                    size: 11,
                    color: "#333333"
                },
                standoff: 20
            },

            tickfont: {
                size: 10.5,
                color: "#333333"
            },

            autorange:
                "reversed",

            showgrid:
                false,

            zeroline:
                false,

            showline:
                false,

            ticks:
                "",

            automargin:
                true,

            fixedrange:
                true
        },


        hoverlabel: {

            bgcolor:
                "#ffffff",

            bordercolor:
                "#bdbdbd",

            font: {
                family:
                    "Arial, Helvetica, sans-serif",
                size: 11,
                color: "#222222"
            }
        }
    };


    // --------------------------------------------------------
    // Plotly controls
    // --------------------------------------------------------

    const config = {

        responsive:
            true,

        displaylogo:
            false,

        scrollZoom:
            false,

        doubleClick:
            false,

        modeBarButtonsToRemove: [
            "zoom2d",
            "pan2d",
            "select2d",
            "lasso2d",
            "zoomIn2d",
            "zoomOut2d",
            "autoScale2d",
            "resetScale2d"
        ],

        toImageButtonOptions: {

            format:
                "svg",

            filename:
                (
                    "wavemap_context_"
                    + currentGroup.toLowerCase()
                    + "_"
                    + currentView
                ),

            scale:
                1
        }
    };


    await Plotly.react(
        graph,
        [trace],
        layout,
        config
    );
}


// ============================================================
// CLICKED CELL
// ============================================================

function showSelectedCell(
    point
) {

    if (
        !point ||
        !point.customdata
    ) {
        return;
    }

    const classLabel =
        point.customdata[0];

    const context =
        point.customdata[1];

    const value =
        point.customdata[2];


    document.getElementById(
        "selected-class"
    ).textContent =
        classLabel;


    document.getElementById(
        "selected-context"
    ).textContent =
        context;


    // --------------------------------------------------------
    // Absolute
    // --------------------------------------------------------

    if (currentView === "absolute") {

        document.getElementById(
            "selected-value"
        ).textContent =
            formatAbsolute(value);

        document.getElementById(
            "selected-interpretation"
        ).textContent =
            (
                value === null ||
                value === undefined
            )
            ? "No value available."
            : (
                "Mean within-session abundance of this "
                + "local class in the selected context."
            );
    }


    // --------------------------------------------------------
    // Enrichment
    // --------------------------------------------------------

    else {

        document.getElementById(
            "selected-value"
        ).textContent =
            formatEnrichment(value);

        let interpretation =
            "No value available.";

        if (
            value !== null &&
            value !== undefined &&
            Number.isFinite(Number(value))
        ) {

            const numeric =
                Number(value);

            if (Math.abs(numeric) < 1e-12) {

                interpretation =
                    "At the regional class baseline.";

            } else if (numeric > 0) {

                interpretation =
                    "Enriched relative to this class's regional baseline.";

            } else {

                interpretation =
                    "Depleted relative to this class's regional baseline.";
            }
        }

        document.getElementById(
            "selected-interpretation"
        ).textContent =
            interpretation;
    }


    selection.style.display =
        "block";
}


// ============================================================
// INITIALIZATION
// ============================================================

async function initialize() {

    areaSelect.value =
        currentGroup;


    // --------------------------------------------------------
    // Initial plot
    // --------------------------------------------------------

    await renderFigure();


    // --------------------------------------------------------
    // Area selector
    // --------------------------------------------------------

    areaSelect.addEventListener(
        "change",
        async function() {

            currentGroup =
                this.value;

            await renderFigure();
        }
    );


    // --------------------------------------------------------
    // Absolute composition
    // --------------------------------------------------------

    absoluteButton.addEventListener(
        "click",
        async function() {

            if (
                currentView === "absolute"
            ) {
                return;
            }

            currentView =
                "absolute";

            await renderFigure();
        }
    );


    // --------------------------------------------------------
    // Enrichment
    // --------------------------------------------------------

    enrichmentButton.addEventListener(
        "click",
        async function() {

            if (
                currentView === "enrichment"
            ) {
                return;
            }

            currentView =
                "enrichment";

            await renderFigure();
        }
    );


    // --------------------------------------------------------
    // Heatmap click
    // --------------------------------------------------------

    graph.on(
        "plotly_click",
        function(eventData) {

            if (
                !eventData ||
                !eventData.points ||
                eventData.points.length === 0
            ) {
                return;
            }

            showSelectedCell(
                eventData.points[0]
            );
        }
    );


    // --------------------------------------------------------
    // Responsive resize
    // --------------------------------------------------------

    window.addEventListener(
        "resize",
        function() {

            if (
                graph &&
                graph.data
            ) {
                Plotly.Plots.resize(
                    graph
                );
            }
        }
    );
}


initialize();

</script>


</body>

</html>
"""


# ============================================================
# 10. INSERT SERIALIZED DATA
#
# Explicit placeholder replacement avoids Python f-string /
# JavaScript brace problems.
# ============================================================

html = HTML_TEMPLATE

html = html.replace("@@AREA_OPTIONS@@", AREA_OPTIONS)

html = html.replace(
    "@@DATA_JSON@@", json.dumps(FIGURE_PAYLOAD, separators=(",", ":"), allow_nan=False)
)

html = html.replace("@@GROUP_ORDER_JSON@@", json.dumps(GROUP_ORDER_FIG3, separators=(",", ":")))

html = html.replace("@@ABS_ZMIN_JSON@@", json.dumps(float(ABS_ZMIN)))

html = html.replace("@@ABS_ZMAX_JSON@@", json.dumps(float(ABS_ZMAX)))

html = html.replace("@@ENR_LIM_JSON@@", json.dumps(float(ENR_LIM)))


# ============================================================
# 11. VERIFY ALL PLACEHOLDERS WERE REPLACED
# ============================================================

placeholders = [
    "@@AREA_OPTIONS@@",
    "@@DATA_JSON@@",
    "@@GROUP_ORDER_JSON@@",
    "@@ABS_ZMIN_JSON@@",
    "@@ABS_ZMAX_JSON@@",
    "@@ENR_LIM_JSON@@",
]

remaining = [token for token in placeholders if token in html]

if remaining:
    raise RuntimeError("Unresolved HTML placeholders: " + ", ".join(remaining))


# ============================================================
# 12. SAVE HTML
# ============================================================

FIG3_HTML.write_text(html, encoding="utf-8")


# ============================================================
# 13. FINAL VALIDATION SUMMARY
# ============================================================

print()
print("=" * 76)
print("FIGURE 3 — FINAL PUBLICATION INTERACTIVE EXPORTED")
print("=" * 76)
print()

print("File:", FIG3_HTML)

print()

print("Absolute source: region_context_summary['mean_percent']")

print("Enrichment source: enrich_df['log2_enrichment']")

print()

print(f"Shared absolute colour scale: {ABS_ZMIN:.0f} to {ABS_ZMAX:.0f}%")

print(f"Shared enrichment colour scale: {-ENR_LIM:.2f} to +{ENR_LIM:.2f}")

print()

print("Anatomical groups:", ", ".join(GROUP_ORDER_FIG3))

print("Predictive contexts:", ", ".join(CONTEXT_ORDER_FIG3))

print()

print("Scientific values recomputed: NO")
print("Session normalization changed: NO")
print("Enrichment calculation changed: NO")
print("Shared cross-region scales preserved: YES")
print("Plot legend: NONE")
print("Controls outside plotting area: YES")
print("Colour bar allocated separate space: YES")
print("Responsive layout: YES")
print()


# ============================================================
# 14. NOTEBOOK CONFIRMATION
# ============================================================

display(
    HTML(
        """
        <div style="
            margin:14px 0;
            padding:14px 16px;
            border:1px solid #dddddd;
            border-radius:4px;
            background:#ffffff;
            font-family:Arial,Helvetica,sans-serif;
        ">

            <div style="
                margin-bottom:5px;
                font-size:14px;
                font-weight:600;
                color:#222222;
            ">
                ✓ Figure 3 exported
            </div>

            <div style="
                font-size:12px;
                line-height:1.5;
                color:#666666;
            ">
                Area selector + absolute/enrichment switch +
                exact-value hover/click interaction. The heatmap,
                labels, colour bar, controls and metadata occupy
                separate layout regions to prevent overlap.
            </div>

        </div>
        """
    )
)
# ---------------------------------------------------------------------------
# Copy ONLY the three approved static counterparts and three interactive HTMLs.
# ---------------------------------------------------------------------------
_outputs = {
    OUT_DIR / "interactive" / "wavemap-area-explorer.html": FINAL_INTERACTIVE_DIR
    / "wavemap-area-explorer.html",
    OUT_DIR / "interactive" / "fs-sst-wavemap-explorer.html": FINAL_INTERACTIVE_DIR
    / "fs-sst-wavemap-explorer.html",
    OUT_DIR / "interactive" / "wavemap-context-explorer.html": FINAL_INTERACTIVE_DIR
    / "wavemap-context-explorer.html",
}
for src, dst in _outputs.items():
    if not src.exists():
        raise RuntimeError(f"Expected figure output was not generated: {src}")
    shutil.copy2(src, dst)
    print(f"Published: {dst.relative_to(REPO_ROOT)}")
