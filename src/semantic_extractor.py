"""Optional CoI-compatible semantic-profile extraction."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
from typing import Any, Awaitable, Callable


AsyncLLMCall = Callable[[list[dict[str, str]]], Awaitable[str]]


def _bundled_reference_prompt(paper_content: str, topic: str) -> str:
    """Return a self-contained prompt compatible with the legacy CoI parser."""

    return f"""Analyze the supplied paper for the research topic: {topic}.

Extract topic-relevant entities; summarize the background, novelty,
contribution, methods, detailed rationale, and limitations; describe the
experimental design and baselines; and select the three most relevant references
by paper title. Prefer methodological, task, and baseline relevance.

Paper content:
{paper_content}

Return only this tagged structure:
<entities>entity names and short descriptions</entities>
<idea>Background: ...
Novelty: ...
Contribution: ...
Methods: ...
Detail reason: ...
Limitation: ...</idea>
<experiment>experimental process, technical details, and baselines</experiment>
<references>["Paper title 1", "Paper title 2", "Paper title 3"]</references>

Use <references>[]</references> when no reference is relevant to {topic}.
"""


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
        prompt_path = (
            self.upstream_path / "prompts" / "deep_research_agent_prompts.py"
        )
        if prompt_path.is_file():
            spec = importlib.util.spec_from_file_location(
                "research_genealogy_coi_prompts", prompt_path
            )
            if spec is None or spec.loader is None:
                raise RuntimeError(f"cannot load CoI prompt module: {prompt_path}")
            prompts = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(prompts)
            self._prompt_function = prompts.get_deep_reference_prompt
            self.prompt_source = f"coi_upstream:{prompt_path}"
        else:
            self._prompt_function = _bundled_reference_prompt
            self.prompt_source = "bundled_coi_compatible"

    async def extract(self, paper_content: str, topic: str) -> dict[str, Any]:
        prompt = self._prompt_function(paper_content, topic)
        raw_response = await self.llm_call([{"role": "user", "content": prompt}])
        if not isinstance(raw_response, str) or not raw_response.strip():
            raise RuntimeError("CoI extraction LLM returned an empty response")
        return {
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "prompt_source": self.prompt_source,
            "parsed_profile": parse_coi_response(raw_response),
            "raw_response": raw_response,
    }


@dataclass(slots=True, frozen=True)
class LLMSettings:
    provider: str
    api_key: str
    base_url: str | None
    model: str
    thinking: str = "disabled"


def _normalized_llm_provider(value: str) -> str:
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
            "LLM_PROVIDER must be openai, deepseek, or openai_compatible"
        )
    return normalized


def llm_settings_from_environment() -> LLMSettings:
    """Resolve provider-specific credentials without mixing unrelated keys."""

    provider_value = os.getenv("LLM_PROVIDER")
    base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    generic_key = os.getenv("LLM_API_KEY")
    if provider_value:
        provider = _normalized_llm_provider(provider_value)
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
                "LLM_PROVIDER"
            )
        elif generic_key:
            raise ValueError("LLM_API_KEY requires LLM_PROVIDER")
        else:
            raise RuntimeError(
                "LLM_API_KEY, OPENAI_API_KEY, or DEEPSEEK_API_KEY is required"
            )

    provider_key = {
        "openai": os.getenv("OPENAI_API_KEY"),
        "deepseek": os.getenv("DEEPSEEK_API_KEY"),
        "openai_compatible": None,
    }[provider]
    api_key = generic_key or provider_key
    if not api_key:
        raise RuntimeError(f"no API key is configured for LLM_PROVIDER={provider}")
    if provider == "deepseek" and not base_url:
        base_url = "https://api.deepseek.com"
    model = (
        os.getenv("LLM_MODEL")
        or os.getenv("CHEAP_LLM_MODEL")
        or os.getenv("MAIN_LLM_MODEL")
    )
    if not model:
        model = {
            "openai": "gpt-5.4-mini",
            "deepseek": "deepseek-chat",
            "openai_compatible": "",
        }[provider]
    if provider == "openai_compatible" and (not base_url or not model):
        raise ValueError(
            "openai_compatible requires LLM_BASE_URL and LLM_MODEL"
        )
    return LLMSettings(
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        thinking=os.getenv("LLM_THINKING", "disabled").casefold(),
    )


def llm_call_from_environment() -> AsyncLLMCall:
    """Create an OpenAI-compatible call for optional profile extraction."""

    from openai import AsyncAzureOpenAI, AsyncOpenAI

    use_azure = os.getenv("is_azure", "false").casefold() in {"1", "true", "yes"}
    if use_azure:
        model = (
            os.getenv("LLM_MODEL")
            or os.getenv("CHEAP_LLM_MODEL")
            or os.getenv("MAIN_LLM_MODEL")
        )
        if not model:
            raise RuntimeError("LLM_MODEL is required for Azure OpenAI")
        client = AsyncAzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_KEY"],
            api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
        )
        provider = "azure_openai"
        thinking = "disabled"
    else:
        settings = llm_settings_from_environment()
        model = settings.model
        provider = settings.provider
        thinking = settings.thinking
        client = AsyncOpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url or None,
        )

    async def call(messages: list[dict[str, str]]) -> str:
        if provider == "openai":
            response = await client.responses.create(
                model=model,
                input=messages,
                max_output_tokens=4000,
            )
            return response.output_text or ""
        request: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 4000,
            "timeout": 180,
        }
        if provider == "deepseek":
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
