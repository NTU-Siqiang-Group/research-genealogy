"""End-to-end persistent genealogy search orchestration."""

from __future__ import annotations

from collections import Counter, deque
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import traceback
from typing import Any, Callable, Iterable

import yaml

from .result_store import ResultStore, utc_now


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def _normalized(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


_SIMILARITY_STOP_WORDS = {
    "and",
    "are",
    "for",
    "from",
    "has",
    "have",
    "into",
    "its",
    "our",
    "that",
    "the",
    "their",
    "this",
    "using",
    "via",
    "with",
}


def _content_tokens(value: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if len(token) >= 3 and token not in _SIMILARITY_STOP_WORDS
    ]


def _paper_terms(paper: dict[str, Any]) -> list[str]:
    """Return dependency-free TF-IDF terms with extra title weight."""

    title = _content_tokens(str(paper.get("title") or ""))
    abstract = _content_tokens(str(paper.get("abstract") or ""))
    title_bigrams = [f"{left}_{right}" for left, right in zip(title, title[1:])]
    abstract_bigrams = [
        f"{left}_{right}" for left, right in zip(abstract, abstract[1:])
    ]
    return title * 3 + abstract + title_bigrams * 3 + abstract_bigrams


def _semantic_seed_scores(
    by_id: dict[str, dict[str, Any]], seed_ids: set[str]
) -> dict[str, float]:
    """Measure title/abstract similarity to the closest resolved seed.

    This is intentionally local and lightweight: candidate selection must still
    work in the public installation without an embedding model.  Its purpose is
    to retain likely descendants when a provider omitted their citation links.
    """

    terms = {paper_id: _paper_terms(paper) for paper_id, paper in by_id.items()}
    document_frequency = Counter(
        term for paper_terms in terms.values() for term in set(paper_terms)
    )
    document_count = max(len(terms), 1)
    vectors: dict[str, dict[str, float]] = {}
    for paper_id, paper_terms in terms.items():
        term_frequency = Counter(paper_terms)
        vector = {
            term: (1.0 + math.log(count))
            * (math.log((document_count + 1) / (document_frequency[term] + 1)) + 1.0)
            for term, count in term_frequency.items()
        }
        norm = math.sqrt(sum(weight * weight for weight in vector.values())) or 1.0
        vectors[paper_id] = {term: weight / norm for term, weight in vector.items()}

    seed_vectors = [vectors[paper_id] for paper_id in seed_ids if paper_id in vectors]
    scores: dict[str, float] = {}
    for paper_id, vector in vectors.items():
        scores[paper_id] = max(
            (
                sum(weight * seed.get(term, 0.0) for term, weight in vector.items())
                for seed in seed_vectors
            ),
            default=0.0,
        )
    return scores


def select_fulltext_candidates(
    corpus: dict[str, Any], seeds: Iterable[str], limit: int
) -> list[dict[str, Any]]:
    """Prioritize seeds, then rank candidates by content with a citation bonus."""

    if limit <= 0:
        return []
    papers = [item for item in corpus.get("papers", []) if isinstance(item, dict)]
    by_id = {str(item.get("paper_id")): item for item in papers if item.get("paper_id")}
    seed_queries = list(seeds)
    seed_ids: set[str] = set()
    for query in seed_queries:
        query_normalized = _normalized(query)
        query_prefix = _normalized(query.split(":", 1)[0])
        for paper_id, paper in by_id.items():
            title = str(paper.get("title") or "")
            if (
                query.casefold() in {paper_id.casefold(), str(paper.get("metadata", {}).get("doi") or "").casefold()}
                or _normalized(title) == query_normalized
                or (":" in query and _normalized(title) == query_prefix)
            ):
                seed_ids.add(paper_id)

    adjacency: dict[str, set[str]] = {paper_id: set() for paper_id in by_id}
    for paper_id, paper in by_id.items():
        for related in [*(paper.get("references") or []), *(paper.get("citations") or [])]:
            related_id = str(related)
            if related_id in by_id:
                adjacency[paper_id].add(related_id)
                adjacency[related_id].add(paper_id)
    distances = {paper_id: 10_000 for paper_id in by_id}
    queue: deque[str] = deque()
    for seed_id in seed_ids:
        distances[seed_id] = 0
        queue.append(seed_id)
    while queue:
        current = queue.popleft()
        for neighbor in adjacency[current]:
            if distances[neighbor] > distances[current] + 1:
                distances[neighbor] = distances[current] + 1
                queue.append(neighbor)

    def is_direct_descendant(paper: dict[str, Any]) -> bool:
        return bool(seed_ids & set(map(str, paper.get("references") or [])))

    semantic_scores = _semantic_seed_scores(by_id, seed_ids)

    ranked = sorted(
        by_id.items(),
        key=lambda item: (
            item[0] in seed_ids,
            # A provider citation is useful but not decisive: OpenAlex can
            # expose an OA paper with an empty referenced_works list.  A small
            # bonus preserves that signal while title/abstract similarity can
            # still rescue metadata-missing descendants such as InfiniGen.
            semantic_scores[item[0]]
            + (0.01 if is_direct_descendant(item[1]) else 0.0),
            item[1].get("year") or 0,
            item[1].get("metadata", {}).get("citation_count") or 0,
            str(item[1].get("title") or "").casefold(),
        ),
        reverse=True,
    )[:limit]
    return [
        {
            "paper_id": paper_id,
            "title": paper.get("title"),
            "year": paper.get("year"),
            "distance_from_seed": None if distances[paper_id] == 10_000 else distances[paper_id],
            "semantic_similarity": round(semantic_scores[paper_id], 6),
            "selection_reason": (
                "seed"
                if paper_id in seed_ids
                else "direct_descendant"
                if is_direct_descendant(paper)
                else "semantic_neighbor"
                if semantic_scores[paper_id] > 0
                else "nearest_citation_neighbor"
                if distances[paper_id] < 10_000
                else "topic_candidate"
            ),
        }
        for paper_id, paper in ranked
    ]


class SearchPipeline:
    STAGES = {
        "preparing": 5,
        "corpus": 15,
        "citations": 35,
        "fulltext": 48,
        "evidence": 72,
        "genealogy": 84,
        "inspector": 93,
        "manifest": 98,
        "completed": 100,
    }

    def __init__(
        self,
        store: ResultStore,
        *,
        workspace: str | Path,
        python_executable: str | Path | None = None,
        command_runner: CommandRunner = subprocess.run,
    ) -> None:
        self.store = store
        self.workspace = Path(workspace).resolve()
        self.python = str(python_executable or sys.executable)
        self.command_runner = command_runner

    def _stage(self, result_id: str, stage: str, message: str) -> None:
        self.store.update_status(
            result_id,
            state="running",
            stage=stage,
            progress=self.STAGES[stage],
            message=message,
        )

    def _run_command(
        self,
        result_id: str,
        arguments: list[str],
        *,
        allowed_returncodes: set[int] = {0},
    ) -> subprocess.CompletedProcess[str]:
        log_path = self.store.result_dir(result_id) / "logs" / "pipeline.log"
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"\n[{utc_now()}] $ {json.dumps(arguments, ensure_ascii=False)}\n")
            result = self.command_runner(
                arguments,
                cwd=self.workspace,
                env=os.environ.copy(),
                capture_output=True,
                text=True,
            )
            log.write(result.stdout or "")
            if result.stderr:
                log.write("\n[stderr]\n" + result.stderr)
            log.write(f"\n[exit {result.returncode}]\n")
        if result.returncode not in allowed_returncodes:
            detail = (result.stderr or result.stdout or "no output")[-2000:]
            raise RuntimeError(
                f"pipeline command failed with exit {result.returncode}: {detail}"
            )
        return result

    def run(self, result_id: str) -> None:
        directory = self.store.result_dir(result_id)
        request = self.store.get(result_id)
        try:
            self.store.update_status(
                result_id,
                state="running",
                stage="preparing",
                progress=self.STAGES["preparing"],
                message="Saving configuration snapshots",
                started_at=utc_now(),
                error=None,
            )
            inputs = directory / "inputs"
            search_config = {
                "topic": request["topic"],
                "corpus_cap": request["corpus_cap"],
                "must_find": [
                    {"key": f"seed_{index + 1}", "title": seed}
                    for index, seed in enumerate(request["seeds"])
                ],
            }
            (inputs / "search.yaml").write_text(
                yaml.safe_dump(search_config, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            retrieval_snapshot = inputs / "fulltext_retrieval.yaml"
            shutil.copy2(
                self.workspace / "configs" / "fulltext_retrieval.yaml",
                retrieval_snapshot,
            )
            (inputs / "fulltext_manifest.yaml").write_text(
                yaml.safe_dump(
                    {"documents": [], "entity_origins": []},
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            corpus_path = directory / "corpus.json"
            self._stage(result_id, "corpus", "Resolving seeds and building the bounded OpenAlex corpus")
            self._run_command(
                result_id,
                [
                    self.python,
                    "scripts/01_build_corpus.py",
                    "--provider",
                    request["provider"],
                    "--config",
                    str(inputs / "search.yaml"),
                    "--output",
                    str(corpus_path),
                    "--cache-dir",
                    str(directory / "raw" / "openalex"),
                    "--paper-dir",
                    str(directory / "raw" / "pdfs"),
                    "--topic-search-limit",
                    str(request["topic_search_limit"]),
                ],
                allowed_returncodes={0, 2},
            )
            corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
            unresolved = list(corpus.get("unresolved_seeds") or [])
            if len(unresolved) == len(request["seeds"]):
                raise RuntimeError("none of the requested seed papers could be resolved")

            citation_path = directory / "citation_graph.json"
            self._stage(result_id, "citations", "Normalizing in-corpus citation directions")
            self._run_command(
                result_id,
                [
                    self.python,
                    "scripts/04_overlay_citations.py",
                    "--corpus",
                    str(corpus_path),
                    "--output",
                    str(citation_path),
                ],
            )

            self._stage(result_id, "fulltext", "Retrieving and title-validating prioritized full text")
            candidates = select_fulltext_candidates(
                corpus, request["seeds"], request["fulltext_limit"]
            )
            selection_path = directory / "inputs" / "fulltext_selection.json"
            selection_path.write_text(
                json.dumps(
                    {
                        "method": "seed_then_hybrid_semantic_relevance",
                        "papers": candidates,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            retrieval_index = directory / "raw" / "fulltext" / "retrieval_index.json"
            if candidates:
                retrieval_arguments = [
                    self.python,
                    "scripts/03_retrieve_fulltext.py",
                    "--corpus",
                    str(corpus_path),
                    "--config",
                    str(retrieval_snapshot),
                    "--output-dir",
                    str(directory / "raw" / "pdfs"),
                    "--index",
                    str(retrieval_index),
                ]
                for candidate in candidates:
                    retrieval_arguments.extend(["--paper-id", candidate["paper_id"]])
                self._run_command(
                    result_id,
                    retrieval_arguments,
                    allowed_returncodes={0, 2},
                )
            else:
                retrieval_index.write_text(
                    json.dumps(
                        {
                            "method": "fulltext_disabled",
                            "retrieved_at": utc_now(),
                            "papers": [],
                        },
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )

            evidence_path = directory / "evidence.json"
            self._stage(result_id, "evidence", "Extracting section-aware relation evidence")
            self._run_command(
                result_id,
                [
                    self.python,
                    "scripts/04_extract_relation_evidence.py",
                    "--corpus",
                    str(corpus_path),
                    "--manifest",
                    str(inputs / "fulltext_manifest.yaml"),
                    "--retrieval-index",
                    str(retrieval_index),
                    "--output",
                    str(evidence_path),
                ],
            )

            output_dir = directory / "outputs"
            self._stage(result_id, "genealogy", "Inferring evidence-first genealogy edges")
            self._run_command(
                result_id,
                [
                    self.python,
                    "scripts/05_infer_tree.py",
                    "--overlay",
                    str(citation_path),
                    "--evidence",
                    str(evidence_path),
                    "--axis",
                    "citation_only",
                    "--output-dir",
                    str(output_dir),
                ],
            )

            inspector_path = directory / "inspector.json"
            self._stage(result_id, "inspector", "Packaging the reopenable browser result")
            self._run_command(
                result_id,
                [
                    self.python,
                    "scripts/07_build_inspector_data.py",
                    "--dag",
                    str(output_dir / "evolution_dag.json"),
                    "--retrieval",
                    str(retrieval_index),
                    "--topic",
                    request["topic"],
                    "--output",
                    str(inspector_path),
                ],
            )
            inspector = json.loads(inspector_path.read_text(encoding="utf-8"))
            retrieval = json.loads(retrieval_index.read_text(encoding="utf-8"))
            retrieved_count = sum(
                item.get("status") == "retrieved"
                for item in retrieval.get("papers", [])
                if isinstance(item, dict)
            )
            warnings = []
            if unresolved:
                warnings.append(f"Unresolved seeds: {', '.join(unresolved)}")
            if candidates and retrieved_count == 0:
                warnings.append("No prioritized full text could be retrieved; the result is citation-only.")
            self._stage(result_id, "manifest", "Hashing every saved artifact")
            self.store.update_status(
                result_id,
                state="completed",
                stage="completed",
                progress=100,
                message="Search result is ready",
                completed_at=utc_now(),
                summary=inspector.get("summary"),
                unresolved_seeds=unresolved,
                fulltext_requested=len(candidates),
                fulltext_retrieved=retrieved_count,
                warnings=warnings,
            )
            self.store.write_artifact_manifest(result_id, workspace=self.workspace)
        except Exception as error:
            error_text = f"{type(error).__name__}: {error}"
            (directory / "logs" / "traceback.log").write_text(
                traceback.format_exc(), encoding="utf-8"
            )
            self.store.update_status(
                result_id,
                state="failed",
                stage="failed",
                message=error_text,
                error=error_text,
                failed_at=utc_now(),
            )
            self.store.write_artifact_manifest(result_id, workspace=self.workspace)
