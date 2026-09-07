import unittest

from src.search_pipeline import select_fulltext_candidates


class SearchPipelineTest(unittest.TestCase):
    def test_fulltext_selection_prioritizes_seed_then_direct_descendant(self) -> None:
        corpus = {
            "papers": [
                {
                    "paper_id": "P:old",
                    "title": "Seed Paper",
                    "year": 2020,
                    "references": [],
                    "citations": ["P:new"],
                    "metadata": {"citation_count": 100},
                },
                {
                    "paper_id": "P:new",
                    "title": "Direct Follow-up",
                    "year": 2024,
                    "references": ["P:old"],
                    "citations": [],
                    "metadata": {"citation_count": 5},
                },
                {
                    "paper_id": "P:topic",
                    "title": "Topic Result",
                    "year": 2025,
                    "references": [],
                    "citations": [],
                    "metadata": {"citation_count": 500},
                },
            ]
        }
        selected = select_fulltext_candidates(corpus, ["Seed Paper"], 2)
        self.assertEqual(
            [item["paper_id"] for item in selected], ["P:old", "P:new"]
        )
        self.assertEqual(selected[1]["selection_reason"], "direct_descendant")

    def test_fulltext_selection_supports_multiple_seed_ids(self) -> None:
        corpus = {
            "papers": [
                {"paper_id": "OPENALEX:W1", "title": "One", "year": 2020},
                {"paper_id": "OPENALEX:W2", "title": "Two", "year": 2021},
                {"paper_id": "OPENALEX:W3", "title": "Three", "year": 2022},
            ]
        }
        selected = select_fulltext_candidates(
            corpus, ["OPENALEX:W2", "OPENALEX:W1"], 2
        )
        self.assertEqual(
            {item["paper_id"] for item in selected},
            {"OPENALEX:W1", "OPENALEX:W2"},
        )

    def test_semantic_candidate_can_survive_missing_provider_citation(self) -> None:
        corpus = {
            "papers": [
                {
                    "paper_id": "P:seed",
                    "title": "GPU Offloading for Language Model Inference",
                    "year": 2023,
                    "abstract": "Offload model weights and the KV cache between GPU and CPU memory.",
                    "references": [],
                    "metadata": {"citation_count": 20},
                },
                {
                    "paper_id": "P:noisy-citer",
                    "title": "A General Software Engineering Survey",
                    "year": 2025,
                    "abstract": "A broad review of software engineering research.",
                    "references": ["P:seed"],
                    "metadata": {"citation_count": 500},
                },
                {
                    "paper_id": "P:metadata-gap",
                    "title": "Dynamic KV Cache Management for Language Model Inference",
                    "year": 2024,
                    "abstract": "Efficient CPU GPU KV cache prefetching for offloading systems.",
                    # Model the OpenAlex failure: the PDF cites the seed, but
                    # referenced_works is empty in provider metadata.
                    "references": [],
                    "metadata": {"citation_count": 1},
                },
            ]
        }

        selected = select_fulltext_candidates(
            corpus, ["GPU Offloading for Language Model Inference"], 2
        )

        self.assertEqual(
            [item["paper_id"] for item in selected],
            ["P:seed", "P:metadata-gap"],
        )
        self.assertEqual(selected[1]["selection_reason"], "semantic_neighbor")
        self.assertGreater(selected[1]["semantic_similarity"], 0)


if __name__ == "__main__":
    unittest.main()
