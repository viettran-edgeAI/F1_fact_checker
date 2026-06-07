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
from fact_check_service.knowledge.fact_generator import generate_facts
from fact_check_service.knowledge.jolpica_sync import JolpicaClient, sync_jolpica_range
from fact_check_service.knowledge.sqlite_store import connect, status


def parse_args() -> argparse.Namespace:
    config = FactCheckConfig.from_env()
    parser = argparse.ArgumentParser(description="Sync local F1 database from Jolpica.")
    parser.add_argument("--db", default=str(config.db_path), help="SQLite database path.")
    parser.add_argument("--cache-dir", default=str(config.jolpica_cache_dir), help="Jolpica JSON cache directory.")
    parser.add_argument("--base-url", default=config.jolpica_base_url, help="Jolpica Ergast-compatible base URL.")
    parser.add_argument("--start-season", type=int, required=True, help="First season to sync.")
    parser.add_argument("--end-season", type=int, default=None, help="Last season to sync. Defaults to start season.")
    parser.add_argument("--skip-facts", action="store_true", help="Do not regenerate facts after sync.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db).expanduser().resolve()
    cache_dir = Path(args.cache_dir).expanduser().resolve()
    end_season = args.end_season or args.start_season

    client = JolpicaClient(base_url=args.base_url, cache_dir=cache_dir)
    with connect(db_path) as conn:
        synced = sync_jolpica_range(
            conn,
            client=client,
            start_season=args.start_season,
            end_season=end_season,
        )
        regenerated = 0 if args.skip_facts else generate_facts(conn)
        summary = status(conn)

    print(
        json.dumps(
            {
                "db_path": str(db_path),
                "cache_dir": str(cache_dir),
                "synced": synced,
                "regenerated_facts": regenerated,
                "status": summary,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
