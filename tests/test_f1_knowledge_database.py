from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fact_check_service.knowledge.dataset_importer import import_formula_one_dataset
from fact_check_service.knowledge.fact_generator import generate_facts
from fact_check_service.knowledge.retrieval import search_facts
from fact_check_service.knowledge.sqlite_store import connect, status


def test_builds_knowledge_database_from_formula_one_dataset(tmp_path: Path) -> None:
    db_path = tmp_path / "f1.sqlite"
    source_dir = ROOT / "data" / "F1_WC_data"

    with connect(db_path) as conn:
        imported = import_formula_one_dataset(conn, source_dir)
        fact_count = generate_facts(conn)
        summary = status(conn)
        facts = search_facts(conn, "Verstappen won Abu Dhabi 2021", limit=3)

    assert imported["races"] >= 1000
    assert imported["drivers"] >= 800
    assert fact_count >= 30000
    assert summary["season_min"] == 1950
    assert summary["season_max"] >= 2024
    assert facts
    assert facts[0]["fact_text"] == "Max Verstappen won the 2021 Abu Dhabi Grand Prix for Red Bull."
