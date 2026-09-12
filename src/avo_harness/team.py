from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from .config import RoleConfig, TeamConfig, WorkerConfig
from .models import WorkerResult
from .worker import Worker, make_worker


_ITERATION_RE = re.compile(r"(?im)^ITERATION\s*\n\s*(\d+)\s+of\s+\d+")


def _iteration_from_prompt(prompt: str) -> int:
    match = _ITERATION_RE.search(prompt)
    return int(match.group(1)) if match else 1


def _explicit_role_requested(prompt: str, role: str) -> bool:
    escaped = re.escape(role)
    return bool(re.search(rf"(?i)(?:@{escaped}\b|\[role:{escaped}\]|\buse\s+{escaped}\b)", prompt))


def _triggered(role: RoleConfig, prompt: str) -> bool:
    return any(re.search(pattern, prompt, flags=re.IGNORECASE | re.MULTILINE) for pattern in role.triggers)


def _usage_totals(role_runs: list[dict[str, Any]]) -> dict[str, float | int]:
    totals: dict[str, float | int] = {}
    for item in role_runs:
        usage = item.get("metadata", {}).get("usage")
        if not isinstance(usage, dict):
            continue
        for key, value in usage.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                totals[key] = totals.get(key, 0) + value
    return totals


class TeamWorker:
    """A deterministic, lazy multi-role worker built on the normal Worker boundary."""

    def __init__(self, config: TeamConfig, base_worker: WorkerConfig):
        self.config = config
        self.base_worker = base_worker
        self.role_configs = config.resolved_workers(base_worker)
        self.role_workers: dict[str, Worker] = {
            name: make_worker(worker_config)
            for name, worker_config in self.role_configs.items()
        }

    def plan(self, prompt: str) -> list[tuple[str, str]]:
        iteration = _iteration_from_prompt(prompt)
        primary = self.config.primary_role
        orchestrator = self.config.orchestrator_role
        selected: dict[str, str] = {}

        for name, role in self.config.roles.items():
            if not role.enabled or name == primary:
                continue
            if _explicit_role_requested(prompt, name):
                selected[name] = "explicit"
            elif _triggered(role, prompt):
                selected[name] = "trigger"
            elif role.activate_on_retry and iteration >= self.config.retry_after_iteration:
                selected[name] = "retry"
            elif role.activate_on_deep_retry and iteration >= self.config.deep_retry_after_iteration:
                selected[name] = "deep-retry"

        specialists = [
            name for name in selected
            if name != orchestrator and self.config.roles[name].phase != "coordination"
        ]
        if orchestrator in self.config.roles and self.config.roles[orchestrator].enabled:
            if _explicit_role_requested(prompt, orchestrator):
                selected[orchestrator] = "explicit"
            elif iteration >= self.config.orchestrate_after_iteration:
                selected[orchestrator] = "retry"
            elif len(specialists) >= 2:
                selected[orchestrator] = "multiple-specialists"

        plan: list[tuple[str, str]] = []
        for phase in ("advice", "coordination", "implementation"):
            for name, role in self.config.roles.items():
                if name == primary or role.phase != phase or name not in selected:
                    continue
                plan.append((name, selected[name]))
        plan.append((primary, "primary"))
        return plan

    def _shared_context(self, completed: list[dict[str, Any]]) -> str:
        if not completed:
            return ""
        remaining = self.config.max_shared_context_chars
        chunks: list[str] = []
        for item in completed:
            text = (item.get("output") or item.get("error") or "").strip()
            if not text:
                continue
            limit = min(self.config.max_role_output_chars, remaining)
            if limit <= 0:
                break
            text = text[:limit]
            chunks.append(f"[{item['role']}]\n{text}")
            remaining -= len(text)
        return "\n\n".join(chunks)

    def _role_prompt(
        self,
        role_name: str,
        reason: str,
        original_prompt: str,
        completed: list[dict[str, Any]],
    ) -> str:
        context = self._shared_context(completed)
        role = self.config.roles[role_name]
        parts = [
            f"ROLE\n{role_name}",
            f"\nACTIVATION\n{reason}",
            f"\nTASK CONTEXT\n{original_prompt}",
        ]
        if context:
            parts.append(f"\nTEAM CONTEXT\n{context}")
        if role.phase == "advice":
            parts.append(
                "\nROLE OUTPUT CONTRACT\nReturn compact findings for the implementation workers. "
                "Do not spend tokens narrating your process."
            )
        elif role.phase == "coordination":
            parts.append(
                "\nROLE OUTPUT CONTRACT\nReturn one concise implementation directive that resolves "
                "the available evidence. Do not edit files."
            )
        elif role_name == self.config.primary_role:
            parts.append(
                "\nROLE OUTPUT CONTRACT\nImplement the task now. Inspect any changes already made by "
                "specialist implementation roles, integrate them, and run the relevant checks."
            )
        else:
            parts.append(
                "\nROLE OUTPUT CONTRACT\nImplement only the changes in your specialty that materially "
                "advance the task, run relevant checks, and leave the workspace ready for the primary coder."
            )
        return "\n".join(parts)

    def run(self, prompt: str, workspace: Path) -> WorkerResult:
        plan = self.plan(prompt)
        completed: list[dict[str, Any]] = []
        role_runs: list[dict[str, Any]] = []
        primary_result: WorkerResult | None = None
        started = time.monotonic()

        for sequence, (role_name, reason) in enumerate(plan, start=1):
            worker = self.role_workers[role_name]
            worker_config = self.role_configs[role_name]
            role_prompt = self._role_prompt(role_name, reason, prompt, completed)
            role_started = time.monotonic()
            try:
                result = worker.run(role_prompt, workspace)
            except Exception as exc:
                result = WorkerResult(success=False, error=f"{role_name} failed: {exc}")
            duration_ms = int((time.monotonic() - role_started) * 1000)
            record = {
                "sequence": sequence,
                "role": role_name,
                "reason": reason,
                "success": result.success,
                "duration_ms": duration_ms,
                "output": result.output[-self.config.max_role_output_chars :],
                "error": result.error[-self.config.max_role_output_chars :],
                "metadata": {
                    **result.metadata,
                    "execution_class": worker_config.execution_class,
                    "backend": worker_config.backend,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "cost_usd": result.cost_usd,
                },
            }
            role_runs.append(record)
            completed.append(record)
            if role_name == self.config.primary_role:
                primary_result = result

        total_duration = time.monotonic() - started
        if primary_result is None:
            return WorkerResult(
                success=False,
                error=f"team primary role {self.config.primary_role!r} did not run",
                metadata={"role_runs": role_runs},
                duration_seconds=total_duration,
            )

        summaries: list[str] = []
        for item in completed:
            text = (item["output"] or item["error"]).strip().replace("\n", " ")
            if text:
                summaries.append(f"{item['role']}: {text[:900]}")
        team_summary = " | ".join(summaries)[:4000]
        metadata = dict(primary_result.metadata)
        metadata.update(
            {
                "team": True,
                "team_mode": self.config.mode,
                "team_roles": [role for role, _ in plan],
                "role_runs": role_runs,
                "team_summary": team_summary,
                "team_duration_ms": int(total_duration * 1000),
            }
        )
        usage = _usage_totals(role_runs)
        if usage:
            metadata["team_usage"] = usage

        input_tokens = sum(item.get("metadata", {}).get("input_tokens") or 0 for item in role_runs)
        output_tokens = sum(item.get("metadata", {}).get("output_tokens") or 0 for item in role_runs)
        costs = [item.get("metadata", {}).get("cost_usd") for item in role_runs]
        cost_usd = sum(value for value in costs if isinstance(value, (int, float)))

        return WorkerResult(
            success=primary_result.success,
            output=primary_result.output,
            error=primary_result.error,
            metadata=metadata,
            duration_seconds=total_duration,
            input_tokens=input_tokens or None,
            output_tokens=output_tokens or None,
            cost_usd=cost_usd or None,
        )


def make_team_worker(config: TeamConfig, base_worker: WorkerConfig) -> TeamWorker:
    return TeamWorker(config, base_worker)
