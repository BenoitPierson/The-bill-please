-- Schema as shipped before the Invoices redesign (frozen for migration tests).

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
