"""Processing orchestration: text -> classification -> extraction -> actions.

Each heavy step lives in its own module.  This file only wires them together
and persists the result, which makes the pipeline easy to run from tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from lifepilot import config
from lifepilot.db import crud
from lifepilot.db.models import Document, utcnow
from lifepilot.pipeline.classify import classify_document, classify_filename
from lifepilot.pipeline.extract import ExtractedField, extract_entities
from lifepilot.pipeline.llm_fallback import (
    extract_with_llm,
    llm_available,
    merge_llm_result,
)
from lifepilot.pipeline.obligations import Obligation, extract_obligations
from lifepilot.pipeline.ocr import extract_text
from lifepilot.pipeline.tasks import (
    DeadlineDraft,
    detect_missing_info,
    derive_deadlines,
    expected_field_names,
    generate_tasks,
)


@dataclass
class ProcessResult:
    document_id: int
    ok: bool
    doc_type: str = "other"
    doc_type_confidence: float = 0.0
    text_method: str = ""
    entities: int = 0
    deadlines: int = 0
    tasks: int = 0
    missing: int = 0
    llm_used: bool = False
    llm_attempted: bool = False
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


def _reference_date(fields: list[ExtractedField]) -> date:
    """Use the document's own date as the anchor for 'within N days' clauses."""
    for name in (
        "invoice_date",
        "issue_date",
        "purchase_date",
        "agreement_date",
        "start_date",
        "submission_date",
        "due_date",
    ):
        for item in fields:
            if item.field_name == name:
                try:
                    return date.fromisoformat(item.value[:10])
                except ValueError:
                    continue
    return date.today()


def _needs_llm(
    fields: list[ExtractedField], doc_type: str, threshold: float
) -> list[str]:
    """Return the expected fields that are missing or low confidence."""
    best: dict[str, float] = {}
    for item in fields:
        best[item.field_name] = max(best.get(item.field_name, 0.0), item.confidence)
    needed: list[str] = []
    for name in expected_field_names(doc_type):
        if name not in best or best[name] < threshold:
            needed.append(name)
    return needed


def _merge_llm_obligations(
    obligations: list[Obligation], llm_obligations: list
) -> list[Obligation]:
    existing = {item.sentence.strip().lower() for item in obligations}
    for item in llm_obligations:
        if item.text.strip().lower() in existing:
            continue
        due = date.fromisoformat(item.due_date) if item.due_date else None
        obligations.append(
            Obligation(
                sentence=item.text,
                clause_type=item.clause_type,
                keyword="llm",
                due_date=due,
                confidence=0.7,
            )
        )
        existing.add(item.text.strip().lower())
    return obligations


def _apply_doc_type_override(
    text: str,
    doc_type: str,
    confidence: float,
    llm_doc_type: str,
) -> tuple[str, float, list[ExtractedField] | None]:
    """Use the LLM's type only when rules were uncertain (and re-extract)."""
    if llm_doc_type == doc_type or confidence >= 0.6:
        return doc_type, confidence, None
    rerun = extract_entities(text, llm_doc_type).fields
    return llm_doc_type, max(confidence, 0.62), rerun


def process_document(
    session: Session,
    document_id: int,
    *,
    enable_llm: bool | None = None,
) -> ProcessResult:
    """Run the full pipeline for an uploaded document.

    The caller owns the transaction (use ``session_scope``).  Failures are
    recorded on the document row and returned, never raised to the UI.
    """
    document = session.get(Document, document_id)
    if document is None:
        return ProcessResult(document_id=document_id, ok=False, error="Document not found")

    settings = crud.get_settings(session)
    document.status = "processing"
    document.error_message = None

    extraction_result = extract_text(Path(document.stored_path))
    if not extraction_result.text.strip():
        document.status = "failed"
        document.extraction_method = extraction_result.method
        document.error_message = (
            extraction_result.warnings[0]
            if extraction_result.warnings
            else "No readable text found in this file."
        )
        return ProcessResult(
            document_id=document.id,
            ok=False,
            text_method=extraction_result.method,
            warnings=extraction_result.warnings,
            error=document.error_message,
        )

    # 1. Classify ------------------------------------------------------------
    classification = classify_document(extraction_result.text)
    doc_type = classification.doc_type
    doc_confidence = classification.confidence
    if doc_type == "other" and doc_confidence < 0.5:
        hint = classify_filename(document.filename)
        if hint:
            doc_type = hint
            doc_confidence = max(0.45, doc_confidence)

    # 2. Extract -------------------------------------------------------------
    fields = extract_entities(extraction_result.text, doc_type).fields

    # 3. Optional LLM fallback ----------------------------------------------
    llm_used = False
    llm_attempted = False
    llm_error: str | None = None
    llm_result = None
    use_llm = settings.llm_enabled if enable_llm is None else enable_llm
    needed = _needs_llm(fields, doc_type, config.NEEDS_REVIEW_THRESHOLD)
    if llm_available(use_llm) and needed:
        llm_attempted = True
        llm_result = extract_with_llm(
            extraction_result.text,
            enabled=True,
            doc_type=doc_type,
            missing_fields=needed,
            model=settings.llm_model,
        )
        if llm_result is not None:
            if llm_result.doc_type != doc_type and doc_confidence < 0.6:
                doc_type, doc_confidence, rerun_fields = _apply_doc_type_override(
                    extraction_result.text,
                    doc_type,
                    doc_confidence,
                    llm_result.doc_type,
                )
                if rerun_fields is not None:
                    fields = rerun_fields
            fields = merge_llm_result(fields, llm_result, review_threshold=config.NEEDS_REVIEW_THRESHOLD)
            llm_used = True
        else:
            llm_error = "AI assist was unavailable or returned an invalid response."
    elif needed and not use_llm:
        llm_error = "Some fields are missing; enable AI assist in Settings to try the LLM fallback."

    # 4. Obligations ---------------------------------------------------------
    reference_date = _reference_date(fields)
    obligations = extract_obligations(extraction_result.text, reference_date=reference_date)
    if llm_used and llm_result is not None:
        obligations = _merge_llm_obligations(obligations, llm_result.obligations)

    # 5. Values, deadlines, tasks, missing info ------------------------------
    value_map: dict[str, str] = {}
    for item in sorted(fields, key=lambda field: field.confidence, reverse=True):
        value_map.setdefault(item.field_name, item.value)

    required_documents = [
        item.value for item in fields if item.field_name == "required_document"
    ]
    deadlines: list[DeadlineDraft] = derive_deadlines(
        doc_type,
        value_map,
        obligations,
        default_remind_days=settings.remind_days_before,
    )
    task_drafts = generate_tasks(
        doc_type=doc_type,
        fields=value_map,
        deadlines=deadlines,
        obligations=obligations,
        required_documents=required_documents,
        filename=document.filename,
        currency=value_map.get("currency", settings.currency or "INR"),
    )
    missing_drafts = detect_missing_info(doc_type, value_map)

    # 6. Persist -------------------------------------------------------------
    entity_payloads = [item.to_payload() for item in fields]
    deadline_payloads = [
        {
            "title": draft.title,
            "due_date": draft.due_date,
            "kind": draft.kind,
            "confidence": draft.confidence,
            "remind_days_before": draft.remind_days_before,
            "source_text": draft.source_text,
        }
        for draft in deadlines
    ]
    task_payloads = [
        {
            "title": draft.title,
            "description": draft.description,
            "due_date": draft.due_date,
            "priority": draft.priority,
            "category": draft.category,
            "source": draft.source,
            "deadline_index": draft.deadline_index,
        }
        for draft in task_drafts
    ]
    missing_payloads = [
        {
            "field_name": draft.field_name,
            "description": draft.description,
            "severity": draft.severity,
        }
        for draft in missing_drafts
    ]

    crud.replace_extraction(
        session,
        document,
        entities=entity_payloads,
        deadlines=deadline_payloads,
        tasks=task_payloads,
        missing_info=missing_payloads,
    )

    document.doc_type = doc_type
    document.doc_type_confidence = round(doc_confidence, 2)
    document.raw_text = extraction_result.text
    document.extraction_method = extraction_result.method
    document.status = "processed"
    document.processed_at = utcnow()
    document.error_message = None

    warnings = list(extraction_result.warnings)
    if llm_error:
        warnings.append(llm_error)

    return ProcessResult(
        document_id=document.id,
        ok=True,
        doc_type=doc_type,
        doc_type_confidence=round(doc_confidence, 2),
        text_method=extraction_result.method,
        entities=len(entity_payloads),
        deadlines=len(deadline_payloads),
        tasks=len(task_payloads),
        missing=len(missing_payloads),
        llm_used=llm_used,
        llm_attempted=llm_attempted,
        warnings=warnings,
    )


def save_upload(
    session: Session,
    *,
    filename: str,
    data: bytes,
    upload_dir: Path | None = None,
) -> Document:
    """Store an uploaded file on disk and create its document row."""
    import hashlib
    import mimetypes
    import re
    import uuid

    target_dir = upload_dir or config.UPLOAD_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    safe_name = re.sub(r"[^A-Za-z0-9._ -]+", "_", Path(filename).name).strip() or "upload"
    stored_path = target_dir / f"{uuid.uuid4().hex[:12]}_{safe_name}"
    stored_path.write_bytes(data)
    mime_type = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    return crud.create_document(
        session,
        filename=safe_name,
        stored_path=str(stored_path),
        mime_type=mime_type,
        file_hash=digest,
    )
