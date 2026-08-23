"""Automatic, cluster-free branch discovery for an evidence genealogy DAG."""

from __future__ import annotations

from collections import defaultdict, deque
import re
from typing import Any, Iterable

from .schema import EvolutionEdge, PaperRecord


def _short_title(title: str, limit: int = 34) -> str:
    plain = re.sub(r"<[^>]+>", "", title).strip()
    prefix = plain.split(":", 1)[0].strip()
    candidate = prefix if 2 <= len(prefix) <= limit else plain
    if len(candidate) <= limit:
        return candidate
    words = candidate.split()
    shortened = ""
    for word in words:
        proposed = f"{shortened} {word}".strip()
        if len(proposed) > limit:
            break
        shortened = proposed
    return shortened or candidate[: limit - 1] + "…"


def _reachable(
    source: str,
    target: str,
    adjacency: dict[str, set[str]],
    *,
    excluded_edge: tuple[str, str] | None = None,
) -> bool:
    stack = [source]
    seen = {source}
    while stack:
        current = stack.pop()
        for child in adjacency.get(current, set()):
            if excluded_edge == (current, child):
                continue
            if child == target:
                return True
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return False


def transitive_reduction_edges(
    edges: Iterable[EvolutionEdge],
) -> tuple[list[EvolutionEdge], list[EvolutionEdge]]:
    """Return display backbone and redundant direct edges, preserving evidence."""

    candidates = [edge for edge in edges if edge.dominant]
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in candidates:
        adjacency[edge.source].add(edge.target)
    kept: list[EvolutionEdge] = []
    redundant: list[EvolutionEdge] = []
    for edge in candidates:
        bucket = redundant if _reachable(
            edge.source,
            edge.target,
            adjacency,
            excluded_edge=(edge.source, edge.target),
        ) else kept
        bucket.append(edge)
    return kept, redundant


def _descendants(root: str, adjacency: dict[str, set[str]]) -> set[str]:
    result: set[str] = set()
    stack = list(adjacency.get(root, set()))
    while stack:
        current = stack.pop()
        if current in result:
            continue
        result.add(current)
        stack.extend(adjacency.get(current, set()) - result)
    return result


def _components(nodes: set[str], edges: list[EvolutionEdge]) -> list[set[str]]:
    undirected: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        undirected[edge.source].add(edge.target)
        undirected[edge.target].add(edge.source)
    result: list[set[str]] = []
    unseen = set(nodes)
    while unseen:
        start = min(unseen)
        component = {start}
        queue = deque([start])
        unseen.remove(start)
        while queue:
            current = queue.popleft()
            for neighbor in undirected.get(current, set()):
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    component.add(neighbor)
                    queue.append(neighbor)
        result.append(component)
    return result


def _paper_order(paper: PaperRecord) -> tuple[int, str, str]:
    return (
        paper.year if paper.year is not None else 9999,
        paper.title.casefold(),
        paper.paper_id,
    )


def discover_auto_branches(
    papers: Iterable[PaperRecord], edges: Iterable[EvolutionEdge]
) -> dict[str, Any]:
    """Discover branch cones from the transitively reduced primary DAG.

    The result is a navigation lens rather than a hard partition. Branch
    membership may overlap when the genealogy later merges.
    """

    records = list(papers)
    by_id = {paper.paper_id: paper for paper in records}
    backbone, redundant = transitive_reduction_edges(edges)
    adjacency: dict[str, set[str]] = defaultdict(set)
    incoming: dict[str, set[str]] = defaultdict(set)
    edge_by_pair = {(edge.source, edge.target): edge for edge in backbone}
    backbone_nodes: set[str] = set()
    for edge in backbone:
        adjacency[edge.source].add(edge.target)
        incoming[edge.target].add(edge.source)
        backbone_nodes.update((edge.source, edge.target))

    branches: list[dict[str, Any]] = []
    for component_index, component in enumerate(
        sorted(
            _components(backbone_nodes, backbone),
            key=lambda ids: min(_paper_order(by_id[item]) for item in ids),
        )
    ):
        splits = sorted(
            (paper_id for paper_id in component if len(adjacency[paper_id]) > 1),
            key=lambda item: _paper_order(by_id[item]),
        )
        specifications: list[tuple[str | None, str, set[str], str]] = []
        if splits:
            for split in splits:
                for anchor in sorted(adjacency[split], key=lambda item: _paper_order(by_id[item])):
                    members = {split, anchor} | _descendants(anchor, adjacency)
                    specifications.append((split, anchor, members, "branch_cone"))
        else:
            roots = sorted(
                (item for item in component if not (incoming[item] & component)),
                key=lambda item: _paper_order(by_id[item]),
            )
            root = roots[0] if roots else min(component, key=lambda item: _paper_order(by_id[item]))
            specifications.append((None, root, set(component), "lineage_component"))

        for local_index, (split, anchor, members, kind) in enumerate(specifications):
            ordered_members = sorted(members, key=lambda item: _paper_order(by_id[item]))
            internal_edges = [
                edge
                for edge in backbone
                if edge.source in members and edge.target in members
            ]
            roots = [item for item in ordered_members if not (incoming[item] & members)]
            leaves = [item for item in ordered_members if not (adjacency[item] & members)]
            start = split or (roots[0] if roots else ordered_members[0])
            end = leaves[-1] if leaves else ordered_members[-1]
            if kind == "branch_cone":
                label = f"After {_short_title(by_id[start].title)}: {_short_title(by_id[anchor].title)}"
            elif start != end:
                label = f"{_short_title(by_id[start].title)} → {_short_title(by_id[end].title)}"
            else:
                label = _short_title(by_id[start].title)
            representative_ids = list(
                dict.fromkeys([start, anchor, end])
            )
            relation_types = sorted(
                {
                    relation
                    for edge in internal_edges
                    for relation in (edge.relation_types or [edge.relation])
                    if relation
                    not in {"CITES", "KEY_AUTHOR_OVERLAP", "SAME_RESEARCH_GROUP"}
                }
            )
            confidence = (
                min(edge.confidence for edge in internal_edges)
                if internal_edges
                else 0.0
            )
            branches.append(
                {
                    "branch_id": f"auto:{component_index}:{local_index}:{anchor}",
                    "kind": kind,
                    "label": label,
                    "paper_ids": ordered_members,
                    "representative_paper_ids": representative_ids,
                    "edge_keys": [f"{edge.source}→{edge.target}" for edge in internal_edges],
                    "split_paper_id": split,
                    "anchor_paper_id": anchor,
                    "relation_types": relation_types,
                    "confidence": confidence,
                    "explanation": (
                        "Automatically derived from the transitively reduced, "
                        "strong parent-eligible evidence DAG. Branch membership "
                        "may overlap after later merges."
                    ),
                }
            )

    return {
        "method": "primary_dag_transitive_reduction_and_branch_cones",
        "backbone_edge_keys": [f"{edge.source}→{edge.target}" for edge in backbone],
        "redundant_edge_keys": [f"{edge.source}→{edge.target}" for edge in redundant],
        "branches": branches,
    }
