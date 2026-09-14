from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .assistant import AssistantService
from .config import AVOConfig


def register_chat_routes(
    app: Any,
    *,
    config: AVOConfig,
    config_file: Path,
    authorize: Callable[..., str],
    snapshot: Callable[[str], dict[str, Any] | None],
) -> AssistantService:
    from fastapi import Body, Depends, HTTPException, Query

    service = AssistantService(config, config_file)

    def enrich(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for message in messages:
            run_id = message.get("run_id")
            if not run_id:
                continue
            run = snapshot(str(run_id))
            if run is not None:
                message["run"] = {
                    "id": run["id"],
                    "objective": run["objective"],
                    "repo_path": run["repo_path"],
                    "best_score": run["best_score"],
                    "status": run["status"],
                    "created_at": run["created_at"],
                    "updated_at": run["updated_at"],
                }
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
