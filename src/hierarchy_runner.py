"""File-based wrapper around the pinned SCYCHIC hierarchy processor."""

from __future__ import annotations

from collections import Counter
import importlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable


class DeterministicSummaryGenerator:
    """Credential-free token-frequency labeler, not a grounded semantic result."""

    def generate_cluster_summary(
        self, texts: list[str], debug: bool = False
    ) -> tuple[str, str]:
        tokens = Counter(
            token
            for text in texts
            for token in re.findall(r"[a-z][a-z0-9-]+", text.casefold())
            if len(token) >= 5
            and token not in {"title", "problem", "solution", "results"}
        )
        common = [token for token, _ in tokens.most_common(3)]
        name = " / ".join(common) if common else "Unlabeled cluster"
        return name, f"Deterministic token summary for {len(texts)} papers: {name}."

    def cleanup(self) -> None:
        return None


class SCYCHICRunner:
    """Invoke SCYCHIC without using its currently broken top-level CLI."""

    def __init__(
        self,
        *,
        upstream_path: str | Path = "upstream/science-hierarchography/SCYCHIC",
        summary_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.upstream_path = Path(upstream_path).resolve()
        self.summary_factory = summary_factory or DeterministicSummaryGenerator

    def _processor_type(self) -> type:
        if not self.upstream_path.exists():
            raise RuntimeError(f"SCYCHIC checkout not found at {self.upstream_path}")
        path = str(self.upstream_path)
        sys.path.insert(0, path)
        try:
            module = importlib.import_module("pipeline.pipeline")
        except ModuleNotFoundError as error:
            raise RuntimeError(
                f"SCYCHIC dependency {error.name!r} is unavailable; use its "
                "isolated environment"
            ) from error
        finally:
            if sys.path and sys.path[0] == path:
                sys.path.pop(0)

        base = module.PaperProcessor
        summary_factory = self.summary_factory

        class InjectedSummaryProcessor(base):
            @property
            def summarizer(self) -> Any:
                if self._summarizer is None:
                    self._summarizer = summary_factory()
                return self._summarizer

        return InjectedSummaryProcessor

    @staticmethod
    def _canonical_ids(input_folder: str | Path) -> dict[str, str]:
        ids: dict[str, str] = {}
        for path in Path(input_folder).glob("*.json"):
            value = json.loads(path.read_text(encoding="utf-8"))
            records = value if isinstance(value, list) else [value]
            for record in records:
                if isinstance(record, dict) and record.get("title"):
                    paper_id = record.get("paper_id")
                    if paper_id:
                        ids[str(record["title"])] = str(paper_id)
        return ids

    @staticmethod
    def _decorate_leaf_ids(node: Any, ids: dict[str, str]) -> None:
        if isinstance(node, dict):
            if "paper_id" in node and node.get("title") in ids:
                node["scychic_paper_index"] = node["paper_id"]
                node["paper_id"] = ids[str(node["title"])]
            for child in node.get("clusters", []):
                SCYCHICRunner._decorate_leaf_ids(child, ids)
            for child in node.get("children", []):
                SCYCHICRunner._decorate_leaf_ids(child, ids)
        elif isinstance(node, list):
            for child in node:
                SCYCHICRunner._decorate_leaf_ids(child, ids)

    @staticmethod
    def _native(value: Any) -> Any:
        """Convert NumPy scalars emitted by SCYCHIC into JSON-native values."""

        if isinstance(value, dict):
            return {str(key): SCYCHICRunner._native(item) for key, item in value.items()}
        if isinstance(value, list):
            return [SCYCHICRunner._native(item) for item in value]
        if isinstance(value, tuple):
            return [SCYCHICRunner._native(item) for item in value]
        if hasattr(value, "item") and callable(value.item):
            return value.item()
        return value

    def run(
        self,
        *,
        input_folder: str | Path,
        embeddings_file: str | Path,
        output_file: str | Path,
        axis: str,
        cluster_sizes: list[int],
        random_seed: int = 1037,
    ) -> dict[str, Any]:
        if axis == "all":
            embedding_type, embedding_key = "all", None
        elif "." in axis:
            embedding_type, embedding_key = "subkey", axis
        else:
            embedding_type, embedding_key = "key", axis

        processor_type = self._processor_type()
        processor = processor_type(
            base_path=str(Path(output_file).parent / "scychic_work"),
            embedding_generator="qwen",
            summary_generator="injected",
            clustering_method="kmeans",
            clustering_direction="top_down",
            random_seed=random_seed,
            embedding_type=embedding_type,
            embedding_key=embedding_key,
            pre_generated_embeddings_file=str(embeddings_file),
        )
        hierarchy = processor.process_hierarchical_clustering(
            cluster_sizes=cluster_sizes,
            run_seed=random_seed,
            input_folder=str(input_folder),
        )
        hierarchy = self._native(hierarchy)
        self._decorate_leaf_ids(hierarchy, self._canonical_ids(input_folder))
        result = {
            "axis": axis,
            "cluster_sizes": cluster_sizes,
            "random_seed": random_seed,
            "summary_mode": "deterministic_token_frequency",
            "hierarchy": hierarchy,
        }
        output = Path(output_file)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return result


def extract_cluster_paths(result: dict[str, Any]) -> dict[str, list[str]]:
    paths: dict[str, list[str]] = {}

    def visit(node: dict[str, Any], path: list[str]) -> None:
        if "cluster_id" in node:
            current = path + [str(node["cluster_id"])]
        else:
            current = path
        if "paper_id" in node:
            paths[str(node["paper_id"])] = current
        for child in node.get("children", []):
            visit(child, current)

    for cluster in result.get("hierarchy", {}).get("clusters", []):
        visit(cluster, [])
    return paths
