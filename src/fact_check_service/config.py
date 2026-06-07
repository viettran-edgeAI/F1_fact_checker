from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class FactCheckConfig:
    db_path: Path
    source_data_dir: Path
    jolpica_cache_dir: Path
    fact_metadata_path: Path
    jolpica_base_url: str
    jolpica_timeout_seconds: float

    @classmethod
    def from_env(cls) -> "FactCheckConfig":
        data_root = APP_ROOT / "data"
        return cls(
            db_path=Path(os.environ.get("FACT_DB_PATH", data_root / "knowledge_db" / "f1.sqlite")),
            source_data_dir=Path(os.environ.get("FACT_SOURCE_DATA_DIR", data_root / "F1_WC_data")),
            jolpica_cache_dir=Path(
                os.environ.get("JOLPICA_CACHE_DIR", data_root / "source_data" / "jolpica_cache")
            ),
            fact_metadata_path=Path(
                os.environ.get("FACT_METADATA_PATH", data_root / "knowledge_db" / "fact_metadata.jsonl")
            ),
            jolpica_base_url=os.environ.get("JOLPICA_BASE_URL", "https://api.jolpi.ca/ergast/f1").rstrip("/"),
            jolpica_timeout_seconds=float(os.environ.get("JOLPICA_TIMEOUT_SECONDS", "20")),
        )
