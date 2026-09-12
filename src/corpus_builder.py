"""CoI-backed Semantic Scholar retrieval and bounded corpus construction.

This module intentionally wraps ``SementicSearcher.search_papers_async`` from
the pinned CoI-Agent checkout.  It does not reuse CoI's single-result
``search_related_paper_async`` method because that method drops Semantic Scholar
IDs and is designed to extend one idea chain rather than retain a candidate set.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from difflib import SequenceMatcher
import hashlib
import importlib
import json
from pathlib import Path
import re
import sys
import types
from typing import Any, Iterable, Mapping, Protocol

from .schema import PaperRecord


BASIC_FIELDS = [
    "title",
    "paperId",
    "abstract",
    "year",
    "venue",
    "publicationDate",
    "citationCount",
    "isOpenAccess",
    "openAccessPdf",
]

NEIGHBORHOOD_FIELDS = BASIC_FIELDS + [
    "references.paperId",
    "references.title",
    "references.abstract",
    "references.year",
    "references.venue",
    "references.citationCount",
    "references.isOpenAccess",
    "references.openAccessPdf",
    "citations.paperId",
    "citations.title",
    "citations.abstract",
    "citations.year",
    "citations.venue",
    "citations.citationCount",
    "citations.isOpenAccess",
    "citations.openAccessPdf",
]


class SearcherProtocol(Protocol):
    async def search_papers_async(self, query: str, **kwargs: Any) -> Any: ...


class RetrievalAdapterProtocol(Protocol):
    async def resolve_paper(self, title_or_id: str) -> PaperRecord | None: ...
    async def topic_search(self, query: str, limit: int) -> list[PaperRecord]: ...
    async def get_neighborhood(
        self, paper: PaperRecord
    ) -> tuple[PaperRecord, list[PaperRecord], list[PaperRecord]]: ...


def _normalized_title(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _s2_id(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    return text if text.startswith("S2:") else f"S2:{text}"


def _pdf_url(value: Any) -> str | None:
    if isinstance(value, Mapping):
        url = value.get("url")
        return str(url) if url else None
    return None


def paper_from_s2(value: Mapping[str, Any]) -> PaperRecord | None:
    paper_id = _s2_id(value.get("paperId"))
    title = value.get("title")
    if not paper_id or not title:
        return None
    return PaperRecord(
        paper_id=paper_id,
        title=str(title),
        year=value.get("year"),
        venue=value.get("venue"),
        abstract=value.get("abstract"),
        pdf_url=_pdf_url(value.get("openAccessPdf")),
        metadata={
            "citation_count": value.get("citationCount"),
            "publication_date": value.get("publicationDate"),
            "is_open_access": value.get("isOpenAccess"),
            "source": "semantic_scholar_via_coi",
        },
    )


class CoIRetrievalAdapter:
    """Canonical facade over the pinned CoI Semantic Scholar search client."""

    def __init__(
        self,
        *,
        upstream_path: str | Path = "upstream/CoI-Agent",
        cache_dir: str | Path = "data/raw/semantic_scholar",
        paper_dir: str | Path = "data/raw/pdfs",
        searcher: SearcherProtocol | None = None,
        metadata_only: bool = True,
        request_timeout_seconds: float = 30.0,
        http_timeout_seconds: float = 15.0,
    ) -> None:
        self.upstream_path = Path(upstream_path).resolve()
        self.cache_dir = Path(cache_dir)
        self.paper_dir = Path(paper_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.paper_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_only = metadata_only
        self.request_timeout_seconds = request_timeout_seconds
        self.http_timeout_seconds = http_timeout_seconds
        self.using_scipdf_stub = False
        self._searcher = searcher or self._load_upstream_searcher()

    @staticmethod
    def _metadata_only_scipdf_stub() -> types.ModuleType:
        module = types.ModuleType("scipdf")

        def unavailable(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError(
                "SciPDF Parser is unavailable in metadata-only mode; install it "
                "and run GROBID before requesting full-text parsing"
            )

        module.parse_pdf_to_dict = unavailable  # type: ignore[attr-defined]
        return module

    def _configure_upstream_requests(self, module: Any) -> None:
        """Bound CoI's unbounded synchronous HTTP call without editing upstream."""

        requests_module = module.requests
        original_get = requests_module.get
        timeout = self.http_timeout_seconds

        class RequestsProxy:
            RequestException = requests_module.RequestException

            @staticmethod
            def get(*args: Any, **kwargs: Any) -> Any:
                kwargs.setdefault("timeout", timeout)
                return original_get(*args, **kwargs)

        module.requests = RequestsProxy

    def _load_upstream_searcher(self) -> SearcherProtocol:
        if not self.upstream_path.exists():
            raise RuntimeError(
                f"CoI-Agent checkout not found at {self.upstream_path}; "
                "clone the revision in upstream.lock first"
            )
        path = str(self.upstream_path)
        sys.path.insert(0, path)
        try:
            module = importlib.import_module("searcher.sementic_search")
            self._configure_upstream_requests(module)
            searcher_type = getattr(module, "SementicSearcher")
            return searcher_type(save_file=str(self.paper_dir))
        except ModuleNotFoundError as error:
            if error.name == "scipdf" and self.metadata_only:
                # CoI imports SciPDF at module load even though its Semantic
                # Scholar metadata client does not use it. Supply only the symbol
                # boundary needed for metadata calls; full-text calls fail loudly.
                for name in list(sys.modules):
                    if name == "searcher" or name.startswith("searcher."):
                        sys.modules.pop(name, None)
                sys.modules["scipdf"] = self._metadata_only_scipdf_stub()
                module = importlib.import_module("searcher.sementic_search")
                self._configure_upstream_requests(module)
                searcher_type = getattr(module, "SementicSearcher")
                self.using_scipdf_stub = True
                return searcher_type(save_file=str(self.paper_dir))
            raise RuntimeError(
                f"CoI retrieval dependency {error.name!r} is unavailable. Run "
                "this adapter inside the isolated CoI environment."
            ) from error
        finally:
            if sys.path and sys.path[0] == path:
                sys.path.pop(0)

    def _cache_path(self, parameters: Mapping[str, Any]) -> Path:
        payload = json.dumps(parameters, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    async def _search(
        self,
        query: str,
        *,
        limit: int,
        fields: list[str],
        year: str | None = None,
        publication_date: str | None = None,
    ) -> JsonDict:
        parameters = {
            "query": query,
            "limit": limit,
            "fields": fields,
            "year": year,
            "publication_date": publication_date,
        }
        cache_path = self._cache_path(parameters)
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            return cached if isinstance(cached, dict) else {}

        try:
            result = await asyncio.wait_for(
                self._searcher.search_papers_async(
                    query=query,
                    limit=limit,
                    fields=fields,
                    year=year,
                    publicationDate=publication_date,
                ),
                timeout=self.request_timeout_seconds,
            )
        except TimeoutError as error:
            raise RuntimeError(
                f"CoI search timed out for {query!r}; the upstream client may be "
                "stuck in its unbounded Semantic Scholar 429 retry loop"
            ) from error
        if not isinstance(result, dict):
            raise RuntimeError(f"CoI search returned no usable response for {query!r}")
        cache_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return result

    @staticmethod
    def _best_match(
        query: str, values: Iterable[Mapping[str, Any]]
    ) -> Mapping[str, Any] | None:
        candidates = list(values)
        if not candidates:
            return None
        raw_id = query.removeprefix("S2:")
        for candidate in candidates:
            if str(candidate.get("paperId") or "") == raw_id:
                return candidate
        normalized_query = _normalized_title(query)
        return max(
            candidates,
            key=lambda item: SequenceMatcher(
                None, normalized_query, _normalized_title(str(item.get("title") or ""))
            ).ratio(),
        )

    async def resolve_paper(self, title_or_id: str) -> PaperRecord | None:
        payload = await self._search(title_or_id, limit=5, fields=BASIC_FIELDS)
        match = self._best_match(title_or_id, payload.get("data") or [])
        return paper_from_s2(match) if match else None

    async def topic_search(self, query: str, limit: int) -> list[PaperRecord]:
        payload = await self._search(query, limit=limit, fields=BASIC_FIELDS)
        records = [paper_from_s2(item) for item in payload.get("data") or []]
        return [record for record in records if record is not None]

    async def _record_with_neighborhood(self, paper: PaperRecord) -> PaperRecord:
        payload = await self._search(paper.title, limit=5, fields=NEIGHBORHOOD_FIELDS)
        match = self._best_match(paper.paper_id, payload.get("data") or [])
        if match is None:
            return paper
        full_record = paper_from_s2(match) or paper
        references = [paper_from_s2(item) for item in match.get("references") or []]
        citations = [paper_from_s2(item) for item in match.get("citations") or []]
        full_record.references = [item.paper_id for item in references if item]
        full_record.citations = [item.paper_id for item in citations if item]
        full_record.metadata["reference_records"] = [
            item.to_dict() for item in references if item
        ]
        full_record.metadata["citation_records"] = [
            item.to_dict() for item in citations if item
        ]
        return full_record

    async def get_references(self, paper: PaperRecord) -> list[PaperRecord]:
        expanded = await self._record_with_neighborhood(paper)
        return [
            PaperRecord.from_dict(item)
            for item in expanded.metadata.get("reference_records", [])
        ]

    async def get_citations(self, paper: PaperRecord) -> list[PaperRecord]:
        expanded = await self._record_with_neighborhood(paper)
        return [
            PaperRecord.from_dict(item)
            for item in expanded.metadata.get("citation_records", [])
        ]

    async def get_neighborhood(
        self, paper: PaperRecord
    ) -> tuple[PaperRecord, list[PaperRecord], list[PaperRecord]]:
        expanded = await self._record_with_neighborhood(paper)
        references = [
            PaperRecord.from_dict(item)
            for item in expanded.metadata.pop("reference_records", [])
        ]
        citations = [
            PaperRecord.from_dict(item)
            for item in expanded.metadata.pop("citation_records", [])
        ]
        return expanded, references, citations


JsonDict = dict[str, Any]


@dataclass(slots=True)
class CorpusBuildResult:
    papers: list[PaperRecord]
    unresolved_seeds: list[str]
    seed_paper_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> JsonDict:
        return {
            "papers": [paper.to_dict() for paper in self.papers],
            "unresolved_seeds": self.unresolved_seeds,
            "seed_paper_ids": self.seed_paper_ids,
        }

    def dump(self, path: str | Path) -> None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


class CorpusBuilder:
    """Build one-hop + topic-search corpus without doing genealogy inference."""

    def __init__(self, adapter: RetrievalAdapterProtocol) -> None:
        self.adapter = adapter

    @staticmethod
    def _relevance(paper: PaperRecord, topic: str) -> float:
        topic_tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", topic.casefold())
            if len(token) >= 3 and token not in {"and", "the", "for", "tree"}
        }
        haystack = f"{paper.title} {paper.abstract or ''}".casefold()
        token_score = sum(1.0 for token in topic_tokens if token in haystack)
        lsm_bonus = 3.0 if re.search(r"\blsm(?:-|\s)?trees?\b", haystack) else 0.0
        citations = paper.metadata.get("citation_count") or 0
        return token_score + lsm_bonus + min(float(citations), 1000.0) / 10000.0

    async def build(
        self,
        *,
        topic: str,
        seeds: Iterable[str],
        corpus_cap: int = 150,
        topic_search_limit: int = 50,
    ) -> CorpusBuildResult:
        if corpus_cap < 1:
            raise ValueError("corpus_cap must be positive")
        seed_queries = list(dict.fromkeys(seeds))
        # CoI performs synchronous requests inside its async method. Sequential
        # calls avoid blocking all per-request timers and respect no-key API
        # rate limits more reliably.
        resolved = []
        for seed in seed_queries:
            resolved.append(await self.adapter.resolve_paper(seed))
        seed_title_aliases: dict[str, list[str]] = {}
        for seed, paper in zip(seed_queries, resolved, strict=True):
            if paper is not None and _normalized_title(seed) != _normalized_title(
                paper.title
            ):
                seed_title_aliases.setdefault(paper.paper_id, []).append(seed)
        unresolved = [
            seed for seed, paper in zip(seed_queries, resolved, strict=True) if paper is None
        ]
        seed_papers = [paper for paper in resolved if paper is not None]

        neighborhoods = []
        for paper in seed_papers:
            neighborhoods.append(await self.adapter.get_neighborhood(paper))
        topic_candidates = await self.adapter.topic_search(topic, topic_search_limit)

        records: dict[str, PaperRecord] = {}
        forced_ids: set[str] = set()
        for expanded, references, citations in neighborhoods:
            records[expanded.paper_id] = expanded
            forced_ids.add(expanded.paper_id)
            for related in references + citations:
                records.setdefault(related.paper_id, related)
        for candidate in topic_candidates:
            records.setdefault(candidate.paper_id, candidate)

        # Some OpenAlex systems records are indexed only by the acronym before
        # a colon ("Monkey", "Dostoevsky", "Spooky"). Reconcile unresolved
        # long-form seeds against papers discovered through another seed's
        # neighborhood or the topic search before declaring them missing.
        still_unresolved: list[str] = []
        for seed in unresolved:
            normalized = _normalized_title(seed)
            prefix = _normalized_title(seed.split(":", 1)[0])
            match = next(
                (
                    paper
                    for paper in records.values()
                    if _normalized_title(paper.title) == normalized
                    or (
                        ":" in seed
                        and prefix
                        and _normalized_title(paper.title) == prefix
                    )
                ),
                None,
            )
            if match is None:
                still_unresolved.append(seed)
            else:
                forced_ids.add(match.paper_id)
                if _normalized_title(seed) != _normalized_title(match.title):
                    seed_title_aliases.setdefault(match.paper_id, []).append(seed)
        unresolved = still_unresolved

        # OpenAlex may represent a preprint and venue version as separate works
        # with the same title. Keep one canonical record and redirect in-corpus
        # bibliography IDs to it so clustering does not see duplicate papers.
        grouped: dict[str, list[PaperRecord]] = {}
        for paper in records.values():
            grouped.setdefault(_normalized_title(paper.title), []).append(paper)
        canonical_records: dict[str, PaperRecord] = {}
        aliases: dict[str, str] = {}
        for group in grouped.values():
            canonical = max(
                group,
                key=lambda paper: (
                    paper.paper_id in forced_ids,
                    bool(paper.abstract),
                    len(paper.references) + len(paper.citations),
                    paper.metadata.get("citation_count") or 0,
                ),
            )
            canonical_records[canonical.paper_id] = canonical
            for duplicate in group:
                aliases[duplicate.paper_id] = canonical.paper_id
        for paper in canonical_records.values():
            paper.references = list(
                dict.fromkeys(aliases.get(item, item) for item in paper.references)
            )
            paper.citations = list(
                dict.fromkeys(aliases.get(item, item) for item in paper.citations)
            )
        forced_ids = {aliases.get(paper_id, paper_id) for paper_id in forced_ids}
        seed_title_aliases = {
            aliases.get(paper_id, paper_id): list(dict.fromkeys(values))
            for paper_id, values in seed_title_aliases.items()
        }
        records = canonical_records

        ranked = sorted(
            records.values(),
            key=lambda paper: (
                paper.paper_id in forced_ids,
                self._relevance(paper, topic),
                paper.year or 0,
            ),
            reverse=True,
        )
        # The corpus cap bounds discovered context, never the user's resolved
        # seeds. This matters for multi-seed searches whose seed count happens
        # to exceed a deliberately small cap.
        selected = ranked[: max(corpus_cap, len(forced_ids))]
        hydrate = getattr(self.adapter, "hydrate_records", None)
        if callable(hydrate):
            selected = await hydrate(selected)
        for paper in selected:
            title_aliases = seed_title_aliases.get(paper.paper_id)
            if title_aliases:
                paper.metadata["title_aliases"] = title_aliases
        selected_ids = {paper.paper_id for paper in selected}
        for paper in selected:
            paper.references = [
                paper_id for paper_id in paper.references if paper_id in selected_ids
            ]
            paper.citations = [
                paper_id for paper_id in paper.citations if paper_id in selected_ids
            ]
        selected.sort(key=lambda paper: (paper.year is None, paper.year or 0, paper.title))
        seed_paper_ids = [
            paper.paper_id for paper in selected if paper.paper_id in forced_ids
        ]
        return CorpusBuildResult(selected, unresolved, seed_paper_ids)
