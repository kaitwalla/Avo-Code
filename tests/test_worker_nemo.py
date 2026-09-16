from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

from avo_harness.config import WorkerConfig
from avo_harness.worker import NeMoWorker, _nemo_failure


class FakeFabricConfig:
    @classmethod
    def from_mapping(cls, payload):
        return payload


class FakeFabric:
    last_config = None
    adapter_python_seen = None

    async def run(self, config, *, input):
        type(self).last_config = config
        type(self).adapter_python_seen = os.environ.get("ADAPTER_PYTHON")
        return SimpleNamespace(
            output=SimpleNamespace(response=f"done: {input}"),
            error=None,
            status="completed",
            usage=None,
            telemetry=None,
            events=[],
        )


def install_fake_fabric(monkeypatch) -> None:
    FakeFabric.last_config = None
    FakeFabric.adapter_python_seen = None
    monkeypatch.setitem(
        sys.modules,
        "nemo_fabric",
        SimpleNamespace(Fabric=FakeFabric, FabricConfig=FakeFabricConfig),
    )


def nemo_config(adapter_id: str, **kwargs) -> WorkerConfig:
    return WorkerConfig(
        backend="nemo",
        adapter_id=adapter_id,
        model="smoke",
        provider="openai",
        base_url="http://127.0.0.1:1/v1",
        **kwargs,
    )


def test_codex_omits_unsupported_max_turns(monkeypatch, tmp_path: Path) -> None:
    install_fake_fabric(monkeypatch)
    worker = NeMoWorker(nemo_config("nvidia.fabric.codex", max_turns=37, timeout_seconds=91))

    result = asyncio.run(worker._run("fix it", tmp_path))

    assert result.success is True
    assert FakeFabric.last_config["runtime"] == {"timeout_seconds": 91}


def test_hermes_keeps_max_turns(monkeypatch, tmp_path: Path) -> None:
    install_fake_fabric(monkeypatch)
    worker = NeMoWorker(nemo_config("nvidia.fabric.hermes", max_turns=37, timeout_seconds=91))

    result = asyncio.run(worker._run("fix it", tmp_path))

    assert result.success is True
    assert FakeFabric.last_config["runtime"] == {
        "timeout_seconds": 91,
        "max_turns": 37,
    }


def test_adapter_python_is_scoped_to_one_worker(monkeypatch, tmp_path: Path) -> None:
    install_fake_fabric(monkeypatch)
    monkeypatch.delenv("ADAPTER_PYTHON", raising=False)
    adapter_python = str(tmp_path / "codex-venv" / "bin" / "python")
    worker = NeMoWorker(
        nemo_config(
            "nvidia.fabric.codex",
            env={"ADAPTER_PYTHON": adapter_python, "KEEP_ME": "yes"},
        )
    )

    result = worker.run("fix it", tmp_path)

    assert result.success is True
    assert FakeFabric.adapter_python_seen == adapter_python
    assert os.environ.get("ADAPTER_PYTHON") is None
    assert FakeFabric.last_config["environment"]["env"] == {"KEEP_ME": "yes"}
    assert result.metadata["adapter_python"] == adapter_python


def test_unknown_adapter_error_explains_install_and_isolation() -> None:
    message = _nemo_failure(
        RuntimeError("unknown adapter nvidia.fabric.hermes"),
        "nvidia.fabric.hermes",
    )

    assert "nemo-fabric[hermes-agent]" in message
    assert "ADAPTER_PYTHON" in message
