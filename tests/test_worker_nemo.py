from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from avo_harness.config import WorkerConfig
from avo_harness.worker import NeMoWorker, _adapter_python_env, _nemo_failure


class FakeFabricConfig:
    @classmethod
    def from_mapping(cls, payload):
        return payload


class FakeFabric:
    last_config = None
    last_base_dir = None
    adapter_python_seen = None

    def plan(self, config, *, base_dir=None):
        type(self).last_config = config
        type(self).last_base_dir = base_dir
        return SimpleNamespace(
            adapter=SimpleNamespace(adapter_id=config["harness"]["adapter_id"])
        )

    async def doctor(self, config, *, base_dir=None):
        type(self).last_config = config
        type(self).last_base_dir = base_dir
        return SimpleNamespace(status="pass", checks=[])

    async def run(self, config, *, base_dir=None, input):
        type(self).last_config = config
        type(self).last_base_dir = base_dir
        type(self).adapter_python_seen = os.environ.get("ADAPTER_PYTHON")
        return SimpleNamespace(
            output=SimpleNamespace(response=f"done: {input}"),
            error=None,
            status="completed",
            usage=None,
            telemetry=None,
            events=[],
        )


class FailingDoctorFabric(FakeFabric):
    async def doctor(self, config, *, base_dir=None):
        type(self).last_config = config
        type(self).last_base_dir = base_dir
        return SimpleNamespace(
            status="fail",
            checks=[
                SimpleNamespace(
                    status="fail",
                    name="adapter.requirements",
                    message="Hermes Agent is not installed",
                )
            ],
        )


class WarningDoctorFabric(FakeFabric):
    async def doctor(self, config, *, base_dir=None):
        type(self).last_config = config
        type(self).last_base_dir = base_dir
        return SimpleNamespace(
            status="warn",
            checks=[
                SimpleNamespace(
                    status="warn",
                    name="model.connectivity",
                    message="model endpoint was not contacted during preflight",
                )
            ],
        )


def install_fake_fabric(monkeypatch, fabric_class=FakeFabric) -> None:
    FakeFabric.last_config = None
    FakeFabric.last_base_dir = None
    FakeFabric.adapter_python_seen = None
    monkeypatch.setitem(
        sys.modules,
        "nemo_fabric",
        SimpleNamespace(Fabric=fabric_class, FabricConfig=FakeFabricConfig),
    )


def nemo_config(adapter_id: str, **kwargs) -> WorkerConfig:
    kwargs.setdefault("env", {"OPENAI_API_KEY": "test"})
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
    assert FakeFabric.last_base_dir == tmp_path


def test_hermes_keeps_max_turns(monkeypatch, tmp_path: Path) -> None:
    install_fake_fabric(monkeypatch)
    worker = NeMoWorker(nemo_config("nvidia.fabric.hermes", max_turns=37, timeout_seconds=91))

    result = asyncio.run(worker._run("fix it", tmp_path))

    assert result.success is True
    assert FakeFabric.last_config["runtime"] == {
        "timeout_seconds": 91,
        "max_turns": 37,
    }
    assert FakeFabric.last_config["harness"]["resolution"] == "preinstalled"
    assert FakeFabric.last_base_dir == tmp_path


def test_validate_resolves_adapter_and_runs_doctor(monkeypatch, tmp_path: Path) -> None:
    install_fake_fabric(monkeypatch)
    worker = NeMoWorker(nemo_config("nvidia.fabric.hermes"))

    result = worker.validate(tmp_path)

    assert result.success is True
    assert result.metadata["adapter_id"] == "nvidia.fabric.hermes"
    assert result.metadata["doctor_status"] == "pass"
    assert result.metadata["api_key_env"] == "OPENAI_API_KEY"
    assert result.metadata["adapter_python"] == sys.executable
    assert FakeFabric.last_config["harness"]["adapter_id"] == "nvidia.fabric.hermes"
    assert FakeFabric.last_config["harness"]["resolution"] == "preinstalled"
    assert FakeFabric.last_base_dir == tmp_path


def test_validate_reports_doctor_failures(monkeypatch, tmp_path: Path) -> None:
    install_fake_fabric(monkeypatch, FailingDoctorFabric)
    worker = NeMoWorker(nemo_config("nvidia.fabric.hermes"))

    result = worker.validate(tmp_path)

    assert result.success is False
    assert "adapter.requirements" in result.error
    assert "Hermes Agent is not installed" in result.error


def test_validate_preserves_doctor_warnings_without_failing(monkeypatch, tmp_path: Path) -> None:
    install_fake_fabric(monkeypatch, WarningDoctorFabric)
    worker = NeMoWorker(nemo_config("nvidia.fabric.hermes"))

    result = worker.validate(tmp_path)

    assert result.success is True
    assert result.metadata["doctor_status"] == "warn"
    assert result.metadata["doctor_warnings"] == [
        "model.connectivity: model endpoint was not contacted during preflight"
    ]


def test_validate_fails_before_first_turn_when_hermes_key_is_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    install_fake_fabric(monkeypatch)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    worker = NeMoWorker(nemo_config("nvidia.fabric.hermes", env={}))

    result = worker.validate(tmp_path)

    assert result.success is False
    assert "OPENAI_API_KEY" in result.error
    assert "dummy value" in result.error


def test_validate_accepts_explicit_hermes_api_key_env(monkeypatch, tmp_path: Path) -> None:
    install_fake_fabric(monkeypatch)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    worker = NeMoWorker(
        nemo_config(
            "nvidia.fabric.hermes",
            api_key_env="LOCAL_MODEL_TOKEN",
            env={"LOCAL_MODEL_TOKEN": "local"},
        )
    )

    result = worker.validate(tmp_path)

    assert result.success is True
    assert result.metadata["api_key_env"] == "LOCAL_MODEL_TOKEN"
    assert FakeFabric.last_config["models"]["default"]["api_key_env"] == "LOCAL_MODEL_TOKEN"


def test_nemo_defaults_adapter_host_to_its_running_interpreter(monkeypatch, tmp_path: Path) -> None:
    install_fake_fabric(monkeypatch)
    monkeypatch.delenv("ADAPTER_PYTHON", raising=False)
    worker = NeMoWorker(nemo_config("nvidia.fabric.hermes"))

    result = worker.run("fix it", tmp_path)

    assert result.success is True
    assert FakeFabric.adapter_python_seen == sys.executable
    assert result.metadata["adapter_python"] == sys.executable
    assert os.environ.get("ADAPTER_PYTHON") is None


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


def test_adapter_python_override_cannot_leak_to_unscoped_worker(monkeypatch) -> None:
    monkeypatch.delenv("ADAPTER_PYTHON", raising=False)
    override_entered = threading.Event()
    unscoped_attempted = threading.Event()
    release_override = threading.Event()
    observed: list[str | None] = []

    def scoped_worker() -> None:
        with _adapter_python_env("/tmp/hermes-python"):
            override_entered.set()
            assert release_override.wait(timeout=2)

    def unscoped_worker() -> None:
        assert override_entered.wait(timeout=2)
        unscoped_attempted.set()
        with _adapter_python_env(None):
            observed.append(os.environ.get("ADAPTER_PYTHON"))

    scoped = threading.Thread(target=scoped_worker)
    unscoped = threading.Thread(target=unscoped_worker)
    scoped.start()
    unscoped.start()

    assert unscoped_attempted.wait(timeout=2)
    time.sleep(0.05)
    release_override.set()
    scoped.join(timeout=2)
    unscoped.join(timeout=2)

    assert not scoped.is_alive()
    assert not unscoped.is_alive()
    assert observed == [None]
    assert os.environ.get("ADAPTER_PYTHON") is None


def test_unknown_adapter_error_explains_install_and_isolation() -> None:
    message = _nemo_failure(
        RuntimeError("unknown adapter nvidia.fabric.hermes"),
        "nvidia.fabric.hermes",
    )

    assert "nemo-fabric[hermes-agent]" in message
    assert "ADAPTER_PYTHON" in message
