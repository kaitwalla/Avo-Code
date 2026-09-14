from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from .assistant import AssistantService
from .auth import AuthStore
from .config import AVOConfig

SESSION_COOKIE = "avo_session"


def register_chat_routes(app: Any, *, config: AVOConfig, config_file: Path) -> AssistantService:
    from fastapi import Body, Cookie, Depends, Header, HTTPException, Query

    service = AssistantService(config, config_file)
    auth_store = AuthStore(config.state_path / "state.sqlite3")
    auth_disabled = os.environ.get("AVO_AUTH_DISABLED", "").lower() in {"1", "true", "yes"}

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
        db = sqlite3.connect(path)
        db.row_factory = sqlite3.Row
        try:
            row = db.execute(
                """SELECT id, objective, repo_path, best_score, status, created_at, updated_at
                   FROM runs WHERE id=?""",
                (run_id,),
            ).fetchone()
        finally:
            db.close()
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
        auto_execute = payload.get("auto_execute", True)
        if not isinstance(auto_execute, bool):
            raise HTTPException(status_code=400, detail="auto_execute must be a boolean")
        result = service.submit(
            content.strip(),
            conversation_id=conversation_id.strip()[:100],
            auto_execute=auto_execute,
        )
        return {"accepted": True, **result}

    return service
