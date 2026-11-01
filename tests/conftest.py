"""Shared pytest fixtures: temporary database and sample documents."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from lifepilot.db import crud
from lifepilot.db.database import configure_database, get_session_factory, init_db
from lifepilot.tests.make_samples import main as generate_samples

SAMPLE_DIR = Path(__file__).resolve().parent / "sample_documents"


@pytest.fixture(scope="session", autouse=True)
def ensure_samples() -> None:
    if not (SAMPLE_DIR / "electricity_bill.pdf").exists():
        generate_samples()


@pytest.fixture()
def session() -> Session:
    """Fresh in-memory database per test."""
    configure_database("sqlite:///:memory:")
    init_db()
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def settings(session: Session):
    return crud.get_settings(session)
