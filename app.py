"""LifePilot - Streamlit entry point.

Run from the repository root:

    streamlit run lifepilot/app.py
"""

from __future__ import annotations

import html
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
for _path in (PROJECT_ROOT, PACKAGE_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

try:  # normal case: the project folder is importable as the ``lifepilot`` package
    import lifepilot  # noqa: F401
except ModuleNotFoundError:  # e.g. deployed repo folder is named something else
    import importlib.util

    _spec = importlib.util.spec_from_file_location(
        "lifepilot",
        PACKAGE_DIR / "__init__.py",
        submodule_search_locations=[str(PACKAGE_DIR)],
    )
    if _spec and _spec.loader:
        _module = importlib.util.module_from_spec(_spec)
        sys.modules["lifepilot"] = _module
        _spec.loader.exec_module(_module)

import pandas as pd
import plotly.express as px
import streamlit as st

from lifepilot import config
from lifepilot import notifications as mail
from lifepilot.db import crud
from lifepilot.db.database import init_db, session_scope
from lifepilot.exports.calendar import build_calendar, build_document_calendar
from lifepilot.pipeline import llm_fallback
from lifepilot.pipeline.ocr import ocr_available
from lifepilot.pipeline.processor import process_document, save_upload
from lifepilot.pipeline.tasks import EXPECTED_FIELDS
from lifepilot.scheduler import check_reminders, scheduler_status, start_scheduler
from lifepilot.seed import seed_demo_documents
from lifepilot.utils import fmt_date, format_amount, parse_amount

# ---------------------------------------------------------------------------
# Page configuration & theme
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="LifePilot · Document to action",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)

PALETTE = [
    "#5B5BD6", "#8B5CF6", "#06B6D4", "#F59E0B", "#10B981",
    "#EF4444", "#EC4899", "#84CC16", "#64748B", "#F97316",
]
DOC_ICONS = {
    "bill": "🧾",
    "receipt": "🧾",
    "warranty": "🛡️",
    "agreement": "📜",
    "certificate": "🎓",
    "application": "📝",
    "other": "📎",
}
DOC_LABELS = {
    "bill": "Bill",
    "receipt": "Receipt",
    "warranty": "Warranty",
    "agreement": "Agreement",
    "certificate": "Certificate",
    "application": "Application",
    "other": "Document",
}
DATE_FIELDS = {
    "due_date", "purchase_date", "invoice_date", "expiry_date", "renewal_date",
    "start_date", "end_date", "issue_date", "submission_date", "dob",
    "agreement_date",
}
MONEY_FIELDS = {"amount_total", "rent_amount", "deposit_amount", "purchase_price"}
GENERIC_FIELDS = {"named_person", "named_org", "date_mention", "money_mention"}

FIELD_LABELS: dict[str, str] = {}
for _type, _fields in EXPECTED_FIELDS.items():
    for _field in _fields:
        FIELD_LABELS[_field.name] = _field.label
FIELD_LABELS.update(
    {
        "invoice_date": "Bill / invoice date",
        "issue_date": "Issue date",
        "purchase_date": "Purchase date",
        "purchase_price": "Purchase price",
        "product": "Product",
        "vendor": "Vendor / provider",
        "amount_total": "Total amount",
        "currency": "Currency",
        "category": "Spending category",
        "warranty_period": "Warranty period",
        "notice_period": "Notice period",
        "property_address": "Property address",
        "agreement_date": "Agreement date",
        "required_document": "Required document",
        "named_person": "Named person",
        "named_org": "Named organisation",
        "invoice_number": "Invoice number",
        "receipt_number": "Receipt number",
        "warranty_number": "Warranty number",
        "application_number": "Application number",
        "certificate_number": "Certificate number",
        "policy_number": "Policy number",
        "account_number": "Account number",
        "agreement_number": "Agreement number",
        "deposit_amount": "Security deposit",
        "rent_amount": "Monthly rent",
        "landlord_name": "Landlord / lessor",
        "tenant_name": "Tenant / lessee",
        "holder_name": "Certificate holder",
        "applicant_name": "Applicant",
        "submission_date": "Submission deadline",
        "dob": "Date of birth",
        "issuer": "Issuing organisation",
    }
)

CSS = """
<style>
:root {
  --ink: #19192E;
  --muted: #6E6E8A;
  --primary: #5B5BD6;
  --primary-2: #8B5CF6;
  --bg: #F6F7FC;
  --card: #FFFFFF;
  --line: #E7E8F3;
  --green: #0E9F6E;
  --amber: #D97706;
  --red: #DC2626;
  --blue: #2563EB;
}
html, body, [class*="css"] {
  font-family: "Segoe UI", "Inter", -apple-system, BlinkMacSystemFont, sans-serif;
}
.stApp {
  background:
    radial-gradient(circle at 8% 0%, rgba(91,91,214,.10) 0, transparent 34%),
    radial-gradient(circle at 95% 12%, rgba(6,182,212,.08) 0, transparent 30%),
    #F6F7FC;
}
[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer { visibility: hidden; }
.block-container { padding-top: 1.4rem; padding-bottom: 3rem; max-width: 1280px; }
section[data-testid="stSidebar"] {
  background: #FFFFFF;
  border-right: 1px solid var(--line);
}
section[data-testid="stSidebar"] .block-container { padding-top: 1.2rem; }
section[data-testid="stSidebar"] div[role="radiogroup"] label {
  padding: .5rem .65rem;
  border-radius: 10px;
  transition: background .15s ease;
  font-weight: 500;
  color: #35354F;
}
section[data-testid="stSidebar"] div[role="radiogroup"] label:hover { background: #F0F0FB; }
div[data-testid="stVerticalBlockBorderWrapper"] {
  border: 1px solid var(--line) !important;
  border-radius: 16px !important;
  background: rgba(255,255,255,.92) !important;
  box-shadow: 0 2px 10px rgba(25,25,46,.03);
}
div[data-testid="stVerticalBlockBorderWrapper"]:hover {
  box-shadow: 0 6px 24px rgba(91,91,214,.08);
}
.stButton > button {
  border-radius: 10px;
  border: 1px solid var(--line);
  font-weight: 600;
  transition: all .15s ease;
}
.stButton > button[kind="primary"] {
  background: linear-gradient(120deg, #5B5BD6, #7C6CF6);
  border: none;
  color: white;
  box-shadow: 0 5px 16px rgba(91,91,214,.25);
}
.stButton > button[kind="primary"]:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 22px rgba(91,91,214,.32);
}
.stDownloadButton > button { border-radius: 10px; font-weight: 600; }
h1, h2, h3 { letter-spacing: -.02em; color: var(--ink); }
a { color: var(--primary); }
.lp-brand { display:flex; align-items:center; gap:.7rem; margin: .1rem 0 1.1rem 0; }
.lp-logo {
  width: 42px; height: 42px; border-radius: 13px;
  background: linear-gradient(135deg,#5B5BD6,#8B5CF6 60%,#06B6D4);
  color: white; font-weight: 800; font-size: 17px;
  display:flex; align-items:center; justify-content:center;
  box-shadow: 0 6px 16px rgba(91,91,214,.3);
}
.lp-brand-name { font-size: 1.22rem; font-weight: 800; color: var(--ink); line-height: 1.1; }
.lp-brand-tag { font-size: .72rem; color: var(--muted); letter-spacing: .02em; }
.lp-side-label {
  text-transform: uppercase; letter-spacing: .12em; font-size: .66rem;
  color: #9999B0; font-weight: 700; margin: 1rem 0 .25rem .2rem;
}
.lp-side-card {
  background: linear-gradient(135deg,#F4F2FF,#F8F7FF);
  border: 1px solid #E9E5FF; border-radius: 14px; padding: .8rem .9rem;
  font-size: .8rem; color: #55557A; margin-top: .6rem;
}
.lp-side-card strong { color: var(--ink); }
.lp-hero {
  position: relative; overflow: hidden;
  background: linear-gradient(120deg, #1E1E3F 0%, #3B3796 46%, #6D5BF0 100%);
  border-radius: 22px; padding: 2rem 2.2rem 1.8rem 2.2rem; color: white;
  box-shadow: 0 18px 50px rgba(45,40,120,.25);
  margin-bottom: 1.2rem;
}
.lp-hero:after {
  content:""; position:absolute; width: 320px; height: 320px; right: -80px; top: -140px;
  background: radial-gradient(circle, rgba(255,255,255,.22), transparent 65%);
  border-radius: 50%;
}
.lp-hero:before {
  content:""; position:absolute; width: 180px; height: 180px; right: 160px; bottom: -110px;
  background: radial-gradient(circle, rgba(6,182,212,.35), transparent 65%);
  border-radius: 50%;
}
.lp-eyebrow {
  display:inline-flex; align-items:center; gap:.4rem;
  font-size:.7rem; letter-spacing:.13em; text-transform:uppercase; font-weight:700;
  background: rgba(255,255,255,.13); border: 1px solid rgba(255,255,255,.2);
  border-radius: 999px; padding: .3rem .7rem; margin-bottom: .9rem;
}
.lp-hero h1 { color: #fff; font-size: 2.15rem; margin: 0 0 .45rem 0; line-height: 1.12; }
.lp-hero p { color: rgba(255,255,255,.78); font-size: .98rem; max-width: 720px; margin: 0; }
.lp-hero .lp-hero-meta { color: rgba(255,255,255,.6); font-size: .8rem; margin-top: .9rem; }
.lp-page-head { display:flex; justify-content: space-between; align-items: flex-end; margin: .2rem 0 1.1rem 0; gap: 1rem;}
.lp-page-head h1 { font-size: 1.8rem; margin: 0; }
.lp-page-head p { color: var(--muted); margin: .25rem 0 0 0; font-size: .92rem; }
.lp-metric {
  background: #fff; border: 1px solid var(--line); border-radius: 16px;
  padding: 1rem 1.05rem; min-height: 112px;
  box-shadow: 0 2px 10px rgba(25,25,46,.03);
}
.lp-metric-top { display:flex; align-items:center; gap:.5rem; color:#777791; font-size:.78rem; font-weight:600; }
.lp-metric-icon {
  width: 28px; height: 28px; border-radius: 9px; display:flex; align-items:center; justify-content:center;
  background:#F1F0FF; font-size:.9rem;
}
.lp-metric-value { font-size: 1.75rem; font-weight: 800; color: var(--ink); line-height: 1.15; margin-top: .45rem; }
.lp-metric-sub { font-size: .73rem; color: var(--muted); margin-top: .15rem; }
.lp-metric.warn .lp-metric-icon { background: #FFF6E6; }
.lp-metric.danger .lp-metric-value { color: var(--red); }
.lp-metric.good .lp-metric-value { color: var(--green); }
.lp-badge {
  display:inline-block; font-size:.68rem; font-weight:700; padding:.18rem .5rem;
  border-radius:999px; letter-spacing:.01em; white-space: nowrap;
}
.lp-badge.high { background:#E7F8F0; color:#067A55; }
.lp-badge.medium { background:#FFF4DC; color:#A15C03; }
.lp-badge.low { background:#FEE8E8; color:#B91C1C; }
.lp-badge.neutral { background:#F0F1F8; color:#5E5E7A; }
.lp-badge.info { background:#EAEDFF; color:#4040A8; }
.lp-badge.confirmed { background:#E6F4FF; color:#1D4ED8; }
.lp-banner {
  display:flex; gap: .9rem; align-items:flex-start;
  background: linear-gradient(110deg,#FFF9ED,#FFF4E0);
  border: 1px solid #F7D9A5; border-left: 5px solid #F59E0B;
  border-radius: 14px; padding: .9rem 1.1rem; margin: .2rem 0 1rem 0;
}
.lp-banner.calm { background: linear-gradient(110deg,#F1FBF6,#EAF9F2); border-color:#BCEBD7; border-left-color:#10B981; }
.lp-banner .b-icon { font-size:1.2rem; }
.lp-banner .b-title { font-weight:700; color:#3B2E12; font-size:.9rem; }
.lp-banner .b-sub { color:#7A6845; font-size:.8rem; margin-top:.1rem; }
.lp-deadline {
  border:1px solid var(--line); border-radius:14px; background:#fff;
  padding:.75rem .85rem; margin-bottom:.55rem; display:flex; gap:.8rem; align-items:center;
  border-left: 4px solid #C7C8DD;
}
.lp-deadline.overdue { border-left-color: #EF4444; background: #FFFBFB; }
.lp-deadline.soon { border-left-color: #F59E0B; background: #FFFCF5; }
.lp-deadline.later { border-left-color: #10B981; }
.lp-date-box {
  min-width: 46px; text-align:center; border-radius: 10px; background:#F4F4FB;
  padding:.3rem .25rem; color:#35355A;
}
.lp-date-box .d { display:block; font-size: 1.05rem; font-weight:800; line-height:1; }
.lp-date-box .m { display:block; font-size:.6rem; text-transform:uppercase; letter-spacing:.08em; color:#777791; margin-top:.2rem;}
.lp-deadline .dt { font-weight:700; font-size:.87rem; color:var(--ink); }
.lp-deadline .ds { font-size:.73rem; color:var(--muted); margin-top:.12rem; }
.lp-task {
  display:flex; gap:.65rem; align-items:flex-start; padding:.6rem 0;
  border-bottom:1px solid #F0F0F7;
}
.lp-task:last-child { border-bottom:none; }
.lp-task .tt { font-weight:600; font-size:.86rem; color:var(--ink); line-height:1.35; }
.lp-task .tm { font-size:.72rem; color:var(--muted); margin-top:.15rem; }
.lp-doc-row { display:flex; align-items:center; gap:.8rem; }
.lp-doc-icon {
  width: 44px; height: 44px; border-radius: 12px; background:#F2F1FF;
  display:flex; align-items:center; justify-content:center; font-size:1.25rem; flex-shrink:0;
}
.lp-doc-name { font-weight:700; color:var(--ink); font-size:.9rem; word-break: break-word; }
.lp-doc-meta { color:var(--muted); font-size:.73rem; margin-top:.12rem; }
.lp-field {
  border:1px solid var(--line); border-radius:13px; background:#fff; padding:.65rem .8rem;
  margin-bottom:.45rem;
}
.lp-field.needs { border-color:#F3C6C6; background:#FFFBFB; }
.lp-field-top { display:flex; justify-content:space-between; gap:.6rem; align-items:center; }
.lp-field-label { color:#777791; font-size:.68rem; font-weight:700; letter-spacing:.07em; text-transform:uppercase; }
.lp-field-value { font-weight:650; color:var(--ink); font-size:.9rem; margin-top:.18rem; word-break:break-word; }
.lp-field-source { color:#9A9AB2; font-size:.68rem; margin-top:.18rem; }
.lp-doc-head {
  display:flex; align-items:center; gap:1rem; background:#fff; border:1px solid var(--line);
  border-radius:18px; padding:1rem 1.15rem; margin-bottom:1rem;
}
.lp-doc-head .icon {
  width:54px; height:54px; border-radius:15px; background:linear-gradient(135deg,#F0EEFF,#E7F7FF);
  display:flex; align-items:center; justify-content:center; font-size:1.6rem;
}
.lp-doc-head h2 { margin:0; font-size:1.3rem; }
.lp-doc-head .sub { color:var(--muted); font-size:.78rem; margin-top:.2rem; }
.lp-empty {
  text-align:center; background:#fff; border:1px dashed #D8D8EA; border-radius:18px;
  padding: 2.4rem 1.2rem; margin: .5rem 0 1rem 0;
}
.lp-empty .e-icon { font-size:2.2rem; }
.lp-empty h3 { margin:.5rem 0 .25rem 0; }
.lp-empty p { color:var(--muted); max-width:520px; margin: .2rem auto 1rem auto; font-size:.88rem; }
.lp-feature {
  background:#fff; border:1px solid var(--line); border-radius:15px; padding:1rem;
  height:100%;
}
.lp-feature .f-icon { font-size:1.25rem; }
.lp-feature strong { display:block; margin:.45rem 0 .2rem 0; font-size:.88rem; }
.lp-feature span { color:var(--muted); font-size:.77rem; line-height:1.45; }
.lp-divider { height:1px; background:var(--line); margin:1rem 0; }
.lp-strip {
  display:flex; gap:.45rem; flex-wrap:wrap; align-items:center;
}
.lp-kv { display:flex; justify-content:space-between; gap:1rem; padding:.38rem 0; border-bottom:1px solid #F2F2F8; font-size:.8rem;}
.lp-kv:last-child { border-bottom:none; }
.lp-kv .k { color:var(--muted); }
.lp-kv .v { color:var(--ink); font-weight:600; text-align:right; word-break:break-word; }
.lp-source {
  font-family: "Cascadia Code", "Consolas", monospace; font-size:.72rem;
  background:#F8F8FD; border:1px solid #ECECF6; border-radius:10px; padding:.6rem .7rem;
  color:#4A4A66; white-space:pre-wrap;
}
.lp-note { color:var(--muted); font-size:.76rem; line-height:1.5; }
.lp-strong { color:var(--ink); font-weight:700; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def bootstrap() -> bool:
    config.ensure_data_dirs()
    init_db()
    start_scheduler()
    try:
        with session_scope() as session:
            # A fresh public deployment starts with the bundled samples so
            # visitors immediately see a populated dashboard.
            if config.DEMO_MODE and not crud.list_documents(session, limit=1):
                seed_demo_documents(session)
            check_reminders(session)
    except Exception:
        pass
    return True


bootstrap()

NAV_ITEMS = [
    ("🏠", "Dashboard"),
    ("📤", "Upload"),
    ("🗂️", "Documents"),
    ("⏰", "Reminders"),
    ("📊", "Spending"),
    ("⚙️", "Settings"),
]
LABEL_BY_PAGE = {page: f"{icon}  {page}" for icon, page in NAV_ITEMS}
PAGE_BY_LABEL = {label: page for page, label in LABEL_BY_PAGE.items()}

st.session_state.setdefault("nav_label", LABEL_BY_PAGE["Dashboard"])
st.session_state.setdefault("selected_doc", None)
st.session_state.setdefault("upload_results", [])


def goto(page: str, document_id: int | None = None) -> None:
    # A widget's session-state value cannot be changed after the widget has been
    # rendered, so navigation is deferred to the top of the next script run.
    st.session_state["_pending_page"] = page
    if document_id is not None:
        st.session_state["selected_doc"] = document_id
    if page == "Documents" and document_id is None:
        st.session_state["selected_doc"] = None
    st.rerun()


def flash(message: str, kind: str = "success") -> None:
    st.session_state["flash_message"] = (kind, message)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def confidence_badge(confidence: float, confirmed: bool = False) -> str:
    if confirmed:
        return '<span class="lp-badge confirmed">✓ Confirmed</span>'
    if confidence >= 0.85:
        return f'<span class="lp-badge high">High · {confidence:.0%}</span>'
    if confidence >= config.NEEDS_REVIEW_THRESHOLD:
        return f'<span class="lp-badge medium">Medium · {confidence:.0%}</span>'
    return f'<span class="lp-badge low">Needs review · {confidence:.0%}</span>'


def type_badge(doc_type: str | None) -> str:
    doc_type = doc_type or "other"
    return f'<span class="lp-badge info">{DOC_ICONS.get(doc_type, "📎")} {DOC_LABELS.get(doc_type, "Document")}</span>'


def status_badge(status: str | None) -> str:
    status = status or "uploaded"
    css = {"processed": "high", "failed": "low", "processing": "medium"}.get(status, "neutral")
    return f'<span class="lp-badge {css}">{status.title()}</span>'


def priority_badge(priority: str) -> str:
    css = {"high": "low", "medium": "medium", "low": "neutral"}.get(priority, "neutral")
    return f'<span class="lp-badge {css}">{priority.title()}</span>'


def deadline_state(due: date) -> tuple[str, str]:
    days = (due - date.today()).days
    if days < 0:
        return "overdue", f"Overdue {-days}d"
    if days == 0:
        return "soon", "Today"
    if days <= 7:
        return "soon", f"{days}d left"
    return "later", f"{days}d left"


def metric_card(
    column: Any, label: str, value: Any, sub: str, icon: str, tone: str = ""
) -> None:
    column.markdown(
        f"""
        <div class="lp-metric {tone}">
          <div class="lp-metric-top"><span class="lp-metric-icon">{icon}</span>{esc(label)}</div>
          <div class="lp-metric-value">{esc(value)}</div>
          <div class="lp-metric-sub">{esc(sub)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def page_header(title: str, subtitle: str, actions: Iterable[Any] = ()) -> None:
    st.markdown(
        f'<div class="lp-page-head"><div><h1>{esc(title)}</h1><p>{esc(subtitle)}</p></div></div>',
        unsafe_allow_html=True,
    )


def field_display(entity: dict, currency: str) -> str:
    value = entity["value"]
    name = entity["field_name"]
    if name in DATE_FIELDS:
        try:
            return fmt_date(date.fromisoformat(value[:10]))
        except ValueError:
            return value
    if name in MONEY_FIELDS or entity.get("value_type") == "money":
        amount = parse_amount(value)
        if amount is not None:
            return format_amount(amount, currency)
    return value


# ---------------------------------------------------------------------------
# Data loading (plain dicts keep sessions short and Streamlit-safe)
# ---------------------------------------------------------------------------
def deadline_dict(deadline: Any) -> dict:
    return {
        "id": deadline.id,
        "title": deadline.title,
        "due_date": deadline.due_date,
        "kind": deadline.kind,
        "confidence": deadline.confidence,
        "remind_days_before": deadline.remind_days_before,
        "status": deadline.status,
        "source_text": deadline.source_text or "",
        "document_id": deadline.document_id,
        "document": deadline.document.filename if deadline.document else "",
    }


def task_dict(task: Any) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description or "",
        "due_date": task.due_date,
        "priority": task.priority,
        "category": task.category,
        "status": task.status,
        "document_id": task.document_id,
        "document": task.document.filename if task.document else "",
    }


def notification_dict(item: Any) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "message": item.message,
        "kind": item.kind,
        "read": item.read,
        "created_at": item.created_at,
        "document_id": item.document_id,
    }


def entity_dict(entity: Any) -> dict:
    return {
        "id": entity.id,
        "field_name": entity.field_name,
        "value": entity.value,
        "value_type": entity.value_type,
        "confidence": entity.confidence,
        "source": entity.source,
        "confirmed": entity.confirmed,
        "needs_review": entity.needs_review,
        "position_ratio": entity.position_ratio or 0.0,
    }


def load_dashboard() -> dict:
    with session_scope() as session:
        counts = crud.dashboard_counts(session)
        deadlines = [deadline_dict(item) for item in crud.upcoming_deadlines(session, limit=10)]
        tasks = [task_dict(item) for item in crud.list_tasks(session, limit=9)]
        notifications = [
            notification_dict(item)
            for item in crud.list_notifications(session, unread_only=True, limit=8)
        ]
        documents = [
            {
                "id": document.id,
                "filename": document.filename,
                "doc_type": document.doc_type,
                "status": document.status,
                "uploaded_at": document.uploaded_at,
            }
            for document in crud.list_documents(session, limit=5)
        ]
        settings = crud.get_settings(session)
        currency = settings.currency or config.DEFAULT_CURRENCY
        return {
            "counts": counts,
            "deadlines": deadlines,
            "tasks": tasks,
            "notifications": notifications,
            "documents": documents,
            "currency": currency,
        }


def load_documents() -> list[dict]:
    with session_scope() as session:
        rows: list[dict] = []
        for document in crud.list_documents(session, limit=500):
            rows.append(
                {
                    "id": document.id,
                    "filename": document.filename,
                    "doc_type": document.doc_type,
                    "status": document.status,
                    "uploaded_at": document.uploaded_at,
                    "processed_at": document.processed_at,
                    "doc_type_confidence": document.doc_type_confidence,
                    "fields": len(document.entities),
                    "tasks": len(crud.list_tasks(session, document_id=document.id, limit=500)),
                    "deadlines": len(
                        crud.upcoming_deadlines(session, document_id=document.id, limit=500)
                    ),
                    "missing": crud.unresolved_missing_count(session, document.id),
                }
            )
        return rows


def load_document_detail(document_id: int) -> dict | None:
    with session_scope() as session:
        document = crud.get_document(session, document_id)
        if document is None:
            return None
        entities = [entity_dict(item) for item in crud.get_entities(session, document.id)]
        deadlines = [
            deadline_dict(item)
            for item in crud.upcoming_deadlines(
                session, document_id=document.id, include_overdue=True, limit=500
            )
        ]
        tasks = [
            task_dict(item)
            for item in crud.list_tasks(
                session, document_id=document.id, include_done=True, limit=500
            )
        ]
        missing = [
            {
                "id": item.id,
                "field_name": item.field_name,
                "description": item.description,
                "severity": item.severity,
                "resolved": item.resolved,
            }
            for item in crud.list_missing_info(session, document.id, include_resolved=True)
        ]
        settings = crud.get_settings(session)
        return {
            "id": document.id,
            "filename": document.filename,
            "stored_path": document.stored_path,
            "doc_type": document.doc_type,
            "doc_type_confidence": document.doc_type_confidence,
            "status": document.status,
            "raw_text": document.raw_text or "",
            "extraction_method": document.extraction_method,
            "uploaded_at": document.uploaded_at,
            "processed_at": document.processed_at,
            "error_message": document.error_message,
            "entities": entities,
            "deadlines": deadlines,
            "tasks": tasks,
            "missing": missing,
            "currency": settings.currency or config.DEFAULT_CURRENCY,
        }


def load_expenses() -> list[dict]:
    with session_scope() as session:
        return crud.spending_records(session)


def load_notifications(include_read: bool = True) -> list[dict]:
    with session_scope() as session:
        return [
            notification_dict(item)
            for item in crud.list_notifications(session, unread_only=not include_read, limit=100)
        ]


def load_email_log(limit: int = 15) -> list[dict]:
    with session_scope() as session:
        return [
            {
                "id": item.id,
                "to": item.to_address,
                "subject": item.subject,
                "body": item.body,
                "status": item.status,
                "detail": item.detail or "",
                "created_at": item.created_at,
            }
            for item in crud.list_email_log(session, limit=limit)
        ]


# ---------------------------------------------------------------------------
# Shared actions
# ---------------------------------------------------------------------------
def mark_task_done(task_id: int, done: bool = True) -> None:
    with session_scope() as session:
        crud.set_task_done(session, task_id, done)
    flash("Task marked as done." if done else "Task reopened.")
    st.rerun()


def mark_notification_read(notification_id: int) -> None:
    with session_scope() as session:
        crud.mark_notification_read(session, notification_id)
    st.rerun()


def load_samples() -> None:
    with st.status("Processing sample documents…", expanded=True) as status:
        status.write("Reading electricity bill…")
        with session_scope() as session:
            created = seed_demo_documents(session)
            status.write("Building deadlines and reminders…")
            check_reminders(session, email_fn=lambda _n, _t: (False, "demo"))
        status.update(
            label=f"Loaded {len(created)} sample document(s)" if created else "Samples already loaded",
            state="complete",
        )
    flash(
        f"Loaded {len(created)} sample document(s). Explore the dashboard."
        if created
        else "Sample documents are already in your library.",
        "success",
    )
    st.rerun()


def delete_all_documents() -> None:
    if config.DEMO_MODE:
        flash("Bulk delete is disabled in the public demo.", "warning")
        st.rerun()
        return
    paths: list[str] = []
    with session_scope() as session:
        for document in crud.list_documents(session, limit=5000):
            paths.append(document.stored_path)
            crud.delete_document(session, document.id)
    for path in paths:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass
    st.session_state["selected_doc"] = None
    flash("All documents and extracted data were removed.", "warning")
    st.rerun()


def reset_demo_data() -> None:
    """Restore the four bundled samples (public demo only)."""
    paths: list[str] = []
    with session_scope() as session:
        for document in crud.list_documents(session, limit=5000):
            paths.append(document.stored_path)
            crud.delete_document(session, document.id)
        created = seed_demo_documents(session)
        check_reminders(session, email_fn=lambda _n, _t: (False, "demo"))
    for path in paths:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass
    st.session_state["selected_doc"] = None
    st.session_state["upload_results"] = []
    flash(f"Demo reset · {len(created)} sample document(s) reloaded.")
    st.rerun()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
def render_sidebar() -> str:
    pending = st.session_state.pop("_pending_page", None)
    if pending in LABEL_BY_PAGE:
        st.session_state["nav_label"] = LABEL_BY_PAGE[pending]
    with st.sidebar:
        st.markdown(
            """
            <div class="lp-brand">
              <div class="lp-logo">LP</div>
              <div>
                <div class="lp-brand-name">LifePilot</div>
                <div class="lp-brand-tag">Paperwork → plan</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.radio(
            "Navigation",
            list(PAGE_BY_LABEL.keys()),
            key="nav_label",
            label_visibility="collapsed",
        )
        st.markdown('<div class="lp-divider"></div>', unsafe_allow_html=True)

        unread = load_notifications(include_read=False)
        if unread:
            with st.expander(f"🔔 {len(unread)} unread reminder(s)", expanded=False):
                for item in unread[:5]:
                    st.markdown(f"**{esc(item['title'])}**")
                    st.caption(item["message"][:160])
                    if st.button("Mark read", key=f"side_read_{item['id']}"):
                        mark_notification_read(item["id"])
        else:
            st.caption("🔔 No unread reminders")

        scheduler = scheduler_status()
        st.markdown(
            f"""
            <div class="lp-side-card">
              <strong>System status</strong><br/>
              OCR: {"ready" if ocr_available() else "Tesseract not found"}<br/>
              AI assist: {"available" if config.llm_configured() else "not configured"}<br/>
              Email: {"ready" if mail.email_configured() else "off"}<br/>
              Reminders: {"running" if scheduler["running"] else "paused"}{"<br/>Mode: public demo" if config.DEMO_MODE else ""}
            </div>
            """,
            unsafe_allow_html=True,
        )
        if config.DEMO_MODE:
            st.markdown(
                '<p class="lp-note" style="margin-top:.8rem">Public demo: try the sample documents. '
                "Don't upload personal files — the shared database resets when the app restarts.</p>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<p class="lp-note" style="margin-top:.8rem">Local-first. Your files stay on this machine unless you enable AI assist.</p>',
                unsafe_allow_html=True,
            )
        st.caption("LifePilot v1.0")

    return PAGE_BY_LABEL.get(st.session_state.get("nav_label"), "Dashboard")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def render_deadline_row(item: dict, *, compact: bool = False) -> None:
    due: date = item["due_date"]
    css, label = deadline_state(due)
    with st.container(border=True):
        cols = st.columns([1.0, 5.3, 1.9, 1.1], vertical_alignment="center")
        cols[0].markdown(
            f'<div class="lp-date-box"><span class="d">{due.day}</span>'
            f'<span class="m">{due.strftime("%b")}</span></div>',
            unsafe_allow_html=True,
        )
        cols[1].markdown(
            f'<div class="dt">{esc(item["title"])}</div>'
            f'<div class="ds">{esc(item.get("document", ""))}'
            f'{" · " + esc(item.get("kind", "").title()) if item.get("kind") else ""}</div>',
            unsafe_allow_html=True,
        )
        cols[2].markdown(
            f'<span class="lp-badge {"low" if css == "overdue" else "medium" if css == "soon" else "high"}">{label}</span>',
            unsafe_allow_html=True,
        )
        if cols[3].button("Open", key=f"deadline_open_{item['id']}_{compact}"):
            goto("Documents", item["document_id"])


def render_task_row(item: dict, key_prefix: str) -> None:
    cols = st.columns([0.4, 5.6, 1.4, 1.0], vertical_alignment="center")
    checked = cols[0].checkbox(
        f"Done: {item['title']}",
        key=f"{key_prefix}_task_{item['id']}",
        label_visibility="collapsed",
    )
    due = fmt_date(item["due_date"]) if item["due_date"] else "No due date"
    cols[1].markdown(
        f'<div class="tt">{esc(item["title"])}</div>'
        f'<div class="tm">{esc(item["document"])} · {esc(item["category"].title())} · {esc(due)}</div>',
        unsafe_allow_html=True,
    )
    cols[2].markdown(priority_badge(item["priority"]), unsafe_allow_html=True)
    if cols[3].button("Open", key=f"{key_prefix}_open_{item['id']}"):
        goto("Documents", item["document_id"])
    if checked:
        mark_task_done(item["id"], True)


def render_dashboard() -> None:
    data = load_dashboard()
    counts = data["counts"]
    today = date.today()
    greeting = "Good morning" if datetime.now().hour < 12 else "Good afternoon" if datetime.now().hour < 18 else "Good evening"

    st.markdown(
        f"""
        <div class="lp-hero">
          <div class="lp-eyebrow">✦ {greeting}</div>
          <h1>Your paperwork, on autopilot.</h1>
          <p>Upload a bill, warranty, agreement or form. LifePilot pulls out the details,
             turns them into deadlines and gives you one clear next step.</p>
          <div class="lp-hero-meta">{today.strftime("%A, %d %B %Y")} · {counts["documents"]} documents tracked</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if counts["documents"] == 0:
        render_empty_dashboard()
        return

    urgent = [
        item for item in data["deadlines"] if item["due_date"] <= today + timedelta(days=7)
    ]
    overdue = [item for item in urgent if item["due_date"] < today]
    if urgent:
        names = " · ".join(item["title"] for item in urgent[:3])
        st.markdown(
            f"""
            <div class="lp-banner">
              <div class="b-icon">⏰</div>
              <div>
                <div class="b-title">{len(urgent)} item{"s" if len(urgent) != 1 else ""} need attention
                  {"(" + str(len(overdue)) + " overdue)" if overdue else "this week"}</div>
                <div class="b-sub">{esc(names)}{"…" if len(urgent) > 3 else ""}</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="lp-banner calm"><div class="b-icon">✅</div><div>'
            '<div class="b-title">Nothing urgent this week</div>'
            '<div class="b-sub">Your upcoming deadlines are under control.</div></div></div>',
            unsafe_allow_html=True,
        )

    cols = st.columns(4)
    metric_card(cols[0], "Documents", counts["documents"], "in your library", "🗂️")
    metric_card(cols[1], "Open tasks", counts["open_tasks"], "ready to action", "⚡")
    metric_card(cols[2], "Due this week", counts["due_this_week"], f'{counts["overdue"]} overdue', "⏰", "warn")
    metric_card(
        cols[3], "Needs review", counts["needs_review"],
        "low-confidence fields", "🔍",
        "danger" if counts["needs_review"] else "good",
    )

    st.markdown("")
    left, right = st.columns([1.55, 1.0], gap="large")

    with left:
        st.markdown("### Upcoming deadlines")
        if data["deadlines"]:
            for item in data["deadlines"][:7]:
                render_deadline_row(item)
            if st.button("View all deadlines →", key="dashboard_all_deadlines"):
                goto("Reminders")
        else:
            st.info("No active deadlines yet. Upload a document with a due date.")

        st.markdown("### Open tasks")
        if data["tasks"]:
            for item in data["tasks"][:6]:
                render_task_row(item, "dash")
        else:
            st.success("All caught up — no open tasks.")

    with right:
        st.markdown("### Documents")
        if data["documents"]:
            for document in data["documents"]:
                with st.container(border=True):
                    cols = st.columns([0.7, 4.0, 1.2], vertical_alignment="center")
                    cols[0].markdown(
                        f'<div class="lp-doc-icon">{DOC_ICONS.get(document["doc_type"], "📎")}</div>',
                        unsafe_allow_html=True,
                    )
                    cols[1].markdown(
                        f'<div class="lp-doc-name">{esc(document["filename"])}</div>'
                        f'<div class="lp-doc-meta">{DOC_LABELS.get(document["doc_type"], "Processing")} · '
                        f'{fmt_date(document["uploaded_at"])}</div>',
                        unsafe_allow_html=True,
                    )
                    if cols[2].button("Open", key=f"dash_doc_{document['id']}"):
                        goto("Documents", document["id"])
        st.markdown("")
        if st.button("＋ Add a document", key="dash_upload", type="primary", width="stretch"):
            goto("Upload")

    st.markdown("")
    with st.expander("Why LifePilot?", expanded=False):
        f1, f2, f3, f4 = st.columns(4)
        for column, icon, title, text in [
            (f1, "🧠", "Understands", "Classifies bills, warranties, agreements, certificates and forms."),
            (f2, "🧾", "Extracts", "Dates, amounts, parties and reference numbers with confidence scores."),
            (f3, "⚡", "Acts", "Generates payment, renewal and renewal-reminder tasks automatically."),
            (f4, "🔒", "Stays local", "SQLite by default. AI assist is opt-in and never silent."),
        ]:
            column.markdown(
                f'<div class="lp-feature"><div class="f-icon">{icon}</div>'
                f"<strong>{title}</strong><span>{text}</span></div>",
                unsafe_allow_html=True,
            )


def render_empty_dashboard() -> None:
    st.markdown(
        """
        <div class="lp-empty">
          <div class="e-icon">📄 → ✅</div>
          <h3>Start with a document</h3>
          <p>Upload a bill, receipt, warranty, agreement, certificate or application form.
             LifePilot will extract the details and build your action plan.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    left, mid, right = st.columns([1, 1.2, 1])
    with mid:
        if st.button("✨ Load 4 sample documents", type="primary", width="stretch"):
            load_samples()
        if st.button("📤 Upload my own", width="stretch"):
            goto("Upload")
        st.caption("Samples: electricity bill · warranty card · rental agreement · application form")

    st.markdown("### What happens next")
    c1, c2, c3, c4 = st.columns(4)
    for column, icon, title, text in [
        (c1, "🔎", "Extract", "Text PDFs are read directly; scans fall back to OCR."),
        (c2, "🧩", "Structure", "Fields, dates, amounts and obligations are pulled into a clean database."),
        (c3, "🗓️", "Plan", "Tasks and deadlines are generated from document-specific rules."),
        (c4, "📤", "Export", "Download an .ics calendar or review everything in the dashboard."),
    ]:
        column.markdown(
            f'<div class="lp-feature"><div class="f-icon">{icon}</div>'
            f"<strong>{title}</strong><span>{text}</span></div>",
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------
def render_upload_results(results: list[dict]) -> None:
    if not results:
        return
    st.markdown("### Latest processing results")
    for result in results:
        if not result.get("ok"):
            with st.container(border=True):
                st.markdown(
                    f'<div class="lp-doc-row"><div class="lp-doc-icon">⚠️</div>'
                    f'<div><div class="lp-doc-name">{esc(result["filename"])}</div>'
                    f'<div class="lp-doc-meta">Could not process</div></div></div>',
                    unsafe_allow_html=True,
                )
                st.error(result.get("error") or "Processing failed.")
                for warning in result.get("warnings", []):
                    st.caption(warning)
            continue
        with st.container(border=True):
            cols = st.columns([0.8, 4.0, 2.5, 1.2], vertical_alignment="center")
            cols[0].markdown(
                f'<div class="lp-doc-icon">{DOC_ICONS.get(result["doc_type"], "📎")}</div>',
                unsafe_allow_html=True,
            )
            cols[1].markdown(
                f'<div class="lp-doc-name">{esc(result["filename"])}</div>'
                f'<div class="lp-doc-meta">{DOC_LABELS.get(result["doc_type"], "Document")} · '
                f'{result["entities"]} fields · {result["tasks"]} tasks · {result["deadlines"]} deadlines</div>',
                unsafe_allow_html=True,
            )
            cols[2].markdown(
                type_badge(result["doc_type"])
                + " "
                + confidence_badge(result["doc_type_confidence"]),
                unsafe_allow_html=True,
            )
            if cols[3].button("Open", key=f"upload_open_{result['document_id']}"):
                goto("Documents", result["document_id"])
            if result.get("missing"):
                st.warning(f'{result["missing"]} expected field(s) could not be found. Open the document to review.')
            for warning in result.get("warnings", []):
                st.caption(f"ℹ️ {warning}")
    st.markdown("")


def render_upload() -> None:
    page_header("Upload a document", "PDF, JPG or PNG · up to 25 MB · processed locally")
    st.markdown("")

    with session_scope() as session:
        settings = crud.get_settings(session)
        llm_on = settings.llm_enabled and config.llm_configured()
    if config.DEMO_MODE:
        st.warning(
            "This is a public demo. Use the bundled sample PDFs or an invented document — "
            "files are shared with other visitors and the database resets when the app restarts."
        )
    if llm_on:
        st.info("AI assist is enabled. It will only be called if a required field is missing or below 60% confidence.")
    else:
        st.caption("AI assist is off. Rule-based extraction works fully offline.")

    render_upload_results(st.session_state.get("upload_results", []))

    uploads = st.file_uploader(
        "Drop your documents here",
        type=["pdf", "png", "jpg", "jpeg"],
        accept_multiple_files=True,
        help="Text PDFs are parsed directly. Scans use Tesseract OCR when installed.",
    )

    if uploads:
        st.caption(f"{len(uploads)} file(s) selected")
        if st.button("Process documents", type="primary", width="stretch"):
            results: list[dict] = []
            progress = st.progress(0.0, text="Preparing…")
            status = st.status("Processing documents…", expanded=True)
            total = len(uploads)
            for index, upload in enumerate(uploads):
                progress.progress(index / max(total, 1), text=f"Reading {upload.name}…")
                text_status = f"{upload.name} ({index + 1}/{total})"
                status.update(label=f"Processing {text_status}", state="running")
                data = upload.getvalue()
                if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
                    results.append(
                        {
                            "ok": False,
                            "filename": upload.name,
                            "error": f"File exceeds the {config.MAX_UPLOAD_MB} MB limit.",
                            "warnings": [],
                        }
                    )
                    continue
                try:
                    with session_scope() as session:
                        document = save_upload(session, filename=upload.name, data=data)
                        result = process_document(session, document.id)
                    results.append(
                        {
                            "ok": result.ok,
                            "document_id": result.document_id,
                            "filename": upload.name,
                            "doc_type": result.doc_type,
                            "doc_type_confidence": result.doc_type_confidence,
                            "entities": result.entities,
                            "tasks": result.tasks,
                            "deadlines": result.deadlines,
                            "missing": result.missing,
                            "warnings": result.warnings,
                            "error": result.error,
                            "llm_used": result.llm_used,
                        }
                    )
                    status.write(f"✓ {upload.name}: {result.tasks} task(s), {result.deadlines} deadline(s)")
                except Exception as exc:  # keep the batch going
                    results.append(
                        {
                            "ok": False,
                            "filename": upload.name,
                            "error": f"Unexpected error: {exc}",
                            "warnings": [],
                        }
                    )
                    status.write(f"✗ {upload.name}: {exc}")
                progress.progress((index + 1) / total, text=f"Processed {upload.name}")
            with session_scope() as session:
                check_reminders(session)
            status.update(label="Processing complete", state="complete")
            st.session_state["upload_results"] = results
            succeeded = sum(1 for item in results if item.get("ok"))
            flash(f"Processed {succeeded} of {len(results)} document(s).")
            st.rerun()

    st.markdown("### How processing works")
    steps = st.columns(4)
    for column, number, title, text in [
        (steps[0], "1", "Read", "pdfplumber first, OCR fallback for scans."),
        (steps[1], "2", "Understand", "Rule-based type detection and entity extraction."),
        (steps[2], "3", "Score", "Every field gets a confidence score for review."),
        (steps[3], "4", "Plan", "Tasks, deadlines and reminders are generated."),
    ]:
        column.markdown(
            f'<div class="lp-feature"><div class="f-icon">{number}</div>'
            f"<strong>{title}</strong><span>{text}</span></div>",
            unsafe_allow_html=True,
        )
    st.caption("Privacy: files are stored in the local `data/uploads` folder. Nothing is sent to an LLM unless you enable AI assist in Settings.")


# ---------------------------------------------------------------------------
# Documents list & detail
# ---------------------------------------------------------------------------
def render_documents() -> None:
    if st.session_state.get("selected_doc"):
        render_document_detail(int(st.session_state["selected_doc"]))
        return

    page_header("Your documents", "Everything LifePilot has read, structured and planned")
    top = st.columns([3.0, 1.4, 1.1], vertical_alignment="bottom")
    search = top[0].text_input("Search documents", placeholder="Search by filename or vendor…", label_visibility="collapsed")
    type_filter = top[1].selectbox(
        "Type",
        ["All types"] + [DOC_LABELS[key] for key in DOC_LABELS],
        label_visibility="collapsed",
    )
    if top[2].button("＋ Upload", type="primary", width="stretch"):
        goto("Upload")

    documents = load_documents()
    if not documents:
        st.markdown(
            '<div class="lp-empty"><div class="e-icon">🗂️</div><h3>No documents yet</h3>'
            "<p>Upload your first document or load the bundled samples to see LifePilot in action.</p></div>",
            unsafe_allow_html=True,
        )
        c1, c2 = st.columns(2)
        if c1.button("✨ Load sample documents", width="stretch"):
            load_samples()
        if c2.button("📤 Upload a document", type="primary", width="stretch"):
            goto("Upload")
        return

    query = search.strip().lower()
    filtered = [
        document
        for document in documents
        if (not query or query in document["filename"].lower())
        and (
            type_filter == "All types"
            or DOC_LABELS.get(document["doc_type"], "Document") == type_filter
        )
    ]
    if not filtered:
        st.info("No documents match that filter.")
        return

    st.caption(f"{len(filtered)} document(s)")
    for document in filtered:
        with st.container(border=True):
            cols = st.columns([0.7, 4.1, 2.4, 1.8, 1.2], vertical_alignment="center")
            cols[0].markdown(
                f'<div class="lp-doc-icon">{DOC_ICONS.get(document["doc_type"], "📎")}</div>',
                unsafe_allow_html=True,
            )
            cols[1].markdown(
                f'<div class="lp-doc-name">{esc(document["filename"])}</div>'
                f'<div class="lp-doc-meta">Uploaded {fmt_date(document["uploaded_at"])}'
                f'{" · processed " + fmt_date(document["processed_at"]) if document["processed_at"] else ""}</div>',
                unsafe_allow_html=True,
            )
            cols[2].markdown(
                type_badge(document["doc_type"]) + " " + status_badge(document["status"]),
                unsafe_allow_html=True,
            )
            cols[3].markdown(
                f'<div class="lp-doc-meta">{document["fields"]} fields<br/>'
                f'{document["tasks"]} open tasks · {document["deadlines"]} deadlines'
                f'{" · " + str(document["missing"]) + " missing" if document["missing"] else ""}</div>',
                unsafe_allow_html=True,
            )
            if cols[4].button("Open", key=f"doc_open_{document['id']}", width="stretch"):
                goto("Documents", document["id"])


def render_document_detail(document_id: int) -> None:
    detail = load_document_detail(document_id)
    if detail is None:
        st.warning("That document no longer exists.")
        st.session_state["selected_doc"] = None
        if st.button("Back to documents"):
            goto("Documents")
        return

    if st.button("← Back to documents", key="detail_back"):
        st.session_state["selected_doc"] = None
        goto("Documents")

    doc_type = detail["doc_type"]
    unresolved = [item for item in detail["missing"] if not item["resolved"]]
    open_tasks = [item for item in detail["tasks"] if item["status"] == "open"]

    st.markdown(
        f"""
        <div class="lp-doc-head">
          <div class="icon">{DOC_ICONS.get(doc_type, "📎")}</div>
          <div style="flex:1">
            <h2>{esc(detail["filename"])}</h2>
            <div class="sub">{DOC_LABELS.get(doc_type, "Document")} · uploaded {fmt_date(detail["uploaded_at"])}
              {(" · processed " + fmt_date(detail["processed_at"])) if detail["processed_at"] else ""}
              · {esc(detail["extraction_method"] or "text")}</div>
          </div>
          <div class="lp-strip">{type_badge(doc_type)}{status_badge(detail["status"])}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if detail["status"] == "failed":
        st.error(detail["error_message"] or "Processing failed for this document.")

    action_cols = st.columns([1.5, 1.4, 1.4, 1.0, 3.7], vertical_alignment="center")
    if action_cols[0].button("↻ Reprocess", key="detail_reprocess", help="Re-run extraction. Manual edits will be replaced."):
        with st.spinner("Reprocessing…"):
            with session_scope() as session:
                process_document(session, document_id)
                check_reminders(session)
        flash("Document reprocessed.")
        st.rerun()

    if detail["deadlines"]:
        raw = build_document_calendar(
            detail["deadlines"], document_name=detail["filename"]
        )
        action_cols[1].download_button(
            "📅 Download .ics",
            data=raw,
            file_name=f"lifepilot_{document_id}.ics",
            mime="text/calendar",
            key="detail_ics",
        )
    if action_cols[2].button("🔔 Run reminder check", key="detail_check"):
        with session_scope() as session:
            run = check_reminders(session)
        flash(f"Reminder check complete · {run.created} new reminder(s).")
        st.rerun()

    if config.DEMO_MODE:
        action_cols[3].caption("Delete is disabled in the demo.")
    else:
        with action_cols[3].popover("Delete"):
            st.markdown("**Delete this document?**")
            st.caption("Extracted fields, tasks, deadlines and reminders will be removed.")
            if st.button("Yes, delete", key="delete_doc_confirm", type="primary"):
                path = detail["stored_path"]
                with session_scope() as session:
                    crud.delete_document(session, document_id)
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError:
                    pass
                st.session_state["selected_doc"] = None
                flash("Document deleted.", "warning")
                goto("Documents")

    metric_cols = st.columns(4)
    metric_card(metric_cols[0], "Extracted fields", len(detail["entities"]), "with confidence scores", "🧩")
    metric_card(metric_cols[1], "Open tasks", len(open_tasks), f'{len(detail["tasks"]) - len(open_tasks)} completed', "⚡")
    metric_card(metric_cols[2], "Deadlines", len(detail["deadlines"]), "active and exportable", "🗓️")
    metric_card(
        metric_cols[3], "Missing info", len(unresolved),
        "fields need attention" if unresolved else "nothing missing",
        "🚩", "warn" if unresolved else "good",
    )

    tabs = st.tabs(
        [
            f"Fields  ·  {len(detail['entities'])}",
            f"Actions  ·  {len(detail['deadlines'])} / {len(detail['tasks'])}",
            f"Missing info  ·  {len(unresolved)}",
            "Original text",
        ]
    )
    with tabs[0]:
        render_fields_tab(detail)
    with tabs[1]:
        render_actions_tab(detail)
    with tabs[2]:
        render_missing_tab(detail, unresolved)
    with tabs[3]:
        render_text_tab(detail)


def render_entity(entity: dict, detail: dict, *, index: int) -> None:
    name = entity["field_name"]
    label = FIELD_LABELS.get(name, name.replace("_", " ").title())
    needs = entity["confidence"] < config.NEEDS_REVIEW_THRESHOLD and not entity["confirmed"]
    source = entity["source"].replace("_", " ").title()
    value = field_display(entity, detail["currency"])
    st.markdown(
        f"""
        <div class="lp-field {'needs' if needs else ''}">
          <div class="lp-field-top">
            <span class="lp-field-label">{esc(label)}</span>
            {confidence_badge(entity["confidence"], entity["confirmed"])}
          </div>
          <div class="lp-field-value">{esc(value)}</div>
          <div class="lp-field-source">Source: {esc(source)} · {esc(entity["value_type"])}
            {" · needs a quick check" if needs else ""}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander("Edit / confirm value", expanded=needs):
        with st.form(f"entity_form_{entity['id']}_{index}"):
            new_value = st.text_input(
                "Value", value=entity["value"], key=f"entity_value_{entity['id']}_{index}"
            )
            submitted = st.form_submit_button("Save & confirm", type="primary")
        if submitted:
            with session_scope() as session:
                crud.confirm_entity(session, entity["id"], value=new_value)
            flash(f"{label} confirmed and set to 100% confidence.")
            st.rerun()


def render_fields_tab(detail: dict) -> None:
    entities = detail["entities"]
    if not entities:
        st.info("No fields were extracted. Check the original text or reprocess the document.")
        return

    expected_order = [
        item.name for item in EXPECTED_FIELDS.get(detail["doc_type"], ())
    ]
    priority, others = [], []
    seen: set[int] = set()
    for name in expected_order:
        for entity in entities:
            if entity["field_name"] == name:
                priority.append(entity)
                seen.add(entity["id"])
    for entity in entities:
        if entity["id"] not in seen:
            (others if entity["field_name"] in GENERIC_FIELDS else priority).append(entity)

    review_count = sum(
        1
        for item in entities
        if item["confidence"] < config.NEEDS_REVIEW_THRESHOLD and not item["confirmed"]
    )
    if review_count:
        st.markdown(
            f'<div class="lp-banner"><div class="b-icon">🔍</div><div>'
            f'<div class="b-title">{review_count} field(s) need a quick review</div>'
            '<div class="b-sub">Low-confidence values are highlighted below. Edit and confirm to set confidence to 100%.</div>'
            "</div></div>",
            unsafe_allow_html=True,
        )
    else:
        st.caption("All extracted fields are above the review threshold. You can still edit any value below.")

    for index, entity in enumerate(priority):
        render_entity(entity, detail, index=index)

    if others:
        with st.expander(f"Other extracted entities ({len(others)})", expanded=False):
            for index, entity in enumerate(others):
                render_entity(entity, detail, index=1000 + index)

    st.markdown("### Add or correct a field")
    with st.expander("Add a field that was not found", expanded=False):
        missing_names = [
            field_name
            for field_name in dict.fromkeys(
                [item.name for item in EXPECTED_FIELDS.get(detail["doc_type"], ())]
            )
            if not any(entity["field_name"] == field_name for entity in entities)
        ]
        options = missing_names or sorted(set(FIELD_LABELS))
        with st.form("add_field_form"):
            field_name = st.selectbox(
                "Field",
                options,
                format_func=lambda name: FIELD_LABELS.get(name, name.replace("_", " ").title()),
            )
            value = st.text_input("Value", placeholder="e.g. 15/12/2026 or Rs. 2,500")
            submitted = st.form_submit_button("Add & confirm", type="primary")
        if submitted and value.strip():
            value_type = (
                "date" if field_name in DATE_FIELDS else "money" if field_name in MONEY_FIELDS else "text"
            )
            with session_scope() as session:
                crud.upsert_entity(
                    session,
                    detail["id"],
                    field_name=field_name,
                    value=value.strip(),
                    value_type=value_type,
                )
            flash(f"{FIELD_LABELS.get(field_name, field_name)} added.")
            st.rerun()


def render_actions_tab(detail: dict) -> None:
    st.markdown("### Deadlines")
    if detail["deadlines"]:
        for item in detail["deadlines"]:
            due = item["due_date"]
            css, label = deadline_state(due)
            with st.container(border=True):
                cols = st.columns([1.0, 4.8, 1.7, 1.1], vertical_alignment="center")
                cols[0].markdown(
                    f'<div class="lp-date-box"><span class="d">{due.day}</span>'
                    f'<span class="m">{due.strftime("%b")}</span></div>',
                    unsafe_allow_html=True,
                )
                cols[1].markdown(
                    f'<div class="dt">{esc(item["title"])}</div>'
                    f'<div class="ds">{esc(item["kind"].title())} · reminder {item["remind_days_before"]} days before</div>',
                    unsafe_allow_html=True,
                )
                cols[2].markdown(
                    f'<span class="lp-badge {"low" if css == "overdue" else "medium" if css == "soon" else "high"}">{label}</span> '
                    + confidence_badge(item["confidence"]),
                    unsafe_allow_html=True,
                )
                if cols[3].button("Dismiss", key=f"dismiss_deadline_{item['id']}"):
                    with session_scope() as session:
                        crud.dismiss_deadline(session, item["id"])
                    flash("Deadline dismissed.")
                    st.rerun()
                if item["source_text"]:
                    with st.expander("Source clause"):
                        st.markdown(
                            f'<div class="lp-source">{esc(item["source_text"])}</div>',
                            unsafe_allow_html=True,
                        )
    else:
        st.info("No active deadlines for this document.")

    st.markdown("### Tasks")
    open_tasks = [item for item in detail["tasks"] if item["status"] == "open"]
    done_tasks = [item for item in detail["tasks"] if item["status"] == "done"]
    if open_tasks:
        for item in open_tasks:
            render_task_row(item, "detail")
    else:
        st.success("No open tasks. Nice work.")
    if done_tasks:
        with st.expander(f"Completed tasks ({len(done_tasks)})", expanded=False):
            for item in done_tasks:
                cols = st.columns([5, 1.5, 1])
                cols[0].markdown(
                    f'<div class="tt" style="text-decoration:line-through;color:#9999B2">{esc(item["title"])}</div>',
                    unsafe_allow_html=True,
                )
                cols[1].caption(fmt_date(item["due_date"]))
                if cols[2].button("Reopen", key=f"reopen_{item['id']}"):
                    mark_task_done(item["id"], False)


def render_missing_tab(detail: dict, unresolved: list[dict]) -> None:
    st.markdown("### Fields LifePilot expected but could not find")
    if not unresolved:
        st.success("Nothing is missing for this document type.")
    else:
        for item in unresolved:
            label = FIELD_LABELS.get(item["field_name"], item["field_name"].replace("_", " ").title())
            severity_css = {"high": "low", "medium": "medium", "low": "neutral"}.get(item["severity"], "neutral")
            with st.container(border=True):
                cols = st.columns([5, 1.4, 1.2], vertical_alignment="center")
                cols[0].markdown(
                    f'<div class="dt">{esc(label)}</div><div class="ds">{esc(item["description"])}</div>',
                    unsafe_allow_html=True,
                )
                cols[1].markdown(
                    f'<span class="lp-badge {severity_css}">{esc(item["severity"].title())}</span>',
                    unsafe_allow_html=True,
                )
                if cols[2].button("Dismiss", key=f"resolve_missing_{item['id']}"):
                    with session_scope() as session:
                        crud.resolve_missing_info(session, item["id"])
                    flash("Missing field marked as resolved.")
                    st.rerun()
        st.markdown("#### Add the missing value")
        with st.form("missing_value_form"):
            mapping = {
                item["id"]: item["field_name"] for item in unresolved
            }
            chosen = st.selectbox(
                "Missing field",
                list(mapping.keys()),
                format_func=lambda key: FIELD_LABELS.get(mapping[key], mapping[key].replace("_", " ").title()),
            )
            value = st.text_input("Value", placeholder="Enter the value found elsewhere")
            submitted = st.form_submit_button("Save value & resolve", type="primary")
        if submitted and value.strip():
            field_name = mapping[chosen]
            value_type = "date" if field_name in DATE_FIELDS else "money" if field_name in MONEY_FIELDS else "text"
            with session_scope() as session:
                crud.upsert_entity(
                    session,
                    detail["id"],
                    field_name=field_name,
                    value=value.strip(),
                    value_type=value_type,
                )
            flash(f"{FIELD_LABELS.get(field_name, field_name)} saved.")
            st.rerun()

    resolved = [item for item in detail["missing"] if item["resolved"]]
    if resolved:
        with st.expander(f"Resolved fields ({len(resolved)})", expanded=False):
            for item in resolved:
                st.markdown(f"✓ {FIELD_LABELS.get(item['field_name'], item['field_name'])}")


def render_text_tab(detail: dict) -> None:
    text = detail["raw_text"]
    st.markdown(
        f'<div class="lp-strip">{confidence_badge(1.0, True)}'
        f'<span class="lp-badge neutral">{esc((detail["extraction_method"] or "text").replace("_", " ").title())}</span>'
        f'<span class="lp-badge neutral">{len(text):,} characters</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown("")
    if text:
        st.text_area("Extracted document text", value=text, height=440, disabled=True, label_visibility="collapsed")
        st.download_button(
            "Download extracted text",
            data=text.encode("utf-8"),
            file_name=f"{Path(detail['filename']).stem}_extracted.txt",
            mime="text/plain",
        )
    else:
        st.info("No text was extracted from this file.")


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------
def render_reminders() -> None:
    page_header("Reminders & calendar", "Deadlines, in-app notifications and .ics export")
    status = scheduler_status()
    top = st.columns([1.6, 1.6, 1.6, 1.4], vertical_alignment="center")
    metric_card(top[0], "Scheduler", "Running" if status["running"] else "Paused", "background check", "⏱️", "good" if status["running"] else "warn")
    metric_card(top[1], "Next check", status["next_run"].strftime("%d %b · %H:%M") if status["next_run"] else "—", f'every {config.REMINDER_CHECK_HOURS}h', "🔄")
    unread = load_notifications(include_read=False)
    metric_card(top[2], "Unread alerts", len(unread), "in-app notifications", "🔔", "warn" if unread else "good")
    email_state = mail.email_status()
    metric_card(
        top[3],
        "Email",
        "Ready" if email_state["configured"] else "Preview only",
        "SMTP digest",
        "✉️",
        "good" if email_state["configured"] else "warn",
    )
    st.markdown("")
    if st.button("Run reminder check now", key="run_reminders", type="primary"):
        with st.spinner("Checking deadlines…"):
            with session_scope() as session:
                run = check_reminders(session)
        flash(f"Checked {run.checked} deadlines · {run.created} new reminder(s).")
        st.rerun()

    tabs = st.tabs(["Notifications", "Calendar export", "Deadline schedule"])

    with tabs[0]:
        notifications = load_notifications(include_read=True)
        if not notifications:
            st.info("No notifications yet. The scheduler creates them when a deadline enters its reminder window.")
        else:
            unread_items = [item for item in notifications if not item["read"]]
            read_items = [item for item in notifications if item["read"]]
            if unread_items:
                st.markdown(f"#### Unread · {len(unread_items)}")
                for item in unread_items:
                    with st.container(border=True):
                        cols = st.columns([5, 1.3, 1.3], vertical_alignment="center")
                        kind_css = "low" if item["kind"] == "overdue" else "medium"
                        cols[0].markdown(
                            f'<div class="dt">{esc(item["title"])}</div>'
                            f'<div class="ds">{esc(item["message"])}</div>',
                            unsafe_allow_html=True,
                        )
                        cols[1].markdown(
                            f'<span class="lp-badge {kind_css}">{esc(item["kind"].title())}</span>',
                            unsafe_allow_html=True,
                        )
                        if cols[2].button("Mark read", key=f"notif_read_{item['id']}"):
                            mark_notification_read(item["id"])
            if unread_items and st.button("Mark all as read", key="mark_all_read"):
                with session_scope() as session:
                    count = crud.mark_all_notifications_read(session)
                flash(f"Marked {count} notification(s) as read.")
                st.rerun()
            if read_items:
                with st.expander(f"Earlier notifications ({len(read_items)})", expanded=False):
                    for item in read_items[:20]:
                        st.markdown(f"~~{esc(item['title'])}~~")
                        st.caption(item["message"])

    with tabs[1]:
        documents = load_documents()
        if not documents:
            st.info("Process a document first to export its deadlines.")
        else:
            c1, c2 = st.columns([2.4, 1.2])
            options = ["All documents"] + [f'{item["filename"]} (#{item["id"]})' for item in documents]
            scope = c1.selectbox("Export scope", options, key="calendar_scope")
            include_overdue = c2.checkbox("Include overdue", value=False, key="calendar_overdue")
            selected_id = None
            if scope != "All documents":
                selected_id = int(scope.rsplit("#", 1)[1].rstrip(")"))
            with session_scope() as session:
                deadlines = crud.upcoming_deadlines(
                    session,
                    document_id=selected_id,
                    include_overdue=include_overdue,
                    limit=1000,
                )
                rows = [deadline_dict(item) for item in deadlines]
            raw = build_calendar(
                rows,
                calendar_name="LifePilot Deadlines" if selected_id is None else f"LifePilot · {scope}",
            )
            st.markdown(f"**{len(rows)} event(s)** will be exported. Each event includes a display reminder based on its rule.")
            if rows:
                for item in rows[:6]:
                    st.markdown(
                        f'<div class="lp-kv"><span class="k">{fmt_date(item["due_date"])} · {esc(item["document"])}</span>'
                        f'<span class="v">{esc(item["title"])}</span></div>',
                        unsafe_allow_html=True,
                    )
            st.download_button(
                "📅 Download .ics file",
                data=raw,
                file_name="lifepilot_deadlines.ics" if selected_id is None else f"lifepilot_document_{selected_id}.ics",
                mime="text/calendar",
                type="primary",
                key="calendar_download",
            )
            st.caption("Import the file into Google Calendar (**Settings → Import & export**) or Outlook (**Open & Export → Import an iCalendar**).")

    with tabs[2]:
        data = load_dashboard()
        if not data["deadlines"]:
            st.info("No active deadlines.")
        else:
            for item in data["deadlines"]:
                render_deadline_row(item, compact=True)


# ---------------------------------------------------------------------------
# Spending
# ---------------------------------------------------------------------------
def style_plot(fig: Any) -> Any:
    fig.update_layout(
        template="plotly_white",
        height=340,
        margin=dict(l=10, r=10, t=45, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Segoe UI, Inter, sans-serif", color="#4A4A66", size=12),
        legend=dict(orientation="h", y=-0.18, title=""),
        colorway=PALETTE,
    )
    fig.update_xaxes(showgrid=False, linecolor="#E7E8F3")
    fig.update_yaxes(gridcolor="#EFF0F8", zeroline=False)
    return fig


def render_spending() -> None:
    page_header("Spending", "Bills and receipts, grouped by month and category")
    records = load_expenses()
    if not records:
        st.markdown(
            '<div class="lp-empty"><div class="e-icon">📊</div><h3>No spending data yet</h3>'
            "<p>Upload a bill or receipt with an amount. LifePilot will categorise it and build the charts.</p></div>",
            unsafe_allow_html=True,
        )
        if st.button("＋ Upload a bill or receipt", type="primary"):
            goto("Upload")
        return

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    months = sorted(df["month"].unique(), reverse=True)
    label_map = {
        month: pd.to_datetime(month + "-01").strftime("%b %Y") for month in months
    }
    choice = st.selectbox(
        "Month filter",
        ["All months"] + months,
        format_func=lambda value: "All months" if value == "All months" else label_map.get(value, value),
    )
    filtered = df if choice == "All months" else df[df["month"] == choice]
    currency = df["currency"].mode().iloc[0] if not df["currency"].empty else "INR"
    mixed = df["currency"].nunique() > 1

    total = float(filtered["amount"].sum())
    top_category = (
        filtered.groupby("category")["amount"].sum().idxmax() if not filtered.empty else "—"
    )
    monthly_avg = float(df.groupby("month")["amount"].sum().mean()) if not df.empty else 0.0

    metrics = st.columns(4)
    metric_card(metrics[0], "Total spend", format_amount(total, currency), label_map.get(choice, "All months") if choice != "All months" else "all recorded months", "💳")
    metric_card(metrics[1], "Transactions", len(filtered), "bills and receipts", "🧾")
    metric_card(metrics[2], "Top category", top_category, "by amount", "🏷️")
    metric_card(metrics[3], "Monthly average", format_amount(monthly_avg, currency), "across all months", "📈")
    if mixed:
        st.caption("Multiple currencies detected. Amounts are shown using the most common currency without FX conversion.")

    st.markdown("")
    left, right = st.columns([1.1, 1.0], gap="large")
    with left:
        st.markdown("#### Spending by category")
        if filtered.empty:
            st.info("No transactions in this month.")
        else:
            category_df = (
                filtered.groupby("category", as_index=False)["amount"]
                .sum()
                .sort_values("amount", ascending=False)
            )
            fig = px.bar(
                category_df,
                x="category",
                y="amount",
                color="category",
                text_auto=".3s",
                color_discrete_sequence=PALETTE,
            )
            fig.update_traces(textposition="outside", marker_line_width=0)
            fig.update_layout(showlegend=False)
            st.plotly_chart(style_plot(fig), width="stretch", config={"displayModeBar": False})

    with right:
        st.markdown("#### Monthly trend")
        trend = (
            df.groupby(["month", "month_label"], as_index=False)["amount"]
            .sum()
            .sort_values("month")
        )
        if len(trend) == 1:
            st.caption("Add more months of bills to see the trend line fill out.")
        fig = px.line(trend, x="month_label", y="amount", markers=True)
        fig.update_traces(line=dict(width=3, color="#5B5BD6"), marker=dict(size=9, color="#8B5CF6"))
        fig.update_layout(yaxis_title="Amount", xaxis_title="")
        st.plotly_chart(style_plot(fig), width="stretch", config={"displayModeBar": False})

    st.markdown("#### Transactions")
    table = filtered.copy()
    table["Date"] = table["date"].dt.strftime("%d %b %Y")
    table["Amount"] = table.apply(lambda row: format_amount(row["amount"], row["currency"]), axis=1)
    table = table.rename(
        columns={
            "vendor": "Vendor",
            "category": "Category",
            "doc_type": "Type",
            "document": "Document",
        }
    )
    st.dataframe(
        table[["Date", "Vendor", "Category", "Type", "Document", "Amount"]],
        hide_index=True,
        width="stretch",
    )


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def render_settings() -> None:
    page_header("Settings", "AI privacy, reminder timing and local data")
    with session_scope() as session:
        settings = crud.get_settings(session)
        values = {
            "llm_enabled": settings.llm_enabled,
            "llm_model": settings.llm_model,
            "remind_days_before": settings.remind_days_before,
            "currency": settings.currency,
            "email_enabled": settings.email_enabled,
            "email_to": settings.email_to,
        }
    tabs = st.tabs(["General", "AI assist", "Email", "Data & diagnostics"])

    with tabs[0]:
        st.markdown("### Reminders")
        with st.form("general_settings"):
            remind_days = st.slider(
                "Default reminder (days before a deadline)",
                min_value=1,
                max_value=60,
                value=int(values["remind_days_before"]),
                help="Applied to new bills, applications and clause deadlines. Warranty and certificate reminders use 30 days; agreement renewals use 15.",
            )
            currency = st.selectbox(
                "Display currency",
                ["INR", "USD", "EUR", "GBP", "AED"],
                index=["INR", "USD", "EUR", "GBP", "AED"].index(values["currency"])
                if values["currency"] in {"INR", "USD", "EUR", "GBP", "AED"}
                else 0,
                format_func=lambda code: f"{code} ({config.currency_symbol(code)})",
            )
            submitted = st.form_submit_button("Save settings", type="primary")
        if submitted:
            with session_scope() as session:
                crud.update_settings(
                    session, remind_days_before=int(remind_days), currency=currency
                )
            flash("General settings saved.")
            st.rerun()
        st.caption("Reminder timing is stored per deadline when a document is processed. Reprocess a document to apply a new default.")

    with tabs[1]:
        st.markdown("### Optional LLM fallback")
        key_ready = config.llm_configured()
        if key_ready:
            st.success(f"API key detected. Model: `{config.LLM_MODEL}` · endpoint: `{config.LLM_BASE_URL}`")
        else:
            st.warning("No API key detected. Set `LIFEPILOT_LLM_API_KEY` in `.env` and restart the app.")
        st.markdown(
            '<div class="lp-note">AI assist is used only when an expected field is missing or its confidence is below 60%. '
            "The document text is sent to your configured OpenAI-compatible endpoint, and the response must pass a strict JSON schema "
            "before anything is saved. Nothing is sent while this toggle is off.</div>",
            unsafe_allow_html=True,
        )
        with st.form("llm_settings"):
            llm_enabled = st.checkbox(
                "Enable AI assist",
                value=bool(values["llm_enabled"]) and key_ready,
                disabled=not key_ready,
            )
            model = st.text_input("Model", value=values["llm_model"])
            submitted = st.form_submit_button("Save AI settings", type="primary", disabled=not key_ready)
        if submitted:
            with session_scope() as session:
                crud.update_settings(
                    session, llm_enabled=bool(llm_enabled), llm_model=model.strip() or config.LLM_MODEL
                )
            flash("AI settings saved.")
            st.rerun()
        ai_cols = st.columns([1.2, 3.0], vertical_alignment="center")
        if ai_cols[0].button("🔌 Test connection", key="test_llm", disabled=not key_ready):
            with st.spinner("Calling the provider…"):
                ok, message = llm_fallback.test_connection()
            flash(message, "success" if ok else "error")
            st.rerun()
        ai_cols[1].caption(
            "Runs a tiny JSON round-trip. No document text is sent."
        )
        st.caption(
            "Configured via LIFEPILOT_LLM_API_KEY, LIFEPILOT_LLM_BASE_URL and LIFEPILOT_LLM_MODEL "
            "(environment variables or Streamlit secrets)."
        )

    with tabs[2]:
        st.markdown("### Email reminders")
        status = mail.email_status()
        ready = status["configured"]
        if ready:
            st.success(
                f"SMTP ready · {status['host']}:{status['port']} ({status['security']}) · "
                f"from {status['sender']}"
            )
        else:
            st.warning(
                "Email is not configured on this deployment yet, so reminders only appear in-app. "
                "Everything below becomes live as soon as the SMTP settings are supplied."
            )
            if status["missing"]:
                st.markdown(
                    "Missing: " + ", ".join(f"`{name}`" for name in status["missing"])
                )
            st.markdown(
                "Add these as environment variables on your host "
                "(**Render → Environment**, or Streamlit Cloud → App settings → Secrets) "
                "or in `.env` when running locally:"
            )
            st.code(
                'LIFEPILOT_SMTP_HOST = "smtp.gmail.com"\n'
                'LIFEPILOT_SMTP_PORT = "587"\n'
                'LIFEPILOT_SMTP_USER = "you@gmail.com"\n'
                'LIFEPILOT_SMTP_PASSWORD = "your-16-character-app-password"\n'
                'LIFEPILOT_SMTP_FROM = "you@gmail.com"\n'
                'LIFEPILOT_EMAIL_TO = "you@gmail.com"',
                language="toml",
            )
            st.caption(
                "Gmail needs 2-Step Verification turned on and a 16-character App Password "
                "(Google Account → Security → App passwords). Your normal password will not work."
            )

        default_to = values["email_to"] or config.EMAIL_TO
        with st.form("email_settings"):
            email_enabled = st.checkbox(
                "Email me reminder digests",
                value=bool(values["email_enabled"]) and ready,
                disabled=not ready,
            )
            email_to = st.text_input(
                "Recipient email",
                value=default_to,
                disabled=not ready or config.DEMO_MODE,
                help="Where reminder digests and test emails are sent.",
            )
            submitted = st.form_submit_button(
                "Save email settings", type="primary", disabled=not ready
            )
        if submitted:
            with session_scope() as session:
                crud.update_settings(
                    session,
                    email_enabled=bool(email_enabled),
                    email_to=(email_to or default_to).strip(),
                )
            flash("Email settings saved.")
            st.rerun()
        if config.DEMO_MODE:
            st.caption(
                "Public demo: the recipient is fixed so the shared mailbox cannot be used "
                "to email arbitrary addresses."
            )

        actions = st.columns(4)
        recipient = (email_to or default_to).strip()
        if actions[0].button(
            "✉️ Send test email",
            key="send_test_email",
            disabled=not ready or not recipient,
        ):
            with st.spinner("Sending…"):
                ok, message = mail.send_test_email(recipient)
            flash(message, "success" if ok else "error")
            st.rerun()
        if actions[1].button("🔌 Test connection", key="test_smtp", disabled=not ready):
            with st.spinner("Connecting to the SMTP server…"):
                ok, message = mail.test_connection()
            flash(message, "success" if ok else "error")
            st.rerun()
        if actions[2].button("📨 Email unread digest", key="send_digest", disabled=not ready):
            with session_scope() as session:
                pending = list(crud.list_notifications(session, unread_only=True, limit=50))
            if not pending:
                flash("There are no unread reminders to email.", "warning")
            else:
                with st.spinner("Sending digest…"):
                    ok, message = mail.send_reminder_digest(pending, recipient)
                flash(f"{message} ({len(pending)} reminder(s))", "success" if ok else "error")
            st.rerun()
        if actions[3].button("🗑️ Clear outbox", key="clear_outbox"):
            with session_scope() as session:
                removed = crud.clear_email_log(session)
            flash(f"Removed {removed} outbox entry(s).", "warning")
            st.rerun()

        subject, body = mail.render_test_email()
        with st.expander("Preview the test email"):
            st.markdown(f"**Subject:** {subject}")
            st.text(body)
            st.caption("The same content is delivered as an HTML email as well.")

        st.markdown("#### Outbox")
        entries = load_email_log(12)
        if not entries:
            st.caption("No email has been sent yet. Configure SMTP and use **Send test email**.")
        else:
            for entry in entries:
                badge = {"sent": "high", "failed": "low"}.get(entry["status"], "neutral")
                with st.container(border=True):
                    cols = st.columns([4.2, 1.1, 2.2], vertical_alignment="center")
                    cols[0].markdown(
                        f'<div class="dt">{esc(entry["subject"])}</div>'
                        f'<div class="ds">{esc(entry["to"])} · {fmt_date(entry["created_at"])}</div>',
                        unsafe_allow_html=True,
                    )
                    cols[1].markdown(
                        f'<span class="lp-badge {badge}">{esc(entry["status"].title())}</span>',
                        unsafe_allow_html=True,
                    )
                    cols[2].caption(entry["detail"][:140] or "—")
                    if entry["body"]:
                        with st.expander("Show message"):
                            st.text(entry["body"])
        st.caption(
            "Email is sent only when the scheduler creates a new reminder, or when you press a "
            "button above. SMTP credentials never leave the server and are never written to the database."
        )

    with tabs[3]:
        documents = load_documents()
        st.markdown("### Local data")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(
                f'<div class="lp-feature"><div class="f-icon">✨</div><strong>Sample data</strong>'
                f"<span>{len(documents)} document(s) in your library. The bundled samples cover a bill, warranty, agreement and application.</span></div>",
                unsafe_allow_html=True,
            )
            if st.button("Load sample documents", key="settings_samples", width="stretch"):
                load_samples()
            if config.DEMO_MODE:
                if st.button("Reset demo data", key="settings_reset_demo", width="stretch"):
                    reset_demo_data()
                st.caption(
                    "Bulk delete is disabled in the public demo. Reset reloads the four samples."
                )
            elif st.button("Clear sample data" if len(documents) == 4 else "Clear all documents", key="settings_clear", width="stretch"):
                st.session_state["confirm_clear"] = True
            if st.session_state.get("confirm_clear") and not config.DEMO_MODE:
                st.warning("This removes every document, task, deadline and reminder.")
                confirm_cols = st.columns(2)
                if confirm_cols[0].button("Yes, delete everything", type="primary", key="confirm_clear_yes"):
                    st.session_state["confirm_clear"] = False
                    delete_all_documents()
                if confirm_cols[1].button("Cancel", key="confirm_clear_no"):
                    st.session_state["confirm_clear"] = False
                    st.rerun()

        with c2:
            scheduler = scheduler_status()
            st.markdown(
                f"""
                <div class="lp-feature">
                  <div class="f-icon">🔧</div><strong>Diagnostics</strong>
                  <span>
                  Database: {esc(config.DATABASE_URL)}<br/>
                  Tesseract OCR: {"ready" if ocr_available() else "not found"}<br/>
                  Reminder scheduler: {"running" if scheduler["running"] else "paused"}<br/>
                  LLM key: {"configured" if config.llm_configured() else "not configured"}<br/>
                  SMTP: {"configured" if mail.email_configured() else "not configured"}<br/>
                  {"Email security: " + mail.email_status()["security"] + "<br/>" if mail.email_configured() else ""}
                  Demo mode: {"on" if config.DEMO_MODE else "off"}<br/>
                  spacy: check the model with <code>python -m spacy validate</code>
                  </span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        st.markdown("### Privacy")
        st.markdown(
            "- Files live in `data/uploads`; extracted text and fields live in the local SQLite database.\n"
            "- LLM fallback is opt-in and only runs for missing or low-confidence fields.\n"
            "- OCR runs locally through Tesseract. No cloud OCR is used.\n"
            "- Calendar exports are generated locally as `.ics` files."
        )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
def main() -> None:
    page = render_sidebar()

    flash_message = st.session_state.pop("flash_message", None)
    if flash_message:
        kind, message = flash_message
        getattr(st, kind, st.info)(message)

    if page == "Dashboard":
        render_dashboard()
    elif page == "Upload":
        render_upload()
    elif page == "Documents":
        render_documents()
    elif page == "Reminders":
        render_reminders()
    elif page == "Spending":
        render_spending()
    elif page == "Settings":
        render_settings()


if __name__ == "__main__":
    main()
