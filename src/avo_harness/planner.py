from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .config import PLANNER_SYSTEM_PROMPT, PlannerConfig, WorkerConfig
from .models import WorkerResult
from .worker import make_worker


class Planner:
    def __init__(self, config: PlannerConfig, primary_worker: WorkerConfig):
        self.config = config
        source = config.worker or primary_worker
        self.worker_config = replace(
            source,
            command=list(source.command),
            env=dict(source.env),
            system_prompt=PLANNER_SYSTEM_PROMPT,
        )
        self.worker = make_worker(self.worker_config)

    def plan(self, objective: str, workspace: Path) -> tuple[str, WorkerResult]:
        prompt = (
            f"OBJECTIVE\n{objective}\n\n"
            "Inspect the repository enough to create an implementation map. Return a compact plan with: "
            "(1) likely ownership/files, (2) ordered milestones, (3) validation strategy, "
            "(4) major risks/unknowns, and (5) the best first concrete change for the implementation worker."
        )
        result = self.worker.run(prompt, workspace)
        if result.success and result.output.strip():
            return result.output.strip(), result
        return (
            "No model-generated plan was available. Start by locating the code that owns the failing behavior, "
            "identify the narrowest evaluator-visible failure, and make one testable change before broad refactors.",
            result,
        )
