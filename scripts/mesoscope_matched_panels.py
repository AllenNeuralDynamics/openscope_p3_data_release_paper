"""Render the mesoscope column of the unit-extraction figure (panels B, F, J).

Mirrors the SLAP2-glutamate column (panels C, G, K) of PR #171 in
AllenNeuralDynamics/openscope-community-predictive-processing, so the two
columns read as row-matched siblings: same class ramp, same event-amplitude
bin greys, same single-orange example accent, same left-aligned titles and
n-carrying legends.

Row semantics come from the shared grid (figure07_panel_letters.csv):
    row 1  B  example imagery, one source, trace + events
    row 2  F  how signal and noise are measured, class definitions
    row 3  J  distribution of classes across context / anatomy / sessions


Run outside the repo build (see build_mesoscope_unit_extraction_panels.py):
reads the committed per-ROI cohort table figure_sources/data/
mesoscope-unit-extraction-roi-metrics.csv.gz and needs only numpy, pandas
and matplotlib.
"""
from __future__ import annotations

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch

# Design tokens copied from slap2_glutamate_figure7_panels.py so the columns match.
# Same construction as the SLAP2 column -- a single-hue sequential ramp, light to
# dark across Low/Intermediate/High -- in a different hue, so the two columns are
# never mistaken for the same encoding. Purple rather than green keeps the orange
# example accent unambiguous for red-green colour-blind readers.
CLASS_COLORS = {"Low SNR": "#bcbddc", "Intermediate": "#6a51a3", "High SNR": "#3f007d"}
CLASS_ORDER = ["Low SNR", "Intermediate", "High SNR"]
BIN_GREYS = {"lt2": "#c6c5c0", "mid": "#8b8a86", "gt4": "#2e2d2b"}
BIN_LABELS = {"lt2": "< 2 SD", "mid": "2\u20134 SD", "gt4": "> 4 SD"}
INK, INK_2, MUTED = "#0b0b0b", "#52514e", "#8a8985"
GRID, NOISE_GREY = "#e3e2de", "#b6b5b0"
ORANGE = "#eb6834"          # single accent: the example ROI, nothing else

# Same purple hue, polarity flipped for the dark projections of panel B: on black
# a light-to-dark ramp hides its own top class, so lightness must rise with the
# ordered variable. Hue and class order are unchanged.
CLASS_COLORS_DARK = {"Low SNR": "#6b4f9e", "Intermediate": "#a683e0", "High SNR": "#e2cdff"}


def bare(ax, keep=("left", "bottom")):
    for name, sp in ax.spines.items():
        sp.set_visible(name in keep)
        sp.set_color(INK_2)


def class_legend(ax, n=None, **kw):
    handles = [Patch(facecolor=CLASS_COLORS[c],
                     label=f"{c} (n={n[c]:,})" if n is not None else c)
               for c in CLASS_ORDER]
    return ax.legend(handles=handles, labelcolor=INK_2, **kw)


def panel_letter_tl(fig, letter, x=0.012, y=0.975):
    fig.text(x, y, letter, fontsize=15, fontweight="bold", color=INK,
             ha="left", va="top")


def footnote(fig, text, y=0.022):
    fig.text(0.075, y, text, fontsize=6.4, color=MUTED, ha="left", va="bottom")


# ─────────────────────────── B: example imagery and traces ────────────────────

def mask_outline(mask):
    """One-pixel boundary of a boolean mask: the mask minus its 3x3 erosion.

    A pixel survives the erosion only if it and all eight neighbours are set;
    pixels on the array border count as having unset neighbours outside it.
    Nine shifted views of a zero-padded copy give exactly that, so no image
    library is needed.
    """
    m = np.asarray(mask, dtype=bool)
    padded = np.pad(m, 1, constant_values=False)
    eroded = np.ones_like(m)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            eroded &= padded[1 + dy:1 + dy + m.shape[0], 1 + dx:1 + dx + m.shape[1]]
    return m & ~eroded


def _class_outlines(labels, roi_class, cls):
    """Boundary pixels of every ROI assigned to `cls`, in one pass per class."""
    members = np.isin(labels, [i for i, c in roi_class.items() if c == cls])
    if not members.any():
        return None
    return mask_outline(members)


def panel_B(planes, example, counts, out, session_label):
    """B mirrors C: every ROI of one session on its plane's projection, coloured
    by quality class, with one ROI ringed and its trace and footprint below."""
    n = len(planes)
    ncol = 4
    nrow = int(np.ceil(n / ncol))
    fig = plt.figure(figsize=(9.2, 2.15 * nrow + 3.3))
    outer = fig.add_gridspec(2, 1, height_ratios=[2.15 * nrow, 2.5], hspace=0.30,
                             left=0.045, right=0.985, top=0.90, bottom=0.155)
    img_gs = outer[0].subgridspec(nrow, ncol, hspace=0.30, wspace=0.06)

    for k, p in enumerate(planes):
        ax = fig.add_subplot(img_gs[k // ncol, k % ncol])
        ax.imshow(p["projection"], cmap="gray", interpolation="nearest",
                  vmin=0.0, vmax=float(np.percentile(p["projection"], 99.5)) * 1.9)
        for cls in CLASS_ORDER:
            edge = _class_outlines(p["labels"], p["roi_class"], cls)
            if edge is None:
                continue
            rgba = np.zeros((*edge.shape, 4))
            rgba[edge] = mpl.colors.to_rgba(CLASS_COLORS_DARK[cls], 0.95)
            ax.imshow(rgba, interpolation="nearest")
        ax.set_title(f"{p['plane']} \u00b7 {p['depth']:.0f} \u00b5m \u2014 {p['n']} ROIs",
                     fontsize=7, loc="left", color=INK, pad=3)
        ax.set_xticks([])
        ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_color(GRID)
        if p["plane"] == example["plane"]:
            ax.plot(example["cx"], example["cy"], marker="o", ms=11, mfc="none",
                    mec=ORANGE, mew=1.1)

    bot = outer[1].subgridspec(1, 2, width_ratios=[2.6, 1.0], wspace=0.14)
    ax_t = fig.add_subplot(bot[0])
    ax_t.plot(example["t"], example["trace"], color=INK_2, lw=0.7)
    hit = example["events"] > 0
    ax_t.plot(example["t"][hit], np.full(hit.sum(), example["trace"].max() * 1.12),
              ls="none", marker="v", ms=3.4, color=ORANGE)
    ax_t.set_xlabel("time (s, from the excerpt start)", fontsize=7)
    ax_t.set_ylabel("\u0394F/F", fontsize=7)
    ax_t.set_xlim(example["t"][0], example["t"][-1])
    ax_t.set_title(f"ROI {example['roi']} \u2014 {example['cls']}, "
                   f"{example['n_events']:,} events at {example['rate_hz']:.2f} Hz "
                   f"over the whole recording", fontsize=7, loc="left", color=INK, pad=4)
    ax_t.text(0.995, 1.02, "OASIS event onset", transform=ax_t.transAxes, fontsize=6.2,
              color=ORANGE, ha="right", va="bottom")
    bare(ax_t)
    ax_t.tick_params(labelsize=7)

    ax_z = fig.add_subplot(bot[1])
    ax_z.imshow(example["zoom"], cmap="gray", interpolation="nearest",
                vmin=0.0, vmax=float(np.percentile(example["zoom"], 99.5)) * 1.3)
    edge = example["zoom_edge"]
    rgba = np.zeros((*edge.shape, 4))
    rgba[edge] = mpl.colors.to_rgba(ORANGE, 1.0)
    ax_z.imshow(rgba, interpolation="nearest")
    ax_z.set_title(f"ROI {example['roi']} footprint\n(average projection), "
                   f"{example['area']:.0f} px", fontsize=7, loc="left", color=INK, pad=3)
    ax_z.set_xticks([])
    ax_z.set_yticks([])
    for sp in ax_z.spines.values():
        sp.set_color(GRID)

    fig.suptitle(f"{session_label} \u2014 {counts['n_rois']:,} ROIs, "
                 f"{n} simultaneous planes", fontsize=8, color=INK,
                 x=0.045, ha="left", y=0.988)
    handles = [Patch(facecolor=CLASS_COLORS_DARK[c], edgecolor=INK_2, lw=0.4,
                     label=f"{c} (n={counts['per_class'][c]:,})") for c in CLASS_ORDER]
    fig.legend(handles=handles, loc="upper right", bbox_to_anchor=(0.985, 0.955),
               ncol=3, frameon=False, fontsize=6.4, labelcolor=INK_2, handlelength=1.1)
    panel_letter_tl(fig, "B", x=0.004)
    footnote(fig, "Footprint colour is the quality class of panel F, fit over all "
                  "sessions. \u0394F/F excerpt is 60 s taken one quarter of the way into "
                  "the session. Onset marks are the quantised excerpt series, so they are "
                  "indicative; the quoted count and rate are the pipeline's own, over the "
                  "full recording.\nOn the dark projections the purple ramp runs dim to bright so "
                  "every class stays visible against black; hue and class order are those "
                  "of panels F and J.", y=0.016)
    fig.savefig(out, dpi=300)
    return fig


# ─────────────────────────── F: the measure and the classes ───────────────────

def panel_F(trace_sd, t, event_amp_sd, examples, feat, counts, out,
            example_label, bins_edges=(2.0, 4.0)):
    """F mirrors G: measurement on one trace, class definition by example,
    then every ROI of the cohort in the event-amplitude feature space."""
    fig = plt.figure(figsize=(7.2, 5.3))
    outer = fig.add_gridspec(2, 1, height_ratios=[1.0, 1.3], hspace=0.50,
                             left=0.075, right=0.965, top=0.89, bottom=0.17)
    top = outer[0].subgridspec(2, 1, hspace=0.42, height_ratios=[1.0, 1.15])
    ax_d = fig.add_subplot(top[0])
    ax_m = fig.add_subplot(top[1], sharex=ax_d)

    # (1) detect - the pipeline's own OASIS events, not a re-detection
    ax_d.plot(t, trace_sd, color=INK, lw=0.6)
    ax_d.axhline(bins_edges[1], color=INK_2, ls="--", lw=0.7)
    ax_d.text(0.998, bins_edges[1], "4 SD ", fontsize=6.4, color=INK_2, va="bottom",
              ha="right", transform=ax_d.get_yaxis_transform(which="grid"))
    hit = event_amp_sd > 0
    ax_d.plot(t[hit], trace_sd[hit], ls="none", marker="o", ms=2.6, color=INK)
    ax_d.set_ylabel("\u0394F/F\n(noise SD)", fontsize=7)
    ax_d.set_title("\u2460 detect \u2014 events are the processing pipeline's own OASIS "
                   "series, not a re-detection", fontsize=7, loc="left", color=INK_2, pad=3)
    bare(ax_d)
    ax_d.tick_params(labelbottom=False, labelsize=7)

    # (2) measure - each event's amplitude in SD of that ROI's noise
    ax_m.plot(t, trace_sd, color=NOISE_GREY, lw=0.6)
    for lo, hi, key in ((-np.inf, bins_edges[0], "lt2"),
                        (bins_edges[0], bins_edges[1], "mid"),
                        (bins_edges[1], np.inf, "gt4")):
        m = hit & (event_amp_sd > lo) & (event_amp_sd <= hi)
        ax_m.vlines(t[m], 0, event_amp_sd[m], color=BIN_GREYS[key], lw=1.3)
    for e, lab in zip(bins_edges, ("+2 SD", "+4 SD"), strict=False):
        ax_m.axhline(e, color=INK_2, ls=":", lw=0.7)
        ax_m.text(0.998, e, f"{lab} ", fontsize=6.4, color=INK_2, va="bottom",
                  ha="right", transform=ax_m.get_yaxis_transform(which="grid"))
    ax_m.set_ylabel("event amplitude\n(SD of noise)", fontsize=7)
    ax_m.set_xlabel("time (s, from the excerpt start)", fontsize=7)
    ax_m.set_title("\u2461 measure \u2014 amplitude in SD of that ROI's \u0394F/F noise, "
                   "binned < 2 / 2\u20134 / > 4 SD", fontsize=7, loc="left", color=INK_2, pad=3)
    bare(ax_m)
    ax_m.tick_params(labelsize=7)
    ax_m.legend(handles=[Patch(facecolor=BIN_GREYS[k], label=BIN_LABELS[k])
                         for k in ("lt2", "mid", "gt4")],
                fontsize=6, frameon=False, ncol=3, loc="upper right", labelcolor=INK_2)

    bot = outer[1].subgridspec(1, 2, width_ratios=[1.0, 1.3], wspace=0.30)
    ex_gs = bot[0].subgridspec(3, 1, hspace=0.62)
    for i, (cls, row) in enumerate(examples):
        ax = fig.add_subplot(ex_gs[i])
        left = 0.0
        for key, col in (("lt2", "frac_events_lt2sd"), ("mid", "frac_events_2_4sd"),
                         ("gt4", "frac_events_gt4sd")):
            w = row[col] * 100
            ax.barh([0], [w], left=[left], color=BIN_GREYS[key], height=0.55)
            if w > 7:
                ax.text(left + w / 2, 0, f"{w:.0f} %", ha="center", va="center",
                        fontsize=6.4, color="white" if key == "gt4" else INK)
            left += w
        ax.set_xlim(0, 100)
        ax.set_ylim(-0.5, 0.5)
        ax.set_yticks([])
        ax.set_title(f"{cls} \u2014 ROI {int(row['roi_index'])}, {row['plane']}",
                     fontsize=7, loc="left", color=INK, pad=3)
        ax.text(100, 0, f"  {int(row['n_events']):,}\n  events", fontsize=6.2,
                color=MUTED, va="center", ha="left")
        bare(ax, keep=("bottom",))
        ax.tick_params(labelsize=7)
        if i < 2:
            ax.tick_params(labelbottom=False, bottom=False)
        else:
            ax.set_xlabel("share of this ROI's events", fontsize=7)

    ax_f = fig.add_subplot(bot[1])
    for cls in CLASS_ORDER:
        sub = feat[feat["amp_threshold_quality_class"] == cls]
        ax_f.scatter(sub["frac_events_lt2sd"] * 100, sub["frac_events_gt4sd"] * 100,
                     s=1.6, lw=0, alpha=0.55, color=CLASS_COLORS[cls])
    for _cls, row in examples:
        ax_f.plot(row["frac_events_lt2sd"] * 100, row["frac_events_gt4sd"] * 100,
                  marker="o", ms=9, mfc="none", mec=ORANGE, mew=1.0)
    ax_f.set_xlabel("% of the ROI's events < 2 SD", fontsize=7)
    ax_f.set_ylabel("% of the ROI's events > 4 SD", fontsize=7)
    ax_f.set_title(f"All sessions \u2014 {counts['sessions']} sessions, "
                   f"{counts['mice']} mice, {counts['rois']:,} ROIs",
                   fontsize=7, loc="left", color=INK, pad=4)
    class_legend(ax_f, n=counts["per_class"], fontsize=6, frameon=False,
                 loc="upper right", handlelength=1.1)
    bare(ax_f)
    ax_f.tick_params(labelsize=7)
    ax_f.grid(True, color=GRID, lw=0.5)
    ax_f.set_axisbelow(True)

    fig.suptitle(f"Measuring signal and noise on a trace \u2014 {example_label}",
                 fontsize=8, color=INK, x=0.075, ha="left", y=0.975)
    panel_letter_tl(fig, "F")
    footnote(fig, "k-means (k = 3) on each ROI's (< 2, 2\u20134, > 4 SD) event-amplitude "
                  "fractions, one fit over all sessions; classes ordered by the > 4 SD "
                  "fraction.\nRings: the three example ROIs at left.")
    fig.savefig(out, dpi=300)
    return fig


# ─────────────────────────── J: where the classes sit ─────────────────────────

def panel_J(by_area, by_depth, by_session, counts, out, by_mouse=None):
    """J mirrors K's lower two cells: class composition across anatomy, and
    across the animal series (the mesoscope analogue of K's per-session cell).

    One bar per session stops working past ~40 sessions: the in-bar
    percentages and ISO dates collide into an unreadable band, and 81 date
    ticks carry no signal a reader can use. Past that size the cell switches
    to a per-mouse aggregate with the session-level spread kept as a strip
    beneath it, so the summary reads at a glance while the across-session
    variation -- the thing the cohort-wide class fit exists to expose --
    stays visible. Per-session detail lives in the interactive viewer.
    """
    dense = len(by_session) > 40 and by_mouse is not None
    fig = plt.figure(figsize=(9.2, 5.0 if dense else 4.6))
    outer = fig.add_gridspec(1, 2, width_ratios=[1.0, 1.85 if dense else 1.75], wspace=0.26,
                             left=0.10, right=0.985, top=0.80, bottom=0.26)
    left_gs = outer[0].subgridspec(2, 1, hspace=0.75, height_ratios=[1.0, 1.7])

    for gi, (tab, title) in enumerate(((by_area, "Classes across cortical area"),
                                       (by_depth, "Classes across imaging depth"))):
        ax = fig.add_subplot(left_gs[gi])
        labels = [f"{i}\nn={int(tab.loc[i, 'n']):,}" for i in tab.index]
        left = np.zeros(len(tab))
        for cls in CLASS_ORDER:
            w = tab[cls].values
            ax.barh(range(len(tab)), w, left=left, color=CLASS_COLORS[cls], height=0.62)
            for y, (start, v) in enumerate(zip(left, w, strict=False)):
                if v > 7:
                    ax.text(start + v / 2, y, f"{v:.0f}", ha="center", va="center",
                            fontsize=6.4, color="white" if cls == "High SNR" else INK)
            left += w
        ax.set_yticks(range(len(tab)))
        ax.set_yticklabels(labels, fontsize=6.6)
        ax.invert_yaxis()
        ax.set_xlim(0, 100)
        ax.set_title(title, fontsize=7.5, loc="left", color=INK, pad=4)
        bare(ax, keep=("bottom",))
        ax.tick_params(labelsize=7)
        if gi == 1:
            ax.set_xlabel("% of ROIs", fontsize=7)

    if not dense:
        ax_s = fig.add_subplot(outer[1])
        x = np.arange(len(by_session))
        bottom = np.zeros(len(by_session))
        for cls in CLASS_ORDER:
            v = by_session[cls].values
            ax_s.bar(x, v, bottom=bottom, color=CLASS_COLORS[cls], width=0.74)
            for xi, (b, vi) in enumerate(zip(bottom, v, strict=False)):
                if vi > 9:
                    ax_s.text(xi, b + vi / 2, f"{vi:.0f}", ha="center", va="center",
                              fontsize=5.8, color="white" if cls == "High SNR" else INK)
            bottom += v
        ax_s.set_xticks(x)
        ax_s.set_xticklabels(by_session["date"], rotation=90, fontsize=6.2)
        ax_s.set_ylabel("% of ROIs", fontsize=7)
        ax_s.set_ylim(0, 100)
        ax_s.set_xlim(-0.7, len(by_session) - 0.3)
        ax_s.set_title("Classes across sessions \u2014 by mouse and date", fontsize=7.5,
                       loc="left", color=INK, pad=16)
        bare(ax_s)
        ax_s.tick_params(labelsize=7)
        for mouse, idx in by_session.groupby("subject", sort=False).groups.items():
            pos = [by_session.index.get_loc(i) for i in idx]
            ax_s.plot([min(pos) - 0.35, max(pos) + 0.35], [103, 103], color=MUTED,
                      lw=0.8, clip_on=False)
            ax_s.text(np.mean(pos), 105, str(mouse), fontsize=6.0, color=MUTED,
                      ha="center", va="bottom", clip_on=False)
        legend_ax = ax_s
    else:
        right = outer[1].subgridspec(2, 1, hspace=0.46, height_ratios=[1.0, 0.72])
        ax_m = fig.add_subplot(right[0])
        xs = np.arange(len(by_mouse))
        bottom = np.zeros(len(by_mouse))
        for cls in CLASS_ORDER:
            v = by_mouse[cls].values
            ax_m.bar(xs, v, bottom=bottom, color=CLASS_COLORS[cls], width=0.70)
            for xi, (b, vi) in enumerate(zip(bottom, v, strict=False)):
                if vi > 9:
                    ax_m.text(xi, b + vi / 2, f"{vi:.0f}", ha="center", va="center",
                              fontsize=6.2, color="white" if cls == "High SNR" else INK)
            bottom += v
        ax_m.set_xticks(xs)
        ax_m.set_xticklabels([str(i) for i in by_mouse.index], fontsize=6.4)
        ax_m.set_ylabel("% of ROIs", fontsize=7)
        ax_m.set_ylim(0, 100)
        ax_m.set_xlim(-0.65, len(by_mouse) - 0.35)
        ax_m.set_title("Classes across mice \u2014 all sessions of each animal pooled",
                       fontsize=7.5, loc="left", color=INK, pad=16)
        bare(ax_m)
        ax_m.tick_params(labelsize=7)
        for xi, n_ses in enumerate(by_mouse["n_sessions"].values):
            ax_m.text(xi, 101.5, f"{int(n_ses)}", fontsize=5.6, color=MUTED,
                      ha="center", va="bottom")
        ax_m.text(-0.65, 101.5, "sessions ", fontsize=5.6, color=MUTED,
                  ha="right", va="bottom")

        # session-level spread, so pooling by mouse does not hide it
        ax_v = fig.add_subplot(right[1], sharex=ax_m)
        order = {m: i for i, m in enumerate(by_mouse.index)}
        rng = np.random.default_rng(0)
        for mouse, grp in by_session.groupby("subject", sort=False):
            xi = order[mouse]
            vals = grp["High SNR"].values
            ax_v.plot(xi + rng.uniform(-0.17, 0.17, len(vals)), vals, ls="none",
                      marker="o", ms=2.8, mfc=CLASS_COLORS["High SNR"], mec="none",
                      alpha=0.75)
            ax_v.plot([xi - 0.30, xi + 0.30], [np.median(vals)] * 2,
                      color=INK, lw=1.0, solid_capstyle="butt")
        ax_v.set_ylabel("% High SNR\nper session", fontsize=7)
        ax_v.set_ylim(0, max(45, float(by_session["High SNR"].max()) * 1.12))
        ax_v.set_xlabel("mouse", fontsize=7)
        ax_v.set_title(f"Session-level spread \u2014 one dot per session "
                       f"(n = {len(by_session)}), bar is the animal median",
                       fontsize=7.5, loc="left", color=INK, pad=4)
        bare(ax_v)
        ax_v.tick_params(labelsize=7)
        ax_v.grid(True, axis="y", color=GRID, lw=0.5)
        ax_v.set_axisbelow(True)
        legend_ax = ax_m

    if dense:
        # the mouse cell's title and its sessions row already occupy the strip
        # above the bars, so the legend goes to the figure header instead
        handles = [Patch(facecolor=CLASS_COLORS[c], label=f"{c} (n={counts['per_class'][c]:,})")
                   for c in CLASS_ORDER]
        fig.legend(handles=handles, loc="upper right", bbox_to_anchor=(0.985, 0.995),
                   ncol=3, frameon=False, fontsize=6.4, labelcolor=INK_2, handlelength=1.1)
    else:
        class_legend(legend_ax, n=counts["per_class"], fontsize=6.4, frameon=False, ncol=3,
                     loc="lower center", bbox_to_anchor=(0.5, 1.10), handlelength=1.1)
    panel_letter_tl(fig, "J")
    tail = ("\nPer-session and per-plane detail is in the interactive viewer."
            if dense else "")
    footnote(fig, "One class fit over all sessions, not within each session. Depth is in "
                  "\u00b5m, not named layers \u2014 these planes are not\nregistered to a layer "
                  "atlas. Counting unit is the somatic ROI, whereas the SLAP2 panels count "
                  "glutamate-release sources\non dendrites, so counts are not comparable "
                  f"across the two columns.{tail}", y=0.015)
    fig.savefig(out, dpi=300)
    return fig
