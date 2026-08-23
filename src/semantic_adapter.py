"""Literal CoI-to-SCYCHIC field mapping for the P0 direct baseline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .schema import PaperRecord, SemanticProfile


COI_ALIASES: dict[str, tuple[str, ...]] = {
    "background": ("background", "Background"),
    "novelty": ("novelty", "Novelty"),
    "contribution": ("contribution", "Contribution"),
    "methods": ("methods", "Methods", "method", "Method"),
    "detail_reason": ("detail_reason", "Detail reason", "Detail Reason"),
    "limitation": ("limitation", "Limitation", "limitations", "Limitations"),
    "experiment": ("experiment", "Experiment"),
    "entities": ("entities", "Entities"),
    "selected_references": (
        "selected_references",
        "Three relevant references",
        "three_relevant_references",
    ),
}


def normalize_coi_profile(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize capitalization only; do not reinterpret CoI semantics."""

    normalized: dict[str, Any] = {}
    for canonical, aliases in COI_ALIASES.items():
        value = next((raw[name] for name in aliases if name in raw), None)
        if value not in (None, "", []):
            normalized[canonical] = value
    return normalized


def map_coi_to_scychic(raw: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    """Apply the intentionally imperfect mechanical mapping from the P0 plan."""

    coi = normalize_coi_profile(raw)

    def text(key: str) -> str:
        value = coi.get(key, "")
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    return {
        "problem": {
            "overarching problem domain": "",
            "challenges/difficulties": text("limitation"),
            "research question/goal": text("contribution"),
            "novelty of the problem": "",
            "knowns or prior work": text("background"),
        },
        "solution": {
            "overarching solution domain": text("detail_reason"),
            "knowns or prior work": "",
            "solution approach": text("methods"),
            "novelty of the solution": text("novelty"),
        },
        "results": {
            "findings/results": text("experiment"),
            "potential impact of the results": text("contribution"),
        },
    }


def adapt_paper(
    paper: PaperRecord,
    raw_coi_profile: Mapping[str, Any],
    *,
    raw_response_path: str | None = None,
) -> PaperRecord:
    paper.semantic_profile = SemanticProfile(
        coi=normalize_coi_profile(raw_coi_profile),
        scychic=map_coi_to_scychic(raw_coi_profile),
        raw_response_path=raw_response_path,
    )
    return paper


def write_scychic_input(paper: PaperRecord, output_dir: str | Path) -> Path:
    """Write the one-paper-per-file shape expected by SCYCHIC/generate.py."""

    if not paper.semantic_profile:
        raise ValueError(f"paper {paper.paper_id} has no semantic profile")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    safe_id = paper.paper_id.replace(":", "_").replace("/", "_")
    path = output / f"{safe_id}.json"
    payload = {
        "paper_id": paper.paper_id,
        "title": paper.title,
        **paper.semantic_profile.scychic,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path

