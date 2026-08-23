"""Recover verified corresponding-author roles from paper front matter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import unicodedata
from typing import Any, Mapping

from .schema import PaperRecord


FOOTNOTE_MARKERS = "*†‡§"


@dataclass(frozen=True, slots=True)
class CorrespondingAuthorMatch:
    display_name: str
    method: str
    evidence: str


def _name_pattern(name: str) -> str:
    tokens = re.findall(r"[\w'-]+", unicodedata.normalize("NFKC", name))
    return r"\s+".join(re.escape(token) for token in tokens)


def _evidence_window(text: str, start: int, end: int) -> str:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end < 0:
        line_end = len(text)
    return re.sub(r"\s+", " ", text[line_start:line_end]).strip()


def corresponding_authors_from_front_matter(
    text: str, authorships: list[Mapping[str, Any]]
) -> list[CorrespondingAuthorMatch]:
    """Match only explicit front-matter correspondence statements/markers."""

    normalized_text = unicodedata.normalize("NFKC", text)
    matches: list[CorrespondingAuthorMatch] = []
    for authorship in authorships:
        name = str(authorship.get("display_name") or "").strip()
        if not name:
            continue
        name_pattern = _name_pattern(name)
        if not name_pattern:
            continue

        direct_patterns = (
            rf"{name_pattern}\s+is\s+(?:the\s+)?corresponding\s+author",
            rf"corresponding\s+author(?:s)?\s*[:\-]\s*{name_pattern}",
            rf"correspondence\s*(?:to|:)\s*{name_pattern}",
        )
        direct = next(
            (
                found
                for pattern in direct_patterns
                if (found := re.search(pattern, normalized_text, re.IGNORECASE))
            ),
            None,
        )
        if direct is not None:
            matches.append(
                CorrespondingAuthorMatch(
                    name,
                    "explicit_statement",
                    _evidence_window(normalized_text, direct.start(), direct.end()),
                )
            )
            continue

        marked_name = re.search(
            rf"{name_pattern}\s*([{re.escape(FOOTNOTE_MARKERS)}])",
            normalized_text,
            re.IGNORECASE,
        )
        if marked_name is None:
            continue
        marker = marked_name.group(1)
        legend = re.search(
            rf"{re.escape(marker)}\s*(?:is\s+(?:the\s+)?)?corresponding\s+author",
            normalized_text,
            re.IGNORECASE,
        )
        if legend is not None:
            name_evidence = _evidence_window(
                normalized_text, marked_name.start(), marked_name.end()
            )
            legend_evidence = _evidence_window(
                normalized_text, legend.start(), legend.end()
            )
            matches.append(
                CorrespondingAuthorMatch(
                    name,
                    "matched_footnote_marker",
                    f"{name_evidence}; {legend_evidence}",
                )
            )
    return matches


def first_pages_text(pdf_path: str | Path, *, pages: int = 2) -> str:
    completed = subprocess.run(
        [
            "pdftotext",
            "-f",
            "1",
            "-l",
            str(pages),
            "-layout",
            str(Path(pdf_path)),
            "-",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout.decode("utf-8", errors="replace")


def apply_front_matter_correspondence(
    paper: PaperRecord, pdf_path: str | Path
) -> list[CorrespondingAuthorMatch]:
    """Merge verified PDF roles into OpenAlex authorships in place."""

    authorships = paper.metadata.get("authorships") or []
    if not isinstance(authorships, list) or not authorships:
        return []
    matches = corresponding_authors_from_front_matter(
        first_pages_text(pdf_path), authorships
    )
    by_name = {match.display_name.casefold(): match for match in matches}
    evidence = []
    for authorship in authorships:
        if not isinstance(authorship, dict):
            continue
        match = by_name.get(str(authorship.get("display_name") or "").casefold())
        if match is None:
            continue
        authorship["is_corresponding"] = True
        authorship["corresponding_source"] = "paper_front_matter"
        authorship["corresponding_source_path"] = str(pdf_path)
        evidence.append(
            {
                "display_name": match.display_name,
                "method": match.method,
                "text": match.evidence,
                "source_path": str(pdf_path),
            }
        )
    if evidence:
        paper.metadata["corresponding_author_evidence"] = evidence
    return matches
