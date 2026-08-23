"""Thin wrapper around CoI's existing deep-reference extraction prompt."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Awaitable, Callable


AsyncLLMCall = Callable[[list[dict[str, str]]], Awaitable[str]]


def _between(text: str, tag: str) -> str:
    match = re.search(fr"<{tag}>(.*?)</{tag}>", text, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def parse_coi_response(raw_response: str) -> dict[str, Any]:
    """Parse CoI's tagged response without semantically rewriting its fields."""

    idea = _between(raw_response, "idea")
    profile: dict[str, Any] = {}
    field_pattern = re.compile(
        r"(?im)^\s*(Background|Novelty|Contribution|Methods?|Detail\s+reason|Limitations?)\s*:\s*"
    )
    matches = list(field_pattern.finditer(idea))
    aliases = {
        "background": "background",
        "novelty": "novelty",
        "contribution": "contribution",
        "method": "methods",
        "methods": "methods",
        "detail reason": "detail_reason",
        "limitation": "limitation",
        "limitations": "limitation",
    }
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(idea)
        key = aliases[" ".join(match.group(1).casefold().split())]
        profile[key] = idea[match.end() : end].strip()
    profile["experiment"] = _between(raw_response, "experiment")
    profile["entities"] = _between(raw_response, "entities")
    references = _between(raw_response, "references")
    try:
        decoded = json.loads(references) if references else []
        profile["selected_references"] = decoded if isinstance(decoded, list) else []
    except json.JSONDecodeError:
        profile["selected_references"] = []
    return profile


class CoISemanticExtractor:
    def __init__(
        self,
        llm_call: AsyncLLMCall,
        *,
        upstream_path: str | Path = "upstream/CoI-Agent",
    ) -> None:
        self.llm_call = llm_call
        self.upstream_path = Path(upstream_path).resolve()
        path = str(self.upstream_path)
        sys.path.insert(0, path)
        try:
            prompts = importlib.import_module("prompts.deep_research_agent_prompts")
            self._prompt_function = prompts.get_deep_reference_prompt
        finally:
            if sys.path and sys.path[0] == path:
                sys.path.pop(0)

    async def extract(self, paper_content: str, topic: str) -> dict[str, Any]:
        prompt = self._prompt_function(paper_content, topic)
        raw_response = await self.llm_call([{"role": "user", "content": prompt}])
        if not isinstance(raw_response, str) or not raw_response.strip():
            raise RuntimeError("CoI extraction LLM returned an empty response")
        return {
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "parsed_profile": parse_coi_response(raw_response),
            "raw_response": raw_response,
        }


def llm_call_from_environment() -> AsyncLLMCall:
    """Create an OpenAI-compatible call while retaining CoI's prompt verbatim."""

    from openai import AsyncAzureOpenAI, AsyncOpenAI

    model = (
        os.getenv("LLM_MODEL")
        or os.getenv("CHEAP_LLM_MODEL")
        or os.getenv("MAIN_LLM_MODEL")
    )
    if not model:
        raise RuntimeError("CHEAP_LLM_MODEL or MAIN_LLM_MODEL is required")
    use_azure = os.getenv("is_azure", "false").casefold() in {"1", "true", "yes"}
    base_url: str | None = None
    if use_azure:
        client = AsyncAzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_KEY"],
            api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
        )
    else:
        api_key = (
            os.getenv("LLM_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY")
            or os.getenv("OPENAI_API_KEY")
        )
        if not api_key:
            raise RuntimeError(
                "LLM_API_KEY, DEEPSEEK_API_KEY, or OPENAI_API_KEY is required"
            )
        base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url or None,
        )

    async def call(messages: list[dict[str, str]]) -> str:
        request: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 4000,
            "timeout": 180,
        }
        provider = os.getenv("LLM_PROVIDER", "").casefold()
        thinking = os.getenv("LLM_THINKING", "disabled").casefold()
        if provider == "deepseek" or (base_url and "api.deepseek.com" in base_url):
            request["extra_body"] = {
                "thinking": {
                    "type": "enabled" if thinking == "enabled" else "disabled"
                }
            }
        response = await client.chat.completions.create(
            **request,
        )
        content = response.choices[0].message.content
        return content or ""

    return call


# Backward-compatible name used by the first P0 scripts and external callers.
openai_llm_call_from_environment = llm_call_from_environment
