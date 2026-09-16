import json
from pathlib import Path

from fastapi.testclient import TestClient

from avo_harness.api import create_app as create_canonical_app
from avo_harness.api_chat import create_app


def write_config(tmp_path: Path) -> Path:
    path = tmp_path / "avo.json"
    path.write_text(
        json.dumps(
            {
                "repo": str(tmp_path),
                "state_dir": str(tmp_path / "state"),
                "worker": {"backend": "command", "command": ["echo", "ok"]},
                "evaluators": [{"name": "tests", "command": "true"}],
                "supervisor": {"enabled": False},
            }
        ),
        encoding="utf-8",
    )
    return path


def configure_env(monkeypatch, tmp_path: Path) -> None:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html><body>avo-shell</body></html>", encoding="utf-8")
    monkeypatch.setenv("AVO_PUBLIC_ORIGIN", "https://avo.example.com")
    monkeypatch.setenv("AVO_WEB_STATIC_DIR", str(static))
    monkeypatch.setenv("AVO_AUTH_DISABLED", "1")


def test_canonical_app_includes_chat_and_access_routes(tmp_path: Path, monkeypatch) -> None:
    config = write_config(tmp_path)
    configure_env(monkeypatch, tmp_path)
    client = TestClient(create_canonical_app(config))

    messages = client.get("/api/chat/messages")
    assert messages.status_code == 200
    assert messages.json() == []

    conversations = client.get("/api/chat/conversations")
    assert conversations.status_code == 200
    assert [item["id"] for item in conversations.json()] == ["main"]

    # Access may report manifest validation state, but it must be a registered
    # first-party API route rather than falling through to the SPA 404.
    access = client.get("/api/access")
    assert access.status_code != 404


def test_chat_routes_are_registered_before_spa_catchall(tmp_path: Path, monkeypatch) -> None:
    config = write_config(tmp_path)
    configure_env(monkeypatch, tmp_path)
    client = TestClient(create_app(config))

    response = client.get("/api/chat/messages")
    assert response.status_code == 200
    assert response.json() == []

    page = client.get("/some/client/route")
    assert page.status_code == 200
    assert "avo-shell" in page.text


def test_chat_message_validation_happens_before_worker_launch(tmp_path: Path, monkeypatch) -> None:
    config = write_config(tmp_path)
    configure_env(monkeypatch, tmp_path)
    client = TestClient(create_app(config))

    response = client.post("/api/chat/messages", json={"content": "   "})
    assert response.status_code == 400
    assert response.json()["detail"] == "content is required"


def test_chat_conversations_can_be_created_listed_and_selected(tmp_path: Path, monkeypatch) -> None:
    config = write_config(tmp_path)
    configure_env(monkeypatch, tmp_path)
    client = TestClient(create_app(config))

    initial = client.get("/api/chat/conversations")
    assert initial.status_code == 200
    assert [item["id"] for item in initial.json()] == ["main"]

    created = client.post("/api/chat/conversations", json={})
    assert created.status_code == 201
    conversation = created.json()
    assert conversation["id"] != "main"
    assert conversation["title"] == "New chat"
    assert conversation["message_count"] == 0

    selected = client.get("/api/chat/messages", params={"conversation_id": conversation["id"]})
    assert selected.status_code == 200
    assert selected.json() == []

    conversations = client.get("/api/chat/conversations")
    assert conversations.status_code == 200
    assert {item["id"] for item in conversations.json()} == {"main", conversation["id"]}
