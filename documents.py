"""Stored originals as pages: how many there are, and one of them as a PNG.

Feeds the invoice viewer, which shows a page image with the doubtful areas
drawn over it. Kept apart from app.py so it can be tested without a server.
"""
from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def page_count(path: Path) -> int:
    """Pages in a stored original: a PDF's page count, 1 for a photo, 0 otherwise."""
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return 1 if path.is_file() else 0
    if suffix != ".pdf" or not path.is_file():
        return 0
    try:
        with fitz.open(str(path)) as doc:
            return doc.page_count
    except Exception:  # noqa: BLE001 - an unreadable file simply has no pages to show
        return 0


def render_page_png(path: Path, page: int, dpi: int = 200) -> bytes:
    """One page of a PDF (1-based), rendered as PNG bytes."""
    with fitz.open(str(path)) as doc:
        return doc[page - 1].get_pixmap(dpi=dpi).tobytes("png")
