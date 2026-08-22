# AVO Harness

**AVO Harness is an unofficial open-source implementation of a long-horizon agent loop inspired by NVIDIA's published AVO architecture. It is not an NVIDIA project and does not contain NVIDIA's internal AVO implementation.**

The harness sits above a coding agent and turns repeated agent runs into a persistent search process:

```text
objective
   |
   v
persistent orchestrator ---- episodic memory
   |                              ^
   v                              |
candidate worktree -> evaluators -+
   |                    |
   +---- improved? -----+---- no progress ----> supervisor
   |                                             |
   +---------------- next iteration <------------+
```

Each attempt starts from the best known Git commit in an isolated worktree. The worker edits the repository, the harness commits the candidate, deterministic evaluators score it, SQLite stores the lineage and evidence, and the next attempt receives compact memory from previous rounds. Repeated stagnation wakes a separate supervisor pass that injects a new strategy without editing the target repository.

## What works in v0.1

- Persistent run, candidate, evaluator, and intervention history in SQLite.
- Git worktree isolation and explicit candidate lineage.
- Weighted deterministic evaluators with either exit-code scoring or a one-line JSON score protocol.
- Automatic promotion of better candidates and a stable `avo/<run>/best` result branch.
- Episodic memory assembled from recent attempts and evaluator evidence.
- Stagnation detection plus a supervisor agent with cooldown.
- A generic command worker for any CLI coding agent.
- A native NVIDIA NeMo Fabric worker using its typed Python SDK and local workspace contract.
- Hermes, Codex, Claude, or another Fabric adapter can be selected through `worker.adapter_id` when the corresponding Fabric adapter is installed.
- Optional up-front planner role with a disposable repository worktree.
- Explicit local/cloud execution classes and a cloud-assist budget for planner/supervisor calls.
- AvoGym benchmark/ablation runner with hidden external oracle evaluation.

This deliberately leaves scheduling, distributed workers, semantic memory, and tree search out of the first cut. The core loop is small enough to reason about before those are layered on.

## Install

Core command-worker mode has no runtime dependencies beyond Python 3.11+ and Git:

```bash
python -m pip install -e .
```

For NeMo Fabric:

```bash
python -m pip install -e '.[nemo]'
```

Install the Fabric adapter/harness you intend to use as described by NVIDIA. For example, Hermes uses the `nvidia.fabric.hermes` adapter; Codex uses `nvidia.fabric.codex`; Claude uses its corresponding Fabric adapter.

## Configure

Generate a starting config:

```bash
avo-harness init --repo /path/to/project --output avo.json
```

The generated config is local-first: NeMo Fabric + Hermes pointed at a self-hosted OpenAI-compatible endpoint (`http://127.0.0.1:8000/v1`) with a placeholder model name. Replace `local-open-model` with the open model you serve. A minimal command-worker config looks like this:

```json
{
  "repo": "/path/to/project",
  "state_dir": "~/.local/state/avo-harness",
  "max_iterations": 12,
  "acceptance_score": 1.0,
  "cloud_assist_budget": 2,
  "worker": {
    "backend": "command",
    "command": ["your-agent", "--non-interactive"],
    "execution_class": "local"
  },
  "planner": {
    "enabled": false
  },
  "supervisor": {
    "enabled": true,
    "stagnation_rounds": 2,
    "cooldown_rounds": 2
  },
  "evaluators": [
    {
      "name": "tests",
      "command": "pytest -q",
      "weight": 1.0
    }
  ]
}
```

A command worker receives the full iteration prompt on stdin unless its command contains `{prompt}` or `{prompt_file}`. It also receives `AVO_PROMPT` and `AVO_WORKSPACE` environment variables. `{workspace}` can be used in command arguments.

### Local-first model roles

Avo-Code separates model roles so open models that fit on DGX Spark-class hardware or less can do the repetitive implementation work while cloud models remain optional assistants:

- **worker**: the implementation loop; intended to be local/open by default.
- **planner**: optional up-front planning for larger tasks; may be local or cloud.
- **supervisor**: optional intervention after stagnation; may be local or cloud.
- `cloud_assist_budget`: caps **cloud planner/supervisor calls** without limiting local worker iterations.

Every worker configuration accepts `execution_class: "local" | "cloud"`. The harness records role, execution class, wall time, and token/cost fields when the backend reports them. This lets AvoGym measure whether cloud assistance actually improves quality enough to justify the dependency.

For a larger task, a cloud planner can inspect a disposable worktree and hand a persistent implementation plan to the local worker:

```json
{
  "cloud_assist_budget": 2,
  "worker": {
    "backend": "nemo",
    "adapter_id": "nvidia.fabric.hermes",
    "provider": "openai",
    "model": "local-open-model",
    "base_url": "http://127.0.0.1:8000/v1",
    "execution_class": "local"
  },
  "planner": {
    "enabled": true,
    "worker": {
      "backend": "command",
      "command": ["your-cloud-planner-cli", "--prompt-file", "{prompt_file}"],
      "execution_class": "cloud"
    }
  }
}
```

A cloud primary worker is still allowed if intentionally configured; `cloud_assist_budget` is specifically a budget for planning/supervision assistance rather than a blanket ban on cloud execution.

### NeMo Fabric worker

```json
{
  "worker": {
    "backend": "nemo",
    "adapter_id": "nvidia.fabric.hermes",
    "provider": "openai",
    "model": "local-open-model",
    "base_url": "http://127.0.0.1:8000/v1",
    "max_turns": 24,
    "execution_class": "local"
  }
}
```

The integration uses `EnvironmentConfig(provider="local", workspace=...)`, so every candidate worktree is the workspace visible to the selected Fabric harness.

## Evaluator protocol

An evaluator is any shell command. By default, exit code `0` scores `1.0` and a nonzero exit code scores `0.0`.

For partial credit, print a JSON object as the final non-empty stdout line:

```json
{"score": 0.72, "summary": "18 of 25 benchmark cases pass"}
```

`score` is clamped to `[0, 1]`. Multiple evaluator scores are combined by weight. This lets tests, lint, benchmarks, static analysis, or task-specific judges contribute independently.

## AvoGym

AvoGym runs reproducible benchmark and ablation experiments around the real harness. Search-time evaluators stay in the candidate repository, while **hidden oracle evaluators run externally and are never used for candidate promotion or injected into agent memory**. The visible/oracle score gap therefore exposes test gaming or weak evaluators rather than rewarding them.

```json
{
  "name": "local-first-ablation",
  "base_config": "avo.json",
  "seeds": [0, 1, 2],
  "variants": [
    {"name": "local-only", "overrides": {"planner": {"enabled": false}, "cloud_assist_budget": 0}},
    {"name": "cloud-plan", "overrides": {"planner": {"enabled": true}, "cloud_assist_budget": 1}},
    {"name": "cloud-plan-supervise", "overrides": {"planner": {"enabled": true}, "cloud_assist_budget": 2}}
  ],
  "tasks": [
    {
      "id": "example",
      "source": "tasks/example/repo",
      "objective": "Fix the behavior without weakening tests",
      "oracle_cwd": "tasks/example",
      "oracle": [
        {"name": "hidden", "command": "python oracle.py {workspace}"}
      ],
      "tags": ["correctness", "test-integrity"]
    }
  ]
}
```

Run it with:

```bash
avo-harness benchmark experiment.json -o reports/local-first
```

The JSON and HTML reports include oracle solve rate, visible/oracle score gap, score gain, progress AUC, iterations, wall time, local/cloud invocation counts, planner/supervisor calls, supervisor uplift, and reported cost.

Oracle commands support `{workspace}` and `{task}` substitutions. The oracle working directory is external to the candidate Git worktree. This is a benchmark-integrity boundary, not a security sandbox: if the worker itself is hostile or untrusted, run it inside an OS/container sandbox as well.

## Run

First validate the environment:

```bash
avo-harness doctor -c avo.json
```

Then start a run:

```bash
avo-harness run -c avo.json "Fix the failing authentication flow without regressing the API contract"
```

The target repository must be clean by default. Each candidate lives on its own `avo/<run-id>/i-####` branch. At the end, the best commit is also pointed to by `avo/<run-id>/best`; the harness never merges it into your main branch automatically.

Inspect the latest persisted run:

```bash
avo-harness status -c avo.json
```

`status` includes the stored run metadata plus invocation totals by role and local/cloud execution class.

## How the AVO-style loop maps

| AVO-style concept | This implementation |
| --- | --- |
| Long-running main agent | repeated worker invocations against the best candidate |
| Persistent memory | SQLite trajectory + compact episodic prompt memory |
| Environment/tool use | real Git worktree exposed to the coding harness |
| External feedback | deterministic weighted evaluators |
| Supervisor intervention | isolated supervisor pass after configurable stagnation |
| Search/variation | candidate branches descending from the best known commit |
| Durable result | best commit + result branch + complete evidence trail |

## Safety / operational boundaries

The worker is a coding agent with whatever filesystem/tool permissions its backend provides. Run it in a disposable clone or sandbox when working with untrusted repositories or powerful agent configurations. Evaluator commands are also arbitrary shell commands from your config.

The harness intentionally does **not** auto-merge, push, deploy, or mutate the target branch. It creates Git branches and linked worktrees only.
