"""Application-wide configuration.

Every deployment-specific value is read from (in order):

1. an environment variable,
2. a Streamlit secret with the same name,
3. the default below.

That order means a local ``.env`` file keeps working, while a hosted app can be
configured entirely from **Streamlit Cloud -> App settings -> Secrets** without
committing anything to the repository.
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


def _secret_value(name: str) -> str | None:
    """Read ``name`` from Streamlit secrets when running inside Streamlit."""
    try:
        from streamlit.runtime import exists as runtime_exists

        if not runtime_exists():
            return None
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:  # no secrets file, or not running under Streamlit
        return None
    return None


def get_setting(name: str, default: str = "") -> str:
    """Return a setting from the environment, then Streamlit secrets."""
    raw = os.getenv(name)
    if raw is not None and raw.strip() != "":
        return raw
    secret = _secret_value(name)
    if secret is not None and secret.strip() != "":
        return secret
    return default


def get_int(name: str, default: int) -> int:
    try:
        return int(float(get_setting(name, str(default))))
    except (TypeError, ValueError):
        return default


def as_bool(raw: str | None, default: bool = False) -> bool:
    """Parse common truthy spellings, falling back to ``default``."""
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def env_flag(name: str, default: bool = False) -> bool:
    """Boolean setting from the environment or Streamlit secrets."""
    return as_bool(get_setting(name, ""), default)


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
DATA_DIR: Path = Path(get_setting("LIFEPILOT_DATA_DIR", str(BASE_DIR / "data")))
UPLOAD_DIR: Path = DATA_DIR / "uploads"
EXPORT_DIR: Path = DATA_DIR / "exports"
SAMPLE_DIR: Path = BASE_DIR / "tests" / "sample_documents"

# Optional explicit paths for the OCR binaries. On Windows the usual install
# locations are detected automatically; on Linux (Streamlit Cloud) both tools
# are installed system-wide by packages.txt and found on PATH.
def _first_existing(candidates: list[str]) -> str:
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return ""


def _default_tesseract_cmd() -> str:
    if os.name != "nt":
        return ""
    return _first_existing(
        [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            str(Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "Tesseract-OCR" / "tesseract.exe"),
        ]
    )


def _default_poppler_path() -> str:
    if os.name != "nt":
        return ""
    winget_root = Path(os.getenv("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if not winget_root.exists():
        return ""
    matches = [
        str(path.parent)
        for path in winget_root.glob("oschwartz10612.Poppler*/**/pdftoppm.exe")
    ]
    return matches[0] if matches else ""


TESSERACT_CMD: str = get_setting("LIFEPILOT_TESSERACT_CMD", _default_tesseract_cmd())
POPPLER_PATH: str = get_setting("LIFEPILOT_POPPLER_PATH", _default_poppler_path())

DATABASE_URL: str = get_setting(
    "LIFEPILOT_DB_URL", f"sqlite:///{(DATA_DIR / 'lifepilot.db').as_posix()}"
)

# ---------------------------------------------------------------------------
# Extraction / review
# ---------------------------------------------------------------------------
NEEDS_REVIEW_THRESHOLD: float = 0.60
DEFAULT_REMIND_DAYS: int = 7
DEFAULT_CURRENCY: str = "INR"
MAX_UPLOAD_MB: int = get_int("LIFEPILOT_MAX_UPLOAD_MB", 25)

# ---------------------------------------------------------------------------
# LLM fallback (optional -- the app is fully functional without it)
# ---------------------------------------------------------------------------
LLM_API_KEY: str = get_setting("LIFEPILOT_LLM_API_KEY", "")
LLM_BASE_URL: str = get_setting(
    "LIFEPILOT_LLM_BASE_URL", "https://api.openai.com/v1"
)
LLM_MODEL: str = get_setting("LIFEPILOT_LLM_MODEL", "gpt-4o-mini")
LLM_TIMEOUT: int = get_int("LIFEPILOT_LLM_TIMEOUT", 45)

# ---------------------------------------------------------------------------
# Email (optional)
# ---------------------------------------------------------------------------
SMTP_HOST: str = get_setting("LIFEPILOT_SMTP_HOST", "")
SMTP_PORT: int = get_int("LIFEPILOT_SMTP_PORT", 587)
SMTP_USER: str = get_setting("LIFEPILOT_SMTP_USER", "")
SMTP_PASSWORD: str = get_setting("LIFEPILOT_SMTP_PASSWORD", "")
SMTP_FROM: str = get_setting("LIFEPILOT_SMTP_FROM", SMTP_USER)
# STARTTLS on 587 (Gmail, Outlook, most providers). Set the SSL flag instead
# for providers that only offer implicit TLS on port 465.
SMTP_USE_TLS: bool = env_flag("LIFEPILOT_SMTP_USE_TLS", True)
SMTP_USE_SSL: bool = env_flag("LIFEPILOT_SMTP_USE_SSL", False)
SMTP_TIMEOUT: int = get_int("LIFEPILOT_SMTP_TIMEOUT", 20)
# Default recipient, useful for a hosted demo where visitors should not be
# able to type arbitrary addresses into a shared mailbox.
EMAIL_TO: str = get_setting("LIFEPILOT_EMAIL_TO", "")
# Start with reminder emails enabled (used by fresh hosted deployments where
# the SQLite file is recreated on restart).
EMAIL_ENABLED: bool = env_flag("LIFEPILOT_EMAIL_ENABLED", False)

# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
REMINDER_CHECK_HOURS: int = get_int("LIFEPILOT_REMINDER_CHECK_HOURS", 6)

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
    """True when an API key is present in the environment or secrets."""
    return bool(LLM_API_KEY.strip())


def smtp_configured() -> bool:
    """True when enough SMTP settings exist to attempt delivery."""
    if not (SMTP_HOST and SMTP_FROM):
        return False
    # A username without a password is a misconfiguration we can detect early.
    if SMTP_USER and not SMTP_PASSWORD:
        return False
    return True


def smtp_missing_settings() -> list[str]:
    """Human-readable list of the SMTP keys that still need a value."""
    missing: list[str] = []
    if not SMTP_HOST:
        missing.append("LIFEPILOT_SMTP_HOST")
    if not SMTP_USER:
        missing.append("LIFEPILOT_SMTP_USER")
    if not SMTP_PASSWORD:
        missing.append("LIFEPILOT_SMTP_PASSWORD")
    if not SMTP_FROM:
        missing.append("LIFEPILOT_SMTP_FROM")
    return missing


# Public-demo mode: auto-loads samples and disables destructive actions.
# Enable with LIFEPILOT_DEMO_MODE=true (env) or the same key in Streamlit secrets.
DEMO_MODE: bool = env_flag("LIFEPILOT_DEMO_MODE", False)
