from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Protocol

from .config import WorkerConfig
from .models import WorkerResult


class Worker(Protocol):
    def run(self, prompt: str, workspace: Path) -> WorkerResult: ...


_ADAPTER_ENV_LOCK = threading.Lock()
_MAX_TURNS_UNSUPPORTED_ADAPTERS = {"nvidia.fabric.codex"}
_ADAPTER_INSTALL_HINTS = {
    "nvidia.fabric.hermes": "nemo-fabric[hermes-agent] plus Hermes Agent 0.20+ from source",
    "nvidia.fabric.codex": "nemo-fabric[codex]",
    "nvidia.fabric.claude": "nemo-fabric[claude]",
    "nvidia.fabric.langchain.deepagents": "nemo-fabric[deepagents]",
    "nvidia.fabric.mini-swe-agent": "nemo-fabric[mini-swe-agent]",
}


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json", exclude_none=True)
        except TypeError:
            return value.model_dump()
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)


def _number(mapping: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = mapping.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def _normalized_usage(value: Any) -> tuple[int | None, int | None, float | None, dict[str, Any] | None]:
    raw = _jsonable(value)
    if not isinstance(raw, dict):
        return None, None, None, raw if raw is not None else None

    # NeMo adapters/providers do not all use the same field names. Prefer the
    # normalized names, then accept common OpenAI/LangChain aliases.
    input_tokens = _number(raw, "input_tokens", "prompt_tokens", "input")
    output_tokens = _number(raw, "output_tokens", "completion_tokens", "output")
    cost = _number(raw, "cost_usd", "total_cost_usd", "cost")

    # Some providers wrap usage in a nested token_usage/usage object.
    if input_tokens is None or output_tokens is None or cost is None:
        for key in ("token_usage", "usage", "tokens"):
            nested = raw.get(key)
            if not isinstance(nested, dict):
                continue
            input_tokens = input_tokens if input_tokens is not None else _number(
                nested, "input_tokens", "prompt_tokens", "input"
            )
            output_tokens = output_tokens if output_tokens is not None else _number(
                nested, "output_tokens", "completion_tokens", "output"
            )
            cost = cost if cost is not None else _number(
                nested, "cost_usd", "total_cost_usd", "cost"
            )

    return (
        int(input_tokens) if input_tokens is not None else None,
        int(output_tokens) if output_tokens is not None else None,
        float(cost) if cost is not None else None,
        raw,
    )


@contextmanager
def _adapter_python_env(adapter_python: str | None):
    """Temporarily select an isolated NeMo adapter environment for one worker.

    NeMo Fabric discovers Python adapter descriptors and their harness through
    ADAPTER_PYTHON. WorkerConfig.env is already overrideable per role/strategy,
    so treating that one key as runtime-owned lets Avo mix incompatible harness
    environments without introducing another configuration surface.

    ADAPTER_PYTHON lives in process-global os.environ, so every NeMo call must
    participate in the same lock. Otherwise a worker without an override can run
    while another worker has temporarily set ADAPTER_PYTHON and silently discover
    the wrong adapter environment.
    """

    with _ADAPTER_ENV_LOCK:
        previous = os.environ.get("ADAPTER_PYTHON")
        if adapter_python:
            os.environ["ADAPTER_PYTHON"] = adapter_python
        try:
            yield
        finally:
            if adapter_python:
                if previous is None:
                    os.environ.pop("ADAPTER_PYTHON", None)
                else:
                    os.environ["ADAPTER_PYTHON"] = previous


def _nemo_failure(exc: Exception, adapter_id: str) -> str:
    detail = str(exc)
    lowered = detail.lower().replace("_", " ")
    if "unknown adapter" in lowered or "unknownadapter" in lowered.replace(" ", ""):
        install = _ADAPTER_INSTALL_HINTS.get(adapter_id, "the adapter package for this adapter ID")
        return (
            f"NeMo Fabric cannot resolve adapter {adapter_id!r}. Install {install}. "
            "If its harness has dependency conflicts with Avo's main environment, install it in "
            "a separate virtualenv and set worker.env.ADAPTER_PYTHON to that environment's Python. "
            f"Original error: {detail}"
        )
    return f"NeMo Fabric worker failed: {detail}"


class CommandWorker:
    def __init__(self, config: WorkerConfig):
        self.config = config

    def run(self, prompt: str, workspace: Path) -> WorkerResult:
        started = time.monotonic()
        env = os.environ.copy()
        env.update(self.config.env)
        env["AVO_WORKSPACE"] = str(workspace)
        env["AVO_PROMPT"] = prompt
        prompt_path = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
                handle.write(prompt)
                prompt_path = handle.name
            command = [
                part.replace("{workspace}", str(workspace))
                .replace("{prompt_file}", prompt_path)
                .replace("{prompt}", prompt)
                for part in self.config.command
            ]
            uses_prompt_placeholder = any(
                token in part
                for part in self.config.command
                for token in ("{prompt}", "{prompt_file}")
            )
            proc = subprocess.run(
                command,
                cwd=workspace,
                env=env,
                input=None if uses_prompt_placeholder else prompt,
                text=True,
                capture_output=True,
                timeout=self.config.timeout_seconds,
            )
            return WorkerResult(
                success=proc.returncode == 0,
                output=proc.stdout[-50000:],
                error=proc.stderr[-50000:],
                metadata={
                    "return_code": proc.returncode,
                    "command": shlex.join(command),
                    "backend": "command",
                },
                duration_seconds=time.monotonic() - started,
            )
        except subprocess.TimeoutExpired as exc:
            return WorkerResult(
                success=False,
                output=(exc.stdout or "")[-50000:] if isinstance(exc.stdout, str) else "",
                error=f"worker timed out after {self.config.timeout_seconds}s",
                metadata={"backend": "command", "timed_out": True},
                duration_seconds=time.monotonic() - started,
            )
        finally:
            if prompt_path:
                try:
                    os.unlink(prompt_path)
                except FileNotFoundError:
                    pass


class NeMoWorker:
    def __init__(self, config: WorkerConfig):
        self.config = config

    def run(self, prompt: str, workspace: Path) -> WorkerResult:
        started = time.monotonic()
        adapter_python = self.config.env.get("ADAPTER_PYTHON")
        try:
            with _adapter_python_env(adapter_python):
                result = asyncio.run(self._run(prompt, workspace))
            result.duration_seconds = time.monotonic() - started
            if adapter_python:
                result.metadata["adapter_python"] = adapter_python
            return result
        except Exception as exc:
            return self._failure_result(exc, started, adapter_python)

    def validate(self, workspace: Path) -> WorkerResult:
        """Resolve and diagnose the configured adapter without calling a model."""

        started = time.monotonic()
        adapter_python = self.config.env.get("ADAPTER_PYTHON")
        try:
            with _adapter_python_env(adapter_python):
                result = asyncio.run(self._validate(workspace))
            result.duration_seconds = time.monotonic() - started
            if adapter_python:
                result.metadata["adapter_python"] = adapter_python
            return result
        except Exception as exc:
            return self._failure_result(exc, started, adapter_python)

    def _failure_result(
        self,
        exc: Exception,
        started: float,
        adapter_python: str | None,
    ) -> WorkerResult:
        metadata: dict[str, Any] = {
            "backend": "nemo",
            "adapter_id": self.config.adapter_id,
        }
        if adapter_python:
            metadata["adapter_python"] = adapter_python
        return WorkerResult(
            success=False,
            error=_nemo_failure(exc, self.config.adapter_id),
            metadata=metadata,
            duration_seconds=time.monotonic() - started,
        )

    def _fabric_config(self, workspace: Path):
        try:
            from nemo_fabric import FabricConfig
        except ImportError as exc:
            raise RuntimeError(
                "NeMo Fabric is not installed. Install this project with the 'nemo' extra."
            ) from exc

        # ADAPTER_PYTHON selects the adapter host interpreter and must be visible
        # to the Fabric runtime process, not forwarded as a harness environment
        # variable. Other configured variables remain harness-visible.
        harness_env = dict(self.config.env)
        harness_env.pop("ADAPTER_PYTHON", None)

        runtime: dict[str, Any] = {
            "timeout_seconds": self.config.timeout_seconds,
        }
        # max_turns is a normalized optional capability, not a universal one.
        # Codex intentionally has no mapping for it; including Avo's default of
        # 24 makes Fabric reject an otherwise valid Codex configuration.
        if self.config.adapter_id not in _MAX_TURNS_UNSUPPORTED_ADAPTERS:
            runtime["max_turns"] = self.config.max_turns

        payload: dict[str, Any] = {
            "metadata": {"name": "avo-worker"},
            "harness": {
                "adapter_id": self.config.adapter_id,
                "settings": self.config.harness_settings,
            },
            "instructions": {
                "system": {"content": self.config.system_prompt, "mode": "replace"}
            },
            "runtime": runtime,
            "environment": {
                "provider": "local",
                "workspace": str(workspace),
                "env": harness_env,
            },
            "models": {},
        }
        if self.config.model:
            model: dict[str, Any] = {
                "provider": self.config.provider or "nvidia",
                "model": self.config.model,
            }
            if self.config.api_key_env:
                model["api_key_env"] = self.config.api_key_env
            if self.config.base_url:
                model["base_url"] = self.config.base_url
            if self.config.temperature is not None:
                model["temperature"] = self.config.temperature
            if self.config.model_settings:
                model["settings"] = self.config.model_settings
            payload["models"]["default"] = model
        if self.config.tools is not None:
            payload["tools"] = self.config.tools
        if self.config.mcp is not None:
            payload["mcp"] = self.config.mcp
        if self.config.skills is not None:
            payload["skills"] = self.config.skills
        if self.config.telemetry is not None:
            payload["telemetry"] = self.config.telemetry

        if hasattr(FabricConfig, "from_mapping"):
            return FabricConfig.from_mapping(payload)
        return FabricConfig(**payload)

    async def _validate(self, workspace: Path) -> WorkerResult:
        try:
            from nemo_fabric import Fabric
        except ImportError as exc:
            raise RuntimeError(
                "NeMo Fabric is not installed. Install this project with the 'nemo' extra."
            ) from exc

        config = self._fabric_config(workspace)
        fabric = Fabric()
        plan = fabric.plan(config)
        resolved_adapter = getattr(getattr(plan, "adapter", None), "adapter_id", None)
        if resolved_adapter != self.config.adapter_id:
            raise RuntimeError(
                f"NeMo Fabric planned adapter {resolved_adapter!r}, expected {self.config.adapter_id!r}"
            )

        # NeMo's doctor goes beyond descriptor discovery: it validates declared
        # adapter/harness requirements and environment assumptions without
        # starting a runtime or contacting the configured model.
        report = await fabric.doctor(config)
        doctor_status = str(getattr(report, "status", "unknown"))
        if doctor_status != "pass":
            failures = []
            for check in getattr(report, "checks", []) or []:
                if str(getattr(check, "status", "")) != "fail":
                    continue
                name = str(getattr(check, "name", "runtime"))
                message = str(getattr(check, "message", "failed"))
                failures.append(f"{name}: {message}")
            detail = "; ".join(failures) or f"overall status {doctor_status}"
            raise RuntimeError(f"NeMo Fabric doctor failed: {detail}")

        return WorkerResult(
            success=True,
            metadata={
                "backend": "nemo",
                "adapter_id": self.config.adapter_id,
                "doctor_status": doctor_status,
            },
        )

    async def _run(self, prompt: str, workspace: Path) -> WorkerResult:
        try:
            from nemo_fabric import Fabric
        except ImportError as exc:
            raise RuntimeError(
                "NeMo Fabric is not installed. Install this project with the 'nemo' extra."
            ) from exc

        config = self._fabric_config(workspace)
        result = await Fabric().run(config, input=prompt)
        output_obj = getattr(result, "output", None)
        response = getattr(output_obj, "response", "") if output_obj is not None else ""
        error_obj = getattr(result, "error", None)
        status = str(getattr(result, "status", "unknown"))
        metadata: dict[str, Any] = {
            "status": status,
            "adapter_id": self.config.adapter_id,
            "backend": "nemo",
        }
        input_tokens, output_tokens, cost_usd, usage = _normalized_usage(
            getattr(result, "usage", None)
        )
        if usage is not None:
            metadata["usage"] = usage
        telemetry = getattr(result, "telemetry", None)
        if telemetry is not None:
            metadata["telemetry"] = _jsonable(telemetry)
        events = getattr(result, "events", None)
        if events is not None:
            try:
                metadata["event_count"] = len(events)
            except TypeError:
                pass
        return WorkerResult(
            success=error_obj is None,
            output=str(response or ""),
            error="" if error_obj is None else str(error_obj),
            metadata=metadata,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
        )


def make_worker(config: WorkerConfig) -> Worker:
    if config.backend == "command":
        return CommandWorker(config)
    if config.backend == "nemo":
        return NeMoWorker(config)
    raise ValueError(f"unknown worker backend: {config.backend}")
