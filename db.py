"""Per-tenant SQLite storage: schema, connections and queries.

Every tenant has its own database file, so callers never pass a tenant id to a
query — they open that tenant's connection and everything they see belongs to
it. Connections are short-lived and created per call: SQLite connections are
not shareable across threads, and the import pipeline is multi-threaded.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

import tenants

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS batches (
    id          TEXT PRIMARY KEY,
    label       TEXT,
    total       INTEGER NOT NULL DEFAULT 0,
    done        INTEGER NOT NULL DEFAULT 0,
    failed      INTEGER NOT NULL DEFAULT 0,
    duplicates  INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'running',
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    started_by      TEXT,
    acknowledged_at TEXT
);

CREATE TABLE IF NOT EXISTS duplicates (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id     TEXT,
    archive      TEXT,
    filename     TEXT NOT NULL,
    duplicate_of TEXT NOT NULL,
    file_size    INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invoices (
    id               TEXT PRIMARY KEY,
    batch_id         TEXT,
    archive          TEXT,
    filename         TEXT NOT NULL,
    stored_name      TEXT,
    content_type     TEXT,
    supplier_name    TEXT,
    invoice_number   TEXT,
    invoice_date     TEXT,
    total_amount     REAL,
    currency         TEXT,
    vat_amount       REAL,
    extraction_notes TEXT,
    error            TEXT,
    page_count       INTEGER DEFAULT 0,
    uncertain_fields TEXT NOT NULL DEFAULT '[]',
    edited_fields    TEXT NOT NULL DEFAULT '[]',
    content_sha256   TEXT,
    file_size        INTEGER,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

-- One row per product line of an invoice. A new table (not new columns), so
-- `CREATE TABLE IF NOT EXISTS` is enough to bring existing tenant databases up
-- to date; only added *columns* need an entry in MIGRATIONS.
CREATE TABLE IF NOT EXISTS invoice_lines (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id   TEXT NOT NULL,
    line_no      INTEGER NOT NULL DEFAULT 0,
    label        TEXT NOT NULL,
    product_key  TEXT NOT NULL,
    category     TEXT,
    quantity     REAL,
    unit         TEXT,
    unit_price   REAL,
    line_total   REAL,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lines_invoice ON invoice_lines(invoice_id);
CREATE INDEX IF NOT EXISTS idx_lines_product ON invoice_lines(product_key);

CREATE INDEX IF NOT EXISTS idx_invoices_supplier ON invoices(supplier_name);
CREATE INDEX IF NOT EXISTS idx_invoices_date     ON invoices(invoice_date);
CREATE INDEX IF NOT EXISTS idx_invoices_batch    ON invoices(batch_id);

CREATE TABLE IF NOT EXISTS corrections (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id    TEXT NOT NULL,
    supplier_name TEXT,
    field         TEXT NOT NULL,
    old_value     TEXT,
    new_value     TEXT,
    user_email    TEXT,
    created_at    TEXT NOT NULL,
    learned       INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_corrections_pending ON corrections(learned, supplier_name);

CREATE TABLE IF NOT EXISTS learned_rules (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_name TEXT,
    rule          TEXT NOT NULL,
    based_on      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_rules_supplier
    ON learned_rules(IFNULL(supplier_name, ''));
"""

# Fields the user is allowed to correct in the Invoices table. Everything else
# (filename, archive, ids) is provenance and must stay as recorded.
EDITABLE_FIELDS = (
    "supplier_name",
    "invoice_number",
    "invoice_date",
    "total_amount",
    "currency",
    "vat_amount",
)

NUMERIC_FIELDS = ("total_amount", "vat_amount")


def now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


# Columns added after the first release. SCHEMA creates them on new databases;
# existing tenant databases get them through ALTER TABLE, since CREATE TABLE IF
# NOT EXISTS never alters a table that is already there. Additive only.
MIGRATIONS = (
    ("invoices", "content_sha256", "TEXT"),
    ("invoices", "file_size", "INTEGER"),
    ("batches", "duplicates", "INTEGER NOT NULL DEFAULT 0"),
    ("batches", "started_by", "TEXT"),
    ("batches", "acknowledged_at", "TEXT"),
)

_initialised = set()
_init_lock = threading.Lock()


def _migrate(conn: sqlite3.Connection, slug: str) -> None:
    added = set()
    for table, column, declaration in MIGRATIONS:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info({})".format(table))}
        if column not in columns:
            conn.execute("ALTER TABLE {} ADD COLUMN {} {}".format(table, column, declaration))
            added.add(column)
    added_hash = "content_sha256" in added

    if "acknowledged_at" in added:
        # Imports finished before the summary pop-up existed: nobody is waiting
        # for their summary, so it must not surface on the next page load.
        conn.execute(
            "UPDATE batches SET acknowledged_at = IFNULL(finished_at, started_at) "
            "WHERE status != 'running'"
        )

    # Created here rather than in SCHEMA: on an old database the column only
    # exists once the ALTER TABLE above has run.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_invoices_sha ON invoices(content_sha256)")

    if added_hash:
        _backfill_fingerprints(conn, slug)


def _backfill_fingerprints(conn: sqlite3.Connection, slug: str) -> None:
    """Fingerprint invoices imported before deduplication existed, so a new
    import recognises them too."""
    directory = tenants.files_dir(slug)
    rows = conn.execute(
        "SELECT id, stored_name FROM invoices "
        "WHERE content_sha256 IS NULL AND stored_name IS NOT NULL"
    ).fetchall()
    for row in rows:
        path = directory / row["stored_name"]
        if not path.is_file():
            continue
        content = path.read_bytes()
        conn.execute(
            "UPDATE invoices SET content_sha256 = ?, file_size = ? WHERE id = ?",
            (hashlib.sha256(content).hexdigest(), len(content), row["id"]),
        )


@contextmanager
def connect(slug: str) -> Iterator[sqlite3.Connection]:
    """Open (and initialise on first use) a tenant database."""
    tenants.create(slug)  # ensures the directory layout exists
    path = tenants.database_path(slug)
    fresh_file = not path.exists()
    connection = sqlite3.connect(str(path), timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA busy_timeout=30000")
        # Schema and migrations run once per database per process, not on every
        # connection: an import opens thousands of them from parallel threads.
        key = str(path)
        with _init_lock:
            if fresh_file or key not in _initialised:
                # WAL lets the web request read while import threads write; the
                # mode is persistent, so setting it once is enough.
                connection.execute("PRAGMA journal_mode=WAL")
                connection.executescript(SCHEMA)
                _migrate(connection, slug)
                connection.commit()
                _initialised.add(key)
        yield connection
        connection.commit()
    finally:
        connection.close()


# --------------------------------------------------------------------------- users


def count_users(slug: str) -> int:
    with connect(slug) as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]


def create_user(slug: str, email: str, password_hash: str) -> None:
    with connect(slug) as conn:
        conn.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email.strip(), password_hash, now()),
        )


def get_user(slug: str, email: str) -> Optional[sqlite3.Row]:
    with connect(slug) as conn:
        return conn.execute(
            "SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email.strip(),)
        ).fetchone()


# -------------------------------------------------------------------------- batches


def create_batch(slug: str, label: str, total: int, started_by: Optional[str] = None) -> str:
    batch_id = uuid.uuid4().hex
    with connect(slug) as conn:
        conn.execute(
            "INSERT INTO batches (id, label, total, started_at, started_by) VALUES (?, ?, ?, ?, ?)",
            (batch_id, label, total, now(), started_by),
        )
    return batch_id


def bump_batch(slug: str, batch_id: str, failed: bool = False, duplicate: bool = False) -> None:
    with connect(slug) as conn:
        conn.execute(
            "UPDATE batches SET done = done + 1, failed = failed + ?, duplicates = duplicates + ? "
            "WHERE id = ?",
            (1 if failed else 0, 1 if duplicate else 0, batch_id),
        )


def finish_batch(slug: str, batch_id: str, status: str = "done") -> None:
    with connect(slug) as conn:
        conn.execute(
            "UPDATE batches SET status = ?, finished_at = ? WHERE id = ?",
            (status, now(), batch_id),
        )


def get_batch(slug: str, batch_id: str) -> Optional[sqlite3.Row]:
    with connect(slug) as conn:
        return conn.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()


def active_batches(slug: str) -> List[sqlite3.Row]:
    with connect(slug) as conn:
        return conn.execute(
            "SELECT * FROM batches WHERE status = 'running' ORDER BY started_at DESC"
        ).fetchall()


def pending_summary_batch(slug: str, email: str) -> Optional[str]:
    """The most recent finished import whose summary its author hasn't closed.

    Lets the summary survive the user leaving the page mid-import: it is shown
    on their next page load instead of being lost. Scoped to the person who
    started the import, so a colleague isn't handed someone else's summary.
    """
    with connect(slug) as conn:
        row = conn.execute(
            """
            SELECT id FROM batches
            WHERE status != 'running' AND acknowledged_at IS NULL
              AND (started_by IS NULL OR started_by = ? COLLATE NOCASE)
            ORDER BY IFNULL(finished_at, started_at) DESC, started_at DESC
            LIMIT 1
            """,
            (email,),
        ).fetchone()
    return row["id"] if row else None


def acknowledge_batch(slug: str, batch_id: str) -> None:
    with connect(slug) as conn:
        conn.execute(
            "UPDATE batches SET acknowledged_at = ? WHERE id = ? AND acknowledged_at IS NULL",
            (now(), batch_id),
        )


# Every error message the import can record, grouped by what the user can do
# about it. Matched on the message's opening words, which are written by
# extraction.py and pipeline.py — keep these in step when adding a new error.
ERROR_KINDS = (
    ("quota", ("Quota de stockage",)),
    ("unsupported", (
        "Format non pris en charge", "Archive illisible", "Archive trop imbriquee",
        "Aucune facture", "Aucune page", "Lecture impossible", "Impossible de lire le fichier",
    )),
    ("extraction", ("Erreur API", "Extraction refusee", "Reponse vide", "JSON invalide")),
)


def error_kind(message: Optional[str]) -> str:
    text = (message or "").strip()
    for kind, prefixes in ERROR_KINDS:
        if text.startswith(prefixes):
            return kind
    return "other"


def batch_summary(slug: str, batch_id: str, examples: int = 8) -> Optional[Dict[str, Any]]:
    """What an import produced, counted from the rows it actually wrote."""
    with connect(slug) as conn:
        batch = conn.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
        if batch is None:
            return None

        counts = conn.execute(
            """
            SELECT SUM(CASE WHEN error IS NULL THEN 1 ELSE 0 END) AS succeeded,
                   SUM(CASE WHEN error IS NULL AND uncertain_fields != '[]' THEN 1 ELSE 0 END) AS needs_review,
                   SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS failed
            FROM invoices WHERE batch_id = ?
            """,
            (batch_id,),
        ).fetchone()
        error_rows = conn.execute(
            "SELECT filename, archive, error FROM invoices "
            "WHERE batch_id = ? AND error IS NOT NULL ORDER BY filename",
            (batch_id,),
        ).fetchall()
        duplicate_count = conn.execute(
            "SELECT COUNT(*) AS n FROM duplicates WHERE batch_id = ?", (batch_id,)
        ).fetchone()["n"]
        duplicate_rows = conn.execute(
            """
            SELECT d.filename, d.archive, i.filename AS original_filename
            FROM duplicates d LEFT JOIN invoices i ON i.id = d.duplicate_of
            WHERE d.batch_id = ? ORDER BY d.filename LIMIT ?
            """,
            (batch_id, examples),
        ).fetchall()

    succeeded = counts["succeeded"] or 0
    failed = counts["failed"] or 0
    by_kind = {"extraction": 0, "unsupported": 0, "quota": 0, "other": 0}
    for row in error_rows:
        by_kind[error_kind(row["error"])] += 1

    return {
        "batch_id": batch["id"],
        "label": batch["label"],
        "status": batch["status"],
        "started_at": batch["started_at"],
        "finished_at": batch["finished_at"],
        "total": batch["total"],
        "succeeded": succeeded,
        "needs_review": counts["needs_review"] or 0,
        "duplicates": duplicate_count,
        "failed": failed,
        "failed_by_kind": by_kind,
        # Documents the import never reached: an interrupted batch, or a worker
        # that crashed before writing anything.
        "not_processed": max(0, batch["total"] - succeeded - failed - duplicate_count),
        "failures": [
            {"filename": r["filename"], "archive": r["archive"], "error": r["error"],
             "kind": error_kind(r["error"])}
            for r in error_rows[:examples]
        ],
        "duplicate_examples": [dict(r) for r in duplicate_rows],
    }


# ------------------------------------------------------------------------- invoices


def insert_invoice(slug: str, record: Dict[str, Any]) -> str:
    invoice_id = record.get("id") or uuid.uuid4().hex
    timestamp = now()
    with connect(slug) as conn:
        conn.execute(
            """
            INSERT INTO invoices (
                id, batch_id, archive, filename, stored_name, content_type,
                supplier_name, invoice_number, invoice_date, total_amount, currency,
                vat_amount, extraction_notes, error, page_count, uncertain_fields,
                edited_fields, content_sha256, file_size, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                invoice_id,
                record.get("batch_id"),
                record.get("archive"),
                record.get("filename"),
                record.get("stored_name"),
                record.get("content_type"),
                record.get("supplier_name"),
                record.get("invoice_number"),
                record.get("invoice_date"),
                record.get("total_amount"),
                record.get("currency"),
                record.get("vat_amount"),
                record.get("extraction_notes"),
                record.get("error"),
                record.get("page_count") or 0,
                json.dumps(record.get("uncertain_fields") or [], ensure_ascii=False),
                "[]",
                record.get("content_sha256"),
                record.get("file_size"),
                timestamp,
                timestamp,
            ),
        )
    return invoice_id


def find_by_fingerprint(slug: str, content_sha256: str) -> Optional[sqlite3.Row]:
    """The invoice already holding this exact document, if any.

    A successful or hand-edited row wins over a failed one, so a document that
    once failed extraction and was later retried is matched to the good copy.
    """
    with connect(slug) as conn:
        return conn.execute(
            """
            SELECT id, filename, archive, error, edited_fields, stored_name, file_size
            FROM invoices WHERE content_sha256 = ?
            ORDER BY (error IS NULL) DESC, created_at
            LIMIT 1
            """,
            (content_sha256,),
        ).fetchone()


def delete_invoice(slug: str, invoice_id: str) -> None:
    with connect(slug) as conn:
        conn.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))
        # No foreign keys in SQLite by default: the lines would otherwise
        # survive their invoice and keep counting in the product statistics.
        conn.execute("DELETE FROM invoice_lines WHERE invoice_id = ?", (invoice_id,))


def insert_lines(slug: str, invoice_id: str, lines: List[Dict[str, Any]]) -> int:
    """Store the product lines read off one invoice."""
    if not lines:
        return 0
    timestamp = now()
    with connect(slug) as conn:
        conn.executemany(
            """
            INSERT INTO invoice_lines (
                invoice_id, line_no, label, product_key, category,
                quantity, unit, unit_price, line_total, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    invoice_id, index, line.get("label") or "", line.get("product_key") or "",
                    line.get("category"), line.get("quantity"), line.get("unit"),
                    line.get("unit_price"), line.get("line_total"), timestamp,
                )
                for index, line in enumerate(lines)
            ],
        )
    return len(lines)


def record_duplicate(
    slug: str,
    batch_id: str,
    filename: str,
    archive: Optional[str],
    duplicate_of: str,
    file_size: int,
) -> None:
    with connect(slug) as conn:
        conn.execute(
            "INSERT INTO duplicates (batch_id, archive, filename, duplicate_of, file_size, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (batch_id, archive, filename, duplicate_of, file_size, now()),
        )


def list_duplicates(slug: str, limit: int = 50) -> List[sqlite3.Row]:
    with connect(slug) as conn:
        return conn.execute(
            """
            SELECT d.filename, d.archive, d.file_size, d.created_at, d.duplicate_of,
                   i.filename AS original_filename, i.archive AS original_archive,
                   i.stored_name AS original_stored_name
            FROM duplicates d LEFT JOIN invoices i ON i.id = d.duplicate_of
            ORDER BY d.created_at DESC, d.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


def duplicate_summary(slug: str) -> Dict[str, int]:
    with connect(slug) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n, IFNULL(SUM(file_size), 0) AS bytes FROM duplicates"
        ).fetchone()
    return {"count": row["n"], "bytes": row["bytes"]}


def _filter_clause(filters: Dict[str, Any]):
    where: List[str] = []
    params: List[Any] = []

    supplier = (filters.get("supplier") or "").strip()
    if supplier:
        where.append("supplier_name = ?")
        params.append(supplier)

    date_from = (filters.get("date_from") or "").strip()
    if date_from:
        where.append("invoice_date >= ?")
        params.append(date_from)

    date_to = (filters.get("date_to") or "").strip()
    if date_to:
        where.append("invoice_date <= ?")
        params.append(date_to)

    search = (filters.get("search") or "").strip()
    if search:
        where.append(
            "(supplier_name LIKE ? OR invoice_number LIKE ? OR filename LIKE ? OR archive LIKE ?)"
        )
        params.extend(["%{}%".format(search)] * 4)

    batch = (filters.get("batch") or "").strip()
    if batch:
        where.append("batch_id = ?")
        params.append(batch)

    status = (filters.get("status") or "").strip()
    if status == "errors":
        where.append("error IS NOT NULL")
    elif status == "uncertain":
        where.append("uncertain_fields != '[]' AND error IS NULL")
    elif status == "ok":
        where.append("error IS NULL")

    return (" WHERE " + " AND ".join(where)) if where else "", params


def list_invoices(slug: str, filters: Dict[str, Any], limit: int = 500, offset: int = 0):
    clause, params = _filter_clause(filters)
    with connect(slug) as conn:
        rows = conn.execute(
            "SELECT * FROM invoices{} ORDER BY IFNULL(invoice_date, '') DESC, created_at DESC "
            "LIMIT ? OFFSET ?".format(clause),
            params + [limit, offset],
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM invoices{}".format(clause), params
        ).fetchone()["n"]
    return rows, total


def product_lines(slug: str, filters: Dict[str, Any], limit: int = 100000) -> List[Dict[str, Any]]:
    """Priced invoice lines, filtered like the rest of the app.

    Returned raw rather than aggregated in SQL: picking the most frequent
    wording and category per product is awkward in SQLite and trivial in
    Python (see products.summarise), and the same rows feed the price history.
    """
    clause, params = _filter_clause(filters)
    with connect(slug) as conn:
        rows = conn.execute(
            """
            SELECT l.product_key, l.label, l.category, l.quantity, l.unit,
                   l.unit_price, l.line_total, l.invoice_id,
                   i.supplier_name AS supplier, i.invoice_date, i.currency,
                   i.invoice_number, i.filename, i.stored_name
            FROM invoice_lines l JOIN invoices i ON i.id = l.invoice_id
            {}{} l.unit_price IS NOT NULL AND l.unit_price > 0 AND i.error IS NULL
            ORDER BY i.invoice_date, l.id LIMIT ?
            """.format(clause, " AND" if clause else " WHERE"),
            params + [limit],
        ).fetchall()
    return [dict(row) for row in rows]


def count_lines(slug: str) -> int:
    with connect(slug) as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM invoice_lines").fetchone()["n"]


def get_invoice(slug: str, invoice_id: str) -> Optional[sqlite3.Row]:
    with connect(slug) as conn:
        return conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()


def update_invoice_field(slug: str, invoice_id: str, field: str, value: Any) -> None:
    """Apply a user correction and remember the field was hand-edited."""
    if field not in EDITABLE_FIELDS:
        raise ValueError("Champ non modifiable : {}".format(field))

    with connect(slug) as conn:
        row = conn.execute(
            "SELECT uncertain_fields, edited_fields FROM invoices WHERE id = ?", (invoice_id,)
        ).fetchone()
        if row is None:
            raise LookupError("Facture introuvable")

        edited = set(json.loads(row["edited_fields"] or "[]"))
        edited.add(field)
        # A hand-corrected value is no longer doubtful.
        uncertain = [f for f in json.loads(row["uncertain_fields"] or "[]") if f != field]

        conn.execute(
            "UPDATE invoices SET {} = ?, edited_fields = ?, uncertain_fields = ?, updated_at = ? "
            "WHERE id = ?".format(field),
            (
                value,
                json.dumps(sorted(edited), ensure_ascii=False),
                json.dumps(uncertain, ensure_ascii=False),
                now(),
                invoice_id,
            ),
        )


def distinct_suppliers(slug: str) -> List[str]:
    with connect(slug) as conn:
        rows = conn.execute(
            "SELECT DISTINCT supplier_name FROM invoices "
            "WHERE supplier_name IS NOT NULL AND supplier_name != '' ORDER BY supplier_name"
        ).fetchall()
    return [r["supplier_name"] for r in rows]


# ---------------------------------------------------------------------- corrections


def record_correction(
    slug: str,
    invoice_id: str,
    supplier_name: Optional[str],
    field: str,
    old_value: Any,
    new_value: Any,
    user_email: str,
) -> None:
    with connect(slug) as conn:
        conn.execute(
            """
            INSERT INTO corrections
                (invoice_id, supplier_name, field, old_value, new_value, user_email, created_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                invoice_id,
                supplier_name,
                field,
                "" if old_value is None else str(old_value),
                "" if new_value is None else str(new_value),
                user_email,
                now(),
            ),
        )


def pending_corrections(slug: str, supplier_name: Optional[str] = None) -> List[sqlite3.Row]:
    with connect(slug) as conn:
        if supplier_name is None:
            return conn.execute(
                "SELECT * FROM corrections WHERE learned = 0 ORDER BY created_at"
            ).fetchall()
        return conn.execute(
            "SELECT * FROM corrections WHERE learned = 0 AND IFNULL(supplier_name,'') = ? "
            "ORDER BY created_at",
            (supplier_name or "",),
        ).fetchall()


def count_pending_corrections(slug: str) -> int:
    with connect(slug) as conn:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM corrections WHERE learned = 0"
        ).fetchone()["n"]


def mark_corrections_learned(slug: str, correction_ids: List[int]) -> None:
    if not correction_ids:
        return
    placeholders = ",".join("?" for _ in correction_ids)
    with connect(slug) as conn:
        conn.execute(
            "UPDATE corrections SET learned = 1 WHERE id IN ({})".format(placeholders),
            correction_ids,
        )


# -------------------------------------------------------------------- learned rules


def upsert_rule(slug: str, supplier_name: Optional[str], rule: str, based_on: int) -> None:
    with connect(slug) as conn:
        existing = conn.execute(
            "SELECT id, based_on FROM learned_rules WHERE IFNULL(supplier_name,'') = ?",
            (supplier_name or "",),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE learned_rules SET rule = ?, based_on = ?, updated_at = ? WHERE id = ?",
                (rule, existing["based_on"] + based_on, now(), existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO learned_rules (supplier_name, rule, based_on, created_at, updated_at)"
                " VALUES (?,?,?,?,?)",
                (supplier_name, rule, based_on, now(), now()),
            )


def list_rules(slug: str) -> List[sqlite3.Row]:
    with connect(slug) as conn:
        return conn.execute(
            "SELECT * FROM learned_rules ORDER BY IFNULL(supplier_name, '') "
        ).fetchall()


def delete_rule(slug: str, rule_id: int) -> None:
    with connect(slug) as conn:
        conn.execute("DELETE FROM learned_rules WHERE id = ?", (rule_id,))


# ------------------------------------------------------------------------ dashboard


def dashboard_stats(slug: str, filters: Dict[str, Any]) -> Dict[str, Any]:
    """Aggregates for the Dashboard tab, honouring the same filters as Invoices."""
    clause, params = _filter_clause(filters)
    with connect(slug) as conn:
        totals = conn.execute(
            """
            SELECT COUNT(*)                                   AS invoice_count,
                   IFNULL(SUM(total_amount), 0)               AS total_amount,
                   IFNULL(SUM(vat_amount), 0)                 AS vat_amount,
                   COUNT(DISTINCT supplier_name)              AS supplier_count,
                   SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END)          AS error_count,
                   SUM(CASE WHEN uncertain_fields != '[]' THEN 1 ELSE 0 END)   AS uncertain_count
            FROM invoices{}
            """.format(clause),
            params,
        ).fetchone()

        by_month = conn.execute(
            """
            SELECT substr(invoice_date, 1, 7)    AS period,
                   IFNULL(SUM(total_amount), 0)  AS amount,
                   COUNT(*)                      AS invoice_count
            FROM invoices{}{} invoice_date IS NOT NULL AND length(invoice_date) >= 7
            GROUP BY period ORDER BY period
            """.format(clause, " AND" if clause else " WHERE"),
            params,
        ).fetchall()

        # Rows without a supplier are failed extractions with no amount; they
        # would only add an empty "(unknown)" bar to the ranking.
        by_supplier = conn.execute(
            """
            SELECT supplier_name                AS supplier,
                   IFNULL(SUM(total_amount), 0) AS amount,
                   COUNT(*)                     AS invoice_count
            FROM invoices{}{} supplier_name IS NOT NULL AND supplier_name != ''
            GROUP BY supplier ORDER BY amount DESC LIMIT 10
            """.format(clause, " AND" if clause else " WHERE"),
            params,
        ).fetchall()

        # One row per (day, supplier) for the heatmap. Kept unaggregated by
        # month on purpose: the grid is the only view that shows *when* in the
        # month a supplier invoices.
        by_day_supplier = conn.execute(
            """
            SELECT invoice_date                 AS day,
                   supplier_name                AS supplier,
                   IFNULL(SUM(total_amount), 0) AS amount,
                   COUNT(*)                     AS invoice_count
            FROM invoices{}{} invoice_date IS NOT NULL AND length(invoice_date) = 10
              AND supplier_name IS NOT NULL AND supplier_name != ''
            GROUP BY day, supplier ORDER BY day
            """.format(clause, " AND" if clause else " WHERE"),
            params,
        ).fetchall()

        currencies = conn.execute(
            "SELECT IFNULL(currency,'') AS currency, COUNT(*) AS n FROM invoices{}"
            " GROUP BY currency ORDER BY n DESC".format(clause),
            params,
        ).fetchall()

    return {
        "totals": dict(totals) if totals else {},
        "by_month": [dict(r) for r in by_month],
        "by_supplier": [dict(r) for r in by_supplier],
        "by_day_supplier": [dict(r) for r in by_day_supplier],
        "currencies": [dict(r) for r in currencies if r["currency"]],
    }
