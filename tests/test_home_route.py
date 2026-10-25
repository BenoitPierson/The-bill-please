from __future__ import annotations

from datetime import date

import pytest
from starlette.testclient import TestClient

import app as app_module
import auth
import charts
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
    monkeypatch.setattr(app_module, "_today", lambda: date(2026, 10, 25))
    db.create_user(tenant, "a@b.fr", auth.hash_password("motdepasse1"))
    test_client = TestClient(app_module.app)
    response = test_client.post("/login", data={"email": "a@b.fr", "password": "motdepasse1"})
    assert response.status_code in (200, 303)
    return test_client


def test_home_empty_state(client):
    page = client.get("/dashboard")
    assert page.status_code == 200
    assert "Importer des factures" in page.text


def test_home_shows_last_complete_month_only(client, tenant):
    add(tenant, invoice_date="2026-09-12", total_amount=1200.0, currency="KES")
    add(tenant, invoice_date="2026-10-02", total_amount=999.0, currency="KES")
    page = client.get("/dashboard").text
    assert "septembre 2026" in page
    assert charts.format_amount(1200.0) in page
    assert charts.format_amount(2199.0) not in page


def test_home_escapes_supplier_names(client, tenant):
    add(tenant, supplier_name='<b>Evil "Co"</b>', invoice_date="2026-09-12",
        total_amount=10.0, currency="KES")
    page = client.get("/dashboard").text
    assert "<b>Evil" not in page and "&lt;b&gt;Evil" in page


def test_home_other_currency_is_a_chip_not_a_sum(client, tenant):
    add(tenant, invoice_date="2026-09-12", total_amount=100.0, currency="KES")
    add(tenant, invoice_date="2026-09-13", total_amount=100.0, currency="KES")
    add(tenant, invoice_date="2026-09-14", total_amount=40.0, currency="USD")
    page = client.get("/dashboard").text
    assert charts.format_amount(200.0) in page and charts.format_amount(240.0) not in page
    assert "USD" in page


def test_home_lists_three_latest_imports(client, tenant):
    for n in range(5):
        add(tenant, invoice_number="NUM-{}".format(n), invoice_date="2026-09-1{}".format(n))
    page = client.get("/dashboard").text
    assert "NUM-4" in page and "NUM-2" in page and "NUM-1" not in page


def test_home_has_no_filters_and_no_scale_toggle(client, tenant):
    add(tenant, supplier_name="Bidco", invoice_date="2026-09-12", total_amount=10.0, currency="KES")
    page = client.get("/dashboard").text
    assert 'name="date_from"' not in page
    assert "data-heat-mode" not in page
