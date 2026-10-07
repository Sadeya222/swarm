"""The guarded two-stage coding workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from .deep_agent import DeepAgentSetupError, create_agent, invoke_agent
from .guards import InputGuard, OutputGuard
from .models import RiskLevel, RunResult
from .workspace import Workspace

DEFAULT_PLAN = (
    "Inspect the workspace and identify relevant files, package metadata, and existing tests.",
    "Research the APIs and dependencies needed for the approved request; record assumptions.",
    "Create a small implementation plan with acceptance criteria and a rollback-friendly file list.",
    "Implement the plan inside the selected workspace without storing credentials or weakening guardrails.",
    "Review the diff, run bounded tests, and report changed files, test results, and follow-up items.",
)


@dataclass
class CodingOrchestrator:
    workspace: Workspace
    input_guard: InputGuard = field(default_factory=InputGuard)
    output_guard: OutputGuard = field(default_factory=OutputGuard)

    def preview(self, prompt: str) -> RunResult:
        decision = self.input_guard.inspect(prompt)
        if not decision.allowed:
            return RunResult(
                status="blocked",
                message="I can't help bypass safety controls or build credential theft, malware, destructive access, or exfiltration tooling.",
                prompt_decision=decision,
                plan=DEFAULT_PLAN,
            )
        return RunResult(
            status="review" if decision.risk.value == "review" else "planned",
            message="Dry run only: no model call or file changes were made.",
            prompt_decision=decision,
            plan=DEFAULT_PLAN,
        )

    def run(self, prompt: str, *, apply: bool = False, model_name: str | None = None) -> RunResult:
        decision = self.input_guard.inspect(prompt)
        if not decision.allowed:
            return RunResult(
                status="blocked",
                message="I can't help bypass safety controls or build credential theft, malware, destructive access, or exfiltration tooling.",
                prompt_decision=decision,
                plan=DEFAULT_PLAN,
            )
        if decision.risk is RiskLevel.REVIEW:
            return RunResult(
                status="needs_review",
                message="The request was not sent to the model because it contains injection or unsafe-execution signals. Rephrase it as a specific benign task or review it manually.",
                prompt_decision=decision,
                plan=DEFAULT_PLAN,
            )
        if not apply:
            return self.preview(prompt)

        self.workspace.ensure()
        try:
            agent = create_agent(self.workspace.root, model_name)
            reply = invoke_agent(agent, decision.normalized_text, uuid4().hex)
        except DeepAgentSetupError as exc:
            return RunResult(
                status="needs_setup",
                message=str(exc),
                prompt_decision=decision,
                plan=DEFAULT_PLAN,
            )

        guarded = self.output_guard.inspect(reply.text)
        if not guarded.allowed:
            return RunResult(
                status="blocked_output",
                message="The model response was withheld because it contained unsafe output.",
                prompt_decision=decision,
                plan=DEFAULT_PLAN,
            )
        checks = self.workspace.run_checks()
        artifact_dir = self.workspace.create_run_artifact(prompt, guarded.safe_text, list(DEFAULT_PLAN))
        failed = [check for check in checks if not check.passed and not check.skipped]
        status = "completed_with_failures" if failed else "completed"
        message = "Agent completed the guarded workflow. Review the diff before committing."
        if guarded.redactions:
            message += " Secrets were redacted from the displayed response."
        return RunResult(
            status=status,
            message=message,
            prompt_decision=decision,
            response=guarded.safe_text,
            plan=DEFAULT_PLAN,
            checks=checks,
            artifact_dir=str(artifact_dir),
        )
