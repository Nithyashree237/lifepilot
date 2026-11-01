"""End-to-end pipeline, persistence and dashboard-query tests."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest
from icalendar import Calendar

from lifepilot.db import crud
from lifepilot.db.models import Document, Entity
from lifepilot.exports.calendar import build_document_calendar
from lifepilot.pipeline.processor import process_document, save_upload

SAMPLE_DIR = Path(__file__).resolve().parent / "sample_documents"


def upload_and_process(session, tmp_path: Path, name: str):
    data = (SAMPLE_DIR / f"{name}.pdf").read_bytes()
    document = save_upload(
        session, filename=f"{name}.pdf", data=data, upload_dir=tmp_path
    )
    result = process_document(session, document.id, enable_llm=False)
    session.commit()
    return document, result


@pytest.mark.parametrize(
    ("name", "doc_type", "min_tasks"),
    [
        ("electricity_bill", "bill", 1),
        ("warranty_card", "warranty", 1),
        ("rental_agreement", "agreement", 2),
        ("application_form", "application", 5),
    ],
)
def test_full_pipeline_for_each_sample(
    session, tmp_path: Path, name: str, doc_type: str, min_tasks: int
) -> None:
    document, result = upload_and_process(session, tmp_path, name)

    assert result.ok, result.error
    assert result.doc_type == doc_type
    assert document.status == "processed"
    assert document.raw_text
    assert document.doc_type_confidence > 0.5
    assert result.entities > 0
    assert result.tasks >= min_tasks

    entities = crud.get_entities(session, document.id)
    assert entities
    assert all(0 <= entity.confidence <= 1 for entity in entities)
    assert all(entity.value for entity in entities)

    tasks = crud.list_tasks(session, document_id=document.id)
    assert len(tasks) >= min_tasks
    assert any(task.due_date for task in tasks)

    deadlines = crud.upcoming_deadlines(session, document_id=document.id)
    assert deadlines


def test_bill_pipeline_values_and_calendar(session, tmp_path: Path) -> None:
    document, _ = upload_and_process(session, tmp_path, "electricity_bill")
    entities = {item.field_name: item for item in crud.get_entities(session, document.id)}
    assert entities["amount_total"].value == "2158.75"
    assert entities["due_date"].value == "2026-11-06"
    assert entities["vendor"].confidence > 0.5

    deadlines = crud.upcoming_deadlines(session, document_id=document.id)
    raw = build_document_calendar(deadlines, document_name=document.filename)
    calendar = Calendar.from_ical(raw)
    events = [item for item in calendar.walk() if item.name == "VEVENT"]
    assert len(events) == len(deadlines) == 1
    assert "Bill payment due" in str(events[0].get("summary"))


def test_reprocessing_does_not_duplicate_rows(session, tmp_path: Path) -> None:
    document, _ = upload_and_process(session, tmp_path, "electricity_bill")
    counts_before = (
        len(crud.get_entities(session, document.id)),
        len(crud.list_tasks(session, document_id=document.id, include_done=True)),
        len(crud.upcoming_deadlines(session, document_id=document.id)),
        len(crud.list_missing_info(session, document.id, include_resolved=True)),
    )
    process_document(session, document.id, enable_llm=False)
    session.commit()
    counts_after = (
        len(crud.get_entities(session, document.id)),
        len(crud.list_tasks(session, document_id=document.id, include_done=True)),
        len(crud.upcoming_deadlines(session, document_id=document.id)),
        len(crud.list_missing_info(session, document.id, include_resolved=True)),
    )
    assert counts_before == counts_after


def test_mark_task_done(session, tmp_path: Path) -> None:
    document, _ = upload_and_process(session, tmp_path, "electricity_bill")
    task = crud.list_tasks(session, document_id=document.id)[0]
    crud.set_task_done(session, task.id, True)
    session.commit()
    assert crud.list_tasks(session, document_id=document.id) == []
    assert len(crud.list_tasks(session, document_id=document.id, include_done=True)) >= 1


def test_dashboard_counts(session, tmp_path: Path) -> None:
    upload_and_process(session, tmp_path, "electricity_bill")
    counts = crud.dashboard_counts(session)
    assert counts["documents"] == 1
    assert counts["open_tasks"] >= 1
    assert counts["due_this_week"] >= 0


def test_spending_records_from_bill_and_receipt(session) -> None:
    bill = Document(
        filename="power.pdf",
        stored_path="power.pdf",
        doc_type="bill",
        status="processed",
        uploaded_at=datetime(2026, 10, 28),
    )
    receipt = Document(
        filename="shop.pdf",
        stored_path="shop.pdf",
        doc_type="receipt",
        status="processed",
        uploaded_at=datetime(2026, 11, 2),
    )
    session.add_all([bill, receipt])
    session.flush()
    session.add_all(
        [
            Entity(document_id=bill.id, field_name="vendor", value="BESCOM", confidence=0.9),
            Entity(document_id=bill.id, field_name="amount_total", value="2158.75", value_type="money", confidence=0.9),
            Entity(document_id=bill.id, field_name="invoice_date", value="2026-10-28", value_type="date", confidence=0.9),
            Entity(document_id=bill.id, field_name="category", value="Electricity", confidence=0.8),
            Entity(document_id=bill.id, field_name="currency", value="INR", confidence=0.9),
            Entity(document_id=receipt.id, field_name="vendor", value="FreshMart", confidence=0.9),
            Entity(document_id=receipt.id, field_name="amount_total", value="450", value_type="money", confidence=0.9),
            Entity(document_id=receipt.id, field_name="purchase_date", value="2026-11-01", value_type="date", confidence=0.9),
            Entity(document_id=receipt.id, field_name="category", value="Shopping", confidence=0.8),
        ]
    )
    session.flush()

    records = crud.spending_records(session)
    assert len(records) == 2
    by_vendor = {record["vendor"]: record for record in records}
    assert by_vendor["BESCOM"]["amount"] == 2158.75
    assert by_vendor["BESCOM"]["month"] == "2026-10"
    assert by_vendor["FreshMart"]["category"] == "Shopping"
    assert by_vendor["FreshMart"]["currency"] == "INR"


def test_missing_fields_are_persisted_and_resolved(session, tmp_path: Path) -> None:
    document, _ = upload_and_process(session, tmp_path, "warranty_card")
    assert crud.unresolved_missing_count(session, document.id) == 0

    # Simulate a sparse warranty by creating a new document with missing rows.
    sparse = Document(
        filename="unknown_warranty.pdf",
        stored_path="unknown.pdf",
        doc_type="warranty",
        status="processed",
    )
    session.add(sparse)
    session.flush()
    from lifepilot.db.models import MissingInfo

    missing = MissingInfo(
        document_id=sparse.id,
        field_name="expiry_date",
        description="Warranty expiry date was not found.",
        severity="high",
    )
    session.add(missing)
    session.flush()
    assert crud.unresolved_missing_count(session, sparse.id) == 1
    crud.resolve_missing_info(session, missing.id)
    session.flush()
    assert crud.unresolved_missing_count(session, sparse.id) == 0
