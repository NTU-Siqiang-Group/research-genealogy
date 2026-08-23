#!/usr/bin/env python3
"""Verify that local upstream checkouts match upstream.lock and remain clean."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]


def git(path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> int:
    lock = yaml.safe_load((ROOT / "upstream.lock").read_text(encoding="utf-8"))
    locations = {
        "coi_agent": ROOT / "upstream/CoI-Agent",
        "science_hierarchography": ROOT / "upstream/science-hierarchography",
    }
    result = {}
    failed = False
    for name, path in locations.items():
        expected = str(lock[name]["commit"])
        actual = git(path, "rev-parse", "HEAD")
        status = git(path, "status", "--short")
        item = {
            "expected_commit": expected,
            "actual_commit": actual,
            "commit_matches": actual == expected,
            "working_tree_clean": not status,
        }
        result[name] = item
        failed = failed or not item["commit_matches"] or not item["working_tree_clean"]
    result["licensing"] = {
        "coi_agent_license_present": (locations["coi_agent"] / "LICENSE").exists(),
        "science_hierarchography_license_present": (
            locations["science_hierarchography"] / "LICENSE"
        ).exists(),
    }
    result["packaging"] = {
        "coi_agent_requirements_present": (
            locations["coi_agent"] / "requirements.txt"
        ).exists(),
        "science_hierarchography_requirements_present": (
            locations["science_hierarchography"] / "requirements.txt"
        ).exists(),
    }
    print(json.dumps(result, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

