"""
FILE:         app/security/injection.py
WHAT IT DOES: Spots prompt-injection attempts - text that tries to give the AI new orders
              ("ignore previous instructions", "you are now admin", "reveal your prompt").
WHERE IT FITS: Phase 7. Used in TWO places:
                INPUT GUARD    on the user's question  -> refuse before searching
                CONTEXT GUARD  on every retrieved chunk -> drop a poisoned chunk before it
                               reaches the LLM (documents can carry injections too)
USED BY:      generation/answer.py, tests.

This is one layer, not the whole defence. Even a missed injection cannot reveal what the
user may not read - search (Phase 6) never hands restricted chunks to the LLM. These
checks stop the model being hijacked for everything else (leaking its rules, ignoring
grounding, impersonating staff).

Before matching, text is normalised: Unicode look-alikes are folded (NFKC) and invisible
zero-width characters removed, so "ig​nore previous instructions" is still caught.
Since Phase 11 every pattern is also tried against de-disguised VIEWS of the text -
leetspeak undone, spaced letters joined, 'string' + 'pieces' joined, ROT13 and base64
decoded - and there are patterns for French, Spanish, German and Hindi. These close the
gaps the red-team evaluation found (reports/EVAL_REPORT.md).
"""

import base64
import binascii
import codecs
import re
import unicodedata
from dataclasses import dataclass, field

# =============================================================================
# 1. NORMALISATION + "VIEWS" (Phase 11 hardening)
# =============================================================================
_INVISIBLE = dict.fromkeys(map(ord, "​‌‍⁠﻿­"), None)
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t",
                       "@": "a", "$": "s"})


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_INVISIBLE)
    return re.sub(r"\s+", " ", text).lower()


def _decode_base64(token: str) -> str | None:
    try:
        raw = base64.b64decode(token + "=" * (-len(token) % 4), validate=True)
        text = raw.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    return text if " " in text and text.isprintable() else None


def _views(text: str) -> list[str]:
    """The text plus de-disguised versions of it. Attacks found by the Phase 11 red-team
    evaluation hid behind exactly these tricks."""
    base = normalize(text)
    views = [
        base,
        base.translate(_LEET),  # leetspeak: "1gn0re" -> "ignore"
        re.sub(r"\b(?:\w[-_.\s]){3,}\w\b",  # spaced letters: "i-g-n-o-r-e" -> "ignore"
               lambda m: re.sub(r"[-_.\s]", "", m.group()), base),
        re.sub(r"['\"]\s*\+\s*['\"]", "", base),  # concatenation: "'ign' + 'ore'"
        codecs.encode(base, "rot13"),  # ROT13-encoded instructions
    ]
    for token in re.findall(r"[A-Za-z0-9+/]{16,}={0,2}", text):  # base64 payloads
        decoded = _decode_base64(token)
        if decoded:
            views.append(normalize(decoded))
    return views


# =============================================================================
# 2. PATTERNS - (name, regex). Tuned to catch attacks, not ordinary questions such
#    as "who can act as incident commander?" or "what should I ignore on a receipt?"
# =============================================================================
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("override_instructions", re.compile(
        r"\b(ignore|disregard|forget|override|bypass|skip)\b.{0,40}?"
        r"\b(previous|prior|above|earlier|all|any|your|the|these|those|system)\b.{0,25}?"
        r"\b(instructions?|rules?|prompts?|guidelines?|restrictions?|polic(?:y|ies)|guardrails?)\b")),
    ("role_hijack", re.compile(
        r"\b(you are now|from now on,? you|pretend (?:to be|you are)|roleplay as|"
        r"act as (?:an? |the )?(?:unrestricted|unfiltered|jailbroken|admin|administrator|"
        r"root|developer|system))\b")),
    ("fake_authority", re.compile(
        r"\b(system|developer|admin(?:istrator)?|root)\s*(?:override|mode|message|command)\b"
        r"|\bnew (?:system )?instructions?\s*:")),
    ("prompt_extraction", re.compile(
        r"\b(reveal|show|print|repeat|output|display|tell me|what (?:is|are)|translate|"
        r"summari[sz]e|rewrite|paraphrase)\b.{0,30}?"
        r"\b(system prompt|your (?:instructions|rules|prompt|guidelines)|"
        r"hidden (?:instructions|prompt)|initial prompt)\b"
        r"|\brepeat (?:the |all )?(?:text|words|everything|content) (?:above|before)\b")),
    ("jailbreak_keyword", re.compile(r"\bjailbreak\b|\bdo anything now\b|\bdan mode\b")),
    ("claimed_clearance", re.compile(
        r"\b(?:i am|i'm|this is)\b.{0,25}?\b(admin|administrator|ceo|cfo|root|superuser|"
        r"security team)\b.{0,50}?\b(access|clearance|permission|authori[sz]e[ds]?|override)\b")),
    ("tag_injection", re.compile(r"</?\s*(?:system|source|instructions?|question)\s*>")),
    # --- added after the Phase 11 baseline evaluation ---
    ("format_hijack", re.compile(  # the one attack that SUCCEEDED in the baseline
        r"\bnew rules?\s*:"
        r"|\balways (?:end|start|begin|finish) (?:your |every |each )?"
        r"(?:answers?|responses?|replies)\b"
        r"|\b(?:end|start|finish) (?:every|each|all) (?:answers?|responses?|replies)\b")),
    ("rule_breaking_persona", re.compile(
        r"\bwho (?:ignores|has no|doesn't follow|does not follow)\b.{0,20}?"
        r"\b(?:rules|restrictions|instructions|guidelines|limits)\b")),
    ("permission_claim", re.compile(
        r"\b(?:you (?:may|can|are allowed to|have permission to)"
        r"|i (?:authori[sz]e|allow|permit) you to)"
        r"\b.{0,30}?\b(?:reveal|show|share|bypass|ignore|disclose|display)\b.{0,40}?"
        r"\b(?:everything|restricted|confidential|secret|hidden)\b")),
    ("prompt_extraction_indirect", re.compile(
        r"\b(?:rules|instructions|guidelines)\b.{0,15}?\byou (?:were given|operate under|follow|"
        r"received|have been given)\b"
        r"|\binternal reference\b|\b(?:confidential|secret|hidden) (?:rules|instructions)\b")),
    ("encoded_instruction", re.compile(
        r"\b(?:decode|decrypt|translate)\b.{0,40}?\b(?:and|then)\b.{0,20}?"
        r"\b(?:follow|obey|execute|do what|run)\b")),
    ("override_multilingual", re.compile(  # French, Spanish, German / Hindi
        r"\b(?:ignor\w*|olvid\w*|vergiss\w*|oubli\w*)\b.{0,40}?"
        r"\b(?:instruc\w*|anweisung\w*|r[eè]gl\w*|regeln|reglas|consignes)\b"
        r"|(?:अनदेखा|नज़रअंदाज़|नजरअंदाज|भूल).{0,40}निर्देश|निर्देश.{0,40}(?:अनदेखा|नज़रअंदाज़|नजरअंदाज|भूल)")),
]


@dataclass(frozen=True)
class InjectionResult:
    flagged: bool
    reasons: list[str] = field(default_factory=list)


# =============================================================================
# 3. DETECTION
# =============================================================================
def detect_injection(text: str) -> InjectionResult:
    views = _views(text)
    reasons = [name for name, pattern in _PATTERNS
               if any(pattern.search(view) for view in views)]
    return InjectionResult(flagged=bool(reasons), reasons=reasons)
