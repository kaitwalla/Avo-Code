from __future__ import annotations

import subprocess
from pathlib import Path

from avo_harness.avogym import ExperimentSpec


ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "benchmarks" / "representative"


def test_representative_suite_prepares_real_failing_git_tasks() -> None:
    subprocess.run(["python", str(SUITE / "prepare.py")], check=True)
    spec = ExperimentSpec.load(SUITE / "experiment.json")

    assert len(spec.tasks) == 5
    assert {variant.name for variant in spec.variants} == {
        "hermes-single",
        "hermes-lazy-team",
        "deepagents-single",
        "deepagents-lazy-team",
        "codex-single",
        "codex-lazy-team",
        "goose-single",
        "goose-lazy-team",
    }

    tags = {tag for task in spec.tasks for tag in task.tags}
    assert {"bugfix", "repo-analysis", "migration", "infra", "feature"} <= tags

    for task in spec.tasks:
        assert (task.source / ".git").exists(), task.id
        visible = subprocess.run(
            ["python", "visible_test.py"],
            cwd=task.source,
            text=True,
            capture_output=True,
        )
        assert visible.returncode != 0, f"{task.id} baseline unexpectedly passes visible evaluator"

        hidden = subprocess.run(
            ["python", "oracle.py", str(task.source)],
            cwd=task.oracle_cwd,
            text=True,
            capture_output=True,
        )
        assert hidden.returncode != 0, f"{task.id} baseline unexpectedly passes hidden oracle"


def test_representative_suite_holds_model_constant_for_fabric_variants() -> None:
    spec = ExperimentSpec.load(SUITE / "experiment.json")
    base = spec.base_config.read_text(encoding="utf-8")
    assert '"base_url": "http://127.0.0.1:8000/v1"' in base
    assert '"model": "local-coder"' in base

    for variant in spec.variants:
        if variant.name.startswith("goose-"):
            continue
        worker = variant.overrides["worker"]
        assert "model" not in worker
        assert "base_url" not in worker
