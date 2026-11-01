"""Obligation / clause extraction tests."""

from __future__ import annotations

from datetime import date

from lifepilot.pipeline.obligations import extract_obligations, split_sentences


def test_payment_clause_deadline() -> None:
    text = "The customer must pay the outstanding amount by 15/12/2026."
    obligations = extract_obligations(text)
    assert len(obligations) == 1
    assert obligations[0].clause_type == "payment"
    assert obligations[0].due_date == date(2026, 12, 15)
    assert obligations[0].confidence > 0.5


def test_renewal_clause_deadline() -> None:
    text = "The agreement shall renew before 15/04/2027 unless notice is given."
    obligations = extract_obligations(text)
    assert obligations
    assert obligations[0].clause_type == "renewal"
    assert obligations[0].due_date == date(2027, 4, 15)


def test_relative_deadline_uses_reference_date() -> None:
    text = "The tenant must pay within 10 days of the bill date."
    obligations = extract_obligations(text, reference_date=date(2026, 11, 1))
    assert obligations[0].relative_days == 10
    assert obligations[0].due_date == date(2026, 11, 11)


def test_key_value_lines_are_not_obligations() -> None:
    text = "Expiry Date: 11/08/2028\nWarranty Number: WC-2026-778812"
    assert extract_obligations(text) == []


def test_modal_verbs_are_detected_without_a_date() -> None:
    text = "The lessor must repair the roof and shall maintain the structure."
    obligations = extract_obligations(text)
    assert obligations
    assert all(item.due_date is None for item in obligations)


def test_split_sentences_keeps_clause_numbers() -> None:
    chunks = split_sentences("1. The tenant must pay rent.\n2. The tenant shall maintain the premises.")
    assert len(chunks) == 2
    assert chunks[0].startswith("1.")
