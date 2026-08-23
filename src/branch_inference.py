"""Evidence-first genealogy inference with clustering kept downstream."""

from __future__ import annotations

from collections import defaultdict
import math
from typing import Any, Iterable

from .authorship_affinity import key_author_overlap_edges
from .schema import Branch, CitationEdge, EvolutionDAG, EvolutionEdge, PaperRecord


def _path(paper: PaperRecord, axis: str) -> list[str]:
    return paper.cluster_paths.get(axis, [])


def _same_branch_score(left: PaperRecord, right: PaperRecord, axis: str) -> float:
    left_path, right_path = _path(left, axis), _path(right, axis)
    if not left_path or not right_path:
        return 0.0
    if left_path == right_path:
        return 2.0
    shared = 0
    for left_part, right_part in zip(left_path, right_path):
        if left_part != right_part:
            break
        shared += 1
    return 1.0 if shared else 0.0


def _descendants(
    paper_ids: Iterable[str], edges: Iterable[CitationEdge | EvolutionEdge]
) -> dict[str, set[str]]:
    children: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        children[edge.source].add(edge.target)
    result: dict[str, set[str]] = {}
    for root in paper_ids:
        seen: set[str] = set()
        stack = list(children[root])
        while stack:
            child = stack.pop()
            if child in seen:
                continue
            seen.add(child)
            stack.extend(children[child] - seen)
        result[root] = seen
    return result


def _branch_records(
    papers: list[PaperRecord],
    axis: str,
    hub_scores: dict[str, float],
    descendants: dict[str, set[str]],
) -> list[Branch]:
    leaf_paths = {tuple(_path(paper, axis)) for paper in papers if _path(paper, axis)}
    paths = sorted(
        {()} | {path[:length] for path in leaf_paths for length in range(1, len(path) + 1)},
        key=lambda path: (len(path), path),
    )
    branches: list[Branch] = []
    for path in paths:
        members = [
            paper for paper in papers if tuple(_path(paper, axis))[: len(path)] == path
        ]
        representatives = sorted(
            members,
            key=lambda paper: (
                hub_scores.get(paper.paper_id, 0.0),
                paper.metadata.get("citation_count") or 0,
            ),
            reverse=True,
        )[:3]
        branch_id = f"{axis}:" + ("/".join(path) if path else "root")
        if not path:
            parent = None
        elif len(path) == 1:
            parent = f"{axis}:root"
        else:
            parent = f"{axis}:" + "/".join(path[:-1])
        label = " / ".join(path) if path else f"{axis} root"
        child_paths = [
            candidate
            for candidate in paths
            if len(candidate) == len(path) + 1 and candidate[:-1] == path
        ]
        split_hub = None
        split_reason = ""
        if len(child_paths) >= 2:
            candidates: list[tuple[int, float, str]] = []
            child_start_years = []
            for child_path in child_paths:
                years = [
                    paper.year
                    for paper in papers
                    if paper.year is not None
                    and tuple(_path(paper, axis))[: len(child_path)] == child_path
                ]
                if years:
                    child_start_years.append(min(years))
            latest_candidate_year = (
                min(child_start_years) + 1 if child_start_years else None
            )
            for paper in papers:
                if (
                    latest_candidate_year is not None
                    and (paper.year is None or paper.year > latest_candidate_year)
                ):
                    continue
                descendant_paths = {
                    tuple(_path(descendant, axis))[: len(path) + 1]
                    for descendant in papers
                    if descendant.paper_id in descendants.get(paper.paper_id, set())
                }
                coverage = len(set(child_paths) & descendant_paths)
                if coverage >= 2:
                    candidates.append(
                        (coverage, hub_scores.get(paper.paper_id, 0.0), paper.paper_id)
                    )
            if candidates:
                split_hub = max(candidates)[2]
            split_reason = (
                "Deterministic P0 contrast between child semantic clusters: "
                + ", ".join("/".join(child) for child in child_paths)
                + ". Semantic what-changed wording requires cluster summaries."
            )
        branches.append(
            Branch(
                branch_id=branch_id,
                label=label,
                summary=f"SCYCHIC {axis} cluster path {label}",
                parent_branch=parent,
                representative_papers=[paper.paper_id for paper in representatives],
                split_hub=split_hub,
                split_reason=split_reason,
            )
        )
    return branches


def infer_evolution_dag(
    papers: Iterable[PaperRecord],
    citation_edges: Iterable[CitationEdge],
    *,
    evidence_edges: Iterable[EvolutionEdge] | None = None,
    axis: str = "citation_only",
    hub_threshold: float = 1.0,
    run_metadata: dict[str, Any] | None = None,
) -> EvolutionDAG:
    records = list(papers)
    citations = list(citation_edges)
    extracted = list(evidence_edges or [])
    authorship_edges = key_author_overlap_edges(records)
    by_id = {paper.paper_id: paper for paper in records}

    citation_by_pair = {(edge.source, edge.target): edge for edge in citations}
    evidence_by_pair = {(edge.source, edge.target): edge for edge in extracted}
    authorship_by_pair: dict[tuple[str, str], EvolutionEdge] = {}
    for edge in authorship_edges:
        pair = (edge.source, edge.target)
        reverse = (edge.target, edge.source)
        # On same-year papers, logical/citation direction is more meaningful
        # than the deterministic title tie-break used by the symmetric group
        # signal. Align the supplemental evidence to that existing direction.
        if reverse in citation_by_pair or reverse in evidence_by_pair:
            edge.source, edge.target = edge.target, edge.source
            for atom in edge.evidence_details:
                atom.paper_id = edge.target
                atom.cited_paper_id = edge.source
            pair = reverse
        authorship_by_pair[pair] = edge
    pairs = sorted(
        set(citation_by_pair) | set(evidence_by_pair) | set(authorship_by_pair)
    )

    evolution_edges: list[EvolutionEdge] = []
    for pair in pairs:
        citation = citation_by_pair.get(pair)
        semantic = evidence_by_pair.get(pair)
        authorship = authorship_by_pair.get(pair)
        if semantic is None and authorship is None:
            evolution_edges.append(
                EvolutionEdge(
                    source=pair[0],
                    target=pair[1],
                    citation_exists=True,
                    relation="CITES",
                    relation_types=["CITES"],
                    association_level="weak",
                    explanation=(
                        "Weak association: bibliography-level citation without "
                        "section-aware inheritance evidence."
                    ),
                    evidence=list(citation.evidence if citation else []),
                    confidence=0.25,
                    dominant=False,
                    parent_eligible=False,
                )
            )
            continue

        if semantic is None:
            # Key-author overlap is medium but supplemental: it upgrades an
            # ordinary citation association without becoming a parent edge.
            semantic = authorship
        elif authorship is not None:
            semantic.relation_types = sorted(
                set(semantic.relation_types)
                | set(authorship.relation_types)
            )
            semantic.evidence = sorted(
                set(semantic.evidence) | set(authorship.evidence)
            )
            semantic.evidence_details.extend(authorship.evidence_details)
            if semantic.association_level == "weak":
                semantic.association_level = "medium"
                semantic.relation = "SAME_RESEARCH_GROUP"
                semantic.explanation = authorship.explanation
            else:
                semantic.explanation = (
                    semantic.explanation.rstrip()
                    + " Supplemental research-group evidence is also present from "
                    + "key-author overlap."
                )
            semantic.confidence = max(semantic.confidence, authorship.confidence)

        # Full-text evidence is authoritative.  Citation overlay only contributes
        # provenance and never upgrades a relationship by itself. Authorship
        # evidence may upgrade weak to medium, but never changes parent eligibility.
        assert semantic is not None
        semantic.citation_exists = bool(citation) or semantic.citation_exists
        semantic.evidence = sorted(
            set(semantic.evidence) | set(citation.evidence if citation else [])
        )
        semantic.relation_types = sorted(
            set(semantic.relation_types or [semantic.relation])
            | ({"CITES"} if semantic.citation_exists else set())
        )
        semantic.dominant = (
            semantic.association_level == "strong" and semantic.parent_eligible
        )
        evolution_edges.append(semantic)

    # Hubs are now measured on strong, parent-eligible genealogy edges rather
    # than on the entire citation graph.
    genealogy_edges = [edge for edge in evolution_edges if edge.dominant]
    descendants = _descendants(by_id, genealogy_edges)

    hub_scores: dict[str, float] = {}
    for paper_id, later_ids in descendants.items():
        branches = {
            tuple(_path(by_id[later_id], axis))
            for later_id in later_ids
            if later_id in by_id and _path(by_id[later_id], axis)
        }
        coverage = len(branches)
        hub_scores[paper_id] = coverage * math.log1p(len(later_ids))
        by_id[paper_id].metadata["hub_score"] = round(hub_scores[paper_id], 6)
        by_id[paper_id].metadata["is_hub"] = hub_scores[paper_id] >= hub_threshold

    branches = _branch_records(records, axis, hub_scores, descendants)
    level_counts = {
        level: sum(edge.association_level == level for edge in evolution_edges)
        for level in ("weak", "medium", "strong")
    }
    return EvolutionDAG(
        nodes=records,
        edges=evolution_edges,
        branches=branches,
        run_metadata={
            "axis": axis,
            "lineage_inference": "section_aware_evidence",
            "clustering_role": "branch_grouping_and_display_only",
            "association_level_counts": level_counts,
            "authorship_overlap_edge_count": len(authorship_edges),
            "authorship_metadata_paper_count": sum(
                bool(paper.metadata.get("authorships") or paper.metadata.get("authors"))
                for paper in records
            ),
            **(run_metadata or {}),
        },
    )


def dominant_tree(dag: EvolutionDAG) -> EvolutionDAG:
    return EvolutionDAG(
        nodes=dag.nodes,
        edges=[edge for edge in dag.edges if edge.dominant],
        branches=dag.branches,
        run_metadata={**dag.run_metadata, "projection": "dominant_tree"},
    )
