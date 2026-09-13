FROM node:22.13-bookworm-slim AS ui-build
WORKDIR /build/ui
COPY ui/package.json ./
RUN npm install
COPY ui/ ./
RUN npx expo export --platform web

FROM python:3.12-slim AS runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir '.[web]'
COPY --from=ui-build /build/ui/dist /app/static

ENV AVO_WEB_STATIC_DIR=/app/static \
    AVO_PUBLIC_ORIGIN=https://avo.penginlab.com \
    PYTHONUNBUFFERED=1

EXPOSE 8765
ENTRYPOINT ["avo-harness", "web"]
CMD ["-c", "/data/avo.json", "--host", "0.0.0.0", "--port", "8765"]
