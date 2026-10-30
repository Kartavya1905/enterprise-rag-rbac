"""
FILE:         app/security/output_guard.py
WHAT IT DOES: Checks the LLM's answer BEFORE the user sees it.
                CHECK 1  canary   - the hidden marker from the system rules appears?
                                    -> the model is leaking its instructions: BLOCK
                CHECK 2  redact   - mask tax IDs / bank accounts / card numbers
                CHECK 3  citations - keep only [S#] ids that were actually given to the
                                    model; strip invented ones
                CHECK 4  grounding - an answer with no valid citation is flagged
WHERE IT FITS: Phase 7 - last step before the answer is returned.
USED BY:      generation/answer.py, tests.
"""

import re
from dataclasses import dataclass, field

from app.generation.prompts import CANARY, NO_ANSWER
from app.security.redaction import redact

_CITATION = re.compile(r"\[(S\d+)\]")


@dataclass
class GuardedAnswer:
    text: str
    cited_ids: list[str]  # valid source ids, in order of first appearance
    flags: list[str] = field(default_factory=list)  # for logs, not shown to users
    blocked: bool = False


def check_answer(answer: str, valid_ids: set[str]) -> GuardedAnswer:
    # --- CHECK 1: instruction leak -> replace the whole answer ---
    if CANARY.lower() in answer.lower():
        return GuardedAnswer(NO_ANSWER, [], ["canary_leak"], blocked=True)

    flags: list[str] = []

    # --- CHECK 2: sensitive identifiers ---
    redaction = redact(answer)
    answer = redaction.text
    flags += [f"redacted:{kind}" for kind in redaction.redacted]

    # --- CHECK 3: citations must point at sources the model was actually given ---
    def keep_valid(match: re.Match[str]) -> str:
        if match.group(1) in valid_ids:
            return match.group(0)
        flags.append(f"invalid_citation:{match.group(1)}")
        return ""

    answer = _CITATION.sub(keep_valid, answer).strip()
    cited = list(dict.fromkeys(_CITATION.findall(answer)))  # unique, keep order

    # --- CHECK 4: grounding ---
    if not cited and NO_ANSWER.lower().rstrip(".") not in answer.lower():
        flags.append("uncited")

    return GuardedAnswer(answer, cited, flags)
