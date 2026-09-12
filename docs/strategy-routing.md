# Benchmark-driven strategy routing

AvoGym can now compare execution strategies, including different harnesses, models, and lazy-team configurations, while holding the task and hidden oracle fixed.

Each trial records:

- hidden-oracle success and score
- visible evaluator score and evaluator gap
- wall time and iteration count
- local/cloud invocation counts
- input/output model tokens when the backend reports them
- lazy-team role invocation count and wall time
- per-role token/time breakdown when role usage is available
- reported provider cost when available

The benchmark report includes `tokens_per_oracle_solve`, which is more useful than raw token count when comparing harnesses that have different success rates.

## Routing policy

`avo-harness benchmark` writes `routing-policy.json` beside the JSON/HTML report. The policy contains a global default plus choices for task tags supplied by the benchmark dataset.

Selection is deterministic and quality-first:

1. highest hidden-oracle solve rate
2. highest mean hidden-oracle score
3. lowest mean token use
4. lowest mean wall time
5. lowest reported cost

This means a cheap strategy cannot become preferred merely by failing quickly.

Example shape:

```json
{
  "version": 1,
  "selection": "quality-first-then-efficiency",
  "default": {
    "variant": "single-goose-local"
  },
  "by_tag": {
    "bugfix": {
      "variant": "single-goose-local"
    },
    "infra": {
      "variant": "lazy-team"
    }
  }
}
```

The policy is deliberately an artifact, not an opaque learned model. A future runtime router can consume it directly while retaining deterministic fallbacks and explicit operator overrides.

## Recommended experiment design

Use the same underlying model/provider when first comparing harness behavior. Once a harness baseline is established, add model changes as separate variants. Otherwise model quality and harness overhead become confounded.

Useful initial variants are:

- single worker with the leanest coding harness
- lazy team with the same primary model
- alternative coding harness with the same primary model
- stronger cloud fallback only after stagnation

Tag tasks by the property you actually want the router to learn, such as `bugfix`, `feature`, `repo-analysis`, `migration`, `infra`, or `refactor`. Keep hidden oracle checks external to the candidate repository so a worker cannot improve its benchmark score by weakening visible tests.
