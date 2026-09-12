from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import mean
from typing import Any, Iterable, Protocol


class TrialLike(Protocol):
    variant: str
    oracle_passed: bool
    oracle_score: float
    wall_seconds: float
    reported_cost_usd: float
    input_tokens: int
    output_tokens: int
    tags: list[str]


@dataclass(slots=True)
class StrategyChoice:
    variant: str
    trials: int
    solve_rate: float
    mean_oracle_score: float
    mean_tokens: float
    mean_wall_seconds: float
    mean_cost_usd: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _stats(trials: list[TrialLike], variant: str) -> StrategyChoice:
    selected = [trial for trial in trials if trial.variant == variant]
    total_tokens = [trial.input_tokens + trial.output_tokens for trial in selected]
    return StrategyChoice(
        variant=variant,
        trials=len(selected),
        solve_rate=mean(1.0 if trial.oracle_passed else 0.0 for trial in selected),
        mean_oracle_score=mean(trial.oracle_score for trial in selected),
        mean_tokens=mean(total_tokens),
        mean_wall_seconds=mean(trial.wall_seconds for trial in selected),
        mean_cost_usd=mean(trial.reported_cost_usd for trial in selected),
    )


def choose_strategy(trials: Iterable[TrialLike]) -> StrategyChoice | None:
    """Choose a strategy quality-first, then minimize execution overhead.

    This is deliberately deterministic. Solve rate and hidden-oracle score dominate;
    tokens, wall time, and reported cost only break quality ties. A routing policy
    therefore cannot learn to prefer a cheap strategy that simply fails more often.
    """

    items = list(trials)
    variants = sorted({trial.variant for trial in items})
    if not variants:
        return None
    choices = [_stats(items, variant) for variant in variants]
    return min(
        choices,
        key=lambda choice: (
            -choice.solve_rate,
            -choice.mean_oracle_score,
            choice.mean_tokens,
            choice.mean_wall_seconds,
            choice.mean_cost_usd,
            choice.variant,
        ),
    )


def build_strategy_policy(trials: Iterable[TrialLike]) -> dict[str, Any]:
    items = list(trials)
    default = choose_strategy(items)
    by_tag: dict[str, dict[str, Any]] = {}
    tags = sorted({tag for trial in items for tag in trial.tags})
    for tag in tags:
        tagged = [trial for trial in items if tag in trial.tags]
        choice = choose_strategy(tagged)
        if choice is not None:
            by_tag[tag] = choice.to_dict()
    return {
        "version": 1,
        "selection": "quality-first-then-efficiency",
        "default": default.to_dict() if default is not None else None,
        "by_tag": by_tag,
    }


def select_policy_variant(policy: dict[str, Any], tags: Iterable[str]) -> str | None:
    """Resolve a benchmark policy for a task without invoking a model.

    When several tags match, prefer the choice backed by the most trials, then the
    highest solve rate/oracle score. Fall back to the global default.
    """

    candidates: list[dict[str, Any]] = []
    by_tag = policy.get("by_tag", {})
    if isinstance(by_tag, dict):
        for tag in tags:
            choice = by_tag.get(tag)
            if isinstance(choice, dict) and choice.get("variant"):
                candidates.append(choice)
    if candidates:
        selected = min(
            candidates,
            key=lambda choice: (
                -int(choice.get("trials", 0)),
                -float(choice.get("solve_rate", 0.0)),
                -float(choice.get("mean_oracle_score", 0.0)),
                float(choice.get("mean_tokens", float("inf"))),
                str(choice.get("variant")),
            ),
        )
        return str(selected["variant"])
    default = policy.get("default")
    if isinstance(default, dict) and default.get("variant"):
        return str(default["variant"])
    return None
