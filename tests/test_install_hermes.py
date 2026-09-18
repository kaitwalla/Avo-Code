from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest


def load_installer():
    path = Path(__file__).parents[1] / 'scripts' / 'install_hermes.py'
    spec = importlib.util.spec_from_file_location('install_hermes', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_checkout_rejects_existing_repository_with_wrong_origin(monkeypatch, tmp_path: Path) -> None:
    installer = load_installer()
    destination = tmp_path / 'hermes-agent'
    (destination / '.git').mkdir(parents=True)
    commands: list[tuple[str, ...]] = []

    def fake_run(command, **kwargs):
        command = tuple(command)
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout='https://example.invalid/not-hermes.git\n')

    monkeypatch.setattr(subprocess, 'run', fake_run)

    with pytest.raises(SystemExit, match='unexpected origin'):
        installer.checkout(destination, installer.DEFAULT_HERMES_REF)

    assert commands == [('git', '-C', str(destination), 'remote', 'get-url', 'origin')]


def test_checkout_fetches_existing_repository_with_expected_origin(monkeypatch, tmp_path: Path) -> None:
    installer = load_installer()
    destination = tmp_path / 'hermes-agent'
    (destination / '.git').mkdir(parents=True)
    commands: list[tuple[str, ...]] = []

    def fake_run(command, **kwargs):
        command = tuple(command)
        commands.append(command)
        stdout = installer.HERMES_REPOSITORY + '\n' if command[-3:] == ('remote', 'get-url', 'origin') else ''
        return subprocess.CompletedProcess(command, 0, stdout=stdout)

    monkeypatch.setattr(subprocess, 'run', fake_run)

    installer.checkout(destination, installer.DEFAULT_HERMES_REF)

    assert commands == [
        ('git', '-C', str(destination), 'remote', 'get-url', 'origin'),
        ('git', '-C', str(destination), 'fetch', '--depth', '1', 'origin', installer.DEFAULT_HERMES_REF),
        ('git', '-C', str(destination), 'checkout', '--detach', 'FETCH_HEAD'),
    ]
