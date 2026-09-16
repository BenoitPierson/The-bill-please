"""Per-tenant SQLite storage: schema, connections and queries.

Every tenant has its own database file, so callers never pass a tenant id to a
query — they open that tenant's connection and everything they see belongs to
it. Connections are short-lived and created per call: SQLite connections are
not shareable across threads, and the import pipeline is multi-threaded.
"""
from __future__ import annotations

import json
import sqlite3
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
    status      TEXT NOT NULL DEFAULT 'running',
    started_at  TEXT NOT NULL,
    finished_at TEXT
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
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

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


@contextmanager
def connect(slug: str) -> Iterator[sqlite3.Connection]:
    """Open (and initialise on first use) a tenant database."""
    tenants.create(slug)  # ensures the directory layout exists
    connection = sqlite3.connect(str(tenants.database_path(slug)), timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        # WAL lets the web request read while import threads write.
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        connection.executescript(SCHEMA)
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


def create_batch(slug: str, label: str, total: int) -> str:
    batch_id = uuid.uuid4().hex
    with connect(slug) as conn:
        conn.execute(
            "INSERT INTO batches (id, label, total, started_at) VALUES (?, ?, ?, ?)",
            (batch_id, label, total, now()),
        )
    return batch_id


def bump_batch(slug: str, batch_id: str, failed: bool) -> None:
    with connect(slug) as conn:
        conn.execute(
            "UPDATE batches SET done = done + 1, failed = failed + ? WHERE id = ?",
            (1 if failed else 0, batch_id),
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
                edited_fields, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                timestamp,
                timestamp,
            ),
        )
    return invoice_id


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

        currencies = conn.execute(
            "SELECT IFNULL(currency,'') AS currency, COUNT(*) AS n FROM invoices{}"
            " GROUP BY currency ORDER BY n DESC".format(clause),
            params,
        ).fetchall()

    return {
        "totals": dict(totals) if totals else {},
        "by_month": [dict(r) for r in by_month],
        "by_supplier": [dict(r) for r in by_supplier],
        "currencies": [dict(r) for r in currencies if r["currency"]],
    }
