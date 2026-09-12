#!/usr/bin/env python3
"""Extract weak/medium/strong relationship evidence from local PDFs."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.citation_overlay import load_corpus  # noqa: E402
from src.evidence_extraction import (  # noqa: E402
    EntityOrigin,
    pdf_to_document,
    relation_edges_from_documents,
    resolve_bibliography,
    write_evidence_edges,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument(
        "--retrieval-index",
        help="append successfully retrieved PDFs from 03_retrieve_fulltext.py",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    papers = load_corpus(args.corpus)
    by_id = {paper.paper_id: paper for paper in papers}
    manifest_path = Path(args.manifest)
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}

    document_items = list(manifest.get("documents", []))
    if args.retrieval_index:
        retrieval = json.loads(
            Path(args.retrieval_index).read_text(encoding="utf-8")
        )
        existing_ids = {str(item["paper_id"]) for item in document_items}
        for item in retrieval.get("papers", []):
            paper_id = str(item.get("paper_id") or "")
            local_path = item.get("local_path")
            if (
                item.get("status") == "retrieved"
                and paper_id
                and local_path
                and paper_id not in existing_ids
            ):
                document_items.append(
                    {"paper_id": paper_id, "pdf_path": str(local_path)}
                )
                existing_ids.add(paper_id)

    documents = []
    resolution_stats = []
    for item in document_items:
        paper_id = str(item["paper_id"])
        if paper_id not in by_id:
            raise ValueError(f"manifest paper is absent from corpus: {paper_id}")
        pdf_path = Path(str(item["pdf_path"]))
        document = pdf_to_document(pdf_path, paper_id)
        resolved = resolve_bibliography(document, papers)
        documents.append(document)
        resolution_stats.append(
            {
                "paper_id": paper_id,
                "pdf_path": str(pdf_path),
                "sections": len(document.sections),
                "bibliography_entries": len(document.references),
                "resolved_references": len(resolved),
            }
        )

    origins = [
        EntityOrigin(
            entity=str(item["entity"]),
            paper_id=str(item["paper_id"]),
            aliases=[str(alias) for alias in item.get("aliases", [])],
            evidence_text=str(item.get("evidence_text") or ""),
            section=str(item.get("section") or "unknown"),
            source_path=item.get("source_path"),
        )
        for item in manifest.get("entity_origins", [])
    ]
    edges = relation_edges_from_documents(
        papers, documents, entity_origins=origins
    )
    counts = Counter(edge.association_level for edge in edges)
    write_evidence_edges(
        edges,
        args.output,
        metadata={
            "manifest": str(manifest_path),
            "documents": resolution_stats,
            "association_level_counts": dict(counts),
            "method": "section_aware_numeric_or_author_year_citation_and_entity_provenance",
        },
    )
    print(
        f"wrote {len(edges)} evidence-backed relations to {args.output}; "
        f"levels={dict(counts)}"
    )
    for stat in resolution_stats:
        print(
            f"{stat['paper_id']}: sections={stat['sections']} "
            f"references={stat['resolved_references']}/"
            f"{stat['bibliography_entries']} resolved"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
