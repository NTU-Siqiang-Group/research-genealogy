#!/usr/bin/env python3
"""Build the bounded LSM P0 corpus through OpenAlex or the pinned CoI client."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.corpus_builder import CoIRetrievalAdapter, CorpusBuilder  # noqa: E402
from src.local_config import load_env_file  # noqa: E402
from src.openalex_adapter import OpenAlexRetrievalAdapter  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--provider",
        choices=["openalex", "semantic-scholar"],
        default="openalex",
    )
    parser.add_argument("--config", default="configs/lsm_gold.yaml")
    parser.add_argument("--output", default="data/papers/lsm_corpus.json")
    parser.add_argument("--cache-dir")
    parser.add_argument("--paper-dir", default="data/raw/pdfs")
    parser.add_argument("--topic-search-limit", type=int, default=50)
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    load_env_file()
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    seeds = [entry["title"] for entry in config["must_find"]]
    if args.provider == "openalex":
        adapter = OpenAlexRetrievalAdapter(
            api_key=os.getenv("OPENALEX_API_KEY"),
            cache_dir=args.cache_dir or "data/raw/openalex",
        )
    else:
        adapter = CoIRetrievalAdapter(
            cache_dir=args.cache_dir or "data/raw/semantic_scholar",
            paper_dir=args.paper_dir,
        )
    result = await CorpusBuilder(adapter).build(
        topic=config["topic"],
        seeds=seeds,
        corpus_cap=int(config.get("corpus_cap", 150)),
        topic_search_limit=args.topic_search_limit,
    )
    result.dump(args.output)
    print(f"wrote {len(result.papers)} papers to {args.output}")
    if result.unresolved_seeds:
        print("unresolved must-find papers:")
        for title in result.unresolved_seeds:
            print(f"- {title}")
        return 2
    print("all must-find papers resolved")
    return 0


def main() -> int:
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
