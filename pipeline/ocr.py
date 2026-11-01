"""Text extraction from PDFs and images.

Text-based PDFs are read with pdfplumber.  When a PDF has little or no text
layer (a scan), we render pages with pdf2image and run Tesseract OCR.  Images
are OCR'd directly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pdfplumber
import pytesseract
from pdf2image import convert_from_path
from PIL import Image

from lifepilot import config

if config.TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD

TEXT_PDF_MIN_CHARS = 60
OCR_DPI = 300
MAX_PDF_PAGES = 20

SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".txt"}


@dataclass
class TextExtractionResult:
    text: str
    method: str  # pdf_text | ocr | plain_text | failed
    page_count: int = 0
    confidence: float = 0.0
    warnings: list[str] = field(default_factory=list)


@lru_cache(maxsize=1)
def ocr_available() -> bool:
    """Check that the Tesseract binary can be found."""
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _clean_text(text: str) -> str:
    """Normalise line endings and excessive whitespace for downstream regex."""
    text = text.replace("\x0c", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.splitlines()).strip()


def _ocr_image(image: Image.Image) -> str:
    if not ocr_available():
        raise RuntimeError(
            "Tesseract OCR is not installed or not on PATH. "
            "Install it from https://github.com/UB-Mannheim/tesseract/wiki."
        )
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    return pytesseract.image_to_string(image, config="--psm 3")


def _extract_pdf(path: Path) -> TextExtractionResult:
    warnings: list[str] = []
    pages: list[str] = []
    try:
        with pdfplumber.open(str(path)) as pdf:
            page_count = len(pdf.pages)
            for page in pdf.pages[:MAX_PDF_PAGES]:
                pages.append(page.extract_text() or "")
    except Exception as exc:  # corrupt/encrypted PDF
        return TextExtractionResult(
            text="", method="failed", confidence=0.0, warnings=[f"PDF read error: {exc}"]
        )

    text = _clean_text("\n\n".join(pages))
    if len(text) >= TEXT_PDF_MIN_CHARS:
        avg_chars = len(text) / max(1, min(page_count, MAX_PDF_PAGES))
        confidence = 0.97 if avg_chars > 200 else 0.85
        if page_count > MAX_PDF_PAGES:
            warnings.append(f"Only the first {MAX_PDF_PAGES} pages were read.")
        return TextExtractionResult(
            text=text,
            method="pdf_text",
            page_count=page_count,
            confidence=confidence,
            warnings=warnings,
        )

    # Scanned PDF fallback.
    if not ocr_available():
        warnings.append(
            "The PDF appears to be scanned but Tesseract is not installed. "
            "Install Tesseract and try again, or upload a text-based PDF."
        )
        return TextExtractionResult(
            text=text, method="failed", page_count=page_count, confidence=0.0, warnings=warnings
        )

    try:
        images = convert_from_path(
            str(path),
            dpi=OCR_DPI,
            first_page=1,
            last_page=MAX_PDF_PAGES,
            poppler_path=config.POPPLER_PATH or None,
        )
        ocr_pages = [_ocr_image(image) for image in images]
        text = _clean_text("\n\n".join(ocr_pages))
        return TextExtractionResult(
            text=text,
            method="ocr",
            page_count=page_count,
            confidence=0.72 if text else 0.0,
            warnings=warnings,
        )
    except Exception as exc:
        warnings.append(f"OCR failed: {exc}")
        return TextExtractionResult(
            text=text, method="failed", page_count=page_count, confidence=0.0, warnings=warnings
        )


def _extract_image(path: Path) -> TextExtractionResult:
    warnings: list[str] = []
    try:
        with Image.open(path) as image:
            text = _clean_text(_ocr_image(image))
        return TextExtractionResult(
            text=text,
            method="ocr" if text else "failed",
            page_count=1,
            confidence=0.70 if text else 0.0,
            warnings=warnings,
        )
    except Exception as exc:
        return TextExtractionResult(
            text="", method="failed", confidence=0.0, warnings=[f"Image OCR failed: {exc}"]
        )


def extract_text(file_path: str | Path) -> TextExtractionResult:
    """Extract text from a PDF, image or plain-text file.

    Never raises for extraction problems: inspect ``method``, ``text`` and
    ``warnings`` on the result instead.
    """
    path = Path(file_path)
    if not path.exists():
        return TextExtractionResult(
            text="", method="failed", warnings=[f"File not found: {path}"]
        )

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(path)
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        return _extract_image(path)
    if suffix in {".txt", ".md"}:
        try:
            return TextExtractionResult(
                text=_clean_text(path.read_text(encoding="utf-8")),
                method="plain_text",
                page_count=1,
                confidence=1.0,
            )
        except Exception as exc:
            return TextExtractionResult(
                text="", method="failed", warnings=[f"File read error: {exc}"]
            )
    return TextExtractionResult(
        text="",
        method="failed",
        warnings=[f"Unsupported file type: {suffix or 'unknown'}"],
    )
