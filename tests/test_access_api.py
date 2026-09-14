import json
from pathlib import Path

from fastapi.testclient import TestClient

from avo_harness.api_chat import create_app
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


def configure(monkeypatch, tmp_path: Path, *, auth_disabled: bool) -> None:
    static = tmp_path / "static"
    static.mkdir(exist_ok=True)
    (static / "index.html").write_text("avo", encoding="utf-8")
    monkeypatch.setenv("AVO_PUBLIC_ORIGIN", "https://avo.example.com")
    monkeypatch.setenv("AVO_WEB_STATIC_DIR", str(static))
    if auth_disabled:
        monkeypatch.setenv("AVO_AUTH_DISABLED", "1")
    else:
        monkeypatch.delenv("AVO_AUTH_DISABLED", raising=False)


def test_access_api_is_session_protected(tmp_path: Path, monkeypatch) -> None:
    config = write_config(tmp_path)
    configure(monkeypatch, tmp_path, auth_disabled=False)
    client = TestClient(create_app(config))
    response = client.get("/api/access")
    assert response.status_code == 401


def test_production_increase_creates_step_up_approval(tmp_path: Path, monkeypatch) -> None:
    config = write_config(tmp_path)
    configure(monkeypatch, tmp_path, auth_disabled=False)
    client = TestClient(create_app(config))
    session = AuthStore(tmp_path / "state" / "state.sqlite3").issue_session()
    headers = {"Authorization": f"Bearer {session.token}"}

    candidate = """version: 1
repositories:
  primary:
    path: .
    access: write
secrets: {}
services: {}
tools: {}
network:
  allow: [github.com]
"""
    response = client.post("/api/access/apply", json={"yaml": candidate}, headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["applied"] is False
    assert payload["requires_passkey"] is True
    assert payload["approval_id"]
    assert not (tmp_path / ".avo" / "access.yaml").exists()

    # A pending privilege increase cannot be completed without an actual registered passkey.
    options = client.post(
        f"/api/access/approvals/{payload['approval_id']}/options",
        headers=headers,
    )
    assert options.status_code == 409
    assert "no passkeys" in options.json()["detail"]


def test_access_api_edits_repo_manifest_in_local_dev(tmp_path: Path, monkeypatch) -> None:
    config = write_config(tmp_path)
    configure(monkeypatch, tmp_path, auth_disabled=True)
    client = TestClient(create_app(config))

    initial = client.get("/api/access")
    assert initial.status_code == 200
    assert initial.json()["path"] == ".avo/access.yaml"

    text = """version: 1
repositories:
  app:
    path: .
    access: write
secrets:
  github:
    source: env:GITHUB_TOKEN
    expose_to: [coder]
services: {}
tools: {}
network:
  allow: [api.github.com]
"""
    preview = client.post("/api/access/preview", json={"yaml": text})
    assert preview.status_code == 200
    assert preview.json()["requires_approval"] is True

    # Explicit auth-disabled development mode also disables step-up approval.
    applied = client.post("/api/access/apply", json={"yaml": text})
    assert applied.status_code == 200
    assert applied.json()["applied"] is True
    manifest = tmp_path / ".avo" / "access.yaml"
    assert manifest.exists()

    status = client.get("/api/access").json()
    assert status["requires_approval"] is False
    assert status["effective"]["repositories"]["app"]["access"] == "write"
    assert status["effective"]["network"]["allow"] == ["api.github.com"]
