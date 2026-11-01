"""Clause / obligation detection.

Finds sentences containing duty phrases such as "must", "shall", "due by" or
"renew before" and captures an explicit (or relative) deadline when present.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from lifepilot.pipeline.confidence import compute_confidence
from lifepilot.pipeline.extract import find_dates, parse_date_text

# (clause type, patterns, base strength)
OBLIGATION_RULES: list[tuple[str, list[str], float]] = [
    (
        "payment",
        [
            r"\bmust pay\b",
            r"\bshall pay\b",
            r"\bpayable within\b",
            r"\bpayment (?:is )?due\b",
            r"\bdue by\b",
            r"\bdue on\b",
            r"\bpay by\b",
            r"\bremit(?:ted)? by\b",
        ],
        0.93,
    ),
    (
        "renewal",
        [
            r"\brenew(?:al)? before\b",
            r"\brenew(?:al)? on\b",
            r"\bshall renew\b",
            r"\brenewal (?:clause|term|option)\b",
            r"\bnotice of renewal\b",
        ],
        0.9,
    ),
    (
        "expiry",
        [r"\bexpires? on\b", r"\bexpiry date\b", r"\bvalid (?:until|till|up to)\b"],
        0.92,
    ),
    (
        "submission",
        [
            r"\bmust submit\b",
            r"\bshall submit\b",
            r"\bsubmit(?:ted)? by\b",
            r"\bno later than\b",
            r"\bapplication must be\b",
            r"\bmust provide\b",
        ],
        0.9,
    ),
    (
        "termination",
        [r"\bterminate\b", r"\btermination\b", r"\bnotice period\b"],
        0.83,
    ),
    (
        "general",
        [
            r"\bmust\b",
            r"\bshall\b",
            r"\brequired to\b",
            r"\bobligat(?:ed|ion)\b",
            r"\bresponsible for\b",
        ],
        0.72,
    ),
]

_RELATIVE_DAYS = re.compile(
    r"\bwithin\s+(\d{1,3})\s*(days?|weeks?|months?)\b", re.IGNORECASE
)
_KEY_VALUE_LINE = re.compile(r"^[A-Za-z][A-Za-z /'().-]{1,35}\s*:\s*\S.{0,90}$")


def _is_key_value_line(sentence: str) -> bool:
    """Ignore label/value lines such as ``Expiry Date: 11/08/2028``."""
    if not _KEY_VALUE_LINE.match(sentence):
        return False
    return not re.search(
        r"\b(?:must|shall|due by|renew before|payable|within|submit by)\b",
        sentence,
        re.IGNORECASE,
    )


@dataclass
class Obligation:
    sentence: str
    clause_type: str
    keyword: str
    due_date: date | None = None
    relative_days: int | None = None
    confidence: float = 0.6

    def to_payload(self) -> dict[str, object]:
        return {
            "sentence": self.sentence,
            "clause_type": self.clause_type,
            "keyword": self.keyword,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "relative_days": self.relative_days,
            "confidence": self.confidence,
        }


def split_sentences(text: str) -> list[str]:
    """Split text into sentence-like chunks while keeping clause numbers."""
    if not text:
        return []
    normalized = text.replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    chunks = re.split(r"(?<=[A-Za-z][.!?])\s+(?=[A-Z0-9(\"'])|[\n;]+", normalized)
    sentences: list[str] = []
    for chunk in chunks:
        cleaned = re.sub(r"\s+", " ", chunk).strip(" \t")
        if 15 <= len(cleaned) <= 700:
            sentences.append(cleaned)
    return sentences


def _classify_sentence(sentence: str) -> tuple[str, str, float] | None:
    lowered = sentence.lower()
    for clause_type, patterns, strength in OBLIGATION_RULES:
        for pattern in patterns:
            match = re.search(pattern, lowered)
            if match:
                return clause_type, match.group(0), strength
    return None


def _relative_due(sentence: str, reference_date: date | None) -> tuple[int | None, date | None]:
    match = _RELATIVE_DAYS.search(sentence)
    if not match:
        return None, None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    days = amount if unit.startswith("day") else amount * 7 if unit.startswith("week") else amount * 30
    if reference_date is None:
        return days, None
    return days, reference_date + timedelta(days=days)


def extract_obligations(
    text: str, *, reference_date: date | None = None
) -> list[Obligation]:
    """Return actionable clauses with an optional captured deadline."""
    obligations: list[Obligation] = []
    seen: set[str] = set()
    for sentence in split_sentences(text):
        classified = _classify_sentence(sentence)
        if classified is None or _is_key_value_line(sentence):
            continue
        clause_type, keyword, strength = classified
        key = re.sub(r"\W+", " ", sentence.lower()).strip()[:160]
        if key in seen:
            continue
        seen.add(key)

        due_date: date | None = None
        dates = find_dates(sentence)
        if dates:
            due_date = dates[0].value
        relative_days, relative_due = _relative_due(sentence, reference_date)
        if due_date is None and relative_due is not None:
            due_date = relative_due

        confidence = compute_confidence(
            method="regex",
            pattern_strength=min(0.98, strength + (0.02 if due_date else 0.0)),
            position_ratio=0.5,
            validated=due_date is not None,
        )
        obligations.append(
            Obligation(
                sentence=sentence,
                clause_type=clause_type,
                keyword=keyword,
                due_date=due_date,
                relative_days=relative_days,
                confidence=confidence,
            )
        )
        if len(obligations) >= 25:
            break
    return obligations


def obligations_with_deadlines(obligations: list[Obligation]) -> list[Obligation]:
    """Filter to clauses that produced a usable date."""
    return [item for item in obligations if item.due_date is not None]
