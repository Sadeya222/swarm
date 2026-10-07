"""Optional LangChain Deep Agents integration.

Importing this module does not require the optional model packages. That keeps
input guardrails and local commands usable before a provider is configured.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .policy import SUBAGENTS, SYSTEM_PROMPT, WORKFLOW_PROMPT


class DeepAgentSetupError(RuntimeError):
    """Raised when the optional model runtime is not configured."""


@dataclass(frozen=True)
class AgentReply:
    text: str


# Deliberately omit delete and execute. FilesystemBackend does not provide a
# shell, but hiding those tools makes the safety intent explicit. Deny reads and
# writes for the most common credential-bearing paths as defense in depth.
_SAFE_FILESYSTEM_TOOLS = ["ls", "read_file", "write_file", "edit_file", "glob", "grep"]


def _secret_permissions(filesystem_permission_type: Any) -> list[Any]:
    return [
        filesystem_permission_type(
            operations=["read", "write"],
            paths=[
                "/**/.env",
                "/**/*.env",
                "/**/.env.*",
                "/**/*.pem",
                "/**/*.key",
                "/**/.git/**",
                "/**/secrets/**",
            ],
            mode="deny",
        )
    ]


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return str(content) if content is not None else ""


def _last_response_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    messages = result.get("messages", []) if isinstance(result, dict) else []
    if messages:
        last = messages[-1]
        content = getattr(last, "content", last.get("content") if isinstance(last, dict) else last)
        return _content_to_text(content)
    return _content_to_text(result)


def create_agent(workspace: Path, model_name: str | None = None) -> Any:
    """Construct a Deep Agent with a virtual filesystem rooted at ``workspace``."""

    try:
        from deepagents import create_deep_agent
        from deepagents.backends import FilesystemBackend
        from deepagents.middleware.filesystem import FilesystemMiddleware, FilesystemPermission
        from langchain.chat_models import init_chat_model
    except ImportError as exc:
        raise DeepAgentSetupError(
            "Deep Agents dependencies are not installed. Run: pip install -e '.[quality]'"
        ) from exc

    model_name = model_name or os.getenv("SWARM_MODEL", "openai:gpt-4.1-mini")
    try:
        model = init_chat_model(model=model_name)
        backend = FilesystemBackend(root_dir=str(workspace), virtual_mode=True)
        permissions = _secret_permissions(FilesystemPermission)
        main_filesystem = FilesystemMiddleware(
            backend=backend,
            tools=_SAFE_FILESYSTEM_TOOLS,
            _permissions=permissions,
        )
        safe_subagents = [
            {
                **spec,
                "permissions": permissions,
                "middleware": [
                    FilesystemMiddleware(
                        backend=backend,
                        tools=_SAFE_FILESYSTEM_TOOLS,
                        _permissions=permissions,
                    )
                ],
            }
            for spec in SUBAGENTS
        ]
        return create_deep_agent(
            model=model,
            backend=backend,
            system_prompt=SYSTEM_PROMPT,
            middleware=[main_filesystem],
            permissions=permissions,
            subagents=safe_subagents,
        )
    except Exception as exc:  # provider and dependency configuration errors vary by integration
        raise DeepAgentSetupError(f"Could not configure model {model_name!r}: {exc}") from exc


def invoke_agent(agent: Any, request: str, thread_id: str) -> AgentReply:
    prompt = f"{WORKFLOW_PROMPT}\n\nApproved user request:\n---\n{request}\n---"
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": prompt}]},
            config={"configurable": {"thread_id": thread_id}},
        )
    except Exception as exc:
        raise DeepAgentSetupError(f"The model request failed: {exc}") from exc
    return AgentReply(_last_response_text(result))
