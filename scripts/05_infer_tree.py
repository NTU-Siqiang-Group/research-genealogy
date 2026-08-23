#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.branch_inference import dominant_tree, infer_evolution_dag  # noqa: E402
from src.citation_overlay import read_overlay  # noqa: E402
from src.evidence_extraction import load_evidence_edges  # noqa: E402
from src.render import render  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overlay", required=True)
    parser.add_argument("--evidence")
    parser.add_argument("--axis", default="citation_only")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    papers, citations = read_overlay(args.overlay)
    evidence = load_evidence_edges(args.evidence) if args.evidence else []
    dag = infer_evolution_dag(
        papers, citations, evidence_edges=evidence, axis=args.axis
    )
    tree = dominant_tree(dag)
    dag.dump(f"{args.output_dir}/evolution_dag.json")
    tree.dump(f"{args.output_dir}/dominant_tree.json")
    renderer = render(tree, f"{args.output_dir}/tree.dot", f"{args.output_dir}/tree.svg")
    print(f"wrote DAG/tree to {args.output_dir}; SVG renderer={renderer}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
