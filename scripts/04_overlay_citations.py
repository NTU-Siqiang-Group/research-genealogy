#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.citation_overlay import (  # noqa: E402
    load_corpus,
    load_hierarchy,
    overlay_citations,
    write_overlay,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--hierarchy")
    parser.add_argument("--axis", default="citation_only")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    hierarchy = load_hierarchy(args.hierarchy) if args.hierarchy else None
    papers, edges = overlay_citations(load_corpus(args.corpus), hierarchy, axis=args.axis)
    write_overlay(papers, edges, args.output)
    print(f"wrote {len(edges)} normalized citation edges to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

