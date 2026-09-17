from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from .auth import AuthStore
from .avogym import BenchmarkRunner, ExperimentSpec, write_report, write_strategy_policy
from .config import AVOConfig, WorkerConfig, example_config
from .gitops import GitRepo
from .orchestrator import Orchestrator
from .store import Store
from .worker import NeMoWorker


def _load(path: str) -> AVOConfig:
    return AVOConfig.load(path)


def cmd_init(args: argparse.Namespace) -> int:
    path = Path(args.output)
    if path.exists() and not args.force:
        print(f"refusing to overwrite {path}; use --force", file=sys.stderr)
        return 2
    config = example_config(args.repo)
    if args.state_dir is not None:
        config["state_dir"] = args.state_dir
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(path)
    return 0


def _check_worker(
    label: str,
    worker: WorkerConfig,
    workspace: Path,
    problems: list[str],
    warnings: list[str],
) -> None:
    if worker.backend == "command":
        executable = worker.command[0]
        if "{" not in executable and shutil.which(executable) is None:
            problems.append(f"{label} executable not found: {executable}")
        return

    # Importing nemo_fabric alone is not a usable-runtime check. The runtime can
    # import while having zero discoverable adapter descriptors, which is exactly
    # the failure mode that produces "available adapters: []" at execution time.
    # NeMoWorker.validate resolves the configured adapter and runs Fabric.doctor
    # without contacting the model.
    result = NeMoWorker(worker).validate(workspace)
    if not result.success:
        problems.append(f"{label}: {result.error}")
        return
    warnings.extend(
        f"{label}: {warning}"
        for warning in result.metadata.get("doctor_warnings", [])
    )


def _configured_workers(config: AVOConfig) -> list[tuple[str, WorkerConfig]]:
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
    return workers


def _check_configured_workers(config: AVOConfig) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    warnings: list[str] = []
    for label, worker in _configured_workers(config):
        _check_worker(label, worker, config.repo_path, problems, warnings)
    return list(dict.fromkeys(problems)), list(dict.fromkeys(warnings))


def _print_worker_diagnostics(problems: list[str], warnings: list[str]) -> None:
    for item in problems:
        print(f"FAIL: {item}")
    for item in warnings:
        print(f"WARN: {item}")


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

    worker_problems, warnings = _check_configured_workers(config)
    problems.extend(worker_problems)
    problems = list(dict.fromkeys(problems))
    _print_worker_diagnostics(problems, warnings)
    if problems:
        return 1
    print("OK: configuration, adapters, harnesses, and runtime prerequisites look usable")
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
            payload["role_runs"] = [dict(item) for item in store.recent_role_runs(run_id, args.limit)]
        print(json.dumps(payload, indent=2))
        return 0
    finally:
        store.close()


def cmd_benchmark(args: argparse.Namespace) -> int:
    spec = ExperimentSpec.load(args.experiment)
    report = BenchmarkRunner(spec).run()
    json_path, html_path = write_report(report, args.output)
    policy_path = write_strategy_policy(report, args.output)
    print(json.dumps(report.variants, indent=2))
    print(f"JSON: {json_path}")
    print(f"HTML: {html_path}")
    print(f"Routing policy: {policy_path}")
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError:
        print("web dependencies are missing; install avo-harness[web]", file=sys.stderr)
        return 2
    from .api_chat import create_app

    # Fail before binding a port if the configured worker stack cannot actually
    # resolve its adapter/harness or lacks Hermes' required credential variable.
    # This intentionally does not call the model endpoint. Connectivity remains
    # an execution-time concern, but install/runtime mistakes should never hide
    # behind a web server that appears healthy until its first chat request.
    config = _load(args.config)
    problems, warnings = _check_configured_workers(config)
    _print_worker_diagnostics(problems, warnings)
    if problems:
        return 2

    uvicorn.run(create_app(args.config), host=args.host, port=args.port, log_level=args.log_level)
    return 0


def cmd_auth_bootstrap(args: argparse.Namespace) -> int:
    config = _load(args.config)
    store = AuthStore(config.state_path / "state.sqlite3")
    try:
        try:
            code, expires_at = store.issue_bootstrap_code(ttl_minutes=args.minutes)
        except RuntimeError as exc:
            print(f"FAIL: {exc}", file=sys.stderr)
            return 1
        print("Avo passkey enrollment code")
        print(code)
        print(f"Expires: {expires_at}")
        print("Open the Avo web/iOS app and use this code once to create the first passkey.")
        return 0
    finally:
        store.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="avo-harness")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="write an example JSON configuration")
    init.add_argument("--repo", default=".")
    init.add_argument("--output", default="avo.json")
    init.add_argument(
        "--state-dir",
        help="persistent state directory written into the generated configuration",
    )
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

    web = sub.add_parser("web", help="serve the unified chat-first web/iOS control plane")
    web.add_argument("-c", "--config", default="avo.json")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8765)
    web.add_argument("--log-level", default="info")
    web.set_defaults(func=cmd_web)

    auth = sub.add_parser("auth", help="manage single-user passkey authentication")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    bootstrap = auth_sub.add_parser("bootstrap", help="issue a one-time first-passkey enrollment code")
    bootstrap.add_argument("-c", "--config", default="avo.json")
    bootstrap.add_argument("--minutes", type=int, default=10, help="enrollment code lifetime")
    bootstrap.set_defaults(func=cmd_auth_bootstrap)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
