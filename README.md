# AVO Harness

**AVO Harness is an unofficial open-source implementation of a long-horizon agent loop inspired by NVIDIA's published AVO architecture. It is not an NVIDIA project and does not contain NVIDIA's internal AVO implementation.**

The harness sits above coding agents and turns repeated runs into a persistent search process:

```text
objective
   |
   v
persistent AVO orchestrator ---- compact episodic memory
   |                                  ^
   v                                  |
candidate worktree -> evaluators -----+
   |                    |
   +---- improved? -----+---- no progress ----> supervisor
   |                                             |
   +---------------- next iteration <------------+
```

Each attempt starts from the best known Git commit in an isolated worktree. A worker edits the repository, the harness commits the candidate, deterministic evaluators score it, SQLite stores the lineage and evidence, and the next attempt receives compact memory from previous rounds. Repeated stagnation wakes a separate supervisor pass that injects a new strategy without editing the target repository.

## What works in v0.2

- Persistent run, candidate, evaluator, memory, and role-invocation history in SQLite.
- Git worktree isolation and explicit candidate lineage.
- Weighted deterministic evaluators with either exit-code scoring or a one-line JSON score protocol.
- Automatic promotion of better candidates and a stable `avo/<run>/best` result branch.
- Episodic memory assembled from recent attempts and evaluator evidence.
- Stagnation detection plus a supervisor agent with cooldown.
- A generic command worker for any CLI coding agent.
- A NeMo Fabric worker with normalized model, tools, MCP, skills, harness settings, and telemetry configuration.
- Hermes, Codex, Claude, Deep Agents, or another supported Fabric adapter can be selected through `worker.adapter_id` when the corresponding adapter is installed.
- **Lazy multi-agent teams** with five built-in roles: orchestrator, architect, researcher, coder, and infrastructure.
- Per-role sparse worker overrides while inheriting shared model/tool/MCP configuration from one base worker.
- Progressive escalation: simple tasks start with the coder only; specialists are activated by task shape, explicit `@role` requests, or failed iterations.
- Aggregated per-role usage metadata when the underlying harness reports token usage.

The core deliberately remains small. Scheduling, distributed workers, semantic memory, and tree search are still outside the first execution path.

## Why the team is lazy

The default team policy is designed to avoid paying multi-agent overhead on every task:

```text
iteration 1, ordinary code task
  coder

iteration 1, infrastructure-shaped task
  infrastructure -> coder

iteration 2 after a failed evaluator
  architect -> orchestrator -> coder

iteration 3 after continued failure
  architect -> researcher -> orchestrator -> coder

repeated stagnation
  AVO supervisor -> next iteration
```

Explicit role mentions such as `@researcher`, `@architect`, or `@infrastructure` force that specialist for the current attempt. Role activation is deterministic and configurable, so the harness does not spend an extra LLM call deciding whether it should use another LLM.

All roles share the same candidate worktree. Role-specific worker configuration is a sparse override over the base `worker`, which means MCP servers, tool policy, skills, credentials, and default provider/model settings are configured once unless a role actually needs something different.

## Install

Core command-worker mode has no runtime dependencies beyond Python 3.11+ and Git:

```bash
python -m pip install -e .
```

For NeMo Fabric:

```bash
python -m pip install -e '.[nemo]'
```

For the current NeMo Fabric LangChain Deep Agents adapter and harness:

```bash
python -m pip install -e '.[deepagents]'
```

Codex and Claude Fabric extras are also available:

```bash
python -m pip install -e '.[codex]'
python -m pip install -e '.[claude]'
```

Hermes currently requires its own installation in addition to the matching NeMo Fabric adapter.

## Configure

Generate a starting config:

```bash
avo-harness init --repo /path/to/project --output avo.json
```

A minimal command-worker config looks like this:

```json
{
  "repo": "/path/to/project",
  "state_dir": "~/.local/state/avo-harness",
  "max_iterations": 12,
  "acceptance_score": 1.0,
  "worker": {
    "backend": "command",
    "command": ["your-agent", "--non-interactive"]
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

### Lazy five-role team

Enable the built-in team without duplicating worker configuration:

```json
{
  "worker": {
    "backend": "nemo",
    "adapter_id": "nvidia.fabric.langchain.deepagents",
    "provider": "openai",
    "model": "default-coding-model",
    "base_url": "http://rooter.example/v1",
    "api_key_env": "ROOTER_API_KEY",
    "mcp": {
      "servers": {
        "github": {
          "transport": "stdio",
          "url": "github-mcp-server"
        }
      }
    }
  },
  "team": {
    "enabled": true,
    "retry_after_iteration": 2,
    "deep_retry_after_iteration": 3,
    "roles": {
      "architect": {"worker": {"model": "strong-reasoning-model"}},
      "researcher": {"worker": {"model": "fast-research-model"}},
      "coder": {"worker": {"model": "best-coding-model"}},
      "infrastructure": {"worker": {"model": "best-coding-model"}},
      "orchestrator": {"worker": {"model": "strong-reasoning-model"}}
    }
  }
}
```

The MCP configuration above is inherited by all five roles. The role blocks only specify what differs.

Built-in activation policy:

| Role | Default activation |
| --- | --- |
| coder | every attempt |
| infrastructure | infra/container/CI/deployment task or explicit request |
| architect | architecture/refactor/migration task, explicit request, or iteration 2+ |
| researcher | research/dependency/upstream task, explicit request, or iteration 3+ |
| orchestrator | iteration 2+, explicit request, or when multiple specialists are active |

Triggers, prompts, models, backends, and role phases are configurable under `team.roles`.

### NeMo Fabric worker

A single NeMo worker configuration is the shared capability registry for the team:

```json
{
  "worker": {
    "backend": "nemo",
    "adapter_id": "nvidia.fabric.langchain.deepagents",
    "provider": "openai",
    "model": "qwen-coder",
    "api_key_env": "ROOTER_API_KEY",
    "base_url": "http://rooter.example/v1",
    "max_turns": 24,
    "tools": {"blocked": ["dangerous_tool"]},
    "mcp": {"servers": {}},
    "skills": {"paths": []},
    "harness_settings": {"deepagents": {}}
  }
}
```

AVO passes these fields into NeMo Fabric's normalized `FabricConfig`. Role overrides inherit them by default. NeMo Fabric adapters decide which normalized capabilities they support, so use `avo-harness doctor` and the Fabric adapter compatibility documentation when changing adapters.

## Evaluator protocol

An evaluator is any shell command. By default, exit code `0` scores `1.0` and a nonzero exit code scores `0.0`.

For partial credit, print a JSON object as the final non-empty stdout line:

```json
{"score": 0.72, "summary": "18 of 25 benchmark cases pass"}
```

`score` is clamped to `[0, 1]`. Multiple evaluator scores are combined by weight. This lets tests, lint, benchmarks, static analysis, or task-specific judges contribute independently.

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

Include recent role invocations, activation reasons, durations, and underlying worker metadata:

```bash
avo-harness status -c avo.json --roles
```

## How the AVO-style loop maps

| AVO-style concept | This implementation |
| --- | --- |
| Long-running main agent | repeated worker/team invocations against the best candidate |
| Persistent memory | SQLite trajectory + compact episodic prompt memory |
| Environment/tool use | real Git worktree exposed to the coding harness |
| External feedback | deterministic weighted evaluators |
| Supervisor intervention | isolated supervisor pass after configurable stagnation |
| Search/variation | candidate branches descending from the best known commit |
| Durable result | best commit + result branch + complete evidence trail |
| Multi-agent escalation | deterministic role activation inside one candidate attempt |
| Harness experimentation | worker backend/adapter/model can change without changing the AVO loop |

## Safety / operational boundaries

Workers have whatever filesystem/tool permissions their selected backend provides. Run powerful or untrusted agents in a disposable clone or sandbox. Evaluator commands are also arbitrary shell commands from your config.

The harness intentionally does **not** auto-merge, push, deploy, or mutate the target branch. It creates Git branches and linked worktrees only.
