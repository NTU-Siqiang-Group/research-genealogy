#!/usr/bin/env python3
"""Run CoI's literal extraction prompt over cached title/abstract content."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.citation_overlay import load_corpus  # noqa: E402
from src.local_config import load_env_file  # noqa: E402
from src.semantic_extractor import (  # noqa: E402
    CoISemanticExtractor,
    llm_call_from_environment,
)


async def run(args: argparse.Namespace) -> int:
    load_env_file()
    extractor = CoISemanticExtractor(llm_call_from_environment())
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    papers = load_corpus(args.corpus)
    if args.paper_id:
        papers = [paper for paper in papers if paper.paper_id == args.paper_id]
        if not papers:
            raise RuntimeError(f"paper not found in corpus: {args.paper_id}")
    if args.limit is not None:
        papers = papers[: args.limit]
    semaphore = asyncio.Semaphore(args.max_concurrency)

    async def extract_one(paper) -> bool:
        safe_id = paper.paper_id.replace(":", "_").replace("/", "_")
        output = output_dir / f"{safe_id}.json"
        if output.exists() and not args.force:
            print(f"cached {output}")
            return True
        try:
            async with semaphore:
                content = f"Title: {paper.title}\nAbstract: {paper.abstract or ''}"
                result = await extractor.extract(content, args.topic)
            result.update(
                {
                    "paper_id": paper.paper_id,
                    "title": paper.title,
                    "source_tier": "title_abstract",
                }
            )
            output.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"wrote {output}")
            return True
        except Exception as error:
            print(f"failed {paper.paper_id}: {error}", file=sys.stderr)
            return False

    results = await asyncio.gather(*(extract_one(paper) for paper in papers))
    failures = len(results) - sum(results)
    print(f"profiles ready: {sum(results)}/{len(results)}; failures: {failures}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default="data/papers/lsm_corpus.json")
    parser.add_argument("--output-dir", default="data/semantic_profiles/coi")
    parser.add_argument(
        "--topic", default="LSM-tree structural and workload-adaptive optimization"
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--paper-id")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--max-concurrency", type=int, default=4)
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
