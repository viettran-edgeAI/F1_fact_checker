from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fact_check_service.config import FactCheckConfig
from fact_check_service.knowledge.dataset_importer import import_formula_one_dataset
from fact_check_service.knowledge.fact_generator import generate_facts
from fact_check_service.knowledge.retrieval import search_facts
from fact_check_service.knowledge.sqlite_store import connect, initialize_schema, status, upsert_facts


def test_builds_knowledge_database_from_formula_one_dataset(tmp_path: Path) -> None:
    db_path = tmp_path / "f1.sqlite"
    source_dir = ROOT / "data" / "F1_WC_data"
    config = FactCheckConfig(
        db_path=db_path,
        faiss_index_path=tmp_path / "faiss.index",
        source_data_dir=source_dir,
        jolpica_cache_dir=tmp_path,
        fact_metadata_path=tmp_path / "fact_metadata.jsonl",
        embedding_model_dir=tmp_path / "missing-model",
        jolpica_base_url="https://example.com",
        jolpica_timeout_seconds=20.0,
        llm_service_url="http://llm-service:8081",
        ocr_service_url="http://ocr-service:8000",
        llm_timeout_seconds=120.0,
        brave_search_count=3,
        brave_search_timeout=10.0,
        brave_context_count=10,
        brave_context_max_urls=5,
        brave_context_max_snippets=12,
        brave_context_max_tokens=4096,
        structured_sql_first=True,
        min_vector_score=0.35,
        embedding_batch_size=4,
        url_fetch_timeout_seconds=10.0,
        url_fetch_max_bytes=3_000_000,
        url_allowed_schemes=("http", "https"),
    )

    with connect(db_path) as conn:
        imported = import_formula_one_dataset(conn, source_dir)
        fact_count = generate_facts(conn)
        summary = status(conn)
        facts = search_facts(conn, "Verstappen won Abu Dhabi 2021", limit=3, config=config)

    assert imported["races"] >= 1000
    assert imported["drivers"] >= 800
    assert fact_count >= 30000
    assert summary["season_min"] == 1950
    assert summary["season_max"] >= 2024
    assert facts
    assert facts[0]["fact_text"] == "Max Verstappen won the 2021 Abu Dhabi Grand Prix for Red Bull."


def test_search_facts_falls_back_to_fts_when_embedding_model_is_missing(tmp_path: Path) -> None:
    db_path = tmp_path / "f1.sqlite"
    config = FactCheckConfig(
        db_path=db_path,
        faiss_index_path=tmp_path / "faiss.index",
        source_data_dir=tmp_path,
        jolpica_cache_dir=tmp_path,
        fact_metadata_path=tmp_path / "fact_metadata.jsonl",
        embedding_model_dir=tmp_path / "missing-model",
        jolpica_base_url="https://example.com",
        jolpica_timeout_seconds=20.0,
        llm_service_url="http://llm-service:8081",
        ocr_service_url="http://ocr-service:8000",
        llm_timeout_seconds=120.0,
        brave_search_count=3,
        brave_search_timeout=10.0,
        brave_context_count=10,
        brave_context_max_urls=5,
        brave_context_max_snippets=12,
        brave_context_max_tokens=4096,
        structured_sql_first=True,
        min_vector_score=0.35,
        embedding_batch_size=4,
        url_fetch_timeout_seconds=10.0,
        url_fetch_max_bytes=3_000_000,
        url_allowed_schemes=("http", "https"),
    )

    with connect(db_path) as conn:
        initialize_schema(conn)
        upsert_facts(
            conn,
            [
                {
                    "fact_key": "race:1:winner",
                    "fact_text": "Max Verstappen won the 2021 Abu Dhabi Grand Prix for Red Bull.",
                    "subject": "Max Verstappen",
                    "relation": "won_race",
                    "object": "2021 Abu Dhabi Grand Prix",
                    "season": 2021,
                    "race_id": "1",
                    "driver_id": "1",
                    "constructor_id": "9",
                    "source": "test",
                }
            ],
        )
        conn.commit()

        facts = search_facts(conn, "Verstappen won Abu Dhabi 2021", limit=3, config=config)

    assert facts
    assert facts[0]["fact_text"] == "Max Verstappen won the 2021 Abu Dhabi Grand Prix for Red Bull."
    assert facts[0]["retrieval_method"] == "fts"


def test_search_facts_uses_local_minilm_vector_retrieval_when_model_exists(tmp_path: Path) -> None:
    model_dir = Path("/home/viettran_orin/models/embedding/all-MiniLM-L6-v2")
    if not model_dir.exists():
        return

    db_path = tmp_path / "f1.sqlite"
    config = FactCheckConfig(
        db_path=db_path,
        faiss_index_path=tmp_path / "faiss.index",
        source_data_dir=tmp_path,
        jolpica_cache_dir=tmp_path,
        fact_metadata_path=tmp_path / "fact_metadata.jsonl",
        embedding_model_dir=model_dir,
        jolpica_base_url="https://example.com",
        jolpica_timeout_seconds=20.0,
        llm_service_url="http://llm-service:8081",
        ocr_service_url="http://ocr-service:8000",
        llm_timeout_seconds=120.0,
        brave_search_count=3,
        brave_search_timeout=10.0,
        brave_context_count=10,
        brave_context_max_urls=5,
        brave_context_max_snippets=12,
        brave_context_max_tokens=4096,
        structured_sql_first=False,
        min_vector_score=0.2,
        embedding_batch_size=4,
        url_fetch_timeout_seconds=10.0,
        url_fetch_max_bytes=3_000_000,
        url_allowed_schemes=("http", "https"),
    )

    with connect(db_path) as conn:
        initialize_schema(conn)
        upsert_facts(
            conn,
            [
                {
                    "fact_key": "race:1:winner",
                    "fact_text": "Max Verstappen won the 2021 Abu Dhabi Grand Prix for Red Bull.",
                    "subject": "Max Verstappen",
                    "relation": "won_race",
                    "object": "2021 Abu Dhabi Grand Prix",
                    "season": 2021,
                    "race_id": "1",
                    "driver_id": "1",
                    "constructor_id": "9",
                    "source": "test",
                },
                {
                    "fact_key": "title:hamilton",
                    "fact_text": "Lewis Hamilton won the 2020 Formula 1 Drivers' Championship for Mercedes.",
                    "subject": "Lewis Hamilton",
                    "relation": "won_drivers_championship",
                    "object": "2020 Drivers' Championship",
                    "season": 2020,
                    "race_id": None,
                    "driver_id": "44",
                    "constructor_id": "131",
                    "source": "test",
                },
            ],
        )
        conn.commit()

        facts = search_facts(conn, "Who won Abu Dhabi in 2021 for Red Bull?", limit=2, config=config)

    assert facts
    assert facts[0]["fact_text"] == "Max Verstappen won the 2021 Abu Dhabi Grand Prix for Red Bull."
    assert facts[0]["retrieval_method"] in {"vector", "hybrid"}
