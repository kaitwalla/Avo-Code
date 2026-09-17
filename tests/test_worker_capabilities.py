from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from avo_harness.config import WorkerConfig
from avo_harness.worker import NeMoWorker


class FakeFabricConfig:
    @classmethod
    def from_mapping(cls, payload):
        return payload


def test_deepagents_omits_unsupported_max_turns(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setitem(sys.modules, "nemo_fabric", SimpleNamespace(FabricConfig=FakeFabricConfig))
    worker = NeMoWorker(
        WorkerConfig(
            backend="nemo",
            adapter_id="nvidia.fabric.langchain.deepagents",
            provider="openai",
            model="smoke",
            max_turns=37,
            timeout_seconds=91,
        )
    )

    payload = worker._fabric_config(tmp_path)

    assert payload["runtime"] == {"timeout_seconds": 91}
