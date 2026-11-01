"""Entity and field extraction.

Combines explicit label rules, regular expressions and (when installed) spaCy
named-entity recognition.  Every returned field carries a confidence score and
its relative position in the document.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Any, Iterable

import dateparser

from lifepilot.pipeline.confidence import (
    compute_confidence,
    score_label_match,
    score_regex_match,
)
from lifepilot.utils import infer_expense_category, parse_amount

# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------
@dataclass
class DateMention:
    raw: str
    value: date
    start: int
    end: int
    confidence: float


@dataclass
class AmountMention:
    raw: str
    value: float
    currency: str
    start: int
    confidence: float


@dataclass
class ExtractedField:
    field_name: str
    value: str
    value_type: str = "text"
    confidence: float = 0.5
    source: str = "rule"
    position_ratio: float = 0.0

    def to_payload(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "value": self.value,
            "value_type": self.value_type,
            "confidence": self.confidence,
            "source": self.source,
            "position_ratio": self.position_ratio,
        }


@dataclass
class ExtractionResult:
    fields: list[ExtractedField] = field(default_factory=list)
    dates: list[DateMention] = field(default_factory=list)
    amounts: list[AmountMention] = field(default_factory=list)
    people: list[str] = field(default_factory=list)
    organizations: list[str] = field(default_factory=list)

    def first(self, field_name: str) -> ExtractedField | None:
        candidates = [f for f in self.fields if f.field_name == field_name]
        return max(candidates, key=lambda f: f.confidence, default=None)

    def values(self, field_name: str) -> list[str]:
        return [f.value for f in self.fields if f.field_name == field_name]

    def as_value_map(self) -> dict[str, str]:
        """Best value per field name -- convenient for task generation."""
        result: dict[str, str] = {}
        for item in sorted(self.fields, key=lambda f: f.confidence, reverse=True):
            result.setdefault(item.field_name, item.value)
        return result

    def to_payloads(self) -> list[dict[str, Any]]:
        return [item.to_payload() for item in self.fields]


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------
_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
_MONTH_RE = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"

_DATE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"(?<!\d)(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)"),
        "iso",
    ),
    (
        re.compile(
            rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?[\s./-]+(\d{{1,2}})[\s./-]+(20\d{{2}}|\d{{2}})(?!\d)",
            re.IGNORECASE,
        ),
        "dmy_numeric",
    ),
    (
        re.compile(
            rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?[\s./-]+({_MONTH_RE})[a-z]*[,\s]+(20\d{{2}}|\d{{2}})(?!\d)",
            re.IGNORECASE,
        ),
        "dmy_month",
    ),
    (
        re.compile(
            rf"(?<![A-Za-z])({_MONTH_RE})[a-z]*[\s.-]+(\d{{1,2}})(?:st|nd|rd|th)?,?[\s,]+(20\d{{2}})(?!\d)",
            re.IGNORECASE,
        ),
        "mdy_month",
    ),
]


def _coerce_year(year: int) -> int:
    if year < 100:
        return 2000 + year if year <= 69 else 1900 + year
    return year


def _make_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(_coerce_year(year), month, day)
    except ValueError:
        return None


def _match_to_date(match: re.Match[str], kind: str) -> date | None:
    groups = match.groups()
    if kind == "iso":
        return _make_date(int(groups[0]), int(groups[1]), int(groups[2]))
    if kind == "dmy_numeric":
        return _make_date(int(groups[2]), int(groups[1]), int(groups[0]))
    if kind == "dmy_month":
        month = _MONTHS.get(groups[1].lower()[:3])
        if month is None:
            month = _MONTHS.get(groups[1].lower())
        return _make_date(int(groups[2]), month or 0, int(groups[0]))
    if kind == "mdy_month":
        month = _MONTHS.get(groups[0].lower()[:3]) or _MONTHS.get(groups[0].lower())
        return _make_date(int(groups[2]), month or 0, int(groups[1]))
    return None


def parse_date_text(raw: str, *, reference_date: date | None = None) -> date | None:
    """Parse a date written in common Indian/international formats."""
    if not raw:
        return None
    text = re.sub(r"(?i)\b(\d{1,2})(st|nd|rd|th)\b", r"\1", str(raw))
    text = text.strip().strip(".,;:()[]")

    for pattern, kind in _DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            parsed = _match_to_date(match, kind)
            if parsed and 1990 <= parsed.year <= 2100:
                return parsed

    # Only hand free text to dateparser when it plausibly contains a date.
    if re.search(r"\b(?:19|20)\d{2}\b", text) or re.search(_MONTH_RE, text, re.IGNORECASE):
        try:
            parsed_dt = dateparser.parse(
                text,
                settings={
                    "DATE_ORDER": "DMY",
                    "PREFER_DAY_OF_MONTH": "first",
                    "RELATIVE_BASE": datetime.combine(
                        reference_date or date.today(), datetime.min.time()
                    ),
                },
            )
            if parsed_dt and 1990 <= parsed_dt.year <= 2100:
                return parsed_dt.date()
        except Exception:
            return None
    return None


def find_dates(text: str) -> list[DateMention]:
    """Find all explicit dates in a block of text."""
    if not text:
        return []
    seen_spans: list[tuple[int, int]] = []
    mentions: list[DateMention] = []
    for pattern, kind in _DATE_PATTERNS:
        for match in pattern.finditer(text):
            if any(match.start() < end and match.end() > start for start, end in seen_spans):
                continue
            parsed = _match_to_date(match, kind)
            if parsed is None or not (1990 <= parsed.year <= 2100):
                continue
            seen_spans.append((match.start(), match.end()))
            position = match.start() / max(len(text), 1)
            confidence = score_regex_match(strength=0.92, position_ratio=position, strong=True)
            mentions.append(
                DateMention(match.group(0).strip(), parsed, match.start(), match.end(), confidence)
            )
    return sorted(mentions, key=lambda item: item.start)


# ---------------------------------------------------------------------------
# Amount parsing
# ---------------------------------------------------------------------------
_CURRENCY_PATTERN = r"(?:Rs\.?|INR|₹|\$|USD|EUR|€|GBP|£)"
_AMOUNT_RE = re.compile(
    rf"({_CURRENCY_PATTERN})\s*([\d][\d,]*(?:\.\d{{1,2}})?)",
    re.IGNORECASE,
)


def _currency_from_token(token: str) -> str:
    token = token.lower()
    if token in {"₹", "rs", "rs.", "inr"}:
        return "INR"
    if token in {"$", "usd"}:
        return "USD"
    if token in {"€", "eur"}:
        return "EUR"
    if token in {"£", "gbp"}:
        return "GBP"
    return "INR"


def find_amounts(text: str) -> list[AmountMention]:
    """Find currency-prefixed amounts in text."""
    mentions: list[AmountMention] = []
    for match in _AMOUNT_RE.finditer(text):
        raw_value = match.group(2)
        value = parse_amount(raw_value)
        if value is None or value <= 0:
            continue
        position = match.start() / max(len(text), 1)
        confidence = score_regex_match(
            strength=0.92 if "," in raw_value or "." in raw_value else 0.84,
            position_ratio=position,
            strong=True,
        )
        mentions.append(
            AmountMention(
                raw=match.group(0).strip(),
                value=value,
                currency=_currency_from_token(match.group(1)),
                start=match.start(),
                confidence=confidence,
            )
        )
    return mentions


# ---------------------------------------------------------------------------
# spaCy (optional)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def load_spacy_model() -> Any | None:
    """Load ``en_core_web_sm`` if available; otherwise return ``None``."""
    try:
        import spacy

        return spacy.load("en_core_web_sm")
    except Exception:
        return None


@dataclass
class _NamedEntity:
    text: str
    label: str
    start: int
    confidence: float


def extract_named_entities(text: str) -> list[_NamedEntity]:
    """Extract PERSON/ORG entities with spaCy, falling back to heuristics."""
    model = load_spacy_model()
    entities: list[_NamedEntity] = []
    if model is not None and text:
        try:
            doc = model(text[:100_000])
            for ent in doc.ents:
                if ent.label_ not in {"PERSON", "ORG"}:
                    continue
                cleaned = re.sub(r"\s+", " ", ent.text).strip()
                if len(cleaned) < 3 or cleaned.lower() in {"the", "this", "that"}:
                    continue
                position = ent.start_char / max(len(text), 1)
                confidence = compute_confidence(
                    method="spacy",
                    pattern_strength=0.8,
                    position_ratio=position,
                    label=ent.label_,
                )
                entities.append(
                    _NamedEntity(cleaned, ent.label_, ent.start_char, confidence)
                )
        except Exception:
            entities = []

    if not entities:
        # Lightweight fallback: capitalised sequences containing organisation
        # suffixes (keeps the app useful when the spaCy model is not installed).
        org_re = re.compile(
            r"\b([A-Z][A-Za-z&.'-]*(?:\s+[A-Z][A-Za-z&.'-]*){0,4}\s+"
            r"(?:Ltd\.?|Limited|Pvt\.?|Private|LLC|Inc\.?|Corporation|Corp\.?|"
            r"Bank|Power|Insurance|Services|Authority|Department|University|"
            r"Academy|Supermarket|Store|Mart))\b"
        )
        for match in org_re.finditer(text):
            position = match.start() / max(len(text), 1)
            entities.append(
                _NamedEntity(
                    match.group(1).strip(),
                    "ORG",
                    match.start(),
                    compute_confidence(
                        method="heuristic",
                        pattern_strength=0.7,
                        position_ratio=position,
                        label="ORG",
                    ),
                )
            )
    return entities


# ---------------------------------------------------------------------------
# Label-based field extraction
# ---------------------------------------------------------------------------
@dataclass
class _LabelValue:
    label: str
    value: str
    start: int
    strength: float


def _label_values(
    text: str, labels: Iterable[str], strength: float = 0.9
) -> list[_LabelValue]:
    """Return values that follow a label, on the same or next line."""
    labels_sorted = sorted({label for label in labels}, key=len, reverse=True)
    if not labels_sorted:
        return []
    alternatives = "|".join(re.escape(label) for label in labels_sorted)
    pattern = re.compile(rf"(?<![A-Za-z])({alternatives})(?![A-Za-z])", re.IGNORECASE)
    results: list[_LabelValue] = []
    for match in pattern.finditer(text):
        line_end = text.find("\n", match.end())
        if line_end == -1:
            line_end = len(text)
        segment = text[match.end() : line_end]
        # Strip a "No.", "Number", "#" suffix plus separators.
        segment = re.sub(
            r"(?i)^\s*(?:no\.?|number|num\.?|#|id)?\s*[:\-–#.]?\s*", "", segment
        )
        value = segment.strip(" \t:.-–")
        if not value:
            next_line_start = line_end + 1
            next_line_end = text.find("\n", next_line_start)
            if next_line_end == -1:
                next_line_end = len(text)
            next_line = text[next_line_start:next_line_end].strip(" \t:.-–")
            if next_line and len(next_line) <= 120:
                value = next_line
        if not value:
            continue
        results.append(_LabelValue(match.group(1), value, match.start(), strength))
    # De-duplicate overlapping labels ("amount" inside "amount due").
    deduped: list[_LabelValue] = []
    seen_starts: set[int] = set()
    for item in sorted(results, key=lambda item: (-len(item.label), item.start)):
        if item.start in seen_starts:
            continue
        seen_starts.add(item.start)
        deduped.append(item)
    return deduped


def _clean_text_value(raw: str, max_len: int = 120) -> str:
    value = re.split(r"\s{2,}|\s*[|•]\s*", raw)[0]
    value = value.strip(" \t:.-–,;")
    value = re.sub(r"\s+", " ", value)
    return value[:max_len]


def _position(text: str, index: int) -> float:
    return round(index / max(len(text), 1), 4)


def _add_field(
    fields: list[ExtractedField],
    *,
    field_name: str,
    value: str | None,
    value_type: str,
    confidence: float,
    source: str = "rule",
    position_ratio: float,
) -> None:
    if value is None:
        return
    value = value.strip()
    if not value:
        return
    fields.append(
        ExtractedField(
            field_name=field_name,
            value=value,
            value_type=value_type,
            confidence=round(confidence, 2),
            source=source,
            position_ratio=position_ratio,
        )
    )


def _extract_date_field(
    text: str,
    labels: list[str],
    field_name: str,
    *,
    strength: float = 0.92,
    doc_type_match: float = 0.8,
    allow_generic: bool = False,
) -> ExtractedField | None:
    for candidate in _label_values(text, labels, strength=strength):
        parsed = parse_date_text(candidate.value)
        if parsed is None:
            continue
        confidence = score_label_match(
            strength=strength,
            position_ratio=_position(text, candidate.start),
            doc_type_match=doc_type_match,
        )
        return ExtractedField(
            field_name,
            parsed.isoformat(),
            "date",
            confidence,
            "rule",
            _position(text, candidate.start),
        )
    if allow_generic:
        dates = find_dates(text)
        if dates:
            first = dates[0]
            confidence = score_regex_match(
                strength=0.75,
                position_ratio=first.start / max(len(text), 1),
                strong=False,
            )
            return ExtractedField(
                field_name,
                first.value.isoformat(),
                "date",
                confidence,
                "rule",
                _position(text, first.start),
            )
    return None


def _extract_amount_field(
    text: str, labels: list[str], field_name: str, *, strength: float = 0.92
) -> ExtractedField | None:
    for candidate in _label_values(text, labels, strength=strength):
        lowered = candidate.value.lower()
        if any(bad in lowered for bad in ("subtotal", "sub-total", "tax", "discount", "gst", "%")):
            continue
        amount = parse_amount(candidate.value)
        if amount is None or amount <= 0 or amount > 10_00_00_000:
            continue
        confidence = score_label_match(
            strength=strength,
            position_ratio=_position(text, candidate.start),
            doc_type_match=0.9,
        )
        return ExtractedField(
            field_name,
            f"{amount:.2f}",
            "money",
            confidence,
            "rule",
            _position(text, candidate.start),
        )
    return None


_PERSON_FIELDS = {"landlord_name", "tenant_name", "holder_name", "applicant_name", "named_person"}


def _clean_person_name(value: str) -> str:
    """Drop trailing address/relationship details from a person label."""
    value = re.split(
        r",|\bresiding at\b|\bs/o\b|\bw/o\b|\bd/o\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return value.strip(" \t.-–")


def _extract_text_field(
    text: str,
    labels: list[str],
    field_name: str,
    *,
    strength: float = 0.88,
    value_type: str = "text",
    max_len: int = 120,
) -> ExtractedField | None:
    for candidate in _label_values(text, labels, strength=strength):
        value = _clean_text_value(candidate.value, max_len=max_len)
        if not value:
            continue
        if field_name in _PERSON_FIELDS or value_type == "person":
            value = _clean_person_name(value)
        if not value:
            continue
        # Reject values that are clearly the next label / unrelated data.
        if re.fullmatch(r"(?i)(?:date|amount|name|address|signature|no\.?|number)", value):
            continue
        if parse_date_text(value) is not None and value_type != "text":
            continue
        confidence = score_label_match(
            strength=strength,
            position_ratio=_position(text, candidate.start),
            doc_type_match=0.85,
        )
        return ExtractedField(
            field_name,
            value,
            value_type,
            confidence,
            "rule",
            _position(text, candidate.start),
        )
    return None


# ---------------------------------------------------------------------------
# Reference numbers
# ---------------------------------------------------------------------------
_REFERENCE_RULES: list[tuple[str, str, float]] = [
    ("invoice_number", r"(?:tax\s+)?invoice\s*(?:no\.?|number|#|id)\s*[:\-–]?\s*([A-Z0-9][A-Z0-9/_\-]{2,})", 0.92),
    ("receipt_number", r"receipt\s*(?:no\.?|number|#|id)\s*[:\-–]?\s*([A-Z0-9][A-Z0-9/_\-]{2,})", 0.92),
    ("policy_number", r"policy\s*(?:no\.?|number|#|id)\s*[:\-–]?\s*([A-Z0-9][A-Z0-9/_\-]{2,})", 0.93),
    ("account_number", r"(?:consumer|customer|account)\s*(?:no\.?|number|#|id)\s*[:\-–]?\s*((?:[0-9][0-9 ]{4,}[0-9])|[A-Z0-9][A-Z0-9/_\-]{2,})", 0.9),
    ("application_number", r"application\s*(?:no\.?|number|#|id)\s*[:\-–]?\s*([A-Z0-9][A-Z0-9/_\-]{2,})", 0.92),
    ("agreement_number", r"(?:agreement|contract)\s*(?:no\.?|number|#|id)\s*[:\-–]?\s*([A-Z0-9][A-Z0-9/_\-]{2,})", 0.9),
    ("warranty_number", r"warranty\s*(?:no\.?|number|#|id)\s*[:\-–]?\s*([A-Z0-9][A-Z0-9/_\-]{2,})", 0.9),
    ("certificate_number", r"certificate\s*(?:no\.?|number|#|id)\s*[:\-–]?\s*([A-Z0-9][A-Z0-9/_\-]{2,})", 0.92),
]


def _extract_reference_fields(text: str) -> list[ExtractedField]:
    fields: list[ExtractedField] = []
    for field_name, pattern, strength in _REFERENCE_RULES:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        value = match.group(1).strip(" .:;-–")
        if len(value) < 3 or value.isalpha() and value.lower() in {"number", "date"}:
            continue
        confidence = score_regex_match(
            strength=strength,
            position_ratio=_position(text, match.start(1)),
            strong=True,
        )
        fields.append(
            ExtractedField(
                field_name,
                value,
                "id",
                confidence,
                "rule",
                _position(text, match.start(1)),
            )
        )
    return fields


# ---------------------------------------------------------------------------
# Vendor / organisation heuristics
# ---------------------------------------------------------------------------
_COMPANY_SUFFIXES = re.compile(
    r"\b(?:ltd\.?|limited|pvt\.?|private|llc|inc\.?|corp\.?|corporation|bank|"
    r"power|energy|insurance|services|service|authority|department|university|"
    r"academy|supermarket|store|mart|hospital|company|co\.?|motors|infotech|"
    r"technologies|solutions)\b",
    re.IGNORECASE,
)
_NON_VENDOR_LINES = re.compile(
    r"(?i)^(?:tax invoice|invoice|receipt|warranty card|rental agreement|"
    r"lease agreement|application form|certificate|statement|bill)\b"
)


def _guess_vendor(text: str) -> ExtractedField | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    best: tuple[float, str, int] | None = None
    for index, line in enumerate(lines[:15]):
        if len(line) < 3 or len(line) > 90 or ":" in line:
            continue
        if _NON_VENDOR_LINES.search(line) or _COMPANY_SUFFIXES.search(line) is None:
            continue
        if parse_date_text(line):
            continue
        score = 0.72 + (0.06 if index < 5 else 0.0)
        if best is None or score > best[0]:
            best = (score, line, index)
    if best is None:
        for index, line in enumerate(lines[:6]):
            if (
                3 <= len(line) <= 70
                and ":" not in line
                and not _NON_VENDOR_LINES.search(line)
                and not re.search(r"\d{3,}", line)
                and parse_date_text(line) is None
            ):
                best = (0.58, line, index)
                break
    if best is None:
        return None
    score, value, _index = best
    confidence = compute_confidence(
        method="heuristic",
        pattern_strength=min(0.95, score),
        position_ratio=0.02,
        label="ORG",
        doc_type_match=0.9,
    )
    return ExtractedField("vendor", value, "text", confidence, "heuristic", 0.02)


# ---------------------------------------------------------------------------
# Document-type specific fields
# ---------------------------------------------------------------------------
def _extract_required_documents(text: str) -> list[ExtractedField]:
    heading = re.search(
        r"(?im)^\s*(?:documents?\s+required|required\s+documents?|enclosures?|"
        r"supporting\s+documents?|please\s+attach|documents?\s+to\s+be\s+attached)"
        r"\s*[:\-–]?\s*$",
        text,
    )
    if not heading:
        heading = re.search(
            r"(?i)(?:documents?\s+required|required\s+documents?|enclosures?|"
            r"please\s+attach)\s*[:\-–]\s*",
            text,
        )
    if not heading:
        return []

    tail = text[heading.end() : heading.end() + 900]
    items: list[str] = []
    for raw_line in tail.splitlines():
        line = raw_line.strip(" \t•*-–")
        if not line:
            if items:
                break
            continue
        if re.match(
            r"(?i)^(?:note|declaration|signature|date|place|for office|office use)\b",
            line,
        ):
            break
        # Numbered or bulleted list items; otherwise split comma lists.
        if re.match(r"^(?:\d+[.)]|[-•*])\s*", raw_line.strip()):
            items.append(re.sub(r"^(?:\d+[.)]|[-•*])\s*", "", raw_line.strip()))
        elif "," in line and len(line) < 200:
            items.extend(part.strip() for part in line.split(","))
        elif len(line) <= 120:
            items.append(line)
        if len(items) >= 12:
            break

    fields: list[ExtractedField] = []
    for item in dict.fromkeys(items):
        item = _clean_text_value(item, max_len=100)
        if len(item) < 3:
            continue
        fields.append(
            ExtractedField(
                "required_document",
                item,
                "list",
                0.86,
                "rule",
                _position(text, heading.start()),
            )
        )
    return fields


def _extract_warranty_period(text: str) -> ExtractedField | None:
    patterns = [
        r"warranty\s*(?:period)?\s*(?:of|is|:)?\s*(\d{1,2})\s*(months?|years?)",
        r"(\d{1,2})\s*(months?|years?)\s*(?:warranty|guarantee|coverage)",
        r"coverage\s*(?:period)?\s*(?:of|is|:)?\s*(\d{1,2})\s*(months?|years?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        qty = int(match.group(1))
        unit = "months" if match.group(2).lower().startswith("month") else "years"
        confidence = score_label_match(
            strength=0.9,
            position_ratio=_position(text, match.start()),
            doc_type_match=0.9,
        )
        return ExtractedField(
            "warranty_period",
            f"{qty} {unit}",
            "duration",
            confidence,
            "rule",
            _position(text, match.start()),
        )
    return None


def _add_months(value: date, months: int) -> date:
    """Add months without requiring dateutil."""
    year = value.year + (value.month - 1 + months) // 12
    month = (value.month - 1 + months) % 12 + 1
    day = min(value.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


def _derive_warranty_expiry(fields: list[ExtractedField]) -> ExtractedField | None:
    period = next((f for f in fields if f.field_name == "warranty_period"), None)
    purchase = next((f for f in fields if f.field_name == "purchase_date"), None)
    if period is None or purchase is None:
        return None
    match = re.match(r"(\d+)\s*(months?|years?)", period.value)
    if not match:
        return None
    try:
        purchase_date = date.fromisoformat(purchase.value)
    except ValueError:
        return None
    months = int(match.group(1)) * (12 if match.group(2).lower().startswith("year") else 1)
    expiry = _add_months(purchase_date, months)
    return ExtractedField(
        "expiry_date",
        expiry.isoformat(),
        "date",
        0.64,
        "heuristic",
        purchase.position_ratio,
    )


def _extract_application_fields(text: str) -> list[ExtractedField]:
    fields: list[ExtractedField] = []
    applicant = _extract_text_field(
        text,
        ["applicant name", "name of applicant", "full name", "candidate name"],
        "applicant_name",
        strength=0.86,
        max_len=80,
    )
    if applicant:
        fields.append(applicant)
    fields.extend(_extract_required_documents(text))
    return fields


def _extract_agreement_fields(text: str) -> list[ExtractedField]:
    fields: list[ExtractedField] = []
    mapping = [
        (
            "landlord_name",
            ["lessor", "landlord", "owner", "first party"],
            "text",
            0.88,
        ),
        (
            "tenant_name",
            ["lessee", "tenant", "second party"],
            "text",
            0.88,
        ),
        (
            "property_address",
            ["property address", "premises address", "address of premises", "demised premises", "property"],
            "text",
            0.84,
        ),
        (
            "rent_amount",
            ["monthly rent", "rent per month", "monthly rental", "rent amount", "rent"],
            "money",
            0.9,
        ),
        (
            "deposit_amount",
            ["security deposit", "interest free security deposit", "deposit amount", "deposit"],
            "money",
            0.88,
        ),
        ("notice_period", ["notice period", "notice"], "duration", 0.84),
    ]
    for field_name, labels, value_type, strength in mapping:
        if value_type == "money":
            field = _extract_amount_field(text, labels, field_name, strength=strength)
        else:
            field = _extract_text_field(
                text,
                labels,
                field_name,
                strength=strength,
                value_type=value_type,
                max_len=160 if field_name == "property_address" else 90,
            )
        if field:
            fields.append(field)
    return fields


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def extract_entities(
    text: str, doc_type: str = "other", *, reference_date: date | None = None
) -> ExtractionResult:
    """Extract fields, dates, amounts and named entities from document text."""
    result = ExtractionResult()
    if not text or not text.strip():
        return result

    fields: list[ExtractedField] = result.fields
    dates = find_dates(text)
    amounts = find_amounts(text)
    result.dates = dates
    result.amounts = amounts

    # Common date fields -----------------------------------------------------
    date_field_specs: list[tuple[str, list[str], float, bool]] = []
    if doc_type in {"bill", "receipt"}:
        purchase_date_labels = [
            "purchase date",
            "transaction date",
            "receipt date",
            "date of purchase",
        ]
        if doc_type == "receipt":
            purchase_date_labels.append("date")
        date_field_specs += [
            (
                "due_date",
                ["payment due date", "due date", "due on", "payable by", "pay by", "last date for payment"],
                0.95,
                False,
            ),
            (
                "invoice_date",
                ["bill date", "invoice date", "date of issue", "issued on"],
                0.92,
                False,
            ),
            (
                "purchase_date",
                purchase_date_labels,
                0.88,
                doc_type == "receipt",
            ),
        ]
    elif doc_type == "warranty":
        date_field_specs += [
            ("purchase_date", ["purchase date", "date of purchase", "invoice date", "bill date"], 0.92, False),
            ("expiry_date", ["expiry date", "warranty expiry", "valid until", "valid till", "expires on", "valid up to"], 0.94, False),
        ]
    elif doc_type == "agreement":
        date_field_specs += [
            ("start_date", ["start date", "commencement date", "effective from", "w.e.f", "lease start date"], 0.9, False),
            ("end_date", ["end date", "lease end date", "termination date", "valid until", "expires on"], 0.9, False),
            ("renewal_date", ["renewal date", "renewal on", "renew before", "renewal due date"], 0.92, False),
            ("agreement_date", ["agreement date", "date of agreement", "dated"], 0.88, False),
        ]
    elif doc_type == "certificate":
        date_field_specs += [
            ("issue_date", ["issue date", "issued on", "date of issue"], 0.92, False),
            ("expiry_date", ["expiry date", "valid until", "valid till", "expires on"], 0.92, False),
        ]
    elif doc_type == "application":
        date_field_specs += [
            ("submission_date", ["submission date", "application date", "date of application", "received on"], 0.9, False),
            ("dob", ["date of birth", "d.o.b", "dob"], 0.92, False),
        ]

    for field_name, labels, strength, allow_generic in date_field_specs:
        field = _extract_date_field(
            text,
            labels,
            field_name,
            strength=strength,
            allow_generic=allow_generic,
        )
        if field:
            fields.append(field)

    # Amount fields ----------------------------------------------------------
    if doc_type in {"bill", "receipt"}:
        amount = _extract_amount_field(
            text,
            ["total amount due", "amount due", "total payable", "net payable", "grand total", "amount payable", "total", "amount"],
            "amount_total",
            strength=0.93,
        )
        if amount is None and amounts:
            best = max(amounts, key=lambda item: item.value)
            amount = ExtractedField(
                "amount_total",
                f"{best.value:.2f}",
                "money",
                best.confidence,
                "regex",
                best.start / max(len(text), 1),
            )
        if amount:
            fields.append(amount)
    elif doc_type == "warranty":
        amount = _extract_amount_field(
            text, ["purchase price", "price", "amount paid", "mrp"], "purchase_price", strength=0.86
        )
        if amount:
            fields.append(amount)
    elif doc_type == "agreement":
        fields.extend(_extract_agreement_fields(text))

    # Reference numbers ------------------------------------------------------
    fields.extend(_extract_reference_fields(text))

    # Type-specific fields ---------------------------------------------------
    if doc_type in {"bill", "receipt"}:
        vendor = _extract_text_field(
            text,
            ["biller name", "vendor name", "merchant name", "supplier", "seller", "issued by", "vendor"],
            "vendor",
            strength=0.9,
            max_len=100,
        )
        if vendor is None:
            vendor = _guess_vendor(text)
        if vendor:
            fields.append(vendor)

    if doc_type == "warranty":
        vendor = _extract_text_field(
            text,
            ["brand", "manufacturer", "purchased from", "seller", "vendor"],
            "vendor",
            strength=0.86,
            max_len=100,
        )
        if vendor is None:
            vendor = _guess_vendor(text)
        if vendor:
            fields.append(vendor)
        product = _extract_text_field(
            text,
            ["product name", "product", "model name", "model", "item", "description"],
            "product",
            strength=0.9,
            max_len=100,
        )
        if product:
            fields.append(product)
        period = _extract_warranty_period(text)
        if period:
            fields.append(period)
        derived = _derive_warranty_expiry(fields)
        if derived and not any(f.field_name == "expiry_date" for f in fields):
            fields.append(derived)

    if doc_type == "certificate":
        holder = _extract_text_field(
            text,
            ["awarded to", "holder name", "name of candidate", "this is to certify that", "certified that"],
            "holder_name",
            strength=0.9,
            max_len=100,
        )
        if holder:
            fields.append(holder)
        issuer = _extract_text_field(
            text,
            ["issued by", "issuing authority", "issued on behalf of", "organisation", "organization"],
            "issuer",
            strength=0.88,
            max_len=120,
        )
        if issuer:
            fields.append(issuer)

    if doc_type == "application":
        fields.extend(_extract_application_fields(text))

    # Named entities (used as fallbacks and stored as generic mentions) ------
    named = extract_named_entities(text)
    result.people = [e.text for e in named if e.label == "PERSON"]
    result.organizations = [e.text for e in named if e.label == "ORG"]

    specific_values = {
        f.value.strip().lower() for f in fields if f.field_name not in {"required_document"}
    }

    if doc_type == "bill" and not any(f.field_name == "vendor" for f in fields):
        for entity in named:
            if entity.label == "ORG" and entity.text.lower() not in specific_values:
                fields.append(
                    ExtractedField(
                        "vendor",
                        entity.text,
                        "text",
                        entity.confidence,
                        "spacy",
                        round(entity.start / max(len(text), 1), 4),
                    )
                )
                break

    if doc_type == "certificate" and not any(f.field_name == "holder_name" for f in fields):
        for entity in named:
            if entity.label == "PERSON":
                fields.append(
                    ExtractedField(
                        "holder_name",
                        entity.text,
                        "person",
                        entity.confidence,
                        "spacy",
                        round(entity.start / max(len(text), 1), 4),
                    )
                )
                break

    if doc_type == "application" and not any(f.field_name == "applicant_name" for f in fields):
        for entity in named:
            if entity.label == "PERSON":
                fields.append(
                    ExtractedField(
                        "applicant_name",
                        entity.text,
                        "person",
                        entity.confidence,
                        "spacy",
                        round(entity.start / max(len(text), 1), 4),
                    )
                )
                break

    # Generic mentions (kept as searchable entities, not key-value fields) ---
    for entity in named[:12]:
        if entity.text.lower() in specific_values or entity.label == "GPE":
            continue
        field_name = "named_person" if entity.label == "PERSON" else "named_org"
        fields.append(
            ExtractedField(
                field_name,
                entity.text,
                "person" if entity.label == "PERSON" else "org",
                entity.confidence,
                "spacy",
                round(entity.start / max(len(text), 1), 4),
            )
        )

    # Category & currency for spending --------------------------------------
    if doc_type in {"bill", "receipt"}:
        vendor_value = next(
            (f.value for f in sorted(fields, key=lambda f: f.confidence, reverse=True) if f.field_name == "vendor"),
            "",
        )
        category = infer_expense_category(text, vendor_value)
        fields.append(
            ExtractedField("category", category, "text", 0.82, "rule", 0.0)
        )
        currency = amounts[0].currency if amounts else "INR"
        fields.append(
            ExtractedField("currency", currency, "currency", 0.9, "rule", 0.0)
        )

    # De-duplicate and rank fields ------------------------------------------
    multi_valued = {
        "required_document",
        "named_person",
        "named_org",
        "date_mention",
        "amount_mention",
    }
    best: dict[tuple[str, str], ExtractedField] = {}
    for item in fields:
        key = (
            item.field_name,
            item.value.lower() if item.field_name in multi_valued else "",
        )
        if key not in best or item.confidence > best[key].confidence:
            best[key] = item
    result.fields = sorted(
        best.values(), key=lambda item: (-item.confidence, item.field_name)
    )
    return result


# Convenience export for tests / callers.
__all__ = [
    "ExtractedField",
    "ExtractionResult",
    "AmountMention",
    "DateMention",
    "extract_entities",
    "extract_named_entities",
    "find_amounts",
    "find_dates",
    "parse_date_text",
]
