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
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import quote, unquote, urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from .schema import PaperRecord


USER_AGENT = "academic-genealogy-fulltext/0.2"
MAX_PDF_BYTES = 100 * 1024 * 1024
MAX_AUTO_AUTHOR_PAGE_CANDIDATES = 8
MAX_AUTO_AUTHOR_CANDIDATES = 12
PROVIDER_PRIORITY = {
    "openalex_pdf": 100,
    "openalex_location": 95,
    "author_homepage_auto": 92,
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
    author_name: str | None = None
    author_role: str | None = None
    discovery_method: str | None = None


@dataclass(slots=True)
class RetrievalAttempt:
    url: str
    provider: str
    source_page: str | None
    status: str
    detail: str = ""
    resolved_url: str | None = None
    title_score: float | None = None
    author_name: str | None = None
    author_role: str | None = None
    discovery_method: str | None = None


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
    selected_author: str | None = None
    selected_author_role: str | None = None
    discovery_method: str | None = None
    attempts: list[RetrievalAttempt] = field(default_factory=list)
    author_discovery: list[dict[str, Any]] = field(default_factory=list)

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


def _preferred_title(paper: PaperRecord) -> str:
    """Prefer a full user-supplied title over an acronym-only provider title."""

    aliases = paper.metadata.get("title_aliases") or []
    candidates = [paper.title, *(str(item) for item in aliases if item)]
    return max(candidates, key=lambda value: len(_normalize(value)))


def _selected_author_targets(paper: PaperRecord) -> list[dict[str, Any]]:
    """Return first/corresponding authors, with last author as a marked proxy.

    OpenAlex often leaves ``is_corresponding`` empty for older systems papers.
    In that case the last author is included as a conservative proxy so the
    fallback does not silently exclude the likely supervising/corresponding
    author.  The proxy role is retained in retrieval provenance.
    """

    raw = [
        dict(item)
        for item in paper.metadata.get("authorships") or []
        if isinstance(item, Mapping) and item.get("display_name")
    ]
    if not raw:
        names = [str(item) for item in paper.metadata.get("authors") or [] if item]
        raw = [
            {
                "display_name": name,
                "byline_index": index,
                "author_position": "first" if index == 0 else "last" if index == len(names) - 1 else "middle",
                "is_corresponding": False,
                "institutions": [],
            }
            for index, name in enumerate(names)
        ]
    if not raw:
        return []

    ordered = sorted(raw, key=lambda item: int(item.get("byline_index") or 0))
    first = next(
        (item for item in ordered if item.get("author_position") == "first"),
        ordered[0],
    )
    selected: list[tuple[dict[str, Any], str]] = [(first, "first_author")]
    correspondings = [item for item in ordered if item.get("is_corresponding")]
    if correspondings:
        selected.extend((item, "corresponding_author") for item in correspondings)
    elif len(ordered) > 1:
        selected.append((ordered[-1], "last_author_proxy"))

    targets: list[dict[str, Any]] = []
    by_key: dict[str, int] = {}
    for item, role in selected:
        key = str(item.get("author_id") or item.get("display_name")).casefold()
        if key in by_key:
            existing = targets[by_key[key]]
            if existing["role"] != role:
                existing["role"] = "first_and_corresponding_author"
            continue
        by_key[key] = len(targets)
        targets.append(
            {
                "author_id": item.get("author_id"),
                "display_name": str(item["display_name"]),
                "role": role,
                "orcid": item.get("orcid"),
                "homepage_url": item.get("homepage_url"),
                "institutions": [
                    str(institution.get("display_name"))
                    for institution in item.get("institutions") or []
                    if isinstance(institution, Mapping)
                    and institution.get("display_name")
                ],
            }
        )
    return targets


def _safe_public_url(value: Any) -> str | None:
    """Reject malformed and obvious local-network URLs from model output."""

    if not value:
        return None
    url = str(value).strip()
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    hostname = parsed.hostname.casefold().rstrip(".")
    if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
        return None
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if not address.is_global:
            return None
    return url


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            value = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return dict(value) if isinstance(value, Mapping) else {}


AuthorWebSearch = Callable[[PaperRecord, list[dict[str, Any]]], list[dict[str, Any]]]


def _author_search_request(
    paper: PaperRecord, authors: list[dict[str, Any]]
) -> tuple[str, str, dict[str, Any]]:
    author_lines = "\n".join(
        f"- {item['display_name']} ({item['role']}), affiliations: "
        + (", ".join(item.get("institutions") or []) or "unknown")
        for item in authors
    )
    instructions = (
        "Use web search separately for every listed author. Search the exact "
        "paper title together with that author's full name and PDF. Find the "
        "author's official personal, university, or research-group homepage, "
        "then look for an official publication entry and a direct PDF URL. "
        "Prefer author-controlled static files (including GitHub Pages) over "
        "publisher landing pages, because publisher pages may be inaccessible. "
        "Do not stop after finding only a publication page when a direct PDF "
        "can be located through another exact-title search. Return only "
        "verified-looking candidate URLs. Exclude ResearchGate, Academia.edu, "
        "social networks, piracy sites, and unrelated people. A URL is only a "
        "candidate; the caller will independently fetch and validate the PDF "
        "title."
    )
    input_text = (
        f"Paper title: {_preferred_title(paper)}\n"
        f"Year: {paper.year or 'unknown'}\n"
        f"DOI: {paper.metadata.get('doi') or 'unknown'}\n"
        f"Selected authors:\n{author_lines}"
    )
    output_format = {
        "type": "json_schema",
        "name": "author_homepage_candidates",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "authors": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "author_name": {"type": "string"},
                            "homepage_urls": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "publication_page_urls": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "pdf_urls": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": [
                            "author_name",
                            "homepage_urls",
                            "publication_page_urls",
                            "pdf_urls",
                        ],
                    },
                }
            },
            "required": ["authors"],
        },
    }
    return instructions, input_text, output_format


def _author_search_results(value: str) -> list[dict[str, Any]]:
    parsed = _parse_json_object(value)
    return [
        dict(item)
        for item in parsed.get("authors") or []
        if isinstance(item, Mapping)
    ]


def _author_search_cache_key(
    paper: PaperRecord, authors: list[dict[str, Any]]
) -> str:
    return paper.paper_id + "|" + "|".join(
        str(item.get("author_id") or item["display_name"]) for item in authors
    )


class OpenAIAuthorWebSearch:
    """Discover author-controlled full-text candidates with OpenAI web search."""

    discovery_method = "openai_web_search"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None = None,
        model: str = "gpt-5.4-mini",
        timeout_seconds: float = 45.0,
    ) -> None:
        from openai import OpenAI

        options: dict[str, Any] = {
            "api_key": api_key,
            "timeout": timeout_seconds,
            "max_retries": 0,
        }
        if base_url:
            options["base_url"] = base_url
        self.client = OpenAI(**options)
        self.model = model
        self._cache: dict[str, list[dict[str, Any]]] = {}

    def __call__(
        self, paper: PaperRecord, authors: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        cache_key = _author_search_cache_key(paper, authors)
        if cache_key in self._cache:
            return self._cache[cache_key]
        instructions, input_text, output_format = _author_search_request(
            paper, authors
        )
        response = self.client.responses.create(
            model=self.model,
            instructions=instructions,
            input=input_text,
            tools=[{"type": "web_search"}],
            tool_choice={"type": "web_search"},
            text={"format": output_format},
            max_output_tokens=1200,
        )
        if not any(
            getattr(item, "type", None) == "web_search_call"
            for item in response.output
        ):
            raise RuntimeError("author web search returned no search actions")
        results = _author_search_results(response.output_text or "")
        self._cache[cache_key] = results
        return results


class OpenAICompatibleAuthorWebSearch(OpenAIAuthorWebSearch):
    """Use an endpoint implementing Responses web search and structured output."""

    discovery_method = "openai_compatible_web_search"


class DeepSeekAuthorWebSearch:
    """Generate author-controlled homepage/PDF candidates with web search.

    Search output is only candidate generation.  ``FullTextResolver`` still
    downloads and title-validates every returned PDF before accepting it.
    """

    discovery_method = "deepseek_web_search"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-v4-flash",
        timeout_seconds: float = 45.0,
    ) -> None:
        from openai import OpenAI

        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=0,
        )
        self.model = model
        self._cache: dict[str, list[dict[str, Any]]] = {}

    def __call__(
        self, paper: PaperRecord, authors: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        cache_key = _author_search_cache_key(paper, authors)
        if cache_key in self._cache:
            return self._cache[cache_key]
        instructions, input_text, output_format = _author_search_request(
            paper, authors
        )
        stream = self.client.responses.create(
            model=self.model,
            instructions=instructions,
            input=input_text,
            reasoning={"effort": "none"},
            tools=[{"type": "web_search"}],
            tool_choice={"type": "web_search"},
            max_output_tokens=1200,
            stream=True,
        )
        searched_response: Any | None = None
        for event in stream:
            if getattr(event, "type", None) == "response.completed":
                searched_response = getattr(event, "response", None)
        if searched_response is None:
            raise RuntimeError("author web search did not complete")
        search_items = [
            item.model_dump(exclude_none=True)
            for item in searched_response.output
            if getattr(item, "type", None) == "web_search_call"
        ]
        if not search_items:
            raise RuntimeError("author web search returned no search actions")

        # DeepSeek's Responses API is stateless. The first response contains
        # only server-side web_search_call items; passing those items back lets
        # the second response restore the search results and synthesize URLs.
        synthesis = self.client.responses.create(
            model=self.model,
            instructions=instructions,
            input=[
                {"role": "user", "content": input_text},
                *search_items,
                {
                    "role": "user",
                    "content": (
                        "Using only the restored search results, emit the requested "
                        "author_homepage_candidates JSON."
                    ),
                },
            ],
            reasoning={"effort": "none"},
            text={"format": output_format},
            max_output_tokens=1200,
        )
        results = _author_search_results(synthesis.output_text or "")
        self._cache[cache_key] = results
        return results


@dataclass(slots=True, frozen=True)
class AuthorSearchSettings:
    provider: str
    api_key: str
    base_url: str | None
    model: str


def _normalized_author_search_provider(value: str) -> str:
    normalized = value.strip().casefold().replace("-", "_")
    aliases = {
        "open_ai": "openai",
        "deep_seek": "deepseek",
        "custom": "openai_compatible",
        "compatible": "openai_compatible",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"openai", "deepseek", "openai_compatible"}:
        raise ValueError(
            "author web search provider must be openai, deepseek, or "
            "openai_compatible"
        )
    return normalized


def author_search_settings_from_environment() -> AuthorSearchSettings | None:
    """Resolve an isolated author-search provider with legacy LLM fallbacks."""

    author_provider = os.getenv("AUTHOR_SEARCH_PROVIDER")
    llm_provider = os.getenv("LLM_PROVIDER")
    if author_provider:
        provider_value = author_provider
    elif llm_provider:
        try:
            provider_value = _normalized_author_search_provider(llm_provider)
        except ValueError:
            # A profile-extraction provider need not support hosted web search.
            return None
    else:
        provider_value = None
    try:
        normalized_llm = (
            _normalized_author_search_provider(llm_provider) if llm_provider else None
        )
    except ValueError:
        normalized_llm = None
    inherit_llm = not author_provider or (
        normalized_llm is not None
        and _normalized_author_search_provider(author_provider) == normalized_llm
    )
    base_url = os.getenv("AUTHOR_SEARCH_BASE_URL") or (
        os.getenv("LLM_BASE_URL") if inherit_llm else None
    )
    generic_key = os.getenv("AUTHOR_SEARCH_API_KEY") or (
        os.getenv("LLM_API_KEY") if inherit_llm else None
    )
    if provider_value:
        provider = _normalized_author_search_provider(provider_value)
    elif base_url and "deepseek.com" in base_url.casefold():
        provider = "deepseek"
    elif base_url and "openai.com" in base_url.casefold():
        provider = "openai"
    else:
        available = [
            name
            for name, key in (
                ("openai", os.getenv("OPENAI_API_KEY")),
                ("deepseek", os.getenv("DEEPSEEK_API_KEY")),
            )
            if key
        ]
        if len(available) == 1:
            provider = available[0]
        elif len(available) > 1:
            raise ValueError(
                "both OPENAI_API_KEY and DEEPSEEK_API_KEY are set; choose "
                "AUTHOR_SEARCH_PROVIDER"
            )
        elif generic_key:
            raise ValueError(
                "AUTHOR_SEARCH_API_KEY requires AUTHOR_SEARCH_PROVIDER"
            )
        else:
            return None

    provider_key = {
        "openai": os.getenv("OPENAI_API_KEY"),
        "deepseek": os.getenv("DEEPSEEK_API_KEY"),
        "openai_compatible": None,
    }[provider]
    api_key = generic_key or provider_key
    if not api_key:
        return None

    if not base_url and provider == "openai":
        base_url = os.getenv("OPENAI_BASE_URL")
    if not base_url and provider == "deepseek":
        base_url = "https://api.deepseek.com"
    model = os.getenv("AUTHOR_SEARCH_MODEL") or (
        os.getenv("LLM_MODEL") if inherit_llm else None
    )
    if not model:
        model = {
            "openai": "gpt-5.4-mini",
            "deepseek": "deepseek-v4-flash",
            "openai_compatible": "",
        }[provider]
    if provider == "openai_compatible" and (not base_url or not model):
        raise ValueError(
            "openai_compatible author search requires AUTHOR_SEARCH_BASE_URL "
            "and AUTHOR_SEARCH_MODEL"
        )
    return AuthorSearchSettings(provider, api_key, base_url, model)


def author_web_search_from_environment(
    *, timeout_seconds: float = 45.0
) -> AuthorWebSearch | None:
    settings = author_search_settings_from_environment()
    if settings is None:
        return None
    search_class = {
        "openai": OpenAIAuthorWebSearch,
        "deepseek": DeepSeekAuthorWebSearch,
        "openai_compatible": OpenAICompatibleAuthorWebSearch,
    }[settings.provider]
    return search_class(
        api_key=settings.api_key,
        base_url=settings.base_url,
        model=settings.model,
        timeout_seconds=timeout_seconds,
    )


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
        auto_author_homepages: bool = False,
        author_web_search: AuthorWebSearch | None = None,
        http_get: HttpGet | None = None,
    ) -> None:
        self.author_pages = list(author_pages)
        self.overrides = dict(overrides or {})
        self.use_arxiv = use_arxiv
        self.use_dblp = use_dblp
        self.use_doi = use_doi
        self.auto_author_homepages = auto_author_homepages
        self.author_web_search = author_web_search
        self.author_search_method = str(
            getattr(author_web_search, "discovery_method", "author_web_search")
        )
        self.http_get = http_get or _default_http_get
        self._http_cache: dict[str, HttpPayload] = {}
        self._discovered_author_pages: dict[str, list[str]] = {}

    def _get(self, url: str) -> HttpPayload:
        if url not in self._http_cache:
            self._http_cache[url] = self.http_get(url)
        return self._http_cache[url]

    @staticmethod
    def _candidate(
        url: str,
        provider: str,
        source_page: str | None = None,
        *,
        author_name: str | None = None,
        author_role: str | None = None,
        discovery_method: str | None = None,
    ) -> FullTextCandidate:
        return FullTextCandidate(
            url=url,
            provider=provider,
            source_page=source_page,
            priority=PROVIDER_PRIORITY[provider],
            author_name=author_name,
            author_role=author_role,
            discovery_method=discovery_method,
        )

    @staticmethod
    def _likely_fulltext_url(url: str) -> bool:
        parsed = urlsplit(url)
        decoded_path = unquote(parsed.path)
        path = decoded_path.casefold()
        filename = decoded_path.rsplit("/", 1)[-1]
        stem = filename[:-4] if filename.casefold().endswith(".pdf") else filename
        compact_stem = re.sub(r"[^a-z0-9]+", "", stem.casefold())
        obvious_profile_document = (
            compact_stem in {"cv", "resume", "curriculumvitae", "vita"}
            or re.search(
                r"(?:^|[-_.\d])(?:cv|resume|curriculum[-_.]?vitae|vita)$",
                stem,
                flags=re.IGNORECASE,
            )
            is not None
            or stem.endswith("CV")
        )
        if obvious_profile_document:
            return False
        return (
            path.endswith(".pdf")
            or "/pdf/" in path
            or (parsed.hostname or "").casefold().endswith("arxiv.org")
            and path.startswith("/pdf")
        )

    @staticmethod
    def _page_title_matches(text: str, expected_title: str) -> bool:
        """Require page-level identity before scanning every attachment.

        A paper title appearing somewhere in an author/DBLP publication index
        does not make every PDF on that page relevant.  Only title metadata or
        a page-level heading can authorize a whole-page attachment scan.
        """

        cleaned = unescape(text.replace("\\/", "/"))
        candidates: list[str] = []
        for tag in re.findall(r"<meta\b[^>]*>", cleaned, flags=re.IGNORECASE):
            attributes = {
                name.casefold(): value
                for name, value in re.findall(
                    r"([:\w-]+)\s*=\s*[\"']([^\"']*)[\"']", tag
                )
            }
            kind = (attributes.get("name") or attributes.get("property") or "").casefold()
            if kind in {"citation_title", "dc.title", "og:title", "twitter:title"}:
                candidates.append(attributes.get("content") or "")
        for match in re.findall(
            r"<(?:title|h1)\b[^>]*>(.*?)</(?:title|h1)>",
            cleaned,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            candidates.append(re.sub(r"<[^>]+>", " ", match))
        return any(_title_score(expected_title, candidate) >= 0.78 for candidate in candidates)

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

    @staticmethod
    def _fulltext_urls_on_page(text: str, page_url: str) -> list[str]:
        """Extract PDF-like links from a page whose title match was verified.

        University publication pages often render the title near the top but
        place attachments much farther down the document.  The small
        title-local window used for broad homepages therefore misses otherwise
        obvious links such as Drupal attachment blocks.
        """

        cleaned = unescape(text.replace("\\/", "/"))
        urls: list[str] = []
        for raw in re.findall(
            r"(?:href|src|data-url|url)\s*=\s*[\"']([^\"']+)[\"']",
            cleaned,
            flags=re.IGNORECASE,
        ):
            url = urljoin(page_url, raw.strip())
            if FullTextResolver._likely_fulltext_url(url):
                urls.append(url)
        for raw in re.findall(r"https?://[^\"'\s<>\\]+", cleaned):
            url = raw.rstrip(".,);]")
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
            discovered = self._urls_near_title(
                text, page.url, _preferred_title(paper)
            )
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
                        self._urls_near_title(
                            script_text, page.url, _preferred_title(paper)
                        )
                    )
                    if discovered:
                        break
            candidates.extend(
                self._candidate(url, "author_homepage", page_url)
                for url in dict.fromkeys(discovered)
            )
        return candidates

    @staticmethod
    def _author_match(
        returned_name: str, targets: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        normalized = _normalize(returned_name)
        return next(
            (
                target
                for target in targets
                if _normalize(str(target["display_name"])) == normalized
                or SequenceMatcher(
                    None, _normalize(str(target["display_name"])), normalized
                ).ratio()
                >= 0.82
            ),
            None,
        )

    def _crawl_auto_author_page(
        self,
        *,
        paper: PaperRecord,
        page_url: str,
        author: Mapping[str, Any],
        discovery_method: str = "known_author_homepage",
    ) -> list[FullTextCandidate]:
        try:
            page = self._get(page_url)
        except Exception:
            return []
        text = page.body.decode("utf-8", errors="replace")
        title = _preferred_title(paper)
        urls = self._urls_near_title(text, page.url, title)
        # Once the page itself clearly mentions the target title, scan its
        # whole attachment area.  Every resulting PDF is still independently
        # title-validated before the resolver accepts it.
        if self._page_title_matches(text, title):
            urls.extend(self._fulltext_urls_on_page(text, page.url))
        return [
            self._candidate(
                url,
                "author_homepage_auto",
                page.url,
                author_name=str(author["display_name"]),
                author_role=str(author["role"]),
                discovery_method=discovery_method,
            )
            for url in list(dict.fromkeys(urls))[:MAX_AUTO_AUTHOR_PAGE_CANDIDATES]
            if _safe_public_url(url)
        ]

    @staticmethod
    def _bounded_auto_candidates(
        candidates: Iterable[FullTextCandidate],
    ) -> tuple[list[FullTextCandidate], int]:
        deduplicated: dict[str, FullTextCandidate] = {}
        for candidate in candidates:
            deduplicated.setdefault(candidate.url, candidate)
        before_limit = len(deduplicated)
        return list(deduplicated.values())[:MAX_AUTO_AUTHOR_CANDIDATES], before_limit

    def _automatic_author_page_candidates(
        self,
        paper: PaperRecord,
        discovery: list[dict[str, Any]],
    ) -> list[FullTextCandidate]:
        targets = _selected_author_targets(paper)
        if not targets:
            discovery.append(
                {
                    "status": "skipped",
                    "method": "selected_author_homepage_search",
                    "detail": "paper has no usable authorship metadata",
                }
            )
            return []

        candidates: list[FullTextCandidate] = []
        for target in targets:
            cache_key = str(target.get("author_id") or target["display_name"]).casefold()
            homepage = _safe_public_url(target.get("homepage_url"))
            known_pages = [
                *(self._discovered_author_pages.get(cache_key) or []),
                *([homepage] if homepage else []),
            ]
            for page_url in dict.fromkeys(known_pages):
                candidates.extend(
                    self._crawl_auto_author_page(
                        paper=paper,
                        page_url=page_url,
                        author=target,
                        discovery_method="known_author_homepage",
                    )
                )
        if candidates:
            bounded, before_limit = self._bounded_auto_candidates(candidates)
            discovery.append(
                {
                    "status": "candidate_found",
                    "method": "cached_selected_author_homepage",
                    "authors": [
                        {"name": item["display_name"], "role": item["role"]}
                        for item in targets
                    ],
                    "candidate_count": len(bounded),
                    "candidate_count_before_limit": before_limit,
                    "candidate_limit": MAX_AUTO_AUTHOR_CANDIDATES,
                }
            )
            return bounded

        if self.author_web_search is None:
            discovery.append(
                {
                    "status": "unavailable",
                    "method": "selected_author_homepage_search",
                    "authors": [
                        {"name": item["display_name"], "role": item["role"]}
                        for item in targets
                    ],
                    "detail": "no web-search provider is configured",
                }
            )
            return []
        try:
            results = self.author_web_search(paper, targets)
        except Exception as error:
            discovery.append(
                {
                    "status": "failed",
                    "method": self.author_search_method,
                    "authors": [
                        {"name": item["display_name"], "role": item["role"]}
                        for item in targets
                    ],
                    "detail": f"{type(error).__name__}: {error}",
                }
            )
            return []

        accepted_pages: list[dict[str, Any]] = []
        for result in results:
            author = self._author_match(str(result.get("author_name") or ""), targets)
            if author is None:
                continue
            cache_key = str(author.get("author_id") or author["display_name"]).casefold()
            homepages = [
                url
                for item in result.get("homepage_urls") or []
                if (url := _safe_public_url(item)) is not None
            ]
            publication_pages = [
                url
                for item in result.get("publication_page_urls") or []
                if (url := _safe_public_url(item)) is not None
            ]
            pdf_urls = [
                url
                for item in result.get("pdf_urls") or []
                if (url := _safe_public_url(item)) is not None
                and self._likely_fulltext_url(url)
            ]
            self._discovered_author_pages.setdefault(cache_key, []).extend(homepages)
            source_page = next(iter(publication_pages or homepages), None)
            candidates.extend(
                self._candidate(
                    url,
                    "author_homepage_auto",
                    source_page,
                    author_name=str(author["display_name"]),
                    author_role=str(author["role"]),
                    discovery_method=self.author_search_method,
                )
                for url in pdf_urls
            )
            for page_url in dict.fromkeys([*publication_pages, *homepages]):
                if self._likely_fulltext_url(page_url):
                    candidates.append(
                        self._candidate(
                            page_url,
                            "author_homepage_auto",
                            page_url,
                            author_name=str(author["display_name"]),
                            author_role=str(author["role"]),
                            discovery_method=self.author_search_method,
                        )
                    )
                else:
                    candidates.extend(
                        self._crawl_auto_author_page(
                            paper=paper,
                            page_url=page_url,
                            author=author,
                            discovery_method=self.author_search_method,
                        )
                    )
            accepted_pages.append(
                {
                    "name": author["display_name"],
                    "role": author["role"],
                    "homepage_urls": homepages,
                    "publication_page_urls": publication_pages,
                    "pdf_urls": pdf_urls,
                }
            )

        bounded, before_limit = self._bounded_auto_candidates(candidates)
        discovery.append(
            {
                "status": "candidate_found" if bounded else "not_found",
                "method": self.author_search_method,
                "authors": accepted_pages
                or [
                    {"name": item["display_name"], "role": item["role"]}
                    for item in targets
                ],
                "candidate_count": len(bounded),
                "candidate_count_before_limit": before_limit,
                "candidate_limit": MAX_AUTO_AUTHOR_CANDIDATES,
            }
        )
        return bounded

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
        urls = self._urls_near_title(text, payload.url, _preferred_title(paper))
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
        title = _preferred_title(paper)
        query = urlencode(
            {
                "search_query": f'ti:"{title}"',
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
            score = SequenceMatcher(
                None, _normalize(_preferred_title(paper)), _normalize(title)
            ).ratio()
            if score < 0.72:
                continue
            entry_id = entry.findtext("atom:id", "", namespace)
            if entry_id:
                url = entry_id.replace("/abs/", "/pdf/")
                candidates.append(self._candidate(url, "arxiv", endpoint))
        return candidates

    def _dblp_candidates(self, paper: PaperRecord) -> list[FullTextCandidate]:
        title = _preferred_title(paper)
        endpoint = "https://dblp.org/search/publ/api?" + urlencode(
            {"q": title, "format": "json", "h": 5}
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
                None, _normalize(title), _normalize(str(info.get("title") or ""))
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
        self,
        paper: PaperRecord,
        author_discovery: list[dict[str, Any]] | None = None,
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
        if self.auto_author_homepages:
            yield self._automatic_author_page_candidates(
                paper, author_discovery if author_discovery is not None else []
            )

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
        author_discovery: list[dict[str, Any]] = []

        seen_urls: set[str] = set()
        for stage in self._candidate_stages(paper, author_discovery):
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
                    author_name=candidate.author_name,
                    author_role=candidate.author_role,
                    discovery_method=candidate.discovery_method,
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
                    score = self._validate_pdf(temporary, _preferred_title(paper))
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
                        selected_author=candidate.author_name,
                        selected_author_role=candidate.author_role,
                        discovery_method=candidate.discovery_method,
                        attempts=attempts,
                        author_discovery=author_discovery,
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
            author_discovery=author_discovery,
        )


def write_retrieval_index(
    results: Iterable[FullTextRetrievalResult], path: str | Path
) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Retrieval is often run for one newly discovered paper at a time.  Keep
    # the already validated records instead of silently replacing the index.
    records_by_id: dict[str, dict[str, Any]] = {}
    if output.exists():
        try:
            existing = json.loads(output.read_text(encoding="utf-8"))
            records_by_id.update(
                {
                    record["paper_id"]: record
                    for record in existing.get("papers", [])
                    if isinstance(record, dict) and record.get("paper_id")
                }
            )
        except (OSError, json.JSONDecodeError, TypeError):
            # A malformed cache should not prevent a fresh, auditable index
            # from being written from the validated results.
            records_by_id = {}
    for result in results:
        records_by_id[result.paper_id] = result.to_dict()
    records = sorted(records_by_id.values(), key=lambda record: record["paper_id"])
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
