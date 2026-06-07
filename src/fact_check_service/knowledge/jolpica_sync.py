from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from .dataset_importer import rebuild_aliases
from .sqlite_store import initialize_schema, upsert_source


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JolpicaClient:
    def __init__(self, *, base_url: str, cache_dir: Path, timeout_seconds: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache_dir = cache_dir
        self.timeout_seconds = timeout_seconds
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get(self, path: str, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        normalized_path = path.strip("/")
        url = f"{self.base_url}/{normalized_path}.json"
        params = {"limit": str(limit), "offset": str(offset)}
        response = httpx.get(url, params=params, timeout=self.timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        self._write_cache(normalized_path, offset, payload)
        return payload

    def get_all(self, path: str, *, limit: int = 100) -> list[dict[str, Any]]:
        offset = 0
        output: list[dict[str, Any]] = []
        while True:
            payload = self.get(path, limit=limit, offset=offset)
            mr_data = payload.get("MRData", {})
            total = int(mr_data.get("total", "0") or 0)
            rows = _extract_rows(mr_data)
            output.extend(rows)
            offset += limit
            if not rows or offset >= total:
                break
        return output

    def _write_cache(self, path: str, offset: int, payload: dict[str, Any]) -> None:
        cache_path = self.cache_dir / f"{path.replace('/', '__')}__offset_{offset}.json"
        cache_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _extract_rows(mr_data: dict[str, Any]) -> list[dict[str, Any]]:
    for table_key, row_key in (
        ("RaceTable", "Races"),
        ("DriverTable", "Drivers"),
        ("ConstructorTable", "Constructors"),
        ("CircuitTable", "Circuits"),
        ("StandingsTable", "StandingsLists"),
    ):
        table = mr_data.get(table_key)
        if isinstance(table, dict) and isinstance(table.get(row_key), list):
            return table[row_key]
    return []


def sync_jolpica_season(
    conn: Any,
    *,
    client: JolpicaClient,
    season: int,
    include_results: bool = True,
    include_qualifying: bool = True,
    include_standings: bool = True,
) -> dict[str, int]:
    initialize_schema(conn)
    counts = {"races": 0, "results": 0, "qualifying": 0, "driver_standings": 0, "constructor_standings": 0}

    races = client.get_all(f"{season}/races")
    counts["races"] += _upsert_races(conn, races)

    if include_results:
        result_races = client.get_all(f"{season}/results")
        counts["results"] += _upsert_result_races(conn, result_races)

    if include_qualifying:
        qualifying_races = client.get_all(f"{season}/qualifying")
        counts["qualifying"] += _upsert_qualifying_races(conn, qualifying_races)

    if include_standings:
        driver_standings = client.get_all(f"{season}/driverstandings")
        constructor_standings = client.get_all(f"{season}/constructorstandings")
        counts["driver_standings"] += _upsert_driver_standings(conn, driver_standings)
        counts["constructor_standings"] += _upsert_constructor_standings(conn, constructor_standings)

    upsert_source(
        conn,
        source_id=f"jolpica:{season}",
        source_type="jolpica_api",
        source_url=f"{client.base_url}/{season}",
        fetched_at=_utc_now(),
        row_count=sum(counts.values()),
        metadata=counts,
    )
    rebuild_aliases(conn)
    conn.commit()
    return counts


def sync_jolpica_range(conn: Any, *, client: JolpicaClient, start_season: int, end_season: int) -> dict[int, dict[str, int]]:
    return {
        season: sync_jolpica_season(conn, client=client, season=season)
        for season in range(start_season, end_season + 1)
    }


def _race_id(conn: Any, season: str, round_: str) -> str:
    row = conn.execute("SELECT raceId FROM races WHERE year = ? AND round = ?", (season, round_)).fetchone()
    return str(row["raceId"]) if row else f"jolpica:{season}:{round_}"


def _driver_id(conn: Any, driver: dict[str, Any]) -> str:
    ref = str(driver.get("driverId") or "")
    row = conn.execute("SELECT driverId FROM drivers WHERE driverRef = ?", (ref,)).fetchone()
    if row:
        return str(row["driverId"])
    driver_id = f"jolpica:driver:{ref}"
    conn.execute(
        """
        INSERT OR REPLACE INTO drivers(driverId, driverRef, number, code, forename, surname, dob, nationality, url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            driver_id,
            ref,
            str(driver.get("permanentNumber") or ""),
            str(driver.get("code") or ""),
            str(driver.get("givenName") or ""),
            str(driver.get("familyName") or ""),
            str(driver.get("dateOfBirth") or ""),
            str(driver.get("nationality") or ""),
            str(driver.get("url") or ""),
        ),
    )
    return driver_id


def _constructor_id(conn: Any, constructor: dict[str, Any]) -> str:
    ref = str(constructor.get("constructorId") or "")
    row = conn.execute("SELECT constructorId FROM constructors WHERE constructorRef = ?", (ref,)).fetchone()
    if row:
        return str(row["constructorId"])
    constructor_id = f"jolpica:constructor:{ref}"
    conn.execute(
        """
        INSERT OR REPLACE INTO constructors(constructorId, constructorRef, name, nationality, url)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            constructor_id,
            ref,
            str(constructor.get("name") or ""),
            str(constructor.get("nationality") or ""),
            str(constructor.get("url") or ""),
        ),
    )
    return constructor_id


def _circuit_id(conn: Any, circuit: dict[str, Any]) -> str:
    ref = str(circuit.get("circuitId") or "")
    row = conn.execute("SELECT circuitId FROM circuits WHERE circuitRef = ?", (ref,)).fetchone()
    if row:
        return str(row["circuitId"])
    circuit_id = f"jolpica:circuit:{ref}"
    location = circuit.get("Location") or {}
    conn.execute(
        """
        INSERT OR REPLACE INTO circuits(circuitId, circuitRef, name, location, country, lat, lng, alt, url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            circuit_id,
            ref,
            str(circuit.get("circuitName") or ""),
            str(location.get("locality") or ""),
            str(location.get("country") or ""),
            str(location.get("lat") or ""),
            str(location.get("long") or ""),
            "",
            str(circuit.get("url") or ""),
        ),
    )
    return circuit_id


def _upsert_races(conn: Any, races: list[dict[str, Any]]) -> int:
    count = 0
    for race in races:
        season = str(race.get("season") or "")
        round_ = str(race.get("round") or "")
        race_id = _race_id(conn, season, round_)
        circuit_id = _circuit_id(conn, race.get("Circuit") or {})
        conn.execute(
            """
            INSERT OR REPLACE INTO races(
                raceId, year, round, circuitId, name, date, time, url,
                fp1_date, fp1_time, fp2_date, fp2_time, fp3_date, fp3_time, quali_date, quali_time, sprint_date, sprint_time
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', '', '', '', '', '', '', '', '', '')
            """,
            (
                race_id,
                season,
                round_,
                circuit_id,
                str(race.get("raceName") or ""),
                str(race.get("date") or ""),
                str(race.get("time") or ""),
                str(race.get("url") or ""),
            ),
        )
        count += 1
    return count


def _upsert_result_races(conn: Any, races: list[dict[str, Any]]) -> int:
    count = 0
    for race in races:
        _upsert_races(conn, [race])
        season = str(race.get("season") or "")
        round_ = str(race.get("round") or "")
        race_id = _race_id(conn, season, round_)
        for result in race.get("Results") or []:
            driver_id = _driver_id(conn, result.get("Driver") or {})
            constructor_id = _constructor_id(conn, result.get("Constructor") or {})
            result_id = f"jolpica:result:{season}:{round_}:{driver_id}"
            status_id = _status_id(conn, str(result.get("status") or ""))
            conn.execute(
                """
                INSERT OR REPLACE INTO results(
                    resultId, raceId, driverId, constructorId, number, grid, position, positionText, positionOrder,
                    points, laps, time, milliseconds, fastestLap, rank, fastestLapTime, fastestLapSpeed, statusId
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result_id,
                    race_id,
                    driver_id,
                    constructor_id,
                    str(result.get("number") or ""),
                    str(result.get("grid") or ""),
                    str(result.get("position") or ""),
                    str(result.get("positionText") or ""),
                    str(result.get("positionOrder") or result.get("position") or ""),
                    str(result.get("points") or ""),
                    str(result.get("laps") or ""),
                    str((result.get("Time") or {}).get("time") or ""),
                    str((result.get("Time") or {}).get("millis") or ""),
                    str((result.get("FastestLap") or {}).get("lap") or ""),
                    str((result.get("FastestLap") or {}).get("rank") or ""),
                    str(((result.get("FastestLap") or {}).get("Time") or {}).get("time") or ""),
                    str(((result.get("FastestLap") or {}).get("AverageSpeed") or {}).get("speed") or ""),
                    status_id,
                ),
            )
            count += 1
    return count


def _upsert_qualifying_races(conn: Any, races: list[dict[str, Any]]) -> int:
    count = 0
    for race in races:
        _upsert_races(conn, [race])
        season = str(race.get("season") or "")
        round_ = str(race.get("round") or "")
        race_id = _race_id(conn, season, round_)
        for item in race.get("QualifyingResults") or []:
            driver_id = _driver_id(conn, item.get("Driver") or {})
            constructor_id = _constructor_id(conn, item.get("Constructor") or {})
            qualify_id = f"jolpica:qualifying:{season}:{round_}:{driver_id}"
            conn.execute(
                """
                INSERT OR REPLACE INTO qualifying(qualifyId, raceId, driverId, constructorId, number, position, q1, q2, q3)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    qualify_id,
                    race_id,
                    driver_id,
                    constructor_id,
                    str(item.get("number") or ""),
                    str(item.get("position") or ""),
                    str(item.get("Q1") or ""),
                    str(item.get("Q2") or ""),
                    str(item.get("Q3") or ""),
                ),
            )
            count += 1
    return count


def _upsert_driver_standings(conn: Any, standings_lists: list[dict[str, Any]]) -> int:
    count = 0
    for item in standings_lists:
        season = str(item.get("season") or "")
        round_ = str(item.get("round") or "")
        race_id = _race_id(conn, season, round_)
        for standing in item.get("DriverStandings") or []:
            driver_id = _driver_id(conn, standing.get("Driver") or {})
            standing_id = f"jolpica:driver_standings:{season}:{round_}:{driver_id}"
            conn.execute(
                """
                INSERT OR REPLACE INTO driver_standings(driverStandingsId, raceId, driverId, points, position, positionText, wins)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    standing_id,
                    race_id,
                    driver_id,
                    str(standing.get("points") or ""),
                    str(standing.get("position") or ""),
                    str(standing.get("positionText") or ""),
                    str(standing.get("wins") or ""),
                ),
            )
            count += 1
    return count


def _upsert_constructor_standings(conn: Any, standings_lists: list[dict[str, Any]]) -> int:
    count = 0
    for item in standings_lists:
        season = str(item.get("season") or "")
        round_ = str(item.get("round") or "")
        race_id = _race_id(conn, season, round_)
        for standing in item.get("ConstructorStandings") or []:
            constructor_id = _constructor_id(conn, standing.get("Constructor") or {})
            standing_id = f"jolpica:constructor_standings:{season}:{round_}:{constructor_id}"
            conn.execute(
                """
                INSERT OR REPLACE INTO constructor_standings(
                    constructorStandingsId, raceId, constructorId, points, position, positionText, wins
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    standing_id,
                    race_id,
                    constructor_id,
                    str(standing.get("points") or ""),
                    str(standing.get("position") or ""),
                    str(standing.get("positionText") or ""),
                    str(standing.get("wins") or ""),
                ),
            )
            count += 1
    return count


def _status_id(conn: Any, status: str) -> str:
    row = conn.execute("SELECT statusId FROM status WHERE status = ?", (status,)).fetchone()
    if row:
        return str(row["statusId"])
    status_id = f"jolpica:status:{status.lower().replace(' ', '_')}"
    conn.execute("INSERT OR REPLACE INTO status(statusId, status) VALUES (?, ?)", (status_id, status))
    return status_id
