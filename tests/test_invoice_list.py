from __future__ import annotations

import pytest
from starlette.testclient import TestClient

import app as app_module
import auth
import db
import tenants


def add(slug, **fields):
    record = {"filename": "f.pdf"}
    record.update(fields)
    return db.insert_invoice(slug, record)


@pytest.fixture
def client(tenant, monkeypatch):
    monkeypatch.setattr(app_module, "DEFAULT_TENANT", tenant)
    monkeypatch.setattr(tenants, "DEFAULT_TENANT", tenant)
    db.create_user(tenant, "a@b.fr", auth.hash_password("motdepasse1"))
    test_client = TestClient(app_module.app)
    test_client.post("/login", data={"email": "a@b.fr", "password": "motdepasse1"})
    return test_client


@pytest.mark.parametrize("sort,expected", [
    ("date_desc", ["B", "A", "N"]), ("date_asc", ["A", "B", "N"]),
    ("amount_desc", ["A", "B", "N"]), ("amount_asc", ["B", "A", "N"]), ("drop table", ["B", "A", "N"])])
def test_sort_orders_put_missing_values_last(tenant, sort, expected):
    add(tenant, invoice_number="A", invoice_date="2026-01-01", total_amount=50.0)
    add(tenant, invoice_number="B", invoice_date="2026-02-01", total_amount=10.0)
    add(tenant, invoice_number="N")
    rows, _ = db.list_invoices(tenant, {}, sort=sort)
    assert [r["invoice_number"] for r in rows] == expected


def test_status_counts_ignore_the_status_filter(tenant):
    add(tenant)
    add(tenant, uncertain_fields=["invoice_number"])
    add(tenant, error="Erreur API : x")
    assert db.status_counts(tenant, {"status": "errors"}) == {"all": 3, "uncertain": 1, "errors": 1}


def test_invoices_page_has_no_duplicates_panel_and_keeps_sort_in_pagination(client, tenant):
    for n in range(101):
        add(tenant, invoice_number="N{}".format(n))
    page = client.get("/invoices?sort=amount_asc&status=ok").text
    assert "doublons" not in page.lower()
    assert "sort=amount_asc" in page and "page=2" in page


def test_page_lists_rows_with_state_and_has_detail_pane(client, tenant):
    add(tenant, supplier_name="Bidco", uncertain_fields=["invoice_number"])
    add(tenant, filename="scan_0.pdf", error="Erreur API : x")
    page = client.get("/invoices").text
    assert 'data-state="uncertain"' in page and 'data-state="error"' in page
    assert 'id="detailPane"' in page and 'id="viewer"' in page and 'id="docModal"' not in page
    assert "scan_0.pdf" in page


def test_status_links_keep_other_filters(client, tenant):
    add(tenant, supplier_name="Bidco")
    page = client.get("/invoices?supplier=Bidco&sort=amount_desc").text
    assert "status=uncertain" in page and "supplier=Bidco" in page and "sort=amount_desc" in page


def test_empty_list_offers_to_reset_filters(client, tenant):
    add(tenant, supplier_name="Bidco")
    page = client.get("/invoices?search=introuvable").text
    assert "Aucune facture ne correspond" in page and 'href="/invoices"' in page
