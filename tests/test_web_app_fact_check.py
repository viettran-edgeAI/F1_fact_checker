from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class FakeUpload:
    filename = "claim.png"
    content_type = "image/png"

    async def read(self) -> bytes:
        return b"\x89PNG\r\n\x1a\n"


def test_text_check_session_persists_fact_check_result(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_APP_DATA_DIR", str(tmp_path / "web_app"))
    monkeypatch.setenv("WEB_APP_SECRET_KEY", "dev-insecure-change-me")
    main = importlib.import_module("web_app.main")
    main = importlib.reload(main)

    def fake_check_text(text: str, *, meta: dict[str, object] | None = None) -> dict[str, object]:
        return {
            "text": text,
            "verdict": "SUPPORTS",
            "summary": "The local evidence supports the claim.",
            "claims": [
                {
                    "claim": {
                        "claim_id": "c001",
                        "text": "Max Verstappen won the 2021 Abu Dhabi Grand Prix.",
                        "claim_type": "race_result",
                        "verification_stream": "structured",
                    },
                    "verdict": "SUPPORTS",
                    "verification_stream": "structured",
                    "confidence": 0.92,
                    "rationale": "Matched local race result evidence.",
                    "evidence": [
                        {
                            "source_type": "local_db",
                            "title": "2021 Abu Dhabi Grand Prix",
                            "snippet": "Max Verstappen won the race.",
                        }
                    ],
                }
            ],
            "unsupported_claims": [],
            "meta": {"run_id": "run_test_text"},
        }

    monkeypatch.setattr(main.fact_check_client, "check_text", fake_check_text)

    identity = main.Identity(
        owner_type="guest",
        owner_id="guest-test",
        tier="guest",
        username="Guest",
        avatar_key="guest",
        is_authenticated=False,
    )
    payload = asyncio.run(
        main.check_session(
            main.CheckSessionRequest(
                input_type="text",
                text="Max Verstappen won the 2021 Abu Dhabi Grand Prix.",
            ),
            identity=identity,
        ),
    )
    assert payload["status"] == "completed"
    assert payload["input_type"] == "text"
    assert payload["overall_verdict"] == "SUPPORTS"
    assert payload["fact_check_result"]["claims"][0]["claim"]["claim_id"] == "c001"
    assert payload["fact_check_runs"][0]["claims"][0]["claim_text"].startswith("Max Verstappen")


def test_image_check_uses_fact_check_service_client(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_APP_DATA_DIR", str(tmp_path / "web_app"))
    monkeypatch.setenv("WEB_APP_SECRET_KEY", "dev-insecure-change-me")
    main = importlib.import_module("web_app.main")
    main = importlib.reload(main)
    captured: dict[str, object] = {}

    def fake_check_image(**kwargs):
        captured.update(kwargs)
        return {
            "text": "Lewis Hamilton won the 2021 Abu Dhabi Grand Prix.",
            "verdict": "REFUTES",
            "summary": "The claim conflicts with local race result evidence.",
            "claims": [],
            "unsupported_claims": [],
            "meta": {"run_id": "run_test_image"},
        }

    monkeypatch.setattr(main.fact_check_client, "check_image", fake_check_image)

    identity = main.Identity(
        owner_type="guest",
        owner_id="guest-test",
        tier="guest",
        username="Guest",
        avatar_key="guest",
        is_authenticated=False,
    )
    payload = asyncio.run(main.check_image_session(FakeUpload(), identity=identity))
    assert payload["status"] == "completed"
    assert payload["input_type"] == "image"
    assert payload["overall_verdict"] == "REFUTES"
    assert captured["filename"] == "claim.png"
    assert captured["content_type"] == "image/png"


def test_streamed_text_check_persists_done_result(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_APP_DATA_DIR", str(tmp_path / "web_app"))
    monkeypatch.setenv("WEB_APP_SECRET_KEY", "dev-insecure-change-me")
    main = importlib.import_module("web_app.main")
    main = importlib.reload(main)
    identity = main.Identity(
        owner_type="guest",
        owner_id="guest-test",
        tier="guest",
        username="Guest",
        avatar_key="guest",
        is_authenticated=False,
    )
    result = {
        "text": "Driver X said Y after the race.",
        "verdict": "SUPPORTS",
        "summary": "Evidence supports the claim.",
        "claims": [
            {
                "claim": {
                    "claim_id": "C1",
                    "text": "Driver X said Y after the race.",
                    "claim_type": "statement",
                    "verification_stream": "web",
                },
                "verdict": "SUPPORTS",
                "verification_stream": "web",
                "confidence": 0.8,
                "rationale": "Matched web evidence.",
                "evidence": [],
            }
        ],
        "unsupported_claims": [],
        "meta": {"run_id": "run_stream_text"},
    }

    main._create_or_update_fact_check_session(
        session_id="stream-session",
        identity=identity,
        input_type="text",
        preview="Driver X said Y after the race.",
        filename="Check: Driver X said Y",
        original_path="",
    )

    def backend_events():
        yield {"event": "claim_extraction_started", "data": {"stage": "claim_extraction", "status": "started"}}
        yield {"event": "gemma_token", "data": {"delta": "{\"verdict\"", "kind": "answer"}}
        yield {"event": "done", "data": {"result": result}}

    chunks = list(
        main._stream_session_events(
            session_id="stream-session",
            input_type="text",
            identity=identity,
            backend_events=backend_events,
        )
    )
    session = main.serialize_session_detail(
        main.store.get_session("stream-session", owner_type="guest", owner_id="guest-test")
    )

    assert any("event: gemma_token" in chunk for chunk in chunks)
    assert any("event: done" in chunk for chunk in chunks)
    assert session["status"] == "completed"
    assert session["fact_check_result"]["meta"]["run_id"] == "run_stream_text"


def test_recent_sessions_filters_to_fact_checks(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_APP_DATA_DIR", str(tmp_path / "web_app"))
    monkeypatch.setenv("WEB_APP_SECRET_KEY", "dev-insecure-change-me")
    main = importlib.import_module("web_app.main")
    main = importlib.reload(main)
    now = main.utc_now()
    main.store.create_session(
        session_id="legacy-chat",
        owner_type="guest",
        owner_id="guest-test",
        filename="legacy",
        content_type="application/x-legacy-session",
        original_path="",
        created_at=now,
        status="completed",
    )
    main.store.create_session(
        session_id="fact-check",
        owner_type="guest",
        owner_id="guest-test",
        filename="Check: Max won",
        content_type=main.FACT_CHECK_CONTENT_TYPE,
        original_path="",
        created_at=now,
        status="completed",
        input_type="text",
        input_preview="Max won",
    )
    identity = main.Identity(owner_type="guest", owner_id="guest-test", tier="guest")

    payload = asyncio.run(main.recent_sessions(identity=identity))

    assert [session["id"] for session in payload["sessions"]] == ["fact-check"]


def test_index_embeds_configurable_knowledge_source_label(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_APP_DATA_DIR", str(tmp_path / "web_app"))
    monkeypatch.setenv("WEB_APP_SECRET_KEY", "dev-insecure-change-me")
    monkeypatch.setenv("WEB_APP_KNOWLEDGE_SOURCE_LABEL", "Custom F1 knowledge source")
    main = importlib.import_module("web_app.main")
    main = importlib.reload(main)

    response = asyncio.run(main.index())
    body = response.body.decode("utf-8")

    assert '"knowledgeSourceLabel": "Custom F1 knowledge source"' in body
    assert "__F1_FACT_CHECK_CONFIG__" not in body


def test_static_ui_uses_truthful_wait_and_reveal_labels():
    app_js = (ROOT / "src" / "web_app" / "static" / "app.js").read_text(encoding="utf-8")

    assert "Waiting for fact-check result" in app_js
    assert "/sessions/check/stream" in app_js
    assert "/sessions/check-image/stream" in app_js
    assert "readSseResponse" in app_js
    assert "gemma_token" in app_js
    assert "revealCompletedChatMessages" not in app_js
    assert "Finalizing result" not in app_js
    assert "streamChatMessages" not in app_js


def test_legacy_ocr_and_chat_routes_are_removed(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_APP_DATA_DIR", str(tmp_path / "web_app"))
    monkeypatch.setenv("WEB_APP_SECRET_KEY", "dev-insecure-change-me")
    main = importlib.import_module("web_app.main")
    main = importlib.reload(main)
    route_paths = {route.path for route in main.app.routes}

    assert "/sessions/chat" not in route_paths
    assert "/sessions/upload" not in route_paths
    assert "/sessions/{session_id}/ask" not in route_paths
    assert "/sessions/{session_id}/ask/stream" not in route_paths
