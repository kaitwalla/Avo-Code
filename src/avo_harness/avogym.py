from __future__ import annotations

import copy
import html
import json
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any

from .config import AVOConfig, EvaluatorConfig
from .evaluator import evaluate_all
from .gitops import GitRepo
from .orchestrator import Orchestrator
from .store import Store


@dataclass(slots=True)
class VariantSpec:
    name: str
    overrides: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TaskSpec:
    id: str
    objective: str
    source: Path
    oracle: list[EvaluatorConfig]
    oracle_cwd: Path
    tags: list[str] = field(default_factory=list)
    config_overrides: dict[str, Any] = field(default_factory=dict)
    oracle_acceptance_score: float = 1.0


@dataclass(slots=True)
class ExperimentSpec:
    name: str
    base_config: Path
    variants: list[VariantSpec]
    tasks: list[TaskSpec]
    seeds: list[int]
    root: Path

    @classmethod
    def load(cls, path: str | Path) -> "ExperimentSpec":
        experiment_path = Path(path).resolve()
        root = experiment_path.parent
        raw = json.loads(experiment_path.read_text(encoding="utf-8"))
        variants = [
            VariantSpec(name=item["name"], overrides=dict(item.get("overrides", {})))
            for item in raw.get("variants", [{"name": "default"}])
        ]
        tasks: list[TaskSpec] = []
        for item in raw.get("tasks", []):
            source = (root / item["source"]).resolve()
            oracle_cwd = (root / item.get("oracle_cwd", ".")).resolve()
            tasks.append(
                TaskSpec(
                    id=item["id"],
                    objective=item["objective"],
                    source=source,
                    oracle=[EvaluatorConfig.from_dict(x) for x in item.get("oracle", [])],
                    oracle_cwd=oracle_cwd,
                    tags=list(item.get("tags", [])),
                    config_overrides=dict(item.get("config_overrides", {})),
                    oracle_acceptance_score=float(item.get("oracle_acceptance_score", 1.0)),
                )
            )
        if not tasks:
            raise ValueError("AvoGym experiment requires at least one task")
        if any(not task.oracle for task in tasks):
            raise ValueError("every AvoGym task requires at least one hidden oracle evaluator")
        return cls(
            name=raw.get("name", experiment_path.stem),
            base_config=(root / raw["base_config"]).resolve(),
            variants=variants,
            tasks=tasks,
            seeds=[int(x) for x in raw.get("seeds", [0])],
            root=root,
        )


@dataclass(slots=True)
class TrialResult:
    experiment: str
    task_id: str
    variant: str
    seed: int
    status: str
    baseline_score: float
    visible_score: float
    oracle_score: float
    oracle_passed: bool
    score_gain: float
    progress_auc: float
    evaluator_gap: float
    iterations: int
    wall_seconds: float
    local_invocations: int
    cloud_invocations: int
    planner_invocations: int
    supervisor_invocations: int
    supervisor_uplift: float
    reported_cost_usd: float
    run_id: str
    best_commit: str
    tags: list[str]


@dataclass(slots=True)
class BenchmarkReport:
    experiment: str
    trials: list[TrialResult]
    variants: dict[str, dict[str, float | int]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment": self.experiment,
            "trials": [asdict(item) for item in self.trials],
            "variants": self.variants,
        }


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _git_clone(source: Path, destination: Path) -> None:
    proc = subprocess.run(
        ["git", "clone", "--quiet", "--no-hardlinks", str(source), str(destination)],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"failed to clone AvoGym task source {source}: {proc.stderr.strip()}")


def _progress_auc(baseline: float, candidates: list[dict[str, Any]]) -> float:
    progression = [baseline]
    incumbent = baseline
    for row in candidates:
        incumbent = max(incumbent, float(row["score"]))
        progression.append(incumbent)
    return sum(progression) / len(progression)


def _supervisor_uplift(
    baseline: float,
    candidates: list[dict[str, Any]],
    invocations: list[dict[str, Any]],
) -> float:
    supervisor_iterations = [
        int(row["iteration"]) for row in invocations if row["role"] == "supervisor"
    ]
    if not supervisor_iterations:
        return 0.0
    improvements: list[float] = []
    for iteration in supervisor_iterations:
        before = baseline
        for row in candidates:
            if int(row["iteration"]) <= iteration:
                before = max(before, float(row["score"]))
        after_scores = [
            float(row["score"]) for row in candidates if int(row["iteration"]) > iteration
        ]
        if after_scores:
            improvements.append(max(0.0, max(after_scores) - before))
    return mean(improvements) if improvements else 0.0


def _variant_summary(trials: list[TrialResult]) -> dict[str, float | int]:
    if not trials:
        return {}
    return {
        "trials": len(trials),
        "oracle_solve_rate": mean(1.0 if x.oracle_passed else 0.0 for x in trials),
        "mean_oracle_score": mean(x.oracle_score for x in trials),
        "mean_visible_score": mean(x.visible_score for x in trials),
        "mean_score_gain": mean(x.score_gain for x in trials),
        "mean_progress_auc": mean(x.progress_auc for x in trials),
        "mean_evaluator_gap": mean(x.evaluator_gap for x in trials),
        "mean_iterations": mean(x.iterations for x in trials),
        "mean_wall_seconds": mean(x.wall_seconds for x in trials),
        "mean_cloud_invocations": mean(x.cloud_invocations for x in trials),
        "mean_local_invocations": mean(x.local_invocations for x in trials),
        "mean_supervisor_uplift": mean(x.supervisor_uplift for x in trials),
        "reported_cost_usd": sum(x.reported_cost_usd for x in trials),
    }


class BenchmarkRunner:
    def __init__(self, spec: ExperimentSpec):
        self.spec = spec
        self.base_config = json.loads(spec.base_config.read_text(encoding="utf-8"))

    def _run_trial(self, task: TaskSpec, variant: VariantSpec, seed: int) -> TrialResult:
        with tempfile.TemporaryDirectory(prefix="avogym-") as tmp:
            root = Path(tmp)
            repo = root / "repo"
            state = root / "state"
            _git_clone(task.source, repo)

            raw = _deep_merge(self.base_config, task.config_overrides)
            raw = _deep_merge(raw, variant.overrides)
            raw["repo"] = str(repo)
            raw["state_dir"] = str(state)
            worker = raw.setdefault("worker", {})
            worker.setdefault("env", {})["AVO_GYM_SEED"] = str(seed)
            config = AVOConfig.from_dict(raw)

            orchestrator = Orchestrator(config)
            try:
                summary = orchestrator.run(task.objective)
            finally:
                orchestrator.close()

            store = Store(state / "state.sqlite3")
            try:
                candidate_rows = [dict(x) for x in store.list_candidates(summary.run_id)]
                invocation_rows = [dict(x) for x in store.list_invocations(summary.run_id)]
            finally:
                store.close()

            git = GitRepo(repo, state / "oracle-worktrees")
            wt = git.add_worktree(summary.run_id, "oracle-final", summary.best_commit, branch=None)
            try:
                oracle_score, _ = evaluate_all(
                    wt.path,
                    task.oracle,
                    cwd=task.oracle_cwd,
                    variables={"task": str(task.oracle_cwd)},
                )
            finally:
                git.remove_worktree(wt)

            progress_auc = _progress_auc(summary.baseline_score, candidate_rows)
            supervisor_uplift = _supervisor_uplift(
                summary.baseline_score, candidate_rows, invocation_rows
            )
            return TrialResult(
                experiment=self.spec.name,
                task_id=task.id,
                variant=variant.name,
                seed=seed,
                status=summary.status,
                baseline_score=summary.baseline_score,
                visible_score=summary.best_score,
                oracle_score=oracle_score,
                oracle_passed=oracle_score >= task.oracle_acceptance_score,
                score_gain=summary.best_score - summary.baseline_score,
                progress_auc=progress_auc,
                evaluator_gap=summary.best_score - oracle_score,
                iterations=summary.iterations,
                wall_seconds=summary.wall_seconds,
                local_invocations=summary.local_invocations,
                cloud_invocations=summary.cloud_invocations,
                planner_invocations=summary.planner_invocations,
                supervisor_invocations=summary.supervisor_invocations,
                supervisor_uplift=supervisor_uplift,
                reported_cost_usd=summary.reported_cost_usd,
                run_id=summary.run_id,
                best_commit=summary.best_commit,
                tags=task.tags,
            )

    def run(self) -> BenchmarkReport:
        trials = [
            self._run_trial(task, variant, seed)
            for variant in self.spec.variants
            for task in self.spec.tasks
            for seed in self.spec.seeds
        ]
        variants = {
            variant.name: _variant_summary([x for x in trials if x.variant == variant.name])
            for variant in self.spec.variants
        }
        return BenchmarkReport(experiment=self.spec.name, trials=trials, variants=variants)


def write_report(report: BenchmarkReport, output: str | Path) -> tuple[Path, Path]:
    output_path = Path(output)
    if output_path.suffix:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        json_path = output_path.with_suffix(".json")
        html_path = output_path.with_suffix(".html")
    else:
        output_path.mkdir(parents=True, exist_ok=True)
        json_path = output_path / "report.json"
        html_path = output_path / "report.html"
    json_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")

    header = (
        "<tr><th>Variant</th><th>Trials</th><th>Oracle solve</th><th>Oracle score</th>"
        "<th>Visible score</th><th>Eval gap</th><th>AUC</th><th>Cloud calls</th><th>Local calls</th>"
        "<th>Wall s</th></tr>"
    )
    rows = []
    for name, metrics in report.variants.items():
        rows.append(
            "<tr>"
            f"<td>{html.escape(name)}</td>"
            f"<td>{int(metrics.get('trials', 0))}</td>"
            f"<td>{float(metrics.get('oracle_solve_rate', 0)):.1%}</td>"
            f"<td>{float(metrics.get('mean_oracle_score', 0)):.3f}</td>"
            f"<td>{float(metrics.get('mean_visible_score', 0)):.3f}</td>"
            f"<td>{float(metrics.get('mean_evaluator_gap', 0)):.3f}</td>"
            f"<td>{float(metrics.get('mean_progress_auc', 0)):.3f}</td>"
            f"<td>{float(metrics.get('mean_cloud_invocations', 0)):.2f}</td>"
            f"<td>{float(metrics.get('mean_local_invocations', 0)):.2f}</td>"
            f"<td>{float(metrics.get('mean_wall_seconds', 0)):.2f}</td>"
            "</tr>"
        )
    document = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{html.escape(report.experiment)}</title>
<style>body{{font-family:system-ui,sans-serif;margin:2rem}}table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #bbb;padding:.45rem;text-align:right}}th:first-child,td:first-child{{text-align:left}}</style>
</head><body><h1>{html.escape(report.experiment)}</h1><table><thead>{header}</thead><tbody>{''.join(rows)}</tbody></table></body></html>"""
    html_path.write_text(document, encoding="utf-8")
    return json_path, html_path
