from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
import tempfile
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Protocol

from .config import WorkerConfig
from .models import WorkerResult


class Worker(Protocol):
    def run(self, prompt: str, workspace: Path) -> WorkerResult: ...


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
        try:
            result = asyncio.run(self._run(prompt, workspace))
            result.duration_seconds = time.monotonic() - started
            return result
        except Exception as exc:
            return WorkerResult(
                success=False,
                error=f"NeMo Fabric worker failed: {exc}",
                metadata={"backend": "nemo", "adapter_id": self.config.adapter_id},
                duration_seconds=time.monotonic() - started,
            )

    async def _run(self, prompt: str, workspace: Path) -> WorkerResult:
        try:
            from nemo_fabric import Fabric, FabricConfig
        except ImportError as exc:
            raise RuntimeError(
                "NeMo Fabric is not installed. Install this project with the 'nemo' extra."
            ) from exc

        payload: dict[str, Any] = {
            "metadata": {"name": "avo-worker"},
            "harness": {
                "adapter_id": self.config.adapter_id,
                "settings": self.config.harness_settings,
            },
            "instructions": {
                "system": {"content": self.config.system_prompt, "mode": "replace"}
            },
            "runtime": {
                "max_turns": self.config.max_turns,
                "timeout_seconds": self.config.timeout_seconds,
            },
            "environment": {
                "provider": "local",
                "workspace": str(workspace),
                "env": self.config.env,
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
            config = FabricConfig.from_mapping(payload)
        else:
            config = FabricConfig(**payload)

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
