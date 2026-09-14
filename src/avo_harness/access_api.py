from __future__ import annotations

import os
from typing import Any

from .access import AccessRegistry
from .api import SESSION_COOKIE, _public_origin, _rp_id
from .auth import AuthStore, PasskeyAuth
from .config import AVOConfig


def register_access_routes(app: Any, *, config: AVOConfig) -> AccessRegistry:
    from fastapi import Body, Cookie, Depends, Header, HTTPException

    db_path = config.state_path / "state.sqlite3"
    auth_store = AuthStore(db_path)
    origin = _public_origin()
    passkeys = PasskeyAuth(auth_store, rp_id=_rp_id(origin), origin=origin)
    auth_disabled = os.environ.get("AVO_AUTH_DISABLED", "").lower() in {"1", "true", "yes"}
    registry = AccessRegistry(config.repo_path, db_path)

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
