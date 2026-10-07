"""Explicit, non-shell GitHub workspace connection."""

from __future__ import annotations

import subprocess
from pathlib import Path
from urllib.parse import urlparse

from .guards import OutputGuard
from .workspace import WorkspaceError


def validate_github_url(value: str) -> str:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in {"github.com", "www.github.com"}:
        raise WorkspaceError("Only HTTPS URLs hosted on github.com are accepted")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2 or not parts[1].removesuffix(".git"):
        raise WorkspaceError("Expected a repository URL such as https://github.com/owner/repository")
    if parsed.query or parsed.fragment:
        raise WorkspaceError("Repository URLs must not contain a query or fragment")
    return f"https://github.com/{parts[0]}/{parts[1].removesuffix('.git')}.git"


def clone_github_repo(url: str, destination: str | Path, branch: str | None = None) -> Path:
    normalized_url = validate_github_url(url)
    target = Path(destination).expanduser().resolve()
    if target.exists() and any(target.iterdir()):
        raise WorkspaceError(f"Destination must be empty: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    command = ["git", "clone"]
    if branch:
        if branch.startswith("-") or any(char.isspace() for char in branch):
            raise WorkspaceError("Invalid branch name")
        command.extend(["--branch", branch])
    command.extend(["--", normalized_url, str(target)])
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False, shell=False)
    except subprocess.TimeoutExpired as exc:
        raise WorkspaceError("git clone timed out") from exc
    if completed.returncode != 0:
        message = OutputGuard.redact_for_log((completed.stdout + completed.stderr).strip())
        raise WorkspaceError(f"git clone failed: {message[-2000:]}")
    return target
