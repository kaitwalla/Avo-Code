from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from avo_harness.config import (
    AVOConfig,
    EvaluatorConfig,
    PlannerConfig,
    SupervisorConfig,
    WorkerConfig,
)
from avo_harness.orchestrator import Orchestrator


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], text=True, capture_output=True, check=True)
    return proc.stdout.strip()


def init_repo(repo: Path) -> None:
    repo.mkdir()
    git(repo, "init")
    (repo / "README.md").write_text("start\n", encoding="utf-8")
    git(repo, "add", ".")
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "init"],
        check=True,
        capture_output=True,
        text=True,
    )


def answer_evaluator() -> str:
    return (
        "import json, pathlib, sys; "
        "p=pathlib.Path('answer.txt'); ok=p.exists() and p.read_text().strip()=='good'; "
        "print(json.dumps({'score': 1.0 if ok else 0.0, 'summary': 'ok' if ok else 'missing'})); "
        "sys.exit(0 if ok else 1)"
    )


def test_end_to_end_candidate_lineage(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    worker_script = (
        "from pathlib import Path; "
        "Path('answer.txt').write_text('good\\n', encoding='utf-8'); "
        "print('implemented answer')"
    )
    config = AVOConfig(
        repo=str(repo),
        state_dir=str(tmp_path / "state"),
        max_iterations=2,
        worker=WorkerConfig(backend="command", command=[sys.executable, "-c", worker_script]),
        supervisor=SupervisorConfig(enabled=False),
        evaluators=[EvaluatorConfig(name="answer", command=f"{sys.executable} -c \"{answer_evaluator()}\"")],
    )
    orchestrator = Orchestrator(config)
    try:
        summary = orchestrator.run("create answer.txt containing good")
    finally:
        orchestrator.close()

    assert summary.status == "accepted"
    assert summary.best_score == 1.0
    assert summary.baseline_score == 0.0
    assert summary.local_invocations == 1
    assert git(repo, "rev-parse", summary.result_branch) == summary.best_commit
    assert git(repo, "show", f"{summary.best_commit}:answer.txt") == "good"


def test_cloud_planner_guides_local_worker_and_counts_budget(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    planner_script = "print('Create answer.txt containing good before doing anything else.')"
    worker_script = (
        "import sys; from pathlib import Path; p=sys.stdin.read(); "
        "Path('answer.txt').write_text('good\\n', encoding='utf-8') if 'RUN PLAN' in p and 'answer.txt' in p else None; "
        "print('worker finished')"
    )
    config = AVOConfig(
        repo=str(repo),
        state_dir=str(tmp_path / "state"),
        max_iterations=2,
        cloud_assist_budget=1,
        worker=WorkerConfig(
            backend="command", command=[sys.executable, "-c", worker_script], execution_class="local"
        ),
        planner=PlannerConfig(
            enabled=True,
            worker=WorkerConfig(
                backend="command", command=[sys.executable, "-c", planner_script], execution_class="cloud"
            ),
        ),
        supervisor=SupervisorConfig(enabled=False),
        evaluators=[EvaluatorConfig(name="answer", command=f"{sys.executable} -c \"{answer_evaluator()}\"")],
    )
    orchestrator = Orchestrator(config)
    try:
        summary = orchestrator.run("make the requested repository change")
    finally:
        orchestrator.close()

    assert summary.status == "accepted"
    assert summary.planner_invocations == 1
    assert summary.cloud_invocations == 1
    assert summary.local_invocations == 1


def test_cloud_assist_budget_prevents_extra_cloud_supervision(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    noop = "print('no change')"
    config = AVOConfig(
        repo=str(repo),
        state_dir=str(tmp_path / "state"),
        max_iterations=2,
        cloud_assist_budget=1,
        worker=WorkerConfig(
            backend="command", command=[sys.executable, "-c", noop], execution_class="local"
        ),
        planner=PlannerConfig(
            enabled=True,
            worker=WorkerConfig(
                backend="command", command=[sys.executable, "-c", "print('plan')"], execution_class="cloud"
            ),
        ),
        supervisor=SupervisorConfig(
            enabled=True,
            stagnation_rounds=1,
            cooldown_rounds=1,
            worker=WorkerConfig(
                backend="command", command=[sys.executable, "-c", "print('supervise')"], execution_class="cloud"
            ),
        ),
        evaluators=[EvaluatorConfig(name="never", command=f"{sys.executable} -c \"import sys; sys.exit(1)\"")],
    )
    orchestrator = Orchestrator(config)
    try:
        summary = orchestrator.run("a deliberately unsolved task")
    finally:
        orchestrator.close()

    assert summary.status == "exhausted"
    assert summary.cloud_invocations == 1
    assert summary.planner_invocations == 1
    assert summary.supervisor_invocations == 0
    assert summary.local_invocations == 2
