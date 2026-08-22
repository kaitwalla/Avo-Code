from __future__ import annotations

import json
import os
import shlex
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_SYSTEM_PROMPT = """You are the implementation worker in a long-horizon coding loop.
Work directly in the provided repository workspace. Inspect the code before changing it.
Make concrete changes that advance the objective, run relevant tests or checks, and leave
all useful modifications in the workspace. Do not merely describe what should be changed.
Use the supplied memory to avoid repeating failed approaches."""

PLANNER_SYSTEM_PROMPT = """You are the planning agent for a long-horizon coding task.
Inspect the provided repository workspace but do not rely on making persistent edits. Produce a concise,
actionable implementation plan for a separate coding worker. Identify likely ownership boundaries,
important files or subsystems to inspect, validation strategy, sequencing, risks, and the highest-value
first implementation step. Prefer a plan that helps a smaller local model avoid broad unfocused search."""

SUPERVISOR_SYSTEM_PROMPT = """You supervise a long-horizon coding agent. You do not edit the target repository.
Study the objective, scores, evaluator feedback, and recent attempt summaries. Identify why
progress has stalled and return a concise strategic directive for the next worker. Prefer a
materially different hypothesis or decomposition over generic encouragement."""


@dataclass(slots=True)
class WorkerConfig:
    backend: str = "command"  # command | nemo
    command: list[str] = field(default_factory=list)
    adapter_id: str = "nvidia.fabric.hermes"
    provider: str | None = None
    model: str | None = None
    api_key_env: str | None = None
    base_url: str | None = None
    max_turns: int = 24
    timeout_seconds: int = 3600
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    env: dict[str, str] = field(default_factory=dict)
    execution_class: str = "local"  # local | cloud

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "WorkerConfig":
        raw = dict(raw or {})
        command = raw.get("command", [])
        if isinstance(command, str):
            command = shlex.split(command)
        raw["command"] = command
        return cls(**raw)


@dataclass(slots=True)
class EvaluatorConfig:
    name: str
    command: str
    weight: float = 1.0
    timeout_seconds: int = 900
    pass_score: float = 1.0

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "EvaluatorConfig":
        return cls(**raw)


@dataclass(slots=True)
class PlannerConfig:
    enabled: bool = False
    worker: WorkerConfig | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "PlannerConfig":
        raw = dict(raw or {})
        if "worker" in raw and raw["worker"] is not None:
            raw["worker"] = WorkerConfig.from_dict(raw["worker"])
        return cls(**raw)


@dataclass(slots=True)
class SupervisorConfig:
    enabled: bool = True
    stagnation_rounds: int = 2
    cooldown_rounds: int = 2
    worker: WorkerConfig | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "SupervisorConfig":
        raw = dict(raw or {})
        if "worker" in raw and raw["worker"] is not None:
            raw["worker"] = WorkerConfig.from_dict(raw["worker"])
        return cls(**raw)


@dataclass(slots=True)
class AVOConfig:
    repo: str
    worker: WorkerConfig
    evaluators: list[EvaluatorConfig]
    planner: PlannerConfig = field(default_factory=PlannerConfig)
    supervisor: SupervisorConfig = field(default_factory=SupervisorConfig)
    state_dir: str = "~/.local/state/avo-harness"
    max_iterations: int = 12
    acceptance_score: float = 1.0
    min_improvement: float = 0.001
    memory_window: int = 6
    keep_worktrees: bool = False
    allow_dirty_repo: bool = False
    result_branch_prefix: str = "avo"
    cloud_assist_budget: int | None = 2

    @property
    def repo_path(self) -> Path:
        return Path(os.path.expanduser(self.repo)).resolve()

    @property
    def state_path(self) -> Path:
        return Path(os.path.expanduser(self.state_dir)).resolve()

    def validate(self) -> None:
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")
        if not self.evaluators:
            raise ValueError("at least one evaluator is required")
        if self.cloud_assist_budget is not None and self.cloud_assist_budget < 0:
            raise ValueError("cloud_assist_budget must be >= 0 or null")
        workers = [self.worker]
        if self.planner.worker is not None:
            workers.append(self.planner.worker)
        if self.supervisor.worker is not None:
            workers.append(self.supervisor.worker)
        for worker in workers:
            if worker.backend not in {"command", "nemo"}:
                raise ValueError("worker.backend must be 'command' or 'nemo'")
            if worker.backend == "command" and not worker.command:
                raise ValueError("command worker requires worker.command")
            if worker.execution_class not in {"local", "cloud"}:
                raise ValueError("worker.execution_class must be 'local' or 'cloud'")
        if self.supervisor.stagnation_rounds < 1:
            raise ValueError("supervisor.stagnation_rounds must be >= 1")
        for ev in self.evaluators:
            if ev.weight <= 0:
                raise ValueError(f"evaluator {ev.name!r} weight must be > 0")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AVOConfig":
        raw = dict(raw)
        raw["worker"] = WorkerConfig.from_dict(raw.get("worker"))
        raw["evaluators"] = [EvaluatorConfig.from_dict(x) for x in raw.get("evaluators", [])]
        raw["planner"] = PlannerConfig.from_dict(raw.get("planner"))
        raw["supervisor"] = SupervisorConfig.from_dict(raw.get("supervisor"))
        config = cls(**raw)
        config.validate()
        return config

    @classmethod
    def load(cls, path: str | Path) -> "AVOConfig":
        with open(path, "r", encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def example_config(repo: str = ".") -> dict[str, Any]:
    return {
        "repo": repo,
        "state_dir": "~/.local/state/avo-harness",
        "max_iterations": 12,
        "acceptance_score": 1.0,
        "min_improvement": 0.001,
        "memory_window": 6,
        "keep_worktrees": False,
        "cloud_assist_budget": 2,
        "worker": {
            "backend": "nemo",
            "adapter_id": "nvidia.fabric.hermes",
            "provider": "openai",
            "model": "local-open-model",
            "base_url": "http://127.0.0.1:8000/v1",
            "max_turns": 24,
            "timeout_seconds": 3600,
            "execution_class": "local",
        },
        "planner": {"enabled": False},
        "supervisor": {
            "enabled": True,
            "stagnation_rounds": 2,
            "cooldown_rounds": 2,
        },
        "evaluators": [
            {
                "name": "tests",
                "command": "pytest -q",
                "weight": 1.0,
                "timeout_seconds": 900,
                "pass_score": 1.0,
            }
        ],
    }
