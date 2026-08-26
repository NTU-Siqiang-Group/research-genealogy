"""Persistent, content-audited search result bundles.

Each user search owns a directory.  Raw provider responses, retrieved PDFs,
derived graphs, browser payloads, logs, and the exact request/configuration are
kept together so opening an old result never triggers retrieval again.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import threading
from typing import Any, Mapping


RESULT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,95}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str, limit: int = 36) -> str:
    normalized = "-".join(re.findall(r"[a-z0-9]+", value.casefold()))
    return (normalized[:limit].strip("-") or "search")


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def normalize_search_request(value: Mapping[str, Any]) -> dict[str, Any]:
    raw_seeds = value.get("seeds")
    if isinstance(raw_seeds, str):
        raw_seeds = raw_seeds.splitlines()
    if not isinstance(raw_seeds, list):
        raise ValueError("seeds must be a list or newline-delimited string")
    seeds: list[str] = []
    seen: set[str] = set()
    for item in raw_seeds:
        seed = str(item).strip()
        key = seed.casefold()
        if seed and key not in seen:
            seeds.append(seed)
            seen.add(key)
    if not seeds:
        raise ValueError("at least one paper title, OpenAlex ID, or DOI is required")
    if len(seeds) > 20:
        raise ValueError("at most 20 seeds are supported in one search")

    def bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
        result = int(value.get(name, default))
        if not minimum <= result <= maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}")
        return result

    provider = str(value.get("provider") or "openalex").strip().casefold()
    if provider != "openalex":
        raise ValueError("the persistent search pipeline currently supports openalex")
    topic = str(value.get("topic") or seeds[0]).strip()
    return {
        "seeds": seeds,
        "topic": topic,
        "provider": provider,
        "corpus_cap": bounded_int("corpus_cap", 100, 10, 500),
        "topic_search_limit": bounded_int("topic_search_limit", 40, 1, 100),
        "fulltext_limit": bounded_int("fulltext_limit", 16, 0, 100),
    }


def request_fingerprint(request: Mapping[str, Any]) -> str:
    stable = {
        key: request[key]
        for key in (
            "seeds",
            "topic",
            "provider",
            "corpus_cap",
            "topic_search_limit",
            "fulltext_limit",
        )
    }
    payload = json.dumps(stable, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ResultStore:
    def __init__(self, root: str | Path = "data/searches") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def result_dir(self, result_id: str) -> Path:
        if not RESULT_ID_RE.fullmatch(result_id):
            raise ValueError("invalid result ID")
        return self.root / result_id

    def create(
        self,
        request_value: Mapping[str, Any],
        *,
        result_id: str | None = None,
    ) -> dict[str, Any]:
        request = normalize_search_request(request_value)
        fingerprint = request_fingerprint(request)
        with self._lock:
            if result_id is None:
                stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
                base = f"{stamp}-{_slug(request['seeds'][0])}-{fingerprint[:6]}"
                result_id = base
                suffix = 2
                while (self.root / result_id).exists():
                    result_id = f"{base}-{suffix}"
                    suffix += 1
            directory = self.result_dir(result_id)
            if directory.exists():
                raise FileExistsError(f"result already exists: {result_id}")
            for relative in (
                "inputs",
                "raw/openalex",
                "raw/pdfs",
                "raw/fulltext",
                "outputs",
                "logs",
            ):
                (directory / relative).mkdir(parents=True, exist_ok=True)
            created_at = utc_now()
            record = {
                "schema_version": 1,
                "result_id": result_id,
                "fingerprint": fingerprint,
                "created_at": created_at,
                **request,
            }
            _atomic_json(directory / "request.json", record)
            _atomic_json(
                directory / "status.json",
                {
                    "schema_version": 1,
                    "result_id": result_id,
                    "state": "queued",
                    "stage": "queued",
                    "progress": 0,
                    "message": "Waiting to start",
                    "created_at": created_at,
                    "updated_at": created_at,
                },
            )
            return record

    def update_status(self, result_id: str, **changes: Any) -> dict[str, Any]:
        with self._lock:
            path = self.result_dir(result_id) / "status.json"
            current = _read_json(path, {}) or {}
            current.update(changes)
            current["schema_version"] = 1
            current["result_id"] = result_id
            current["updated_at"] = utc_now()
            _atomic_json(path, current)
            return current

    def get(self, result_id: str) -> dict[str, Any]:
        directory = self.result_dir(result_id)
        request = _read_json(directory / "request.json")
        if not isinstance(request, dict):
            raise FileNotFoundError(result_id)
        status = _read_json(directory / "status.json", {}) or {}
        inspector = _read_json(directory / "inspector.json", {}) or {}
        return {
            **request,
            "status": status,
            "summary": inspector.get("summary") if isinstance(inspector, dict) else None,
            "open_url": f"/web/?result={result_id}",
        }

    def list(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        with self._lock:
            for path in self.root.iterdir():
                if not path.is_dir() or not RESULT_ID_RE.fullmatch(path.name):
                    continue
                try:
                    records.append(self.get(path.name))
                except FileNotFoundError:
                    continue
        return sorted(records, key=lambda item: item.get("created_at", ""), reverse=True)

    def find_completed(self, fingerprint: str) -> dict[str, Any] | None:
        return next(
            (
                item
                for item in self.list()
                if item.get("fingerprint") == fingerprint
                and item.get("status", {}).get("state") == "completed"
            ),
            None,
        )

    def recover_interrupted(self) -> int:
        recovered = 0
        for item in self.list():
            if item.get("status", {}).get("state") == "running":
                self.update_status(
                    item["result_id"],
                    state="interrupted",
                    message="The previous server stopped while this search was running.",
                )
                recovered += 1
        return recovered

    @staticmethod
    def git_commit(workspace: str | Path) -> str | None:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=workspace,
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip() or None
        except (OSError, subprocess.CalledProcessError):
            return None

    def write_artifact_manifest(
        self, result_id: str, *, workspace: str | Path
    ) -> dict[str, Any]:
        directory = self.result_dir(result_id)
        artifacts = []
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.name == "artifact_manifest.json":
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            artifacts.append(
                {
                    "path": str(path.relative_to(directory)),
                    "bytes": path.stat().st_size,
                    "sha256": digest,
                }
            )
        manifest = {
            "schema_version": 1,
            "result_id": result_id,
            "generated_at": utc_now(),
            "git_commit": self.git_commit(workspace),
            "artifact_count": len(artifacts),
            "artifacts": artifacts,
        }
        _atomic_json(directory / "artifact_manifest.json", manifest)
        return manifest
