import sqlite3
from pathlib import Path
from typing import Any

import pytest

from avo_harness.access import AccessRegistry, dump_manifest
from avo_harness.assistant import ChatStore
from avo_harness.auth import AuthStore


class TrackedConnection:
    def __init__(self, connection: sqlite3.Connection, connections: list["TrackedConnection"]):
        self.connection = connection
        self.closed = False
        connections.append(self)

    def __enter__(self) -> "TrackedConnection":
        self.connection.__enter__()
        return self

    def __exit__(self, *args: Any) -> Any:
        return self.connection.__exit__(*args)

    def close(self) -> None:
        self.closed = True
        self.connection.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.connection, name)


def track_connections(store: Any) -> list[TrackedConnection]:
    connections: list[TrackedConnection] = []
    connect = store._connect

    def tracked_connect() -> TrackedConnection:
        return TrackedConnection(connect(), connections)

    store._connect = tracked_connect
    return connections


def test_repeated_auth_session_operations_close_every_connection(tmp_path: Path) -> None:
    store = AuthStore(tmp_path / "state.sqlite3")
    connections = track_connections(store)

    for _ in range(50):
        session = store.issue_session()
        assert store.validate_session(session.token)
        store.revoke_session(session.token)

    assert connections
    assert all(connection.closed for connection in connections)


def test_chat_operations_close_every_connection(tmp_path: Path) -> None:
    store = ChatStore(tmp_path / "state.sqlite3")
    connections = track_connections(store)

    for index in range(50):
        message_id = store.add_message("main", "user", f"message {index}")
        store.update_message(
            message_id,
            content="done",
            kind="text",
            status="complete",
        )
    assert len(store.messages("main")) == 50

    assert connections
    assert all(connection.closed for connection in connections)


def test_repeated_access_operations_close_every_connection(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".avo").mkdir()
    manifest = {
        "version": 1,
        "repositories": {"app": {"path": ".", "access": "read"}},
        "secrets": {},
        "services": {},
        "tools": {},
        "network": {"allow": []},
    }
    (repo / ".avo" / "access.yaml").write_text(dump_manifest(manifest), encoding="utf-8")
    registry = AccessRegistry(repo, tmp_path / "state.sqlite3")
    connections = track_connections(registry)

    for _ in range(50):
        assert registry.status()["requires_approval"] is False
        assert registry.granted()["repositories"]["app"]["access"] == "read"

    assert connections
    assert all(connection.closed for connection in connections)


def test_connection_closes_when_transaction_rolls_back(tmp_path: Path) -> None:
    store = AuthStore(tmp_path / "state.sqlite3")
    connections = track_connections(store)
    store.add_credential(
        credential_id="AQID",
        public_key=b"key",
        sign_count=0,
        transports=[],
        device_type="single_device",
        backed_up=False,
    )

    with pytest.raises(sqlite3.IntegrityError):
        store.add_credential(
            credential_id="AQID",
            public_key=b"key",
            sign_count=0,
            transports=[],
            device_type="single_device",
            backed_up=False,
        )

    assert all(connection.closed for connection in connections)
