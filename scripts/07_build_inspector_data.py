#!/usr/bin/env python3
"""Build the self-contained data payload consumed by the graph inspector."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.branch_discovery import discover_auto_branches  # noqa: E402
from src.schema import EvolutionDAG  # noqa: E402


def _read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def build_inspector_payload(
    *,
    dag_path: str | Path,
    retrieval_path: str | Path,
    topic: str | None = None,
) -> dict[str, Any]:
    dag = _read_json(dag_path)
    retrieval = _read_json(retrieval_path)

    nodes = dag.get("nodes") or []
    edges = dag.get("edges") or []
    dag_model = EvolutionDAG.from_dict(dag)
    auto_discovery = discover_auto_branches(dag_model.nodes, dag_model.edges)
    run_metadata = dict(dag.get("run_metadata") or {})

    # Legacy semantic clusters may remain in the inference artifact for
    # offline experiments, but they are neither an input to branch discovery
    # nor part of the product-facing visualization contract.
    visualization_dag = dict(dag)
    visualization_dag["nodes"] = [
        {
            key: value
            for key, value in node.items()
            if key not in {"cluster_paths", "semantic_profile"}
        }
        for node in nodes
        if isinstance(node, dict)
    ]
    visualization_dag.pop("branches", None)
    visualization_dag["run_metadata"] = {
        key: value
        for key, value in run_metadata.items()
        if key not in {"axis", "clustering_role"}
    }

    fulltext = {}
    for item in retrieval.get("papers") or []:
        if item.get("status") != "retrieved" or not item.get("paper_id"):
            continue
        fulltext[str(item["paper_id"])] = {
            "local_path": item.get("local_path"),
            "selected_url": item.get("selected_url"),
            "selected_provider": item.get("selected_provider"),
            "source_page": item.get("source_page"),
            "sha256": item.get("sha256"),
            "title_score": item.get("title_score"),
            "selected_author": item.get("selected_author"),
            "selected_author_role": item.get("selected_author_role"),
            "discovery_method": item.get("discovery_method"),
            "retrieved_at": retrieval.get("retrieved_at"),
        }

    level_counts = {
        level: sum(
            1
            for edge in edges
            if isinstance(edge, dict) and edge.get("association_level") == level
        )
        for level in ("weak", "medium", "strong")
    }
    dominant_count = sum(
        1 for edge in edges if isinstance(edge, dict) and edge.get("dominant")
    )
    evidence_atom_count = sum(
        len(edge.get("evidence_details") or [])
        for edge in edges
        if isinstance(edge, dict)
    )
    technical_edge_keys = set(auto_discovery["technical_edge_keys"])
    technical_node_ids = {
        endpoint
        for edge in dag_model.edges
        if f"{edge.source}→{edge.target}" in technical_edge_keys
        for endpoint in (edge.source, edge.target)
    }
    narrative_edge_keys = set(auto_discovery["narrative_edge_keys"])
    narrative_node_ids = {
        endpoint
        for edge in dag_model.edges
        if f"{edge.source}→{edge.target}" in narrative_edge_keys
        for endpoint in (edge.source, edge.target)
    }

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "topic": topic
        or run_metadata.get("topic")
        or "Academic research genealogy",
        "source_artifacts": {
            "dag": str(dag_path),
            "retrieval": str(retrieval_path),
        },
        "summary": {
            "paper_count": len(nodes),
            "edge_count": len(edges),
            "dominant_count": dominant_count,
            "evidence_atom_count": evidence_atom_count,
            "association_level_counts": level_counts,
            "display_primary_count": len(auto_discovery["backbone_edge_keys"]),
            "redundant_primary_count": len(auto_discovery["redundant_edge_keys"]),
            "auto_branch_count": len(auto_discovery["branches"]),
            "technical_lineage_edge_count": len(technical_edge_keys),
            "technical_lineage_paper_count": len(technical_node_ids),
            "narrative_lineage_edge_count": len(narrative_edge_keys),
            "narrative_lineage_paper_count": len(narrative_node_ids),
        },
        "dag": visualization_dag,
        "auto_branch_discovery": {
            "method": auto_discovery["method"],
            "technical_edge_keys": auto_discovery["technical_edge_keys"],
            "narrative_edge_keys": auto_discovery["narrative_edge_keys"],
            "backbone_edge_keys": auto_discovery["backbone_edge_keys"],
            "redundant_edge_keys": auto_discovery["redundant_edge_keys"],
        },
        "auto_branches": auto_discovery["branches"],
        "fulltext": fulltext,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dag", default="data/output/evidence_first/evolution_dag.json"
    )
    parser.add_argument(
        "--retrieval", default="data/raw/fulltext/retrieval_index.json"
    )
    parser.add_argument(
        "--topic",
        help="Optional display topic; otherwise use DAG metadata or a generic label",
    )
    parser.add_argument("--output", default="web/data/inspector.json")
    args = parser.parse_args()

    payload = build_inspector_payload(
        dag_path=args.dag,
        retrieval_path=args.retrieval,
        topic=args.topic,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    summary = payload["summary"]
    print(
        f"wrote inspector data to {output}: "
        f"{summary['paper_count']} papers, {summary['edge_count']} edges, "
        f"{summary['evidence_atom_count']} evidence atoms"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
