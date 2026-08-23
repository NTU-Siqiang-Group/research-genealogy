import asyncio
import unittest

from src.semantic_extractor import CoISemanticExtractor, parse_coi_response


RAW = """<entities>FLSM-tree: flexible structure</entities>
<idea>Background: static workloads
Novelty: online transitions
Contribution: adaptive optimization
Methods: reinforcement learning
Detail reason: efficient structural changes
Limitation: training cost</idea>
<experiment>Compare tail latency.</experiment>
<references>["Monkey", "Dostoevsky"]</references>"""


class SemanticExtractorTest(unittest.TestCase):
    def test_parser_preserves_coi_fields(self) -> None:
        profile = parse_coi_response(RAW)
        self.assertEqual(profile["methods"], "reinforcement learning")
        self.assertEqual(profile["selected_references"], ["Monkey", "Dostoevsky"])

    def test_uses_upstream_prompt_and_keeps_raw_response(self) -> None:
        captured = []

        async def fake_call(messages):
            captured.extend(messages)
            return RAW

        result = asyncio.run(
            CoISemanticExtractor(fake_call).extract("Title: RusKey", "LSM trees")
        )
        self.assertEqual(result["raw_response"], RAW)
        self.assertIn("three most relevant references", captured[0]["content"])
        self.assertEqual(len(result["prompt_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()

