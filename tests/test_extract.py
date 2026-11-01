"""Extraction and date/number parsing tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from lifepilot.pipeline.extract import (
    extract_entities,
    find_amounts,
    parse_date_text,
)
from lifepilot.pipeline.ocr import extract_text

SAMPLE_DIR = Path(__file__).resolve().parent / "sample_documents"


def sample_text(name: str) -> str:
    return (SAMPLE_DIR / f"{name}.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("15/12/2026", date(2026, 12, 15)),
        ("15-12-2026", date(2026, 12, 15)),
        ("2026-12-15", date(2026, 12, 15)),
        ("15th December 2026", date(2026, 12, 15)),
        ("December 15, 2026", date(2026, 12, 15)),
        ("15 Dec 2026", date(2026, 12, 15)),
        ("06/11/26", date(2026, 11, 6)),
        ("not a date", None),
    ],
)
def test_parse_date_text(raw: str, expected: date | None) -> None:
    assert parse_date_text(raw) == expected


def test_find_amounts_handles_currency_and_commas() -> None:
    amounts = find_amounts("Energy charges: Rs. 1,850.00. Total: ₹ 2,158.75. Deposit $500")
    values = sorted(item.value for item in amounts)
    assert values == [500.0, 1850.0, 2158.75]
    by_value = {item.value: item.currency for item in amounts}
    assert by_value[2158.75] == "INR"
    assert by_value[500.0] == "USD"


def test_extract_bill_fields() -> None:
    result = extract_entities(sample_text("electricity_bill"), "bill")
    values = result.as_value_map()
    assert "BESCOM" in values["invoice_number"]
    assert values["amount_total"] == "2158.75"
    assert values["due_date"] == "2026-11-06"
    assert values["account_number"].replace(" ", "") == "40501234567"
    assert "Bangalore" in values["vendor"].title() or "BESCOM" in values["vendor"]
    assert values["category"] == "Electricity"
    assert values["currency"] == "INR"


def test_extract_warranty_fields() -> None:
    result = extract_entities(sample_text("warranty_card"), "warranty")
    values = result.as_value_map()
    assert values["product"] == "AquaPure RO Water Purifier"
    assert values["warranty_period"] == "24 months"
    assert values["purchase_date"] == "2026-08-12"
    assert values["expiry_date"] == "2028-08-11"
    assert "AquaCare" in values["vendor"]


def test_extract_agreement_fields() -> None:
    result = extract_entities(sample_text("rental_agreement"), "agreement")
    values = result.as_value_map()
    assert "Ramesh Kumar" in values["landlord_name"]
    assert "Akshaya Rao" in values["tenant_name"]
    assert values["rent_amount"] == "28000.00"
    assert values["deposit_amount"] == "112000.00"
    assert values["renewal_date"] == "2027-04-15"
    assert values["notice_period"] == "2 months"
    assert "Koramangala" in values["property_address"]


def test_application_required_documents_are_all_kept() -> None:
    result = extract_entities(sample_text("application_form"), "application")
    documents = result.values("required_document")
    assert len(documents) == 5
    assert "Transfer certificate" in documents
    values = result.as_value_map()
    assert values["applicant_name"] == "Akshaya Rao"
    assert values["application_number"] == "PGC/2026/009874"
    assert values["submission_date"] == "2026-11-30"
    assert values["dob"] == "2003-06-14"


def test_every_field_has_valid_confidence() -> None:
    result = extract_entities(sample_text("rental_agreement"), "agreement")
    assert result.fields
    for item in result.fields:
        assert 0.0 <= item.confidence <= 1.0
        assert 0.0 <= item.position_ratio <= 1.0


def test_extract_text_from_text_pdf() -> None:
    result = extract_text(SAMPLE_DIR / "electricity_bill.pdf")
    assert result.method == "pdf_text"
    assert result.confidence > 0.8
    assert "Total Amount Due" in result.text
    assert result.page_count == 1


def test_extract_text_handles_missing_file(tmp_path: Path) -> None:
    result = extract_text(tmp_path / "missing.pdf")
    assert result.method == "failed"
    assert result.text == ""
    assert result.warnings
