"""Input and output guardrails for the coding-agent boundary.

These checks are intentionally conservative. They normalize text for analysis
only, detect common obfuscation, and fail closed for explicit requests to evade
safety controls or facilitate credential theft, malware, destructive access, or
exfiltration. They do not rewrite a disallowed request into an allowed one.
"""

from __future__ import annotations

import base64
import binascii
import re
import unicodedata
from dataclasses import dataclass

from .models import GuardDecision, GuardedText, RiskLevel

_ZERO_WIDTH = re.compile(r"[\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180b-\u180f\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u206f\u3164\ufe00-\ufe0f\ufeff]")
_BASE64_TOKEN = re.compile(r"(?<![A-Za-z0-9+/])([A-Za-z0-9+/]{24,}={0,2})(?![A-Za-z0-9+/])")
_HEX_TOKEN = re.compile(r"(?<![0-9a-fA-F])([0-9a-fA-F]{24,})(?![0-9a-fA-F])")

# These patterns describe actions, not individual programming words. A normal
# request to implement authentication or scan a local app should not match.
_BLOCKED_PATTERNS: tuple[tuple[str, str], ...] = (
    ("guardrail_evasion", r"\b(?:bypass|circumvent|evade|disable|ignore)\b.{0,60}\b(?:guardrail|safety|restriction|filter|policy|refusal|alignment)\b"),
    ("credential_theft", r"\b(?:steal|harvest|dump|scrape|exfiltrate)\b.{0,50}\b(?:passwords?|tokens?|credentials?|cookies?|private keys?)\b"),
    ("malware_behavior", r"\b(?:ransomware|keylogger|credential stealer|remote access trojan|botnet|persistence payload)\b"),
    ("destructive_access", r"\b(?:delete|wipe|destroy|encrypt)\b.{0,50}\b(?:all files|the filesystem|backups?|production data|user data)\b"),
    ("secret_exfiltration", r"\b(?:send|post|upload|exfiltrate)\b.{0,50}\b(?:secrets?|api keys?|passwords?|environment variables?|credentials?)\b"),
)

_REVIEW_PATTERNS: tuple[tuple[str, str], ...] = (
    ("instruction_override", r"\b(?:ignore|forget|disregard)\b.{0,60}\b(?:previous|prior|system|developer)\b.{0,30}\b(?:instructions?|rules?|message)\b"),
    ("role_injection", r"\b(?:you are now|act as|pretend to be|new system prompt|developer message)\b"),
    ("unsafe_execution", r"\b(?:reverse shell|bind shell|disable antivirus|turn off security|privilege escalation)\b"),
)

_OUTPUT_BLOCK_PATTERNS: tuple[tuple[str, str], ...] = (
    ("destructive_command", r"(?:rm\s+-rf\s+/(?:\s|$)|format\s+[a-z]:|dd\s+if=.*\s+of=/dev/)"),
    ("reverse_shell", r"\b(?:reverse shell|bind shell|/dev/tcp/|nc\s+-e|powershell\s+.*-enc)\b"),
    ("malware_payload", r"\b(?:keylogger|ransomware|credential stealer|persistence payload|disable antivirus)\b"),
)

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"), "[REDACTED_PRIVATE_KEY]"),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "[REDACTED_API_KEY]"),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghs|github_pat)_[A-Za-z0-9_]{20,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    ("bearer_token", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{20,}"), "Bearer [REDACTED_TOKEN]"),
)


def normalize_for_analysis(text: str) -> str:
    """Normalize Unicode and whitespace without changing task semantics."""

    normalized = unicodedata.normalize("NFKC", text)
    normalized = _ZERO_WIDTH.sub("", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _printable_decoded(value: bytes) -> str | None:
    if not value or len(value) > 4096:
        return None
    try:
        decoded = value.decode("utf-8")
    except UnicodeDecodeError:
        return None
    printable = sum(char.isprintable() or char.isspace() for char in decoded)
    if printable / max(len(decoded), 1) < 0.9:
        return None
    return decoded


def _obfuscated_text(text: str) -> tuple[str, ...]:
    """Return signal names when an encoded fragment contains a risky phrase."""

    signals: list[str] = []
    for match in _BASE64_TOKEN.finditer(text):
        token = match.group(1)
        try:
            decoded = _printable_decoded(base64.b64decode(token, validate=True))
        except (binascii.Error, ValueError):
            decoded = None
        if decoded:
            candidate = normalize_for_analysis(decoded).lower()
            if any(re.search(pattern, candidate) for _, pattern in _BLOCKED_PATTERNS + _REVIEW_PATTERNS):
                signals.append("encoded_instruction")
                break

    for match in _HEX_TOKEN.finditer(text):
        token = match.group(1)
        try:
            decoded = _printable_decoded(bytes.fromhex(token))
        except ValueError:
            decoded = None
        if decoded:
            candidate = normalize_for_analysis(decoded).lower()
            if any(re.search(pattern, candidate) for _, pattern in _BLOCKED_PATTERNS + _REVIEW_PATTERNS):
                signals.append("encoded_instruction")
                break
    return tuple(dict.fromkeys(signals))


@dataclass
class InputGuard:
    """Inspect user text before it is sent to a model or tool."""

    max_chars: int = 32_000

    def inspect(self, text: str) -> GuardDecision:
        if not isinstance(text, str) or not text.strip():
            return GuardDecision(False, RiskLevel.BLOCKED, ("The request is empty.",), normalized_text="")

        normalized = normalize_for_analysis(text)
        reasons: list[str] = []
        signals: list[str] = []
        if len(normalized) > self.max_chars:
            reasons.append(f"The request exceeds the {self.max_chars} character limit.")
            signals.append("size_limit")

        lowered = normalized.lower()
        for name, pattern in _BLOCKED_PATTERNS:
            if re.search(pattern, lowered, flags=re.IGNORECASE):
                signals.append(name)
        for name, pattern in _REVIEW_PATTERNS:
            if re.search(pattern, lowered, flags=re.IGNORECASE):
                signals.append(name)
        signals.extend(_obfuscated_text(normalized))
        signals = list(dict.fromkeys(signals))

        blocked_signals = {name for name, _ in _BLOCKED_PATTERNS}
        if any(signal in blocked_signals or signal == "encoded_instruction" for signal in signals):
            reasons.append("The request asks for harmful behavior or for safety controls to be bypassed.")
            return GuardDecision(False, RiskLevel.BLOCKED, tuple(reasons), tuple(signals), normalized)
        if "size_limit" in signals:
            return GuardDecision(False, RiskLevel.BLOCKED, tuple(reasons), tuple(signals), normalized)
        if signals:
            reasons.append("The request contains instruction-injection or unsafe-execution signals and needs human review.")
            return GuardDecision(True, RiskLevel.REVIEW, tuple(reasons), tuple(signals), normalized)
        return GuardDecision(True, RiskLevel.SAFE, normalized_text=normalized)


@dataclass
class OutputGuard:
    """Redact secrets and stop unsafe content before it is displayed."""

    def inspect(self, text: str) -> GuardedText:
        if not isinstance(text, str):
            return GuardedText(False, RiskLevel.BLOCKED, "", ("The model returned a non-text response.",))

        safe_text = text
        redactions = 0
        for _name, pattern, replacement in _SECRET_PATTERNS:
            safe_text, count = pattern.subn(replacement, safe_text)
            redactions += count

        reasons: list[str] = []
        for name, pattern in _OUTPUT_BLOCK_PATTERNS:
            if re.search(pattern, safe_text, flags=re.IGNORECASE):
                reasons.append(f"Unsafe output signal: {name}.")
        if reasons:
            return GuardedText(False, RiskLevel.BLOCKED, "", tuple(reasons), redactions)
        if redactions:
            return GuardedText(True, RiskLevel.REVIEW, safe_text, ("Secrets were redacted before display.",), redactions)
        return GuardedText(True, RiskLevel.SAFE, safe_text)

    @staticmethod
    def redact_for_log(text: str) -> str:
        return OutputGuard().inspect(text).safe_text
