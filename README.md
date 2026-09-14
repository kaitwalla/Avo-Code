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

`AVO_APPLE_TEAM_ID` is required for native iOS passkey domain association. Web passkeys can work without it. For explicit local-only development, `AVO_AUTH_DISABLED=1` disables authentication; do not use that on a remotely reachable deployment.

### Unified Docker image

The root `Dockerfile` builds the Expo web frontend and copies it into the Python runtime image, so frontend and backend deploy together:

```bash
docker build -t avo-code .
docker run --rm \
  -p 8765:8765 \
  -v /srv/avo:/data \
  -e AVO_PUBLIC_ORIGIN=https://avo.penginlab.com \
  -e AVO_APPLE_TEAM_ID=YOUR_APPLE_TEAM_ID \
  avo-code
```

The default container command expects `/data/avo.json` and serves on port `8765`.

### Local development

Backend:

```bash
python -m pip install -e '.[web]'
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
