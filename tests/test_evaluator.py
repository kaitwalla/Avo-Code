from pathlib import Path

from avo_harness.config import EvaluatorConfig
from avo_harness.evaluator import evaluate_all, evaluate_one


def test_json_score_protocol(tmp_path: Path) -> None:
    spec = EvaluatorConfig(
        name="quality",
        command="python -c 'print(\"{\\\"score\\\": 0.75, \\\"summary\\\": \\\"better\\\"}\")'",
    )
    result = evaluate_one(tmp_path, spec)
    assert result.score == 0.75
    assert result.summary == "better"
    assert result.duration_seconds >= 0


def test_weighted_score(tmp_path: Path) -> None:
    specs = [
        EvaluatorConfig(name="a", command="python -c 'print(\"{\\\"score\\\": 1}\")'", weight=1),
        EvaluatorConfig(name="b", command="python -c 'print(\"{\\\"score\\\": 0}\")'", weight=3),
    ]
    score, _ = evaluate_all(tmp_path, specs)
    assert score == 0.25


def test_external_evaluator_workspace_substitution(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    oracle = tmp_path / "oracle"
    workspace.mkdir()
    oracle.mkdir()
    (workspace / "answer.txt").write_text("good\n", encoding="utf-8")
    script = oracle / "check.py"
    script.write_text(
        "import pathlib,sys,json; p=pathlib.Path(sys.argv[1])/'answer.txt'; "
        "ok=p.read_text().strip()=='good'; print(json.dumps({'score': 1 if ok else 0}))\n",
        encoding="utf-8",
    )
    result = evaluate_one(
        workspace,
        EvaluatorConfig(name="oracle", command="python check.py {workspace}"),
        cwd=oracle,
    )
    assert result.score == 1.0
