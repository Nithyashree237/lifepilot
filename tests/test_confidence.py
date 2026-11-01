"""Confidence scoring and review-workflow tests."""

from __future__ import annotations

from lifepilot.db import crud
from lifepilot.db.models import Document, Entity, MissingInfo
from lifepilot.pipeline.confidence import (
    combine_confidence,
    compute_confidence,
    confidence_band,
    confidence_label,
    needs_review,
)


def test_confidence_is_always_bounded() -> None:
    extremes = [
        compute_confidence(method="heuristic", pattern_strength=0, position_ratio=1, label="PERSON", validated=False),
        compute_confidence(method="label", pattern_strength=1, position_ratio=0, label="DATE", doc_type_match=1),
        compute_confidence(method="regex_strong", pattern_strength=0.95, position_ratio=0.05),
    ]
    for score in extremes:
        assert 0.0 <= score <= 1.0


def test_strong_label_beats_heuristic() -> None:
    strong = compute_confidence(
        method="label", pattern_strength=0.95, position_ratio=0.1, label="DATE"
    )
    weak = compute_confidence(
        method="heuristic", pattern_strength=0.5, position_ratio=0.9, validated=False
    )
    assert strong > weak
    assert strong > 0.85
    assert weak < 0.6


def test_position_and_validation_affect_score() -> None:
    top = compute_confidence(method="regex", pattern_strength=0.8, position_ratio=0.05)
    bottom = compute_confidence(method="regex", pattern_strength=0.8, position_ratio=0.95)
    invalid = compute_confidence(
        method="regex", pattern_strength=0.8, position_ratio=0.05, validated=False
    )
    assert top > bottom
    assert top > invalid


def test_user_confidence_and_review_threshold() -> None:
    assert compute_confidence(method="user") == 1.0
    assert needs_review(0.59)
    assert not needs_review(0.60)
    assert not needs_review(0.2, confirmed=True)
    assert confidence_band(0.9) == "high"
    assert confidence_band(0.65) == "medium"
    assert confidence_band(0.2) == "low"
    assert confidence_label(0.2) == "Needs review"


def test_combine_confidence() -> None:
    assert combine_confidence([0.8, 0.6]) == 0.7
    assert combine_confidence([0.8, 0.4], [3, 1]) == 0.7
    assert combine_confidence([]) == 0.0


def test_confirming_an_entity_sets_full_confidence_and_resolves_flag(session) -> None:
    document = Document(filename="bill.pdf", stored_path="bill.pdf", doc_type="bill", status="processed")
    session.add(document)
    session.flush()
    entity = Entity(
        document_id=document.id,
        field_name="amount_total",
        value="2158.75",
        value_type="money",
        confidence=0.42,
    )
    missing = MissingInfo(
        document_id=document.id,
        field_name="amount_total",
        description="Amount missing",
        severity="high",
    )
    session.add_all([entity, missing])
    session.flush()

    assert entity.needs_review is True
    updated = crud.confirm_entity(session, entity.id, value="2199.00")
    session.flush()

    assert updated is not None
    assert updated.value == "2199.00"
    assert updated.confidence == 1.0
    assert updated.confirmed is True
    assert updated.source == "user"
    assert updated.needs_review is False
    assert missing.resolved is True
