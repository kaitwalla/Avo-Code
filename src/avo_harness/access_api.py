from __future__ import annotations

from typing import Any, Callable

from .access import AccessRegistry
from .auth import PasskeyAuth
from .config import AVOConfig


def register_access_routes(
    app: Any,
    *,
    config: AVOConfig,
    authorize: Callable[..., str],
    passkeys: PasskeyAuth,
    auth_disabled: bool = False,
) -> AccessRegistry:
    from fastapi import Body, Depends, HTTPException

    registry = AccessRegistry(config.repo_path, config.state_path / "state.sqlite3")

    def text(payload: dict[str, Any]) -> str:
        value = payload.get("yaml")
        if not isinstance(value, str):
            raise HTTPException(status_code=400, detail="yaml is required")
        return value

    @app.get("/api/access")
    def access_status(_: str = Depends(authorize)) -> dict[str, Any]:
        try:
            return registry.status()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/access/preview")
    def preview_access(
        payload: dict[str, Any] = Body(...),
        _: str = Depends(authorize),
    ) -> dict[str, Any]:
        try:
            return registry.preview(text(payload))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/access/apply")
    def apply_access(
        payload: dict[str, Any] = Body(...),
        _: str = Depends(authorize),
    ) -> dict[str, Any]:
        try:
            return registry.apply(text(payload), allow_increase=auth_disabled)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/access/approvals/{approval_id}/options")
    def approval_options(
        approval_id: str,
        _: str = Depends(authorize),
    ) -> dict[str, Any]:
        try:
            registry.pending_approval(approval_id)
            return passkeys.authentication_options()
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/access/approvals/{approval_id}/verify")
    def approval_verify(
        approval_id: str,
        payload: dict[str, Any] = Body(...),
        _: str = Depends(authorize),
    ) -> dict[str, Any]:
        challenge_id = payload.get("challenge_id")
        credential = payload.get("credential")
        if not isinstance(challenge_id, str) or not challenge_id.strip():
            raise HTTPException(status_code=400, detail="challenge_id is required")
        if not isinstance(credential, dict):
            raise HTTPException(status_code=400, detail="credential is required")
        try:
            registry.pending_approval(approval_id)
            passkeys.verify_authentication(challenge_id.strip(), credential)
            return {"ok": True, "status": registry.apply_approval(approval_id)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return registry
