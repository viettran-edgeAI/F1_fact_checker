from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .sqlite_store import CSV_TABLES, initialize_schema, replace_table_rows, upsert_source


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def import_formula_one_dataset(conn: Any, source_dir: Path) -> dict[str, int]:
    initialize_schema(conn)
    if not source_dir.exists():
        raise FileNotFoundError(f"Formula 1 dataset directory not found: {source_dir}")

    counts: dict[str, int] = {}
    for table, (filename, _columns, _primary_key) in CSV_TABLES.items():
        path = source_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Required dataset file not found: {path}")
        rows = _read_csv(path)
        counts[table] = replace_table_rows(conn, table, rows, clear_existing=True)
        upsert_source(
            conn,
            source_id=f"csv:{filename}",
            source_type="formula_1_world_championship_csv",
            source_path=str(path),
            row_count=counts[table],
        )

    conn.commit()
    rebuild_aliases(conn)
    conn.commit()
    return counts


def _add_alias(conn: Any, alias: str, entity_type: str, entity_id: str, canonical_name: str) -> None:
    normalized = " ".join(alias.replace("_", " ").split()).strip()
    if not normalized or normalized == r"\N":
        return
    conn.execute(
        """
        INSERT OR REPLACE INTO aliases(alias, entity_type, entity_id, canonical_name)
        VALUES (?, ?, ?, ?)
        """,
        (normalized.lower(), entity_type, entity_id, canonical_name),
    )


def rebuild_aliases(conn: Any) -> int:
    conn.execute("DELETE FROM aliases")
    count = 0

    for row in conn.execute("SELECT driverId, driverRef, code, forename, surname FROM drivers"):
        full_name = f"{row['forename']} {row['surname']}".strip()
        aliases = {full_name, row["surname"], row["driverRef"], row["code"]}
        for alias in aliases:
            before = conn.total_changes
            _add_alias(conn, alias, "driver", row["driverId"], full_name)
            count += max(0, conn.total_changes - before)

    for row in conn.execute("SELECT constructorId, constructorRef, name FROM constructors"):
        aliases = {row["name"], row["constructorRef"]}
        for alias in aliases:
            before = conn.total_changes
            _add_alias(conn, alias, "constructor", row["constructorId"], row["name"])
            count += max(0, conn.total_changes - before)

    for row in conn.execute("SELECT circuitId, circuitRef, name FROM circuits"):
        aliases = {row["name"], row["circuitRef"]}
        for alias in aliases:
            before = conn.total_changes
            _add_alias(conn, alias, "circuit", row["circuitId"], row["name"])
            count += max(0, conn.total_changes - before)

    for row in conn.execute("SELECT raceId, year, name FROM races"):
        race_name = row["name"]
        aliases = {race_name, f"{row['year']} {race_name}"}
        for alias in aliases:
            before = conn.total_changes
            _add_alias(conn, alias, "race", row["raceId"], race_name)
            count += max(0, conn.total_changes - before)

    return count
