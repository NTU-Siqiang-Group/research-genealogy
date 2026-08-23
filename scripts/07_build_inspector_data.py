#!/usr/bin/env python3
"""Build the self-contained data payload consumed by the graph inspector."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def build_inspector_payload(
    *,
    dag_path: str | Path,
    evaluation_path: str | Path,
    retrieval_path: str | Path,
    gold_path: str | Path,
) -> dict[str, Any]:
    dag = _read_json(dag_path)
    evaluation = _read_json(evaluation_path)
    retrieval = _read_json(retrieval_path)
    gold = yaml.safe_load(Path(gold_path).read_text(encoding="utf-8")) or {}

    nodes = dag.get("nodes") or []
    edges = dag.get("edges") or []
    by_id = {
        str(node["paper_id"]): node
        for node in nodes
        if isinstance(node, dict) and node.get("paper_id")
    }
    resolved = evaluation.get("resolved_gold_keys") or {}

    landmarks = []
    for item in gold.get("must_find") or []:
        key = str(item.get("key") or "")
        paper_id = resolved.get(key)
        node = by_id.get(str(paper_id))
        aliases = [str(alias) for alias in item.get("aliases") or []]
        landmarks.append(
            {
                "key": key,
                "paper_id": paper_id,
                "title": (node or {}).get("title") or item.get("title"),
                "aliases": aliases,
                "short_name": aliases[0] if aliases else None,
                "year": (node or {}).get("year") or item.get("year"),
                "found": paper_id in by_id,
            }
        )

    evaluation_branches = {
        str(item.get("id")): item for item in evaluation.get("branches") or []
    }
    benchmark_branches = []
    for item in gold.get("branch_hypotheses") or []:
        branch_id = str(item.get("id") or "")
        representative_keys = [str(key) for key in item.get("representatives") or []]
        benchmark_branches.append(
            {
                "branch_id": branch_id,
                "label": item.get("label") or branch_id,
                "note": item.get("note") or "",
                "representative_keys": representative_keys,
                "paper_ids": [
                    resolved[key] for key in representative_keys if key in resolved
                ],
                "evaluation": evaluation_branches.get(branch_id, {}),
            }
        )

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

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "topic": gold.get("topic") or "Academic research genealogy",
        "source_artifacts": {
            "dag": str(dag_path),
            "evaluation": str(evaluation_path),
            "retrieval": str(retrieval_path),
            "gold": str(gold_path),
        },
        "summary": {
            "paper_count": len(nodes),
            "edge_count": len(edges),
            "dominant_count": dominant_count,
            "evidence_atom_count": evidence_atom_count,
            "association_level_counts": level_counts,
        },
        "dag": dag,
        "evaluation": evaluation,
        "landmarks": landmarks,
        "benchmark_branches": benchmark_branches,
        "fulltext": fulltext,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dag", default="data/output/evidence_first/evolution_dag.json"
    )
    parser.add_argument(
        "--evaluation", default="data/output/evidence_first/evaluation.json"
    )
    parser.add_argument(
        "--retrieval", default="data/raw/fulltext/retrieval_index.json"
    )
    parser.add_argument("--gold", default="configs/lsm_gold.yaml")
    parser.add_argument("--output", default="web/data/inspector.json")
    args = parser.parse_args()

    payload = build_inspector_payload(
        dag_path=args.dag,
        evaluation_path=args.evaluation,
        retrieval_path=args.retrieval,
        gold_path=args.gold,
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
