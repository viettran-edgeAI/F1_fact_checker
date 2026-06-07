from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any


CSV_TABLES: dict[str, tuple[str, Sequence[str], str]] = {
    "circuits": (
        "circuits.csv",
        ("circuitId", "circuitRef", "name", "location", "country", "lat", "lng", "alt", "url"),
        "circuitId",
    ),
    "constructors": (
        "constructors.csv",
        ("constructorId", "constructorRef", "name", "nationality", "url"),
        "constructorId",
    ),
    "drivers": (
        "drivers.csv",
        ("driverId", "driverRef", "number", "code", "forename", "surname", "dob", "nationality", "url"),
        "driverId",
    ),
    "races": (
        "races.csv",
        (
            "raceId",
            "year",
            "round",
            "circuitId",
            "name",
            "date",
            "time",
            "url",
            "fp1_date",
            "fp1_time",
            "fp2_date",
            "fp2_time",
            "fp3_date",
            "fp3_time",
            "quali_date",
            "quali_time",
            "sprint_date",
            "sprint_time",
        ),
        "raceId",
    ),
    "results": (
        "results.csv",
        (
            "resultId",
            "raceId",
            "driverId",
            "constructorId",
            "number",
            "grid",
            "position",
            "positionText",
            "positionOrder",
            "points",
            "laps",
            "time",
            "milliseconds",
            "fastestLap",
            "rank",
            "fastestLapTime",
            "fastestLapSpeed",
            "statusId",
        ),
        "resultId",
    ),
    "qualifying": (
        "qualifying.csv",
        ("qualifyId", "raceId", "driverId", "constructorId", "number", "position", "q1", "q2", "q3"),
        "qualifyId",
    ),
    "driver_standings": (
        "driver_standings.csv",
        ("driverStandingsId", "raceId", "driverId", "points", "position", "positionText", "wins"),
        "driverStandingsId",
    ),
    "constructor_standings": (
        "constructor_standings.csv",
        ("constructorStandingsId", "raceId", "constructorId", "points", "position", "positionText", "wins"),
        "constructorStandingsId",
    ),
    "status": (
        "status.csv",
        ("statusId", "status"),
        "statusId",
    ),
}


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def initialize_schema(conn: sqlite3.Connection) -> None:
    for table, (_filename, columns, primary_key) in CSV_TABLES.items():
        column_sql = ", ".join(
            f"{column} TEXT{' PRIMARY KEY' if column == primary_key else ''}" for column in columns
        )
        conn.execute(f"CREATE TABLE IF NOT EXISTS {table} ({column_sql})")

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sources (
            source_id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL,
            source_path TEXT,
            source_url TEXT,
            fetched_at TEXT,
            row_count INTEGER,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS aliases (
            alias TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            canonical_name TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS facts (
            fact_id INTEGER PRIMARY KEY AUTOINCREMENT,
            fact_key TEXT NOT NULL UNIQUE,
            fact_text TEXT NOT NULL,
            subject TEXT NOT NULL,
            relation TEXT NOT NULL,
            object TEXT NOT NULL,
            season INTEGER,
            race_id TEXT,
            driver_id TEXT,
            constructor_id TEXT,
            source TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
            fact_text,
            subject,
            object,
            content='facts',
            content_rowid='fact_id'
        );

        CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
            INSERT INTO facts_fts(rowid, fact_text, subject, object)
            VALUES (new.fact_id, new.fact_text, new.subject, new.object);
        END;

        CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
            INSERT INTO facts_fts(facts_fts, rowid, fact_text, subject, object)
            VALUES('delete', old.fact_id, old.fact_text, old.subject, old.object);
        END;

        CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE ON facts BEGIN
            INSERT INTO facts_fts(facts_fts, rowid, fact_text, subject, object)
            VALUES('delete', old.fact_id, old.fact_text, old.subject, old.object);
            INSERT INTO facts_fts(rowid, fact_text, subject, object)
            VALUES (new.fact_id, new.fact_text, new.subject, new.object);
        END;
        """
    )
    conn.commit()


def replace_table_rows(
    conn: sqlite3.Connection,
    table: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    clear_existing: bool = True,
) -> int:
    columns = CSV_TABLES[table][1]
    if clear_existing:
        conn.execute(f"DELETE FROM {table}")
    placeholders = ", ".join("?" for _ in columns)
    column_sql = ", ".join(columns)
    values = [tuple(str(row.get(column, "") or "") for column in columns) for row in rows]
    if values:
        conn.executemany(f"INSERT OR REPLACE INTO {table} ({column_sql}) VALUES ({placeholders})", values)
    return len(values)


def upsert_source(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    source_type: str,
    source_path: str | None = None,
    source_url: str | None = None,
    fetched_at: str | None = None,
    row_count: int | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO sources(source_id, source_type, source_path, source_url, fetched_at, row_count, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id) DO UPDATE SET
            source_type=excluded.source_type,
            source_path=excluded.source_path,
            source_url=excluded.source_url,
            fetched_at=excluded.fetched_at,
            row_count=excluded.row_count,
            metadata_json=excluded.metadata_json
        """,
        (
            source_id,
            source_type,
            source_path,
            source_url,
            fetched_at,
            row_count,
            json.dumps(dict(metadata or {}), sort_keys=True),
        ),
    )


def clear_generated_facts(conn: sqlite3.Connection, *, source: str | None = None) -> None:
    if source is None:
        conn.execute("DELETE FROM facts")
    else:
        conn.execute("DELETE FROM facts WHERE source = ?", (source,))
    conn.execute("INSERT INTO facts_fts(facts_fts) VALUES('rebuild')")


def upsert_facts(conn: sqlite3.Connection, facts: Iterable[Mapping[str, Any]]) -> int:
    rows = list(facts)
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT INTO facts(
            fact_key, fact_text, subject, relation, object, season, race_id, driver_id, constructor_id, source
        )
        VALUES (
            :fact_key, :fact_text, :subject, :relation, :object, :season, :race_id, :driver_id, :constructor_id, :source
        )
        ON CONFLICT(fact_key) DO UPDATE SET
            fact_text=excluded.fact_text,
            subject=excluded.subject,
            relation=excluded.relation,
            object=excluded.object,
            season=excluded.season,
            race_id=excluded.race_id,
            driver_id=excluded.driver_id,
            constructor_id=excluded.constructor_id,
            source=excluded.source,
            updated_at=CURRENT_TIMESTAMP
        """,
        rows,
    )
    return len(rows)


def status(conn: sqlite3.Connection) -> dict[str, Any]:
    tables = {}
    for table in [*CSV_TABLES.keys(), "facts", "aliases", "sources"]:
        tables[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    season_range = conn.execute("SELECT MIN(CAST(year AS INTEGER)), MAX(CAST(year AS INTEGER)) FROM races").fetchone()
    return {
        "tables": tables,
        "season_min": season_range[0],
        "season_max": season_range[1],
    }
