from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass

from .config import AVOConfig, WorkerConfig
from .evaluator import evaluate_all
from .gitops import GitRepo
from .models import Candidate, EvaluationResult
from .planner import Planner
from .store import Store
from .supervisor import Supervisor
from .worker import make_worker


@dataclass(slots=True)
class RunSummary:
    run_id: str
    status: str
    baseline_score: float
    best_score: float
    best_commit: str
    result_branch: str
    iterations: int
    wall_seconds: float
    local_invocations: int
    cloud_invocations: int
    planner_invocations: int
    supervisor_invocations: int
    reported_cost_usd: float

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "baseline_score": self.baseline_score,
            "best_score": self.best_score,
            "best_commit": self.best_commit,
            "result_branch": self.result_branch,
            "iterations": self.iterations,
            "wall_seconds": self.wall_seconds,
            "local_invocations": self.local_invocations,
            "cloud_invocations": self.cloud_invocations,
            "planner_invocations": self.planner_invocations,
            "supervisor_invocations": self.supervisor_invocations,
            "reported_cost_usd": self.reported_cost_usd,
        }


class Orchestrator:
    def __init__(self, config: AVOConfig):
        config.validate()
        self.config = config
        self.config.state_path.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.config.state_path / "state.sqlite3")
        self.git = GitRepo(self.config.repo_path, self.config.state_path / "worktrees")
        self.worker = make_worker(self.config.worker)
        self.planner = Planner(self.config.planner, self.config.worker)
        self.supervisor = Supervisor(self.config.supervisor, self.config.worker)
        self._cloud_assist_calls = 0

    def close(self) -> None:
        self.store.close()

    def _evaluation_memory(self, evaluations: list[EvaluationResult]) -> str:
        chunks = []
        for ev in evaluations:
            detail = ev.summary or ev.stderr or ev.stdout
            detail = detail.strip().replace("\n", " ")[:1000]
            chunks.append(f"{ev.name}: score={ev.score:.3f}; {detail}")
        return " | ".join(chunks)

    def _prompt(
        self,
        objective: str,
        run_id: str,
        iteration: int,
        best_score: float,
        run_plan: str | None,
        supervisor_directive: str | None,
    ) -> str:
        recent = self.store.recent_candidates(run_id, self.config.memory_window)
        memories = self.store.recent_memories(run_id, self.config.memory_window)
        lines = [
            f"OBJECTIVE\n{objective}",
            f"\nITERATION\n{iteration} of {self.config.max_iterations}",
            f"\nCURRENT BEST SCORE\n{best_score:.4f}",
        ]
        if run_plan:
            lines.append(f"\nRUN PLAN\n{run_plan}")
        if recent:
            lines.append("\nRECENT TRAJECTORY")
            for row in recent:
                text = (row["worker_output"] or row["worker_error"] or "").strip().replace("\n", " ")
                lines.append(
                    f"- i{row['iteration']}: score={row['score']:.4f}, improved={bool(row['improved'])}; "
                    f"worker note: {text[:800]}"
                )
        if memories:
            lines.append("\nEPISODIC MEMORY")
            for row in memories:
                if row["kind"] == "plan":
                    continue
                lines.append(f"- [{row['kind']}] {row['content'][:1400]}")
        if supervisor_directive:
            lines.append(f"\nSUPERVISOR DIRECTIVE\n{supervisor_directive}")
        lines.append(
            "\nTASK\nInspect the workspace, choose the highest-leverage next change, implement it, and run relevant "
            "checks. Preserve useful existing work. Do not only write a plan or explanation."
        )
        return "\n".join(lines)

    def _baseline(self, run_id: str, base_commit: str) -> tuple[float, list[EvaluationResult]]:
        wt = self.git.add_worktree(run_id, "baseline", base_commit, branch=None)
        try:
            return evaluate_all(wt.path, self.config.evaluators)
        finally:
            self.git.remove_worktree(wt)

    def _assist_allowed(self, worker_config: WorkerConfig) -> bool:
        if worker_config.execution_class != "cloud":
            return True
        budget = self.config.cloud_assist_budget
        return budget is None or self._cloud_assist_calls < budget

    def _record_assist_use(self, worker_config: WorkerConfig) -> None:
        if worker_config.execution_class == "cloud":
            self._cloud_assist_calls += 1

    def _run_planner(self, objective: str, run_id: str, base_commit: str) -> str | None:
        if not self.config.planner.enabled:
            return None
        worker_config = self.planner.worker_config
        if not self._assist_allowed(worker_config):
            self.store.add_memory(
                run_id,
                0,
                "planner-budget",
                "Upfront planner skipped because the cloud assist budget was exhausted.",
            )
            return None
        wt = self.git.add_worktree(run_id, "planner", base_commit, branch=None)
        try:
            plan, result = self.planner.plan(objective, wt.path)
            self.store.add_invocation(
                run_id,
                0,
                "planner",
                worker_config.execution_class,
                worker_config.backend,
                result,
            )
            self._record_assist_use(worker_config)
            self.store.add_memory(run_id, 0, "plan", plan)
            return plan
        finally:
            self.git.remove_worktree(wt)

    def run(self, objective: str) -> RunSummary:
        started = time.monotonic()
        self._cloud_assist_calls = 0
        self.git.validate(allow_dirty=self.config.allow_dirty_repo)
        run_id = uuid.uuid4().hex[:12]
        base_commit = self.git.head()
        baseline_score, baseline_evals = self._baseline(run_id, base_commit)
        self.store.create_run(
            run_id=run_id,
            objective=objective,
            repo_path=str(self.config.repo_path),
            base_commit=base_commit,
            best_score=baseline_score,
        )
        config_hash = hashlib.sha256(
            json.dumps(self.config.to_dict(), sort_keys=True).encode("utf-8")
        ).hexdigest()
        self.store.set_run_metadata(run_id, "config_hash", config_hash)
        self.store.set_run_metadata(run_id, "baseline_score", baseline_score)
        self.store.add_memory(
            run_id,
            0,
            "baseline",
            f"Baseline score={baseline_score:.4f}. {self._evaluation_memory(baseline_evals)}",
        )

        best_commit = base_commit
        best_score = baseline_score
        stagnant_rounds = 0
        last_supervised = -10_000
        directive: str | None = None
        run_plan: str | None = None
        iterations = 0
        status = "exhausted"

        try:
            if best_score >= self.config.acceptance_score:
                status = "accepted"
            else:
                run_plan = self._run_planner(objective, run_id, base_commit)
                for iteration in range(1, self.config.max_iterations + 1):
                    iterations = iteration
                    branch = f"{self.config.result_branch_prefix}/{run_id}/i-{iteration:04d}"
                    wt = self.git.add_worktree(
                        run_id, f"i-{iteration:04d}", best_commit, branch=branch
                    )
                    try:
                        prompt = self._prompt(
                            objective, run_id, iteration, best_score, run_plan, directive
                        )
                        directive = None
                        worker_result = self.worker.run(prompt, wt.path)
                        self.store.add_invocation(
                            run_id,
                            iteration,
                            "worker",
                            self.config.worker.execution_class,
                            self.config.worker.backend,
                            worker_result,
                        )
                        commit_sha = self.git.commit_all(
                            wt, f"avo: candidate {run_id} iteration {iteration}"
                        )
                        score, evaluations = evaluate_all(wt.path, self.config.evaluators)
                        improved = score > best_score + self.config.min_improvement
                        candidate = Candidate(
                            iteration=iteration,
                            branch=branch,
                            workspace=wt.path,
                            base_commit=best_commit,
                            commit_sha=commit_sha,
                            score=score,
                            worker=worker_result,
                            evaluations=evaluations,
                            improved=improved,
                        )
                        self.store.add_candidate(run_id, candidate)
                        self.store.add_memory(
                            run_id,
                            iteration,
                            "attempt",
                            f"score={score:.4f}; improved={improved}; "
                            f"{self._evaluation_memory(evaluations)}",
                        )

                        if improved:
                            best_score = score
                            best_commit = commit_sha
                            stagnant_rounds = 0
                            self.store.update_run_best(run_id, best_commit, best_score)
                        else:
                            stagnant_rounds += 1

                        if best_score >= self.config.acceptance_score:
                            status = "accepted"
                            break

                        supervisor_due = (
                            self.config.supervisor.enabled
                            and stagnant_rounds >= self.config.supervisor.stagnation_rounds
                            and iteration - last_supervised >= self.config.supervisor.cooldown_rounds
                        )
                        if supervisor_due:
                            supervisor_config = self.supervisor.worker_config
                            if self._assist_allowed(supervisor_config):
                                directive, supervisor_result = self.supervisor.advise(
                                    objective=objective,
                                    run_id=run_id,
                                    iteration=iteration,
                                    best_score=best_score,
                                    store=self.store,
                                    memory_window=self.config.memory_window,
                                )
                                self.store.add_invocation(
                                    run_id,
                                    iteration,
                                    "supervisor",
                                    supervisor_config.execution_class,
                                    supervisor_config.backend,
                                    supervisor_result,
                                )
                                self._record_assist_use(supervisor_config)
                            else:
                                directive = self.supervisor.fallback()
                                self.store.add_memory(
                                    run_id,
                                    iteration,
                                    "supervisor-budget",
                                    "Cloud supervisor skipped because the assist budget was exhausted; "
                                    "using deterministic fallback guidance.",
                                )
                            self.store.add_memory(
                                run_id, iteration, "supervisor", directive
                            )
                            last_supervised = iteration
                    finally:
                        if not self.config.keep_worktrees:
                            self.git.remove_worktree(wt)

            result_branch = f"{self.config.result_branch_prefix}/{run_id}/best"
            self.git.point_branch(result_branch, best_commit)
            self.store.finish_run(run_id, status)
            wall_seconds = time.monotonic() - started
            self.store.set_run_metadata(run_id, "wall_seconds", wall_seconds)
            invocation = self.store.invocation_summary(run_id)
            return RunSummary(
                run_id=run_id,
                status=status,
                baseline_score=baseline_score,
                best_score=best_score,
                best_commit=best_commit,
                result_branch=result_branch,
                iterations=iterations,
                wall_seconds=wall_seconds,
                local_invocations=int(invocation["local_invocations"]),
                cloud_invocations=int(invocation["cloud_invocations"]),
                planner_invocations=int(invocation["planner_invocations"]),
                supervisor_invocations=int(invocation["supervisor_invocations"]),
                reported_cost_usd=float(invocation["reported_cost_usd"]),
            )
        except Exception:
            self.store.finish_run(run_id, "failed")
            raise
