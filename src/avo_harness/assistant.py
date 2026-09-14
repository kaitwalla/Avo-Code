from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AVOConfig
from .gitops import GitRepo
from .worker import make_worker


ASSISTANT_SYSTEM_PROMPT = """You are Avo, a conversational engineering assistant with access to a disposable
checkout of the configured repository. Your normal job is to answer questions, investigate code, and reduce
uncertainty. Do not treat every message as a coding task.

The checkout you see is disposable. You may inspect files, run read-only commands and tests, and use available
research tools. Do not make implementation edits during this conversational phase. If a tool happens to modify
the checkout, those changes will be discarded and must not be relied upon.

For informational questions, answer normally. For requested code changes, investigate until you either have a
concrete, evidence-backed implementation target or discover an ambiguity that matters. Never use a made-up
confidence percentage. A change is execution-ready only when you can cite concrete evidence from files/symbols,
test output, configuration, or authoritative documentation and you know how success will be checked.

Return ONLY one JSON object with this shape:
{
  "reply": "natural-language response to the user",
  "action": "answer" | "clarify" | "execute",
  "objective": "concise implementation objective or empty string",
  "evidence": [{"fact": "what you established", "source": "file/symbol/test/docs source"}],
  "acceptance": ["observable condition that means the change worked"],
  "constraints": ["important behavior that must not change"],
  "question": "one targeted clarification question or empty string"
}

Rules:
- Use action=answer when no repository mutation is requested.
- Use action=clarify when a material product/behavior decision is unresolved. Ask one targeted question.
- Use action=execute only when the user has requested a code/configuration change AND you have at least two
  concrete evidence items with sources AND at least one observable acceptance condition.
- Do not use action=execute merely because a likely fix sounds plausible.
- Keep the reply concise and useful. When action=execute, explain what you established and that you have enough
  evidence to implement it; do not narrate internal reasoning.
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_object(text: str) -> dict[str, Any] | None:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s*```$", "", value)
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    start = value.find("{")
    end = value.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(value[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


@dataclass(slots=True)
class Evidence:
    fact: str
    source: str


@dataclass(slots=True)
class AssistantDecision:
    reply: str
    action: str = "answer"
    objective: str = ""
    evidence: list[Evidence] = field(default_factory=list)
    acceptance: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    question: str = ""

    @property
    def execution_ready(self) -> bool:
        return (
            self.action == "execute"
            and len(self.objective.strip()) >= 8
            and len(self.evidence) >= 2
            and all(item.fact.strip() and item.source.strip() for item in self.evidence)
            and any(item.strip() for item in self.acceptance)
            and not self.question.strip()
        )

    def metadata(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "objective": self.objective,
            "evidence": [{"fact": item.fact, "source": item.source} for item in self.evidence],
            "acceptance": self.acceptance,
            "constraints": self.constraints,
            "question": self.question,
            "execution_ready": self.execution_ready,
        }


def parse_decision(output: str) -> AssistantDecision:
    payload = _json_object(output)
    if payload is None:
        return AssistantDecision(reply=output.strip() or "I couldn't produce a useful response.")

    action = str(payload.get("action") or "answer").lower()
    if action not in {"answer", "clarify", "execute"}:
        action = "answer"

    evidence: list[Evidence] = []
    for item in payload.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        evidence.append(
            Evidence(fact=str(item.get("fact") or "").strip(), source=str(item.get("source") or "").strip())
        )

    def strings(key: str) -> list[str]:
        values = payload.get(key) or []
        if not isinstance(values, list):
            return []
        return [str(value).strip() for value in values if str(value).strip()]

    decision = AssistantDecision(
        reply=str(payload.get("reply") or "").strip(),
        action=action,
        objective=str(payload.get("objective") or "").strip(),
        evidence=evidence,
        acceptance=strings("acceptance"),
        constraints=strings("constraints"),
        question=str(payload.get("question") or "").strip(),
    )
    if not decision.reply:
        decision.reply = decision.question or "I need a little more information before I can help with that."

    # An agent is not allowed to promote itself into execution without the deterministic evidence contract.
    if decision.action == "execute" and not decision.execution_ready:
        decision.action = "clarify"
        if not decision.question:
            decision.question = "I don't have enough concrete evidence yet to make this change safely. What behavior should I verify before I proceed?"
        if decision.question not in decision.reply:
            decision.reply = f"{decision.reply}\n\n{decision.question}".strip()
    return decision


class ChatStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def _init_schema(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS chat_conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    run_id TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES chat_conversations(id)
                );
                CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation
                    ON chat_messages(conversation_id, created_at);
                """
            )

    def ensure_conversation(self, conversation_id: str = "main") -> None:
        now = _now()
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO chat_conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (conversation_id, "Avo", now, now),
            )

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        kind: str = "text",
        status: str = "complete",
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        self.ensure_conversation(conversation_id)
        message_id = uuid.uuid4().hex
        now = _now()
        with self._connect() as db:
            db.execute(
                """INSERT INTO chat_messages
                   (id, conversation_id, role, content, kind, status, run_id, metadata_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    message_id,
                    conversation_id,
                    role,
                    content,
                    kind,
                    status,
                    run_id,
                    json.dumps(metadata or {}, sort_keys=True),
                    now,
                    now,
                ),
            )
            db.execute("UPDATE chat_conversations SET updated_at=? WHERE id=?", (now, conversation_id))
        return message_id

    def update_message(
        self,
        message_id: str,
        *,
        content: str,
        kind: str,
        status: str,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._connect() as db:
            db.execute(
                """UPDATE chat_messages SET content=?, kind=?, status=?, run_id=?, metadata_json=?, updated_at=?
                   WHERE id=?""",
                (content, kind, status, run_id, json.dumps(metadata or {}, sort_keys=True), _now(), message_id),
            )

    def messages(self, conversation_id: str = "main", limit: int = 200) -> list[dict[str, Any]]:
        self.ensure_conversation(conversation_id)
        with self._connect() as db:
            rows = db.execute(
                """SELECT * FROM (
                       SELECT * FROM chat_messages WHERE conversation_id=? ORDER BY created_at DESC LIMIT ?
                   ) ORDER BY created_at""",
                (conversation_id, limit),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["metadata"] = json.loads(item.pop("metadata_json"))
            except (json.JSONDecodeError, TypeError):
                item["metadata"] = {}
            result.append(item)
        return result


class AssistantService:
    def __init__(self, config: AVOConfig, config_file: Path):
        self.config = config
        self.config_file = config_file
        self.store = ChatStore(config.state_path / "state.sqlite3")
        self.git = GitRepo(config.repo_path, config.state_path / "assistant-worktrees")

    def messages(self, conversation_id: str = "main") -> list[dict[str, Any]]:
        return self.store.messages(conversation_id)

    def submit(self, content: str, *, conversation_id: str = "main", auto_execute: bool = True) -> dict[str, str]:
        user_id = self.store.add_message(conversation_id, "user", content)
        assistant_id = self.store.add_message(
            conversation_id,
            "assistant",
            "Checking the repository…",
            kind="thinking",
            status="thinking",
        )
        thread = threading.Thread(
            target=self._process,
            args=(conversation_id, assistant_id, auto_execute),
            daemon=True,
            name=f"avo-chat-{assistant_id[:8]}",
        )
        thread.start()
        return {"user_message_id": user_id, "assistant_message_id": assistant_id}

    def _history_prompt(self, conversation_id: str) -> str:
        messages = self.store.messages(conversation_id, limit=24)
        chunks: list[str] = []
        total = 0
        for message in reversed(messages):
            if message["status"] == "thinking":
                continue
            role = "USER" if message["role"] == "user" else "AVO"
            content = str(message["content"]).strip()
            if not content:
                continue
            chunk = f"{role}: {content}"
            if total + len(chunk) > 24000:
                break
            chunks.append(chunk)
            total += len(chunk)
        chunks.reverse()
        return "\n\n".join(chunks)

    def _investigate(self, conversation_id: str) -> AssistantDecision:
        worker_config = self.config.worker.clone()
        worker_config.system_prompt = ASSISTANT_SYSTEM_PROMPT
        worker_config.max_turns = min(worker_config.max_turns, 14)
        worker = make_worker(worker_config)
        turn_id = f"chat-{uuid.uuid4().hex[:12]}"
        base_commit = self.git.head()
        worktree = self.git.add_worktree(turn_id, "inspect", base_commit, branch=None)
        try:
            prompt = (
                f"{ASSISTANT_SYSTEM_PROMPT}\n\n"
                f"REPOSITORY\n{self.config.repo_path}\n\n"
                f"CONVERSATION\n{self._history_prompt(conversation_id)}\n\n"
                "Respond with the required JSON object only."
            )
            result = worker.run(prompt, worktree.path)
            if not result.success and not result.output.strip():
                raise RuntimeError(result.error or "assistant worker failed")
            return parse_decision(result.output or result.error)
        finally:
            self.git.remove_worktree(worktree)

    def _launch_run(self, objective: str) -> subprocess.Popen[str]:
        return subprocess.Popen(
            [sys.executable, "-m", "avo_harness", "run", objective, "-c", str(self.config_file)],
            cwd=self.config.repo_path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            text=True,
        )

    def _find_run(self, objective: str, started_at: str, timeout_seconds: float = 12.0) -> str | None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                with sqlite3.connect(self.config.state_path / "state.sqlite3") as db:
                    row = db.execute(
                        """SELECT id FROM runs WHERE objective=? AND created_at>=?
                           ORDER BY created_at DESC LIMIT 1""",
                        (objective, started_at),
                    ).fetchone()
                if row:
                    return str(row[0])
            except sqlite3.OperationalError:
                pass
            time.sleep(0.25)
        return None

    def _process(self, conversation_id: str, assistant_id: str, auto_execute: bool) -> None:
        try:
            decision = self._investigate(conversation_id)
            run_id: str | None = None
            kind = "text"
            metadata = decision.metadata()
            if decision.execution_ready and auto_execute:
                started_at = _now()
                proc = self._launch_run(decision.objective)
                run_id = self._find_run(decision.objective, started_at)
                metadata["pid"] = proc.pid
                metadata["auto_executed"] = True
                kind = "execution"
            elif decision.execution_ready:
                metadata["auto_executed"] = False
                kind = "ready"
            self.store.update_message(
                assistant_id,
                content=decision.reply,
                kind=kind,
                status="complete",
                run_id=run_id,
                metadata=metadata,
            )
        except Exception as exc:
            self.store.update_message(
                assistant_id,
                content=f"I hit an error while investigating the repository: {exc}",
                kind="error",
                status="error",
                metadata={"error": str(exc)},
            )
