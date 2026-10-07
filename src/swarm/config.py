"""Explicit loading of local model configuration without exposing secrets."""

from __future__ import annotations

import os
from pathlib import Path

_ALLOWED_KEYS = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "SWARM_MODEL"}


def load_env_file(path: str | os.PathLike[str]) -> None:
    """Load only supported Swarm settings from an explicitly selected file.

    Swarm never auto-loads a repository's ``.env`` file. This prevents a cloned
    repository from silently changing provider settings. Values already present
    in the process environment win over file values.
    """

    try:
        from dotenv import dotenv_values
    except ImportError as exc:  # pragma: no cover - dependency is in pyproject
        raise RuntimeError("python-dotenv is required for --env-file") from exc
    env_path = Path(path).expanduser().resolve()
    if not env_path.is_file():
        raise ValueError(f"Environment file does not exist: {env_path}")
    for key, value in dotenv_values(env_path).items():
        if key in _ALLOWED_KEYS and value is not None and key not in os.environ:
            os.environ[key] = value
