"""Non-negotiable #1: no advice language anywhere. Call `lint_language()` on every string
before it is shown to a user or posted. When unsure whether wording is advice, it is."""

from __future__ import annotations

import re
from dataclasses import dataclass

# English + Arabic. Matched as whole words, case-insensitive. Extend via discussion.
BANNED_TERMS: tuple[str, ...] = (
    "buy",
    "sell",
    "buy now",
    "sell now",
    "recommend",
    "recommendation",
    "recommended",
    "signal",
    "signals",
    "should buy",
    "should sell",
    "guaranteed",
    "sure thing",
    "can't lose",
    "اشتري",
    "اشترِ",
    "بيع",
    "بع",
    "توصية",
    "توصيات",
    "نوصي",
    "إشارة",
    "اشارة",
    "إشارات",
    "مضمون",
    "مضمونة",
    "لا تخسر",
)

# Preferred wording, for error messages and templates.
ALTERNATIVES = {
    "buy": "setup / meets your rule",
    "sell": "exit rule / result",
    "recommend": "meets your rule",
    "signal": "setup",
    "توصية": "إعداد مطابق للقاعدة",
    "إشارة": "إعداد",
}


@dataclass(frozen=True)
class LanguageViolationError(Exception):
    text: str
    terms: tuple[str, ...]

    def __str__(self) -> str:
        return f"advice language blocked: {', '.join(self.terms)}"


_PATTERN = re.compile(
    r"(?<![\w؀-ۿ])(" + "|".join(re.escape(t) for t in BANNED_TERMS) + r")(?![\w؀-ۿ])",
    re.IGNORECASE,
)


def find_banned(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(m.group(1).lower() for m in _PATTERN.finditer(text)))


def lint_language(text: str) -> str:
    """Return `text` unchanged if clean; raise LanguageViolationError otherwise."""
    hits = find_banned(text)
    if hits:
        raise LanguageViolationError(text, hits)
    return text
