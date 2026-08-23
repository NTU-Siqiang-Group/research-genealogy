#!/usr/bin/env python3
"""Exercise SCYCHIC top-down clustering with a tiny local embedding fixture."""

from __future__ import annotations

import json
from pathlib import Path
import pickle
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.hierarchy_runner import SCYCHICRunner, extract_cluster_paths  # noqa: E402


PAPERS = [
    ("S2:monkey", "Monkey", "analytical optimization", [1.0, 0.0]),
    ("S2:dostoevsky", "Dostoevsky", "analytical compaction", [0.9, 0.1]),
    ("S2:bush", "LSM-Bush", "analytical design continuum", [0.8, 0.2]),
    ("S2:ruskey", "RusKey", "learned dynamic adaptation", [0.0, 1.0]),
    ("S2:camal", "CAMAL", "active learning tuning", [0.1, 0.9]),
    ("S2:arce", "ArceKV", "dynamic transition optimization", [0.2, 0.8]),
]


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        input_dir = root / "papers"
        input_dir.mkdir()
        embeddings = {}
        for index, (paper_id, title, solution, vector) in enumerate(PAPERS):
            payload = {
                "paper_id": paper_id,
                "title": title,
                "problem": {"research question/goal": "optimize LSM trees"},
                "solution": {"solution approach": solution},
            }
            (input_dir / f"{index}.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            embeddings[title] = {
                "file_name": f"{index}.json",
                "key_embeddings": {
                    "solution.solution approach": {
                        "text": solution,
                        "embedding": vector,
                    }
                },
            }
        embedding_file = root / "embeddings.pkl"
        with embedding_file.open("wb") as handle:
            pickle.dump(embeddings, handle)
        output = root / "hierarchy.json"
        result = SCYCHICRunner().run(
            input_folder=input_dir,
            embeddings_file=embedding_file,
            output_file=output,
            axis="solution",
            cluster_sizes=[4, 2],
            random_seed=1037,
        )
        paths = extract_cluster_paths(result)
        if set(paths) != {paper_id for paper_id, *_ in PAPERS}:
            raise RuntimeError(f"SCYCHIC dropped canonical paper IDs: {paths}")
        print(json.dumps(paths, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
