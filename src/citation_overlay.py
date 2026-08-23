"""Normalize in-corpus bibliography evidence and attach semantic paths."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .hierarchy_runner import extract_cluster_paths
from .schema import CitationEdge, PaperRecord


def load_corpus(path: str | Path) -> list[PaperRecord]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    records = value.get("papers", value) if isinstance(value, dict) else value
    if not isinstance(records, list):
        raise ValueError("corpus JSON must be a list or contain a papers list")
    return [PaperRecord.from_dict(record) for record in records]


def load_hierarchy(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("hierarchy JSON must be an object")
    return value


def overlay_citations(
    papers: Iterable[PaperRecord],
    hierarchy_result: dict[str, Any] | None = None,
    *,
    axis: str = "citation_only",
) -> tuple[list[PaperRecord], list[CitationEdge]]:
    records = list(papers)
    by_id = {paper.paper_id: paper for paper in records}
    if len(by_id) != len(records):
        raise ValueError("duplicate paper_id in corpus")

    if hierarchy_result:
        hierarchy_axis = str(hierarchy_result.get("axis") or axis)
        for paper_id, path in extract_cluster_paths(hierarchy_result).items():
            if paper_id in by_id:
                by_id[paper_id].cluster_paths[hierarchy_axis] = path
        axis = hierarchy_axis

    evidence: dict[tuple[str, str], set[str]] = {}

    def add(source_id: str, target_id: str, reason: str) -> None:
        if source_id == target_id or source_id not in by_id or target_id not in by_id:
            return
        source, target = by_id[source_id], by_id[target_id]
        if source.year is None or target.year is None or source.year > target.year:
            return
        evidence.setdefault((source_id, target_id), set()).add(reason)

    for paper in records:
        for reference_id in paper.references:
            add(reference_id, paper.paper_id, f"{paper.paper_id} lists {reference_id} as a reference")
        for citation_id in paper.citations:
            add(paper.paper_id, citation_id, f"{citation_id} appears in citations of {paper.paper_id}")

    edges = [
        CitationEdge(source, target, sorted(reasons))
        for (source, target), reasons in sorted(evidence.items())
    ]
    records.sort(key=lambda paper: (paper.year is None, paper.year or 0, paper.title))
    return records, edges


def write_overlay(
    papers: list[PaperRecord], edges: list[CitationEdge], output_file: str | Path
) -> None:
    output = Path(output_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "papers": [paper.to_dict() for paper in papers],
                "edges": [edge.to_dict() for edge in edges],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def read_overlay(path: str | Path) -> tuple[list[PaperRecord], list[CitationEdge]]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    return (
        [PaperRecord.from_dict(item) for item in value.get("papers", [])],
        [CitationEdge.from_dict(item) for item in value.get("edges", [])],
    )

