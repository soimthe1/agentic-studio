"""Answer guardrail: secrets and personal identifiers never leave an agent's answer as they are.

Applied to every answer Agent Studio shows or passes on (chat, shared chat, approvals). The engine's notify tool applies
the same patterns before a message is posted: tools/studio_tools/studio_tools/core/redact.py is an exact copy of this file
(the engine has no Agent Studio backend; tests/test_guard.py keeps the two identical). Masks, never drops: people still see that
something was there ("[hidden password]").
ponytail: pattern list, not a classifier; add a pattern when a new kind of secret shows up in answers.
"""

from __future__ import annotations

import re

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[hidden private key]"),
    (re.compile(r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|token|access[_-]?key)\b(\s*[:=]\s*|\s+is\s+)(\"[^\"]+\"|'[^']+'|[^\s,;]+)"),
     r"\1\2[hidden \1]"),
    (re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{16,}"), "Bearer [hidden token]"),
    (re.compile(r"\beyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\b"), "[hidden token]"),          # JWT
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^\s:/@]+):([^\s@/]+)@"), r"\1:[hidden password]@"),                       # URL creds
    (re.compile(r"\b784-?\d{4}-?\d{7}-?\d\b"), "[hidden Emirates ID]"),
]
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def _luhn(digits: str) -> bool:
    total, odd = 0, True
    for ch in reversed(digits):
        d = int(ch)
        if not odd:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        odd = not odd
    return total % 10 == 0


def redact(text: str) -> str:
    if not text:
        return text
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return _CARD.sub(lambda m: "[hidden card number]" if _luhn(re.sub(r"\D", "", m.group())) else m.group(), text)


if __name__ == "__main__":
    assert redact("the password is Hunter2!") == "the password is [hidden password]"
    assert redact("api_key=abc123def") == "api_key=[hidden api_key]"
    assert redact("connect to postgres://app:s3cr3t@db:5432/x") == "connect to postgres://app:[hidden password]@db:5432/x"
    assert redact("ID 784-1990-1234567-1 here") == "ID [hidden Emirates ID] here"
    assert redact("card 4111 1111 1111 1111") == "card [hidden card number]"
    assert redact("order 1234567890123") == "order 1234567890123"                 # not a card (Luhn)
    assert redact("CPU at 93%, 4 failed jobs") == "CPU at 93%, 4 failed jobs"
    print("guard ok")
