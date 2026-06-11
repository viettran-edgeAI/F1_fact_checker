from __future__ import annotations

import re
from typing import Any

from ..config import FactCheckConfig
from .vector_index import StructuredFactVectorIndex


_VECTOR_INDEX_CACHE: dict[tuple[str, str, str], StructuredFactVectorIndex] = {}

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
    filtered = []
    for term in terms:
        normalized = term.replace("'", "")
        if len(normalized) > 1 and normalized not in stop_words:
            filtered.append(normalized)
    return " OR ".join(filtered[:24])


def search_facts_fts(conn: Any, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
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
    facts = [dict(row) for row in rows]
    for fact in facts:
        fact["fts_score"] = fact["score"]
        fact["retrieval_method"] = "fts"
    return facts


def search_facts(conn: Any, query: str, *, limit: int = 8, config: FactCheckConfig | None = None) -> list[dict[str, Any]]:
    keyword_results = search_facts_fts(conn, query, limit=limit)
    resolved_config = config or FactCheckConfig.from_env()
    vector_results = _search_facts_vector(conn, query, limit=limit, config=resolved_config)
    return _merge_ranked_results(
        keyword_results,
        vector_results,
        limit=limit,
        sql_first=resolved_config.structured_sql_first,
    )


def _search_facts_vector(
    conn: Any,
    query: str,
    *,
    limit: int,
    config: FactCheckConfig,
) -> list[dict[str, Any]]:
    if not config.embedding_model_dir.exists():
        return []
    index = _vector_index_for_config(config)
    return index.search(conn, query, limit=limit, min_score=config.min_vector_score)


def _vector_index_for_config(config: FactCheckConfig) -> StructuredFactVectorIndex:
    key = (str(config.embedding_model_dir), str(config.faiss_index_path), str(config.fact_metadata_path))
    if key not in _VECTOR_INDEX_CACHE:
        _VECTOR_INDEX_CACHE[key] = StructuredFactVectorIndex(
            model_dir=config.embedding_model_dir,
            index_path=config.faiss_index_path,
            metadata_path=config.fact_metadata_path,
            embedding_batch_size=config.embedding_batch_size,
        )
    return _VECTOR_INDEX_CACHE[key]


def _merge_ranked_results(
    keyword_results: list[dict[str, Any]],
    vector_results: list[dict[str, Any]],
    *,
    limit: int,
    sql_first: bool,
) -> list[dict[str, Any]]:
    if not keyword_results:
        return vector_results[:limit]
    if not vector_results:
        return keyword_results[:limit]

    merged: dict[int, dict[str, Any]] = {}
    for rank, row in enumerate(keyword_results, start=1):
        payload = dict(row)
        payload["hybrid_score"] = 1.0 / (10 + rank)
        payload["rank_fts"] = rank
        payload["rank_vector"] = None
        merged[int(payload["fact_id"])] = payload

    for rank, row in enumerate(vector_results, start=1):
        fact_id = int(row["fact_id"])
        if fact_id not in merged:
            payload = dict(row)
            payload["hybrid_score"] = 0.0
            payload["rank_fts"] = None
            payload["rank_vector"] = rank
            merged[fact_id] = payload
        payload = merged[fact_id]
        payload["hybrid_score"] += 1.0 / (10 + rank)
        payload["rank_vector"] = rank
        payload["vector_score"] = row.get("vector_score")
        if payload.get("retrieval_method") == "fts":
            payload["retrieval_method"] = "hybrid"

    def sort_key(row: dict[str, Any]) -> tuple[float, int, int, float, float]:
        has_fts = 1 if row.get("rank_fts") is not None else 0
        has_vector = 1 if row.get("rank_vector") is not None else 0
        vector_score = float(row.get("vector_score") or 0.0)
        fts_score = float(row.get("fts_score") or 0.0)
        return (
            float(row.get("hybrid_score") or 0.0),
            has_fts if sql_first else has_vector,
            has_vector if sql_first else has_fts,
            vector_score,
            -fts_score,
        )

    ranked = sorted(merged.values(), key=sort_key, reverse=True)
    for row in ranked:
        if row.get("retrieval_method") == "hybrid":
            row["score"] = float(row.get("hybrid_score") or 0.0)
    return ranked[:limit]
