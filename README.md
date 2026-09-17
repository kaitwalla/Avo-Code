# Avo-Code

Avo-Code is a chat-first engineering assistant backed by a long-horizon coding control plane. Conversation and repository investigation are the default; deterministic evaluation, isolated candidate worktrees, compact memory, lazy specialist activation, and benchmark-driven strategy routing come online when a requested change is ready to execute.

## Chat first, agents when warranted

The Assistant tab is Avo's primary interface. You can ask architectural questions, investigate a bug, trace behavior through the repository, or ask for a change in the same conversation.

Avo does **not** turn every request into a coding run. It investigates in a disposable detached worktree and returns one of three internal outcomes:

- `answer` — no repository mutation is needed
- `clarify` — a material behavior/product decision is still unresolved
- `execute` — the requested change has an evidence-backed target and a validation path

Execution readiness is deterministic rather than a self-reported confidence percentage. Before Avo can auto-launch the coding loop it must produce a concrete objective, at least two sourced evidence items, at least one observable acceptance condition, and no unresolved clarification question. If that contract is incomplete, an attempted `execute` decision is downgraded to `clarify`.

When execution is ready, the conversation launches the normal Avo coding loop and embeds a task card in chat. Runs, evaluator history, specialist activity, diffs/telemetry, and AvoGym remain available as drill-down instrumentation rather than being the product's front door.

The conversational investigation checkout is disposable. Any accidental edits made by an investigation harness are discarded before execution. Actual coding still happens through Avo's isolated candidate-worktree/evaluator loop.

## Declarative access

Each repository can describe the capabilities it wants Avo to use in `.avo/access.yaml`. The manifest is intentionally human-readable and version-controlled:

```yaml
version: 1
repositories:
  avo-code:
    path: .
    access: write
  rooter:
    path: /workspace/rooter
    access: read

secrets:
  github:
    source: env:GITHUB_TOKEN
    expose_to: [researcher, coder]

services:
  rooter:
    url: http://rooter:8080
    access: write

tools:
  shell:
    enabled: true
    expose_to: [coder, infrastructure]

network:
  allow:
    - github.com
    - api.github.com
```

Secret values never belong in this file. Secret sources must be references such as `env:GITHUB_TOKEN` or `file:/run/secrets/github`; the Access UI reports only whether a referenced secret is configured, never its value.

Avo keeps a persisted **granted** capability snapshot alongside the repo's **requested** manifest. Reductions take effect immediately. Increases such as adding a repository or secret, adding a network host/tool, changing a resource location, or escalating `read` to `write` remain ineffective until the owner approves the exact manifest through a fresh passkey assertion. This means an agent can edit `.avo/access.yaml`, but that edit alone cannot grant it more authority.

Open **Settings → Access → Manage access** to enumerate effective repositories, secret references, services, tools, and network hosts or to edit the YAML directly. The backend validates the same file, so the UI and the checked-in manifest cannot drift into separate configuration systems.

The capability manifest is Avo's application-level access contract. Container mounts, Unix permissions, network policy, and external service permissions remain the hard operating-system/infrastructure boundary; declaring a path or host does not magically make an unmounted or blocked resource reachable.

## One web + iOS control plane

Avo-Code ships one first-party product:

- FastAPI serves the API and the exported Expo web app from the same process and hostname
- the same Expo Router / React Native project builds the native iOS app
- the web client uses same-origin `/api/*` requests
- native iOS uses the same backend at `https://avo.penginlab.com`

The default production topology is therefore:

```text
avo.penginlab.com
├── /                                  Expo web app
├── /api/*                             Avo API
├── /api/auth/*                        passkey ceremonies + sessions
└── /.well-known/apple-app-site-association
```

### Passkey authentication

Avo is deliberately single-user. There are no passwords, user/organization tables, or permanent API keys.

Web sessions are stored in an `HttpOnly`, `Secure`, `SameSite=Strict` cookie. The native app receives an opaque session token after passkey verification and keeps it in iOS Keychain through Expo SecureStore.

To enroll the first passkey, generate a short-lived one-time code on the Avo host:

```bash
avo-harness auth bootstrap -c /data/avo.json
```

Open Avo, enter that code once, and create the passkey. Bootstrap enrollment automatically stops working after the first credential exists. Additional passkeys are added from **Settings → Security** while signed in.

Production passkey configuration:

```bash
export AVO_PUBLIC_ORIGIN=https://avo.penginlab.com
export AVO_APPLE_TEAM_ID=YOUR_APPLE_TEAM_ID
```

`AVO_RP_ID` normally does not need to be set; it defaults to the hostname from `AVO_PUBLIC_ORIGIN`. The iOS bundle ID is `com.kaitwalla.avocode` and the app is associated with `webcredentials:avo.penginlab.com`.

`AVO_APPLE_TEAM_ID` is required for native iOS passkey domain association. Web passkeys can work without it. For explicit local-only development, `AVO_AUTH_DISABLED=1` disables authentication and step-up access approval; do not use that on a remotely reachable deployment.

### Unified Docker image

The root `Dockerfile` builds the Expo web frontend and copies it into the Python runtime image, so frontend and backend deploy together. It also installs the pinned Hermes Agent source plus the matching NeMo Fabric Hermes adapter, then runs Avo's adapter/harness preflight during the image build.

Build the image, then generate a container-valid configuration once. The repository must be mounted at the same path recorded in `avo.json`, and Avo state must live on a persistent mount so passkeys, conversations, runs, and worktree metadata survive container replacement:

```bash
docker build -t avo-code .
mkdir -p /srv/avo

docker run --rm \
  --entrypoint avo-harness \
  -v /srv/avo:/data \
  -v /path/to/repository:/workspace \
  avo-code \
  init --repo /workspace --state-dir /data/state --output /data/avo.json

docker run --rm \
  -p 8765:8765 \
  -v /srv/avo:/data \
  -v /path/to/repository:/workspace \
  -e AVO_PUBLIC_ORIGIN=https://avo.penginlab.com \
  -e AVO_APPLE_TEAM_ID=YOUR_APPLE_TEAM_ID \
  avo-code
```

The default container command expects `/data/avo.json` and serves on port `8765`. Mount any additional repository paths referenced by `.avo/access.yaml` as well. Do not point `state_dir` at the container's home directory for a replaceable deployment; use `/data/state` or another persisted path.

### Local development

The generated default configuration uses NeMo Fabric's Hermes adapter. A usable local installation therefore needs **Python 3.11–3.13**, Hermes Agent 0.20+ installed from source, and the `nemo` extra. Installing only `.[web]` is not enough.

The supported local setup is:

```bash
python3.12 -m venv .venv
source .venv/bin/activate

# Installs the same pinned Hermes source ref used by Docker and CI.
python scripts/install_hermes.py
python -m pip install -e '.[web,nemo,dev]'
python -m pip check

avo-harness init --repo /path/to/repository --output avo.json
avo-harness doctor -c avo.json
```

`avo-harness doctor` does not merely import `nemo_fabric`. It resolves every configured NeMo adapter and runs NeMo Fabric's diagnostics without calling the model. An environment with `available adapters: []`, a missing Hermes harness, an incompatible adapter configuration, or a broken `ADAPTER_PYTHON` environment fails here instead of at the first coding request. Advisory NeMo diagnostics are printed as `WARN`; actual failed checks make `doctor` fail.

`python scripts/install_hermes.py` installs into the Python interpreter used to invoke it and checks out the source under `.deps/hermes-agent` by default. Set `HERMES_AGENT_REF` only when intentionally testing a different Hermes release. For a separate harness virtualenv, install Hermes and the matching adapter there and set that worker's `env.ADAPTER_PYTHON` to the virtualenv's Python executable.

Start the backend after `doctor` passes:

```bash
AVO_PUBLIC_ORIGIN=http://localhost:8765 \
AVO_AUTH_DISABLED=1 \
avo-harness web -c avo.json --host 0.0.0.0 --port 8765
```

Frontend development still supports Expo's separate dev server:

```bash
cd ui
npm install
npm run web
```

For native iOS development:

```bash
cd ui
npm install
npm run ios
```

The production web build itself does not need an API URL or CORS configuration because it is served from the backend origin. For native builds, `EXPO_PUBLIC_AVO_API_URL` can override the default `https://avo.penginlab.com` when testing against another backend.

The mobile layout is single-column with bottom navigation and large touch targets. Wider web layouts expand into multi-column dashboards rather than stretching the phone UI. The native app is not a WebView wrapper.

### AvoGym reports

AvoGym reports are discovered recursively beneath `AVO_BENCHMARK_ROOT`. By default that is `benchmarks/` beside the selected `avo.json` file. Point it elsewhere when reports are stored on another volume:

```bash
export AVO_BENCHMARK_ROOT=/srv/avo/benchmarks
```

The Benchmarks tab reads `report.json` and `routing-policy.json` from those output folders and shows benchmark history, strategy comparisons, the learned global default, and tag-specific routing evidence.

## Core CLI

```bash
avo-harness init --repo /path/to/repo
avo-harness doctor -c avo.json
avo-harness run "fix the failing auth flow" -c avo.json
avo-harness status --roles -c avo.json
```

## AvoGym

The representative benchmark suite lives under `benchmarks/representative/`.

```bash
python benchmarks/representative/prepare.py
avo-harness benchmark benchmarks/representative/experiment.json \
  -o benchmarks/representative/reports/local-harnesses
```

AvoGym records hidden-oracle quality, tokens, wall time, cost, role overhead, and emits a quality-first routing policy. When that output lives beneath `AVO_BENCHMARK_ROOT`, it appears in the web/iOS Benchmarks tab automatically.
