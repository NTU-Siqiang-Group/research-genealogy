"""Section-aware, auditable relationship evidence extraction.

This module deliberately does not use embeddings or clusters.  It turns local
full text into evidence atoms, resolves numeric citation markers to canonical
corpus IDs, and assigns the weak/medium/strong association levels used by the
genealogy layer.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import subprocess
import unicodedata
from typing import Any, Iterable, Mapping

from .schema import EvidenceAtom, EvolutionEdge, PaperRecord


LEVEL_RANK = {"weak": 0, "medium": 1, "strong": 2}

LIMITATION_CUES = re.compile(
    r"\b(limit(?:ation|ed|ing|s)?|deficien|drawback|shortcoming|fails?|"
    r"sub[- ]optimal|not known a priori|remains? open|overlooked|bottleneck)\b",
    re.IGNORECASE,
)
INHERITANCE_CUES = re.compile(
    r"\b(extend(?:s|ed|ing)?|generaliz(?:e|es|ed|ing)|build(?:s|ing)? on|"
    r"based on|adopt(?:s|ed|ing)?|incorporat(?:e|es|ed|ing)|following|"
    r"use(?:s|d|ing)?|derived? from)\b",
    re.IGNORECASE,
)
BASELINE_CUES = re.compile(
    r"\b(baseline(?:s)?|compare(?:s|d|ing)?(?: with| against)?|"
    r"comparative evaluation(?:s)?(?: with| against)?|"
    r"comparison(?:s)?(?: with| against| to)?|evaluat(?:e|es|ed|ing) against|"
    r"versus|vs\.?|outperform(?:s|ed|ing)?|following the setting)\b",
    re.IGNORECASE,
)
DISCUSSION_CUES = re.compile(
    r"\b(point(?:s|ed)? out|show(?:s|ed)?|propos(?:e|es|ed)|"
    r"introduc(?:e|es|ed)|require(?:s|d)?|assum(?:e|es|ed)|"
    r"design(?:s|ed)?|model(?:s|ed)?|approach|strategy|technique|method)\b",
    re.IGNORECASE,
)
CITATION_RE = re.compile(r"\[(\d+(?:\s*[,;\-–]\s*\d+)*)\]")
HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)\s+(.{2,100})$")
KNOWN_HEADING_WORDS = (
    "abstract",
    "introduction",
    "background",
    "prelim",
    "related work",
    "overview",
    "method",
    "design",
    "algorithm",
    "implementation",
    "evaluation",
    "experiment",
    "conclusion",
    "acknowledg",
)


@dataclass(slots=True)
class FullTextSection:
    heading: str
    section_type: str
    text: str


@dataclass(slots=True)
class FullTextDocument:
    paper_id: str
    sections: list[FullTextSection]
    references: dict[int, str] = field(default_factory=dict)
    reference_ids: dict[int, str] = field(default_factory=dict)
    source_path: str | None = None


@dataclass(slots=True)
class EntityOrigin:
    entity: str
    paper_id: str
    aliases: list[str] = field(default_factory=list)
    evidence_text: str = ""
    section: str = "unknown"
    source_path: str | None = None


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    return " ".join(re.findall(r"[a-z0-9]+", value))


def _clean_pdf_text(value: str) -> str:
    value = value.replace("\u00ad", "").replace("\r", "")
    # Repair words split at a PDF line boundary ("intro-\nduce").
    value = re.sub(r"(?<=\w)-\n\s*(?=[a-z])", "", value)
    return value


def _section_type(number: str, title: str, parent_title: str = "") -> str:
    name = f"{parent_title} {title}".casefold()
    title_name = title.casefold()
    if "related work" in title_name:
        return "related_work"
    if "introduction" in name or number == "1" or number.startswith("1."):
        return "introduction"
    if any(word in name for word in ("prelim", "background")):
        return "preliminary"
    if any(
        word in title_name
        for word in ("experiment", "evaluation", "performance", "benchmark")
    ):
        return "evaluation"
    if any(
        word in title_name
        for word in (
            "method",
            "design",
            "system",
            "approach",
            "algorithm",
            "implementation",
            "overview",
            "transition",
            "compaction",
            "controller",
            "decision",
            "optimiz",
            "training",
            "model",
            "lsm-tree",
            "flsm",
        )
    ):
        return "method"
    return "other"


def _looks_like_heading(number: str, title: str) -> bool:
    if len(title.split()) > 14:
        return False
    if len(re.findall(r"[A-Za-z]", title)) < 4:
        return False
    major = number.split(".", 1)[0]
    if not (major.isdigit() and 0 < int(major) < 100):
        return False
    lowered = title.casefold()
    known = any(word in lowered for word in KNOWN_HEADING_WORDS)
    mostly_upper = title.upper() == title and any(char.isalpha() for char in title)
    subsection_title = (
        "." in number
        and title[:1].isupper()
        and len(title.split()) <= 8
        and not title.endswith(('.', '?', '!', ';'))
        and not re.search(r"\d", title)
    )
    return known or mostly_upper or subsection_title


def _looks_like_standalone_heading(
    title: str, *, number: str | None
) -> bool:
    if len(title) > 100 or len(title.split()) > 14:
        return False
    if len(re.findall(r"[A-Za-z]", title)) < 4:
        return False
    if title.endswith(('.', '?', '!', ';')):
        return False
    lowered = title.casefold()
    known = any(word in lowered for word in KNOWN_HEADING_WORDS)
    mostly_upper = title.upper() == title and any(char.isalpha() for char in title)
    if mostly_upper:
        return known or number is not None
    return bool(
        number
        and "." in number
        and "," not in title
        and title[:1].isupper()
        and not title.endswith(('.', '?', '!', ';'))
    )


def _is_page_header(value: str) -> bool:
    lowered = value.casefold()
    return (
        "sigmod’" in lowered
        or "sigmod'" in lowered
        or "proceedings of" in lowered
        or "learning to optimize lsm-trees" in lowered
    )


def split_sections(text: str) -> tuple[list[FullTextSection], str]:
    """Split pdftotext output into numbered sections and bibliography text."""

    text = _clean_pdf_text(text)
    reference_match = re.search(r"(?m)^\s*REFERENCES\s*$", text)
    body = text[: reference_match.start()] if reference_match else text
    bibliography = text[reference_match.end() :] if reference_match else ""

    sections: list[FullTextSection] = []
    current_heading = "front_matter"
    current_number = "0"
    current_parent = ""
    current_lines: list[str] = []
    top_titles: dict[str, str] = {}

    def flush() -> None:
        cleaned = "\n".join(line.rstrip() for line in current_lines).strip()
        if cleaned:
            sections.append(
                FullTextSection(
                    heading=current_heading,
                    section_type=_section_type(
                        current_number, current_heading, current_parent
                    ),
                    text=cleaned,
                )
            )

    pending_number: str | None = None
    for raw_line in body.splitlines():
        stripped = raw_line.strip()
        match = HEADING_RE.match(stripped)
        number_only = re.fullmatch(r"\d+(?:\.\d+)*", stripped)
        if number_only and 0 < int(stripped.split(".", 1)[0]) < 100:
            pending_number = stripped
            continue

        split_heading = bool(
            stripped
            and _looks_like_standalone_heading(
                stripped, number=pending_number
            )
        )
        if pending_number and stripped and _is_page_header(stripped):
            continue

        if match and _looks_like_heading(match.group(1), match.group(2)):
            flush()
            current_lines = []
            current_number, title = match.group(1), match.group(2).strip()
            pending_number = None
        elif split_heading:
            flush()
            current_lines = []
            current_number = pending_number or "0"
            title = stripped
            pending_number = None
        else:
            if stripped:
                pending_number = None
            current_lines.append(raw_line)
            continue

        major = current_number.split(".", 1)[0]
        if current_number != "0" and "." not in current_number:
            top_titles[major] = title
            current_parent = title
        else:
            current_parent = top_titles.get(major, "")
        current_heading = f"{current_number} {title}"
    flush()
    return sections, bibliography


def parse_bibliography(text: str) -> dict[int, str]:
    starts = list(re.finditer(r"(?m)^\s*\[(\d+)\]\s+", text))
    result: dict[int, str] = {}
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        entry = re.sub(r"\s+", " ", text[match.end() : end]).strip()
        result[int(match.group(1))] = entry
    return result


def pdf_to_document(pdf_path: str | Path, paper_id: str) -> FullTextDocument:
    path = Path(pdf_path)
    completed = subprocess.run(
        # ``-raw`` preserves the content-stream/column order.  On two-column
        # papers this keeps the right-hand continuation of the Introduction
        # after its heading instead of interleaving it into the Abstract.
        ["pdftotext", "-raw", str(path), "-"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    text = completed.stdout.decode("utf-8", errors="replace")
    sections, _bibliography = split_sections(text)
    return FullTextDocument(
        paper_id=paper_id,
        sections=sections,
        # Some two-column PDFs emit part of the right bibliography column just
        # before the REFERENCES heading. Parsing the full text recovers that
        # displaced block; line-anchored numeric markers keep body citations
        # out in the normal case.
        references=parse_bibliography(text),
        source_path=str(path),
    )


def resolve_bibliography(
    document: FullTextDocument, papers: Iterable[PaperRecord]
) -> dict[int, str]:
    """Map local bibliography numbers to stable corpus IDs."""

    candidates = list(papers)
    target = next((paper for paper in candidates if paper.paper_id == document.paper_id), None)
    resolved: dict[int, str] = {}
    for number, reference in document.references.items():
        normalized_reference = _normalize(reference)
        best: tuple[float, str] | None = None
        for paper in candidates:
            if (
                target is not None
                and target.year is not None
                and paper.year is not None
                and paper.year > target.year
            ):
                continue
            doi = _normalize(str(paper.metadata.get("doi") or "").removeprefix("https doi org "))
            normalized_title = _normalize(paper.title)
            title_tokens = set(normalized_title.split())
            reference_tokens = set(normalized_reference.split())
            overlap = (
                len(title_tokens & reference_tokens) / len(title_tokens)
                if title_tokens
                else 0.0
            )
            sequence = SequenceMatcher(
                None, normalized_title, normalized_reference
            ).ratio()
            exact = bool(
                normalized_title
                and len(normalized_title) >= 8
                and normalized_title in normalized_reference
            )
            doi_match = bool(doi and doi in normalized_reference)
            score = 1.0 if doi_match else 0.99 if exact else max(overlap, sequence)
            if best is None or score > best[0]:
                best = (score, paper.paper_id)
        if best and best[0] >= 0.72:
            resolved[number] = best[1]
    document.reference_ids = resolved
    return resolved


def _sentences(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", text).strip()
    if not flat:
        return []
    return [
        item.strip()
        for item in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9“\"])", flat)
        if item.strip()
    ]


def _citation_numbers(marker_body: str) -> list[int]:
    result: set[int] = set()
    for part in re.split(r"\s*[,;]\s*", marker_body):
        range_match = re.fullmatch(r"(\d+)\s*[\-–]\s*(\d+)", part)
        if range_match:
            start, end = int(range_match.group(1)), int(range_match.group(2))
            if 0 <= end - start <= 100:
                result.update(range(start, end + 1))
        elif part.isdigit():
            result.add(int(part))
    return sorted(result)


def _title_mentions(paper: PaperRecord, text: str) -> bool:
    normalized = _normalize(text)
    title = _normalize(paper.title)
    anchors = [token for token in title.split() if len(token) >= 6]
    return title in normalized or bool(anchors and anchors[0] in normalized)


def _matching_entity(
    text: str, cited_id: str, origins: Iterable[EntityOrigin]
) -> EntityOrigin | None:
    normalized_text = f" {_normalize(text)} "
    compact_text = normalized_text.replace(" ", "")
    for origin in origins:
        if origin.paper_id != cited_id:
            continue
        for name in [origin.entity, *origin.aliases]:
            normalized_name = _normalize(name)
            compact_name = normalized_name.replace(" ", "")
            if normalized_name and (
                f" {normalized_name} " in normalized_text
                or (len(compact_name) >= 8 and compact_name in compact_text)
            ):
                return origin
    return None


def _substantive_discussion(text: str, citation_count: int) -> bool:
    # A many-paper citation list is weak evidence even when another clause in
    # the same sentence happens to contain a relation verb.
    if citation_count > 3:
        return False
    return bool(
        LIMITATION_CUES.search(text)
        or INHERITANCE_CUES.search(text)
        or DISCUSSION_CUES.search(text)
        or (citation_count <= 1 and len(text.split()) >= 12)
    )


def _relation_for_context(
    *,
    section_type: str,
    sentence: str,
    context: str,
    cited_paper: PaperRecord,
    entity: EntityOrigin | None,
    citation_count: int,
) -> tuple[str, list[str], bool, float]:
    relations = ["CITES"]
    parent_eligible = False
    inheritance_here = bool(INHERITANCE_CUES.search(sentence))

    if LIMITATION_CUES.search(context):
        relations.append("ADDRESSES_LIMITATION")
    if inheritance_here:
        relations.append("USES_CONCEPT_FROM" if entity else "EXTENDS")

    if section_type == "related_work":
        return "weak", relations, False, 0.35

    if section_type == "evaluation" and BASELINE_CUES.search(sentence):
        implicit = entity is not None and not _title_mentions(cited_paper, context)
        relations.append("IMPLICIT_BASELINE" if implicit else "EXPLICIT_BASELINE")
        if implicit:
            relations.append("USES_CONCEPT_FROM")
            parent_eligible = True
        elif inheritance_here and (
            citation_count <= 1 or _title_mentions(cited_paper, sentence)
        ):
            parent_eligible = True
        return "strong", relations, parent_eligible, 0.92 if implicit else 0.88

    if section_type == "method" and inheritance_here and (
        citation_count <= 1
        or entity is not None
        or _title_mentions(cited_paper, sentence)
    ):
        relations.append("METHOD_DEPENDENCY")
        return "strong", relations, True, 0.88

    if section_type in {"introduction", "preliminary"} and _substantive_discussion(
        context, citation_count
    ):
        return "medium", relations, parent_eligible, 0.72

    return "weak", relations, False, 0.35


def extract_evidence_atoms(
    document: FullTextDocument,
    papers: Iterable[PaperRecord],
    *,
    entity_origins: Iterable[EntityOrigin] = (),
) -> list[tuple[str, EvidenceAtom, str, list[str], bool]]:
    """Return predecessor ID plus atom and classification metadata."""

    paper_list = list(papers)
    by_id = {paper.paper_id: paper for paper in paper_list}
    if not document.reference_ids:
        resolve_bibliography(document, paper_list)
    origins = list(entity_origins)
    extracted: list[tuple[str, EvidenceAtom, str, list[str], bool]] = []

    for section in document.sections:
        sentences = _sentences(section.text)
        for index, sentence in enumerate(sentences):
            matches = list(CITATION_RE.finditer(sentence))
            context = " ".join(
                # A cited method is often named first, described in the next
                # sentence, and critiqued in the sentence after that.  Keep two
                # following sentences so the Introduction-level limitation is
                # attached to the cited predecessor rather than lost.
                sentences[max(0, index - 1) : min(len(sentences), index + 3)]
            )
            if not matches:
                if section.section_type != "evaluation" or not BASELINE_CUES.search(
                    sentence
                ):
                    continue
                for origin in origins:
                    entity = _matching_entity(sentence, origin.paper_id, [origin])
                    if entity is None or origin.paper_id == document.paper_id:
                        continue
                    atom = EvidenceAtom(
                        paper_id=document.paper_id,
                        cited_paper_id=origin.paper_id,
                        section=section.heading,
                        section_type=section.section_type,
                        text=context,
                        role="IMPLICIT_BASELINE",
                        entity=origin.entity,
                        source_path=document.source_path,
                        confidence=0.82,
                    )
                    extracted.append(
                        (
                            origin.paper_id,
                            atom,
                            "strong",
                            ["IMPLICIT_BASELINE", "USES_CONCEPT_FROM"],
                            True,
                        )
                    )
                continue
            all_numbers = {
                number
                for match in matches
                for number in _citation_numbers(match.group(1))
            }
            for match in matches:
                marker = match.group(0)
                for number in _citation_numbers(match.group(1)):
                    cited_id = document.reference_ids.get(number)
                    # PDF text extraction can splice a running page header into
                    # the final bibliography entry on a page.  If that header is
                    # the current paper's title, fuzzy bibliography resolution
                    # may otherwise create a bogus self-citation/self-loop.
                    if cited_id == document.paper_id:
                        continue
                    cited_paper = by_id.get(cited_id or "")
                    if cited_paper is None:
                        continue
                    entity = _matching_entity(context, cited_id, origins)
                    level, relations, parent_eligible, confidence = _relation_for_context(
                        section_type=section.section_type,
                        sentence=sentence,
                        context=context,
                        cited_paper=cited_paper,
                        entity=entity,
                        citation_count=len(all_numbers),
                    )
                    role = (
                        "IMPLICIT_BASELINE"
                        if "IMPLICIT_BASELINE" in relations
                        else "EXPLICIT_BASELINE"
                        if "EXPLICIT_BASELINE" in relations
                        else "METHOD_DEPENDENCY"
                        if "METHOD_DEPENDENCY" in relations
                        else "DIRECT_DISCUSSION"
                        if level == "medium"
                        else "CITATION"
                    )
                    atom = EvidenceAtom(
                        paper_id=document.paper_id,
                        cited_paper_id=cited_id,
                        section=section.heading,
                        section_type=section.section_type,
                        text=context,
                        role=role,
                        citation_marker=marker,
                        entity=entity.entity if entity else None,
                        source_path=document.source_path,
                        confidence=confidence,
                    )
                    extracted.append(
                        (cited_id, atom, level, relations, parent_eligible)
                    )
    return extracted


def relation_edges_from_documents(
    papers: Iterable[PaperRecord],
    documents: Iterable[FullTextDocument],
    *,
    entity_origins: Iterable[EntityOrigin] = (),
) -> list[EvolutionEdge]:
    paper_list = list(papers)
    origins = list(entity_origins)
    grouped: dict[tuple[str, str], list[tuple[EvidenceAtom, str, list[str], bool]]] = defaultdict(list)
    for document in documents:
        for source_id, atom, level, relations, parent_eligible in extract_evidence_atoms(
            document, paper_list, entity_origins=origins
        ):
            grouped[(source_id, document.paper_id)].append(
                (atom, level, relations, parent_eligible)
            )

    edges: list[EvolutionEdge] = []
    for (source_id, target_id), items in sorted(grouped.items()):
        strongest = max((item[1] for item in items), key=LEVEL_RANK.get)
        relations = sorted({relation for item in items for relation in item[2]})
        eligible = any(item[3] and item[1] == "strong" for item in items)
        # An explicit experimental baseline becomes a genealogy candidate when
        # the same predecessor is also discussed as a limitation in the
        # Introduction/Preliminaries.  This distinguishes a direct technical
        # continuation (RusKey -> ArceKV) from a comparison-only baseline such
        # as CAMAL, while preserving both as strong associations.
        has_explicit_baseline = any(
            item[1] == "strong" and "EXPLICIT_BASELINE" in item[2]
            for item in items
        )
        has_lineage_problem_statement = any(
            item[0].section_type in {"introduction", "preliminary"}
            and "ADDRESSES_LIMITATION" in item[2]
            for item in items
        )
        eligible = eligible or (
            has_explicit_baseline and has_lineage_problem_statement
        )
        atoms = [item[0] for item in items]
        origin_keys: set[tuple[str, str]] = set()
        for atom in list(atoms):
            if not atom.entity:
                continue
            for origin in origins:
                if (
                    origin.paper_id == source_id
                    and _normalize(origin.entity) == _normalize(atom.entity)
                    and origin.evidence_text
                ):
                    key = (origin.paper_id, _normalize(origin.entity))
                    if key in origin_keys:
                        continue
                    origin_keys.add(key)
                    atoms.append(
                        EvidenceAtom(
                            paper_id=origin.paper_id,
                            section=origin.section,
                            section_type="entity_origin",
                            text=origin.evidence_text,
                            role="ENTITY_ORIGIN",
                            entity=origin.entity,
                            source_path=origin.source_path,
                            confidence=0.95,
                        )
                    )
        confidence = max(atom.confidence for atom in atoms)
        primary = next(
            (
                relation
                for relation in (
                    # When a paper both names the predecessor directly and
                    # also evaluates one of its artifacts, show the explicit
                    # baseline as the primary label and retain the implicit
                    # dependency in relation_types/evidence_details.
                    "EXPLICIT_BASELINE",
                    "IMPLICIT_BASELINE",
                    "METHOD_DEPENDENCY",
                    "USES_CONCEPT_FROM",
                    "ADDRESSES_LIMITATION",
                    "EXTENDS",
                    "CITES",
                )
                if relation in relations
            ),
            "CITES",
        )
        edges.append(
            EvolutionEdge(
                source=source_id,
                target=target_id,
                citation_exists=any(atom.citation_marker for atom in atoms),
                relation=primary,
                explanation=(
                    f"{strongest.capitalize()} association supported by "
                    f"{len(atoms)} section-aware full-text evidence atom(s)."
                ),
                evidence=[
                    f"{atom.paper_id} {atom.section}: {atom.role}" for atom in atoms
                ],
                evidence_details=atoms,
                confidence=confidence,
                dominant=eligible and strongest == "strong",
                association_level=strongest,
                relation_types=relations,
                parent_eligible=eligible,
            )
        )
    return edges


def load_evidence_edges(path: str | Path) -> list[EvolutionEdge]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    records = value.get("edges", value) if isinstance(value, dict) else value
    if not isinstance(records, list):
        raise ValueError("evidence JSON must be a list or contain an edges list")
    return [EvolutionEdge.from_dict(item) for item in records]


def write_evidence_edges(
    edges: Iterable[EvolutionEdge], path: str | Path, *, metadata: Mapping[str, Any] | None = None
) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "metadata": dict(metadata or {}),
        "edges": [edge.to_dict() for edge in edges],
    }
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
