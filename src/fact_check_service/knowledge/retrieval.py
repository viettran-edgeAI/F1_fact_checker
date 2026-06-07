from __future__ import annotations

import re
from typing import Any


def _fts_query(text: str) -> str:
    terms = re.findall(r"[A-Za-z0-9']+", text.lower())
    stop_words = {
        "a",
        "an",
        "and",
        "at",
        "for",
        "in",
        "of",
        "on",
        "the",
        "to",
        "with",
    }
    filtered = [term for term in terms if len(term) > 1 and term not in stop_words]
    return " OR ".join(filtered[:24])


def search_facts(conn: Any, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
    fts = _fts_query(query)
    if not fts:
        return []
    rows = conn.execute(
        """
        SELECT
            f.fact_id,
            f.fact_text,
            f.subject,
            f.relation,
            f.object,
            f.season,
            f.race_id,
            f.driver_id,
            f.constructor_id,
            f.source,
            bm25(facts_fts) AS score
        FROM facts_fts
        JOIN facts f ON f.fact_id = facts_fts.rowid
        WHERE facts_fts MATCH ?
        ORDER BY score
        LIMIT ?
        """,
        (fts, limit),
    )
    return [dict(row) for row in rows]
