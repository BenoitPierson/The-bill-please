"""Core logic: turn an uploaded invoice (PDF or image) into structured data
using the Claude API (vision + structured outputs), then build an Excel report.
"""
from __future__ import annotations

import base64
import io
import json
import os
from dataclasses import dataclass, field

import fitz  # PyMuPDF
from PIL import Image
from anthropic import Anthropic

MODEL = "claude-sonnet-5"
PDF_RENDER_DPI = 150
MAX_IMAGE_LONG_EDGE = 2000  # caps token cost for large phone photos
MAX_PAGES_PER_INVOICE = 5

INVOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "supplier_name": {
            "type": "string",
            "description": "Name of the company or person issuing the invoice.",
        },
        "invoice_number": {
            "type": "string",
            "description": "Invoice number / reference exactly as printed or written.",
        },
        "invoice_date": {
            "type": "string",
            "description": (
                "Invoice date normalized to YYYY-MM-DD if it can be determined "
                "unambiguously; otherwise the date exactly as written on the invoice."
            ),
        },
        "total_amount": {
            "anyOf": [{"type": "number"}, {"type": "null"}],
            "description": "Total amount due, as a plain number (no currency symbol, '.' as decimal separator).",
        },
        "currency": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": "Currency code or symbol found on the invoice (e.g. EUR, USD, €, $).",
        },
        "vat_amount": {
            "anyOf": [{"type": "number"}, {"type": "null"}],
            "description": "VAT / TVA amount as a plain number if present on the invoice, otherwise null.",
        },
        "extraction_notes": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": "Short note about anything illegible, ambiguous, or uncertain. Null if nothing to flag.",
        },
    },
    "required": [
        "supplier_name",
        "invoice_number",
        "invoice_date",
        "total_amount",
        "currency",
        "vat_amount",
        "extraction_notes",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """Tu es un assistant specialise dans l'extraction de donnees de factures \
professionnelles. On te fournit une ou plusieurs images representant les pages d'UNE SEULE \
facture. Les factures peuvent etre en francais ou en anglais, imprimees ou manuscrites, et \
organisees sous forme de tableau (lignes d'articles, recapitulatif des totaux, etc.).

Analyse attentivement toutes les images fournies (y compris les tableaux) et extrait :
- le nom du fournisseur (l'entreprise ou la personne qui EMET la facture, pas le client) ;
- le numero de facture ;
- la date de la facture ;
- le montant total TTC ;
- la devise ;
- le montant de la TVA (VAT), si elle est mentionnee ;

Regles importantes :
- Les montants doivent etre des nombres (pas de texte, pas de symbole monetaire), avec un \
point comme separateur decimal. Convertis les formats europeens ("1 234,56" ou "1.234,56") \
en nombre standard (1234.56).
- Normalise la date au format AAAA-MM-JJ si elle est determinable sans ambiguite ; sinon \
recopie-la telle qu'ecrite.
- Sur une facture multi-pages, le total et la TVA se trouvent generalement dans le \
recapitulatif final : verifie toutes les pages avant de conclure.
- Si un champ est illisible, absent, ou incertain, mets null et explique brievement pourquoi \
dans extraction_notes (mets null dans extraction_notes s'il n'y a rien a signaler).
- Ne confonds jamais le fournisseur (emetteur) avec le client (destinataire) de la facture."""

USER_INSTRUCTION = (
    "Voici les pages d'une facture. Extrait les informations demandees au format JSON."
)


@dataclass
class InvoiceResult:
    filename: str
    supplier_name: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = None
    total_amount: float | None = None
    currency: str | None = None
    vat_amount: float | None = None
    extraction_notes: str | None = None
    error: str | None = None
    page_count: int = 0


def _resize_if_needed(image_bytes: bytes, fmt: str) -> bytes:
    with Image.open(io.BytesIO(image_bytes)) as img:
        long_edge = max(img.size)
        if long_edge <= MAX_IMAGE_LONG_EDGE:
            return image_bytes
        scale = MAX_IMAGE_LONG_EDGE / long_edge
        new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
        resized = img.convert("RGB") if img.mode not in ("RGB", "L") else img
        resized = resized.resize(new_size, Image.LANCZOS)
        buf = io.BytesIO()
        resized.save(buf, format=fmt)
        return buf.getvalue()


def _pdf_to_page_images(pdf_bytes: bytes) -> list[tuple[bytes, str]]:
    """Rasterize each PDF page to PNG bytes. Returns list of (bytes, media_type)."""
    pages: list[tuple[bytes, str]] = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            if len(pages) >= MAX_PAGES_PER_INVOICE:
                break
            pix = page.get_pixmap(dpi=PDF_RENDER_DPI)
            png_bytes = pix.tobytes("png")
            png_bytes = _resize_if_needed(png_bytes, "PNG")
            pages.append((png_bytes, "image/png"))
    return pages


def _photo_to_image(content_bytes: bytes, content_type: str | None, filename: str) -> tuple[bytes, str]:
    ext = os.path.splitext(filename)[1].lower()
    if content_type in ("image/jpeg", "image/jpg") or ext in (".jpg", ".jpeg"):
        media_type, fmt = "image/jpeg", "JPEG"
    elif content_type == "image/webp" or ext == ".webp":
        media_type, fmt = "image/webp", "WEBP"
    else:
        media_type, fmt = "image/png", "PNG"
    return _resize_if_needed(content_bytes, fmt), media_type


def file_to_page_images(filename: str, content_bytes: bytes, content_type: str | None) -> list[tuple[bytes, str]]:
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf" or content_type == "application/pdf":
        return _pdf_to_page_images(content_bytes)
    img_bytes, media_type = _photo_to_image(content_bytes, content_type, filename)
    return [(img_bytes, media_type)]


def _build_content_blocks(pages: list[tuple[bytes, str]]) -> list[dict]:
    blocks: list[dict] = []
    for img_bytes, media_type in pages:
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.standard_b64encode(img_bytes).decode("utf-8"),
                },
            }
        )
    blocks.append({"type": "text", "text": USER_INSTRUCTION})
    return blocks


def extract_invoice(client: Anthropic, filename: str, pages: list[tuple[bytes, str]]) -> InvoiceResult:
    if not pages:
        return InvoiceResult(filename=filename, error="Aucune page/image exploitable dans ce fichier.")

    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        thinking={"type": "disabled"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_content_blocks(pages)}],
        # The installed SDK (0.72.0) predates typed `output_config` support;
        # extra_body passes it through to the API as raw JSON regardless.
        extra_body={"output_config": {"format": {"type": "json_schema", "schema": INVOICE_SCHEMA}}},
    )

    if response.stop_reason == "refusal":
        return InvoiceResult(filename=filename, error="Extraction refusee par le modele.", page_count=len(pages))

    text_block = next((b for b in response.content if b.type == "text"), None)
    if text_block is None:
        return InvoiceResult(filename=filename, error="Reponse vide du modele.", page_count=len(pages))

    try:
        data = json.loads(text_block.text)
    except json.JSONDecodeError as exc:
        return InvoiceResult(filename=filename, error=f"JSON invalide: {exc}", page_count=len(pages))

    return InvoiceResult(
        filename=filename,
        supplier_name=data.get("supplier_name"),
        invoice_number=data.get("invoice_number"),
        invoice_date=data.get("invoice_date"),
        total_amount=data.get("total_amount"),
        currency=data.get("currency"),
        vat_amount=data.get("vat_amount"),
        extraction_notes=data.get("extraction_notes"),
        page_count=len(pages),
    )


def process_upload(client: Anthropic, filename: str, content_bytes: bytes, content_type: str | None) -> InvoiceResult:
    try:
        pages = file_to_page_images(filename, content_bytes, content_type)
    except Exception as exc:  # noqa: BLE001 - surface any parsing failure per-file
        return InvoiceResult(filename=filename, error=f"Impossible de lire le fichier : {exc}")

    try:
        return extract_invoice(client, filename, pages)
    except Exception as exc:  # noqa: BLE001 - keep batch processing resilient
        return InvoiceResult(filename=filename, error=f"Erreur API : {exc}", page_count=len(pages))
