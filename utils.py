"""Small shared helpers for money formatting and category inference."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from lifepilot import config

_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_LAKH_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(lakh|lac|crore)", re.IGNORECASE)


def parse_amount(raw: str | float | int | None) -> float | None:
    """Parse a monetary string such as ``Rs. 1,25,000.50`` into a float."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().lower().replace("₹", "").replace("rs.", "").replace("rs", "")
    lakh_match = _LAKH_RE.search(text)
    if lakh_match:
        value = float(lakh_match.group(1))
        multiplier = 100_000 if lakh_match.group(2).lower() in {"lakh", "lac"} else 10_000_000
        return round(value * multiplier, 2)
    match = _NUMBER_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def format_amount(value: float | None, currency: str = "INR") -> str:
    """Format an amount with a currency symbol and Indian grouping for INR."""
    if value is None:
        return "—"
    symbol = config.currency_symbol(currency)
    if currency.upper() == "INR":
        whole = f"{value:,.2f}"
        # Convert international grouping (1,234,567.89) to Indian (12,34,567.89)
        integer, _, decimals = whole.partition(".")
        digits = integer.replace(",", "")
        if len(digits) > 3:
            head, tail = digits[:-3], digits[-3:]
            groups = []
            while len(head) > 2:
                groups.insert(0, head[-2:])
                head = head[:-2]
            if head:
                groups.insert(0, head)
            formatted = ",".join(groups + [tail])
        else:
            formatted = digits
        return f"{symbol}{formatted}.{decimals}"
    return f"{symbol}{value:,.2f}"


def fmt_date(value: date | datetime | None, fallback: str = "—") -> str:
    """Human friendly date, e.g. ``05 Dec 2026``."""
    if value is None:
        return fallback
    if isinstance(value, datetime):
        value = value.date()
    return value.strftime("%d %b %Y")


def infer_expense_category(text: str | None, vendor: str | None = None) -> str:
    """Best-effort expense category from keywords in the document."""
    haystack = f"{vendor or ''} {text or ''}".lower()
    rules: list[tuple[str, tuple[str, ...]]] = [
        ("Electricity", ("electricity", "electric bill", "power", "bescom", "tata power", "kwh", "units consumed")),
        ("Rent", ("rent", "lease", "landlord", "tenant", "monthly rent")),
        ("Insurance", ("insurance", "policy", "premium", "coverage", "insured")),
        ("Water", ("water bill", "water supply", "municipal water")),
        ("Internet", ("internet", "broadband", "wifi", "fibre", "fiber")),
        ("Phone", ("mobile", "airtel", "jio", "vodafone", "vi ", "postpaid", "prepaid")),
        ("Gas", ("gas bill", "lpg", "indane", "hp gas", "piped gas")),
        ("Groceries", ("grocery", "groceries", "supermarket", "bigbasket", "dmart", "vegetables")),
        ("Dining", ("restaurant", "cafe", "coffee", "swiggy", "zomato", "food court")),
        ("Healthcare", ("hospital", "pharmacy", "clinic", "medical", "diagnostic", "apollo")),
        ("Fuel", ("petrol", "diesel", "fuel", "hpcl", "bpcl", "indian oil", "shell")),
        ("Subscriptions", ("subscription", "netflix", "spotify", "prime video", "hotstar", "youtube premium")),
        ("Education", ("school", "college", "tuition", "course", "university", "exam fee")),
        ("Shopping", ("amazon", "flipkart", "myntra", "retail", "store", "mall", "shopping", "purchase")),
    ]
    for category, keywords in rules:
        if any(keyword in haystack for keyword in keywords):
            return category
    return "Other"


def to_jsonable(value: Any) -> Any:
    """Convert dates and other values into JSON-friendly primitives."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value
