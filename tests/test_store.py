from pathlib import Path

from avo_harness.models import Candidate, EvaluationResult, WorkerResult
from avo_harness.store import Store


def test_store_persists_lineage_memory_and_invocations(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.sqlite3")
    store.create_run("r1", "fix it", "/repo", "abc", 0.2)
    store.set_run_metadata("r1", "baseline_score", 0.2)
    candidate = Candidate(
        iteration=1,
        branch="avo/r1/i-1",
        workspace=tmp_path,
        base_commit="abc",
        commit_sha="def",
        score=0.8,
        worker=WorkerResult(success=True, output="done", duration_seconds=1.5),
        evaluations=[EvaluationResult("tests", 0.8, 1, False, 1, summary="one failure")],
        improved=True,
    )
    store.add_candidate("r1", candidate)
    store.add_memory("r1", 1, "attempt", "one failure remains")
    store.add_invocation("r1", 1, "worker", "local", "command", candidate.worker)
    store.update_run_best("r1", "def", 0.8)

    run = store.get_run("r1")
    assert run is not None
    assert run["best_commit"] == "def"
    assert store.get_run_metadata("r1")["baseline_score"] == 0.2
    assert store.recent_candidates("r1", 3)[0]["score"] == 0.8
    assert store.recent_memories("r1", 3)[0]["kind"] == "attempt"
    summary = store.invocation_summary("r1")
    assert summary["local_invocations"] == 1
    assert summary["cloud_invocations"] == 0
    store.close()
