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
# NeMo Fabric 0.2 ships harness adapters separately from the runtime. Avo's
# default worker is Hermes, and Hermes Agent 0.20+ is source-distributed rather
# than bundled by the NeMo extra, so install a pinned Hermes release first.
RUN python -m pip install --no-cache-dir \
      "git+https://github.com/NousResearch/hermes-agent.git@${HERMES_AGENT_REF}" \
    && python -m pip install --no-cache-dir '.[web,nemo]'
# Importing nemo_fabric alone does not prove an adapter is registered. Planning
# a tiny run resolves the configured descriptor without contacting a model.
RUN python - <<'PY'
from nemo_fabric import Fabric, FabricConfig

payload = {
    "metadata": {"name": "avo-image-smoke"},
    "harness": {"adapter_id": "nvidia.fabric.hermes", "settings": {}},
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
plan = Fabric().plan(config)
assert plan.adapter.adapter_id == "nvidia.fabric.hermes", plan
print("NeMo Fabric Hermes adapter available")
PY
COPY --from=ui-build /build/ui/dist /app/static

ENV AVO_WEB_STATIC_DIR=/app/static \
    AVO_PUBLIC_ORIGIN=https://avo.penginlab.com \
    PYTHONUNBUFFERED=1

EXPOSE 8765
ENTRYPOINT ["avo-harness", "web"]
CMD ["-c", "/data/avo.json", "--host", "0.0.0.0", "--port", "8765"]
