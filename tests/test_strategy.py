from dataclasses import dataclass, field

from avo_harness.strategy import build_strategy_policy, choose_strategy, select_policy_variant


@dataclass
class Trial:
    variant: str
    oracle_passed: bool
    oracle_score: float
    wall_seconds: float
    reported_cost_usd: float
    input_tokens: int
    output_tokens: int
    tags: list[str] = field(default_factory=list)


def test_quality_beats_cheaper_failure() -> None:
    trials = [
        Trial("cheap", False, 0.4, 1.0, 0.0, 10, 10, ["bugfix"]),
        Trial("reliable", True, 1.0, 10.0, 1.0, 1000, 1000, ["bugfix"]),
    ]
    choice = choose_strategy(trials)
    assert choice is not None
    assert choice.variant == "reliable"


def test_efficiency_breaks_quality_tie() -> None:
    trials = [
        Trial("lean", True, 1.0, 5.0, 0.1, 100, 100),
        Trial("heavy", True, 1.0, 4.0, 0.05, 1000, 1000),
    ]
    choice = choose_strategy(trials)
    assert choice is not None
    assert choice.variant == "lean"


def test_policy_learns_tag_specific_variant_and_falls_back() -> None:
    trials = [
        Trial("coder-only", True, 1.0, 2.0, 0.0, 50, 50, ["bugfix"]),
        Trial("team", True, 1.0, 6.0, 0.0, 500, 500, ["bugfix"]),
        Trial("coder-only", False, 0.2, 2.0, 0.0, 50, 50, ["infra"]),
        Trial("team", True, 1.0, 6.0, 0.0, 500, 500, ["infra"]),
    ]
    policy = build_strategy_policy(trials)
    assert policy["by_tag"]["bugfix"]["variant"] == "coder-only"
    assert policy["by_tag"]["infra"]["variant"] == "team"
    assert select_policy_variant(policy, ["infra"]) == "team"
    assert select_policy_variant(policy, ["unknown"]) == policy["default"]["variant"]
