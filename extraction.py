"""Core logic: turn an uploaded invoice (PDF or image) into structured data
using the Claude API (vision + structured outputs), then build an Excel report.
"""
from __future__ import annotations

import base64
import io
import json
import os
import posixpath
import zipfile
from dataclasses import dataclass, field
from typing import List, Optional

import fitz  # PyMuPDF
from PIL import Image
from anthropic import Anthropic

MODEL = "claude-sonnet-5"
PDF_RENDER_DPI = 150
MAX_IMAGE_LONG_EDGE = 2000  # caps token cost for large phone photos
MAX_PAGES_PER_INVOICE = 5

INVOICE_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}
ARCHIVE_EXTENSIONS = {".zip"}
MAX_ARCHIVE_DEPTH = 3  # allows archives nested inside archives, without looping forever

# The fields the model fills in, in the order they are shown to the user.
EXTRACTED_FIELDS = (
    "supplier_name",
    "invoice_number",
    "invoice_date",
    "total_amount",
    "currency",
    "vat_amount",
)

INVOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "supplier_name": {
            "type": "string",
            "description": "Name of the company or person issuing the invoice.",
        },
        "invoice_number": {
            "type": "string",
            "description": (
                "The invoice number (e.g. labeled 'Invoice Number', 'CV Invoice Number', "
                "'Numero de facture'), exactly as printed or written. This is NOT the same "
                "as a 'Receipt Number' — if both appear on the document, use the invoice "
                "number and ignore the receipt number."
            ),
        },
        "invoice_date": {
            "type": "string",
            "description": (
                "Invoice date, ALWAYS normalized to YYYY-MM-DD (e.g. 2026-03-05), "
                "regardless of how it was originally written (DD/MM/YYYY, MM/DD/YYYY, "
                "'5 mars 2026', 'March 5, 2026', etc.). Never return the raw/original "
                "format. If the day/month order is genuinely ambiguous, make the best "
                "guess from context (invoice language/country, other dates on the "
                "document) and flag the uncertainty in extraction_notes."
            ),
        },
        "total_amount": {
            "anyOf": [{"type": "number"}, {"type": "null"}],
            "description": "Total amount due, as a plain number (no currency symbol, '.' as decimal separator).",
        },
        "currency": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": (
                "Currency as an ISO 4217 three-letter code (EUR, USD, KES, GBP...), "
                "normalized from however it is written on the invoice — 'Ksh', 'KShs', "
                "'SHS' and 'K.Sh' are all KES; '€' is EUR; '$' is USD unless the "
                "document points to another dollar. Null if no currency can be "
                "determined at all."
            ),
        },
        "vat_amount": {
            "anyOf": [{"type": "number"}, {"type": "null"}],
            "description": "VAT / TVA amount as a plain number if present on the invoice, otherwise null.",
        },
        "extraction_notes": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": "Short note about anything illegible, ambiguous, or uncertain. Null if nothing to flag.",
        },
        "uncertain_fields": {
            "type": "array",
            "items": {"type": "string", "enum": list(EXTRACTED_FIELDS)},
            "description": (
                "Names of the fields above whose value you are NOT confident about — "
                "illegible, ambiguous, guessed from context, or possibly mislabelled on "
                "the document. Empty array when every value is certain. These fields are "
                "highlighted for human review, so list a field whenever a human should "
                "double-check it."
            ),
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
        "uncertain_fields",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """Tu es un assistant specialise dans l'extraction de donnees de factures \
professionnelles. On te fournit une ou plusieurs images representant les pages d'UNE SEULE \
facture. Les factures peuvent etre en francais ou en anglais, imprimees ou manuscrites, et \
organisees sous forme de tableau (lignes d'articles, recapitulatif des totaux, etc.).

Analyse attentivement toutes les images fournies (y compris les tableaux) et extrait :
- le nom du fournisseur (l'entreprise ou la personne qui EMET la facture, pas le client) ;
- le numero de facture (INVOICE NUMBER) ;
- la date de la facture ;
- le montant total TTC ;
- la devise ;
- le montant de la TVA (VAT), si elle est mentionnee ;

Regles importantes :
- Les montants doivent etre des nombres (pas de texte, pas de symbole monetaire), avec un \
point comme separateur decimal. Convertis les formats europeens ("1 234,56" ou "1.234,56") \
en nombre standard (1234.56).
- La date de facture doit TOUJOURS etre convertie au format AAAA-MM-JJ (ex: 2026-03-05), \
quel que soit son format d'origine (JJ/MM/AAAA, MM/JJ/AAAA, "5 mars 2026", "March 5, 2026", \
etc.) : ne renvoie jamais la date telle qu'ecrite sur la facture. Si l'ordre jour/mois est \
reellement ambigu, deduis-le du contexte (langue/pays de la facture, autres dates presentes \
sur le document) et signale ton incertitude dans extraction_notes plutot que de laisser le \
format d'origine.
- La devise doit TOUJOURS etre renvoyee sous forme de code ISO 4217 a trois lettres \
(EUR, USD, KES, GBP...), quelle que soit son ecriture sur la facture : "Ksh", "KShs", \
"SHS", "K.Sh" donnent tous KES ; "€" donne EUR ; "$" donne USD sauf indication contraire. \
Sans cette normalisation, les totaux par devise deviennent inexploitables.
- Sur une facture multi-pages, le total et la TVA se trouvent generalement dans le \
recapitulatif final : verifie toutes les pages avant de conclure.
- Si un champ est illisible, absent, ou incertain, mets null et explique brievement pourquoi \
dans extraction_notes (mets null dans extraction_notes s'il n'y a rien a signaler).
- Ne confonds jamais le fournisseur (emetteur) avec le client (destinataire) de la facture.
- NE CONFONDS PAS le numero de facture (INVOICE NUMBER, parfois intitule "CV INVOICE NUMBER") \
avec le RECEIPT NUMBER (numero de recu/reçu) : ce sont deux identifiants differents qui \
peuvent tous les deux apparaitre sur le meme document. Le champ invoice_number doit \
toujours contenir le numero de facture (INVOICE NUMBER / CV INVOICE NUMBER), jamais le \
RECEIPT NUMBER, meme si le RECEIPT NUMBER est plus visible ou plus proche du haut de page.
- Remplis uncertain_fields avec le nom de chaque champ dont tu n'es pas sur : valeur illisible, \
deduite du contexte, ambigue, ou dont l'etiquette sur le document prete a confusion. Ces champs \
seront surlignes pour relecture humaine : mieux vaut signaler un doute leger que laisser passer \
une erreur silencieuse. Laisse le tableau vide si tout est certain."""

RULES_HEADER = """

REGLES APPRISES DES CORRECTIONS DE L'UTILISATEUR
Ces regles viennent de corrections deja apportees a la main sur des factures precedentes.
Elles decrivent ce que l'utilisateur attend reellement : applique-les en priorite sur les \
consignes generales ci-dessus quand elles concernent la facture en cours."""

USER_INSTRUCTION = (
    "Voici les pages d'une facture. Extrait les informations demandees au format JSON."
)


def build_system_prompt(rules: Optional[List[str]] = None) -> str:
    """System prompt, extended with the rules learned from user corrections."""
    if not rules:
        return SYSTEM_PROMPT
    lines = "\n".join("- {}".format(rule) for rule in rules)
    return "{}{}\n{}".format(SYSTEM_PROMPT, RULES_HEADER, lines)


@dataclass
class InvoiceResult:
    filename: str
    archive: str | None = None  # name of the .zip the invoice came from, if any
    supplier_name: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = None
    total_amount: float | None = None
    currency: str | None = None
    vat_amount: float | None = None
    extraction_notes: str | None = None
    uncertain_fields: List[str] = field(default_factory=list)
    error: str | None = None
    page_count: int = 0


@dataclass
class InvoiceSource:
    """One invoice to process, with a lazy handle on its bytes.

    An uploaded archive can hold hundreds of invoices, so the bytes are read
    only when a worker actually picks the invoice up — the whole archive is
    never decompressed into memory at once. `archive_bytes` is shared (and
    never mutated) across every source of the same archive.
    """

    filename: str
    content_type: Optional[str] = None
    archive: Optional[str] = None
    data: Optional[bytes] = None
    archive_bytes: Optional[bytes] = None
    member: Optional[str] = None
    skip_reason: Optional[str] = None

    def read(self) -> bytes:
        if self.data is not None:
            return self.data
        # A fresh ZipFile per call: zipfile handles are not thread-safe, but the
        # underlying bytes are immutable so wrapping them is cheap and safe.
        with zipfile.ZipFile(io.BytesIO(self.archive_bytes)) as archive:
            return archive.read(self.member)


def _is_archive(filename: str, content_type: Optional[str]) -> bool:
    if os.path.splitext(filename)[1].lower() in ARCHIVE_EXTENSIONS:
        return True
    return content_type in ("application/zip", "application/x-zip-compressed")


def _is_junk_entry(member: str) -> bool:
    """Filter out archive noise: OS metadata and hidden files."""
    if member.startswith("__MACOSX/") or "/__MACOSX/" in member:
        return True
    basename = posixpath.basename(member)
    return not basename or basename.startswith(".") or basename == "Thumbs.db"


def _expand_archive(
    archive_name: str, archive_bytes: bytes, depth: int = 1
) -> List[InvoiceSource]:
    """List the invoices held in a .zip, recursing into nested archives."""
    sources: List[InvoiceSource] = []
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            members = [m for m in archive.infolist() if not m.is_dir()]
            nested: List[tuple] = []
            for member in members:
                name = member.filename
                if _is_junk_entry(name):
                    continue

                extension = os.path.splitext(name)[1].lower()
                if extension in INVOICE_EXTENSIONS:
                    sources.append(
                        InvoiceSource(
                            filename=name,
                            archive=archive_name,
                            archive_bytes=archive_bytes,
                            member=name,
                        )
                    )
                elif extension in ARCHIVE_EXTENSIONS:
                    if depth < MAX_ARCHIVE_DEPTH:
                        nested.append((name, archive.read(name)))
                    else:
                        sources.append(
                            InvoiceSource(
                                filename=name,
                                archive=archive_name,
                                skip_reason="Archive trop imbriquee : non exploree.",
                            )
                        )
                else:
                    # Reported rather than dropped, so nothing disappears silently.
                    sources.append(
                        InvoiceSource(
                            filename=name,
                            archive=archive_name,
                            skip_reason="Format non pris en charge (ni PDF, ni image).",
                        )
                    )
    except zipfile.BadZipFile as exc:
        return [
            InvoiceSource(
                filename=archive_name,
                skip_reason="Archive illisible ou corrompue : {}".format(exc),
            )
        ]

    for nested_name, nested_bytes in nested:
        label = "{} > {}".format(archive_name, nested_name)
        sources.extend(_expand_archive(label, nested_bytes, depth + 1))

    if not sources:
        return [
            InvoiceSource(
                filename=archive_name,
                skip_reason="Aucune facture (PDF ou image) trouvee dans l'archive.",
            )
        ]

    sources.sort(key=lambda s: s.filename)
    return sources


def expand_upload(
    filename: str, content_bytes: bytes, content_type: Optional[str]
) -> List[InvoiceSource]:
    """Turn one upload into the list of invoices it contains.

    A PDF or photo yields a single invoice; a .zip yields one per document
    found inside it.
    """
    if _is_archive(filename, content_type):
        return _expand_archive(filename, content_bytes)
    return [InvoiceSource(filename=filename, content_type=content_type, data=content_bytes)]


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


def extract_invoice(
    client: Anthropic,
    filename: str,
    pages: list[tuple[bytes, str]],
    rules: Optional[List[str]] = None,
) -> InvoiceResult:
    if not pages:
        return InvoiceResult(filename=filename, error="Aucune page/image exploitable dans ce fichier.")

    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        thinking={"type": "disabled"},
        system=build_system_prompt(rules),
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

    uncertain = data.get("uncertain_fields") or []
    return InvoiceResult(
        filename=filename,
        supplier_name=data.get("supplier_name"),
        invoice_number=data.get("invoice_number"),
        invoice_date=data.get("invoice_date"),
        total_amount=data.get("total_amount"),
        currency=data.get("currency"),
        vat_amount=data.get("vat_amount"),
        extraction_notes=data.get("extraction_notes"),
        uncertain_fields=[f for f in uncertain if f in EXTRACTED_FIELDS],
        page_count=len(pages),
    )


def process_upload(
    client: Anthropic,
    filename: str,
    content_bytes: bytes,
    content_type: str | None,
    rules: Optional[List[str]] = None,
) -> InvoiceResult:
    try:
        pages = file_to_page_images(filename, content_bytes, content_type)
    except Exception as exc:  # noqa: BLE001 - surface any parsing failure per-file
        return InvoiceResult(filename=filename, error=f"Impossible de lire le fichier : {exc}")

    try:
        return extract_invoice(client, filename, pages, rules=rules)
    except Exception as exc:  # noqa: BLE001 - keep batch processing resilient
        return InvoiceResult(filename=filename, error=f"Erreur API : {exc}", page_count=len(pages))
