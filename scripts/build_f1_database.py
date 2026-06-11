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
from fact_check_service.knowledge.vector_index import build_structured_fact_vector_index


def parse_args() -> argparse.Namespace:
    config = FactCheckConfig.from_env()
    parser = argparse.ArgumentParser(description="Build the local F1 SQLite knowledge database from CSV files.")
    parser.add_argument("--source-dir", default=str(config.source_data_dir), help="Directory containing F1 CSV files.")
    parser.add_argument("--db", default=str(config.db_path), help="SQLite database output path.")
    parser.add_argument("--skip-import", action="store_true", help="Do not import CSV tables before later build steps.")
    parser.add_argument("--skip-facts", action="store_true", help="Import tables only; do not regenerate facts.")
    parser.add_argument(
        "--build-vector-index",
        action="store_true",
        help="Build vector artifacts after facts are generated.",
    )
    parser.add_argument(
        "--force-vector-index",
        action="store_true",
        help="Rebuild vector artifacts even if the existing manifest matches the database snapshot.",
    )
    parser.add_argument("--faiss-index", default=str(config.faiss_index_path), help="FAISS index output path.")
    parser.add_argument("--fact-metadata", default=str(config.fact_metadata_path), help="Vector metadata JSONL path.")
    parser.add_argument(
        "--embedding-model",
        default=str(config.embedding_model_dir),
        help="Local embedding model directory.",
    )
    parser.add_argument(
        "--embedding-batch-size",
        type=int,
        default=config.embedding_batch_size,
        help="Embedding batch size for vector index builds.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db).expanduser().resolve()
    source_dir = Path(args.source_dir).expanduser().resolve()
    faiss_index_path = Path(args.faiss_index).expanduser().resolve()
    fact_metadata_path = Path(args.fact_metadata).expanduser().resolve()
    embedding_model_dir = Path(args.embedding_model).expanduser().resolve()

    with connect(db_path) as conn:
        imported = {} if args.skip_import else import_formula_one_dataset(conn, source_dir)
        fact_count = 0 if args.skip_facts else generate_facts(conn)
        vector_index = None
        if args.build_vector_index:
            vector_index = build_structured_fact_vector_index(
                conn,
                model_dir=embedding_model_dir,
                index_path=faiss_index_path,
                metadata_path=fact_metadata_path,
                embedding_batch_size=args.embedding_batch_size,
                force=args.force_vector_index,
            )
        summary = status(conn)

    print(
        json.dumps(
            {
                "db_path": str(db_path),
                "source_dir": str(source_dir),
                "imported": imported,
                "generated_facts": fact_count,
                "vector_index": None
                if vector_index is None
                else {
                    "backend": vector_index.backend,
                    "dimension": vector_index.dimension,
                    "fact_count": vector_index.fact_count,
                    "max_updated_at": vector_index.max_updated_at,
                    "index_path": str(vector_index.index_path),
                    "numpy_index_path": str(vector_index.numpy_index_path),
                    "metadata_path": str(vector_index.metadata_path),
                    "manifest_path": str(vector_index.manifest_path),
                    "wrote_faiss_index": vector_index.wrote_faiss_index,
                },
                "status": summary,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
