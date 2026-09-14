import os
from pathlib import Path

import pytest

from avo_harness.access import AccessRegistry, capability_changes, dump_manifest, parse_manifest_text


def manifest(*, repo_access: str = "read", secret: bool = False, hosts: list[str] | None = None):
    value = {
        "version": 1,
        "repositories": {"app": {"path": ".", "access": repo_access}},
        "secrets": {},
        "services": {},
        "tools": {},
        "network": {"allow": hosts or []},
    }
    if secret:
        value["secrets"] = {
            "github": {"source": "env:GITHUB_TOKEN", "expose_to": ["coder"]}
        }
    return value


def write_manifest(repo: Path, value: dict) -> Path:
    path = repo / ".avo" / "access.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_manifest(value), encoding="utf-8")
    return path


def test_literal_secret_values_are_rejected() -> None:
    with pytest.raises(ValueError, match="secret values do not belong"):
        parse_manifest_text(
            """
version: 1
secrets:
  github:
    source: ghp_this_is_not_a_reference
"""
        )


def test_privilege_increase_from_direct_repo_edit_is_not_effective(tmp_path: Path) -> None:
    write_manifest(tmp_path, manifest(repo_access="read"))
    registry = AccessRegistry(tmp_path, tmp_path / "state.sqlite3")
    assert registry.effective()["repositories"]["app"]["access"] == "read"

    write_manifest(tmp_path, manifest(repo_access="write", secret=True, hosts=["api.github.com"]))
    status = registry.status()

    assert status["requires_approval"] is True
    assert status["effective"]["repositories"]["app"]["access"] == "read"
    assert "github" not in status["effective"]["secrets"]
    assert status["effective"]["network"]["allow"] == []
    assert any(change["increase"] for change in status["changes"])


def test_reductions_take_effect_immediately(tmp_path: Path) -> None:
    write_manifest(tmp_path, manifest(repo_access="write", hosts=["api.github.com"]))
    registry = AccessRegistry(tmp_path, tmp_path / "state.sqlite3")

    write_manifest(tmp_path, manifest(repo_access="read", hosts=[]))
    status = registry.status()

    assert status["requires_approval"] is False
    assert status["effective"]["repositories"]["app"]["access"] == "read"
    assert status["effective"]["network"]["allow"] == []


def test_increase_requires_pending_approval_and_applies_exact_manifest(tmp_path: Path) -> None:
    path = write_manifest(tmp_path, manifest(repo_access="read"))
    registry = AccessRegistry(tmp_path, tmp_path / "state.sqlite3")
    candidate = dump_manifest(manifest(repo_access="write", secret=True))

    result = registry.apply(candidate)
    assert result["applied"] is False
    assert result["requires_passkey"] is True
    assert result["approval_id"]
    assert parse_manifest_text(path.read_text(encoding="utf-8"))["repositories"]["app"]["access"] == "read"

    status = registry.apply_approval(result["approval_id"])
    assert status["requires_approval"] is False
    assert status["effective"]["repositories"]["app"]["access"] == "write"
    assert status["effective"]["secrets"]["github"]["source"] == "env:GITHUB_TOKEN"


def test_secret_status_never_contains_secret_value(tmp_path: Path, monkeypatch) -> None:
    write_manifest(tmp_path, manifest(secret=True))
    monkeypatch.setenv("GITHUB_TOKEN", "super-secret-value")
    registry = AccessRegistry(tmp_path, tmp_path / "state.sqlite3")

    status = registry.status()
    serialized = str(status)
    assert status["secret_status"]["github"]["configured"] is True
    assert "super-secret-value" not in serialized
    assert "super-secret-value" not in registry.prompt_context()


def test_changes_classify_additions_as_increases() -> None:
    before = manifest(repo_access="read")
    after = manifest(repo_access="write", secret=True, hosts=["github.com"])
    changes = capability_changes(before, after)
    increased = {(item["category"], item["name"]) for item in changes if item["increase"]}
    assert ("repositories", "app") in increased
    assert ("secrets", "github") in increased
    assert ("network", "github.com") in increased
