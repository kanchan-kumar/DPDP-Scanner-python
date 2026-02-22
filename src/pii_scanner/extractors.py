"""File text extraction layer for supported scanner input types."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

try:
    import PyPDF2
except ImportError:  # pragma: no cover - optional runtime module
    PyPDF2 = None

try:
    import docx
except ImportError:  # pragma: no cover - optional runtime module
    docx = None

try:
    from PIL import Image
except ImportError:  # pragma: no cover - optional runtime module
    Image = None

try:
    import pytesseract
except ImportError:  # pragma: no cover - optional runtime module
    pytesseract = None


def read_text(path: Path) -> str:
    """Read UTF-8-ish text from disk with a tolerant decoder."""
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        return handle.read()


def extract_text_from_pdf(path: Path, max_pages: int) -> str:
    """Extract text from PDF pages up to a configured page limit."""
    if PyPDF2 is None:
        raise RuntimeError("PyPDF2 is not installed but PDF scanning is enabled")
    text_parts: List[str] = []
    with path.open("rb") as handle:
        reader = PyPDF2.PdfReader(handle)
        for index, page in enumerate(reader.pages):
            if index >= max_pages:
                break
            text_parts.append(page.extract_text() or "")
    return "\n".join(text_parts)


def extract_text_from_docx(path: Path) -> str:
    """Extract text content from DOCX paragraph runs."""
    if docx is None:
        raise RuntimeError("python-docx is not installed but DOCX scanning is enabled")
    document = docx.Document(str(path))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def extract_text_from_image(path: Path) -> str:
    """Extract OCR text from image files."""
    if Image is None or pytesseract is None:
        raise RuntimeError("Pillow/pytesseract not installed but image OCR is enabled")
    with Image.open(str(path)) as image:
        return pytesseract.image_to_string(image)


def extract_text(path: Path, scan_cfg: Dict[str, Any]) -> str:
    """
    Dispatch extraction by file extension.

    Unknown file types can optionally be decoded as text when configured.
    """
    ext = path.suffix.lower()

    if ext == ".pdf":
        max_pages = int(scan_cfg.get("pdf_max_pages", 50))
        return extract_text_from_pdf(path, max_pages=max_pages)

    if ext == ".docx":
        return extract_text_from_docx(path)

    if ext in {".png", ".jpg", ".jpeg"}:
        if not scan_cfg.get("ocr_images", False):
            return ""
        return extract_text_from_image(path)

    if ext in {".txt", ".csv", ".json", ".log", ".md", ".xml", ".yaml", ".yml"}:
        return read_text(path)

    if scan_cfg.get("read_binary_files_as_text", False):
        with path.open("rb") as handle:
            return handle.read().decode("utf-8", errors="ignore")

    return ""

