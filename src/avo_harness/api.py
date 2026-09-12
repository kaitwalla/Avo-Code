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


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


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
                "default_strategy": policy.get("default_strategy"),
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
    return {
        "id": benchmark_id,
        "report": report,
        "routing_policy": policy or report.get("routing_policy", {}),
    }


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
    benchmark_root = Path(
        os.environ.get("AVO_BENCHMARK_ROOT", str(config_file.parent / "benchmarks"))
    ).expanduser().resolve()
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
        return {
            "ok": True,
            "state_dir": str(config.state_path),
            "benchmark_root": str(benchmark_root),
            "auth": bool(token),
        }

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

    @app.get("/api/benchmarks")
    def list_benchmarks(_: None = Depends(authorize)) -> list[dict[str, Any]]:
        return _benchmark_entries(benchmark_root)

    @app.get("/api/benchmarks/{benchmark_id:path}")
    def get_benchmark(benchmark_id: str, _: None = Depends(authorize)) -> dict[str, Any]:
        result = _benchmark_detail(benchmark_root, benchmark_id)
        if result is None:
            raise HTTPException(status_code=404, detail="benchmark report not found")
        return result

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
