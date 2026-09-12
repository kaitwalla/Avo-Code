from __future__ import annotations

import sys
from pathlib import Path

from avo_harness.config import TeamConfig, WorkerConfig
from avo_harness.team import TeamWorker


WORKER_SCRIPT = r'''
import re
import sys
from pathlib import Path
prompt = sys.stdin.read()
match = re.search(r"ROLE\n([^\n]+)", prompt)
role = match.group(1) if match else "unknown"
with Path("roles.log").open("a", encoding="utf-8") as handle:
    handle.write(role + "\n")
if role == "coder":
    Path("answer.txt").write_text("done\n", encoding="utf-8")
print(f"{role} completed")
'''


def base_worker() -> WorkerConfig:
    return WorkerConfig(backend="command", command=[sys.executable, "-c", WORKER_SCRIPT])


def prompt(iteration: int, objective: str = "fix the bug") -> str:
    return f"OBJECTIVE\n{objective}\n\nITERATION\n{iteration} of 4\n\nCURRENT BEST SCORE\n0.0"


def test_simple_first_iteration_uses_only_primary_coder(tmp_path: Path) -> None:
    team = TeamWorker(TeamConfig(enabled=True), base_worker())
    result = team.run(prompt(1), tmp_path)
    assert result.success
    assert (tmp_path / "roles.log").read_text().splitlines() == ["coder"]
    assert result.metadata["team_roles"] == ["coder"]


def test_retry_progressively_activates_architect_then_researcher(tmp_path: Path) -> None:
    team = TeamWorker(TeamConfig(enabled=True), base_worker())
    result2 = team.run(prompt(2), tmp_path)
    assert result2.success
    assert result2.metadata["team_roles"] == ["architect", "orchestrator", "coder"]
    (tmp_path / "roles.log").unlink()
    result3 = team.run(prompt(3), tmp_path)
    assert result3.success
    assert result3.metadata["team_roles"] == [
        "architect", "researcher", "orchestrator", "coder",
    ]


def test_infrastructure_trigger_is_lazy_and_runs_before_coder(tmp_path: Path) -> None:
    team = TeamWorker(TeamConfig(enabled=True), base_worker())
    result = team.run(prompt(1, "fix the docker compose deployment"), tmp_path)
    assert result.success
    assert result.metadata["team_roles"] == ["infrastructure", "coder"]


def test_explicit_role_request_forces_specialist(tmp_path: Path) -> None:
    team = TeamWorker(TeamConfig(enabled=True), base_worker())
    result = team.run(prompt(1, "@researcher check this behavior then fix it"), tmp_path)
    assert result.success
    assert result.metadata["team_roles"] == ["researcher", "coder"]
