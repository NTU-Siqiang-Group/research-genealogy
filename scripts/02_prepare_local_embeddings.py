#!/usr/bin/env python3
"""Prepare credential-free TF-IDF embeddings for Run A or Run B."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.local_embeddings import (  # noqa: E402
    prepare_abstract_baseline,
    prepare_semantic_embeddings,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["abstract", "semantic"], required=True)
    parser.add_argument("--corpus", default="data/papers/lsm_corpus.json")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--embeddings-file", required=True)
    parser.add_argument("--max-features", type=int, default=384)
    args = parser.parse_args()
    if args.mode == "abstract":
        stats = prepare_abstract_baseline(
            args.corpus,
            args.input_dir,
            args.embeddings_file,
            max_features=args.max_features,
        )
    else:
        stats = prepare_semantic_embeddings(
            args.input_dir,
            args.embeddings_file,
            max_features=args.max_features,
        )
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
