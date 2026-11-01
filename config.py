"""Application-wide configuration.

All secrets and deployment-specific values are read from environment variables
(optionally loaded from a local ``.env`` file).  The module intentionally keeps
plain module-level constants so the rest of the app can import them directly.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# The project folder that contains app.py, .env, data/ and tests/.
BASE_DIR: Path = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

APP_NAME: str = "LifePilot"
APP_TAGLINE: str = "Turn paperwork into a plan."

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
DATA_DIR: Path = Path(os.getenv("LIFEPILOT_DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR: Path = DATA_DIR / "uploads"
EXPORT_DIR: Path = DATA_DIR / "exports"
SAMPLE_DIR: Path = BASE_DIR / "tests" / "sample_documents"

# Optional explicit paths for the OCR binaries on Windows.
TESSERACT_CMD: str = os.getenv("LIFEPILOT_TESSERACT_CMD", "")
POPPLER_PATH: str = os.getenv("LIFEPILOT_POPPLER_PATH", "")

DATABASE_URL: str = os.getenv(
    "LIFEPILOT_DB_URL", f"sqlite:///{(DATA_DIR / 'lifepilot.db').as_posix()}"
)

# ---------------------------------------------------------------------------
# Extraction / review
# ---------------------------------------------------------------------------
NEEDS_REVIEW_THRESHOLD: float = 0.60
DEFAULT_REMIND_DAYS: int = 7
DEFAULT_CURRENCY: str = "INR"
MAX_UPLOAD_MB: int = 25

# ---------------------------------------------------------------------------
# LLM fallback (optional -- the app is fully functional without it)
# ---------------------------------------------------------------------------
LLM_API_KEY: str = os.getenv("LIFEPILOT_LLM_API_KEY", "")
LLM_BASE_URL: str = os.getenv(
    "LIFEPILOT_LLM_BASE_URL", "https://api.openai.com/v1"
)
LLM_MODEL: str = os.getenv("LIFEPILOT_LLM_MODEL", "gpt-4o-mini")
LLM_TIMEOUT: int = int(os.getenv("LIFEPILOT_LLM_TIMEOUT", "45"))

# ---------------------------------------------------------------------------
# Email (optional)
# ---------------------------------------------------------------------------
SMTP_HOST: str = os.getenv("LIFEPILOT_SMTP_HOST", "")
SMTP_PORT: int = int(os.getenv("LIFEPILOT_SMTP_PORT", "587"))
SMTP_USER: str = os.getenv("LIFEPILOT_SMTP_USER", "")
SMTP_PASSWORD: str = os.getenv("LIFEPILOT_SMTP_PASSWORD", "")
SMTP_FROM: str = os.getenv("LIFEPILOT_SMTP_FROM", SMTP_USER)
SMTP_USE_TLS: bool = os.getenv("LIFEPILOT_SMTP_USE_TLS", "true").lower() in {
    "1",
    "true",
    "yes",
}

# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
REMINDER_CHECK_HOURS: int = int(os.getenv("LIFEPILOT_REMINDER_CHECK_HOURS", "6"))

# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------
CURRENCY_SYMBOLS: dict[str, str] = {
    "INR": "₹",
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "AED": "د.إ",
}


def currency_symbol(code: str | None) -> str:
    """Return a display symbol for an ISO currency code."""
    return CURRENCY_SYMBOLS.get((code or "").upper(), "₹")


def ensure_data_dirs() -> None:
    """Create runtime data directories if they do not exist."""
    for directory in (DATA_DIR, UPLOAD_DIR, EXPORT_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def llm_configured() -> bool:
    """True when an API key is present in the environment."""
    return bool(LLM_API_KEY.strip())


def smtp_configured() -> bool:
    """True when enough SMTP settings exist to attempt delivery."""
    return bool(SMTP_HOST and SMTP_FROM)


def env_flag(name: str, default: bool = False) -> bool:
    """Parse a boolean environment variable."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _streamlit_secret_flag(name: str) -> bool:
    """Read a boolean from Streamlit secrets, when running inside Streamlit."""
    try:
        from streamlit.runtime import exists as runtime_exists

        if not runtime_exists():
            return False
        import streamlit as st

        value = st.secrets.get(name)
    except Exception:
        return False
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


# Public-demo mode: auto-loads samples and disables bulk deletion.
# Enable with LIFEPILOT_DEMO_MODE=true (env) or the same key in Streamlit secrets.
DEMO_MODE: bool = env_flag("LIFEPILOT_DEMO_MODE", False) or _streamlit_secret_flag(
    "LIFEPILOT_DEMO_MODE"
)
