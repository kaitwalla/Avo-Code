from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .assistant import AssistantService
from .api import _transaction
from .auth import AuthStore
from .config import AVOConfig

SESSION_COOKIE = "avo_session"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def register_chat_routes(app: Any, *, config: AVOConfig, config_file: Path) -> AssistantService:
    from fastapi import Body, Cookie, Depends, Header, HTTPException, Query

    service = AssistantService(config, config_file)
    auth_store = AuthStore(config.state_path / "state.sqlite3")
    auth_disabled = os.environ.get("AVO_AUTH_DISABLED", "").lower() in {"1", "true", "yes"}
    service.store.ensure_conversation("main")

    def raw_session(
        authorization: str | None = Header(default=None),
        avo_session: str | None = Cookie(default=None),
    ) -> str | None:
        if authorization and authorization.lower().startswith("bearer "):
            return authorization[7:].strip()
        return avo_session

    def authorize(token: str | None = Depends(raw_session)) -> str:
        if auth_disabled:
            return "dev"
        if not auth_store.validate_session(token):
            raise HTTPException(status_code=401, detail="passkey authentication required")
        return token or ""

    def run_summary(run_id: str) -> dict[str, Any] | None:
        path = config.state_path / "state.sqlite3"
        if not path.exists():
            return None
        with _transaction(path) as db:
            row = db.execute(
                """SELECT id, objective, repo_path, best_score, status, created_at, updated_at
                   FROM runs WHERE id=?""",
                (run_id,),
            ).fetchone()
        return dict(row) if row else None

    def enrich(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for message in messages:
            run_id = message.get("run_id")
            if not run_id:
                continue
            run = run_summary(str(run_id))
            if run is not None:
                message["run"] = run
        return messages

    def conversation_rows() -> list[dict[str, Any]]:
        with _transaction(config.state_path / "state.sqlite3") as db:
            rows = db.execute(
                """SELECT c.id, c.title, c.created_at, c.updated_at, COUNT(m.id) AS message_count
                   FROM chat_conversations c
                   LEFT JOIN chat_messages m ON m.conversation_id = c.id
                   GROUP BY c.id, c.title, c.created_at, c.updated_at
                   ORDER BY c.updated_at DESC"""
            ).fetchall()
        return [dict(row) for row in rows]

    @app.get("/api/chat/conversations")
    def chat_conversations(
        _: str = Depends(authorize),
    ) -> list[dict[str, Any]]:
        return conversation_rows()

    @app.post("/api/chat/conversations", status_code=201)
    def create_chat_conversation(
        payload: dict[str, Any] | None = Body(default=None),
        _: str = Depends(authorize),
    ) -> dict[str, Any]:
        title = "New chat"
        if payload and "title" in payload:
            requested = payload.get("title")
            if not isinstance(requested, str) or not requested.strip():
                raise HTTPException(status_code=400, detail="title must be a non-empty string")
            title = requested.strip()[:100]
        conversation_id = uuid.uuid4().hex
        now = _now()
        with _transaction(config.state_path / "state.sqlite3") as db:
            db.execute(
                """INSERT INTO chat_conversations (id, title, created_at, updated_at)
                   VALUES (?, ?, ?, ?)""",
                (conversation_id, title, now, now),
            )
        return {
            "id": conversation_id,
            "title": title,
            "created_at": now,
            "updated_at": now,
            "message_count": 0,
        }

    @app.get("/api/chat/messages")
    def chat_messages(
        conversation_id: str = Query(default="main", min_length=1, max_length=100),
        _: str = Depends(authorize),
    ) -> list[dict[str, Any]]:
        return enrich(service.messages(conversation_id))

    @app.post("/api/chat/messages", status_code=202)
    def send_chat_message(
        payload: dict[str, Any] = Body(...),
        _: str = Depends(authorize),
    ) -> dict[str, Any]:
        content = payload.get("content")
        if not isinstance(content, str) or not content.strip():
            raise HTTPException(status_code=400, detail="content is required")
        conversation_id = payload.get("conversation_id") or "main"
        if not isinstance(conversation_id, str) or not conversation_id.strip():
            raise HTTPException(status_code=400, detail="conversation_id must be a string")
        conversation_id = conversation_id.strip()[:100]
        auto_execute = payload.get("auto_execute", True)
        if not isinstance(auto_execute, bool):
            raise HTTPException(status_code=400, detail="auto_execute must be a boolean")
        result = service.submit(
            content.strip(),
            conversation_id=conversation_id,
            auto_execute=auto_execute,
        )

        # Give a newly-created thread a useful label after its first user message.
        # Existing/default conversations retain their title once they have history.
        with _transaction(config.state_path / "state.sqlite3") as db:
            row = db.execute(
                """SELECT c.title,
                          SUM(CASE WHEN m.role = 'user' THEN 1 ELSE 0 END) AS user_messages
                   FROM chat_conversations c
                   LEFT JOIN chat_messages m ON m.conversation_id = c.id
                   WHERE c.id=?
                   GROUP BY c.id, c.title""",
                (conversation_id,),
            ).fetchone()
            if row and int(row["user_messages"] or 0) == 1 and row["title"] in {"New chat", "Avo"}:
                first_line = content.strip().splitlines()[0].strip()
                title = first_line[:72] or "New chat"
                db.execute(
                    "UPDATE chat_conversations SET title=?, updated_at=? WHERE id=?",
                    (title, _now(), conversation_id),
                )

        return {"accepted": True, "conversation_id": conversation_id, **result}

    return service
