#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation import evaluate_gold, write_evaluation  # noqa: E402
from src.schema import EvolutionDAG  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dag", required=True)
    parser.add_argument("--gold", default="configs/lsm_gold.yaml")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    gold = yaml.safe_load(Path(args.gold).read_text(encoding="utf-8"))
    result = evaluate_gold(EvolutionDAG.load(args.dag), gold)
    write_evaluation(result, args.output)
    print(f"wrote evaluation to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

