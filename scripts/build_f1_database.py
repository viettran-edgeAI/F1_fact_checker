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
from fact_check_service.knowledge.dataset_importer import import_formula_one_dataset
from fact_check_service.knowledge.fact_generator import generate_facts
from fact_check_service.knowledge.sqlite_store import connect, status


def parse_args() -> argparse.Namespace:
    config = FactCheckConfig.from_env()
    parser = argparse.ArgumentParser(description="Build the local F1 SQLite knowledge database from CSV files.")
    parser.add_argument("--source-dir", default=str(config.source_data_dir), help="Directory containing F1 CSV files.")
    parser.add_argument("--db", default=str(config.db_path), help="SQLite database output path.")
    parser.add_argument("--skip-facts", action="store_true", help="Import tables only; do not regenerate facts.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db).expanduser().resolve()
    source_dir = Path(args.source_dir).expanduser().resolve()

    with connect(db_path) as conn:
        imported = import_formula_one_dataset(conn, source_dir)
        fact_count = 0 if args.skip_facts else generate_facts(conn)
        summary = status(conn)

    print(
        json.dumps(
            {
                "db_path": str(db_path),
                "source_dir": str(source_dir),
                "imported": imported,
                "generated_facts": fact_count,
                "status": summary,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
