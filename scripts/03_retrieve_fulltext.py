#!/usr/bin/env python3
"""Retrieve validated PDFs with fallbacks when OpenAlex has no full text."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.citation_overlay import load_corpus  # noqa: E402
from src.fulltext_retriever import (  # noqa: E402
    FullTextResolver,
    author_web_search_from_environment,
    write_retrieval_index,
)
from src.local_config import load_env_file  # noqa: E402


def main() -> int:
    load_env_file(Path(__file__).resolve().parents[1] / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--config", default="configs/fulltext_retrieval.yaml")
    parser.add_argument("--paper-id", action="append", default=[])
    parser.add_argument("--missing-only", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output-dir", default="data/raw/pdfs")
    parser.add_argument("--index", default="data/raw/fulltext/retrieval_index.json")
    args = parser.parse_args()

    papers = load_corpus(args.corpus)
    requested = set(args.paper_id)
    if requested:
        selected = [paper for paper in papers if paper.paper_id in requested]
        missing_ids = requested - {paper.paper_id for paper in selected}
        if missing_ids:
            raise ValueError(f"paper IDs absent from corpus: {sorted(missing_ids)}")
    elif args.missing_only:
        selected = [paper for paper in papers if not paper.pdf_url][: args.limit]
    else:
        raise ValueError("pass --paper-id at least once or use --missing-only")

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8")) or {}
    auto_author_homepages = bool(config.get("auto_author_homepages", True))
    search_timeout = float(config.get("author_search_timeout_seconds", 45))
    author_web_search = (
        author_web_search_from_environment(timeout_seconds=search_timeout)
        if auto_author_homepages
        else None
    )
    resolver = FullTextResolver(
        author_pages=config.get("author_pages") or [],
        overrides=config.get("overrides") or {},
        use_arxiv=bool(config.get("use_arxiv", True)),
        use_dblp=bool(config.get("use_dblp", True)),
        use_doi=bool(config.get("use_doi", True)),
        auto_author_homepages=auto_author_homepages,
        author_web_search=author_web_search,
    )
    results = []
    for paper in selected:
        result = resolver.retrieve(paper, args.output_dir)
        results.append(result)
        provider = f" via {result.selected_provider}" if result.selected_provider else ""
        print(f"{paper.paper_id}: {result.status}{provider}")
        if result.local_path:
            print(f"  {result.local_path}")
    write_retrieval_index(results, args.index)
    print(
        json.dumps(
            {
                "requested": len(selected),
                "retrieved": sum(result.status == "retrieved" for result in results),
                "not_found": sum(result.status != "retrieved" for result in results),
                "index": args.index,
            },
            indent=2,
        )
    )
    if requested and any(result.status != "retrieved" for result in results):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
