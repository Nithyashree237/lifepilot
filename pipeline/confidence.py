"""Confidence scoring for extracted fields.

Scores are intentionally transparent: a base score per extraction method is
adjusted by pattern strength, entity label and where the match appears in the
document.  The UI flags anything below ``NEEDS_REVIEW_THRESHOLD``.
"""

from __future__ import annotations

from lifepilot.config import NEEDS_REVIEW_THRESHOLD

# Base reliability per extraction method.
METHOD_BASE: dict[str, float] = {
    "user": 1.0,
    "label": 0.88,          # explicit "Due Date: ..." style label
    "regex_strong": 0.87,   # well-known pattern with validation
    "regex": 0.76,          # generic regular expression
    "spacy": 0.68,          # statistical NER
    "heuristic": 0.52,      # inferred from layout / first lines
    "llm": 0.72,            # validated LLM JSON
    "llm_verified": 0.85,   # LLM value corroborated by another signal
}

# Small bonuses by spaCy label / field semantics.
LABEL_BONUS: dict[str, float] = {
    "DATE": 0.02,
    "MONEY": 0.02,
    "ORG": 0.01,
    "MONEY_AMOUNT": 0.02,
    "PERSON": -0.02,
    "GPE": -0.01,
}


def clamp(value: float, low: float = 0.0, high: float = 0.99) -> float:
    """Clamp a score into the supported range and round to 2 decimals."""
    return round(max(low, min(high, value)), 2)


def _position_bonus(position_ratio: float | None) -> float:
    """Fields near the top of a document tend to be identifying details."""
    if position_ratio is None:
        return 0.0
    if position_ratio <= 0.25:
        return 0.05
    if position_ratio <= 0.50:
        return 0.02
    if position_ratio <= 0.80:
        return 0.0
    return -0.03


def compute_confidence(
    *,
    method: str = "regex",
    pattern_strength: float = 0.8,
    position_ratio: float | None = 0.5,
    label: str | None = None,
    doc_type_match: float = 0.0,
    validated: bool = True,
) -> float:
    """Calculate a confidence score between 0 and 0.99.

    Args:
        method: one of :data:`METHOD_BASE` keys.
        pattern_strength: 0..1 quality of the regex/keyword that matched.
        position_ratio: where the match occurs in the text (0 = start).
        label: optional NER/entity label used for small adjustments.
        doc_type_match: 0..1 prior that the field is typical for the doc type.
        validated: whether the value passed syntax validation (date/amount).
    """
    if method == "user":
        return 1.0

    base = METHOD_BASE.get(method, 0.55)
    score = base
    score += (max(0.0, min(1.0, pattern_strength)) - 0.7) * 0.18
    score += _position_bonus(position_ratio)
    if label:
        score += LABEL_BONUS.get(label.upper(), 0.0)
    score += max(0.0, min(1.0, doc_type_match)) * 0.04
    if not validated:
        score -= 0.25
    return clamp(score)


def score_label_match(
    *,
    strength: float,
    position_ratio: float | None,
    doc_type_match: float = 0.5,
    validated: bool = True,
) -> float:
    """Convenience wrapper for rules-based label extraction."""
    return compute_confidence(
        method="label",
        pattern_strength=strength,
        position_ratio=position_ratio,
        doc_type_match=doc_type_match,
        validated=validated,
    )


def score_regex_match(
    *,
    strength: float,
    position_ratio: float | None,
    strong: bool = False,
    validated: bool = True,
) -> float:
    """Convenience wrapper for regular-expression extraction."""
    return compute_confidence(
        method="regex_strong" if strong else "regex",
        pattern_strength=strength,
        position_ratio=position_ratio,
        validated=validated,
    )


def needs_review(confidence: float, confirmed: bool = False) -> bool:
    """True when a human should check the value."""
    return not confirmed and confidence < NEEDS_REVIEW_THRESHOLD


def confidence_band(confidence: float) -> str:
    """Return a short label used by UI badges."""
    if confidence >= 0.85:
        return "high"
    if confidence >= NEEDS_REVIEW_THRESHOLD:
        return "medium"
    return "low"


def confidence_label(confidence: float) -> str:
    """Human readable confidence label."""
    band = confidence_band(confidence)
    return {"high": "High confidence", "medium": "Medium confidence", "low": "Needs review"}[band]


def combine_confidence(scores: list[float], weights: list[float] | None = None) -> float:
    """Weighted average of multiple signals (e.g. regex + LLM corroboration)."""
    if not scores:
        return 0.0
    if weights is None:
        weights = [1.0] * len(scores)
    total_weight = sum(weights)
    if total_weight <= 0:
        return 0.0
    return clamp(sum(s * w for s, w in zip(scores, weights)) / total_weight)
