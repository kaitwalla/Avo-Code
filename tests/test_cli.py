from __future__ import annotations

import json
from pathlib import Path

from avo_harness.cli import build_parser


def test_init_writes_explicit_state_directory(tmp_path: Path) -> None:
    output = tmp_path / "avo.json"
    state = tmp_path / "persistent-state"
    parser = build_parser()
    args = parser.parse_args(
        [
            "init",
            "--repo",
            str(tmp_path),
            "--state-dir",
            str(state),
            "--output",
            str(output),
        ]
    )

    assert args.func(args) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["repo"] == str(tmp_path)
    assert payload["state_dir"] == str(state)
    assert payload["worker"]["adapter_id"] == "nvidia.fabric.hermes"
