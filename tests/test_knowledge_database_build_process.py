from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fact_check_service.config import FactCheckConfig
from fact_check_service.knowledge.dataset_importer import import_formula_one_dataset
from fact_check_service.knowledge.fact_generator import generate_facts
from fact_check_service.knowledge.jolpica_sync import JolpicaClient, sync_jolpica_season
from fact_check_service.knowledge.retrieval import _VECTOR_INDEX_CACHE, search_facts
from fact_check_service.knowledge.sqlite_store import CSV_TABLES, connect, initialize_schema, upsert_facts
from fact_check_service.knowledge.vector_index import StructuredFactVectorIndex


def _write_table(source_dir: Path, table: str, rows: list[dict[str, Any]]) -> None:
    filename, columns, _primary_key = CSV_TABLES[table]
    path = source_dir / filename
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def minimal_f1_csv_dir(tmp_path: Path, *, omit_table: str | None = None) -> Path:
    source_dir = tmp_path / "mini_f1_csv"
    source_dir.mkdir()
    rows_by_table: dict[str, list[dict[str, Any]]] = {
        "circuits": [
            {
                "circuitId": "1",
                "circuitRef": "yas_marina",
                "name": "Yas Marina Circuit",
                "location": "Abu Dhabi",
                "country": "UAE",
            },
            {
                "circuitId": "2",
                "circuitRef": "silverstone",
                "name": "Silverstone Circuit",
                "location": "Silverstone",
                "country": "UK",
            },
        ],
        "constructors": [
            {"constructorId": "9", "constructorRef": "red_bull", "name": "Red Bull", "nationality": "Austrian"},
            {"constructorId": "131", "constructorRef": "mercedes", "name": "Mercedes", "nationality": "German"},
        ],
        "drivers": [
            {
                "driverId": "830",
                "driverRef": "max_verstappen",
                "number": "33",
                "code": "VER",
                "forename": "Max",
                "surname": "Verstappen",
                "nationality": "Dutch",
            },
            {
                "driverId": "1",
                "driverRef": "hamilton",
                "number": "44",
                "code": "HAM",
                "forename": "Lewis",
                "surname": "Hamilton",
                "nationality": "British",
            },
        ],
        "races": [
            {
                "raceId": "101",
                "year": "2021",
                "round": "1",
                "circuitId": "2",
                "name": "British Grand Prix",
                "date": "2021-07-18",
            },
            {
                "raceId": "102",
                "year": "2021",
                "round": "2",
                "circuitId": "1",
                "name": "Abu Dhabi Grand Prix",
                "date": "2021-12-12",
            },
        ],
        "results": [
            {
                "resultId": "1001",
                "raceId": "101",
                "driverId": "1",
                "constructorId": "131",
                "number": "44",
                "grid": "2",
                "position": "1",
                "positionText": "1",
                "positionOrder": "1",
                "points": "25",
                "laps": "52",
                "statusId": "1",
            },
            {
                "resultId": "1002",
                "raceId": "101",
                "driverId": "830",
                "constructorId": "9",
                "number": "33",
                "grid": "1",
                "position": "2",
                "positionText": "2",
                "positionOrder": "2",
                "points": "18",
                "laps": "52",
                "statusId": "1",
            },
            {
                "resultId": "1003",
                "raceId": "102",
                "driverId": "830",
                "constructorId": "9",
                "number": "33",
                "grid": "1",
                "position": "1",
                "positionText": "1",
                "positionOrder": "1",
                "points": "25",
                "laps": "58",
                "statusId": "1",
            },
            {
                "resultId": "1004",
                "raceId": "102",
                "driverId": "1",
                "constructorId": "131",
                "number": "44",
                "grid": "2",
                "position": "2",
                "positionText": "2",
                "positionOrder": "2",
                "points": "18",
                "laps": "58",
                "statusId": "1",
            },
        ],
        "qualifying": [
            {
                "qualifyId": "2001",
                "raceId": "101",
                "driverId": "1",
                "constructorId": "131",
                "number": "44",
                "position": "1",
                "q1": "1:26.786",
                "q2": "1:26.023",
                "q3": "1:25.892",
            },
            {
                "qualifyId": "2002",
                "raceId": "102",
                "driverId": "830",
                "constructorId": "9",
                "number": "33",
                "position": "1",
                "q1": "1:22.109",
                "q2": "1:22.800",
                "q3": "1:22.109",
            },
        ],
        "driver_standings": [
            {
                "driverStandingsId": "3001",
                "raceId": "102",
                "driverId": "830",
                "points": "395.5",
                "position": "1",
                "positionText": "1",
                "wins": "10",
            },
            {
                "driverStandingsId": "3002",
                "raceId": "102",
                "driverId": "1",
                "points": "387.5",
                "position": "2",
                "positionText": "2",
                "wins": "8",
            },
        ],
        "constructor_standings": [
            {
                "constructorStandingsId": "4001",
                "raceId": "102",
                "constructorId": "9",
                "points": "613.5",
                "position": "1",
                "positionText": "1",
                "wins": "11",
            },
            {
                "constructorStandingsId": "4002",
                "raceId": "102",
                "constructorId": "131",
                "points": "587.5",
                "position": "2",
                "positionText": "2",
                "wins": "9",
            },
        ],
        "status": [{"statusId": "1", "status": "Finished"}],
    }

    for table, rows in rows_by_table.items():
        if table != omit_table:
            _write_table(source_dir, table, rows)
    return source_dir


def tiny_config(tmp_path: Path, *, structured_sql_first: bool = True) -> FactCheckConfig:
    model_dir = tmp_path / "fake_model"
    model_dir.mkdir(parents=True, exist_ok=True)
    return FactCheckConfig(
        db_path=tmp_path / "f1.sqlite",
        faiss_index_path=tmp_path / "knowledge_db" / "faiss.index",
        source_data_dir=tmp_path / "mini_f1_csv",
        jolpica_cache_dir=tmp_path / "jolpica_cache",
        fact_metadata_path=tmp_path / "knowledge_db" / "fact_metadata.jsonl",
        embedding_model_dir=model_dir,
        jolpica_base_url="https://example.test/f1",
        jolpica_timeout_seconds=1.0,
        llm_service_url="http://llm-service:8081",
        ocr_service_url="http://ocr-service:8000",
        llm_timeout_seconds=120.0,
        brave_search_count=3,
        brave_search_timeout=10.0,
        brave_context_count=10,
        brave_context_max_urls=5,
        brave_context_max_snippets=12,
        brave_context_max_tokens=4096,
        structured_sql_first=structured_sql_first,
        min_vector_score=0.0,
        embedding_batch_size=2,
        url_fetch_timeout_seconds=10.0,
        url_fetch_max_bytes=3_000_000,
        url_allowed_schemes=("http", "https"),
    )


def fact_snapshot(conn: Any) -> list[tuple[str, str, str]]:
    rows = conn.execute("SELECT fact_key, fact_text, relation FROM facts ORDER BY fact_key").fetchall()
    return [(row["fact_key"], row["fact_text"], row["relation"]) for row in rows]


def test_static_csv_import_loads_all_required_tables_and_aliases(tmp_path: Path) -> None:
    source_dir = minimal_f1_csv_dir(tmp_path)
    db_path = tmp_path / "f1.sqlite"

    with connect(db_path) as conn:
        imported = import_formula_one_dataset(conn, source_dir)
        source_count = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        season_range = conn.execute("SELECT MIN(year), MAX(year) FROM races").fetchone()
        aliases = {
            (row["alias"], row["entity_type"], row["canonical_name"])
            for row in conn.execute("SELECT alias, entity_type, canonical_name FROM aliases")
        }

    assert imported == {
        "circuits": 2,
        "constructors": 2,
        "drivers": 2,
        "races": 2,
        "results": 4,
        "qualifying": 2,
        "driver_standings": 2,
        "constructor_standings": 2,
        "status": 1,
    }
    assert source_count == len(CSV_TABLES)
    assert tuple(season_range) == ("2021", "2021")
    assert ("verstappen", "driver", "Max Verstappen") in aliases
    assert ("ver", "driver", "Max Verstappen") in aliases
    assert ("max verstappen", "driver", "Max Verstappen") in aliases
    assert ("red bull", "constructor", "Red Bull") in aliases
    assert ("red bull", "constructor", "Red Bull") in aliases
    assert ("2021 abu dhabi grand prix", "race", "Abu Dhabi Grand Prix") in aliases
    assert ("yas marina", "circuit", "Yas Marina Circuit") in aliases


def test_static_csv_import_fails_when_required_csv_missing(tmp_path: Path) -> None:
    source_dir = minimal_f1_csv_dir(tmp_path, omit_table="status")

    with connect(tmp_path / "f1.sqlite") as conn:
        try:
            import_formula_one_dataset(conn, source_dir)
        except FileNotFoundError as exc:
            message = str(exc)
        else:  # pragma: no cover - defensive failure path.
            raise AssertionError("expected missing status.csv to raise FileNotFoundError")

    assert "status.csv" in message
    assert str(source_dir / "status.csv") in message


def test_generate_facts_is_deterministic_and_idempotent(tmp_path: Path) -> None:
    source_dir = minimal_f1_csv_dir(tmp_path)

    with connect(tmp_path / "f1.sqlite") as conn:
        import_formula_one_dataset(conn, source_dir)
        first_count = generate_facts(conn)
        first_snapshot = fact_snapshot(conn)
        second_count = generate_facts(conn)
        second_snapshot = fact_snapshot(conn)

    assert first_count == 18
    assert second_count == 18
    assert second_snapshot == first_snapshot
    assert (
        "result:1003:winner",
        "Max Verstappen won the 2021 Abu Dhabi Grand Prix for Red Bull.",
        "won_race",
    ) in first_snapshot
    assert (
        "result:1003:podium",
        "Max Verstappen finished on the podium in P1 at the 2021 Abu Dhabi Grand Prix.",
        "podium_finish",
    ) in first_snapshot
    assert (
        "qualifying:2002:pole",
        "Max Verstappen took pole position for the 2021 Abu Dhabi Grand Prix with Red Bull.",
        "pole_position",
    ) in first_snapshot
    assert (
        "season:2021:drivers_champion",
        "Max Verstappen won the 2021 Formula 1 Drivers' Championship with 395.5 points and 10 wins.",
        "won_drivers_championship",
    ) in first_snapshot


class FakeJolpicaClient:
    base_url = "https://example.test/f1"

    def get_all(self, path: str, *, limit: int = 100) -> list[dict[str, Any]]:
        _ = limit
        return {
            "2022/races": [
                {
                    "season": "2022",
                    "round": "1",
                    "raceName": "Bahrain Grand Prix",
                    "date": "2022-03-20",
                    "Circuit": {
                        "circuitId": "bahrain",
                        "circuitName": "Bahrain International Circuit",
                        "Location": {"locality": "Sakhir", "country": "Bahrain"},
                    },
                }
            ],
            "2022/results": [
                {
                    "season": "2022",
                    "round": "1",
                    "raceName": "Bahrain Grand Prix",
                    "date": "2022-03-20",
                    "Circuit": {
                        "circuitId": "bahrain",
                        "circuitName": "Bahrain International Circuit",
                        "Location": {"locality": "Sakhir", "country": "Bahrain"},
                    },
                    "Results": [
                        {
                            "number": "16",
                            "position": "1",
                            "positionText": "1",
                            "positionOrder": "1",
                            "points": "26",
                            "laps": "57",
                            "status": "Finished",
                            "Driver": {
                                "driverId": "leclerc",
                                "permanentNumber": "16",
                                "code": "LEC",
                                "givenName": "Charles",
                                "familyName": "Leclerc",
                                "dateOfBirth": "1997-10-16",
                                "nationality": "Monegasque",
                            },
                            "Constructor": {
                                "constructorId": "ferrari",
                                "name": "Ferrari",
                                "nationality": "Italian",
                            },
                        }
                    ],
                }
            ],
            "2022/qualifying": [
                {
                    "season": "2022",
                    "round": "1",
                    "raceName": "Bahrain Grand Prix",
                    "Circuit": {"circuitId": "bahrain", "circuitName": "Bahrain International Circuit"},
                    "QualifyingResults": [
                        {
                            "number": "16",
                            "position": "1",
                            "Q1": "1:31.471",
                            "Q2": "1:30.932",
                            "Q3": "1:30.558",
                            "Driver": {"driverId": "leclerc", "code": "LEC", "givenName": "Charles", "familyName": "Leclerc"},
                            "Constructor": {"constructorId": "ferrari", "name": "Ferrari"},
                        }
                    ],
                }
            ],
            "2022/driverstandings": [
                {
                    "season": "2022",
                    "round": "1",
                    "DriverStandings": [
                        {
                            "position": "1",
                            "positionText": "1",
                            "points": "26",
                            "wins": "1",
                            "Driver": {"driverId": "leclerc", "code": "LEC", "givenName": "Charles", "familyName": "Leclerc"},
                        }
                    ],
                }
            ],
            "2022/constructorstandings": [
                {
                    "season": "2022",
                    "round": "1",
                    "ConstructorStandings": [
                        {
                            "position": "1",
                            "positionText": "1",
                            "points": "44",
                            "wins": "1",
                            "Constructor": {"constructorId": "ferrari", "name": "Ferrari"},
                        }
                    ],
                }
            ],
        }[path]


def test_jolpica_sync_merges_payloads_without_network_and_is_idempotent(tmp_path: Path) -> None:
    source_dir = minimal_f1_csv_dir(tmp_path)

    with connect(tmp_path / "f1.sqlite") as conn:
        import_formula_one_dataset(conn, source_dir)
        first_counts = sync_jolpica_season(conn, client=FakeJolpicaClient(), season=2022)
        first_table_counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("races", "results", "qualifying", "driver_standings", "constructor_standings")
        }
        second_counts = sync_jolpica_season(conn, client=FakeJolpicaClient(), season=2022)
        second_table_counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("races", "results", "qualifying", "driver_standings", "constructor_standings")
        }
        jolpica_source = conn.execute(
            "SELECT row_count, metadata_json FROM sources WHERE source_id = 'jolpica:2022'"
        ).fetchone()
        aliases = {
            (row["alias"], row["entity_type"], row["canonical_name"])
            for row in conn.execute("SELECT alias, entity_type, canonical_name FROM aliases")
        }
        leclerc_id = conn.execute("SELECT driverId FROM drivers WHERE driverRef = 'leclerc'").fetchone()[0]
        ferrari_id = conn.execute("SELECT constructorId FROM constructors WHERE constructorRef = 'ferrari'").fetchone()[0]

    assert first_counts == {
        "races": 1,
        "results": 1,
        "qualifying": 1,
        "driver_standings": 1,
        "constructor_standings": 1,
    }
    assert second_counts == first_counts
    assert second_table_counts == first_table_counts
    assert jolpica_source["row_count"] == 5
    assert json.loads(jolpica_source["metadata_json"]) == first_counts
    assert leclerc_id == "jolpica:driver:leclerc"
    assert ferrari_id == "jolpica:constructor:ferrari"
    assert ("leclerc", "driver", "Charles Leclerc") in aliases
    assert ("ferrari", "constructor", "Ferrari") in aliases


def test_jolpica_client_writes_cache_files_from_mocked_httpx(tmp_path: Path, monkeypatch: Any) -> None:
    payloads = {
        0: {
            "MRData": {
                "total": "3",
                "RaceTable": {"Races": [{"season": "2024", "round": "1"}, {"season": "2024", "round": "2"}]},
            }
        },
        2: {"MRData": {"total": "3", "RaceTable": {"Races": [{"season": "2024", "round": "3"}]}}},
    }

    class FakeResponse:
        def __init__(self, payload: dict[str, Any]) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return self._payload

    def fake_get(url: str, *, params: dict[str, str], timeout: float) -> FakeResponse:
        assert url == "https://example.test/f1/2024/races.json"
        assert timeout == 3.0
        return FakeResponse(payloads[int(params["offset"])])

    monkeypatch.setattr("fact_check_service.knowledge.jolpica_sync.httpx.get", fake_get)

    client = JolpicaClient(base_url="https://example.test/f1", cache_dir=tmp_path / "cache", timeout_seconds=3.0)
    rows = client.get_all("2024/races", limit=2)

    assert rows == [{"season": "2024", "round": "1"}, {"season": "2024", "round": "2"}, {"season": "2024", "round": "3"}]
    assert json.loads((tmp_path / "cache" / "2024__races__offset_0.json").read_text(encoding="utf-8")) == payloads[0]
    assert json.loads((tmp_path / "cache" / "2024__races__offset_2.json").read_text(encoding="utf-8")) == payloads[2]
    assert not (tmp_path / "cache" / "2024__races__offset_4.json").exists()


class FakeVectorEmbedder:
    dimension = 3

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = []
        for text in texts:
            lower = text.lower()
            if "verstappen" in lower and "abu dhabi" in lower:
                vector = np.array([1.0, 0.0, 0.0], dtype=np.float32)
            elif "hamilton" in lower:
                vector = np.array([0.0, 1.0, 0.0], dtype=np.float32)
            else:
                vector = np.array([0.0, 0.0, 1.0], dtype=np.float32)
            vectors.append(vector)
        return np.vstack(vectors)


def _patch_fake_vector_embedder(monkeypatch: Any) -> None:
    monkeypatch.setattr(StructuredFactVectorIndex, "available", property(lambda self: True))
    monkeypatch.setattr(StructuredFactVectorIndex, "_embedder_or_raise", lambda self: FakeVectorEmbedder())
    _VECTOR_INDEX_CACHE.clear()


def test_vector_index_builds_artifacts_and_is_idempotent(tmp_path: Path, monkeypatch: Any) -> None:
    _patch_fake_vector_embedder(monkeypatch)
    config = tiny_config(tmp_path, structured_sql_first=False)

    with connect(config.db_path) as conn:
        initialize_schema(conn)
        upsert_facts(
            conn,
            [
                {
                    "fact_key": "race:abu-dhabi-2021:winner",
                    "fact_text": "Max Verstappen won the 2021 Abu Dhabi Grand Prix for Red Bull.",
                    "subject": "Max Verstappen",
                    "relation": "won_race",
                    "object": "2021 Abu Dhabi Grand Prix",
                    "season": 2021,
                    "race_id": "102",
                    "driver_id": "830",
                    "constructor_id": "9",
                    "source": "test",
                },
                {
                    "fact_key": "race:british-2021:winner",
                    "fact_text": "Lewis Hamilton won the 2021 British Grand Prix for Mercedes.",
                    "subject": "Lewis Hamilton",
                    "relation": "won_race",
                    "object": "2021 British Grand Prix",
                    "season": 2021,
                    "race_id": "101",
                    "driver_id": "1",
                    "constructor_id": "131",
                    "source": "test",
                },
            ],
        )
        conn.commit()
        index = StructuredFactVectorIndex(
            model_dir=config.embedding_model_dir,
            index_path=config.faiss_index_path,
            metadata_path=config.fact_metadata_path,
            embedding_batch_size=config.embedding_batch_size,
        )
        first_result = index.build(conn)
        first_metadata = config.fact_metadata_path.read_text(encoding="utf-8")
        first_manifest = first_result.manifest_path.read_text(encoding="utf-8")
        first_vectors = np.load(first_result.numpy_index_path)
        second_result = index.build(conn, force=True)
        second_metadata = config.fact_metadata_path.read_text(encoding="utf-8")
        second_manifest = second_result.manifest_path.read_text(encoding="utf-8")
        second_vectors = np.load(second_result.numpy_index_path)

    assert first_result.fact_count == 2
    assert first_result.dimension == 3
    assert first_result.metadata_path.exists()
    assert first_result.manifest_path.exists()
    assert first_result.numpy_index_path.exists()
    assert first_result.wrote_faiss_index == first_result.index_path.exists()
    assert first_metadata == second_metadata
    assert first_manifest == second_manifest
    np.testing.assert_array_equal(first_vectors, second_vectors)
    metadata_rows = [json.loads(line) for line in first_metadata.splitlines()]
    assert [row["fact_text"] for row in metadata_rows] == [
        "Max Verstappen won the 2021 Abu Dhabi Grand Prix for Red Bull.",
        "Lewis Hamilton won the 2021 British Grand Prix for Mercedes.",
    ]


def test_retrieval_uses_explicit_vector_artifacts_and_prefers_exact_f1_evidence(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _patch_fake_vector_embedder(monkeypatch)
    config = tiny_config(tmp_path, structured_sql_first=True)

    with connect(config.db_path) as conn:
        initialize_schema(conn)
        upsert_facts(
            conn,
            [
                {
                    "fact_key": "race:abu-dhabi-2021:winner",
                    "fact_text": "Max Verstappen won the 2021 Abu Dhabi Grand Prix for Red Bull.",
                    "subject": "Max Verstappen",
                    "relation": "won_race",
                    "object": "2021 Abu Dhabi Grand Prix",
                    "season": 2021,
                    "race_id": "102",
                    "driver_id": "830",
                    "constructor_id": "9",
                    "source": "test",
                },
                {
                    "fact_key": "race:british-2021:winner",
                    "fact_text": "Lewis Hamilton won the 2021 British Grand Prix for Mercedes.",
                    "subject": "Lewis Hamilton",
                    "relation": "won_race",
                    "object": "2021 British Grand Prix",
                    "season": 2021,
                    "race_id": "101",
                    "driver_id": "1",
                    "constructor_id": "131",
                    "source": "test",
                },
                {
                    "fact_key": "season:2021:constructors_champion",
                    "fact_text": "Mercedes won the 2021 Formula 1 Constructors' Championship.",
                    "subject": "Mercedes",
                    "relation": "won_constructors_championship",
                    "object": "2021 Constructors' Championship",
                    "season": 2021,
                    "race_id": None,
                    "driver_id": None,
                    "constructor_id": "131",
                    "source": "test",
                },
            ],
        )
        conn.commit()
        index = StructuredFactVectorIndex(
            model_dir=config.embedding_model_dir,
            index_path=config.faiss_index_path,
            metadata_path=config.fact_metadata_path,
            embedding_batch_size=config.embedding_batch_size,
        )
        index.build(conn)
        results = search_facts(conn, "Verstappen won Abu Dhabi 2021", limit=3, config=config)

    assert results
    assert results[0]["fact_text"] == "Max Verstappen won the 2021 Abu Dhabi Grand Prix for Red Bull."
    assert results[0]["retrieval_method"] in {"hybrid", "vector"}
    assert config.fact_metadata_path.exists()
    assert config.fact_metadata_path.with_suffix(".jsonl.meta.json").exists()
    assert config.faiss_index_path.with_suffix(".npy").exists()


def test_cli_build_f1_database_smoke_uses_tmp_dirs(tmp_path: Path) -> None:
    source_dir = minimal_f1_csv_dir(tmp_path)
    db_path = tmp_path / "cli" / "f1.sqlite"

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "build_f1_database.py"),
            "--source-dir",
            str(source_dir),
            "--db",
            str(db_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["db_path"] == str(db_path.resolve())
    assert payload["source_dir"] == str(source_dir.resolve())
    assert payload["imported"]["races"] == 2
    assert payload["imported"]["results"] == 4
    assert payload["generated_facts"] == 18
    assert payload["status"]["tables"]["facts"] == 18
