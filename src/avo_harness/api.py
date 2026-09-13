from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .auth import AuthStore, PasskeyAuth
from .config import AVOConfig

SESSION_COOKIE = "avo_session"
SESSION_MAX_AGE = 30 * 24 * 60 * 60


def _connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    return db


def _json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _policy_variant(policy: dict[str, Any]) -> str | None:
    default = policy.get("default")
    if isinstance(default, dict) and default.get("variant"):
        return str(default["variant"])
    return None


def _benchmark_entries(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    entries: list[dict[str, Any]] = []
    for report_path in root.rglob("report.json"):
        report = _read_json(report_path)
        if not report:
            continue
        folder = report_path.parent
        try:
            benchmark_id = folder.relative_to(root).as_posix() or "."
        except ValueError:
            continue
        policy = _read_json(folder / "routing-policy.json")
        if not policy:
            embedded = report.get("routing_policy")
            policy = embedded if isinstance(embedded, dict) else {}
        stat = report_path.stat()
        variants = report.get("variants", {})
        trials = report.get("trials", [])
        entries.append(
            {
                "id": benchmark_id,
                "experiment": str(report.get("experiment") or folder.name),
                "updated_at": stat.st_mtime,
                "variant_count": len(variants) if isinstance(variants, dict) else 0,
                "trial_count": len(trials) if isinstance(trials, list) else 0,
                "default_strategy": _policy_variant(policy),
            }
        )
    return sorted(entries, key=lambda item: float(item["updated_at"]), reverse=True)


def _benchmark_detail(root: Path, benchmark_id: str) -> dict[str, Any] | None:
    candidate = (root / benchmark_id).resolve()
    resolved_root = root.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        return None
    report = _read_json(candidate / "report.json")
    if not report:
        return None
    policy = _read_json(candidate / "routing-policy.json")
    if not policy:
        embedded = report.get("routing_policy")
        policy = embedded if isinstance(embedded, dict) else {}
    return {"id": benchmark_id, "report": report, "routing_policy": policy}


def _public_origin() -> str:
    return os.environ.get("AVO_PUBLIC_ORIGIN", "https://avo.penginlab.com").rstrip("/")


def _rp_id(origin: str) -> str:
    configured = os.environ.get("AVO_RP_ID", "").strip()
    if configured:
        return configured
    hostname = urlparse(origin).hostname
    if not hostname:
        raise ValueError("AVO_PUBLIC_ORIGIN must contain a hostname")
    return hostname


def _static_root() -> Path:
    default = Path(__file__).resolve().parents[2] / "ui" / "dist"
    return Path(os.environ.get("AVO_WEB_STATIC_DIR", str(default))).expanduser().resolve()


def create_app(config_path: str = "avo.json"):
    try:
        from fastapi import (
            Body,
            Cookie,
            Depends,
            FastAPI,
            Header,
            HTTPException,
            Query,
            Response,
            WebSocket,
            WebSocketDisconnect,
        )
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import FileResponse, JSONResponse
    except ImportError as exc:
        raise RuntimeError("Web UI dependencies are missing; install avo-harness[web]") from exc

    config_file = Path(config_path).expanduser().resolve()
    config = AVOConfig.load(config_file)
    db_path = config.state_path / "state.sqlite3"
    benchmark_root = Path(
        os.environ.get("AVO_BENCHMARK_ROOT", str(config_file.parent / "benchmarks"))
    ).expanduser().resolve()
    origin = _public_origin()
    rp_id = _rp_id(origin)
    static_root = _static_root()
    apple_team_id = os.environ.get("AVO_APPLE_TEAM_ID", "").strip()
    apple_bundle_id = os.environ.get("AVO_IOS_BUNDLE_ID", "com.kaitwalla.avocode").strip()
    auth_disabled = os.environ.get("AVO_AUTH_DISABLED", "").lower() in {"1", "true", "yes"}
    auth_store = AuthStore(db_path)
    passkeys = PasskeyAuth(auth_store, rp_id=rp_id, origin=origin)

    app = FastAPI(title="Avo-Code API", version="1")

    origins = [
        value.strip()
        for value in os.environ.get("AVO_WEB_ORIGINS", "").split(",")
        if value.strip()
    ]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Avo-Client"],
        )

    def rows(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        if not db_path.exists():
            return []
        db = _connect(db_path)
        try:
            return [dict(row) for row in db.execute(query, params).fetchall()]
        finally:
            db.close()

    def snapshot(run_id: str) -> dict[str, Any] | None:
        found = rows("SELECT * FROM runs WHERE id=?", (run_id,))
        if not found:
            return None
        run = found[0]
        candidates = rows(
            "SELECT id, iteration, commit_sha, score, improved, worker_success, created_at "
            "FROM candidates WHERE run_id=? ORDER BY iteration", (run_id,)
        )
        invocations = rows(
            "SELECT iteration, role, execution_class, backend, success, duration_seconds, "
            "input_tokens, output_tokens, cost_usd, created_at FROM invocations "
            "WHERE run_id=? ORDER BY id", (run_id,)
        )
        role_runs = rows(
            "SELECT rr.sequence, rr.role, rr.reason, rr.success, rr.duration_ms, rr.output, rr.error, "
            "rr.metadata_json, rr.created_at, c.iteration FROM role_runs rr "
            "JOIN candidates c ON c.id=rr.candidate_id WHERE c.run_id=? ORDER BY rr.id", (run_id,)
        )
        for item in role_runs:
            item["metadata"] = _json(item.pop("metadata_json", "{}"), {})
        evaluations = rows(
            "SELECT c.iteration, e.name, e.score, e.passed, e.summary FROM evaluations e "
            "JOIN candidates c ON c.id=e.candidate_id WHERE c.run_id=? ORDER BY e.id", (run_id,)
        )
        metadata_rows = rows("SELECT key, value FROM run_metadata WHERE run_id=?", (run_id,))
        metadata = {item["key"]: _json(item["value"], item["value"]) for item in metadata_rows}
        return {
            **run,
            "candidates": candidates,
            "invocations": invocations,
            "role_runs": role_runs,
            "evaluations": evaluations,
            "metadata": metadata,
        }

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

    def issue_session(response: Response, native: bool) -> dict[str, Any]:
        session = auth_store.issue_session()
        response.set_cookie(
            SESSION_COOKIE,
            session.token,
            max_age=SESSION_MAX_AGE,
            httponly=True,
            secure=origin.startswith("https://"),
            samesite="strict",
            path="/",
        )
        payload: dict[str, Any] = {"ok": True, "expires_at": session.expires_at}
        if native:
            payload["token"] = session.token
        return payload

    def require_string(payload: dict[str, Any], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(status_code=400, detail=f"{key} is required")
        return value.strip()

    def require_credential(payload: dict[str, Any]) -> dict[str, Any]:
        value = payload.get("credential")
        if not isinstance(value, dict):
            raise HTTPException(status_code=400, detail="credential is required")
        return value

    @app.get("/.well-known/apple-app-site-association", include_in_schema=False)
    def apple_app_site_association():
        apps = [f"{apple_team_id}.{apple_bundle_id}"] if apple_team_id else []
        return JSONResponse(
            {"webcredentials": {"apps": apps}},
            media_type="application/json",
            headers={"Cache-Control": "public, max-age=300"},
        )

    @app.get("/api/auth/status")
    def auth_status(token: str | None = Depends(raw_session)) -> dict[str, Any]:
        authenticated = auth_disabled or auth_store.validate_session(token)
        count = auth_store.credential_count()
        return {
            "authenticated": authenticated,
            "bootstrap_required": count == 0,
            "passkey_count": count,
            "rp_id": rp_id,
            "auth_disabled": auth_disabled,
        }

    @app.post("/api/auth/bootstrap/options")
    def bootstrap_options(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        code = require_string(payload, "code")
        if not auth_store.validate_bootstrap(code):
            raise HTTPException(status_code=403, detail="invalid or expired enrollment code")
        return passkeys.registration_options()

    @app.post("/api/auth/bootstrap/verify")
    def bootstrap_verify(
        response: Response,
        payload: dict[str, Any] = Body(...),
        x_avo_client: str | None = Header(default=None),
    ) -> dict[str, Any]:
        code = require_string(payload, "code")
        challenge_id = require_string(payload, "challenge_id")
        credential = require_credential(payload)
        if not auth_store.validate_bootstrap(code):
            raise HTTPException(status_code=403, detail="invalid or expired enrollment code")
        try:
            passkeys.verify_registration(challenge_id, credential)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"passkey registration failed: {exc}") from exc
        auth_store.consume_bootstrap()
        return issue_session(response, x_avo_client == "native")

    @app.post("/api/auth/login/options")
    def login_options() -> dict[str, Any]:
        try:
            return passkeys.authentication_options()
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/auth/login/verify")
    def login_verify(
        response: Response,
        payload: dict[str, Any] = Body(...),
        x_avo_client: str | None = Header(default=None),
    ) -> dict[str, Any]:
        challenge_id = require_string(payload, "challenge_id")
        credential = require_credential(payload)
        try:
            passkeys.verify_authentication(challenge_id, credential)
        except Exception as exc:
            raise HTTPException(status_code=401, detail=f"passkey authentication failed: {exc}") from exc
        return issue_session(response, x_avo_client == "native")

    @app.post("/api/auth/register/options")
    def register_options(_: str = Depends(authorize)) -> dict[str, Any]:
        return passkeys.registration_options()

    @app.post("/api/auth/register/verify")
    def register_verify(
        payload: dict[str, Any] = Body(...),
        _: str = Depends(authorize),
    ) -> dict[str, Any]:
        challenge_id = require_string(payload, "challenge_id")
        credential = require_credential(payload)
        try:
            credential_id = passkeys.verify_registration(challenge_id, credential)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"passkey registration failed: {exc}") from exc
        return {"ok": True, "credential_id": credential_id}

    @app.get("/api/auth/credentials")
    def credentials(_: str = Depends(authorize)) -> list[dict[str, Any]]:
        return [
            {
                "id": str(row["credential_id"]),
                "label": str(row["label"]),
                "device_type": str(row["device_type"]),
                "backed_up": bool(row["backed_up"]),
                "created_at": str(row["created_at"]),
                "last_used_at": row["last_used_at"],
            }
            for row in auth_store.list_credentials()
        ]

    @app.post("/api/auth/logout")
    def logout(
        response: Response,
        token: str | None = Depends(raw_session),
    ) -> dict[str, bool]:
        auth_store.revoke_session(token)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/health")
    def health(_: str = Depends(authorize)) -> dict[str, Any]:
        return {
            "ok": True,
            "state_dir": str(config.state_path),
            "benchmark_root": str(benchmark_root),
            "rp_id": rp_id,
            "static_web": static_root.exists(),
        }

    @app.get("/api/runs")
    def list_runs(limit: int = Query(default=50, ge=1, le=250), _: str = Depends(authorize)):
        return rows(
            "SELECT id, objective, repo_path, best_score, status, created_at, updated_at "
            "FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
        )

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str, _: str = Depends(authorize)):
        result = snapshot(run_id)
        if result is None:
            raise HTTPException(status_code=404, detail="run not found")
        return result

    @app.post("/api/runs", status_code=202)
    def start_run(payload: dict[str, Any] = Body(...), _: str = Depends(authorize)):
        objective = require_string(payload, "objective")
        proc = subprocess.Popen(
            [sys.executable, "-m", "avo_harness", "run", objective, "-c", str(config_file)],
            cwd=config.repo_path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {"accepted": True, "pid": proc.pid}

    @app.get("/api/benchmarks")
    def list_benchmarks(_: str = Depends(authorize)) -> list[dict[str, Any]]:
        return _benchmark_entries(benchmark_root)

    @app.get("/api/benchmarks/{benchmark_id:path}")
    def get_benchmark(benchmark_id: str, _: str = Depends(authorize)) -> dict[str, Any]:
        result = _benchmark_detail(benchmark_root, benchmark_id)
        if result is None:
            raise HTTPException(status_code=404, detail="benchmark report not found")
        return result

    @app.websocket("/api/ws")
    async def websocket(websocket: WebSocket, access_token: str | None = Query(default=None)):
        token = access_token or websocket.cookies.get(SESSION_COOKIE)
        if not auth_disabled and not auth_store.validate_session(token):
            await websocket.close(code=4401)
            return
        await websocket.accept()
        last = ""
        try:
            while True:
                current = json.dumps(
                    rows(
                        "SELECT id, objective, best_score, status, created_at, updated_at "
                        "FROM runs ORDER BY created_at DESC LIMIT 50"
                    ),
                    sort_keys=True,
                )
                if current != last:
                    await websocket.send_text(current)
                    last = current
                await asyncio.sleep(1.5)
        except WebSocketDisconnect:
            return

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path == "api" or path.startswith("api/") or path == ".well-known" or path.startswith(".well-known/"):
            raise HTTPException(status_code=404)
        if not static_root.exists():
            raise HTTPException(status_code=404, detail="web frontend has not been built")
        requested = (static_root / path).resolve()
        if static_root != requested and static_root not in requested.parents:
            raise HTTPException(status_code=404)
        if requested.is_file():
            return FileResponse(requested)
        index = static_root / "index.html"
        if index.is_file():
            return FileResponse(index)
        raise HTTPException(status_code=404)

    return app
