from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from .avogym import BenchmarkRunner, ExperimentSpec, write_report
from .config import AVOConfig, WorkerConfig, example_config
from .gitops import GitRepo
from .orchestrator import Orchestrator
from .store import Store


def _load(path: str) -> AVOConfig:
    return AVOConfig.load(path)


def cmd_init(args: argparse.Namespace) -> int:
    path = Path(args.output)
    if path.exists() and not args.force:
        print(f"refusing to overwrite {path}; use --force", file=sys.stderr)
        return 2
    path.write_text(json.dumps(example_config(args.repo), indent=2) + "\n", encoding="utf-8")
    print(path)
    return 0


def _check_worker(label: str, worker: WorkerConfig, problems: list[str]) -> None:
    if worker.backend == "command":
        executable = worker.command[0]
        if "{" not in executable and shutil.which(executable) is None:
            problems.append(f"{label} executable not found: {executable}")
    else:
        try:
            import nemo_fabric  # noqa: F401
        except ImportError:
            problems.append(f"{label}: nemo_fabric is not installed; install avo-harness[nemo]")


def cmd_doctor(args: argparse.Namespace) -> int:
    config = _load(args.config)
    problems: list[str] = []
    if shutil.which("git") is None:
        problems.append("git is not installed")
    else:
        try:
            GitRepo(config.repo_path, config.state_path / "worktrees").validate(
                allow_dirty=config.allow_dirty_repo
            )
        except Exception as exc:
            problems.append(str(exc))

    workers: list[tuple[str, WorkerConfig]] = [("worker", config.worker)]
    if config.planner.enabled and config.planner.worker is not None:
        workers.append(("planner", config.planner.worker))
    if config.supervisor.enabled and config.supervisor.worker is not None:
        workers.append(("supervisor", config.supervisor.worker))
    if config.team.enabled:
        workers.extend(
            (f"team.roles.{name}", worker)
            for name, worker in config.team.resolved_workers(config.worker).items()
        )
    for label, worker in workers:
        _check_worker(label, worker, problems)

    if problems:
        for item in dict.fromkeys(problems):
            print(f"FAIL: {item}")
        return 1
    print("OK: configuration and runtime prerequisites look usable")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config = _load(args.config)
    orchestrator = Orchestrator(config)
    try:
        summary = orchestrator.run(args.objective)
        print(json.dumps(summary.to_dict(), indent=2))
        return 0 if summary.status == "accepted" else 3
    finally:
        orchestrator.close()


def cmd_status(args: argparse.Namespace) -> int:
    config = _load(args.config)
    store = Store(config.state_path / "state.sqlite3")
    try:
        row = store.get_run(args.run_id) if args.run_id else store.latest_run()
        if row is None:
            print("no runs found", file=sys.stderr)
            return 1
        run_id = str(row["id"])
        payload: dict[str, object] = dict(row)
        payload["metadata"] = store.get_run_metadata(run_id)
        payload["invocations"] = store.invocation_summary(run_id)
        if args.roles:
            payload["role_runs"] = [
                dict(item) for item in store.recent_role_runs(run_id, args.limit)
            ]
        print(json.dumps(payload, indent=2))
        return 0
    finally:
        store.close()


def cmd_benchmark(args: argparse.Namespace) -> int:
    spec = ExperimentSpec.load(args.experiment)
    report = BenchmarkRunner(spec).run()
    json_path, html_path = write_report(report, args.output)
    print(json.dumps(report.variants, indent=2))
    print(f"JSON: {json_path}")
    print(f"HTML: {html_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="avo-harness")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="write an example JSON configuration")
    init.add_argument("--repo", default=".")
    init.add_argument("--output", default="avo.json")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    doctor = sub.add_parser("doctor", help="validate configuration and prerequisites")
    doctor.add_argument("-c", "--config", default="avo.json")
    doctor.set_defaults(func=cmd_doctor)

    run = sub.add_parser("run", help="run the long-horizon optimization loop")
    run.add_argument("objective")
    run.add_argument("-c", "--config", default="avo.json")
    run.set_defaults(func=cmd_run)

    status = sub.add_parser("status", help="show a persisted run")
    status.add_argument("run_id", nargs="?")
    status.add_argument("-c", "--config", default="avo.json")
    status.add_argument("--roles", action="store_true", help="include recent lazy-team role invocations")
    status.add_argument("--limit", type=int, default=50, help="maximum role invocations to include")
    status.set_defaults(func=cmd_status)

    benchmark = sub.add_parser("benchmark", help="run an AvoGym benchmark/ablation experiment")
    benchmark.add_argument("experiment")
    benchmark.add_argument("-o", "--output", default="avogym-report")
    benchmark.set_defaults(func=cmd_benchmark)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
