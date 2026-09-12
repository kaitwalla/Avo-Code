from __future__ import annotations

import copy
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

ROLE_SYSTEM_PROMPTS: dict[str, str] = {
    "orchestrator": """You are the task orchestrator for a coding team. Do not edit the repository.
Read the task and any specialist findings, resolve conflicts, and return a short execution directive
for the implementation workers. Prefer the smallest high-confidence next step. Do not restate the task.""",
    "architect": """You are the architecture specialist for a coding team. Treat the repository as read-only.
Inspect relevant code and return a compact implementation plan covering interfaces, invariants,
acceptance criteria, and migration/compatibility risks. Do not modify files.""",
    "researcher": """You are the research specialist for a coding team. Treat the repository as read-only.
Investigate uncertain behavior using the repository and any available documentation/search tools.
Return concise evidence, version/API facts, and implications for implementation. Do not modify files.""",
    "infrastructure": """You are the infrastructure specialist for a coding team. Work on infrastructure concerns
such as containers, CI, deployment, networking, services, observability, and runtime configuration.
Make concrete changes when the task needs them, run relevant checks, and leave the workspace usable.""",
    "coder": """You are the primary implementation worker in a coding team. Work directly in the repository.
Use any supplied specialist findings and orchestrator directive, inspect the code before changing it,
implement the task, and run relevant tests/checks. Do not merely describe what should be changed.""",
}


def _copy_json(value: Any) -> Any:
    return copy.deepcopy(value)


@dataclass(slots=True)
class WorkerConfig:
    backend: str = "command"  # command | nemo
    command: list[str] = field(default_factory=list)
    adapter_id: str = "nvidia.fabric.hermes"
    provider: str | None = None
    model: str | None = None
    api_key_env: str | None = None
    base_url: str | None = None
    temperature: float | None = None
    model_settings: dict[str, Any] = field(default_factory=dict)
    max_turns: int = 24
    timeout_seconds: int = 3600
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    env: dict[str, str] = field(default_factory=dict)
    harness_settings: dict[str, Any] = field(default_factory=dict)
    tools: dict[str, Any] | None = None
    mcp: dict[str, Any] | None = None
    skills: dict[str, Any] | None = None
    telemetry: dict[str, Any] | None = None
    execution_class: str = "local"  # local | cloud

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "WorkerConfig":
        raw = dict(raw or {})
        command = raw.get("command", [])
        if isinstance(command, str):
            command = shlex.split(command)
        raw["command"] = command
        return cls(**raw)

    def clone(self) -> "WorkerConfig":
        return WorkerConfig.from_dict(_copy_json(asdict(self)))


@dataclass(slots=True)
class WorkerOverride:
    """Sparse per-role changes applied on top of the shared worker configuration."""

    backend: str | None = None
    command: list[str] | None = None
    adapter_id: str | None = None
    provider: str | None = None
    model: str | None = None
    api_key_env: str | None = None
    base_url: str | None = None
    temperature: float | None = None
    model_settings: dict[str, Any] | None = None
    max_turns: int | None = None
    timeout_seconds: int | None = None
    env: dict[str, str] = field(default_factory=dict)
    harness_settings: dict[str, Any] | None = None
    tools: dict[str, Any] | None = None
    mcp: dict[str, Any] | None = None
    skills: dict[str, Any] | None = None
    telemetry: dict[str, Any] | None = None
    execution_class: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "WorkerOverride":
        raw = dict(raw or {})
        if isinstance(raw.get("command"), str):
            raw["command"] = shlex.split(raw["command"])
        return cls(**raw)

    def apply(self, base: WorkerConfig, *, system_prompt: str | None = None) -> WorkerConfig:
        merged = base.clone()
        scalar_fields = (
            "backend", "command", "adapter_id", "provider", "model", "api_key_env",
            "base_url", "temperature", "model_settings", "max_turns", "timeout_seconds",
            "harness_settings", "tools", "mcp", "skills", "telemetry", "execution_class",
        )
        for name in scalar_fields:
            value = getattr(self, name)
            if value is not None:
                setattr(merged, name, _copy_json(value))
        if self.env:
            merged.env.update(self.env)
        if system_prompt is not None:
            merged.system_prompt = system_prompt
        return merged


@dataclass(slots=True)
class RoleConfig:
    enabled: bool = True
    description: str = ""
    phase: str = "advice"  # advice | coordination | implementation
    system_prompt: str = ""
    triggers: list[str] = field(default_factory=list)
    activate_on_retry: bool = False
    activate_on_deep_retry: bool = False
    worker: WorkerOverride = field(default_factory=WorkerOverride)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None, *, base: "RoleConfig | None" = None) -> "RoleConfig":
        if base is None:
            base = cls()
        data = {
            "enabled": base.enabled,
            "description": base.description,
            "phase": base.phase,
            "system_prompt": base.system_prompt,
            "triggers": list(base.triggers),
            "activate_on_retry": base.activate_on_retry,
            "activate_on_deep_retry": base.activate_on_deep_retry,
            "worker": base.worker,
        }
        incoming = dict(raw or {})
        if "worker" in incoming:
            incoming["worker"] = WorkerOverride.from_dict(incoming["worker"])
        data.update(incoming)
        return cls(**data)


def default_team_roles() -> dict[str, RoleConfig]:
    return {
        "orchestrator": RoleConfig(
            description="Coordinates specialist findings into the next implementation step.",
            phase="coordination",
            system_prompt=ROLE_SYSTEM_PROMPTS["orchestrator"],
        ),
        "architect": RoleConfig(
            description="Designs interfaces, invariants, and implementation plans.",
            phase="advice",
            system_prompt=ROLE_SYSTEM_PROMPTS["architect"],
            triggers=[r"\barchitect(?:ure)?\b", r"\bdesign\b", r"\brefactor\b", r"\bmigration\b", r"\bschema\b", r"\binterface\b", r"\bcross[- ]cutting\b", r"\bnew subsystem\b"],
            activate_on_retry=True,
        ),
        "researcher": RoleConfig(
            description="Investigates uncertain code, dependencies, APIs, and external behavior.",
            phase="advice",
            system_prompt=ROLE_SYSTEM_PROMPTS["researcher"],
            triggers=[r"\bresearch\b", r"\bupstream\b", r"\bdocs?\b", r"\bdocumentation\b", r"\bdependency\b", r"\blibrary\b", r"\bunknown behavior\b", r"\bversion(?:s|ed)?\b", r"\brelease(?:s|d)?\b"],
            activate_on_deep_retry=True,
        ),
        "infrastructure": RoleConfig(
            description="Handles containers, CI, deployment, networking, services, and runtime config.",
            phase="implementation",
            system_prompt=ROLE_SYSTEM_PROMPTS["infrastructure"],
            triggers=[r"\bdocker(?:file)?\b", r"\bcompose\b", r"\bcontainer(?:s|ized)?\b", r"\bci\b", r"\bpipeline\b", r"\bdeploy(?:ment|ing)?\b", r"\bterraform\b", r"\bkubernetes\b", r"\bk8s\b", r"\bnginx\b", r"\bproxy\b", r"\bnetwork(?:ing)?\b", r"\bsystemd\b", r"\binfrastructure\b"],
        ),
        "coder": RoleConfig(
            description="Primary implementation worker.",
            phase="implementation",
            system_prompt=ROLE_SYSTEM_PROMPTS["coder"],
        ),
    }


@dataclass(slots=True)
class TeamConfig:
    enabled: bool = False
    mode: str = "lazy"
    primary_role: str = "coder"
    orchestrator_role: str = "orchestrator"
    retry_after_iteration: int = 2
    deep_retry_after_iteration: int = 3
    orchestrate_after_iteration: int = 2
    max_shared_context_chars: int = 12000
    max_role_output_chars: int = 5000
    roles: dict[str, RoleConfig] = field(default_factory=default_team_roles)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "TeamConfig":
        raw = dict(raw or {})
        roles = default_team_roles()
        for name, role_raw in dict(raw.pop("roles", {}) or {}).items():
            roles[name] = RoleConfig.from_dict(role_raw, base=roles.get(name))
        raw["roles"] = roles
        return cls(**raw)

    def resolved_workers(self, base: WorkerConfig) -> dict[str, WorkerConfig]:
        return {
            name: role.worker.apply(base, system_prompt=role.system_prompt or base.system_prompt)
            for name, role in self.roles.items()
            if role.enabled
        }


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


def _validate_worker(worker: WorkerConfig, label: str) -> None:
    if worker.backend not in {"command", "nemo"}:
        raise ValueError(f"{label}.backend must be 'command' or 'nemo'")
    if worker.backend == "command" and not worker.command:
        raise ValueError(f"command worker requires {label}.command")
    if worker.execution_class not in {"local", "cloud"}:
        raise ValueError(f"{label}.execution_class must be 'local' or 'cloud'")
    if worker.max_turns < 1:
        raise ValueError(f"{label}.max_turns must be >= 1")
    if worker.timeout_seconds < 1:
        raise ValueError(f"{label}.timeout_seconds must be >= 1")


@dataclass(slots=True)
class AVOConfig:
    repo: str
    worker: WorkerConfig
    evaluators: list[EvaluatorConfig]
    planner: PlannerConfig = field(default_factory=PlannerConfig)
    supervisor: SupervisorConfig = field(default_factory=SupervisorConfig)
    team: TeamConfig = field(default_factory=TeamConfig)
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
        _validate_worker(self.worker, "worker")
        if self.planner.worker is not None:
            _validate_worker(self.planner.worker, "planner.worker")
        if self.supervisor.worker is not None:
            _validate_worker(self.supervisor.worker, "supervisor.worker")
        if self.supervisor.stagnation_rounds < 1:
            raise ValueError("supervisor.stagnation_rounds must be >= 1")
        for ev in self.evaluators:
            if ev.weight <= 0:
                raise ValueError(f"evaluator {ev.name!r} weight must be > 0")

        if self.team.enabled:
            if self.team.mode != "lazy":
                raise ValueError("team.mode currently supports only 'lazy'")
            if self.team.primary_role not in self.team.roles:
                raise ValueError("team.primary_role must name a configured role")
            if not self.team.roles[self.team.primary_role].enabled:
                raise ValueError("team.primary_role must be enabled")
            if self.team.orchestrator_role not in self.team.roles:
                raise ValueError("team.orchestrator_role must name a configured role")
            if self.team.retry_after_iteration < 1:
                raise ValueError("team.retry_after_iteration must be >= 1")
            if self.team.deep_retry_after_iteration < self.team.retry_after_iteration:
                raise ValueError("team.deep_retry_after_iteration must be >= retry_after_iteration")
            if self.team.max_shared_context_chars < 1000:
                raise ValueError("team.max_shared_context_chars must be >= 1000")
            if self.team.max_role_output_chars < 200:
                raise ValueError("team.max_role_output_chars must be >= 200")
            for name, role in self.team.roles.items():
                if role.phase not in {"advice", "coordination", "implementation"}:
                    raise ValueError(f"team role {name!r} has invalid phase {role.phase!r}")
            for name, worker in self.team.resolved_workers(self.worker).items():
                _validate_worker(worker, f"team.roles.{name}.worker")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AVOConfig":
        raw = dict(raw)
        raw["worker"] = WorkerConfig.from_dict(raw.get("worker"))
        raw["evaluators"] = [EvaluatorConfig.from_dict(x) for x in raw.get("evaluators", [])]
        raw["planner"] = PlannerConfig.from_dict(raw.get("planner"))
        raw["supervisor"] = SupervisorConfig.from_dict(raw.get("supervisor"))
        raw["team"] = TeamConfig.from_dict(raw.get("team"))
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
        "team": {"enabled": False},
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
