import json
from pathlib import Path

from avo_harness.api import _benchmark_detail, _benchmark_entries


def write_report(folder: Path, experiment: str, variant: str = "single") -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "report.json").write_text(
        json.dumps(
            {
                "experiment": experiment,
                "trials": [{"variant": variant}],
                "variants": {
                    variant: {
                        "trials": 1,
                        "oracle_solve_rate": 1.0,
                        "mean_oracle_score": 1.0,
                        "mean_total_tokens": 1234,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (folder / "routing-policy.json").write_text(
        json.dumps(
            {
                "version": 1,
                "selection": "quality-first-then-efficiency",
                "default": {
                    "variant": variant,
                    "trials": 1,
                    "solve_rate": 1.0,
                    "mean_oracle_score": 1.0,
                    "mean_tokens": 1234,
                    "mean_wall_seconds": 4.2,
                    "mean_cost_usd": 0.0,
                },
                "by_tag": {},
            }
        ),
        encoding="utf-8",
    )


def test_benchmark_entries_are_recursive_and_newest_first(tmp_path: Path) -> None:
    old = tmp_path / "representative" / "old"
    new = tmp_path / "representative" / "new"
    write_report(old, "old-run", "goose-single")
    write_report(new, "new-run", "lazy-team")
    (old / "report.json").touch()
    (new / "report.json").touch()

    entries = _benchmark_entries(tmp_path)
    assert {item["id"] for item in entries} == {"representative/old", "representative/new"}
    by_id = {item["id"]: item for item in entries}
    assert by_id["representative/new"]["experiment"] == "new-run"
    assert by_id["representative/new"]["trial_count"] == 1
    assert by_id["representative/new"]["variant_count"] == 1
    assert by_id["representative/new"]["default_strategy"] == "lazy-team"


def test_benchmark_detail_returns_report_and_policy(tmp_path: Path) -> None:
    target = tmp_path / "suite" / "run-1"
    write_report(target, "suite-one", "hermes-single")

    detail = _benchmark_detail(tmp_path, "suite/run-1")
    assert detail is not None
    assert detail["report"]["experiment"] == "suite-one"
    assert detail["routing_policy"]["default"]["variant"] == "hermes-single"


def test_benchmark_detail_rejects_path_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-benchmark"
    write_report(outside, "outside")
    assert _benchmark_detail(tmp_path, "../outside-benchmark") is None
