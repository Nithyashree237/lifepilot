"""Task generation and missing-information tests."""

from __future__ import annotations

from datetime import date, timedelta

from lifepilot.pipeline.tasks import (
    detect_missing_info,
    derive_deadlines,
    generate_tasks,
)


def future(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def test_bill_task_contains_amount_vendor_and_deadline() -> None:
    due = future(10)
    fields = {
        "vendor": "BESCOM",
        "amount_total": "2158.75",
        "due_date": due,
        "currency": "INR",
    }
    deadlines = derive_deadlines("bill", fields)
    tasks = generate_tasks(doc_type="bill", fields=fields, deadlines=deadlines)
    assert len(deadlines) == 1
    assert deadlines[0].kind == "payment"
    assert any(
        "Pay" in task.title and "BESCOM" in task.title and "2,158.75" in task.title
        and task.due_date == date.fromisoformat(due)
        for task in tasks
    )
    payment_task = next(task for task in tasks if task.title.startswith("Pay"))
    assert payment_task.deadline_index == 0


def test_bill_without_due_date_creates_follow_up() -> None:
    fields = {"vendor": "BESCOM", "amount_total": "2158.75"}
    tasks = generate_tasks(doc_type="bill", fields=fields, deadlines=[])
    assert any("due date" in task.title.lower() for task in tasks)


def test_warranty_reminder_is_30_days_before_expiry() -> None:
    expiry = (date.today() + timedelta(days=200))
    fields = {
        "product": "AquaPure",
        "expiry_date": expiry.isoformat(),
        "purchase_date": future(10),
    }
    deadlines = derive_deadlines("warranty", fields)
    tasks = generate_tasks(doc_type="warranty", fields=fields, deadlines=deadlines)
    assert deadlines[0].remind_days_before == 30
    assert tasks[0].due_date == expiry - timedelta(days=30)
    assert tasks[0].deadline_index == 0
    assert "warranty" in tasks[0].title.lower()


def test_agreement_renewal_is_15_days_before() -> None:
    renewal = (date.today() + timedelta(days=100))
    fields = {
        "renewal_date": renewal.isoformat(),
        "property_address": "7B Lakeview Apartments",
        "rent_amount": "28000",
        "landlord_name": "Ramesh Kumar",
        "tenant_name": "Akshaya Rao",
    }
    deadlines = derive_deadlines("agreement", fields)
    tasks = generate_tasks(doc_type="agreement", fields=fields, deadlines=deadlines)
    assert deadlines[0].remind_days_before == 15
    renewal_task = next(task for task in tasks if "Review renewal" in task.title)
    assert renewal_task.due_date == renewal - timedelta(days=15)
    assert renewal_task.deadline_index == 0


def test_certificate_renewal_reminder() -> None:
    expiry = (date.today() + timedelta(days=90))
    fields = {"holder_name": "Akshaya Rao", "expiry_date": expiry.isoformat()}
    deadlines = derive_deadlines("certificate", fields)
    tasks = generate_tasks(doc_type="certificate", fields=fields, deadlines=deadlines)
    assert deadlines[0].remind_days_before == 30
    assert tasks[0].due_date == expiry - timedelta(days=30)
    assert "Renew" in tasks[0].title


def test_application_lists_required_documents() -> None:
    submission = (date.today() + timedelta(days=20))
    fields = {
        "applicant_name": "Akshaya Rao",
        "submission_date": submission.isoformat(),
    }
    deadlines = derive_deadlines("application", fields)
    tasks = generate_tasks(
        doc_type="application",
        fields=fields,
        deadlines=deadlines,
        required_documents=["Aadhaar card", "Transfer certificate"],
    )
    collect_titles = [task.title for task in tasks if task.title.startswith("Collect document")]
    assert len(collect_titles) == 2
    assert any("submit" in task.title.lower() for task in tasks)
    assert all(task.due_date is not None for task in tasks)


def test_missing_information_detection() -> None:
    missing = detect_missing_info("bill", {"vendor": "BESCOM"})
    names = {item.field_name for item in missing}
    assert {"amount_total", "due_date"}.issubset(names)
    assert all(item.description for item in missing)
    assert all(item.severity in {"high", "medium", "low"} for item in missing)


def test_no_missing_information_for_complete_bill() -> None:
    fields = {
        "vendor": "BESCOM",
        "amount_total": "100",
        "due_date": future(5),
        "invoice_number": "INV-1",
        "account_number": "123",
    }
    assert detect_missing_info("bill", fields) == []


def test_obligation_deadlines_become_tasks() -> None:
    from lifepilot.pipeline.obligations import Obligation

    due = date.today() + timedelta(days=12)
    obligation = Obligation(
        sentence="The tenant must submit the renewal form before 15/12/2026.",
        clause_type="submission",
        keyword="must submit",
        due_date=due,
        confidence=0.8,
    )
    deadlines = derive_deadlines("other", {}, [obligation])
    tasks = generate_tasks(doc_type="other", fields={}, deadlines=deadlines, obligations=[obligation])
    assert any(task.due_date == due for task in tasks)
