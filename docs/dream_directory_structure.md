```
F1_fact_checker/
├── README.md
├── docker-compose.yml
├── .env
├── .env.example
├── .gitignore
├── start_app.sh
├── stop_app.sh
│
├── docs/
│   ├── project_structure.md
│   ├── web_app.md
│   ├── ocr_service.md
│   ├── llm_service.md
│   ├── fact_check_service.md
│   ├── project_progress.md
│   ├── ...
│
├── configs/
│   ├── models.host.env
│   ├── models.container.env
│   ├── fact_check.yaml
│   ├── brave_search.yaml
│   ├── logging.yaml
│   ├── ...
│
├── docker/
│   ├── Dockerfile.web
│   ├── Dockerfile.ocr
│   ├── Dockerfile.llm
│   └── Dockerfile.fact_check
│
├── requirements/
│   ├── web.txt
│   ├── ocr.txt
│   ├── llm.txt
│   └── fact_check.txt
│
├── data/
│   ├── web_app/
│   │   ├── uploads/
│   │   ├── sessions/
│   │   └── app.db
│   │
│   ├── ocr_service/
│   │   ├── uploads/
│   │   └── results/
│   │
│   ├── fact_check/
│   │   ├── inputs/
│   │   ├── results/
│   │   ├── cache/
│   │   └── evidence/
│   │
│   └── knowledge_db/
│       ├── raw/
│       │   ├── kaggle_f1/
│       │   └── jolpica/
│       │
│       ├── processed/
│       │   ├── normalized/
│       │   └── facts/
│       │
│       ├── sqlite/
│       │   └── f1_knowledge.db
│       │
│       └── faiss/
│           ├── facts.index
│           └── facts_metadata.json
│
├── models/
│   └── README.md
│
├── prompts/
│   ├── claim_extraction.md
│   ├── f1_relevance_classification.md
│   ├── claim_classification.md
│   ├── search_query_generation.md
│   ├── verdict_generation.md
│   ├── final_result_summary.md
│   └── ...
│
├── scripts/
│   ├── build_knowledge_db.py
│   ├── sync_jolpica.py
│   ├── generate_facts.py
│   ├── build_faiss_index.py
│   ├── test_brave_search.py
│   ├── test_fact_check.py
│   ├── eset_runtime_data.sh
│   └── ...
│
├── src/
│   ├── web_app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── store.py
│   │   ├── auth.py
│   │   ├── clients/
│   │   │   ├── __init__.py
│   │   │   ├── ocr_client.py
│   │   │   ├── llm_client.py
│   │   │   ├── fact_check_client.py
│   │   │   └── ...
│   │   │
│   │   ├── templates/
│   │   │   └── index.html
│   │   │
│   │   └── static/
│   │       ├── css/
│   │       │   └── app.css
│   │       ├── js/
│   │       │   ├── app.js
│   │       │   ├── input_panel.js
│   │       │   ├── result_panel.js
│   │       │   └── sessions.js
│   │       └── assets/
│   │
│   ├── ocr_service/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── pipeline.py
│   │   ├── paddle_adapter.py
│   │   ├── image_ops.py
│   │   └── models.py
│   │
│   ├── llm_service/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── llama_client.py
│   │   ├── prompt_loader.py
│   │   ├── prompt_builder.py
│   │   └── ...
│   │
│   └── fact_check_service/
│       ├── __init__.py
│       ├── main.py
│       ├── config.py
│       ├── schemas.py
│       │
│       ├── input/
│       │   ├── __init__.py
│       │   ├── normalizer.py
│       │   ├── text_input.py
│       │   ├── image_input.py
│       │   └── url_input.py
│       │
│       ├── relevance/
│       │   ├── __init__.py
│       │   └── f1_classifier.py
│       │
│       ├── claims/
│       │   ├── __init__.py
│       │   ├── extractor.py
│       │   ├── classifier.py
│       │   └── router.py
│       │
│       ├── retrieval/
│       │   ├── __init__.py
│       │   ├── local_retriever.py
│       │   ├── sqlite_store.py
│       │   ├── faiss_store.py
│       │   ├── brave_client.py
│       │   ├── web_retriever.py
│       │   └── evidence_ranker.py
│       │
│       ├── verdict/
│       │   ├── __init__.py
│       │   ├── generator.py
│       │   └── aggregator.py
│       │
│       └── knowledge_db/
│           ├── __init__.py
│           ├── importer.py
│           ├── normalizer.py
│           ├── jolpica_client.py
│           ├── fact_generator.py
│           └── index_builder.py
│
├── tests/
│   ├── test_ocr_service/
│   │   ├── test_simple_ocr.py
│   │   └── ...
│   │
│   ├── test_llm_service/
│   │   ├── test_prompt_builder.py
│   │   └── ...
│   │
│   ├── test_fact_check_service/
│   │   ├── test_input_normalizer.py
│   │   ├── test_f1_relevance.py
│   │   ├── test_claim_router.py
│   │   ├── test_local_retriever.py
│   │   ├── test_brave_client.py
│   │   ├── ...
│   │
│   └── test_web_app/
│       ├── test_routes.py
│       └── ...
│
├── third_party/
│   ├── llama-bin/
│   │	└── bin/
│   └── ...     
│
└── wheels/
    ├── paddlepaddle_gpu-...
    └── ...


```
