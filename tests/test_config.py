from avo_harness.config import AVOConfig


def test_team_roles_inherit_shared_worker_and_allow_sparse_model_override() -> None:
    config = AVOConfig.from_dict(
        {
            "repo": ".",
            "worker": {
                "backend": "command",
                "command": ["echo", "ok"],
                "model": "shared-model",
                "env": {"SHARED": "1"},
                "mcp": {"servers": {"github": {"transport": "stdio", "url": "github-mcp"}}},
            },
            "team": {
                "enabled": True,
                "roles": {
                    "architect": {"worker": {"model": "reasoner", "env": {"ROLE": "arch"}}}
                },
            },
            "evaluators": [{"name": "tests", "command": "true"}],
        }
    )
    workers = config.team.resolved_workers(config.worker)
    assert workers["coder"].model == "shared-model"
    assert workers["coder"].mcp == config.worker.mcp
    assert workers["architect"].model == "reasoner"
    assert workers["architect"].mcp == config.worker.mcp
    assert workers["architect"].env == {"SHARED": "1", "ROLE": "arch"}
