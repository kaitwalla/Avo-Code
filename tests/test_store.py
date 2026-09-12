from pathlib import Path

from avo_harness.models import Candidate, EvaluationResult, WorkerResult
from avo_harness.store import Store


def test_store_persists_lineage_memory_and_role_runs(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.sqlite3")
    store.create_run("r1", "fix it", "/repo", "abc", 0.2)
    candidate = Candidate(
        iteration=1,
        branch="avo/r1/i-1",
        workspace=tmp_path,
        base_commit="abc",
        commit_sha="def",
        score=0.8,
        worker=WorkerResult(
            success=True,
            output="done",
            metadata={
                "role_runs": [
                    {
                        "sequence": 1,
                        "role": "coder",
                        "reason": "primary",
                        "success": True,
                        "duration_ms": 12,
                        "output": "done",
                        "error": "",
                        "metadata": {"usage": {"input_tokens": 10}},
                    }
                ]
            },
        ),
        evaluations=[EvaluationResult("tests", 0.8, 1, False, 1, summary="one failure")],
        improved=True,
    )
    store.add_candidate("r1", candidate)
    store.add_memory("r1", 1, "attempt", "one failure remains")
    store.update_run_best("r1", "def", 0.8)

    run = store.get_run("r1")
    assert run is not None
    assert run["best_commit"] == "def"
    assert store.recent_candidates("r1", 3)[0]["score"] == 0.8
    assert store.recent_memories("r1", 3)[0]["kind"] == "attempt"
    role = store.recent_role_runs("r1", 3)[0]
    assert role["role"] == "coder"
    assert role["duration_ms"] == 12
    assert '"input_tokens": 10' in role["metadata_json"]
    store.close()
