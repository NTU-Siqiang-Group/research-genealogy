#!/usr/bin/env python3
"""Import the current LSM Gold Case into the persistent result store."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._import_support import rewrite_path_prefixes  # noqa: E402
from src.result_store import ResultStore, utc_now  # noqa: E402


RESULT_ID = "lsm-tree-gold-case"


def copy_directory(source: Path, target: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="refresh an existing imported bundle without deleting it",
    )
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[1]
    store = ResultStore(workspace / "data" / "searches")
    try:
        existing = store.get(RESULT_ID)
        if not args.refresh:
            print(f"Gold Case already imported: {existing['open_url']}")
            return 0
    except FileNotFoundError:
        existing = None

    config = yaml.safe_load((workspace / "configs" / "lsm_gold.yaml").read_text(encoding="utf-8"))
    seeds = [item["title"] for item in config.get("must_find", [])]
    if existing:
        record = existing
    else:
        record = store.create(
            {
                "seeds": seeds,
                "topic": config.get("topic"),
                "corpus_cap": config.get("corpus_cap", 150),
                "topic_search_limit": 40,
                "fulltext_limit": 5,
            },
            result_id=RESULT_ID,
        )
    result_dir = store.result_dir(RESULT_ID)
    store.update_status(
        RESULT_ID,
        state="running",
        stage="importing",
        progress=10,
        message="Importing the existing audited Gold Case",
        started_at=utc_now(),
    )

    inputs = result_dir / "inputs"
    for name in ("lsm_gold.yaml", "lsm_fulltext.yaml", "fulltext_retrieval.yaml"):
        shutil.copy2(workspace / "configs" / name, inputs / name)
    (inputs / "import_provenance.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "imported_at": utc_now(),
                "description": "Snapshot of every retained input and output used by the pre-search Gold Case workflow.",
                "source_artifacts": [
                    "data/raw/openalex",
                    "data/raw/pdfs",
                    "data/raw/fulltext/retrieval_index.json",
                    "data/papers/openalex_lsm_corpus.json",
                    "data/evidence/lsm_fulltext_evidence.json",
                    "data/semantic_profiles/run_b",
                    "data/hierarchy/run_b",
                    "data/output/run_b/solution",
                    "data/output/evidence_first",
                    "web/data/inspector.json",
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    copy_directory(workspace / "data" / "raw" / "openalex", result_dir / "raw" / "openalex")
    copy_directory(workspace / "data" / "raw" / "pdfs", result_dir / "raw" / "pdfs")
    shutil.copy2(
        workspace / "data" / "raw" / "fulltext" / "retrieval_index.json",
        result_dir / "raw" / "fulltext" / "retrieval_index.json",
    )
    shutil.copy2(workspace / "data" / "papers" / "openalex_lsm_corpus.json", result_dir / "corpus.json")
    shutil.copy2(workspace / "data" / "output" / "run_b" / "solution" / "citation_graph.json", result_dir / "citation_graph.json")
    shutil.copy2(workspace / "data" / "evidence" / "lsm_fulltext_evidence.json", result_dir / "evidence.json")
    copy_directory(workspace / "data" / "output" / "evidence_first", result_dir / "outputs")

    # These are no longer product-facing inputs, but preserving them makes the
    # imported historical run fully auditable rather than merely viewable.
    legacy = result_dir / "raw" / "legacy_pipeline"
    copy_directory(workspace / "data" / "semantic_profiles" / "run_b", legacy / "semantic_profiles")
    copy_directory(workspace / "data" / "hierarchy" / "run_b", legacy / "hierarchy")
    copy_directory(workspace / "data" / "output" / "run_b" / "solution", legacy / "run_b_solution")

    local_prefix = f"data/searches/{RESULT_ID}/raw/pdfs/"
    rewrite_targets = [
        result_dir / "raw" / "fulltext" / "retrieval_index.json",
        result_dir / "evidence.json",
        result_dir / "outputs" / "evolution_dag.json",
        result_dir / "outputs" / "dominant_tree.json",
    ]
    for target in rewrite_targets:
        if target.is_file():
            rewrite_path_prefixes(target, {"data/raw/pdfs/": local_prefix})

    inspector = json.loads((workspace / "web" / "data" / "inspector.json").read_text(encoding="utf-8"))
    inspector = rewrite_path_prefixes(
        inspector,
        {
            "data/raw/pdfs/": local_prefix,
            "data/output/evidence_first/evolution_dag.json": f"data/searches/{RESULT_ID}/outputs/evolution_dag.json",
            "data/raw/fulltext/retrieval_index.json": f"data/searches/{RESULT_ID}/raw/fulltext/retrieval_index.json",
        },
    )
    fulltext_manifest = yaml.safe_load(
        (workspace / "configs" / "lsm_fulltext.yaml").read_text(encoding="utf-8")
    ) or {}
    fulltext = inspector.setdefault("fulltext", {})
    for document in fulltext_manifest.get("documents", []):
        paper_id = str(document.get("paper_id") or "")
        source = workspace / str(document.get("pdf_path") or "")
        if not paper_id or not source.is_file() or paper_id in fulltext:
            continue
        fulltext[paper_id] = {
            "local_path": local_prefix + source.name,
            "selected_url": None,
            "selected_provider": "configured_manifest",
            "source_page": None,
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "title_score": None,
            "retrieved_at": None,
        }
    (result_dir / "inspector.json").write_text(
        json.dumps(inspector, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    retrieval = json.loads((result_dir / "raw" / "fulltext" / "retrieval_index.json").read_text(encoding="utf-8"))
    retrieved = len(inspector.get("fulltext", {}))
    store.update_status(
        RESULT_ID,
        state="completed",
        stage="completed",
        progress=100,
        message="Imported Gold Case is ready",
        completed_at=utc_now(),
        imported=True,
        imported_request_id=record["fingerprint"],
        summary=inspector.get("summary"),
        fulltext_requested=len(retrieval.get("papers", [])),
        fulltext_retrieved=retrieved,
        warnings=[],
    )
    manifest = store.write_artifact_manifest(RESULT_ID, workspace=workspace)
    print(f"Imported {manifest['artifact_count']} artifacts")
    print(f"Open http://127.0.0.1:4174/web/?result={RESULT_ID}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
