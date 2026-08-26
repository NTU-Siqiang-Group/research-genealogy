"""Helpers kept separate so migration behavior can be unit tested."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


def rewrite_path_prefixes(
    value: Any, replacements: Mapping[str, str]
) -> Any:
    """Recursively rewrite saved local paths, or rewrite a JSON file in place."""

    if isinstance(value, Path):
        payload = json.loads(value.read_text(encoding="utf-8"))
        rewritten = rewrite_path_prefixes(payload, replacements)
        value.write_text(
            json.dumps(rewritten, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return rewritten
    if isinstance(value, dict):
        return {
            key: rewrite_path_prefixes(item, replacements)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [rewrite_path_prefixes(item, replacements) for item in value]
    if isinstance(value, str):
        for source, target in replacements.items():
            if value.startswith(source):
                return target + value[len(source):]
    return value
