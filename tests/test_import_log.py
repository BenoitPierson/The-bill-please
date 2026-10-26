from __future__ import annotations

import pytest

import db
import pipeline
from extraction import InvoiceResult, InvoiceSource


def rows_of(slug, table):
    with db.connect(slug) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM {} ORDER BY rowid".format(table))]


@pytest.fixture
def fake_extraction(monkeypatch):
    def fake(client, filename, content, content_type, rules=None):
        return InvoiceResult(filename=filename, supplier_name="Bidco", page_count=1)
    monkeypatch.setattr(pipeline, "process_upload", fake)


def test_reason_for_error():
    assert db.reason_for_error("Quota de stockage atteint : x") == "QUOTA"
    assert db.reason_for_error("Format non pris en charge (ni PDF, ni image).") == "UNSUPPORTED"
    assert db.reason_for_error("Erreur API : surcharge") == "EXTRACTION"
    assert db.reason_for_error("autre chose") == "OTHER"


def test_duplicate_in_same_archive_is_logged(tenant, fake_extraction):
    batch = db.create_batch(tenant, "a.zip", 2)
    state = pipeline._BatchState(tenant)
    same = b"%PDF-1.4 same bytes"
    first = InvoiceSource(filename="m/x.pdf", archive="a.zip", data=same)
    second = InvoiceSource(filename="n/x.pdf", archive="a.zip", data=same)
    assert pipeline._process_one(None, tenant, batch, first, [], state) == pipeline.OK
    assert pipeline._process_one(None, tenant, batch, second, [], state) == pipeline.DUPLICATE
    (row,) = rows_of(tenant, "import_log")
    assert row["reason"] == "DUPLICATE" and row["filename"] == "n/x.pdf" and row["duplicate_of"]


def test_unsupported_file_is_logged_and_kept_as_error_row(tenant):
    batch = db.create_batch(tenant, "a.zip", 1)
    source = InvoiceSource(filename="notes.txt", archive="a.zip",
                           skip_reason="Format non pris en charge (ni PDF, ni image).")
    pipeline._process_one(None, tenant, batch, source, [], pipeline._BatchState(tenant))
    (log,) = rows_of(tenant, "import_log")
    assert log["reason"] == "UNSUPPORTED" and log["invoice_id"]
    assert db.get_invoice(tenant, log["invoice_id"])["error"].startswith("Format non pris en charge")


def test_failed_extraction_is_logged(tenant, monkeypatch):
    monkeypatch.setattr(pipeline, "process_upload",
                        lambda c, f, b, t, rules=None: InvoiceResult(filename=f, error="Erreur API : surcharge"))
    batch = db.create_batch(tenant, "a.zip", 1)
    source = InvoiceSource(filename="x.pdf", archive="a.zip", data=b"%PDF-1.4 x")
    assert pipeline._process_one(None, tenant, batch, source, [], pipeline._BatchState(tenant)) == pipeline.FAILED
    (log,) = rows_of(tenant, "import_log")
    assert log["reason"] == "EXTRACTION" and log["invoice_id"]


def test_batch_summary_counts_duplicates_from_log(tenant):
    batch = db.create_batch(tenant, "a.zip", 1)
    db.log_import_event(tenant, batch, "x.pdf", "a.zip", "DUPLICATE", "...", file_size=10, duplicate_of="abc")
    summary = db.batch_summary(tenant, batch)
    assert summary["duplicates"] == 1 and summary["duplicate_examples"][0]["filename"] == "x.pdf"
    assert db.duplicate_summary(tenant) == {"count": 1, "bytes": 10}


def test_invoices_page_renders_without_duplicates_panel(tenant, monkeypatch):
    from starlette.testclient import TestClient
    import app as app_module
    import auth
    import tenants
    monkeypatch.setattr(app_module, "DEFAULT_TENANT", tenant)
    monkeypatch.setattr(tenants, "DEFAULT_TENANT", tenant)
    db.create_user(tenant, "a@b.fr", auth.hash_password("motdepasse1"))
    client = TestClient(app_module.app)
    client.post("/login", data={"email": "a@b.fr", "password": "motdepasse1"})
    page = client.get("/invoices")
    assert page.status_code == 200 and 'id="doublons"' not in page.text
