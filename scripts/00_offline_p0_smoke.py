#!/usr/bin/env python3
"""Run downstream P0 contracts on a document-derived, non-evaluative fixture."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.branch_inference import dominant_tree, infer_evolution_dag  # noqa: E402
from src.citation_overlay import overlay_citations, write_overlay  # noqa: E402
from src.evaluation import evaluate_gold, write_evaluation  # noqa: E402
from src.render import render  # noqa: E402
from src.schema import PaperRecord, SemanticProfile  # noqa: E402


PAPER_DATA = [
    ("lsm_tree", "The Log-Structured Merge-Tree (LSM-tree)", 1996, ["root"], []),
    ("monkey", "Monkey: Optimal Navigable Key-Value Store", 2017, ["analytical", "models"], ["lsm_tree"]),
    ("dostoevsky", "Dostoevsky: Better Space-Time Trade-Offs for LSM-Tree Based Key-Value Stores via Adaptive Removal of Superfluous Merging", 2018, ["analytical", "compaction"], ["monkey"]),
    ("lsm_bush", "The Log-Structured Merge-Bush & the Wacky Continuum", 2019, ["analytical", "design_space"], ["dostoevsky"]),
    ("spooky", "Spooky: Granulating LSM-Tree Compactions Correctly", 2022, ["granularity", "compaction"], []),
    ("ruskey", "Learning to Optimize LSM-trees: Towards A Reinforcement Learning based Key-Value Store for Dynamic Workloads", 2023, ["learned", "rl_transition"], ["dostoevsky", "monkey"]),
    ("moose", "Structural Designs Meet Optimality: Exploring Optimized LSM-tree Structures in a Colossal Configuration Space", 2024, ["design_space", "expanded"], ["monkey"]),
    ("camal", "CAMAL: Optimizing LSM-trees via Active Learning", 2024, ["learned", "active_tuning"], ["monkey", "ruskey"]),
    ("grow_lsm", "How to Grow an LSM-tree? Towards Bridging the Gap Between Theory and Practice", 2025, ["analytical", "growth"], ["lsm_bush"]),
    ("arcekv", "ArceKV: Towards Workload-driven LSM-compactions for Key-Value Store Under Dynamic Workloads", 2026, ["learned", "rl_transition"], ["dostoevsky", "ruskey", "moose", "camal"]),
]


def main() -> int:
    output = Path("data/output/offline_smoke")
    output.mkdir(parents=True, exist_ok=True)
    papers = []
    for key, title, year, path, references in PAPER_DATA:
        papers.append(
            PaperRecord(
                paper_id=f"FIXTURE:{key}",
                title=title,
                year=year,
                references=[f"FIXTURE:{item}" for item in references],
                semantic_profile=SemanticProfile(
                    coi={"contribution": f"Document-derived placeholder for {key}"},
                    scychic={},
                ),
                cluster_paths={"fixture_branch": path},
                metadata={"gold_key": key, "fixture_only": True},
            )
        )
    corpus = {
        "fixture_notice": (
            "This corpus is transcribed from 02_p0_prototype_plan.md solely to "
            "exercise contracts. It is not a retrieval, clustering, or quality result."
        ),
        "papers": [paper.to_dict() for paper in papers],
    }
    (output / "papers.json").write_text(
        json.dumps(corpus, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    hierarchy = {
        "axis": "fixture_branch",
        "fixture_notice": corpus["fixture_notice"],
        "hierarchy": {"clusters": []},
    }
    (output / "hierarchy.json").write_text(
        json.dumps(hierarchy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    overlaid, citation_edges = overlay_citations(papers, axis="fixture_branch")
    write_overlay(overlaid, citation_edges, output / "citation_graph.json")
    dag = infer_evolution_dag(
        overlaid,
        citation_edges,
        axis="fixture_branch",
        run_metadata={"fixture_only": True},
    )
    tree = dominant_tree(dag)
    dag.dump(output / "evolution_dag.json")
    tree.dump(output / "dominant_tree.json")
    renderer = render(tree, output / "tree.dot", output / "tree.svg")
    gold = yaml.safe_load(Path("configs/lsm_gold.yaml").read_text(encoding="utf-8"))
    evaluation = evaluate_gold(dag, gold)
    evaluation["fixture_notice"] = corpus["fixture_notice"]
    evaluation["renderer"] = renderer
    write_evaluation(evaluation, output / "evaluation.json")
    print(json.dumps(evaluation["metrics"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

