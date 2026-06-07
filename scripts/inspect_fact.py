#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fact_check_service.config import FactCheckConfig
from fact_check_service.knowledge.retrieval import search_facts
from fact_check_service.knowledge.sqlite_store import connect, status


def parse_args() -> argparse.Namespace:
    config = FactCheckConfig.from_env()
    parser = argparse.ArgumentParser(description="Inspect local F1 facts.")
    parser.add_argument("query", nargs="?", default="", help="Text to search in the facts FTS index.")
    parser.add_argument("--db", default=str(config.db_path), help="SQLite database path.")
    parser.add_argument("--limit", type=int, default=8, help="Maximum facts to return.")
    parser.add_argument("--status", action="store_true", help="Print database status instead of searching.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with connect(Path(args.db).expanduser().resolve()) as conn:
        if args.status:
            payload = status(conn)
        else:
            payload = {"query": args.query, "facts": search_facts(conn, args.query, limit=args.limit)}
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
