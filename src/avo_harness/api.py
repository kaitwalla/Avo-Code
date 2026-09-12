from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

from .config import AVOConfig


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


def create_app(config_path: str = "avo.json"):
    try:
        from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
        from fastapi.middleware.cors import CORSMiddleware
        from pydantic import BaseModel
    except ImportError as exc:
        raise RuntimeError("Web UI dependencies are missing; install avo-harness[web]") from exc

    config_file = Path(config_path).expanduser().resolve()
    config = AVOConfig.load(config_file)
    db_path = config.state_path / "state.sqlite3"
    token = os.environ.get("AVO_WEB_TOKEN", "")

    class RunRequest(BaseModel):
        objective: str

    app = FastAPI(title="Avo-Code API", version="1")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in os.environ.get("AVO_WEB_ORIGINS", "*").split(",")],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    def authorize(authorization: str | None = Header(default=None)) -> None:
        if not token:
            return
        if authorization != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="invalid API token")

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

    @app.get("/api/health")
    def health(_: None = Depends(authorize)) -> dict[str, Any]:
        return {"ok": True, "state_dir": str(config.state_path), "auth": bool(token)}

    @app.get("/api/runs")
    def list_runs(limit: int = Query(default=50, ge=1, le=250), _: None = Depends(authorize)):
        return rows(
            "SELECT id, objective, repo_path, best_score, status, created_at, updated_at "
            "FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
        )

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str, _: None = Depends(authorize)):
        result = snapshot(run_id)
        if result is None:
            raise HTTPException(status_code=404, detail="run not found")
        return result

    @app.post("/api/runs", status_code=202)
    def start_run(request: RunRequest, _: None = Depends(authorize)):
        objective = request.objective.strip()
        if not objective:
            raise HTTPException(status_code=400, detail="objective is required")
        proc = subprocess.Popen(
            [sys.executable, "-m", "avo_harness", "run", objective, "-c", str(config_file)],
            cwd=config.repo_path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {"accepted": True, "pid": proc.pid}

    @app.websocket("/api/ws")
    async def websocket(websocket: WebSocket, access_token: str | None = Query(default=None)):
        if token and access_token != token:
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

    return app
