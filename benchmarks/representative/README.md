# Representative harness strategy benchmark

This suite answers a narrow question: which harness/team strategy completes representative coding work with the best hidden-oracle quality for the least token/time overhead?

## Corpus

`prepare.py` generates five isolated Git repositories with deliberately incomplete visible tests and stricter external oracles:

- `bugfix-normalize` — small bugfix plus hidden input-validation cases
- `repo-analysis-settings` — trace precedence/coercion across multiple files
- `migration-config-v2` — backwards-compatible schema migration
- `infra-compose-health` — Docker Compose/runtime configuration
- `feature-ttl-cache` — stateful feature implementation and expiry edge cases

The initial repository for every task fails its visible evaluator, so AVO must actually invoke a worker. The hidden oracle is outside the candidate repository and is never injected into agent context.

## Strategies

`experiment.json` compares the same task corpus across:

- Hermes single worker
- Hermes lazy team
- LangChain Deep Agents single worker
- LangChain Deep Agents lazy team
- Codex single worker
- Codex lazy team
- Goose single worker
- Goose lazy team

The NeMo Fabric variants inherit the same provider/model/base URL from `base.local.json`. This is intended to hold the model constant while changing the harness.

Goose runs through the generic command worker using `goose run --text`. Configure Goose separately to use the same Rooter/local model before treating Goose results as an apples-to-apples model comparison. Goose's current CLI supports headless `run --text` execution.

## Prepare

```bash
python benchmarks/representative/prepare.py
```

Then edit `benchmarks/representative/base.local.json` so `model` and `base_url` point to the model under test. The checked-in defaults assume an OpenAI-compatible local endpoint at `http://127.0.0.1:8000/v1` and a placeholder model ID `local-coder`.

Install the harness adapters you plan to benchmark. NeMo Fabric currently maintains adapters for Hermes, Codex, Claude, LangChain Deep Agents, and mini-SWE-agent. The strategy file uses `nvidia.fabric.hermes`, `nvidia.fabric.langchain.deepagents`, and `nvidia.fabric.codex`.

## Run

```bash
avo-harness benchmark benchmarks/representative/experiment.json \
  -o benchmarks/representative/reports/local-harnesses
```

The run emits:

- `report.json` — per-trial quality, tokens, time, cost, and role breakdown
- `report.html` — comparison table
- `routing-policy.json` — quality-first global and task-tag strategy recommendations

With eight strategies, five tasks, and two seeds, a full run is 80 trials. For a quick smoke test, temporarily reduce the strategy list and use one seed.

## Interpretation

Do not choose the harness with the fewest tokens in isolation. Routing policy ranks hidden-oracle solve rate first, then oracle score, then token use, wall time, and reported cost. A cheap failure therefore cannot beat a more expensive strategy that consistently solves the task.

The most useful comparisons are:

1. `*-single` vs the matching `*-lazy-team`, measuring whether specialist roles earn their overhead.
2. Hermes vs Deep Agents with the same local model, measuring pure harness effects.
3. Goose vs the Fabric variants after Goose is configured to the same model/provider.
4. Tag-specific winners, especially `infra`, `migration`, `repo-analysis`, and `small-change`, to determine when AVO should escalate beyond the lean single-worker path.
