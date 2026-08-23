#!/usr/bin/env python3
"""Mechanically convert cached CoI profiles to SCYCHIC paper JSON files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.schema import PaperRecord  # noqa: E402
from src.semantic_adapter import adapt_paper, write_scychic_input  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default="data/papers/lsm_corpus.json")
    parser.add_argument("--profile-dir", default="data/semantic_profiles/coi")
    parser.add_argument("--output-dir", default="data/hierarchy/scychic_input")
    args = parser.parse_args()

    corpus_payload = json.loads(Path(args.corpus).read_text(encoding="utf-8"))
    profile_dir = Path(args.profile_dir)
    converted = 0
    missing: list[str] = []
    for item in corpus_payload.get("papers", []):
        paper = PaperRecord.from_dict(item)
        safe_id = paper.paper_id.replace(":", "_").replace("/", "_")
        profile_path = profile_dir / f"{safe_id}.json"
        if not profile_path.exists():
            missing.append(paper.paper_id)
            continue
        raw = json.loads(profile_path.read_text(encoding="utf-8"))
        profile = raw.get("parsed_profile", raw)
        adapt_paper(paper, profile, raw_response_path=str(profile_path))
        write_scychic_input(paper, args.output_dir)
        converted += 1

    print(f"converted {converted} profiles")
    if missing:
        print(f"missing profiles: {len(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

