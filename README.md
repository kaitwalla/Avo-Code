# Avo-Code

Avo-Code is a long-horizon coding control plane built around deterministic evaluation, isolated candidate worktrees, compact memory, lazy specialist activation, and benchmark-driven strategy routing.

## Web + iOS control plane

Avo-Code includes a universal Expo frontend in `ui/` plus a FastAPI backend exposed from the Python package.

The UI is intentionally one product with two distribution targets:

- responsive web app for desktop and mobile browsers
- native iOS app built from the same Expo Router / React Native codebase

The mobile layout is single-column with bottom navigation and large touch targets. Wider web layouts expand into multi-column dashboards rather than stretching the phone UI.

### Start the backend

```bash
python -m pip install -e '.[web]'
export AVO_WEB_TOKEN='replace-me'   # optional but recommended off localhost
avo-harness web -c avo.json --host 0.0.0.0 --port 8765
```

If the UI is hosted from a different origin, set `AVO_WEB_ORIGINS` to a comma-separated list of allowed origins.

AvoGym reports are discovered recursively beneath `AVO_BENCHMARK_ROOT`. By default that is `benchmarks/` beside the selected `avo.json` file. Point it elsewhere when reports are stored on another volume:

```bash
export AVO_BENCHMARK_ROOT=/srv/avo/benchmarks
```

The Benchmarks tab reads `report.json` and `routing-policy.json` from those output folders and shows benchmark history, strategy comparisons, the learned global default, and tag-specific routing evidence.

### Run the universal frontend

Expo SDK 57 requires Node 22.13 or newer.

```bash
cd ui
npm install
npm run web
```

For iOS development:

```bash
cd ui
npm install
npm run ios
```

Configure the backend URL and API token in the Settings tab. Native iOS stores the token through Expo SecureStore / Keychain; web stores it in browser-local storage.

The native app is not a WebView wrapper. Expo Router renders native navigation on iOS and web routing from the same route tree, with room for `.ios.tsx` / `.web.tsx` platform-specific components later where the UX genuinely differs.

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
