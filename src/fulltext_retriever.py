"""Fallback discovery and validated download of academic full text.

OpenAlex remains the first metadata source, but a missing ``pdf_url`` is not a
terminal condition.  This resolver can inspect configured author/group pages
(including JavaScript bundles), DOI landing pages, arXiv, and DBLP.  A candidate
is accepted only when it is a real PDF and its first pages match the requested
paper title.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
import hashlib
from html import unescape
import json
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from .schema import PaperRecord


USER_AGENT = "academic-genealogy-fulltext/0.2"
MAX_PDF_BYTES = 100 * 1024 * 1024
PROVIDER_PRIORITY = {
    "openalex_pdf": 100,
    "openalex_location": 95,
    "author_homepage": 90,
    "configured_override": 88,
    "doi_landing": 85,
    "arxiv": 80,
    "dblp": 75,
}


@dataclass(slots=True)
class HttpPayload:
    url: str
    body: bytes
    content_type: str = ""


HttpGet = Callable[[str], HttpPayload]


@dataclass(slots=True, frozen=True)
class FullTextCandidate:
    url: str
    provider: str
    source_page: str | None = None
    priority: int = 0


@dataclass(slots=True)
class RetrievalAttempt:
    url: str
    provider: str
    source_page: str | None
    status: str
    detail: str = ""
    resolved_url: str | None = None
    title_score: float | None = None


@dataclass(slots=True)
class FullTextRetrievalResult:
    paper_id: str
    title: str
    status: str
    local_path: str | None = None
    selected_url: str | None = None
    selected_provider: str | None = None
    source_page: str | None = None
    sha256: str | None = None
    title_score: float | None = None
    attempts: list[RetrievalAttempt] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", unescape(value).casefold()))


def _title_score(expected: str, extracted: str) -> float:
    expected_normalized = _normalize(expected)
    extracted_normalized = _normalize(extracted)
    expected_tokens = {
        token
        for token in expected_normalized.split()
        if len(token) >= 3 and token not in {"the", "and", "for", "with", "towards"}
    }
    extracted_tokens = set(extracted_normalized.split())
    coverage = (
        len(expected_tokens & extracted_tokens) / len(expected_tokens)
        if expected_tokens
        else 0.0
    )
    prefix = extracted_normalized[: max(500, len(expected_normalized) * 4)]
    sequence = SequenceMatcher(None, expected_normalized, prefix).ratio()
    return max(coverage, sequence)


def _safe_name(paper: PaperRecord) -> str:
    prefix = paper.title.split(":", 1)[0]
    if len(prefix.split()) <= 3 and len(prefix) <= 40:
        slug = "_".join(re.findall(r"[a-z0-9]+", prefix.casefold()))
    else:
        slug = paper.paper_id.replace(":", "_").casefold()
    return (slug or paper.paper_id.replace(":", "_").casefold()) + ".pdf"


def _default_http_get(url: str) -> HttpPayload:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/pdf,text/html,application/json,application/atom+xml;q=0.9,*/*;q=0.5",
        },
    )
    with urlopen(request, timeout=30) as response:
        body = response.read(MAX_PDF_BYTES + 1)
        if len(body) > MAX_PDF_BYTES:
            raise RuntimeError("response exceeds 100 MiB safety limit")
        return HttpPayload(
            url=response.geturl(),
            body=body,
            content_type=response.headers.get_content_type(),
        )


class FullTextResolver:
    def __init__(
        self,
        *,
        author_pages: Iterable[str] = (),
        overrides: Mapping[str, str] | None = None,
        use_arxiv: bool = True,
        use_dblp: bool = True,
        use_doi: bool = True,
        http_get: HttpGet | None = None,
    ) -> None:
        self.author_pages = list(author_pages)
        self.overrides = dict(overrides or {})
        self.use_arxiv = use_arxiv
        self.use_dblp = use_dblp
        self.use_doi = use_doi
        self.http_get = http_get or _default_http_get
        self._http_cache: dict[str, HttpPayload] = {}

    def _get(self, url: str) -> HttpPayload:
        if url not in self._http_cache:
            self._http_cache[url] = self.http_get(url)
        return self._http_cache[url]

    @staticmethod
    def _candidate(
        url: str, provider: str, source_page: str | None = None
    ) -> FullTextCandidate:
        return FullTextCandidate(
            url=url,
            provider=provider,
            source_page=source_page,
            priority=PROVIDER_PRIORITY[provider],
        )

    @staticmethod
    def _likely_fulltext_url(url: str) -> bool:
        lowered = url.casefold()
        return (
            lowered.endswith(".pdf")
            or "/pdf/" in lowered
            or "arxiv.org/pdf" in lowered
        )

    @staticmethod
    def _urls_near_title(text: str, page_url: str, title: str) -> list[str]:
        cleaned = unescape(text.replace("\\/", "/"))
        lowered = cleaned.casefold()
        needles = [title.casefold(), title.split(":", 1)[0].casefold()]
        windows: list[str] = []
        for needle in needles:
            start = 0
            while needle and (index := lowered.find(needle, start)) >= 0:
                windows.append(cleaned[max(0, index - 500) : index + 1800])
                start = index + len(needle)
        urls: list[str] = []
        for window in windows:
            for raw in re.findall(r"https?://[^\"'\s<>\\]+", window):
                url = raw.rstrip(".,);]")
                if FullTextResolver._likely_fulltext_url(url):
                    urls.append(url)
            for raw in re.findall(
                r"(?:href|url)\s*[=:]\s*[\"']([^\"']+)[\"']",
                window,
                flags=re.IGNORECASE,
            ):
                url = urljoin(page_url, raw)
                if FullTextResolver._likely_fulltext_url(url):
                    urls.append(url)
        return list(dict.fromkeys(urls))

    def _author_page_candidates(self, paper: PaperRecord) -> list[FullTextCandidate]:
        candidates: list[FullTextCandidate] = []
        for page_url in self.author_pages:
            try:
                page = self._get(page_url)
            except Exception:
                continue
            text = page.body.decode("utf-8", errors="replace")
            discovered = self._urls_near_title(text, page.url, paper.title)
            script_urls = [
                urljoin(page.url, source)
                for source in re.findall(
                    r"<script[^>]+src=[\"']([^\"']+)[\"']",
                    text,
                    flags=re.IGNORECASE,
                )
            ][:5]
            script_urls.sort(
                key=lambda url: (
                    not any(
                        token in url.casefold()
                        for token in ("main", "app", "index", "bundle")
                    ),
                    url,
                )
            )
            if not discovered:
                for script_url in script_urls:
                    try:
                        script = self._get(script_url)
                    except Exception:
                        continue
                    script_text = script.body.decode("utf-8", errors="replace")
                    discovered.extend(
                        self._urls_near_title(script_text, page.url, paper.title)
                    )
                    if discovered:
                        break
            candidates.extend(
                self._candidate(url, "author_homepage", page_url)
                for url in dict.fromkeys(discovered)
            )
        return candidates

    def _doi_candidates(self, paper: PaperRecord) -> list[FullTextCandidate]:
        doi = str(paper.metadata.get("doi") or "")
        if not doi:
            return []
        doi_url = doi if doi.startswith("http") else f"https://doi.org/{doi.removeprefix('doi:')}"
        try:
            payload = self._get(doi_url)
        except Exception:
            return []
        if payload.body.startswith(b"%PDF"):
            return [self._candidate(payload.url, "doi_landing", doi_url)]
        text = payload.body.decode("utf-8", errors="replace")
        urls = self._urls_near_title(text, payload.url, paper.title)
        # Publisher pages often put PDF links outside the title container.
        urls.extend(
            urljoin(payload.url, value)
            for value in re.findall(
                r"href=[\"']([^\"']+(?:\.pdf|/pdf)[^\"']*)[\"']",
                text,
                flags=re.IGNORECASE,
            )
        )
        return [
            self._candidate(url, "doi_landing", doi_url)
            for url in dict.fromkeys(urls)
        ]

    def _arxiv_candidates(self, paper: PaperRecord) -> list[FullTextCandidate]:
        query = urlencode(
            {
                "search_query": f'ti:"{paper.title}"',
                "start": 0,
                "max_results": 5,
            }
        )
        endpoint = f"https://export.arxiv.org/api/query?{query}"
        try:
            payload = self._get(endpoint)
            root = ElementTree.fromstring(payload.body)
        except Exception:
            return []
        namespace = {"atom": "http://www.w3.org/2005/Atom"}
        candidates: list[FullTextCandidate] = []
        for entry in root.findall("atom:entry", namespace):
            title = " ".join((entry.findtext("atom:title", "", namespace)).split())
            score = SequenceMatcher(None, _normalize(paper.title), _normalize(title)).ratio()
            if score < 0.72:
                continue
            entry_id = entry.findtext("atom:id", "", namespace)
            if entry_id:
                url = entry_id.replace("/abs/", "/pdf/")
                candidates.append(self._candidate(url, "arxiv", endpoint))
        return candidates

    def _dblp_candidates(self, paper: PaperRecord) -> list[FullTextCandidate]:
        endpoint = "https://dblp.org/search/publ/api?" + urlencode(
            {"q": paper.title, "format": "json", "h": 5}
        )
        try:
            payload = json.loads(self._get(endpoint).body.decode("utf-8"))
        except Exception:
            return []
        hits = (((payload.get("result") or {}).get("hits") or {}).get("hit") or [])
        candidates: list[FullTextCandidate] = []
        for hit in hits:
            info = hit.get("info") or {}
            score = SequenceMatcher(
                None, _normalize(paper.title), _normalize(str(info.get("title") or ""))
            ).ratio()
            if score < 0.72:
                continue
            editions = info.get("ee") or []
            if isinstance(editions, str):
                editions = [editions]
            for url in editions:
                if self._likely_fulltext_url(str(url)):
                    candidates.append(
                        self._candidate(str(url), "dblp", endpoint)
                    )
        return candidates

    def discover(self, paper: PaperRecord) -> list[FullTextCandidate]:
        candidates = [
            candidate
            for stage in self._candidate_stages(paper)
            for candidate in stage
        ]
        deduplicated: dict[str, FullTextCandidate] = {}
        for candidate in candidates:
            current = deduplicated.get(candidate.url)
            if current is None or candidate.priority > current.priority:
                deduplicated[candidate.url] = candidate
        return sorted(
            deduplicated.values(), key=lambda item: item.priority, reverse=True
        )

    def _candidate_stages(
        self, paper: PaperRecord
    ) -> Iterable[list[FullTextCandidate]]:
        """Yield progressively more expensive discovery stages.

        Keeping this lazy matters for batch retrieval: once an author/group page
        provides a valid PDF, DOI, arXiv, and DBLP are never queried.
        """

        openalex: list[FullTextCandidate] = []
        if paper.pdf_url:
            openalex.append(self._candidate(paper.pdf_url, "openalex_pdf"))
        for location in paper.metadata.get("openalex_locations") or []:
            if isinstance(location, Mapping) and location.get("pdf_url"):
                openalex.append(
                    self._candidate(str(location["pdf_url"]), "openalex_location")
                )
        yield openalex

        yield self._author_page_candidates(paper)

        override = self.overrides.get(paper.paper_id) or self.overrides.get(paper.title)
        if override:
            yield [self._candidate(override, "configured_override")]
        if self.use_doi:
            yield self._doi_candidates(paper)
        if self.use_arxiv:
            yield self._arxiv_candidates(paper)
        if self.use_dblp:
            yield self._dblp_candidates(paper)

    @staticmethod
    def _validate_pdf(path: Path, expected_title: str) -> float:
        completed = subprocess.run(
            ["pdftotext", "-f", "1", "-l", "2", str(path), "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        extracted = completed.stdout.decode("utf-8", errors="replace")
        return _title_score(expected_title, extracted)

    def retrieve(
        self, paper: PaperRecord, output_dir: str | Path
    ) -> FullTextRetrievalResult:
        destination_dir = Path(output_dir)
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / _safe_name(paper)
        attempts: list[RetrievalAttempt] = []

        seen_urls: set[str] = set()
        for stage in self._candidate_stages(paper):
            for candidate in sorted(
                stage, key=lambda item: item.priority, reverse=True
            ):
                if candidate.url in seen_urls:
                    continue
                seen_urls.add(candidate.url)
                attempt = RetrievalAttempt(
                    url=candidate.url,
                    provider=candidate.provider,
                    source_page=candidate.source_page,
                    status="failed",
                )
                attempts.append(attempt)
                temporary: Path | None = None
                try:
                    payload = self._get(candidate.url)
                    attempt.resolved_url = payload.url
                    if not payload.body.startswith(b"%PDF"):
                        attempt.detail = f"not a PDF ({payload.content_type or 'unknown type'})"
                        continue
                    with tempfile.NamedTemporaryFile(
                        dir=destination_dir, suffix=".pdf", delete=False
                    ) as handle:
                        handle.write(payload.body)
                        temporary = Path(handle.name)
                    score = self._validate_pdf(temporary, paper.title)
                    attempt.title_score = round(score, 4)
                    if score < 0.70:
                        attempt.detail = "PDF title did not match requested paper"
                        temporary.unlink(missing_ok=True)
                        continue
                    temporary.replace(destination)
                    digest = hashlib.sha256(payload.body).hexdigest()
                    attempt.status = "selected"
                    attempt.detail = "valid PDF with matching title"
                    return FullTextRetrievalResult(
                        paper_id=paper.paper_id,
                        title=paper.title,
                        status="retrieved",
                        local_path=str(destination),
                        selected_url=payload.url,
                        selected_provider=candidate.provider,
                        source_page=candidate.source_page,
                        sha256=digest,
                        title_score=round(score, 4),
                        attempts=attempts,
                    )
                except Exception as error:
                    attempt.detail = f"{type(error).__name__}: {error}"
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)

        return FullTextRetrievalResult(
            paper_id=paper.paper_id,
            title=paper.title,
            status="not_found",
            attempts=attempts,
        )


def write_retrieval_index(
    results: Iterable[FullTextRetrievalResult], path: str | Path
) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    records = [result.to_dict() for result in results]
    output.write_text(
        json.dumps(
            {
                "method": "openalex_then_author_doi_arxiv_dblp_fallback",
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "papers": records,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
