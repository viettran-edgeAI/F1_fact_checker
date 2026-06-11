from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .embeddings import MiniLMEmbedder

try:
    import faiss  # type: ignore
except ImportError:  # pragma: no cover - optional runtime acceleration.
    faiss = None


@dataclass(frozen=True, slots=True)
class FactIndexSnapshot:
    fact_count: int
    max_updated_at: str


@dataclass(frozen=True, slots=True)
class FactVectorBuildResult:
    backend: str
    dimension: int
    fact_count: int
    max_updated_at: str
    index_path: Path
    numpy_index_path: Path
    metadata_path: Path
    manifest_path: Path
    wrote_faiss_index: bool


def current_snapshot(conn: Any) -> FactIndexSnapshot:
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS fact_count,
            COALESCE(MAX(updated_at), '') AS max_updated_at
        FROM facts
        """
    ).fetchone()
    return FactIndexSnapshot(fact_count=int(row["fact_count"]), max_updated_at=str(row["max_updated_at"] or ""))


def fetch_fact_rows(conn: Any) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            fact_id,
            fact_text,
            subject,
            relation,
            object,
            season,
            race_id,
            driver_id,
            constructor_id,
            source,
            updated_at
        FROM facts
        ORDER BY fact_id
        """
    )
    return [dict(row) for row in rows]


class StructuredFactVectorIndex:
    def __init__(
        self,
        *,
        model_dir: Path,
        index_path: Path,
        metadata_path: Path,
        embedding_batch_size: int = 32,
    ) -> None:
        self._model_dir = model_dir
        self._index_path = index_path
        self._metadata_path = metadata_path
        self._manifest_path = metadata_path.with_suffix(f"{metadata_path.suffix}.meta.json")
        self._numpy_index_path = index_path.with_suffix(".npy")
        self._embedding_batch_size = max(1, embedding_batch_size)
        self._lock = threading.Lock()
        self._embedder: MiniLMEmbedder | None = None
        self._records: list[dict[str, Any]] = []
        self._matrix: np.ndarray | None = None
        self._faiss_index: Any | None = None
        self._snapshot: FactIndexSnapshot | None = None
        self._backend = "uninitialized"

    @property
    def available(self) -> bool:
        return (self._model_dir / "tokenizer.json").exists() and (self._model_dir / "onnx" / "model.onnx").exists()

    def search(self, conn: Any, query: str, *, limit: int, min_score: float) -> list[dict[str, Any]]:
        if not self.available or not query.strip():
            return []
        self._ensure_loaded(conn)
        if not self._records:
            return []

        query_vector = self._embedder_or_raise().encode([query])[0]
        scores, indices = self._search_vectors(query_vector, limit)
        matches: list[dict[str, Any]] = []
        for score, index in zip(scores, indices, strict=False):
            if index < 0 or score < min_score:
                continue
            row = dict(self._records[index])
            row["vector_score"] = float(score)
            row["score"] = float(score)
            row["retrieval_method"] = "vector"
            row["vector_backend"] = self._backend
            matches.append(row)
        return matches

    def backend_name(self) -> str:
        return self._backend

    def build(self, conn: Any, *, force: bool = False) -> FactVectorBuildResult:
        if not self.available:
            raise FileNotFoundError(f"Embedding model is not available: {self._model_dir}")

        snapshot = current_snapshot(conn)
        with self._lock:
            if not force and self._load_from_disk(snapshot):
                return self._build_result(snapshot)
            self._rebuild(conn, snapshot)
            return self._build_result(snapshot)

    def _ensure_loaded(self, conn: Any) -> None:
        snapshot = current_snapshot(conn)
        if self._snapshot == snapshot and self._records:
            return

        with self._lock:
            if self._snapshot == snapshot and self._records:
                return
            if self._load_from_disk(snapshot):
                return
            self._rebuild(conn, snapshot)

    def _load_from_disk(self, snapshot: FactIndexSnapshot) -> bool:
        if not self._manifest_path.exists() or not self._metadata_path.exists():
            return False

        manifest = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        if int(manifest.get("fact_count", -1)) != snapshot.fact_count:
            return False
        if str(manifest.get("max_updated_at", "")) != snapshot.max_updated_at:
            return False

        records = [json.loads(line) for line in self._metadata_path.read_text(encoding="utf-8").splitlines() if line]
        if len(records) != snapshot.fact_count:
            return False

        backend = str(manifest.get("backend", "numpy"))
        dimension = int(manifest.get("dimension", 384))
        if backend == "faiss" and faiss is not None and self._index_path.exists():
            index = faiss.read_index(str(self._index_path))
            self._faiss_index = index
            self._matrix = None
        elif self._numpy_index_path.exists():
            matrix = np.load(self._numpy_index_path, mmap_mode="r")
            if matrix.ndim != 2 or matrix.shape[1] != dimension:
                return False
            self._matrix = matrix
            self._faiss_index = None
            backend = "numpy"
        else:
            return False

        self._records = records
        self._snapshot = snapshot
        self._backend = backend
        return True

    def _rebuild(self, conn: Any, snapshot: FactIndexSnapshot) -> None:
        rows = fetch_fact_rows(conn)
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        self._metadata_path.parent.mkdir(parents=True, exist_ok=True)

        if not rows:
            self._records = []
            self._matrix = np.zeros((0, 384), dtype=np.float32)
            self._faiss_index = None
            self._snapshot = snapshot
            self._backend = "numpy"
            self._persist(records=[], backend=self._backend, snapshot=snapshot, dimension=384)
            return

        embedder = self._embedder_or_raise()
        vectors = np.lib.format.open_memmap(
            self._numpy_index_path,
            mode="w+",
            dtype=np.float32,
            shape=(len(rows), embedder.dimension),
        )
        backend = "faiss" if faiss is not None else "numpy"
        if faiss is not None:
            index = faiss.IndexFlatIP(embedder.dimension)
        else:
            index = None

        for start in range(0, len(rows), self._embedding_batch_size):
            batch_rows = rows[start : start + self._embedding_batch_size]
            batch_vectors = embedder.encode([str(row["fact_text"]) for row in batch_rows])
            stop = start + len(batch_rows)
            vectors[start:stop] = batch_vectors
            if index is not None:
                index.add(batch_vectors)

        del vectors
        persisted_vectors = np.load(self._numpy_index_path, mmap_mode="r")

        if faiss is not None:
            self._faiss_index = index
            self._matrix = None
        else:
            self._faiss_index = None
            self._matrix = persisted_vectors

        self._records = rows
        self._snapshot = snapshot
        self._backend = backend
        self._persist(records=rows, backend=backend, snapshot=snapshot, dimension=embedder.dimension)

    def _persist(
        self,
        *,
        records: list[dict[str, Any]],
        backend: str,
        snapshot: FactIndexSnapshot,
        dimension: int,
    ) -> None:
        with self._metadata_path.open("w", encoding="utf-8") as handle:
            for row in records:
                handle.write(json.dumps(row, sort_keys=True))
                handle.write("\n")

        manifest = {
            "backend": backend,
            "dimension": dimension,
            "fact_count": snapshot.fact_count,
            "max_updated_at": snapshot.max_updated_at,
        }
        self._manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")

        if backend == "faiss" and faiss is not None and self._faiss_index is not None:
            faiss.write_index(self._faiss_index, str(self._index_path))
            return

    def _build_result(self, snapshot: FactIndexSnapshot) -> FactVectorBuildResult:
        dimension = 384
        if self._matrix is not None and self._matrix.ndim == 2:
            dimension = int(self._matrix.shape[1])
        elif self._faiss_index is not None:
            dimension = int(self._faiss_index.d)
        elif self._records:
            dimension = self._embedder_or_raise().dimension

        return FactVectorBuildResult(
            backend=self._backend,
            dimension=dimension,
            fact_count=snapshot.fact_count,
            max_updated_at=snapshot.max_updated_at,
            index_path=self._index_path,
            numpy_index_path=self._numpy_index_path,
            metadata_path=self._metadata_path,
            manifest_path=self._manifest_path,
            wrote_faiss_index=self._backend == "faiss" and self._index_path.exists(),
        )

    def _search_vectors(self, query_vector: np.ndarray, limit: int) -> tuple[np.ndarray, np.ndarray]:
        top_k = max(limit * 2, limit)
        if self._faiss_index is not None:
            scores, indices = self._faiss_index.search(query_vector.reshape(1, -1), top_k)
            return scores[0], indices[0]

        matrix = self._matrix
        if matrix is None or matrix.size == 0:
            return np.zeros((0,), dtype=np.float32), np.zeros((0,), dtype=np.int64)

        scores = matrix @ query_vector.astype(np.float32)
        order = np.argsort(scores)[::-1][:top_k]
        return scores[order], order.astype(np.int64)

    def _embedder_or_raise(self) -> MiniLMEmbedder:
        if self._embedder is None:
            self._embedder = MiniLMEmbedder.from_model_dir(self._model_dir)
        return self._embedder


def build_structured_fact_vector_index(
    conn: Any,
    *,
    model_dir: Path,
    index_path: Path,
    metadata_path: Path,
    embedding_batch_size: int = 32,
    force: bool = False,
) -> FactVectorBuildResult:
    index = StructuredFactVectorIndex(
        model_dir=model_dir,
        index_path=index_path,
        metadata_path=metadata_path,
        embedding_batch_size=embedding_batch_size,
    )
    return index.build(conn, force=force)
