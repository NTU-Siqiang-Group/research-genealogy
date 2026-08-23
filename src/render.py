"""Graphviz DOT output plus a dependency-free timeline SVG fallback."""

from __future__ import annotations

from collections import defaultdict
import html
from pathlib import Path
import shutil
import subprocess

from .schema import EvolutionDAG


PALETTE = ["#dbeafe", "#dcfce7", "#fef3c7", "#fce7f3", "#ede9fe", "#cffafe"]


def _dot_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def render_dot(dag: EvolutionDAG) -> str:
    axis = str(dag.run_metadata.get("axis") or "citation_only")
    branch_keys = sorted(
        {tuple(paper.cluster_paths.get(axis, [])[:1]) for paper in dag.nodes}
    )
    colors = {key: PALETTE[index % len(PALETTE)] for index, key in enumerate(branch_keys)}
    lines = [
        "digraph academic_genealogy {",
        '  graph [rankdir=LR, bgcolor="white", nodesep=0.35, ranksep=0.8];',
        '  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10];',
        '  edge [fontname="Helvetica", fontsize=8, color="#94a3b8"];',
    ]
    for paper in dag.nodes:
        branch = tuple(paper.cluster_paths.get(axis, [])[:1])
        fill = colors.get(branch, "#f1f5f9")
        penwidth = 3 if paper.metadata.get("is_hub") else 1
        label = f"{paper.title}\\n{paper.year or '?'}"
        lines.append(
            f'  "{_dot_text(paper.paper_id)}" [label="{_dot_text(label)}", '
            f'fillcolor="{fill}", penwidth={penwidth}];'
        )
    for edge in dag.edges:
        if not edge.dominant and edge.relation != "CITES_CROSS_BRANCH":
            continue
        style = "bold" if edge.dominant else "dashed"
        width = 2.4 if edge.dominant else 1.0
        color = "#334155" if edge.dominant else "#cbd5e1"
        lines.append(
            f'  "{_dot_text(edge.source)}" -> "{_dot_text(edge.target)}" '
            f'[style={style}, penwidth={width}, color="{color}", label="{edge.relation}"];'
        )
    by_year: dict[int, list[str]] = defaultdict(list)
    for paper in dag.nodes:
        if paper.year is not None:
            by_year[paper.year].append(paper.paper_id)
    for year, ids in sorted(by_year.items()):
        quoted = "; ".join(f'"{_dot_text(item)}"' for item in ids)
        lines.append(f"  {{ rank=same; {quoted}; }} // {year}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _fallback_svg(dag: EvolutionDAG) -> str:
    axis = str(dag.run_metadata.get("axis") or "citation_only")
    nodes = sorted(dag.nodes, key=lambda paper: (paper.year or 0, paper.title))
    if not nodes:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="200"/>'
    years = [paper.year for paper in nodes if paper.year is not None]
    min_year, max_year = (min(years), max(years)) if years else (0, 1)
    year_span = max(1, max_year - min_year)
    branch_keys = sorted({tuple(p.cluster_paths.get(axis, [])[:1]) for p in nodes})
    branch_index = {key: index for index, key in enumerate(branch_keys)}
    counts: dict[tuple[int, tuple[str, ...]], int] = defaultdict(int)
    positions: dict[str, tuple[float, float]] = {}
    width = 1400
    for paper in nodes:
        year = paper.year if paper.year is not None else min_year
        x = 110 + (year - min_year) / year_span * (width - 220)
        branch = tuple(paper.cluster_paths.get(axis, [])[:1])
        collision_key = (year, branch)
        offset = counts[collision_key]
        counts[collision_key] += 1
        y = 90 + branch_index.get(branch, 0) * 150 + offset * 52
        positions[paper.paper_id] = (x, y)
    height = max(260, int(max(y for _, y in positions.values()) + 100))
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<style>text{font-family:Arial,sans-serif}.paper{font-size:11px}.year{font-size:10px;fill:#64748b}</style>',
    ]
    for edge in dag.edges:
        if not edge.dominant or edge.source not in positions or edge.target not in positions:
            continue
        x1, y1 = positions[edge.source]
        x2, y2 = positions[edge.target]
        parts.append(
            f'<line x1="{x1 + 70:.1f}" y1="{y1:.1f}" x2="{x2 - 70:.1f}" y2="{y2:.1f}" stroke="#475569" stroke-width="2"/>'
        )
    for paper in nodes:
        x, y = positions[paper.paper_id]
        branch = tuple(paper.cluster_paths.get(axis, [])[:1])
        fill = PALETTE[branch_index.get(branch, 0) % len(PALETTE)]
        stroke_width = 3 if paper.metadata.get("is_hub") else 1
        short = paper.title if len(paper.title) <= 25 else paper.title[:22] + "…"
        parts.append(
            f'<rect x="{x - 70:.1f}" y="{y - 24:.1f}" width="140" height="48" rx="8" fill="{fill}" stroke="#334155" stroke-width="{stroke_width}"/>'
        )
        parts.append(
            f'<text class="paper" x="{x:.1f}" y="{y - 2:.1f}" text-anchor="middle">{html.escape(short)}</text>'
        )
        parts.append(
            f'<text class="year" x="{x:.1f}" y="{y + 14:.1f}" text-anchor="middle">{paper.year or "?"}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def render(dag: EvolutionDAG, dot_path: str | Path, svg_path: str | Path) -> str:
    dot_output, svg_output = Path(dot_path), Path(svg_path)
    dot_output.parent.mkdir(parents=True, exist_ok=True)
    svg_output.parent.mkdir(parents=True, exist_ok=True)
    dot_output.write_text(render_dot(dag), encoding="utf-8")
    dot_binary = shutil.which("dot")
    if dot_binary:
        subprocess.run(
            [dot_binary, "-Tsvg", str(dot_output), "-o", str(svg_output)],
            check=True,
        )
        return "graphviz"
    svg_output.write_text(_fallback_svg(dag), encoding="utf-8")
    return "fallback_svg"

