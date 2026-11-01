"""Rule-based document classification.

Keyword weights are tuned so that overlapping documents (for example a bill
that also contains the word "receipt") resolve to the most specific type.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

DOC_TYPES: tuple[str, ...] = (
    "bill",
    "receipt",
    "warranty",
    "agreement",
    "certificate",
    "application",
    "other",
)

# (keyword, weight) -- strong, unambiguous phrases get weight 3.
KEYWORDS: dict[str, dict[str, float]] = {
    "bill": {
        "electricity bill": 3,
        "water bill": 3,
        "gas bill": 3,
        "amount due": 2.5,
        "total amount due": 3,
        "payment due": 2.5,
        "due date": 1.5,
        "bill date": 2,
        "invoice": 1.5,
        "invoice number": 2,
        "customer number": 1.5,
        "consumer number": 2,
        "units consumed": 2.5,
        "kwh": 2,
        "tariff": 1.5,
        "arrears": 2,
        "billing period": 2,
        "payable by": 2,
    },
    "receipt": {
        "receipt": 3,
        "tax receipt": 3,
        "cash receipt": 3,
        "thank you for your purchase": 2.5,
        "payment received": 2.5,
        "cashier": 1.5,
        "subtotal": 1.5,
        "change due": 1.5,
        "payment method": 2,
        "transaction id": 1.5,
        "paid via": 2,
    },
    "warranty": {
        "warranty card": 3.5,
        "warranty": 2.5,
        "warranty period": 3,
        "guarantee": 2,
        "serial number": 1.5,
        "service centre": 2,
        "service center": 2,
        "product name": 1.5,
        "coverage period": 2.5,
        "valid till": 1.5,
        "authorised service": 2,
    },
    "agreement": {
        "rental agreement": 4,
        "lease agreement": 4,
        "tenancy agreement": 4,
        "agreement": 1.5,
        "lessor": 2.5,
        "lessee": 2.5,
        "landlord": 2,
        "tenant": 2,
        "security deposit": 2,
        "monthly rent": 2.5,
        "notice period": 2,
        "renewal": 1.5,
        "hereby agree": 2.5,
        "premises": 1.5,
    },
    "certificate": {
        "certificate of": 4,
        "certificate": 1.5,
        "hereby certify": 3,
        "this is to certify": 3,
        "awarded to": 2.5,
        "has successfully completed": 2.5,
        "accredited": 2,
        "issued on": 1.5,
        "certificate number": 2.5,
    },
    "application": {
        "application form": 4,
        "applicant": 2,
        "applicant name": 2.5,
        "father's name": 2.5,
        "mother's name": 2.5,
        "declaration": 2,
        "enclosures": 2.5,
        "documents required": 2.5,
        "required documents": 2.5,
        "please attach": 2.5,
        "signature of applicant": 2.5,
        "date of birth": 1.5,
    },
}

# Minimum evidence needed before returning a concrete type.
_MIN_SCORE = 1.8


@dataclass
class ClassificationResult:
    doc_type: str
    confidence: float
    scores: dict[str, float] = field(default_factory=dict)
    matched_keywords: list[str] = field(default_factory=list)


def _keyword_score(text: str, keywords: dict[str, float]) -> tuple[float, list[str]]:
    lowered = text.lower()
    total = 0.0
    matches: list[str] = []
    for keyword, weight in keywords.items():
        # Word-boundary regex avoids matching "tenant" inside another word.
        pattern = r"(?<![a-z])" + re.escape(keyword) + r"(?![a-z])"
        count = len(re.findall(pattern, lowered))
        if count:
            total += weight + (0.25 * min(count - 1, 3))
            matches.append(keyword)
    return total, matches


def classify_document(text: str) -> ClassificationResult:
    """Classify a document using weighted keyword rules."""
    if not text or not text.strip():
        return ClassificationResult("other", 0.0, {}, [])

    scores: dict[str, float] = {}
    matched: dict[str, list[str]] = {}
    for doc_type, keywords in KEYWORDS.items():
        score, words = _keyword_score(text, keywords)
        if score:
            scores[doc_type] = round(score, 2)
            matched[doc_type] = words

    if not scores:
        return ClassificationResult("other", 0.15, {}, [])

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_type, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0

    if best_score < _MIN_SCORE:
        # Weak evidence: fall back to "other" but preserve the runner-up score.
        confidence = min(0.45, 0.15 + best_score * 0.1)
        return ClassificationResult("other", round(confidence, 2), scores, matched[best_type])

    separation = (best_score - second_score) / max(best_score, 1.0)
    evidence = min(len(matched[best_type]), 6) / 6
    confidence = 0.50 + 0.28 * separation + 0.20 * evidence
    confidence = round(min(0.98, confidence), 2)
    return ClassificationResult(
        doc_type=best_type,
        confidence=confidence,
        scores=scores,
        matched_keywords=matched[best_type],
    )


def classify_filename(filename: str) -> str | None:
    """Optional hint from the filename (used only as a tie-breaker)."""
    lowered = filename.lower()
    mapping = {
        "bill": "bill",
        "invoice": "bill",
        "receipt": "receipt",
        "warranty": "warranty",
        "guarantee": "warranty",
        "agreement": "agreement",
        "lease": "agreement",
        "rent": "agreement",
        "certificate": "certificate",
        "application": "application",
        "form": "application",
    }
    for needle, doc_type in mapping.items():
        if needle in lowered:
            return doc_type
    return None
