"""Import pipeline: uploads -> stored originals -> extracted rows in the database.

Runs in a background thread so a large archive (the reference dataset holds
~1180 invoices, roughly 35 minutes of API calls) does not sit inside an HTTP
request. The browser starts the import, then polls the batch for progress.
"""
from __future__ import annotations

import logging
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

from anthropic import Anthropic

import db
import learning
import tenants
from config import MAX_CONCURRENT_EXTRACTIONS
from extraction import InvoiceResult, InvoiceSource, expand_upload, process_upload

logger = logging.getLogger("uvicorn.error")

# Guards against launching a second import for a tenant while one is running:
# concurrent batches would multiply API concurrency and blow past rate limits.
_running_imports = set()
_lock = threading.Lock()


def is_importing(slug: str) -> bool:
    with _lock:
        return slug in _running_imports


def _store_original(slug: str, invoice_id: str, filename: str, content: bytes) -> str:
    """Keep the original document so the user can open it from the table."""
    extension = os.path.splitext(filename)[1].lower()[:10]
    stored_name = "{}{}".format(invoice_id, extension)
    destination = tenants.files_dir(slug) / stored_name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return stored_name


def _process_one(
    client: Anthropic, slug: str, batch_id: str, source: InvoiceSource, rules: List[str]
) -> bool:
    """Extract a single invoice and persist it. Returns True on failure."""
    invoice_id = uuid.uuid4().hex

    if source.skip_reason is not None:
        db.insert_invoice(
            slug,
            {
                "id": invoice_id,
                "batch_id": batch_id,
                "archive": source.archive,
                "filename": source.filename,
                "error": source.skip_reason,
            },
        )
        return True

    try:
        content = source.read()
    except Exception as exc:  # noqa: BLE001 - one bad entry must not stop the batch
        db.insert_invoice(
            slug,
            {
                "id": invoice_id,
                "batch_id": batch_id,
                "archive": source.archive,
                "filename": source.filename,
                "error": "Lecture impossible depuis l'archive : {}".format(exc),
            },
        )
        return True

    stored_name: Optional[str] = None
    try:
        stored_name = _store_original(slug, invoice_id, source.filename, content)
    except OSError as exc:
        logger.warning("[%s] original non conserve pour %s : %s", slug, source.filename, exc)

    result: InvoiceResult = process_upload(
        client, source.filename, content, source.content_type, rules=rules
    )

    db.insert_invoice(
        slug,
        {
            "id": invoice_id,
            "batch_id": batch_id,
            "archive": source.archive,
            "filename": source.filename,
            "stored_name": stored_name,
            "content_type": source.content_type,
            "supplier_name": result.supplier_name,
            "invoice_number": result.invoice_number,
            "invoice_date": result.invoice_date,
            "total_amount": result.total_amount,
            "currency": result.currency,
            "vat_amount": result.vat_amount,
            "extraction_notes": result.extraction_notes,
            "error": result.error,
            "page_count": result.page_count,
            "uncertain_fields": result.uncertain_fields,
        },
    )
    return result.error is not None


def _run_batch(client: Anthropic, slug: str, batch_id: str, sources: List[InvoiceSource]) -> None:
    rules = learning.rules_for_prompt(slug)
    if rules:
        logger.info("[%s] extraction avec %d regle(s) apprise(s)", slug, len(rules))

    try:
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_EXTRACTIONS) as pool:
            futures = [
                pool.submit(_process_one, client, slug, batch_id, source, rules)
                for source in sources
            ]
            done = 0
            for future in as_completed(futures):
                try:
                    failed = future.result()
                except Exception as exc:  # noqa: BLE001 - defensive: never lose the batch
                    logger.exception("[%s] echec inattendu : %s", slug, exc)
                    failed = True
                db.bump_batch(slug, batch_id, failed)
                done += 1
                if done % 10 == 0 or done == len(sources):
                    logger.info("[%s] factures traitees : %d/%d", slug, done, len(sources))
        db.finish_batch(slug, batch_id, "done")
    except Exception as exc:  # noqa: BLE001
        logger.exception("[%s] import interrompu : %s", slug, exc)
        db.finish_batch(slug, batch_id, "error")
    finally:
        with _lock:
            _running_imports.discard(slug)


def start_import(client: Anthropic, slug: str, uploads: List[tuple]) -> dict:
    """Expand uploads and kick off extraction in the background.

    `uploads` is a list of (filename, content_bytes, content_type).
    Returns {"batch_id", "total"} or {"error"}.
    """
    with _lock:
        if slug in _running_imports:
            return {"error": "Un import est deja en cours pour ce compte."}
        _running_imports.add(slug)

    try:
        sources: List[InvoiceSource] = []
        for filename, content, content_type in uploads:
            sources.extend(expand_upload(filename or "sans_nom", content, content_type))

        if not sources:
            with _lock:
                _running_imports.discard(slug)
            return {"error": "Aucune facture exploitable dans les fichiers deposes."}

        label = ", ".join(name for name, _, _ in uploads)[:200]
        batch_id = db.create_batch(slug, label, len(sources))
        logger.info("[%s] import de %d facture(s) demarre", slug, len(sources))

        thread = threading.Thread(
            target=_run_batch,
            args=(client, slug, batch_id, sources),
            name="import-{}".format(slug),
            daemon=True,
        )
        thread.start()
        return {"batch_id": batch_id, "total": len(sources)}
    except Exception:
        with _lock:
            _running_imports.discard(slug)
        raise
