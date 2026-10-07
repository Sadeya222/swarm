"""Command-line interface for the guarded coding agent."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

from .config import load_env_file
from .github import clone_github_repo
from .orchestrator import CodingOrchestrator
from .workspace import ProjectScaffolder, Workspace, WorkspaceError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="swarm", description="A guarded local-first coding agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="scaffold a new Python 3.10+ project")
    init.add_argument("name")
    init.add_argument("--directory", default=".", help="parent directory for the new project")

    connect = subparsers.add_parser("connect", help="connect an existing GitHub repository")
    connect_sub = connect.add_subparsers(dest="connect_command", required=True)
    github = connect_sub.add_parser("github", help="clone a GitHub repository over HTTPS")
    github.add_argument("url")
    github.add_argument("--directory", required=True, help="empty destination directory")
    github.add_argument("--branch")

    vscode = subparsers.add_parser("vscode", help="add VS Code workspace settings without overwriting existing files")
    vscode.add_argument("--workspace", default=".")

    run = subparsers.add_parser("run", help="preview or apply a coding request")
    run.add_argument("prompt", nargs="+", help="the coding request")
    run.add_argument("--workspace", default=".")
    run.add_argument("--apply", action="store_true", help="allow the configured model to edit the workspace")
    run.add_argument("--model", help="provider-qualified model name, for example openai:gpt-4.1-mini")
    run.add_argument("--env-file", help="explicit local file containing supported provider settings")
    run.add_argument("--json", action="store_true", dest="as_json")

    check = subparsers.add_parser("check", help="run bounded compile and test checks")
    check.add_argument("--workspace", default=".")
    check.add_argument("--json", action="store_true", dest="as_json")

    subparsers.add_parser("doctor", help="report local setup without printing credential values")
    return parser


def _print_result(value: dict, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(value, indent=2))
        return
    print(f"Status: {value.get('status', 'ok')}")
    if value.get("message"):
        print(value["message"])
    if value.get("plan"):
        print("\nPlan:")
        for index, item in enumerate(value["plan"], 1):
            print(f"  {index}. {item}")
    if value.get("response"):
        print("\nAgent response:\n" + value["response"])
    if value.get("checks"):
        print("\nChecks:")
        for check in value["checks"]:
            status = "SKIP" if check["skipped"] else ("PASS" if check["passed"] else "FAIL")
            print(f"  {status}  {check['command']}")
            if check.get("output"):
                print(check["output"])
    if value.get("artifact_dir"):
        print(f"\nRun artifacts: {value['artifact_dir']}")


def _doctor() -> dict:
    keys = [name for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY") if os.getenv(name)]
    return {
        "status": "ok",
        "python": sys.version.split()[0],
        "python_supported": sys.version_info >= (3, 10),
        "git": shutil.which("git") is not None,
        "deepagents_installed": importlib.util.find_spec("deepagents") is not None,
        "langchain_installed": importlib.util.find_spec("langchain") is not None,
        "configured_provider_keys": keys,
        "model": os.getenv("SWARM_MODEL", "openai:gpt-4.1-mini"),
        "note": "Key names are shown only as a setup check; values are never printed or persisted.",
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if getattr(args, "env_file", None):
            load_env_file(args.env_file)
        if args.command == "init":
            path = ProjectScaffolder.create(args.directory, args.name)
            print(f"Created project at {path}")
            print("Open that directory in VS Code, create a virtual environment, and install its dependencies.")
            return 0
        if args.command == "connect" and args.connect_command == "github":
            path = clone_github_repo(args.url, args.directory, args.branch)
            print(f"Connected GitHub repository at {path}")
            return 0
        if args.command == "vscode":
            files = ProjectScaffolder.configure_vscode(Workspace(args.workspace))
            print("Configured:")
            for path in files:
                print(f"  {path}")
            return 0
        if args.command == "check":
            checks = Workspace(args.workspace).run_checks()
            value = {"status": "passed" if all(check.passed or check.skipped for check in checks) else "failed", "checks": [check.to_dict() for check in checks]}
            _print_result(value, args.as_json)
            return 0 if value["status"] == "passed" else 1
        if args.command == "doctor":
            _print_result(_doctor())
            return 0
        if args.command == "run":
            prompt = " ".join(args.prompt)
            result = CodingOrchestrator(Workspace(args.workspace)).run(prompt, apply=args.apply, model_name=args.model)
            _print_result(result.to_dict(), args.as_json)
            return 0 if result.status not in {"blocked", "blocked_output", "needs_review", "needs_setup", "completed_with_failures"} else 1
    except (WorkspaceError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
