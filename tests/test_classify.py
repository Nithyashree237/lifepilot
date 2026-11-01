"""Document classification tests."""

from __future__ import annotations

from pathlib import Path

from lifepilot.pipeline.classify import classify_document, classify_filename

SAMPLE_DIR = Path(__file__).resolve().parent / "sample_documents"


def sample_text(name: str) -> str:
    return (SAMPLE_DIR / f"{name}.txt").read_text(encoding="utf-8")


def test_sample_documents_classify_correctly() -> None:
    expected = {
        "electricity_bill": "bill",
        "warranty_card": "warranty",
        "rental_agreement": "agreement",
        "application_form": "application",
    }
    for name, doc_type in expected.items():
        result = classify_document(sample_text(name))
        assert result.doc_type == doc_type, (name, result.scores)
        assert result.confidence >= 0.6


def test_receipt_keywords() -> None:
    text = """
    FreshMart Supermarket
    Cash Receipt
    Thank you for your purchase!
    Subtotal: Rs. 450.00
    Payment method: UPI
    Cashier: Anita
    """
    result = classify_document(text)
    assert result.doc_type == "receipt"
    assert result.confidence > 0.5


def test_certificate_keywords() -> None:
    text = """
    Certificate of Completion
    This is to certify that Ms. Akshaya Rao has successfully completed
    the Data Analytics programme. Certificate Number: CERT-2026-0091.
    """
    assert classify_document(text).doc_type == "certificate"


def test_empty_and_unknown_text() -> None:
    assert classify_document("").doc_type == "other"
    assert classify_document("Lunch menu\nSoup of the day").doc_type == "other"


def test_filename_hint() -> None:
    assert classify_filename("Electricity_Bill_Nov.pdf") == "bill"
    assert classify_filename("warranty-card.pdf") == "warranty"
    assert classify_filename("scan_001.pdf") is None
