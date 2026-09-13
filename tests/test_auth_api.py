import json
from pathlib import Path

from fastapi.testclient import TestClient

from avo_harness.api import create_app
from avo_harness.auth import AuthStore


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


def configure_env(monkeypatch, tmp_path: Path) -> Path:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html><body>avo-shell</body></html>", encoding="utf-8")
    monkeypatch.setenv("AVO_PUBLIC_ORIGIN", "https://avo.example.com")
    monkeypatch.setenv("AVO_WEB_STATIC_DIR", str(static))
    monkeypatch.setenv("AVO_APPLE_TEAM_ID", "TEAM123")
    monkeypatch.delenv("AVO_AUTH_DISABLED", raising=False)
    return static


def test_auth_status_and_protected_api_without_session(tmp_path: Path, monkeypatch) -> None:
    config = write_config(tmp_path)
    configure_env(monkeypatch, tmp_path)
    client = TestClient(create_app(config))

    status = client.get("/api/auth/status")
    assert status.status_code == 200
    assert status.json()["bootstrap_required"] is True
    assert status.json()["authenticated"] is False
    assert status.json()["rp_id"] == "avo.example.com"

    health = client.get("/api/health")
    assert health.status_code == 401


def test_bootstrap_options_accept_only_current_one_time_code(tmp_path: Path, monkeypatch) -> None:
    config = write_config(tmp_path)
    configure_env(monkeypatch, tmp_path)
    store = AuthStore(tmp_path / "state" / "state.sqlite3")
    code, _ = store.issue_bootstrap_code()

    client = TestClient(create_app(config))
    denied = client.post("/api/auth/bootstrap/options", json={"code": "BAD-CODE"})
    assert denied.status_code == 403

    allowed = client.post("/api/auth/bootstrap/options", json={"code": code})
    assert allowed.status_code == 200
    payload = allowed.json()
    assert payload["challenge_id"]
    assert payload["options"]["rp"]["id"] == "avo.example.com"


def test_same_host_spa_does_not_swallow_unknown_api_routes(tmp_path: Path, monkeypatch) -> None:
    config = write_config(tmp_path)
    configure_env(monkeypatch, tmp_path)
    monkeypatch.setenv("AVO_AUTH_DISABLED", "1")
    client = TestClient(create_app(config))

    page = client.get("/runs/some-client-route")
    assert page.status_code == 200
    assert "avo-shell" in page.text

    missing_api = client.get("/api/not-a-real-route")
    assert missing_api.status_code == 404
    assert "avo-shell" not in missing_api.text


def test_aasa_contains_native_app_identifier(tmp_path: Path, monkeypatch) -> None:
    config = write_config(tmp_path)
    configure_env(monkeypatch, tmp_path)
    client = TestClient(create_app(config))

    response = client.get("/.well-known/apple-app-site-association")
    assert response.status_code == 200
    assert response.json() == {
        "webcredentials": {"apps": ["TEAM123.com.kaitwalla.avocode"]}
    }
