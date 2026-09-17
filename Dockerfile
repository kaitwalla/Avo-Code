FROM node:22.13-bookworm-slim AS ui-build
WORKDIR /build/ui
COPY ui/package.json ./
RUN npm install
COPY ui/ ./
RUN npx expo export --platform web

FROM python:3.12-slim AS runtime
ARG HERMES_AGENT_REF=v2026.8.19
RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts ./scripts
# The production image ships the default Hermes stack only. Keep the source
# checkout/install recipe shared with local development and CI so an environment
# cannot look healthy merely because the NeMo runtime itself imports.
RUN PIP_NO_CACHE_DIR=1 HERMES_AGENT_REF="${HERMES_AGENT_REF}" \
      python scripts/install_hermes.py /opt/hermes-agent \
    && python -m pip install --no-cache-dir '.[web,nemo]' \
    && python -m pip check
# Exercise Avo's own no-model preflight. This resolves the configured descriptor
# and runs Fabric.doctor, which checks adapter/harness runtime requirements.
RUN python - <<'PY'
from pathlib import Path

from avo_harness.config import WorkerConfig
from avo_harness.worker import NeMoWorker

adapter_id = "nvidia.fabric.hermes"
worker = WorkerConfig(
    backend="nemo",
    adapter_id=adapter_id,
    model="smoke",
    provider="openai",
    base_url="http://127.0.0.1:1/v1",
    max_turns=1,
    timeout_seconds=1,
)
result = NeMoWorker(worker).validate(Path("/tmp"))
if not result.success:
    raise RuntimeError(result.error)
print(f"Avo NeMo preflight passed: {adapter_id}")
PY
COPY --from=ui-build /build/ui/dist /app/static

ENV AVO_WEB_STATIC_DIR=/app/static \
    AVO_PUBLIC_ORIGIN=https://avo.penginlab.com \
    PYTHONUNBUFFERED=1

EXPOSE 8765
ENTRYPOINT ["avo-harness", "web"]
CMD ["-c", "/data/avo.json", "--host", "0.0.0.0", "--port", "8765"]
