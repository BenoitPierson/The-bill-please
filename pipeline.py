"""Import pipeline: uploads -> stored originals -> extracted rows in the database.

Runs in a background thread so a large archive (the reference dataset holds
~1180 invoices, roughly 35 minutes of API calls) does not sit inside an HTTP
request. The browser starts the import, then polls the batch for progress.

Every document is fingerprinted (SHA-256 of its bytes) before anything is
stored or sent to Claude. A document already imported — in an earlier batch, or
earlier in the same one — is skipped and logged as a duplicate: on the
reference dataset 39 of 1181 files are exact copies, several of them the same
invoice filed in two monthly archives, which would otherwise be stored twice,
paid for twice and counted twice in the Dashboard totals.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

from anthropic import Anthropic

import db
import learning
import tenants
from config import MAX_CONCURRENT_EXTRACTIONS
from extraction import InvoiceResult, InvoiceSource, expand_upload, process_upload

logger = logging.getLogger("uvicorn.error")

OK, FAILED, DUPLICATE = "ok", "failed", "duplicate"

# Guards against launching a second import for a tenant while one is running:
# concurrent batches would multiply API concurrency and blow past rate limits,
# and would let two copies of a document race past deduplication.
_running_imports = set()
_lock = threading.Lock()


def is_importing(slug: str) -> bool:
    with _lock:
        return slug in _running_imports


class _BatchState:
    """What the parallel workers of one batch must agree on."""

    def __init__(self, slug: str) -> None:
        self.lock = threading.Lock()
        # fingerprint -> invoice id, for copies appearing within this batch
        # (the database only sees the first copy once it has been extracted).
        self.claimed: Dict[str, str] = {}
        self.quota_bytes = tenants.storage_quota_bytes(slug)
        self.used_bytes = tenants.storage_usage(slug)["total_bytes"]


def _can_retry(existing) -> bool:
    """A failed, untouched import of the same document may be replaced.

    Re-importing a file whose extraction errored (API overload, timeout) is how
    a user retries it; treating that as a duplicate would make the failure
    permanent. A row the user has edited is kept, error or not.
    """
    return existing["error"] is not None and json.loads(existing["edited_fields"] or "[]") == []


def _store_original(slug: str, invoice_id: str, filename: str, content: bytes) -> str:
    """Keep the original document so the user can open it from the table."""
    extension = os.path.splitext(filename)[1].lower()[:10]
    stored_name = "{}{}".format(invoice_id, extension)
    destination = tenants.files_dir(slug) / stored_name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return stored_name


def _remove_original(slug: str, stored_name: Optional[str]) -> int:
    if not stored_name:
        return 0
    path = tenants.files_dir(slug) / stored_name
    try:
        size = path.stat().st_size
        path.unlink()
        return size
    except OSError:
        return 0


def _record_failure(slug: str, batch_id: str, source: InvoiceSource, message: str) -> str:
    db.insert_invoice(
        slug,
        {
            "id": uuid.uuid4().hex,
            "batch_id": batch_id,
            "archive": source.archive,
            "filename": source.filename,
            "error": message,
        },
    )
    return FAILED


def _process_one(
    client: Anthropic,
    slug: str,
    batch_id: str,
    source: InvoiceSource,
    rules: List[str],
    state: _BatchState,
) -> str:
    """Deduplicate, extract and persist a single invoice. Returns its outcome."""
    if source.skip_reason is not None:
        return _record_failure(slug, batch_id, source, source.skip_reason)

    try:
        content = source.read()
    except Exception as exc:  # noqa: BLE001 - one bad entry must not stop the batch
        return _record_failure(
            slug, batch_id, source, "Lecture impossible depuis l'archive : {}".format(exc)
        )

    fingerprint = hashlib.sha256(content).hexdigest()
    size = len(content)
    invoice_id = uuid.uuid4().hex
    replaced = None

    # The check and the claim must be atomic: two workers holding the same
    # document would otherwise both find nothing and both import it.
    with state.lock:
        duplicate_of = state.claimed.get(fingerprint)
        if duplicate_of is None:
            existing = db.find_by_fingerprint(slug, fingerprint)
            if existing is not None:
                if _can_retry(existing):
                    replaced = existing
                else:
                    duplicate_of = existing["id"]

        if duplicate_of is not None:
            db.record_duplicate(slug, batch_id, source.filename, source.archive, duplicate_of, size)
            return DUPLICATE

        if state.quota_bytes and state.used_bytes + size > state.quota_bytes:
            return _record_failure(
                slug,
                batch_id,
                source,
                "Quota de stockage atteint : facture non importee "
                "(contacter l'administrateur pour l'augmenter).",
            )

        state.claimed[fingerprint] = invoice_id
        state.used_bytes += size

    if replaced is not None:
        freed = _remove_original(slug, replaced["stored_name"])
        db.delete_invoice(slug, replaced["id"])
        with state.lock:
            state.used_bytes -= freed
        logger.info("[%s] nouvel essai de %s (echec precedent remplace)", slug, source.filename)

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
            "content_sha256": fingerprint,
            "file_size": size,
        },
    )
    return FAILED if result.error is not None else OK


def _run_batch(client: Anthropic, slug: str, batch_id: str, sources: List[InvoiceSource]) -> None:
    rules = learning.rules_for_prompt(slug)
    if rules:
        logger.info("[%s] extraction avec %d regle(s) apprise(s)", slug, len(rules))

    state = _BatchState(slug)
    counts = {OK: 0, FAILED: 0, DUPLICATE: 0}

    try:
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_EXTRACTIONS) as pool:
            futures = [
                pool.submit(_process_one, client, slug, batch_id, source, rules, state)
                for source in sources
            ]
            for done, future in enumerate(as_completed(futures), start=1):
                try:
                    outcome = future.result()
                except Exception as exc:  # noqa: BLE001 - defensive: never lose the batch
                    logger.exception("[%s] echec inattendu : %s", slug, exc)
                    outcome = FAILED
                counts[outcome] += 1
                db.bump_batch(
                    slug, batch_id, failed=outcome == FAILED, duplicate=outcome == DUPLICATE
                )
                if done % 10 == 0 or done == len(sources):
                    logger.info("[%s] factures traitees : %d/%d", slug, done, len(sources))
        db.finish_batch(slug, batch_id, "done")
        logger.info(
            "[%s] import termine : %d extraite(s), %d en erreur, %d doublon(s) ignore(s)",
            slug, counts[OK], counts[FAILED], counts[DUPLICATE],
        )
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
    quota = tenants.storage_quota_bytes(slug)
    if quota and tenants.storage_usage(slug)["total_bytes"] >= quota:
        return {"error": "Quota de stockage atteint : aucun import possible. "
                         "Contacte l'administrateur pour l'augmenter."}

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
