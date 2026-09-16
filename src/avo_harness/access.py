from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import yaml


_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_ACCESS = {"read", "write"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _clean_roles(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"{label} must be a list of role names")
    return sorted(dict.fromkeys(item.strip() for item in value))


def _named_mapping(value: Any, label: str) -> dict[str, dict[str, Any]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    result: dict[str, dict[str, Any]] = {}
    for raw_name, raw_config in value.items():
        name = str(raw_name)
        if not _NAME.fullmatch(name):
            raise ValueError(f"invalid {label} name: {name!r}")
        if not isinstance(raw_config, dict):
            raise ValueError(f"{label}.{name} must be a mapping")
        result[name] = dict(raw_config)
    return result


def parse_manifest_text(text: str) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(text) if text.strip() else {}
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML: {exc}") from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("capability manifest must be a YAML mapping")
    unknown_top = set(raw) - {"version", "repositories", "secrets", "services", "tools", "network"}
    if unknown_top:
        raise ValueError(f"unknown manifest keys: {', '.join(sorted(map(str, unknown_top)))}")
    version = raw.get("version", 1)
    if version != 1:
        raise ValueError("capability manifest version must be 1")

    repositories: dict[str, Any] = {}
    for name, item in _named_mapping(raw.get("repositories"), "repositories").items():
        unknown = set(item) - {"path", "access"}
        if unknown:
            raise ValueError(f"repositories.{name} has unknown keys: {', '.join(sorted(unknown))}")
        path = item.get("path")
        access = item.get("access", "read")
        if not isinstance(path, str) or not path.strip():
            raise ValueError(f"repositories.{name}.path is required")
        if access not in _ACCESS:
            raise ValueError(f"repositories.{name}.access must be read or write")
        repositories[name] = {"path": path.strip(), "access": access}

    secrets: dict[str, Any] = {}
    for name, item in _named_mapping(raw.get("secrets"), "secrets").items():
        unknown = set(item) - {"source", "expose_to"}
        if unknown:
            raise ValueError(f"secrets.{name} has unknown keys: {', '.join(sorted(unknown))}")
        source = item.get("source")
        if not isinstance(source, str) or not source.strip():
            raise ValueError(f"secrets.{name}.source is required")
        source = source.strip()
        if not (source.startswith("env:") or source.startswith("file:")):
            raise ValueError(
                f"secrets.{name}.source must be an env:NAME or file:/path reference; secret values do not belong in the manifest"
            )
        if source.startswith("env:") and not source[4:].strip():
            raise ValueError(f"secrets.{name}.source has an empty environment variable name")
        if source.startswith("file:") and not source[5:].strip():
            raise ValueError(f"secrets.{name}.source has an empty file path")
        secrets[name] = {"source": source, "expose_to": _clean_roles(item.get("expose_to"), f"secrets.{name}.expose_to")}

    services: dict[str, Any] = {}
    for name, item in _named_mapping(raw.get("services"), "services").items():
        unknown = set(item) - {"url", "access"}
        if unknown:
            raise ValueError(f"services.{name} has unknown keys: {', '.join(sorted(unknown))}")
        url = item.get("url")
        access = item.get("access", "read")
        if not isinstance(url, str) or not url.strip():
            raise ValueError(f"services.{name}.url is required")
        if access not in _ACCESS:
            raise ValueError(f"services.{name}.access must be read or write")
        services[name] = {"url": url.strip(), "access": access}

    tools: dict[str, Any] = {}
    for name, item in _named_mapping(raw.get("tools"), "tools").items():
        unknown = set(item) - {"enabled", "expose_to"}
        if unknown:
            raise ValueError(f"tools.{name} has unknown keys: {', '.join(sorted(unknown))}")
        enabled = item.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(f"tools.{name}.enabled must be true or false")
        tools[name] = {"enabled": enabled, "expose_to": _clean_roles(item.get("expose_to"), f"tools.{name}.expose_to")}

    network_raw = raw.get("network") or {}
    if not isinstance(network_raw, dict):
        raise ValueError("network must be a mapping")
    unknown_network = set(network_raw) - {"allow"}
    if unknown_network:
        raise ValueError(f"network has unknown keys: {', '.join(sorted(unknown_network))}")
    allow = network_raw.get("allow") or []
    if not isinstance(allow, list) or not all(isinstance(item, str) and item.strip() for item in allow):
        raise ValueError("network.allow must be a list of hosts")

    return {
        "version": 1,
        "repositories": repositories,
        "secrets": secrets,
        "services": services,
        "tools": tools,
        "network": {"allow": sorted(dict.fromkeys(item.strip().lower() for item in allow))},
    }


def dump_manifest(manifest: dict[str, Any]) -> str:
    return yaml.safe_dump(manifest, sort_keys=False, default_flow_style=False, allow_unicode=True)


def default_manifest() -> dict[str, Any]:
    return {
        "version": 1,
        "repositories": {"primary": {"path": ".", "access": "write"}},
        "secrets": {},
        "services": {},
        "tools": {},
        "network": {"allow": []},
    }


def _level(value: str) -> int:
    return 2 if value == "write" else 1


def capability_changes(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []

    for category in ("repositories", "secrets", "services", "tools"):
        old_items = before.get(category, {})
        new_items = after.get(category, {})
        for name in sorted(set(old_items) | set(new_items)):
            old = old_items.get(name)
            new = new_items.get(name)
            if old == new:
                continue
            increase = False
            change = "changed"
            if old is None:
                change = "added"
                if category != "tools" or bool(new.get("enabled", True)):
                    increase = True
            elif new is None:
                change = "removed"
            elif category == "repositories":
                increase = old.get("path") != new.get("path") or _level(new.get("access", "read")) > _level(old.get("access", "read"))
            elif category == "services":
                increase = old.get("url") != new.get("url") or _level(new.get("access", "read")) > _level(old.get("access", "read"))
            elif category == "secrets":
                increase = old.get("source") != new.get("source") or bool(set(new.get("expose_to", [])) - set(old.get("expose_to", [])))
            elif category == "tools":
                increase = (not bool(old.get("enabled")) and bool(new.get("enabled"))) or bool(
                    set(new.get("expose_to", [])) - set(old.get("expose_to", []))
                )
            changes.append({"category": category, "name": name, "change": change, "increase": increase, "before": old, "after": new})

    old_hosts = set(before.get("network", {}).get("allow", []))
    new_hosts = set(after.get("network", {}).get("allow", []))
    for host in sorted(old_hosts | new_hosts):
        if host in old_hosts and host in new_hosts:
            continue
        changes.append(
            {
                "category": "network",
                "name": host,
                "change": "added" if host in new_hosts else "removed",
                "increase": host in new_hosts and host not in old_hosts,
                "before": host if host in old_hosts else None,
                "after": host if host in new_hosts else None,
            }
        )
    return changes


def effective_manifest(granted: dict[str, Any], requested: dict[str, Any]) -> dict[str, Any]:
    result = default_manifest()
    result["repositories"] = {}
    result["secrets"] = {}
    result["services"] = {}
    result["tools"] = {}

    for name, request in requested.get("repositories", {}).items():
        grant = granted.get("repositories", {}).get(name)
        if not grant or grant.get("path") != request.get("path"):
            continue
        access = "read" if "read" in {grant.get("access"), request.get("access")} else "write"
        result["repositories"][name] = {"path": request["path"], "access": access}

    for name, request in requested.get("secrets", {}).items():
        grant = granted.get("secrets", {}).get(name)
        if not grant or grant.get("source") != request.get("source"):
            continue
        roles = sorted(set(grant.get("expose_to", [])) & set(request.get("expose_to", [])))
        result["secrets"][name] = {"source": request["source"], "expose_to": roles}

    for name, request in requested.get("services", {}).items():
        grant = granted.get("services", {}).get(name)
        if not grant or grant.get("url") != request.get("url"):
            continue
        access = "read" if "read" in {grant.get("access"), request.get("access")} else "write"
        result["services"][name] = {"url": request["url"], "access": access}

    for name, request in requested.get("tools", {}).items():
        grant = granted.get("tools", {}).get(name)
        if not grant:
            continue
        enabled = bool(grant.get("enabled")) and bool(request.get("enabled"))
        roles = sorted(set(grant.get("expose_to", [])) & set(request.get("expose_to", [])))
        result["tools"][name] = {"enabled": enabled, "expose_to": roles}

    result["network"] = {
        "allow": sorted(set(granted.get("network", {}).get("allow", [])) & set(requested.get("network", {}).get("allow", [])))
    }
    return result


def _secret_configured(source: str) -> bool:
    if source.startswith("env:"):
        return bool(os.environ.get(source[4:]))
    if source.startswith("file:"):
        return Path(source[5:]).expanduser().exists()
    return False


class AccessRegistry:
    def __init__(self, repo_root: Path, db_path: Path):
        self.repo_root = repo_root.resolve()
        self.manifest_path = self.repo_root / ".avo" / "access.yaml"
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        self._ensure_initial_grant()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=10.0)
        db.row_factory = sqlite3.Row
        return db

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        db = self._connect()
        try:
            with db:
                yield db
        finally:
            db.close()

    def _init_schema(self) -> None:
        with self._transaction() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS access_grant (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    manifest_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS access_approvals (
                    id TEXT PRIMARY KEY,
                    manifest_yaml TEXT NOT NULL,
                    changes_json TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    applied_at TEXT
                );
                """
            )

    def requested(self) -> dict[str, Any]:
        if not self.manifest_path.exists():
            return default_manifest()
        return parse_manifest_text(self.manifest_path.read_text(encoding="utf-8"))

    def requested_text(self) -> str:
        if self.manifest_path.exists():
            return self.manifest_path.read_text(encoding="utf-8")
        return dump_manifest(default_manifest())

    def granted(self) -> dict[str, Any]:
        with self._transaction() as db:
            row = db.execute("SELECT manifest_json FROM access_grant WHERE id=1").fetchone()
        if row is None:
            return default_manifest()
        value = json.loads(str(row["manifest_json"]))
        return parse_manifest_text(dump_manifest(value))

    def _set_granted(self, manifest: dict[str, Any]) -> None:
        with self._transaction() as db:
            db.execute(
                """INSERT INTO access_grant(id, manifest_json, updated_at) VALUES(1, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET manifest_json=excluded.manifest_json, updated_at=excluded.updated_at""",
                (_json(manifest), _iso(_now())),
            )

    def _ensure_initial_grant(self) -> None:
        with self._transaction() as db:
            row = db.execute("SELECT 1 FROM access_grant WHERE id=1").fetchone()
        if row is None:
            self._set_granted(self.requested())

    def effective(self) -> dict[str, Any]:
        return effective_manifest(self.granted(), self.requested())

    def changes(self) -> list[dict[str, Any]]:
        return capability_changes(self.granted(), self.requested())

    def status(self) -> dict[str, Any]:
        requested = self.requested()
        granted = self.granted()
        effective = effective_manifest(granted, requested)
        changes = capability_changes(granted, requested)
        secret_status = {
            name: {"source": item["source"], "configured": _secret_configured(item["source"])}
            for name, item in requested.get("secrets", {}).items()
        }
        return {
            "path": str(self.manifest_path.relative_to(self.repo_root)),
            "yaml": self.requested_text(),
            "requested": requested,
            "effective": effective,
            "secret_status": secret_status,
            "changes": changes,
            "requires_approval": any(bool(item["increase"]) for item in changes),
        }

    def preview(self, text: str) -> dict[str, Any]:
        candidate = parse_manifest_text(text)
        baseline = self.effective()
        changes = capability_changes(baseline, candidate)
        return {
            "manifest": candidate,
            "changes": changes,
            "requires_approval": any(bool(item["increase"]) for item in changes),
        }

    def _write(self, text: str, manifest: dict[str, Any]) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        normalized = dump_manifest(manifest)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.manifest_path.parent, delete=False
        ) as handle:
            handle.write(normalized)
            temp = Path(handle.name)
        temp.replace(self.manifest_path)
        self._set_granted(manifest)

    def apply(self, text: str, *, allow_increase: bool = False) -> dict[str, Any]:
        candidate = parse_manifest_text(text)
        changes = capability_changes(self.effective(), candidate)
        increases = [item for item in changes if item["increase"]]
        if increases and not allow_increase:
            approval_id = uuid.uuid4().hex
            with self._transaction() as db:
                db.execute(
                    "INSERT INTO access_approvals(id, manifest_yaml, changes_json, expires_at, applied_at) VALUES(?, ?, ?, ?, NULL)",
                    (approval_id, dump_manifest(candidate), _json(changes), _iso(_now() + timedelta(minutes=5))),
                )
            return {
                "applied": False,
                "requires_passkey": True,
                "approval_id": approval_id,
                "changes": changes,
            }
        self._write(text, candidate)
        return {"applied": True, "requires_passkey": False, "changes": changes, "status": self.status()}

    def pending_approval(self, approval_id: str) -> sqlite3.Row:
        with self._transaction() as db:
            row = db.execute("SELECT * FROM access_approvals WHERE id=?", (approval_id,)).fetchone()
        if row is None or row["applied_at"] is not None:
            raise ValueError("access approval is invalid or already used")
        if _parse_time(str(row["expires_at"])) <= _now():
            raise ValueError("access approval expired")
        return row

    def apply_approval(self, approval_id: str) -> dict[str, Any]:
        row = self.pending_approval(approval_id)
        manifest = parse_manifest_text(str(row["manifest_yaml"]))
        self._write(str(row["manifest_yaml"]), manifest)
        with self._transaction() as db:
            db.execute("UPDATE access_approvals SET applied_at=? WHERE id=?", (_iso(_now()), approval_id))
        return self.status()

    def prompt_context(self) -> str:
        effective = self.effective()
        safe = {
            "repositories": effective.get("repositories", {}),
            "secrets": {
                name: {"source": item["source"], "expose_to": item.get("expose_to", []), "configured": _secret_configured(item["source"])}
                for name, item in effective.get("secrets", {}).items()
            },
            "services": effective.get("services", {}),
            "tools": effective.get("tools", {}),
            "network": effective.get("network", {"allow": []}),
        }
        return json.dumps(safe, indent=2, sort_keys=True)
