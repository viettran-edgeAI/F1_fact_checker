# Project Directory Structure

This document lists the current repository layout only. It intentionally excludes architecture, workflow, and progress details.

## Detail

```text
/
├── README.md
├── configs/
│   ├── fact_check.env.example
│   ├── models.container.env
│   └── models.host.env
├── data/
├── docker/
│   ├── Dockerfile.fact_check
│   ├── Dockerfile.llm
│   ├── Dockerfile.ocr
│   └── Dockerfile.web
├── docs/
│   ├── fact_check_service.md
│   ├── llm_service.md
│   ├── ocr_service.md
│   ├── project_directory_structure.md
│   ├── project_progress.md
│   └── web_app.md
├── requirements/
│   ├── fact_check.txt
│   ├── llm.txt
│   ├── ocr.txt
│   └── web.txt
├── scripts/
│   ├── build_f1_database.py
│   ├── inspect_fact.py
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
│   │   ├── prompts/
│   │   │   ├── claim_classification.md
│   │   │   ├── claim_extraction.md
│   │   │   ├── search_query_generation.md
│   │   │   ├── verdict_generation.md
│   │   │   └── f1_relevance_classification.md
│   │   ├── retrieval.py
│   │   ├── schemas.py
│   │   ├── web_evidence.py
│   │   ├── web_search.py
│   │   └── knowledge/
│   │       ├── __init__.py
│   │       ├── dataset_importer.py
│   │       ├── fact_generator.py
│   │       ├── jolpica_sync.py
│   │       ├── retrieval.py
│   │       └── sqlite_store.py
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
│   ├── test_fact_check_text_flow.py
│   ├── test_f1_knowledge_database.py
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
| `README.md` | Root landing page and doc index. |
| `configs/` | Runtime configuration files and environment examples. |
| `data/` | Generated runtime artifacts, caches, uploads, and knowledge data. |
| `docker/` | Service Dockerfiles. |
| `docs/` | Active documentation only. |
| `requirements/` | Python dependency sets split by service. |
| `scripts/` | Local helper and build/sync scripts. |
| `src/` | Application source code for the four runtime services. |
| `tests/` | Automated tests. |
| `third_party/` | Bundled third-party runtime dependencies. |
| `wheels/` | Local wheel cache for Jetson-compatible packages. |
| `docker-compose.yml` | Local multi-service runtime definition. |
| `start_app.sh` / `stop_app.sh` | Shell helpers for bringing the stack up and down. |
