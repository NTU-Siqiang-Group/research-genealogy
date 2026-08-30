import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.fulltext_retriever import (
    DeepSeekAuthorWebSearch,
    FullTextResolver,
    FullTextRetrievalResult,
    HttpPayload,
    MAX_AUTO_AUTHOR_CANDIDATES,
    OpenAIAuthorWebSearch,
    _preferred_title,
    _selected_author_targets,
    _title_score,
    author_search_settings_from_environment,
    author_web_search_from_environment,
    write_retrieval_index,
)
from src.schema import PaperRecord


class FullTextRetrieverTest(unittest.TestCase):
    def test_fulltext_url_detection_ignores_share_wrappers(self) -> None:
        self.assertTrue(
            FullTextResolver._likely_fulltext_url(
                "https://papers.example/target.pdf?download=true"
            )
        )
        self.assertTrue(
            FullTextResolver._likely_fulltext_url(
                "https://dl.example/doi/pdf/10.1000/target?download=true"
            )
        )
        self.assertFalse(
            FullTextResolver._likely_fulltext_url(
                "https://bsky.app/intent/compose?text=https%3A%2F%2Fpapers.example%2Fold.pdf"
            )
        )
        self.assertFalse(
            FullTextResolver._likely_fulltext_url(
                "https://www.bibsonomy.org/editPublication?url=https%3A%2F%2Fpapers.example%2Fold.pdf"
            )
        )
        self.assertFalse(
            FullTextResolver._likely_fulltext_url(
                "https://author.example/homepage_assets/pdf/2023TesicCV.pdf"
            )
        )
        self.assertFalse(
            FullTextResolver._likely_fulltext_url(
                "https://author.example/files/resume.pdf"
            )
        )

    def test_deepseek_author_search_uses_two_stage_responses_protocol(self) -> None:
        class SearchItem:
            type = "web_search_call"

            def model_dump(self, exclude_none=True):
                return {
                    "type": "web_search_call",
                    "id": "ws_1",
                    "status": "completed",
                    "action": {"type": "search", "query": "target"},
                }

        class SearchResponse:
            output = [SearchItem()]

        class CompletedEvent:
            type = "response.completed"
            response = SearchResponse()

        class SynthesisResponse:
            output_text = json.dumps(
                {
                    "authors": [
                        {
                            "author_name": "First Author",
                            "homepage_urls": ["https://first.example"],
                            "publication_page_urls": [],
                            "pdf_urls": ["https://first.example/target.pdf"],
                        }
                    ]
                }
            )

        class Responses:
            def __init__(self):
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                return [CompletedEvent()] if kwargs.get("stream") else SynthesisResponse()

        responses = Responses()
        search = DeepSeekAuthorWebSearch.__new__(DeepSeekAuthorWebSearch)
        search.client = type("Client", (), {"responses": responses})()
        search.model = "deepseek-v4-flash"
        search._cache = {}
        paper = PaperRecord("OPENALEX:W0", "Target Paper", 2025)
        result = search(
            paper,
            [
                {
                    "author_id": "OPENALEX:A1",
                    "display_name": "First Author",
                    "role": "first_author",
                    "institutions": ["Example University"],
                }
            ],
        )

        self.assertEqual(result[0]["author_name"], "First Author")
        self.assertEqual(len(responses.calls), 2)
        self.assertTrue(responses.calls[0]["stream"])
        self.assertEqual(
            responses.calls[1]["input"][1]["type"], "web_search_call"
        )

    def test_openai_author_search_uses_single_responses_call(self) -> None:
        class SearchItem:
            type = "web_search_call"

        class SearchResponse:
            output = [SearchItem()]
            output_text = json.dumps(
                {
                    "authors": [
                        {
                            "author_name": "First Author",
                            "homepage_urls": ["https://first.example"],
                            "publication_page_urls": [],
                            "pdf_urls": ["https://first.example/target.pdf"],
                        }
                    ]
                }
            )

        class Responses:
            def __init__(self):
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                return SearchResponse()

        responses = Responses()
        search = OpenAIAuthorWebSearch.__new__(OpenAIAuthorWebSearch)
        search.client = type("Client", (), {"responses": responses})()
        search.model = "gpt-5.4-mini"
        search._cache = {}
        result = search(
            PaperRecord("OPENALEX:W0", "Target Paper", 2025),
            [
                {
                    "author_id": "OPENALEX:A1",
                    "display_name": "First Author",
                    "role": "first_author",
                    "institutions": ["Example University"],
                }
            ],
        )

        self.assertEqual(result[0]["author_name"], "First Author")
        self.assertEqual(len(responses.calls), 1)
        self.assertEqual(responses.calls[0]["tools"], [{"type": "web_search"}])
        self.assertEqual(
            responses.calls[0]["text"]["format"]["name"],
            "author_homepage_candidates",
        )

    def test_openai_key_is_auto_detected_for_author_search(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai"}, clear=True):
            settings = author_search_settings_from_environment()

        self.assertIsNotNone(settings)
        assert settings is not None
        self.assertEqual(settings.provider, "openai")
        self.assertEqual(settings.model, "gpt-5.4-mini")
        self.assertIsNone(settings.base_url)

    def test_author_provider_override_does_not_inherit_other_provider_model(self) -> None:
        environment = {
            "AUTHOR_SEARCH_PROVIDER": "openai",
            "OPENAI_API_KEY": "test-openai",
            "LLM_PROVIDER": "deepseek",
            "LLM_MODEL": "deepseek-v4-flash",
            "LLM_BASE_URL": "https://api.deepseek.com",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = author_search_settings_from_environment()

        assert settings is not None
        self.assertEqual(settings.provider, "openai")
        self.assertEqual(settings.model, "gpt-5.4-mini")
        self.assertIsNone(settings.base_url)

    def test_compatible_author_provider_requires_explicit_endpoint_and_model(self) -> None:
        environment = {
            "AUTHOR_SEARCH_PROVIDER": "openai_compatible",
            "AUTHOR_SEARCH_API_KEY": "test-compatible",
        }
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(ValueError, "requires AUTHOR_SEARCH_BASE_URL"):
                author_search_settings_from_environment()

    def test_author_search_factory_builds_openai_adapter(self) -> None:
        environment = {
            "AUTHOR_SEARCH_PROVIDER": "openai",
            "OPENAI_API_KEY": "test-openai",
            "DEEPSEEK_API_KEY": "test-deepseek",
            "AUTHOR_SEARCH_MODEL": "gpt-5.4-mini",
        }
        with patch.dict(os.environ, environment, clear=True), patch(
            "src.fulltext_retriever.OpenAIAuthorWebSearch"
        ) as constructor:
            search = author_web_search_from_environment(timeout_seconds=17)

        self.assertIs(search, constructor.return_value)
        constructor.assert_called_once_with(
            api_key="test-openai",
            base_url=None,
            model="gpt-5.4-mini",
            timeout_seconds=17,
        )

    def test_two_provider_keys_require_an_explicit_author_choice(self) -> None:
        environment = {
            "OPENAI_API_KEY": "test-openai",
            "DEEPSEEK_API_KEY": "test-deepseek",
        }
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(ValueError, "choose AUTHOR_SEARCH_PROVIDER"):
                author_search_settings_from_environment()

    def test_selects_first_and_corresponding_authors_only(self) -> None:
        paper = PaperRecord(
            "OPENALEX:W0",
            "A Paper",
            metadata={
                "authorships": [
                    {
                        "author_id": "OPENALEX:A1",
                        "display_name": "First Author",
                        "byline_index": 0,
                        "author_position": "first",
                        "is_corresponding": False,
                    },
                    {
                        "author_id": "OPENALEX:A2",
                        "display_name": "Middle Author",
                        "byline_index": 1,
                        "author_position": "middle",
                        "is_corresponding": False,
                    },
                    {
                        "author_id": "OPENALEX:A3",
                        "display_name": "Corresponding Author",
                        "byline_index": 2,
                        "author_position": "last",
                        "is_corresponding": True,
                    },
                ]
            },
        )
        targets = _selected_author_targets(paper)
        self.assertEqual(
            [(item["display_name"], item["role"]) for item in targets],
            [
                ("First Author", "first_author"),
                ("Corresponding Author", "corresponding_author"),
            ],
        )

    def test_uses_last_author_proxy_when_corresponding_metadata_is_absent(self) -> None:
        paper = PaperRecord(
            "OPENALEX:W0",
            "Dostoevsky",
            metadata={
                "authorships": [
                    {
                        "author_id": "OPENALEX:A1",
                        "display_name": "Niv Dayan",
                        "byline_index": 0,
                        "author_position": "first",
                        "is_corresponding": False,
                    },
                    {
                        "author_id": "OPENALEX:A2",
                        "display_name": "Stratos Idreos",
                        "byline_index": 1,
                        "author_position": "last",
                        "is_corresponding": False,
                    },
                ]
            },
        )
        targets = _selected_author_targets(paper)
        self.assertEqual(
            [(item["display_name"], item["role"]) for item in targets],
            [
                ("Niv Dayan", "first_author"),
                ("Stratos Idreos", "last_author_proxy"),
            ],
        )

    def test_prefers_full_seed_title_over_acronym_provider_title(self) -> None:
        full_title = (
            "Dostoevsky: Better Space-Time Trade-Offs for LSM-Tree Based "
            "Key-Value Stores via Adaptive Removal of Superfluous Merging"
        )
        paper = PaperRecord(
            "OPENALEX:W0",
            "Dostoevsky",
            metadata={"title_aliases": [full_title]},
        )
        self.assertEqual(_preferred_title(paper), full_title)

    def test_discovers_pdf_from_javascript_author_page(self) -> None:
        homepage = "https://group.example/publication"
        script = "https://group.example/static/main.js"
        pdf = "https://venue.example/papers/arcekv.pdf"
        payloads = {
            homepage: HttpPayload(
                homepage,
                b'<html><script src="/static/main.js"></script></html>',
                "text/html",
            ),
            script: HttpPayload(
                script,
                (
                    '{"title":"ArceKV: Towards Workload-driven LSM-compactions '
                    'for Key-Value Store Under Dynamic Workloads",'
                    f'"href":"{pdf}"}}'
                ).encode(),
                "application/javascript",
            ),
        }
        resolver = FullTextResolver(
            author_pages=[homepage],
            use_arxiv=False,
            use_dblp=False,
            use_doi=False,
            http_get=payloads.__getitem__,
        )
        paper = PaperRecord(
            "OPENALEX:W1",
            "ArceKV: Towards Workload-driven LSM-compactions for Key-Value Store Under Dynamic Workloads",
            2026,
        )
        candidates = resolver.discover(paper)
        self.assertEqual(candidates[0].url, pdf)
        self.assertEqual(candidates[0].provider, "author_homepage")
        self.assertEqual(candidates[0].source_page, homepage)

    def test_openalex_location_is_a_fallback_candidate(self) -> None:
        paper = PaperRecord(
            "OPENALEX:W2",
            "A Paper",
            metadata={
                "openalex_locations": [
                    {"pdf_url": "https://repository.example/paper.pdf"}
                ]
            },
        )
        resolver = FullTextResolver(
            use_arxiv=False,
            use_dblp=False,
            use_doi=False,
        )
        candidate = resolver.discover(paper)[0]
        self.assertEqual(candidate.provider, "openalex_location")

    def test_title_validation_uses_first_page_token_coverage(self) -> None:
        expected = "ArceKV: Towards Workload-driven LSM-compactions for Key-Value Store Under Dynamic Workloads"
        self.assertGreater(_title_score(expected, expected + " Authors Abstract"), 0.95)
        self.assertLess(_title_score(expected, "An unrelated paper about graph drawing"), 0.3)

    def test_retrieve_stops_before_later_fallback_stages(self) -> None:
        homepage = "https://group.example/publication"
        pdf = "https://venue.example/paper.pdf"
        calls: list[str] = []

        def fake_get(url: str) -> HttpPayload:
            calls.append(url)
            if url == homepage:
                return HttpPayload(
                    homepage,
                    (
                        '<div>Target Paper Title '
                        f'<a href="{pdf}">paper</a></div>'
                    ).encode(),
                    "text/html",
                )
            if url == pdf:
                return HttpPayload(pdf, b"%PDF-fake", "application/pdf")
            raise AssertionError(f"later fallback should not be queried: {url}")

        paper = PaperRecord(
            "OPENALEX:W3",
            "Target Paper Title",
            metadata={"doi": "10.1000/slow-provider"},
        )
        resolver = FullTextResolver(
            author_pages=[homepage],
            use_arxiv=True,
            use_dblp=True,
            use_doi=True,
            http_get=fake_get,
        )
        with tempfile.TemporaryDirectory() as output_dir:
            with patch.object(FullTextResolver, "_validate_pdf", return_value=1.0):
                result = resolver.retrieve(paper, output_dir)

        self.assertEqual(result.status, "retrieved")
        self.assertEqual(result.selected_provider, "author_homepage")
        self.assertEqual(calls, [homepage, pdf])

    def test_automatic_author_search_is_audited_and_title_validated(self) -> None:
        pdf = "https://first.example/papers/target.pdf"
        seen_authors: list[tuple[str, str]] = []

        def fake_search(paper, authors):
            seen_authors.extend(
                (item["display_name"], item["role"]) for item in authors
            )
            return [
                {
                    "author_name": "First Author",
                    "homepage_urls": ["https://first.example/publications"],
                    "publication_page_urls": [],
                    "pdf_urls": [pdf],
                }
            ]

        fake_search.discovery_method = "openai_web_search"

        def fake_get(url: str) -> HttpPayload:
            if url == pdf:
                return HttpPayload(pdf, b"%PDF-fake", "application/pdf")
            raise AssertionError(f"unexpected URL: {url}")

        paper = PaperRecord(
            "OPENALEX:W4",
            "Target",
            metadata={
                "title_aliases": ["Target Paper Full Title"],
                "authorships": [
                    {
                        "author_id": "OPENALEX:A1",
                        "display_name": "First Author",
                        "byline_index": 0,
                        "author_position": "first",
                        "is_corresponding": False,
                    },
                    {
                        "author_id": "OPENALEX:A2",
                        "display_name": "Middle Author",
                        "byline_index": 1,
                        "author_position": "middle",
                        "is_corresponding": False,
                    },
                    {
                        "author_id": "OPENALEX:A3",
                        "display_name": "Corresponding Author",
                        "byline_index": 2,
                        "author_position": "last",
                        "is_corresponding": True,
                    },
                ],
            },
        )
        resolver = FullTextResolver(
            use_arxiv=False,
            use_dblp=False,
            use_doi=False,
            auto_author_homepages=True,
            author_web_search=fake_search,
            http_get=fake_get,
        )
        with tempfile.TemporaryDirectory() as output_dir:
            with patch.object(
                FullTextResolver, "_validate_pdf", return_value=1.0
            ) as validate:
                result = resolver.retrieve(paper, output_dir)

        self.assertEqual(
            seen_authors,
            [
                ("First Author", "first_author"),
                ("Corresponding Author", "corresponding_author"),
            ],
        )
        self.assertEqual(result.status, "retrieved")
        self.assertEqual(result.selected_provider, "author_homepage_auto")
        self.assertEqual(result.selected_author, "First Author")
        self.assertEqual(result.selected_author_role, "first_author")
        self.assertEqual(result.discovery_method, "openai_web_search")
        self.assertEqual(result.author_discovery[0]["status"], "candidate_found")
        validate.assert_called_once()
        self.assertEqual(validate.call_args.args[1], "Target Paper Full Title")

    def test_auto_author_page_finds_attachment_far_from_title(self) -> None:
        page = "https://author.example/publications/target"
        pdf = "https://author.example/files/target.pdf"
        title = "Target Paper Full Title"

        def fake_search(paper, authors):
            return [
                {
                    "author_name": "First Author",
                    "homepage_urls": [],
                    "publication_page_urls": [page],
                    "pdf_urls": [],
                }
            ]

        def fake_get(url: str) -> HttpPayload:
            if url == page:
                return HttpPayload(
                    page,
                    (
                        f"<h1>{title}</h1>"
                        + ("<div>publication metadata</div>" * 200)
                        + '<a href="/files/target.pdf">Download paper</a>'
                    ).encode(),
                    "text/html",
                )
            if url == pdf:
                return HttpPayload(pdf, b"%PDF-fake", "application/pdf")
            raise AssertionError(f"unexpected URL: {url}")

        paper = PaperRecord(
            "OPENALEX:W5",
            title,
            metadata={
                "authorships": [
                    {
                        "author_id": "OPENALEX:A1",
                        "display_name": "First Author",
                        "byline_index": 0,
                        "author_position": "first",
                        "is_corresponding": True,
                    }
                ]
            },
        )
        resolver = FullTextResolver(
            use_arxiv=False,
            use_dblp=False,
            use_doi=False,
            auto_author_homepages=True,
            author_web_search=fake_search,
            http_get=fake_get,
        )
        with tempfile.TemporaryDirectory() as output_dir:
            with patch.object(FullTextResolver, "_validate_pdf", return_value=1.0):
                result = resolver.retrieve(paper, output_dir)

        self.assertEqual(result.status, "retrieved")
        self.assertEqual(result.selected_url, pdf)
        self.assertEqual(result.source_page, page)
        self.assertEqual(result.selected_author, "First Author")

    def test_auto_author_index_only_extracts_pdf_near_target_title(self) -> None:
        page = "https://author.example/publications"
        target_pdf = "https://author.example/papers/bam-ann.pdf"
        old_pdf = "https://author.example/papers/old-work.pdf"
        title = (
            "Accelerating Vector Search at Scale: BAM-ANN with Batch-Aware "
            "Memory-Disk Hybrid Indexing"
        )

        def fake_search(paper, authors):
            return [
                {
                    "author_name": "First Author",
                    "homepage_urls": [page],
                    "publication_page_urls": [],
                    "pdf_urls": [],
                }
            ]

        page_html = (
            "<html><head><title>First Author — Publications</title></head><body>"
            f'<a href="{old_pdf}">Old work</a>'
            + ("<p>unrelated publication metadata</p>" * 100)
            + f'<article><h2>{title}</h2><a href="{target_pdf}">PDF</a></article>'
            + ("<p>more unrelated publication metadata</p>" * 100)
            + '<a href="https://bsky.app/intent/compose?text=https%3A%2F%2Fpapers.example%2Fold.pdf">Share</a>'
            + "</body></html>"
        )
        paper = PaperRecord(
            "OPENALEX:W6",
            title,
            metadata={
                "authorships": [
                    {
                        "author_id": "OPENALEX:A1",
                        "display_name": "First Author",
                        "byline_index": 0,
                        "author_position": "first",
                        "is_corresponding": True,
                    }
                ]
            },
        )
        resolver = FullTextResolver(
            use_arxiv=False,
            use_dblp=False,
            use_doi=False,
            auto_author_homepages=True,
            author_web_search=fake_search,
            http_get=lambda url: HttpPayload(page, page_html.encode(), "text/html"),
        )

        candidates = resolver.discover(paper)

        self.assertEqual([candidate.url for candidate in candidates], [target_pdf])

    def test_auto_author_candidates_have_audited_safety_limit(self) -> None:
        def fake_search(paper, authors):
            return [
                {
                    "author_name": "First Author",
                    "homepage_urls": [],
                    "publication_page_urls": [],
                    "pdf_urls": [
                        f"https://author.example/papers/candidate-{index}.pdf"
                        for index in range(MAX_AUTO_AUTHOR_CANDIDATES + 5)
                    ],
                }
            ]

        paper = PaperRecord(
            "OPENALEX:W7",
            "Target Paper",
            metadata={
                "authorships": [
                    {
                        "author_id": "OPENALEX:A1",
                        "display_name": "First Author",
                        "byline_index": 0,
                        "author_position": "first",
                        "is_corresponding": True,
                    }
                ]
            },
        )
        resolver = FullTextResolver(
            use_arxiv=False,
            use_dblp=False,
            use_doi=False,
            auto_author_homepages=True,
            author_web_search=fake_search,
        )
        discovery: list[dict] = []

        candidates = resolver._automatic_author_page_candidates(paper, discovery)

        self.assertEqual(len(candidates), MAX_AUTO_AUTHOR_CANDIDATES)
        self.assertEqual(discovery[0]["candidate_count"], MAX_AUTO_AUTHOR_CANDIDATES)
        self.assertEqual(
            discovery[0]["candidate_count_before_limit"],
            MAX_AUTO_AUTHOR_CANDIDATES + 5,
        )
        self.assertEqual(discovery[0]["candidate_limit"], MAX_AUTO_AUTHOR_CANDIDATES)

    def test_retrieval_index_merges_incremental_runs(self) -> None:
        with tempfile.TemporaryDirectory() as output_dir:
            index = Path(output_dir) / "retrieval_index.json"
            write_retrieval_index(
                [FullTextRetrievalResult("OPENALEX:W1", "First", "retrieved")],
                index,
            )
            write_retrieval_index(
                [FullTextRetrievalResult("OPENALEX:W2", "Second", "retrieved")],
                index,
            )
            records = json.loads(index.read_text(encoding="utf-8"))["papers"]

        self.assertEqual(
            [record["paper_id"] for record in records],
            ["OPENALEX:W1", "OPENALEX:W2"],
        )


if __name__ == "__main__":
    unittest.main()
