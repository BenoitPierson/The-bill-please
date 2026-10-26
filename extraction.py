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
from typing import Any, Dict, List, Optional, Sequence

import fitz  # PyMuPDF
from PIL import Image, ImageOps
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

# Product categories are a closed list on purpose: free-form labels drift
# ("Alimentaire", "Nourriture", "Food") and stop grouping after a few months.
PRODUCT_CATEGORIES = (
    "Alimentaire",
    "Boissons",
    "Alcool",
    "Entretien",
    "Emballage",
    "Mobilier",
    "Equipement",
    "Services",
    "Transport",
    "Autre",
)

# Units are normalised to this list so two suppliers' prices are only ever
# compared when they mean the same thing (2 EUR/kg is not 2 EUR/carton).
PRODUCT_UNITS = (
    "kg", "g", "l", "cl", "piece", "lot", "carton", "palette", "m", "m2", "heure", "jour",
)

LINE_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {
            "type": "string",
            "description": "Product description exactly as printed on the invoice line.",
        },
        "product_key": {
            "type": "string",
            "description": (
                "Generic French name of the product, lowercase, singular, with no brand, "
                "no packaging, no colour and no grade — so that the same goods sold by two "
                "suppliers under different wordings share one key. 'Red Tomatoes 5kg', "
                "'Tomates grappe' and 'TOMATO (FRESH)' all give 'tomate'. Keep a real "
                "distinction when it is one: 'tomate cerise' stays distinct from 'tomate'."
            ),
        },
        "category": {
            "type": "string",
            "enum": list(PRODUCT_CATEGORIES),
            "description": "Broad category the product belongs to. Use 'Autre' when none fits.",
        },
        "quantity": {
            "anyOf": [{"type": "number"}, {"type": "null"}],
            "description": "Quantity billed on the line, as a plain number. Null if absent.",
        },
        "unit": {
            "anyOf": [{"type": "string", "enum": list(PRODUCT_UNITS)}, {"type": "null"}],
            "description": (
                "Unit the quantity is expressed in, normalised to the list. 'Kgs', 'KG', "
                "'kilos' give 'kg'; 'pcs', 'pieces', 'each', 'unit' give 'piece'; 'ctn', "
                "'box', 'carton' give 'carton'; 'ltr', 'litres' give 'l'. Null if the "
                "invoice gives no unit at all."
            ),
        },
        "unit_price": {
            "anyOf": [{"type": "number"}, {"type": "null"}],
            "description": (
                "Price of ONE unit, as printed. If only a line total and a quantity are "
                "given, divide. Null if neither is available."
            ),
        },
        "line_total": {
            "anyOf": [{"type": "number"}, {"type": "null"}],
            "description": "Total amount for this line, as a plain number. Null if absent.",
        },
    },
    "required": ["label", "product_key", "category", "quantity", "unit", "unit_price", "line_total"],
    "additionalProperties": False,
}

INVOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": LINE_SCHEMA,
            "description": (
                "One entry per product or service line actually billed on the invoice. "
                "Empty array when the invoice shows no itemised lines. Never include "
                "subtotals, VAT lines, totals, discounts or payment lines here."
            ),
        },
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
        "uncertain_regions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "enum": list(EXTRACTED_FIELDS)},
                    "page": {"type": "integer"},
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "width": {"type": "number"},
                    "height": {"type": "number"},
                },
                "required": ["field", "page", "x", "y", "width", "height"],
                "additionalProperties": False,
            },
            "description": (
                "For each field listed in uncertain_fields, where on the document its value was "
                "read: page number (1 = first image) and a box in fractions of the page, origin "
                "top-left. Approximate is fine. Empty when uncertain_fields is empty."
            ),
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
        "lines",
        "extraction_notes",
        "uncertain_fields",
        "uncertain_regions",
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
- le detail des lignes d'articles (lines) : un element par produit ou service reellement \
facture.

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
- LIGNES D'ARTICLES (lines) : reprends chaque ligne de produit ou de service facturee, dans \
l'ordre du document. N'y mets JAMAIS les sous-totaux, la TVA, le total, les remises ou les \
lignes de reglement. Si la facture n'a pas de detail par article, renvoie un tableau vide.
- Pour chaque ligne, product_key est le nom GENERIQUE du produit en francais, en minuscules, \
au singulier, sans marque, sans conditionnement, sans couleur ni calibre : "Red Tomatoes 5kg", \
"Tomates grappe" et "TOMATO (FRESH)" donnent tous "tomate". C'est cette cle qui permet de \
comparer deux fournisseurs qui n'ecrivent pas le produit de la meme facon : elle doit donc \
etre stable d'une facture a l'autre. Garde en revanche les vraies distinctions : \
"tomate cerise" reste different de "tomate". Le champ label, lui, garde le libelle exact \
imprime sur la facture.
- unit_price est le prix d'UNE unite. Si seuls le total de ligne et la quantite figurent, \
divise l'un par l'autre. Normalise l'unite dans la liste imposee (kg, g, l, cl, piece, lot, \
carton, palette, m, m2, heure, jour) : "Kgs" et "kilos" donnent "kg", "pcs" et "each" donnent \
"piece", "ctn" et "box" donnent "carton". Sans cette normalisation, un prix au carton serait \
compare a un prix au kilo.
- Remplis uncertain_fields avec le nom de chaque champ dont tu n'es pas sur : valeur illisible, \
deduite du contexte, ambigue, ou dont l'etiquette sur le document prete a confusion. Ces champs \
seront surlignes pour relecture humaine : mieux vaut signaler un doute leger que laisser passer \
une erreur silencieuse. Laisse le tableau vide si tout est certain.
- Pour chaque champ de uncertain_fields, ajoute dans uncertain_regions la zone du document ou tu as lu la valeur : numero de page (1 pour la premiere image) et cadre en proportions de la page, de 0 a 1, origine en haut a gauche (x, y, width, height). Le cadre peut etre approximatif mais doit entourer la valeur. Laisse uncertain_regions vide si uncertain_fields est vide."""

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
    uncertain_regions: List[dict] = field(default_factory=list)
    lines: List[dict] = field(default_factory=list)
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
        # A phone photo stores its rotation in EXIF and the browser applies it.
        # Re-encoding drops the tag, so rotate the pixels first: the model must
        # see the frame the viewer shows, or its doubt boxes land elsewhere.
        rotated = img.getexif().get(0x0112, 1) not in (1, None)
        long_edge = max(img.size)
        if long_edge <= MAX_IMAGE_LONG_EDGE and not rotated:
            return image_bytes
        upright = ImageOps.exif_transpose(img) if rotated else img
        resized = upright.convert("RGB") if upright.mode not in ("RGB", "L") else upright
        if long_edge > MAX_IMAGE_LONG_EDGE:
            scale = MAX_IMAGE_LONG_EDGE / long_edge
            new_size = (max(1, int(resized.width * scale)), max(1, int(resized.height * scale)))
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


MAX_LINES_PER_INVOICE = 200


def _number(value) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def clean_lines(raw) -> List[dict]:
    """Keep only line items that can actually be compared later.

    The schema constrains the model, but a value that arrives outside the
    closed lists (or a line with no usable price) would silently pollute the
    per-product statistics, so it is normalised or dropped here.
    """
    lines: List[dict] = []
    for entry in (raw or [])[:MAX_LINES_PER_INVOICE]:
        if not isinstance(entry, dict):
            continue
        label = (entry.get("label") or "").strip()
        key = (entry.get("product_key") or "").strip().lower()
        if not label and not key:
            continue
        unit = (entry.get("unit") or "").strip().lower() or None
        category = entry.get("category")
        lines.append(
            {
                "label": label or key,
                "product_key": key or label.lower(),
                "category": category if category in PRODUCT_CATEGORIES else "Autre",
                "quantity": _number(entry.get("quantity")),
                "unit": unit if unit in PRODUCT_UNITS else None,
                "unit_price": _number(entry.get("unit_price")),
                "line_total": _number(entry.get("line_total")),
            }
        )
    return lines


def _fraction(value: Any) -> Optional[float]:
    number = _number(value)
    return None if number is None else min(1.0, max(0.0, number))


def clean_regions(raw: Any, uncertain_fields: Sequence[str], page_count: int) -> List[Dict[str, Any]]:
    """Keep only usable boxes for doubtful fields, clamped inside their page.

    The model's coordinates are approximate and unchecked: a box for a field it
    did not flag, on a page that does not exist, or with no area would draw
    something misleading on the document, so it is dropped here.
    """
    regions: List[Dict[str, Any]] = []
    if not isinstance(raw, list):
        return regions
    allowed = set(uncertain_fields)
    for entry in raw:
        if not isinstance(entry, dict) or entry.get("field") not in allowed:
            continue
        page = _number(entry.get("page"))
        if page is None or page != int(page) or not 1 <= int(page) <= page_count:
            continue
        x, y = _fraction(entry.get("x")), _fraction(entry.get("y"))
        width, height = _number(entry.get("width")), _number(entry.get("height"))
        if None in (x, y, width, height):
            continue
        width, height = min(width, 1.0 - x), min(height, 1.0 - y)
        if width <= 0 or height <= 0:
            continue
        regions.append({
            "field": entry["field"], "page": int(page),
            "x": round(x, 4), "y": round(y, 4), "width": round(width, 4), "height": round(height, 4),
        })
    return regions


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
        # Line items make the answer much longer than the header fields alone:
        # a 40-line invoice needs room for all of them or the JSON is truncated.
        max_tokens=8192,
        thinking={"type": "disabled"},
        # The system prompt is byte-identical for every invoice of a batch (the
        # learned rules are loaded once), while the images differ — the textbook
        # shared-prefix case for caching. Without it, a tenant with many learned
        # rules pays for the whole rule set on every single invoice.
        system=[
            {
                "type": "text",
                "text": build_system_prompt(rules),
                "cache_control": {"type": "ephemeral"},
            }
        ],
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
        lines=clean_lines(data.get("lines")),
        filename=filename,
        supplier_name=data.get("supplier_name"),
        invoice_number=data.get("invoice_number"),
        invoice_date=data.get("invoice_date"),
        total_amount=data.get("total_amount"),
        currency=data.get("currency"),
        vat_amount=data.get("vat_amount"),
        extraction_notes=data.get("extraction_notes"),
        uncertain_fields=[f for f in uncertain if f in EXTRACTED_FIELDS],
        uncertain_regions=clean_regions(
            data.get("uncertain_regions"), [f for f in uncertain if f in EXTRACTED_FIELDS], len(pages)
        ),
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
