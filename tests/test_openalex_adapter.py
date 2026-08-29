import asyncio
import tempfile
from pathlib import Path
import unittest

from src.corpus_builder import CorpusBuilder
from src.openalex_adapter import OpenAlexRetrievalAdapter, paper_from_openalex


ROOT = {
    "id": "https://openalex.org/W1",
    "title": "The Log-Structured Merge-Tree (LSM-tree)",
    "publication_year": 1996,
    "cited_by_count": 1000,
    "referenced_works": [],
    "abstract_inverted_index": {"Log-structured": [0], "storage": [1]},
}
MONKEY = {
    "id": "https://openalex.org/W2",
    "title": "Monkey: Optimal Navigable Key-Value Store",
    "publication_year": 2017,
    "cited_by_count": 300,
    "referenced_works": ["https://openalex.org/W1"],
    "authorships": [
        {
            "author_position": "first",
            "author": {
                "id": "https://openalex.org/A1",
                "display_name": "Niv Dayan",
            },
            "is_corresponding": False,
        },
        {
            "author_position": "last",
            "author": {
                "id": "https://openalex.org/A2",
                "display_name": "Stratos Idreos",
            },
            "is_corresponding": False,
        },
    ],
    "corresponding_author_ids": ["https://openalex.org/A2"],
    "locations": [
        {
            "pdf_url": "https://example.org/monkey.pdf",
            "landing_page_url": "https://example.org/monkey",
            "source": {"display_name": "Example Repository"},
            "is_oa": True,
        }
    ],
}


class FakeOpenAlexTransport:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, path, params):
        self.calls += 1
        if path == "/works/W1":
            return ROOT
        if params.get("filter") == "cites:W1":
            return {"results": [MONKEY]}
        if str(params.get("filter", "")).startswith("openalex:"):
            requested = str(params["filter"])
            return {
                "results": [
                    item
                    for item in (ROOT, MONKEY)
                    if item["id"].rsplit("/", 1)[-1] in requested
                ]
            }
        if params.get("search") == "LSM-tree optimization":
            return {"results": [MONKEY]}
        return {"results": [ROOT]}


class OpenAlexAdapterTest(unittest.TestCase):
    def test_maps_ids_abstract_and_references(self) -> None:
        paper = paper_from_openalex(MONKEY)
        self.assertEqual(paper.paper_id, "OPENALEX:W2")
        self.assertEqual(paper.references, ["OPENALEX:W1"])
        self.assertEqual(paper.pdf_url, "https://example.org/monkey.pdf")
        self.assertEqual(paper.metadata["authors"], ["Niv Dayan", "Stratos Idreos"])
        self.assertEqual(
            paper.metadata["authorships"],
            [
                {
                    "author_id": "OPENALEX:A1",
                    "display_name": "Niv Dayan",
                    "orcid": None,
                    "homepage_url": None,
                    "byline_index": 0,
                    "author_position": "first",
                    "is_corresponding": False,
                    "institutions": [],
                },
                {
                    "author_id": "OPENALEX:A2",
                    "display_name": "Stratos Idreos",
                    "orcid": None,
                    "homepage_url": None,
                    "byline_index": 1,
                    "author_position": "last",
                    "is_corresponding": True,
                    "institutions": [],
                },
            ],
        )
        root = paper_from_openalex(ROOT)
        self.assertEqual(root.abstract, "Log-structured storage")

    def test_acronym_only_openalex_title_resolves_long_seed(self) -> None:
        match = OpenAlexRetrievalAdapter._best_match(
            "Monkey: Optimal Navigable Key-Value Store",
            [{**MONKEY, "title": "Monkey"}],
        )
        self.assertIsNotNone(match)

    def test_authorship_hydration_preserves_pipeline_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            transport = FakeOpenAlexTransport()
            adapter = OpenAlexRetrievalAdapter(
                cache_dir=directory, transport=transport
            )
            local = paper_from_openalex({**MONKEY, "authorships": []})
            local.cluster_paths = {"solution": ["local-cluster"]}
            hydrated = asyncio.run(adapter.hydrate_authorship_metadata([local]))
            self.assertEqual(hydrated[0].cluster_paths, {"solution": ["local-cluster"]})
            self.assertEqual(hydrated[0].metadata["authors"][0], "Niv Dayan")
            self.assertEqual(hydrated[0].metadata["authorship_source"], "openalex")

    def test_cache_and_corpus_builder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            transport = FakeOpenAlexTransport()
            adapter = OpenAlexRetrievalAdapter(
                cache_dir=Path(directory), transport=transport
            )
            first = asyncio.run(adapter.resolve_paper("The Log-Structured Merge-Tree"))
            second = asyncio.run(adapter.resolve_paper("The Log-Structured Merge-Tree"))
            self.assertEqual(first, second)
            self.assertEqual(transport.calls, 1)
            result = asyncio.run(
                CorpusBuilder(adapter).build(
                    topic="LSM-tree optimization",
                    seeds=["The Log-Structured Merge-Tree"],
                    corpus_cap=2,
                    topic_search_limit=10,
                )
            )
            self.assertEqual(result.unresolved_seeds, [])
            self.assertEqual(
                {paper.paper_id for paper in result.papers},
                {"OPENALEX:W1", "OPENALEX:W2"},
            )


if __name__ == "__main__":
    unittest.main()
