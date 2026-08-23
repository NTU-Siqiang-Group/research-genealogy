import tempfile
import unittest
from unittest.mock import patch

from src.fulltext_retriever import FullTextResolver, HttpPayload, _title_score
from src.schema import PaperRecord


class FullTextRetrieverTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
