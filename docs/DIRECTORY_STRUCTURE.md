# Directory Structure

Keep this document brief and update it whenever folders change.

| Path | Purpose |
| --- | --- |
| `/` | Project root for Compose wiring, helper scripts, top-level planning docs, and the landing `README.md`. |
| `configs/` | Runtime configuration files and examples. |
| `configs/models.host.env` | Host-side active model paths for OCR det/rec, LLM, and embeddings. |
| `configs/models.container.env` | Container-side active model paths used by Compose. |
| `configs/fact_check.env.example` | Example fact-check service configuration for knowledge DB, OCR, LLM, and URL ingest settings. |
| `data/` | Local runtime artifacts and development data. |
| `data/fact_check/` | Saved fact-check requests, results, and session artifacts. |
| `data/knowledge_db/` | Planned SQLite, FAISS, metadata, and manifest outputs for the local F1 knowledge database. |
| `data/source_data/` | Raw Formula 1 CSV source data and cached Jolpica responses. |
| `data/uploads/` | OCR upload staging area. |
| `data/ocr_text/` | OCR plain-text extraction outputs. |
| `data/web_app/` | Existing web-app runtime state retained for later UI/session refactor. |
| `docker/` | Container build recipes. |
| `docker/Dockerfile.ocr` | Jetson OCR service image recipe for image-to-text extraction. |
| `docker/Dockerfile.fact_check` | Fact-check service image recipe. |
| `docker/Dockerfile.llm` | Jetson LLM service image recipe. |
| `docker/Dockerfile.web` | Public web-app image recipe. |
| `docs/` | Active project documentation. |
| `docs/archive/jetson_ocr_ai/` | Archived OCR AI service documents kept for reference. |
| `requirements/` | Python dependency sets grouped by service. |
| `requirements/ocr.txt` | OCR service dependencies. |
| `requirements/fact_check.txt` | Fact-check service dependencies. |
| `requirements/llm.txt` | LLM service dependencies. |
| `requirements/web.txt` | Web-app dependencies. |
| `scripts/` | Local helper and smoke-test scripts. Legacy OCR diagnostics remain here until later archival. |
| `src/fact_check_service/` | New F1 fact-check orchestration service. Currently health-checkable scaffold only. |
| `src/fact_check_service/knowledge/` | Planned local knowledge DB import, sync, fact generation, embeddings, SQLite, and FAISS code. |
| `src/ocr_service/` | Private OCR backend. Active contract is image upload to plain-text JSON. |
| `src/llm_service/` | Private Gemma/llama-server wrapper retained for later claim extraction and verdict generation refactor. |
| `src/web_app/` | Public browser UI and session layer retained for later F1 fact-check UI refactor. |
| `tests/` | Automated tests, including the OCR service API contract test. |
| `third_party/` | Bundled third-party runtime dependencies. |
| `wheels/` | Jetson-compatible PaddlePaddle wheel storage. |
| `docker-compose.yml` | Local four-service runtime wiring. |
| `start_app.sh` | Start helper for the multi-container runtime with readiness checks. |
| `stop_app.sh` | Stop helper for the running stack. |

External model storage remains outside the repository under `/home/viettran_orin/models`.
