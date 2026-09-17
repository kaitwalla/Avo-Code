from __future__ import annotations

import os
import subprocess
from pathlib import Path

from avo_harness.gitops import _git


def test_git_uses_ephemeral_exact_safe_directory(monkeypatch, tmp_path: Path) -> None:
    repo = tmp_path / 'repo with spaces'
    repo.mkdir()
    observed: dict[str, str] = {}

    def fake_run(command, *, text, capture_output, env):
        config_path = Path(env['GIT_CONFIG_GLOBAL'])
        observed['config'] = config_path.read_text(encoding='utf-8')
        observed['global_path'] = str(config_path)
        observed['command'] = ' '.join(command)
        assert config_path.exists()
        return subprocess.CompletedProcess(command, 0, stdout='true\n', stderr='')

    monkeypatch.setattr(subprocess, 'run', fake_run)
    original_global = os.environ.get('GIT_CONFIG_GLOBAL')

    result = _git(repo, 'rev-parse', '--is-inside-work-tree')

    assert result.stdout.strip() == 'true'
    assert f'directory = "{repo.resolve()}"' in observed['config']
    assert 'directory = "*"' not in observed['config']
    assert observed['command'].startswith(f'git -C {repo.resolve()}')
    assert not Path(observed['global_path']).exists()
    assert os.environ.get('GIT_CONFIG_GLOBAL') == original_global
