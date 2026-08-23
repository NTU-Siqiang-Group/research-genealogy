"""OpenAlex retrieval adapter for the bounded P0 corpus contract."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping
from difflib import SequenceMatcher
import hashlib
from html import unescape
import json
import os
from pathlib import Path
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .schema import PaperRecord


JsonDict = dict[str, Any]
Transport = Callable[[str, Mapping[str, Any]], Awaitable[JsonDict]]

WORK_FIELDS = ",".join(
    [
        "id",
        "doi",
        "title",
        "publication_year",
        "publication_date",
        "cited_by_count",
        "referenced_works",
        "abstract_inverted_index",
        "open_access",
        "best_oa_location",
        "primary_location",
        "locations",
        "authorships",
        "corresponding_author_ids",
    ]
)


def _normalized_title(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", unescape(value).casefold()))


def _work_id(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).rstrip("/").rsplit("/", 1)[-1]
    text = text.removeprefix("OPENALEX:")
    return text if re.fullmatch(r"W\d+", text, flags=re.IGNORECASE) else None


def _canonical_id(value: Any) -> str | None:
    work_id = _work_id(value)
    return f"OPENALEX:{work_id.upper()}" if work_id else None


def _abstract(value: Any) -> str | None:
    if not isinstance(value, Mapping) or not value:
        return None
    positions = [
        position
        for word_positions in value.values()
        if isinstance(word_positions, list)
        for position in word_positions
        if isinstance(position, int) and position >= 0
    ]
    if not positions:
        return None
    words = [""] * (max(positions) + 1)
    for word, word_positions in value.items():
        if not isinstance(word_positions, list):
            continue
        for position in word_positions:
            if isinstance(position, int) and 0 <= position < len(words):
                words[position] = str(word)
    return " ".join(word for word in words if word).strip() or None


def _location_pdf(value: Any) -> str | None:
    if isinstance(value, Mapping):
        pdf_url = value.get("pdf_url")
        if pdf_url:
            return str(pdf_url)
    return None


def _venue(value: Mapping[str, Any]) -> str | None:
    location = value.get("primary_location")
    if not isinstance(location, Mapping):
        return None
    source = location.get("source")
    if isinstance(source, Mapping) and source.get("display_name"):
        return str(source["display_name"])
    return None


def _location_records(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for location in value.get("locations") or []:
        if not isinstance(location, Mapping):
            continue
        source = location.get("source")
        records.append(
            {
                "pdf_url": location.get("pdf_url"),
                "landing_page_url": location.get("landing_page_url"),
                "source": (
                    source.get("display_name")
                    if isinstance(source, Mapping)
                    else None
                ),
                "is_oa": location.get("is_oa"),
            }
        )
    return records


def _author_id(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).rstrip("/").rsplit("/", 1)[-1]
    text = text.removeprefix("OPENALEX:")
    return f"OPENALEX:{text.upper()}" if re.fullmatch(r"A\d+", text, re.IGNORECASE) else None


def _authorship_records(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    corresponding_ids = {
        author_id
        for item in value.get("corresponding_author_ids") or []
        if (author_id := _author_id(item)) is not None
    }
    records: list[dict[str, Any]] = []
    for index, authorship in enumerate(value.get("authorships") or []):
        if not isinstance(authorship, Mapping):
            continue
        author = authorship.get("author")
        if not isinstance(author, Mapping):
            author = {}
        author_id = _author_id(author.get("id"))
        display_name = author.get("display_name") or authorship.get("raw_author_name")
        if not author_id and not display_name:
            continue
        records.append(
            {
                "author_id": author_id,
                "display_name": str(display_name or author_id),
                # OpenAlex exposes first/middle/last, while the exact byline
                # index is needed to distinguish the second author.
                "byline_index": index,
                "author_position": authorship.get("author_position"),
                "is_corresponding": bool(authorship.get("is_corresponding"))
                or bool(author_id and author_id in corresponding_ids),
                "institutions": [
                    {
                        "institution_id": institution.get("id"),
                        "display_name": institution.get("display_name"),
                    }
                    for institution in authorship.get("institutions") or []
                    if isinstance(institution, Mapping)
                ],
            }
        )
    return records


def paper_from_openalex(value: Mapping[str, Any]) -> PaperRecord | None:
    paper_id = _canonical_id(value.get("id"))
    title = value.get("title")
    if not paper_id or not title:
        return None
    open_access = value.get("open_access")
    best_oa = value.get("best_oa_location")
    primary = value.get("primary_location")
    locations = _location_records(value)
    authorships = _authorship_records(value)
    references = [
        canonical
        for item in value.get("referenced_works") or []
        if (canonical := _canonical_id(item)) is not None
    ]
    return PaperRecord(
        paper_id=paper_id,
        title=unescape(str(title)),
        year=value.get("publication_year"),
        venue=_venue(value),
        abstract=_abstract(value.get("abstract_inverted_index")),
        pdf_url=(
            _location_pdf(best_oa)
            or _location_pdf(primary)
            or next(
                (
                    str(location["pdf_url"])
                    for location in locations
                    if location.get("pdf_url")
                ),
                None,
            )
        ),
        references=references,
        metadata={
            "citation_count": value.get("cited_by_count"),
            "publication_date": value.get("publication_date"),
            "is_open_access": (
                open_access.get("is_oa") if isinstance(open_access, Mapping) else None
            ),
            "doi": value.get("doi"),
            "authors": [item["display_name"] for item in authorships],
            "authorships": authorships,
            "openalex_locations": locations,
            "source": "openalex",
        },
    )


class OpenAlexRetrievalAdapter:
    """Cached OpenAlex implementation of the retrieval methods used by CorpusBuilder."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        cache_dir: str | Path = "data/raw/openalex",
        base_url: str = "https://api.openalex.org",
        request_timeout_seconds: float = 30.0,
        max_retries: int = 4,
        neighborhood_limit: int = 100,
        transport: Transport | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENALEX_API_KEY")
        if not self.api_key and transport is None:
            raise RuntimeError(
                "OPENALEX_API_KEY is required; create a free key and place it in .env"
            )
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.base_url = base_url.rstrip("/")
        self.request_timeout_seconds = request_timeout_seconds
        self.max_retries = max_retries
        self.neighborhood_limit = neighborhood_limit
        self.transport = transport

    def _cache_path(self, path: str, params: Mapping[str, Any]) -> Path:
        payload = json.dumps([path, sorted(params.items())], ensure_ascii=False)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def _sync_request(self, path: str, params: Mapping[str, Any]) -> JsonDict:
        query = dict(params)
        query["api_key"] = self.api_key
        url = f"{self.base_url}{path}?{urlencode(query)}"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "academic-genealogy-p0/0.1",
            },
        )
        with urlopen(request, timeout=self.request_timeout_seconds) as response:
            value = json.loads(response.read().decode("utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError(f"OpenAlex returned non-object JSON for {path}")
        return value

    async def _request(self, path: str, params: Mapping[str, Any]) -> JsonDict:
        cache_path = self._cache_path(path, params)
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            return cached if isinstance(cached, dict) else {}

        if self.transport is not None:
            value = await self.transport(path, params)
        else:
            value = {}
            for attempt in range(self.max_retries):
                try:
                    value = await asyncio.to_thread(self._sync_request, path, params)
                    break
                except HTTPError as error:
                    if error.code != 429 and not 500 <= error.code < 600:
                        detail = error.read().decode("utf-8", errors="replace")[:500]
                        raise RuntimeError(
                            f"OpenAlex HTTP {error.code} for {path}: {detail}"
                        ) from error
                    if attempt + 1 >= self.max_retries:
                        raise RuntimeError(
                            f"OpenAlex remained unavailable after {self.max_retries} attempts"
                        ) from error
                except URLError as error:
                    if attempt + 1 >= self.max_retries:
                        raise RuntimeError(f"OpenAlex request failed: {error.reason}") from error
                await asyncio.sleep(2**attempt)

        if not isinstance(value, dict):
            raise RuntimeError(f"OpenAlex returned no usable response for {path}")
        cache_path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return value

    @staticmethod
    def _best_match(
        query: str, values: Iterable[Mapping[str, Any]]
    ) -> Mapping[str, Any] | None:
        candidates = list(values)
        if not candidates:
            return None
        requested_id = _work_id(query)
        if requested_id:
            for candidate in candidates:
                if _work_id(candidate.get("id")) == requested_id:
                    return candidate
        normalized_query = _normalized_title(query)
        # Systems papers are sometimes indexed only by their acronym/title
        # prefix (for example "Monkey", "Dostoevsky", and "Spooky").
        prefix = _normalized_title(query.split(":", 1)[0])
        if prefix:
            for candidate in candidates:
                if _normalized_title(str(candidate.get("title") or "")) == prefix:
                    return candidate
        scored = [
            (
                SequenceMatcher(
                    None,
                    normalized_query,
                    _normalized_title(str(candidate.get("title") or "")),
                ).ratio(),
                candidate,
            )
            for candidate in candidates
        ]
        score, candidate = max(scored, key=lambda item: item[0])
        return candidate if score >= 0.55 else None

    async def resolve_paper(self, title_or_id: str) -> PaperRecord | None:
        work_id = _work_id(title_or_id)
        if work_id:
            payload = await self._request(
                f"/works/{quote(work_id)}", {"select": WORK_FIELDS}
            )
            return paper_from_openalex(payload)
        if title_or_id.casefold().startswith(("doi:", "10.")):
            doi = title_or_id.removeprefix("doi:")
            payload = await self._request(
                f"/works/{quote('https://doi.org/' + doi, safe='')}",
                {"select": WORK_FIELDS},
            )
            return paper_from_openalex(payload)
        # OpenAlex full-text search uses query-parser syntax.  Strip title
        # punctuation so colons, ampersands, and hyphenated acronyms are not
        # accidentally interpreted as operators.
        search_query = " ".join(re.findall(r"[A-Za-z0-9]+", unescape(title_or_id)))
        payload = await self._request(
            "/works",
            {"search": search_query, "per_page": 5, "select": WORK_FIELDS},
        )
        match = self._best_match(title_or_id, payload.get("results") or [])
        if match is None and ":" in title_or_id:
            acronym = title_or_id.split(":", 1)[0].strip()
            acronym_payload = await self._request(
                "/works",
                {"search": acronym, "per_page": 100, "select": WORK_FIELDS},
            )
            match = self._best_match(title_or_id, acronym_payload.get("results") or [])
        return paper_from_openalex(match) if match else None

    async def topic_search(self, query: str, limit: int) -> list[PaperRecord]:
        payload = await self._request(
            "/works",
            {
                "search": query,
                "per_page": min(limit, 100),
                "select": WORK_FIELDS,
            },
        )
        records = [paper_from_openalex(item) for item in payload.get("results") or []]
        return [record for record in records if record is not None]

    async def _fetch_by_ids(self, paper_ids: Iterable[str]) -> list[PaperRecord]:
        work_ids = list(
            dict.fromkeys(
                work_id
                for paper_id in paper_ids
                if (work_id := _work_id(paper_id)) is not None
            )
        )
        records: list[PaperRecord] = []
        for start in range(0, len(work_ids), 100):
            chunk = work_ids[start : start + 100]
            payload = await self._request(
                "/works",
                {
                    "filter": "openalex:" + "|".join(chunk),
                    "per_page": len(chunk),
                    "select": WORK_FIELDS,
                },
            )
            parsed = [paper_from_openalex(item) for item in payload.get("results") or []]
            records.extend(record for record in parsed if record is not None)
        return records

    async def get_neighborhood(
        self, paper: PaperRecord
    ) -> tuple[PaperRecord, list[PaperRecord], list[PaperRecord]]:
        work_id = _work_id(paper.paper_id)
        if not work_id:
            return paper, [], []
        payload = await self._request(
            f"/works/{quote(work_id)}", {"select": WORK_FIELDS}
        )
        expanded = paper_from_openalex(payload) or paper
        references = await self._fetch_by_ids(
            expanded.references[: self.neighborhood_limit]
        )
        citing_payload = await self._request(
            "/works",
            {
                "filter": f"cites:{work_id}",
                "sort": "cited_by_count:desc",
                "per_page": self.neighborhood_limit,
                "select": WORK_FIELDS,
            },
        )
        citations = [
            record
            for item in citing_payload.get("results") or []
            if (record := paper_from_openalex(item)) is not None
        ]
        expanded.citations = [record.paper_id for record in citations]
        return expanded, references, citations

    async def get_references(self, paper: PaperRecord) -> list[PaperRecord]:
        _, references, _ = await self.get_neighborhood(paper)
        return references

    async def get_citations(self, paper: PaperRecord) -> list[PaperRecord]:
        _, _, citations = await self.get_neighborhood(paper)
        return citations

    async def hydrate_records(self, papers: list[PaperRecord]) -> list[PaperRecord]:
        """Populate bibliography fields for every selected paper in two cheap batches."""

        hydrated = await self._fetch_by_ids(paper.paper_id for paper in papers)
        by_id = {paper.paper_id: paper for paper in hydrated}
        return [by_id.get(paper.paper_id, paper) for paper in papers]

    async def hydrate_authorship_metadata(
        self, papers: list[PaperRecord]
    ) -> list[PaperRecord]:
        """Refresh authorship fields without replacing local pipeline state.

        ``hydrate_records`` is appropriate while the corpus is being built, but
        replacing records later would discard semantic profiles and cluster
        paths.  This narrower operation updates only the ordered author fields
        required by research-group affinity inference.
        """

        hydrated = await self._fetch_by_ids(paper.paper_id for paper in papers)
        by_id = {paper.paper_id: paper for paper in hydrated}
        for paper in papers:
            current = by_id.get(paper.paper_id)
            if current is None:
                continue
            paper.metadata["authors"] = list(current.metadata.get("authors") or [])
            paper.metadata["authorships"] = list(
                current.metadata.get("authorships") or []
            )
            paper.metadata["authorship_source"] = "openalex"
        return papers
