"""Database engine / session management.

A single lazily-created engine is shared by the Streamlit UI, the pipeline and
the scheduler.  Tests can call :func:`configure_database` with a temporary URL.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from lifepilot import config
from lifepilot.db.models import Base

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_current_url: str | None = None


def _make_engine(url: str) -> Engine:
    kwargs: dict = {"future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
        else:
            db_path = url.replace("sqlite:///", "", 1)
            if db_path:
                Path(db_path).expanduser().resolve().parent.mkdir(
                    parents=True, exist_ok=True
                )
    engine = create_engine(url, **kwargs)

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _enable_fk(dbapi_connection, _record):  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            # WAL + a busy timeout keep concurrent cloud visitors from
            # immediately hitting "database is locked" on write.
            if ":memory:" not in url:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine


def get_engine(url: str | None = None) -> Engine:
    """Return the shared engine, creating it on first use."""
    global _engine, _session_factory, _current_url
    # Once configured, keep using that database even when callers omit the URL
    # (tests configure an in-memory database, the app uses config.DATABASE_URL).
    target = url or _current_url or config.DATABASE_URL
    if _engine is None or target != _current_url:
        if _engine is not None:
            _engine.dispose()
        _engine = _make_engine(target)
        _session_factory = sessionmaker(
            bind=_engine, autoflush=False, expire_on_commit=False
        )
        _current_url = target
    return _engine


def get_session_factory(url: str | None = None) -> sessionmaker[Session]:
    get_engine(url)
    assert _session_factory is not None
    return _session_factory


def configure_database(url: str) -> None:
    """Point the app at a new database URL (used by tests)."""
    global _engine, _session_factory, _current_url
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
    _current_url = None
    get_engine(url)


def init_db(url: str | None = None) -> None:
    """Create all tables if they do not already exist."""
    engine = get_engine(url)
    Base.metadata.create_all(engine)


def reset_db(url: str | None = None) -> None:
    """Drop and recreate every table (tests only)."""
    engine = get_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


@contextmanager
def session_scope(url: str | None = None) -> Iterator[Session]:
    """Transactional session context manager."""
    factory = get_session_factory(url)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
