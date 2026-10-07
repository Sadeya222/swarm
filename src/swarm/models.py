"""Small, dependency-free data models used by the agent pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class RiskLevel(str, Enum):
    SAFE = "safe"
    REVIEW = "review"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class GuardDecision:
    """A decision made before text crosses an agent boundary.

    ``normalized_text`` is for analysis and display only. It is intentionally not
    a rewritten version of the request intended to evade a policy decision.
    """

    allowed: bool
    risk: RiskLevel
    reasons: tuple[str, ...] = field(default_factory=tuple)
    signals: tuple[str, ...] = field(default_factory=tuple)
    normalized_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["risk"] = self.risk.value
        value["reasons"] = list(self.reasons)
        value["signals"] = list(self.signals)
        return value


@dataclass(frozen=True)
class GuardedText:
    """Output of an output guard after secret redaction and risk checks."""

    allowed: bool
    risk: RiskLevel
    safe_text: str
    reasons: tuple[str, ...] = field(default_factory=tuple)
    redactions: int = 0

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["risk"] = self.risk.value
        value["reasons"] = list(self.reasons)
        return value


@dataclass(frozen=True)
class CheckResult:
    command: str
    passed: bool
    skipped: bool
    output: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RunResult:
    status: str
    message: str
    prompt_decision: GuardDecision
    response: str = ""
    plan: tuple[str, ...] = field(default_factory=tuple)
    checks: tuple[CheckResult, ...] = field(default_factory=tuple)
    artifact_dir: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "prompt_decision": self.prompt_decision.to_dict(),
            "response": self.response,
            "plan": list(self.plan),
            "checks": [item.to_dict() for item in self.checks],
            "artifact_dir": self.artifact_dir,
        }
