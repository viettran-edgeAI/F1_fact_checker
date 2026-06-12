from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_POLICY_PATH = APP_ROOT / "configs" / "source_policy.yaml"


@dataclass(frozen=True, slots=True)
class FactCheckConfig:
    db_path: Path
    faiss_index_path: Path
    source_data_dir: Path
    jolpica_cache_dir: Path
    fact_metadata_path: Path
    embedding_model_dir: Path
    jolpica_base_url: str
    jolpica_timeout_seconds: float
    llm_service_url: str
    ocr_service_url: str
    llm_timeout_seconds: float
    brave_search_count: int
    brave_search_timeout: float
    brave_context_count: int
    brave_context_max_urls: int
    brave_context_max_snippets: int
    brave_context_max_tokens: int
    structured_sql_first: bool
    min_vector_score: float
    embedding_batch_size: int
    url_fetch_timeout_seconds: float
    url_fetch_max_bytes: int
    url_allowed_schemes: tuple[str, ...]
    source_policy_path: Path = DEFAULT_SOURCE_POLICY_PATH

    @classmethod
    def from_env(cls) -> "FactCheckConfig":
        data_root = APP_ROOT / "data"
        source_policy_path = Path(os.environ.get("FACT_SOURCE_POLICY_PATH", DEFAULT_SOURCE_POLICY_PATH))
        brave_context_defaults = _source_policy_brave_context_defaults(source_policy_path)
        default_embedding_root = Path("/home/viettran_orin/models/embedding/all-MiniLM-L6-v2")
        return cls(
            db_path=Path(os.environ.get("FACT_DB_PATH", data_root / "knowledge_db" / "f1.sqlite")),
            faiss_index_path=Path(os.environ.get("FACT_FAISS_INDEX_PATH", data_root / "knowledge_db" / "faiss.index")),
            source_data_dir=Path(os.environ.get("FACT_SOURCE_DATA_DIR", data_root / "F1_WC_data")),
            jolpica_cache_dir=Path(
                os.environ.get("JOLPICA_CACHE_DIR", data_root / "source_data" / "jolpica_cache")
            ),
            fact_metadata_path=Path(
                os.environ.get("FACT_METADATA_PATH", data_root / "knowledge_db" / "fact_metadata.jsonl")
            ),
            source_policy_path=source_policy_path,
            embedding_model_dir=Path(os.environ.get("EMBEDDING_MODEL_DIR", default_embedding_root)),
            jolpica_base_url=os.environ.get("JOLPICA_BASE_URL", "https://api.jolpi.ca/ergast/f1").rstrip("/"),
            jolpica_timeout_seconds=float(os.environ.get("JOLPICA_TIMEOUT_SECONDS", "20")),
            llm_service_url=os.environ.get("LLM_SERVICE_URL", "http://llm-service:8081").rstrip("/"),
            ocr_service_url=os.environ.get("OCR_SERVICE_URL", "http://ocr-service:8000").rstrip("/"),
            llm_timeout_seconds=float(os.environ.get("FACT_LLM_TIMEOUT_SECONDS", "120")),
            brave_search_count=int(os.environ.get("BRAVE_SEARCH_COUNT", os.environ.get("BRAVE_SEARCH_TOP_N", "3"))),
            brave_search_timeout=float(os.environ.get("BRAVE_SEARCH_TIMEOUT", "10")),
            brave_context_count=int(os.environ.get("BRAVE_CONTEXT_COUNT", "10")),
            brave_context_max_urls=int(
                os.environ.get("BRAVE_CONTEXT_MAX_URLS", str(brave_context_defaults.get("maximum_number_of_urls", 5)))
            ),
            brave_context_max_snippets=int(
                os.environ.get(
                    "BRAVE_CONTEXT_MAX_SNIPPETS",
                    str(brave_context_defaults.get("maximum_number_of_snippets", 12)),
                )
            ),
            brave_context_max_tokens=int(
                os.environ.get(
                    "BRAVE_CONTEXT_MAX_TOKENS",
                    str(brave_context_defaults.get("maximum_number_of_tokens", 4096)),
                )
            ),
            structured_sql_first=os.environ.get("FACT_STRUCTURED_SQL_FIRST", "1").strip().lower()
            not in {"0", "false", "no", "off"},
            min_vector_score=float(os.environ.get("FACT_MIN_VECTOR_SCORE", "0.35")),
            embedding_batch_size=int(os.environ.get("FACT_EMBEDDING_BATCH_SIZE", "32")),
            url_fetch_timeout_seconds=float(os.environ.get("URL_FETCH_TIMEOUT_SECONDS", "10")),
            url_fetch_max_bytes=int(os.environ.get("URL_FETCH_MAX_BYTES", "3000000")),
            url_allowed_schemes=tuple(
                scheme.strip().lower()
                for scheme in os.environ.get("URL_ALLOWED_SCHEMES", "http,https").split(",")
                if scheme.strip()
            ),
        )


def _source_policy_brave_context_defaults(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    try:
        import yaml

        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    defaults = payload.get("brave_llm_context_defaults") if isinstance(payload, dict) else None
    if not isinstance(defaults, dict):
        return {}
    output: dict[str, int] = {}
    for key, value in defaults.items():
        try:
            output[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return output
