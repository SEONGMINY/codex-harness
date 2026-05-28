"""Secret redaction helpers for harness output artifacts."""

from __future__ import annotations

import re

from policy_pack import redaction_policy


def redact_text(value: str) -> str:
    policy = redaction_policy()
    replacement = str(policy.get("replacement") or "[REDACTED]")
    text = value
    for pattern in policy.get("secret_patterns") or []:
        try:
            text = re.sub(str(pattern), replacement, text, flags=re.DOTALL)
        except re.error:
            continue
    return text
