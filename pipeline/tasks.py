"""Deadline derivation, task generation and missing-information rules.

This module is intentionally pure: it takes extracted field values and returns
plain dataclasses, making the rules easy to unit test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Mapping, Sequence

from lifepilot.pipeline.extract import ExtractedField
from lifepilot.pipeline.obligations import Obligation
from lifepilot.utils import fmt_date, format_amount, parse_amount

# ---------------------------------------------------------------------------
# Expected fields (missing information detection)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ExpectedField:
    name: str
    label: str
    severity: str = "medium"


EXPECTED_FIELDS: dict[str, tuple[ExpectedField, ...]] = {
    "bill": (
        ExpectedField("vendor", "Vendor / biller", "high"),
        ExpectedField("amount_total", "Total amount due", "high"),
        ExpectedField("due_date", "Payment due date", "high"),
        ExpectedField("invoice_number", "Invoice number", "low"),
        ExpectedField("account_number", "Account / consumer number", "low"),
    ),
    "receipt": (
        ExpectedField("vendor", "Merchant / vendor", "high"),
        ExpectedField("amount_total", "Total paid", "high"),
        ExpectedField("purchase_date", "Purchase date", "medium"),
        ExpectedField("receipt_number", "Receipt number", "low"),
    ),
    "warranty": (
        ExpectedField("product", "Product name", "high"),
        ExpectedField("purchase_date", "Purchase date", "high"),
        ExpectedField("expiry_date", "Warranty expiry date", "high"),
        ExpectedField("warranty_period", "Warranty period", "medium"),
        ExpectedField("vendor", "Brand / seller", "low"),
        ExpectedField("warranty_number", "Warranty serial number", "low"),
    ),
    "agreement": (
        ExpectedField("landlord_name", "Landlord / lessor", "high"),
        ExpectedField("tenant_name", "Tenant / lessee", "high"),
        ExpectedField("rent_amount", "Monthly rent", "high"),
        ExpectedField("start_date", "Agreement start date", "medium"),
        ExpectedField("end_date", "Agreement end date", "medium"),
        ExpectedField("renewal_date", "Renewal date", "medium"),
        ExpectedField("deposit_amount", "Security deposit", "low"),
        ExpectedField("notice_period", "Notice period", "low"),
    ),
    "certificate": (
        ExpectedField("holder_name", "Certificate holder", "high"),
        ExpectedField("issuer", "Issuing organisation", "medium"),
        ExpectedField("certificate_number", "Certificate number", "low"),
        ExpectedField("expiry_date", "Expiry date", "medium"),
    ),
    "application": (
        ExpectedField("applicant_name", "Applicant name", "high"),
        ExpectedField("application_number", "Application number", "medium"),
        ExpectedField("submission_date", "Submission deadline", "medium"),
        ExpectedField("dob", "Date of birth", "medium"),
        ExpectedField("required_document", "Required documents list", "low"),
    ),
    "other": (),
}


@dataclass
class MissingInfoDraft:
    field_name: str
    description: str
    severity: str = "medium"


def expected_field_names(doc_type: str) -> list[str]:
    return [item.name for item in EXPECTED_FIELDS.get(doc_type, ())]


def detect_missing_info(
    doc_type: str, fields: Mapping[str, str]
) -> list[MissingInfoDraft]:
    """Flag expected fields that are absent from the extraction result."""
    missing: list[MissingInfoDraft] = []
    for expected in EXPECTED_FIELDS.get(doc_type, ()):
        if not str(fields.get(expected.name, "")).strip():
            missing.append(
                MissingInfoDraft(
                    field_name=expected.name,
                    description=f"{expected.label} was not found in the document.",
                    severity=expected.severity,
                )
            )
    return missing


# ---------------------------------------------------------------------------
# Deadlines
# ---------------------------------------------------------------------------
@dataclass
class DeadlineDraft:
    title: str
    due_date: date
    kind: str = "deadline"
    confidence: float = 0.8
    remind_days_before: int = 7
    source_text: str = ""


@dataclass
class TaskDraft:
    title: str
    description: str = ""
    due_date: date | None = None
    priority: str = "medium"
    category: str = "general"
    source: str = "rule"
    deadline_index: int | None = None


def _field_value(fields: Mapping[str, str], name: str) -> str:
    return str(fields.get(name, "") or "").strip()


def _field_date(fields: Mapping[str, str], name: str) -> date | None:
    raw = _field_value(fields, name)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _priority_for(due: date | None, *, high_within: int = 3, medium_within: int = 14) -> str:
    if due is None:
        return "low"
    remaining = (due - date.today()).days
    if remaining < 0 or remaining <= high_within:
        return "high"
    if remaining <= medium_within:
        return "medium"
    return "low"


def derive_deadlines(
    doc_type: str,
    fields: Mapping[str, str],
    obligations: Sequence[Obligation] = (),
    *,
    default_remind_days: int = 7,
) -> list[DeadlineDraft]:
    """Turn extracted dates into trackable deadlines."""
    deadlines: list[DeadlineDraft] = []

    def add(
        title: str,
        due: date | None,
        *,
        kind: str,
        confidence: float,
        remind_days: int,
        source_text: str = "",
    ) -> None:
        if due is None:
            return
        key = (due, kind)
        if any((item.due_date, item.kind) == key for item in deadlines):
            return
        deadlines.append(
            DeadlineDraft(
                title=title,
                due_date=due,
                kind=kind,
                confidence=round(confidence, 2),
                remind_days_before=remind_days,
                source_text=source_text,
            )
        )

    if doc_type == "bill":
        add(
            "Bill payment due",
            _field_date(fields, "due_date"),
            kind="payment",
            confidence=0.9,
            remind_days=default_remind_days,
        )
    elif doc_type == "warranty":
        add(
            "Warranty expires",
            _field_date(fields, "expiry_date"),
            kind="expiry",
            confidence=0.85,
            remind_days=30,
        )
    elif doc_type == "agreement":
        renewal = _field_date(fields, "renewal_date") or _field_date(fields, "end_date")
        add(
            "Agreement renewal due",
            renewal,
            kind="renewal",
            confidence=0.85,
            remind_days=15,
        )
    elif doc_type == "certificate":
        add(
            "Certificate expires",
            _field_date(fields, "expiry_date"),
            kind="expiry",
            confidence=0.85,
            remind_days=30,
        )
    elif doc_type == "application":
        add(
            "Application submission deadline",
            _field_date(fields, "submission_date"),
            kind="submission",
            confidence=0.8,
            remind_days=default_remind_days,
        )

    # Clauses can add deadlines the typed rules did not know about.
    kind_by_clause = {
        "payment": "payment",
        "renewal": "renewal",
        "expiry": "expiry",
        "submission": "submission",
        "termination": "termination",
        "general": "obligation",
    }
    for obligation in obligations:
        if obligation.due_date is None:
            continue
        add(
            f"{obligation.clause_type.title()} clause deadline",
            obligation.due_date,
            kind=kind_by_clause.get(obligation.clause_type, "obligation"),
            confidence=obligation.confidence,
            remind_days=default_remind_days,
            source_text=obligation.sentence[:400],
        )
    return sorted(deadlines, key=lambda item: item.due_date)


def _link(
    deadlines: Sequence[DeadlineDraft], kinds: Sequence[str], due: date | None
) -> int | None:
    if due is None:
        return None
    for index, deadline in enumerate(deadlines):
        if deadline.due_date == due and deadline.kind in kinds:
            return index
    return None


# ---------------------------------------------------------------------------
# Task rules
# ---------------------------------------------------------------------------
def generate_tasks(
    *,
    doc_type: str,
    fields: Mapping[str, str],
    deadlines: Sequence[DeadlineDraft] = (),
    obligations: Sequence[Obligation] = (),
    required_documents: Sequence[str] = (),
    filename: str = "document",
    currency: str = "INR",
) -> list[TaskDraft]:
    """Generate actionable tasks for a processed document."""
    tasks: list[TaskDraft] = []
    vendor = _field_value(fields, "vendor") or "the vendor"
    amount = parse_amount(_field_value(fields, "amount_total"))
    due = _field_date(fields, "due_date")

    if doc_type == "bill":
        if due and amount is not None:
            tasks.append(
                TaskDraft(
                    title=f"Pay {format_amount(amount, currency)} to {vendor} by {fmt_date(due)}",
                    description="Bill payment generated automatically from the uploaded document.",
                    due_date=due,
                    priority="high" if (due - date.today()).days <= 7 else "medium",
                    category="payments",
                    deadline_index=_link(deadlines, ["payment"], due),
                )
            )
        elif due:
            tasks.append(
                TaskDraft(
                    title=f"Pay the {vendor} bill by {fmt_date(due)}",
                    description="The amount could not be extracted; confirm it and pay.",
                    due_date=due,
                    priority="high" if (due - date.today()).days <= 7 else "medium",
                    category="payments",
                    deadline_index=_link(deadlines, ["payment"], due),
                )
            )
        else:
            tasks.append(
                TaskDraft(
                    title=f"Find the payment due date for the {vendor} bill",
                    description="No due date was found. Check the bill and add a deadline.",
                    due_date=date.today() + timedelta(days=3),
                    priority="high",
                    category="payments",
                )
            )
        if amount is None and due:
            tasks.append(
                TaskDraft(
                    title=f"Confirm the bill amount from {vendor}",
                    description="The total amount is missing or ambiguous.",
                    due_date=max(date.today(), due - timedelta(days=2)),
                    priority="medium",
                    category="payments",
                )
            )

    elif doc_type == "receipt":
        purchase = _field_date(fields, "purchase_date") or date.today()
        tasks.append(
            TaskDraft(
                title=f"File receipt from {vendor}"
                + (f" ({format_amount(amount, currency)})" if amount is not None else ""),
                description="Keep the receipt for returns, warranty claims and expense tracking.",
                due_date=purchase + timedelta(days=3),
                priority="low",
                category="records",
            )
        )

    elif doc_type == "warranty":
        expiry = _field_date(fields, "expiry_date")
        product = _field_value(fields, "product") or "your product"
        if expiry:
            reminder_date = expiry - timedelta(days=30)
            tasks.append(
                TaskDraft(
                    title=f"Book a warranty check for {product} before {fmt_date(expiry)}",
                    description=(
                        f"The warranty expires on {fmt_date(expiry)}. "
                        "Schedule any repairs or service before cover ends."
                    ),
                    due_date=max(date.today(), reminder_date),
                    priority=_priority_for(reminder_date, high_within=7, medium_within=30),
                    category="warranty",
                    deadline_index=_link(deadlines, ["expiry"], expiry),
                )
            )
        else:
            tasks.append(
                TaskDraft(
                    title=f"Find the warranty expiry date for {product}",
                    description="No expiry date was found; check the warranty card or invoice.",
                    due_date=date.today() + timedelta(days=7),
                    priority="medium",
                    category="warranty",
                )
            )

    elif doc_type == "agreement":
        start = _field_date(fields, "start_date")
        renewal = _field_date(fields, "renewal_date") or _field_date(fields, "end_date")
        property_label = _field_value(fields, "property_address") or "rental"
        rent = parse_amount(_field_value(fields, "rent_amount"))
        if renewal:
            review_date = renewal - timedelta(days=15)
            tasks.append(
                TaskDraft(
                    title=f"Review renewal for the {property_label} agreement",
                    description=(
                        f"Renewal / end date is {fmt_date(renewal)}. "
                        f"Review terms 15 days before the deadline."
                        + (
                            f" Current rent: {format_amount(rent, currency)}."
                            if rent is not None
                            else ""
                        )
                    ),
                    due_date=max(date.today(), review_date),
                    priority=_priority_for(review_date, high_within=7, medium_within=30),
                    category="renewals",
                    deadline_index=_link(deadlines, ["renewal"], renewal),
                )
            )
        else:
            tasks.append(
                TaskDraft(
                    title=f"Review the {property_label} agreement terms",
                    description="No renewal date was found. Confirm the renewal window with the other party.",
                    due_date=date.today() + timedelta(days=14),
                    priority="medium",
                    category="renewals",
                )
            )
        if rent is not None:
            rent_due = (
                start - timedelta(days=3)
                if start and start > date.today()
                else date.today() + timedelta(days=3)
            )
            tasks.append(
                TaskDraft(
                    title=f"Set up a standing instruction for rent of {format_amount(rent, currency)}",
                    description="Avoid late payments by automating the monthly rent transfer.",
                    due_date=rent_due,
                    priority="medium",
                    category="payments",
                )
            )

    elif doc_type == "certificate":
        expiry = _field_date(fields, "expiry_date")
        holder = _field_value(fields, "holder_name") or "the certificate"
        if expiry:
            reminder_date = expiry - timedelta(days=30)
            tasks.append(
                TaskDraft(
                    title=f"Renew {holder} certificate before {fmt_date(expiry)}",
                    description=f"The certificate expires on {fmt_date(expiry)}.",
                    due_date=max(date.today(), reminder_date),
                    priority=_priority_for(reminder_date, high_within=7, medium_within=30),
                    category="renewals",
                    deadline_index=_link(deadlines, ["expiry"], expiry),
                )
            )
        else:
            tasks.append(
                TaskDraft(
                    title=f"Check the validity of {holder}",
                    description="No expiry date was found on the certificate.",
                    due_date=date.today() + timedelta(days=14),
                    priority="low",
                    category="renewals",
                )
            )

    elif doc_type == "application":
        submission = _field_date(fields, "submission_date")
        collect_by = (
            max(date.today(), submission - timedelta(days=5))
            if submission
            else date.today() + timedelta(days=7)
        )
        for document_name in list(dict.fromkeys(required_documents))[:8]:
            tasks.append(
                TaskDraft(
                    title=f"Collect document: {document_name}",
                    description="Required attachment listed on the application form.",
                    due_date=collect_by,
                    priority="medium",
                    category="paperwork",
                )
            )
        if submission:
            tasks.append(
                TaskDraft(
                    title="Review and submit the application",
                    description=(
                        "Check every field, attach the required documents and submit "
                        f"by {fmt_date(submission)}."
                    ),
                    due_date=submission,
                    priority="high" if (submission - date.today()).days <= 7 else "medium",
                    category="paperwork",
                    deadline_index=_link(deadlines, ["submission"], submission),
                )
            )

    # Generic fallback: capture dated obligations that did not match a rule.
    covered_categories = {task.category for task in tasks}
    for obligation in obligations:
        if obligation.due_date is None or len(tasks) >= 12:
            continue
        if obligation.clause_type in {"payment", "renewal", "expiry", "submission"}:
            if covered_categories & {"payments", "renewals"}:
                continue
        linked = _link(deadlines, [obligation.clause_type if obligation.clause_type != "general" else "obligation"], obligation.due_date)
        snippet = obligation.sentence[:140]
        tasks.append(
            TaskDraft(
                title=f"Action required: {snippet}",
                description=obligation.sentence[:500],
                due_date=obligation.due_date,
                priority=_priority_for(obligation.due_date),
                category="compliance",
                deadline_index=linked,
            )
        )

    if not tasks:
        tasks.append(
            TaskDraft(
                title=f"Review {filename}",
                description="No scheduled action was detected. Review the extracted fields.",
                due_date=date.today() + timedelta(days=3),
                priority="low",
                category="general",
            )
        )

    # Stable order: earliest due first, then priority.
    priority_order = {"high": 0, "medium": 1, "low": 2}
    tasks.sort(
        key=lambda task: (
            task.due_date or date.max,
            priority_order.get(task.priority, 1),
        )
    )
    return tasks


def fields_from_entities(entities: Sequence[ExtractedField]) -> dict[str, str]:
    """Best value per field name from extracted fields."""
    result: dict[str, str] = {}
    for item in sorted(entities, key=lambda field: field.confidence, reverse=True):
        result.setdefault(item.field_name, item.value)
    return result


def required_documents_from_entities(entities: Sequence[ExtractedField]) -> list[str]:
    return [
        item.value
        for item in entities
        if item.field_name == "required_document" and item.value.strip()
    ]
