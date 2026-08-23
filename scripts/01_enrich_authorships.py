#!/usr/bin/env python3
"""Hydrate corpus authorships and recover verified PDF correspondence roles."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.authorship_enrichment import apply_front_matter_correspondence  # noqa: E402
from src.citation_overlay import load_corpus  # noqa: E402
from src.local_config import load_env_file  # noqa: E402
from src.openalex_adapter import OpenAlexRetrievalAdapter  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default="data/papers/openalex_lsm_corpus.json")
    parser.add_argument("--output")
    parser.add_argument("--manifest", default="configs/lsm_fulltext.yaml")
    parser.add_argument("--retrieval-index", default="data/raw/fulltext/retrieval_index.json")
    parser.add_argument("--cache-dir", default="data/raw/openalex")
    return parser.parse_args()


def _pdfs_by_paper(manifest_path: Path, retrieval_path: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    if manifest_path.exists():
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        for item in manifest.get("documents") or []:
            if item.get("paper_id") and item.get("pdf_path"):
                paths[str(item["paper_id"])] = Path(str(item["pdf_path"]))
    if retrieval_path.exists():
        retrieval = json.loads(retrieval_path.read_text(encoding="utf-8"))
        for item in retrieval.get("papers") or []:
            if (
                item.get("status") == "retrieved"
                and item.get("paper_id")
                and item.get("local_path")
            ):
                paths.setdefault(str(item["paper_id"]), Path(str(item["local_path"])))
    return paths


async def run(args: argparse.Namespace) -> int:
    load_env_file()
    corpus_path = Path(args.corpus)
    output_path = Path(args.output or args.corpus)
    original = json.loads(corpus_path.read_text(encoding="utf-8"))
    papers = load_corpus(corpus_path)
    adapter = OpenAlexRetrievalAdapter(
        api_key=os.getenv("OPENALEX_API_KEY"), cache_dir=args.cache_dir
    )
    await adapter.hydrate_authorship_metadata(papers)

    recovered = 0
    pdfs = _pdfs_by_paper(Path(args.manifest), Path(args.retrieval_index))
    for paper in papers:
        pdf_path = pdfs.get(paper.paper_id)
        if pdf_path is not None and pdf_path.exists():
            recovered += len(apply_front_matter_correspondence(paper, pdf_path))

    payload = dict(original) if isinstance(original, dict) else {}
    payload["papers"] = [paper.to_dict() for paper in papers]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with_authorships = sum(bool(paper.metadata.get("authorships")) for paper in papers)
    print(
        f"wrote authorship metadata for {with_authorships}/{len(papers)} papers "
        f"to {output_path}; recovered {recovered} corresponding-author roles "
        "from front matter"
    )
    return 0


def main() -> int:
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
