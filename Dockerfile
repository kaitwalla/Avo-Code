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
# NeMo Fabric 0.2 ships harness adapters separately from the runtime. Hermes
# Agent 0.20+ is source-distributed and deliberately refuses wheel/sdist builds,
# so keep a pinned source checkout in the image and install it editable. Then
# install every NeMo-maintained harness Avo can route to.
RUN git clone --depth 1 --branch "${HERMES_AGENT_REF}" \
      https://github.com/NousResearch/hermes-agent.git /opt/hermes-agent \
    && python -m pip install --no-cache-dir -e /opt/hermes-agent \
    && python -m pip install --no-cache-dir \
      '.[web,nemo,deepagents,codex,claude,mini-swe-agent]'
# Importing nemo_fabric alone does not prove descriptors are registered. Plan a
# minimal run for every adapter Avo advertises; planning resolves descriptors
# and normalized capability routing without contacting a model.
RUN python - <<'PY'
from nemo_fabric import Fabric, FabricConfig

adapter_ids = (
    "nvidia.fabric.hermes",
    "nvidia.fabric.codex",
    "nvidia.fabric.claude",
    "nvidia.fabric.langchain.deepagents",
    "nvidia.fabric.mini-swe-agent",
)
fabric = Fabric()
for adapter_id in adapter_ids:
    payload = {
        "metadata": {"name": f"avo-image-smoke-{adapter_id.rsplit('.', 1)[-1]}"},
        "harness": {"adapter_id": adapter_id, "settings": {}},
        "runtime": {"max_turns": 1, "timeout_seconds": 1},
        "environment": {"provider": "local", "workspace": "/tmp", "env": {}},
        "models": {
            "default": {
                "provider": "openai",
                "model": "smoke",
                "base_url": "http://127.0.0.1:1/v1",
            }
        },
    }
    config = FabricConfig.from_mapping(payload) if hasattr(FabricConfig, "from_mapping") else FabricConfig(**payload)
    plan = fabric.plan(config)
    assert plan.adapter.adapter_id == adapter_id, plan
    print(f"NeMo Fabric adapter available: {adapter_id}")
PY
COPY --from=ui-build /build/ui/dist /app/static

ENV AVO_WEB_STATIC_DIR=/app/static \
    AVO_PUBLIC_ORIGIN=https://avo.penginlab.com \
    PYTHONUNBUFFERED=1

EXPOSE 8765
ENTRYPOINT ["avo-harness", "web"]
CMD ["-c", "/data/avo.json", "--host", "0.0.0.0", "--port", "8765"]
