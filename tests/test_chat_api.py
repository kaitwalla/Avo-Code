import json
from pathlib import Path

from fastapi.testclient import TestClient

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
