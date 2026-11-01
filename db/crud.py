"""CRUD helpers used by the UI, pipeline and scheduler.

Keeping queries here (instead of in Streamlit pages) makes the app easier to
test and keeps the UI layer thin.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Iterable, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from lifepilot.db.models import (
    AppSettings,
    Deadline,
    Document,
    Entity,
    MissingInfo,
    Notification,
    Task,
    utcnow,
)
from lifepilot.utils import infer_expense_category, parse_amount


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
def create_document(
    session: Session,
    *,
    filename: str,
    stored_path: str,
    mime_type: str | None = None,
    file_hash: str | None = None,
    status: str = "uploaded",
) -> Document:
    document = Document(
        filename=filename,
        stored_path=stored_path,
        mime_type=mime_type,
        file_hash=file_hash,
        status=status,
    )
    session.add(document)
    session.flush()
    return document


def get_document(session: Session, document_id: int) -> Document | None:
    return session.get(Document, document_id)


def list_documents(
    session: Session, *, limit: int = 200, doc_type: str | None = None
) -> list[Document]:
    stmt = select(Document).order_by(Document.uploaded_at.desc()).limit(limit)
    if doc_type:
        stmt = stmt.where(Document.doc_type == doc_type)
    return list(session.scalars(stmt))


def delete_document(session: Session, document_id: int) -> bool:
    document = session.get(Document, document_id)
    if document is None:
        return False
    session.delete(document)
    return True


def update_document(session: Session, document_id: int, **values: Any) -> Document | None:
    document = session.get(Document, document_id)
    if document is None:
        return None
    for key, value in values.items():
        if hasattr(document, key):
            setattr(document, key, value)
    return document


# ---------------------------------------------------------------------------
# Extraction replacement (used on upload and re-processing)
# ---------------------------------------------------------------------------
def replace_extraction(
    session: Session,
    document: Document,
    *,
    entities: Sequence[dict[str, Any]],
    deadlines: Sequence[dict[str, Any]],
    tasks: Sequence[dict[str, Any]],
    missing_info: Sequence[dict[str, Any]],
) -> None:
    """Replace every derived row for a document atomically.

    ``tasks`` may include a ``deadline_index`` key pointing into ``deadlines``
    so generated tasks are linked to the right reminder.
    """
    for model in (Task, MissingInfo, Deadline, Entity):
        session.query(model).filter(model.document_id == document.id).delete(
            synchronize_session=False
        )
    session.flush()

    for payload in entities:
        session.add(Entity(document_id=document.id, **payload))

    deadline_objects: list[Deadline] = []
    for payload in deadlines:
        deadline = Deadline(document_id=document.id, **payload)
        session.add(deadline)
        deadline_objects.append(deadline)
    session.flush()

    for payload in tasks:
        data = dict(payload)
        index = data.pop("deadline_index", None)
        deadline = deadline_objects[index] if index is not None and index < len(deadline_objects) else None
        session.add(
            Task(
                document_id=document.id,
                deadline_id=deadline.id if deadline else None,
                **data,
            )
        )

    for payload in missing_info:
        session.add(MissingInfo(document_id=document.id, **payload))
    session.flush()


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------
def get_entities(
    session: Session, document_id: int, *, field_name: str | None = None
) -> list[Entity]:
    stmt = (
        select(Entity)
        .where(Entity.document_id == document_id)
        .order_by(Entity.field_name, Entity.id)
    )
    if field_name:
        stmt = stmt.where(Entity.field_name == field_name)
    return list(session.scalars(stmt))


def get_entity_map(session: Session, document_id: int) -> dict[str, Entity]:
    """First (highest confidence) entity per field name."""
    entities = get_entities(session, document_id)
    result: dict[str, Entity] = {}
    for entity in sorted(entities, key=lambda e: e.confidence, reverse=True):
        result.setdefault(entity.field_name, entity)
    return result


def confirm_entity(
    session: Session,
    entity_id: int,
    *,
    value: str | None = None,
    value_type: str | None = None,
) -> Entity | None:
    """User review: store the edited value with confidence 1.0."""
    entity = session.get(Entity, entity_id)
    if entity is None:
        return None
    if value is not None:
        entity.value = value.strip()
    if value_type:
        entity.value_type = value_type
    entity.confidence = 1.0
    entity.confirmed = True
    entity.source = "user"
    for missing in session.scalars(
        select(MissingInfo).where(
            MissingInfo.document_id == entity.document_id,
            MissingInfo.field_name == entity.field_name,
        )
    ):
        missing.resolved = True
    return entity


def delete_entity(session: Session, entity_id: int) -> bool:
    entity = session.get(Entity, entity_id)
    if entity is None:
        return False
    session.delete(entity)
    return True


def upsert_entity(
    session: Session,
    document_id: int,
    *,
    field_name: str,
    value: str,
    value_type: str = "text",
    confidence: float = 1.0,
    source: str = "user",
) -> Entity:
    """Create or update a manually entered field and clear its missing flag."""
    entity = session.scalar(
        select(Entity)
        .where(Entity.document_id == document_id, Entity.field_name == field_name)
        .order_by(Entity.confidence.desc())
        .limit(1)
    )
    if entity is None:
        entity = Entity(
            document_id=document_id,
            field_name=field_name,
            value=value,
            value_type=value_type,
            confidence=confidence,
            source=source,
            confirmed=True,
        )
        session.add(entity)
    else:
        entity.value = value
        entity.value_type = value_type
        entity.confidence = confidence
        entity.source = source
        entity.confirmed = True
    session.query(MissingInfo).filter(
        MissingInfo.document_id == document_id,
        MissingInfo.field_name == field_name,
    ).update({"resolved": True}, synchronize_session=False)
    session.flush()
    return entity


# ---------------------------------------------------------------------------
# Deadlines & tasks
# ---------------------------------------------------------------------------
def upcoming_deadlines(
    session: Session,
    *,
    document_id: int | None = None,
    days: int | None = None,
    include_overdue: bool = True,
    limit: int = 100,
) -> list[Deadline]:
    today = date.today()
    stmt = (
        select(Deadline)
        .options(joinedload(Deadline.document))
        .where(Deadline.status == "active")
        .order_by(Deadline.due_date.asc())
        .limit(limit)
    )
    if document_id is not None:
        stmt = stmt.where(Deadline.document_id == document_id)
    if days is not None:
        stmt = stmt.where(Deadline.due_date <= today + timedelta(days=days))
    if not include_overdue:
        stmt = stmt.where(Deadline.due_date >= today)
    return list(session.scalars(stmt).unique())


def dismiss_deadline(session: Session, deadline_id: int) -> bool:
    deadline = session.get(Deadline, deadline_id)
    if deadline is None:
        return False
    deadline.status = "dismissed"
    return True


def list_tasks(
    session: Session,
    *,
    document_id: int | None = None,
    include_done: bool = False,
    limit: int = 200,
) -> list[Task]:
    stmt = (
        select(Task)
        .options(joinedload(Task.document))
        .order_by(Task.status.asc(), Task.due_date.asc().nulls_last(), Task.id.desc())
        .limit(limit)
    )
    if document_id is not None:
        stmt = stmt.where(Task.document_id == document_id)
    if not include_done:
        stmt = stmt.where(Task.status == "open")
    return list(session.scalars(stmt).unique())


def set_task_done(session: Session, task_id: int, done: bool = True) -> Task | None:
    task = session.get(Task, task_id)
    if task is None:
        return None
    task.status = "done" if done else "open"
    task.completed_at = utcnow() if done else None
    return task


# ---------------------------------------------------------------------------
# Missing information
# ---------------------------------------------------------------------------
def list_missing_info(
    session: Session, document_id: int, *, include_resolved: bool = False
) -> list[MissingInfo]:
    stmt = (
        select(MissingInfo)
        .where(MissingInfo.document_id == document_id)
        .order_by(MissingInfo.severity.desc(), MissingInfo.id)
    )
    if not include_resolved:
        stmt = stmt.where(MissingInfo.resolved.is_(False))
    return list(session.scalars(stmt))


def resolve_missing_info(session: Session, missing_id: int, resolved: bool = True) -> bool:
    item = session.get(MissingInfo, missing_id)
    if item is None:
        return False
    item.resolved = resolved
    return True


def unresolved_missing_count(session: Session, document_id: int) -> int:
    return int(
        session.scalar(
            select(func.count(MissingInfo.id)).where(
                MissingInfo.document_id == document_id,
                MissingInfo.resolved.is_(False),
            )
        )
        or 0
    )


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def get_settings(session: Session) -> AppSettings:
    settings = session.get(AppSettings, 1)
    if settings is None:
        settings = AppSettings(id=1)
        session.add(settings)
        session.flush()
    return settings


def update_settings(session: Session, **values: Any) -> AppSettings:
    settings = get_settings(session)
    for key, value in values.items():
        if hasattr(settings, key) and key != "id":
            setattr(settings, key, value)
    settings.updated_at = utcnow()
    session.flush()
    return settings


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
def list_notifications(
    session: Session, *, unread_only: bool = False, limit: int = 50
) -> list[Notification]:
    stmt = select(Notification).order_by(Notification.created_at.desc()).limit(limit)
    if unread_only:
        stmt = stmt.where(Notification.read.is_(False))
    return list(session.scalars(stmt))


def create_notification(
    session: Session,
    *,
    title: str,
    message: str,
    document_id: int | None = None,
    deadline_id: int | None = None,
    kind: str = "reminder",
    dedupe_key: str | None = None,
) -> Notification | None:
    if dedupe_key:
        existing = session.scalar(
            select(Notification).where(Notification.dedupe_key == dedupe_key)
        )
        if existing:
            return existing
    notification = Notification(
        title=title,
        message=message,
        document_id=document_id,
        deadline_id=deadline_id,
        kind=kind,
        dedupe_key=dedupe_key,
    )
    session.add(notification)
    session.flush()
    return notification


def mark_notification_read(session: Session, notification_id: int) -> bool:
    notification = session.get(Notification, notification_id)
    if notification is None:
        return False
    notification.read = True
    return True


def mark_all_notifications_read(session: Session) -> int:
    count = (
        session.query(Notification)
        .filter(Notification.read.is_(False))
        .update({"read": True}, synchronize_session=False)
    )
    return int(count or 0)


# ---------------------------------------------------------------------------
# Dashboard statistics & spending
# ---------------------------------------------------------------------------
def dashboard_counts(session: Session) -> dict[str, int]:
    today = date.today()
    week_end = today + timedelta(days=7)
    return {
        "documents": int(session.scalar(select(func.count(Document.id))) or 0),
        "open_tasks": int(
            session.scalar(select(func.count(Task.id)).where(Task.status == "open")) or 0
        ),
        "due_this_week": int(
            session.scalar(
                select(func.count(Deadline.id)).where(
                    Deadline.status == "active",
                    Deadline.due_date >= today,
                    Deadline.due_date <= week_end,
                )
            )
            or 0
        ),
        "overdue": int(
            session.scalar(
                select(func.count(Deadline.id)).where(
                    Deadline.status == "active", Deadline.due_date < today
                )
            )
            or 0
        ),
        "needs_review": int(
            session.scalar(
                select(func.count(Entity.id)).where(
                    Entity.confidence < 0.6, Entity.confirmed.is_(False)
                )
            )
            or 0
        ),
    }


def spending_records(session: Session) -> list[dict[str, Any]]:
    """Flat records for the spending dashboard.

    Uses ``amount_total`` (falling back to ``amount``) from bills/receipts and
    the best available date (purchase/invoice/due date, else upload date).
    """
    settings = get_settings(session)
    docs = list(
        session.scalars(
            select(Document).where(Document.doc_type.in_(["bill", "receipt"]))
        )
    )
    records: list[dict[str, Any]] = []
    for doc in docs:
        fields = {
            e.field_name: e
            for e in sorted(doc.entities, key=lambda x: x.confidence, reverse=True)
        }
        amount_entity = fields.get("amount_total") or fields.get("amount")
        if amount_entity is None:
            continue
        amount = parse_amount(amount_entity.value)
        if amount is None or amount <= 0:
            continue
        when: date | None = None
        for field_name in ("purchase_date", "invoice_date", "due_date"):
            entity = fields.get(field_name)
            if entity is None:
                continue
            try:
                when = date.fromisoformat(entity.value[:10])
                break
            except ValueError:
                continue
        when = when or doc.uploaded_at.date()
        vendor = fields.get("vendor").value if fields.get("vendor") else doc.filename
        category_entity = fields.get("category")
        category = (
            category_entity.value
            if category_entity is not None
            else infer_expense_category(doc.raw_text, vendor)
        )
        currency = (
            fields["currency"].value
            if "currency" in fields
            else settings.currency or "INR"
        )
        records.append(
            {
                "document_id": doc.id,
                "document": doc.filename,
                "doc_type": doc.doc_type,
                "vendor": vendor,
                "category": category,
                "amount": amount,
                "currency": currency,
                "date": when,
                "month": when.strftime("%Y-%m"),
                "month_label": when.strftime("%b %Y"),
                "confidence": amount_entity.confidence,
            }
        )
    records.sort(key=lambda row: row["date"], reverse=True)
    return records
