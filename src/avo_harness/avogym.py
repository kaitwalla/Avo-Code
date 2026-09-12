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
from .strategy import build_strategy_policy


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
    input_tokens: int
    output_tokens: int
    role_invocations: int
    role_seconds: float
    role_breakdown: dict[str, dict[str, float | int]]
    run_id: str
    best_commit: str
    tags: list[str]

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(slots=True)
class BenchmarkReport:
    experiment: str
    trials: list[TrialResult]
    variants: dict[str, dict[str, Any]]
    routing_policy: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment": self.experiment,
            "trials": [asdict(item) for item in self.trials],
            "variants": self.variants,
            "routing_policy": self.routing_policy,
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


def _usage_number(value: Any, *names: str) -> int:
    if not isinstance(value, dict):
        return 0
    for name in names:
        item = value.get(name)
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            return int(item)
    for key in ("usage", "token_usage", "tokens"):
        nested = value.get(key)
        if isinstance(nested, dict):
            found = _usage_number(nested, *names)
            if found:
                return found
    return 0


def _role_metrics(rows: list[dict[str, Any]]) -> tuple[int, int, float, dict[str, dict[str, float | int]]]:
    input_tokens = 0
    output_tokens = 0
    seconds = 0.0
    breakdown: dict[str, dict[str, float | int]] = {}
    for row in rows:
        role = str(row.get("role", "unknown"))
        try:
            metadata = json.loads(row.get("metadata_json") or "{}")
        except json.JSONDecodeError:
            metadata = {}
        role_input = _usage_number(metadata, "input_tokens", "prompt_tokens", "input")
        role_output = _usage_number(metadata, "output_tokens", "completion_tokens", "output")
        role_seconds = float(row.get("duration_ms", 0) or 0) / 1000.0
        input_tokens += role_input
        output_tokens += role_output
        seconds += role_seconds
        bucket = breakdown.setdefault(
            role,
            {"invocations": 0, "input_tokens": 0, "output_tokens": 0, "seconds": 0.0},
        )
        bucket["invocations"] = int(bucket["invocations"]) + 1
        bucket["input_tokens"] = int(bucket["input_tokens"]) + role_input
        bucket["output_tokens"] = int(bucket["output_tokens"]) + role_output
        bucket["seconds"] = float(bucket["seconds"]) + role_seconds
    return input_tokens, output_tokens, seconds, breakdown


def _invocation_tokens(rows: list[dict[str, Any]], *, exclude_worker: bool) -> tuple[int, int]:
    selected = [row for row in rows if not (exclude_worker and row.get("role") == "worker")]
    return (
        sum(int(row.get("input_tokens") or 0) for row in selected),
        sum(int(row.get("output_tokens") or 0) for row in selected),
    )


def _variant_summary(trials: list[TrialResult]) -> dict[str, Any]:
    if not trials:
        return {}
    solves = sum(1 for trial in trials if trial.oracle_passed)
    tokens = sum(trial.total_tokens for trial in trials)
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
        "mean_role_invocations": mean(x.role_invocations for x in trials),
        "mean_role_seconds": mean(x.role_seconds for x in trials),
        "mean_input_tokens": mean(x.input_tokens for x in trials),
        "mean_output_tokens": mean(x.output_tokens for x in trials),
        "mean_total_tokens": mean(x.total_tokens for x in trials),
        "tokens_per_oracle_solve": (tokens / solves) if solves else None,
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
                role_rows = [dict(x) for x in store.recent_role_runs(summary.run_id, 100000)]
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
            role_input, role_output, role_seconds, role_breakdown = _role_metrics(role_rows)
            invocation_input, invocation_output = _invocation_tokens(
                invocation_rows, exclude_worker=bool(role_rows)
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
                input_tokens=invocation_input + role_input,
                output_tokens=invocation_output + role_output,
                role_invocations=len(role_rows),
                role_seconds=role_seconds,
                role_breakdown=role_breakdown,
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
        return BenchmarkReport(
            experiment=self.spec.name,
            trials=trials,
            variants=variants,
            routing_policy=build_strategy_policy(trials),
        )


def _report_paths(output: str | Path) -> tuple[Path, Path, Path]:
    output_path = Path(output)
    if output_path.suffix:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        return (
            output_path.with_suffix(".json"),
            output_path.with_suffix(".html"),
            output_path.with_name(output_path.stem + "-routing-policy.json"),
        )
    output_path.mkdir(parents=True, exist_ok=True)
    return output_path / "report.json", output_path / "report.html", output_path / "routing-policy.json"


def write_strategy_policy(report: BenchmarkReport, output: str | Path) -> Path:
    _, _, policy_path = _report_paths(output)
    policy_path.write_text(json.dumps(report.routing_policy, indent=2) + "\n", encoding="utf-8")
    return policy_path


def write_report(report: BenchmarkReport, output: str | Path) -> tuple[Path, Path]:
    json_path, html_path, _ = _report_paths(output)
    json_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")

    header = (
        "<tr><th>Variant</th><th>Trials</th><th>Oracle solve</th><th>Oracle score</th>"
        "<th>Visible score</th><th>Eval gap</th><th>Tokens</th><th>Tokens / solve</th>"
        "<th>Role calls</th><th>Role s</th><th>Cloud calls</th><th>Wall s</th><th>Cost $</th></tr>"
    )
    rows = []
    for name, metrics in report.variants.items():
        tokens_per_solve = metrics.get("tokens_per_oracle_solve")
        tokens_per_solve_text = "-" if tokens_per_solve is None else f"{float(tokens_per_solve):.0f}"
        rows.append(
            "<tr>"
            f"<td>{html.escape(name)}</td>"
            f"<td>{int(metrics.get('trials', 0))}</td>"
            f"<td>{float(metrics.get('oracle_solve_rate', 0)):.1%}</td>"
            f"<td>{float(metrics.get('mean_oracle_score', 0)):.3f}</td>"
            f"<td>{float(metrics.get('mean_visible_score', 0)):.3f}</td>"
            f"<td>{float(metrics.get('mean_evaluator_gap', 0)):.3f}</td>"
            f"<td>{float(metrics.get('mean_total_tokens', 0)):.0f}</td>"
            f"<td>{tokens_per_solve_text}</td>"
            f"<td>{float(metrics.get('mean_role_invocations', 0)):.2f}</td>"
            f"<td>{float(metrics.get('mean_role_seconds', 0)):.2f}</td>"
            f"<td>{float(metrics.get('mean_cloud_invocations', 0)):.2f}</td>"
            f"<td>{float(metrics.get('mean_wall_seconds', 0)):.2f}</td>"
            f"<td>{float(metrics.get('reported_cost_usd', 0)):.4f}</td>"
            "</tr>"
        )
    default = report.routing_policy.get("default") or {}
    default_text = html.escape(str(default.get("variant", "none")))
    document = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{html.escape(report.experiment)}</title>
<style>body{{font-family:system-ui,sans-serif;margin:2rem}}table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #bbb;padding:.45rem;text-align:right}}th:first-child,td:first-child{{text-align:left}}</style>
</head><body><h1>{html.escape(report.experiment)}</h1><p>Recommended default: <strong>{default_text}</strong></p><table><thead>{header}</thead><tbody>{''.join(rows)}</tbody></table></body></html>"""
    html_path.write_text(document, encoding="utf-8")
    return json_path, html_path
