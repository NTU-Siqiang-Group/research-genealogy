import asyncio
import tempfile
from pathlib import Path
import unittest

from src.corpus_builder import CoIRetrievalAdapter, CorpusBuilder


class FakeCoISearcher:
    def __init__(self) -> None:
        self.calls = 0

    async def search_papers_async(self, query, **kwargs):
        self.calls += 1
        root = {
            "paperId": "root",
            "title": "The Log-Structured Merge-Tree (LSM-tree)",
            "year": 1996,
            "abstract": "LSM-tree key-value storage",
            "citationCount": 1000,
        }
        monkey = {
            "paperId": "monkey",
            "title": "Monkey: Optimal Navigable Key-Value Store",
            "year": 2017,
            "abstract": "Analytical LSM-tree optimization",
            "citationCount": 300,
        }
        unrelated = {
            "paperId": "unrelated",
            "title": "Primate behavior",
            "year": 2020,
            "abstract": "Animal behavior",
            "citationCount": 900,
        }
        if "Log-Structured" in query:
            if any(field.startswith("citations.") for field in kwargs["fields"]):
                root = dict(root, references=[], citations=[monkey])
            return {"data": [root]}
        if query == "LSM-tree optimization":
            return {"data": [monkey, unrelated]}
        return {"data": []}


class RateLimitedSearcher:
    async def search_papers_async(self, query, **kwargs):
        await asyncio.sleep(0.05)
        return {"data": []}


class CoIRetrievalAdapterTest(unittest.TestCase):
    def test_cache_prevents_repeated_upstream_calls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            searcher = FakeCoISearcher()
            adapter = CoIRetrievalAdapter(
                cache_dir=Path(directory) / "cache",
                paper_dir=Path(directory) / "papers",
                searcher=searcher,
            )
            first = asyncio.run(adapter.resolve_paper("The Log-Structured Merge-Tree"))
            second = asyncio.run(adapter.resolve_paper("The Log-Structured Merge-Tree"))
            self.assertEqual(first, second)
            self.assertEqual(searcher.calls, 1)
            self.assertEqual(first.paper_id, "S2:root")

    def test_one_hop_corpus_keeps_ids_and_forced_seed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            adapter = CoIRetrievalAdapter(
                cache_dir=Path(directory) / "cache",
                paper_dir=Path(directory) / "papers",
                searcher=FakeCoISearcher(),
            )
            result = asyncio.run(
                CorpusBuilder(adapter).build(
                    topic="LSM-tree optimization",
                    seeds=["The Log-Structured Merge-Tree"],
                    corpus_cap=2,
                    topic_search_limit=10,
                )
            )
            self.assertEqual(result.unresolved_seeds, [])
            self.assertEqual({p.paper_id for p in result.papers}, {"S2:root", "S2:monkey"})
            root = next(p for p in result.papers if p.paper_id == "S2:root")
            self.assertEqual(root.citations, ["S2:monkey"])

    def test_upstream_retry_loop_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            adapter = CoIRetrievalAdapter(
                cache_dir=Path(directory) / "cache",
                paper_dir=Path(directory) / "papers",
                searcher=RateLimitedSearcher(),
                request_timeout_seconds=0.001,
            )
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                asyncio.run(adapter.resolve_paper("anything"))


if __name__ == "__main__":
    unittest.main()
