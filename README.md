# Swarm guarded coding agent

Swarm is a local-first Python 3.10+ coding-agent starter. It combines a small, dependency-free safety boundary with an optional [LangChain Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview) runtime.

It is designed for a personal learning project that can:

- preview a coding request before making any model call;
- inspect a repository and delegate research, planning, implementation, and review to isolated Deep Agent sub-agents;
- work against a selected local workspace or a GitHub repository cloned over HTTPS;
- create a real `src/`, `tests/`, `pyproject.toml`, `.vscode/`, and `AGENTS.md` project layout;
- run bounded compile and pytest checks without using a shell; and
- redact secrets from model output and run artifacts.

## Important boundary

I did **not** implement a prompt-filter bypass. Encoding, translation, roleplay, indirect injection, payload fragmentation, and output obfuscation are common ways to evade safety controls, so this project detects those signals and fails closed for explicit evasion or harmful requests. It does not rewrite a disallowed task into an allowed one. This keeps the coding agent useful for ordinary and defensive development without turning it into an evasion or malware tool.

The guards are a useful first layer, not a complete security boundary. Run the agent with least-privilege credentials, review diffs, use disposable workspaces, and do not give an LLM production access.

## Quick start

Create an isolated environment and install the project:

```bash
python3.10 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[quality]'
```

Preview a request. Preview is the default and does not call an LLM or change files:

```bash
swarm run --workspace ./my-project "Add a JSON health-check endpoint with unit tests"
```

After reviewing the plan, explicitly allow the configured Deep Agent to edit the workspace:

```bash
export OPENAI_API_KEY='...'
export SWARM_MODEL='openai:gpt-4.1-mini'
swarm run --apply --workspace ./my-project "Add a JSON health-check endpoint with unit tests"

# Or explicitly select an untracked local file with only these supported keys:
swarm run --apply --env-file .env --workspace ./my-project "Add a JSON health-check endpoint with unit tests"
```

Supported provider model names depend on the installed LangChain integration. Examples include `openai:...` and other provider-qualified names. API key values are never printed by `doctor`. Swarm does not auto-load a repository `.env`; use shell exports or the explicit `--env-file` option. Only `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, and `SWARM_MODEL` are read from that file.

## CLI

```text
swarm init NAME [--directory PARENT]
swarm connect github URL --directory EMPTY_DESTINATION [--branch BRANCH]
swarm vscode --workspace PATH
swarm run [--apply] [--model MODEL] [--workspace PATH] REQUEST...
swarm check --workspace PATH
swarm doctor
```

### New project structure

```bash
swarm init inventory-service --directory ~/src
cd ~/src/inventory-service
python -m venv .venv
. .venv/bin/activate
pip install -e '.[quality]'
```

The scaffold includes:

```text
inventory-service/
├── AGENTS.md
├── .env.example
├── .gitignore
├── .vscode/
├── pyproject.toml
├── src/inventory_service/
└── tests/
```

`swarm vscode` adds settings and a test task without overwriting existing VS Code files. The CLI is the integration point for a VS Code workspace; no editor extension or local browser service is required.

### Connect a GitHub repository

The connection command only accepts HTTPS URLs on `github.com`, invokes `git` with an argument list rather than a shell, and requires an empty destination:

```bash
swarm connect github https://github.com/owner/repository --directory ~/src/repository
cd ~/src/repository
swarm run --workspace . "Add ..."
```

GitHub authentication is handled by the user's existing Git credential helper or SSH/HTTPS setup; Swarm does not ask for or store tokens.

## Workflow design

1. **Input guard** normalizes Unicode for analysis, detects explicit guardrail evasion, credential theft, destructive access, exfiltration, instruction injection, unsafe execution, and risky Base64/hex fragments. It returns `safe`, `review`, or `blocked` and never turns a blocked prompt into a rewritten prompt.
2. **Core agent policy** treats user text, repository files, issue text, and tool output as untrusted data. Deep Agents receives a system policy and four contracts: researcher, planner, implementer, and reviewer.
3. **Deep Agent workspace** uses `FilesystemBackend` rooted at the selected workspace. The integration intentionally does not install packages or expose an unrestricted shell to the model. Package installation and checks are explicit CLI operations.
4. **Output guard** redacts private keys and common API/token formats, then withholds obviously destructive or malware-like output.
5. **Verification** runs `python -m compileall -q .` and, when available, `pytest -q` with a timeout, no shell, and no stdin. Run artifacts are written under `.swarm/runs/` with redacted request/response text.

## Development

The core tests do not require an API key or model package:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

If pytest is installed:

```bash
pytest -q
```

## Known limitations and next safe steps

- The input and output guards are regex and heuristic based. For production, add a reviewed policy service, audit logging with data minimization, human approval for writes, and sandboxed execution.
- A model can edit files during an `--apply` run, so use a disposable branch/worktree and review `git diff` before committing.
- GitHub cloning supports public or credential-helper-authenticated HTTPS repositories. A future connector can use an explicit GitHub App or OAuth integration, but must keep tokens outside prompts and logs.
- The current CLI is intentionally small. A VS Code extension or web UI should call the same orchestrator rather than duplicate guard logic.
