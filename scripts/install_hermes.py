#!/usr/bin/env python3
"""Install the pinned Hermes Agent source into the current Python environment.

Hermes Agent 0.20+ intentionally does not support wheel/sdist builds. Keep this
helper as Avo's single installation path so local development, CI, and Docker all
use the same source ref, interpreter, and durable editable checkout.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERMES_REPOSITORY = "https://github.com/NousResearch/hermes-agent.git"
DEFAULT_HERMES_REF = "v2026.8.19"


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def require_supported_python() -> None:
    if (3, 11) <= sys.version_info[:2] < (3, 14):
        return
    raise SystemExit(
        "Hermes Agent requires Python 3.11 through 3.13; "
        f"this interpreter is Python {sys.version_info.major}.{sys.version_info.minor}."
    )


def checkout(destination: Path, ref: str) -> None:
    if destination.exists():
        if not (destination / ".git").is_dir():
            raise SystemExit(
                f"refusing to replace non-git path used for Hermes Agent: {destination}"
            )
        run("git", "-C", str(destination), "fetch", "--depth", "1", "origin", ref)
        run("git", "-C", str(destination), "checkout", "--detach", "FETCH_HEAD")
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    run(
        "git",
        "clone",
        "--depth",
        "1",
        "--branch",
        ref,
        HERMES_REPOSITORY,
        str(destination),
    )


def main() -> None:
    require_supported_python()
    root = Path(__file__).resolve().parents[1]
    destination = (
        Path(sys.argv[1]).expanduser().resolve()
        if len(sys.argv) > 1
        else root / ".deps" / "hermes-agent"
    )
    ref = os.environ.get("HERMES_AGENT_REF", DEFAULT_HERMES_REF).strip()
    if not ref:
        raise SystemExit("HERMES_AGENT_REF cannot be empty")

    checkout(destination, ref)
    # Hermes 0.20.x deliberately refuses wheel/sdist builds and supports source
    # installation through an editable checkout. This checkout is therefore a
    # runtime dependency: Docker keeps it under /opt, and local installs keep it
    # under .deps unless the caller provides another durable destination.
    run(sys.executable, "-m", "pip", "install", "-e", str(destination))

    # Fail immediately if the source checkout did not install the expected
    # distribution into this exact interpreter.
    run(
        sys.executable,
        "-c",
        (
            "from importlib.metadata import version; "
            "v=version('hermes-agent'); "
            "print(f'Hermes Agent installed: {v}')"
        ),
    )
    print(f"Hermes Agent source checkout (required at runtime): {destination}")


if __name__ == "__main__":
    main()
