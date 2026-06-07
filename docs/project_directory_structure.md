# Project Directory Structure

This document lists the current repository layout only. It intentionally excludes architecture, workflow, and progress details.

## Detail

```text
/
├── README.md
├── configs/
├── data/
├── docker/
├── docs/
├── requirements/
├── scripts/
├── src/
├── tests/
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
