from __future__ import annotations

import pytest
from starlette.testclient import TestClient

import app as app_module
import db
import tenants


@pytest.fixture
def make_client(tenant, monkeypatch):
    monkeypatch.setattr(app_module, "DEFAULT_TENANT", tenant)
    monkeypatch.setattr(tenants, "DEFAULT_TENANT", tenant)
    monkeypatch.setattr(tenants, "APP_DOMAIN", "")

    def build(base_url):
        return TestClient(app_module.app, base_url=base_url)
    return build


def test_local_host_skips_login(make_client):
    page = make_client("http://127.0.0.1:8000").get("/dashboard", follow_redirects=False)
    assert page.status_code == 200
    assert "Poste local" in page.text


def test_localhost_name_skips_login(make_client):
    page = make_client("http://localhost:8000").get("/invoices", follow_redirects=False)
    assert page.status_code == 200


def test_login_page_redirects_home_in_local_mode(make_client):
    client = make_client("http://127.0.0.1:8000")
    for path in ("/login", "/setup"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303 and response.headers["location"] == "/dashboard"


def test_login_required_when_app_domain_is_set(make_client, monkeypatch):
    monkeypatch.setattr(tenants, "APP_DOMAIN", "factures.example.com")
    response = make_client("http://127.0.0.1:8000").get("/dashboard", follow_redirects=False)
    assert response.status_code == 303


def test_login_required_for_a_non_local_host(make_client):
    response = make_client("http://monpc.local").get("/dashboard", follow_redirects=False)
    assert response.status_code == 303


def test_local_corrections_are_attributed_to_the_local_post(make_client, tenant):
    invoice_id = db.insert_invoice(tenant, {"filename": "f.pdf", "invoice_number": "A1"})
    response = make_client("http://127.0.0.1:8000").patch(
        "/api/invoices/{}".format(invoice_id), json={"field": "invoice_number", "value": "A2"})
    assert response.status_code == 200
    (correction,) = db.pending_corrections(tenant)
    assert correction["user_email"] == "Poste local"
