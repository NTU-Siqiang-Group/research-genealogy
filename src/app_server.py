"""Small local web/API server for persistent genealogy searches."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import json
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from typing import Any, Callable, Mapping
from urllib.parse import unquote, urlsplit

from .result_store import (
    RESULT_ID_RE,
    ResultStore,
    normalize_search_request,
    request_fingerprint,
)
from .search_pipeline import SearchPipeline


PipelineFactory = Callable[[], SearchPipeline]


class SearchManager:
    """Serialize expensive runs while keeping the web interface responsive."""

    def __init__(
        self,
        store: ResultStore,
        pipeline_factory: PipelineFactory,
        *,
        workers: int = 1,
    ) -> None:
        self.store = store
        self.pipeline_factory = pipeline_factory
        self.executor = ThreadPoolExecutor(
            max_workers=max(1, workers), thread_name_prefix="genealogy-search"
        )
        self._lock = threading.RLock()
        self._futures: dict[str, Future[None]] = {}
        self.store.recover_interrupted()

    def submit(self, value: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        force = bool(value.get("force", False))
        request = normalize_search_request(value)
        fingerprint = request_fingerprint(request)
        with self._lock:
            if not force:
                existing = self.store.find_completed(fingerprint)
                if existing:
                    return existing, True
            record = self.store.create(request)
            result_id = record["result_id"]
            future = self.executor.submit(self.pipeline_factory().run, result_id)
            self._futures[result_id] = future
            future.add_done_callback(
                lambda _future, item=result_id: self._discard_future(item)
            )
            return self.store.get(result_id), False

    def _discard_future(self, result_id: str) -> None:
        with self._lock:
            self._futures.pop(result_id, None)

    def close(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=False)


def make_handler(
    *, workspace: str | Path, manager: SearchManager
) -> type[SimpleHTTPRequestHandler]:
    root = Path(workspace).resolve()

    class GenealogyHandler(SimpleHTTPRequestHandler):
        server_version = "ResearchGenealogy/0.2"

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(root), **kwargs)

        def _json(self, value: Any, status: int = HTTPStatus.OK) -> None:
            body = (json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _error(self, message: str, status: int) -> None:
            self._json({"error": message}, status)

        def _result_route(self, path: str) -> tuple[str, str | None] | None:
            parts = [unquote(item) for item in path.strip("/").split("/")]
            if len(parts) not in {3, 4} or parts[:2] != ["api", "results"]:
                return None
            result_id = parts[2]
            if not RESULT_ID_RE.fullmatch(result_id):
                return None
            return result_id, parts[3] if len(parts) == 4 else None

        def _serve_static(self, path: str) -> None:
            request_path = "/web/home.html" if path == "/" else path
            candidate = (root / unquote(request_path).lstrip("/")).resolve()
            web_root = (root / "web").resolve()
            try:
                relative = candidate.relative_to(root)
            except ValueError:
                self._error("not found", HTTPStatus.NOT_FOUND)
                return
            parts = relative.parts
            is_web_asset = candidate == web_root or candidate.is_relative_to(web_root)
            is_saved_pdf = (
                len(parts) >= 6
                and parts[0] == "data"
                and parts[1] == "searches"
                and RESULT_ID_RE.fullmatch(parts[2]) is not None
                and parts[3:5] == ("raw", "pdfs")
            )
            if not (is_web_asset or is_saved_pdf):
                self._error("not found", HTTPStatus.NOT_FOUND)
                return
            self.path = request_path
            super().do_GET()

        def do_GET(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path == "/api/health":
                self._json({"ok": True})
                return
            if path == "/api/results":
                self._json({"results": manager.store.list()})
                return
            route = self._result_route(path)
            if route:
                result_id, resource = route
                try:
                    if resource is None:
                        self._json(manager.store.get(result_id))
                    elif resource == "inspector":
                        inspector = manager.store.result_dir(result_id) / "inspector.json"
                        if not inspector.is_file():
                            status = manager.store.get(result_id).get("status", {})
                            self._json(
                                {
                                    "error": "result is not ready",
                                    "result_id": result_id,
                                    "status": status,
                                },
                                HTTPStatus.CONFLICT,
                            )
                        else:
                            self._json(json.loads(inspector.read_text(encoding="utf-8")))
                    else:
                        self._error("unknown result resource", HTTPStatus.NOT_FOUND)
                except FileNotFoundError:
                    self._error("result not found", HTTPStatus.NOT_FOUND)
                return
            self._serve_static(path)

        def do_POST(self) -> None:  # noqa: N802
            if urlsplit(self.path).path != "/api/results":
                self._error("not found", HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._error("invalid Content-Length", HTTPStatus.BAD_REQUEST)
                return
            if length <= 0 or length > 65_536:
                self._error("request body must be between 1 and 65536 bytes", HTTPStatus.BAD_REQUEST)
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("request body must be a JSON object")
                result, reused = manager.submit(payload)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                self._error(str(error), HTTPStatus.BAD_REQUEST)
                return
            self._json(
                {"result": result, "reused": reused},
                HTTPStatus.OK if reused else HTTPStatus.ACCEPTED,
            )

        def end_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            super().end_headers()

    return GenealogyHandler


def serve(
    *,
    workspace: str | Path,
    store_path: str | Path,
    host: str = "127.0.0.1",
    port: int = 4174,
    workers: int = 1,
) -> None:
    root = Path(workspace).resolve()
    store = ResultStore(store_path)
    manager = SearchManager(
        store,
        lambda: SearchPipeline(store, workspace=root),
        workers=workers,
    )
    server = ThreadingHTTPServer(
        (host, port), make_handler(workspace=root, manager=manager)
    )
    try:
        print(f"Research Genealogy home: http://{host}:{port}/")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        manager.close()
