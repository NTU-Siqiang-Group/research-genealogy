import asyncio
import os
import tempfile
import unittest
from unittest.mock import patch

from src.semantic_extractor import (
    CoISemanticExtractor,
    llm_call_from_environment,
    llm_settings_from_environment,
    parse_coi_response,
)


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

    def test_bundled_prompt_keeps_clean_clone_self_contained(self) -> None:
        captured = []

        async def fake_call(messages):
            captured.extend(messages)
            return RAW

        with tempfile.TemporaryDirectory() as directory:
            result = asyncio.run(
                CoISemanticExtractor(fake_call, upstream_path=directory).extract(
                    "Title: RusKey", "LSM trees"
                )
            )
        self.assertEqual(result["raw_response"], RAW)
        self.assertIn("three most relevant references", captured[0]["content"])
        self.assertEqual(len(result["prompt_sha256"]), 64)
        self.assertEqual(result["prompt_source"], "bundled_coi_compatible")

    def test_openai_key_gets_safe_defaults(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai"}, clear=True):
            settings = llm_settings_from_environment()

        self.assertEqual(settings.provider, "openai")
        self.assertEqual(settings.model, "gpt-5.4-mini")
        self.assertIsNone(settings.base_url)

    def test_deepseek_key_remains_supported(self) -> None:
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-deepseek"}, clear=True):
            settings = llm_settings_from_environment()

        self.assertEqual(settings.provider, "deepseek")
        self.assertEqual(settings.model, "deepseek-chat")
        self.assertEqual(settings.base_url, "https://api.deepseek.com")

    def test_generic_key_requires_explicit_provider(self) -> None:
        with patch.dict(os.environ, {"LLM_API_KEY": "test-generic"}, clear=True):
            with self.assertRaisesRegex(ValueError, "requires LLM_PROVIDER"):
                llm_settings_from_environment()

    def test_openai_profile_extraction_uses_responses_api(self) -> None:
        class Responses:
            def __init__(self):
                self.calls = []

            async def create(self, **kwargs):
                self.calls.append(kwargs)
                return type("Response", (), {"output_text": RAW})()

        responses = Responses()
        client = type("Client", (), {"responses": responses})()
        environment = {
            "LLM_PROVIDER": "openai",
            "OPENAI_API_KEY": "test-openai",
            "LLM_MODEL": "gpt-5.4-mini",
        }
        with patch.dict(os.environ, environment, clear=True), patch(
            "openai.AsyncOpenAI", return_value=client
        ):
            call = llm_call_from_environment()
            result = asyncio.run(call([{"role": "user", "content": "paper"}]))

        self.assertEqual(result, RAW)
        self.assertEqual(len(responses.calls), 1)
        self.assertEqual(responses.calls[0]["model"], "gpt-5.4-mini")
        self.assertNotIn("messages", responses.calls[0])


if __name__ == "__main__":
    unittest.main()
