from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .sqlite_store import clear_generated_facts, upsert_facts


def _fact(
    *,
    fact_key: str,
    fact_text: str,
    subject: str,
    relation: str,
    object_: str,
    season: int | None,
    race_id: str | None = None,
    driver_id: str | None = None,
    constructor_id: str | None = None,
    source: str = "generated",
) -> dict[str, Any]:
    return {
        "fact_key": fact_key,
        "fact_text": fact_text,
        "subject": subject,
        "relation": relation,
        "object": object_,
        "season": season,
        "race_id": race_id,
        "driver_id": driver_id,
        "constructor_id": constructor_id,
        "source": source,
    }


def _int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def generate_facts(conn: Any, *, clear_existing: bool = True) -> int:
    if clear_existing:
        clear_generated_facts(conn)

    total = 0
    for chunk in (
        _race_location_facts(conn),
        _result_facts(conn),
        _qualifying_facts(conn),
        _driver_champion_facts(conn),
        _constructor_champion_facts(conn),
    ):
        total += upsert_facts(conn, chunk)

    conn.commit()
    return total


def _race_location_facts(conn: Any) -> Iterable[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT r.raceId, r.year, r.name AS race_name, c.circuitId, c.name AS circuit_name, c.location, c.country
        FROM races r
        JOIN circuits c ON c.circuitId = r.circuitId
        """
    )
    for row in rows:
        season = _int(row["year"])
        location = ", ".join(part for part in (row["location"], row["country"]) if part and part != r"\N")
        yield _fact(
            fact_key=f"race:{row['raceId']}:held_at",
            fact_text=f"The {season} {row['race_name']} was held at {row['circuit_name']} in {location}.",
            subject=f"{season} {row['race_name']}",
            relation="held_at",
            object_=row["circuit_name"],
            season=season,
            race_id=row["raceId"],
            source="generated:race_location",
        )


def _result_facts(conn: Any) -> Iterable[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            res.resultId,
            res.raceId,
            res.driverId,
            res.constructorId,
            res.positionOrder,
            res.grid,
            res.points,
            r.year,
            r.name AS race_name,
            d.forename,
            d.surname,
            c.name AS constructor_name,
            s.status
        FROM results res
        JOIN races r ON r.raceId = res.raceId
        JOIN drivers d ON d.driverId = res.driverId
        JOIN constructors c ON c.constructorId = res.constructorId
        LEFT JOIN status s ON s.statusId = res.statusId
        WHERE res.positionOrder != ''
        """
    )
    for row in rows:
        season = _int(row["year"])
        position = _int(row["positionOrder"])
        if season is None or position is None:
            continue
        driver_name = f"{row['forename']} {row['surname']}".strip()
        race = f"{season} {row['race_name']}"
        constructor_name = row["constructor_name"]
        points = row["points"]

        if position == 1:
            yield _fact(
                fact_key=f"result:{row['resultId']}:winner",
                fact_text=f"{driver_name} won the {race} for {constructor_name}.",
                subject=driver_name,
                relation="won_race",
                object_=race,
                season=season,
                race_id=row["raceId"],
                driver_id=row["driverId"],
                constructor_id=row["constructorId"],
                source="generated:race_result",
            )
            yield _fact(
                fact_key=f"result:{row['resultId']}:constructor_winner",
                fact_text=f"{constructor_name} won the {race} with {driver_name}.",
                subject=constructor_name,
                relation="won_race",
                object_=race,
                season=season,
                race_id=row["raceId"],
                driver_id=row["driverId"],
                constructor_id=row["constructorId"],
                source="generated:race_result",
            )

        if position <= 3:
            yield _fact(
                fact_key=f"result:{row['resultId']}:podium",
                fact_text=f"{driver_name} finished on the podium in P{position} at the {race}.",
                subject=driver_name,
                relation="podium_finish",
                object_=race,
                season=season,
                race_id=row["raceId"],
                driver_id=row["driverId"],
                constructor_id=row["constructorId"],
                source="generated:race_result",
            )

        yield _fact(
            fact_key=f"result:{row['resultId']}:finish",
            fact_text=f"{driver_name} finished P{position} in the {race} for {constructor_name} and scored {points} points.",
            subject=driver_name,
            relation="finished",
            object_=f"P{position} {race}",
            season=season,
            race_id=row["raceId"],
            driver_id=row["driverId"],
            constructor_id=row["constructorId"],
            source="generated:race_result",
        )


def _qualifying_facts(conn: Any) -> Iterable[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            q.qualifyId,
            q.raceId,
            q.driverId,
            q.constructorId,
            q.position,
            r.year,
            r.name AS race_name,
            d.forename,
            d.surname,
            c.name AS constructor_name
        FROM qualifying q
        JOIN races r ON r.raceId = q.raceId
        JOIN drivers d ON d.driverId = q.driverId
        JOIN constructors c ON c.constructorId = q.constructorId
        WHERE q.position = '1'
        """
    )
    for row in rows:
        season = _int(row["year"])
        driver_name = f"{row['forename']} {row['surname']}".strip()
        race = f"{season} {row['race_name']}"
        yield _fact(
            fact_key=f"qualifying:{row['qualifyId']}:pole",
            fact_text=f"{driver_name} took pole position for the {race} with {row['constructor_name']}.",
            subject=driver_name,
            relation="pole_position",
            object_=race,
            season=season,
            race_id=row["raceId"],
            driver_id=row["driverId"],
            constructor_id=row["constructorId"],
            source="generated:qualifying",
        )


def _driver_champion_facts(conn: Any) -> Iterable[dict[str, Any]]:
    rows = conn.execute(
        """
        WITH final_races AS (
            SELECT year, MAX(CAST(round AS INTEGER)) AS final_round
            FROM races
            GROUP BY year
        )
        SELECT
            ds.driverStandingsId,
            ds.driverId,
            ds.points,
            ds.wins,
            r.year,
            d.forename,
            d.surname
        FROM driver_standings ds
        JOIN races r ON r.raceId = ds.raceId
        JOIN final_races fr ON fr.year = r.year AND fr.final_round = CAST(r.round AS INTEGER)
        JOIN drivers d ON d.driverId = ds.driverId
        WHERE ds.position = '1'
        """
    )
    for row in rows:
        season = _int(row["year"])
        driver_name = f"{row['forename']} {row['surname']}".strip()
        yield _fact(
            fact_key=f"season:{season}:drivers_champion",
            fact_text=f"{driver_name} won the {season} Formula 1 Drivers' Championship with {row['points']} points and {row['wins']} wins.",
            subject=driver_name,
            relation="won_drivers_championship",
            object_=f"{season} Drivers' Championship",
            season=season,
            driver_id=row["driverId"],
            source="generated:driver_standings",
        )


def _constructor_champion_facts(conn: Any) -> Iterable[dict[str, Any]]:
    rows = conn.execute(
        """
        WITH final_races AS (
            SELECT year, MAX(CAST(round AS INTEGER)) AS final_round
            FROM races
            GROUP BY year
        )
        SELECT
            cs.constructorStandingsId,
            cs.constructorId,
            cs.points,
            cs.wins,
            r.year,
            c.name AS constructor_name
        FROM constructor_standings cs
        JOIN races r ON r.raceId = cs.raceId
        JOIN final_races fr ON fr.year = r.year AND fr.final_round = CAST(r.round AS INTEGER)
        JOIN constructors c ON c.constructorId = cs.constructorId
        WHERE cs.position = '1'
        """
    )
    for row in rows:
        season = _int(row["year"])
        constructor_name = row["constructor_name"]
        yield _fact(
            fact_key=f"season:{season}:constructors_champion",
            fact_text=f"{constructor_name} won the {season} Formula 1 Constructors' Championship with {row['points']} points and {row['wins']} wins.",
            subject=constructor_name,
            relation="won_constructors_championship",
            object_=f"{season} Constructors' Championship",
            season=season,
            constructor_id=row["constructorId"],
            source="generated:constructor_standings",
        )
