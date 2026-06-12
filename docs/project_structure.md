# Project Directory Structure

This document describes the current repository layout only. It intentionally stays focused on the file tree and short path notes.

## Detail

```text
/
├── README.md
├── AGENTS.md
├── configs/
│   ├── fact_check.env.example
│   ├── models.container.env
│   ├── models.host.env
│   └── source_policy.yaml
├── data/
├── docker/
│   ├── Dockerfile.fact_check
│   ├── Dockerfile.llm
│   ├── Dockerfile.ocr
│   └── Dockerfile.web
├── docs/
│   ├── Brave_search_API_for_AI_agent.md
│   ├── dream_directory_structure.md
│   ├── fact_check_service.md
│   ├── f1_source_policy.md
│   ├── knowledge_database_build_process.md
│   ├── llm_service.md
│   ├── ocr_service.md
│   ├── project_diary.md
│   ├── project_overview.md
│   ├── project_progress.md
│   ├── project_structure.md
│   └── web_app.md
├── requirements/
│   ├── fact_check.txt
│   ├── llm.txt
│   ├── ocr.txt
│   └── web.txt
├── scripts/
│   ├── build_f1_database.py
│   ├── inspect_fact.py
│   ├── measure_pipeline_baseline.py
│   ├── run_pipeline_box_overlay.py
│   ├── smoke_ocr_service.py
│   └── sync_jolpica.py
├── src/
│   ├── fact_check_service/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── input_adapters.py
│   │   ├── llm_client.py
│   │   ├── main.py
│   │   ├── orchestrator.py
│   │   ├── retrieval.py
│   │   ├── schemas.py
│   │   ├── source_policy.py
│   │   ├── web_evidence.py
│   │   ├── web_search.py
│   │   ├── prompts/
│   │   │   ├── claim_classification.md
│   │   │   ├── claim_extraction.md
│   │   │   ├── search_query_generation.md
│   │   │   └── verdict_generation.md
│   │   └── knowledge/
│   │       ├── __init__.py
│   │       ├── dataset_importer.py
│   │       ├── embeddings.py
│   │       ├── fact_generator.py
│   │       ├── jolpica_sync.py
│   │       ├── retrieval.py
│   │       ├── sqlite_store.py
│   │       └── vector_index.py
│   ├── llm_service/
│   │   ├── __init__.py
│   │   └── main.py
│   ├── ocr_service/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── image_ops.py
│   │   ├── local_infer.py
│   │   ├── main.py
│   │   ├── models.py
│   │   ├── module_benchmark.py
│   │   ├── paddle_adapter.py
│   │   ├── pipeline.py
│   │   └── schemas.py
│   ├── runtime_env.py
│   └── web_app/
│       ├── __init__.py
│       ├── auth.py
│       ├── main.py
│       ├── store.py
│       ├── clients/
│       │   ├── __init__.py
│       │   └── fact_check_client.py
│       └── static/
│           ├── app.js
│           ├── index.html
│           └── styles.css
├── tests/
│   ├── f1_fact_check_jsonl_runner.py
│   ├── f1_fact_check_test_cases.jsonl
│   ├── test_fact_check_text_flow.py
│   ├── test_f1_knowledge_database.py
│   ├── test_knowledge_database_build_process.py
│   ├── test_llm_service_parsing.py
│   ├── test_ocr_service_api.py
│   └── test_web_app_fact_check.py
├── third_party/
├── wheels/
├── docker-compose.yml
├── start_app.sh
└── stop_app.sh
```

## Path Notes

| Path | Purpose |
| --- | --- |
| `README.md` | Root entry point and documentation index. |
| `AGENTS.md` | Project-specific working instructions for coding agents. |
| `configs/` | Environment examples, model path configs, and source-ranking policy. |
| `data/` | Runtime-generated artifacts such as uploads, OCR text, caches, and the local knowledge database. |
| `docker/` | Per-service Dockerfiles for the local stack. |
| `docs/` | Active project and module documentation. |
| `requirements/` | Python dependency sets split by runtime service. |
| `scripts/` | Local helper scripts for knowledge-base build, sync, OCR checks, and pipeline inspection. |
| `src/fact_check_service/` | F1 fact-check orchestration, routing, source-policy handling, retrieval, and verdict generation. |
| `src/fact_check_service/knowledge/` | Local knowledge-base build, storage, embeddings, vector index, and retrieval helpers. |
| `src/llm_service/` | FastAPI wrapper around local `llama-server` / Gemma inference. |
| `src/ocr_service/` | Image-only OCR service used to normalize screenshots into text. |
| `src/web_app/` | User-facing FastAPI app, auth/session storage, and static browser assets. |
| `src/runtime_env.py` | Shared runtime environment utilities. |
| `tests/` | Automated tests plus JSONL-based fact-check case runner inputs. |
| `third_party/` | Bundled third-party runtime dependencies when needed locally. |
| `wheels/` | Local wheel cache for environment-specific packages. |
| `docker-compose.yml` | Multi-service local runtime definition. |
| `start_app.sh` / `stop_app.sh` | Shell helpers for starting and stopping the stack. |

## Notes

- This document lists active tracked paths only; it does not describe runtime behavior in detail.
- `__pycache__/` directories and other generated files are intentionally omitted from the structure view.
