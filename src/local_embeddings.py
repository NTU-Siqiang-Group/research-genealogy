"""Create small, reproducible TF-IDF embeddings for P0 A/B comparisons."""

from __future__ import annotations

import json
from pathlib import Path
import pickle
import re
from typing import Any, Iterable

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from .citation_overlay import load_corpus


def _safe_id(paper_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", paper_id)


def _fit_vectors(texts: list[str], max_features: int) -> tuple[np.ndarray, int]:
    usable = [text if text.strip() else "empty" for text in texts]
    vectorizer = TfidfVectorizer(
        lowercase=True,
        stop_words="english",
        ngram_range=(1, 2),
        max_features=max_features,
        sublinear_tf=True,
    )
    matrix = vectorizer.fit_transform(usable).astype(np.float32).toarray()
    return matrix, len(vectorizer.vocabulary_)


def _dump_embeddings(value: dict[str, Any], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as handle:
        pickle.dump(value, handle)


def prepare_abstract_baseline(
    corpus_path: str | Path,
    input_dir: str | Path,
    embeddings_path: str | Path,
    *,
    max_features: int = 384,
) -> dict[str, int]:
    papers = load_corpus(corpus_path)
    output_dir = Path(input_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    texts = [f"{paper.title}. {paper.abstract or ''}" for paper in papers]
    vectors, vocabulary_size = _fit_vectors(texts, max_features)
    embeddings: dict[str, Any] = {}
    for paper, text, vector in zip(papers, texts, vectors, strict=True):
        payload = {
            "paper_id": paper.paper_id,
            "title": paper.title,
            "abstract": paper.abstract or paper.title,
        }
        file_name = f"{_safe_id(paper.paper_id)}.json"
        (output_dir / file_name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        embeddings[paper.title] = {
            "file_name": file_name,
            "key_embeddings": {
                "all.title_abstract": {"text": text, "embedding": vector}
            },
        }
    _dump_embeddings(embeddings, embeddings_path)
    return {"papers": len(papers), "vocabulary_size": vocabulary_size}


def _flatten_semantic(record: dict[str, Any]) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    for section in ("problem", "solution", "results"):
        section_value = record.get(section)
        if not isinstance(section_value, dict):
            continue
        for key, value in section_value.items():
            fields.append((f"{section}.{key}", str(value or "")))
    return fields


def prepare_semantic_embeddings(
    input_dir: str | Path,
    embeddings_path: str | Path,
    *,
    max_features: int = 384,
) -> dict[str, int]:
    records: list[tuple[Path, dict[str, Any], list[tuple[str, str]]]] = []
    all_texts: list[str] = []
    for path in sorted(Path(input_dir).glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or not value.get("title"):
            continue
        fields = _flatten_semantic(value)
        records.append((path, value, fields))
        all_texts.extend(text for _, text in fields)
    if not records:
        raise ValueError(f"no semantic paper JSON found in {input_dir}")
    matrix, vocabulary_size = _fit_vectors(all_texts, max_features)
    row = 0
    embeddings: dict[str, Any] = {}
    for path, record, fields in records:
        key_embeddings: dict[str, Any] = {}
        for key, field_text in fields:
            key_embeddings[key] = {
                "text": field_text,
                "embedding": matrix[row],
            }
            row += 1
        embeddings[str(record["title"])] = {
            "file_name": path.name,
            "key_embeddings": key_embeddings,
        }
    _dump_embeddings(embeddings, embeddings_path)
    return {"papers": len(records), "vocabulary_size": vocabulary_size}
