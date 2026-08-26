#!/usr/bin/env python3
"""Serve the search homepage, API, result history, and graph inspector."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.app_server import serve  # noqa: E402
from src.local_config import load_env_file  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4174)
    parser.add_argument("--store", default="data/searches")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    workspace = Path(__file__).resolve().parents[1]
    load_env_file(workspace / ".env")
    store_path = Path(args.store)
    if not store_path.is_absolute():
        store_path = workspace / store_path
    serve(
        workspace=workspace,
        store_path=store_path,
        host=args.host,
        port=args.port,
        workers=args.workers,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

