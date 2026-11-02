"""SQLAlchemy models for LifePilot.

The schema is deliberately conservative (no SQLite-only features) so it can be
moved to PostgreSQL by only changing ``LIFEPILOT_DB_URL``.  All extracted values
carry a confidence score in ``[0, 1]`` and a provenance label.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """Timezone-naive UTC timestamp (portable across SQLite/PostgreSQL)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    """Declarative base for all LifePilot tables."""


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_hash: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(128))
    doc_type: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    doc_type_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    raw_text: Mapped[Optional[str]] = mapped_column(Text)
    extraction_method: Mapped[Optional[str]] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24), default="uploaded", index=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    entities: Mapped[List["Entity"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    deadlines: Mapped[List["Deadline"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    tasks: Mapped[List["Task"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    missing_info: Mapped[List["MissingInfo"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    notifications: Mapped[List["Notification"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Document id={self.id} type={self.doc_type!r} file={self.filename!r}>"


class Entity(Base):
    """A single extracted field (key/value pair) from a document."""

    __tablename__ = "entities"
    __table_args__ = (
        Index("ix_entities_document_field", "document_id", "field_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(String(24), default="text")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(24), default="rule")
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    position_ratio: Mapped[Optional[float]] = mapped_column(Float)
    page_number: Mapped[Optional[int]] = mapped_column(Integer)
    extra: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    document: Mapped[Document] = relationship(back_populates="entities")

    @property
    def needs_review(self) -> bool:
        return self.confidence < 0.6 and not self.confirmed


class Deadline(Base):
    """A dated obligation extracted from a document."""

    __tablename__ = "deadlines"
    __table_args__ = (
        Index("ix_deadlines_due_status", "due_date", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="deadline")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    remind_days_before: Mapped[int] = mapped_column(Integer, default=7)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    source_text: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    document: Mapped[Document] = relationship(back_populates="deadlines")
    tasks: Mapped[List["Task"]] = relationship(back_populates="deadline")

    @property
    def is_overdue(self) -> bool:
        return self.due_date < date.today() and self.status == "active"

    @property
    def days_remaining(self) -> int:
        return (self.due_date - date.today()).days


class Task(Base):
    """An actionable item generated from a document or deadline."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    deadline_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("deadlines.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    due_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    priority: Mapped[str] = mapped_column(String(16), default="medium")
    category: Mapped[str] = mapped_column(String(32), default="general")
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    source: Mapped[str] = mapped_column(String(24), default="rule")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    document: Mapped[Document] = relationship(back_populates="tasks")
    deadline: Mapped[Optional[Deadline]] = relationship(back_populates="tasks")

    @property
    def is_done(self) -> bool:
        return self.status == "done"


class MissingInfo(Base):
    """A field that the document type expects but extraction could not find."""

    __tablename__ = "missing_info"
    __table_args__ = (
        UniqueConstraint("document_id", "field_name", name="uq_missing_document_field"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(512), default="")
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    document: Mapped[Document] = relationship(back_populates="missing_info")


class AppSettings(Base):
    """Single-row settings table (id is always 1)."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    llm_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    llm_model: Mapped[str] = mapped_column(String(128), default="gpt-4o-mini")
    remind_days_before: Mapped[int] = mapped_column(Integer, default=7)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    email_to: Mapped[str] = mapped_column(String(320), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Notification(Base):
    """In-app reminder generated by the scheduler."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    deadline_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("deadlines.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    message: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(24), default="reminder")
    dedupe_key: Mapped[Optional[str]] = mapped_column(String(255), unique=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    document: Mapped[Optional[Document]] = relationship(back_populates="notifications")


class EmailLog(Base):
    """Delivery record for every email LifePilot tries to send.

    Keeping the rendered subject and body makes the email feature inspectable
    in the UI (an outbox) even when SMTP is not configured yet.
    """

    __tablename__ = "email_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    to_address: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(512), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="sent", index=True)
    detail: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
