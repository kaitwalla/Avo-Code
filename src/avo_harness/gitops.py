from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


class GitError(RuntimeError):
    pass


def _git_config_value(value: str) -> str:
    """Quote a value for Git's config-file syntax."""

    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


@contextmanager
def _trusted_repo_env(repo: Path) -> Iterator[dict[str, str]]:
    """Give one Git subprocess a protected exact-path safe.directory entry.

    Host bind mounts commonly appear to be owned by a different UID inside a
    container, which makes modern Git reject them before Avo can even inspect the
    repository. Writing `safe.directory=*` would disable that protection globally.
    Instead, each Avo Git command receives a short-lived global config containing
    only the exact path it was asked to operate on. The user's normal environment
    remains untouched after the subprocess exits.
    """

    trusted = repo.resolve()
    env = os.environ.copy()
    for key in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_COMMON_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_PREFIX",
    ):
        env.pop(key, None)
    with tempfile.TemporaryDirectory(prefix="avo-git-config-") as directory:
        config = Path(directory) / "gitconfig"
        config.write_text(
            "[safe]\n"
            f"\tdirectory = {_git_config_value(str(trusted))}\n",
            encoding="utf-8",
        )
        env["GIT_CONFIG_GLOBAL"] = str(config)
        yield env


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    repo = repo.resolve()
    with _trusted_repo_env(repo) as env:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            text=True,
            capture_output=True,
            env=env,
        )
    if check and proc.returncode != 0:
        raise GitError(proc.stderr.strip() or proc.stdout.strip() or "git command failed")
    return proc


@dataclass(slots=True)
class Worktree:
    path: Path
    branch: str
    base_commit: str
    detached: bool = False


class GitRepo:
    def __init__(self, repo: Path, worktree_root: Path):
        self.repo = repo.resolve()
        self.worktree_root = worktree_root.resolve()

    def validate(self, allow_dirty: bool = False) -> None:
        if not self.repo.exists():
            raise GitError(f"repository does not exist: {self.repo}")
        inside = _git(self.repo, "rev-parse", "--is-inside-work-tree").stdout.strip()
        if inside != "true":
            raise GitError(f"not a git worktree: {self.repo}")
        if not allow_dirty and _git(self.repo, "status", "--porcelain").stdout.strip():
            raise GitError(
                "target repository has uncommitted changes; commit/stash them or set allow_dirty_repo=true"
            )

    def head(self) -> str:
        return _git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def add_worktree(
        self,
        run_id: str,
        label: str,
        base_commit: str,
        branch: str | None,
    ) -> Worktree:
        path = self.worktree_root / run_id / label
        if path.exists():
            shutil.rmtree(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if branch:
            _git(self.repo, "worktree", "add", "-b", branch, str(path), base_commit)
            return Worktree(path=path, branch=branch, base_commit=base_commit)
        _git(self.repo, "worktree", "add", "--detach", str(path), base_commit)
        return Worktree(path=path, branch="(detached)", base_commit=base_commit, detached=True)

    def commit_all(self, worktree: Worktree, message: str) -> str:
        status = _git(worktree.path, "status", "--porcelain").stdout.strip()
        if not status:
            return _git(worktree.path, "rev-parse", "HEAD").stdout.strip()
        _git(worktree.path, "add", "-A")
        _git(
            worktree.path,
            "-c",
            "user.name=AVO Harness",
            "-c",
            "user.email=avo-harness@localhost",
            "commit",
            "-m",
            message,
        )
        return _git(worktree.path, "rev-parse", "HEAD").stdout.strip()

    def remove_worktree(self, worktree: Worktree) -> None:
        _git(self.repo, "worktree", "remove", "--force", str(worktree.path), check=False)
        if worktree.path.exists():
            shutil.rmtree(worktree.path, ignore_errors=True)

    def point_branch(self, branch: str, commit_sha: str) -> None:
        _git(self.repo, "branch", "-f", branch, commit_sha)
