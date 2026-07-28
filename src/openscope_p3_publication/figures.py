from __future__ import annotations

import csv
from dataclasses import dataclass
from html import escape
from pathlib import Path

import plotly.graph_objects as go

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "figure_sources" / "data"
INTERACTIVE_OUTPUT = REPO_ROOT / "interactive" / "experimental-design.html"
STATIC_OUTPUT = REPO_ROOT / "images" / "figures" / "generated" / "experimental-design.svg"


@dataclass(frozen=True)
class Session:
    number: int
    name: str
    mismatch: str
    color: str


@dataclass(frozen=True)
class Block:
    name: str
    duration_minutes: float
    category: str


def load_sessions(
    path: Path = DATA_DIR / "experimental-design-sessions.csv",
) -> tuple[Session, ...]:
    with path.open(newline="", encoding="utf-8") as stream:
        return tuple(
            Session(
                number=int(row["number"]),
                name=row["name"],
                mismatch=row["mismatch"],
                color=row["color"],
            )
            for row in csv.DictReader(stream)
        )


def load_blocks(path: Path = DATA_DIR / "experimental-design-blocks.csv") -> tuple[Block, ...]:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = sorted(csv.DictReader(stream), key=lambda row: int(row["order"]))
        return tuple(
            Block(
                name=row["name"],
                duration_minutes=float(row["duration_minutes"]),
                category=row["category"],
            )
            for row in rows
        )


SESSIONS = load_sessions()
BLOCKS = load_blocks()

SHARED_COLORS = (
    "#D9DFE3",
    "#C7D0D6",
    "#B5C1C8",
    "#A4B2BA",
    "#92A3AC",
    "#80949E",
    "#6F858F",
)


def total_duration_minutes() -> float:
    return sum(block.duration_minutes for block in BLOCKS)


def build_interactive_figure() -> go.Figure:
    figure = go.Figure()
    offset = 0.0
    shared_index = 0

    for block in BLOCKS:
        colors = []
        hover_details = []
        for session in SESSIONS:
            if block.category == "context":
                colors.append(session.color)
                hover_details.append(session.mismatch)
            else:
                colors.append(SHARED_COLORS[shared_index])
                hover_details.append("Shared across all four sessions")

        legend_name = (
            "Context block (color by session)" if block.category == "context" else "Shared blocks"
        )
        figure.add_trace(
            go.Bar(
                x=[block.duration_minutes] * len(SESSIONS),
                y=[f"S{session.number}<br>{session.name.split()[0]}" for session in SESSIONS],
                base=[offset] * len(SESSIONS),
                orientation="h",
                name=legend_name,
                showlegend=block.category == "context" or shared_index == 0,
                marker={"color": colors, "line": {"color": "#FFFFFF", "width": 1}},
                customdata=[
                    [
                        f"Session {session.number}: {session.name}",
                        block.name,
                        block.duration_minutes,
                        detail,
                    ]
                    for session, detail in zip(SESSIONS, hover_details, strict=True)
                ],
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>%{customdata[1]}<br>"
                    "%{customdata[2]:.1f} min<br>%{customdata[3]}<extra></extra>"
                ),
            )
        )
        offset += block.duration_minutes
        if block.category == "shared":
            shared_index += 1

    figure.update_layout(
        title={
            "text": "Shared session structure",
            "x": 0,
            "xanchor": "left",
            "font": {"size": 21},
        },
        barmode="overlay",
        bargap=0.28,
        font={"family": "IBM Plex Sans, sans-serif", "color": "#172126", "size": 12},
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        margin={"l": 105, "r": 15, "t": 78, "b": 78},
        height=460,
        legend={
            "orientation": "h",
            "yanchor": "top",
            "y": -0.19,
            "xanchor": "left",
            "x": 0,
            "font": {"size": 12},
        },
        hoverlabel={"font": {"family": "IBM Plex Sans, sans-serif"}},
    )
    figure.update_xaxes(
        title="Minutes from session start",
        range=[0, total_duration_minutes()],
        showgrid=True,
        gridcolor="#E7EAEC",
        zeroline=False,
        ticksuffix=" min",
    )
    figure.update_yaxes(autorange="reversed", showgrid=False, tickfont={"size": 11})
    return figure


def write_interactive_html(output: Path = INTERACTIVE_OUTPUT) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    build_interactive_figure().write_html(
        output,
        include_plotlyjs="cdn",
        full_html=True,
        div_id="experimental-design-plot",
        config={
            "displaylogo": False,
            "responsive": True,
            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        },
    )
    return output


def write_static_svg(output: Path = STATIC_OUTPUT) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    width = 1200
    height = 500
    label_width = 220
    plot_width = 920
    top = 105
    row_height = 72
    bar_height = 44
    scale = plot_width / total_duration_minutes()

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        'aria-labelledby="title description">',
        '<title id="title">Shared structure of the four predictive-processing sessions</title>',
        '<desc id="description">Four horizontal session timelines with a context-specific '
        'mismatch block and seven shared control and characterization blocks.</desc>',
        '<rect width="1200" height="500" fill="#FFFFFF"/>',
        '<text x="40" y="52" font-family="IBM Plex Sans, sans-serif" font-size="28" '
        'font-weight="600" fill="#172126">Shared structure of the four predictive-processing '
        "sessions</text>",
    ]

    for session_index, session in enumerate(SESSIONS):
        y = top + session_index * row_height
        svg.append(
            f'<text x="40" y="{y + 18}" font-family="IBM Plex Sans, sans-serif" '
            f'font-size="17" font-weight="600" fill="#172126">Session {session.number}</text>'
        )
        svg.append(
            f'<text x="40" y="{y + 39}" font-family="IBM Plex Sans, sans-serif" '
            f'font-size="14" fill="#49565C">{escape(session.name)}</text>'
        )
        x = label_width
        shared_index = 0
        for block in BLOCKS:
            block_width = block.duration_minutes * scale
            color = session.color if block.category == "context" else SHARED_COLORS[shared_index]
            svg.append(
                f'<rect x="{x:.2f}" y="{y}" width="{block_width:.2f}" height="{bar_height}" '
                f'fill="{color}" stroke="#FFFFFF" stroke-width="1"/>'
            )
            if block_width >= 80:
                svg.append(
                    f'<text x="{x + block_width / 2:.2f}" y="{y + 27}" '
                    'font-family="IBM Plex Sans, sans-serif" font-size="11" '
                    f'text-anchor="middle" fill="#172126">{escape(block.name)}</text>'
                )
            x += block_width
            if block.category == "shared":
                shared_index += 1

    axis_y = top + len(SESSIONS) * row_height + 12
    svg.append(
        f'<line x1="{label_width}" y1="{axis_y}" x2="{label_width + plot_width}" '
        f'y2="{axis_y}" stroke="#49565C" stroke-width="1"/>'
    )
    for minute in range(0, 71, 10):
        x = label_width + minute * scale
        svg.extend(
            [
                f'<line x1="{x:.2f}" y1="{axis_y}" x2="{x:.2f}" y2="{axis_y + 6}" '
                'stroke="#49565C" stroke-width="1"/>',
                f'<text x="{x:.2f}" y="{axis_y + 24}" '
                'font-family="IBM Plex Sans, sans-serif" font-size="12" '
                f'text-anchor="middle" fill="#49565C">{minute} min</text>',
            ]
        )
    svg.append("</svg>")
    output.write_text("\n".join(svg) + "\n", encoding="utf-8")
    return output


def main() -> None:
    html_path = write_interactive_html()
    svg_path = write_static_svg()
    print(f"Wrote {html_path.relative_to(REPO_ROOT)}")
    print(f"Wrote {svg_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()