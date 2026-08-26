#!/usr/bin/env python3
"""Create or resume one persistent genealogy search result."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.local_config import load_env_file  # noqa: E402
from src.result_store import (  # noqa: E402
    ResultStore,
    normalize_search_request,
    request_fingerprint,
)
from src.search_pipeline import SearchPipeline  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", action="append", default=[])
    parser.add_argument("--topic")
    parser.add_argument("--corpus-cap", type=int, default=100)
    parser.add_argument("--topic-search-limit", type=int, default=40)
    parser.add_argument("--fulltext-limit", type=int, default=16)
    parser.add_argument("--store", default="data/searches")
    parser.add_argument("--result-id")
    parser.add_argument("--resume")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    workspace = Path(__file__).resolve().parents[1]
    load_env_file(workspace / ".env")
    store = ResultStore(workspace / args.store)
    if args.resume:
        result_id = args.resume
        store.get(result_id)
    else:
        request = normalize_search_request(
            {
                "seeds": args.seed,
                "topic": args.topic,
                "corpus_cap": args.corpus_cap,
                "topic_search_limit": args.topic_search_limit,
                "fulltext_limit": args.fulltext_limit,
            }
        )
        existing = None if args.force else store.find_completed(request_fingerprint(request))
        if existing:
            print(f"reusing completed result {existing['result_id']}")
            print(f"open http://127.0.0.1:4174{existing['open_url']}")
            return 0
        result_id = store.create(request, result_id=args.result_id)["result_id"]

    print(f"running search {result_id}")
    SearchPipeline(
        store,
        workspace=workspace,
        python_executable=sys.executable,
    ).run(result_id)
    status = store.get(result_id)["status"]
    print(status.get("message"))
    print(f"open http://127.0.0.1:4174/web/?result={result_id}")
    return 0 if status.get("state") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
