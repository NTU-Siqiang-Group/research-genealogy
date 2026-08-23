"""Supplemental research-group evidence from key-author overlap.

This signal deliberately stays separate from technical inheritance.  An
overlap among the first author, second author, or corresponding authors is
stronger than a bibliography-only citation for association browsing, but it
can never establish a genealogy parent on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
import re
import unicodedata
from typing import Any, Iterable, Mapping

from .schema import EvidenceAtom, EvolutionEdge, PaperRecord


@dataclass(frozen=True, slots=True)
class KeyAuthor:
    author_id: str | None
    display_name: str
    normalized_name: str
    roles: tuple[str, ...]
    source_path: str


def _normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).casefold()
    return " ".join(re.findall(r"[a-z0-9]+", normalized))


def _canonical_author_id(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).rstrip("/").rsplit("/", 1)[-1]
    text = text.removeprefix("OPENALEX:")
    return f"OPENALEX:{text.upper()}" if re.fullmatch(r"A\d+", text, re.IGNORECASE) else None


def _key_authors(paper: PaperRecord) -> list[KeyAuthor]:
    structured = paper.metadata.get("authorships") or []
    authors: list[KeyAuthor] = []
    if isinstance(structured, list) and structured:
        for fallback_index, item in enumerate(structured):
            if not isinstance(item, Mapping):
                continue
            nested = item.get("author")
            nested = nested if isinstance(nested, Mapping) else {}
            author_id = _canonical_author_id(
                item.get("author_id") or item.get("id") or nested.get("id")
            )
            name = str(
                item.get("display_name")
                or item.get("raw_author_name")
                or nested.get("display_name")
                or ""
            ).strip()
            index_value = item.get("byline_index", fallback_index)
            index = index_value if isinstance(index_value, int) else fallback_index
            roles: list[str] = []
            if index == 0 or item.get("author_position") == "first":
                roles.append("first_author")
            if index == 1:
                roles.append("second_author")
            if bool(item.get("is_corresponding")):
                roles.append("corresponding_author")
            normalized_name = _normalize_name(name)
            if roles and (author_id or normalized_name):
                source_path = str(
                    item.get("corresponding_source_path")
                    or paper.metadata.get("authorship_source")
                    or "openalex:authorships"
                )
                authors.append(
                    KeyAuthor(
                        author_id,
                        name or str(author_id),
                        normalized_name,
                        tuple(roles),
                        source_path,
                    )
                )
        return authors

    # Backward-compatible fallback for corpora that only retain ordered names.
    # It can recover first/second-author overlap but never guesses correspondence.
    names = paper.metadata.get("authors") or []
    if isinstance(names, list):
        for index, value in enumerate(names[:2]):
            name = str(value).strip()
            normalized_name = _normalize_name(name)
            if normalized_name:
                authors.append(
                    KeyAuthor(
                        None,
                        name,
                        normalized_name,
                        ("first_author" if index == 0 else "second_author",),
                        "corpus:ordered_authors",
                    )
                )
    return authors


def _same_person(left: KeyAuthor, right: KeyAuthor) -> bool:
    if left.author_id and right.author_id:
        return left.author_id == right.author_id
    return bool(
        left.normalized_name
        and left.normalized_name == right.normalized_name
        and len(left.normalized_name.split()) >= 2
    )


def _paper_order(paper: PaperRecord) -> tuple[int, str, str, str]:
    publication_date = str(paper.metadata.get("publication_date") or "")
    return (
        paper.year if paper.year is not None else 9999,
        publication_date,
        paper.title.casefold(),
        paper.paper_id,
    )


def key_author_overlap_edges(papers: Iterable[PaperRecord]) -> list[EvolutionEdge]:
    """Return non-parent medium edges for key-author overlap."""

    records = list(papers)
    keyed = {paper.paper_id: _key_authors(paper) for paper in records}
    edges: list[EvolutionEdge] = []
    for left, right in combinations(records, 2):
        matches: list[tuple[KeyAuthor, KeyAuthor]] = []
        for left_author in keyed[left.paper_id]:
            for right_author in keyed[right.paper_id]:
                if _same_person(left_author, right_author):
                    matches.append((left_author, right_author))
        if not matches:
            continue

        source, target = sorted((left, right), key=_paper_order)
        source_is_left = source.paper_id == left.paper_id
        ordered_matches = [
            pair if source_is_left else (pair[1], pair[0]) for pair in matches
        ]
        stable_id_match = any(old.author_id and old.author_id == new.author_id for old, new in ordered_matches)
        confidence = min(
            0.64,
            (0.60 if stable_id_match else 0.56) + 0.02 * (len(ordered_matches) - 1),
        )
        atoms: list[EvidenceAtom] = []
        summaries: list[str] = []
        for old, new in ordered_matches:
            name = new.display_name or old.display_name
            source_roles = ", ".join(old.roles)
            target_roles = ", ".join(new.roles)
            text = (
                f"Key-author overlap: {name} is {source_roles} in the earlier paper "
                f"and {target_roles} in the later paper. This is supplemental "
                "research-group evidence, not technical inheritance evidence."
            )
            atoms.append(
                EvidenceAtom(
                    paper_id=target.paper_id,
                    cited_paper_id=source.paper_id,
                    section="Authorship metadata",
                    section_type="metadata",
                    text=text,
                    role="KEY_AUTHOR_OVERLAP",
                    entity=name,
                    source_path=f"{old.source_path}; {new.source_path}",
                    confidence=confidence,
                )
            )
            summaries.append(f"{name} ({source_roles} → {target_roles})")
        summary = "; ".join(summaries)
        edges.append(
            EvolutionEdge(
                source=source.paper_id,
                target=target.paper_id,
                citation_exists=False,
                relation="SAME_RESEARCH_GROUP",
                explanation=(
                    "Medium supplemental association from overlapping first, second, "
                    f"or corresponding authors: {summary}. Logical lineage evidence "
                    "takes priority over this research-group signal."
                ),
                evidence=[f"Key-author overlap: {summary}"],
                confidence=confidence,
                dominant=False,
                association_level="medium",
                relation_types=["KEY_AUTHOR_OVERLAP", "SAME_RESEARCH_GROUP"],
                parent_eligible=False,
                evidence_details=atoms,
            )
        )
    return sorted(edges, key=lambda edge: (edge.source, edge.target))
