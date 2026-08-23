"""Small, transparent gold-constraint evaluator for P0 runs."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
from typing import Any, Mapping

from .schema import EvolutionDAG, PaperRecord


def _normalize(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _resolve_gold_papers(
    nodes: list[PaperRecord], gold: Mapping[str, Any]
) -> tuple[dict[str, str], list[str]]:
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for entry in gold.get("must_find", []):
        key = str(entry["key"])
        candidates = [str(entry["title"]), *(entry.get("aliases") or [])]
        match = next(
            (
                paper
                for paper in nodes
                if paper.metadata.get("gold_key") == key
                or any(_normalize(paper.title) == _normalize(title) for title in candidates)
                or any(
                    len(_normalize(alias)) >= 5
                    and _normalize(alias) in _normalize(paper.title)
                    for alias in entry.get("aliases") or []
                )
            ),
            None,
        )
        if match:
            resolved[key] = match.paper_id
        else:
            missing.append(key)
    return resolved, missing


def evaluate_gold(dag: EvolutionDAG, gold: Mapping[str, Any]) -> dict[str, Any]:
    resolved, missing = _resolve_gold_papers(dag.nodes, gold)
    all_pairs = {(edge.source, edge.target) for edge in dag.edges}
    edge_by_pair = {(edge.source, edge.target): edge for edge in dag.edges}
    dominant_pairs = {
        (edge.source, edge.target) for edge in dag.edges if edge.dominant
    }

    expected_details = []
    for expected in gold.get("expected_edges", []):
        source = resolved.get(str(expected["source"]))
        target = resolved.get(str(expected["target"]))
        found = bool(source and target and (source, target) in all_pairs)
        dominant = bool(source and target and (source, target) in dominant_pairs)
        recovered = edge_by_pair.get((source, target)) if source and target else None
        expected_details.append(
            {
                **dict(expected),
                "found": found,
                "dominant": dominant,
                "association_level": (
                    recovered.association_level if recovered else None
                ),
                "parent_eligible": (
                    recovered.parent_eligible if recovered else False
                ),
                "relation_types": (
                    recovered.relation_types if recovered else []
                ),
                "fulltext_evidence_count": (
                    len(recovered.evidence_details) if recovered else 0
                ),
            }
        )

    forbidden_details = []
    for forbidden in gold.get("must_not_force", []):
        source = resolved.get(str(forbidden["source"]))
        target = resolved.get(str(forbidden["target"]))
        forced = bool(source and target and (source, target) in dominant_pairs)
        forbidden_details.append({**dict(forbidden), "forced": forced})

    by_id = {paper.paper_id: paper for paper in dag.nodes}
    axis = str(dag.run_metadata.get("axis") or "citation_only")
    branch_details = []
    for branch in gold.get("branch_hypotheses", []):
        requested = [str(key) for key in branch.get("representatives", [])]
        found_ids = [resolved[key] for key in requested if key in resolved]
        top_paths = [
            tuple(by_id[paper_id].cluster_paths.get(axis, [])[:1])
            for paper_id in found_ids
            if by_id[paper_id].cluster_paths.get(axis)
        ]
        majority = Counter(top_paths).most_common(1)[0][1] if top_paths else 0
        branch_details.append(
            {
                "id": branch["id"],
                "paper_coverage": len(found_ids) / len(requested) if requested else 0.0,
                "coarse_cluster_coherence": majority / len(top_paths) if top_paths else None,
                "found_paper_ids": found_ids,
            }
        )

    expected_hubs = [str(key) for key in gold.get("expected_hubs", [])]
    recovered_hubs = [
        key
        for key in expected_hubs
        if key in resolved and by_id[resolved[key]].metadata.get("is_hub")
    ]

    chronology_violations = []
    for edge in dag.edges:
        source, target = by_id[edge.source], by_id[edge.target]
        if source.year is not None and target.year is not None and source.year > target.year:
            chronology_violations.append([edge.source, edge.target])

    expected_found = sum(item["found"] for item in expected_details)
    expected_dominant = sum(item["dominant"] for item in expected_details)
    expected_strong = sum(
        item["association_level"] == "strong" for item in expected_details
    )
    expected_evidence_backed = sum(
        item["fulltext_evidence_count"] > 0 for item in expected_details
    )
    expected_parent_eligible = sum(
        item["parent_eligible"] for item in expected_details
    )
    return {
        "run": dag.run_metadata,
        "metrics": {
            "must_find_recall": len(resolved) / max(1, len(gold.get("must_find", []))),
            "expected_edge_recall": expected_found / max(1, len(expected_details)),
            "expected_dominant_edge_recall": expected_dominant
            / max(1, len(expected_details)),
            "expected_strong_association_recall": expected_strong
            / max(1, len(expected_details)),
            "expected_fulltext_evidence_recall": expected_evidence_backed
            / max(1, len(expected_details)),
            "expected_parent_eligible_recall": expected_parent_eligible
            / max(1, len(expected_details)),
            "forbidden_edge_count": sum(item["forced"] for item in forbidden_details),
            "expected_hub_recall": (
                len(recovered_hubs) / len(expected_hubs) if expected_hubs else None
            ),
            "chronology_violation_count": len(chronology_violations),
            "manual_topology_score_0_to_3": None,
            "manual_branch_semantics_score_0_to_3": None,
            "manual_split_explanation_score_0_to_3": None,
        },
        "resolved_gold_keys": resolved,
        "missing_must_find": missing,
        "expected_edges": expected_details,
        "forbidden_edges": forbidden_details,
        "branches": branch_details,
        "recovered_expected_hubs": recovered_hubs,
        "chronology_violations": chronology_violations,
    }


def write_evaluation(result: Mapping[str, Any], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
