"""Seed the app with the bundled sample documents for a quick demo."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from lifepilot import config
from lifepilot.db import crud
from lifepilot.pipeline.processor import ProcessResult, process_document, save_upload
from lifepilot.pipeline.tasks import EXPECTED_FIELDS

SAMPLE_FILES: tuple[str, ...] = (
    "electricity_bill.pdf",
    "warranty_card.pdf",
    "rental_agreement.pdf",
    "application_form.pdf",
)


def seed_demo_documents(
    session: Session, *, upload_dir: Path | None = None
) -> list[tuple[int, str, ProcessResult]]:
    """Process bundled PDFs that are not already in the database."""
    existing = {document.filename for document in crud.list_documents(session, limit=1000)}
    created: list[tuple[int, str, ProcessResult]] = []
    for filename in SAMPLE_FILES:
        if filename in existing:
            continue
        path = config.SAMPLE_DIR / filename
        if not path.exists():
            continue
        document = save_upload(
            session,
            filename=filename,
            data=path.read_bytes(),
            upload_dir=upload_dir,
        )
        result = process_document(session, document.id, enable_llm=False)
        created.append((document.id, filename, result))
    return created


def expected_fields_for(doc_type: str) -> list[tuple[str, str]]:
    """Labels for the expected fields of a document type (UI helper)."""
    return [
        (item.name, item.label) for item in EXPECTED_FIELDS.get(doc_type, ())
    ]
