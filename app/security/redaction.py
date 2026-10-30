"""
FILE:         app/security/redaction.py
WHAT IT DOES: Masks highly sensitive identifiers - tax IDs, social security numbers, bank
              accounts, card numbers - with [REDACTED].
WHERE IT FITS: Phase 7. Applied TWICE:
                to the chunks BEFORE the LLM sees them  (it can't repeat what it never saw)
                to the answer AFTER the LLM writes it   (belt and braces)
USED BY:      generation/answer.py, security/output_guard.py, tests.

Policy: these identifiers are NEVER shown in chat answers, whatever the user's clearance.
HR may read the payroll file itself, but a chat answer has no business repeating a tax ID
(data minimisation). Names, salaries and emails are not masked here - access to those is
already decided by clearance, department and column labels.
"""

import re
from dataclasses import dataclass

REDACTED = "[REDACTED]"

_SENSITIVE: list[tuple[str, re.Pattern[str]]] = [
    ("tax_id", re.compile(r"\bFAKE-TX-\d{5}\b", re.IGNORECASE)),  # our dataset's format
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),  # US social security number shape
    ("bank_account", re.compile(r"\*{4}\d{4}\b")),  # masked account "****1234"
    ("card_number", re.compile(r"\b(?:\d[ -]?){13,19}\b")),  # 13-19 digit card numbers
]


@dataclass(frozen=True)
class RedactionResult:
    text: str
    redacted: list[str]  # which kinds were masked (for logging)


def redact(text: str) -> RedactionResult:
    found = []
    for name, pattern in _SENSITIVE:
        text, count = pattern.subn(REDACTED, text)
        if count:
            found.append(name)
    return RedactionResult(text, found)
