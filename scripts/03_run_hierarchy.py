#!/usr/bin/env python3
"""Run one controlled SCYCHIC hierarchy variant from pre-generated embeddings."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.hierarchy_runner import SCYCHICRunner  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-folder", required=True)
    parser.add_argument("--embeddings-file", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--axis", choices=["problem", "solution", "results", "all"], required=True)
    parser.add_argument("--cluster-sizes", type=int, nargs="+", required=True)
    parser.add_argument("--random-seed", type=int, default=1037)
    args = parser.parse_args()
    SCYCHICRunner().run(
        input_folder=args.input_folder,
        embeddings_file=args.embeddings_file,
        output_file=args.output,
        axis=args.axis,
        cluster_sizes=args.cluster_sizes,
        random_seed=args.random_seed,
    )
    print(f"wrote hierarchy to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

