from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import db
import tenants

OLD_SCHEMA = (Path(__file__).parent / "fixtures" / "schema_v1.sql").read_text(encoding="utf-8")


@pytest.fixture
def old_tenant(tenant):
    path = tenants.database_path(tenant)
    conn = sqlite3.connect(str(path))
    conn.executescript(OLD_SCHEMA)
    for name in ("a.pdf", "b.pdf"):
        conn.execute(
            "INSERT INTO duplicates (batch_id, archive, filename, duplicate_of, file_size, created_at)"
            " VALUES ('b1', 'x.zip', ?, 'inv1', 10, '2026-01-01T00:00:00')", (name,))
    conn.commit()
    conn.close()
    db._initialised.clear()
    return tenant


def test_old_database_gets_new_columns_and_log(old_tenant):
    with db.connect(old_tenant) as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(invoices)")}
        assert "uncertain_regions" in cols
        assert "kind" in {r["name"] for r in conn.execute("PRAGMA table_info(corrections)")}
        rows = conn.execute("SELECT reason FROM import_log ORDER BY id").fetchall()
    assert [r["reason"] for r in rows] == ["DUPLICATE", "DUPLICATE"]


def test_duplicates_are_copied_only_once(old_tenant):
    with db.connect(old_tenant):
        pass
    db._initialised.clear()
    with db.connect(old_tenant) as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM import_log").fetchone()["n"] == 2
